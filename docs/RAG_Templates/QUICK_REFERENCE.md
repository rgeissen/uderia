# Quick Reference: RAG Template System

## 🚀 UI Workflow (Recommended)

### Complete End-to-End Flow

1. **RAG Collections Tab** → **Add RAG Collection**
2. **Collection Setup**:
   - Name: `my_collection`
   - MCP Server: Select your database server
   - Select: **Populate with SQL Template**
3. **Choose Population Mode**:
   - **Auto-Generate (LLM)** - Automatic question generation
   - **Manual Input** - Enter examples directly
4. **LLM Auto-Generation Steps**:
   ```
   a. Generate Context → Execute sample query (HELP TABLE, DESCRIBE, etc.)
   b. Configure:
      - Context Topic: "Customer order analytics"
      - Num Examples: 10
      - Database Name: sales_db
   c. Generate Questions → Review generated pairs
   d. Populate Collection → Add to collection
   e. Create Collection → Finalize
   ```

## 🔧 API Reference

### List Templates
```bash
curl http://localhost:5050/api/v1/rag/templates
```

Response:
```json
{
  "templates": [
    {
      "template_id": "sql_query_v1",
      "display_name": "SQL Query Constructor - Database Context",
      "version": "1.0.0"
    }
  ]
}
```

### Get Template Details
```bash
curl http://localhost:5050/api/v1/rag/templates/sql_query_v1/plugin-info
```

### Generate Questions (LLM)
```bash
curl -X POST http://localhost:5050/api/v1/rag/generate-questions \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "sql_query_v1",
    "execution_context": "CREATE TABLE customers (id INT, name VARCHAR(100), status VARCHAR(20))...",
    "subject": "Customer analytics and reporting",
    "count": 10,
    "database_name": "sales_db"
  }'
```

Response:
```json
{
  "questions": [
    {
      "user_query": "Show all active customers",
      "sql_statement": "SELECT * FROM sales_db.customers WHERE status = 'active';"
    }
  ],
  "input_tokens": 1234,
  "output_tokens": 567
}
```

### Populate Collection
```bash
curl -X POST http://localhost:5050/api/v1/rag/collections/1/populate \
  -H "Content-Type: application/json" \
  -d '{
    "template_type": "sql_query",
    "examples": [
      {
        "user_query": "Show all active customers",
        "sql_statement": "SELECT * FROM sales_db.customers WHERE status = '\''active'\'';"
      },
      {
        "user_query": "Count total orders",
        "sql_statement": "SELECT COUNT(*) FROM sales_db.orders;"
      }
    ],
    "database_name": "sales_db"
  }'
```

Response:
```json
{
  "status": "success",
  "message": "Successfully populated 2 cases",
  "results": {
    "successful": 2,
    "failed": 0,
    "errors": []
  }
}
```

## 📁 File Structure

```
rag_templates/
├── template_registry.json          # Template registration
└── templates/
    ├── sql-query-basic/            # Plugin directory
    │   ├── manifest.json           # UI config & validation
    │   ├── sql_query_v1.json       # Strategy template
    │   └── README.md
    └── sql-query-doc-context/
        ├── manifest.json
        ├── sql_query_doc_context_v1.json
        └── README.md

rag/tda_rag_cases/
├── collection_0/                   # Cases organized by collection
│   ├── case_abc123.json
│   └── case_def456.json
└── collection_1/
    └── case_xyz789.json
```

## 🎯 Template Types

### SQL Query Template (sql_query_v1)
**Use Case**: Database queries with business context  
**Phases**:
1. Execute SQL query via MCP tool
2. Generate natural language report

**Manual Input Fields**:
- `database_name` - Target database

**Auto-Generate Fields**:
- `context_topic` - Business context (e.g., "Sales reporting")
- `num_examples` - Number of pairs to generate (1-1000)
- `database_name` - Target database (optional)

### SQL Query with Document Context (sql_query_doc_context_v1)
**Use Case**: Queries requiring document/schema analysis  
**Phases**:
1. Retrieve relevant documentation
2. Execute SQL query
3. Generate final report

## 🔍 Validation Rules

### Manifest.json Controls UI Validation
```json
{
  "num_examples": {
    "type": "integer",
    "default": 5,
    "min": 1,
    "max": 1000,
    "required": true
  }
}
```

- Validation occurs **on input** (real-time)
- Min/max enforced by frontend before submission
- Template changes require server restart

## 💡 Tips

### LLM Question Generation
✅ **DO**:
- Use descriptive context topics
- Execute schema queries (HELP TABLE, DESCRIBE)
- Start with 5-10 examples to test
- Review and edit generated cases

❌ **DON'T**:
- Use vague context ("general queries")
- Generate 1000 examples without testing first
- Skip the review step
- Ignore validation errors

### Manual Population
✅ **DO**:
- Include database name in SQL statements
- Use realistic, diverse examples
- Test queries before adding to collection

❌ **DON'T**:
- Use incomplete or invalid SQL
- Duplicate similar queries
- Add database_name as separate argument (embedded in SQL only)

## 🐛 Common Issues

### "Value must be at most 1000"
→ Check `manifest.json` max value is set correctly  
→ Restart server to reload template configuration

### Template not found
→ Verify `template_registry.json` has correct `template_id`  
→ Check plugin directory matches registry entry  
→ Restart server

### Generated questions poor quality
→ Refine context topic to be more specific  
→ Provide comprehensive schema in sample query  
→ Reduce number of examples for higher quality

### Database name parameter error
→ Database name should be embedded in SQL string  
→ Do not pass as separate Phase 1 argument  
→ Updated templates remove database_name from Phase 1

## 📚 Additional Resources

- **Full Guide**: `README.md`
- **Plugin Development**: `TEMPLATE_PLUGIN_DEVELOPMENT.md`
- **Template Files**: `../../rag_templates/templates/`
