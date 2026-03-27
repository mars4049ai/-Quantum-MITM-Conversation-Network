"""
Quantum state functions for MITM detection — powered by real Qiskit BB84.

This module replaces the SHA256 placeholder with a genuine BB84 quantum key
distribution simulation built on the same Qiskit libraries used
by Qsim.py.  The logic mirrors Qsim.simulate_qkd_bb84() exactly; the key
difference is deterministic seeding so that the generator and the Flink job
independently reproduce the same quantum state for every (session_id, seq_num).

Seeding contract (must be identical in flink_job/job.py inline UDFs):
    seed_str  = f"{session_id}:{sequence_num}"               (or hacker variant)
    seed_int  = int(SHA256(seed_str)[:8], 16) % 2**31
    np.random.seed(seed_int)
    random.seed(seed_int)
    seed_simulator = seed_int + qubit_index   (per Qiskit circuit run)

BB84 channel security rule (mirrors Qsim.find_secure_channel):
    QBER < 15 %  →  channel is secure, use shared key
    QBER ≥ 15 %  →  channel is insecure, terminate and restart
"""

import hashlib
import math
import random

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.providers.basic_provider import BasicSimulator

# ---------------------------------------------------------------------------
# Number of BB84 qubits per quantum-state measurement.
# Must match the value used in flink_job/job.py UDFs for determinism.
# ---------------------------------------------------------------------------
_BB84_BITS = 8

# Module-level simulator — instantiated once per process.
_simulator = None


def _get_simulator():
    global _simulator
    if _simulator is None:
        _simulator = BasicSimulator()
    return _simulator


def _run_bb84(
    num_bits: int,
    eve_active: bool,
    seed_int: int,
) -> tuple[float, str, str]:
    """
    Deterministic BB84 simulation — mirrors Qsim.simulate_qkd_bb84().

    Seeding:
        np.random.seed(seed_int) / random.seed(seed_int) control basis choices.
        seed_simulator = seed_int + i       for Alice/Eve circuit (qubit i)
        seed_simulator = seed_int + i + 100 for Bob's circuit    (qubit i)

    Returns:
        (qber_pct, key_alice, key_bob)
        qber_pct  — Quantum Bit Error Rate in percent [0, 100]
        key_alice — agreed key bits from Alice's perspective (binary string)
        key_bob   — agreed key bits from Bob's perspective   (binary string)
    """
    sim = _get_simulator()
    np.random.seed(seed_int)
    random.seed(seed_int)

    alice_bits  = np.random.randint(2, size=num_bits)
    alice_bases = np.random.randint(2, size=num_bits)

    bob_measurements = []

    for i in range(num_bits):
        qc = QuantumCircuit(1, 1)
        if alice_bits[i] == 1:
            qc.x(0)
        if alice_bases[i] == 1:
            qc.h(0)

        if eve_active:
            # Eve intercepts: measure in a random basis, re-prepare qubit
            eve_basis = random.choice([0, 1])
            if eve_basis == 1:
                qc.h(0)
            qc.measure(0, 0)
            res_eve = sim.run(
                transpile(qc, sim), shots=1, seed_simulator=seed_int + i
            ).result().get_counts()
            e_bit = int(max(res_eve, key=res_eve.get))

            # Eve re-prepares and forwards to Bob
            qc = QuantumCircuit(1, 1)
            if e_bit == 1:
                qc.x(0)
            if eve_basis == 1:
                qc.h(0)

        # Bob measures in his own random basis
        bob_basis = random.choice([0, 1])
        if bob_basis == 1:
            qc.h(0)
        qc.measure(0, 0)

        res_bob = sim.run(
            transpile(qc, sim), shots=1, seed_simulator=seed_int + i + 100
        ).result().get_counts()
        b_bit = int(max(res_bob, key=res_bob.get))
        bob_measurements.append({"bit": b_bit, "basis": bob_basis})

    # Basis reconciliation: keep only bits where Alice and Bob used the same basis
    agreed_alice: list[int] = []
    agreed_bob:   list[int] = []
    for i in range(num_bits):
        if alice_bases[i] == bob_measurements[i]["basis"]:
            agreed_alice.append(int(alice_bits[i]))
            agreed_bob.append(bob_measurements[i]["bit"])

    key_alice = "".join(map(str, agreed_alice))
    key_bob   = "".join(map(str, agreed_bob))

    errors  = sum(a != b for a, b in zip(agreed_alice, agreed_bob))
    qber    = (errors / len(agreed_alice)) * 100 if agreed_alice else 0.0

    return qber, key_alice, key_bob


# ---------------------------------------------------------------------------
# Public API — same signatures as the original placeholder module
# ---------------------------------------------------------------------------

def compute_quantum_state(session_id: str, sequence_num: int) -> float:
    """
    Compute the expected quantum channel state for a message.

    Runs a seeded BB84 simulation WITHOUT Eve (clean channel).  Without an
    eavesdropper QBER = 0 %, so Alice and Bob's keys agree perfectly.  The
    float returned is derived from the agreed key bits and the session seed,
    giving a deterministic value in [0, 1] that varies per (session, seq).

    Both generator/quantum.py and flink_job/job.py must call this with the
    SAME seeding to guarantee identical expected-state values.

    Args:
        session_id:   Unique session identifier (acts as shared secret proxy).
        sequence_num: Message sequence number within the session.

    Returns:
        Float in [0, 1] representing the expected quantum state.
    """
    seed_str = f"{session_id}:{sequence_num}"
    seed_int = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16) % (2 ** 31)

    qber, key_alice, _ = _run_bb84(_BB84_BITS, eve_active=False, seed_int=seed_int)

    if key_alice:
        max_val  = (1 << len(key_alice)) - 1
        key_frac = int(key_alice, 2) / max_val if max_val > 0 else 0.5
        # Blend key quality (1 - QBER/100 ≈ 1.0) with the key-derived fraction
        return round((1.0 - qber / 100.0) * 0.4 + key_frac * 0.6, 8)

    # Fallback (all bases mismatched): use SHA256-derived float
    digest = hashlib.sha256(seed_str.encode()).hexdigest()
    value  = int(digest[:8], 16) / 0xFFFFFFFF
    return round((math.sin(value * math.pi * 7) + 1) / 2, 8)


def hacker_perturbation(hacker_id: int, session_id: str, sequence_num: int) -> float:
    """
    Compute a hacker's quantum measurement perturbation using BB84 with Eve.

    Each hacker has a unique (hacker_id, session_id, seq) seed, so they
    produce a characteristic, deterministic perturbation derived from the
    QBER they introduce when acting as Eve.

    With Eve active, QBER ≈ 25 % (theoretical BB84 value), so the
    resulting perturbation magnitude is guaranteed > 15 %.

    Args:
        hacker_id:    Unique hacker identifier (1-250).
        session_id:   Session being intercepted.
        sequence_num: Message sequence number.

    Returns:
        Signed perturbation factor (magnitude ≥ 0.20).
        Applied as: actual = expected * (1 + offset).
    """
    seed_str = f"hacker:{hacker_id}:{session_id}:{sequence_num}"
    seed_int = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16) % (2 ** 31)

    qber, _, _ = _run_bb84(_BB84_BITS, eve_active=True, seed_int=seed_int)

    # Map QBER [0, 100] → magnitude [0.20, 0.50] — always > 15 % detection threshold
    magnitude = max(0.20, min(0.50, qber / 100.0 + 0.10))
    # Direction: deterministic per hacker_id so each hacker has a unique "signature"
    direction = 1 if hacker_id % 2 == 0 else -1
    return direction * magnitude


def identify_hacker(
    session_id: str,
    sequence_num: int,
    expected: float,
    actual: float,
    num_hackers: int = 250,
) -> int:
    """
    Identify which hacker caused the observed quantum state perturbation.

    Brute-forces all hacker signatures using the same seeded BB84 logic as
    hacker_perturbation() and returns the best match.

    NOTE: This is an expensive O(num_hackers) operation (each call runs
    num_hackers × BB84 simulations).  It is only called from the generator
    for diagnostic purposes; Flink uses its own inline UDF.

    Args:
        session_id:   Session identifier.
        sequence_num: Message sequence number.
        expected:     Expected quantum state.
        actual:       Observed (possibly tampered) quantum state.
        num_hackers:  Total number of hackers to check.

    Returns:
        hacker_id (1-250) if matched within tolerance, -1 otherwise.
    """
    best_match = -1
    best_diff  = float("inf")
    for hacker_id in range(1, num_hackers + 1):
        offset          = hacker_perturbation(hacker_id, session_id, sequence_num)
        expected_actual = expected * (1 + offset)
        diff            = abs(expected_actual - actual)
        if diff < best_diff:
            best_diff  = diff
            best_match = hacker_id
    return best_match if best_diff < 0.01 else -1
