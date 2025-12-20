-- ============================================================================
-- Uderia Prompt Management System - Profile Prompt Mappings
-- ============================================================================
-- Description: Maps profiles to specific prompts for each functional category
-- Version: 1.0
-- Created: 2025-12-20
-- Note: This provides fine-grained control over which prompts are used for
--       different functional areas (master system, workflow, error recovery, etc.)
-- ============================================================================

-- ============================================================================
-- Profile Prompt Mappings
-- ============================================================================
-- Purpose: Define which prompt each profile uses for each functional category
-- Always uses the active version of the mapped prompt
-- Falls back to system defaults from tda_config.json if no mapping exists
-- ============================================================================

CREATE TABLE IF NOT EXISTS profile_prompt_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,               -- Profile string ID from tda_config.json
    category TEXT NOT NULL,                 -- Functional category (see categories below)
    subcategory TEXT,                       -- Optional subcategory (e.g., provider for master_system)
    prompt_name TEXT NOT NULL,              -- Database prompt name (e.g., 'GOOGLE_MASTER_SYSTEM_PROMPT')
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,                        -- User UUID who created this mapping
    
    -- Constraints
    FOREIGN KEY (prompt_name) REFERENCES prompts(name) ON DELETE RESTRICT,
    UNIQUE(profile_id, category, subcategory)  -- One mapping per category per profile
);

-- ============================================================================
-- Categories and Subcategories
-- ============================================================================
-- master_system:
--   - subcategory = provider (Google, Anthropic, OpenAI, etc.)
--   - Default from tda_config.json: default_prompt_mappings.master_system_prompts
--
-- workflow_classification:
--   - subcategory = task_classification, workflow_meta_planning, workflow_tactical
--   - Default from tda_config.json: default_prompt_mappings.workflow_classification
--
-- error_recovery:
--   - subcategory = error_recovery, tactical_self_correction, 
--                   self_correction_column_error, self_correction_table_error
--   - Default from tda_config.json: default_prompt_mappings.error_recovery
--
-- data_operations:
--   - subcategory = sql_consolidation
--   - Default from tda_config.json: default_prompt_mappings.data_operations
--
-- visualization:
--   - subcategory = charting_instructions, g2plot_guidelines
--   - Default from tda_config.json: default_prompt_mappings.visualization
-- ============================================================================

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_profile_prompt_mappings_lookup 
ON profile_prompt_mappings(profile_id, category, subcategory);

-- Create index for prompt name lookups (for warnings when prompts are deleted)
CREATE INDEX IF NOT EXISTS idx_profile_prompt_mappings_prompt 
ON profile_prompt_mappings(prompt_name);
