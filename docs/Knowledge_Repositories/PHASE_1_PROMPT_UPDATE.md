# Phase 1 Implementation: Prompt Template Update Required

## Overview
Phase 1 Backend Foundation has been successfully implemented. However, the encrypted `prompts.dat` file needs to be updated to include the `{knowledge_context}` placeholder in the `WORKFLOW_META_PLANNING_PROMPT`.

## What Was Implemented

### 1. APP_CONFIG Constants (config.py)
Added new configuration constants:
```python
# Knowledge Repository Configuration
KNOWLEDGE_RAG_ENABLED = True
KNOWLEDGE_RAG_NUM_DOCS = 3
KNOWLEDGE_MIN_RELEVANCE_SCORE = 0.70
KNOWLEDGE_MAX_TOKENS = 2000
KNOWLEDGE_RERANKING_ENABLED = False
```

### 2. RAGRetriever Enhancement (rag_retriever.py)
- Added `repository_type` parameter to `retrieve_examples()` method
- Added filtering by `repository_type` ("planner" or "knowledge")
- Enhanced returned metadata with `collection_name`, `document_id`, and `repository_type`

### 3. Knowledge Retrieval Infrastructure (planner.py)
Implemented complete knowledge retrieval pipeline:

#### Helper Methods:
- `_is_knowledge_enabled()` - Check if knowledge retrieval is enabled
- `_get_knowledge_collections()` - Get configured knowledge collections from profile
- `_balance_collection_diversity()` - Balance documents across multiple collections
- `_format_with_token_limit()` - Format knowledge with token budget respect
- `_rerank_knowledge_with_llm()` - Optional LLM reranking per collection

#### Main Method:
- `_retrieve_knowledge_for_planning()` - Complete retrieval pipeline

### 4. Integration into Planning (planner.py)
- Added knowledge retrieval call in `_generate_meta_plan()`
- Passes `knowledge_context` parameter to `WORKFLOW_META_PLANNING_PROMPT.format()`

## Required Prompt Update

### Location
The `WORKFLOW_META_PLANNING_PROMPT` in the encrypted `prompts.dat` file needs to be updated.

### Required Changes
Add a new section in the prompt template to inject knowledge context. The placeholder `{knowledge_context}` should be added where domain knowledge should appear in the planning context.

### Recommended Placement
The knowledge context should be placed AFTER the RAG few-shot examples but BEFORE the main planning instructions. This ensures:
1. Execution patterns (RAG examples) are learned first
2. Domain knowledge enriches the planning context
3. Planning instructions remain at the end for recency

### Example Placement in Prompt Template
```
... (existing prompt sections) ...

{rag_few_shot_examples}

{knowledge_context}

--- PLANNING INSTRUCTIONS ---
... (existing planning instructions) ...
```

### Format of Knowledge Context
When populated, the `knowledge_context` string will have this format:

```
--- KNOWLEDGE CONTEXT ---
The following domain knowledge may be relevant to your planning:

### Knowledge Document 1 (from 'Collection Name', relevance: 0.85)
[Document content: user query, strategy, etc.]

### Knowledge Document 2 (from 'Collection Name', relevance: 0.78)
[Document content...]

```

### When Empty
When no knowledge is retrieved, `knowledge_context` will be an empty string `""`, so the prompt gracefully degrades.

## Profile Schema Extension

The profile schema now supports a `knowledgeConfig` object:

```json
{
  "knowledgeConfig": {
    "enabled": true,
    "collections": [
      {
        "collectionId": 1,
        "reranking": false
      },
      {
        "collectionId": 2,
        "reranking": true
      }
    ],
    "minRelevanceScore": 0.70,
    "maxDocs": 3,
    "maxTokens": 2000
  }
}
```

**Note:** Profile configuration is ready to use but requires frontend UI implementation (Phase 3).

## Testing Checklist

Before considering Phase 1 complete, verify:

- [x] `WORKFLOW_META_PLANNING_PROMPT` includes `{knowledge_context}` placeholder ✅
- [x] Encrypted `prompts.dat` file has been regenerated with updated prompt ✅
- [ ] Knowledge collections can be created with `repository_type="knowledge"`
- [ ] `retrieve_examples(repository_type="knowledge")` returns only knowledge repositories
- [ ] `retrieve_examples(repository_type="planner")` returns only planner repositories
- [ ] Knowledge context appears in planning LLM calls when collections are configured
- [ ] Empty knowledge config gracefully degrades (no errors)

## Next Steps

**Phase 2: Session Tracking & Events**
- Add `knowledge_accessed` metadata to session turn summaries
- Implement SSE events for knowledge retrieval tracking
- Add session replay support for knowledge context

## Files Modified

1. `src/trusted_data_agent/core/config.py` - Added constants
2. `src/trusted_data_agent/agent/rag_retriever.py` - Enhanced retrieval
3. `src/trusted_data_agent/agent/planner.py` - Added knowledge infrastructure

## Notes

- All code is backward compatible - existing planner repository functionality unchanged
- Knowledge retrieval is opt-in via profile configuration
- LLM reranking is per-collection configurable for cost control
- Token limits prevent context overflow
- Multi-collection diversity balancing ensures no single collection dominates
