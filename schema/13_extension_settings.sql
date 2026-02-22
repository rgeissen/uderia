-- ============================================================
-- Schema: Extension Settings
-- Version: 1.0
-- Description: Admin-controlled extension governance settings.
--              Key-value pattern matching genie_global_settings.
--              Controls built-in extension availability,
--              custom extension creation, and marketplace access.
-- ============================================================

-- Extension governance settings (admin-controlled)
CREATE TABLE IF NOT EXISTS extension_settings (
    id INTEGER PRIMARY KEY,
    setting_key TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT  -- admin user UUID
);

-- Default values
INSERT OR IGNORE INTO extension_settings (setting_key, setting_value) VALUES
    ('extensions_mode', 'all'),                       -- 'all' | 'selective'
    ('disabled_extensions', '[]'),                    -- JSON array of extension_ids
    ('user_extensions_enabled', 'true'),              -- 'true' | 'false'
    ('user_extensions_marketplace_enabled', 'true');  -- 'true' | 'false'

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_extension_settings_key
    ON extension_settings(setting_key);
