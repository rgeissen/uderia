-- ============================================================================
-- Uderia Platform - Database Migration 09
-- ============================================================================
-- Description: Add nesting level tracking for nested Genie coordination
-- Version: 1.0
-- Created: 2026-01-16
-- Purpose: Enable Genie profiles to coordinate other Genie profiles while
--          tracking the depth of nesting for safety and debugging
-- ============================================================================

-- ============================================================================
-- Add nesting_level column to genie_session_links
-- ============================================================================
-- Purpose: Track the depth in the nested Genie hierarchy
--   - Level 0: Direct child of top-level Genie
--   - Level 1: Child of a child
--   - Level 2: Child of a child of a child
--   - etc.
-- Note: Column names preserved for API compatibility
-- ============================================================================

ALTER TABLE genie_session_links
ADD COLUMN nesting_level INTEGER DEFAULT 0;

-- Create index for performance on nesting level queries
CREATE INDEX IF NOT EXISTS idx_genie_nesting_level
ON genie_session_links(nesting_level);

-- Backfill existing records with level 0 (backward compatibility)
UPDATE genie_session_links SET nesting_level = 0 WHERE nesting_level IS NULL;

-- Verify migration
SELECT 'Migration 09 completed: nesting_level column added to genie_session_links' AS status;
