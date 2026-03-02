# Intelligence Marketplace — Architecture Document

## Executive Summary

The Intelligence Marketplace is Uderia's collaborative ecosystem for sharing, discovering, and deploying enterprise AI assets. It transforms the platform from a single-user tool into a network where community-validated strategies, domain knowledge, agent configurations, behavioral skills, processing extensions, and entity-relationship models circulate freely — reducing token costs, accelerating onboarding, and enabling continuous improvement through fork-and-improve workflows.

### Product Catalog

The marketplace serves **six product types** through a unified infrastructure:

| Product Type | Description | Acquisition Models |
|---|---|---|
| **Planner Repositories** | Proven execution patterns and strategies for autonomous task completion | Subscribe, Fork |
| **Knowledge Repositories** | Reference documents and domain knowledge for planning context | Subscribe, Fork |
| **Agent Packs** | Bundled agent teams (coordinator, experts, knowledge collections) as portable `.agentpack` files | Subscribe, Fork |
| **Skills** | Pre-processing prompt injections that modify LLM behavior (Claude Code compatible `skill.json` + `.md`) | Install |
| **Extensions** | Reusable processing modules with tiered complexity (convention, simple, standard, LLM) | Install |
| **Knowledge Graphs** | Entity-relationship models for database topology, business concepts, and domain ontologies | Install, Fork |

### Design Principles

1. **Unified Infrastructure** — Shared tables (`marketplace_sharing_grants`) and consistent API patterns across all product types
2. **Zero-Trust Security** — JWT authentication on every endpoint, ownership validation on every mutation
3. **Ownership Sovereignty** — Publishers retain full control; consumers choose between reference subscriptions (live updates) and independent forks (full autonomy)
4. **Admin Governance** — Every product type has an administrative enable/disable toggle
5. **Network Effects** — Ratings, install counts, and subscriber metrics surface the highest-quality assets

---

## System Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Frontend (UI Layer)                           │
│  marketplaceHandler.js  │  skillHandler.js  │  agentPackHandler.js  │
│  ─────────────────────────────────────────────────────────────────── │
│  6 Product Type Tabs  │  Browse / My Assets  │  Search, Sort, Rate  │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ REST API (JWT Auth)
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        Backend (API Layer)                           │
│  rest_routes.py          — Collections (Planner + Knowledge)        │
│  agent_pack_routes.py    — Agent Packs                              │
│  skills_routes.py        — Skills                                   │
│  extension_routes.py     — Extensions                               │
│  kg_marketplace_routes.py — Knowledge Graphs                        │
│  admin_routes.py         — Governance settings                      │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────────────┐
│  SQLite Database  │ │   ChromaDB   │ │  File System             │
│  tda_auth.db      │ │ Vector Store │ │  marketplace_data/       │
│  ───────────────  │ │ ──────────── │ │  ──────────────────────  │
│  rag_collections  │ │  Embeddings  │ │  skills/{id}/            │
│  marketplace_*    │ │  per-coll.   │ │  agent-packs/{id}/       │
│  *_ratings        │ │              │ │  extensions/{id}/        │
│  sharing_grants   │ │              │ │  knowledge-graphs/{id}/  │
└──────────────────┘ └──────────────┘ └──────────────────────────┘
```

### Data Flow Patterns

All product types follow three core lifecycle patterns:

#### Publish Flow

```
Publisher creates asset locally
    ↓
Publisher clicks "Publish"
    ↓
[Backend] JWT authentication + ownership validation
    ↓
[Backend] Validate: asset meets minimum requirements (e.g., ≥1 RAG case)
    ↓
[Database] Insert marketplace record (metadata, visibility, metrics)
    ↓
[Filesystem] Copy asset content to marketplace_data/{type}/{marketplace_id}/
    ↓
Asset appears in marketplace browse (if public) or targeted recipients
```

#### Subscribe / Install Flow

```
Consumer finds asset in marketplace
    ↓
Consumer clicks "Subscribe" / "Install"
    ↓
[Backend] JWT authentication
    ↓
[Backend] Validate: not owner (for subscribe), visibility access check
    ↓
[Database] INSERT subscription/sharing grant  OR  copy asset to user workspace
    ↓
[Database] INCREMENT subscriber_count / install_count
    ↓
Asset available in consumer's workspace
```

#### Fork Flow (Full Copy)

```
Consumer clicks "Fork"
    ↓
[Frontend] Display fork modal (custom name input)
    ↓
[Backend] JWT authentication
    ↓
[Database] Create new record (consumer as owner)
    ↓
[ChromaDB] Copy all embeddings to new collection (Collections only)
    ↓
[Filesystem] Copy all asset files to new directory
    ↓
Consumer owns independent copy — modify freely without affecting original
```

---

## Product Type Architectures

### 1. Collections (Planner & Knowledge Repositories)

Collections are the foundational marketplace product. **Planner Repositories** contain proven execution patterns that guide the autonomous agent, while **Knowledge Repositories** provide reference documents and domain context for planning.

**Database Tables:**

```sql
-- Core collection table (pre-existing, extended for marketplace)
rag_collections (
    id, name, description, owner_user_id,
    is_marketplace_listed, visibility,      -- marketplace fields
    subscriber_count, average_rating,
    rag_case_count
)

-- Subscriptions (reference-based, no data duplication)
collection_subscriptions (
    id, user_id, collection_id, subscribed_at,
    UNIQUE(user_id, collection_id)
)

-- Ratings
collection_ratings (
    id, user_id, collection_id, rating CHECK(1-5), review,
    created_at, updated_at,
    UNIQUE(user_id, collection_id)
)
```

**Access Control Matrix:**

| Action | Owner | Subscriber | Public User |
|--------|-------|------------|-------------|
| View | Yes | Yes | Yes (if public) |
| Edit | Yes | No | No |
| Delete | Yes | No | No |
| Publish | Yes | No | No |
| Subscribe | No | N/A | Yes |
| Fork | Yes | Yes | Yes (if public) |
| Rate | No | Yes | Yes |

**API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/marketplace/collections` | Browse with search, filters, pagination |
| POST | `/v1/marketplace/collections/:id/subscribe` | Subscribe (reference) |
| DELETE | `/v1/marketplace/subscriptions/:id` | Unsubscribe |
| POST | `/v1/marketplace/collections/:id/fork` | Fork (full copy incl. embeddings) |
| POST | `/v1/rag/collections/:id/publish` | Publish (owner only) |
| POST | `/v1/marketplace/collections/:id/rate` | Rate (1-5 stars + review) |

**Key Implementation Detail — Fork:**
Forking a collection is a deep copy operation that clones the database record, copies all ChromaDB vector embeddings to a new collection, and duplicates all RAG case files on disk. The consumer becomes the full owner of the fork.

---

### 2. Agent Packs

Agent Packs bundle complete agent teams — coordinator configurations, expert agents, and their associated knowledge collections — into portable `.agentpack` files for one-click distribution.

**Pack Types:** `genie` (full orchestrator), `bundle` (multi-agent), `single` (individual agent)

**Database Tables:**

```sql
-- Schema: 10_marketplace_agent_packs.sql
marketplace_agent_packs (
    id, source_installation_id, publisher_user_id,
    name, description, version, author, pack_type,
    visibility, manifest_summary_json, content_hash,
    download_count, install_count,
    created_at, updated_at
)

agent_pack_ratings (
    id, marketplace_pack_id, user_id,
    rating CHECK(1-5), comment,
    created_at, updated_at,
    UNIQUE(marketplace_pack_id, user_id)
)
```

**API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/agent-packs/:installation_id/publish` | Publish to marketplace |
| GET | `/v1/marketplace/agent-packs` | Browse published packs |
| GET | `/v1/marketplace/agent-packs/:id` | Detail view |
| POST | `/v1/marketplace/agent-packs/:id/install` | Subscribe (sharing grant) |
| DELETE | `/v1/marketplace/agent-packs/:id/subscribe` | Unsubscribe |
| POST | `/v1/marketplace/agent-packs/:id/fork` | Fork (physical copy) |
| POST | `/v1/marketplace/agent-packs/:id/rate` | Rate/review |
| DELETE | `/v1/marketplace/agent-packs/:id` | Unpublish |

**Key Implementation Detail — Source Tracking:**
Installed agent packs maintain a `source_installation_id` reference back to the publisher's original, enabling provenance tracking and future update notifications.

---

### 3. Skills

Skills are pre-processing prompt injections that modify LLM behavior before query execution — enforcing SQL best practices, requiring concise responses, enabling chain-of-thought reasoning, etc. Skills use the **Claude Code compatible format** (`skill.json` + `<name>.md`), ensuring portability between Uderia and Claude Code environments.

**Skill Format:**

```
skill-name/
├── skill.json      ← Manifest (name, version, description, author, tags, main_file)
└── skill-name.md   ← Pure markdown content (the actual prompt injection)
```

With optional Uderia enhancement:
```json
{
  "name": "sql-expert",
  "version": "1.0.0",
  "description": "SQL optimization guidance",
  "author": "admin",
  "tags": ["sql", "database"],
  "main_file": "sql-expert.md",
  "uderia": {
    "allowed_params": ["strict", "lenient"],
    "param_descriptions": { "strict": "Enforce strict SQL standards" },
    "injection_target": "system_prompt",
    "icon": "database"
  }
}
```

**Database Tables:**

```sql
-- Schema: 17_marketplace_skills.sql
marketplace_skills (
    id, skill_id, publisher_user_id,
    name, version, description, author, tags_json,
    injection_target, visibility,
    install_count, download_count,
    created_at, updated_at
)

skill_ratings (
    id, marketplace_skill_id, user_id,
    rating CHECK(1-5), comment,
    created_at, updated_at,
    UNIQUE(marketplace_skill_id, user_id)
)
```

**API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/skills/:skill_id/publish` | Publish user skill |
| GET | `/v1/marketplace/skills` | Browse with search/sort/paginate |
| GET | `/v1/marketplace/skills/:id` | Detail + ratings |
| POST | `/v1/marketplace/skills/:id/install` | Install (copies to `~/.tda/skills/`) |
| POST | `/v1/marketplace/skills/:id/rate` | Rate (1-5 + comment) |
| DELETE | `/v1/marketplace/skills/:id` | Unpublish (publisher only) |

**Key Implementation Detail — Hot Reload:**
After installation, the skill manager hot-reloads so the new skill is immediately available for activation via `!skill-name` syntax without restart.

**Export Format:**
Skills export as `.skill` files (ZIP containing `skill.json` + `<name>.md`). Import accepts both `.skill` and `.zip`.

---

### 4. Extensions

Extensions are reusable processing modules that extend agent capabilities. They follow a tiered complexity model that determines their execution environment and resource requirements.

**Extension Tiers:**

| Tier | Description | Execution Model |
|------|-------------|-----------------|
| `convention` | Naming/format conventions | Static rules |
| `simple` | Basic transformations | Lightweight processing |
| `standard` | Full processing pipelines | Standard execution |
| `llm` | LLM-powered extensions | Requires model inference |

**Database Tables:**

```sql
marketplace_extensions (
    id, extension_id, publisher_user_id,
    name, version, description, author,
    extension_tier, tags_json, visibility,
    install_count, download_count,
    content_hash, manifest_json,
    created_at, updated_at
)

extension_ratings (
    id, marketplace_extension_id, user_id,
    rating CHECK(1-5), comment,
    created_at, updated_at,
    UNIQUE(marketplace_extension_id, user_id)
)
```

**API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/extensions/:id/publish` | Publish extension |
| GET | `/v1/marketplace/extensions` | Browse with search/sort/paginate |
| GET | `/v1/marketplace/extensions/:id` | Detail + ratings |
| POST | `/v1/marketplace/extensions/:id/install` | Install into system |
| POST | `/v1/marketplace/extensions/:id/rate` | Rate (1-5 + comment) |
| DELETE | `/v1/marketplace/extensions/:id` | Unpublish |

---

### 5. Knowledge Graphs

Knowledge Graphs represent entity-relationship models — database schemas, business concepts, domain ontologies — built through the Intelligence Performance page. Published KGs can be installed into specific target profiles with merge semantics.

**Database Tables:**

```sql
-- Schema: 23_marketplace_knowledge_graphs.sql
marketplace_knowledge_graphs (
    id, source_profile_id, publisher_user_id,
    name, description, version, author, domain,
    entity_count, relationship_count,
    entity_types_json, relationship_types_json, tags_json,
    visibility, download_count, install_count,
    created_at, updated_at
)

knowledge_graph_ratings (
    id, marketplace_kg_id, user_id,
    rating CHECK(1-5), comment,
    created_at, updated_at,
    UNIQUE(marketplace_kg_id, user_id)
)

kg_marketplace_settings (
    id, kg_marketplace_enabled BOOLEAN DEFAULT 1,
    updated_at
)
```

**API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/knowledge-graph/:profile_id/publish` | Publish KG |
| GET | `/v1/marketplace/knowledge-graphs` | Browse with search, sort, domain filter |
| GET | `/v1/marketplace/knowledge-graphs/:id` | Detail + user's rating |
| POST | `/v1/marketplace/knowledge-graphs/:id/install` | Install into target profile |
| POST | `/v1/marketplace/knowledge-graphs/:id/fork` | Fork (alias for install, increments download_count) |
| POST | `/v1/marketplace/knowledge-graphs/:id/rate` | Rate (1-5 + comment) |
| DELETE | `/v1/marketplace/knowledge-graphs/:id` | Unpublish (publisher only) |
| GET/POST | `/v1/admin/kg-marketplace-settings` | Admin governance |

**Key Implementation Details:**

- **Profile-scoped install:** Unlike Skills (global), KGs install into a specific target profile via `GraphStore.import_bulk()`. The install modal includes a profile picker.
- **Merge semantics:** Entities are matched by `(name, entity_type)` — existing entities are upserted, not replaced.
- **Source provenance:** Installed entities receive `source = 'marketplace'` for tracking.
- **Export compatibility:** Published KGs use the same format as `/v1/knowledge-graph/export`, with relationships containing both ID-based and name-based references.

---

## Shared Infrastructure

### Targeted Sharing (marketplace_sharing_grants)

A unified table enables fine-grained visibility control across all product types:

```sql
marketplace_sharing_grants (
    id,
    resource_type TEXT,    -- 'collection', 'agent_pack', 'skill', 'extension', 'knowledge_graph'
    resource_id INTEGER,
    granted_to_user_id TEXT,
    granted_by_user_id TEXT,
    created_at DATETIME
)
```

When a publisher sets visibility to **targeted**, they can grant access to specific users. The marketplace browse query joins against this table to filter results per-user.

### Visibility Model

All product types share a two-tier visibility model:

| Visibility | Behavior |
|---|---|
| **Public** | Discoverable by all authenticated users in marketplace browse |
| **Targeted** | Visible only to users with an explicit sharing grant |

Private assets (not published) are invisible to the marketplace entirely.

### Rating Architecture

Each product type has its own rating table following a consistent pattern:

- **1-5 star scale** with optional text comment
- **One rating per user per asset** (UNIQUE constraint, upsert on re-rate)
- **Self-rating prevention** — publishers cannot rate their own assets
- **Average rating** computed and cached on the marketplace record for efficient browse queries

### Metrics Tracking

All product types track engagement through consistent counter fields:

| Metric | Incremented On |
|---|---|
| `subscriber_count` | Subscribe action |
| `download_count` | Fork / download action |
| `install_count` | Install action |
| `average_rating` | Rating submission (recomputed) |

---

## Security Architecture

### Authentication

All marketplace endpoints require JWT authentication:

```http
Authorization: Bearer <JWT_TOKEN>
```

- Token issued on login, includes `user_id` claim
- Configurable expiration (default: 24 hours)
- Middleware validates and extracts `user_id` before handler execution

### Authorization Rules

| Action | Constraint |
|--------|-----------|
| **Publish** | Must be asset owner |
| **Unpublish** | Must be asset publisher |
| **Subscribe** | Cannot subscribe to own assets |
| **Fork** | Anyone with visibility access |
| **Install** | Anyone with visibility access |
| **Rate** | Cannot rate own assets |
| **Manage sharing grants** | Must be asset publisher |
| **Admin settings** | Must have admin role |

### Input Validation & Threat Mitigation

| Threat | Mitigation |
|--------|------------|
| SQL Injection | Parameterized queries throughout |
| XSS | Output escaping (`escapeHtml()`), Content Security Policy |
| CSRF | JWT in Authorization header (not cookies) |
| Unauthorized Access | JWT validation + ownership checks on every mutation |
| Data Exfiltration | Visibility-based access control per asset |
| Content Integrity | `content_hash` on stored marketplace files |

---

## Frontend Architecture

### UI Structure

The marketplace frontend is organized around two main views and six product type tabs:

**Main Tabs:**
- **Browse Marketplace** — discover and acquire community assets
- **My Assets** — manage your published and installed assets

**Product Type Tabs:**

| Tab | Handler | Icon |
|---|---|---|
| Planner Repositories | `marketplaceHandler.js` | Clipboard |
| Knowledge Repositories | `marketplaceHandler.js` | Chart |
| Agent Packs | `marketplaceHandler.js` | Cube |
| Extensions | `marketplaceHandler.js` | Puzzle |
| Skills | `marketplaceHandler.js` | Wand |
| Knowledge Graphs | `marketplaceHandler.js` | Graph/Link |

**Shared UI Components:**
- Search bar with type-ahead
- Sort dropdown (subscribers, downloads, installs, rating, recent)
- Visibility filter (public / targeted)
- Paginated card grid with glass-morphism design
- Rating modal (interactive 5-star selection + comment)
- Fork modal (custom name input + explainer)
- Install modal (target selector where applicable)
- Publish modal (name, description, version, visibility)

### Card Design

Each product type renders branded cards with consistent structure:
- Asset name and description
- Publisher username
- Type badge with product-specific accent color
- Star rating (visual + numeric)
- Engagement metrics (subscribers, installs, downloads)
- Context-aware action buttons (Subscribe / Fork / Install / Rate / Publish / Unpublish)

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, Tailwind CSS, Vanilla JavaScript (ES6 modules) |
| Backend | Python 3.10+, Quart (async Flask) |
| Database | SQLite (`tda_auth.db`) |
| Vector Store | ChromaDB (embeddings for Collections) |
| Authentication | JWT (PyJWT) |
| File Storage | Local filesystem (`marketplace_data/`) |

### File Structure

```
uderia/
├── src/trusted_data_agent/
│   ├── api/
│   │   ├── rest_routes.py              # Collection marketplace endpoints
│   │   ├── agent_pack_routes.py        # Agent Pack marketplace endpoints
│   │   ├── skills_routes.py            # Skills marketplace endpoints
│   │   ├── extension_routes.py         # Extension marketplace endpoints
│   │   ├── kg_marketplace_routes.py    # Knowledge Graph marketplace endpoints
│   │   └── admin_routes.py             # Governance settings
│   ├── agent/
│   │   └── rag_retriever.py            # Collection access control, fork logic
│   ├── skills/
│   │   └── settings.py                 # Skills marketplace governance
│   ├── kg/
│   │   └── settings.py                 # KG marketplace governance
│   └── auth/
│       ├── database.py                 # Schema bootstrap
│       └── models.py                   # Subscription, Rating models
├── static/js/handlers/
│   ├── marketplaceHandler.js           # Collections, Agent Packs, Extensions, KGs UI
│   └── skillHandler.js                 # Skills marketplace UI
├── schema/
│   ├── 10_marketplace_agent_packs.sql
│   ├── 11_marketplace_sharing_grants.sql
│   ├── 14_marketplace_extensions.sql
│   ├── 16_skill_settings.sql
│   ├── 17_marketplace_skills.sql
│   └── 23_marketplace_knowledge_graphs.sql
├── marketplace_data/                   # Published asset files
│   ├── skills/{marketplace_id}/
│   ├── agent-packs/{marketplace_id}/
│   ├── extensions/{marketplace_id}/
│   └── knowledge-graphs/{marketplace_id}/
└── templates/
    └── index.html                      # Marketplace UI
```

---

## API Reference — Complete Endpoint Catalog

### Collection Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/v1/marketplace/collections` | Yes | Browse collections |
| POST | `/v1/marketplace/collections/:id/subscribe` | Yes | Subscribe |
| DELETE | `/v1/marketplace/subscriptions/:id` | Yes | Unsubscribe |
| POST | `/v1/marketplace/collections/:id/fork` | Yes | Fork (deep copy) |
| POST | `/v1/rag/collections/:id/publish` | Owner | Publish |
| POST | `/v1/marketplace/collections/:id/rate` | Yes | Rate |

### Agent Pack Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/v1/agent-packs/:installation_id/publish` | Owner | Publish |
| GET | `/v1/marketplace/agent-packs` | Yes | Browse |
| GET | `/v1/marketplace/agent-packs/:id` | Yes | Detail |
| POST | `/v1/marketplace/agent-packs/:id/install` | Yes | Subscribe |
| DELETE | `/v1/marketplace/agent-packs/:id/subscribe` | Yes | Unsubscribe |
| POST | `/v1/marketplace/agent-packs/:id/fork` | Yes | Fork |
| POST | `/v1/marketplace/agent-packs/:id/rate` | Yes | Rate |
| DELETE | `/v1/marketplace/agent-packs/:id` | Publisher | Unpublish |

### Skill Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/v1/skills/:skill_id/publish` | Owner | Publish |
| GET | `/v1/marketplace/skills` | Yes | Browse |
| GET | `/v1/marketplace/skills/:id` | Yes | Detail |
| POST | `/v1/marketplace/skills/:id/install` | Yes | Install |
| POST | `/v1/marketplace/skills/:id/rate` | Yes | Rate |
| DELETE | `/v1/marketplace/skills/:id` | Publisher | Unpublish |

### Extension Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/v1/extensions/:id/publish` | Owner | Publish |
| GET | `/v1/marketplace/extensions` | Yes | Browse |
| GET | `/v1/marketplace/extensions/:id` | Yes | Detail |
| POST | `/v1/marketplace/extensions/:id/install` | Yes | Install |
| POST | `/v1/marketplace/extensions/:id/rate` | Yes | Rate |
| DELETE | `/v1/marketplace/extensions/:id` | Publisher | Unpublish |

### Knowledge Graph Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/v1/knowledge-graph/:profile_id/publish` | Owner | Publish |
| GET | `/v1/marketplace/knowledge-graphs` | Yes | Browse |
| GET | `/v1/marketplace/knowledge-graphs/:id` | Yes | Detail |
| POST | `/v1/marketplace/knowledge-graphs/:id/install` | Yes | Install into profile |
| POST | `/v1/marketplace/knowledge-graphs/:id/fork` | Yes | Fork |
| POST | `/v1/marketplace/knowledge-graphs/:id/rate` | Yes | Rate |
| DELETE | `/v1/marketplace/knowledge-graphs/:id` | Publisher | Unpublish |

### Admin Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/v1/admin/kg-marketplace-settings` | Admin | KG marketplace toggle |
| GET/POST | `/v1/admin/skill-settings` | Admin | Skills marketplace toggle |

### Common API Patterns

**Pagination** (all browse endpoints):
```
?page=1&per_page=10
```

**Search** (all browse endpoints):
```
?search=keyword
```

**Sort** (all browse endpoints):
```
?sort_by=rating|recent|installs|downloads|subscribers
```

**Error Response Format:**
```json
{
  "error": "Human-readable error message",
  "details": "Optional additional context"
}
```

**HTTP Status Codes:**
- `200` — Success
- `400` — Invalid input
- `401` — Missing/invalid JWT
- `403` — Insufficient permissions (or marketplace disabled)
- `404` — Resource not found
- `409` — Conflict (already subscribed, already rated, etc.)
- `500` — Server error

---

## Governance & Administration

### Per-Product-Type Toggles

Administrators control marketplace availability through settings tables:

| Product Type | Setting | Location |
|---|---|---|
| Skills | `user_skills_marketplace_enabled` | `skill_settings` table |
| Knowledge Graphs | `kg_marketplace_enabled` | `kg_marketplace_settings` table |

When disabled:
- Publish returns `403 Forbidden`
- Marketplace browse button hidden in UI
- Install returns `403 Forbidden`
- Existing installations are not affected

Managed via: **Administration > App Config > Settings**

---

## Performance & Scalability

### Current Performance Characteristics

| Operation | Typical Latency | Notes |
|---|---|---|
| Browse (paginated) | < 200ms | JOIN-optimized queries, 10 items/page |
| Subscribe / Unsubscribe | < 50ms | Simple INSERT/DELETE |
| Rate | < 50ms | Upsert + average recomputation |
| Fork (Collection, 100 embeddings) | 1-2s | ChromaDB copy + file copy |
| Install (Skill) | < 200ms | File copy + hot-reload |
| Install (KG, 500 entities) | 1-3s | Bulk import with merge |

### Database Indexes

```sql
CREATE INDEX idx_subscriptions_user ON collection_subscriptions(user_id);
CREATE INDEX idx_subscriptions_collection ON collection_subscriptions(collection_id);
CREATE INDEX idx_ratings_collection ON collection_ratings(collection_id);
-- Similar indexes exist for all product-type rating and subscription tables
```

### Scalability Considerations

| Component | Current | Production Scale |
|---|---|---|
| Database | SQLite (single-instance) | PostgreSQL for multi-user |
| Vector Store | ChromaDB (local) | Distributed (Milvus, Weaviate) |
| File Storage | Local filesystem | S3 / blob storage |
| Search | SQL LIKE queries | Full-text search / Elasticsearch |
| Caching | None | Redis for browse result caching |

---

## Document History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2024 | Initial guide (Phases 1-4: Collections) |
| 1.1 | Feb 2026 | Added Skills (Phase 5) and Knowledge Graphs (Phase 6) |
| 1.2 | Mar 2026 | Added Extensions and Agent Packs |
| 2.0 | Mar 2026 | Elevated to Architecture Document — unified all 6 product types, removed phase-by-phase build log, restructured around architectural concerns |
