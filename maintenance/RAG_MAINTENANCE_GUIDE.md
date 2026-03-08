# RAG Case Maintenance Summary

## Overview
The RAG case maintenance scripts help keep your case studies and vector store in sync with active sessions.

## Scripts

### 1. `identify_orphan_cases.py`
**Purpose**: Identifies RAG cases that don't have associated sessions.

**What it does**:
- Scans all session files (including archived ones)
- Scans all RAG case files across all collections
- Identifies orphan cases (cases whose sessions no longer exist)
- **Preserves intentional orphans** (cases created through batch population)

**Preservation Rules**:
Cases with the following session IDs are preserved and NOT marked for deletion:
- `00000000-0000-0000-0000-000000000000` - Batch-populated examples

**Output**:
- Console report showing:
  - Total cases
  - Cases with valid sessions
  - Preserved cases (intentional orphans)
  - Deletable orphan cases
- Creates `orphan_cases.json` with details of deletable orphans

**Usage**:
```bash
python3 maintenance/identify_orphan_cases.py
```

### 2. `delete_orphan_cases.py`
**Purpose**: Deletes orphan case files identified by the identification script.

**What it does**:
- Reads the `orphan_cases.json` file
- **Double-checks** for preserved session IDs before deletion
- Asks for confirmation before deletion
- Deletes only the orphan case JSON files
- Reports deletion results

**Safety Features**:
- Only deletes cases identified as deletable orphans
- **Extra safety check**: Filters out preserved session IDs even if they appear in orphan_cases.json
- Preserves intentional orphans (batch-populated examples with session_id='00000000-0000-0000-0000-000000000000')
- Requires explicit confirmation
- Shows protected cases during execution

**Usage**:
```bash
python3 maintenance/delete_orphan_cases.py
```

### 3. `clean_vector_store.py`
**Purpose**: Cleans up the ChromaDB vector store to match disk files.

**What it does**:
- Connects to ChromaDB
- For each collection, compares vector store entries with disk files
- Removes vector store entries for cases that no longer exist on disk
- Syncs vector store with current case files

**Usage**:
```bash
# Run with conda environment that has chromadb installed
conda run -n mcp python maintenance/clean_vector_store.py
```

## Workflow

### Regular Cleanup (Removing Orphaned Cases)

1. **Identify orphans**:
   ```bash
   python3 maintenance/identify_orphan_cases.py
   ```
   Review the output to see:
   - Preserved cases (will NOT be deleted)
   - Deletable orphans (from deleted sessions)

2. **Delete orphan files** (if desired):
   ```bash
   python3 maintenance/delete_orphan_cases.py
   ```
   Confirm deletion when prompted.

3. **Clean vector store**:
   ```bash
   conda run -n mcp python maintenance/clean_vector_store.py
   ```
   This removes orphan entries from ChromaDB.

## When Sessions are Archived

The new session archiving feature (implemented 2025-11-23) marks sessions as `archived: true` instead of deleting them. This means:

- Archived sessions remain on disk
- Their associated RAG cases are NOT orphaned
- No cleanup is needed for archived sessions
- Cases remain available for RAG retrieval

## Preserved Cases

Cases that are intentionally created without sessions (preserved orphans):

- **Session ID**: `00000000-0000-0000-0000-000000000000`
- **Purpose**: Batch-populated examples, template cases
- **Collection**: Typically in collection_1
- **Behavior**: Never marked for deletion, always preserved

## Best Practices

1. **Before cleanup**: Always run `identify_orphan_cases.py` first to see what will be deleted
2. **Review preserved cases**: Ensure intentional orphans are properly marked
3. **Backup important cases**: Consider backing up before mass deletion
4. **Clean vector store**: After deleting case files, clean the vector store
5. **Regular maintenance**: Run cleanup periodically to keep storage clean

## Recent Changes (2025-11-23)

- ✅ Implemented session archiving (soft delete)
- ✅ Added preserved case identification
- ✅ Protected batch-populated examples from deletion
- ✅ Created vector store cleanup script
- ✅ Cleaned up 54 orphan cases from deleted sessions

## Current Status

- **Total RAG cases**: 49
- **Cases with valid sessions**: 49
- **Preserved cases**: 0 (all previously preserved cases were from deleted sessions)
- **Orphan cases**: 0
- **Status**: ✅ Clean
