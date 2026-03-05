-- ============================================================
-- Vector Store Governance Settings
-- Description: Admin-controlled vector store backend availability
--              per user tier. Controls which backends users can
--              select when creating knowledge repositories.
--              Planner repositories are unaffected.
-- ============================================================

CREATE TABLE IF NOT EXISTS vectorstore_settings (
    id INTEGER PRIMARY KEY,
    setting_key TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT  -- admin user UUID who last changed this setting
);

-- Default: all backends allowed for all tiers.
-- Admin tier always has full access (enforced in code, not stored here).
INSERT OR IGNORE INTO vectorstore_settings (setting_key, setting_value) VALUES
    ('allowed_backends_user', '["chromadb","teradata","qdrant"]'),
    ('allowed_backends_developer', '["chromadb","teradata","qdrant"]');

CREATE INDEX IF NOT EXISTS idx_vectorstore_settings_key
    ON vectorstore_settings(setting_key);
