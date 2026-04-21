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
