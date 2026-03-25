# Streaming Hackathon: Quantum MITM Detection

Real-time man-in-the-middle attack detection on encrypted communication sessions using Apache Kafka, Apache Flink, and PostgreSQL.

## Quantum Concept

Inspired by the **BB84 quantum key distribution protocol**: observing a quantum state disturbs it. When two parties communicate over a quantum channel, an eavesdropper who intercepts a message must "measure" it, introducing a detectable perturbation.

In this demo, each message carries a **quantum state** — a deterministic value derived from `session_id + sequence_num`. Under normal conditions, noise stays within 10%. When a hacker intercepts, their unique **measurement signature** pushes deviation above 15%, triggering detection and hacker identification. The quantum function is a placeholder and can be replaced with a real implementation.

## Architecture

```
                                                    +--> PostgreSQL: messages table
[Python Generator] --> [Kafka: messages] --> [Flink] +--> PostgreSQL: alerts table
   (local venv)          (Docker)           (Docker) +--> Kafka: alerts topic
```

- **500 users** chat in pairs, creating continuous sessions (20-40 messages each)
- **250 hackers** can intercept sessions, each with a unique quantum measurement signature
- **Flink** detects quantum state deviations >15% and identifies the responsible hacker in real-time
- Alerts are written to both **PostgreSQL** (for querying) and a **Kafka `alerts` topic** (for downstream consumers)

## Prerequisites

- Docker and Docker Compose
- Python 3.11+

## Quick Start

### 1. Start infrastructure

```bash
docker compose up -d --build
```

Wait **~30-60 seconds** for Kafka, Postgres, and Flink to fully initialize.

| UI              | URL                    |
|-----------------|------------------------|
| Flink Dashboard | http://localhost:8081   |
| Kafka UI        | http://localhost:8080   |

### 2. Set up Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r generator/requirements.txt
```

### 3. Submit the Flink job

```bash
docker exec jobmanager flink run -py /opt/flink/usrlib/job.py -d
```

Open http://localhost:8081 and verify the job shows as **RUNNING**.

### 4. Start the message generator

```bash
cd generator
python generator.py --sessions 10 --mitm-pct 10 --delay 0.3 0.6
```

| Option          | Description                                    | Default   |
|-----------------|------------------------------------------------|-----------|
| `--sessions N`  | Number of concurrent active chat sessions      | 10        |
| `--mitm-pct P`  | Percentage of sessions intercepted by a hacker | 5         |
| `--delay MIN MAX` | Min/max seconds between messages             | 0.5 1.0   |

Runs continuously until `Ctrl+C`.

### 5. Verify results

```bash
./scripts/verify.sh
```

Or query Postgres directly:

```bash
docker exec postgres psql -U hackathon -d streaming -c "SELECT COUNT(*) FROM messages;"
docker exec postgres psql -U hackathon -d streaming -c "SELECT COUNT(*) FROM alerts;"
```

You can also inspect the `alerts` topic in Kafka UI at http://localhost:8080.

## Flink Job Logic

The Flink job (`flink_job/job.py`) is a PyFlink SQL streaming pipeline:

1. **Source**: reads JSON messages from Kafka `messages` topic (earliest offset)
2. **Enrichment**: computes the expected quantum state for each message via a UDF (SHA256-based deterministic function), then calculates the deviation percentage between actual and expected state
3. **Detection**: messages with deviation > 15% are flagged as tampered
4. **Hacker identification**: for tampered messages, a UDF brute-force matches the observed perturbation against all 250 known hacker signatures to identify the attacker
5. **Fan-out** via `StatementSet` — three simultaneous sinks:
   - All messages → PostgreSQL `messages` table (with `is_tampered` flag)
   - Tampered messages → PostgreSQL `alerts` table (with hacker ID, deviation)
   - Tampered messages → Kafka `alerts` topic (for downstream consumers)

## Extension Points

### Replacing the quantum function

The quantum logic lives in two places (both must be updated):

- **`generator/quantum.py`** — used by the Python message generator
- **`flink_job/job.py`** (inline UDFs) — used by the Flink job. These are intentionally duplicated because Flink UDFs must be self-contained for serialization.

Keep the function signatures the same. After changes, re-submit the Flink job and restart the generator.

### Changing the detection threshold

Search for `0.15` in `flink_job/job.py` (the `WHERE deviation_pct > 0.15` clauses). The generator's `NORMAL_NOISE_MAX` in `generator/generator.py` must stay below whatever new threshold you set.

### Adding new sinks

In `flink_job/job.py`:
1. Add a new `CREATE TABLE` with the appropriate Flink connector
2. Add another `stmt_set.add_insert_sql(...)` with a SELECT from `enriched_messages`

## Re-submitting Flink Jobs

### Via Flink Web UI

1. Open http://localhost:8081
2. Click on the running job → **Cancel Job**
3. Re-submit:

```bash
docker exec jobmanager flink run -py /opt/flink/usrlib/job.py -d
```

### Via CLI

```bash
# List running jobs
docker exec jobmanager flink list

# Cancel a job
docker exec jobmanager flink cancel <JOB_ID>

# Re-submit
docker exec jobmanager flink run -py /opt/flink/usrlib/job.py -d
```

**Note on state**: this demo does not use savepoints or checkpoints. The Kafka consumer is configured with `earliest-offset`, so re-submitting will reprocess all messages from the beginning. To process only new messages, change `scan.startup.mode` to `latest-offset` in `job.py`.

## Cleanup

**Stop containers, keep data** (Postgres data and Kafka logs persist for next start):

```bash
docker compose down
```

**Stop containers and remove all data**:

```bash
docker compose down -v
```

**Remove everything** (containers, volumes, and locally built images):

```bash
docker compose down -v --rmi local
```

**Remove Python virtual environment**:

```bash
rm -rf .venv
```

## Data Files

User and hacker data is pre-generated and deterministic:

- `data/users.json` — 500 users with fixed IDs and names
- `data/hackers.json` — 250 hackers with fixed IDs and signature seeds

To regenerate (produces identical output):

```bash
python generator/generate_data.py
```
