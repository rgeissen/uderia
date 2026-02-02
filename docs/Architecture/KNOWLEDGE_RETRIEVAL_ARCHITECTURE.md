# Knowledge Retrieval Architecture

## Overview

The Knowledge Retrieval system powers the **Focus** profile class (`rag_focused`), delivering grounded, hallucination-free answers from verified documents. Unlike Planner Repositories that self-improve execution strategies, Knowledge Repositories serve as the organization's searchable institutional memory — policies, documentation, domain expertise, and reference materials accessible through natural language.

This document provides a comprehensive architectural deep-dive into the retrieval pipeline, scoring algorithms, configuration system, and integration points.

---

## Table of Contents

1. [Design Philosophy](#design-philosophy)
2. [Architecture Overview](#architecture-overview)
3. [Execution Flow](#execution-flow)
4. [Document Ingestion Pipeline](#document-ingestion-pipeline)
5. [Retrieval Pipeline](#retrieval-pipeline)
6. [Scoring Algorithms](#scoring-algorithms)
7. [Configuration System](#configuration-system)
8. [LLM Synthesis](#llm-synthesis)
9. [Multi-User Access Control](#multi-user-access-control)
10. [Event System](#event-system)
11. [Comparison: Knowledge vs Planner Repositories](#comparison-knowledge-vs-planner-repositories)
12. [Performance Characteristics](#performance-characteristics)
13. [Advanced Features](#advanced-features)
14. [Troubleshooting](#troubleshooting)
15. [File Reference](#file-reference)

---

## Design Philosophy

### Anti-Hallucination by Architecture

The Focus profile class enforces a strict retrieval-then-synthesize pattern:

1. **No general knowledge**: The LLM receives a system prompt instructing it to answer **only** from retrieved documents
2. **No tool calling**: The execution path bypasses the Planner/Executor entirely — no MCP tools, no strategic planning
3. **Transparent failure**: If no relevant documents are found, the system reports this honestly rather than fabricating an answer
4. **Source traceability**: Every synthesized answer carries citations back to specific document chunks and metadata

### Separation from Planner Repositories

The system maintains a clear architectural boundary between two repository types:

| Concern | Planner Repositories | Knowledge Repositories |
|---------|---------------------|----------------------|
| **Goal** | Improve agent execution over time | Ground answers in verified sources |
| **Profile Class** | Optimize (`tool_enabled`) | Focus (`rag_focused`) |
| **Data lifecycle** | Auto-captured from successful executions | Manually uploaded documents |
| **Consumer** | Strategic planner (few-shot examples) | LLM synthesis (direct context) |
| **Mutation** | System writes, user rates | User uploads, system indexes |
| **Metadata filters** | `strategy_type`, `is_most_efficient`, `user_feedback_score` | None (all chunks searchable) |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        KNOWLEDGE RETRIEVAL SYSTEM                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────────┐  │
│  │  Document  │    │  Repository  │    │   ChromaDB   │    │  Embedding  │  │
│  │  Upload    │───►│  Constructor │───►│  Collection  │◄───│   Model     │  │
│  │  (API)     │    │  (Chunking)  │    │  (Vectors)   │    │ MiniLM-L6   │  │
│  └───────────┘    └──────────────┘    └──────┬───────┘    └─────────────┘  │
│                                              │                              │
│                                              │ query()                      │
│                                              ▼                              │
│  ┌───────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────────┐  │
│  │  Profile   │───►│  Config      │───►│  RAG         │───►│  LLM        │  │
│  │  Config    │    │  Resolution  │    │  Retriever   │    │  Synthesis   │  │
│  │            │    │  (3-Tier)    │    │  (Scoring)   │    │  (Answer)    │  │
│  └───────────┘    └──────────────┘    └──────────────┘    └─────────────┘  │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Executor (rag_focused path)                                         │  │
│  │  - No planning, no tools                                             │  │
│  │  - Mandatory retrieval → LLM synthesis → answer with citations       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | File | Responsibility |
|-----------|------|----------------|
| **Executor** | `agent/executor.py` | Orchestrates the rag_focused execution path |
| **RAG Retriever** | `agent/rag_retriever.py` | Semantic search, scoring, deduplication |
| **Repository Constructor** | `agent/repository_constructor.py` | Document chunking and ChromaDB population |
| **Config Manager** | `core/config_manager.py` | Three-tier configuration resolution |
| **Knowledge Routes** | `api/knowledge_routes.py` | Document upload and collection management API |
| **Collection DB** | `core/collection_db.py` | ChromaDB client and collection lifecycle |

---

## Execution Flow

When a query arrives at a `rag_focused` profile, the executor follows a dedicated path that bypasses the Planner/Executor architecture entirely.

### Step-by-Step Flow

```
1. PROFILE DETECTION
   │  executor.py: _is_rag_focused_profile()
   │  Checks profile_type == "rag_focused"
   │
   ▼
2. CONFIGURATION RESOLUTION
   │  config_manager.py: get_effective_knowledge_config()
   │  Three-tier: Admin Lock → Profile Override → Global Default
   │  → maxDocs, minRelevanceScore, maxTokens, freshnessWeight, etc.
   │
   ▼
3. COLLECTION DISCOVERY
   │  executor.py: Extract knowledge collections from profile config
   │  Each collection has: collectionId, optional reranking flag
   │
   ▼
4. RETRIEVAL
   │  rag_retriever.py: retrieve_examples()
   │  For each accessible collection:
   │    → ChromaDB.query() with cosine similarity
   │    → Calculate similarity_score = 1 - distance
   │    → Calculate freshness_score = exp(-decay × days_old)
   │    → Calculate adjusted_score = blend(similarity, freshness)
   │    → Filter by minRelevanceScore
   │    → Apply maxChunksPerDocument deduplication
   │  Sort all results by adjusted_score descending
   │  Return top maxDocs results
   │
   ▼
5. OPTIONAL RERANKING
   │  executor.py: Per-collection LLM reranking if enabled
   │  Sends top candidates to LLM for relevance re-ordering
   │
   ▼
6. CONTEXT FORMATTING
   │  executor.py: Format documents into knowledge context string
   │  Respect maxTokens budget
   │  Include metadata (title, filename, source)
   │
   ▼
7. LLM SYNTHESIS
   │  llm/handler.py: call_llm_api()
   │  Input: system_prompt + knowledge_context + user_query
   │  System prompt: RAG_FOCUSED_EXECUTION or synthesisPromptOverride
   │  Output: Synthesized answer grounded in retrieved documents
   │
   ▼
8. RESPONSE FORMATTING
   │  Format HTML answer with source citations
   │  Include TTS payload
   │  Include knowledge source metadata
   │
   ▼
9. PERSISTENCE
   │  session_manager.py: Save to conversation history
   │  Update token counts (input + output)
   │  Emit workflow_history entry for turn replay
```

### What the Focus Profile Does NOT Do

Unlike `tool_enabled` profiles, the `rag_focused` path:
- Does **not** invoke the strategic planner
- Does **not** call MCP tools
- Does **not** execute tactical planning phases
- Does **not** save results as champion cases for future RAG
- Does **not** perform self-correction loops

This intentional simplicity ensures predictable, fast, grounded responses.

---

## Document Ingestion Pipeline

### Supported Document Formats

| Format | Handler | Notes |
|--------|---------|-------|
| PDF | PyPDF2 / pdfplumber | Text extraction with page-aware chunking |
| DOCX | python-docx | Preserves paragraph structure |
| TXT | Direct read | Plain text processing |
| Markdown | Direct read | Preserves heading structure |

### Upload Flow

```
1. Client uploads file via POST /api/v1/knowledge/collections/{id}/documents
   │
   ▼
2. DocumentUploadHandler.prepare_document_for_llm()
   │  - Extract text content from file format
   │  - Calculate content hash for deduplication
   │  - Extract metadata (title, author if available)
   │
   ▼
3. RepositoryConstructor.construct()
   │  - Apply chunking strategy
   │  - Generate embeddings for each chunk
   │  - Store chunks + embeddings in ChromaDB
   │  - Save original document to disk
   │
   ▼
4. Register in knowledge_documents table
   │  - document_id, filename, title, author
   │  - category, tags, content_hash
   │  - Link to collection_id
   │
   ▼
5. SSE progress events emitted to client
   │  - Chunk count, embedding progress
   │  - Final completion status
```

### Chunking Strategies

The `RepositoryConstructor` (`agent/repository_constructor.py`) supports four chunking strategies:

#### 1. Paragraph-Based (Default)

The recommended strategy for most documents. Respects natural paragraph boundaries while maintaining consistent chunk sizes.

**Algorithm:**
1. Split content on double newlines (`\n\n`)
2. Combine small paragraphs until reaching `chunk_size` (default: 1000 chars)
3. If a paragraph exceeds `chunk_size × 1.5`, split by sentence boundaries
4. If fewer than 3 paragraphs exist in a very large document, fall back to fixed-size

**Properties:**
- Preserves semantic coherence within chunks
- Adapts to document structure
- Handles edge cases (single massive paragraph, many tiny paragraphs)

#### 2. Sentence-Based

Splits content at sentence boundaries (regex: `(?<=[.!?])\s+`). Best for dense technical content where precision matters more than narrative flow.

#### 3. Fixed-Size

Character-count chunking with configurable overlap. The overlap ensures that information spanning a chunk boundary is captured in at least one chunk.

**Parameters:**
- `chunk_size`: Characters per chunk (default: 1000)
- `chunk_overlap`: Overlap between consecutive chunks (default: 200)

#### 4. Semantic

Boundary-aware splitting that attempts to detect topic shifts. Uses structural cues (headings, section breaks) to find natural split points.

### Chunk Metadata

Each chunk stored in ChromaDB carries metadata for filtering and scoring:

```json
{
  "collection_id": 37,
  "document_id": "doc_abc123",
  "chunk_index": 3,
  "chunk_method": "paragraph",
  "chunk_size": 847,
  "title": "Product Roadmap 2026",
  "author": "Engineering Team",
  "filename": "roadmap_2026.pdf",
  "category": "product",
  "tags": "roadmap,2026,features",
  "created_at": "2026-01-15T10:30:00+00:00",
  "source": "upload",
  "strategy_type": "knowledge"
}
```

### Embedding Model

Documents are embedded using **`all-MiniLM-L6-v2`** (384-dimensional vectors) via the `sentence-transformers` library. This model provides a strong balance of speed and quality for semantic similarity tasks.

ChromaDB stores both the embedding vectors and the original chunk text, enabling retrieval by semantic similarity with full content access.

---

## Retrieval Pipeline

### ChromaDB Query

The retriever (`rag_retriever.py`) queries each knowledge collection independently:

```python
query_results = collection.query(
    query_texts=[query],        # User's natural language question
    n_results=k * 10,           # Over-fetch for post-filtering
    where=None,                 # Knowledge repos: no metadata filter
    include=["metadatas", "distances", "documents"]
)
```

**Key design choice**: Knowledge repositories use `where=None` (no metadata filter), unlike planner repositories which filter on `strategy_type`, `is_most_efficient`, and `user_feedback_score`. This ensures all uploaded knowledge is searchable.

### Candidate Processing

For each result returned by ChromaDB:

```python
distance = query_results["distances"][0][i]
similarity_score = 1 - distance          # Convert cosine distance to similarity

if similarity_score < min_score:
    continue                              # Below relevance threshold

candidate = {
    "case_id": chunk_id,
    "collection_id": collection_id,
    "content": chunk_text,
    "similarity_score": similarity_score,
    "metadata": chunk_metadata,
    "document_id": metadata.get("document_id"),
    "strategy_type": "knowledge"
}
```

### Multi-Collection Retrieval

When a profile is configured with multiple knowledge collections, the retriever:

1. Queries each collection independently
2. Collects all candidates into a single list
3. Applies scoring, deduplication, and sorting across all collections
4. Returns the top `maxDocs` results regardless of which collection they came from

This means collections compete on merit — the most relevant chunks surface regardless of their source collection.

---

## Scoring Algorithms

### Hybrid Scoring: Relevance + Freshness

Knowledge documents use a blended scoring model that combines semantic relevance with temporal freshness:

```
adjusted_score = (1 - freshnessWeight) × similarity_score + freshnessWeight × freshness_score
```

Where:
- `similarity_score` = `1 - cosine_distance` (range: 0.0 to 1.0)
- `freshness_score` = `exp(-freshnessDecayRate × days_old)` (range: 0.0 to 1.0)
- `freshnessWeight` = configurable blend ratio (default: 0.0 = pure relevance)

### Freshness Decay Model

The freshness score uses exponential decay, providing a natural time-based penalty:

```
freshness_score = e^(-decay_rate × days_old)
```

**Decay curve with default rate (0.005):**

| Document Age | Freshness Score | Impact |
|-------------|----------------|--------|
| Today | 1.000 (100%) | Maximum freshness |
| 1 week | 0.966 (97%) | Negligible penalty |
| 1 month | 0.861 (86%) | Mild penalty |
| 3 months | 0.638 (64%) | Moderate penalty |
| 6 months | 0.407 (41%) | Significant penalty |
| 1 year | 0.161 (16%) | Heavy penalty |
| 2 years | 0.026 (3%) | Near-zero freshness |

**When no date is available**: The system assigns a default freshness score of `0.5` (neutral), ensuring undated documents are neither advantaged nor severely penalized.

### Scoring Examples

**Example 1: Pure relevance (freshnessWeight = 0.0)**
```
adjusted_score = (1.0 × 0.82) + (0.0 × 0.95) = 0.82
→ Only semantic similarity matters
```

**Example 2: Balanced (freshnessWeight = 0.3)**
```
Doc A: similarity=0.85, 10 days old → freshness=0.951
  adjusted = (0.7 × 0.85) + (0.3 × 0.951) = 0.595 + 0.285 = 0.880

Doc B: similarity=0.90, 200 days old → freshness=0.368
  adjusted = (0.7 × 0.90) + (0.3 × 0.368) = 0.630 + 0.110 = 0.740

→ Doc A wins despite lower raw similarity (it's much newer)
```

**Example 3: Heavy freshness bias (freshnessWeight = 0.7)**
```
Doc A: similarity=0.60, 2 days old → freshness=0.990
  adjusted = (0.3 × 0.60) + (0.7 × 0.990) = 0.180 + 0.693 = 0.873

Doc B: similarity=0.95, 365 days old → freshness=0.161
  adjusted = (0.3 × 0.95) + (0.7 × 0.161) = 0.285 + 0.113 = 0.398

→ Very recent doc dominates even with low relevance
```

### Contrast: Planner Repository Scoring

Planner repositories use a different scoring model based on execution efficiency:

```
adjusted_score = similarity_score - penalties

Where penalties:
  - had_tactical_improvements: -0.05 (5%)
  - had_plan_improvements: -0.05 (5%)
```

This penalizes cases that required self-correction, preferring strategies that executed cleanly on the first attempt.

### Per-Document Deduplication

After scoring, the system applies per-document chunk limits to prevent a single document from dominating results:

```python
if max_chunks_per_doc > 0:
    doc_chunk_count = {}
    for case in sorted_candidates:
        doc_id = case.get("document_id", case["case_id"])
        count = doc_chunk_count.get(doc_id, 0)
        if count < max_chunks_per_doc:
            kept.append(case)
            doc_chunk_count[doc_id] = count + 1
        # else: skip — this document already contributed enough chunks
```

**Use case**: When a 50-page document has 5 chunks matching the query, `maxChunksPerDocument=2` ensures other documents also get representation in the final results.

---

## Configuration System

### Three-Tier Resolution

Knowledge retrieval configuration follows a strict precedence hierarchy:

```
┌─────────────────────────────────────────────┐
│  1. ADMIN LOCK (highest priority)           │
│     Global setting with lock = true         │
│     → Always uses global value              │
│     → Profile overrides ignored             │
├─────────────────────────────────────────────┤
│  2. PROFILE OVERRIDE                        │
│     Profile's knowledgeConfig has value     │
│     → Uses profile-specific value           │
├─────────────────────────────────────────────┤
│  3. GLOBAL DEFAULT (lowest priority)        │
│     Global setting value                    │
│     → Used when no profile override exists  │
└─────────────────────────────────────────────┘
```

**Implementation** (`config_manager.py`):

```python
def get_effective_knowledge_config(self, profile_knowledge_config=None):
    global_settings = self.get_knowledge_global_settings()
    effective = {}

    for key, global_config in global_settings.items():
        global_value = global_config['value']
        is_locked = global_config['is_locked']

        if is_locked:
            effective[key] = global_value              # Admin enforced
        else:
            profile_value = profile_knowledge_config.get(key)
            if profile_value is not None:
                effective[key] = profile_value          # Profile override
            else:
                effective[key] = global_value           # Global default

    return effective
```

### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `maxDocs` | integer | 3 | Maximum documents returned after scoring and deduplication |
| `minRelevanceScore` | float | 0.30 | Minimum cosine similarity threshold (0.0–1.0). Chunks below this are discarded. |
| `maxTokens` | integer | 2,000 | Token budget for the formatted knowledge context sent to the LLM |
| `maxChunksPerDocument` | integer | 0 | Maximum chunks from any single source document. 0 = unlimited. |
| `freshnessWeight` | float | 0.0 | Blend ratio between relevance and freshness. 0.0 = pure relevance, 1.0 = pure freshness. |
| `freshnessDecayRate` | float | 0.005 | Exponential decay constant. Higher values penalize older documents more aggressively. |
| `synthesisPromptOverride` | string | "" | Custom system prompt for LLM synthesis. Replaces the default RAG_FOCUSED_EXECUTION prompt. |

### Profile Configuration Example

```json
{
  "profile_type": "rag_focused",
  "knowledgeConfig": {
    "enabled": true,
    "collections": [
      { "collectionId": 37, "reranking": false },
      { "collectionId": 38, "reranking": false }
    ],
    "maxDocs": 10,
    "minRelevanceScore": 0.25,
    "maxTokens": 8000,
    "maxChunksPerDocument": 2,
    "freshnessWeight": 0.3,
    "freshnessDecayRate": 0.005,
    "synthesisPromptOverride": "You are a domain expert. Answer using ONLY the provided documents..."
  }
}
```

### Tuning Guidelines

**For high-precision use cases** (compliance, legal, policy):
```
minRelevanceScore: 0.50    # Higher threshold, only very relevant docs
maxDocs: 5                  # Focused result set
freshnessWeight: 0.0        # Policy doesn't expire — pure relevance
maxChunksPerDocument: 1     # Diverse sources
```

**For broad knowledge bases** (product documentation, FAQ):
```
minRelevanceScore: 0.25    # Lower threshold to catch related content
maxDocs: 10                 # More documents for comprehensive answers
freshnessWeight: 0.3        # Prefer recent docs (product updates)
maxChunksPerDocument: 3     # Allow detailed coverage from key docs
```

**For time-sensitive content** (news, market intelligence, release notes):
```
minRelevanceScore: 0.30
maxDocs: 8
freshnessWeight: 0.5        # Strong freshness bias
freshnessDecayRate: 0.01    # Aggressive decay (6 months = 5% freshness)
maxChunksPerDocument: 2
```

---

## LLM Synthesis

### System Prompt

The Focus profile uses the `RAG_FOCUSED_EXECUTION` system prompt (stored encrypted in the database). This prompt instructs the LLM to:

1. Answer **exclusively** from the provided knowledge context
2. Cite sources with document titles and metadata
3. Acknowledge when the knowledge base doesn't contain sufficient information
4. Maintain conversational context from prior turns in the session

### Synthesis Prompt Override

Profiles can specify a `synthesisPromptOverride` to customize the LLM's behavior for domain-specific needs. This completely replaces the default system prompt.

**Use cases:**
- Enforce specific citation formats
- Require structured output (tables, bullet points)
- Add domain-specific instructions ("Always mention regulatory requirements")
- Control tone and formality

### Context Assembly

The LLM receives a message structured as:

```
[System Prompt]
  RAG_FOCUSED_EXECUTION (or synthesisPromptOverride)

[Knowledge Context]
  === Document 1 ===
  Title: Product Roadmap 2026
  Source: roadmap_2026.pdf
  ---
  [chunk content]

  === Document 2 ===
  Title: Technical Architecture Guide
  Source: architecture.md
  ---
  [chunk content]

  ... up to maxDocs documents, within maxTokens budget

[Conversation History]
  Previous turns in the session (if any)

[User Query]
  "What new features are planned for Q2?"
```

### Token Tracking

Token counts are extracted from the actual LLM response (not pre-estimated):

- **Input tokens**: System prompt + knowledge context + conversation history + user query
- **Output tokens**: LLM's synthesized answer

These counts are accumulated per-session and emitted as `token_update` events for the UI's real-time token counters.

---

## Multi-User Access Control

### Collection Visibility

Knowledge collections follow a multi-tenant access model:

| Visibility | Who Can Access |
|------------|---------------|
| **Private** | Owner only |
| **Unlisted** | Anyone with the collection ID |
| **Public** | All authenticated users |
| **Admin-owned** (owner_user_id = NULL) | All authenticated users |

### Access Resolution at Query Time

```python
def _get_user_accessible_collections(self, user_id):
    accessible = []
    for collection in all_collections:
        if collection.owner_user_id is None:          # Admin-owned
            accessible.append(collection.id)
        elif collection.owner_user_id == user_id:     # User owns it
            accessible.append(collection.id)
        elif collection.visibility in ["public", "unlisted"]:
            accessible.append(collection.id)
        elif has_active_subscription(user_id, collection.id):
            accessible.append(collection.id)          # Marketplace subscription
    return accessible
```

At query time, the retriever intersects the user's accessible collections with the profile's configured collection IDs, ensuring no unauthorized data leaks into results.

### Marketplace Integration

Collections published to the Intelligence Marketplace can be subscribed to by other users. Subscribed collections appear in the user's accessible set and can be assigned to their profiles.

---

## Event System

The Focus profile emits a specific set of events during execution, enabling real-time UI updates:

### Event Flow

```
execution_start
  │
  ▼
knowledge_retrieval_start
  │  → UI shows "Retrieving knowledge..."
  ▼
knowledge_retrieval_complete
  │  → UI shows retrieved document titles
  │  → UI updates knowledge banner
  ▼
conversation_llm_step (synthesis)
  │  → UI shows "Synthesizing answer..."
  │  → Token counts emitted
  ▼
token_update
  │  → UI updates token counters
  ▼
final_answer
  │  → UI renders answer with citations
  ▼
execution_complete
  │  → UI clears execution indicators
```

### Key Events

| Event | Payload | Purpose |
|-------|---------|---------|
| `execution_start` | `{ profile_type, profile_tag }` | Initialize UI execution state |
| `knowledge_retrieval_start` | `{ collection_count }` | Show retrieval indicator |
| `knowledge_retrieval_complete` | `{ results_count, documents[], sources[] }` | Populate knowledge panel |
| `conversation_llm_step` | `{ input_tokens, output_tokens, model }` | Token tracking |
| `token_update` | `{ total_input, total_output }` | Cumulative token counters |
| `final_answer` | `{ html, sources[], tts_payload }` | Render answer |
| `execution_complete` | `{ duration_ms, tokens }` | Cleanup UI state |

### Session UI Cache Integration

When a user switches away from a session with active knowledge retrieval, the full execution state (including knowledge banner, retrieved documents, token counters) is cached in `state.sessionUiCache`. Switching back restores the complete UI state without re-fetching from the server.

---

## Comparison: Knowledge vs Planner Repositories

| Aspect | Planner Repositories | Knowledge Repositories |
|--------|---------------------|----------------------|
| **Profile class** | Optimize (`tool_enabled`) | Focus (`rag_focused`) |
| **Purpose** | Self-improving execution strategies | Grounded document retrieval |
| **Data source** | Auto-captured execution traces | Uploaded documents (PDF, DOCX, TXT, MD) |
| **Storage format** | JSON case files on disk + ChromaDB | Chunks in ChromaDB only |
| **MCP server required** | Yes (tied to specific MCP server) | No |
| **Chunking** | None (full case as single document) | Paragraph / sentence / fixed-size / semantic |
| **Metadata filters** | `strategy_type=successful`, `is_most_efficient`, `user_feedback_score` | None (all chunks searchable) |
| **Scoring model** | Similarity - efficiency penalties | Hybrid similarity + freshness |
| **Tool execution** | Yes (full MCP tool calling) | None |
| **Self-correction** | Yes (retry loops with LLM guidance) | No |
| **RAG mining** | Yes (successful turns saved as cases) | No |
| **Reranking** | No | Optional LLM-based reranking per collection |
| **Typical token cost** | 8,000–15,000 input per turn | 3,000–5,000 input per turn |

---

## Performance Characteristics

### Typical Query Breakdown

| Operation | Input Tokens | Output Tokens | Latency |
|-----------|-------------|---------------|---------|
| Configuration resolution | — | — | <1ms |
| ChromaDB semantic search | — | — | 50–200ms |
| Scoring & deduplication | — | — | <10ms |
| LLM synthesis | 3,000–5,000 | 200–800 | 1–3s |
| **Total** | **3,000–5,000** | **200–800** | **1–4s** |

### Scaling Factors

- **Collection size**: ChromaDB handles millions of chunks with sub-second query times
- **Number of collections**: Each collection is queried independently; more collections = linear increase in query time
- **maxDocs**: Higher values increase LLM synthesis input tokens and cost
- **maxTokens**: Caps the context sent to LLM regardless of maxDocs
- **Document count**: ChromaDB's HNSW index maintains fast approximate nearest-neighbor search at scale

### Token Efficiency vs Other Profile Types

| Profile Type | Typical Input Tokens | Typical Output Tokens |
|-------------|---------------------|----------------------|
| Conversation (`llm_only`) | ~2,000 | 200–500 |
| **Knowledge (`rag_focused`)** | **~3,000–5,000** | **200–800** |
| Conversation with tools (`llm_only` + MCP) | ~3,000–4,000 | 200–500 |
| Optimizer (`tool_enabled`) | ~8,000–15,000 | ~1,000 |

---

## Advanced Features

### LLM-Based Reranking

When enabled per collection, the system performs a second-pass reranking using the LLM:

1. ChromaDB returns top candidates (quantity: `maxDocs × 3`)
2. Candidates are sent to the LLM with the original query
3. LLM scores each candidate for relevance
4. Results reordered by LLM relevance score
5. Top `maxDocs` returned

**Trade-off**: Improved relevance at the cost of an additional LLM call (typically 1,000–2,000 extra input tokens).

### Synthesis Prompt Override

Profiles can inject domain-specific synthesis instructions. This is particularly valuable for:

- **Multi-expert systems** (e.g., Virtual Account Team): Each expert profile gets a specialized prompt that shapes answer style, depth, and focus area
- **Compliance profiles**: Enforce specific citation and disclaimer formats
- **Multilingual use cases**: Instruct the LLM to respond in a specific language

### Session Context Continuity

The Focus profile maintains full session context across turns:

- **Turn 1**: "What products support AI workloads?" → Retrieves and synthesizes
- **Turn 2**: "Tell me more about the first one" → Uses conversation history to resolve "the first one", retrieves relevant chunks

The conversation history is included in the LLM synthesis call, enabling natural multi-turn interactions without losing context.

### No-Results Handling

When retrieval returns zero results above the minimum relevance threshold:

1. The system emits a `knowledge_retrieval_complete` event with empty results
2. A user-friendly message is generated (not an error)
3. The turn is still saved to conversation history
4. Token counts reflect only the system prompt + empty context overhead

This transparent failure mode prevents hallucination — the system never fabricates answers when it lacks supporting evidence.

---

## Troubleshooting

### No Results Returned

**Symptom**: Query returns "no relevant knowledge found" despite documents being uploaded.

**Checks**:
1. **Collection IDs**: Verify the profile's `knowledgeConfig.collections` references correct IDs. After cleanup/reimport, IDs change.
2. **Server restart**: The RAGRetriever loads collections into memory at startup. After creating new collections, the server must be restarted.
3. **minRelevanceScore**: A threshold of 0.50+ may be too restrictive. Try lowering to 0.25.
4. **Embedding mismatch**: Ensure documents were embedded with the same model used for queries (`all-MiniLM-L6-v2`).

### Wrong Documents Returned

**Symptom**: Retrieved documents seem irrelevant to the query.

**Checks**:
1. **Chunking strategy**: Very large chunks dilute semantic signal. Try smaller `chunk_size` or sentence-based chunking.
2. **freshnessWeight**: If set too high, old but relevant documents are penalized. Check if the returned docs are simply newer.
3. **maxChunksPerDocument**: If set to 0 (unlimited), one document with many chunks can dominate results.

### Freshness Scoring Not Working

**Symptom**: All documents have the same adjusted score regardless of age.

**Checks**:
1. **freshnessWeight = 0.0**: The default disables freshness scoring entirely. Set to 0.1+ to activate.
2. **Missing dates**: If `created_at` metadata is missing or malformed, the system assigns a neutral freshness score of 0.5.
3. **Date format**: Dates must be ISO 8601 format (e.g., `2026-01-15T10:30:00+00:00`). Truncated dates cause parsing failures.

### Configuration Not Taking Effect

**Symptom**: Profile overrides appear to be ignored.

**Checks**:
1. **Admin lock**: Check the global Knowledge Repository Configuration panel. If the lock checkbox is enabled for a parameter, the global value overrides all profile settings.
2. **Server restart**: Configuration changes to profiles require a server restart to take effect in the executor.
3. **Diagnostic logging**: Check server logs for `[Executor] Effective knowledge config:` to see what values are actually being used.

### High Token Cost

**Symptom**: Focus profile queries consume more tokens than expected.

**Optimization**:
1. Lower `maxDocs` (fewer documents = less context)
2. Lower `maxTokens` (caps context regardless of doc count)
3. Use `maxChunksPerDocument` to limit repetitive content from single sources
4. Increase `minRelevanceScore` to filter out marginally relevant chunks

---

## File Reference

| File | Key Lines | Description |
|------|-----------|-------------|
| `src/trusted_data_agent/agent/executor.py` | 2584–3390 | RAG-focused execution path |
| `src/trusted_data_agent/agent/executor.py` | 2638–2653 | Configuration parameter extraction |
| `src/trusted_data_agent/agent/executor.py` | 2693–2703 | Core retrieval call |
| `src/trusted_data_agent/agent/rag_retriever.py` | 1288–1345 | ChromaDB query and WHERE filter logic |
| `src/trusted_data_agent/agent/rag_retriever.py` | 1355–1452 | Scoring: similarity, freshness, adjusted |
| `src/trusted_data_agent/agent/rag_retriever.py` | 1454–1465 | Per-document deduplication |
| `src/trusted_data_agent/agent/rag_retriever.py` | 662–755 | Collection creation |
| `src/trusted_data_agent/agent/repository_constructor.py` | 40–312 | Chunking strategies |
| `src/trusted_data_agent/core/config_manager.py` | 2026–2068 | Three-tier config resolution |
| `src/trusted_data_agent/api/knowledge_routes.py` | 175–393 | Document upload API |
| `src/trusted_data_agent/core/collection_db.py` | — | ChromaDB client management |

---

*Last updated: February 2026*
