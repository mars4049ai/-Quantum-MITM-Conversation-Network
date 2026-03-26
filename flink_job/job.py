#!/usr/bin/env python3
"""
PyFlink streaming job for Quantum MITM detection.

Reads messages from Kafka, recomputes the expected quantum state via real
Qiskit BB84 simulation (same seeding as generator/quantum.py), detects
anomalies (deviation > 15 %), identifies the responsible hacker, records
the hacker's failed decryption attempt, and writes results to PostgreSQL
and the Kafka alerts topic.

All UDFs are fully self-contained (imports inside function body) because
Flink serialises them and ships them to TaskManagers — no external module
state is available at call time, but module-level globals created inside
the function body persist within the Python worker process.

BB84 seeding contract (identical to generator/quantum.py):
    seed_str  = f"{session_id}:{seq_num}"   (or hacker variant)
    seed_int  = int(SHA256(seed_str)[:8], 16) % 2**31
    np.random.seed(seed_int); random.seed(seed_int)
    seed_simulator = seed_int + qubit_index         (Alice/Eve circuit)
    seed_simulator = seed_int + qubit_index + 100   (Bob circuit)
"""

from pyflink.table import EnvironmentSettings, TableEnvironment, DataTypes
from pyflink.table.udf import udf

# ============================================================
#  UDF 1: compute_expected_state
#  Mirrors generator/quantum.py:compute_quantum_state() exactly.
# ============================================================

@udf(result_type=DataTypes.DOUBLE())
def compute_expected_state(session_id: str, sequence_num: int) -> float:
    """
    Deterministic BB84 (no Eve) quantum state — identical to generator.
    """
    import hashlib, math, random
    import numpy as np
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import Aer

    global _QASM_SIM_EXPECTED
    try:
        _QASM_SIM_EXPECTED
    except NameError:
        _QASM_SIM_EXPECTED = Aer.get_backend("qasm_simulator")
    sim = _QASM_SIM_EXPECTED

    _NUM_BITS = 8
    seed_str = f"{session_id}:{sequence_num}"
    seed_int = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16) % (2 ** 31)
    np.random.seed(seed_int)
    random.seed(seed_int)

    alice_bits  = np.random.randint(2, size=_NUM_BITS)
    alice_bases = np.random.randint(2, size=_NUM_BITS)
    bob_measurements = []

    for i in range(_NUM_BITS):
        qc = QuantumCircuit(1, 1)
        if alice_bits[i] == 1:
            qc.x(0)
        if alice_bases[i] == 1:
            qc.h(0)
        bob_basis = random.choice([0, 1])
        if bob_basis == 1:
            qc.h(0)
        qc.measure(0, 0)
        res = sim.run(
            transpile(qc, sim), shots=1, seed_simulator=seed_int + i + 100
        ).result().get_counts()
        b_bit = int(max(res, key=res.get))
        bob_measurements.append({"bit": b_bit, "basis": bob_basis})

    agreed_alice = []
    agreed_bob   = []
    for i in range(_NUM_BITS):
        if alice_bases[i] == bob_measurements[i]["basis"]:
            agreed_alice.append(int(alice_bits[i]))
            agreed_bob.append(bob_measurements[i]["bit"])

    key_alice = "".join(map(str, agreed_alice))
    errors    = sum(a != b for a, b in zip(agreed_alice, agreed_bob))
    qber      = (errors / len(agreed_alice)) * 100 if agreed_alice else 0.0

    if key_alice:
        max_val  = (1 << len(key_alice)) - 1
        key_frac = int(key_alice, 2) / max_val if max_val > 0 else 0.5
        return round((1.0 - qber / 100.0) * 0.4 + key_frac * 0.6, 8)

    digest = hashlib.sha256(seed_str.encode()).hexdigest()
    value  = int(digest[:8], 16) / 0xFFFFFFFF
    return round((math.sin(value * math.pi * 7) + 1) / 2, 8)


# ============================================================
#  UDF 2: identify_hacker
#  Brute-forces 250 hacker signatures using the same seeded
#  BB84 approach as generator/quantum.py:hacker_perturbation().
#  Uses 4-bit BB84 for Flink performance (full 250 × 8 = 2000
#  Qiskit runs per tampered message would be too slow).
# ============================================================

@udf(result_type=DataTypes.INT())
def identify_hacker_udf(
    session_id: str, sequence_num: int, expected: float, actual: float
) -> int:
    import hashlib, random
    import numpy as np
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import Aer

    global _QASM_SIM_IDENTIFY
    try:
        _QASM_SIM_IDENTIFY
    except NameError:
        _QASM_SIM_IDENTIFY = Aer.get_backend("qasm_simulator")
    sim = _QASM_SIM_IDENTIFY

    _NUM_BITS  = 4       # fewer bits for performance in identification loop
    num_hackers = 250
    best_match  = -1
    best_diff   = float("inf")

    for hacker_id in range(1, num_hackers + 1):
        seed_str = f"hacker:{hacker_id}:{session_id}:{sequence_num}"
        seed_int = (
            int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16) % (2 ** 31)
        )
        np.random.seed(seed_int)
        random.seed(seed_int)

        alice_bits  = np.random.randint(2, size=_NUM_BITS)
        alice_bases = np.random.randint(2, size=_NUM_BITS)
        bob_measurements = []

        for i in range(_NUM_BITS):
            qc = QuantumCircuit(1, 1)
            if alice_bits[i] == 1:
                qc.x(0)
            if alice_bases[i] == 1:
                qc.h(0)
            # Eve intercepts
            eve_basis = random.choice([0, 1])
            if eve_basis == 1:
                qc.h(0)
            qc.measure(0, 0)
            res_eve = sim.run(
                transpile(qc, sim), shots=1, seed_simulator=seed_int + i
            ).result().get_counts()
            e_bit = int(max(res_eve, key=res_eve.get))

            qc2 = QuantumCircuit(1, 1)
            if e_bit == 1:
                qc2.x(0)
            if eve_basis == 1:
                qc2.h(0)
            bob_basis = random.choice([0, 1])
            if bob_basis == 1:
                qc2.h(0)
            qc2.measure(0, 0)
            res_bob = sim.run(
                transpile(qc2, sim), shots=1, seed_simulator=seed_int + i + 100
            ).result().get_counts()
            b_bit = int(max(res_bob, key=res_bob.get))
            bob_measurements.append({"bit": b_bit, "basis": bob_basis})

        agreed_alice = [int(alice_bits[i]) for i in range(_NUM_BITS)
                        if alice_bases[i] == bob_measurements[i]["basis"]]
        agreed_bob   = [bob_measurements[i]["bit"] for i in range(_NUM_BITS)
                        if alice_bases[i] == bob_measurements[i]["basis"]]

        errors   = sum(a != b for a, b in zip(agreed_alice, agreed_bob))
        qber_frac = (errors / len(agreed_alice)) if agreed_alice else 0.25
        magnitude = max(0.20, min(0.50, qber_frac + 0.10))
        direction = 1 if hacker_id % 2 == 0 else -1
        offset    = direction * magnitude

        expected_actual = expected * (1 + offset)
        diff = abs(expected_actual - actual)
        if diff < best_diff:
            best_diff  = diff
            best_match = hacker_id

    return best_match if best_diff < 0.01 else -1


# ============================================================
#  UDFs 3-5: hacker attempt simulation
#  These three UDFs reconstruct what the hacker computed and
#  what garbage they got when trying to decrypt with wrong key.
#  They share the same seeded BB84-with-Eve logic for the hacker.
# ============================================================

def _bb84_hacker_run(hacker_id: int, session_id: str, sequence_num: int,
                     sim, num_bits: int = 8):
    """
    Shared helper (called inside each hacker-attempt UDF) — NOT a UDF itself.
    Returns (qber_pct, key_bob_str, key_alice_str).
    """
    import hashlib, random
    import numpy as np
    from qiskit import QuantumCircuit, transpile

    seed_str = f"hacker:{hacker_id}:{session_id}:{sequence_num}"
    seed_int = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16) % (2 ** 31)
    np.random.seed(seed_int)
    random.seed(seed_int)

    alice_bits  = np.random.randint(2, size=num_bits)
    alice_bases = np.random.randint(2, size=num_bits)
    bob_meas    = []

    for i in range(num_bits):
        qc = QuantumCircuit(1, 1)
        if alice_bits[i] == 1:
            qc.x(0)
        if alice_bases[i] == 1:
            qc.h(0)
        eve_basis = random.choice([0, 1])
        if eve_basis == 1:
            qc.h(0)
        qc.measure(0, 0)
        res_eve = sim.run(
            transpile(qc, sim), shots=1, seed_simulator=seed_int + i
        ).result().get_counts()
        e_bit = int(max(res_eve, key=res_eve.get))

        qc2 = QuantumCircuit(1, 1)
        if e_bit == 1:
            qc2.x(0)
        if eve_basis == 1:
            qc2.h(0)
        bob_basis = random.choice([0, 1])
        if bob_basis == 1:
            qc2.h(0)
        qc2.measure(0, 0)
        res_bob = sim.run(
            transpile(qc2, sim), shots=1, seed_simulator=seed_int + i + 100
        ).result().get_counts()
        b_bit = int(max(res_bob, key=res_bob.get))
        bob_meas.append({"bit": b_bit, "basis": bob_basis})

    agreed_alice = [int(alice_bits[i]) for i in range(num_bits)
                    if alice_bases[i] == bob_meas[i]["basis"]]
    agreed_bob   = [bob_meas[i]["bit"] for i in range(num_bits)
                    if alice_bases[i] == bob_meas[i]["basis"]]

    key_alice = "".join(map(str, agreed_alice))
    key_bob   = "".join(map(str, agreed_bob))
    errors    = sum(a != b for a, b in zip(agreed_alice, agreed_bob))
    qber      = (errors / len(agreed_alice)) * 100 if agreed_alice else 25.0

    return qber, key_bob, key_alice


@udf(result_type=DataTypes.DOUBLE())
def hacker_qber_udf(session_id: str, sequence_num: int, hacker_id: int) -> float:
    """QBER (%) that this hacker produced during their BB84 interception."""
    from qiskit_aer import Aer
    global _QASM_SIM_HACKER_Q
    try:
        _QASM_SIM_HACKER_Q
    except NameError:
        _QASM_SIM_HACKER_Q = Aer.get_backend("qasm_simulator")
    qber, _, _ = _bb84_hacker_run(hacker_id, session_id, sequence_num,
                                   _QASM_SIM_HACKER_Q)
    return round(qber, 4)


@udf(result_type=DataTypes.STRING())
def hacker_key_udf(session_id: str, sequence_num: int, hacker_id: int) -> str:
    """The wrong key the hacker derived from their disturbed BB84 measurement."""
    from qiskit_aer import Aer
    global _QASM_SIM_HACKER_K
    try:
        _QASM_SIM_HACKER_K
    except NameError:
        _QASM_SIM_HACKER_K = Aer.get_backend("qasm_simulator")
    _, key_bob, _ = _bb84_hacker_run(hacker_id, session_id, sequence_num,
                                      _QASM_SIM_HACKER_K)
    return key_bob if key_bob else "0000"


@udf(result_type=DataTypes.STRING())
def hacker_garbage_udf(
    session_id: str, sequence_num: int, hacker_id: int, content: str
) -> str:
    """
    Simulate the hacker's failed decryption attempt.

    The message content is ciphertext encrypted with Alice's correct BB84 key.
    The hacker uses their own (wrong) key derived from the disturbed BB84
    measurement → decryption produces garbage, demonstrating quantum security.

    Mirrors Qsim.decrypt_message() / classical_message_exchange() logic.
    """
    import hashlib, base64
    from qiskit_aer import Aer
    global _QASM_SIM_HACKER_G
    try:
        _QASM_SIM_HACKER_G
    except NameError:
        _QASM_SIM_HACKER_G = Aer.get_backend("qasm_simulator")

    _, key_bob, _ = _bb84_hacker_run(hacker_id, session_id, sequence_num,
                                      _QASM_SIM_HACKER_G)
    wrong_key = key_bob if key_bob else "0000"

    # Inline XOR decrypt (mirrors Qsim.decrypt_message)
    try:
        encrypted_bytes = base64.b64decode(content.encode("ascii"))
    except Exception:
        return "[invalid ciphertext]"

    key_hash   = hashlib.sha256(wrong_key.encode()).digest()
    decrypted  = bytes(b ^ key_hash[i % len(key_hash)]
                       for i, b in enumerate(encrypted_bytes))
    # The result is garbage — display first 80 chars, replace un-printable bytes
    garbage = decrypted.decode("utf-8", errors="replace")[:80]
    return garbage


# ============================================================
#  Main Flink job
# ============================================================

def main():
    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)

    # Register UDFs
    t_env.create_temporary_function("compute_expected_state", compute_expected_state)
    t_env.create_temporary_function("identify_hacker",        identify_hacker_udf)
    t_env.create_temporary_function("hacker_qber_udf",        hacker_qber_udf)
    t_env.create_temporary_function("hacker_key_udf",         hacker_key_udf)
    t_env.create_temporary_function("hacker_garbage_udf",     hacker_garbage_udf)

    # ------------------------------------------------------------------
    # Sources and Sinks
    # ------------------------------------------------------------------

    # Kafka source
    t_env.execute_sql("""
        CREATE TABLE kafka_messages (
            message_id    STRING,
            session_id    STRING,
            sender_id     INT,
            sender_name   STRING,
            receiver_id   INT,
            receiver_name STRING,
            sequence_num  INT,
            content       STRING,
            quantum_state DOUBLE,
            `timestamp`   STRING
        ) WITH (
            'connector'                     = 'kafka',
            'topic'                         = 'messages',
            'properties.bootstrap.servers'  = 'kafka:9092',
            'properties.group.id'           = 'flink-mitm-detector',
            'scan.startup.mode'             = 'earliest-offset',
            'format'                        = 'json',
            'json.fail-on-missing-field'    = 'false'
        )
    """)

    # PostgreSQL: all messages (with is_tampered flag)
    t_env.execute_sql("""
        CREATE TABLE pg_messages (
            message_id    STRING,
            session_id    STRING,
            sender_id     INT,
            sender_name   STRING,
            receiver_id   INT,
            receiver_name STRING,
            sequence_num  INT,
            content       STRING,
            quantum_state DOUBLE,
            is_tampered   BOOLEAN
        ) WITH (
            'connector'  = 'jdbc',
            'url'        = 'jdbc:postgresql://postgres:5432/streaming',
            'table-name' = 'messages',
            'username'   = 'hackathon',
            'password'   = 'hackathon',
            'driver'     = 'org.postgresql.Driver'
        )
    """)

    # PostgreSQL: tampered message alerts
    t_env.execute_sql("""
        CREATE TABLE pg_alerts (
            message_id     STRING,
            session_id     STRING,
            sender_id      INT,
            sequence_num   INT,
            hacker_id      INT,
            expected_state DOUBLE,
            actual_state   DOUBLE,
            deviation_pct  DOUBLE
        ) WITH (
            'connector'  = 'jdbc',
            'url'        = 'jdbc:postgresql://postgres:5432/streaming',
            'table-name' = 'alerts',
            'username'   = 'hackathon',
            'password'   = 'hackathon',
            'driver'     = 'org.postgresql.Driver'
        )
    """)

    # PostgreSQL: hacker decryption attempts
    t_env.execute_sql("""
        CREATE TABLE pg_hacker_attempts (
            message_id        STRING,
            session_id        STRING,
            sequence_num      INT,
            hacker_id         INT,
            hacker_qber       DOUBLE,
            attempted_key     STRING,
            decrypted_garbage STRING,
            noise_level       DOUBLE
        ) WITH (
            'connector'  = 'jdbc',
            'url'        = 'jdbc:postgresql://postgres:5432/streaming',
            'table-name' = 'hacker_decryption_attempts',
            'username'   = 'hackathon',
            'password'   = 'hackathon',
            'driver'     = 'org.postgresql.Driver'
        )
    """)

    # Kafka: alerts topic (for downstream consumers)
    t_env.execute_sql("""
        CREATE TABLE kafka_alerts (
            message_id     STRING,
            session_id     STRING,
            sender_id      INT,
            sequence_num   INT,
            hacker_id      INT,
            expected_state DOUBLE,
            actual_state   DOUBLE,
            deviation_pct  DOUBLE
        ) WITH (
            'connector'                    = 'kafka',
            'topic'                        = 'alerts',
            'properties.bootstrap.servers' = 'kafka:9092',
            'format'                       = 'json'
        )
    """)

    # ------------------------------------------------------------------
    # Enriched view: compute expected state + deviation per message
    # ------------------------------------------------------------------
    t_env.execute_sql("""
        CREATE TEMPORARY VIEW enriched_messages AS
        SELECT
            message_id, session_id, sender_id, sender_name,
            receiver_id, receiver_name, sequence_num, content,
            quantum_state, expected_state,
            ABS(quantum_state - expected_state)
                / GREATEST(ABS(expected_state), 0.01) AS deviation_pct
        FROM (
            SELECT *,
                   compute_expected_state(session_id, sequence_num) AS expected_state
            FROM kafka_messages
        )
    """)

    # Tampered-only sub-view with hacker_id computed once (avoid triple Qiskit call)
    t_env.execute_sql("""
        CREATE TEMPORARY VIEW tampered_with_hacker AS
        SELECT
            message_id, session_id, sender_id, sender_name,
            receiver_id, receiver_name, sequence_num, content,
            quantum_state, expected_state, deviation_pct,
            identify_hacker(session_id, sequence_num, expected_state, quantum_state)
                AS hacker_id
        FROM enriched_messages
        WHERE deviation_pct > 0.15
    """)

    # ------------------------------------------------------------------
    # Fan-out via StatementSet
    # ------------------------------------------------------------------
    stmt_set = t_env.create_statement_set()

    # 1. All messages → pg_messages
    stmt_set.add_insert_sql("""
        INSERT INTO pg_messages
        SELECT
            message_id, session_id, sender_id, sender_name,
            receiver_id, receiver_name, sequence_num, content,
            quantum_state,
            deviation_pct > 0.15 AS is_tampered
        FROM enriched_messages
    """)

    # 2. Tampered messages → pg_alerts
    stmt_set.add_insert_sql("""
        INSERT INTO pg_alerts
        SELECT
            message_id, session_id, sender_id, sequence_num,
            hacker_id, expected_state, quantum_state, deviation_pct
        FROM tampered_with_hacker
    """)

    # 3. Tampered messages → Kafka alerts topic
    stmt_set.add_insert_sql("""
        INSERT INTO kafka_alerts
        SELECT
            message_id, session_id, sender_id, sequence_num,
            hacker_id, expected_state, quantum_state, deviation_pct
        FROM tampered_with_hacker
    """)

    # 4. Hacker decryption attempts → pg_hacker_attempts
    #    Shows what the hacker computed (QBER, wrong key) and the garbage
    #    they get when trying to decrypt the ciphertext with their wrong key.
    stmt_set.add_insert_sql("""
        INSERT INTO pg_hacker_attempts
        SELECT
            message_id,
            session_id,
            sequence_num,
            hacker_id,
            hacker_qber_udf(session_id, sequence_num, hacker_id),
            hacker_key_udf(session_id, sequence_num, hacker_id),
            hacker_garbage_udf(session_id, sequence_num, hacker_id, content),
            deviation_pct
        FROM tampered_with_hacker
    """)

    stmt_set.execute().wait()


if __name__ == "__main__":
    main()
