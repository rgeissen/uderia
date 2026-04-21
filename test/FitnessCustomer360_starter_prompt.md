# FitnessCustomer360 — ANDP Design Playbook

> **Purpose:** Minimal-complexity test playbook for the ANDP Agent Pack.
> Covers 3 mandatory modules (Memory, Semantic, Domain) with 2 entities
> drawn from `fitness_db` (real tables, real columns).

---

## How to Use

**Do NOT paste this entire file as a single message.**

The ANDP coordinator routes queries to module specialist slaves based on topic.
Pasting everything at once causes the coordinator to answer directly from base context,
bypassing all slaves. Instead, send **one deliverable at a time** as a focused query.

**Workflow:**
1. Open a new session in Uderia
2. Copy the query block for the current deliverable (everything inside the code fence)
3. Send it — the coordinator routes to the correct specialist
4. Review the output, then move to the next deliverable
5. Each query is self-contained — no need to re-send prior context

---

## Product Reference

*(Not sent as a message — included inline in each query below)*

| Field | Value |
|---|---|
| Product name | FitnessCustomer360 |
| Business purpose | 360-degree customer view: membership profile + purchase history |
| Primary consumers | AI agents, CRM analysts, churn-prediction pipelines |
| Database layout | Single database `FitnessCustomer360` (module prefixes on table names) |
| Modules deployed | Domain, Semantic, Memory |
| Modules deferred | Observability (Phase 2), Prediction (Phase 2) |
| Modules excluded | Search (no vector use case) |

**Source entities:**

| Source table | Columns |
|---|---|
| `fitness_db.Customers` | CustomerID, FirstName, LastName, Email, Phone, Address, City, State, ZipCode, RegistrationDate |
| `fitness_db.Sales` | SaleID, CustomerID, SalesPersonID, SaleDate, TotalAmount |

**Data volumes:** Customers ~10k rows (+500/mo) · Sales ~120k rows (+5k/mo) · Batch load daily

---

## Deliverable Queries

---

### D1 — Requirements & Entity Map

*Routes to: coordinator (cross-module scoping)*

```
@ANDP

For the FitnessCustomer360 data product, produce the Requirements & Entity Map.

Product context:
- Two source entities: Customer (fitness_db.Customers) and Sale (fitness_db.Sales)
- Both entities belong to the Domain module
- Relationship: Sale.CustomerID → Customer.CustomerID (many Sales per Customer)
- Single-database layout: database name FitnessCustomer360
- Modules in scope: Domain, Semantic, Memory
- Observability and Prediction are deferred to Phase 2
- Search is out of scope (no vector use case at this stage)

Deliverable:
- Confirm the two core entities (name, purpose, source table)
- Map each entity to the correct module
- Identify the Customer→Sale relationship with cardinality
- For each deferred/excluded module, state the rationale (this feeds Memory D5)
- Note any anticipated deviations from the design standards

Stop after this deliverable and wait for review.
```

---

### D2 — Logical Data Model

*Routes to: ANDP-DOMAIN (entity structure)*

```
@ANDP

Design the Logical Data Model for the FitnessCustomer360 data product (Domain module).

Entities:
- Customer: CustomerID, FirstName, LastName, Email, Phone, Address, City, State,
  ZipCode, RegistrationDate (source: fitness_db.Customers)
- Sale: SaleID, CustomerID, SalesPersonID, SaleDate, TotalAmount
  (source: fitness_db.Sales)

Deliverable:
- Entity definitions with key business attributes
- Relationships with cardinality (one Customer → many Sales)
- ERD as a Mermaid diagram

Stop after this deliverable and wait for review.
```

---

### D3 — Domain Module Schema

*Routes to: ANDP-DOMAIN*

```
@ANDP

Design the Domain module DDL for the FitnessCustomer360 data product.

Entities:
- Customer: CustomerID, FirstName, LastName, Email, Phone, Address, City, State,
  ZipCode, RegistrationDate (source: fitness_db.Customers)
- Sale: SaleID, CustomerID, SalesPersonID, SaleDate, TotalAmount
  (source: fitness_db.Sales)

Database layout: single database FitnessCustomer360 (all modules share this database).

Before writing any DDL, ask: "Does the database FitnessCustomer360 already exist
on Teradata?" — include CREATE DATABASE only if the answer is no.

Deliverable:
- CREATE DATABASE FitnessCustomer360 (if needed)
- Bi-temporal history tables: Customer_H and Sale_H
- Keymap surrogate key tables: Customer_Keymap and Sale_Keymap
- COMMENT ON TABLE and COMMENT ON COLUMN for every object
- Primary Index selection with justification per table
- Standard views: Customer_Current and Sale_Current

Stop after this deliverable and wait for review.
```

---

### D4 — Semantic Module Schema & Seed Data

*Routes to: ANDP-SEMANTIC*

```
@ANDP

Design the Semantic module for the FitnessCustomer360 data product.

Domain module tables already designed: Customer_H, Sale_H, Customer_Keymap, Sale_Keymap
(all in database FitnessCustomer360)
Deployed modules: Domain, Semantic, Memory

Deliverable:
- DDL for all Semantic tables (entity_metadata, column_metadata, table_relationship,
  naming_standard, data_product_map) in database FitnessCustomer360
- Seed INSERT statements:
  - data_product_map: one row per deployed module (Domain, Semantic, Memory)
  - entity_metadata: one row each for Customer_H and Sale_H
  - naming_standard: full set for FitnessCustomer360 conventions
  - column_metadata: all PII columns at minimum
    (Email, Phone, FirstName, LastName, Address)
  - table_relationship: Customer→Sale FK traversal in both directions
- Run the isolation check query to confirm no entity has zero table_relationship entries

Stop after this deliverable and wait for review.
```

---

### D5 — Memory Module Schema & Seed Data

*Routes to: ANDP-MEMORY*

```
@ANDP

Design the Memory module for the FitnessCustomer360 data product.

Modules considered during this design:
- Domain: DEPLOYED
- Semantic: DEPLOYED
- Memory: DEPLOYED
- Observability: PLANNED (deferred to Phase 2)
- Prediction: PLANNED (deferred to Phase 2)
- Search: DEPRECATED (out of scope — no vector use case)

Database: FitnessCustomer360 (single-database layout)

Deliverable:
- Production-ready DDL for all Memory module tables in database FitnessCustomer360
- Mandatory seed data:
  - Module_Registry: one row for each of the 6 modules above with correct
    deployment_status
  - Design_Decision entries:
    - DD-SCOPE-001: single-database layout choice and rationale
    - DD-SCOPE-002: Search excluded — no vector use case
    - DD-SCOPE-003: Observability and Prediction deferred to Phase 2
  - Query_Cookbook entry QC-SEMANTIC-002: standard ERD generation recipe
  - One cross-module Query_Cookbook entry: Domain → Semantic join pattern

Stop after this deliverable and wait for review.
```

---

### D6 — Integration Patterns

*Routes to: ANDP-SEMANTIC (agent discovery patterns)*

```
@ANDP

Document the integration patterns for the FitnessCustomer360 data product.

Deployed modules: Domain, Semantic, Memory — all in database FitnessCustomer360
Domain tables: Customer_H, Sale_H
Semantic tables: entity_metadata, column_metadata, table_relationship,
  naming_standard, data_product_map

Deliverable:
- Customer→Sale join pattern specific to this product
- Data flow narrative: fitness_db.Customers + fitness_db.Sales → Domain module
- Agent consumption sequence: how an agent discovers and queries FitnessCustomer360
  end-to-end using data_product_map and v_relationship_paths

Stop after this deliverable and wait for review.
```

---

### D7 — Deviations & Implementation Plan

*Routes to: coordinator (cross-module sign-off)*

```
@ANDP

Produce the final deviations summary and implementation plan for FitnessCustomer360.

Deployed modules: Domain, Semantic, Memory (database FitnessCustomer360)
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
