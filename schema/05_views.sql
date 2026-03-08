-- ============================================================================
-- Uderia Prompt Management System - Useful Views
-- ============================================================================
-- Description: Common query views for simplified access
-- Version: 1.0
-- Created: 2025-12-18
-- ============================================================================

-- ============================================================================
-- Active Prompts with Class Information
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_active_prompts AS
SELECT 
    p.id,
    p.name,
    p.display_name,
    p.content,
    p.description,
    p.role,
    p.provider,
    p.version,
    p.is_template,
    p.is_system_default,
    pc.name as class_name,
    pc.display_name as class_display_name,
    p.created_at,
    p.updated_at
FROM prompts p
LEFT JOIN prompt_classes pc ON p.class_id = pc.id
WHERE p.is_active = 1;

-- ============================================================================
-- Prompt Parameters with Validation Rules
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_prompt_parameters_full AS
SELECT 
    p.name as prompt_name,
    pp.parameter_name,
    pp.display_name,
    pp.parameter_type,
    pp.is_required,
    pp.default_value,
    pp.description,
    pp.allowed_values,
    pp.validation_regex,
    pp.min_value,
    pp.max_value
FROM prompt_parameters pp
JOIN prompts p ON pp.prompt_id = p.id
WHERE p.is_active = 1;

-- ============================================================================
-- Profile Prompt Configuration
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_profile_prompt_config AS
SELECT 
    ppa.profile_id,
    ppa.prompt_role,
    p.id as prompt_id,
    p.name as prompt_name,
    p.display_name as prompt_display_name,
    p.content as prompt_content,
    ppa.is_active
FROM profile_prompt_assignments ppa
JOIN prompts p ON ppa.prompt_id = p.id
WHERE ppa.is_active = 1 AND p.is_active = 1;

-- ============================================================================
-- Profile Prompt Parameters with Values
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_profile_prompt_parameters AS
SELECT 
    ppa.profile_id,
    ppa.prompt_role,
    p.name as prompt_name,
    pp.parameter_name,
    pp.display_name as parameter_display_name,
    pp.parameter_type,
    pp.default_value as parameter_default,
    COALESCE(pppv.parameter_value, pp.default_value) as parameter_value,
    pp.is_required,
    pp.allowed_values,
    pp.min_value,
    pp.max_value
FROM profile_prompt_assignments ppa
JOIN prompts p ON ppa.prompt_id = p.id
JOIN prompt_parameters pp ON p.id = pp.prompt_id
LEFT JOIN profile_prompt_parameter_values pppv ON ppa.profile_id = pppv.profile_id 
    AND ppa.prompt_id = pppv.prompt_id
    AND pp.parameter_name = pppv.parameter_name
WHERE ppa.is_active = 1 AND p.is_active = 1;

-- ============================================================================
-- Global Parameters with Override Status
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_global_parameters_full AS
SELECT 
    gp.parameter_name,
    gp.display_name,
    gp.parameter_type,
    gp.default_value,
    gp.is_system_managed,
    gp.is_user_configurable,
    gp.description,
    gp.allowed_values,
    gp.validation_regex,
    COUNT(gpo.id) as override_count
FROM global_parameters gp
LEFT JOIN global_parameter_overrides gpo ON gp.parameter_name = gpo.parameter_name 
    AND gpo.is_active = 1
GROUP BY gp.id, gp.parameter_name;

-- ============================================================================
-- Prompt Class Hierarchy
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_prompt_class_hierarchy AS
WITH RECURSIVE class_tree AS (
    -- Base case: root classes (no parent)
    SELECT 
        id,
        name,
        display_name,
        parent_class_id,
        0 as level,
        name as path
    FROM prompt_classes
    WHERE parent_class_id IS NULL AND is_active = 1
    
    UNION ALL
    
    -- Recursive case: children
    SELECT 
        pc.id,
        pc.name,
        pc.display_name,
        pc.parent_class_id,
        ct.level + 1,
        ct.path || ' > ' || pc.name
    FROM prompt_classes pc
    JOIN class_tree ct ON pc.parent_class_id = ct.id
    WHERE pc.is_active = 1
)
SELECT * FROM class_tree
ORDER BY path;

-- ============================================================================
-- Prompt Version History Summary
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_prompt_version_history AS
SELECT 
    p.name as prompt_name,
    p.display_name as prompt_display_name,
    pv.version,
    pv.changed_by,
    pv.change_reason,
    pv.created_at,
    LENGTH(pv.content) as content_length,
    p.version as current_version
FROM prompt_versions pv
JOIN prompts p ON pv.prompt_id = p.id
ORDER BY p.name, pv.version DESC;

-- ============================================================================
-- Prompt Usage Summary (which profiles use which prompts)
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_prompt_usage AS
SELECT 
    p.name as prompt_name,
    p.display_name as prompt_display_name,
    p.role,
    COUNT(DISTINCT ppa.profile_id) as profile_count,
    GROUP_CONCAT(DISTINCT ppa.prompt_role) as used_for_roles
FROM prompts p
LEFT JOIN profile_prompt_assignments ppa ON p.id = ppa.prompt_id AND ppa.is_active = 1
WHERE p.is_active = 1
GROUP BY p.id, p.name
ORDER BY profile_count DESC, p.name;
