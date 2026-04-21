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
