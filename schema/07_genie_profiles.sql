-- ============================================================================
-- Uderia Prompt Management System - Genie Profiles
-- ============================================================================
-- Description: Schema for Genie profile session tracking and coordination
-- Version: 1.0
-- Created: 2026-01-12
-- Note: Genie profiles coordinate multiple child profiles via LangChain
-- Note: Column names like 'slave_*' preserved for API compatibility
-- ============================================================================

-- ============================================================================
-- Genie Session Links
-- ============================================================================
-- Purpose: Track parent-child session relationships for Genie coordination
-- When a Genie profile spawns child sessions, this table records the linkage
-- to enable:
--   - UI display of child sessions under their parent
--   - Session cleanup when parent is deleted
--   - Context reuse tracking across coordination turns
-- Note: Column names like 'slave_*' preserved for API compatibility
-- ============================================================================

CREATE TABLE IF NOT EXISTS genie_session_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id TEXT NOT NULL,       -- Genie coordinator session
    slave_session_id TEXT NOT NULL,        -- Child session ID (column name preserved for API compatibility)
    slave_profile_id TEXT NOT NULL,        -- Profile used for child (column name preserved for API compatibility)
    slave_profile_tag TEXT,                -- Profile tag (e.g., @CHAT, @RAG)
    user_uuid TEXT NOT NULL,               -- User who owns both sessions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active',          -- active, completed, failed
    execution_order INTEGER DEFAULT 0,     -- Order in which child was invoked
    nesting_level INTEGER DEFAULT 0,       -- Depth in nested Genie hierarchy (0=direct child, 1=grandchild, etc.)
    archived BOOLEAN DEFAULT 0,            -- Archived flag (set when child session profile is deleted)

    -- Ensure unique parent-child relationship
    UNIQUE(parent_session_id, slave_session_id)
);

-- Index for finding all children of a parent session
CREATE INDEX IF NOT EXISTS idx_genie_parent
ON genie_session_links(parent_session_id);

-- Index for finding parent of a child session
CREATE INDEX IF NOT EXISTS idx_genie_slave
ON genie_session_links(slave_session_id);

-- Index for user-based queries
CREATE INDEX IF NOT EXISTS idx_genie_user
ON genie_session_links(user_uuid);

-- Index for nesting level queries
CREATE INDEX IF NOT EXISTS idx_genie_nesting_level
ON genie_session_links(nesting_level);
