-- ============================================================
-- Schema: Skills
-- Version: 1.0
-- Description: Per-user skill activation with configuration
--              parameters. Each activation has a unique
--              activation_name (what the user types as !name)
--              mapped to a skill_id (which skill content to load).
-- ============================================================

-- Per-user skill activations
CREATE TABLE IF NOT EXISTS user_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_uuid VARCHAR(36) NOT NULL,
    skill_id VARCHAR(100) NOT NULL,              -- Base skill (sql-expert, concise, etc.)
    activation_name VARCHAR(100) NOT NULL,       -- User-facing name (!sql-expert, !sql2)
    is_active BOOLEAN NOT NULL DEFAULT 1,
    default_param VARCHAR(255),                  -- Default parameter value (e.g., "strict")
    config_json TEXT,                             -- JSON object for advanced configuration
    activated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_uuid) REFERENCES users(id),
    UNIQUE(user_uuid, activation_name)           -- Unique name per user
);

-- Index for fast lookup of user's active skills
CREATE INDEX IF NOT EXISTS idx_user_skills_user
    ON user_skills(user_uuid, is_active);

-- Index for fast lookup by activation name
CREATE INDEX IF NOT EXISTS idx_user_skills_name
    ON user_skills(user_uuid, activation_name);
