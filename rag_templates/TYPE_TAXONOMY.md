# RAG Template Type Taxonomy

## Overview

The RAG template system uses three distinct but related type concepts. Understanding the difference is crucial for template development and system maintenance.

## The Three Type Concepts

### 1. `template_type` (Strategy/Execution Type)

**Purpose:** Defines HOW the template executes or processes data

**Location:** Template JSON file (`template_type` field)

**Values:**
- **Planner Types** (execution strategies):
  - `sql_query` - SQL query execution with result reporting
  - `api_request` - API call execution workflows
  - `custom_workflow` - Multi-step custom processes
  - Future: `file_processing`, `data_transformation`, etc.

- **Knowledge Type** (document storage):
  - `knowledge_repository` - Document chunking and embedding

**Usage:**
```json
{
  "template_id": "sql_query_v1",
  "template_type": "sql_query",  // ← Strategy type
  ...
}
```

**Determines:**
- Which JSON schema validates the template (planner-schema.json or knowledge-template-schema.json)
- Which template fields are required
- How the template generates RAG cases

---

### 2. `repository_type` (Storage Model)

**Purpose:** Defines HOW collection data is stored in the database

**Location:** Collections table in database (`repository_type` column)

**Values:**
- `planner` - Stores execution traces (successful strategies)
- `knowledge` - Stores document chunks with embeddings

**Usage:**
```python
# When creating a collection
collection_db.create_collection(
    name="My Collection",
    repository_type="planner",  // ← Storage model
    ...
)
```

**Determines:**
- Database schema for the collection
- How ChromaDB stores and retrieves data
- Which REST API endpoints apply
- Query patterns for retrieval

**Relationship to template_type:**
```
template_type              → repository_type (in collections table)
─────────────────────────    ────────────────────────────────────
sql_query                 → planner
api_request               → planner
custom_workflow           → planner
knowledge_repository      → knowledge
```

---

### 3. `category` (UI Grouping)

**Purpose:** Organizes templates in the user interface

**Location:** 
- Template registry (`template_registry.json`)
- Plugin manifest (`manifest.json`)

**Values:** (Examples - not restricted)
- `Database`
- `Knowledge Management`
- `API Integration`
- `File Processing`
- `Data Transformation`

**Usage:**
```json
// In template_registry.json
{
  "template_id": "sql_query_v1",
  "category": "Database",  // ← UI grouping
  "status": "active"
}
```

**Determines:**
- How templates are grouped in UI dropdowns
- Template discovery and filtering
- Help text and documentation organization

---

## Relationship Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Template System Type Hierarchy                              │
└─────────────────────────────────────────────────────────────┘

TEMPLATE FILE (template.json)
├─ template_type: "sql_query"        ← Strategy/Execution
│  └─ Determines: Schema validation, required fields
│
TEMPLATE REGISTRY (template_registry.json)
├─ category: "Database"              ← UI Grouping  
│  └─ Determines: UI organization, filtering
│
COLLECTION DATABASE (collections table)
└─ repository_type: "planner"        ← Storage Model
   └─ Determines: DB schema, query patterns
```

---

## Common Patterns

### Pattern 1: SQL Query Template (Planner)
```json
// Template file
{
  "template_type": "sql_query",           // Execution strategy
  ...
}

// Registry
{
  "template_id": "sql_query_v1",
  "category": "Database"                  // UI grouping
}

// Collection (created from this template)
{
  "repository_type": "planner"            // Storage model
}
```

### Pattern 2: Knowledge Repository Template
```json
// Template file
{
  "template_type": "knowledge_repository", // Document storage
  ...
}

// Registry
{
  "template_id": "knowledge_repo_v1",
  "category": "Knowledge Management"       // UI grouping
}

// Collection (created from this template)
{
  "repository_type": "knowledge"          // Storage model
}
```

---

## Validation Rules

### Template Validation
```python
# Schema selection based on template_type
if template_type == "knowledge_repository":
    schema = "knowledge-template-schema.json"
else:
    schema = "planner-schema.json"  # All other types
```

### Required Fields by template_type

**Planner Templates** (sql_query, api_request, etc.):
- ✅ `input_variables`
- ✅ `output_configuration`
- ✅ `strategy_template`

**Knowledge Templates** (knowledge_repository):
- ✅ `repository_configuration`

---

## Why Three Separate Concepts?

### Design Rationale

**1. template_type (Strategy)**
- **Purpose:** Extensibility - Add new execution strategies without changing DB schema
- **Example:** Can add `api_request`, `file_processing` without migrations
- **Benefit:** Template developers can create new strategy types

**2. repository_type (Storage)**
- **Purpose:** Performance - Different storage optimizations for different use cases
- **Example:** Planner needs strategy retrieval, Knowledge needs semantic search
- **Benefit:** Database queries optimized for access patterns

**3. category (UI Grouping)**
- **Purpose:** User Experience - Organize templates by business domain
- **Example:** Group all database-related templates together
- **Benefit:** Users find templates by use case, not implementation detail

---

## Migration Considerations

### From Legacy Naming
Old code may use inconsistent terminology:

```python
# OLD (inconsistent)
if template_type == "sql_query":
    repo_type = "planner"  # Conflates strategy and storage

# NEW (clear separation)
template_type = "sql_query"        # Strategy type
repository_type = "planner"        # Storage model
category = "Database"              # UI grouping
```

### Adding New Types

**To add a new planner strategy:**
1. Create template with new `template_type` (e.g., `api_request`)
2. Set `repository_type="planner"` in collections
3. Choose appropriate `category` for UI

**To add a new storage model:**
1. Requires database migration (new `repository_type`)
2. Create new JSON schema for validation
3. Update collection creation logic

---

## Code Examples

### Check Template Type
```python
# Determine schema for validation
def get_schema_type(template_data):
    """Return 'knowledge' or 'planner' schema type."""
    template_type = template_data.get("template_type", "")
    
    if template_type == "knowledge_repository":
        return "knowledge"
    else:
        return "planner"  # All execution strategies
```

### Create Collection with Correct Storage
```python
# Template defines strategy, collection defines storage
template = manager.get_template("sql_query_v1")
template_type = template["template_type"]  # "sql_query"

# Determine storage model
if template_type == "knowledge_repository":
    repository_type = "knowledge"
else:
    repository_type = "planner"

# Create collection with appropriate storage
collection = create_collection(
    name="Sales Queries",
    repository_type=repository_type  # "planner"
)
```

### Filter Templates by Category
```python
# Group templates for UI display
def get_templates_by_category():
    """Return templates grouped by category."""
    templates = manager.list_templates()
    
    groups = {}
    for template in templates:
        category = template.get("category", "Other")
        if category not in groups:
            groups[category] = []
        groups[category].append(template)
    
    return groups
```

---

## Best Practices

### ✅ DO

1. **Use template_type for strategy logic**
   ```python
   if template_type == "knowledge_repository":
       # Handle document storage
   ```

2. **Use repository_type for database queries**
   ```python
   SELECT * FROM collections WHERE repository_type = 'planner'
   ```

3. **Use category for UI organization**
   ```python
   const databaseTemplates = templates.filter(t => t.category === "Database");
   ```

4. **Document type relationships clearly**
   - Add comments explaining which type concept you're using
   - Use consistent variable names

### ❌ DON'T

1. **Don't conflate template_type and repository_type**
   ```python
   # BAD
   if template_type == "planner":  # Wrong! "planner" is repository_type
   
   # GOOD
   if repository_type == "planner":
   ```

2. **Don't assume template_type maps directly to UI categories**
   ```python
   # BAD
   category = template_type  # Not always true
   
   # GOOD
   category = manifest.get("category", "Other")
   ```

3. **Don't use string matching for type detection**
   ```python
   # BAD
   if "knowledge" in template_type:  # Fragile
   
   # GOOD
   if template_type == "knowledge_repository":  # Exact match
   ```

---

## Summary

| Concept | Purpose | Location | Example Values | Determines |
|---------|---------|----------|----------------|------------|
| **template_type** | How template executes | Template JSON | `sql_query`, `knowledge_repository` | Schema, required fields, execution logic |
| **repository_type** | How data is stored | Collections table | `planner`, `knowledge` | DB schema, query patterns |
| **category** | UI organization | Registry/Manifest | `Database`, `Knowledge Management` | UI grouping, filtering |

**Key Insight:** These are **orthogonal concepts** serving different purposes. Don't conflate them!

---

## References

- JSON Schemas: `rag_templates/schemas/`
- Template Examples: `rag_templates/templates/`
- Collection Database: `src/trusted_data_agent/core/collection_db.py`
- Template Manager: `src/trusted_data_agent/agent/rag_template_manager.py`
