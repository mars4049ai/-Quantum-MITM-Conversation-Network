#!/usr/bin/env python3
"""
Continuous message generator for the streaming hackathon demo.

Loads pre-generated users and hackers from data/ files. Runs multiple
concurrent chat sessions, sending messages to Kafka. A configurable
percentage of sessions are intercepted by a hacker.

Runs until Ctrl+C.

Usage:
    python generator.py [--sessions N] [--mitm-pct P] [--delay MIN MAX]
"""

import argparse
import json
import os
import random
import signal
import threading
import time
import uuid
from datetime import datetime, timezone

import psycopg2
from kafka import KafkaProducer

from quantum import compute_quantum_state, hacker_perturbation

# --- Configuration defaults ---
KAFKA_BOOTSTRAP = "localhost:29092"
KAFKA_TOPIC = "messages"
PG_HOST = "localhost"
PG_PORT = 5432
PG_DB = "streaming"
PG_USER = "hackathon"
PG_PASSWORD = "hackathon"

NORMAL_NOISE_MAX = 0.10
MESSAGES_PER_SESSION = (20, 40)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# --- Globals for graceful shutdown ---
running = True
stats_lock = threading.Lock()
stats = {"sessions": 0, "messages": 0, "tampered_sessions": 0, "tampered_messages": 0}


def signal_handler(sig, frame):
    global running
    print("\nShutting down gracefully...")
    running = False


signal.signal(signal.SIGINT, signal_handler)


def load_json(filename: str) -> list[dict]:
    path = os.path.join(DATA_DIR, filename)
    with open(path) as f:
        return json.load(f)


def seed_hackers_to_postgres(hackers: list[dict]):
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD
    )
    try:
        cur = conn.cursor()
        for h in hackers:
            cur.execute(
                "INSERT INTO hackers (id, name, signature_seed) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (h["hacker_id"], h["name"], h["signature_seed"]),
            )
        conn.commit()
        cur.close()
        print(f"Seeded {len(hackers)} hackers into Postgres.")
    finally:
        conn.close()


def create_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )


def run_session(producer: KafkaProducer, user_a: dict, user_b: dict,
                hackers: list[dict], mitm_pct: float, delay: tuple[float, float]):
    """Generate a single chat session between two users."""
    session_id = str(uuid.uuid4())
    num_messages = random.randint(*MESSAGES_PER_SESSION)
    is_mitm = random.random() < (mitm_pct / 100.0)
    hacker = random.choice(hackers) if is_mitm else None
    intercept_start = random.randint(1, num_messages) if is_mitm else num_messages + 1

    with stats_lock:
        if is_mitm:
            stats["tampered_sessions"] += 1
        stats["sessions"] += 1
        session_num = stats["sessions"]

    status = f"[MITM by {hacker['name']} from msg #{intercept_start}]" if is_mitm else "[clean]"
    print(
        f"Session {session_num}: {user_a['name']} <-> {user_b['name']} "
        f"({num_messages} msgs) {status}"
    )

    for seq in range(1, num_messages + 1):
        if not running:
            break

        if seq % 2 == 1:
            sender, receiver = user_a, user_b
        else:
            sender, receiver = user_b, user_a

        expected = compute_quantum_state(session_id, seq)

        if is_mitm and seq >= intercept_start:
            offset = hacker_perturbation(hacker["hacker_id"], session_id, seq)
            quantum_state = expected * (1 + offset)
            with stats_lock:
                stats["tampered_messages"] += 1
        else:
            noise = random.uniform(-NORMAL_NOISE_MAX, NORMAL_NOISE_MAX)
            quantum_state = expected * (1 + noise)

        message = {
            "message_id": str(uuid.uuid4()),
            "session_id": session_id,
            "sender_id": sender["user_id"],
            "sender_name": sender["name"],
            "receiver_id": receiver["user_id"],
            "receiver_name": receiver["name"],
            "sequence_num": seq,
            "content": f"Message {seq} from {sender['name']}",
            "quantum_state": round(quantum_state, 8),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        producer.send(KAFKA_TOPIC, key=session_id, value=message)
        with stats_lock:
            stats["messages"] += 1

        time.sleep(random.uniform(*delay))

    producer.flush()


def session_worker(producer, users, hackers, mitm_pct, delay, semaphore):
    """Worker that runs one session then releases the semaphore slot."""
    try:
        user_a, user_b = random.sample(users, 2)
        run_session(producer, user_a, user_b, hackers, mitm_pct, delay)
    finally:
        semaphore.release()


def main():
    parser = argparse.ArgumentParser(description="Streaming message generator")
    parser.add_argument(
        "--sessions", type=int, default=10,
        help="Number of concurrent active sessions (default: 10)"
    )
    parser.add_argument(
        "--mitm-pct", type=float, default=5.0,
        help="Percentage of sessions that are MITM-tampered (default: 5.0)"
    )
    parser.add_argument(
        "--delay", type=float, nargs=2, default=[0.5, 1.0], metavar=("MIN", "MAX"),
        help="Min and max delay in seconds between messages (default: 0.5 1.0)"
    )
    args = parser.parse_args()

    print("Loading data...")
    users = load_json("users.json")
    hackers = load_json("hackers.json")
    print(f"Loaded {len(users)} users and {len(hackers)} hackers.")

    print("Seeding hackers to Postgres...")
    seed_hackers_to_postgres(hackers)

    print(f"Connecting to Kafka at {KAFKA_BOOTSTRAP}...")
    producer = create_producer()
    print(
        f"Connected. Starting generation: {args.sessions} concurrent sessions, "
        f"{args.mitm_pct}% MITM, delay {args.delay[0]}-{args.delay[1]}s "
        f"(Ctrl+C to stop)\n"
    )

    # Semaphore controls max concurrent sessions
    semaphore = threading.Semaphore(args.sessions)
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
        # Wait for active sessions to finish
        print("Waiting for active sessions to complete...")
        for _ in range(args.sessions):
            semaphore.acquire()
        producer.flush()
        producer.close()
        print(f"\n--- Final Stats ---")
        print(f"Sessions: {stats['sessions']}")
        print(f"Messages: {stats['messages']}")
        print(f"Tampered sessions: {stats['tampered_sessions']}")
        print(f"Tampered messages: {stats['tampered_messages']}")


if __name__ == "__main__":
    main()
