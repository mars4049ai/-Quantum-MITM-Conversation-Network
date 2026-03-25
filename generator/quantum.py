"""
Quantum state functions for MITM detection.

This module is the single source of truth for quantum state computation
and hacker signature matching. Replace the function bodies here to plug
in a real quantum function later.

Note: the Flink job (flink_job/job.py) contains inline copies of these
functions inside UDFs — Flink serialization requires them to be
self-contained. Update both places when changing the algorithms.
"""

import hashlib
import math


def compute_quantum_state(session_id: str, sequence_num: int) -> float:
    """
    Compute expected quantum state for a message. Deterministic.

    Args:
        session_id: Unique session identifier (acts as shared secret proxy).
        sequence_num: Message sequence number within the session.

    Returns:
        Float in [0, 1] representing the expected quantum state.
    """
    seed = f"{session_id}:{sequence_num}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()
    value = int(digest[:8], 16) / 0xFFFFFFFF
    return (math.sin(value * math.pi * 7) + 1) / 2


def hacker_perturbation(hacker_id: int, session_id: str, sequence_num: int) -> float:
    """
    Compute a hacker's unique measurement signature perturbation.

    Each hacker produces a characteristic, deterministic offset when they
    intercept a message. The magnitude is always > 0.15 (ensuring detection).

    Args:
        hacker_id: Unique hacker identifier (1-250).
        session_id: Session being intercepted.
        sequence_num: Message sequence number.

    Returns:
        Signed perturbation factor. Applied as: actual = expected * (1 + offset).
    """
    seed = f"hacker:{hacker_id}:{session_id}:{sequence_num}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()
    raw = int(digest[:8], 16) / 0xFFFFFFFF
    magnitude = 0.20 + raw * 0.30  # [0.20, 0.50]
    direction = 1 if int(digest[8:16], 16) % 2 == 0 else -1
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

    Tries each hacker's signature and finds the best match.

    Args:
        session_id: Session identifier.
        sequence_num: Message sequence number.
        expected: Expected quantum state.
        actual: Observed (possibly tampered) quantum state.
        num_hackers: Total number of hackers to check.

    Returns:
        hacker_id (1-250) if matched, -1 if no match found.
    """
    best_match = -1
    best_diff = float("inf")
    for hacker_id in range(1, num_hackers + 1):
        offset = hacker_perturbation(hacker_id, session_id, sequence_num)
        expected_actual = expected * (1 + offset)
        diff = abs(expected_actual - actual)
        if diff < best_diff:
            best_diff = diff
            best_match = hacker_id
    if best_diff < 0.01:
        return best_match
    return -1
