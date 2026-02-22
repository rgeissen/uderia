-- ============================================================
-- Schema: Skill Settings
-- Version: 1.0
-- Description: Admin-controlled skill governance settings.
--              Key-value pattern matching extension_settings.
--              Controls built-in skill availability,
--              custom skill creation, and auto-skill selection.
-- ============================================================

-- Skill governance settings (admin-controlled)
CREATE TABLE IF NOT EXISTS skill_settings (
    id INTEGER PRIMARY KEY,
    setting_key TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Default values
INSERT OR IGNORE INTO skill_settings (setting_key, setting_value) VALUES
    ('skills_mode', 'all'),                      -- 'all' | 'selective'
    ('disabled_skills', '[]'),                   -- JSON array of skill_ids
    ('user_skills_enabled', 'true'),             -- 'true' | 'false'
    ('auto_skills_enabled', 'false');            -- 'true' | 'false' (Phase 2)

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_skill_settings_key
    ON skill_settings(setting_key);
