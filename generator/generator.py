#!/usr/bin/env python3
"""
Continuous message generator for the Quantum MITM Detection demo.

Each chat session goes through two phases:

  Phase 1 — BB84 Channel Establishment
    Alice and Bob run Qsim.find_secure_channel() to negotiate a quantum key.
    If a hacker is present from message #1 they act as Eve, raising QBER above
    the 15 % threshold and causing the channel to be restarted repeatedly until
    QBER drops below the threshold (or max_attempts is exhausted).
    A session whose channel could never be established is recorded as 'broken'.

  Phase 2 — Encrypted Message Exchange
    Messages are taken from data/messages.txt (pre-built realistic conversations
    grouped by topic).  Each message is encrypted with Qsim.encrypt_message().
    Per-message quantum state is computed via compute_quantum_state() (seeded
    BB84 without Eve).  If a mid-session hacker intercepts, hacker_perturbation()
    shifts the quantum state beyond the 15 % detection threshold.

Message generation:
    No AI required. Messages are loaded from data/messages.txt — a plain-text
    file with one message per line organised under [topic] headers (5 topics,
    36-40 messages each).  To customise, edit that file.

Usage:
    python generator.py [--sessions N] [--mitm-pct P] [--delay MIN MAX]
"""

import argparse
import contextlib
import io
import json
import os
import random
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import psycopg2
from kafka import KafkaProducer

# Bring Qsim into scope — suppress any module-level output from Qsim.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
with contextlib.redirect_stdout(io.StringIO()):
    from Qsim import Qsim

from quantum import compute_quantum_state, hacker_perturbation

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP = "localhost:29092"
KAFKA_TOPIC     = "messages"
PG_HOST         = "localhost"
PG_PORT         = 5432
PG_DB           = "streaming"
PG_USER         = "hackathon"
PG_PASSWORD     = "hackathon"

NORMAL_NOISE_MAX     = 0.10          # max ±10 % noise on clean messages
MESSAGES_PER_SESSION = (20, 40)
BB84_NUM_BITS        = 16            # qubits for channel establishment
BB84_QBER_THRESHOLD  = 15            # percent — matches Flink detection threshold
BB84_MAX_ATTEMPTS    = 10            # retries before marking channel as 'broken'

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# ---------------------------------------------------------------------------
# Globals for graceful shutdown
# ---------------------------------------------------------------------------
running     = True
stats_lock  = threading.Lock()
stats       = {
    "sessions": 0,
    "messages": 0,
    "tampered_sessions": 0,
    "tampered_messages": 0,
    "broken_channels": 0,
}


def signal_handler(sig, frame):
    global running
    print("\nShutting down gracefully...")
    running = False


signal.signal(signal.SIGINT, signal_handler)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def load_json(filename: str) -> list[dict]:
    path = os.path.join(DATA_DIR, filename)
    with open(path) as f:
        return json.load(f)


def _pg_connect():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT,
        dbname=PG_DB, user=PG_USER, password=PG_PASSWORD,
    )


def seed_hackers_to_postgres(hackers: list[dict]):
    conn = _pg_connect()
    try:
        cur = conn.cursor()
        for h in hackers:
            cur.execute(
                "INSERT INTO hackers (id, name, signature_seed) "
                "VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (h["hacker_id"], h["name"], h["signature_seed"]),
            )
        conn.commit()
        cur.close()
        print(f"Seeded {len(hackers)} hackers into Postgres.")
    finally:
        conn.close()


def insert_session_topic(
    session_id: str,
    sender_name: str,
    receiver_name: str,
    topic: str,
    message_count: int,
    channel_status: str,
):
    """Write session metadata (topic + BB84 channel status) to session_topics."""
    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO session_topics
                (session_id, sender_name, receiver_name, topic, message_count, channel_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO NOTHING
            """,
            (session_id, sender_name, receiver_name, topic, message_count, channel_status),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pre-built message pools — loaded from data/messages.txt
# Format: [topic name] header lines followed by one message per line.
# Each topic has 36-40 lines; sessions draw in order from a random offset.
# Edit data/messages.txt to add topics or change message text.
# ---------------------------------------------------------------------------
def _load_message_pools() -> dict[str, list[str]]:
    path = os.path.join(DATA_DIR, "messages.txt")
    pools: dict[str, list[str]] = {}
    current_topic: str | None = None
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                current_topic = line[1:-1]
                pools[current_topic] = []
            elif current_topic is not None:
                pools[current_topic].append(line)
    return pools


_MESSAGE_POOLS: dict[str, list[str]] = _load_message_pools()

def generate_session_messages(
    user_a: dict, user_b: dict, num_messages: int
) -> tuple[list[str], str]:
    """
    Pick a random topic and return num_messages lines from its pre-built pool.

    Messages are drawn in order from the pool and wrap around if the session
    is longer than the pool.  This produces coherent, realistic conversations
    without any external API dependency.
    """
    topic = random.choice(list(_MESSAGE_POOLS.keys()))
    pool  = _MESSAGE_POOLS[topic]
    # Draw in order starting from a random offset so sessions differ
    start = random.randint(0, len(pool) - 1)
    msgs  = [pool[(start + i) % len(pool)] for i in range(num_messages)]
    return msgs, topic


# ---------------------------------------------------------------------------
# Kafka producer
# ---------------------------------------------------------------------------
def create_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )


# ---------------------------------------------------------------------------
# Core session logic
# ---------------------------------------------------------------------------
def run_session(
    producer: KafkaProducer,
    user_a: dict,
    user_b: dict,
    hackers: list[dict],
    mitm_pct: float,
    delay: tuple[float, float],
):
    """
    Execute one complete chat session.

    Phase 1: BB84 channel establishment via Qsim.find_secure_channel().
             If a hacker is active from message #1 they act as Eve and
             repeatedly raise QBER above 15 %, forcing channel restarts.
             Session is aborted and recorded as 'broken' if no secure
             channel can be found within BB84_MAX_ATTEMPTS tries.

    Phase 2: Encrypted message exchange.  Per-message quantum state is
             computed deterministically; mid-session hacker activity shifts
             it beyond the 15 % detection threshold.
    """
    session_id   = str(uuid.uuid4())
    num_messages = random.randint(*MESSAGES_PER_SESSION)
    is_mitm      = random.random() < (mitm_pct / 100.0)
    hacker       = random.choice(hackers) if is_mitm else None
    # When does the hacker start intercepting?  Possibly from message #1.
    intercept_start = random.randint(1, num_messages) if is_mitm else num_messages + 1

    with stats_lock:
        if is_mitm:
            stats["tampered_sessions"] += 1
        stats["sessions"] += 1
        session_num = stats["sessions"]

    # -----------------------------------------------------------------------
    # Phase 1 — BB84 channel establishment
    # -----------------------------------------------------------------------
    qsim = Qsim(num_bits=BB84_NUM_BITS)
    # If the hacker is active from the very first message, they also disturb
    # the initial key exchange (Eve is active during QKD).
    initial_eve = is_mitm and intercept_start == 1

    # Suppress verbose Qsim console output
    with contextlib.redirect_stdout(io.StringIO()):
        shared_key = qsim.find_secure_channel(
            num_bits=BB84_NUM_BITS,
            eve_active=initial_eve,
            max_attempts=BB84_MAX_ATTEMPTS,
            qber_threshold=BB84_QBER_THRESHOLD,
        )

    if not shared_key:
        # Channel could never be established — record as broken and abort
        with stats_lock:
            stats["broken_channels"] += 1
        print(
            f"Session {session_num}: {user_a['name']} <-> {user_b['name']} "
            f"— BB84 FAILED (channel broken, hacker blocked key exchange)"
        )
        insert_session_topic(
            session_id, user_a["name"], user_b["name"],
            topic="channel blocked by hacker",
            message_count=0,
            channel_status="broken",
        )
        return

    # -----------------------------------------------------------------------
    # Phase 2 — Generate messages and exchange them
    # -----------------------------------------------------------------------
    messages_list, topic = generate_session_messages(user_a, user_b, num_messages)

    status = (
        f"[MITM by {hacker['name']} from msg #{intercept_start}]"
        if is_mitm else "[clean]"
    )
    print(
        f"Session {session_num}: {user_a['name']} <-> {user_b['name']} "
        f"({num_messages} msgs, topic: '{topic}') {status}"
    )

    # Record session topic and initial channel status
    insert_session_topic(
        session_id, user_a["name"], user_b["name"],
        topic=topic,
        message_count=num_messages,
        channel_status="secure",
    )

    for seq in range(1, num_messages + 1):
        if not running:
            break

        sender, receiver = (
            (user_a, user_b) if seq % 2 == 1 else (user_b, user_a)
        )

        # ------------------------------------------------------------------
        # Quantum state for this message (seeded BB84, no Eve = expected)
        # ------------------------------------------------------------------
        expected = compute_quantum_state(session_id, seq)

        is_hacker_active = is_mitm and seq >= intercept_start

        if is_hacker_active:
            # Hacker shifts the quantum state beyond 15 % threshold
            offset        = hacker_perturbation(hacker["hacker_id"], session_id, seq)
            quantum_state = expected * (1 + offset)
            with stats_lock:
                stats["tampered_messages"] += 1
        else:
            # Normal channel noise stays well below 15 %
            noise         = random.uniform(-NORMAL_NOISE_MAX, NORMAL_NOISE_MAX)
            quantum_state = expected * (1 + noise)

        # ------------------------------------------------------------------
        # Encrypt message content with the shared quantum key
        # ------------------------------------------------------------------
        plaintext        = messages_list[seq - 1]
        encrypted_content = qsim.encrypt_message(plaintext, shared_key)

        message = {
            "message_id":    str(uuid.uuid4()),
            "session_id":    session_id,
            "sender_id":     sender["user_id"],
            "sender_name":   sender["name"],
            "receiver_id":   receiver["user_id"],
            "receiver_name": receiver["name"],
            "sequence_num":  seq,
            "content":       encrypted_content,    # base64 ciphertext
            "quantum_state": round(quantum_state, 8),
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }

        producer.send(KAFKA_TOPIC, key=session_id, value=message)
        with stats_lock:
            stats["messages"] += 1

        time.sleep(random.uniform(*delay))

    producer.flush()


# ---------------------------------------------------------------------------
# Threading helpers
# ---------------------------------------------------------------------------
def session_worker(producer, users, hackers, mitm_pct, delay, semaphore):
    try:
        user_a, user_b = random.sample(users, 2)
        run_session(producer, user_a, user_b, hackers, mitm_pct, delay)
    finally:
        semaphore.release()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Quantum MITM streaming generator")
    parser.add_argument(
        "--sessions", type=int, default=10,
        help="Max concurrent active chat sessions (default: 10)",
    )
    parser.add_argument(
        "--mitm-pct", type=float, default=5.0,
        help="Percentage of sessions intercepted by a hacker (default: 5.0)",
    )
    parser.add_argument(
        "--delay", type=float, nargs=2, default=[0.5, 1.0],
        metavar=("MIN", "MAX"),
        help="Min/max delay in seconds between messages (default: 0.5 1.0)",
    )
    args = parser.parse_args()

    print("Loading data...")
    users   = load_json("users.json")
    hackers = load_json("hackers.json")
    print(f"Loaded {len(users)} users and {len(hackers)} hackers.")

    print("Seeding hackers to Postgres...")
    seed_hackers_to_postgres(hackers)

    print(f"Message generation: pre-built pools ({len(_MESSAGE_POOLS)} topics)")

    print(f"Connecting to Kafka at {KAFKA_BOOTSTRAP}...")
    producer = create_producer()
    print(
        f"Connected.  Starting: {args.sessions} concurrent sessions, "
        f"{args.mitm_pct}% MITM, delay {args.delay[0]}-{args.delay[1]}s "
        f"(Ctrl+C to stop)\n"
    )

    semaphore  = threading.Semaphore(args.sessions)
    delay_tuple = (args.delay[0], args.delay[1])

    try:
        while running:
            semaphore.acquire()
            if not running:
                semaphore.release()
                break
            t = threading.Thread(
                target=session_worker,
                args=(producer, users, hackers, args.mitm_pct, delay_tuple, semaphore),
                daemon=True,
            )
            t.start()
    finally:
        print("Waiting for active sessions to complete...")
        for _ in range(args.sessions):
            semaphore.acquire()
        producer.flush()
        producer.close()

        print("\n--- Final Stats ---")
        print(f"Sessions total:      {stats['sessions']}")
        print(f"Messages total:      {stats['messages']}")
        print(f"Tampered sessions:   {stats['tampered_sessions']}")
        print(f"Tampered messages:   {stats['tampered_messages']}")
        print(f"Broken channels:     {stats['broken_channels']}")


if __name__ == "__main__":
    main()
