-- ============================================================
-- Schema: Extensions
-- Version: 1.1
-- Description: Per-user extension activation with configuration
--              parameters. Supports multiple activations of the
--              same extension with different default parameters.
--              Each activation has a unique activation_name that
--              the user types in the query box (#name).
-- ============================================================

-- Per-user extension activations
CREATE TABLE IF NOT EXISTS user_extensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_uuid VARCHAR(36) NOT NULL,
    extension_id VARCHAR(100) NOT NULL,        -- Base extension (json, decision, etc.)
    activation_name VARCHAR(100) NOT NULL,     -- User-facing name (#json, #json2, #json3)
    is_active BOOLEAN NOT NULL DEFAULT 1,
    default_param VARCHAR(255),                -- Default parameter value (e.g., "critical" for #decision:critical)
    config_json TEXT,                           -- JSON object for advanced configuration
    activated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_uuid) REFERENCES users(id),
    UNIQUE(user_uuid, activation_name)         -- Unique name per user (allows multiple activations of same extension)
);

-- Index for fast lookup of user's active extensions
CREATE INDEX IF NOT EXISTS idx_user_extensions_user
    ON user_extensions(user_uuid, is_active);

-- Index for fast lookup by activation name
CREATE INDEX IF NOT EXISTS idx_user_extensions_name
    ON user_extensions(user_uuid, activation_name);
