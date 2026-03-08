-- ============================================================================
-- Uderia Prompt Management System - Profile Integration
-- ============================================================================
-- Description: Integration between profiles and prompts (stored in tda_auth.db)
-- Version: 1.0
-- Created: 2025-12-18
-- Note: Profiles are stored in tda_config.json (not in this database)
--       Profile IDs are TEXT strings (e.g., "profile-1763993711628-vvbh23q09")
-- ============================================================================

-- ============================================================================
-- Profile Prompt Assignments
-- ============================================================================
-- Purpose: Define custom prompt assignments for profiles (optional future feature)
-- Note: Current workflow routing is hardcoded by prompt name:
--   - TASK_CLASSIFICATION_PROMPT → planner.py classification
--   - WORKFLOW_META_PLANNING_PROMPT → planner.py planning
--   - WORKFLOW_TACTICAL_PROMPT → phase_executor.py execution
--   - ERROR_RECOVERY_PROMPT → phase_executor.py recovery
-- This table allows future flexibility for profile-specific prompt overrides
-- ============================================================================

CREATE TABLE IF NOT EXISTS profile_prompt_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,               -- Profile string ID from tda_config.json
    prompt_role TEXT NOT NULL,              -- Custom label for this assignment (e.g., 'main_system', 'planning', 'execution')
    prompt_id INTEGER NOT NULL,             -- Which prompt to use
    is_active BOOLEAN DEFAULT 1,            -- Is this assignment active?
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CHECK(is_active IN (0, 1)),
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE RESTRICT,
    UNIQUE(profile_id, prompt_role)  -- Each role label can only have one prompt per profile
);

-- ============================================================================
-- Profile Prompt Parameter Values
-- ============================================================================
-- Purpose: Override parameter values at the profile level
-- Example: Profile "Data Science" might use max_tokens=8000 for strategic
--          while Profile "Customer Support" uses max_tokens=2000
-- ============================================================================

CREATE TABLE IF NOT EXISTS profile_prompt_parameter_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,               -- Profile string ID from tda_config.json
    prompt_id INTEGER NOT NULL,             -- Which prompt
    parameter_name TEXT NOT NULL,           -- Which parameter to override
    parameter_value TEXT NOT NULL,          -- Override value (JSON)
    is_active BOOLEAN DEFAULT 1,            -- Is this override active?
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CHECK(is_active IN (0, 1)),
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE RESTRICT,
    UNIQUE(profile_id, prompt_id, parameter_name)  -- One override per param per prompt per profile
);

-- ============================================================================
-- Profile Class Assignments (Optional - For Future Use)
-- ============================================================================
-- Purpose: Assign entire prompt classes to profiles
-- This is an optional enhancement - profiles can assign multiple prompts
-- from the same class at once by assigning the class
-- ============================================================================

CREATE TABLE IF NOT EXISTS profile_class_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,               -- Profile string ID from tda_config.json
    class_id INTEGER NOT NULL,              -- Prompt class ID
    is_active BOOLEAN DEFAULT 1,            -- Is this assignment active?
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CHECK(is_active IN (0, 1)),
    FOREIGN KEY (class_id) REFERENCES prompt_classes(id) ON DELETE RESTRICT,
    UNIQUE(profile_id, class_id)            -- Each profile can only assign each class once
);

-- ============================================================================
-- Profile Class Parameter Overrides (Optional - For Future Use)
-- ============================================================================
-- Purpose: Override class-level parameters for a specific profile
-- When a profile is assigned a class, it can override the class-level
-- parameter defaults
-- ============================================================================

CREATE TABLE IF NOT EXISTS profile_class_parameter_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,         -- Links to profile_class_assignments
    parameter_name TEXT NOT NULL,           -- Which class parameter to override
    parameter_value TEXT NOT NULL,          -- Value for this profile
    
    -- Constraints
    FOREIGN KEY (assignment_id) REFERENCES profile_class_assignments(id) ON DELETE CASCADE,
    UNIQUE(assignment_id, parameter_name)
);

-- ============================================================================
-- Triggers for Automatic Timestamp Updates
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS update_profile_prompt_assignments_timestamp 
AFTER UPDATE ON profile_prompt_assignments
BEGIN
    UPDATE profile_prompt_assignments SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_profile_class_assignments_timestamp 
AFTER UPDATE ON profile_class_assignments
BEGIN
    UPDATE profile_class_assignments SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
