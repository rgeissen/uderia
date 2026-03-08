# SQL Query Constructor - Database Context Plugin

## Overview

A modular template plugin for executing SQL queries and generating reports. This template provides a two-phase strategy:

1. **Phase 1**: Execute SQL statement using configured MCP tool
2. **Phase 2**: Generate final report from query results

## Features

- ✅ Multi-database support (Teradata, PostgreSQL, MySQL, etc.)
- ✅ Configurable MCP tool selection
- ✅ Flexible query parameter handling
- ✅ Built-in query validation
- ✅ Support for multiple result formats

## Installation

### Built-in (Already Installed)

This template is included with TDA by default.

### Manual Installation

```bash
# Copy to user templates directory
cp -r sql-query-basic ~/.tda/templates/

# Reload templates
curl -X POST http://localhost:8080/api/v1/rag/templates/reload
```

## Usage

### Via REST API

```bash
POST /api/v1/rag/collections/{collection_id}/populate
Content-Type: application/json

{
  "template_type": "sql_query",
  "examples": [
    {
      "user_query": "Show me all active users",
      "sql_statement": "SELECT * FROM users WHERE status = 'active'",
      "database_name": "app_db"
    },
    {
      "user_query": "Count orders by customer",
      "sql_statement": "SELECT customer_id, COUNT(*) as order_count FROM orders GROUP BY customer_id",
      "database_name": "sales_db"
    }
  ],
  "mcp_tool_name": "base_readQuery"
}
```

### Via UI

1. Open "Manage RAG Collections"
2. Select "Auto-generate with LLM"
3. Choose "SQL Query Constructor - Database Context"
4. Configure:
   - Subject/Topic
   - Database Name
   - Target Database System (e.g., Teradata)
   - Explicit Conversion Rules (optional)
5. Generate Context → Generate Questions → Populate → Create

## Configuration

### Input Variables

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `user_query` | string | Yes | Natural language question |
| `sql_statement` | string | Yes | SQL query to execute |
| `database_name` | string | No | Target database name |
| `table_names` | array | No | Tables involved in query |
| `mcp_tool_name` | string | No | MCP tool for execution (default: base_readQuery) |
| `mcp_context_prompt` | string | No | MCP prompt for context (default: base_databaseBusinessDesc) |
| `target_database` | string | No | Database system type (default: Teradata) |

### Editable Configuration

Runtime configuration can be modified via API:

```bash
PUT /api/v1/rag/templates/sql_query_v1/config
Content-Type: application/json

{
  "default_mcp_tool": "base_readQuery",
  "default_mcp_context_prompt": "base_databaseBusinessDesc",
  "estimated_input_tokens": 150,
  "estimated_output_tokens": 180
}
```

## Examples

### Simple SELECT Query

```json
{
  "user_query": "Show me all products in stock",
  "sql_statement": "SELECT * FROM products WHERE quantity > 0",
  "database_name": "inventory_db"
}
```

### JOIN with Aggregation

```json
{
  "user_query": "What is the average order value per customer?",
  "sql_statement": "SELECT c.customer_id, c.name, AVG(o.total) as avg_order FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.customer_id, c.name",
  "database_name": "sales_db",
  "table_names": ["customers", "orders"]
}
```

### Teradata-Specific Query

```json
{
  "user_query": "Get monthly sales for the last year",
  "sql_statement": "SELECT EXTRACT(MONTH FROM sale_date) AS month, SUM(amount) AS total FROM sales WHERE sale_date BETWEEN ADD_MONTHS(CURRENT_DATE, -12) AND CURRENT_DATE GROUP BY 1 ORDER BY 1",
  "database_name": "analytics_db",
  "target_database": "Teradata"
}
```

## Validation Rules

The template validates:

- ✅ SQL statement contains valid SQL keywords (SELECT, INSERT, UPDATE, etc.)
- ✅ Query length between 10-5000 characters
- ✅ User query length between 5-500 characters
- ⚠️ Additional validation can be added via custom validators

## Database Support

| Database | Tested | Notes |
|----------|--------|-------|
| Teradata | ✅ | Full support with dialect-specific functions |
| PostgreSQL | ✅ | Standard SQL with extensions |
| MySQL | ✅ | MySQL-specific syntax supported |
| Oracle | 🔄 | Partial support |
| SQL Server | 🔄 | Partial support |

## Customization

### Custom MCP Tools

To use a custom MCP tool for SQL execution:

1. Set `mcp_tool_name` in your examples
2. Ensure tool accepts `sql` and `database_name` arguments
3. Tool should return query results in expected format

### Database-Specific Syntax

Use the `target_database` variable and Explicit Conversion Rules to ensure correct SQL syntax:

**Example Conversion Rules:**
```
Use CAST(column AS DATE) instead of column::DATE
Use EXTRACT(YEAR FROM date_col) not YEAR(date_col)
Use TOP N instead of LIMIT N for Teradata
Use ADD_MONTHS() for date arithmetic in Teradata
Use proper table name casing: schema.Table not schema.table
```

## Performance

### Token Estimates

- **Planning Phase**: ~150 input tokens
- **Execution Phase**: ~180 output tokens
- **Total**: ~330 tokens per case

### Optimization Tips

1. Use `base_readQuery` for read-only queries (more efficient)
2. Use `base_readQuery` for write operations
3. Batch similar queries in single collection
4. Cache database context for repeated use

## Troubleshooting

### Template Not Found

```bash
# Verify template is loaded
curl http://localhost:8080/api/v1/rag/templates/list | jq '.templates[] | select(.template_id=="sql_query_v1")'

# Reload if missing
curl -X POST http://localhost:8080/api/v1/rag/templates/reload
```

### SQL Syntax Errors

1. Check `target_database` matches actual database
2. Add Explicit Conversion Rules for dialect-specific syntax
3. Validate SQL locally before adding to template
4. Review query in case detail view after execution

### MCP Tool Errors

```bash
# Verify MCP server is configured
curl http://localhost:8080/api/v1/mcp/servers

# Test tool directly
curl -X POST http://localhost:8080/api/v1/prompts/test_tool/execute \
  -d '{"tool": "base_readQuery", "args": {"sql": "SELECT 1", "database_name": "test"}}'
```

## Contributing

To enhance this template:

1. Fork repository
2. Make changes to `sql-query-basic/`
3. Test with validation endpoint
4. Submit pull request with examples

## Version History

### v1.0.0 (2025-11-20)
- Initial release
- Two-phase execution strategy
- Multi-database support
- Configurable MCP tools
- Runtime configuration support

### v1.1.0 (Planned)
- Custom UI configuration panel
- Advanced query validation
- Query result preview
- Performance analytics

## License

AGPL-3.0 - See LICENSE file

## Support

- **Documentation**: https://github.com/rgeissen/uderia/docs
- **Issues**: https://github.com/rgeissen/uderia/issues
- **Template Guide**: See `TEMPLATE_PLUGIN_DEVELOPMENT.md`

## Related Templates

- `api_rest_v1` - REST API request template (coming soon)
- `file_processing_v1` - File processing template (coming soon)
- `custom_workflow_v1` - Custom multi-step workflow (coming soon)
