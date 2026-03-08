-- ============================================================================
-- Uderia Prompt Management System - Core Tables
-- ============================================================================
-- Description: Core tables for prompt storage, classes, and organization
-- Version: 1.0
-- Created: 2025-12-18
-- ============================================================================

-- ============================================================================
-- Prompt Classes
-- ============================================================================
-- Purpose: Define reusable prompt templates and categorization
-- Classes enable:
--   - Template inheritance (parent_class_id)
--   - Categorization for organization
--   - Grouping related prompts
-- ============================================================================

CREATE TABLE IF NOT EXISTS prompt_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,              -- e.g., 'StrategicPlanningTemplates'
    display_name TEXT NOT NULL,             -- e.g., 'Strategic Planning Templates'
    description TEXT,                       -- Human-readable description
    class_type TEXT NOT NULL DEFAULT 'category',  -- 'category', 'template'
    parent_class_id INTEGER,                -- For inheritance hierarchy
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,
    updated_by TEXT,
    
    -- Constraints
    CHECK(class_type IN ('category', 'template')),
    CHECK(is_active IN (0, 1)),
    FOREIGN KEY (parent_class_id) REFERENCES prompt_classes(id) ON DELETE RESTRICT
);

-- ============================================================================
-- Prompts
-- ============================================================================
-- Purpose: Store actual prompt content
-- Each prompt:
--   - Belongs to a class (optional)
--   - Can be a template for other prompts
--   - Has UI categorization for display
--   - Can be provider-specific
--   - Workflow routing is by prompt name (e.g., WORKFLOW_TACTICAL_PROMPT), not role field
-- ============================================================================

CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,              -- e.g., 'MASTER_SYSTEM_PROMPT', 'WORKFLOW_TACTICAL_PROMPT'
    display_name TEXT NOT NULL,             -- e.g., 'Master System Prompt'
    content TEXT NOT NULL,                  -- The actual prompt text with {parameters}
    description TEXT,                       -- What this prompt does
    class_id INTEGER,                       -- Which class this belongs to (for UI grouping)
    role TEXT,                              -- UI category: 'workflow', 'system', 'recovery', 'data', 'visualization'
    provider TEXT,                          -- NULL=universal, or 'Google', 'Anthropic', etc.
    version INTEGER DEFAULT 1,              -- Version number (incremented on updates)
    is_active BOOLEAN DEFAULT 1,            -- Can this prompt be used?
    is_template BOOLEAN DEFAULT 0,          -- Is this a base template for others?
    is_system_default BOOLEAN DEFAULT 0,    -- Is this a system-wide default?
    template_prompt_id INTEGER,             -- If extending another prompt
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,
    updated_by TEXT,
    
    -- Constraints
    CHECK(is_active IN (0, 1)),
    CHECK(is_template IN (0, 1)),
    CHECK(is_system_default IN (0, 1)),
    CHECK(version > 0),
    FOREIGN KEY (class_id) REFERENCES prompt_classes(id) ON DELETE SET NULL,
    FOREIGN KEY (template_prompt_id) REFERENCES prompts(id) ON DELETE SET NULL
);

-- ============================================================================
-- Prompt Version History
-- ============================================================================
-- Purpose: Track all changes to prompts over time
-- Enables:
--   - Audit trail
--   - Rollback to previous versions
--   - Comparison between versions
-- ============================================================================

CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL,
    version INTEGER NOT NULL,               -- Version number being saved
    content TEXT NOT NULL,                  -- Snapshot of content at this version
    changed_by TEXT,                        -- User who made the change
    change_reason TEXT,                     -- Why was it changed?
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CHECK(version > 0),
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
    UNIQUE(prompt_id, version)
);

-- ============================================================================
-- Prompt Overrides (User/Profile-Specific)
-- ============================================================================
-- Purpose: Allow custom prompt versions for specific users or profiles
-- Priority: profile > user > system default
-- ============================================================================

CREATE TABLE IF NOT EXISTS prompt_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL,
    user_uuid TEXT,                         -- NULL = applies to all users with this profile
    profile_id INTEGER,                     -- NULL = user-level override (all profiles)
    content TEXT NOT NULL,                  -- Custom prompt content
    active_version_id INTEGER,              -- NULL = use content, INTEGER = use specific version
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,
    
    -- Constraints
    CHECK(is_active IN (0, 1)),
    CHECK(user_uuid IS NOT NULL OR profile_id IS NOT NULL),  -- Must specify at least one
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
    FOREIGN KEY (active_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL
);

-- ============================================================================
-- Triggers for Automatic Timestamp Updates
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS update_prompt_classes_timestamp 
AFTER UPDATE ON prompt_classes
BEGIN
    UPDATE prompt_classes SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_prompts_timestamp 
AFTER UPDATE ON prompts
BEGIN
    UPDATE prompts SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_prompt_overrides_timestamp 
AFTER UPDATE ON prompt_overrides
BEGIN
    UPDATE prompt_overrides SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- ============================================================================
-- Triggers for Version History
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS create_prompt_version_on_update
AFTER UPDATE OF content ON prompts
WHEN OLD.content != NEW.content AND OLD.content != '[MIGRATE]'
BEGIN
    -- Save old version to history (skip if old content was the [MIGRATE] placeholder)
    INSERT INTO prompt_versions (prompt_id, version, content, changed_by)
    VALUES (OLD.id, OLD.version, OLD.content, NEW.updated_by);
    
    -- Increment version number
    UPDATE prompts SET version = version + 1 WHERE id = NEW.id;
END;
