CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    message_id      VARCHAR(64) NOT NULL,
    session_id      VARCHAR(64) NOT NULL,
    sender_id       INTEGER NOT NULL,
    sender_name     VARCHAR(128) NOT NULL,
    receiver_id     INTEGER NOT NULL,
    receiver_name   VARCHAR(128) NOT NULL,
    sequence_num    INTEGER NOT NULL,
    content         TEXT,
    quantum_state   DOUBLE PRECISION NOT NULL,
    is_tampered     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
    id              BIGSERIAL PRIMARY KEY,
    message_id      VARCHAR(64) NOT NULL,
    session_id      VARCHAR(64) NOT NULL,
    sender_id       INTEGER NOT NULL,
    sequence_num    INTEGER NOT NULL,
    hacker_id       INTEGER NOT NULL,
    expected_state  DOUBLE PRECISION NOT NULL,
    actual_state    DOUBLE PRECISION NOT NULL,
    deviation_pct   DOUBLE PRECISION NOT NULL,
    detected_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hackers (
    id              INTEGER PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    signature_seed  VARCHAR(64) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_alerts_session ON alerts(session_id);
CREATE INDEX IF NOT EXISTS idx_alerts_hacker ON alerts(hacker_id);
