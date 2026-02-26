-- ============================================================
-- Schema: Knowledge Graph
-- Version: 1.0
-- Description: Entity-relationship graph for context enrichment.
--              Scoped per profile_id + user_uuid for isolation.
--              Supports database topology, business concepts,
--              and abstract taxonomies.
-- ============================================================

-- Entities (nodes)
CREATE TABLE IF NOT EXISTS kg_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    user_uuid TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,              -- database, table, column, foreign_key, business_concept, taxonomy, metric, domain
    properties_json TEXT DEFAULT '{}',      -- JSON blob: description, data_type, business_meaning, etc.
    source TEXT NOT NULL DEFAULT 'manual',  -- manual, mcp_discovery, llm_inferred
    source_detail TEXT,                     -- e.g., MCP server ID or tool name
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(profile_id, user_uuid, name, entity_type)
);

-- Relationships (edges)
CREATE TABLE IF NOT EXISTS kg_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    user_uuid TEXT NOT NULL,
    source_entity_id INTEGER NOT NULL,
    target_entity_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,        -- contains, foreign_key, is_a, has_property, measures, derives_from, depends_on, relates_to
    cardinality TEXT,                       -- 1:1, 1:N, N:M, null
    metadata_json TEXT DEFAULT '{}',        -- JSON blob: description, confidence, evidence
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
    UNIQUE(profile_id, user_uuid, source_entity_id, target_entity_id, relationship_type)
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_kg_entities_profile_user
    ON kg_entities(profile_id, user_uuid);

CREATE INDEX IF NOT EXISTS idx_kg_entities_type
    ON kg_entities(profile_id, user_uuid, entity_type);

CREATE INDEX IF NOT EXISTS idx_kg_entities_name
    ON kg_entities(profile_id, user_uuid, name COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_kg_relationships_profile_user
    ON kg_relationships(profile_id, user_uuid);

CREATE INDEX IF NOT EXISTS idx_kg_relationships_source
    ON kg_relationships(source_entity_id);

CREATE INDEX IF NOT EXISTS idx_kg_relationships_target
    ON kg_relationships(target_entity_id);

CREATE INDEX IF NOT EXISTS idx_kg_relationships_type
    ON kg_relationships(profile_id, user_uuid, relationship_type);
