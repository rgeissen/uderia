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
