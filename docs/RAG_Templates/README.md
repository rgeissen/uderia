# Planner Repository Constructors - User Guide

## Overview

The **Planner Repository Constructor** system enables automatic generation of execution strategies and planning patterns through a modular plugin architecture. These constructors build **Planner Repositories** - specialized RAG collections that store proven execution traces, SQL query patterns, and successful agent interactions. Constructors define reusable patterns for specific use cases (SQL queries, API calls, workflows) and support both manual and LLM-assisted population.

**Note:** Planner Repositories are distinct from Knowledge Repositories (general document stores). Planner Repositories contain execution patterns that guide the agent's decision-making, while Knowledge Repositories provide reference documentation accessible during planning.

> **Related Documentation:**
> - `../../rag_templates/TYPE_TAXONOMY.md` - **Comprehensive type system documentation** explaining template_type, repository_type, and category concepts
> - `../../rag_templates/PLUGIN_MANIFEST_SCHEMA.md` - Template plugin manifest schema and field specifications
> - `../../rag_templates/schemas/README.md` - JSON schema validation details for template files

## Key Features

✅ **LLM-Assisted Question Generation** - Automatically generate question/answer pairs from database schemas  
✅ **Modular Plugin System** - Templates are self-contained plugins with manifest files  
✅ **Two-Phase Strategy Templates** - Execute queries and generate natural language reports  
✅ **Multiple Database Support** - Teradata, PostgreSQL, MySQL, and others via MCP tools  
✅ **UI-Based Workflow** - Complete end-to-end workflow in the web interface  
✅ **Template Validation** - Automatic validation of inputs and arguments

## Available Templates

### SQL Query Constructor - Database Context (`sql-query-basic`)

Generate question/SQL pairs from database schema and business requirements using MCP context.

**Features:**
- Uses MCP tools to extract database schema (HELP TABLE, DESCRIBE, etc.)
- LLM generates questions based on business context topic
- Supports 1-1000 question/SQL pairs per generation
- Works with any database supported by MCP tools (Teradata, PostgreSQL, MySQL, etc.)

**Population Mode:**
- **Auto-Generate (LLM)**: Generate from schema context
- **Manual**: Enter question/SQL pairs directly

**Use Cases:**
- Generate training data from production schemas
- Create diverse SQL query examples for specific databases
- Build knowledge bases for business analytics scenarios

### SQL Query Constructor - Document Context (`sql-query-doc-context`)

Generate question/SQL pairs from technical documentation (PDF, TXT, DOC, DOCX) using document upload.

**Features:**
- Upload technical documentation (DBA guides, performance docs, operational manuals)
- Provider-aware document processing (native upload for Google/Anthropic/Amazon, text extraction for others)
- LLM extracts concepts and generates practical SQL questions
- Supports multiple files up to 50MB each
- Maximum 1000 question/SQL pairs per generation

**Population Mode:**
- **Auto-Generate (Document Upload)**: Upload documents and generate questions
- **Manual**: Not supported (use document upload mode)

**Use Cases:**
- Convert DBA documentation into actionable SQL queries
- Extract best practices from performance tuning guides
- Generate troubleshooting queries from operational manuals
- Build knowledge bases from vendor documentation

**Document Upload Configuration:**
Access the Document Upload Configuration in the Admin panel to customize:
- Provider-specific upload methods (native vs. text extraction)
- Maximum file sizes per provider
- Enable/disable upload for specific providers

## Quick Start

### 1. Create a Collection

In the TDA web interface:
1. Navigate to **RAG Collections** tab
2. Click **Add RAG Collection**
3. Enter collection name and select MCP server
4. Choose **Populate with SQL Template**

### 2. Generate Questions (LLM-Assisted)

#### Option A: From Database Schema (Business Context Template)

With **SQL Query Constructor - Database Context** selected:

1. **Generate Context** - Execute a sample query to extract database schema
2. **Enter Configuration**:
   - **Context Topic**: e.g., "Employee analytics and reporting"
   - **Num Examples**: 1-1000 (number of question/SQL pairs to generate)
   - **Database Name**: Your target database
3. **Generate Questions** - LLM creates question/SQL pairs based on schema
4. **Review & Edit** - Verify and modify generated examples
5. **Populate Collection** - Add cases to the collection
6. **Create Collection** - Finalize and activate

#### Option B: From Documents (Document Context Template)

With **SQL Query Template - Document Context** selected:

1. **Upload Documents** - Click to upload PDF, TXT, DOC, or DOCX files
   - Supports multiple files
   - Max 50MB per file (varies by provider)
2. **Enter Configuration**:
   - **Context Topic**: e.g., "database performance tuning"
   - **Num Examples**: 1-1000
   - **Database Name**: Your target database
3. **Generate Questions** - LLM analyzes documents and creates question/SQL pairs
4. **Review & Edit** - Verify generated examples
5. **Populate Collection** - Add cases to collection
6. **Create Collection** - Finalize and activate

### 3. Manual Population

Alternatively, use **Manual Input** to enter question/SQL pairs directly:
- Add multiple question/SQL examples
- Specify database name and MCP tool
- Populate collection immediately

## User Template Directory

### Custom Templates Without System Modification

You can create **custom templates** in your user home directory without modifying the system installation. This allows you to:

- 🔒 **Persist templates** across application updates
- 📦 **Share templates** between users (copy directory)
- 🎯 **Override built-in templates** for customization
- ✅ **Keep system files clean** (no need to edit core files)

### Directory Location

**User Template Directory:** `~/.tda/templates/`

### Directory Structure

```
~/.tda/templates/                      # User template directory (auto-discovered)
├── my-custom-sql/
│   ├── manifest.json                   # Plugin metadata
│   ├── my_custom_sql_v1.json          # Template definition
│   └── README.md                       # Documentation (optional)
├── api-workflow/
│   ├── manifest.json
│   ├── api_workflow_v1.json
│   └── README.md
└── custom-reporting/
    ├── manifest.json
    ├── custom_reporting_v1.json
    └── README.md
```

### Template Discovery Process

When the application starts, the template system loads templates in this order:

1. **Built-in templates** from `rag_templates/templates/` (system installation)
2. **User templates** from `~/.tda/templates/` (user home directory)
3. **Override resolution**: If a user template has the same `template_id` as a built-in template, the **user template takes precedence**
4. **Automatic registration**: User templates are registered automatically (no manual `template_registry.json` editing required)

### Creating a User Template

**Example: Custom Product Inventory Template**

**Step 1: Create Directory**
```bash
# Create template directory
mkdir -p ~/.tda/templates/product-inventory-custom
cd ~/.tda/templates/product-inventory-custom
```

**Step 2: Create manifest.json**
```json
{
  "name": "product-inventory-custom",
  "template_id": "product_inventory_custom_v1",
  "template_type": "sql_query",
  "repository_type": "planner",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "Custom product inventory queries for my company",

  "input_variables": [
    {
      "name": "database_name",
      "type": "string",
      "required": true,
      "description": "Target database"
    },
    {
      "name": "business_domain",
      "type": "select",
      "required": true,
      "options": [
        {"value": "inventory", "label": "Inventory Management"},
        {"value": "sales", "label": "Sales Analysis"}
      ]
    }
  ],

  "output_configuration": {
    "fields": [
      {"name": "question", "type": "text", "required": true},
      {"name": "sql_statement", "type": "code", "required": true},
      {"name": "category", "type": "string", "required": true}
    ]
  },

  "population_modes": {
    "manual": {
      "supported": true,
      "description": "Manually enter questions and SQL"
    },
    "auto_generate": {
      "supported": true,
      "requires_llm": true,
      "requires_mcp_context": true,
      "generation_endpoint": "/api/v1/rag/generate-questions-from-documents"
    }
  }
}
```

**Step 3: Create Template JSON**
Create `product_inventory_custom_v1.json` with your template definition (see `COMPLETE_EXAMPLE.md` for full structure).

**Step 4: Create README.md (Optional)**
Document your template's purpose, usage, and examples.

**Step 5: Reload Templates**
```bash
# Get JWT token
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

# Hot-reload templates (no restart required)
curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
  -H "Authorization: Bearer $JWT"
```

**Expected Response:**
```json
{
  "status": "success",
  "message": "Templates reloaded successfully",
  "templates_count": 7,
  "new_templates": ["product_inventory_custom_v1"],
  "user_templates_count": 1
}
```

**Step 6: Verify in UI**
1. Navigate to **Setup → RAG Collections**
2. Click **"Create New Collection"**
3. Check template dropdown for **"Product Inventory Custom"**
4. Template should appear with your custom metadata

### Overriding Built-In Templates

You can **customize built-in templates** by creating a user template with the same `template_id`:

**Example: Override SQL Query Template**

```bash
# Copy built-in template to user directory
mkdir -p ~/.tda/templates/sql-query-basic-custom
cp rag_templates/templates/sql-query-basic/manifest.json \
   ~/.tda/templates/sql-query-basic-custom/

# Edit manifest.json to customize
# Keep the same template_id: "sql_query_v1"
# Modify fields, validation rules, or prompts as needed

# Reload templates
curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
  -H "Authorization: Bearer $JWT"
```

**Result:** Your customized version of `sql_query_v1` will be used instead of the built-in version.

### Sharing Templates

**Share with team members:**

```bash
# Package template directory
cd ~/.tda/templates
tar -czf product-inventory-template.tar.gz product-inventory-custom/

# Share file with colleague

# Colleague installs:
mkdir -p ~/.tda/templates
cd ~/.tda/templates
tar -xzf ~/Downloads/product-inventory-template.tar.gz

# Reload templates (or restart application)
```

**Share via Git repository:**

```bash
# Create repository for your templates
cd ~/.tda/templates
git init
git add .
git commit -m "Add custom product inventory template"
git remote add origin https://github.com/yourcompany/tda-templates.git
git push -u origin main

# Team members clone:
cd ~/.tda
git clone https://github.com/yourcompany/tda-templates.git templates
```

### Benefits of User Templates

| Feature | Built-In Templates | User Templates |
|---------|-------------------|----------------|
| **Location** | `rag_templates/templates/` | `~/.tda/templates/` |
| **Survive Updates** | ❌ Overwritten on upgrade | ✅ Persist across updates |
| **System Modification** | ⚠️ Requires editing core files | ✅ No system files modified |
| **Sharing** | ⚠️ Must copy from installation | ✅ Easy directory copy or Git |
| **Override Built-Ins** | ❌ N/A | ✅ Override by matching template_id |
| **Automatic Discovery** | ✅ Yes | ✅ Yes |
| **Hot Reload** | ✅ Yes | ✅ Yes |

### Best Practices

1. **Use Descriptive Names**: `product-inventory-acme-corp` instead of `template1`
2. **Version Templates**: Include version in filename (`my_template_v1.json`, `my_template_v2.json`)
3. **Document Thoroughly**: Include README.md with usage examples
4. **Test Before Deploying**: Create test collection to validate template
5. **Backup Templates**: Keep templates in version control (Git)
6. **Namespace Template IDs**: Use company prefix to avoid collisions (`acme_product_inventory_v1`)

### Troubleshooting User Templates

#### Template Not Appearing in UI

**Check:**
1. **Directory structure**: Ensure `~/.tda/templates/your-template/manifest.json` exists
2. **Manifest validity**: Validate JSON syntax (`jq . manifest.json`)
3. **Template reloaded**: Call reload endpoint or restart application
4. **Server logs**: Check for template loading errors

**Debug:**
```bash
# Check if directory exists
ls -la ~/.tda/templates/

# Validate manifest JSON
cd ~/.tda/templates/your-template
jq . manifest.json

# Check server logs for errors
tail -100 logs/app.log | grep -i "template"
```

#### User Template Not Overriding Built-In

**Cause:** `template_id` doesn't match exactly

**Solution:**
1. Check built-in template's `template_id` in manifest
2. Ensure user template uses **exact same** `template_id`
3. Case-sensitive: `sql_query_v1` ≠ `SQL_Query_V1`

**Verification:**
```bash
# List all templates with IDs
curl -X GET http://localhost:5050/api/v1/rag/templates \
  -H "Authorization: Bearer $JWT" | jq '.templates[] | {id: .template_id, source: .is_user_template}'
```

#### Permission Errors

**Cause:** Incorrect file permissions on `~/.tda/templates/`

**Solution:**
```bash
# Fix permissions
chmod -R 755 ~/.tda/templates/
chmod 644 ~/.tda/templates/*/manifest.json
chmod 644 ~/.tda/templates/*/*.json
```

## Template Structure (Built-In)

### Plugin Directory Layout

```
rag_templates/templates/                # Built-in system templates
├── sql-query-basic/
│   ├── manifest.json                   # Plugin metadata and UI configuration
│   ├── sql_query_v1.json              # Template definition (strategy)
│   └── README.md                       # Documentation
└── sql-query-doc-context/
    ├── manifest.json
    ├── sql_query_doc_context_v1.json
    └── README.md
```

### Manifest.json

Defines plugin metadata, UI fields, and validation rules:

```json
{
  "name": "sql-query-basic",
  "version": "1.0.0",
  "template_id": "sql_query_v1",
  "display_name": "SQL Query Template - Business Context",
  "description": "Two-phase strategy...",
  
  "population_modes": {
    "manual": {
      "enabled": true,
      "input_variables": {
        "database_name": {
          "required": true,
          "description": "Target database name"
        }
      }
    },
    "auto_generate": {
      "enabled": true,
      "input_variables": {
        "context_topic": {
          "required": true,
          "type": "string",
          "description": "Business context for question generation"
        },
        "num_examples": {
          "required": true,
          "type": "integer",
          "default": 5,
          "min": 1,
          "max": 1000,
          "description": "Number of question/SQL pairs to generate"
        },
        "database_name": {
          "required": false,
          "description": "Target database name"
        }
      }
    }
  }
}
```

### Template JSON (Strategy Definition)

Defines the execution strategy with phases and arguments:

```json
{
  "template_id": "sql_query_v1",
  "template_version": "1.0.0",
  "strategy_template": {
    "strategy_name": "SQL Query Strategy",
    "phases": [
      {
        "phase_number": 1,
        "phase_description": "Execute SQL query",
        "tool": "base_readQuery",
        "arguments": [
          {
            "name": "sql",
            "type": "sql_statement",
            "required": true,
            "description": "The SQL query to execute (includes database name)"
          }
        ]
      },
      {
        "phase_number": 2,
        "phase_description": "Generate final report",
        "tool": "TDA_FinalReport",
        "arguments": [
          {
            "name": "user_query",
            "type": "user_query",
            "required": true
          }
        ]
      }
    ]
  }
}
```

## LLM Question Generation

### How It Works

1. **Context Extraction**: Execute a sample query (e.g., `HELP TABLE tablename;`) to get schema information
2. **Schema Analysis**: Extract table structures, columns, data types, and constraints
3. **Prompt Construction**: Build a detailed prompt with:
   - Business context topic
   - Complete schema information
   - Number of examples to generate
   - Target database name
4. **LLM Generation**: Generate diverse, realistic question/SQL pairs
5. **Validation**: Ensure SQL is syntactically valid and questions are meaningful

### Best Practices

- **Context Topic**: Be specific (e.g., "Customer order analysis" vs "general queries")
- **Sample Queries**: Use `HELP TABLE` or `DESCRIBE` to get comprehensive schema
- **Review Generated Cases**: Always review before populating - edit if needed
- **Incremental Generation**: Start with 5-10 examples to test, then scale up

## Template Registry

Templates are registered in `rag_templates/template_registry.json`:

```json
{
  "templates": [
    {
      "template_id": "sql_query_v1",
      "template_file": "sql-query-basic/sql_query_v1.json",
      "plugin_directory": "sql-query-basic",
      "status": "active",
      "priority": 1
    }
  ]
}
```

## API Endpoints

### Get Available Templates
```bash
GET /api/v1/rag/templates
```

### Get Template Plugin Info
```bash
GET /api/v1/rag/templates/{template_id}/plugin-info
```

### Generate Questions from Schema (Business Context)
```bash
POST /api/v1/rag/generate-questions
Content-Type: application/json
Authorization: Bearer YOUR_JWT_TOKEN

{
  "template_id": "sql_query_v1",
  "execution_context": "{...extracted schema...}",
  "subject": "Customer analytics",
  "count": 10,
  "database_name": "sales_db"
}
```

### Generate Questions from Documents (Document Context)
```bash
POST /api/v1/rag/generate-questions-from-documents
Content-Type: multipart/form-data
Authorization: Bearer YOUR_JWT_TOKEN

Form Data:
- subject: "performance tuning"
- count: 10
- database_name: "production_db"
- target_database: "Teradata"
- files: [dba_guide.pdf, optimization_tips.pdf]
```

### Populate Collection
```bash
POST /api/v1/rag/collections/{collection_id}/populate
{
  "template_type": "sql_query",
  "examples": [
    {
      "user_query": "Show all active customers",
      "sql_statement": "SELECT * FROM customers WHERE status = 'active'"
    }
  ],
  "database_name": "sales_db"
}
```

## Troubleshooting

### Template Not Loading
- Check `template_registry.json` for correct `template_id` and file paths
- Verify manifest.json has required fields
- Restart server to reload templates

### Validation Errors
- Ensure `num_examples` is within min/max range (1-1000)
- Verify all required fields are provided
- Check that SQL statements include database name in the query string

### Generated Questions Poor Quality
- Refine context topic to be more specific
- Provide more comprehensive schema information in sample query
- Adjust the number of examples (fewer can be higher quality)

## Advanced: Creating Custom Templates

See `TEMPLATE_PLUGIN_DEVELOPMENT.md` for detailed guide on:
- Template plugin structure
- Manifest configuration
- Strategy definition
- UI field customization
- Validation rules
- Distribution and installation

## Migration Notes

### From Legacy System
- Old flat template files (`sql_query_v1.json` at root) are deprecated
- Use plugin directory structure (`templates/plugin-name/`)
- Manifest files now required for UI integration
- Template arguments refined (database_name removed from Phase 1)

## Support

For issues or questions:
- GitHub: https://github.com/rgeissen/uderia
- Check logs: `logs/` directory
- Validate templates: Check browser console and server logs
