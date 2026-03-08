# Knowledge Retrieval Architecture

## Overview

The Knowledge Retrieval system powers the **Focus** profile class (`rag_focused`) and is also available as an optional capability for **Ideate** profiles (`llm_only`). It delivers grounded, hallucination-free answers from verified documents. Unlike Planner Repositories that self-improve execution strategies, Knowledge Repositories serve as the organization's searchable institutional memory — policies, documentation, domain expertise, and reference materials accessible through natural language.

This document provides a comprehensive architectural deep-dive into the retrieval pipeline, scoring algorithms, configuration system, vector store abstraction, and integration points.

> **Related Documentation:** [Vector Store Abstraction Architecture](VECTOR_STORE_ABSTRACTION_ARCHITECTURE.md) — backend interface, factory pattern, ChromaDB and Teradata implementations.

---

## Table of Contents

1. [Design Philosophy](#design-philosophy)
2. [Architecture Overview](#architecture-overview)
3. [Execution Flow](#execution-flow)
4. [Knowledge Retrieval for Ideate Profiles](#knowledge-retrieval-for-ideate-profiles)
5. [Vector Store Abstraction](#vector-store-abstraction)
6. [Document Ingestion Pipeline](#document-ingestion-pipeline)
7. [Retrieval Pipeline](#retrieval-pipeline)
8. [Scoring Algorithms](#scoring-algorithms)
9. [Configuration System](#configuration-system)
10. [LLM Synthesis](#llm-synthesis)
11. [Multi-User Access Control](#multi-user-access-control)
12. [Event System](#event-system)
13. [Comparison: Knowledge vs Planner Repositories](#comparison-knowledge-vs-planner-repositories)
14. [Performance Characteristics](#performance-characteristics)
15. [Advanced Features](#advanced-features)
16. [Troubleshooting](#troubleshooting)
17. [File Reference](#file-reference)

---

## Design Philosophy

### Anti-Hallucination by Architecture

The Focus profile class enforces a strict retrieval-then-synthesize pattern:

1. **No general knowledge**: The LLM receives a system prompt instructing it to answer **only** from retrieved documents
2. **No MCP tool calling**: The execution path bypasses the Planner/Executor entirely — no MCP tools, no strategic planning. *Exception*: When component tools (TDA_Charting, TDA_Canvas) are enabled on the profile, synthesis routes through `ConversationAgentExecutor`, allowing the LLM to visualize retrieved data. See [Agent-Based Synthesis](#agent-based-synthesis-with-component-tools).
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
│  │  Document  │    │  Repository  │    │ Vector Store │    │  Embedding  │  │
│  │  Upload    │───►│  Constructor │───►│   Backend    │◄───│  Provider   │  │
│  │  (API)     │    │  (Chunking)  │    │ (ChromaDB /  │    │ (Client or  │  │
│  └───────────┘    └──────────────┘    │  Teradata)   │    │  Server)    │  │
│                                        └──────┬───────┘    └─────────────┘  │
│                                               │                             │
│                                               │ query()                     │
│                                               ▼                             │
│  ┌───────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────────┐  │
│  │  Profile   │───►│  Config      │───►│  RAG         │───►│  LLM        │  │
│  │  Config    │    │  Resolution  │    │  Retriever   │    │  Synthesis   │  │
│  │            │    │  (3-Tier)    │    │  (Scoring)   │    │  (Answer)    │  │
│  └───────────┘    └──────────────┘    └──────────────┘    └─────────────┘  │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Executor (rag_focused + llm_only paths)                             │  │
│  │  - No planning, no MCP tools (component tools optional)              │  │
│  │  - Mandatory retrieval → LLM synthesis → answer with citations       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | File | Responsibility |
|-----------|------|----------------|
| **Executor** | `agent/executor.py` | Orchestrates rag_focused and llm_only knowledge paths |
| **RAG Retriever** | `agent/rag_retriever.py` | Semantic search, scoring, deduplication |
| **Repository Constructor** | `agent/repository_constructor.py` | Document chunking and vector store population |
| **Config Manager** | `core/config_manager.py` | Three-tier configuration resolution |
| **Knowledge Routes** | `api/knowledge_routes.py` | Document upload and collection management API |
| **Collection Utils** | `core/collection_utils.py` | Collection utility functions |
| **Vector Store Backend** | `vectorstore/base.py` | Abstract interface for vector store operations |
| **Vector Store Factory** | `vectorstore/factory.py` | Backend factory with singleton caching |
| **Conversation Agent** | `agent/conversation_agent.py` | Agent-based synthesis when component tools enabled |

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
- Does **not** call MCP tools (component tools like TDA_Charting are the exception — see [Agent-Based Synthesis](#agent-based-synthesis-with-component-tools))
- Does **not** execute tactical planning phases
- Does **not** save results as champion cases for future RAG
- Does **not** perform self-correction loops

This intentional simplicity ensures predictable, fast, grounded responses.

---

## Knowledge Retrieval for Ideate Profiles

Knowledge retrieval is not exclusive to `rag_focused` profiles. **Ideate** (`llm_only`) profiles can also enable knowledge retrieval via `knowledgeConfig.enabled = true`. This allows conversational profiles to ground their answers in verified documents while retaining their direct-conversation execution model.

### How It Works

When an `llm_only` profile has `knowledgeConfig.enabled = true`, the executor:

1. Detects knowledge is enabled from the profile configuration
2. Runs the **identical retrieval pipeline** as `rag_focused` (3-tier config, scoring, deduplication)
3. Formats retrieved documents into a knowledge context string
4. Injects the context into the LLM prompt alongside the conversation history
5. The LLM synthesizes an answer that blends knowledge documents with conversational context

```python
# executor.py — llm_only knowledge detection (line ~2833)
knowledge_config = profile_config.get("knowledgeConfig", {})
knowledge_enabled = knowledge_config.get("enabled", False)

if knowledge_enabled and self.rag_retriever:
    # Uses same retrieve_examples() pipeline as rag_focused
    all_results = await self.rag_retriever.retrieve_examples(
        query=self.original_user_input,
        repository_type="knowledge",
        ...
    )
```

### Key Differences from Focus Profiles

| Aspect | Focus (`rag_focused`) | Ideate with Knowledge (`llm_only`) |
|--------|----------------------|------------------------------------|
| **Primary purpose** | Document-grounded answers only | Conversational with optional grounding |
| **System prompt** | RAG_FOCUSED_EXECUTION (strict) | Standard conversation prompt + knowledge |
| **Component tools** | Optional via ConversationAgentExecutor | Optional via ConversationAgentExecutor |
| **MCP tools** | Never | Available if `useMcpTools = true` |
| **When no results found** | Reports "no relevant knowledge" | Falls back to general conversation |

### Configuration

The same `knowledgeConfig` structure applies to both profile types:

```json
{
  "profile_type": "llm_only",
  "knowledgeConfig": {
    "enabled": true,
    "collections": [
      { "collectionId": 37, "reranking": false }
    ],
    "maxDocs": 5,
    "minRelevanceScore": 0.30
  }
}
```

All configuration parameters, three-tier resolution, and admin locks work identically.

### Events

The `llm_only` knowledge path emits:
- `execution_start` with `knowledge_enabled: true` and `knowledge_collections` count
- `knowledge_retrieval` notification event (retrieval progress)
- Standard `conversation_llm_step` events (synthesis tokens)

---

## Vector Store Abstraction

Knowledge repositories are backed by a **pluggable vector store abstraction layer** (`src/trusted_data_agent/vectorstore/`). This allows collections to use different storage backends while presenting a unified async interface to the retrieval pipeline.

### Backends

| Backend | Type | Embedding | Capabilities |
|---------|------|-----------|-------------|
| **ChromaDB** | Local embedded | Client-side (SentenceTransformers) | 12 capabilities (default) |
| **Teradata** | Enterprise server | Server-side (Bedrock / Azure OpenAI) | 8 capabilities |

### Architecture

```
RAG Retriever
     │
     ▼
VectorStoreFactory.get_backend(backend_type, config)
     │
     ├── ChromaDB  → PersistentClient, client-side embedding
     └── Teradata  → REST API, server-side embedding
```

- **Factory pattern**: `vectorstore/factory.py` maintains singleton instances keyed by `(backend_type, config)` fingerprint (MD5 of sorted JSON)
- **Async-first**: All interface methods are `async`; ChromaDB wraps sync calls via `asyncio.to_thread()`
- **Capability negotiation**: Backends declare supported operations via `VectorStoreCapability` enum. Callers check `has_capability()` before attempting optional operations.
- **Per-collection backend**: Each collection stores its `backend_type` and `backend_config` in the `collections` table, allowing mixed backends within a single deployment

### Per-Collection Backend Resolution

```python
# factory.py — resolve backend from collection metadata
async def get_backend_for_collection(coll_meta) -> VectorStoreBackend:
    backend_type = coll_meta.get("backend_type", "chromadb")
    backend_config = json.loads(coll_meta.get("backend_config", "{}"))
    return await get_backend(backend_type, backend_config)
```

For a comprehensive deep-dive into the abstraction layer, see [Vector Store Abstraction Architecture](VECTOR_STORE_ABSTRACTION_ARCHITECTURE.md).

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

### Vector Store Query

The retriever (`rag_retriever.py`) queries each knowledge collection independently. For ChromaDB collections, the query goes directly via the ChromaDB client. For non-ChromaDB collections (e.g., Teradata), the query routes through the **Vector Store Abstraction Layer** (`vectorstore/factory.py`):

```python
# ChromaDB collections (default path) — rag_retriever.py:1677
query_results = collection.query(
    query_texts=[query],        # User's natural language question
    n_results=k * 10,           # Over-fetch for post-filtering
    where=None,                 # Knowledge repos: no metadata filter
    include=["metadatas", "distances", "documents"]
)

# Non-ChromaDB collections — rag_retriever.py:1756
backend = await get_backend_for_collection(coll_meta)
results = await backend.query(
    collection_name=coll_meta["collection_name"],
    query_text=query,
    n_results=k * 10,
    include_metadata=True
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

### Context Window Manager Budget Override

When the Context Window Manager is enabled (`APP_CONFIG.USE_CONTEXT_WINDOW_MANAGER`), the `maxTokens` parameter is subject to an additional budget constraint. The context window orchestrator allocates a token budget to the `knowledge_context` module during its five-pass assembly. This budget caps the effective `maxTokens`:

```python
# executor.py — CW budget override (line ~3536)
cw_knowledge_budget = getattr(self, '_cw_knowledge_max_tokens', None)
if cw_knowledge_budget:
    max_tokens = min(cw_knowledge_budget, max_tokens)
```

**Priority**: The lower of `maxTokens` (from configuration) and the CW module budget wins. This ensures knowledge context respects the overall context window allocation, preventing knowledge documents from crowding out conversation history or other modules.

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

### Agent-Based Synthesis with Component Tools

When a `rag_focused` (or `llm_only` with knowledge) profile has **component tools** enabled (e.g., TDA_Charting, TDA_Canvas), the synthesis step routes through `ConversationAgentExecutor` instead of a direct LLM call. This allows the LLM to invoke component tools during synthesis — for example, visualizing retrieved data as a chart.

```
Standard synthesis:     Knowledge Context → LLM → Answer
Agent-based synthesis:  Knowledge Context → LLM Agent → [TDA_Charting] → Answer + Chart
```

**Implementation** (`executor.py`, lines 4047-4080):

```python
rag_component_tools = get_component_langchain_tools(profile_id, user_uuid)

if rag_component_tools:
    # Agent-based synthesis — LLM can call component tools
    rag_agent = ConversationAgentExecutor(
        mcp_tools=rag_component_tools,
        knowledge_context=knowledge_context,
        profile_type="rag_focused",
        ...
    )
    agent_result = await rag_agent.execute(user_query)
else:
    # Standard direct LLM synthesis (no tools)
    response_text = await self._call_llm_and_update_tokens(prompt=user_message)
```

**Events emitted** by agent-based synthesis:
- `conversation_agent_start` with `profile_type: "rag_focused"` (branded as "Focus Agent" in UI)
- `conversation_llm_step` (per LLM call within the agent loop)
- `conversation_tool_invoked` / `conversation_tool_completed` (if component tools are called)
- `conversation_agent_complete` (final summary)

When the agent path is active, the executor skips emitting its own `rag_llm_step` and `tool_result` events to avoid duplication.

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

### RAGAccessContext

Access control is encapsulated in the `RAGAccessContext` class (`agent/rag_access_context.py`), which is passed to `retrieve_examples()` at query time:

```python
# executor.py — RAGAccessContext initialization (line ~3585)
from trusted_data_agent.agent.rag_access_context import RAGAccessContext
rag_context = RAGAccessContext(user_id=self.user_uuid, retriever=self.rag_retriever)

all_results = await self.rag_retriever.retrieve_examples(
    query=self.original_user_input,
    rag_context=rag_context,
    repository_type="knowledge",
    ...
)
```

The `RAGAccessContext` provides:
- **`accessible_collections`** (cached property): Set of collection IDs the user can read (owned + subscribed + public)
- **`validate_collection_access(collection_id, access_type)`**: Validates read or write access before operations
- **Caching**: Accessible collections are computed once per context and cached for the request lifecycle

### Marketplace Integration

Collections published to the Intelligence Marketplace can be subscribed to by other users. Subscribed collections appear in the user's accessible set and can be assigned to their profiles.

---

## Event System

Knowledge retrieval emits events for real-time UI updates. The event flow varies depending on the execution path.

### Standard Event Flow (Direct LLM Synthesis)

```
execution_start
  │  → { profile_type: "rag_focused", knowledge_enabled: true }
  ▼
knowledge_retrieval_start
  │  → UI shows "Retrieving knowledge..."
  ▼
knowledge_retrieval_complete
  │  → UI shows retrieved document titles
  │  → UI updates knowledge banner
  ▼
rag_llm_step (synthesis)
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

### Agent-Based Event Flow (Component Tools Active)

When component tools are enabled, the synthesis step emits agent events instead:

```
execution_start
  │
  ▼
knowledge_retrieval_start → knowledge_retrieval_complete
  │
  ▼
conversation_agent_start          ← "Focus Agent Started"
  │
  ├── conversation_llm_step       ← LLM call (may invoke tools)
  ├── conversation_tool_invoked   ← e.g., TDA_Charting called
  ├── conversation_tool_completed ← Tool result
  ├── conversation_llm_step       ← Follow-up LLM call
  │
  ▼
conversation_agent_complete       ← "Focus Agent Complete"
  │
  ▼
execution_complete
```

Note: When the agent path is active, `rag_llm_step` and `tool_result` events are **not** emitted by the executor (the agent's events replace them).

### Ideate Profile Event Flow (`llm_only` with Knowledge)

```
execution_start
  │  → { profile_type: "llm_only", knowledge_enabled: true }
  ▼
knowledge_retrieval (notification)
  │  → Retrieval progress
  ▼
conversation_llm_step (synthesis)
  │  → Token counts
  ▼
execution_complete
```

### Key Events

| Event | Payload | Purpose |
|-------|---------|---------|
| `execution_start` | `{ profile_type, profile_tag, knowledge_enabled, knowledge_collections }` | Initialize UI execution state |
| `knowledge_retrieval_start` | `{ collection_count }` | Show retrieval indicator |
| `knowledge_retrieval_complete` | `{ results_count, documents[], sources[] }` | Populate knowledge panel |
| `rag_llm_step` | `{ input_tokens, output_tokens, model, cost_usd }` | Token tracking (direct path only) |
| `conversation_agent_start` | `{ profile_type, available_tools[] }` | Agent start (component tools path) |
| `conversation_agent_complete` | `{ tools_used[], input_tokens, output_tokens, cost_usd }` | Agent complete (component tools path) |
| `token_update` | `{ total_input, total_output }` | Cumulative token counters |
| `final_answer` | `{ html, sources[], tts_payload }` | Render answer |
| `execution_complete` | `{ duration_ms, tokens }` | Cleanup UI state |

### Session UI Cache Integration

When a user switches away from a session with active knowledge retrieval, the full execution state (including knowledge banner, retrieved documents, token counters) is cached in `state.sessionUiCache`. Switching back restores the complete UI state without re-fetching from the server.

---

## Comparison: Knowledge vs Planner Repositories

| Aspect | Planner Repositories | Knowledge Repositories |
|--------|---------------------|----------------------|
| **Profile class** | Optimize (`tool_enabled`) | Focus (`rag_focused`) + Ideate (`llm_only` opt-in) |
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
| `src/trusted_data_agent/agent/executor.py` | 3471–4200 | RAG-focused execution path |
| `src/trusted_data_agent/agent/executor.py` | 2831–2867 | llm_only knowledge retrieval path |
| `src/trusted_data_agent/agent/executor.py` | 3531–3548 | Configuration parameter extraction + CW budget override |
| `src/trusted_data_agent/agent/executor.py` | 3585–3598 | RAGAccessContext initialization + retrieve_examples call |
| `src/trusted_data_agent/agent/executor.py` | 4047–4080 | ConversationAgentExecutor for component tools synthesis |
| `src/trusted_data_agent/agent/rag_retriever.py` | 1565–1814 | `retrieve_examples()` — full function with scoring and filtering |
| `src/trusted_data_agent/agent/rag_retriever.py` | 1677–1682 | ChromaDB query |
| `src/trusted_data_agent/agent/rag_retriever.py` | 1753–1809 | Non-ChromaDB (vector store abstraction) query path |
| `src/trusted_data_agent/agent/rag_access_context.py` | 22–100 | RAGAccessContext class — access control encapsulation |
| `src/trusted_data_agent/agent/conversation_agent.py` | 65–140 | ConversationAgentExecutor — agent-based synthesis |
| `src/trusted_data_agent/agent/repository_constructor.py` | 40–312 | Chunking strategies |
| `src/trusted_data_agent/core/config_manager.py` | 2197–2239 | Three-tier config resolution |
| `src/trusted_data_agent/core/collection_utils.py` | — | Collection utility functions |
| `src/trusted_data_agent/api/knowledge_routes.py` | 175–393 | Document upload API |
| `src/trusted_data_agent/vectorstore/base.py` | 31–150 | VectorStoreBackend abstract interface |
| `src/trusted_data_agent/vectorstore/factory.py` | 64–150 | Backend factory with singleton caching |
| `src/trusted_data_agent/vectorstore/capabilities.py` | — | VectorStoreCapability enum (8 capabilities) |
| `components/builtin/context_window/modules/knowledge_context/handler.py` | — | CW knowledge module (budget allocation) |

---

*Last updated: March 2026*
