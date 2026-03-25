#!/usr/bin/env python3
"""
PyFlink streaming job for MITM detection.

Reads messages from Kafka, computes expected quantum state, detects anomalies
(deviation > 15%), identifies the responsible hacker, and writes results to
PostgreSQL (all messages to `messages` table, alerts to `alerts` table)
and Kafka `alerts` topic.
"""

from pyflink.table import EnvironmentSettings, TableEnvironment, DataTypes
from pyflink.table.udf import udf

# --- Inline quantum functions (must be self-contained for Flink serialization) ---

@udf(result_type=DataTypes.DOUBLE())
def compute_expected_state(session_id: str, sequence_num: int) -> float:
    import hashlib, math
    seed = f"{session_id}:{sequence_num}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()
    value = int(digest[:8], 16) / 0xFFFFFFFF
    return (math.sin(value * math.pi * 7) + 1) / 2


@udf(result_type=DataTypes.INT())
def identify_hacker_udf(session_id: str, sequence_num: int, expected: float, actual: float) -> int:
    import hashlib
    num_hackers = 250
    best_match = -1
    best_diff = float("inf")
    for hacker_id in range(1, num_hackers + 1):
        seed = f"hacker:{hacker_id}:{session_id}:{sequence_num}".encode("utf-8")
        digest = hashlib.sha256(seed).hexdigest()
        raw = int(digest[:8], 16) / 0xFFFFFFFF
        magnitude = 0.20 + raw * 0.30
        direction = 1 if int(digest[8:16], 16) % 2 == 0 else -1
        offset = direction * magnitude
        expected_actual = expected * (1 + offset)
        diff = abs(expected_actual - actual)
        if diff < best_diff:
            best_diff = diff
            best_match = hacker_id
    if best_diff < 0.01:
        return best_match
    return -1


def main():
    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)

    # Register UDFs
    t_env.create_temporary_function("compute_expected_state", compute_expected_state)
    t_env.create_temporary_function("identify_hacker", identify_hacker_udf)

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
            'connector' = 'kafka',
            'topic' = 'messages',
            'properties.bootstrap.servers' = 'kafka:9092',
            'properties.group.id' = 'flink-mitm-detector',
            'scan.startup.mode' = 'earliest-offset',
            'format' = 'json',
            'json.fail-on-missing-field' = 'false'
        )
    """)

    # PostgreSQL messages sink
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
            'connector' = 'jdbc',
            'url' = 'jdbc:postgresql://postgres:5432/streaming',
            'table-name' = 'messages',
            'username' = 'hackathon',
            'password' = 'hackathon',
            'driver' = 'org.postgresql.Driver'
        )
    """)

    # PostgreSQL alerts sink
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
            'connector' = 'jdbc',
            'url' = 'jdbc:postgresql://postgres:5432/streaming',
            'table-name' = 'alerts',
            'username' = 'hackathon',
            'password' = 'hackathon',
            'driver' = 'org.postgresql.Driver'
        )
    """)

    # Kafka alerts sink
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
            'connector' = 'kafka',
            'topic' = 'alerts',
            'properties.bootstrap.servers' = 'kafka:9092',
            'format' = 'json'
        )
    """)

    # Enriched view: compute expected state and deviation for each message
    # Subquery ensures compute_expected_state UDF is called once per row
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

    # Fan out to all sinks using StatementSet
    stmt_set = t_env.create_statement_set()

    # All messages -> pg_messages (with tampered flag)
    stmt_set.add_insert_sql("""
        INSERT INTO pg_messages
        SELECT
            message_id, session_id, sender_id, sender_name,
            receiver_id, receiver_name, sequence_num, content,
            quantum_state,
            deviation_pct > 0.15 AS is_tampered
        FROM enriched_messages
    """)

    # Anomalous messages -> pg_alerts (with hacker identification)
    stmt_set.add_insert_sql("""
        INSERT INTO pg_alerts
        SELECT
            message_id, session_id, sender_id, sequence_num,
            identify_hacker(session_id, sequence_num, expected_state, quantum_state),
            expected_state, quantum_state, deviation_pct
        FROM enriched_messages
        WHERE deviation_pct > 0.15
    """)

    # Anomalous messages -> kafka_alerts topic
    stmt_set.add_insert_sql("""
        INSERT INTO kafka_alerts
        SELECT
            message_id, session_id, sender_id, sequence_num,
            identify_hacker(session_id, sequence_num, expected_state, quantum_state),
            expected_state, quantum_state, deviation_pct
        FROM enriched_messages
        WHERE deviation_pct > 0.15
    """)

    stmt_set.execute().wait()


if __name__ == "__main__":
    main()
