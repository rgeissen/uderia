# Vector Store Abstraction Layer — Architecture

## Overview

The Uderia Platform's **Vector Store Abstraction Layer** decouples the core platform from any specific vector database implementation. It defines a single, async-first interface that all backends must satisfy, enables capability-based negotiation for optional features, and ships with three production-ready backends: **ChromaDB** (local/embedded, default), **Teradata** (enterprise, server-side embedding via Amazon Bedrock or Azure), and **Qdrant Cloud** (managed cloud vector DB, client-side embedding via SentenceTransformer).

The abstraction makes it possible to add new backends without touching any agent, route, or UI code — only the new backend module and a one-line registry call are required.

---

## Module Layout

```
src/trusted_data_agent/vectorstore/
├── __init__.py               # Public API surface — everything callers import
├── base.py                   # VectorStoreBackend abstract base class
├── capabilities.py           # VectorStoreCapability enum + REQUIRED_CAPABILITIES
├── types.py                  # Shared data types (VectorDocument, QueryResult, …)
├── filters.py                # Metadata filter AST + ChromaDB translation helpers
├── embedding_providers.py    # EmbeddingProvider ABC + concrete implementations
├── factory.py                # Singleton factory + backend registry
├── chromadb_backend.py       # ChromaDB implementation (~435 lines)
├── teradata_backend.py       # Teradata implementation (~756 lines)
└── qdrant_backend.py         # Qdrant Cloud implementation (~445 lines)
```

| File | Lines | Role |
|---|---|---|
| `base.py` | ~195 | Abstract interface all backends implement |
| `types.py` | 92 | Normalized data structures |
| `capabilities.py` | ~60 | Capability flags + required set |
| `embedding_providers.py` | 149 | Embedding abstraction + model cache |
| `filters.py` | 145 | Filter AST + ChromaDB bridge |
| `factory.py` | ~175 | Singleton caching factory with asyncio lock |
| `chromadb_backend.py` | 435 | ChromaDB concrete backend |
| `teradata_backend.py` | ~990 | Teradata concrete backend (client + server-side chunking) |
| `qdrant_backend.py` | ~445 | Qdrant Cloud concrete backend (client-side embedding) |
| **Total** | **~2,686** | Core layer |

---

## Core Components

### 1. Abstract Base — `VectorStoreBackend`

**File:** [vectorstore/base.py](../../src/trusted_data_agent/vectorstore/base.py)

Every backend extends `VectorStoreBackend` and implements the following groups of methods:

#### Identity & Capabilities
```python
@property
@abstractmethod
def backend_type(self) -> str: ...

@abstractmethod
def capabilities(self) -> Set[VectorStoreCapability]: ...

def has_capability(self, cap: VectorStoreCapability) -> bool:
    return cap in self.capabilities()
```

#### Lifecycle
```python
@abstractmethod
async def initialize(self) -> None: ...

@abstractmethod
async def shutdown(self) -> None: ...
```

#### Collection Management
```python
async def create_collection(self, name, config) -> CollectionInfo
async def get_or_create_collection(self, name, config) -> CollectionInfo
async def get_collection_info(self, name) -> Optional[CollectionInfo]
async def delete_collection(self, name) -> None
async def count(self, collection_name) -> int
```

#### Document Writes
```python
async def add(self, collection_name, documents, embedding_provider) -> int
async def upsert(self, collection_name, documents, embedding_provider) -> int
async def delete(self, collection_name, ids) -> None
async def update_metadata(self, collection_name, ids, metadatas) -> None

# Optional — requires SERVER_SIDE_CHUNKING capability
async def add_document_files(self, collection_name, file_paths, chunking_config) -> int
```

#### Document Reads
```python
async def query(self, collection_name, query_text, n_results, where,
                include_documents, include_metadata, include_embeddings) -> QueryResult
async def get(self, collection_name, ids, where,
              include_documents, include_metadata, include_embeddings,
              limit, offset) -> GetResult
```

**Design rule:** All methods are `async`. Synchronous backends (ChromaDB) wrap their blocking I/O with `asyncio.to_thread()` so they never block Quart's event loop.

---

### 2. Normalized Data Types — `types.py`

**File:** [vectorstore/types.py](../../src/trusted_data_agent/vectorstore/types.py)

Each backend translates its native wire format into these shared types at the boundary, so callers are fully insulated from backend-specific shapes.

| Type | Fields | Notes |
|---|---|---|
| `VectorDocument` | `id`, `content`, `metadata`, `embedding?` | Input type for add/upsert |
| `CollectionConfig` | `name`, `metadata`, `embedding_model`, `distance_metric`, `backend_config` | Passed to create_collection |
| `CollectionInfo` | `name`, `count`, `metadata`, `backend_type` | Returned from get_collection_info |
| `QueryResult` | `ids[]`, `documents[]`, `metadatas[]`, `distances[]` | Flat parallel lists |
| `GetResult` | `ids[]`, `documents[]`, `metadatas[]`, `embeddings[]` | Non-similarity fetch |
| `DistanceMetric` | `COSINE`, `EUCLIDEAN`, `DOT_PRODUCT`, `MANHATTAN` | Backend-mapped |

ChromaDB returns nested lists; Teradata returns objects — both are normalized to `QueryResult`/`GetResult` inside the respective backend implementation.

---

### 3. Capability Negotiation — `capabilities.py`

**File:** [vectorstore/capabilities.py](../../src/trusted_data_agent/vectorstore/capabilities.py)

```python
class VectorStoreCapability(Enum):
    # Required (all backends must declare these)
    CREATE_COLLECTION        = "create_collection"
    DELETE_COLLECTION        = "delete_collection"
    ADD_DOCUMENTS            = "add_documents"
    DELETE_DOCUMENTS         = "delete_documents"
    SIMILARITY_SEARCH        = "similarity_search"
    GET_BY_ID                = "get_by_id"
    COUNT                    = "count"

    # Optional
    UPSERT                   = "upsert"
    GET_BY_METADATA_FILTER   = "get_by_metadata_filter"
    UPDATE_METADATA          = "update_metadata"
    EMBEDDING_PASSTHROUGH    = "embedding_passthrough"   # accepts pre-computed vectors
    GET_ALL                  = "get_all"
    SERVER_SIDE_EMBEDDING    = "server_side_embedding"   # backend embeds text itself
    SERVER_SIDE_CHUNKING     = "server_side_chunking"    # backend ingests raw files (PDF, etc.)
```

**Usage pattern for callers:**
```python
if backend.has_capability(VectorStoreCapability.UPSERT):
    await backend.upsert(collection, documents, provider)
else:
    # Fallback: delete-then-add
    await backend.delete(collection, [d.id for d in documents])
    await backend.add(collection, documents, provider)
```

The factory validates that every registered backend declares all required capabilities at registration time.

---

### 4. Embedding Provider Abstraction — `embedding_providers.py`

**File:** [vectorstore/embedding_providers.py](../../src/trusted_data_agent/vectorstore/embedding_providers.py)

```
EmbeddingProvider (ABC)
├── SentenceTransformerProvider   — client-side embedding, class-level model cache
└── ServerSideEmbeddingProvider   — marker class; backend does embedding itself
```

#### `SentenceTransformerProvider`
- Wraps ChromaDB's `SentenceTransformerEmbeddingFunction`
- Class-level cache (`_cache[model_name]`) prevents redundant model loading across collections
- Known dimensions map for common models:
  ```python
  "all-MiniLM-L6-v2"  → 384
  "all-mpnet-base-v2" → 768
  # …
  ```
- Exposes `chromadb_embedding_function` property for direct ChromaDB integration

#### `ServerSideEmbeddingProvider`
- Marker class with `NotImplementedError` on `embed_texts` / `embed_query`
- Backends check `isinstance(provider, ServerSideEmbeddingProvider)` to bypass client inference and defer to their own embedding pipeline

#### Factory Function
```python
def get_embedding_provider(backend_type: str, model_name: str) -> EmbeddingProvider:
    if backend_type == "teradata":
        return ServerSideEmbeddingProvider(model_name)
    return SentenceTransformerProvider(model_name)
```

---

### 5. Metadata Filter AST — `filters.py`

**File:** [vectorstore/filters.py](../../src/trusted_data_agent/vectorstore/filters.py)

Filters are represented as an expression tree that backends translate to their native query syntax. This prevents callers from writing ChromaDB-specific `$and`/`$eq` dicts.

#### Filter Types
```python
@dataclass
class FieldFilter:
    field: str
    op: FilterOp        # EQ, NE, GT, GTE, LT, LTE, IN, NOT_IN
    value: Any

@dataclass
class AndFilter:
    conditions: List[MetadataFilter]

@dataclass
class OrFilter:
    conditions: List[MetadataFilter]

MetadataFilter = Optional[Union[FieldFilter, AndFilter, OrFilter]]
```

#### Convenience Constructors
```python
eq("database_name", "my_db")
gt("score", 0.8)
and_(eq("type", "sql"), eq("db", "prod"))
or_(eq("tier", "premium"), eq("tier", "enterprise"))
```

#### Translation Helpers
```python
# Forward: AST → ChromaDB where dict
to_chromadb_where(filter) -> dict

# Reverse: ChromaDB where dict → AST (used in migration bridge)
from_chromadb_where(where_dict) -> MetadataFilter
```

The reverse translation (`from_chromadb_where`) lets legacy code that already constructs ChromaDB-style `where` dicts be used unchanged through an adaptor call, without requiring a full rewrite.

---

### 6. Backend Factory — `factory.py`

**File:** [vectorstore/factory.py](../../src/trusted_data_agent/vectorstore/factory.py)

The factory is the single point of backend instantiation and caching.

#### Registry
```python
_REGISTRY: Dict[str, Type[VectorStoreBackend]] = {}

def register_backend(backend_type: str, cls: Type[VectorStoreBackend]) -> None:
    _REGISTRY[backend_type] = cls
```

Backends self-register at import time — no central manifest to update.

#### Singleton Cache
```python
_INSTANCES: Dict[str, VectorStoreBackend] = {}   # config fingerprint → backend
_DEFAULT_CHROMADB: Optional[ChromaDBBackend] = None

def _config_fingerprint(backend_type: str, config: dict) -> str:
    return hashlib.md5(
        json.dumps({"t": backend_type, "c": config}, sort_keys=True).encode()
    ).hexdigest()
```

Two backends with identical type + config share the same instance. This is critical for ChromaDB — one `PersistentClient` per persistence directory.

#### Concurrent Initialization Lock
The factory uses a per-key `asyncio.Lock` with double-check pattern to prevent race conditions when concurrent callers both miss the cache and try to create the same backend simultaneously. This is critical for Teradata — concurrent `create_context()` calls on the global teradataml singleton crash the SDK.

#### Key Entry Points

```python
# General-purpose: get or create any backend
async def get_backend(backend_type="chromadb", config=None) -> VectorStoreBackend

# Shared ChromaDB singleton (RAGRetriever calls this on startup)
async def get_default_chromadb_backend(persist_directory) -> ChromaDBBackend

# Resolve backend from collection metadata stored in tda_auth.db
async def get_backend_for_collection(coll_meta: dict) -> VectorStoreBackend

# Register a new backend class
def register_backend(backend_type: str, cls: Type[VectorStoreBackend]) -> None

# Clear instance cache (testing only)
def reset_instances() -> None
```

#### Resolution Flow for a Knowledge Collection
```
knowledge_routes.py
    └─ rag_retriever._get_knowledge_backend(collection_id)
           └─ collection_db.get_collection_by_id(collection_id)
                  → {backend_type: "chromadb", backend_config: "{}"}
           └─ factory.get_backend_for_collection(coll_meta)
                  → parse backend_type + backend_config
                  → _config_fingerprint(backend_type, config)
                  → _INSTANCES.get(fingerprint) or create + initialize + cache
```

---

## Concrete Backends

### ChromaDB Backend

**File:** [vectorstore/chromadb_backend.py](../../src/trusted_data_agent/vectorstore/chromadb_backend.py)

The default backend. Uses ChromaDB's `PersistentClient` (or in-memory client for tests). Wraps all sync ChromaDB calls in `asyncio.to_thread()`.

#### Capabilities (all 12 declared)
`CREATE_COLLECTION` · `DELETE_COLLECTION` · `ADD_DOCUMENTS` · `DELETE_DOCUMENTS` · `SIMILARITY_SEARCH` · `GET_BY_ID` · `COUNT` · `UPSERT` · `GET_BY_METADATA_FILTER` · `UPDATE_METADATA` · `EMBEDDING_PASSTHROUGH` · `GET_ALL`

#### Internal Collection Cache
```python
_coll_cache: Dict[str, chromadb.Collection]
```
Avoids repeated `client.get_collection()` round-trips. Populated via `register_collection()` (called by RAGRetriever) and evicted on `delete_collection()`.

#### Key Implementation Details

**Metadata sanitization** — ChromaDB rejects `None` values and complex types:
```python
def _sanitize_metadata(self, metadata: dict) -> dict:
    result = {}
    for k, v in metadata.items():
        if v is None:
            continue
        if isinstance(v, (list, dict)):
            result[k] = json.dumps(v)  # serialize to string
        else:
            result[k] = v
    return result
```

**Distance metric mapping:**
```python
COSINE      → "cosine"   (HNSW space)
EUCLIDEAN   → "l2"
DOT_PRODUCT → "ip"
```

**Result normalization** — ChromaDB returns nested lists; the backend flattens them:
```python
def _normalize_query_result(self, raw) -> QueryResult:
    return QueryResult(
        ids=raw["ids"][0],
        documents=raw["documents"][0] if raw["documents"] else [],
        metadatas=raw["metadatas"][0] if raw["metadatas"] else [],
        distances=raw["distances"][0] if raw["distances"] else [],
    )
```

**Migration bridge** — Exposes `raw_client` property and `register_collection()` / `evict_collection()` methods for code that predates the abstraction layer and holds a direct ChromaDB client reference.

---

### Teradata Backend

**File:** [vectorstore/teradata_backend.py](../../src/trusted_data_agent/vectorstore/teradata_backend.py)

Enterprise backend. Uses the `teradatagenai` Python SDK (`VectorStore` class) for ANN search and `teradataml` for staging-table SQL operations. Embedding is performed server-side via Amazon Bedrock or Azure OpenAI. Supports two ingestion paths: **client-side chunking** (staging table) and **server-side chunking** (SDK handles everything).

#### Two Ingestion Paths

**Client-Side Chunking** (default for all backends):
- Platform chunks documents locally (semantic/paragraph/sentence/fixed_size)
- Chunks inserted into a staging table, then ingested into VectorStore
- Full document management: browse, inspect, delete individual chunks

**Server-Side Chunking** (`SERVER_SIDE_CHUNKING` capability):
- Raw files (PDF, etc.) passed directly to `VectorStore.create(document_files=[...])`
- SDK handles chunking + embedding via Amazon Bedrock
- Simpler path, but no staging table — SDK manages data internally

#### Staging Table Design (Client-Side Path)

Each client-side-chunked collection has a companion Teradata table that provides document-level ID control (required for `DELETE_DOCUMENTS`, `GET_BY_ID`, and `COUNT`):

```sql
UDERIA_VS_<COLLECTION_NAME_UPPER> (
    CHUNK_ID      VARCHAR(512) NOT NULL,
    CONTENT       CLOB         NOT NULL,
    METADATA_JSON CLOB
) UNIQUE PRIMARY INDEX (CHUNK_ID)
```

The `VectorStore` is built from / updated via this staging table using `add_datasets()` and `delete_datasets()`. VectorStore creation is deferred to the first `add()` call (collections can be empty).

#### Server-Side Table Layout

Server-side chunked collections use SDK-managed tables with a different naming convention:

| Table | Naming Pattern | Purpose |
|---|---|---|
| Index table | `vectorstore_{collection_name}_index` | Embedding vectors + references |
| Chunks table | `chunks_table_{uuid}` | Content column (name varies by SDK version — detected dynamically), `TD_ID`, `TD_FILENAME` |

The chunks table name is a random UUID, discoverable from the index table's `TableName` column via `_resolve_chunks_table()`.

#### Capabilities (11 declared)
`CREATE_COLLECTION` · `DELETE_COLLECTION` · `ADD_DOCUMENTS` · `DELETE_DOCUMENTS` · `SIMILARITY_SEARCH` · `GET_BY_ID` · `GET_ALL` · `COUNT` · `UPSERT` · `SERVER_SIDE_EMBEDDING` · `SERVER_SIDE_CHUNKING`

#### Configuration
```json
{
    "host":             "54.156.178.22",
    "base_url":         "https://pmlakeprod.innovationlabs.teradata.com/api/accounts/<env-id>",
    "username":         "td_user",
    "password":         "td_pass",
    "pat_token":        "gwxhTfZg...",
    "pem_file":         "/path/to/td_user.pem",
    "database":         "TD_USER",
    "embedding_model":  "amazon.titan-embed-text-v1",
    "search_algorithm": "VECTORDISTANCE",
    "top_k":            10
}
```

| Field | Required | Description |
|---|---|---|
| `host` | Yes | Teradata database hostname (for `teradataml` direct SQL) |
| `base_url` | Yes | UES endpoint URL, aka `ues_uri` on JupyterHub (for `teradatagenai` VS REST API auth). Trailing `/open-analytics` is stripped automatically. |
| `username` | Yes | Teradata user (maps to `username` in JupyterHub `.env`) |
| `password` | Yes* | Teradata password (maps to `my_variable` in JupyterHub `.env`). Required for `create_context`. |
| `pat_token` | Yes* | PAT (Personal Access Token) generated from VantageCloud Lake Console (maps to `access_token` in JupyterHub `.env`). Used with `pem_file` for VS REST API auth. |
| `pem_file` | Yes* | Path to PEM private key file. **Critical:** the filename stem must match the `kid` (key ID) registered in VantageCloud Lake — typically the username (e.g., `td_user.pem`). Maps to `pem_file` in JupyterHub `.env`. |
| `database` | Yes | Target database for staging tables and VS data |
| `embedding_model` | No | Server-side embedding model (default: `amazon.titan-embed-text-v1`) |
| `search_algorithm` | No | VS search algorithm (default: `VECTORDISTANCE`) |
| `top_k` | No | Default result count for similarity search (default: `10`) |

\* Auth requires `password` for SQL context + either (`pat_token` + `pem_file`) or (`username` + `password`) for VS REST API. The PAT + PEM method is preferred and matches the official Getting Started pattern.

#### Authentication

Follows the VantageCloud Lake Getting Started pattern. Two connections are established sequentially at `initialize()`:

1. **`create_context(host, username, password)`** — opens a direct SQL connection for staging table management (`teradataml` global state). Must be called FIRST (SDK requirement).

2. **`set_auth_token(base_url, pat_token, pem_file)`** — authenticates with the Teradata Vector Store REST API (`teradatagenai` global state). The SDK generates a JWT signed with the PEM private key, using RS256 algorithm. The `kid` (key ID) in the JWT header is derived from `pathlib.Path(pem_file).stem`, so the **PEM filename must match** the registered key ID on VantageCloud Lake (typically the username).

```python
# Matches Getting Started cell [4] and [5]:
create_context(host=host, username=username, password=my_variable)

ues_uri = base_url
if ues_uri.endswith("/open-analytics"):
    ues_uri = ues_uri[:-len("/open-analytics")]
set_auth_token(base_url=ues_uri, pat_token=access_token, pem_file=pem_file)
```

**Fallback:** If no `pat_token` is provided, the backend falls back to Basic authentication: `set_auth_token(base_url, username, password)`.

#### Add / Delete Flow (Client-Side)

```
add(documents)
    ↓ insert rows → staging table (CHUNK_ID, CONTENT, METADATA_JSON)
    ↓ copy rows  → temp delta table
    ↓ if first add:  VectorStore.create(object_names=staging_table, key_columns=["CHUNK_ID"])
    ↓ else:          vs.add_datasets(data=delta_table, key_columns=["CHUNK_ID"])
    ↓ poll vs.status() until COMPLETED
    ↓ drop temp delta table

delete(ids)
    ↓ SELECT rows from staging table WHERE CHUNK_ID IN (ids)
    ↓ copy rows  → temp delete table
    ↓ vs.delete_datasets(data=delete_table, key_columns=["CHUNK_ID"])
    ↓ poll vs.status()
    ↓ DELETE FROM staging table WHERE CHUNK_ID IN (ids)
    ↓ drop temp delete table
```

#### Server-Side Chunking Flow

```
add_document_files(file_paths, chunking_config)
    ↓ VectorStore(collection_name)
    ↓ vs.create(document_files=file_paths, chunk_size=500, optimized_chunking=True, ...)
    ↓ poll vs.status() until COMPLETED (timeout 900s — PDF processing can take 5-10+ min)
    ↓ SDK creates chunks_table_{uuid} + vectorstore_{name}_index
    ↓ cache VS instance + register collection
```

#### Transparent Browse/Inspect for Both Paths

`count()` and `get()` transparently handle both client-side and server-side collections:

```
count(collection_name)
    ↓ _staging_count(UDERIA_VS_{name})
    ↓ if staging > 0 → return staging count
    ↓ else → _resolve_chunks_table() → count chunks_table_{uuid}

get(collection_name, limit, offset)
    ↓ query staging table (CHUNK_ID, CONTENT, METADATA_JSON)
    ↓ if staging has data → return staging rows
    ↓ else → _resolve_chunks_table() → SELECT * FROM chunks_table
    ↓ dynamic column detection: tries FILE_SPLITS, CHUNKS, CONTENT, REV_TEXT, TEXT (priority order)
    ↓ column mapping: TD_ID→id, {detected_content_col}→content, TD_FILENAME→metadata.filename
```

#### Connection Resilience

The `teradataml` library stores its database connection as a module-level global singleton. After idle periods (~10 min) or external SDK calls, the connection goes stale, causing failures like `AttributeError: 'NoneType' object has no attribute 'cursor'` or `OperationalError: N is not a valid connection pool handle`.

**Detection — `_is_connection_lost(exc)`:**

A static helper classifies exceptions as connection-loss indicators:

| Exception Type | Pattern Matched |
|---|---|
| `AttributeError` | `'NoneType'` + `'cursor'` in message |
| `OperationalError` | `"not a valid connection pool handle"`, `"socket"`, or `"connection"` in message |
| Any exception | `"not a valid connection pool handle"` in message (defensive fallback) |

**Reconnect — `_reconnect_all()`:**

Serialized via `asyncio.Lock` + monotonic timestamp to prevent thundering herd (multiple concurrent requests each detecting stale connections and calling `create_context()`, invalidating each other's fresh connections in a cascade):

```python
async def _reconnect_all(self) -> None:
    ts_before = time.monotonic()
    async with self._reconnect_lock:
        if self._last_reconnect_ts > ts_before:
            return  # Another coroutine already reconnected
        create_context(host, username, password, database=database)
        set_auth_token(pem_file=pem_path, base_url=base_url, access_token=pat_token)
        self._last_reconnect_ts = time.monotonic()
```

**SQL Wrapper — `_execute_sql(sql)`:**

All SQL operations go through this wrapper:
1. Attempts `execute_sql(sql)` via `asyncio.to_thread()`
2. On failure, checks `_is_connection_lost(exc)` — if not connection-related, re-raises immediately
3. If a VS operation is in progress (`_vs_operation_active`), skips reconnect and re-raises (to avoid invalidating the SDK's own connection mid-operation)
4. Calls `_reconnect_all()` (serialized, skip-if-recent)
5. Retries the exact same SQL once

**Query Resilience:**

The same pattern protects `query()`'s `similarity_search()` call, which doesn't use `execute_sql` but suffers from the same stale-connection issue. On connection loss: `_reconnect_all()` → re-acquire VectorStore handle via `_get_store()` (since the SDK object may be invalidated) → retry search once.

**Why not a connection probe?** An earlier approach used `SELECT 1` before every operation (`_ensure_connection`). This was unreliable — the connection could die between the probe and the actual query. The retry-at-failure wrapper catches the error at the exact point of failure.

#### Result Normalization — `_result_to_rows()`

`teradataml.execute_sql()` may return either a teradataml DataFrame (has `.to_pandas()`) or a raw `TeradataCursor` (has `.description` + `.fetchall()`). The static helper `_result_to_rows()` normalizes both to `List[dict]`, used throughout the backend.

#### Distance Convention
Teradata returns a similarity score (0–1, higher = closer). The backend converts to distance at the boundary to match `QueryResult`'s convention:
```python
distance = 1.0 - similarity_score
```

#### Known Limitations / TODOs
| Feature | Status |
|---|---|
| Metadata filter in `query()` | TODO — `where` filter logged as warning, results unfiltered |
| `UPDATE_METADATA` | `NotImplementedError` — no metadata-only update without re-embedding; use `delete()` + `add()` |
| `UPSERT` | Delegates to `add()` — Teradata key-column semantics provide upsert behaviour |
| `EMBEDDING_PASSTHROUGH` | Not supported — Teradata always embeds server-side |
| Deletion performance | O(n_deleted) — requires temp table creation, `delete_datasets`, and staging SQL |
| Server-side: delete by ID | Not available — no staging table for server-side collections |
| Server-side: add more docs | Not yet supported — would need `vs.add_datasets()` with file path |

#### Provider-Specific: Teradata Credential Management

This section documents the credential storage, runtime materialization, and connection testing patterns specific to the Teradata backend. These findings were discovered during the Vector Store Test Button implementation (March 2026).

##### Critical Discovery: PEM Filename → JWT Key ID (`kid`)

The `teradataml` SDK's `set_auth_token()` generates a JWT signed with the PEM private key using RS256. The JWT `kid` (key ID) header value is derived from **the PEM file's stem name**:

```python
# Inside teradataml SDK (not user code):
kid = pathlib.Path(pem_file).stem
# e.g., "/tmp/tda_vs_abc123.pem" → kid = "tda_vs_abc123" ← WRONG
# e.g., "/tmp/dir/test_user.pem"  → kid = "test_user"     ← CORRECT
```

The VantageCloud Lake server validates the `kid` against registered keys. If the filename doesn't match the key name registered in the Lake Console, authentication fails with `TDML_2412` even when the key content is byte-identical to a working file.

**Implication:** When storing PEM content in the database (rather than referencing a file path), the temp file created at runtime **must** be named `{key_name}.pem` where `key_name` matches the registered key in VantageCloud Lake Console. A random temp filename will always fail.

##### Credential Storage Architecture

Teradata credentials are stored encrypted in the `vectorstore_configurations` table using Fernet encryption (`encrypt_credentials` / `decrypt_credentials`). The stored credential fields:

| Field | Storage | Purpose |
|---|---|---|
| `username` | Encrypted | Teradata database user |
| `password` | Encrypted | Teradata database password |
| `pat_token` | Encrypted | Personal Access Token from Lake Console |
| `pem_content` | Encrypted | PEM private key content (full text, including headers) |
| `pem_key_name` | Encrypted | Key name registered in Lake Console (used for temp file naming) |

Non-sensitive configuration (`host`, `base_url`, `database`, `embedding_model`, etc.) is stored in plaintext `backend_config`.

##### Runtime PEM Materialization

When a `TeradataVectorBackend` instance is initialized with `pem_content` (no `pem_file` path):

```
initialize()
    ↓ Check: pem_content provided AND no pem_file path?
    ↓ Validate: pem_key_name is set (raise RuntimeError if missing)
    ↓ Create temp directory: tempfile.mkdtemp(prefix="tda_vs_")
    ↓ Write file: {tmpdir}/{pem_key_name}.pem
    ↓ Ensure trailing newline (PEM format requirement)
    ↓ Set self._pem_file = path to temp file
    ↓ Continue with normal set_auth_token(pem_file=...) flow

shutdown()
    ↓ If self._pem_tempfile is set:
    ↓   shutil.rmtree(temp_directory, ignore_errors=True)
    ↓   Clear self._pem_tempfile
```

This ensures the PEM content is only on disk for the duration of the backend's lifecycle.

##### Connection Test Flow (Test Before Save)

The platform enforces "test before save" for Teradata configurations. The test uses the abstraction layer directly — **not** the factory singleton — to avoid cache pollution:

```
UI: Test Connection button
    ↓ POST /v1/vectorstore/test-connection
    ↓ Body: { backend_type, backend_config, credentials }
    ↓ Merge credentials into backend_config
    ↓
_test_vectorstore_backend(backend_type, config)
    ↓ ChromaDB? → return success immediately (local, no connection)
    ↓ Validate: host, base_url, credentials present
    ↓ Instantiate TeradataVectorBackend(connection_config=config) directly
    ↓ await backend.initialize()  ← tests create_context + set_auth_token
    ↓ Return success with server_info
    ↓ finally: await backend.shutdown()  ← cleans up temp PEM + connections
```

**Why not use the factory?** The factory maintains a singleton cache keyed by config fingerprint. Test connections with potentially wrong credentials would pollute this cache, causing subsequent real connections to reuse a broken instance.

**Credential gating:** The create/update endpoints require `connection_tested: true` in the request body for Teradata configurations. The frontend tracks this flag and resets it whenever credential fields change.

##### Diagnostic Hints

When `set_auth_token` fails, the test endpoint appends diagnostic information:

- **Auth mode**: PAT token vs username/password
- **Base URL**: The endpoint being used (helps catch missing `/open-analytics` strip)
- **PEM status**: Whether PEM content was provided, and the key name being used

This aids troubleshooting since `TDML_2412` is a generic error that doesn't indicate which specific argument is invalid.

### Qdrant Cloud Backend

**File:** [vectorstore/qdrant_backend.py](../../src/trusted_data_agent/vectorstore/qdrant_backend.py)

Managed cloud vector database backend. Uses `AsyncQdrantClient` (native async — no `asyncio.to_thread()` wrapping needed) for all operations. Embedding is client-side via `SentenceTransformerProvider`, identical to ChromaDB. Supports optional gRPC transport for higher throughput.

#### ID Mapping

Qdrant requires point IDs to be valid UUIDs or unsigned 64-bit integers. Uderia document IDs are often compound strings (e.g. `f602a7e6-..._chunk_0_8aa7f63d`) that fail UUID parsing. The backend handles this transparently:

1. If the document ID is already a valid UUID, it is used as-is
2. Otherwise, a deterministic UUID5 is generated from the ID using a fixed namespace
3. The original ID is stored in the payload under `_uderia_id` for round-trip fidelity

Content is stored in the payload under `_content` (Qdrant has no native "document" concept).

#### Score-to-Distance Conversion

Qdrant returns similarity scores (higher = better). The backend converts to distances (lower = better) via `distance = 1.0 - score` for abstraction layer consistency with ChromaDB.

#### Scroll Pagination

Qdrant uses cursor-based pagination (point ID offset), not integer offset. For compatibility with the abstraction layer's integer offset interface, the backend uses a fetch-and-slice strategy: fetch `offset + limit` points, then slice the result.

#### Capabilities (12 declared)

`CREATE_COLLECTION` · `DELETE_COLLECTION` · `ADD_DOCUMENTS` · `DELETE_DOCUMENTS` · `SIMILARITY_SEARCH` · `GET_BY_ID` · `COUNT` · `UPSERT` · `GET_BY_METADATA_FILTER` · `UPDATE_METADATA` · `EMBEDDING_PASSTHROUGH` · `GET_ALL`

#### Configuration

```json
{
    "url":          "https://xxx.cloud.qdrant.io:6333",
    "api_key":      "xxx",
    "prefer_grpc":  false,
    "timeout":      30
}
```

| Field | Required | Description |
|---|---|---|
| `url` | Yes | Qdrant Cloud cluster URL (HTTPS) |
| `api_key` | Yes | API key from Qdrant Cloud dashboard |
| `prefer_grpc` | No | Use gRPC transport for data operations (default: `false`). ~2-3x faster for bulk operations. |
| `timeout` | No | Client timeout in seconds (default: `30`) |

---

## Integration Points

### Collection Database Schema

**File:** [core/collection_db.py](../../src/trusted_data_agent/core/collection_db.py)

The `collections` table in `tda_auth.db` stores per-collection backend metadata:

```sql
ALTER TABLE collections ADD COLUMN backend_type   TEXT DEFAULT 'chromadb';
ALTER TABLE collections ADD COLUMN backend_config TEXT DEFAULT '{}';
```

All CRUD functions (`get_collection_by_id`, `create_collection`, `get_user_owned_collections`) include these fields in their return values, making backend resolution transparent to callers.

---

### RAGRetriever Integration

**File:** [agent/rag_retriever.py](../../src/trusted_data_agent/agent/rag_retriever.py)

RAGRetriever manages the lifecycle bridge between the legacy ChromaDB client and the new abstraction layer.

#### Startup Seeding (prevents duplicate connections)
```python
async def _init_chromadb_backend_singleton(self):
    """Pre-seed factory with RAGRetriever's existing ChromaDB client."""
    backend = ChromaDBBackend(persist_directory=self.persist_dir)
    backend._client = self.client          # inject existing client
    backend._initialized = True
    # Register under same fingerprint factory would compute
    _INSTANCES[fingerprint] = backend
```

This ensures the factory and RAGRetriever share one `PersistentClient` rather than opening two connections to the same database file.

#### Per-Collection Backend Cache
```python
_knowledge_backends: Dict[int, VectorStoreBackend]

async def _get_knowledge_backend(collection_id: int) -> VectorStoreBackend:
    if collection_id in self._knowledge_backends:
        return self._knowledge_backends[collection_id]

    coll_meta = await collection_db.get_collection_by_id(collection_id)
    backend = await get_backend_for_collection(coll_meta)

    # For ChromaDB: register already-loaded collection in backend's cache
    if backend.backend_type == "chromadb" and collection_name in self.collections:
        backend.register_collection(collection_name, self.collections[collection_name])

    self._knowledge_backends[collection_id] = backend
    return backend
```

#### Complete Data Flow for Knowledge Repository Query
```
User Query
    │
    ▼
knowledge_routes.py  ──► rag_retriever._get_knowledge_backend(id)
                                │
                      ┌─────────▼──────────┐
                      │  _knowledge_backends │  hit → return cached
                      └─────────────────────┘
                                │ miss
                                ▼
                      collection_db.get_collection_by_id()
                                │
                                ▼
                      factory.get_backend_for_collection()
                                │
                    ┌───────────┴───────────┐
                    │                       │
               chromadb              teradata
            (singleton)           (new instance)
                    │                       │
                    └───────────┬───────────┘
                                ▼
                      backend.query(collection, text, n, filter)
                                │
                                ▼
                          QueryResult
```

---

### Knowledge Routes

**File:** [api/knowledge_routes.py](../../src/trusted_data_agent/api/knowledge_routes.py)

Routes use the abstraction layer exclusively. Legacy ChromaDB-style `where` dicts are bridged via `from_chromadb_where()`:

```python
from trusted_data_agent.vectorstore import FieldFilter, FilterOp, from_chromadb_where

backend = await rag_retriever._get_knowledge_backend(collection_id)

# Convert any legacy filter format
metadata_filter = from_chromadb_where(where_dict) if where_dict else None

result = await backend.query(
    collection_name=collection_name,
    query_text=user_query,
    n_results=10,
    where=metadata_filter,
    include_documents=True,
    include_metadata=True,
)

for doc_id, document, metadata, distance in zip(
    result.ids, result.documents, result.metadatas, result.distances
):
    similarity = 1.0 - distance
    ...
```

---

### Repository Constructor

**File:** [agent/repository_constructor.py](../../src/trusted_data_agent/agent/repository_constructor.py)

Knowledge repository population uses `VectorStoreBackend.add()` via the abstraction layer. Planner repositories retain direct ChromaDB client calls for backward compatibility (migration pending).

```python
async def construct_async(backend: VectorStoreBackend):
    docs = [
        VectorDocument(id=doc_id, content=text, metadata=metadata)
        for doc_id, text, metadata in chunk_data
    ]
    count = await backend.add(
        collection_name=collection_name,
        documents=docs,
        embedding_provider=provider,  # None for server-side embedding
    )
```

---

### Collection Import / Export

**File:** [core/collection_utils.py](../../src/trusted_data_agent/core/collection_utils.py)

Export and import operations are backend-agnostic. The `backend_type` field travels with the exported ZIP so collections round-trip to the correct backend:

```python
# Export: write backend_type into collection_metadata.json
metadata = {
    "backend_type": collection["backend_type"],
    ...
}

# Import: resolve backend from metadata
coll_stub = {"backend_type": metadata["backend_type"], "backend_config": "{}"}
backend = await get_backend_for_collection(coll_stub)

# Batch add (5,000 documents per batch)
await backend.add(collection_name, batch_docs, embedding_provider)
```

Both legacy `documents.json` (single JSON array) and current `documents.jsonl` (newline-delimited JSON) are supported on import.

---

### Frontend

**File:** [static/js/handlers/knowledgeRepositoryHandler.js](../../static/js/handlers/knowledgeRepositoryHandler.js)

The repository management UI surfaces the backend type on each repository card:

```javascript
// Badge helper
function _knowledgeBackendBadge(backendType) {
    const labels = { chromadb: "ChromaDB", teradata: "Teradata" };
    return `<span class="backend-badge">${labels[backendType] ?? backendType}</span>`;
}

// Create dialog: backend selection
const backendType = document.getElementById("createKnowledgeBackendType").value;
// Submitted as backend_type field in create request body
```

---

## Data Flow Diagrams

### Write Path — Adding Documents to a Knowledge Repository

#### Client-Side Chunking (ChromaDB default, Teradata optional)
```
User uploads documents via UI
         │
         ▼
POST /api/v1/knowledge/collections/{id}/documents
         │
         ▼
repository_constructor.construct_async(backend)
         │
    chunk document locally (semantic/paragraph/sentence/fixed_size)
         │
         ▼
[VectorDocument(id, content, metadata), ...]
         │
         ▼
backend.add(collection_name, documents, embedding_provider)
         │
    ┌────┴────────────────────────────────────────────┐
    │ ChromaDB                                         │ Teradata
    │   SentenceTransformerProvider                    │   ServerSideEmbeddingProvider
    │   → client-side SentenceTransformer embedding    │   → pass text only to TDVectorStore
    │   → store vectors in PersistentClient            │   → Bedrock/Azure embeds server-side
    │                                                  │   → stored in Teradata table
    └────┴────────────────────────────────────────────┘
         │
    return document count
```

#### Server-Side Chunking (Teradata only)
```
User uploads PDF via UI (chunking_strategy = "server_side")
         │
         ▼
POST /api/v1/knowledge/collections/{id}/documents (streaming)
         │
    save temp file
         │
         ▼
backend.add_document_files(collection_name, [temp_file], chunking_config)
         │
         ▼
VectorStore.create(document_files=[file], chunk_size=500, optimized_chunking=True, ...)
         │
    SDK handles: text extraction → chunking → embedding (Bedrock) → storage
         │
    poll vs.status() until COMPLETED (up to 15 min)
         │
    SDK creates: chunks_table_{uuid} + vectorstore_{name}_index
         │
    return file count
```

### Read Path — Similarity Search

```
Agent submits knowledge query
         │
         ▼
rag_retriever.retrieve_knowledge(query, collection_id)
         │
         ▼
_get_knowledge_backend(collection_id)
         │
    [cached or resolve via factory]
         │
         ▼
backend.query(collection_name, query_text, n_results, where)
         │
    ┌────┴────────────────────────────────────────────┐
    │ ChromaDB                                         │ Teradata
    │   asyncio.to_thread(collection.query)            │   store.similarity_search()
    │   → client-side embed query text                 │   → server-side embed query
    │   → HNSW ANN search                              │   → ANN search in Teradata
    │   → normalize nested lists → QueryResult         │   → convert score to distance
    └────┴────────────────────────────────────────────┘
         │
    QueryResult(ids, documents, metadatas, distances)
         │
         ▼
Agent synthesizes retrieved documents
```

---

## Adding a New Backend

### Step 1 — Implement the Backend Class

```python
# src/trusted_data_agent/vectorstore/mystore_backend.py
from typing import List, Optional, Set
from .base import VectorStoreBackend
from .capabilities import VectorStoreCapability, REQUIRED_CAPABILITIES
from .types import (
    CollectionConfig, CollectionInfo, DistanceMetric,
    GetResult, QueryResult, VectorDocument,
)
from .filters import MetadataFilter
from .embedding_providers import EmbeddingProvider

class MyStoreBackend(VectorStoreBackend):

    def __init__(self, connection_config: dict):
        self._config = connection_config
        self._client = None

    @property
    def backend_type(self) -> str:
        return "mystore"

    def capabilities(self) -> Set[VectorStoreCapability]:
        return REQUIRED_CAPABILITIES | {
            VectorStoreCapability.UPSERT,
            VectorStoreCapability.GET_BY_METADATA_FILTER,
        }

    async def initialize(self) -> None:
        self._client = MyStoreClient(**self._config)
        await self._client.connect()

    async def shutdown(self) -> None:
        if self._client:
            await self._client.close()

    async def create_collection(self, name: str, config: CollectionConfig) -> CollectionInfo:
        await self._client.create_index(name, ...)
        return CollectionInfo(name=name, count=0, backend_type=self.backend_type)

    async def query(self, collection_name: str, query_text: str,
                    n_results: int = 10, where: MetadataFilter = None,
                    include_documents: bool = True,
                    include_metadata: bool = True,
                    include_embeddings: bool = False) -> QueryResult:
        raw = await self._client.search(collection_name, query_text, n_results)
        return QueryResult(
            ids=[r.id for r in raw],
            documents=[r.text for r in raw],
            metadatas=[r.meta for r in raw],
            distances=[r.distance for r in raw],
        )

    # … implement remaining abstract methods
```

### Step 2 — Self-Register at Import Time

```python
# At the bottom of mystore_backend.py
def _register() -> None:
    from .factory import register_backend
    register_backend("mystore", MyStoreBackend)

_register()
```

### Step 3 — Trigger Registration via `__init__.py`

```python
# vectorstore/__init__.py — add import
from . import mystore_backend  # noqa: F401  (triggers _register())
```

### Step 4 — Add Frontend Support

In `knowledgeRepositoryHandler.js`, extend the `_knowledgeBackendBadge()` labels map and the backend selection dropdown to include the new type.

### Step 5 — (Optional) Add Embedding Provider

If the backend uses server-side embedding, return `ServerSideEmbeddingProvider` from `get_embedding_provider()`. If it needs a custom client-side model, subclass `EmbeddingProvider`.

---

## Design Decisions

### Bridge Pattern — ChromaDB Dual Access (by design)

ChromaDB-backed knowledge repos use **dual access**: both direct ChromaDB objects (`self.collections[id]`) and the abstraction layer (`self._knowledge_backends[id]`). Reads (queries, counts, listing) go direct; writes (upload, export, delete) go through the abstraction layer.

Non-ChromaDB backends (Teradata) use **single access**: exclusively through the abstraction layer. All 13 direct-ChromaDB code paths in `rag_retriever.py`, `routes.py`, `rest_routes.py`, and `auth_routes.py` are guarded by `_is_chromadb_backend()` checks and are unreachable for Teradata collections.

This is intentional — ChromaDB was the original implementation, and the abstraction layer was added around it for Teradata. Any future third backend would follow the Teradata pattern (fully abstracted).

### Async-First, Sync Backends Allowed
All interface methods are `async`. Sync backends adapt via `asyncio.to_thread()`. This keeps Quart's event loop unblocked regardless of backend choice.

### Singleton Factory with Config Fingerprinting
One backend instance per (type + config) combination. Config fingerprint = MD5 of sorted JSON. Prevents multiple `PersistentClient` connections to the same ChromaDB directory.

### Capability Negotiation over Feature Detection
Callers call `has_capability()` before using optional features. This is safer than `try/except NotImplementedError` and makes capability contracts explicit and documentable.

### Filter AST over Backend-Specific Dicts
Callers construct filter expressions with `eq()`, `and_()`, etc. Backends translate the AST to their native format. The `from_chromadb_where()` bridge allows legacy code to be adopted incrementally without a full rewrite.

### Distance Convention
All backends return distances (lower = closer), not similarity scores (higher = closer). Backends that natively return similarity scores convert at the boundary. This keeps all downstream code consistent.

### Embedding Providers as First-Class Objects
Passing `EmbeddingProvider` as an argument to `add()`/`upsert()` means:
- **Client-side embedding:** provider embeds before the call (SentenceTransformer)
- **Server-side embedding:** `ServerSideEmbeddingProvider` marker causes the backend to skip client inference
- **Pre-computed vectors:** `EMBEDDING_PASSTHROUGH` capability + `VectorDocument.embedding` field

### Teradata Object Ownership — EVS-Managed vs Platform-Managed

> **CRITICAL OPERATIONAL RULE:** Never use raw SQL DDL (`DROP TABLE`, `DROP VIEW`) on EVS-managed objects. Always use the EVS SDK (`vs.destroy()`) or the EVS REST API (`DELETE /data-insights/api/v1/vectorstores/<name>`).

The Teradata database contains objects owned by two different systems. Mixing up ownership and using the wrong deletion method causes **ghost dictionary entries** — objects that appear in `DBC.TablesV` but cannot be dropped, queried, or recreated. These ghost entries corrupt the entire database, blocking all future VectorStore creation with the error: *"Object not found. Please issue an object scan to update the dictionary."* Recovery requires DBA intervention (Teradata dictionary object scan) or a fresh database.

#### Object Ownership Map

| Object Pattern | Owner | Created By | Delete With | Raw SQL DDL? |
|---|---|---|---|---|
| `UDERIA_VS_<COLLECTION>` | **Platform** | `_ensure_staging_table()` | `DROP TABLE` | **Yes** — our table |
| `UDERIA_DELTA_<UUID>` | **Platform** | `add()` temp table | `DROP TABLE` | **Yes** — our temp table |
| `UDERIA_DEL_<UUID>` | **Platform** | `delete()` temp table | `DROP TABLE` | **Yes** — our temp table |
| `vectorstoreV_<name>` | **EVS Service** | `vs.create()` | `vs.destroy()` or EVS REST API | **NO** |
| `vectorstore_<name>_index` | **EVS Service** | `vs.create()` | `vs.destroy()` or EVS REST API | **NO** |
| `vectorstore_<name>_index_Embeddings` | **EVS Service** | `vs.create()` | `vs.destroy()` or EVS REST API | **NO** |
| `chunks_table_<uuid>` | **EVS Service** | `vs.create(document_files=...)` | `vs.destroy()` or EVS REST API | **NO** |
| `AWSEmbeddingsAuth` | **EVS Service** | `set_auth_token()` | Never — shared auth object | **NO** |

#### Correct Cleanup Methods

**For individual vector stores:**
```python
# Python SDK (preferred)
vs = VectorStore(name="my_vs_name")
vs.destroy()
vs.status()  # poll until DESTROYED
```

**For listing / bulk operations:**
```python
from teradatagenai import VSManager

VSManager.list()            # List all VS visible to current user
VSManager.list_sessions()   # Show active VS sessions
VSManager.disconnect()      # Disconnect all sessions (clear locks)
```

**REST API (for stuck VS or when SDK fails):**
```bash
# Delete a vector store
curl -X 'DELETE' \
    "$BASE_URL/data-insights/api/v1/vectorstores/<vs_name>" \
    -H "Authorization: Bearer $JWT" \
    -b session_cookie

# Check status after deletion
curl -X 'GET' \
    "$BASE_URL/data-insights/api/v1/vectorstores/<vs_name>" \
    -H "Authorization: Bearer $JWT" \
    -b session_cookie
```

#### Code Compliance

The `teradata_backend.py` implementation **follows this rule correctly**:

- `delete_collection()` uses `vs.destroy()` for the EVS VectorStore, then `DROP TABLE` only for the platform-owned staging table (`UDERIA_VS_*`)
- `add()` and `delete()` use `vs.create()` / `vs.add_datasets()` / `vs.delete_datasets()` for EVS operations, and raw SQL only for platform-owned temp tables (`UDERIA_DELTA_*`, `UDERIA_DEL_*`)
- No production code path ever runs `DROP TABLE`/`DROP VIEW` on `vectorstoreV_*`, `vectorstore_*_index*`, or `chunks_table_*` objects

#### Incident Reference (March 2026)

Manually running `DROP TABLE` / `DROP VIEW` on EVS-managed objects during an ad-hoc cleanup left 5 ghost dictionary entries (4 views + 1 table) that could not be dropped (`Error 3807: Object not found`). These ghosts blocked **all** new VectorStore creation in the database — even with completely new VS names that had no relation to the ghost objects. The EVS service (confirmed via `VSManager.list()`) showed zero vector stores for the user, yet creation consistently failed with *"Object not found. Please issue an object scan to update the dictionary."* The database had to be abandoned and replaced with a fresh ClearScape Experience environment.

---

## Known Limitations

| Area | Limitation | Workaround |
|---|---|---|
| Teradata metadata filters | Not translated to SQL WHERE | Filter post-retrieval in Python |
| Teradata `UPDATE_METADATA` | No metadata-only update without re-embedding | Delete + re-add document |
| Planner repositories | Still use direct ChromaDB client calls (not yet migrated) | Planned migration |
| Filter `IN` / `NOT_IN` | Not supported in all backends | Use multiple `eq` with `or_()` |
| Embedding dimension mismatch | No runtime check across backends | Specify model consistently per collection |
| Server-side: delete by ID | No staging table — SDK manages data internally | Use client-side chunking if per-chunk management needed |
| Server-side: add more docs | Not yet supported after initial create | Would need `vs.add_datasets()` with file path (future) |
| Server-side: chunk preview | Not available — preview requires local chunking | Upload directly; inspect after completion |
| VantageCloud Lake quota | Test environments have ~36 MB quota per AMP | Use smaller PDFs or production environments |
| EVS ghost dictionary entries | Raw SQL DDL on EVS objects corrupts dictionary, blocks all future VS creation | Never DROP EVS objects directly — use `vs.destroy()` or EVS REST API. See *Teradata Object Ownership* in Design Decisions |

---

## File Reference

| File | Purpose |
|---|---|
| [vectorstore/](../../src/trusted_data_agent/vectorstore/) | Core abstraction layer |
| [core/collection_db.py](../../src/trusted_data_agent/core/collection_db.py) | Collections table with `backend_type` / `backend_config` columns |
| [agent/rag_retriever.py](../../src/trusted_data_agent/agent/rag_retriever.py) | Backend lifecycle, ChromaDB singleton seeding, per-collection cache |
| [agent/repository_constructor.py](../../src/trusted_data_agent/agent/repository_constructor.py) | Knowledge repo population via VectorStoreBackend |
| [core/collection_utils.py](../../src/trusted_data_agent/core/collection_utils.py) | Backend-agnostic import/export with backend round-trip |
| [api/knowledge_routes.py](../../src/trusted_data_agent/api/knowledge_routes.py) | Knowledge search/upload routes using abstraction layer (client + server-side paths) |
| [static/js/handlers/knowledgeRepositoryHandler.js](../../static/js/handlers/knowledgeRepositoryHandler.js) | Frontend backend type badge, create dialog, server-side chunking toggle |
| [test/test_teradata_backend.py](../../test/test_teradata_backend.py) | 29 unit tests covering both ingestion paths, browse/inspect fallback, and capabilities |
| [test/test_qdrant_backend.py](../../test/test_qdrant_backend.py) | 41 unit tests covering ID hashing, lifecycle, collections, reads/writes, filter translation |
