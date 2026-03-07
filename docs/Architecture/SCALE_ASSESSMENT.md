# Uderia Platform - Comprehensive Scale Assessment

**Date:** March 2026
**Current capacity estimate:** ~1,000s concurrent agents (single server, after Phase 1 optimizations)

---

## Executive Summary

The platform has **14 critical bottleneck categories** across 6 architectural layers. The root causes are:

1. **SQLite as primary database** -- single-writer serialization
2. **File-based session storage** -- filesystem I/O saturation
3. **In-process-only state** -- all caches, locks, and queues are per-process Python objects
4. **Single-process event loop** -- no horizontal scaling capability
5. **Unbounded in-memory caches** -- no eviction policies anywhere
6. **No backpressure mechanisms** -- no circuit breakers, no request queuing

---

## Layer 1: Database (CRITICAL)

### 1.1 SQLite with StaticPool -- Single Connection Serialization

| Property | Current | Impact at Scale |
|----------|---------|-----------------|
| **Connection pool** | `StaticPool` (1 connection) | All DB ops serialize through 1 connection |
| **Concurrent writers** | 1 (SQLite limitation) | Write throughput: ~100 ops/sec max |
| **WAL mode** | Not enabled | Readers blocked during writes |
| **Connection per request** | `get_db_session()` creates new session each call | 3-5 DB sessions per agent request |

**File:** `src/trusted_data_agent/auth/database.py:32-45`

**At 1K agents:** ~5,000 concurrent DB operations competing for 1 connection -- ~50s queue buildup per burst.
**At 1M agents:** Completely inoperable. ~10,000s (2.7 hours) queue wait.

**Missing optimizations:**
- No `PRAGMA journal_mode=WAL` (would enable concurrent reads during writes)
- No `PRAGMA synchronous=NORMAL`
- No `PRAGMA cache_size` tuning
- No `PRAGMA temp_store=MEMORY`

### 1.2 Collection Database -- No Connection Pooling

**File:** `src/trusted_data_agent/core/collection_db.py:25-29`

Every RAG collection operation creates a brand new SQLite connection. At scale, this creates connection storms and file descriptor exhaustion.

### 1.3 Consumption Enforcement -- N+1 Query Pattern

**File:** `src/trusted_data_agent/auth/consumption_enforcer.py:157-217`

Each enforcement check runs **5 sequential DB queries**:
1. Load User
2. Load ConsumptionProfile
3. Count hourly prompts (`func.count()` table scan)
4. Count daily prompts
5. Sum monthly token usage

**At 1K agents:** 5,000 queries/sec just for enforcement.
**At 1M agents:** 5M queries/sec -- impossible on SQLite.

### Recommended Improvements -- Database Layer

| Scale Target | Action | Effort |
|-------------|--------|--------|
| **100s** | Enable WAL mode, tune PRAGMAs, add connection pooling for collection_db | 1-2 days |
| **1,000s** | Migrate to PostgreSQL with pgBouncer connection pooling | 1-2 weeks |
| **10,000s** | Read replicas for query-heavy paths (consumption checks, session listing) | 1 week |
| **100,000s+** | Shard user data by user_uuid, dedicated DB for token_usage analytics | 2-4 weeks |
| **1M+** | Consumption enforcement via Redis counters (INCR + TTL), not DB queries | 1 week |

---

## Layer 2: Session Management (CRITICAL)

### 2.1 File-Based Session Storage

**File:** `src/trusted_data_agent/core/session_manager.py:91-102`

Sessions stored as `tda_sessions/{user_uuid}/{session_id}.json`. Every mutation requires:
1. Read entire JSON file from disk
2. Parse full JSON into Python dict
3. Modify in-memory
4. Re-serialize entire dict to JSON
5. Write to temp file
6. Atomic rename

**Session sizes:** Typical 500KB-5MB (chat history + workflow traces + execution data). Heavy sessions can reach 10MB+.

**At 1K agents:** 1,000 concurrent file read/write cycles -- filesystem I/O saturation on spinning disk, marginal on SSD.
**At 1M agents:** 1M files in nested directories -- filesystem metadata operations alone become bottleneck (inode lookups, directory scanning).

### 2.2 Session Listing -- O(n) Full Scan

**File:** `src/trusted_data_agent/core/session_manager.py:355-448`

Listing sessions requires opening and parsing EVERY session file. No index, no metadata cache.

**At 100 sessions/user:** ~100 file opens + JSON parses per listing.
**At 10K sessions/user:** UI becomes unusable (seconds of latency).

### 2.3 In-Process Session Locks -- No Cross-Server Coordination

**File:** `src/trusted_data_agent/core/session_manager.py:49-60`

- Locks exist only within a single Python process
- Multiple server instances = independent lock dicts = no coordination
- Lock dict grows unbounded (never pruned for completed sessions)
- Lock creation itself is racy (check-then-create without atomicity)

### Recommended Improvements -- Session Layer

| Scale Target | Action | Effort |
|-------------|--------|--------|
| **100s** | Add session metadata index (SQLite table with id, name, created_at, updated_at) to avoid full-file scans | 2-3 days |
| **1,000s** | Move session hot data (active chat, tokens, status) to Redis; keep cold data on disk | 1-2 weeks |
| **10,000s** | Replace file storage entirely with PostgreSQL (JSONB) or dedicated document store | 2-3 weeks |
| **100,000s+** | Implement session sharding by user_uuid hash; add distributed locking (Redis SETNX) | 2 weeks |
| **1M+** | Event-sourced sessions (append-only log, materialized views) -- eliminates full re-serialization | 4-6 weeks |

---

## Layer 3: LLM & Agent Execution (CRITICAL)

### 3.1 No LLM Client Pooling

**File:** `src/trusted_data_agent/llm/client_factory.py:15-51`

Every `create_llm_client()` call creates a **new client instance** with its own httpx connection pool.

**Memory per client:** ~500KB-1MB (httpx internals + SDK objects).
**At 1K agents:** 1,000 client objects = ~500MB-1GB.
**At 1M agents:** 1M clients = 500GB-1TB -- physically impossible.

### 3.2 Global APP_STATE -- Unbounded, Unprotected

**File:** `src/trusted_data_agent/core/config.py:131-200`

**Problems:**
- No locking on dict mutations -- race conditions under concurrent access
- All sub-dicts grow unbounded (no eviction): `llm_instance_pool`, `mcp_client_pool`, `tts_clients_by_user`, `notification_queues`
- Single `rag_processing_queue` for entire platform
- Single `configuration_lock` serializes all config changes globally

### 3.3 Single RAG Processing Worker

**File:** `src/trusted_data_agent/main.py:95-150`

**ONE worker** processes ALL RAG submissions sequentially.

**At 100ms/operation:** Max throughput = 10 ops/sec.
**At 1K agents:** If 50% trigger RAG = 500 ops queued = 50s wait.
**At 1M agents:** 500K ops queued = 50,000s (13.9 hours) wait.

### 3.4 No Backpressure or Circuit Breakers

- No circuit breaker for LLM provider failures (retry storm on outage)
- No request queuing with priority (all agents equal)
- No adaptive rate limiting based on provider response times
- Hard-coded event queue: `asyncio.Queue(maxsize=100)` in `executor.py:2630`

### 3.5 MCP Connection Management

**File:** `src/trusted_data_agent/mcp_adapter/adapter.py`

- New MCP session per request (no keep-alive/reuse)
- No connection pooling to MCP servers
- At 1M agents: 1M simultaneous MCP connections (most MCP servers would collapse)

### Recommended Improvements -- Execution Layer

| Scale Target | Action | Effort |
|-------------|--------|--------|
| **100s** | Implement LLM client pool (per provider+model key, max 10 clients each) | 2-3 days |
| **1,000s** | Add circuit breaker per LLM provider (exponential backoff, half-open probing) | 1 week |
| **1,000s** | Scale RAG worker to pool of N workers (configurable, default 10) | 2-3 days |
| **10,000s** | Replace APP_STATE dicts with concurrent-safe structures (LRU caches with max-size) | 1-2 weeks |
| **100,000s+** | Distribute execution via task queue (Celery/Redis Queue/NATS) -- decouple API from execution | 3-4 weeks |
| **1M+** | MCP connection multiplexing (shared connections per server, request pipelining) | 2-3 weeks |
| **1M+** | Kubernetes-based autoscaling with pod-per-agent or pod-per-N-agents | 4-6 weeks |

---

## Layer 4: Caching & Memory (HIGH)

### 4.1 Prompt Loader -- Unbounded Triple Cache

**File:** `src/trusted_data_agent/agent/prompt_loader.py:113-116`

Cache key pattern: `f"{name}:{user_uuid}:{profile_id}"`.
**At 1M users x 100 prompts x 10 profiles = 1B possible keys.** No TTL, no eviction, no max size.

### 4.2 ChromaDB Collection Cache -- Unbounded

**File:** `src/trusted_data_agent/agent/rag_retriever.py:56`

Each collection object holds in-memory indices. No eviction policy.

### 4.3 Vector Store Factory -- Unbounded Instance + Lock Caches

**File:** `src/trusted_data_agent/vectorstore/factory.py:36-44`

`_INSTANCES` and `_INIT_LOCKS` dicts grow indefinitely with unique config keys. Never pruned.

### 4.4 Embedding Model Cache

Each unique embedding model loads 100-500MB of weights into memory. With N distinct models cached globally, memory grows as `N * model_size`.

### 4.5 Cost Manager -- No Caching

**File:** `src/trusted_data_agent/core/cost_manager.py:237-246`

`get_model_cost()` creates a new DB session for EVERY lookup. Called on every token count event. No caching whatsoever.

### Recommended Improvements -- Caching Layer

| Scale Target | Action | Effort |
|-------------|--------|--------|
| **100s** | Add TTL (5 min) + max-size (10K entries) to PromptLoader caches | 1 day |
| **100s** | Add LRU cache to `cost_manager.get_model_cost()` (costs change rarely) | 2 hours |
| **1,000s** | Implement cache eviction for ChromaDB collections (LRU, max 100 collections) | 1-2 days |
| **10,000s** | Move hot caches to Redis (prompt cache, cost cache, config cache) -- shared across instances | 1-2 weeks |
| **100,000s+** | Implement tiered caching: L1 (in-process LRU) -> L2 (Redis) -> L3 (database) | 2-3 weeks |
| **1M+** | Embedding model serving via dedicated GPU service (not in-process) | 2-4 weeks |

---

## Layer 5: Web Server & API (HIGH)

### 5.1 Single-Process Event Loop

**File:** `src/trusted_data_agent/main.py:334-349`

All request handling, SSE streaming, LLM calls, and background tasks run on ONE asyncio event loop. Any CPU-bound operation (JSON parsing, column statistics, token estimation) blocks all other requests.

### 5.2 SSE Connection Scaling

Each active agent holds an SSE connection (`/ask_stream`) for the duration of execution.

**At 1K agents:** 1,000 concurrent SSE connections -- manageable for Hypercorn.
**At 10K agents:** TCP backlog pressure, need to tune `somaxconn`.
**At 1M agents:** Requires dedicated SSE/WebSocket gateway (e.g., Centrifugo, Socket.IO cluster).

### 5.3 JWT Validation -- No Caching

**File:** `src/trusted_data_agent/auth/middleware.py:21-86`

Every request: (1) crypto signature verification, (2) database query for user record. No caching of verified tokens.

### 5.4 Rate Limiting -- In-Memory Only

**File:** `src/trusted_data_agent/auth/rate_limiter.py:96-100`

Per-process Python dict. Multiple servers = independent rate limit state. No persistence across restarts.

### Recommended Improvements -- API Layer

| Scale Target | Action | Effort |
|-------------|--------|--------|
| **100s** | Add JWT signature LRU cache (10K entries, 1-hour TTL) | 2-3 hours |
| **1,000s** | Run Hypercorn with multiple workers (`--workers N`) | 1 day |
| **10,000s** | Move rate limiting to Redis (shared across instances) | 2-3 days |
| **100,000s+** | Deploy behind reverse proxy (nginx/envoy) with connection limiting | 1 week |
| **100,000s+** | Separate SSE gateway from API server (dedicated SSE service) | 2-3 weeks |
| **1M+** | Kubernetes Horizontal Pod Autoscaler with readiness probes | 2-3 weeks |
| **1M+** | Replace SSE with WebSocket + pub/sub (Redis Pub/Sub or NATS) | 3-4 weeks |

---

## Layer 6: Infrastructure & Deployment (MEDIUM)

### 6.1 Single-Server Architecture

Current deployment model is one Python process on one machine. All state (files, SQLite, in-memory caches) is local. No mechanism for horizontal scaling, state sharing, automatic failover, or health monitoring.

### 6.2 File System as Database

Three categories of data stored on local filesystem:
1. `tda_auth.db` -- SQLite database
2. `tda_sessions/` -- Session JSON files
3. `chromadb/` -- Vector store data

All are single-machine, single-process resources.

### 6.3 No Observability at Scale

- Logging is per-process (`logging.getLogger`)
- No distributed tracing (no request IDs propagated across LLM calls)
- No metrics collection (no Prometheus/StatsD integration)
- No alerting on resource exhaustion

### Recommended Improvements -- Infrastructure

| Scale Target | Action | Effort |
|-------------|--------|--------|
| **1,000s** | Add health check endpoints, structured JSON logging, request ID tracing | 1 week |
| **10,000s** | Containerize with Docker Compose: API + PostgreSQL + Redis + ChromaDB | 1-2 weeks |
| **100,000s+** | Kubernetes deployment with StatefulSets for databases, Deployments for API | 3-4 weeks |
| **100,000s+** | Add Prometheus metrics (request latency, queue depth, cache hit rate, DB pool usage) | 1-2 weeks |
| **1M+** | Multi-region deployment with geo-routing, data replication | 2-3 months |

---

## Consolidated Bottleneck Severity Matrix

| # | Bottleneck | Layer | Current Limit | Breaks At | Severity | Status |
|---|-----------|-------|--------------|-----------|----------|--------|
| 1 | SQLite StaticPool (1 connection) | Database | ~100 writes/sec | 100s of agents | **CRITICAL** | **RESOLVED** (Phase 1) |
| 2 | File-based sessions (full re-serialize) | Session | ~1K concurrent | 1,000s of agents | **CRITICAL** | Open |
| 3 | Single RAG processing worker | Execution | 10 ops/sec | 100s of agents | **CRITICAL** | **RESOLVED** (Phase 1) |
| 4 | No LLM client pooling (new client per call) | Execution | ~1GB at 1K agents | 1,000s of agents | **CRITICAL** | **RESOLVED** (Phase 1) |
| 5 | Global APP_STATE (unprotected, unbounded) | Execution | Race conditions at any scale | 100s of agents | **CRITICAL** | **RESOLVED** (Phase 1) |
| 6 | In-process-only locks (no distributed coordination) | Session | 1 server instance | Any multi-instance | **CRITICAL** | Open |
| 7 | Session listing O(n) file scan | Session | ~1K sessions/user | 1,000s of sessions | **HIGH** | **RESOLVED** (Phase 1) |
| 8 | Consumption enforcement 5 queries/check | Database | ~200 checks/sec | 1,000s of agents | **HIGH** | Open |
| 9 | No JWT validation cache | API | ~10K verifications/sec | 10,000s of agents | **HIGH** | **RESOLVED** (Phase 1) |
| 10 | Unbounded prompt/collection/backend caches | Caching | GB-scale memory | 10,000s of agents | **HIGH** | **PARTIAL** (Phase 1 -- PromptLoader + cost mgr bounded; VectorStore/collection caches deferred to Phase 2) |
| 11 | Single asyncio event loop | API | CPU-bound ops block all | 1,000s of agents | **HIGH** | Open |
| 12 | In-memory rate limiting (per-process) | API | 1 server instance | Any multi-instance | **MEDIUM** | Open (Phase 2) |
| 13 | No circuit breakers for LLM providers | Execution | Retry storms on outage | 100s of agents | **MEDIUM** | Open (Phase 2) |
| 14 | No observability/metrics | Infra | Blind at any scale | 100s of agents | **MEDIUM** | Open |

---

## Phased Improvement Roadmap

### Phase 1: Quick Wins (COMPLETE -- March 2026) -- Scale to 1,000s of agents

**Goal:** Remove the cheapest critical bottlenecks without architectural changes.
**Status:** All 8 items implemented and verified via REST API testing.

1. **SQLite WAL mode + PRAGMAs** -- `database.py` -- WAL, synchronous=NORMAL, cache_size=-64000, temp_store=MEMORY [DONE]
2. **LLM client pool** -- `client_factory.py` -- `get_or_create_llm_client()` with 50-max pool, keyed by provider+model+credentials hash [DONE]
3. **Scale RAG worker** -- `main.py` -- Pool of 10 workers (configurable via `TDA_RAG_WORKERS`) [DONE]
4. **JWT validation cache** -- `middleware.py` -- In-memory TTL cache (60s, 10K max) with explicit invalidation on token revocation [DONE]
5. **Cost manager cache** -- `cost_manager.py` -- 5-minute TTL cache for model pricing lookups [DONE]
6. **PromptLoader bounded caches** -- `prompt_loader.py` -- `_TTLCache` class with TTL (5 min) + max-size (10K) eviction [DONE]
7. **Session metadata index** -- `session_manager.py` -- aiosqlite-based index with auto-rebuild on startup [DONE]
8. **APP_STATE lock protection** -- `config.py`, `configuration_service.py` -- asyncio.Lock + dict.setdefault() for atomic operations [DONE]

### Phase 2: Foundation (POSTPONED) -- Scale to 10,000s of agents

**Goal:** Add reliability infrastructure (circuit breakers), cache hygiene (evict unbounded caches), and Redis integration (shared state for future multi-process scaling).
**Infrastructure:** Redis instance (existing), Teradata (enterprise DB -- full migration deferred to Phase 3).
**Target:** ~10,000s of concurrent agents with resilience to provider failures.
**Estimated effort:** ~7 days

#### Item 1: LLM Circuit Breakers (~2 days) -- Priority: TOP

Prevents cascading failures when LLM providers go down.

**New file:** `src/trusted_data_agent/llm/circuit_breaker.py`
- `CircuitBreaker` class: CLOSED -> OPEN (after 3 consecutive failures) -> HALF_OPEN (after 60s timeout) -> CLOSED (on success)
- Module-level registry keyed by provider name
- `CircuitBreakerOpen` exception for fast-fail (non-retryable)
- Config: `TDA_CIRCUIT_BREAKER_THRESHOLD` (default 3), `TDA_CIRCUIT_BREAKER_TIMEOUT` (default 60)

**Integration points:**
- `llm/handler.py` -- wrap retry loop: check `allow_request()` before attempts, `record_failure()` in exception handlers, `record_success()` after response
- Expand caught error types: add `GoogleAPIError`, `botocore.ClientError`, `httpx.ConnectError/TimeoutException`, `ConnectionError/TimeoutError`
- `agent/executor.py` -- catch `CircuitBreakerOpen`, yield user-friendly SSE error
- `agent/phase_executor.py` -- catch in tactical calls, treat as non-retryable
- `api/admin_routes.py` -- `GET /api/v1/admin/circuit-breakers` + `POST .../reset`

#### Item 2: Cache Eviction for Unbounded Caches (~1 day) -- Priority: HIGH

**New file:** `src/trusted_data_agent/core/cache_janitor.py`
- Periodic async task (every 5 min): purge completed background_tasks (>1hr), stale mcp_tool_schema_cache (>10min)
- Start via `asyncio.create_task()` in `main.py` startup

**Max-size guards:**
- `configuration_service.py` -- `llm_instance_pool` FIFO eviction at 50
- `vectorstore/factory.py` -- `_INSTANCES` FIFO eviction at 20
- `core/config.py` -- `current_provider_by_user` / `current_model_by_user` FIFO eviction at 500

#### Item 3: Redis Foundation (~0.5 day) -- Priority: MEDIUM

**New file:** `src/trusted_data_agent/core/redis_client.py`
- Async Redis singleton via `redis>=5.0.0` (add to `requirements.txt`)
- Config: `TDA_REDIS_ENABLED` (default false), `TDA_REDIS_URL`, `TDA_REDIS_PREFIX=uderia:`
- `get_redis() -> Optional[Redis]` -- returns None if disabled/unavailable (all consumers must handle None)
- Lifecycle: connect in `@app.before_serving`, close in `@app.after_serving`
- Admin: `GET /api/v1/admin/redis/status`

#### Item 4: Redis-Backed Rate Limiting (~1 day) -- Priority: MEDIUM (depends on Item 3)

- `rate_limiter.py` -- add Redis path (INCR + EXPIRE), fallback to existing in-memory
- `check_rate_limit()` becomes async -- update 4 callers (all in async route handlers)

#### Item 5: Redis-Backed JWT Auth Cache (~0.5 day) -- Priority: LOW (depends on Item 3)

- `middleware.py` -- add Redis as L2 cache: L1 (in-memory) -> L2 (Redis GET/SET with 60s TTL) -> DB
- `get_current_user()` becomes async -- update `require_auth`, `require_admin`, `optional_auth` decorators

#### Item 6: Redis-Backed Consumption Counters (~1 day) -- Priority: LOW (depends on Item 3)

- `consumption_enforcer.py` -- replace 5 sequential DB queries with Redis INCR+EXPIRE counters
- Keep DB writes for audit trail; Redis is fast-path check
- Fallback to existing DB queries if Redis unavailable

#### Item 7: Collection DB Connection Pooling (~0.5 day) -- Priority: LOW

- `collection_db.py` -- replace per-call `sqlite3.connect()` with context-manager pool (3 connections)
- Add WAL mode pragma to pooled connections

#### Implementation Order

```
Day 1-2: Item 1 (Circuit Breakers) -- new file + handler integration + admin endpoints
Day 3:   Item 2 (Cache Eviction) + Item 7 (Collection DB Pooling)
Day 4:   Item 3 (Redis Foundation)
Day 5:   Item 4 (Redis Rate Limiting)
Day 6:   Item 5 (Redis JWT Cache) + Item 6 (Redis Consumption Counters)
Day 7:   Integration testing all items together
```

#### Files Modified (Phase 2)

| File | Items | Changes |
|------|-------|---------|
| **NEW** `llm/circuit_breaker.py` | 1 | CircuitBreaker class + registry |
| **NEW** `core/cache_janitor.py` | 2 | Background cleanup task |
| **NEW** `core/redis_client.py` | 3 | Async Redis singleton |
| `llm/handler.py` | 1 | Circuit breaker wrapping retry loop |
| `agent/executor.py` | 1 | Handle CircuitBreakerOpen |
| `agent/phase_executor.py` | 1 | Handle CircuitBreakerOpen |
| `api/admin_routes.py` | 1, 3 | Circuit breaker + Redis admin endpoints |
| `main.py` | 2, 3 | Cache janitor + Redis lifecycle |
| `core/configuration_service.py` | 2 | LLM pool max-size |
| `vectorstore/factory.py` | 2 | Instance pool max-size |
| `core/config.py` | 2 | Per-user dict max-size |
| `auth/rate_limiter.py` | 4 | Redis rate limiting + async |
| `auth/middleware.py` | 5 | Redis L2 JWT cache + async |
| `auth/consumption_enforcer.py` | 6 | Redis consumption counters |
| `core/collection_db.py` | 7 | Connection pooling |
| `requirements.txt` | 3 | Add redis>=5.0.0 |

### Phase 3: Horizontal Scaling (1-3 months) -- Scale to 100,000s of agents

**Goal:** Stateless API servers with externalized state, horizontal scaling.

1. **Task queue** -- Celery/Redis Queue for agent execution (decouple API from LLM calls)
2. **Dedicated SSE/WebSocket gateway** -- Separate service for real-time streaming
3. **Kubernetes deployment** -- HPA, StatefulSets, service mesh
4. **Observability** -- Prometheus metrics, distributed tracing, structured logging
5. **Embedding model service** -- Dedicated GPU service for vector embeddings
6. **MCP connection multiplexing** -- Shared connection pools per MCP server

### Phase 4: Planet Scale (3-6 months) -- Scale to 1M+ agents

**Goal:** Multi-region, fully distributed, auto-scaling architecture.

1. **Event-sourced sessions** -- Append-only event log, materialized views
2. **Database sharding** -- User-based sharding for PostgreSQL
3. **Multi-region** -- Geo-routing, data replication, eventual consistency
4. **Agent scheduling** -- Priority queues, fair scheduling, resource quotas per tenant
5. **Vector store clustering** -- Qdrant Cloud cluster or Teradata distributed deployment
6. **Pub/Sub for real-time** -- NATS or Redis Streams replacing SSE

---

## Key Files Reference

| Area | File | Primary Concern |
|------|------|-----------------|
| Database engine | `src/trusted_data_agent/auth/database.py:32-52` | StaticPool, no WAL |
| Session storage | `src/trusted_data_agent/core/session_manager.py:49-60, 136-226, 355-448` | File I/O, locks, listing |
| Collection DB | `src/trusted_data_agent/core/collection_db.py:25-29` | No connection pooling |
| Global state | `src/trusted_data_agent/core/config.py:131-200` | Unbounded, unprotected |
| LLM clients | `src/trusted_data_agent/llm/client_factory.py:15-51` | No pooling/reuse |
| LLM handler | `src/trusted_data_agent/llm/handler.py:1058-1090` | No circuit breaker |
| RAG worker | `src/trusted_data_agent/main.py:95-150` | Single worker |
| Agent executor | `src/trusted_data_agent/agent/executor.py:2630` | Hard-coded queue size |
| Prompt caching | `src/trusted_data_agent/agent/prompt_loader.py:113-116` | Unbounded caches |
| JWT auth | `src/trusted_data_agent/auth/middleware.py:21-86` | No validation cache |
| Rate limiting | `src/trusted_data_agent/auth/rate_limiter.py:96-100` | In-memory only |
| Consumption | `src/trusted_data_agent/auth/consumption_enforcer.py:157-217` | N+1 queries |
| Cost tracking | `src/trusted_data_agent/core/cost_manager.py:237-246` | No caching |
| Vector factory | `src/trusted_data_agent/vectorstore/factory.py:36-44` | Unbounded caches |
| ChromaDB | `src/trusted_data_agent/vectorstore/chromadb_backend.py:56-57` | Unbounded collection cache |
| Web server | `src/trusted_data_agent/main.py:334-349` | Single event loop |
| MCP adapter | `src/trusted_data_agent/mcp_adapter/adapter.py` | No connection pooling |
| Component mgr | `src/trusted_data_agent/components/manager.py:38-51` | Global singleton |
