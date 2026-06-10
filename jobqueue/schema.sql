CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    phone TEXT NOT NULL,
    body TEXT NOT NULL,
    received_at TEXT NOT NULL,
    enqueued_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER DEFAULT 0,
    last_attempt_at TEXT,
    fail_reason TEXT,
    reply_sent TEXT,
    sim_used INTEGER,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_message_id ON jobs(message_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_phone ON jobs(phone);

CREATE TABLE IF NOT EXISTS dedup_hashes (
    hash TEXT PRIMARY KEY,
    phone TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
