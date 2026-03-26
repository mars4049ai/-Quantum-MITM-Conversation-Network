# Quantum MITM Detection

Real-time man-in-the-middle attack detection on encrypted communication sessions
using BB84 quantum key distribution, Apache Kafka, Apache Flink, PostgreSQL, and
Apache Superset.

---

## Quantum Architecture

The project implements the **BB84 quantum key distribution protocol** from
[Qsim.py](Qsim.py) to protect every chat session:

```
Alice                       Eve (hacker)               Bob
  │                              │                       │
  │──── Qiskit BB84 exchange ────│───────────────────────│
  │     (16 qubits, Aer sim)     │ intercepts → QBER↑    │
  │                              │                       │
  │  QBER < 15% → secure key ────────────────────────────│
  │  QBER ≥ 15% → restart ───────────────────────────────│
  │               (find_secure_channel loop)             │
  │                                                      │
  │──── encrypt_message(text, shared_key) ───────────────│
  │           XOR + SHA256(key)                          │
  │                                                      │
  │  Eve tries decrypt(ciphertext, wrong_key) → garbage  │
```

### BB84 in This Project

| Stage | What Happens |
|---|---|
| **Session start** | Alice & Bob run `Qsim.find_secure_channel(qber_threshold=15)`. Qiskit Aer simulates qubit transmission. |
| **Eve active** | Eve measures qubits → introduces ~25 % QBER. Alice & Bob detect the mismatch. |
| **Channel restart** | Whenever QBER ≥ 15 %, the session re-tries a new frequency until QBER drops below threshold. |
| **Broken channel** | If BB84 cannot converge in 10 attempts, the session is marked `broken` and aborted. |
| **Per-message state** | Each message carries a `quantum_state` float derived from a seeded mini-BB84 (8 qubits, no Eve). |
| **Flink detection** | Flink recomputes the same quantum state independently; deviation > 15 % triggers an alert. |
| **Hacker identification** | Flink brute-forces 250 hacker signatures (seeded BB84 with Eve, 4 qubits each) to find the best match. |
| **Decryption attempt** | Flink simulates the hacker decrypting with their wrong BB84 key → stores the garbage output. |

### Determinism Guarantee

Both the generator and Flink UDFs use identical seeding:

```python
seed_int = int(SHA256(f"{session_id}:{seq_num}")[:8], 16) % 2**31
np.random.seed(seed_int);  random.seed(seed_int)
# Qiskit: seed_simulator = seed_int + qubit_index (Alice/Eve)
#         seed_simulator = seed_int + qubit_index + 100 (Bob)
```

This ensures `compute_quantum_state(sid, seq)` returns byte-identical values
in the Python generator process and inside Flink TaskManagers.

---

## Full Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Quantum MITM Detection                            │
└──────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────┐
  │     Python Generator     │
  │  • Qiskit BB84 (Qsim.py) │
  │  • Claude Haiku messages │  ──── Kafka: messages ────▶  ┌────────────┐
  │  • 500 users, 250 hackers│                              │   Flink    │
  │  • Encrypts with BB84 key│  ◀─── Kafka: alerts ──────   │ (PyFlink)  │
  └──────────────────────────┘                              └─────┬──────┘
                                                                  │ JDBC
                                                      ┌───────────▼────────────┐
                                                      │       PostgreSQL        │
                                                      │  • messages             │
                                                      │  • alerts               │
                                                      │  • hackers              │
                                                      │  • session_topics       │
                                                      │  • hacker_decryption_   │
                                                      │    attempts             │
                                                      └───────────┬────────────┘
                                                                  │
                                                      ┌───────────▼────────────┐
                                                      │   Apache Superset      │
                                                      │   :8088                │
                                                      │                        │
                                                      │  Communication Graph   │
                                                      │  (green/red/grey edges)│
                                                      │  Top 10 Hackers        │
                                                      │  Most Attacked Clients │
                                                      │  Decryption Attempts   │
                                                      │  Session Topics        │
                                                      └────────────────────────┘

  Service URLs
  ─────────────────────────────────────────────────
  Flink Dashboard   http://localhost:8081
  Kafka UI          http://localhost:8080
  Superset          http://localhost:8088  (admin / admin)
```

---

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- *(Optional)* `ANTHROPIC_API_KEY` for AI-generated chat messages

---

## Quick Start

### 1. Start all infrastructure

```bash
docker compose up -d --build
```

Wait **60–120 seconds** for Kafka, Postgres, Flink, and Superset to initialise
(Superset runs its own `superset db upgrade` + `superset init` on first boot).

| Service | URL | Credentials |
|---|---|---|
| Superset | http://localhost:8088 | admin / admin |
| Flink Dashboard | http://localhost:8081 | — |
| Kafka UI | http://localhost:8080 | — |

### 2. Set up the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r generator/requirements.txt
```

### 3. *(Optional)* Enable AI-generated messages

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Without this variable the generator falls back to built-in message templates.

### 4. Submit the Flink streaming job

```bash
docker exec jobmanager flink run -py /opt/flink/usrlib/job.py -d
```

Open http://localhost:8081 and verify the job status shows **RUNNING**.

### 5. Start the message generator

```bash
cd generator
python generator.py --sessions 10 --mitm-pct 10 --delay 0.3 0.6
```

| Option | Description | Default |
|---|---|---|
| `--sessions N` | Max concurrent active chat sessions | 10 |
| `--mitm-pct P` | Percentage of sessions intercepted | 5 |
| `--delay MIN MAX` | Seconds between messages | 0.5 1.0 |

The generator prints per-session status:
- `[clean]` — BB84 established, no interception
- `[MITM by <hacker> from msg #N]` — hacker active mid-session
- `BB84 FAILED (channel broken…)` — hacker blocked key exchange entirely

Press **Ctrl+C** to stop.

### 6. View results in Superset

Open http://localhost:8088 → **Quantum MITM Dashboard**

The dashboard auto-refreshes and shows:

| Panel | Description |
|---|---|
| **Communication Graph** | Network of client pairs; edge colour: 🟢 protected / 🔴 attacked / ⚫ broken |
| **Top 10 Hackers** | Bar chart ranked by attack count |
| **Most Attacked Clients** | Bar chart ranked by sessions attacked |
| **Attack Timeline** | Line chart of alerts per minute |
| **Big Numbers** | Total messages, total attacks, detection rate % |
| **Session Topics** | What clients were discussing (AI-generated or template) |
| **Hacker Decryption Attempts** | QBER, wrong key, garbage output — demonstrates quantum security |
| **Full Tables** | All messages, alerts, hackers |

### 7. Verify via CLI

```bash
./scripts/verify.sh
```

Or query PostgreSQL directly:

```bash
docker exec postgres psql -U hackathon -d streaming -c \
  "SELECT channel_status, COUNT(*) FROM session_topics GROUP BY 1;"

docker exec postgres psql -U hackathon -d streaming -c \
  "SELECT hacker_id, ROUND(hacker_qber::numeric,1) AS qber_pct,
          LEFT(decrypted_garbage,40) AS garbage
   FROM hacker_decryption_attempts LIMIT 5;"
```

---

## SQL Tables

| Table | Description |
|---|---|
| `messages` | Every message with `quantum_state` and `is_tampered` flag. Content is BB84-encrypted (base64). |
| `alerts` | Tampered messages: hacker ID, expected/actual state, deviation %. |
| `hackers` | Registry of 250 hackers with deterministic signature seeds. |
| `session_topics` | Per-session topic label, participant names, and BB84 `channel_status` (`secure` / `broken`). |
| `hacker_decryption_attempts` | Per-tampered-message record: QBER, hacker's derived key, garbage decryption result, noise level. |

---

## Flink Job Logic

`flink_job/job.py` — PyFlink SQL streaming pipeline:

1. **Source**: reads JSON from Kafka `messages` topic (earliest offset)
2. **Enrichment**: runs `compute_expected_state` UDF (seeded Qiskit BB84, 8 qubits, no Eve), computes `deviation_pct`
3. **Detection**: `deviation_pct > 0.15` → tampered
4. **Identification**: `identify_hacker` UDF — 250-hacker brute-force, each 4-qubit BB84 with Eve
5. **Hacker attempt**: three UDFs reconstruct the hacker's QBER, wrong key, and garbage decryption
6. **Fan-out** (4 simultaneous sinks):
   - All messages → PostgreSQL `messages`
   - Tampered → PostgreSQL `alerts`
   - Tampered → PostgreSQL `hacker_decryption_attempts`
   - Tampered → Kafka `alerts` topic

---

## Superset Dashboard — Algorithm

The `superset/init_dashboards.py` script programmatically creates everything
via the Superset REST API:

```
1. POST /api/v1/security/login          → access_token + CSRF token
2. POST /api/v1/database/               → PostgreSQL connection
3. POST /api/v1/dataset/  × 10          → 5 physical + 5 virtual datasets
4. POST /api/v1/chart/    × 13          → all charts
5. POST /api/v1/dashboard/              → main dashboard
6. PUT  /api/v1/dashboard/{id}          → attach charts + layout
```

Virtual datasets are SQL queries exposing pre-aggregated views:

```sql
-- Communication graph with channel status (drives edge colour)
SELECT st.sender_name AS source, st.receiver_name AS target,
       st.message_count AS value,
       CASE
           WHEN st.channel_status = 'broken' THEN 'broken'
           WHEN EXISTS (SELECT 1 FROM alerts a
                        WHERE a.session_id = st.session_id) THEN 'attacked'
           ELSE 'protected'
       END AS channel_status
FROM session_topics st;
```

Edge colours in the graph chart:
- `protected` → **#00CC66** (green)
- `attacked`  → **#FF3300** (red/orange)
- `broken`    → **#999999** (grey)

---

## Extension Points

### Changing the detection threshold

Search for `0.15` in `flink_job/job.py`. The generator's `NORMAL_NOISE_MAX`
(currently `0.10`) must always stay below the threshold you set.

Also update `BB84_QBER_THRESHOLD` in `generator/generator.py` to match.

### Replacing the quantum function

Quantum logic lives in two places (both must be updated together):

- `generator/quantum.py` — used by the Python generator
- `flink_job/job.py` (inline UDFs) — used by Flink (must be self-contained)

Keep the seeding contract identical in both files.

### Adding new sinks

In `flink_job/job.py`, add a `CREATE TABLE` with the appropriate connector
and a new `stmt_set.add_insert_sql(...)`.

---

## Re-submitting the Flink Job

```bash
# Cancel running job
docker exec jobmanager flink list
docker exec jobmanager flink cancel <JOB_ID>

# Re-submit
docker exec jobmanager flink run -py /opt/flink/usrlib/job.py -d
```

**Note:** `scan.startup.mode = earliest-offset` means re-submission reprocesses
all Kafka messages from the beginning.  Change to `latest-offset` for
incremental-only processing.

---

## Cleanup

```bash
# Stop containers, keep data
docker compose down

# Stop and remove all data
docker compose down -v

# Remove everything including images
docker compose down -v --rmi local

# Remove Python environment
rm -rf .venv
```

---

## Data Files

Pre-generated, deterministic (fixed seed 42):

- `data/users.json` — 500 users
- `data/hackers.json` — 250 hackers with signature seeds

To regenerate (produces identical output):

```bash
python generator/generate_data.py
```
