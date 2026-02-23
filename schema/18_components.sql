-- ============================================================
-- Schema: Components
-- Version: 1.1
-- Description: Generative UI Component system tables.
--              Tracks installed components for admin visibility.
--              Per-profile component config lives on the profile
--              JSON dict (componentConfig key), not in a DB table.
-- ============================================================

-- Installed components registry (tracks what's on disk + metadata)
CREATE TABLE IF NOT EXISTS installed_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    source TEXT NOT NULL DEFAULT 'builtin',  -- 'builtin', 'agent_pack', 'user'
    agent_pack_id TEXT,                       -- FK to agent_packs if installed via pack
    is_active BOOLEAN DEFAULT 1,
    manifest_json TEXT,                       -- Full manifest cached as JSON
    installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_installed_components_source
    ON installed_components(source);

CREATE INDEX IF NOT EXISTS idx_installed_components_active
    ON installed_components(is_active);
