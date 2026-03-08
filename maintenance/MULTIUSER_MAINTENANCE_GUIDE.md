# Multi-User RAG Maintenance Guide

## Overview

Phase 4 introduces multi-user support to the RAG system. This guide explains how the maintenance scripts and operations have been updated to support user isolation.

## Key Changes

### 1. User Attribution
All cases now include a `user_uuid` field in their metadata:
```json
{
  "metadata": {
    "user_uuid": "user-123",      // NEW: UUID of the user who created this case
    "user_query": "...",
    "collection_id": 0,
    "strategy_type": "successful"
  }
}
```

### 2. Collection Types

**Owned Collections** (user's personal collection):
- User sees only their own cases
- Query filter: `{"user_uuid": {"$eq": "user-uuid"}}`
- Example: Collection 0 for each user contains only that user's cases

**Subscribed Collections** (shared marketplace):
- User sees all cases from all creators
- Query filter: no user_uuid filtering
- Example: Collection 1 (marketplace) shows strategies from any user

**Public Collections**:
- Accessible to all users
- Read-only access
- No user_uuid filtering

### 3. Access Control

All RAG operations now use `RAGAccessContext` for access validation:

```python
from trusted_data_agent.agent.rag_access_context import RAGAccessContext

# Create context for a user
context = RAGAccessContext(user_uuid, retriever)

# Validate read access
context.validate_collection_access(collection_id, write=False)

# Validate write access (requires ownership)
context.validate_collection_access(collection_id, write=True)

# Build query filter with context
query_filter = context.build_query_filter(
    collection_id=0,
    strategy_type={"$eq": "successful"}
)
```

## Maintenance Operations

### 1. List Cases by User

See which user owns each case:

```bash
python3 maintenance/list_rag_cases_by_user.py
python3 maintenance/list_rag_cases_by_user.py --collection_id 0
python3 maintenance/list_rag_cases_by_user.py --user_id user-123
```

Output shows:
- Cases organized by user
- Cases without user_uuid (if any - these need migration)
- Collection breakdowns per user

### 2. Clean Vector Store

Existing `clean_vector_store.py` works unchanged - no user-specific logic needed:

```bash
python3 maintenance/clean_vector_store.py
```

Still syncs ChromaDB with case files on disk. User attribution is preserved through case metadata.

### 3. Delete Orphan Cases

Existing `delete_orphan_cases.py` works unchanged - user ownership is preserved:

```bash
python3 maintenance/identify_orphan_cases.py
python3 maintenance/delete_orphan_cases.py
```

Deletes orphan cases while maintaining user data integrity.

### 4. Reset ChromaDB

Reset utility unchanged - rebuilds from case files:

```bash
python3 maintenance/reset_chromadb.py
```

All user attribution data survives because it's in case JSON files, not ChromaDB.

## Important: Data Integrity Rules

### Before Operating on RAG Data

1. **Know the user context** - Which user's data are you modifying?
2. **Validate access** - Use RAGAccessContext to check permissions
3. **Preserve user_uuid** - Never remove or modify the user_uuid field
4. **Backup critical cases** - Before bulk operations, backup important user collections

### Safe Patterns

✅ **Safe**: Querying with RAGAccessContext
```python
context = RAGAccessContext(user_uuid, retriever)
context.build_query_filter(collection_id, **conditions)
```

✅ **Safe**: Reading case files to inspect metadata
```python
with open(case_file) as f:
    metadata = json.load(f)["metadata"]
    user_uuid = metadata.get("user_uuid")
```

✅ **Safe**: Deleting orphan cases (identifies by session, preserves user data)
```python
python3 maintenance/identify_orphan_cases.py
python3 maintenance/delete_orphan_cases.py
```

### Dangerous Patterns

❌ **Dangerous**: Direct ChromaDB operations without context
```python
# NO - bypasses access control
collection.delete(where={...})  # Could delete other users' data
```

❌ **Dangerous**: Modifying case JSON without preserving user_uuid
```python
# NO - loses user attribution
case_data["metadata"].pop("user_uuid")
```

❌ **Dangerous**: Assuming all cases in a collection belong to one user
```python
# NO - subscribed collections have cases from multiple users
for case in all_cases:
    case_owner = case["metadata"]["user_uuid"]  # Verify, don't assume
```

## Scenarios

### Scenario 1: Audit Cases for a Specific User

```bash
python3 maintenance/list_rag_cases_by_user.py --user_id user-123
```

Shows all cases created by user-123 across all collections.

### Scenario 2: Find Cases Without User Attribution

```bash
python3 maintenance/list_rag_cases_by_user.py
```

Look for "Cases WITHOUT User Attribution" section. These should not exist in production (Phase 2 cleaned them).

### Scenario 3: Recover from Corrupted Vector Store

Vector store corruption doesn't affect user data:

```bash
# 1. Reset ChromaDB (removes corrupted index)
python3 maintenance/reset_chromadb.py

# 2. Start application
# The system will rebuild the vector index from your case JSON files
# All user attribution data is preserved
```

### Scenario 4: Backup User's Cases

```python
import json
from pathlib import Path

user_uuid = "user-123"
backup_dir = Path("backups") / user_uuid
backup_dir.mkdir(parents=True, exist_ok=True)

# Find all case files for this user
rag_cases_dir = Path("rag/tda_rag_cases")
for case_file in rag_cases_dir.rglob("case_*.json"):
    with open(case_file) as f:
        case = json.load(f)
    
    if case.get("metadata", {}).get("user_uuid") == user_uuid:
        # Backup this case
        target = backup_dir / case_file.name
        target.write_text(case_file.read_text())
        print(f"Backed up: {case_file.name}")
```

## Troubleshooting

### Issue: Cases appear in wrong user's retrieval

**Cause**: Case doesn't have proper `user_uuid` in metadata

**Fix**:
1. Identify the case file
2. Add user_uuid to metadata:
```python
import json
case_file = Path("rag/tda_rag_cases/collection_0/case_abc.json")
case = json.load(open(case_file))
case["metadata"]["user_uuid"] = "correct-user-uuid"
json.dump(case, open(case_file, 'w'), indent=2)
```
3. Reset ChromaDB: `python3 maintenance/reset_chromadb.py`

### Issue: User can't see their own cases

**Cause**: Collection not properly set up as "owned"

**Fix**:
1. Verify collection ownership in database:
```sql
SELECT id, owner_user_id FROM rag_collections WHERE id = 0;
```
2. If owner_user_id is wrong, update it
3. Verify case has matching user_uuid:
```bash
python3 maintenance/list_rag_cases_by_user.py --collection_id 0
```

### Issue: Subscribed collection shows wrong cases

**Cause**: user_uuid filter being applied to subscribed collection

**Fix**:
1. Verify RAGAccessContext is properly determining access type
2. Check get_access_type() returns "subscribed" for the collection
3. Verify query_filter doesn't include user_uuid for subscribed access

## Monitoring

### Health Check Script

```python
# maintenance/health_check_multiuser_rag.py
# (Create this if needed)

def verify_multiuser_health():
    """Verify multi-user RAG system is healthy"""
    
    # 1. All cases have user_uuid
    # 2. User_uuid values are valid UUIDs
    # 3. Cases are properly isolated by collection type
    # 4. Access context functions work correctly
    
    pass
```

## Summary

The multi-user RAG system maintains backward compatibility while adding user isolation:

- **Backward Compatible**: Existing maintenance scripts still work
- **User-Aware**: All operations respect user ownership and access rules
- **Safe**: RAGAccessContext prevents unauthorized access
- **Observable**: New list_rag_cases_by_user.py provides visibility
- **Recoverable**: User data survives vector store corruption

Always use RAGAccessContext when implementing new maintenance operations!
