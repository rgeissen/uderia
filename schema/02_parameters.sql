-- ============================================================================
-- Uderia Prompt Management System - Parameters
-- ============================================================================
-- Description: Global and local parameter definitions with validation
-- Version: 1.0
-- Created: 2025-12-18
-- ============================================================================

-- ============================================================================
-- Global Parameters
-- ============================================================================
-- Purpose: Parameters available to ALL prompts
-- Types:
--   - System-managed: Auto-populated by application (tools_context, etc.)
--   - User-configurable: Can be overridden by users/profiles
-- ============================================================================

CREATE TABLE IF NOT EXISTS global_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parameter_name TEXT UNIQUE NOT NULL,    -- e.g., 'mcp_system_name', 'tools_context'
    display_name TEXT NOT NULL,             -- e.g., 'MCP System Name'
    parameter_type TEXT NOT NULL,           -- 'string', 'integer', 'boolean', 'json', 'enum'
    description TEXT,                       -- What this parameter does
    default_value TEXT,                     -- Default value (as string, converted at runtime)
    is_system_managed BOOLEAN DEFAULT 1,    -- Auto-populated by system?
    is_user_configurable BOOLEAN DEFAULT 0, -- Can users/profiles override?
    allowed_values TEXT,                    -- JSON array for enum types: ["value1", "value2"]
    validation_regex TEXT,                  -- Regex for string validation
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CHECK(parameter_type IN ('string', 'integer', 'boolean', 'json', 'enum')),
    CHECK(is_system_managed IN (0, 1)),
    CHECK(is_user_configurable IN (0, 1))
);

-- ============================================================================
-- Global Parameter Overrides
-- ============================================================================
-- Purpose: User/Profile-specific overrides for global parameters
-- Priority: profile > user > default
-- Only applies to parameters where is_user_configurable = 1
-- Note: Profiles are stored in tda_config.json (not in this database)
--       Profile IDs are TEXT strings (e.g., "profile-1763993711628-vvbh23q09")
-- ============================================================================

CREATE TABLE IF NOT EXISTS global_parameter_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parameter_name TEXT NOT NULL,           -- References global_parameters.parameter_name
    prompt_id INTEGER,                      -- NULL = applies to all prompts, INTEGER = specific prompt only
    user_uuid TEXT,                         -- NULL = applies to all users with this profile
    profile_id TEXT,                        -- NULL = user-level override (all profiles), TEXT string from tda_config.json
    override_value TEXT NOT NULL,           -- Value as string (converted at runtime)
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CHECK(is_active IN (0, 1)),
    CHECK(user_uuid IS NOT NULL OR profile_id IS NOT NULL),  -- Must specify at least one
    FOREIGN KEY (parameter_name) REFERENCES global_parameters(parameter_name) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE
);

-- ============================================================================
-- Prompt-Specific (Local) Parameters
-- ============================================================================
-- Purpose: Parameters specific to individual prompts
-- Each prompt can define its own parameters with validation rules
-- ============================================================================

CREATE TABLE IF NOT EXISTS prompt_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL,
    parameter_name TEXT NOT NULL,           -- e.g., 'planning_depth', 'optimization_focus'
    display_name TEXT NOT NULL,             -- e.g., 'Planning Depth'
    parameter_type TEXT NOT NULL,           -- 'string', 'integer', 'boolean', 'json', 'enum'
    parameter_scope TEXT DEFAULT 'local',   -- Always 'local' (vs global)
    is_required BOOLEAN DEFAULT 1,          -- Must this parameter be provided?
    default_value TEXT,                     -- Default value if not provided
    description TEXT,                       -- What this parameter does
    
    -- Validation rules
    allowed_values TEXT,                    -- JSON array for enum: ["shallow", "medium", "deep"]
    validation_regex TEXT,                  -- Regex for string validation
    min_value NUMERIC,                      -- For integer/numeric types
    max_value NUMERIC,                      -- For integer/numeric types
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CHECK(parameter_type IN ('string', 'integer', 'boolean', 'json', 'enum')),
    CHECK(parameter_scope = 'local'),
    CHECK(is_required IN (0, 1)),
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
    UNIQUE(prompt_id, parameter_name)
);

-- ============================================================================
-- Class-Level Parameters
-- ============================================================================
-- Purpose: Parameters inherited by all prompts in a class
-- Prompts in a class automatically inherit these parameters
-- Can be overridden at prompt level via prompt_parameters
-- ============================================================================

CREATE TABLE IF NOT EXISTS prompt_class_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    parameter_name TEXT NOT NULL,           -- e.g., 'max_phases'
    display_name TEXT NOT NULL,             -- e.g., 'Maximum Planning Phases'
    parameter_type TEXT NOT NULL,           -- 'string', 'integer', 'boolean', 'json', 'enum'
    default_value TEXT,                     -- Default for all prompts in this class
    is_required BOOLEAN DEFAULT 0,          -- Required for all prompts in class?
    description TEXT,
    
    -- Validation rules (inherited by prompts)
    allowed_values TEXT,                    -- JSON array for enum
    validation_regex TEXT,
    min_value NUMERIC,
    max_value NUMERIC,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CHECK(parameter_type IN ('string', 'integer', 'boolean', 'json', 'enum')),
    CHECK(is_required IN (0, 1)),
    FOREIGN KEY (class_id) REFERENCES prompt_classes(id) ON DELETE CASCADE,
    UNIQUE(class_id, parameter_name)
);

-- ============================================================================
-- Triggers for Automatic Timestamp Updates
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS update_global_parameters_timestamp 
AFTER UPDATE ON global_parameters
BEGIN
    UPDATE global_parameters SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_global_parameter_overrides_timestamp 
AFTER UPDATE ON global_parameter_overrides
BEGIN
    UPDATE global_parameter_overrides SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
