-- ============================================================================
-- Uderia Prompt Management System - Indexes
-- ============================================================================
-- Description: Performance optimization indexes
-- Version: 1.0
-- Created: 2025-12-18
-- ============================================================================

-- ============================================================================
-- Prompt Classes Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_prompt_classes_active 
ON prompt_classes(is_active) WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_prompt_classes_type 
ON prompt_classes(class_type);

CREATE INDEX IF NOT EXISTS idx_prompt_classes_parent 
ON prompt_classes(parent_class_id) WHERE parent_class_id IS NOT NULL;

-- ============================================================================
-- Prompts Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_prompts_name 
ON prompts(name);

CREATE INDEX IF NOT EXISTS idx_prompts_active 
ON prompts(is_active) WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_prompts_class 
ON prompts(class_id) WHERE class_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_prompts_role 
ON prompts(role) WHERE role IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_prompts_provider 
ON prompts(provider) WHERE provider IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_prompts_template 
ON prompts(is_template) WHERE is_template = 1;

CREATE INDEX IF NOT EXISTS idx_prompts_system_default 
ON prompts(is_system_default) WHERE is_system_default = 1;

-- ============================================================================
-- Prompt Versions Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_prompt_versions_prompt 
ON prompt_versions(prompt_id);

CREATE INDEX IF NOT EXISTS idx_prompt_versions_created 
ON prompt_versions(created_at DESC);

-- ============================================================================
-- Prompt Overrides Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_prompt_overrides_prompt 
ON prompt_overrides(prompt_id);

CREATE INDEX IF NOT EXISTS idx_prompt_overrides_user 
ON prompt_overrides(user_uuid) WHERE user_uuid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_prompt_overrides_profile 
ON prompt_overrides(profile_id) WHERE profile_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_prompt_overrides_active 
ON prompt_overrides(is_active) WHERE is_active = 1;

-- ============================================================================
-- Global Parameters Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_global_parameters_name 
ON global_parameters(parameter_name);

CREATE INDEX IF NOT EXISTS idx_global_parameters_system_managed 
ON global_parameters(is_system_managed);

CREATE INDEX IF NOT EXISTS idx_global_parameters_user_configurable 
ON global_parameters(is_user_configurable) WHERE is_user_configurable = 1;

-- ============================================================================
-- Global Parameter Overrides Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_global_overrides_parameter 
ON global_parameter_overrides(parameter_name);

CREATE INDEX IF NOT EXISTS idx_global_overrides_user 
ON global_parameter_overrides(user_uuid) WHERE user_uuid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_global_overrides_profile 
ON global_parameter_overrides(profile_id) WHERE profile_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_global_overrides_active 
ON global_parameter_overrides(is_active) WHERE is_active = 1;

-- ============================================================================
-- Prompt Parameters Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_prompt_parameters_prompt 
ON prompt_parameters(prompt_id);

CREATE INDEX IF NOT EXISTS idx_prompt_parameters_name 
ON prompt_parameters(parameter_name);

CREATE INDEX IF NOT EXISTS idx_prompt_parameters_required 
ON prompt_parameters(is_required) WHERE is_required = 1;

-- ============================================================================
-- Class Parameters Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_class_parameters_class 
ON prompt_class_parameters(class_id);

CREATE INDEX IF NOT EXISTS idx_class_parameters_required 
ON prompt_class_parameters(is_required) WHERE is_required = 1;

-- ============================================================================
-- Profile Prompt Assignments Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_profile_assignments_profile 
ON profile_prompt_assignments(profile_id);

CREATE INDEX IF NOT EXISTS idx_profile_assignments_prompt 
ON profile_prompt_assignments(prompt_id);

CREATE INDEX IF NOT EXISTS idx_profile_assignments_role 
ON profile_prompt_assignments(prompt_role);

CREATE INDEX IF NOT EXISTS idx_profile_assignments_active 
ON profile_prompt_assignments(is_active) WHERE is_active = 1;

-- Composite index for common query pattern (profile + role lookup)
CREATE INDEX IF NOT EXISTS idx_profile_assignments_profile_role 
ON profile_prompt_assignments(profile_id, prompt_role) WHERE is_active = 1;

-- ============================================================================
-- Profile Prompt Parameter Values Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_profile_param_values_profile 
ON profile_prompt_parameter_values(profile_id);

CREATE INDEX IF NOT EXISTS idx_profile_param_values_prompt 
ON profile_prompt_parameter_values(prompt_id);

CREATE INDEX IF NOT EXISTS idx_profile_param_values_param 
ON profile_prompt_parameter_values(parameter_name);

-- ============================================================================
-- Profile Class Assignments Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_profile_class_assignments_profile 
ON profile_class_assignments(profile_id);

CREATE INDEX IF NOT EXISTS idx_profile_class_assignments_class 
ON profile_class_assignments(class_id);

CREATE INDEX IF NOT EXISTS idx_profile_class_assignments_active 
ON profile_class_assignments(is_active) WHERE is_active = 1;

-- ============================================================================
-- Profile Class Parameter Overrides Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_profile_class_overrides_assignment 
ON profile_class_parameter_overrides(assignment_id);
