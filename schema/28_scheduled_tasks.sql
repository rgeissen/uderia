-- Autonomous Scheduling (Track B)
-- Transforms Uderia from a reactive assistant into an always-on agent.
-- Scheduled tasks run through the identical execute_query() pipeline as
-- user-submitted queries; the only additions are persistence, delivery channels,
-- and concurrency governance.

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id               TEXT PRIMARY KEY,
    user_uuid        TEXT NOT NULL,
    profile_id       TEXT NOT NULL,
    name             TEXT NOT NULL,
    prompt           TEXT NOT NULL,
    schedule         TEXT NOT NULL,           -- cron expression (e.g. "0 9 * * 1-5") or "interval:Ns"
    enabled          INTEGER DEFAULT 1,
    session_id       TEXT,                    -- pinned session to reuse; NULL = create fresh each run
    last_run_at      TEXT,
    last_run_status  TEXT,                    -- success | error | timeout | skipped
    next_run_at      TEXT,
    output_channel   TEXT,                    -- null | email | webhook | google_mail
    output_config    TEXT,                    -- JSON: to_address, webhook_url, bearer_token, etc.
    max_tokens_per_run INTEGER,               -- NULL = no limit; enforced per execution
    overlap_policy   TEXT DEFAULT 'skip',     -- skip | queue | allow
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scheduled_task_runs (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
    bg_task_id      TEXT,                     -- background_tasks task_id for live status
    started_at      TEXT,
    completed_at    TEXT,
    status          TEXT,                     -- success | error | timeout | skipped
    skip_reason     TEXT,                     -- populated when status = skipped
    result_summary  TEXT,                     -- brief text extracted from final answer
    tokens_used     INTEGER,
    cost_usd        REAL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_task_id ON scheduled_task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user_uuid   ON scheduled_tasks(user_uuid);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_enabled     ON scheduled_tasks(enabled);

-- Messaging identities for per-user OAuth connectors (Google Mail, etc.)
-- Populated by Track C; referenced by scheduled task delivery when output_channel = 'google_mail'
CREATE TABLE IF NOT EXISTS messaging_identities (
    user_uuid        TEXT NOT NULL,
    platform         TEXT NOT NULL,           -- 'google' (others deferred)
    platform_user_id TEXT NOT NULL,           -- e.g. user@gmail.com
    access_token     TEXT,                    -- Fernet-encrypted
    refresh_token    TEXT,                    -- Fernet-encrypted
    token_expiry     TEXT,
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_uuid, platform)
);
