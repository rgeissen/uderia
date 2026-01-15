-- ============================================================================
-- Uderia Prompt Management System - Global Settings
-- ============================================================================
-- Description: Schema for global settings with admin locks (three-tier configuration)
-- Version: 1.1
-- Created: 2026-01-15
-- Updated: 2026-01-15 - Added knowledge settings
-- Note: Enables three-tier configuration: Global defaults -> Profile overrides -> Admin locks
-- ============================================================================

-- ============================================================================
-- Global Settings Table
-- ============================================================================
-- Purpose: Store system-wide default settings for various features
-- Each setting can be:
--   - Overridden at profile level (if is_locked = FALSE)
--   - Enforced globally (if is_locked = TRUE)
--
-- Setting key prefixes:
--   - temperature, queryTimeout, maxIterations: Genie coordination
--   - knowledge_*: Knowledge repository settings
-- ============================================================================

CREATE TABLE IF NOT EXISTS genie_global_settings (
    id INTEGER PRIMARY KEY,
    setting_key TEXT NOT NULL UNIQUE,       -- Setting identifier (temperature, knowledge_minRelevance, etc.)
    setting_value TEXT NOT NULL,            -- Value stored as string (parse by type)
    is_locked BOOLEAN DEFAULT FALSE,        -- If TRUE, profile overrides are disabled
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT                          -- User UUID who last updated (admin)
);

-- Default values for Genie settings
INSERT OR IGNORE INTO genie_global_settings (setting_key, setting_value, is_locked) VALUES
    ('temperature', '0.7', 0),
    ('queryTimeout', '300', 0),
    ('maxIterations', '10', 0);

-- Default values for Knowledge settings
INSERT OR IGNORE INTO genie_global_settings (setting_key, setting_value, is_locked) VALUES
    ('knowledge_minRelevanceScore', '0.30', 0),
    ('knowledge_maxDocs', '3', 0),
    ('knowledge_maxTokens', '2000', 0),
    ('knowledge_rerankingEnabled', '0', 0);

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_genie_settings_key
ON genie_global_settings(setting_key);
