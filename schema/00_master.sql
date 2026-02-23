-- ============================================================================
-- Uderia Prompt Management System - Master Schema Builder
-- ============================================================================
-- Description: Executes all schema files in order
-- Version: 1.0
-- Created: 2025-12-18
-- Usage: sqlite3 prompts.db < schema/00_master.sql
-- ============================================================================

-- ============================================================================
-- Schema Version Tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- Record initial schema version
INSERT OR IGNORE INTO schema_version (version, description) VALUES 
('1.0.0', 'Initial prompt management system schema');

-- ============================================================================
-- Execute Schema Files in Order
-- ============================================================================

-- Note: When running this file, SQLite does not support .read directive
-- You must run each schema file individually or concatenate them.
--
-- Recommended execution order (prompts.db):
-- 1. 01_core_tables.sql
-- 2. 02_parameters.sql
-- 3. 03_profile_integration.sql
-- 4. 04_indexes.sql
-- 5. 05_views.sql
-- 6. 06_prompt_mappings.sql
-- 7. 07_genie_profiles.sql
--
-- For tda_auth.db (run separately):
-- 8. 08_genie_global_settings.sql - Three-tier configuration settings
--    Note: This is auto-created by database.py bootstrap process.
--    Manual execution only needed for existing installations.
-- 9. 09_agent_packs.sql            - Agent pack installations
-- 10. 10_marketplace_agent_packs.sql - Marketplace agent packs
-- 11. 11_marketplace_sharing.sql    - Marketplace sharing grants
-- 12. 12_extensions.sql             - Per-user extension activations
-- 13. 13_extension_settings.sql     - Admin extension governance settings
-- 14. 14_marketplace_extensions.sql - Marketplace extensions + ratings
-- 15. 15_skills.sql                - Per-user skill activations
-- 16. 16_skill_settings.sql        - Admin skill governance settings
-- 17. 17_marketplace_skills.sql    - Marketplace skills + ratings
-- 18. 18_components.sql            - Installed components + profile config
-- 19. 19_component_settings.sql    - Admin component governance settings

-- ============================================================================
-- Alternatively, use the Python validation script to build the database
-- ============================================================================
-- 
-- python schema/validate_schema.py --create-database prompts.db
--
