-- ============================================================================
-- Uderia Prompt Management System - Migration Data
-- ============================================================================
-- Purpose: Migrate existing prompts from prompts.dat into database
-- Version: 1.0
-- Created: 2025-12-18
-- ============================================================================

-- ============================================================================
-- STEP 1: Create Prompt Classes (UI Categories)
-- ============================================================================

INSERT INTO prompt_classes (name, display_name, description, class_type, is_active) VALUES
('MasterSystemPrompts', 'Master System Prompts', 'System-level prompts for different LLM providers', 'category', 1),
('WorkflowClassification', 'Workflow & Classification', 'Task classification and workflow planning prompts', 'category', 1),
('ErrorRecovery', 'Error Recovery & Self-Correction', 'Error handling and self-correction prompts', 'category', 1),
('DataOperations', 'Data Operations', 'SQL and data manipulation prompts', 'category', 1),
('Visualization', 'Visualization', 'Charting and visualization guidelines', 'category', 1);

-- ============================================================================
-- STEP 2: Insert Prompts (Content will be migrated from prompts.dat)
-- ============================================================================
-- Note: Actual content should be extracted from prompts.dat during migration
--       The 'content' field below is marked as '[MIGRATE]' placeholder
-- ============================================================================

-- Master System Prompts (class_id = 1)
INSERT INTO prompts (name, display_name, content, description, class_id, role, provider, is_active, is_system_default, version) VALUES
(
    'MASTER_SYSTEM_PROMPT',
    'Master System Prompt (Default)',
    '[MIGRATE]',
    'Default system prompt for Anthropic, Amazon, OpenAI, Azure, and Friendli providers',
    1,
    'system',
    NULL,
    1,
    1,
    1
),
(
    'GOOGLE_MASTER_SYSTEM_PROMPT',
    'Google Master System Prompt',
    '[MIGRATE]',
    'System prompt optimized for Google Gemini models',
    1,
    'system',
    'Google',
    1,
    0,
    1
),
(
    'OLLAMA_MASTER_SYSTEM_PROMPT',
    'Ollama Master System Prompt',
    '[MIGRATE]',
    'System prompt optimized for Ollama local models',
    1,
    'system',
    'Ollama',
    1,
    0,
    1
);

-- Workflow & Classification (class_id = 2)
INSERT INTO prompts (name, display_name, content, description, class_id, role, provider, is_active, is_system_default, version) VALUES
(
    'TASK_CLASSIFICATION_PROMPT',
    'Task Classification Prompt',
    '[MIGRATE]',
    'Classifies user tasks into appropriate workflow categories',
    2,
    'workflow',
    NULL,
    1,
    1,
    1
),
(
    'WORKFLOW_META_PLANNING_PROMPT',
    'Workflow Meta Planning Prompt',
    '[MIGRATE]',
    'Creates high-level execution plans for complex tasks',
    2,
    'workflow',
    NULL,
    1,
    1,
    1
),
(
    'WORKFLOW_TACTICAL_PROMPT',
    'Workflow Tactical Prompt',
    '[MIGRATE]',
    'Executes individual steps in the workflow plan',
    2,
    'workflow',
    NULL,
    1,
    1,
    1
);

-- Error Recovery & Self-Correction (class_id = 3)
INSERT INTO prompts (name, display_name, content, description, class_id, role, provider, is_active, is_system_default, version) VALUES
(
    'ERROR_RECOVERY_PROMPT',
    'Error Recovery Prompt',
    '[MIGRATE]',
    'Handles errors and attempts recovery strategies',
    3,
    'recovery',
    NULL,
    1,
    1,
    1
),
(
    'TACTICAL_SELF_CORRECTION_PROMPT',
    'Tactical Self-Correction Prompt',
    '[MIGRATE]',
    'General self-correction prompt for tactical execution errors',
    3,
    'recovery',
    NULL,
    1,
    1,
    1
),
(
    'TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR',
    'Self-Correction: Column Error',
    '[MIGRATE]',
    'Specialized correction for SQL column-related errors',
    3,
    'recovery',
    NULL,
    1,
    1,
    1
),
(
    'TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR',
    'Self-Correction: Table Error',
    '[MIGRATE]',
    'Specialized correction for SQL table-related errors',
    3,
    'recovery',
    NULL,
    1,
    1,
    1
);

-- Data Operations (class_id = 4)
INSERT INTO prompts (name, display_name, content, description, class_id, role, provider, is_active, is_system_default, version) VALUES
(
    'SQL_CONSOLIDATION_PROMPT',
    'SQL Consolidation Prompt',
    '[MIGRATE]',
    'Consolidates multiple SQL queries into optimized operations',
    4,
    'data',
    NULL,
    1,
    1,
    1
);

-- Visualization (class_id = 5)
INSERT INTO prompts (name, display_name, content, description, class_id, role, provider, is_active, is_system_default, version) VALUES
(
    'G2PLOT_GUIDELINES',
    'G2Plot Guidelines',
    '[MIGRATE]',
    'Guidelines for generating G2Plot chart specifications',
    5,
    'visualization',
    NULL,
    1,
    1,
    1
),
(
    'CHARTING_INSTRUCTIONS',
    'Charting Instructions',
    '[MIGRATE]',
    'JSON object containing chart generation instructions by complexity level',
    5,
    'visualization',
    NULL,
    1,
    1,
    1
);

-- ============================================================================
-- STEP 3: Define Common Global Parameters
-- ============================================================================
-- These are system-wide parameters used across multiple prompts
-- ============================================================================

INSERT INTO global_parameters (parameter_name, display_name, parameter_type, default_value, description, is_system_managed, is_user_configurable) VALUES
-- LLM Configuration Parameters (System-Managed)
('max_tokens', 'Maximum Tokens', 'integer', '4096', 'Maximum tokens for LLM responses', 1, 0),
('temperature', 'Temperature', 'string', '0.1', 'LLM temperature setting (0.0-2.0) - stored as string, parsed as float', 1, 0),
('top_p', 'Top P', 'string', '0.95', 'Nucleus sampling parameter - stored as string, parsed as float', 1, 0),

-- Workflow Parameters (User-Configurable)
('max_retries', 'Maximum Retries', 'integer', '3', 'Maximum number of retry attempts for errors', 0, 1),
('timeout_seconds', 'Timeout (seconds)', 'integer', '300', 'Timeout for long-running operations', 0, 1),
('debug_mode', 'Debug Mode', 'boolean', 'false', 'Enable verbose debug logging', 0, 1),

-- Task Classification Parameters (User-Configurable)
('classification_confidence_threshold', 'Classification Confidence Threshold', 'string', '0.8', 'Minimum confidence for task classification - stored as string, parsed as float', 0, 1),

-- Planning Parameters (User-Configurable)
('max_plan_steps', 'Maximum Plan Steps', 'integer', '20', 'Maximum steps in a workflow plan', 0, 1),
('enable_parallel_execution', 'Enable Parallel Execution', 'boolean', 'false', 'Allow parallel execution of independent steps', 0, 1);

-- ============================================================================
-- STEP 4: Define Prompt-Specific Parameters
-- ============================================================================
-- Parameters that are specific to individual prompts
-- ============================================================================

-- TASK_CLASSIFICATION_PROMPT parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'TASK_CLASSIFICATION_PROMPT'), 'task_description', 'Task Description', 'string', '', 'User task to classify', 1);

-- WORKFLOW_META_PLANNING_PROMPT parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'task', 'Task', 'string', '', 'Task to plan', 1),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'context', 'Context', 'string', '', 'Additional context for planning', 0),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'available_tools', 'Available Tools', 'json', '[]', 'List of available tools/capabilities', 0);

-- WORKFLOW_TACTICAL_PROMPT parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'WORKFLOW_TACTICAL_PROMPT'), 'step', 'Step', 'string', '', 'Current step to execute', 1),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_TACTICAL_PROMPT'), 'plan', 'Plan', 'string', '', 'Overall workflow plan', 1),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_TACTICAL_PROMPT'), 'previous_results', 'Previous Results', 'string', '', 'Results from previous steps', 0);

-- ERROR_RECOVERY_PROMPT parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'ERROR_RECOVERY_PROMPT'), 'error_message', 'Error Message', 'string', '', 'The error that occurred', 1),
((SELECT id FROM prompts WHERE name = 'ERROR_RECOVERY_PROMPT'), 'failed_action', 'Failed Action', 'string', '', 'The action that failed', 1),
((SELECT id FROM prompts WHERE name = 'ERROR_RECOVERY_PROMPT'), 'attempt_number', 'Attempt Number', 'integer', '1', 'Current retry attempt', 0);

-- TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR'), 'column_name', 'Column Name', 'string', '', 'Name of the problematic column', 1),
((SELECT id FROM prompts WHERE name = 'TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR'), 'table_name', 'Table Name', 'string', '', 'Name of the table', 1),
((SELECT id FROM prompts WHERE name = 'TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR'), 'available_columns', 'Available Columns', 'json', '[]', 'List of available columns in the table', 0);

-- TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR'), 'mcpTool_listTables', 'MCP Tool: List Tables', 'string', 'base_listTables', 'Name of the MCP tool used to list available tables', 0);

-- TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR'), 'mcpTool_describeColumns', 'MCP Tool: Describe Columns', 'string', 'base_columnDescription', 'Name of the MCP tool used to describe table columns', 0);

-- MASTER_SYSTEM_PROMPT parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'MASTER_SYSTEM_PROMPT'), 'mcpSystemName', 'MCP System Name', 'string', 'Teradata System', 'Name of the MCP system being used', 0),
((SELECT id FROM prompts WHERE name = 'MASTER_SYSTEM_PROMPT'), 'mcpTool_executeQuery', 'MCP Tool: Execute Query', 'string', 'base_readQuery', 'Name of the MCP tool used to execute SQL queries', 0);

-- GOOGLE_MASTER_SYSTEM_PROMPT parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'GOOGLE_MASTER_SYSTEM_PROMPT'), 'mcpTool_executeQuery', 'MCP Tool: Execute Query', 'string', 'base_readQuery', 'Name of the MCP tool used to execute SQL queries', 0),
((SELECT id FROM prompts WHERE name = 'GOOGLE_MASTER_SYSTEM_PROMPT'), 'mcpTool_summarizeColumnQuality', 'MCP Tool: Summarize Column Quality', 'string', 'qlty_columnSummary', 'Name of the MCP tool used to analyze column quality', 0);

-- OLLAMA_MASTER_SYSTEM_PROMPT parameters  
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'OLLAMA_MASTER_SYSTEM_PROMPT'), 'mcpSystemName', 'MCP System Name', 'string', 'Teradata System', 'Name of the MCP system being used', 0),
((SELECT id FROM prompts WHERE name = 'OLLAMA_MASTER_SYSTEM_PROMPT'), 'mcpTool_executeQuery', 'MCP Tool: Execute Query', 'string', 'base_readQuery', 'Name of the MCP tool used to execute SQL queries', 0);

-- WORKFLOW_META_PLANNING_PROMPT parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'mcpTool_executeQuery', 'MCP Tool: Execute Query', 'string', 'base_readQuery', 'Name of the MCP tool used to execute SQL queries', 0),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'mcpPrompt_executeOptimizedQuery', 'MCP Prompt: Execute Optimized Query', 'string', 'base_teradataQuery', 'Name of the MCP prompt used for optimized database queries', 0),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'mcpTool_describeColumns', 'MCP Tool: Describe Columns', 'string', 'base_columnDescription', 'Name of the MCP tool used to describe table columns', 0),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'mcpTool_listDatabases', 'MCP Tool: List Databases', 'string', 'base_databaseList', 'Name of the MCP tool used to list databases', 0),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'mcpTool_listTables', 'MCP Tool: List Tables', 'string', 'base_tableList', 'Name of the MCP tool used to list tables', 0),
((SELECT id FROM prompts WHERE name = 'WORKFLOW_META_PLANNING_PROMPT'), 'mcpTool_getTableSchema', 'MCP Tool: Get Table Schema', 'string', 'base_tableDDL', 'Name of the MCP tool used to get table DDL/schema', 0);

-- SQL_CONSOLIDATION_PROMPT parameters
INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, default_value, description, is_required) VALUES
((SELECT id FROM prompts WHERE name = 'SQL_CONSOLIDATION_PROMPT'), 'queries', 'Queries', 'json', '[]', 'List of SQL queries to consolidate', 1),
((SELECT id FROM prompts WHERE name = 'SQL_CONSOLIDATION_PROMPT'), 'schema_info', 'Schema Info', 'string', '', 'Database schema information', 0);

-- ============================================================================
-- STEP 5: Verification Queries
-- ============================================================================
-- Run these to verify migration was successful
-- ============================================================================

-- Count prompt classes
-- SELECT COUNT(*) as class_count FROM prompt_classes;
-- Expected: 5

-- Count prompts
-- SELECT COUNT(*) as prompt_count FROM prompts;
-- Expected: 12

-- List all prompts with their classes
-- SELECT 
--     pc.display_name as category,
--     p.name as prompt_name,
--     p.display_name,
--     p.role,
--     p.provider
-- FROM prompts p
-- LEFT JOIN prompt_classes pc ON p.class_id = pc.id
-- ORDER BY pc.id, p.name;

-- Count parameters
-- SELECT 
--     COUNT(DISTINCT parameter_name) as global_params
-- FROM global_parameters;
-- Expected: 8

-- SELECT 
--     COUNT(*) as prompt_params
-- FROM prompt_parameters;
-- Expected: 14

-- ============================================================================
-- End of Migration Data
-- ============================================================================
