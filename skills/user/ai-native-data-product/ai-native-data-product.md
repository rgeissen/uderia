<!--
  base_content.md — ANDP Coordinator Context

  DISTILLATION HISTORY (derived from source documents):
  | Date       | Source document                              | Version | Notes                        |
  |------------|----------------------------------------------|---------|------------------------------|
  | 2026-04-21 | AI_Native_Data_Product_Master_Design.md      | 1.9     | Initial distillation         |
  | 2026-04-21 | Advocated_Data_Management_Standards.md       | —       | DDL conventions section      |

  DIRECT EDIT HISTORY (ANDP-specific sections — not derived from source docs):
  | Date       | Section                        | Change                                                              |
  |------------|--------------------------------|---------------------------------------------------------------------|
  | 2026-04-21 | Coordinator Operating Rules    | Added PROHIBITED/PERMITTED constraints to force slave invocation    |
  | 2026-04-21 | Coordinator Routing Table      | Added design-query patterns alongside usage-query patterns          |
-->

# AI-Native Data Product Design Standards — Coordinator Context

This content is loaded for ALL profiles in the ANDP agent pack, including the coordinator.
Module-specific content (full design standards) is injected per-param for each specialist slave.

---

## The Six Core Modules

| Module | Purpose | Database Pattern |
|--------|---------|-----------------|
| **Domain** | Core business entities, relationships, temporal history (source of truth for entity instances) | `{ProductName}_Domain` |
| **Semantic** | Machine-readable metadata: table relationships, column meanings, multi-hop path discovery, agent discovery protocol | `{ProductName}_Semantic` |
| **Search** | Vector embeddings for semantic similarity search; RAG retrieval patterns | `{ProductName}_Search` |
| **Prediction** | Engineered features (ML), model predictions, point-in-time feature reconstruction | `{ProductName}_Prediction` |
| **Observability** | Data quality metrics, change events, pipeline lineage, model performance monitoring | `{ProductName}_Observability` |
| **Memory** | Agent runtime state, learned strategies + Documentation Sub-Module (design decisions, glossary, query patterns) | `{ProductName}_Memory` |

---

## Deployment Order

| Phase | Modules | Reason |
|-------|---------|--------|
| **Phase 1** | Memory, Semantic | Must exist first — Memory hosts documentation tables; Semantic hosts discovery metadata for all subsequent modules |
| **Phase 2** | Domain, Observability | Domain provides entity foundation; Observability begins monitoring immediately |
| **Phase 3** | Search, Prediction | Both require Domain entities to embed or featurise |

---

## Physical Naming Convention

**Standard (recommended):** Separate databases per module — `{ProductName}_{Module}`

```
Customer360_Domain
Customer360_Semantic
Customer360_Prediction
Customer360_Search
Customer360_Memory
Customer360_Observability
```

**Alternative (small deployments):** Single database with module prefix — `{ProductName}` database, tables prefixed `D_`, `S_`, `P_`, `E_`, `M_`, `O_`

---

## Universal DDL Conventions

These apply in **every** module. Details and Teradata-specific implementation are in `Advocated_Data_Management_Standards.md`:

- **Booleans**: `BYTEINT NOT NULL DEFAULT 0|1`, column name starts with `is_`, filter as `= 1` / `= 0` (never `'Y'`/`'N'`)
- **Timestamps**: `TIMESTAMP(6) WITH TIME ZONE`, explicit UTC defaults (`DEFAULT CURRENT_TIMESTAMP(6)` or `DEFAULT TIMESTAMP '9999-12-31 23:59:59.999999+00:00'`)
- **Surrogate keys on Domain `_H` tables**: `BIGINT NOT NULL` via Keymap — manage surrogate allocation separately from the history table so the same ID spans all SCD versions of an entity. Never use `GENERATED ALWAYS AS IDENTITY` on `_H` tables.
- **Surrogate keys on all other module tables**: `INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY`
- **Primary index on temporal tables**: `PRIMARY INDEX` (never `UNIQUE PRIMARY INDEX` — uniqueness would prevent multiple SCD versions)
- **Documentation**: `COMMENT ON TABLE` and `COMMENT ON COLUMN` required on every object
- **Soft delete**: Create new SCD version with `is_current=1, is_deleted=1` — never UPDATE-only

---

## Cross-Module Entity Reference Pattern

All cross-module foreign keys reference the stable surrogate from the Domain Keymap:

```
Domain.{Entity}_Keymap  →  {entity}_id  (BIGINT, one per natural key, stable across SCD versions)
    ↑ referenced by
Prediction.{entity}_features.entity_id
Search.entity_embedding.entity_id
Observability.change_event.entity_id (optional)
```

No module duplicates content from Domain. All raw entity attributes are accessed via JOIN to `{Entity}_H`.

---

## Documentation Capture Protocol

All documentation tables live in `{ProductName}_Memory` (the Documentation Sub-Module).
Every module deployment generates:

| Record type | Table | Minimum | ID prefix |
|------------|-------|---------|-----------|
| Module registration | `Module_Registry` | 1 | `MOD-{MODULE}-{NNN}` |
| Architecture decisions | `Design_Decision` | 3 | `DD-{MODULE}-{NNN}` |
| Change history | `Change_Log` | 1 | `CL-{MODULE}-{NNN}` |
| Business terms | `Business_Glossary` | 3 | `BG-{MODULE}-{NNN}` |
| Query patterns | `Query_Cookbook` | 1 | `QC-{MODULE}-{NNN}` |
| Implementation notes | `Implementation_Note` | 0+ | `IN-{MODULE}-{NNN}` |

Module abbreviations: DOMAIN, SEMANTIC, SEARCH, PREDICTION, OBSERVABILITY, MEMORY

---

## Coordinator Operating Rules

**These are hard constraints, not guidelines.**

**PROHIBITED — never do these yourself:**
- Generate DDL (CREATE DATABASE, CREATE TABLE, CREATE VIEW)
- Write seed INSERT statements for any module table
- Produce ERDs or logical data models
- Design module schemas or table structures
- Answer any question that belongs to a single module specialist

**PERMITTED — coordinator handles these directly:**
- Requirements scoping and entity-to-module mapping (D1-type questions)
- Cross-module synthesis when multiple slaves have already responded
- Deployment sequence and deviations summary (D7-type sign-off)
- Clarifying questions before routing

**RULE: If a request involves designing, creating, or producing output for a specific module — invoke the slave. Do not produce the output yourself, even if you could.**

When you invoke a slave, pass the full product context (database name, entity names and columns, modules in scope) so the slave has everything it needs without asking the user to repeat it.

---

## Coordinator Routing Table

The ANDP coordinator uses this table to determine which slave profile(s) to invoke:

| Query pattern | Route to | Why exclusive |
|---------------|----------|---------------|
| **Design** Domain module DDL, tables, history tables, Keymap | ANDP-DOMAIN | Only ANDP-DOMAIN has the Domain design standard |
| Logical data model, entity definitions, ERD, entity attributes | ANDP-DOMAIN | Entity structure is Domain module territory |
| Entity state, current/historical entity records | ANDP-DOMAIN | Source of truth for entity instances; temporal history lives in `_H` tables |
| Point-in-time queries, SCD history, bi-temporal | ANDP-DOMAIN | Valid/transaction time tracking owned by Domain |
| Surrogate key assignment, Keymap pattern | ANDP-DOMAIN | Keymap is the surrogate allocation authority |
| **Design** Semantic module DDL, metadata tables, seed INSERTs | ANDP-SEMANTIC | Only ANDP-SEMANTIC has the Semantic design standard |
| "How do I join X to Y?", schema structure, multi-hop paths | ANDP-SEMANTIC | `table_relationship` and `v_relationship_paths` authority |
| "What does column X mean?", PII flags, column metadata | ANDP-SEMANTIC | `column_metadata` authority |
| "What entities/modules exist?", agent discovery bootstrap | ANDP-SEMANTIC | `data_product_map` and `entity_metadata` authority |
| Integration patterns, agent consumption sequence, data flow | ANDP-SEMANTIC | Discovery protocol and path traversal authority |
| **Design** Search module DDL, embedding tables | ANDP-SEARCH | Only ANDP-SEARCH has the Search design standard |
| Semantic similarity search, embeddings, RAG retrieval | ANDP-SEARCH | `entity_embedding` + `TD_VectorDistance` authority |
| Vector index strategy (KMEANS, HNSW) | ANDP-SEARCH | ANN index expertise lives here |
| **Design** Prediction module DDL, feature store tables | ANDP-PREDICTION | Only ANDP-PREDICTION has the Prediction design standard |
| Engineered features, feature values, ML model scores | ANDP-PREDICTION | Feature store authority |
| Point-in-time training datasets, no-leakage reconstruction | ANDP-PREDICTION | Temporal feature reconstruction expertise |
| **Design** Observability module DDL, lineage tables | ANDP-OBSERVABILITY | Only ANDP-OBSERVABILITY has the Observability design standard |
| Data quality scores, change events, ETL status/duration | ANDP-OBSERVABILITY | `change_event` and `lineage_run` authority |
| Pipeline lineage, data lineage graph, model performance SLA | ANDP-OBSERVABILITY | `data_lineage` / `lineage_run` split authority |
| **Design** Memory module DDL, documentation tables, seed INSERTs | ANDP-MEMORY | Only ANDP-MEMORY has the Memory design standard |
| Agent session context, learned strategies, user preferences | ANDP-MEMORY | Runtime memory tables authority |
| "Why was X designed this way?", architecture decisions | ANDP-MEMORY | `Design_Decision` (ADR) authority |
| Business glossary terms, proven query patterns, cookbooks | ANDP-MEMORY | Documentation Sub-Module authority |
| Cross-module design (e.g. Domain + Semantic together) | Both relevant slaves | Coordinator consults multiple slaves and synthesizes |

<!-- param:memory -->
# Memory Module
**Database**: `{ProductName}_Memory`
**Purpose**: Agent runtime state (sessions, interactions, learnings) + design memory (documentation sub-module) for this data product.
**Core principle**: "Big Questions, Small Answers" — store SQL/outcomes/metadata at TABLE level; never store individual instance IDs from query results.

---

## Design Decisions

| Decision | Options | Choose when |
|---|---|---|
| Session retention | 30 / 90 / 180 days | Compliance/audit window requirement |
| Strategy scope | USER / TEAM / ORGANIZATION | Agent sharing boundary |
| Doc tables to deploy | All 6 / subset | Complex products need all 6; simple can omit Implementation_Note |
| Learning source | Observability feedback loop | Closed-loop agent improvement cycle |

---

## Common Column Pattern — Privacy Scope (required on every runtime table)

```sql
scope_level      VARCHAR(20) NOT NULL,   -- 'USER', 'TEAM', 'ORGANIZATION', 'AGENT'
scope_identifier VARCHAR(100)            -- user_key, team_key, org_key, or agent_key
```

---

## DDL — Runtime Tables

```sql
CREATE TABLE {ProductName}_Memory.agent_session (
    session_id           INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    session_key          VARCHAR(100) NOT NULL,
    agent_key            VARCHAR(100) NOT NULL,
    user_key             VARCHAR(100),
    session_start_dts    TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    session_end_dts      TIMESTAMP(6) WITH TIME ZONE,
    session_status       VARCHAR(20),               -- 'ACTIVE', 'COMPLETED', 'ABANDONED'
    session_goal         VARCHAR(500),
    session_context_json JSON,
    scope_level          VARCHAR(20) NOT NULL,
    scope_identifier     VARCHAR(100),
    created_at           TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (session_id);
COMMENT ON TABLE {ProductName}_Memory.agent_session IS
'Agent session state - tracks active and historical sessions for continuity across interactions';

CREATE TABLE {ProductName}_Memory.agent_interaction (
    interaction_id    INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    session_id        INTEGER NOT NULL,
    interaction_seq   INTEGER NOT NULL,
    interaction_type  VARCHAR(50),                  -- 'QUERY', 'ACTION', 'DECISION', 'EXPLANATION'
    interaction_dts   TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    user_input        VARCHAR(4000),
    agent_response    VARCHAR(4000),
    action_taken      VARCHAR(500),
    referenced_tables VARCHAR(1000),                -- 'Domain.Party_H, Prediction.customer_features'
    sql_executed      VARCHAR(4000),
    query_result_count INTEGER,
    execution_time_ms  INTEGER,
    outcome_status    VARCHAR(20),                  -- 'SUCCESS', 'PARTIAL', 'FAILED'
    user_feedback     VARCHAR(20),                  -- 'POSITIVE', 'NEUTRAL', 'NEGATIVE'
    scope_level       VARCHAR(20) NOT NULL,
    scope_identifier  VARCHAR(100),
    created_at        TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (interaction_id);
COMMENT ON TABLE {ProductName}_Memory.agent_interaction IS
'Agent interaction log - records what agent did, which tables (TABLE LEVEL: database.table) were involved, and outcomes. referenced_tables is VARCHAR comma-separated - never stores individual record IDs.';

CREATE TABLE {ProductName}_Memory.learned_strategy (
    strategy_id          INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    strategy_name        VARCHAR(128) NOT NULL,
    strategy_description VARCHAR(1000),
    strategy_category    VARCHAR(50),               -- 'QUERY_OPTIMIZATION', 'FEATURE_SELECTION', 'ERROR_HANDLING'
    applies_to_scenario  VARCHAR(500),
    strategy_pattern     VARCHAR(4000),
    strategy_metadata_json JSON,
    discovered_dts       TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    discovered_by_agent  VARCHAR(100),
    times_used           INTEGER DEFAULT 0,
    success_rate         DECIMAL(5,4),
    scope_level          VARCHAR(20) NOT NULL,
    scope_identifier     VARCHAR(100),
    is_active            BYTEINT NOT NULL DEFAULT 1,
    is_validated         BYTEINT NOT NULL DEFAULT 0,
    validation_dts       TIMESTAMP(6) WITH TIME ZONE,
    created_at           TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    updated_at           TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (strategy_id);
COMMENT ON TABLE {ProductName}_Memory.learned_strategy IS
'Strategies learned by agents - successful patterns discovered through experience, scoped for sharing';

CREATE TABLE {ProductName}_Memory.user_preference (
    preference_id       INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    user_key            VARCHAR(100) NOT NULL,
    user_group          VARCHAR(100),
    preference_category VARCHAR(50),               -- 'REPORT_FORMAT', 'DATA_FILTER', 'AGGREGATION_LEVEL'
    preference_name     VARCHAR(128) NOT NULL,
    preference_value    VARCHAR(1000),
    preference_value_json JSON,
    applies_to_entity   VARCHAR(100),
    applies_to_scenario VARCHAR(500),
    learned_from_interactions INTEGER,
    confidence          DECIMAL(5,4),
    last_used_dts       TIMESTAMP(6) WITH TIME ZONE,
    scope_level         VARCHAR(20) DEFAULT 'USER',
    is_active           BYTEINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    updated_at          TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (preference_id);
COMMENT ON TABLE {ProductName}_Memory.user_preference IS
'User preferences learned from interactions - enables personalized agent behavior';

CREATE TABLE {ProductName}_Memory.discovered_pattern (
    pattern_id              INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    pattern_name            VARCHAR(128) NOT NULL,
    pattern_description     VARCHAR(1000),
    pattern_type            VARCHAR(50),           -- 'CORRELATION', 'TEMPORAL', 'TABLE_RELATIONSHIP', 'ANOMALY'
    pattern_definition_json JSON,
    sample_size             INTEGER,
    occurrences             INTEGER,
    confidence_score        DECIMAL(5,4),
    statistical_significance DECIMAL(5,4),
    discovered_dts          TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    discovered_by_agent     VARCHAR(100),
    is_validated            BYTEINT NOT NULL DEFAULT 0,
    involved_tables         VARCHAR(1000),         -- 'Domain.Party_H, Prediction.customer_features'
    scope_level             VARCHAR(20) NOT NULL,
    scope_identifier        VARCHAR(100),
    is_active               BYTEINT NOT NULL DEFAULT 1,
    created_at              TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (pattern_id);
COMMENT ON TABLE {ProductName}_Memory.discovered_pattern IS
'Patterns discovered by agents - stores metadata and statistical support only, NOT individual record details';
```

---

## DDL — Documentation Sub-Module

```sql
CREATE TABLE {ProductName}_Memory.Module_Registry (
    module_registry_key BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    module_name         VARCHAR(50) NOT NULL,
    database_name       VARCHAR(128) NOT NULL,
    deployment_status   VARCHAR(20) NOT NULL DEFAULT 'DEPLOYED', -- 'DEPLOYED', 'PLANNED', 'DEPRECATED'
    module_version      VARCHAR(20) NOT NULL,
    module_purpose      CLOB NOT NULL,
    module_scope        CLOB,
    key_entities        VARCHAR(500),
    dependencies        VARCHAR(500),
    dependents          VARCHAR(500),
    data_owner          VARCHAR(100),
    technical_owner     VARCHAR(100),
    refresh_frequency   VARCHAR(50),
    version_date        DATE NOT NULL,
    is_current          BYTEINT NOT NULL DEFAULT 1,
    valid_from          DATE NOT NULL,
    valid_to            DATE DEFAULT DATE '9999-12-31',
    created_timestamp   TIMESTAMP(6) WITH TIME ZONE,
    updated_timestamp   TIMESTAMP(6) WITH TIME ZONE
) PRIMARY INDEX (module_registry_key);
COMMENT ON TABLE {ProductName}_Memory.Module_Registry IS
'Version registry for all modules considered — DEPLOYED, PLANNED, and DEPRECATED. One row per module per version. Backbone for point-in-time documentation generation.';

CREATE TABLE {ProductName}_Memory.Design_Decision (
    decision_key            BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    decision_id             VARCHAR(50) NOT NULL,    -- DD-{MODULE}-{NNN}
    decision_version        INTEGER NOT NULL DEFAULT 1,
    decision_title          VARCHAR(200) NOT NULL,
    decision_description    CLOB,
    context                 CLOB,
    alternatives_considered CLOB,
    rationale               CLOB,
    consequences            CLOB,
    decision_status         VARCHAR(20) NOT NULL,    -- 'PROPOSED', 'ACCEPTED', 'SUPERSEDED', 'DEPRECATED'
    decision_category       VARCHAR(50) NOT NULL,    -- 'ARCHITECTURE', 'SCHEMA', 'NAMING', 'PERFORMANCE', 'SECURITY', 'INTEGRATION', 'OPERATIONAL'
    source_module           VARCHAR(50) NOT NULL,
    module_version          VARCHAR(20),
    affects_table           VARCHAR(200),
    decided_by              VARCHAR(100),
    decided_date            DATE,
    superseded_by           VARCHAR(50),
    valid_from              DATE NOT NULL,
    valid_to                DATE DEFAULT DATE '9999-12-31',
    is_current              BYTEINT NOT NULL DEFAULT 1,
    created_timestamp       TIMESTAMP(6) WITH TIME ZONE,
    updated_timestamp       TIMESTAMP(6) WITH TIME ZONE
) PRIMARY INDEX (decision_key);
COMMENT ON TABLE {ProductName}_Memory.Design_Decision IS
'Architecture Decision Records with version chain. decision_id format: DD-{MODULE}-{NNN}. decision_category values: ARCHITECTURE, SCHEMA, NAMING, PERFORMANCE, SECURITY, INTEGRATION, OPERATIONAL.';

CREATE TABLE {ProductName}_Memory.Business_Glossary (
    glossary_key      BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    term              VARCHAR(200) NOT NULL,
    term_category     VARCHAR(50) NOT NULL,          -- 'ENTITY', 'ATTRIBUTE', 'METRIC', 'BUSINESS_RULE', 'CLASSIFICATION', 'REFERENCE_CODE'
    definition        CLOB NOT NULL,
    business_context  CLOB,
    synonyms          VARCHAR(500),
    related_terms     VARCHAR(500),
    related_table     VARCHAR(200),
    related_column    VARCHAR(200),
    source_module     VARCHAR(50) NOT NULL,
    module_version    VARCHAR(20),
    is_active         BYTEINT NOT NULL DEFAULT 1,
    valid_from        DATE NOT NULL,
    valid_to          DATE DEFAULT DATE '9999-12-31',
    created_timestamp TIMESTAMP(6) WITH TIME ZONE,
    updated_timestamp TIMESTAMP(6) WITH TIME ZONE
) PRIMARY INDEX (glossary_key);
COMMENT ON TABLE {ProductName}_Memory.Business_Glossary IS
'Domain term definitions — reduces ambiguity for agents and team members, versioned per module';

CREATE TABLE {ProductName}_Memory.Query_Cookbook (
    recipe_key             BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    recipe_id              VARCHAR(50) NOT NULL,     -- QC-{MODULE}-{NNN}
    recipe_title           VARCHAR(200) NOT NULL,
    recipe_description     CLOB NOT NULL,
    use_case               VARCHAR(200) NOT NULL,
    target_module          VARCHAR(50) NOT NULL,     -- 'DOMAIN', 'SEMANTIC', 'SEARCH', 'MEMORY', 'PREDICTION', 'OBSERVABILITY', 'CROSS'
    sql_template           CLOB NOT NULL,
    parameter_descriptions CLOB,
    performance_notes      CLOB,
    complexity             VARCHAR(20) NOT NULL,     -- 'SIMPLE', 'MODERATE', 'COMPLEX', 'ADVANCED'
    source_module          VARCHAR(50) NOT NULL,
    module_version         VARCHAR(20),
    is_active              BYTEINT NOT NULL DEFAULT 1,
    valid_from             DATE NOT NULL,
    valid_to               DATE DEFAULT DATE '9999-12-31',
    created_timestamp      TIMESTAMP(6) WITH TIME ZONE,
    updated_timestamp      TIMESTAMP(6) WITH TIME ZONE
) PRIMARY INDEX (recipe_key);
COMMENT ON TABLE {ProductName}_Memory.Query_Cookbook IS
'Proven query patterns — agents use as starting points. recipe_id: QC-{MODULE}-{NNN}. sql_template uses :parameter placeholders.';

CREATE TABLE {ProductName}_Memory.Implementation_Note (
    note_key          BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    note_id           VARCHAR(50) NOT NULL,          -- IN-{MODULE}-{NNN}
    note_title        VARCHAR(200) NOT NULL,
    note_content      CLOB NOT NULL,
    note_category     VARCHAR(50) NOT NULL,          -- 'DEPLOYMENT', 'WORKAROUND', 'KNOWN_ISSUE', 'PERFORMANCE_TIP', 'OPERATIONAL', 'SECURITY'
    severity          VARCHAR(20),                   -- 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL' (NULL for non-issues)
    affects_table     VARCHAR(200),
    resolution_status VARCHAR(20),                   -- 'OPEN', 'IN_PROGRESS', 'RESOLVED', 'WONT_FIX'
    resolution_notes  CLOB,
    source_module     VARCHAR(50) NOT NULL,
    module_version    VARCHAR(20),
    is_active         BYTEINT NOT NULL DEFAULT 1,
    valid_from        DATE NOT NULL,
    valid_to          DATE DEFAULT DATE '9999-12-31',
    created_timestamp TIMESTAMP(6) WITH TIME ZONE,
    updated_timestamp TIMESTAMP(6) WITH TIME ZONE
) PRIMARY INDEX (note_key);
COMMENT ON TABLE {ProductName}_Memory.Implementation_Note IS
'Operational knowledge — workarounds, known issues, deployment tips. note_id: IN-{MODULE}-{NNN}.';

CREATE TABLE {ProductName}_Memory.Change_Log (
    change_key          BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
    change_id           VARCHAR(50) NOT NULL,        -- CL-{MODULE}-{NNN}
    version_number      VARCHAR(20) NOT NULL,
    change_title        VARCHAR(200) NOT NULL,
    change_description  CLOB NOT NULL,
    change_type         VARCHAR(30) NOT NULL,        -- 'INITIAL_RELEASE', 'SCHEMA_CHANGE', 'FEATURE_ADDITION', 'BUG_FIX', 'PERFORMANCE', 'DEPRECATION'
    change_category     VARCHAR(50) NOT NULL,        -- 'BREAKING', 'NON_BREAKING', 'ADDITIVE', 'DEPRECATION'
    source_module       VARCHAR(50) NOT NULL,
    affects_table       VARCHAR(200),
    migration_steps     CLOB,
    rollback_steps      CLOB,
    related_decision_id VARCHAR(50),
    deployed_date       DATE,
    deployed_by         VARCHAR(100),
    deployment_status   VARCHAR(20) NOT NULL,        -- 'PLANNED', 'DEPLOYED', 'ROLLED_BACK'
    created_timestamp   TIMESTAMP(6) WITH TIME ZONE
) PRIMARY INDEX (change_key);
COMMENT ON TABLE {ProductName}_Memory.Change_Log IS
'Versioned change history — each row is a point-in-time event. change_id: CL-{MODULE}-{NNN}.';
```

---

## Standard View

```sql
CREATE VIEW {ProductName}_Memory.v_interactions_summary AS
SELECT ai.session_id, ai.interaction_seq, ai.interaction_type,
       ai.user_input, ai.action_taken, ai.sql_executed,
       ai.query_result_count, ai.execution_time_ms,
       ai.outcome_status, ai.user_feedback,
       ai.referenced_tables, ai.scope_level, ai.scope_identifier, ai.interaction_dts
FROM {ProductName}_Memory.agent_interaction ai;
COMMENT ON VIEW {ProductName}_Memory.v_interactions_summary IS
'Agent interaction summary - simplified view for LIKE filtering on referenced_tables VARCHAR column';
```

Additional views: `v_Current_Decisions`, `v_Module_Registry_Current`, `v_Glossary_Active`, `v_Cookbook_Active`, `v_Issues_Open`, `v_Change_History`, `v_Documentation_Search`

---

## Entity Reference Pattern — TESTED ✅

`referenced_tables` / `involved_tables`: VARCHAR(1000), format `'Domain.Party_H, Prediction.customer_features'`

```sql
-- Find all decisions related to Party table (TESTED ✅)
SELECT ai.interaction_seq, ai.user_input, ai.action_taken,
       ai.outcome_status, ai.sql_executed, ai.query_result_count, ai.referenced_tables
FROM {ProductName}_Memory.agent_interaction ai
WHERE ai.referenced_tables LIKE '%Domain.Party_H%'
  AND ai.interaction_type = 'DECISION'
ORDER BY ai.interaction_dts DESC;

-- Find patterns discovered about Party table (TESTED ✅)
SELECT dp.pattern_name, dp.pattern_description, dp.sample_size,
       dp.confidence_score, dp.involved_tables
FROM {ProductName}_Memory.discovered_pattern dp
WHERE dp.involved_tables LIKE '%Party_H%'
  AND dp.is_validated = 1
ORDER BY dp.confidence_score DESC;
```

---

## DML Patterns

### Expire-current → insert-new (Design_Decision version chain)
```sql
UPDATE {ProductName}_Memory.Design_Decision
SET valid_to = CURRENT_DATE, is_current = 0, updated_timestamp = CURRENT_TIMESTAMP(6)
WHERE decision_id = 'DD-MEMORY-001' AND is_current = 1;

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, ..., valid_from, valid_to, is_current)
VALUES ('DD-MEMORY-001', 2, '{updated_title}', ..., CURRENT_DATE, DATE '9999-12-31', 1);
```

### Staleness detection
```sql
-- Sessions older than retention window
SELECT session_id, session_key, agent_key, session_end_dts
FROM {ProductName}_Memory.agent_session
WHERE session_status = 'COMPLETED'
  AND session_end_dts < CURRENT_TIMESTAMP(6) - INTERVAL '90' DAY;

-- Decisions not reviewed in over a year
SELECT decision_id, decision_title, decided_date
FROM {ProductName}_Memory.Design_Decision
WHERE is_current = 1 AND decided_date < CURRENT_DATE - 365;
```

---

## Semantic Registration INSERTs

```sql
INSERT INTO {ProductName}_Semantic.data_product_map
(module_name, module_description, module_purpose, database_name, naming_pattern,
 primary_tables, primary_views, module_version, deployment_status, is_active, created_at, updated_at)
VALUES (
 'Memory', 'Agent runtime state, learned strategies, and design documentation',
 'Agent learning, continuity, and design memory for this data product',
 '{ProductName}_Memory', 'SEPARATE_DB',
 'agent_session, agent_interaction, learned_strategy, Module_Registry, Design_Decision',
 'v_interactions_summary, v_Current_Decisions',
 '1.7', 'DEPLOYED', 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));
```

### Agent discovery sequence
```sql
-- 1. Discover deployed modules
SELECT module_name, database_name, primary_tables
FROM {ProductName}_Semantic.data_product_map WHERE is_active = 1;

-- 2. Explore design decisions
SELECT decision_id, decision_title, decision_category, source_module
FROM {ProductName}_Memory.Design_Decision WHERE is_current = 1
ORDER BY source_module, decision_id;

-- 3. Find query patterns
SELECT recipe_id, recipe_title, use_case, complexity, sql_template
FROM {ProductName}_Memory.Query_Cookbook WHERE is_active = 1
ORDER BY complexity;
```

---

## Documentation Capture INSERTs (minimum required)

```sql
-- Module registration (1 per module)
INSERT INTO {ProductName}_Memory.Module_Registry
(module_name, database_name, deployment_status, module_version, module_purpose,
 key_entities, dependencies, dependents, data_owner, technical_owner,
 version_date, is_current, valid_from, valid_to)
VALUES ('MEMORY', '{ProductName}_Memory', 'DEPLOYED', '1.0.0',
 'Agent runtime state and design documentation',
 'agent_session, agent_interaction, learned_strategy, user_preference, discovered_pattern',
 'None', 'All modules (host documentation)', '{owner}', '{tech_contact}',
 CURRENT_DATE, 1, CURRENT_DATE, DATE '9999-12-31');

-- Decision (3+ per module; temporal fields: valid_from=CURRENT_DATE, valid_to=DATE 9999-12-31, is_current=1)
INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-MEMORY-001', 1,
 'Store table references as VARCHAR comma-separated list',
 'referenced_tables and involved_tables use VARCHAR(1000) comma-separated database.table names',
 'Must support LIKE queries without JSON parsing overhead',
 'JSON array, separate FK table',
 'Simple LIKE queries on VARCHAR are sufficient; parse in application for aggregation',
 'Enables fast SQL filtering; table-level granularity aligns with Big Questions principle',
 'ACCEPTED', 'SCHEMA', 'MEMORY', '1.0.0',
 'agent_interaction, discovered_pattern',
 '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);

-- ERD recipe (mandatory for every data product — QC-SEMANTIC-002)
INSERT INTO {ProductName}_Memory.Query_Cookbook
(recipe_id, recipe_title, recipe_description, use_case, target_module,
 sql_template, parameter_descriptions, performance_notes, complexity,
 source_module, module_version, is_active, valid_from, valid_to)
VALUES ('QC-SEMANTIC-002',
 'Generate entity-relationship diagram from table_relationship',
 'Queries Semantic table_relationship to produce a complete ER listing. Output as Mermaid erDiagram or plain listing.',
 'Data model documentation, onboarding, design review',
 'SEMANTIC',
 'SELECT r.from_database, r.from_table, r.from_column, r.relationship_type, r.cardinality,
       r.to_database, r.to_table, r.to_column, r.join_type, r.is_mandatory, r.relationship_desc
FROM {ProductName}_Semantic.table_relationship r
WHERE r.is_active = 1 ORDER BY r.from_table, r.to_table;',
 'Replace {ProductName} with actual product name before executing.',
 'Lightweight query on small metadata table — no performance concerns.',
 'SIMPLE', 'SEMANTIC', :module_version, 1, CURRENT_DATE, DATE '9999-12-31');
```

---

## Design Checklist (Memory-specific)

- [ ] Privacy scope columns (scope_level, scope_identifier) on every runtime table
- [ ] referenced_tables and involved_tables use VARCHAR comma-separated (never individual IDs)
- [ ] No instance IDs stored — only aggregate counts and SQL text
- [ ] Retention windows defined for all 5 runtime tables
- [ ] Module_Registry row exists for every module considered (DEPLOYED / PLANNED / DEPRECATED)
- [ ] Design_Decision entries for deferred/excluded modules and all standards deviations
- [ ] ERD recipe QC-SEMANTIC-002 inserted with correct {ProductName}
- [ ] Min. 1 cross-module Query_Cookbook recipe per deployed module pair
- [ ] All doc tables in same `{ProductName}_Memory` database (no separate bootstrap)
<!-- /param:memory -->

<!-- param:semantic -->
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
<!-- /param:semantic -->

<!-- param:domain -->
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
<!-- /param:domain -->

<!-- param:observability -->
# Observability Module
**Database**: `{ProductName}_Observability` (tables) + views deployed to `{ProductName}_Semantic`
**Purpose**: Monitor data product health — change tracking, quality metrics, lineage, model performance, agent outcomes.
**Core principle**: Store events and metrics, NOT business data. Table-level tracking (not per-record). Separate lineage definition from execution.

---

## Design Decisions

| Decision | Options | Choose when |
|---|---|---|
| Lineage model | data_lineage (definition) + lineage_run (execution) | Always — two-table split is mandatory |
| Change tracking granularity | Table-level aggregates | Always — one event per batch, NOT per row |
| tables_accessed / columns_changed | Comma-separated VARCHAR | Reference table names, not individual row keys |
| Retention: data_lineage | Life of data product | Blueprint — always needed for discovery |
| Retention: lineage_run | 90–365 days (configurable) | Event-scale volume; older runs can be archived |
| OpenLineage alignment | openlineage_job_name + openlineage_run_id | Fill when emitting to Marquez / Amundsen |

---

## DDL

### change_event

```sql
CREATE TABLE {ProductName}_Observability.change_event (
    change_event_id  INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    database_name    VARCHAR(128),
    table_name       VARCHAR(128) NOT NULL,
    change_type      VARCHAR(20) NOT NULL,   -- 'INSERT','UPDATE','DELETE','MERGE','TRUNCATE'
    change_dts       TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    changed_by       VARCHAR(100) NOT NULL,
    change_reason    VARCHAR(500),
    change_source    VARCHAR(50),            -- 'ETL','API','MANUAL','AGENT'
    records_affected INTEGER,
    columns_changed  VARCHAR(1000),          -- Comma-separated column names
    batch_key        VARCHAR(100),
    job_name         VARCHAR(200),
    created_at       TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (change_event_id);
COMMENT ON TABLE {ProductName}_Observability.change_event IS
'Table-level change event tracking - aggregate audit trail, NOT individual record details. One event per batch/job run.';
```

### data_quality_metric

```sql
CREATE TABLE {ProductName}_Observability.data_quality_metric (
    quality_metric_id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    database_name     VARCHAR(128),
    table_name        VARCHAR(128) NOT NULL,
    column_name       VARCHAR(128),         -- NULL for table-level metrics
    metric_name       VARCHAR(128) NOT NULL, -- COMPLETENESS, VALIDITY, UNIQUENESS, TIMELINESS, CONSISTENCY
    metric_value      DECIMAL(10,4),        -- Typically 0.0–1.0
    metric_category   VARCHAR(50),
    measured_dts      TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    quality_threshold DECIMAL(5,4),
    is_threshold_met  BYTEINT NOT NULL DEFAULT 0,
    sample_size       INTEGER,
    created_at        TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (quality_metric_id);
COMMENT ON TABLE {ProductName}_Observability.data_quality_metric IS
'Data quality metrics by table/column over time - enables quality trend monitoring and threshold alerting';
```

### data_lineage (Definitional — one row per declared flow)

```sql
CREATE TABLE {ProductName}_Observability.data_lineage (
    lineage_id            INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    source_database       VARCHAR(128),
    source_table          VARCHAR(100),
    source_system         VARCHAR(100),     -- External origin; NULL if internal
    target_database       VARCHAR(128),
    target_table          VARCHAR(100) NOT NULL,
    job_name              VARCHAR(200),
    transformation_type   VARCHAR(50),      -- ETL, FEATURE_ENG, AGGREGATION, JOIN, EMBEDDING_GEN
    transformation_logic  VARCHAR(4000),
    openlineage_job_name  VARCHAR(200),
    openlineage_namespace VARCHAR(200),
    is_active             BYTEINT NOT NULL DEFAULT 1,
    registered_dts        TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    retired_dts           TIMESTAMP(6) WITH TIME ZONE,
    created_at            TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (lineage_id);
COMMENT ON TABLE {ProductName}_Observability.data_lineage IS
'Definitional lineage — declares structural data flows (source→job→target). One row per unique flow. Changes only when pipeline design changes. Execution tracked in lineage_run.';
```

### lineage_run (Operational — one row per execution)

```sql
CREATE TABLE {ProductName}_Observability.lineage_run (
    lineage_run_id       INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    lineage_id           INTEGER NOT NULL,  -- FK → data_lineage.lineage_id
    run_dts              TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    run_status           VARCHAR(20) NOT NULL,  -- SUCCESS, FAILED, PARTIAL, RUNNING
    run_duration_ms      INTEGER,
    records_read         INTEGER,
    records_written      INTEGER,
    records_rejected     INTEGER,
    batch_key            VARCHAR(100),
    job_name             VARCHAR(200),     -- Denormalised for fast filtering
    openlineage_run_id   VARCHAR(200),
    error_message        VARCHAR(2000),
    created_at           TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (lineage_run_id);
COMMENT ON TABLE {ProductName}_Observability.lineage_run IS
'Operational lineage execution log — one row per execution of a declared flow. Event-scale volume. Independent retention from data_lineage.';
```

### model_performance

```sql
CREATE TABLE {ProductName}_Observability.model_performance (
    performance_id  INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    model_key       VARCHAR(100) NOT NULL,
    model_version   VARCHAR(20) NOT NULL,
    metric_name     VARCHAR(128) NOT NULL,  -- ACCURACY, PRECISION, RECALL, AUC, LATENCY_MS, DRIFT_SCORE
    metric_value    DECIMAL(10,6),
    evaluation_dts  TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    sample_size     INTEGER,
    is_sla_met      BYTEINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (performance_id);
COMMENT ON TABLE {ProductName}_Observability.model_performance IS
'ML model performance metrics over time — tracks accuracy, latency, and drift for monitoring and SLA alerting';
```

### agent_outcome

```sql
CREATE TABLE {ProductName}_Observability.agent_outcome (
    outcome_id        INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    agent_key         VARCHAR(100) NOT NULL,
    session_key       VARCHAR(100),
    action_type       VARCHAR(50) NOT NULL,   -- QUERY, RECOMMENDATION, DECISION, PREDICTION
    action_dts        TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    tables_accessed   VARCHAR(1000),          -- Comma-separated database.table names (table-level only)
    outcome_status    VARCHAR(20) NOT NULL,   -- SUCCESS, PARTIAL, FAILED
    user_feedback     VARCHAR(20),            -- POSITIVE, NEUTRAL, NEGATIVE, CORRECTION
    execution_time_ms INTEGER,
    records_processed INTEGER,
    created_at        TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (outcome_id);
COMMENT ON TABLE {ProductName}_Observability.agent_outcome IS
'Agent action outcomes and user feedback — enables closed-loop learning by feeding Memory.learned_strategy';
```

---

## Semantic Views (deploy to {ProductName}_Semantic)

### lineage_graph — Graph-Ready Edge List

```sql
REPLACE VIEW {ProductName}_Semantic.lineage_graph AS
/*
 * lineage_graph
 * ───────────────
 * Graph-ready edge list for data lineage with ETL jobs surfaced as
 * first-class nodes. Reads from the DEFINITIONAL data_lineage table
 * (not the execution log) — produces one stable edge per declared flow.
 *
 * Each data_lineage row becomes two edges:
 *   Leg 1: source_table  → job_name   (ETL_INPUT)
 *   Leg 2: job_name      → target_table (ETL_OUTPUT)
 *
 * IMPORTANT: All literal strings ('', 'ETL_INPUT', 'Job', etc.) and
 * job_name columns that appear on only one leg of the UNION ALL must
 * be explicitly CAST to a sufficient VARCHAR width. Without CASTs,
 * Teradata infers the column type from Leg 1 — a literal '' becomes
 * VARCHAR(0), truncating Leg 2's actual container names to empty.
 * Similarly, 'ETL_INPUT' (9 chars) truncates 'ETL_OUTPUT' to 'ETL_OUTPU'.
 */
LOCKING ROW FOR ACCESS

    /* ══════════════════════════════════════════════════════════════
     *  Leg 1: Source Table → Job (ETL_INPUT)
     * ══════════════════════════════════════════════════════════════ */
    SELECT
         COALESCE(dl.source_database, '') || '.' || dl.source_table  AS Src_Object_Name_FQ
        ,COALESCE(dl.source_database, '')                            AS Src_Container_Name
        ,dl.source_table                                             AS Src_Object_Name
        /* ── Source Object Type from DBC.TablesV ─────────────────── */
        ,CAST(CASE WHEN Src_Obj.TableKind IS NOT NULL
              THEN CASE Src_Obj.TableKind
                       WHEN 'T' THEN 'Table'
                       WHEN 'O' THEN 'No PI Table'
                       WHEN 'V' THEN 'View'
                       WHEN 'M' THEN 'Macro'
                       WHEN 'P' THEN 'Procedure'
                       WHEN 'E' THEN 'Procedure'
                       WHEN 'G' THEN 'Trigger'
                       WHEN 'I' THEN 'Join Index'
                       WHEN 'A' THEN 'Function'
                       WHEN 'F' THEN 'Function'
                       WHEN 'R' THEN 'Function'
                       WHEN 'B' THEN 'Function'
                       WHEN 'S' THEN 'Function'
                       WHEN 'N' THEN 'Hash Index'
                       WHEN 'K' THEN 'Foreign Server'
                       WHEN 'X' THEN 'Authorization'
                       WHEN 'U' THEN 'Type'
                       WHEN 'C' THEN 'Table Operator'
                       WHEN 'D' THEN 'JAR'
                       WHEN 'H' THEN 'Method'
                       WHEN 'J' THEN 'Journal'
                       WHEN 'L' THEN 'SQL-MR function - Table Operator'
                       WHEN 'Q' THEN 'Queue Table'
                       WHEN 'Y' THEN 'GLOP Set'
                       WHEN 'Z' THEN 'UIF'
                       WHEN '1' THEN 'Schema'
                       WHEN '2' THEN 'Function Alias'
                       WHEN '3' THEN 'UAF - Unbounded Array Framework'
                       ELSE 'Unknown: ' || Src_Obj.TableKind
                   END
              ELSE 'Unknown'
         END AS VARCHAR(30))                                             AS Src_Kind
        ,COALESCE(dl.source_database, '') || '.' || dl.source_table
         || '0A'xc || ' [' || Src_Kind || ']'                        AS Src_Display_Name
        /* ── CAST literals to prevent UNION ALL type-width truncation ── */
        ,CAST('ETL_INPUT' AS VARCHAR(12))                            AS Edge_Relationship
        ,dl.transformation_type                                      AS Transformation_Type
        ,dl.transformation_logic                                     AS Transformation_Logic
        ,dl.lineage_id                                               AS Lineage_ID
        /* ── Target is the Job ───────────────────────────────────── */
        ,CAST(dl.job_name AS VARCHAR(128))                           AS Tgt_Object_Name_FQ
        ,CAST('' AS VARCHAR(128))                                    AS Tgt_Container_Name
        ,dl.job_name                                                 AS Tgt_Object_Name
        ,CAST('Job' AS VARCHAR(30))                                  AS Tgt_Kind
        ,dl.job_name || '0A'xc || ' [' || Tgt_Kind || ']'            AS Tgt_Display_Name
    FROM
        {ProductName}_Observability.data_lineage AS dl
    LEFT OUTER JOIN DBC.TablesV AS Src_Obj
      ON  Src_Obj.DatabaseName = dl.source_database
      AND Src_Obj.TableName    = dl.source_table
    WHERE
        dl.is_active = 1

    UNION ALL

    /* ══════════════════════════════════════════════════════════════
     *  Leg 2: Job → Target Table (ETL_OUTPUT)
     * ══════════════════════════════════════════════════════════════ */
    SELECT
        /* ── CAST literals to match Leg 1 column widths ────────────── */
        CAST(dl.job_name AS VARCHAR(128))                            AS Src_Object_Name_FQ
        ,CAST('' AS VARCHAR(128))                                    AS Src_Container_Name
        ,dl.job_name                                                 AS Src_Object_Name
        ,CAST('Job' AS VARCHAR(30))                                  AS Src_Kind
        ,dl.job_name || '0A'xc || ' [' || Src_Kind || ']'            AS Src_Display_Name
        ,CAST('ETL_OUTPUT' AS VARCHAR(12))                           AS Edge_Relationship
        ,dl.transformation_type                                      AS Transformation_Type
        ,dl.transformation_logic                                     AS Transformation_Logic
        ,dl.lineage_id                                               AS Lineage_ID
        ,COALESCE(dl.target_database, '') || '.' || dl.target_table  AS Tgt_Object_Name_FQ
        ,COALESCE(dl.target_database, '')                            AS Tgt_Container_Name
        ,dl.target_table                                             AS Tgt_Object_Name
        /* ── Target Object Type from DBC.TablesV ─────────────────── */
        ,CAST(CASE WHEN Tgt_Obj.TableKind IS NOT NULL
              THEN CASE Tgt_Obj.TableKind
                       WHEN 'T' THEN 'Table'
                       WHEN 'O' THEN 'No PI Table'
                       WHEN 'V' THEN 'View'
                       WHEN 'M' THEN 'Macro'
                       WHEN 'P' THEN 'Procedure'
                       WHEN 'E' THEN 'Procedure'
                       WHEN 'G' THEN 'Trigger'
                       WHEN 'I' THEN 'Join Index'
                       WHEN 'A' THEN 'Function'
                       WHEN 'F' THEN 'Function'
                       WHEN 'R' THEN 'Function'
                       WHEN 'B' THEN 'Function'
                       WHEN 'S' THEN 'Function'
                       WHEN 'N' THEN 'Hash Index'
                       WHEN 'K' THEN 'Foreign Server'
                       WHEN 'X' THEN 'Authorization'
                       WHEN 'U' THEN 'Type'
                       WHEN 'C' THEN 'Table Operator'
                       WHEN 'D' THEN 'JAR'
                       WHEN 'H' THEN 'Method'
                       WHEN 'J' THEN 'Journal'
                       WHEN 'L' THEN 'SQL-MR function - Table Operator'
                       WHEN 'Q' THEN 'Queue Table'
                       WHEN 'Y' THEN 'GLOP Set'
                       WHEN 'Z' THEN 'UIF'
                       WHEN '1' THEN 'Schema'
                       WHEN '2' THEN 'Function Alias'
                       WHEN '3' THEN 'UAF - Unbounded Array Framework'
                       ELSE 'Unknown: ' || Tgt_Obj.TableKind
                   END
              ELSE 'Unknown'
         END AS VARCHAR(30))                                             AS Tgt_Kind
        ,COALESCE(dl.target_database, '') || '.' || dl.target_table
         || '0A'xc || ' [' || Tgt_Kind || ']'                        AS Tgt_Display_Name
    FROM
        {ProductName}_Observability.data_lineage AS dl
    LEFT OUTER JOIN DBC.TablesV AS Tgt_Obj
      ON  Tgt_Obj.DatabaseName = dl.target_database
      AND Tgt_Obj.TableName    = dl.target_table
    WHERE
        dl.is_active = 1
;
COMMENT ON VIEW {ProductName}_Semantic.lineage_graph IS
'Graph-ready edge list — each data_lineage row produces two edges (source→job, job→target). Reads definitional table only; stable regardless of run frequency.';
```

### lineage_run_latest — Latest Execution per Flow

```sql
REPLACE VIEW {ProductName}_Semantic.lineage_run_latest AS
LOCKING ROW FOR ACCESS
SELECT
     dl.lineage_id
    ,dl.source_database
    ,dl.source_table
    ,dl.job_name
    ,dl.target_database
    ,dl.target_table
    ,dl.transformation_type
    ,dl.is_active
    ,lr.lineage_run_id
    ,lr.run_dts                AS last_run_dts
    ,lr.run_status             AS last_run_status
    ,lr.run_duration_ms        AS last_run_duration_ms
    ,lr.records_read           AS last_records_read
    ,lr.records_written        AS last_records_written
    ,lr.records_rejected       AS last_records_rejected
    ,lr.error_message          AS last_error_message
FROM
    {ProductName}_Observability.data_lineage AS dl
LEFT OUTER JOIN {ProductName}_Observability.lineage_run AS lr
  ON  lr.lineage_id = dl.lineage_id
  AND lr.run_dts = (
        SELECT MAX(lr2.run_dts)
        FROM   {ProductName}_Observability.lineage_run AS lr2
        WHERE  lr2.lineage_id = dl.lineage_id
      )
WHERE
    dl.is_active = 1
;
COMMENT ON VIEW {ProductName}_Semantic.lineage_run_latest IS
'Latest execution status per declared lineage flow — join definition and most recent run for dashboard display';
```

---

## Operational Patterns

### Register a lineage flow (once per pipeline design)

```sql
INSERT INTO {ProductName}_Observability.data_lineage
(source_database, source_table, source_system,
 target_database, target_table,
 job_name, transformation_type, transformation_logic)
VALUES
('{ProductName}_Domain', '{Entity}_H', NULL,
 '{ProductName}_Prediction', '{entity}_features',
 'ETL_{ENTITY}_FEATURES', 'FEATURE_ENG',
 'Extracts features from {Entity}_H for ML scoring');
```

### Log each execution

```sql
INSERT INTO {ProductName}_Observability.lineage_run
(lineage_id, run_dts, run_status, run_duration_ms,
 records_read, records_written, records_rejected, batch_key, job_name)
VALUES
(:{lineage_id}, CURRENT_TIMESTAMP(6), 'SUCCESS', :{duration_ms},
 :{records_in}, :{records_out}, :{records_rej},
 '{BATCH_KEY}', 'ETL_{ENTITY}_FEATURES');
```

### Data freshness check

```sql
SELECT
    dl.target_database || '.' || dl.target_table  AS dataset_name,
    MAX(lr.run_dts)                                AS last_successful_run,
    CASE
        WHEN MAX(lr.run_dts) >= CURRENT_TIMESTAMP(6) - INTERVAL '24' HOUR THEN 'FRESH'
        WHEN MAX(lr.run_dts) >= CURRENT_TIMESTAMP(6) - INTERVAL '48' HOUR THEN 'STALE'
        ELSE 'CRITICAL'
    END                                            AS freshness_status
FROM {ProductName}_Observability.data_lineage dl
INNER JOIN {ProductName}_Observability.lineage_run lr ON lr.lineage_id = dl.lineage_id
WHERE dl.is_active = 1 AND lr.run_status = 'SUCCESS'
GROUP BY dl.target_database, dl.target_table, dl.job_name;
```

---

## Semantic Registration INSERTs

```sql
INSERT INTO {ProductName}_Semantic.data_product_map
(module_name, module_description, module_purpose, database_name, naming_pattern,
 primary_tables, primary_views, module_version, deployment_status, is_active, created_at, updated_at)
VALUES
('Observability', 'Data product health monitoring', 'Events, metrics, lineage, and agent outcomes',
 '{ProductName}_Observability', 'SEPARATE_DB',
 'change_event, data_quality_metric, data_lineage, lineage_run, model_performance, agent_outcome',
 'lineage_graph (in Semantic), lineage_run_latest (in Semantic)',
 '1.0', 'DEPLOYED', 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));
```

---

## Documentation Capture INSERTs

```sql
INSERT INTO {ProductName}_Memory.Module_Registry
(module_name, database_name, deployment_status, module_version, module_purpose,
 key_entities, dependencies, dependents, data_owner, technical_owner,
 version_date, is_current, valid_from, valid_to)
VALUES ('OBSERVABILITY', '{ProductName}_Observability', 'DEPLOYED', '1.0.0',
 'Data product health monitoring — change events, quality metrics, lineage, model performance, agent outcomes',
 'change_event, data_quality_metric, data_lineage, lineage_run, model_performance, agent_outcome',
 'Memory (documentation), Semantic (lineage_graph + lineage_run_latest views hosted there)',
 'All modules (monitored here)',
 '{data_owner}', '{tech_contact}',
 CURRENT_DATE, 1, CURRENT_DATE, DATE '9999-12-31');

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-OBSERVABILITY-001', 1,
 'Lineage split: data_lineage (definition) + lineage_run (execution)',
 'Two-table model: data_lineage holds one row per declared flow; lineage_run holds one row per execution',
 'Graph visualisation needs a stable deduplicated edge list; execution history needs independent retention',
 'Single table with one row per execution; single table with a latest-run flag',
 'Separate tables enable independent retention, stable graph views, and clear mutation semantics',
 'lineage_graph view reads definitions only; lineage_run grows at event-scale; retention policies differ',
 'ACCEPTED', 'ARCHITECTURE', 'OBSERVABILITY', '1.0.0',
 'data_lineage, lineage_run', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-OBSERVABILITY-002', 1,
 'Table-level change tracking (not per-record)',
 'change_event stores one row per batch/job with aggregate records_affected count',
 'ETL batches touch millions of rows; per-record tracking would be unscalable',
 'Per-record change log; CDC-style row versioning',
 'Table-level aggregates match Memory small-answers principle; one event per batch scales efficiently',
 'Cannot reconstruct individual record change history from Observability alone; use domain temporal tables for that',
 'ACCEPTED', 'ARCHITECTURE', 'OBSERVABILITY', '1.0.0',
 'change_event', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);
```

---

## Design Checklist (Observability-specific)

- [ ] `data_lineage` registered for ALL declared pipeline flows (not just some)
- [ ] `lineage_graph` and `lineage_run_latest` views deployed to `{ProductName}_Semantic` (not Observability DB)
- [ ] `lineage_graph` view: all CAST requirements preserved — `CAST('ETL_INPUT' AS VARCHAR(12))`, `CAST('' AS VARCHAR(128))`, `CAST('Job' AS VARCHAR(30))`, `CAST(dl.job_name AS VARCHAR(128))` — without these, Teradata truncates UNION ALL column widths from Leg 1
- [ ] Separate retention policies defined for `data_lineage` (permanent) vs `lineage_run` (event-window)
- [ ] `change_event` tracks at table level — one event per batch, not per row
- [ ] `tables_accessed` in `agent_outcome` uses `database.table` format (table-level only)
- [ ] Quality thresholds populated in `data_quality_metric` for all key tables
- [ ] Closed-loop feed from `agent_outcome` to `{ProductName}_Memory.learned_strategy` planned
- [ ] Memory documentation INSERTs: 1 Module_Registry, ≥3 Design_Decision, ≥1 Query_Cookbook, ≥3 Business_Glossary
<!-- /param:observability -->

<!-- param:search -->
# Search Module
**Database**: `{ProductName}_Search`
**Purpose**: Semantic similarity search using vector embeddings — find by meaning, not keywords. Enables RAG patterns for agents.
**Core principle**: Store vectors + entity IDs only. NEVER duplicate content from Domain. Join back for content.

---

## Design Decisions

| Decision | Options | Choose when |
|---|---|---|
| Storage format | Native VECTOR (FLOAT32(n)) / Columnar (emb_0…emb_N) | VECTOR for Vantage 20.00.26.XX+; columnar for legacy or direct dimension analytics |
| ANN indexing | KMEANS / HNSW / Exact (TD_VectorDistance) | KMEANS → batch, 100K+ vectors; HNSW → real-time, high accuracy; Exact → <50K or post-filter |
| Embedding model | bge-small-en-v1.5 (384) / bge-base-en-v1.5 (768) / text-embedding-ada-002 (1536) | Align with organisational standard; document in Semantic column_metadata |
| Distance metric | Cosine / Euclidean / Manhattan | Cosine for text/semantic; Euclidean for spatial; Manhattan for sparse high-dimensional |
| Update strategy | On-insert / Daily batch / On-demand | On-insert for small volumes; batch for large; on-demand for low-frequency entities |
| Content join | Always join Domain for content | Always — no content duplication in Search |

---

## DDL

### entity_embedding (Standard Key-Only Table)

```sql
CREATE TABLE {ProductName}_Search.entity_embedding (
    embedding_id        INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    -- Entity reference (ID ONLY — no content duplication)
    entity_id           BIGINT NOT NULL,       -- FK to Domain entity surrogate key
    entity_type         VARCHAR(50) NOT NULL,  -- 'PARTY', 'PRODUCT', 'DOCUMENT', etc.
    source_module       VARCHAR(50),           -- 'Domain', 'Prediction', etc.
    source_table        VARCHAR(100),          -- '{Entity}_H'
    source_column       VARCHAR(128),          -- Column that was embedded (e.g., 'description')
    -- Vector embedding
    embedding_vector    VECTOR,                -- Teradata native FLOAT32(n) format
    embedding_dimensions INTEGER NOT NULL,     -- 384, 768, 1536, etc.
    embedding_model     VARCHAR(100) NOT NULL, -- 'bge-small-en-v1.5', 'text-embedding-ada-002'
    embedding_model_version VARCHAR(20),
    computation_method  VARCHAR(50),           -- 'ONNX', 'OPENAI_API', 'NVIDIA_NIM'
    -- Temporal tracking
    generated_dts       TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    valid_from_dts      TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    valid_to_dts        TIMESTAMP(6) WITH TIME ZONE NOT NULL
        DEFAULT TIMESTAMP '9999-12-31 23:59:59.999999+00:00',
    is_current          BYTEINT NOT NULL DEFAULT 1,
    generated_by        VARCHAR(100)
) PRIMARY INDEX (embedding_id);
COMMENT ON TABLE {ProductName}_Search.entity_embedding IS
'Vector embeddings - stores FLOAT32 vectors and entity IDs only. NO content columns. Join to Domain for actual attributes.';
COMMENT ON COLUMN {ProductName}_Search.entity_embedding.entity_id IS
'FK to Domain entity surrogate key — no content duplicated here';
COMMENT ON COLUMN {ProductName}_Search.entity_embedding.embedding_vector IS
'Teradata native VECTOR datatype (FLOAT32(n)) for parallel similarity search via TD_VectorDistance';
```

### Standard Search View (Content join — required per entity)

```sql
CREATE VIEW {ProductName}_Search.v_{entity}_searchable AS
SELECT
    e.entity_id,
    e.embedding_vector,
    e.embedding_model,
    e.embedding_dimensions,
    e.generated_dts,
    -- Content from Domain (NOT stored in Search)
    d.{entity}_key,
    d.[business_attributes]
FROM {ProductName}_Search.entity_embedding e
INNER JOIN {ProductName}_Domain.{Entity}_H d
    ON d.{entity}_id = e.entity_id
   AND d.is_current = 1 AND d.is_deleted = 0
WHERE e.is_current = 1
  AND e.entity_type = '{ENTITY}';
COMMENT ON VIEW {ProductName}_Search.v_{entity}_searchable IS
'{Entity} embeddings joined with Domain content — use this view for RAG and semantic search to avoid querying two tables separately';
```

---

## Similarity Search Patterns

### TD_VectorDistance — Basic Similarity Search

```sql
-- Find top 10 most similar entities to a query entity
SELECT
    ref.entity_id  AS similar_{entity}_id,
    ref.embedding_id,
    dt.distance    AS similarity_distance
FROM TD_VECTORDISTANCE (
    ON (SELECT * FROM {ProductName}_Search.entity_embedding WHERE entity_id = :{query_entity_id})
        AS TargetTable PARTITION BY ANY
    ON (SELECT * FROM {ProductName}_Search.entity_embedding
        WHERE entity_type = '{ENTITY}' AND is_current = 1)
        AS ReferenceTable DIMENSION
    USING
        TargetIDColumn('entity_id')
        TargetFeatureColumns('embedding_vector')
        RefIDColumn('entity_id')
        RefFeatureColumns('embedding_vector')
        DistanceMeasure('cosine')
        TopK(10)
) AS dt
INNER JOIN {ProductName}_Search.entity_embedding ref
    ON ref.entity_id = dt.reference_id
ORDER BY dt.distance;
```

### TD_VectorDistance — With Domain Content (JOIN)

```sql
-- Similarity search with full entity attributes
SELECT
    d.{entity}_key,
    d.[business_attributes],
    dt.distance AS similarity_score
FROM TD_VECTORDISTANCE (
    ON (SELECT embedding_vector FROM {ProductName}_Search.entity_embedding
        WHERE entity_id = :{query_entity_id} AND is_current = 1)
        AS TargetTable PARTITION BY ANY
    ON (SELECT * FROM {ProductName}_Search.entity_embedding
        WHERE entity_type = '{ENTITY}' AND is_current = 1)
        AS ReferenceTable DIMENSION
    USING
        TargetIDColumn('entity_id')
        TargetFeatureColumns('embedding_vector')
        RefIDColumn('entity_id')
        RefFeatureColumns('embedding_vector')
        DistanceMeasure('cosine')
        TopK(10)
) AS dt
-- Join to Domain for content — NOT stored in Search
INNER JOIN {ProductName}_Domain.{Entity}_H d
    ON d.{entity}_id = dt.reference_id
   AND d.is_current = 1 AND d.is_deleted = 0
ORDER BY dt.distance;
```

### RAG Pattern — Retrieve relevant context for LLM

```sql
-- Retrieve top-N most relevant documents for query embedding
SELECT
    d.document_id,
    d.document_title,
    d.content_text,     -- From Domain, NOT stored in Search
    dt.distance AS relevance_score
FROM TD_VECTORDISTANCE (
    ON :{query_embedding_table} AS TargetTable PARTITION BY ANY
    ON (SELECT * FROM {ProductName}_Search.entity_embedding WHERE is_current = 1)
        AS ReferenceTable DIMENSION
    USING
        RefIDColumn('entity_id')
        RefFeatureColumns('embedding_vector')
        DistanceMeasure('cosine')
        TopK(5)
) AS dt
INNER JOIN {ProductName}_Domain.Document_H d
    ON d.document_id = dt.reference_id
   AND d.is_current = 1
ORDER BY dt.distance
QUALIFY ROW_NUMBER() OVER (ORDER BY dt.distance) <= 5;
```

### TD_VectorDistance — Columnar storage (legacy)

```sql
-- Range notation for column-based embeddings (emb_0 to emb_383)
USING
    TargetFeatureColumns('[emb_0:emb_383]')
    RefFeatureColumns('[emb_0:emb_383]')
    DistanceMeasure('cosine')
    TopK(10)
```

---

## Agent Discovery Queries

```sql
-- What entity types have embeddings?
SELECT DISTINCT entity_type, source_table, embedding_model,
    embedding_dimensions, COUNT(*) AS vector_count
FROM {ProductName}_Search.entity_embedding
WHERE is_current = 1
GROUP BY entity_type, source_table, embedding_model, embedding_dimensions;

-- Stale embeddings (entity updated after embedding generated)
SELECT e.entity_id, e.entity_type, e.generated_dts,
    d.updated_at AS domain_updated_at
FROM {ProductName}_Search.entity_embedding e
INNER JOIN {ProductName}_Domain.{Entity}_H d
    ON d.{entity}_id = e.entity_id AND d.is_current = 1
WHERE e.is_current = 1 AND d.updated_at > e.generated_dts;
```

---

## Expire-Current → Insert-New (Embedding Refresh)

```sql
-- Expire stale embedding
UPDATE {ProductName}_Search.entity_embedding
SET is_current   = 0,
    valid_to_dts = CURRENT_TIMESTAMP(6)
WHERE entity_id = :{entity_id} AND entity_type = '{ENTITY}' AND is_current = 1;

-- Insert new embedding
INSERT INTO {ProductName}_Search.entity_embedding
(entity_id, entity_type, source_table, source_column,
 embedding_vector, embedding_dimensions, embedding_model,
 generated_dts, valid_from_dts, valid_to_dts, is_current)
VALUES
(:{entity_id}, '{ENTITY}', '{Entity}_H', '{source_column}',
 :{new_vector}, :{dims}, '{model_name}',
 CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6),
 TIMESTAMP '9999-12-31 23:59:59.999999+00:00', 1);
```

---

## Semantic Registration INSERTs

```sql
INSERT INTO {ProductName}_Semantic.data_product_map
(module_name, module_description, module_purpose, database_name, naming_pattern,
 primary_tables, primary_views, module_version, deployment_status, is_active, created_at, updated_at)
VALUES
('Search', 'Vector embeddings for semantic similarity', 'RAG and similarity search over Domain entities',
 '{ProductName}_Search', 'SEPARATE_DB',
 'entity_embedding',
 'v_{entity}_searchable',
 '1.0', 'DEPLOYED', 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));

-- Register embedding table entity
INSERT INTO {ProductName}_Semantic.entity_metadata
(entity_name, entity_description, module_name, database_name, table_name, view_name,
 surrogate_key_column, natural_key_column, temporal_pattern,
 current_flag_column, deleted_flag_column, is_active, created_at, updated_at)
VALUES
('{Entity}Embedding', 'Vector embeddings for {Entity} entities — key-only, join Domain for content',
 'Search', '{ProductName}_Search', 'entity_embedding', 'v_{entity}_searchable',
 'embedding_id', 'entity_id', 'TYPE_2_SCD',
 'is_current', NULL, 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));
```

---

## Documentation Capture INSERTs

```sql
INSERT INTO {ProductName}_Memory.Module_Registry
(module_name, database_name, deployment_status, module_version, module_purpose,
 key_entities, dependencies, dependents, data_owner, technical_owner,
 version_date, is_current, valid_from, valid_to)
VALUES ('SEARCH', '{ProductName}_Search', 'DEPLOYED', '1.0.0',
 'Vector embeddings for semantic similarity search and RAG over Domain entities',
 'entity_embedding',
 'Domain (entity IDs resolved here), Semantic (embedding strategy documented there)',
 'Agents (RAG queries), Prediction (embedding features)',
 '{data_owner}', '{tech_contact}',
 CURRENT_DATE, 1, CURRENT_DATE, DATE '9999-12-31');

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-SEARCH-001', 1,
 'Key-only vector storage — no content duplication',
 'entity_embedding stores entity_id and embedding_vector only; content accessed via JOIN to Domain',
 'Need semantic similarity search without duplicating Domain entity attributes',
 'Duplicate content columns in embedding table; create standalone Search content store',
 'Key-only avoids storage waste, sync issues, and inconsistency; Domain remains single source of truth',
 'Every Search query must JOIN Domain for content; v_{entity}_searchable view simplifies this',
 'ACCEPTED', 'ARCHITECTURE', 'SEARCH', '1.0.0',
 'entity_embedding', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-SEARCH-002', 1,
 'ANN indexing strategy: {KMEANS|HNSW|Exact}',
 'Selected {chosen_strategy} for {entity} embeddings at {n} vectors',
 'Need similarity search performance for {n} vectors with {latency_requirement} latency',
 'KMEANS (batch, approximate); HNSW (real-time, high accuracy); Exact TD_VectorDistance (brute force)',
 '{rationale_for_choice}',
 'Search queries use {chosen_strategy}; rebuild/refresh cadence: {cadence}',
 'ACCEPTED', 'PERFORMANCE', 'SEARCH', '1.0.0',
 'entity_embedding', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);
```

---

## Design Checklist (Search-specific)

- [ ] `entity_embedding` has NO content columns (only `entity_id`, vector, metadata)
- [ ] `embedding_vector` uses Teradata native VECTOR datatype (`FLOAT32(n)`)
- [ ] `v_{entity}_searchable` view created for each embedded entity type
- [ ] `TD_VectorDistance` call tested with `TargetIDColumn`, `TargetFeatureColumns`, `RefIDColumn`, `RefFeatureColumns`, `DistanceMeasure`, `TopK`
- [ ] ANN index strategy documented and justified (KMEANS / HNSW / Exact)
- [ ] Embedding model name and dimensions recorded in `embedding_model` + `embedding_dimensions`
- [ ] Teradata version ≥ 20.00.26.XX confirmed for native VECTOR UDT
- [ ] Embedding refresh strategy defined (expire-current → insert-new DML ready)
- [ ] Stale embedding detection query validated
- [ ] Semantic registration INSERTs present (data_product_map + entity_metadata)
- [ ] Memory documentation INSERTs: 1 Module_Registry, ≥3 Design_Decision, ≥1 Query_Cookbook, ≥3 Business_Glossary
<!-- /param:search -->

<!-- param:prediction -->
# Prediction Module
**Database**: `{ProductName}_Prediction`
**Purpose**: Feature store for ML model training and serving. Stores engineered features with point-in-time correctness.
**Core principle**: Store ENGINEERED features (normalized, transformed, aggregated), NOT raw domain data copies. Join Domain for context.

---

## Design Decisions

| Decision | Options | Choose when |
|---|---|---|
| Storage pattern | Wide (feature group table) / Tall (feature_value table) | Wide → features accessed together, fixed set, dense; Tall → sparse, dynamic set, individual access |
| Normalization scale | 0–1 range / z-score / None | 0–1 for most ML features; z-score when distribution matters; None only for categoricals |
| Raw value duplication | Avoid / Allowed (selective) | Allowed ONLY for low-latency scoring (<100ms) — document rationale per column |
| Point-in-time tracking | observation_dts + valid_from/to_dts | Always required for training dataset reproducibility |
| Feature metadata | Semantic column_metadata | Always — agents query Semantic to discover what features exist and their meanings |

---

## DDL

### Pattern A — Wide Format (Feature Group Table)

```sql
CREATE TABLE {ProductName}_Prediction.{entity}_features (
    feature_group_id     INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    -- Entity reference
    entity_id            BIGINT NOT NULL,       -- FK to Domain {Entity}_H
    entity_type          VARCHAR(50) NOT NULL,  -- '{ENTITY}'
    -- ENGINEERED feature values (normalized to 0-1 unless noted)
    -- Designer supplies feature columns — examples:
    recency_score        DECIMAL(5,4),  -- ENGINEERED: days_since_last_txn normalized; formula: 1.0 - (days/365)
    frequency_score      DECIMAL(5,4),  -- ENGINEERED: txn_count_30d / max across all entities
    monetary_score       DECIMAL(5,4),  -- ENGINEERED: total_spend_30d / max across all entities
    -- [Add additional engineered features — never raw domain column copies]
    feature_group_name   VARCHAR(128) NOT NULL,
    feature_group_version VARCHAR(20),
    -- Temporal tracking (point-in-time correctness)
    observation_dts      TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    valid_from_dts       TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    valid_to_dts         TIMESTAMP(6) WITH TIME ZONE NOT NULL
        DEFAULT TIMESTAMP '9999-12-31 23:59:59.999999+00:00',
    is_current           BYTEINT NOT NULL DEFAULT 1,
    computation_dts      TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    source_system        VARCHAR(50),
    created_by           VARCHAR(100)
) PRIMARY INDEX (feature_group_id);
COMMENT ON TABLE {ProductName}_Prediction.{entity}_features IS
'{Entity} engineered features normalized to 0-1 range for ML training. NOT raw domain values. Join Domain for context.';
COMMENT ON COLUMN {ProductName}_Prediction.{entity}_features.observation_dts IS
'When features were observed/computed — critical for point-in-time ML training without data leakage';
COMMENT ON COLUMN {ProductName}_Prediction.{entity}_features.recency_score IS
'ENGINEERED: days since last transaction normalized to 0-1. Formula: 1.0 - (days/365). Recent = higher score.';
```

### Pattern B — Tall Format (Feature-Value Table)

```sql
CREATE TABLE {ProductName}_Prediction.feature_value (
    feature_value_id     INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    entity_id            BIGINT NOT NULL,
    entity_type          VARCHAR(50) NOT NULL,
    feature_name         VARCHAR(128) NOT NULL,
    feature_group        VARCHAR(100),
    value_numeric        DECIMAL(18,4),    -- Use for normalized numeric features
    value_text           VARCHAR(500),     -- Use for categorical features
    value_json           JSON,             -- Use for complex multi-dimensional features
    value_type           VARCHAR(20),      -- 'NUMERIC', 'TEXT', 'JSON', 'BOOLEAN'
    feature_version      VARCHAR(20),
    -- Temporal tracking
    observation_dts      TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    valid_from_dts       TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    valid_to_dts         TIMESTAMP(6) WITH TIME ZONE NOT NULL
        DEFAULT TIMESTAMP '9999-12-31 23:59:59.999999+00:00',
    is_current           BYTEINT NOT NULL DEFAULT 1,
    computation_dts      TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6),
    source_system        VARCHAR(50),
    created_by           VARCHAR(100)
) PRIMARY INDEX (feature_value_id);
COMMENT ON TABLE {ProductName}_Prediction.feature_value IS
'Tall-format feature store — one row per feature per entity per time point. Use for sparse or dynamic feature sets.';
```

### model_prediction

```sql
CREATE TABLE {ProductName}_Prediction.model_prediction (
    prediction_id            INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    entity_id                BIGINT NOT NULL,
    entity_type              VARCHAR(50) NOT NULL,
    model_key                VARCHAR(100) NOT NULL,
    model_version            VARCHAR(20) NOT NULL,
    prediction_value         DECIMAL(10,6),   -- Probability, score, or numeric prediction
    prediction_class         VARCHAR(100),    -- Classification result
    prediction_json          JSON,            -- Multi-class probabilities or structured output
    confidence_score         DECIMAL(5,4),   -- 0.0–1.0
    prediction_dts           TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    feature_observation_dts  TIMESTAMP(6) WITH TIME ZONE, -- When input features were observed
    valid_from_dts           TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    valid_to_dts             TIMESTAMP(6) WITH TIME ZONE NOT NULL
        DEFAULT TIMESTAMP '9999-12-31 23:59:59.999999+00:00',
    is_current               BYTEINT NOT NULL DEFAULT 1,
    created_by               VARCHAR(100),
    created_at               TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP(6)
) PRIMARY INDEX (prediction_id);
COMMENT ON TABLE {ProductName}_Prediction.model_prediction IS
'ML model prediction outputs with temporal tracking. Links predictions to feature_observation_dts for reproducibility.';
COMMENT ON COLUMN {ProductName}_Prediction.model_prediction.feature_observation_dts IS
'Timestamp of input features used — links prediction to feature snapshot for explainability and reproducibility';
```

---

## Standard Views

```sql
-- View 1: Current engineered features only
CREATE VIEW {ProductName}_Prediction.v_{entity}_features_current AS
SELECT * FROM {ProductName}_Prediction.{entity}_features
WHERE is_current = 1;
COMMENT ON VIEW {ProductName}_Prediction.v_{entity}_features_current IS
'Current engineered feature values for {entity} — use for real-time scoring and active model serving';

-- View 2: Features enriched with Domain context (no duplication)
CREATE VIEW {ProductName}_Prediction.v_{entity}_features_enriched AS
SELECT
    -- Engineered features (from Prediction — stored here)
    f.entity_id, f.recency_score, f.frequency_score, f.monetary_score,
    f.observation_dts,
    -- Raw domain attributes (from Domain — NOT duplicated in Prediction)
    d.{entity}_key, d.[domain_business_attributes]
FROM {ProductName}_Prediction.v_{entity}_features_current f
INNER JOIN {ProductName}_Domain.{Entity}_H d
    ON d.{entity}_id = f.entity_id
   AND d.is_current = 1 AND d.is_deleted = 0;
COMMENT ON VIEW {ProductName}_Prediction.v_{entity}_features_enriched IS
'Engineered features joined with Domain raw attributes — no data duplication. Use for complete entity context in ML pipelines.';

-- View 3: Point-in-time feature reconstruction (training datasets)
CREATE VIEW {ProductName}_Prediction.v_{entity}_features_pit AS
SELECT
    d.{entity}_key, d.[domain_business_attributes],
    f.recency_score, f.frequency_score, f.monetary_score,
    f.observation_dts, f.valid_from_dts, f.valid_to_dts
FROM {ProductName}_Prediction.{entity}_features f
INNER JOIN {ProductName}_Domain.{Entity}_H d
    ON d.{entity}_id = f.entity_id AND d.is_current = 1;
COMMENT ON VIEW {ProductName}_Prediction.v_{entity}_features_pit IS
'Point-in-time feature history — use to build training datasets without data leakage. Filter by observation_dts/valid_from/to.';
```

---

## Point-in-Time Query Patterns

```sql
-- Get features as they existed on a specific date (training dataset)
SELECT entity_id, feature_name, value_numeric, observation_dts
FROM {ProductName}_Prediction.feature_value
WHERE entity_id = :{entity_id}
  AND entity_type = '{ENTITY}'
  AND observation_dts      <= TIMESTAMP '2024-03-01 00:00:00+00:00'
  AND valid_from_dts        <= TIMESTAMP '2024-03-01 00:00:00+00:00'
  AND valid_to_dts           > TIMESTAMP '2024-03-01 00:00:00+00:00';

-- Join with Domain state at same point in time (avoid data leakage)
SELECT p.{entity}_key, p.[domain_attrs], f.feature_name, f.value_numeric
FROM {ProductName}_Domain.{Entity}_H p
INNER JOIN {ProductName}_Prediction.feature_value f
    ON f.entity_id = p.{entity}_id AND f.entity_type = '{ENTITY}'
WHERE TIMESTAMP '2024-03-01 00:00:00+00:00' >= p.valid_from_dts
  AND TIMESTAMP '2024-03-01 00:00:00+00:00'  < p.valid_to_dts
  AND f.observation_dts        <= TIMESTAMP '2024-03-01 00:00:00+00:00'
  AND f.valid_from_dts          <= TIMESTAMP '2024-03-01 00:00:00+00:00'
  AND f.valid_to_dts             > TIMESTAMP '2024-03-01 00:00:00+00:00';
```

---

## Expire-Current → Insert-New (Feature Refresh)

```sql
-- Expire stale feature row
UPDATE {ProductName}_Prediction.{entity}_features
SET is_current   = 0,
    valid_to_dts = CURRENT_TIMESTAMP(6)
WHERE entity_id = :{entity_id} AND is_current = 1;

-- Insert new feature version (recomputed values)
INSERT INTO {ProductName}_Prediction.{entity}_features
(entity_id, entity_type, recency_score, frequency_score, monetary_score,
 feature_group_name, feature_group_version,
 observation_dts, valid_from_dts, valid_to_dts,
 is_current, computation_dts, source_system)
VALUES
(:{entity_id}, '{ENTITY}', :{recency}, :{frequency}, :{monetary},
 '{group_name}', '{version}',
 CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6),
 TIMESTAMP '9999-12-31 23:59:59.999999+00:00',
 1, CURRENT_TIMESTAMP(6), '{source_system}');
```

### Staleness Detection

```sql
-- Entities with no current features (feature coverage gap)
SELECT d.{entity}_id, d.{entity}_key
FROM {ProductName}_Domain.{Entity}_H d
WHERE d.is_current = 1 AND d.is_deleted = 0
  AND NOT EXISTS (
    SELECT 1 FROM {ProductName}_Prediction.{entity}_features f
    WHERE f.entity_id = d.{entity}_id AND f.is_current = 1
  );

-- Features stale relative to Domain updates
SELECT f.entity_id, f.observation_dts, d.updated_at AS domain_updated_at
FROM {ProductName}_Prediction.{entity}_features f
INNER JOIN {ProductName}_Domain.{Entity}_H d
    ON d.{entity}_id = f.entity_id AND d.is_current = 1
WHERE f.is_current = 1 AND d.updated_at > f.observation_dts;
```

---

## Semantic Registration INSERTs

```sql
INSERT INTO {ProductName}_Semantic.data_product_map
(module_name, module_description, module_purpose, database_name, naming_pattern,
 primary_tables, primary_views, module_version, deployment_status, is_active, created_at, updated_at)
VALUES
('Prediction', 'ML feature store with point-in-time correctness',
 'Engineered features for model training and serving',
 '{ProductName}_Prediction', 'SEPARATE_DB',
 '{entity}_features, feature_value, model_prediction',
 'v_{entity}_features_current, v_{entity}_features_enriched, v_{entity}_features_pit',
 '1.0', 'DEPLOYED', 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));

INSERT INTO {ProductName}_Semantic.entity_metadata
(entity_name, entity_description, module_name, database_name, table_name, view_name,
 surrogate_key_column, natural_key_column, temporal_pattern,
 current_flag_column, deleted_flag_column, is_active, created_at, updated_at)
VALUES
('{Entity}Features', 'Engineered feature group for {Entity} entities — normalized 0-1 values for ML',
 'Prediction', '{ProductName}_Prediction', '{entity}_features', 'v_{entity}_features_current',
 'feature_group_id', 'entity_id', 'TYPE_2_SCD',
 'is_current', NULL, 1, CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));
```

---

## Documentation Capture INSERTs

```sql
INSERT INTO {ProductName}_Memory.Module_Registry
(module_name, database_name, deployment_status, module_version, module_purpose,
 key_entities, dependencies, dependents, data_owner, technical_owner,
 version_date, is_current, valid_from, valid_to)
VALUES ('PREDICTION', '{ProductName}_Prediction', 'DEPLOYED', '1.0.0',
 'Engineered feature store with point-in-time correctness for ML model training and serving',
 '{entity}_features, feature_value, model_prediction',
 'Domain (entity IDs and raw values for engineering), Semantic (feature metadata)',
 'ML models (training input), Observability (model_performance output)',
 '{data_owner}', '{tech_contact}',
 CURRENT_DATE, 1, CURRENT_DATE, DATE '9999-12-31');

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-PREDICTION-001', 1,
 'Wide-format feature storage for {entity} features',
 '{entity}_features table stores all features as columns in a single row per entity-version',
 'Features for {entity} ML model are always used together in training and scoring',
 'Tall format (one row per feature); hybrid (separate tables per feature group)',
 'Wide format reduces JOIN overhead for scoring; features always loaded as a group; easier for model pipelines',
 'Adding new features requires ALTER TABLE; schema changes need feature group version bump',
 'ACCEPTED', 'ARCHITECTURE', 'PREDICTION', '1.0.0',
 '{entity}_features', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);

INSERT INTO {ProductName}_Memory.Design_Decision
(decision_id, decision_version, decision_title, decision_description,
 context, alternatives_considered, rationale, consequences,
 decision_status, decision_category, source_module, module_version,
 affects_table, decided_by, decided_date, valid_from, valid_to, is_current)
VALUES ('DD-PREDICTION-002', 1,
 'Feature normalization to 0-1 range',
 'All continuous features normalized to 0-1 range before storage in feature table',
 'Features have different scales (age: 18-90, income: $0-$1M); unnormalized features bias model training',
 'Store raw values + normalize at training time; z-score standardization',
 '0-1 normalization ensures equal feature weighting; pre-computed in ETL avoids repeated normalization at scoring time',
 'Raw values stay in Domain; Prediction stores only normalized; max values for normalization must be tracked',
 'ACCEPTED', 'SCHEMA', 'PREDICTION', '1.0.0',
 '{entity}_features', '{decided_by}', CURRENT_DATE, CURRENT_DATE, DATE '9999-12-31', 1);
```

---

## Design Checklist (Prediction-specific)

- [ ] All feature columns are ENGINEERED (normalized/transformed) — no raw domain value copies
- [ ] Every feature column has COMMENT ON COLUMN with: `ENGINEERED: <formula>` description
- [ ] `observation_dts`, `valid_from_dts`, `valid_to_dts`, `is_current` present on all feature tables
- [ ] Non-UNIQUE `PRIMARY INDEX` on all feature tables (multiple temporal versions per entity)
- [ ] `v_{entity}_features_current` view (WHERE is_current=1) created
- [ ] `v_{entity}_features_enriched` view joins Domain for raw context (no duplication)
- [ ] `v_{entity}_features_pit` view for point-in-time training dataset reconstruction
- [ ] Point-in-time query pattern tested (training dataset extraction validated)
- [ ] Staleness detection query validated (entities with no current features, features stale vs Domain)
- [ ] Expire-current → insert-new DML pattern used for feature refresh
- [ ] Feature metadata documented in Semantic `column_metadata` (agents discover features there)
- [ ] `model_prediction.feature_observation_dts` wired to feature `observation_dts` for reproducibility
- [ ] Semantic registration INSERTs present (data_product_map + entity_metadata per feature group)
- [ ] Memory documentation INSERTs: 1 Module_Registry, ≥3 Design_Decision, ≥1 Query_Cookbook, ≥3 Business_Glossary
<!-- /param:prediction -->
