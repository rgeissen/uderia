# Semantic Module
**Database**: `{ProductName}_Semantic`
**Purpose**: Machine-readable schema metadata so agents can discover entities, understand column meanings, and navigate relationships without human guidance.
**Core principle**: Entity = Table, Attribute = Column. Scale is hundreds of metadata rows (not millions). The `v_relationship_paths` recursive CTE is the critical agent navigation capability.

---

## Design Decisions

| Decision | Options | Choose when |
|---|---|---|
| Module deployment scope | All 6 / subset in data_product_map | Register PLANNED/DEPRECATED modules too |
| Relationship completeness | Intra-module + cross-module + reverse | Always register all directions agents traverse |
| Naming standard doc | Semantic.naming_standard rows | When deviating from defaults; document every convention |
| Optional tables | ontology, business_rule, data_contract_catalog | Complex taxonomies, validation rules |

---

## DDL

```sql
CREATE TABLE {ProductName}_Semantic.entity_metadata (
    entity_metadata_id   INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    entity_name          VARCHAR(128) NOT NULL,
    entity_description   VARCHAR(1000) NOT NULL,
    module_name          VARCHAR(50) NOT NULL,
    database_name        VARCHAR(128),
    table_name           VARCHAR(128) NOT NULL,
    view_name            VARCHAR(128),
    surrogate_key_column VARCHAR(128),
    natural_key_column   VARCHAR(128),
    temporal_pattern     VARCHAR(50),               -- 'BI_TEMPORAL', 'TYPE_2_SCD', 'NONE'
    current_flag_column  VARCHAR(128),
    deleted_flag_column  VARCHAR(128),
    industry_standard    VARCHAR(50),               -- 'FIBO', 'HL7', 'CUSTOM', etc.
    is_active            BYTEINT NOT NULL DEFAULT 1,
    created_at           TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    updated_at           TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (entity_metadata_id);
COMMENT ON TABLE {ProductName}_Semantic.entity_metadata IS
'Entity (table) catalog - describes all tables across all modules for agent discovery';

CREATE TABLE {ProductName}_Semantic.column_metadata (
    column_metadata_id  INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    database_name       VARCHAR(128) NOT NULL,
    table_name          VARCHAR(128) NOT NULL,
    column_name         VARCHAR(128) NOT NULL,
    business_description VARCHAR(1000),
    is_pii              BYTEINT NOT NULL DEFAULT 0,
    is_sensitive        BYTEINT NOT NULL DEFAULT 0,
    data_classification VARCHAR(50),               -- 'PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'
    is_required         BYTEINT NOT NULL DEFAULT 1,
    data_type           VARCHAR(100),
    allowed_values_json JSON,
    is_active           BYTEINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    updated_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (column_metadata_id);
COMMENT ON TABLE {ProductName}_Semantic.column_metadata IS
'Column (attribute) metadata - describes column meanings, PII flags, classifications, and validation rules';

CREATE TABLE {ProductName}_Semantic.naming_standard (
    naming_standard_id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    standard_type       VARCHAR(50) NOT NULL,       -- 'SUFFIX', 'PREFIX', 'PATTERN', 'ABBREVIATION'
    standard_value      VARCHAR(100) NOT NULL,
    meaning             VARCHAR(500) NOT NULL,
    usage_guidance      VARCHAR(1000),
    applies_to          VARCHAR(50),               -- 'TABLE', 'COLUMN', 'VIEW', 'ALL'
    examples            VARCHAR(1000),
    is_active           BYTEINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (naming_standard_id);
COMMENT ON TABLE {ProductName}_Semantic.naming_standard IS
'Naming convention standards - documents naming patterns for agent interpretation';

CREATE TABLE {ProductName}_Semantic.data_product_map (
    module_id          INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    module_name        VARCHAR(50) NOT NULL,
    module_description VARCHAR(1000),
    module_purpose     VARCHAR(500),
    database_name      VARCHAR(128) NOT NULL,
    naming_pattern     VARCHAR(20),               -- 'SEPARATE_DB' or 'SINGLE_DB_PREFIX'
    table_prefix       VARCHAR(10),
    primary_tables     VARCHAR(500),
    primary_views      VARCHAR(500),
    module_version     VARCHAR(20),
    deployment_status  VARCHAR(20),               -- 'DEPLOYED', 'PLANNED', 'DEPRECATED'
    deployed_dts       TIMESTAMP(6) WITH TIME ZONE,
    is_active          BYTEINT NOT NULL DEFAULT 1,
    created_at         TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    updated_at         TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (module_id);
COMMENT ON TABLE {ProductName}_Semantic.data_product_map IS
'Module registry - agents discover deployed modules and physical locations. Query this first for agent bootstrap.';

CREATE TABLE {ProductName}_Semantic.table_relationship (
    relationship_id      INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    relationship_name    VARCHAR(128) NOT NULL,
    relationship_description VARCHAR(1000),
    source_database      VARCHAR(128),
    source_table         VARCHAR(100) NOT NULL,
    source_column        VARCHAR(128) NOT NULL,
    target_database      VARCHAR(128),
    target_table         VARCHAR(100) NOT NULL,
    target_column        VARCHAR(128) NOT NULL,
    relationship_type    VARCHAR(50) NOT NULL,    -- 'FOREIGN_KEY', 'HIERARCHY', 'ASSOCIATIVE'
    cardinality          VARCHAR(20),             -- '1:1', '1:M', 'M:1', 'M:M'
    relationship_meaning VARCHAR(500),
    is_mandatory         BYTEINT NOT NULL DEFAULT 0,
    is_active            BYTEINT NOT NULL DEFAULT 1,
    created_at           TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    updated_at           TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (relationship_id);
COMMENT ON TABLE {ProductName}_Semantic.table_relationship IS
'Table-level relationship metadata - describes how tables join. COMPLETENESS IS CRITICAL: register intra-module FKs, reference lookups, cross-module joins, and reverse directions agents will traverse.';
```

---

## v_relationship_paths — Multi-Hop Path Discovery (TESTED ✅)

```sql
CREATE VIEW {ProductName}_Semantic.v_relationship_paths AS
WITH RECURSIVE relationship_paths (
    source_table, target_table, path_tables, path_joins, hop_count, path_description
) AS (
    -- Anchor: Forward (1-hop)
    SELECT
        source_table, target_table,
        source_table || ' -> ' || target_table AS path_tables,
        'JOIN ' || target_table || ' ON ' ||
            target_table || '.' || target_column || ' = ' ||
            source_table || '.' || source_column AS path_joins,
        1 AS hop_count,
        relationship_description AS path_description
    FROM {ProductName}_Semantic.table_relationship WHERE is_active = 1

    UNION ALL

    -- Anchor: Reversed (1-hop backward)
    SELECT
        target_table AS source_table, source_table AS target_table,
        target_table || ' -> ' || source_table AS path_tables,
        'JOIN ' || source_table || ' ON ' ||
            source_table || '.' || source_column || ' = ' ||
            target_table || '.' || target_column AS path_joins,
        1 AS hop_count,
        'REVERSE: ' || relationship_description AS path_description
    FROM {ProductName}_Semantic.table_relationship WHERE is_active = 1

    UNION ALL

    -- Recursive: Forward
    SELECT
        rp.source_table, tr.target_table,
        rp.path_tables || ' -> ' || tr.target_table AS path_tables,
        rp.path_joins || ' | ' ||
        'JOIN ' || tr.target_table || ' ON ' ||
            tr.target_table || '.' || tr.target_column || ' = ' ||
            tr.source_table || '.' || tr.source_column AS path_joins,
        rp.hop_count + 1 AS hop_count,
        rp.path_description || ' -> ' || tr.relationship_description AS path_description
    FROM relationship_paths rp
    INNER JOIN {ProductName}_Semantic.table_relationship tr
        ON tr.source_table = rp.target_table AND tr.is_active = 1
    WHERE rp.hop_count < 5
      AND rp.path_tables NOT LIKE '%' || tr.target_table || '%'

    UNION ALL

    -- Recursive: Backward
    SELECT
        rp.source_table, tr.source_table AS target_table,
        rp.path_tables || ' -> ' || tr.source_table AS path_tables,
        rp.path_joins || ' | ' ||
        'JOIN ' || tr.source_table || ' ON ' ||
            tr.source_table || '.' || tr.source_column || ' = ' ||
            tr.target_table || '.' || tr.target_column AS path_joins,
        rp.hop_count + 1 AS hop_count,
        rp.path_description || ' -> REVERSE: ' || tr.relationship_description AS path_description
    FROM relationship_paths rp
    INNER JOIN {ProductName}_Semantic.table_relationship tr
        ON tr.target_table = rp.target_table AND tr.is_active = 1
    WHERE rp.hop_count < 5
      AND rp.path_tables NOT LIKE '%' || tr.source_table || '%'
)
SELECT * FROM relationship_paths;
COMMENT ON VIEW {ProductName}_Semantic.v_relationship_paths IS
'Multi-hop relationship path discovery - finds indirect join paths up to 5 hops with bidirectional traversal and complete JOIN syntax';
```

### Agent path query example (TESTED ✅)
```sql
-- Find path from Party_H to Transaction_H
SELECT hop_count, path_tables, path_joins
FROM {ProductName}_Semantic.v_relationship_paths
WHERE source_table = 'Party_H' AND target_table = 'Transaction_H'
ORDER BY hop_count
QUALIFY ROW_NUMBER() OVER (ORDER BY hop_count) = 1;
```

---

## Integration Patterns

| Pattern | SQL |
|---|---|
| What entities exist? | `SELECT entity_name, module_name, table_name FROM entity_metadata WHERE is_active = 1` |
| What does column X mean? | `SELECT business_description, is_pii FROM column_metadata WHERE table_name = :t AND column_name = :c` |
| How do I join A to B? | `SELECT hop_count, path_joins FROM v_relationship_paths WHERE source_table = :a AND target_table = :b ORDER BY hop_count` |
| What modules are deployed? | `SELECT module_name, database_name, primary_tables FROM data_product_map WHERE is_active = 1` |

---

## Semantic Registration INSERTs

```sql
-- Register all 6 modules in data_product_map (example for Domain; repeat for each module)
INSERT INTO {ProductName}_Semantic.data_product_map
(module_name, module_description, module_purpose, database_name, naming_pattern,
 primary_tables, primary_views, module_version, deployment_status, is_active, created_at, updated_at)
VALUES
('Domain', 'Core business entities, source of truth', 'Business entity storage',
 '{ProductName}_Domain', 'SEPARATE_DB', NULL,
 '{Entity}_H, {Reference}_R', '{Entity}_Current',
 '2.4', 'DEPLOYED', 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));

-- Register entities in entity_metadata (example for Party_H)
INSERT INTO {ProductName}_Semantic.entity_metadata
(entity_name, entity_description, module_name, database_name, table_name,
 surrogate_key_column, natural_key_column, temporal_pattern,
 current_flag_column, deleted_flag_column, is_active, created_at, updated_at)
VALUES
('{Entity}', '{Entity} history with temporal tracking', 'Domain',
 '{ProductName}_Domain', '{Entity}_H',
 '{entity}_id', '{entity}_key', 'TYPE_2_SCD',
 'is_current', 'is_deleted', 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));

-- Register relationship (example; register ALL traversal directions)
INSERT INTO {ProductName}_Semantic.table_relationship
(relationship_name, relationship_description, source_database, source_table, source_column,
 target_database, target_table, target_column, relationship_type, cardinality,
 relationship_meaning, is_mandatory, is_active, created_at, updated_at)
VALUES
('{Entity1}_{Entity2}_FK', '{Entity1} belongs to {Entity2}',
 '{ProductName}_Domain', '{Entity1}_H', '{entity2}_id',
 '{ProductName}_Domain', '{Entity2}_H', '{entity2}_id',
 'FOREIGN_KEY', 'M:1', '{Entity1} references its parent {Entity2}',
 1, 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));
```

### Staleness detection
```sql
-- Entities in entity_metadata with no registered relationships (potential omission)
SELECT em.table_name
FROM {ProductName}_Semantic.entity_metadata em
WHERE em.is_active = 1
  AND NOT EXISTS (
    SELECT 1 FROM {ProductName}_Semantic.table_relationship r
    WHERE r.is_active = 1
      AND (r.source_table = em.table_name OR r.target_table = em.table_name)
  );

-- Verify specific traversal path exists before deployment
SELECT hop_count, path_tables, path_joins
FROM {ProductName}_Semantic.v_relationship_paths
WHERE source_table = '{TableA}' AND target_table = '{TableB}'
ORDER BY hop_count;
```

---

## Documentation Capture INSERTs

```sql
INSERT INTO {ProductName}_Memory.Module_Registry
(module_name, database_name, deployment_status, module_version, module_purpose,
 key_entities, dependencies, dependents, data_owner, technical_owner,
 version_date, is_current, valid_from, valid_to)
VALUES ('SEMANTIC', '{ProductName}_Semantic', 'DEPLOYED', '1.0.0',
 'Machine-readable schema metadata for agent SQL generation and entity discovery',
 'entity_metadata, column_metadata, table_relationship, data_product_map',
 'Memory (documentation tables must exist first)', 'All modules (register here)',
 '{owner}', '{tech_contact}', CURRENT_DATE, 1, CURRENT_DATE, DATE '9999-12-31');

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-SEMANTIC-001', 1,
 'Register all relationship traversal directions in table_relationship',
 'All expected agent traversal paths — forward and reverse — are explicitly registered',
 'Agents navigate data product via v_relationship_paths; missing rows = SQL generation failures',
 'Register only FK direction; auto-infer reverse',
 'Explicit registration ensures completeness; no hidden traversal logic in views',
 'Agents can navigate any expected path without human intervention',
 'ACCEPTED', 'INTEGRATION', 'SEMANTIC', '1.0.0',
 'table_relationship', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);
```

---

## Design Checklist (Semantic-specific)

- [ ] data_product_map has a row for every module considered (DEPLOYED / PLANNED / DEPRECATED)
- [ ] entity_metadata covers all tables across all deployed modules
- [ ] column_metadata covers all is_pii and is_sensitive columns at minimum
- [ ] table_relationship: all intra-module FKs, reference lookups, cross-module joins, reverse directions
- [ ] Run isolation check: no entity_metadata rows with zero table_relationship entries (unless deliberate)
- [ ] v_relationship_paths validated: run for every expected agent traversal pair
- [ ] ERD recipe QC-SEMANTIC-002 registered in Query_Cookbook
