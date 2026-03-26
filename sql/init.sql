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

-- Session topics: what clients are discussing, plus BB84 channel status
CREATE TABLE IF NOT EXISTS session_topics (
    id              BIGSERIAL PRIMARY KEY,
    session_id      VARCHAR(64)  NOT NULL UNIQUE,
    sender_name     VARCHAR(128) NOT NULL,
    receiver_name   VARCHAR(128) NOT NULL,
    topic           VARCHAR(256) NOT NULL,
    message_count   INTEGER      NOT NULL DEFAULT 0,
    channel_status  VARCHAR(16)  NOT NULL DEFAULT 'secure', -- 'secure' | 'broken'
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_session_topics_session ON session_topics(session_id);

-- Hacker decryption attempts: what each hacker computed and got when trying to read
-- intercepted messages with their wrong BB84 key.  success is always FALSE.
CREATE TABLE IF NOT EXISTS hacker_decryption_attempts (
    id                BIGSERIAL PRIMARY KEY,
    message_id        VARCHAR(64)  NOT NULL,
    session_id        VARCHAR(64)  NOT NULL,
    sequence_num      INTEGER      NOT NULL,
    hacker_id         INTEGER      NOT NULL,
    hacker_qber       DOUBLE PRECISION NOT NULL, -- QBER (%) from hacker's BB84 run
    attempted_key     TEXT         NOT NULL,     -- hacker's derived key (bit string)
    decrypted_garbage TEXT         NOT NULL,     -- result of decrypting with wrong key
    noise_level       DOUBLE PRECISION NOT NULL, -- deviation_pct that triggered alert
    success           BOOLEAN      DEFAULT FALSE,
    created_at        TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hacker_attempts_session ON hacker_decryption_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_hacker_attempts_hacker  ON hacker_decryption_attempts(hacker_id);
