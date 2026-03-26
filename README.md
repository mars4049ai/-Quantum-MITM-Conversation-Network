# Quantum MITM Detection

Real-time man-in-the-middle attack detection on encrypted communication sessions
using BB84 quantum key distribution, Apache Kafka, Apache Flink, PostgreSQL, and
Apache Superset.

> **Note:** Message generation does **not** use AI. All chat messages are taken
> from a pre-built list in `data/messages.json` (5 topics, ~38 messages each).
> To customise the conversations, edit that file — no code changes needed.

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
| **Channel restart** | Whenever QBER ≥ 15 %, the session re-tries until QBER drops below threshold. |
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
# Qiskit: seed_simulator = seed_int + qubit_index        (Alice/Eve)
#         seed_simulator = seed_int + qubit_index + 100  (Bob)
```

---

## Full Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Quantum MITM Detection                            │
└──────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────┐
  │       Python Generator       │
  │  • Qiskit BB84 (Qsim.py)     │
  │  • Messages from             │  ──── Kafka: messages ────▶  ┌──────────┐
  │    data/messages.json        │                              │  Flink   │
  │  • 500 users, 250 hackers    │  ◀─── Kafka: alerts ──────   │(PyFlink) │
  │  • Encrypts with BB84 key    │                              └────┬─────┘
  └──────────────────────────────┘                                  │ JDBC
                                                        ┌───────────▼──────────┐
                                                        │      PostgreSQL       │
                                                        │  • messages          │
                                                        │  • alerts            │
                                                        │  • hackers           │
                                                        │  • session_topics    │
                                                        │  • hacker_decryption │
                                                        │    _attempts         │
                                                        └───────────┬──────────┘
                                                                    │
                                                        ┌───────────▼──────────┐
                                                        │   Apache Superset    │
                                                        │   :8088              │
                                                        │  Communication Graph │
                                                        │  (green/red/grey)    │
                                                        │  Top 10 Hackers      │
                                                        │  Most Attacked       │
                                                        │  Decryption Attempts │
                                                        └──────────────────────┘

  Service URLs
  ─────────────────────────────────────────────────────────
  Superset          http://localhost:8088  (admin / postgres123)
  Flink Dashboard   http://localhost:8081
  Kafka UI          http://localhost:8080
```

---

## Prerequisites

- Docker and Docker Compose
- Python 3.11+

---

## Quick Start

### 1. Start all infrastructure

```bash
docker compose up -d --build
```

Wait **60–120 seconds** for all services to initialise. Superset runs
`db upgrade → create-admin → init` automatically on first boot.

| Service | URL | Credentials |
|---|---|---|
| Superset | http://localhost:8088 | admin / postgres123 |
| Flink Dashboard | http://localhost:8081 | — |
| Kafka UI | http://localhost:8080 | — |

### 2. Set up the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r generator/requirements.txt
```

### 3. Submit the Flink streaming job

```bash
docker exec jobmanager flink run -py /opt/flink/usrlib/job.py -d
```

Open http://localhost:8081 and verify the job shows **RUNNING**.

### 4. Start the message generator

```bash
cd generator
python generator.py --sessions 10 --mitm-pct 10 --delay 0.3 0.6
```

| Option | Description | Default |
|---|---|---|
| `--sessions N` | Max concurrent active chat sessions | 10 |
| `--mitm-pct P` | Percentage of sessions intercepted by a hacker | 5 |
| `--delay MIN MAX` | Seconds between messages | 0.5 1.0 |

Console output per session:
- `[clean]` — BB84 established, no interception
- `[MITM by <hacker> from msg #N]` — hacker active mid-session
- `BB84 FAILED (channel broken…)` — hacker blocked key exchange entirely

Press **Ctrl+C** to stop.

### 5. View results in Superset

Open http://localhost:8088 → log in → **Quantum MITM Dashboard**

| Panel | Description |
|---|---|
| **Communication Graph** | Client pairs; edge colour: 🟢 protected / 🔴 attacked / ⚫ broken |
| **Top 10 Hackers** | Bar chart ranked by attack count |
| **Most Attacked Clients** | Bar chart ranked by sessions attacked |
| **Attack Timeline** | Line chart of alerts per minute |
| **Big Numbers** | Total messages / attacks / detection rate % |
| **Session Topics** | Topics from `data/messages.json` |
| **Hacker Decryption Attempts** | QBER, wrong key, garbage output |
| **Full Tables** | Raw messages, alerts, hackers |

### 6. Verify via PostgreSQL

```bash
docker exec postgres psql -U hackathon -d streaming -c \
  "SELECT channel_status, COUNT(*) FROM session_topics GROUP BY 1;"

docker exec postgres psql -U hackathon -d streaming -c \
  "SELECT hacker_id, ROUND(hacker_qber::numeric,1) AS qber_pct,
          LEFT(decrypted_garbage,40) AS garbage
   FROM hacker_decryption_attempts LIMIT 5;"
```

---

## Superset Manual Setup (if auto-init fails)

If the Superset container starts but the dashboard is missing, run these
commands manually (Linux/Mac use `sudo` if needed):

```bash
# Windows (PowerShell / cmd — no sudo)
docker exec -it superset superset fab create-admin ^
    --username admin ^
    --firstname Superset ^
    --lastname Admin ^
    --email admin@admin.com ^
    --password postgres123

docker exec -it superset superset db upgrade
docker exec -it superset superset init

# Linux / Mac
docker exec -it superset superset fab create-admin \
    --username admin \
    --firstname Superset \
    --lastname Admin \
    --email admin@admin.com \
    --password postgres123
docker exec -it superset superset db upgrade
docker exec -it superset superset init
```

Then re-run the dashboard init script inside the container:

```bash
docker exec -it superset python /app/init_dashboards.py
```

---

## Message Customisation

Chat messages come from **`data/messages.json`** — no AI, no API key required.

The file contains 5 topics, each with ~38 pre-written messages:

| Topic | Description |
|---|---|
| `weekend plans` | Hiking, meeting up, leisure |
| `work project` | Reports, meetings, deadlines |
| `food recommendations` | Restaurants, dishes, reservations |
| `tech news` | Chips, OS updates, gadgets |
| `sports update` | Match results, predictions |

To add a topic or change messages, edit `data/messages.json` and restart the generator.

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
2. **Enrichment**: `compute_expected_state` UDF — seeded Qiskit BB84 (8 qubits, no Eve)
3. **Detection**: `deviation_pct > 0.15` → tampered
4. **Identification**: `identify_hacker` UDF — 250-hacker brute-force, 4-qubit BB84 each
5. **Hacker attempt**: `hacker_qber_udf`, `hacker_key_udf`, `hacker_garbage_udf`
6. **Fan-out** (4 sinks): PostgreSQL `messages`, `alerts`, `hacker_decryption_attempts`, Kafka `alerts`

---

## Re-submitting the Flink Job

```bash
docker exec jobmanager flink list
docker exec jobmanager flink cancel <JOB_ID>
docker exec jobmanager flink run -py /opt/flink/usrlib/job.py -d
```

`scan.startup.mode = earliest-offset` — re-submission reprocesses all Kafka
messages from the start. Change to `latest-offset` for incremental-only.

---

## Cleanup

```bash
docker compose down          # stop, keep data
docker compose down -v       # stop + delete all data
docker compose down -v --rmi local   # delete everything including images
rm -rf .venv
```

---

## Data Files

| File | Description |
|---|---|
| `data/users.json` | 500 pre-generated users (fixed seed) |
| `data/hackers.json` | 250 hackers with signature seeds |
| `data/messages.json` | Pre-built chat messages by topic — **edit to customise** |

To regenerate users/hackers:

```bash
python generator/generate_data.py
```
