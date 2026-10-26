PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id        INTEGER UNIQUE NOT NULL,
    username                TEXT,
    first_name              TEXT,
    created_at              TEXT NOT NULL,
    last_seen_at            TEXT NOT NULL,
    credits                 INTEGER NOT NULL DEFAULT 0,
    subscription_expire_at  TEXT,
    is_blocked              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_users_tid ON users(telegram_user_id);

CREATE TABLE IF NOT EXISTS plans (
    plan_code     TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    price_toman   INTEGER NOT NULL,
    credits       INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id             TEXT UNIQUE NOT NULL,
    telegram_user_id     INTEGER NOT NULL,
    plan_code            TEXT NOT NULL,
    amount_toman         INTEGER NOT NULL,
    status               TEXT NOT NULL DEFAULT 'awaiting_payment',
    evidence_type        TEXT NOT NULL DEFAULT 'none',
    evidence_file_id     TEXT,
    evidence_text        TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    reviewed_by_admin_id INTEGER,
    reviewed_at          TEXT,
    admin_note           TEXT,
    FOREIGN KEY (plan_code) REFERENCES plans(plan_code)
);
CREATE INDEX IF NOT EXISTS idx_orders_tid    ON orders(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS jobs (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id          INTEGER NOT NULL,
    target_instagram_username TEXT NOT NULL,
    created_at                TEXT NOT NULL,
    status                    TEXT NOT NULL DEFAULT 'running',
    credits_charged           INTEGER NOT NULL DEFAULT 0,
    result_summary            TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_tid ON jobs(telegram_user_id);

CREATE TABLE IF NOT EXISTS job_sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL,
    title         TEXT,
    link          TEXT,
    snippet       TEXT,
    rank          INTEGER,
    query_pattern TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Reservations track credit origin so refunds cannot cross products or repeat.
CREATE TABLE IF NOT EXISTS search_charges (
    id TEXT PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    service TEXT NOT NULL CHECK (service IN ('email', 'instagram')),
    balance_column TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'reserved',
    created_at TEXT NOT NULL,
    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_search_charge_running
ON search_charges(telegram_user_id, service) WHERE status='reserved';
