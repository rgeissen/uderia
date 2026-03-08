# SQL Query Constructor - Document Context

## Overview
Generate SQL query examples from technical database documentation (DBA guides, performance tuning manuals, operational procedures). This template creates question/SQL pairs based on document content and a specified operational context topic.

## Use Cases

### Performance Tuning
- **Input**: Database performance tuning guide (PDF)
- **Context Topic**: "performance optimization"
- **Output**: Questions like "Show tables with high fragmentation" → SQL queries

### Database Administration
- **Input**: DBA operational procedures manual
- **Context Topic**: "backup and recovery"
- **Output**: Questions like "List failed backup jobs" → SQL queries

### Query Optimization
- **Input**: Query optimization best practices guide
- **Context Topic**: "index management"
- **Output**: Questions like "Find tables without indexes" → SQL queries

## Key Features

### Document-Driven Context
- Upload technical PDF documentation
- Extract operational knowledge and procedures
- Generate relevant SQL queries based on doc content

### Flexible Context Topics
The `context_topic` variable allows you to focus on specific operational areas:
- Performance tuning
- Backup/recovery procedures
- Index optimization
- Query monitoring
- Storage management
- Security auditing
- Capacity planning

### Database Compatibility
Works with multiple database systems:
- Teradata
- PostgreSQL
- MySQL
- Oracle
- SQL Server

## Input Variables

### Required
- **user_query**: Natural language question (e.g., "Show fragmented tables")
- **sql_statement**: The SQL query to execute
- **context_topic**: Operational focus area (e.g., "performance tuning")
- **document_content**: Extracted text from technical documentation

### Optional
- **database_name**: Target database
- **table_names**: Tables involved in the query
- **mcp_tool_name**: MCP tool for SQL execution (default: `base_executeRawSQLStatement`)
- **target_database**: Database system for SQL syntax (default: `Teradata`)

## Workflow

### Phase 1: Document Upload & Processing
1. Upload technical PDF documentation (DBA guides, manuals, etc.)
2. Extract text content using PDF processing
3. Specify the `context_topic` for focused generation
4. System analyzes document for relevant operational patterns

### Phase 2: Question/SQL Generation
1. LLM reads document content with context topic focus
2. Generates relevant operational questions
3. Creates corresponding SQL queries based on doc examples
4. Validates SQL syntax for target database

### Phase 3: Collection Population
1. Store question/SQL pairs in RAG collection
2. Tag with context topic for retrieval
3. Enable semantic search for operational queries

## Example Workflows

### Performance Tuning Use Case
```
Context Topic: "performance tuning"
Document: "Teradata Performance Tuning Guide.pdf"

Generated Pairs:
- Q: "Show me tables with skewed data distribution"
  SQL: "SELECT DatabaseName, TableName, SkewFactor FROM DBC.TableSize WHERE SkewFactor > 50"

- Q: "Find queries consuming most CPU"
  SQL: "SELECT QueryID, UserName, AMPCPUTime FROM DBC.QryLogV ORDER BY AMPCPUTime DESC FETCH FIRST 20 ROWS ONLY"
```

### Index Optimization Use Case
```
Context Topic: "index optimization"
Document: "Database Index Best Practices.pdf"

Generated Pairs:
- Q: "List tables without primary indexes"
  SQL: "SELECT DatabaseName, TableName FROM DBC.Tables WHERE IndexType = 'N'"

- Q: "Show index usage statistics"
  SQL: "SELECT IndexName, AccessCount FROM DBC.Indices ORDER BY AccessCount ASC"
```

## Configuration

### Default Settings
- **MCP Tool**: `base_executeRawSQLStatement`
- **Estimated Tokens**: 200 input, 220 output (higher due to document context)
- **Target Database**: Teradata (configurable)

### Editable Parameters
Access via Template Editor Modal:
- Default MCP tool name
- Estimated token counts
- Champion status flag

## Differences from Business Context Template

| Feature | Business Context | Document Context |
|---------|------------------|------------------|
| Context Source | Live DB via MCP prompts | Technical PDFs/documents |
| Use Case | Business questions | Operational/DBA queries |
| Context Variable | Database name | Context topic |
| Focus | Business data | DB administration |
| Example Question | "Show sales by region" | "Find fragmented tables" |

## Tips for Best Results

### Document Preparation
- Use clear, well-structured technical documents
- Include SQL examples in source documents
- Focus on operational procedures and best practices

### Context Topics
Be specific with context topics:
- ✅ "table fragmentation analysis"
- ✅ "query performance monitoring"
- ❌ "database" (too broad)
- ❌ "stuff" (too vague)

### Question Generation
- Start with 5-10 examples per context topic
- Review and refine SQL queries before storing
- Test queries on target database

## License
MIT License - See LICENSE file for details

## Support
- GitHub Issues: https://github.com/rgeissen/uderia/issues
- Documentation: https://github.com/rgeissen/uderia/docs
