-- ============================================================
-- Schema: Component Settings
-- Version: 1.0
-- Description: Admin-controlled component governance settings.
--              Key-value pattern matching extension_settings.
--              Controls built-in component availability,
--              custom component imports, and marketplace access.
-- ============================================================

-- Component governance settings (admin-controlled)
CREATE TABLE IF NOT EXISTS component_settings (
    id INTEGER PRIMARY KEY,
    setting_key TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT  -- admin user UUID
);

-- Default values
INSERT OR IGNORE INTO component_settings (setting_key, setting_value) VALUES
    ('components_mode', 'all'),                       -- 'all' | 'selective'
    ('disabled_components', '[]'),                     -- JSON array of component_ids
    ('user_components_enabled', 'true'),               -- 'true' | 'false'
    ('user_components_marketplace_enabled', 'true');   -- 'true' | 'false'

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_component_settings_key
    ON component_settings(setting_key);
