# Domain Module
**Database**: `{ProductName}_Domain`
**Purpose**: Authoritative source of truth for core business entities, relationships, and reference data.
**Core principle**: Consistent patterns enable agent autonomy — agents learn once and apply everywhere.

---

## Design Decisions

| Decision | Options | Choose when |
|---|---|---|
| Surrogate key allocation | Keymap (recommended) / IDENTITY | FK-target entities → Keymap; reference/lookup tables → IDENTITY acceptable |
| Temporal strategy | Bi-temporal / Type 2 SCD / append-only | Bi-temporal when business-time corrections needed; Type 2 SCD for simpler history |
| Cross-module FK pattern | Pattern A (generic) / Pattern B (specific) | A when module references many entity types; B when few specific types |
| Column set | Minimal core / Extended metadata | Extended for audit-heavy, compliance domains; minimal for performance-critical |
| Natural key source | Source system key / Derived | Use source system key; document in Semantic naming_standard |

---

## DDL

### Entity History Table

```sql
CREATE TABLE {ProductName}_Domain.{Entity}_H (
    {entity}_id         BIGINT NOT NULL,
    -- Surrogate key: For FK-target entities, manage allocation separately (Keymap pattern)
    -- so the same {entity}_id spans ALL SCD versions of the same real-world entity.
    -- Never use GENERATED ALWAYS AS IDENTITY on _H tables for FK-target entities.
    -- Reference/lookup tables and non-FK-target detail entities may use IDENTITY.
    {entity}_key        VARCHAR(50) NOT NULL,
    -- Designer supplies temporal columns (bi-temporal or Type 2 SCD):
    -- valid_from_dts    TIMESTAMP(6) WITH TIME ZONE,
    -- valid_to_dts      TIMESTAMP(6) WITH TIME ZONE DEFAULT TIMESTAMP '9999-12-31 23:59:59+00:00',
    -- transaction_from_dts TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    -- transaction_to_dts   TIMESTAMP(6) WITH TIME ZONE DEFAULT TIMESTAMP '9999-12-31 23:59:59+00:00',
    is_current          BYTEINT NOT NULL DEFAULT 1,
    is_deleted          BYTEINT NOT NULL DEFAULT 0,
    -- Entity-specific business attributes (designer supplied)
    created_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    updated_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX ({entity}_id);
-- Non-UNIQUE PRIMARY INDEX required: multiple versions of same {entity}_id coexist
COMMENT ON TABLE {ProductName}_Domain.{Entity}_H IS
'{Entity} history table - all SCD versions for point-in-time reconstruction';
COMMENT ON COLUMN {ProductName}_Domain.{Entity}_H.{entity}_id IS
'Surrogate key - stable across all SCD versions. Allocated via Keymap to ensure same ID spans entity lifetime.';
COMMENT ON COLUMN {ProductName}_Domain.{Entity}_H.{entity}_key IS
'Natural business identifier from source system - used in user queries and external references';
COMMENT ON COLUMN {ProductName}_Domain.{Entity}_H.is_current IS
'1 = current active version, 0 = historical superseded version';
COMMENT ON COLUMN {ProductName}_Domain.{Entity}_H.is_deleted IS
'1 = logically deleted (retained for audit), 0 = active record';
```

### Reference Data Table

```sql
CREATE TABLE {ProductName}_Domain.{Reference}_R (
    {reference}_id      BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    {reference}_code    VARCHAR(20) NOT NULL,
    short_description   VARCHAR(100) NOT NULL,
    long_description    VARCHAR(500),
    effective_date      DATE NOT NULL,
    expiration_date     DATE NOT NULL DEFAULT DATE '9999-12-31',
    is_current          BYTEINT NOT NULL DEFAULT 1,
    parent_{reference}_id BIGINT,
    sort_order          INTEGER
) PRIMARY INDEX ({reference}_id);
-- Non-UNIQUE PRIMARY INDEX required: multiple temporal versions of same code coexist
COMMENT ON TABLE {ProductName}_Domain.{Reference}_R IS
'{Reference} reference data - controlled vocabulary with temporal validity periods';
COMMENT ON COLUMN {ProductName}_Domain.{Reference}_R.{reference}_code IS
'Short identifier used in domain tables; unique within effective period';
COMMENT ON COLUMN {ProductName}_Domain.{Reference}_R.expiration_date IS
'Default 9999-12-31 = indefinite validity';
```

### Relationship Table

```sql
CREATE TABLE {ProductName}_Domain.{Entity1}{Entity2}_H (
    {entity1}_{entity2}_id BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    {entity1}_id        BIGINT NOT NULL,
    {entity2}_id        BIGINT NOT NULL,
    -- Designer supplies temporal columns (same pattern as {Entity}_H)
    is_current          BYTEINT NOT NULL DEFAULT 1,
    is_deleted          BYTEINT NOT NULL DEFAULT 0,
    -- Relationship-specific attributes (designer supplied)
    created_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    updated_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX ({entity1}_id);
COMMENT ON TABLE {ProductName}_Domain.{Entity1}{Entity2}_H IS
'{Entity1} to {Entity2} relationship history - associative table with temporal tracking';
COMMENT ON COLUMN {ProductName}_Domain.{Entity1}{Entity2}_H.{entity1}_id IS
'Foreign key to {Entity1}_H.{entity1}_id';
COMMENT ON COLUMN {ProductName}_Domain.{Entity1}{Entity2}_H.{entity2}_id IS
'Foreign key to {Entity2}_H.{entity2}_id';
```

### Standard Views

```sql
CREATE VIEW {ProductName}_Domain.{Entity}_Current AS
SELECT * FROM {ProductName}_Domain.{Entity}_H
WHERE is_current = 1 AND is_deleted = 0;
COMMENT ON VIEW {ProductName}_Domain.{Entity}_Current IS
'Current active {entity} records - filters to is_current=1, is_deleted=0 for simplified querying';

CREATE VIEW {ProductName}_Domain.{Entity}_Enriched AS
SELECT e.*, [columns from related entities/reference data]
FROM {ProductName}_Domain.{Entity}_Current e
LEFT JOIN [common related tables];
COMMENT ON VIEW {ProductName}_Domain.{Entity}_Enriched IS
'{Entity} current records enriched with frequently joined reference data';
```

---

## Cross-Module FK Patterns

### Pattern A — Generic Reference (use when module references many entity types)

```sql
CREATE TABLE {ProductName}_OtherModule.SomeTable (
    some_table_id   BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    entity_id       BIGINT NOT NULL,       -- FK to any Domain entity surrogate key
    entity_type     VARCHAR(50) NOT NULL   -- 'PARTY', 'PRODUCT', 'AGREEMENT', etc.
) PRIMARY INDEX (some_table_id);

-- Join pattern
SELECT t.*, p.{entity}_key, p.[business_attr]
FROM {ProductName}_OtherModule.SomeTable t
INNER JOIN {ProductName}_Domain.{Entity}_H p
    ON p.{entity}_id = t.entity_id
   AND t.entity_type = '{ENTITY}'
   AND p.is_current = 1 AND p.is_deleted = 0;
```

### Pattern B — Specific Reference (use when module references few specific types)

```sql
CREATE TABLE {ProductName}_OtherModule.SomeTable (
    some_table_id   BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    party_id        BIGINT,    -- NULL if not party-related
    product_id      BIGINT     -- NULL if not product-related
) PRIMARY INDEX (some_table_id);
```

---

## Standard DML Patterns

### Current State Query

```sql
-- Current active entity
SELECT * FROM {ProductName}_Domain.{Entity}_H
WHERE is_current = 1 AND is_deleted = 0;

-- By natural key
SELECT * FROM {ProductName}_Domain.{Entity}_H
WHERE {entity}_key = '{KEY_VALUE}'
  AND is_current = 1 AND is_deleted = 0;
```

### Expire-Current → Insert-New (Type 2 SCD update)

```sql
-- Step 1: Expire current version
UPDATE {ProductName}_Domain.{Entity}_H
SET is_current   = 0,
    valid_to_dts = CURRENT_TIMESTAMP(6),
    updated_at   = CURRENT_TIMESTAMP(6)
WHERE {entity}_id = :{entity_id_value}
  AND is_current = 1;

-- Step 2: Insert new current version (reuse same {entity}_id from Keymap)
INSERT INTO {ProductName}_Domain.{Entity}_H
({entity}_id, {entity}_key, [business attrs],
 valid_from_dts, valid_to_dts, is_current, is_deleted, created_at, updated_at)
VALUES
(:{entity_id_value}, :{entity_key_value}, [new values],
 CURRENT_TIMESTAMP(6), TIMESTAMP '9999-12-31 23:59:59+00:00',
 1, 0, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));
```

### Staleness Detection

```sql
-- Entities with no registered Semantic relationships (potential omission)
SELECT em.table_name
FROM {ProductName}_Semantic.entity_metadata em
WHERE em.module_name = 'Domain' AND em.is_active = 1
  AND NOT EXISTS (
    SELECT 1 FROM {ProductName}_Semantic.table_relationship r
    WHERE r.is_active = 1
      AND (r.source_table = em.table_name OR r.target_table = em.table_name)
  );

-- Entities with no _Current view (pattern gap)
SELECT em.table_name
FROM {ProductName}_Semantic.entity_metadata em
WHERE em.module_name = 'Domain' AND em.is_active = 1
  AND em.view_name IS NULL;
```

---

## Semantic Registration INSERTs

```sql
-- Register Domain module
INSERT INTO {ProductName}_Semantic.data_product_map
(module_name, module_description, module_purpose, database_name, naming_pattern,
 primary_tables, primary_views, module_version, deployment_status, is_active, created_at, updated_at)
VALUES
('Domain', 'Core business entities and relationships', 'Authoritative entity storage',
 '{ProductName}_Domain', 'SEPARATE_DB',
 '{Entity}_H, {Reference}_R, {Entity1}{Entity2}_H',
 '{Entity}_Current, {Entity}_Enriched',
 '1.0', 'DEPLOYED', 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));

-- Register entity in entity_metadata
INSERT INTO {ProductName}_Semantic.entity_metadata
(entity_name, entity_description, module_name, database_name, table_name, view_name,
 surrogate_key_column, natural_key_column, temporal_pattern,
 current_flag_column, deleted_flag_column, is_active, created_at, updated_at)
VALUES
('{Entity}', '{Entity} history with Type 2 SCD temporal tracking', 'Domain',
 '{ProductName}_Domain', '{Entity}_H', '{Entity}_Current',
 '{entity}_id', '{entity}_key', 'TYPE_2_SCD',
 'is_current', 'is_deleted', 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));

-- Register FK relationship
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

---

## Documentation Capture INSERTs

```sql
INSERT INTO {ProductName}_Memory.Module_Registry
(module_name, database_name, deployment_status, module_version, module_purpose,
 key_entities, dependencies, dependents, data_owner, technical_owner,
 version_date, is_current, valid_from, valid_to)
VALUES ('DOMAIN', '{ProductName}_Domain', 'DEPLOYED', '1.0.0',
 'Authoritative business entities with temporal tracking for ML features and agent queries',
 '{Entity}_H, {Reference}_R, {Entity1}{Entity2}_H',
 'Memory (documentation tables), Semantic (entity registration)',
 'Search, Prediction, Observability (all join back to Domain)',
 '{data_owner}', '{tech_contact}',
 CURRENT_DATE, 1, CURRENT_DATE, DATE '9999-12-31');

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-DOMAIN-001', 1,
 'Surrogate key allocated via Keymap for FK-target entities',
 '{entity}_id is sourced from a separate Keymap table, not GENERATED ALWAYS AS IDENTITY',
 'Type 2 SCD creates multiple rows per entity; IDENTITY would generate a new surrogate per version',
 'IDENTITY on _H table; sequence in ETL',
 'Keymap ensures the same surrogate ID spans all SCD versions, enabling stable FK references from other modules',
 'All modules joining to Domain use stable {entity}_id across time',
 'ACCEPTED', 'ARCHITECTURE', 'DOMAIN', '1.0.0',
 '{Entity}_H', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-DOMAIN-002', 1,
 'Type 2 SCD temporal strategy for {Entity}_H',
 'Using Type 2 SCD: is_current flag + valid_from_dts/valid_to_dts per version row',
 'Need point-in-time reconstruction for ML feature generation',
 'Bi-temporal (adds transaction time); append-only (no versioning)',
 'Type 2 SCD sufficient for ML use cases; bi-temporal added complexity not required currently',
 'Point-in-time queries use valid_from_dts/valid_to_dts predicates; current queries use is_current=1',
 'ACCEPTED', 'ARCHITECTURE', 'DOMAIN', '1.0.0',
 '{Entity}_H', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);

INSERT INTO {ProductName}_Memory.Query_Cookbook
(recipe_id, recipe_version, recipe_title, recipe_description, recipe_sql,
 output_description, applicable_tables, use_case, complexity_level,
 source_module, module_version, created_by, valid_from, valid_to, is_current)
VALUES ('QC-DOMAIN-001', 1,
 'Current active entity lookup by natural key',
 'Retrieve current non-deleted version of an entity by its business key',
 'SELECT * FROM {ProductName}_Domain.{Entity}_H
WHERE {entity}_key = ''{KEY_VALUE}''
  AND is_current = 1 AND is_deleted = 0;',
 'Single current entity row with all attributes',
 '{Entity}_H', 'Entity lookup for agent queries and UI display',
 'BASIC', 'DOMAIN', '1.0.0', '{created_by}',
 CURRENT_DATE, DATE '9999-12-31', 1);
```

---

## Design Checklist (Domain-specific)

- [ ] All `_H` tables use non-UNIQUE `PRIMARY INDEX`
- [ ] FK-target entities: `{entity}_id BIGINT NOT NULL` sourced from Keymap (not IDENTITY)
- [ ] Reference/lookup tables: IDENTITY acceptable for surrogate allocation
- [ ] Every `_H` table has `is_current BYTEINT NOT NULL DEFAULT 1` and `is_deleted BYTEINT NOT NULL DEFAULT 0`
- [ ] Every entity has `{Entity}_Current` view (WHERE is_current=1 AND is_deleted=0)
- [ ] COMMENT ON TABLE and COMMENT ON COLUMN for all objects
- [ ] Cross-module FK pattern (A or B) chosen and applied consistently within each referencing module
- [ ] All relationships registered in Semantic.table_relationship (both directions)
- [ ] Expire-current → insert-new DML pattern used for SCD updates
- [ ] Semantic registration INSERTs present (data_product_map + entity_metadata per entity)
- [ ] Memory documentation INSERTs: 1 Module_Registry, ≥3 Design_Decision, ≥1 Query_Cookbook, ≥3 Business_Glossary
