# Uderia Platform - Comprehensive Scale Assessment

**Date:** March 2026
**Current capacity estimate:** ~100-1,000 concurrent agents (single server)

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

| # | Bottleneck | Layer | Current Limit | Breaks At | Severity |
|---|-----------|-------|--------------|-----------|----------|
| 1 | SQLite StaticPool (1 connection) | Database | ~100 writes/sec | 100s of agents | **CRITICAL** |
| 2 | File-based sessions (full re-serialize) | Session | ~1K concurrent | 1,000s of agents | **CRITICAL** |
| 3 | Single RAG processing worker | Execution | 10 ops/sec | 100s of agents | **CRITICAL** |
| 4 | No LLM client pooling (new client per call) | Execution | ~1GB at 1K agents | 1,000s of agents | **CRITICAL** |
| 5 | Global APP_STATE (unprotected, unbounded) | Execution | Race conditions at any scale | 100s of agents | **CRITICAL** |
| 6 | In-process-only locks (no distributed coordination) | Session | 1 server instance | Any multi-instance | **CRITICAL** |
| 7 | Session listing O(n) file scan | Session | ~1K sessions/user | 1,000s of sessions | **HIGH** |
| 8 | Consumption enforcement 5 queries/check | Database | ~200 checks/sec | 1,000s of agents | **HIGH** |
| 9 | No JWT validation cache | API | ~10K verifications/sec | 10,000s of agents | **HIGH** |
| 10 | Unbounded prompt/collection/backend caches | Caching | GB-scale memory | 10,000s of agents | **HIGH** |
| 11 | Single asyncio event loop | API | CPU-bound ops block all | 1,000s of agents | **HIGH** |
| 12 | In-memory rate limiting (per-process) | API | 1 server instance | Any multi-instance | **MEDIUM** |
| 13 | No circuit breakers for LLM providers | Execution | Retry storms on outage | 100s of agents | **MEDIUM** |
| 14 | No observability/metrics | Infra | Blind at any scale | 100s of agents | **MEDIUM** |

---

## Phased Improvement Roadmap

### Phase 1: Quick Wins (1-2 weeks) -- Scale to 1,000s of agents

**Goal:** Remove the cheapest critical bottlenecks without architectural changes.

1. **Enable SQLite WAL mode + PRAGMAs** -- `database.py:32-45`
2. **LLM client pool** -- `client_factory.py` -- reuse clients per (provider, model) key
3. **Scale RAG worker** -- `main.py` -- pool of 10 workers instead of 1
4. **JWT validation LRU cache** -- `middleware.py` -- 10K entries, 1-hour TTL
5. **Cost manager cache** -- `cost_manager.py` -- LRU cache for model pricing
6. **Add max-size + TTL to PromptLoader caches** -- `prompt_loader.py`
7. **Session metadata index** -- SQLite table for fast listing without full-file scan
8. **APP_STATE lock protection** -- Add `asyncio.Lock` guards on mutable dict operations

### Phase 2: Foundation (2-6 weeks) -- Scale to 10,000s of agents

**Goal:** Replace core single-server dependencies with scalable alternatives.

1. **Migrate to PostgreSQL** -- Replace SQLite with PostgreSQL + pgBouncer
2. **Redis for hot state** -- Rate limiting, session hot data, JWT cache, config cache
3. **Session storage redesign** -- PostgreSQL JSONB or Redis for active sessions
4. **Circuit breakers** -- Per-LLM-provider circuit breaker with adaptive backoff
5. **Multi-worker Hypercorn** -- Run with `--workers N` behind nginx
6. **Cache eviction everywhere** -- LRU with configurable max-size for all caches
7. **Distributed locking** -- Redis-based session locks (replace asyncio.Lock)

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
