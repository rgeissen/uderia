-- ============================================================
-- Schema: Agent Packs
-- Version: 1.1
-- Description: Tracks installed agent packs and their resources
--              for clean install/uninstall lifecycle.
-- ============================================================

-- Tracks installed agent packs
CREATE TABLE IF NOT EXISTS agent_pack_installations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),
    author VARCHAR(255),
    coordinator_tag VARCHAR(50),            -- Nullable: not all packs have a coordinator
    coordinator_profile_id VARCHAR(100),
    pack_type VARCHAR(20) DEFAULT 'genie',  -- 'genie', 'bundle', or 'single'
    owner_user_id VARCHAR(36) NOT NULL,
    installed_at DATETIME NOT NULL,
    manifest_json TEXT NOT NULL,
    FOREIGN KEY (owner_user_id) REFERENCES users(id)
);

-- Maps pack → resources (many-to-many junction table)
-- Authoritative source of truth for pack ↔ resource relationships.
CREATE TABLE IF NOT EXISTS agent_pack_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_installation_id INTEGER NOT NULL,
    resource_type VARCHAR(20) NOT NULL,   -- 'profile' or 'collection'
    resource_id VARCHAR(100) NOT NULL,    -- profile ID or collection ID
    resource_tag VARCHAR(50),             -- profile tag (NULL for collections)
    resource_role VARCHAR(20),            -- 'coordinator', 'expert', 'standalone', or 'collection'
    is_owned BOOLEAN NOT NULL DEFAULT 1,  -- 1 = created by pack, 0 = references existing
    FOREIGN KEY (pack_installation_id) REFERENCES agent_pack_installations(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_agent_pack_installations_owner
    ON agent_pack_installations(owner_user_id);

CREATE INDEX IF NOT EXISTS idx_agent_pack_installations_coordinator_tag
    ON agent_pack_installations(coordinator_tag);

CREATE INDEX IF NOT EXISTS idx_agent_pack_resources_pack_id
    ON agent_pack_resources(pack_installation_id);

CREATE INDEX IF NOT EXISTS idx_agent_pack_resources_resource
    ON agent_pack_resources(resource_type, resource_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_pack_resources_unique
    ON agent_pack_resources(pack_installation_id, resource_type, resource_id);
