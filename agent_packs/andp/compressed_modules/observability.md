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
