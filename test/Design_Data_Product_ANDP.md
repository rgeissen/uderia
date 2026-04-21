# AI-Native Data Product — ANDP Design Playbook
## For Designing Specific Data Product Implementations with the ANDP Agent Pack

---

## How to Use

1. Replace all `[PLACEHOLDER]` values in the **Product Reference** section with your specifics
2. Paste the updated values into each deliverable query block where indicated
3. Send **one deliverable at a time** — copy the query block and send it to `@ANDP`
4. Review the output, then move to the next deliverable

> **Why not paste everything at once?**
> The ANDP coordinator routes queries to module specialist slaves based on topic.
> A monolithic prompt spanning all modules causes the coordinator to answer directly
> from base context, bypassing the specialists. Each focused query routes to exactly
> one slave — the expert for that module.

---

## Step 1 — Fill in the Product Reference

Replace all placeholders below before sending any queries.

| Field | Your value |
|---|---|
| `[DATA_PRODUCT_NAME]` | *(e.g. CustomerIntelligence360)* |
| `[BUSINESS_PURPOSE]` | *(What problem does this solve?)* |
| `[PRIMARY_CONSUMERS]` | *(AI agents, analysts, APIs, pipelines?)* |
| `[USE_CASE_1]` | *(Specific use case)* |
| `[USE_CASE_2]` | *(Specific use case)* |
| `[USE_CASE_3]` | *(Specific use case)* |
| `[DATABASE_NAME]` | *(Single-database name, e.g. CustomerIntelligence360)* |
| `[ENTITY_1_NAME]` | *(e.g. Customer)* |
| `[ENTITY_1_SOURCE]` | *(e.g. crm_db.Customers)* |
| `[ENTITY_1_COLUMNS]` | *(comma-separated column list)* |
| `[ENTITY_2_NAME]` | *(e.g. Order)* |
| `[ENTITY_2_SOURCE]` | *(e.g. erp_db.Orders)* |
| `[ENTITY_2_COLUMNS]` | *(comma-separated column list)* |
| `[FK_RELATIONSHIP]` | *(e.g. Order.CustomerID → Customer.CustomerID)* |
| `[VOLUME_ENTITY_1]` | *(e.g. ~50k rows, +1k/month)* |
| `[VOLUME_ENTITY_2]` | *(e.g. ~500k rows, +20k/month)* |
| `[LATENCY]` | *(Batch / near-real-time / real-time)* |
| `[DEFERRED_MODULES]` | *(e.g. Observability, Prediction — Phase 2)* |
| `[EXCLUDED_MODULES]` | *(e.g. Search — no vector use case)* |

**Modules to deploy** (tick all that apply — always include Memory, Semantic, Domain):
- [x] Memory — always required
- [x] Semantic — always required
- [x] Domain/Subject Data — always required
- [ ] Observability
- [ ] Prediction
- [ ] Search

> **Database layout:** This playbook assumes **single-database layout** (all modules share
> `[DATABASE_NAME]`, distinguished by table name prefix). For multi-database enterprise
> layout, replace every `[DATABASE_NAME]` reference in the queries with the appropriate
> per-module database name (e.g. `[DATA_PRODUCT_NAME]_Domain`).

---

## Step 2 — Send Deliverable Queries in Order

---

### D1 — Requirements & Entity Map

*Routes to: coordinator (cross-module scoping)*

```
@ANDP

For the [DATA_PRODUCT_NAME] data product, produce the Requirements & Entity Map.

Product context:
- Business purpose: [BUSINESS_PURPOSE]
- Source entities:
  - [ENTITY_1_NAME]: [ENTITY_1_SOURCE]
  - [ENTITY_2_NAME]: [ENTITY_2_SOURCE]
- Relationship: [FK_RELATIONSHIP]
- Single-database layout: database name [DATABASE_NAME]
- Modules in scope: Domain, Semantic, Memory[, LIST_ANY_ADDITIONAL_DEPLOYED_MODULES]
- Deferred: [DEFERRED_MODULES]
- Out of scope: [EXCLUDED_MODULES]

Deliverable:
- Confirm the core entities (name, purpose, source table)
- Map each entity to the correct module
- Identify entity relationships with cardinality
- For each deferred/excluded module, state the rationale
  (this feeds Memory documentation in D5)
- Note any anticipated deviations from the design standards

Stop after this deliverable and wait for review.
```

---

### D2 — Logical Data Model

*Routes to: ANDP-DOMAIN (entity structure)*

```
@ANDP

Design the Logical Data Model for the [DATA_PRODUCT_NAME] data product (Domain module).

Entities:
- [ENTITY_1_NAME]: [ENTITY_1_COLUMNS]
  (source: [ENTITY_1_SOURCE])
- [ENTITY_2_NAME]: [ENTITY_2_COLUMNS]
  (source: [ENTITY_2_SOURCE])

Relationship: [FK_RELATIONSHIP]

Deliverable:
- Entity definitions with key business attributes
- Relationships with cardinality
- ERD as a Mermaid diagram

Stop after this deliverable and wait for review.
```

---

### D3 — Domain Module Schema

*Routes to: ANDP-DOMAIN*

```
@ANDP

Design the Domain module DDL for the [DATA_PRODUCT_NAME] data product.

Entities:
- [ENTITY_1_NAME]: [ENTITY_1_COLUMNS]
  (source: [ENTITY_1_SOURCE])
- [ENTITY_2_NAME]: [ENTITY_2_COLUMNS]
  (source: [ENTITY_2_SOURCE])

Database layout: single database [DATABASE_NAME] (all modules share this database).

Before writing any DDL, ask: "Does the database [DATABASE_NAME] already exist
on Teradata?" — include CREATE DATABASE only if the answer is no.

Deliverable:
- CREATE DATABASE [DATABASE_NAME] (if needed)
- Bi-temporal history tables for each entity (suffix _H)
- Keymap surrogate key tables for each entity (suffix _Keymap)
- COMMENT ON TABLE and COMMENT ON COLUMN for every object
- Primary Index selection with justification per table
- Standard views: [ENTITY_1_NAME]_Current and [ENTITY_2_NAME]_Current

Stop after this deliverable and wait for review.
```

---

### D4 — Semantic Module Schema & Seed Data

*Routes to: ANDP-SEMANTIC*

```
@ANDP

Design the Semantic module for the [DATA_PRODUCT_NAME] data product.

Domain module tables already designed:
- [ENTITY_1_NAME]_H, [ENTITY_1_NAME]_Keymap
- [ENTITY_2_NAME]_H, [ENTITY_2_NAME]_Keymap
(all in database [DATABASE_NAME])

Deployed modules: Domain, Semantic, Memory[, LIST_ANY_ADDITIONAL_DEPLOYED_MODULES]

Deliverable:
- DDL for all Semantic tables (entity_metadata, column_metadata, table_relationship,
  naming_standard, data_product_map) in database [DATABASE_NAME]
- Seed INSERT statements:
  - data_product_map: one row per deployed module
  - entity_metadata: one row per history table (_H)
  - naming_standard: full set for [DATA_PRODUCT_NAME] conventions
  - column_metadata: all PII/sensitive columns at minimum
  - table_relationship: [FK_RELATIONSHIP] traversal in both directions
- Run the isolation check query to confirm no entity has zero table_relationship entries
- Run the path existence query for the expected agent join to confirm v_relationship_paths
  returns a result with valid JOIN syntax

Stop after this deliverable and wait for review.
```

---

### D5 — Memory Module Schema & Seed Data

*Routes to: ANDP-MEMORY*

```
@ANDP

Design the Memory module for the [DATA_PRODUCT_NAME] data product.

Modules considered during this design:
- Domain: DEPLOYED
- Semantic: DEPLOYED
- Memory: DEPLOYED
[- LIST_ADDITIONAL_DEPLOYED_MODULES: DEPLOYED]
- [DEFERRED_MODULE_1]: PLANNED
- [DEFERRED_MODULE_2]: PLANNED
- [EXCLUDED_MODULE]: DEPRECATED

Database: [DATABASE_NAME] (single-database layout)

Deliverable:
- Production-ready DDL for all Memory module tables in database [DATABASE_NAME]
- Mandatory seed data:
  - Module_Registry: one row for each module above with correct deployment_status
  - Design_Decision entries:
    - DD-SCOPE-001: single-database layout choice and rationale
    - DD-SCOPE-002: [EXCLUDED_MODULE] excluded — [EXCLUSION_REASON]
    - DD-SCOPE-003: [DEFERRED_MODULES] deferred — [DEFERRAL_REASON]
  - Query_Cookbook entry QC-SEMANTIC-002: standard ERD generation recipe
  - One cross-module Query_Cookbook entry per deployed module pair

Stop after this deliverable and wait for review.
```

---

### D6 — Integration Patterns

*Routes to: ANDP-SEMANTIC (agent discovery patterns)*

```
@ANDP

Document the integration patterns for the [DATA_PRODUCT_NAME] data product.

Deployed modules: Domain, Semantic, Memory[, LIST_ANY_ADDITIONAL]
All in database [DATABASE_NAME]
Domain tables: [ENTITY_1_NAME]_H, [ENTITY_2_NAME]_H
Semantic tables: entity_metadata, column_metadata, table_relationship,
  naming_standard, data_product_map

Deliverable:
- [ENTITY_1_NAME]→[ENTITY_2_NAME] join pattern specific to this product
- Data flow narrative: source systems → Domain module
- Agent consumption sequence: how an agent discovers and queries [DATA_PRODUCT_NAME]
  end-to-end using data_product_map and v_relationship_paths
- Any integration with other data products

Stop after this deliverable and wait for review.
```

---

### D7 — Deviations & Implementation Plan

*Routes to: coordinator (cross-module sign-off)*

```
@ANDP

Produce the final deviations summary and implementation plan for [DATA_PRODUCT_NAME].

Deployed modules: Domain, Semantic, Memory[, LIST_ANY_ADDITIONAL]
Database: [DATABASE_NAME]
Design decisions already captured in Memory: DD-SCOPE-001, DD-SCOPE-002, DD-SCOPE-003

Deliverable:
- Standards applied without change (summary)
- Documented deviations with business justification
  (reference Memory Design_Decision entries — Memory is the authoritative record)
- Deployment sequence: correct table creation order and data load order
- Suggested feedback to the design standards based on lessons from this design

This is the final deliverable — present for sign-off.
```

---

## Design Principles

- **Standards first** — start with the module design patterns, customise only when necessary
- **Justify deviations** — every departure from a standard must have a documented reason
- **Agent-native** — agents are primary consumers; every design decision should support
  autonomous discovery and querying
- **No data duplication** — each module owns its data; other modules join back, never copy
- **Platform-optimised** — physical design choices are part of the design, not afterthoughts

---

## Adding More Entities

If your data product has more than two entities, extend D1–D4 by repeating the entity
pattern for each additional entity. Add the corresponding `_H` and `_Keymap` table
references to D4 and D5, and add all additional relationships to the
`table_relationship` seed data in D4.

## Adding More Modules

If Observability, Prediction, or Search are in scope, add a dedicated deliverable
between D5 and D6 for each additional module, following the same pattern:
route to `ANDP-OBSERVABILITY`, `ANDP-PREDICTION`, or `ANDP-SEARCH` respectively,
and update the Module_Registry seed data in D5 accordingly.
