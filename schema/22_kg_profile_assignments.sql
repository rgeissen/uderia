-- ============================================================
-- Schema: Knowledge Graph Profile Assignments
-- Version: 2.0
-- Description: Maps knowledge graphs to profiles for shared
--              context enrichment. A KG is owned by one profile
--              (kg_owner_profile_id) but can be assigned to
--              additional profiles (assigned_profile_id).
--              Self-assignment rows (owner == assigned) track
--              the owner's own activation state.
--              Only ONE KG can be active per profile at a time,
--              enforced by a partial unique index.
-- ============================================================

CREATE TABLE IF NOT EXISTS kg_profile_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kg_owner_profile_id TEXT NOT NULL,     -- profile that owns the KG data
    assigned_profile_id TEXT NOT NULL,     -- profile that can USE the KG
    user_uuid TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 0 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kg_owner_profile_id, assigned_profile_id, user_uuid)
);

-- Fast lookup: "which KGs are assigned to this profile?"
CREATE INDEX IF NOT EXISTS idx_kg_assignments_assigned
    ON kg_profile_assignments(assigned_profile_id, user_uuid);

-- Fast lookup: "which profiles are assigned to this KG?"
CREATE INDEX IF NOT EXISTS idx_kg_assignments_owner
    ON kg_profile_assignments(kg_owner_profile_id, user_uuid);

-- Enforce: at most ONE active KG per profile per user
CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_one_active_per_profile
    ON kg_profile_assignments(assigned_profile_id, user_uuid) WHERE is_active = 1;
