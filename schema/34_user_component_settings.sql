-- Per-user component access overrides
-- Admin can explicitly block or grant access to specific components for individual users,
-- independent of global component settings and per-profile componentConfig.
-- Governance chain: global disable_list → user override → profile componentConfig

CREATE TABLE IF NOT EXISTS user_component_settings (
    id          INTEGER PRIMARY KEY,
    user_uuid   TEXT NOT NULL,
    component_id TEXT NOT NULL,
    is_enabled  INTEGER NOT NULL DEFAULT 1,   -- 1 = granted, 0 = blocked
    note        TEXT,                          -- optional admin note
    updated_at  TEXT DEFAULT (datetime('now')),
    updated_by  TEXT,                          -- admin user UUID
    UNIQUE(user_uuid, component_id)
);

CREATE INDEX IF NOT EXISTS idx_ucs_user_uuid     ON user_component_settings(user_uuid);
CREATE INDEX IF NOT EXISTS idx_ucs_component_id  ON user_component_settings(component_id);
