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
