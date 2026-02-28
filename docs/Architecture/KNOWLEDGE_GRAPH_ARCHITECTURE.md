# Knowledge Graph Component Architecture: Context-Enriching Entity-Relationship System

> Dual-layer graph store with SQLite persistence and NetworkX algorithms, D3.js force-directed visualization, automatic planner context injection (guardrail), LLM-driven entity management, and multi-profile management UI — all scoped per `(profile_id, user_uuid)` for multi-user isolation.

## Overview

The Knowledge Graph component (`TDA_KnowledgeGraph`) captures database topology, business concepts, metrics, and domain taxonomies as a typed entity-relationship graph. Unlike static schema documentation, the knowledge graph is a **living, queryable model** that grows as users interact with the platform — through LLM inference, manual enrichment, bulk import, or (future) MCP schema auto-discovery.

The component's primary value is **planner context injection**: before every strategic planning call, the system extracts a relevant subgraph based on the user's query and injects it into the LLM prompt. This guides tool selection, SQL construction, and argument generation — functioning as a semantic guardrail that reduces hallucination and improves first-attempt success rates.

The knowledge graph is scoped per `(profile_id, user_uuid)`, meaning each profile builds its own domain model in isolation. This aligns with the platform's multi-profile architecture where different profiles connect to different MCP servers and data sources.

---

## Table of Contents

- [Design Philosophy](#design-philosophy)
- [File Structure](#file-structure)
- [System Architecture](#system-architecture)
  - [Data Flow](#data-flow)
  - [Dual-Layer Architecture](#dual-layer-architecture)
- [Data Model](#data-model)
  - [Entity Schema](#entity-schema)
  - [Relationship Schema](#relationship-schema)
  - [Type Enumerations](#type-enumerations)
- [Backend Architecture](#backend-architecture)
  - [GraphStore Class](#graphstore-class)
  - [Entity CRUD](#entity-crud)
  - [Relationship CRUD](#relationship-crud)
  - [Bulk Operations](#bulk-operations)
  - [NetworkX Graph Algorithms](#networkx-graph-algorithms)
  - [Cross-Profile Enumeration](#cross-profile-enumeration)
- [Component Handler](#component-handler)
  - [Tool Actions](#tool-actions)
  - [Context Enrichment (Guardrail)](#context-enrichment-guardrail)
  - [Query Search Algorithm](#query-search-algorithm)
  - [Prompt Injection Format](#prompt-injection-format)
- [Frontend Architecture](#frontend-architecture)
  - [D3 Visualization — Three Display Modes](#d3-visualization--three-display-modes)
  - [Interactive Features](#interactive-features)
  - [Theme Compliance](#theme-compliance)
  - [Management UI](#management-ui)
- [REST API](#rest-api)
  - [Entity Endpoints](#entity-endpoints)
  - [Relationship Endpoints](#relationship-endpoints)
  - [Graph Operations](#graph-operations)
  - [Management Endpoints](#management-endpoints)
- [Integration Points](#integration-points)
  - [Planner Integration](#planner-integration)
  - [Component System Integration](#component-system-integration)
  - [Profile Configuration](#profile-configuration)
  - [Session UI Integration](#session-ui-integration)
- [MCP Schema Discovery (V2 Stub)](#mcp-schema-discovery-v2-stub)
- [Security & Isolation](#security--isolation)
- [Performance Characteristics](#performance-characteristics)
- [Roadmap](#roadmap)
- [File Reference](#file-reference)

---

## Design Philosophy

### 1. Dual-Layer Storage

SQLite provides durable, transactional CRUD with multi-user isolation. NetworkX provides graph algorithms (BFS, shortest path, centrality, cycle detection) without reimplementing graph theory. The NetworkX layer is lazy-loaded from SQLite and cached — invalidated on any write operation.

### 2. Guardrail, Not Controller

The knowledge graph enriches the LLM's context but does not constrain it. At `medium` intensity, graph context is advisory; at `heavy` intensity, the LLM is instructed to strictly validate against known relationships. The LLM retains autonomy to deviate when the graph is incomplete.

### 3. Profile-Scoped Isolation

Each `(profile_id, user_uuid)` pair owns an independent graph. A profile connected to a sales database builds a different knowledge graph than one connected to an HR system. Cross-profile enumeration is read-only for management UI purposes.

### 4. Progressive Enrichment

Graphs start empty and grow through three channels:
- **LLM-inferred**: The LLM calls `add_entity`/`add_relationship` during conversation
- **Manual**: Users import JSON files or use the REST API
- **Auto-discovery** (V2): MCP tool schemas parsed to extract topology

### 5. Deterministic Fast-Path

The component handler declares `is_deterministic = True`. When the LLM calls `TDA_KnowledgeGraph`, the response is computed directly from the graph store without an additional LLM call — saving tokens and latency.

---

## File Structure

```
components/builtin/knowledge_graph/
├── manifest.json           # Component metadata, tool definition, render targets
├── handler.py              # KnowledgeGraphHandler — process() + context enrichment
├── graph_store.py          # GraphStore — dual-layer SQLite + NetworkX engine
├── renderer.js             # D3.js v7 force-directed visualization (~1084 lines)
├── instructions.json       # Intensity-keyed LLM guidance (none/medium/heavy)
├── discovery.py            # MCPSchemaDiscovery — V2 stub for auto-population
└── __init__.py

schema/
└── 21_knowledge_graph.sql  # SQLite table definitions + indexes

static/js/
├── api.js                  # Frontend API functions (loadKnowledgeGraphList, etc.)
└── handlers/
    └── knowledgeGraphPanelHandler.js  # Management UI for Resource Panel + Intelligence page

templates/
└── index.html              # Split panel DOM (#kg-split-panel), Intelligence tab
```

---

## System Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          KNOWLEDGE GRAPH DATA FLOW                          │
│                                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │  User Query  │    │  REST API    │    │  JSON Import │                   │
│  │  (session)   │    │  (manual)    │    │  (file)      │                   │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                   │
│         │                   │                   │                           │
│         ▼                   ▼                   ▼                           │
│  ┌─────────────────────────────────────────────────────┐                   │
│  │              GraphStore(profile_id, user_uuid)       │                   │
│  │  ┌───────────────────┐  ┌─────────────────────────┐ │                   │
│  │  │   SQLite Layer    │  │   NetworkX DiGraph       │ │                   │
│  │  │   ─────────────   │  │   ──────────────────     │ │                   │
│  │  │   kg_entities     │──▶  Lazy-loaded on first    │ │                   │
│  │  │   kg_relationships│  │  graph algorithm call    │ │                   │
│  │  │                   │  │                          │ │                   │
│  │  │   CRUD, search,   │  │  BFS, shortest path,    │ │                   │
│  │  │   persistence     │  │  centrality, cycles      │ │                   │
│  │  └───────────────────┘  └─────────────────────────┘ │                   │
│  └──────────────────────────┬──────────────────────────┘                   │
│                              │                                              │
│              ┌───────────────┼───────────────┐                              │
│              │               │               │                              │
│              ▼               ▼               ▼                              │
│  ┌───────────────┐ ┌──────────────┐ ┌───────────────┐                      │
│  │  Context      │ │  Tool Call   │ │  Visualization│                      │
│  │  Enrichment   │ │  Response    │ │  Spec         │                      │
│  │  (guardrail)  │ │  (inline)    │ │  (D3 graph)   │                      │
│  └───────┬───────┘ └──────┬───────┘ └───────┬───────┘                      │
│          │                │                  │                              │
│          ▼                ▼                  ▼                              │
│  ┌───────────────┐ ┌──────────────┐ ┌───────────────┐                      │
│  │  Planner      │ │  Chat        │ │  Split Panel  │                      │
│  │  Prompt       │ │  Message     │ │  D3 Force     │                      │
│  │  Injection    │ │  (HTML)      │ │  Graph        │                      │
│  └───────────────┘ └──────────────┘ └───────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Dual-Layer Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │            GraphStore Instance                │
                    │      (profile_id, user_uuid scoped)          │
                    │                                              │
                    │  ┌────────────────┐  ┌────────────────────┐ │
                    │  │  SQLite Layer  │  │  NetworkX Layer    │ │
                    │  │                │  │                    │ │
                    │  │  add_entity()  │  │  extract_subgraph_ │ │
                    │  │  get_entity()  │  │    adaptive()      │ │
                    │  │  search()      │  │  shortest_path()   │ │
                    │  │  list()        │  │  centrality()      │ │
                    │  │  update()      │  │  detect_cycles()   │ │
                    │  │  delete()      │  │  connected()       │ │
                    │  │  import_bulk() │  │  get_stats()       │ │
                    │  │  clear_graph() │  │                    │ │
                    │  │                │  │  Lazy-loaded,      │ │
                    │  │  ACID durable  │  │  cached,           │ │
                    │  │  Multi-user    │  │  invalidated on    │ │
                    │  │                │  │  any write          │ │
                    │  └────────────────┘  └────────────────────┘ │
                    └──────────────────────────────────────────────┘
                                          │
                    Write ops ────────────┘
                    (add/update/delete)
                    trigger _invalidate_cache()
                    → self._graph = None
                    → Next algorithm call
                      re-loads from SQLite
```

---

## Data Model

### Entity Schema

**Table:** `kg_entities` (SQLite, `tda_auth.db`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing entity ID |
| `profile_id` | TEXT NOT NULL | Profile scope |
| `user_uuid` | TEXT NOT NULL | User scope |
| `name` | TEXT NOT NULL | Entity display name |
| `entity_type` | TEXT NOT NULL | One of 8 enumerated types |
| `properties_json` | TEXT | JSON blob: description, data_type, business_meaning, etc. |
| `source` | TEXT NOT NULL | Origin: `manual`, `mcp_discovery`, `llm_inferred` |
| `source_detail` | TEXT | Optional metadata (MCP server ID, tool name) |
| `created_at` | TIMESTAMP | UTC creation time |
| `updated_at` | TIMESTAMP | UTC last modification |

**Unique constraint:** `(profile_id, user_uuid, name, entity_type)`

**Indexes:**
- `idx_kg_entities_profile_user` — Fast profile/user filtering
- `idx_kg_entities_type` — Type-filtered queries
- `idx_kg_entities_name` — Case-insensitive name lookup (`COLLATE NOCASE`)

### Relationship Schema

**Table:** `kg_relationships` (SQLite, `tda_auth.db`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing relationship ID |
| `profile_id` | TEXT NOT NULL | Profile scope |
| `user_uuid` | TEXT NOT NULL | User scope |
| `source_entity_id` | INTEGER FK | Source node (CASCADE delete) |
| `target_entity_id` | INTEGER FK | Target node (CASCADE delete) |
| `relationship_type` | TEXT NOT NULL | One of 8 enumerated types |
| `cardinality` | TEXT | Optional: `1:1`, `1:N`, `N:M` |
| `metadata_json` | TEXT | JSON blob: description, confidence, evidence |
| `source` | TEXT NOT NULL | Origin tracking |
| `created_at` | TIMESTAMP | UTC creation time |

**Unique constraint:** `(profile_id, user_uuid, source_entity_id, target_entity_id, relationship_type)`

**Indexes:**
- `idx_kg_relationships_profile_user` — Fast profile/user filtering
- `idx_kg_relationships_source` — Outgoing edge queries
- `idx_kg_relationships_target` — Incoming edge queries
- `idx_kg_relationships_type` — Type-filtered queries

### Type Enumerations

**Entity Types (8):**

| Type | Semantic | Example |
|------|----------|---------|
| `database` | Top-level data source | `SalesDB`, `HRSystem` |
| `table` | Relational table/object | `orders`, `employees` |
| `column` | Table column/field | `order_date`, `salary` |
| `foreign_key` | FK constraint entity | `orders.customer_id → customers.id` |
| `business_concept` | Domain concept | `Customer Lifetime Value`, `Churn Rate` |
| `taxonomy` | Classification hierarchy | `Product Category`, `Region` |
| `metric` | Measurable KPI | `Revenue`, `NPS Score` |
| `domain` | Business domain | `Finance`, `Marketing` |

**Relationship Types (8):**

| Type | Semantic | Example |
|------|----------|---------|
| `contains` | Parent → child containment | `database → table`, `table → column` |
| `foreign_key` | FK reference | `orders.customer_id → customers.id` |
| `is_a` | Inheritance/taxonomy | `Premium Customer is_a Customer` |
| `has_property` | Attribute association | `Order has_property status` |
| `measures` | Metric measurement | `Revenue measures Sales Performance` |
| `derives_from` | Calculation derivation | `Profit derives_from Revenue - Costs` |
| `depends_on` | Dependency | `Report depends_on Daily ETL` |
| `relates_to` | Generic association | `Marketing relates_to Sales` |

**Source Origins (5):**

| Source | Meaning | Set By |
|--------|---------|--------|
| `manual` | User-created via REST API or import | REST endpoints, import |
| `mcp_discovery` | Auto-discovered from MCP schemas | Discovery module (V2) |
| `llm_inferred` | Created by LLM during conversation | `TDA_KnowledgeGraph` tool |
| `constructor_structural` | Inferred during KG generation (Phase 3 gap-fill) | `kg_generate()` pipeline |
| `constructor_fk_inferred` | FK relationships inferred from naming conventions, shared columns, or column properties (Phase 3.5) | `kg_generate()` pipeline |

---

## Backend Architecture

### GraphStore Class

**Location:** `components/builtin/knowledge_graph/graph_store.py`

The `GraphStore` class is the single access point for all graph operations. It is instantiated per request with a specific `(profile_id, user_uuid)` scope:

```python
store = GraphStore(profile_id="profile-123", user_uuid="user-456")
```

The class manages two synchronized layers:
1. **SQLite** — All CRUD operations go directly to the database
2. **NetworkX** — Lazy-loaded `DiGraph` cached in `self._graph`, invalidated by `_invalidate_cache()` on every write

### Entity CRUD

| Method | Signature | Behavior |
|--------|-----------|----------|
| `add_entity()` | `(name, entity_type, properties?, source?, source_detail?) → int` | Upsert via `INSERT ON CONFLICT UPDATE`. Returns entity ID. |
| `get_entity()` | `(entity_id) → dict?` | Lookup by ID within profile scope. |
| `get_entity_by_name()` | `(name, entity_type?) → dict?` | Case-insensitive name lookup. Optional type filter. |
| `search_entities()` | `(query_text, limit?, entity_type?) → list[dict]` | Substring match on `name` and `properties_json`. |
| `list_entities()` | `(entity_type?, limit?) → list[dict]` | List all entities, optionally filtered by type. Default limit: 200. |
| `update_entity()` | `(entity_id, properties) → bool` | Merge new properties into existing `properties_json`. |
| `delete_entity()` | `(entity_id) → bool` | Delete entity and all relationships (CASCADE). |

### Relationship CRUD

| Method | Signature | Behavior |
|--------|-----------|----------|
| `add_relationship()` | `(source_entity_id, target_entity_id, relationship_type, cardinality?, metadata?, source?) → int` | Upsert via `INSERT ON CONFLICT UPDATE`. Returns relationship ID. |
| `get_relationships()` | `(entity_id, direction?) → list[dict]` | Get edges from/to entity. Direction: `outgoing`, `incoming`, or `both`. Deduplicates for self-referential edges. |
| `list_relationships()` | `(entity_id?, relationship_type?, limit?) → list[dict]` | List with optional filters. Default limit: 200. |
| `delete_relationship()` | `(relationship_id) → bool` | Delete single edge. |

### Bulk Operations

| Method | Signature | Behavior |
|--------|-----------|----------|
| `import_bulk()` | `(entities, relationships) → {entities_added, relationships_added}` | Batch import. Entities resolved by name for relationship linking. Logs warnings on failures. |
| `clear_graph()` | `() → {entities_deleted, relationships_deleted}` | Delete all data for the profile/user scope. |

**Import format:**
```json
{
  "entities": [
    {"name": "orders", "entity_type": "table", "properties": {"description": "Customer orders"}}
  ],
  "relationships": [
    {"source_name": "orders", "source_type": "table",
     "target_name": "customers", "target_type": "table",
     "relationship_type": "foreign_key", "cardinality": "N:1"}
  ]
}
```

### NetworkX Graph Algorithms

All graph algorithm methods lazy-load the full graph from SQLite into a `networkx.DiGraph` on first call. The graph is cached in `self._graph` and invalidated (set to `None`) by any write operation.

| Method | Signature | Algorithm | Use Case |
|--------|-----------|-----------|----------|
| `extract_subgraph_adaptive()` | `(seed_entity_ids, query_entity_ids?, max_nodes?) → {entities, relationships}` | Three-phase entity-type-aware extraction (see below) | Context enrichment, visualization |
| `extract_subgraph()` | `(entity_ids, depth?, max_nodes?) → {entities, relationships}` | Legacy BFS traversal (both directions) from seed entities | Deprecated — use `extract_subgraph_adaptive()` |
| `get_full_graph()` | `(max_nodes?) → {entities, relationships}` | Full graph export (capped) | Full visualization |
| `find_shortest_path()` | `(source_id, target_id) → list[int]?` | Undirected shortest path | "How are these tables related?" |
| `get_connected_entities()` | `(entity_id) → {descendants, ancestors}` | Directed reachability | Impact analysis |
| `get_entity_importance()` | `() → {entity_id: float}` | Degree centrality | Node sizing in visualization |
| `detect_cycles()` | `() → list[list[int]]` | Simple cycle detection (capped at 20) | Taxonomy validation |
| `get_stats()` | `() → dict` | Entity/relationship type breakdowns, connected components, density, cycle detection | Dashboard, card metadata |

#### Adaptive Subgraph Extraction Algorithm

The `extract_subgraph_adaptive()` method replaces the fixed-depth BFS with a scalable, entity-type-aware algorithm designed for schemas with 1000s of entities. It uses three phases:

```
Phase 1: Structural Discovery (unbounded)
├── Phase 1a: FK-Chain Traversal
│   BFS from seeds through table/foreign_key nodes ONLY.
│   NO depth limit → handles 3, 4, 5, N-way JOIN chains.
│   Skips database hub (would explode), columns (detail), semantic nodes.
│
├── Phase 1b: Joinable Table Discovery
│   For each discovered table → collect its column names.
│   Find OTHER tables sharing those column names → join candidates.
│   Iterate up to 3 rounds for transitive joins:
│     Round 1: orders(customer_id) → discovers customers(customer_id)
│     Round 2: customers(region_id) → discovers regions(region_id)
│     Round 3: regions(country_id) → discovers countries(country_id)
│
└── Phase 1c: Database Context
    For each discovered table → add its parent database entity.
    Context only — don't expand from database nodes.

Phase 2: Column Expansion (budget-aware)
    column_budget = max_nodes - structural_count
    Sort tables: query-matched first, then by distance from seeds.
    Add columns per-table until budget exhausted.

Phase 3: Semantic Enrichment (capped at 50)
    Add business_concept, metric, taxonomy, domain nodes
    connected to discovered structural entities.
```

**Key design choices:**
- **Entity-type awareness**: Only `table` and `foreign_key` nodes are expanded during structural discovery. Database hub nodes (which connect to all tables) are explicitly excluded to prevent explosion.
- **No fixed depth limit**: FK chains are traversed without bound, ensuring 3, 4, 5, or N-way JOINs are always discovered.
- **Iterative joinable-table discovery**: Even without explicit FK edges, tables are connected through shared column names (e.g., `customer_id` in both `orders` and `customers`). Up to 3 iterative rounds discover transitive join paths.
- **Budget-aware column expansion**: Columns are added only after structural discovery, prioritizing query-matched tables and limiting to the remaining node budget.
- **Default `max_nodes=500`** (up from 50): Supports schemas with hundreds of tables while keeping output manageable.

**Scalability:**
| Schema size | Typical result |
|-------------|---------------|
| 10 tables | All tables + all columns (~100 nodes) |
| 100 tables | ~30-50 relevant tables + columns for top priority (~300 nodes) |
| 1000 tables | ~30-100 relevant tables + columns for top ~50 (~500 nodes) |

All phases are O(V + E) combined.

### Cross-Profile Enumeration

**Static method** (no instance needed):

```python
GraphStore.list_all_graphs(user_uuid) → list[dict]
```

Returns one entry per `profile_id` that has at least one entity, with summary statistics (counts, type breakdowns, timestamps). Used by the management UI to show all knowledge graphs across profiles.

---

## Component Handler

**Location:** `components/builtin/knowledge_graph/handler.py`

The `KnowledgeGraphHandler` serves dual purposes:
1. **Tool handler**: Processes `TDA_KnowledgeGraph` tool calls from the LLM
2. **Context enrichment**: Provides `get_context_enrichment()` for planner guardrail injection

### Tool Actions

The `TDA_KnowledgeGraph` tool accepts an `action` parameter routing to five handlers:

| Action | Arguments | Returns | Purpose |
|--------|-----------|---------|---------|
| `query` | `query_text?`, `entity_type?` | HTML results or stats | Search entities, show graph statistics |
| `visualize` | `entity_name?`, `depth?`, `title?` | D3 force-graph spec | Interactive subgraph visualization |
| `add_entity` | `entity_name`, `entity_type`, `properties?` | Confirmation HTML | Add entity (source: `llm_inferred`) |
| `add_relationship` | `entity_name`, `target_entity`, `relationship_type`, `entity_type?`, `target_entity_type?` | Confirmation HTML | Create edge between entities |
| `get_context` | `query_text?` | Pre-formatted enrichment text | Debug/test context enrichment output |

All actions return `ComponentRenderPayload` with either `html` (inline display) or `spec` (D3 visualization data).

### Context Enrichment (Guardrail)

The core intelligence feature. Called automatically before every strategic planning call:

```python
async def get_context_enrichment(query, profile_id, user_uuid) -> str
```

**Pipeline:**

```
User Query: "Show me orders with high revenue customers"
                    │
                    ▼
    ┌───────────────────────────────┐
    │  1. Tokenize query            │
    │     → ["orders", "high",      │
    │        "revenue", "customers"]│
    └───────────────┬───────────────┘
                    │
                    ▼
    ┌───────────────────────────────┐
    │  2. Search entities           │
    │     Full query + individual   │
    │     keywords (skip stop words)│
    │     → match: orders (table),  │
    │       revenue (metric),       │
    │       customers (table)       │
    └───────────────┬───────────────┘
                    │
                    ▼
    ┌───────────────────────────────┐
    │  3. Adaptive extraction       │
    │     max_nodes=500             │
    │     → FK chains (unbounded),  │
    │       joinable tables,        │
    │       budget-aware columns    │
    └───────────────┬───────────────┘
                    │
                    ▼
    ┌───────────────────────────────┐
    │  4. Format for prompt         │
    │     Structured text with      │
    │     entity types, properties, │
    │     and relationships         │
    └───────────────┬───────────────┘
                    │
                    ▼
    Injected into planner's
    knowledge_context_str
```

### Query Search Algorithm

The search combines two strategies for maximum recall:

1. **Direct substring search**: The full query string is matched against entity names and `properties_json`
2. **Tokenized keyword search**: Individual words (3+ chars, stop words excluded) are each searched independently

Results are deduplicated by entity ID and capped at 15 matches.

**Stop words excluded:** `the`, `show`, `get`, `list`, `find`, `all`, `from`, `with`, `for`, `and`, `that`, `this`, `what`, `how`, `many`, `much`, `are`, `was`, `were`, `has`, `have`, `been`, `can`, `will`, `please`, `help`, `give`, `tell`, `about`, `into`, `each`

### Prompt Injection Format

The enrichment text follows a structured format injected into the planner's knowledge context:

```
--- KNOWLEDGE GRAPH CONTEXT ---
The following known entities and relationships may inform your planning:

TABLE ENTITIES:
  - orders (Customer purchase records; type: table)
  - customers (Customer master data; type: table)

COLUMN ENTITIES:
  - customer_id (FK to customers; type: integer)
  - order_date (Purchase timestamp; type: date)
  - amount (Order total; business: Revenue metric source)

METRIC ENTITIES:
  - Revenue (Total order amounts; business: Primary KPI)

KNOWN RELATIONSHIPS:
  - SalesDB --[contains]--> orders
  - orders --[contains]--> customer_id
  - orders --[foreign_key [N:1]]--> customers — Via customer_id
  - Revenue --[measures]--> orders.amount
--- END KNOWLEDGE GRAPH CONTEXT ---
```

---

## Frontend Architecture

### D3 Visualization — Three Display Modes

**Renderer:** `components/builtin/knowledge_graph/renderer.js` (D3 v7 via CDN)

The visualization follows the Canvas component's progressive display pattern:

| Mode | Entry Point | Size | Purpose |
|------|-------------|------|---------|
| **A. Inline Compact** | `renderKGInlineCompact()` | 200px height in chat | Mini preview with simplified force layout |
| **B. Split Panel** | `openKGSplitPanel()` | 50% viewport, side-by-side with chat | Full interactive graph with toolbar |
| **C. Fullscreen** | `toggleKGFullscreen()` | 100% viewport | Maximum graph exploration space |

**Transition flow:**
```
Chat message → [Inline Compact]
                    │
                    ├── "Open in Graph →" button
                    ▼
              [Split Panel]
                    │
                    ├── Fullscreen button (⊞)
                    ▼
              [Fullscreen]
                    │
                    ├── Exit fullscreen
                    ▼
              [Split Panel]
                    │
                    ├── Close button (×)
                    ▼
              [Panel hidden]
```

**Mutual exclusion:** Opening the KG split panel automatically closes the Canvas split panel (and vice versa), dispatching `kg-requesting-split` / `canvas-requesting-split` events for cleanup.

### Interactive Features

| Feature | Description | Implementation |
|---------|-------------|----------------|
| **Force-directed layout** | Spring-charge physics for organic node positioning | `d3.forceSimulation` with link, charge, center, collision forces |
| **Zoom & pan** | Mouse wheel zoom (0.1x–4x), drag to pan | `d3.zoom()` on SVG container |
| **Node drag** | Reposition individual nodes | `d3.drag()` with simulation restart |
| **Hover glow** | Entity-type-colored glow filter on hover | SVG `feGaussianBlur` + `feFlood` filter per type |
| **Click focus** | Click node to highlight connected subgraph, dim unrelated | Connected-set computation, opacity animation |
| **Edge gradients** | Edges colored as gradient from source to target type | SVG `linearGradient` per link |
| **Directional arrows** | Arrowhead markers on edges | SVG `marker` with `refX` offset |
| **Search** | Toolbar input filters nodes by name (live) | Opacity toggle on input event |
| **Entity type filters** | Colored pills toggle entity type visibility | `display:none` on filtered nodes + connected edges |
| **Zoom to fit** | Button resets viewport | `d3.zoom.transform` transition |
| **Export PNG** | Button exports 2x resolution PNG | SVG → Image → Canvas → Blob download |
| **Tooltips** | Hover shows entity properties, type, business meaning | HTML overlay positioned at cursor |
| **Legend** | Color-coded entity type legend overlay | Bottom-right glass panel |
| **Animated entry** | Nodes fade in sequentially, edges draw progressively | CSS transitions + `stroke-dashoffset` animation |
| **Center entity pulse** | Pulsing ring animation on the queried entity | CSS `@keyframes kg-pulse` |
| **Node importance sizing** | Higher-centrality nodes rendered larger | Degree centrality → circle radius |

### Theme Compliance

The renderer uses CSS custom properties for all colors, ensuring compatibility across all three themes (legacy dark, modern, light):

```css
/* SVG elements use CSS fill/stroke to evaluate variables live */
.kg-node-name  { fill: var(--text-primary, #e5e7eb); }
.kg-edge-label { fill: var(--text-muted, #6b7280); opacity: 0.5; }
.kg-mini-label { fill: var(--text-muted, #9ca3af); }
.kg-mini-link  { stroke: var(--border-primary, #4b5563); }

/* Light theme adjustments */
[data-theme="light"] .kg-edge-label { opacity: 0.7; }
[data-theme="light"] .kg-mini-link  { stroke-opacity: 0.6; }
```

Entity type colors are provided by the backend handler (`ENTITY_TYPE_COLORS`) and passed through the D3 spec. These are constant across themes:

| Entity Type | Color | Hex |
|-------------|-------|-----|
| database | Blue | `#3b82f6` |
| table | Green | `#22c55e` |
| column | Lime | `#a3e635` |
| foreign_key | Amber | `#f59e0b` |
| business_concept | Violet | `#8b5cf6` |
| taxonomy | Pink | `#ec4899` |
| metric | Cyan | `#06b6d4` |
| domain | Orange | `#f97316` |

### Management UI

Knowledge graphs are managed in two UI locations:

**1. Resource Panel (Sidebar)**

Location: `knowledgeGraphPanelHandler.js` → `loadKnowledgeGraphsPanel()`

- Compact cards using CSS variables (`--card-bg`, `--border-primary`)
- Active indicator for the profile whose KG matches the current session's profile
- Export button (downloads `.json` file)
- Delete button (styled confirmation modal)
- IFOC badge showing profile type with color coding

**2. Intelligence Performance Page (Third Tab)**

Location: `knowledgeGraphPanelHandler.js` → `loadKnowledgeGraphsIntelligenceTab()`

- Full `glass-panel` cards with `card-btn` action system
- Entity/relationship count display
- Entity type pills showing type breakdown
- Import button with file picker (`.json`)
- Export and Delete buttons
- Promote button (placeholder for future cross-profile migration)
- Tab counter showing number of knowledge graphs
- iPadOS file picker workaround (removes `accept` attribute)

**Cross-panel refresh:** Deleting or importing a KG from either location refreshes both panels to maintain consistency.

---

## REST API

All endpoints are JWT-authenticated and scoped to the current user. The `profile_id` is provided as a query parameter.

### Entity Endpoints

| Endpoint | Method | Parameters | Response |
|----------|--------|------------|----------|
| `/v1/knowledge-graph/entities` | `POST` | Body: `{profile_id, name, entity_type, properties?, source?}` | `{status, entity: {id, name, ...}}` |
| `/v1/knowledge-graph/entities` | `GET` | Query: `profile_id`, `entity_type?`, `search?` | `{status, entities: [...]}` |
| `/v1/knowledge-graph/entities/<id>` | `PUT` | Body: `{profile_id, properties}` | `{status, updated: bool}` |
| `/v1/knowledge-graph/entities/<id>` | `DELETE` | Query: `profile_id` | `{status, deleted: bool}` |

### Relationship Endpoints

| Endpoint | Method | Parameters | Response |
|----------|--------|------------|----------|
| `/v1/knowledge-graph/relationships` | `POST` | Body: `{profile_id, source_entity_id, target_entity_id, relationship_type, cardinality?, metadata?}` | `{status, relationship: {id, ...}}` |
| `/v1/knowledge-graph/relationships` | `GET` | Query: `profile_id`, `entity_id?`, `relationship_type?` | `{status, relationships: [...]}` |
| `/v1/knowledge-graph/relationships/<id>` | `DELETE` | Query: `profile_id` | `{status, deleted: bool}` |

### Graph Operations

| Endpoint | Method | Parameters | Response |
|----------|--------|------------|----------|
| `/v1/knowledge-graph/subgraph` | `GET` | Query: `profile_id`, `entity_name`, `max_nodes?` | `{status, nodes, edges, node_count}` |
| `/v1/knowledge-graph/stats` | `GET` | Query: `profile_id` | `{status, stats: {total_entities, total_relationships, entity_types, ...}}` |
| `/v1/knowledge-graph/import` | `POST` | Body: `{profile_id, entities: [...], relationships: [...]}` | `{status, entities_added, relationships_added}` |
| `/v1/knowledge-graph/clear` | `DELETE` | Query: `profile_id` | `{status, entities_deleted, relationships_deleted}` |
| `/v1/knowledge-graph/context` | `GET` | Query: `profile_id`, `query` | `{status, context_text, entity_count}` |
| `/v1/knowledge-graph/generate` | `POST` | Body: `{profile_id, llm_config_id?}` | `{status, structural, semantic, phase3_relationships, phase3_5_fk_relationships, phase4_relationships, total}` |
| `/v1/knowledge-graph/discover` | `POST` | Body: `{profile_id, tools: [...]}` | `{status, entities_discovered, relationships_discovered}` (V2 stub) |

### Management Endpoints

| Endpoint | Method | Parameters | Response |
|----------|--------|------------|----------|
| `/v1/knowledge-graph/list` | `GET` | None (user-scoped) | `{status, knowledge_graphs: [{profile_id, total_entities, entity_types, ...}]}` |
| `/v1/knowledge-graph/export` | `GET` | Query: `profile_id` | JSON file download (Content-Disposition: attachment) |

**Export file format:**
```json
{
  "knowledge_graph_export": true,
  "version": "1.0",
  "profile_id": "profile-123",
  "profile_tag": "@OPTIM",
  "exported_at": "2026-02-27T10:30:00+00:00",
  "stats": {
    "total_entities": 42,
    "total_relationships": 38
  },
  "entities": [...],
  "relationships": [...]
}
```

---

## Integration Points

### Planner Integration

The knowledge graph injects context into the strategic planner via the component system's `get_context_enrichment()` pipeline:

```
planner.py:2609
    │
    ▼
get_component_context_enrichment(query, profile_id, user_uuid)
    │   (manager.py:93)
    ▼
ComponentManager.get_context_enrichment()
    │   (manager.py:658)
    │   Iterates active components with supports_context_enrichment=true
    ▼
KnowledgeGraphHandler.get_context_enrichment()
    │   (handler.py:116)
    │   1. Search entities for query keywords
    │   2. Adaptive subgraph extraction (max_nodes=500)
    │      → FK chains, joinable tables, budget-aware columns
    │   3. Format as structured text
    ▼
knowledge_context_str += enrichment
    │   (planner.py:2618)
    ▼
Injected into WORKFLOW_META_PLANNING_PROMPT
```

The enrichment text is appended to the planner's `knowledge_context_str`, which already includes knowledge repository retrieval results. This means the LLM receives both RAG case examples and knowledge graph topology in a single context section.

### Component System Integration

The knowledge graph plugs into the standard component lifecycle:

| Integration Point | Mechanism | File |
|-------------------|-----------|------|
| **Tool definition** | `manifest.json` → `tool_definition` | Injected into LLM context via `get_tool_definitions()` |
| **Instructions** | `instructions.json` → intensity-keyed text | Injected via `get_instructions_text()` |
| **Fast-path execution** | `is_deterministic = True` | Bypasses tactical LLM in `phase_executor.py` |
| **LangChain tool** | Auto-generated `StructuredTool` | For `llm_only`, `rag_focused`, `genie` profiles |
| **Context enrichment** | `supports_context_enrichment: true` | Called before strategic planning |
| **Renderer discovery** | `frontend.renderer_file` + CDN deps | D3 loaded on first use |

### Profile Configuration

The knowledge graph is enabled per-profile via `componentConfig`:

```json
{
  "componentConfig": {
    "knowledge_graph": {
      "enabled": true,
      "intensity": "medium"
    }
  }
}
```

**Intensity levels:**

| Level | LLM Behavior |
|-------|-------------|
| `none` | KG disabled — no tool, no instructions, no enrichment |
| `medium` | Use graph context as guidance when available. Add entities/relationships when user explicitly requests. |
| `heavy` | Strictly validate against graph. Proactively suggest adding discovered entities. Always offer to visualize relationships. |

**Default:** Enabled for all profile types (`tool_enabled`, `llm_only`, `rag_focused`, `genie`) at `medium` intensity.

### Session UI Integration

**Split panel DOM** is defined in `templates/index.html`:

```html
<aside id="kg-split-panel" style="display:none;">
    <div class="kg-split-header">
        <span id="kg-split-title" class="kg-split-title-text">Knowledge Graph</span>
        <div class="kg-split-header-actions">
            <button id="kg-split-fullscreen" class="kg-split-action-btn">...</button>
            <button id="kg-split-close" class="kg-split-action-btn">...</button>
        </div>
    </div>
    <div id="kg-split-content" class="kg-split-body"></div>
</aside>
```

The split panel persists across messages within a session — when a new KG visualization is rendered inline, clicking "Open in Graph" updates the existing panel rather than creating a new one. The panel state (open/closed, current spec) is stored in module-level variables in `renderer.js`.

---

## MCP Schema Discovery (V2 Stub)

**Location:** `components/builtin/knowledge_graph/discovery.py`

The `MCPSchemaDiscovery` class provides a placeholder for automatic knowledge graph population from MCP server tool schemas. Currently returns `{entities_discovered: 0, relationships_discovered: 0}`.

**V2 Implementation Plan:**

1. Parse tool `inputSchema` definitions from MCP servers
2. Extract `database_name`, `object_name`, `column_name` parameters → create entities
3. Infer `table → column` containment relationships from tool groupings
4. Detect foreign key hints from parameter descriptions
5. Extract argument `enum` values → create taxonomy nodes
6. Parse resource URIs for additional schema information

**Trigger:** `POST /v1/knowledge-graph/discover` with tool definitions in the body.

---

## Security & Isolation

| Concern | Mechanism |
|---------|-----------|
| **Multi-user isolation** | All queries scoped by `(profile_id, user_uuid)` composite key |
| **Cross-user visibility** | Impossible — no endpoint accepts `user_uuid` as input; derived from JWT |
| **Cross-profile reads** | `list_all_graphs()` only returns metadata (counts), not entity data |
| **SQL injection** | Parameterized queries throughout `GraphStore` |
| **Bulk import validation** | Entity types validated against `ENTITY_TYPES` enum; invalid types raise `ValueError` |
| **JWT authentication** | All REST endpoints decorated with `@require_auth` |

---

## Performance Characteristics

| Operation | Complexity | Notes |
|-----------|------------|-------|
| Entity CRUD | O(1) per operation | SQLite indexed by profile + user |
| Substring search | O(n) | Scans entities within profile scope; V2 will use embedding-based search |
| NetworkX load | O(E + V) | Full graph loaded from SQLite on first algorithm call |
| Adaptive subgraph extraction | O(V + E) | Three-phase: structural (unbounded FK chains), column expansion (budget-aware), semantic enrichment (capped) |
| Legacy subgraph BFS | O(V + E) | Bounded by `depth` and `max_nodes` parameters (deprecated) |
| Centrality | O(V + E) | Computed over full graph |
| Cycle detection | O(V + E) | Capped at 20 cycles |
| Context enrichment | ~5-20ms | Search + adaptive extraction + format for typical graphs (<500 entities) |
| FK inference (ingestion) | O(T² × C) | T=tables, C=avg columns per table; runs once during KG generation |
| D3 rendering | Browser-side | Force simulation self-terminates; mini graph stops after 3s |

**NetworkX cache invalidation:** Any write operation (add, update, delete, import, clear) sets `self._graph = None`. The next graph algorithm call re-loads the full graph from SQLite. For write-heavy workloads, consider batching mutations before querying algorithms.

---

## Roadmap

| Feature | Status | Description |
|---------|--------|-------------|
| Entity/Relationship CRUD | **Shipped** | Full CRUD via REST API and LLM tool |
| D3 force-directed visualization | **Shipped** | 3-mode progressive display with interactive features |
| Planner context enrichment | **Shipped** | Automatic subgraph injection into strategic planning |
| Resource Panel management | **Shipped** | Browse, export, delete across profiles |
| Intelligence Performance tab | **Shipped** | Import, export, delete with IFOC badges |
| Bulk import/export | **Shipped** | JSON file format with profile metadata |
| Adaptive subgraph extraction | **Shipped** | Entity-type-aware, unbounded FK chains, budget-aware columns (replaces fixed-depth BFS) |
| FK edge inference (Phase 3.5) | **Shipped** | Deterministic FK detection via column properties, naming conventions, and shared column names |
| Promote (cross-profile copy) | **Planned** | Copy KG from one profile to another |
| MCP schema auto-discovery | **V2 Stub** | Parse MCP tool schemas to populate graph automatically |
| Embedding-based semantic search | **Planned** | Replace substring matching with vector similarity |
| Auto-enrichment during execution | **Planned** | Automatically capture discovered schema from tool results |
| Marketplace/AgentPack integration | **Planned** | Share knowledge graphs as part of agent pack bundles |
| Graph merge/conflict resolution | **Planned** | Merge two profile graphs with deduplication |

---

## File Reference

### Backend

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `components/builtin/knowledge_graph/graph_store.py` | Dual-layer graph engine | `GraphStore`, `ENTITY_TYPES`, `RELATIONSHIP_TYPES` |
| `components/builtin/knowledge_graph/handler.py` | Component handler + context enrichment | `KnowledgeGraphHandler`, `ENTITY_TYPE_COLORS` |
| `components/builtin/knowledge_graph/manifest.json` | Component metadata + tool definition | `TDA_KnowledgeGraph` tool spec |
| `components/builtin/knowledge_graph/instructions.json` | Intensity-keyed LLM instructions | `none`, `medium`, `heavy` |
| `components/builtin/knowledge_graph/discovery.py` | MCP schema discovery (V2 stub) | `MCPSchemaDiscovery` |
| `schema/21_knowledge_graph.sql` | Database schema | `kg_entities`, `kg_relationships` |
| `src/trusted_data_agent/api/rest_routes.py` | REST API endpoints (15) | `kg_add_entity`, `kg_list_all`, `kg_export`, etc. |
| `src/trusted_data_agent/components/manager.py` | Component manager orchestration | `get_component_context_enrichment()` |
| `src/trusted_data_agent/components/base.py` | Base handler class | `BaseComponentHandler.get_context_enrichment()` |

### Frontend

| File | Purpose | Key Functions |
|------|---------|---------------|
| `components/builtin/knowledge_graph/renderer.js` | D3 visualization (3 modes) | `renderKnowledgeGraph()`, `openKGSplitPanel()`, `closeKGSplitPanel()` |
| `static/js/handlers/knowledgeGraphPanelHandler.js` | Management UI (2 locations) | `loadKnowledgeGraphsPanel()`, `loadKnowledgeGraphsIntelligenceTab()`, `initializeImportHandler()` |
| `static/js/api.js` | API client functions | `loadKnowledgeGraphList()`, `exportKnowledgeGraph()`, `deleteKnowledgeGraph()`, `importKnowledgeGraph()` |
| `templates/index.html` | Split panel DOM + Intelligence tab | `#kg-split-panel`, `#knowledge-graphs-tab-content` |

### Integration

| File | Purpose | Lines |
|------|---------|-------|
| `src/trusted_data_agent/agent/planner.py` | Planner context injection | 2609–2621 |
| `src/trusted_data_agent/agent/phase_executor.py` | Tactical context enrichment | 2425–2466 |
| `static/js/handlers/ragCollectionManagement.js` | Intelligence tab wiring | `initializeKnowledgeGraphIntelligenceHandlers()` |
