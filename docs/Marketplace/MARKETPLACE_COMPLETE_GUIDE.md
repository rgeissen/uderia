# Intelligence Marketplace - Complete Feature Documentation

## Executive Summary

The Intelligence Marketplace is a comprehensive feature enabling users to share, discover, and leverage community-curated RAG (Retrieval-Augmented Generation) collections. This marketplace transforms isolated knowledge bases into a collaborative ecosystem where users benefit from proven execution patterns and domain expertise.

The marketplace supports **three distinct product types:**
- **Planner Repositories:** Execution patterns and strategies for proven task completion
- **Knowledge Repositories:** Reference documents and domain knowledge for planning context
- **Skills:** Pre-processing prompt injections for modifying LLM behavior (Claude Code compatible format)

All types can be published, browsed, installed/subscribed, and rated through the marketplace interface with visual separation for clarity.

**Implementation Date:** 2024 (Phase 1-4), February 2026 (Phase 5: Skills)
**Total Implementation:** 5 Phases
**Lines of Code:** ~4,200 lines (backend + frontend)
**Status:** ✅ Complete

---

## Table of Contents

1. [Vision & Motivation](#vision--motivation)
2. [Architecture Overview](#architecture-overview)
3. [Phase-by-Phase Implementation](#phase-by-phase-implementation)
4. [User Guide](#user-guide)
5. [Technical Specifications](#technical-specifications)
6. [API Reference](#api-reference)
7. [Security & Privacy](#security--privacy)
8. [Performance & Scalability](#performance--scalability)
9. [Future Roadmap](#future-roadmap)
10. [Skills Marketplace (Phase 5)](#skills-marketplace-phase-5)

---

## Vision & Motivation

### The Problem

AI agents powered by LLMs face several challenges:
- **Token Inefficiency**: Repeated trial-and-error consumes tokens
- **Knowledge Isolation**: Users solve identical problems independently
- **Quality Variance**: No mechanism to validate execution strategies
- **Context Fragmentation**: Domain knowledge scattered across documents
- **Onboarding Friction**: New users start from scratch

### The Solution

A marketplace where users:
- **Share** curated RAG collections of proven planner executions (Planner Repositories)
- **Share** domain knowledge and reference documentation (Knowledge Repositories)
- **Discover** community knowledge bases tailored to specific MCP servers and domains
- **Reuse** battle-tested strategies and contextual documentation, reducing token costs
- **Collaborate** through ratings, reviews, and forks
- **Browse** with clear visual separation between execution patterns and knowledge documents

### Value Proposition

| Benefit | Description |
|---------|-------------|
| **Cost Reduction** | Reuse proven patterns instead of trial-and-error |
| **Quality Assurance** | Community ratings surface best collections |
| **Faster Onboarding** | New users subscribe to expert collections |
| **Continuous Improvement** | Forking enables iterative refinement |
| **On-Prem Intelligence** | Augment local models with community knowledge |

---

## Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (UI Layer)                      │
│  • Marketplace Browse View (search, filters, pagination)   │
│  • Modal Dialogs (fork, publish, rate)                     │
│  • JavaScript Handler (marketplaceHandler.js)              │
└────────────────────┬────────────────────────────────────────┘
                     │ REST API (JWT Auth)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   Backend (API Layer)                       │
│  • 6 Marketplace Endpoints (rest_routes.py)                │
│  • Access Control Logic (rag_retriever.py)                 │
│  • Collection Management                                    │
└────────────────────┬────────────────────────────────────────┘
                     │ Database Queries
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  Database (Persistence)                     │
│  • rag_collections (name, owner, visibility, ratings)      │
│  • collection_subscriptions (user_id, collection_id)       │
│  • collection_ratings (user_id, collection_id, rating)     │
└────────────────────┬────────────────────────────────────────┘
                     │ Vector Embeddings
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                ChromaDB (Vector Store)                      │
│  • RAG case embeddings per collection                      │
│  • Semantic search for retrieval                           │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow: Subscribe Workflow

```
User clicks "Subscribe"
    ↓
[Frontend] POST /v1/marketplace/collections/:id/subscribe
    ↓
[Backend] JWT authentication
    ↓
[Backend] Validate: not owner, not already subscribed
    ↓
[Database] INSERT subscription record
    ↓
[Database] UPDATE subscriber_count += 1
    ↓
[Backend] Return success response
    ↓
[Frontend] Update button to "Unsubscribe"
    ↓
[Frontend] Increment displayed subscriber count
```

### Data Flow: Fork Workflow

```
User clicks "Fork"
    ↓
[Frontend] Display fork modal
    ↓
User enters new name, clicks "Fork Collection"
    ↓
[Frontend] POST /v1/marketplace/collections/:id/fork
    ↓
[Backend] JWT authentication
    ↓
[Backend] Validate: not owner (can fork own, but typical use is others')
    ↓
[Database] Create new rag_collection record (user as owner)
    ↓
[ChromaDB] Copy all embeddings to new collection
    ↓
[Filesystem] Copy all RAG case files to new directory
    ↓
[Backend] Return new collection details
    ↓
[Frontend] Show success notification
    ↓
User owns independent copy
```

---

## Phase-by-Phase Implementation

### Phase 1: Data Model & Ownership ✅

**Objective:** Establish database schema for marketplace

**Deliverables:**
- `collection_subscriptions` table
- `collection_ratings` table  
- Migration script for existing collections
- Ownership tracking in `rag_collections`

**Database Schema:**

```sql
-- Subscriptions
CREATE TABLE collection_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    collection_id INTEGER NOT NULL,
    subscribed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (collection_id) REFERENCES rag_collections(id),
    UNIQUE(user_id, collection_id)
);

-- Ratings
CREATE TABLE collection_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    collection_id INTEGER NOT NULL,
    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
    review TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (collection_id) REFERENCES rag_collections(id),
    UNIQUE(user_id, collection_id)
);
```

**Key Decisions:**
- Reference-based subscriptions (no data duplication)
- Star ratings (1-5) with optional reviews
- Timestamps for audit trails
- Unique constraints prevent duplicate subscriptions/ratings

**Testing:** ✅ 5/5 tests passing (`test_marketplace_phase1.py`)

---

### Phase 2: Collection Ownership & Access Control ✅

**Objective:** Implement authorization and ownership validation

**Deliverables:**
- `is_user_collection_owner()` method
- `is_subscribed_collection()` check
- `_get_user_accessible_collections()` filter
- `fork_collection()` implementation

**Access Control Rules:**

| Action | Owner | Subscriber | Public |
|--------|-------|------------|--------|
| **View** | ✅ | ✅ | ✅ (if public) |
| **Edit** | ✅ | ❌ | ❌ |
| **Delete** | ✅ | ❌ | ❌ |
| **Publish** | ✅ | ❌ | ❌ |
| **Subscribe** | ❌ | N/A | ✅ |
| **Fork** | ✅ | ✅ | ✅ (if public) |
| **Rate** | ❌ | ✅ | ✅ |

**Fork Logic:**
```python
def fork_collection(self, collection_id, new_name, user_uuid):
    # 1. Copy database record with new owner
    # 2. Clone ChromaDB collection
    # 3. Copy all RAG case files
    # 4. Return new collection ID
```

**Testing:** ✅ 5/5 tests passing (`test_marketplace_phase2.py`)

---

### Phase 3: Marketplace API ✅

**Objective:** Expose marketplace operations via REST API

**Deliverables:** 6 endpoints

#### 1. Browse Collections
```http
GET /api/v1/marketplace/collections?page=1&per_page=10&visibility=public&search=SQL
```

**Response:**
```json
{
  "collections": [
    {
      "id": 1,
      "name": "SQL Query Patterns",
      "description": "Common SQL queries",
      "owner_username": "john_doe",
      "visibility": "public",
      "subscriber_count": 15,
      "average_rating": 4.5,
      "rag_case_count": 42,
      "is_owner": false,
      "is_subscribed": false,
      "subscription_id": null
    }
  ],
  "total_count": 50,
  "page": 1,
  "per_page": 10,
  "total_pages": 5
}
```

#### 2. Subscribe
```http
POST /api/v1/marketplace/collections/1/subscribe
Authorization: Bearer <JWT>
```

**Validations:**
- Cannot subscribe to own collections
- Cannot subscribe twice
- Collection must be public or unlisted

#### 3. Unsubscribe
```http
DELETE /api/v1/marketplace/subscriptions/123
Authorization: Bearer <JWT>
```

#### 4. Fork Collection
```http
POST /api/v1/marketplace/collections/1/fork
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "new_name": "My SQL Patterns"
}
```

**Response:**
```json
{
  "id": 42,
  "name": "My SQL Patterns",
  "owner_user_id": "user-uuid-456",
  "rag_case_count": 42,
  "message": "Collection forked successfully"
}
```

#### 5. Publish Collection
```http
POST /api/v1/rag/collections/5/publish
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "visibility": "public"
}
```

**Validations:**
- Must be collection owner
- Collection must have at least 1 RAG case
- Visibility: "public" or "unlisted"

#### 6. Rate Collection
```http
POST /api/v1/marketplace/collections/1/rate
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "rating": 5,
  "review": "Excellent collection!"
}
```

**Validations:**
- Cannot rate own collections
- Rating must be 1-5
- Review is optional

**Testing:** ✅ 6/6 tests passing (`test_marketplace_phase3.py`)

---

### Phase 4: Marketplace UI ✅

**Objective:** Implement user-facing marketplace interface

**Deliverables:**
- Marketplace browse view
- Search and filter controls
- Collection cards with metadata
- Fork, Publish, Rate modals
- Subscribe/unsubscribe buttons
- Pagination controls
- JavaScript handler (`marketplaceHandler.js`)

**UI Components:**

1. **Search & Filter Bar**
   - Text search input
   - Visibility dropdown (Public/Unlisted)
   - Search button

2. **Collection Cards**
   - Glass morphism design
   - Metadata display:
     - Name, description
     - Owner, subscriber count, case count
     - Star rating (visual + numeric)
   - Context-aware buttons:
     - Owner: Publish/Update Visibility
     - Non-owner: Subscribe, Fork, Rate

3. **Modals**
   - Fork: Customizable name, forking explainer
   - Publish: Visibility selector, publishing explainer
   - Rate: 5-star selector, optional review

4. **Pagination**
   - Previous/Next buttons
   - Page info: "Page X of Y (Z total)"
   - Disabled state handling

**User Flows:** See [User Guide](#user-guide) section below

**Testing:** Manual test plan (30 test cases) documented in `test_marketplace_phase4_ui.md`

---

## User Guide

### For Collection Consumers

#### Discovering Collections

1. **Navigate to Marketplace**
   - Click "Marketplace" in sidebar navigation
   - View displays public collections with Planner Repositories tab selected by default

2. **Select Repository Type**
   - **Planner Repositories Tab (📋):** Execution patterns and strategies for proven task completion
   - **Knowledge Repositories Tab (📄):** Reference documents and domain knowledge for planning context
   - Active tab highlighted in orange (#F15F22)
   - Description text updates based on selection

3. **Search for Collections**
   - Enter keywords (e.g., "Teradata", "SQL", "Python", "API Documentation")
   - Press Enter or click "Search"
   - Results filter by selected repository type in real-time

4. **Filter by Visibility**
   - Select "Public" to see all public collections
   - Select "Unlisted" to browse hidden gems (if you have direct links)

5. **Browse Results**
   - Scroll through collection cards
   - Review metadata: owner, subscribers, rating, case/document count
   - Blue badge (📋 Planner) or Purple badge (📄 Knowledge) indicates type
   - Click pagination controls for more results

#### Subscribing to Collections

1. **Find Desired Collection**
   - Browse or search for relevant collection
   - Review description and rating

2. **Click "Subscribe"**
   - Button changes to "Subscribing..." briefly
   - Success notification appears
   - Button updates to "Unsubscribe"

3. **Access Subscribed Collection**
   - Subscribed collections available in RAG system
   - Planner can retrieve cases from this collection
   - No duplication—references original collection

#### Forking Collections

1. **Click "Fork" Button**
   - Fork modal opens
   - Source collection info displayed

2. **Customize Fork Name**
   - Edit pre-filled name (e.g., "My SQL Patterns")
   - Optionally add description

3. **Click "Fork Collection"**
   - Full copy created (including embeddings and case files)
   - New collection owned by you
   - Modify independently without affecting original

#### Rating Collections

1. **Click "Rate" Button**
   - Rate modal opens
   - Collection name displayed

2. **Select Star Rating**
   - Click stars (1-5)
   - Selected stars highlight in yellow

3. **Optionally Add Review**
   - Enter text in review field
   - Share specific feedback

4. **Submit Rating**
   - Click "Submit Rating"
   - Rating saves, modal closes
   - Collection card updates with new average

### For Collection Publishers

#### Publishing Your Collection

**Prerequisites:**
- Collection must have at least 1 RAG case
- You must be the collection owner

**Steps:**

1. **Prepare Collection**
   - Ensure high-quality RAG cases
   - Add clear description
   - Test cases work correctly

2. **Navigate to RAG Maintenance** (or use publish button if available)
   - Find your collection
   - Click "Publish" or access via API

3. **Select Visibility**
   - **Public**: Discoverable by all users in marketplace browse
   - **Unlisted**: Accessible only via direct link (not in public browse)

4. **Confirm Publishing**
   - Click "Publish Collection"
   - Collection appears in marketplace

#### Updating Published Collections

- **Edit Cases**: Add/remove/modify RAG cases anytime
- **Change Visibility**: Republish with new visibility setting
- **Unpublish**: Set visibility to "private" (removes from marketplace)

#### Monitoring Your Collections

- **Subscriber Count**: Visible on collection card
- **Average Rating**: Displayed as stars + numeric value
- **Reviews**: (Future enhancement: view detailed reviews)

---

## Technical Specifications

### Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | HTML5, Tailwind CSS, Vanilla JavaScript (ES6 modules) |
| **Backend** | Python 3.10+, Quart (async Flask) |
| **Database** | SQLite (tda_auth.db) |
| **Vector Store** | ChromaDB |
| **Authentication** | JWT (JSON Web Tokens) |

### File Structure

```
uderia/
├── src/trusted_data_agent/
│   ├── api/
│   │   └── rest_routes.py          # Marketplace endpoints
│   ├── agent/
│   │   └── rag_retriever.py        # Access control, fork logic
│   └── auth/
│       └── models.py                # Subscription, Rating models
├── static/js/
│   └── handlers/
│       └── marketplaceHandler.js   # Frontend marketplace logic
├── templates/
│   └── index.html                   # Marketplace UI
├── test/
│   ├── test_marketplace_phase1.py
│   ├── test_marketplace_phase2.py
│   ├── test_marketplace_phase3.py
│   └── test_marketplace_phase4_ui.md
└── docs/Marketplace/
    ├── PHASE_1_COMPLETION.md
    ├── PHASE_2_COMPLETION.md
    ├── PHASE_3_COMPLETION.md
    └── PHASE_4_COMPLETION.md
```

### Dependencies

**Backend:**
- `quart` - Async web framework
- `sqlite3` - Database (Python stdlib)
- `chromadb` - Vector database
- `PyJWT` - JWT authentication

**Frontend:**
- Tailwind CSS (CDN)
- No additional npm packages
- Browser fetch API
- Native ES6 modules

### Database Schema

See [Phase 1 documentation](#phase-1-data-model--ownership) for complete schema.

**Key Tables:**
- `rag_collections` - Collection metadata
- `collection_subscriptions` - User subscriptions
- `collection_ratings` - Ratings and reviews

**Indexes:**
```sql
CREATE INDEX idx_subscriptions_user ON collection_subscriptions(user_id);
CREATE INDEX idx_subscriptions_collection ON collection_subscriptions(collection_id);
CREATE INDEX idx_ratings_collection ON collection_ratings(collection_id);
```

### API Authentication

All marketplace endpoints require JWT authentication:

```http
Authorization: Bearer <JWT_TOKEN>
```

**Token Generation:**
- User logs in → server issues JWT
- Token includes `user_id` claim
- Token expiration configurable (default: 24 hours)

**Token Validation:**
- Middleware decodes and validates JWT
- Extracts `user_id` for authorization checks
- Rejects expired or invalid tokens

---

## API Reference

### Complete Endpoint List

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/v1/marketplace/collections` | Browse collections | Yes |
| POST | `/v1/marketplace/collections/:id/subscribe` | Subscribe | Yes |
| DELETE | `/v1/marketplace/subscriptions/:id` | Unsubscribe | Yes |
| POST | `/v1/marketplace/collections/:id/fork` | Fork collection | Yes |
| POST | `/v1/rag/collections/:id/publish` | Publish collection | Yes (owner) |
| POST | `/v1/marketplace/collections/:id/rate` | Rate collection | Yes |

### Error Responses

All endpoints return standardized error format:

```json
{
  "error": "Human-readable error message",
  "details": "Optional additional context"
}
```

**Common HTTP Status Codes:**
- `200 OK` - Success
- `400 Bad Request` - Invalid input
- `401 Unauthorized` - Missing/invalid JWT
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource doesn't exist
- `409 Conflict` - Already subscribed, already rated, etc.
- `500 Internal Server Error` - Server-side error

---

## Security & Privacy

### Authentication & Authorization

**JWT-Based Auth:**
- All marketplace operations require valid JWT
- Token includes `user_id` for ownership checks
- Token expiration prevents stale sessions

**Authorization Checks:**
- Subscribe: Cannot subscribe to own collections
- Fork: Anyone can fork public/unlisted collections
- Publish: Must be collection owner
- Rate: Cannot rate own collections
- Unsubscribe: Must be subscription owner

### Data Privacy

**User Data:**
- Usernames visible in collection ownership
- User IDs hashed (UUIDs, not sequential)
- Reviews/ratings attributed to user (transparency)

**Collection Visibility:**
- **Private**: Owner only (default)
- **Unlisted**: Accessible via link, not in public browse
- **Public**: Fully discoverable in marketplace

### Input Validation

**Backend Validation:**
- SQL injection prevention (parameterized queries)
- XSS prevention (output escaping)
- Type validation (rating 1-5, etc.)
- Length limits on text fields

**Frontend Validation:**
- Required field checks
- Client-side escaping (`escapeHtml()`)
- Form validation before submission

### Vulnerability Mitigation

| Threat | Mitigation |
|--------|------------|
| **SQL Injection** | Parameterized queries, ORM usage |
| **XSS** | Output escaping, Content Security Policy |
| **CSRF** | JWT in Authorization header (not cookies) |
| **Unauthorized Access** | JWT validation, ownership checks |
| **Rate Limit Abuse** | (Future: implement rate limiting) |
| **Data Exfiltration** | Access control per collection |

---

## Performance & Scalability

### Current Performance

**Browse Endpoint:**
- Pagination (10 collections/page) reduces payload size
- Database query with JOINs optimized
- Average response time: < 200ms

**Fork Operation:**
- ChromaDB copy: ~500ms for 100 embeddings
- File copy: ~100ms for 50 RAG cases
- Total: ~1-2 seconds for medium collection

**Subscribe/Unsubscribe:**
- Simple INSERT/DELETE operations
- Average response time: < 50ms

### Scalability Considerations

**Database:**
- SQLite suitable for single-instance deployments
- For multi-user production: migrate to PostgreSQL
- Indexes on foreign keys improve JOIN performance

**ChromaDB:**
- In-memory mode fast but not persistent across restarts
- Persistent mode (disk-backed) recommended for production
- Consider distributed vector DB (e.g., Milvus, Weaviate) for scale

**File Storage:**
- RAG case files stored on local filesystem
- For cloud deployments: use S3/blob storage
- Fork operation could be async for large collections

### Optimization Opportunities

1. **Caching:**
   - Cache marketplace browse results (Redis)
   - Invalidate on collection updates
   - Reduce database load for frequent queries

2. **Async Fork:**
   - Background task for forking large collections
   - WebSocket notification on completion
   - Improves UX for slow operations

3. **Batch Operations:**
   - Bulk subscribe/unsubscribe (future feature)
   - Batch rating submission (e.g., import reviews)

4. **Search Optimization:**
   - Full-text search index on collection descriptions
   - Elasticsearch integration for advanced search

---

## Future Roadmap

### Short-Term Enhancements (v1.1)

**User-Requested Features:**
- [ ] Collection detail modal (preview RAG cases before subscribing)
- [ ] Sort options (popularity, rating, recent, alphabetical)
- [ ] Tag-based filtering (requires backend schema update)
- [ ] Collection usage analytics (view count, fork count)

**UX Improvements:**
- [ ] Keyboard navigation (Tab, Enter)
- [ ] Accessibility enhancements (ARIA labels, screen reader support)
- [ ] Mobile-responsive design (optimize for touch)
- [ ] Dark mode consistency

**Performance:**
- [ ] Debounced search input (reduce API calls)
- [ ] Infinite scroll pagination (alternative to page-based)
- [ ] Image thumbnails for collections (visual appeal)

### Medium-Term Features (v1.5)

**Advanced Discovery:**
- [ ] Personalized recommendations (ML-based)
- [ ] "Similar collections" suggestions
- [ ] Collection categories/taxonomies
- [ ] Featured collections (admin-curated)

**Collaboration:**
- [ ] Collection co-authorship (multiple owners)
- [ ] Commenting system on collections
- [ ] Collection versioning (track changes over time)
- [ ] Changelog for collection updates

**Analytics:**
- [ ] Publisher dashboard (views, subscribers, rating trends)
- [ ] User dashboard (my subscriptions, my published collections)
- [ ] Marketplace leaderboard (top collections, top publishers)

### Long-Term Vision (v2.0)

**Marketplace Monetization (Optional):**
- [ ] Premium collections (paid access)
- [ ] Donation/tip system for publishers
- [ ] Subscription tiers (free, pro, enterprise)

**Ecosystem Integration:**
- [ ] Import collections from GitHub (code → RAG cases)
- [ ] Export collections to standard formats (JSON, YAML)
- [ ] API marketplace (bundle collections with MCP servers)

**AI-Powered Features:**
- [ ] Auto-generate collection descriptions via LLM
- [ ] Quality scoring (AI-evaluated collection usefulness)
- [ ] Smart merging (suggest combining similar collections)

---

## Conclusion

The Intelligence Marketplace transforms the Uderia Platform from a single-user tool into a collaborative platform. By enabling users to share, discover, and reuse proven RAG collections, the marketplace:

- **Reduces token costs** through pattern reuse
- **Improves quality** via community ratings
- **Accelerates onboarding** for new users
- **Fosters innovation** through forking and iteration

**Implementation Status:** All 4 phases complete, ready for final testing and deployment.

**Total Effort:** ~40 hours of development, testing, and documentation

**Key Metrics to Track Post-Launch:**
- Number of published collections
- Average subscriber count per collection
- Fork rate (% of collections forked)
- Rating participation rate
- User retention improvement

---

## Skills Marketplace (Phase 5)

**Implementation Date:** February 2026
**Status:** ✅ Complete

### Overview

The Skills Marketplace extends the marketplace ecosystem to support sharing of pre-processing prompt injections. Skills modify LLM behavior before query execution — for example, enforcing SQL best practices, requiring concise responses, or enabling chain-of-thought reasoning.

Skills use the **standard Claude Code skill format** (`skill.json` + `<name>.md`), with an optional `uderia` section for platform-specific features (allowed params, injection target). A skill exported from the marketplace can be placed directly in `.claude/skills/` and work natively.

### Architecture

```
User creates skill → Publish to marketplace → Other users browse → Install → Activate with !name
     ↓                      ↓                       ↓                 ↓
  skill.json + .md    marketplace_skills       Search/Sort/Rate    ~/.tda/skills/
                      + skill_ratings          + Pagination        + hot-reload
                      + marketplace_data/
```

### Skill Format (Claude Code Compatible)

```
skill-name/
├── skill.json      ← Manifest (name, version, description, author, tags, main_file)
└── skill-name.md   ← Pure markdown content
```

Optional Uderia enhancement in `skill.json`:
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

### Database Tables

| Table | Purpose |
|-------|---------|
| `marketplace_skills` | Published skill metadata (name, version, author, tags, visibility, install count) |
| `skill_ratings` | Per-user ratings (1-5 stars + comment), unique per user per skill |
| `marketplace_sharing_grants` | Targeted visibility grants (reused, `resource_type='skill'`) |

Schema: `schema/17_marketplace_skills.sql`

### Marketplace Lifecycle

**Publishing:**
1. User creates a skill via the Skill Editor
2. Clicks "Publish" button on the skill card
3. Backend validates: user-created, marketplace enabled, not already published
4. Stores `skill.json` + `.md` in `marketplace_data/skills/{marketplace_id}/`
5. Inserts record into `marketplace_skills` table
6. Optionally sets targeted visibility via `marketplace_sharing_grants`

**Browsing:**
1. Click "Marketplace" button in Skills tab toolbar
2. Modal opens with search bar, sort options, and paginated grid
3. Each card shows: name, version, author, injection target badge, tags, star rating, install count
4. Sort by: Most Recent, Top Rated, Most Installs, Most Downloads, Name A-Z

**Installing:**
1. Click "Install" on a marketplace skill card
2. Backend reads `skill.json` + `.md` from marketplace storage
3. Saves to `~/.tda/skills/{skill_id}/` via skill manager
4. Hot-reloads skill manager
5. Increments `install_count`
6. Skill appears in local skills list, ready to activate with `!name`

**Rating:**
1. Click "Rate" on a marketplace skill card
2. Select 1-5 stars, optionally add a comment
3. Upsert into `skill_ratings` table (one rating per user per skill)
4. Average rating updates on the marketplace card

**Unpublishing:**
1. Publisher clicks "Unpublish" on their own skill card
2. Removes from `marketplace_skills`, `skill_ratings`, and sharing grants
3. Cleans up files from `marketplace_data/skills/{id}/`
4. Does not affect users who already installed the skill

### Admin Governance

The `user_skills_marketplace_enabled` setting in `skill_settings` controls marketplace access:
- When `true`: Publish button visible, marketplace browsable, install available
- When `false`: Publish returns 403, marketplace button hidden, install returns 403

Managed via: Administration → App Config → Skill Settings

### REST API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /v1/skills/{skill_id}/publish` | POST | Publish user skill |
| `GET /v1/marketplace/skills` | GET | Browse with search/sort/paginate |
| `GET /v1/marketplace/skills/{id}` | GET | Skill detail + ratings |
| `POST /v1/marketplace/skills/{id}/install` | POST | Install from marketplace |
| `POST /v1/marketplace/skills/{id}/rate` | POST | Rate (1-5 stars + comment) |
| `DELETE /v1/marketplace/skills/{id}` | DELETE | Unpublish (publisher only) |

Full endpoint documentation: `docs/RestAPI/restAPI.md` Section 3.21.

### Frontend Implementation

The marketplace UI is implemented in `static/js/handlers/skillHandler.js`:
- **Publish button**: Added to user-created skill cards (cloud-upload icon)
- **Marketplace button**: In skills tab toolbar, opens browsing modal
- **Browse modal**: Full-screen overlay with search, sort dropdown, paginated grid
- **Skill cards**: Glass-panel cards with emerald accent, colored tags, star ratings
- **Rating modal**: Interactive star selection with hover preview, comment field

### Export Format

Skills export as `.skill` files (ZIP containing `skill.json` + `<name>.md`). Import accepts both `.skill` and `.zip` for backward compatibility.

### Files Modified/Created

| File | Action | Purpose |
|------|--------|---------|
| `schema/17_marketplace_skills.sql` | Created | Marketplace + ratings tables |
| `schema/16_skill_settings.sql` | Modified | Added `user_skills_marketplace_enabled` |
| `src/trusted_data_agent/skills/settings.py` | Modified | `is_skill_marketplace_enabled()` predicate |
| `src/trusted_data_agent/auth/database.py` | Modified | Bootstrap schema 17 |
| `src/trusted_data_agent/api/skills_routes.py` | Modified | 6 marketplace endpoints + `.skill` export |
| `src/trusted_data_agent/api/admin_routes.py` | Modified | Marketplace setting validation |
| `static/js/handlers/skillHandler.js` | Modified | Publish, browse, install, rate UI |
| `templates/index.html` | Modified | Marketplace button in skills toolbar |

---

## Support & Resources

**Documentation:**
- Phase 1: `docs/Marketplace/PHASE_1_COMPLETION.md`
- Phase 2: `docs/Marketplace/PHASE_2_COMPLETION.md`
- Phase 3: `docs/Marketplace/PHASE_3_COMPLETION.md`
- Phase 4: `docs/Marketplace/PHASE_4_COMPLETION.md`

**Testing:**
- Unit Tests: `test/test_marketplace_phase*.py`
- UI Tests: `test/test_marketplace_phase4_ui.md`

**Code:**
- Backend (Collections): `src/trusted_data_agent/api/rest_routes.py` (~450 lines)
- Backend (Skills): `src/trusted_data_agent/api/skills_routes.py` (~350 lines marketplace)
- Frontend (Collections): `static/js/handlers/marketplaceHandler.js` (~765 lines)
- Frontend (Skills): `static/js/handlers/skillHandler.js` (marketplace modal + rating UI)

**Contact:**
- Project Repo: [uderia](https://github.com/your-org/uderia)
- Issues: GitHub Issues tracker
- Discussions: GitHub Discussions

---

**Document Version:** 1.1
**Last Updated:** February 2026
**Maintainer:** Development Team
