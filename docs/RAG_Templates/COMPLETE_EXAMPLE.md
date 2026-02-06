# Complete Template Creation Tutorial: End-to-End Example

This tutorial walks you through creating a RAG template from scratch, from initial planning to production deployment. We'll build a **Product Inventory Query Template** that generates business intelligence questions from your database schema.

---

## Table of Contents

1. [Planning Phase](#planning-phase)
2. [Creation Phase](#creation-phase)
3. [Testing Phase](#testing-phase)
4. [Deployment Phase](#deployment-phase)
5. [Troubleshooting](#troubleshooting)

---

## Planning Phase

### Step 1: Identify Your Use Case

**Business Requirement:**
- Sales team needs quick insights about product inventory
- Questions should be generated automatically from database schema
- Queries should cover: low stock, high-value items, category analysis

**Template Objectives:**
- Generate 50+ natural language questions
- Each question paired with working SQL query
- Questions categorized by business domain (inventory, sales, procurement)

### Step 2: Choose Template Type

**Decision Matrix:**

| Template Type | Use Case | Context Source | Best For |
|---------------|----------|----------------|----------|
| **Planner Repository** | ✅ **SELECTED** | MCP Server (live schema) | Database queries, structured data |
| Knowledge Repository | ❌ | Uploaded Documents | Reference docs, unstructured knowledge |

**Why Planner Repository?**
- We have live database schema via MCP server
- SQL queries are structured and predictable
- LLM can generate questions from table/column metadata

### Step 3: Define Input Variables

**What information does the LLM need to generate questions?**

| Variable | Purpose | Source | Example Value |
|----------|---------|--------|---------------|
| `database_name` | Identify the database | MCP context | `ecommerce_prod` |
| `schema_context` | Table/column definitions | MCP tools | `Tables: products(id, name, price, quantity, category_id)...` |
| `business_domain` | Focus area for questions | User input | `inventory_management` |
| `complexity_level` | Query difficulty | User input | `beginner`, `intermediate`, `advanced` |

### Step 4: Design Output Format

**What gets stored in the RAG collection?**

```json
{
  "question": "Which products have less than 10 units in stock?",
  "sql_statement": "SELECT name, quantity FROM products WHERE quantity < 10 ORDER BY quantity ASC;",
  "category": "inventory",
  "complexity": "beginner",
  "database_name": "ecommerce_prod"
}
```

**Metadata for RAG Retrieval:**
- `database_name` - Filter questions for specific database
- `category` - Filter by business domain
- `complexity` - Filter by user skill level

---

## Creation Phase

### Step 5: Create Template Directory

```bash
# Navigate to templates directory
cd rag_templates/templates/

# Create new template directory
mkdir product-inventory-queries

# Create necessary files
cd product-inventory-queries
touch manifest.json
touch product_inventory_v1.json
touch README.md
```

**Directory Structure:**
```
rag_templates/templates/product-inventory-queries/
├── manifest.json                    # UI configuration and population modes
├── product_inventory_v1.json        # Template definition with phase structure
└── README.md                        # Documentation for template users
```

### Step 6: Create manifest.json

**File:** `rag_templates/templates/product-inventory-queries/manifest.json`

```json
{
  "name": "Product Inventory Queries",
  "description": "Generate business intelligence questions about product inventory, stock levels, and category analysis",
  "template_id": "product_inventory_v1",
  "template_type": "sql_query",
  "repository_type": "planner",
  "version": "1.0.0",
  "author": "Your Company",
  "license": "MIT",

  "category": "business_intelligence",
  "tags": ["inventory", "products", "sql", "ecommerce"],

  "input_variables": [
    {
      "name": "database_name",
      "type": "string",
      "description": "Name of the target database",
      "required": true,
      "default": "",
      "validation": {
        "pattern": "^[a-zA-Z0-9_]+$",
        "max_length": 64
      }
    },
    {
      "name": "business_domain",
      "type": "select",
      "description": "Focus area for generated questions",
      "required": true,
      "options": [
        {"value": "inventory_management", "label": "Inventory Management"},
        {"value": "sales_analysis", "label": "Sales Analysis"},
        {"value": "procurement", "label": "Procurement & Restocking"}
      ],
      "default": "inventory_management"
    },
    {
      "name": "complexity_level",
      "type": "select",
      "description": "SQL query difficulty level",
      "required": false,
      "options": [
        {"value": "beginner", "label": "Beginner (Simple SELECT)"},
        {"value": "intermediate", "label": "Intermediate (Joins, Aggregations)"},
        {"value": "advanced", "label": "Advanced (Subqueries, CTEs)"}
      ],
      "default": "intermediate"
    }
  ],

  "output_configuration": {
    "fields": [
      {
        "name": "question",
        "type": "text",
        "description": "Natural language business question",
        "required": true,
        "searchable": true
      },
      {
        "name": "sql_statement",
        "type": "code",
        "description": "SQL query to answer the question",
        "required": true,
        "language": "sql"
      },
      {
        "name": "category",
        "type": "string",
        "description": "Business domain category",
        "required": true,
        "indexed": true
      },
      {
        "name": "complexity",
        "type": "string",
        "description": "Query difficulty level",
        "required": false,
        "indexed": true
      },
      {
        "name": "database_name",
        "type": "string",
        "description": "Target database for query",
        "required": true,
        "indexed": true
      }
    ],
    "display_format": "**Q:** {question}\n\n**SQL:**\n```sql\n{sql_statement}\n```\n\n**Category:** {category} | **Complexity:** {complexity}"
  },

  "population_modes": {
    "manual": {
      "supported": true,
      "description": "Manually enter questions and SQL queries",
      "required_fields": ["question", "sql_statement", "database_name"],
      "ui_hints": {
        "question": "Enter a business question in natural language",
        "sql_statement": "Provide the SQL query that answers this question"
      }
    },

    "auto_generate": {
      "supported": true,
      "description": "Automatically generate questions from database schema using LLM",
      "requires_llm": true,
      "requires_mcp_context": true,
      "input_method": "mcp_context",
      "generation_endpoint": "/api/v1/rag/generate-questions-from-documents",

      "mcp_requirements": {
        "tools": ["base_getSchema", "base_listTables"],
        "description": "MCP server must provide database schema introspection"
      },

      "prompt_templates": {
        "system_role": "You are an expert SQL analyst and business intelligence specialist. Your role is to generate insightful, practical business questions that can be answered using SQL queries against a relational database.",

        "task_description": "Generate natural language business questions with corresponding SQL queries for product inventory analysis. Focus on actionable insights that help sales, procurement, and operations teams make data-driven decisions.",

        "requirements": [
          "Each question must be clear, specific, and answerable with a SQL query",
          "SQL queries must be valid, efficient, and follow best practices",
          "Cover diverse scenarios: low stock, high-value items, category trends, supplier analysis",
          "Include a mix of complexity levels: simple SELECT, aggregations with GROUP BY, joins across tables",
          "Questions should be business-focused, not technical SQL exercises"
        ],

        "output_format": "Return a JSON array of objects with fields: question (string), sql_statement (string), category (string), complexity (string), database_name (string)",

        "critical_guidelines": [
          "DO NOT generate duplicate questions (check for semantic similarity)",
          "DO NOT use placeholder values - use actual table/column names from schema",
          "DO validate that referenced tables/columns exist in the provided schema",
          "DO ensure SQL queries are executable (proper syntax, valid joins)"
        ]
      }
    }
  },

  "metadata": {
    "category": "business_intelligence",
    "difficulty": "intermediate",
    "estimated_tokens": {
      "per_question": 150,
      "batch_size": 20,
      "total_for_100": 15000
    },
    "tags": ["inventory", "sql", "ecommerce", "product_management"]
  },

  "ui_config": {
    "icon": "📦",
    "color": "#3B82F6",
    "preview_fields": ["question", "category", "complexity"],
    "sort_by": "category"
  }
}
```

**Key Decisions:**
- **template_type**: `sql_query` (inherits planner template structure)
- **repository_type**: `planner` (for execution strategies)
- **requires_mcp_context**: `true` (needs database schema)
- **generation_endpoint**: REST API endpoint for LLM-assisted generation

### Step 7: Create product_inventory_v1.json

**File:** `rag_templates/templates/product-inventory-queries/product_inventory_v1.json`

```json
{
  "template_id": "product_inventory_v1",
  "template_type": "sql_query",
  "template_version": "1.0.0",
  "description": "Planner template for product inventory queries with business intelligence focus",

  "input_variables": [
    {
      "name": "question",
      "type": "text",
      "description": "Natural language business question",
      "required": true
    },
    {
      "name": "sql_statement",
      "type": "code",
      "description": "SQL query to execute",
      "required": true
    },
    {
      "name": "database_name",
      "type": "string",
      "description": "Target database name",
      "required": true
    },
    {
      "name": "category",
      "type": "string",
      "description": "Business domain category",
      "required": false,
      "default": "general"
    },
    {
      "name": "complexity",
      "type": "string",
      "description": "Query complexity level",
      "required": false,
      "default": "intermediate"
    }
  ],

  "output_configuration": {
    "type": "structured",
    "format": "json",
    "fields": [
      {
        "name": "question",
        "source": "input.question",
        "transformations": ["trim"]
      },
      {
        "name": "sql_statement",
        "source": "input.sql_statement",
        "transformations": ["trim", "normalize_whitespace"]
      },
      {
        "name": "category",
        "source": "input.category",
        "transformations": ["lowercase"]
      },
      {
        "name": "complexity",
        "source": "input.complexity",
        "transformations": ["lowercase"]
      },
      {
        "name": "database_name",
        "source": "input.database_name",
        "transformations": ["trim"]
      },
      {
        "name": "sql_preview",
        "source": "input.sql_statement",
        "transformations": ["truncate:50", "uppercase"]
      }
    ]
  },

  "goal_variables": [
    {
      "name": "business_context",
      "value_template": "Business Question: {question}",
      "description": "User's natural language question"
    },
    {
      "name": "database_context",
      "value_template": "Target Database: {database_name}",
      "description": "Database identifier",
      "condition": "if database_name"
    },
    {
      "name": "category_context",
      "value_template": "Category: {category}",
      "description": "Business domain focus",
      "condition": "if category"
    }
  ],

  "strategy_template": {
    "phase_count": 2,
    "description": "Two-phase execution: SQL query execution followed by report generation",

    "phases": [
      {
        "phase": 1,
        "goal_template": "Execute SQL query for {category} analysis: {sql_preview}",
        "goal_variables": ["business_context", "database_context", "category_context"],
        "description": "Execute the SQL query against the target database",

        "relevant_tools_source": "mcp_tool_name",
        "mcp_tool_name": "base_readQuery",
        "tool_category": "database_query",

        "arguments": {
          "sql": {
            "source": "sql_statement",
            "description": "SQL query to execute",
            "validation": {
              "required": true,
              "type": "string",
              "min_length": 10
            }
          },
          "database": {
            "source": "database_name",
            "description": "Target database",
            "validation": {
              "required": false,
              "type": "string"
            }
          }
        },

        "expected_output": {
          "type": "table",
          "description": "Query results as tabular data"
        },

        "error_handling": {
          "retry_on_failure": true,
          "max_retries": 2,
          "fallback_action": "Report SQL syntax error to user"
        }
      },

      {
        "phase": 2,
        "goal": "Generate a formatted business intelligence report from query results",
        "description": "Transform raw query results into actionable business insights",

        "relevant_tools": ["TDA_FinalReport"],
        "tool_category": "reporting",

        "arguments": {
          "report_content": {
            "source": "phase_1_results",
            "description": "Data from Phase 1 SQL execution"
          },
          "format": {
            "value": "markdown",
            "description": "Output format for report"
          }
        },

        "expected_output": {
          "type": "formatted_text",
          "description": "Markdown-formatted business report"
        }
      }
    ]
  },

  "metadata_extraction": {
    "extractors": [
      {
        "field": "database_name",
        "pattern": "(?i)(?:database|db)\\s*:?\\s*([a-zA-Z0-9_]+)",
        "description": "Extract database name from question or SQL"
      },
      {
        "field": "table_names",
        "pattern": "(?i)FROM\\s+([a-zA-Z0-9_]+)",
        "multiple": true,
        "description": "Extract table names from SQL query"
      },
      {
        "field": "has_aggregation",
        "pattern": "(?i)(COUNT|SUM|AVG|MIN|MAX|GROUP BY)",
        "type": "boolean",
        "description": "Detect if query uses aggregation"
      }
    ]
  },

  "validation_rules": [
    {
      "rule": "sql_not_empty",
      "field": "sql_statement",
      "type": "not_empty",
      "error_message": "SQL statement cannot be empty"
    },
    {
      "rule": "question_not_empty",
      "field": "question",
      "type": "not_empty",
      "error_message": "Question cannot be empty"
    },
    {
      "rule": "sql_has_select",
      "field": "sql_statement",
      "type": "pattern",
      "pattern": "(?i)^\\s*SELECT",
      "error_message": "SQL statement must start with SELECT"
    },
    {
      "rule": "no_destructive_operations",
      "field": "sql_statement",
      "type": "not_pattern",
      "pattern": "(?i)(DROP|DELETE|TRUNCATE|ALTER|CREATE|INSERT|UPDATE)",
      "error_message": "Only SELECT queries are allowed for safety"
    }
  ],

  "usage_examples": [
    {
      "title": "Basic Inventory Query",
      "input": {
        "question": "Which products have less than 10 units in stock?",
        "sql_statement": "SELECT name, quantity, category FROM products WHERE quantity < 10 ORDER BY quantity ASC;",
        "database_name": "ecommerce_prod",
        "category": "inventory_management",
        "complexity": "beginner"
      },
      "expected_output": "Formatted report showing low-stock products"
    },
    {
      "title": "Category Analysis with Aggregation",
      "input": {
        "question": "What is the total inventory value by product category?",
        "sql_statement": "SELECT c.name AS category, SUM(p.price * p.quantity) AS total_value FROM products p JOIN categories c ON p.category_id = c.id GROUP BY c.name ORDER BY total_value DESC;",
        "database_name": "ecommerce_prod",
        "category": "sales_analysis",
        "complexity": "intermediate"
      },
      "expected_output": "Report with category-wise inventory valuation"
    }
  ]
}
```

**Key Components:**
- **strategy_template**: 2-phase execution (SQL query → Report generation)
- **goal_variables**: Conditional context injection based on input
- **metadata_extraction**: Automatic extraction of database/table names via regex
- **validation_rules**: Prevents destructive SQL operations (DROP, DELETE, etc.)

### Step 8: Create README.md

**File:** `rag_templates/templates/product-inventory-queries/README.md`

```markdown
# Product Inventory Queries Template

**Template ID:** `product_inventory_v1`
**Version:** 1.0.0
**Category:** Business Intelligence
**Repository Type:** Planner

## Overview

This template generates business intelligence questions about product inventory, stock levels, and category analysis. It's designed for eCommerce platforms, retail systems, or any application with product catalog management.

## Use Cases

- **Inventory Management**: Identify low-stock products, overstock situations
- **Sales Analysis**: Analyze product performance by category, price range
- **Procurement**: Generate restocking reports, supplier analysis
- **Business Intelligence**: Trend analysis, seasonal patterns

## Prerequisites

### MCP Server Requirements

This template requires an MCP server with database introspection capabilities:

**Required Tools:**
- `base_readQuery` - Execute SELECT queries
- `base_getSchema` - Retrieve table schema (for auto-generation)
- `base_listTables` - List available tables (for auto-generation)

**Example MCP Server:**
- PostgreSQL MCP Server
- MySQL MCP Server
- SQLite MCP Server

### Database Schema Requirements

Your database should contain product-related tables. Typical schema:

```sql
-- Products table
CREATE TABLE products (
    id INT PRIMARY KEY,
    name VARCHAR(255),
    price DECIMAL(10,2),
    quantity INT,
    category_id INT,
    supplier_id INT,
    created_at TIMESTAMP
);

-- Categories table
CREATE TABLE categories (
    id INT PRIMARY KEY,
    name VARCHAR(100),
    parent_id INT
);

-- Suppliers table (optional)
CREATE TABLE suppliers (
    id INT PRIMARY KEY,
    name VARCHAR(255),
    contact_email VARCHAR(255)
);
```

## Population Modes

### 1. Manual Population

**When to use:** Custom questions for specific business needs

**Steps:**
1. Navigate to Setup → RAG Collections
2. Click "Create New Collection"
3. Select "Product Inventory Queries" template
4. Choose "Manual" population mode
5. Fill in form for each question:
   - Question: "Which products are running low on stock?"
   - SQL Statement: `SELECT * FROM products WHERE quantity < 10`
   - Database Name: `ecommerce_prod`
   - Category: `inventory_management`
   - Complexity: `beginner`
6. Click "Add Entry" for each question
7. Click "Create Collection" when done

**Best For:** 5-20 highly curated questions

### 2. Auto-Generate (LLM-Assisted)

**When to use:** Generate 50-100+ questions automatically

**Steps:**
1. Navigate to Setup → RAG Collections
2. Click "Create New Collection"
3. Select "Product Inventory Queries" template
4. Choose "Auto-Generate" population mode
5. Configure generation:
   - Database Name: `ecommerce_prod`
   - Business Domain: `inventory_management`
   - Complexity Level: `intermediate`
   - Number of Questions: `50`
6. Click "Generate Questions"
7. Wait 30-60 seconds for LLM to generate questions
8. Review generated questions (auto-scroll to preview)
9. Click "Create Collection" to save

**Best For:** Comprehensive question sets, rapid prototyping

**Generation Process:**
- LLM retrieves database schema via MCP tools
- Analyzes table/column names, data types, relationships
- Generates diverse, non-duplicate questions
- Produces valid SQL queries using actual schema
- Batches generation (20 questions per batch) to avoid token limits

## Output Structure

Each generated entry contains:

```json
{
  "question": "Which products have less than 10 units in stock?",
  "sql_statement": "SELECT name, quantity FROM products WHERE quantity < 10 ORDER BY quantity ASC;",
  "category": "inventory_management",
  "complexity": "beginner",
  "database_name": "ecommerce_prod"
}
```

**Searchable Fields:**
- `question` - Semantic search for relevant questions
- `category` - Filter by business domain
- `complexity` - Filter by skill level
- `database_name` - Filter by target database

## Integration with Profiles

### RAG-Focused Profile

Create a profile that uses this collection for question-answering:

1. Navigate to Setup → Profiles
2. Create new profile: "Product Inventory Assistant"
3. Profile Type: `rag_focused` (Knowledge Focused)
4. Knowledge Configuration:
   - Primary Collection: "Product Inventory Queries"
   - Retrieval Strategy: `semantic_search`
   - Top K Results: `3`
5. Save profile

**Usage:**
```
User: "Show me products that need restocking"
System: [Retrieves top 3 similar questions from collection]
         [Synthesizes answer using retrieved SQL queries]
```

### Tool-Enabled Profile (Advanced)

Use collection as champion cases for planner optimization:

1. Navigate to Setup → Profiles
2. Edit existing tool-enabled profile
3. Advanced Configuration:
   - Enable RAG Retrieval: ✅
   - Planner Collection: "Product Inventory Queries"
   - Retrieval Strategy: `champion_cases`
4. Save profile

**Usage:**
```
User: "Which products have low inventory?"
System: [Retrieves similar past queries from collection]
         [Uses champion case as template for strategic plan]
         [Adapts SQL query for current context]
         [Executes optimized query via MCP]
```

## Examples

### Example 1: Low Stock Alert

**Question:** "Which products have less than 10 units in stock?"

**SQL:**
```sql
SELECT
    name,
    quantity,
    category
FROM products
WHERE quantity < 10
ORDER BY quantity ASC;
```

**Category:** inventory_management
**Complexity:** beginner

### Example 2: Category Value Analysis

**Question:** "What is the total inventory value by product category?"

**SQL:**
```sql
SELECT
    c.name AS category,
    COUNT(p.id) AS product_count,
    SUM(p.price * p.quantity) AS total_value
FROM products p
JOIN categories c ON p.category_id = c.id
GROUP BY c.name
ORDER BY total_value DESC;
```

**Category:** sales_analysis
**Complexity:** intermediate

### Example 3: Supplier Stock Overview

**Question:** "Show inventory levels grouped by supplier with low-stock alerts"

**SQL:**
```sql
SELECT
    s.name AS supplier,
    COUNT(p.id) AS total_products,
    SUM(CASE WHEN p.quantity < 10 THEN 1 ELSE 0 END) AS low_stock_count,
    SUM(p.quantity) AS total_units
FROM products p
JOIN suppliers s ON p.supplier_id = s.id
GROUP BY s.name
HAVING low_stock_count > 0
ORDER BY low_stock_count DESC;
```

**Category:** procurement
**Complexity:** advanced

## Troubleshooting

### Issue: "MCP tools not found"

**Cause:** Profile not connected to MCP server with database tools

**Solution:**
1. Check profile's MCP server configuration
2. Verify MCP server is running
3. Test MCP connection: Setup → MCP Servers → Test Connection

### Issue: "SQL syntax error during generation"

**Cause:** LLM generated invalid SQL for your database dialect

**Solution:**
1. Review generated questions before creating collection
2. Manually fix SQL syntax errors
3. Or regenerate with more specific prompt (edit `prompt_templates` in manifest)

### Issue: "No results retrieved during query"

**Cause:** Semantic search not finding relevant questions

**Solution:**
1. Increase Top K Results in profile configuration (try 5-10)
2. Add more diverse questions to collection
3. Use more descriptive natural language in user query

## Version History

- **1.0.0** (2026-02-06): Initial release
  - 2-phase execution (query → report)
  - Support for manual and auto-generation
  - Metadata extraction for category/complexity
  - SQL validation (prevents destructive operations)

## License

MIT License - Free for commercial and personal use

## Support

For issues or questions:
- Check `docs/RAG_Templates/TROUBLESHOOTING.md`
- Review `rag_templates/PLUGIN_MANIFEST_SCHEMA.md`
- Contact: support@yourcompany.com
```

### Step 9: Add to Template Registry

**File:** `rag_templates/template_registry.json`

**Add this entry:**

```json
{
  "product-inventory-queries": {
    "template_id": "product_inventory_v1",
    "plugin_directory": "templates/product-inventory-queries",
    "template_file": "product_inventory_v1.json",
    "manifest_file": "manifest.json",
    "status": "active",
    "display_order": 5,
    "category": "business_intelligence",
    "is_builtin": true,
    "description": "Generate business intelligence questions about product inventory and stock levels",
    "icon": "📦",
    "tags": ["inventory", "sql", "ecommerce"]
  }
}
```

**Field Explanation:**
- `display_order: 5` - Shows after default templates (1-4)
- `status: "active"` - Visible in UI immediately
- `is_builtin: true` - System template (vs. user template)
- `category: "business_intelligence"` - Groups with similar templates

---

## Testing Phase

### Step 10: Validate JSON Schemas

**Validate manifest.json:**

```bash
# Install JSON schema validator (if not installed)
pip install jsonschema

# Create validation script
cat > validate_template.py << 'EOF'
import json
from jsonschema import validate, ValidationError

# Load manifest
with open('rag_templates/templates/product-inventory-queries/manifest.json') as f:
    manifest = json.load(f)

# Basic validation checks
required_fields = ['name', 'template_id', 'template_type', 'input_variables', 'output_configuration', 'population_modes']

for field in required_fields:
    if field not in manifest:
        print(f"❌ Missing required field: {field}")
    else:
        print(f"✅ Found field: {field}")

# Validate input variables
for var in manifest['input_variables']:
    required_var_fields = ['name', 'type', 'description', 'required']
    for field in required_var_fields:
        if field not in var:
            print(f"❌ Input variable '{var.get('name', 'unknown')}' missing field: {field}")

print("\n✅ Manifest validation complete!")
EOF

python validate_template.py
```

**Expected Output:**
```
✅ Found field: name
✅ Found field: template_id
✅ Found field: template_type
✅ Found field: input_variables
✅ Found field: output_configuration
✅ Found field: population_modes
✅ Manifest validation complete!
```

**Validate template.json:**

```bash
# Check template structure
cat > validate_template_json.py << 'EOF'
import json

with open('rag_templates/templates/product-inventory-queries/product_inventory_v1.json') as f:
    template = json.load(f)

# Validate strategy template
if 'strategy_template' not in template:
    print("❌ Missing strategy_template")
else:
    strategy = template['strategy_template']
    print(f"✅ Found strategy_template with {strategy['phase_count']} phases")

    # Validate phases
    for i, phase in enumerate(strategy['phases'], 1):
        print(f"  Phase {i}: {phase.get('description', 'No description')}")

        # Check arguments
        if 'arguments' in phase:
            print(f"    Arguments: {', '.join(phase['arguments'].keys())}")

print("\n✅ Template JSON validation complete!")
EOF

python validate_template_json.py
```

**Expected Output:**
```
✅ Found strategy_template with 2 phases
  Phase 1: Execute the SQL query against the target database
    Arguments: sql, database
  Phase 2: Transform raw query results into actionable business insights
    Arguments: report_content, format
✅ Template JSON validation complete!
```

### Step 11: Test Manual Population

**Via Web UI:**

1. Start application:
```bash
python -m trusted_data_agent.main
```

2. Navigate to `http://localhost:5050`

3. Login with admin credentials: `admin` / `admin`

4. Go to: **Setup → RAG Collections**

5. Click **"Create New Collection"**

6. Select **"Product Inventory Queries"** template

7. Choose **"Manual"** population mode

8. Fill in first question:
   - **Question:** "Which products have less than 10 units in stock?"
   - **SQL Statement:** `SELECT name, quantity FROM products WHERE quantity < 10 ORDER BY quantity ASC;`
   - **Database Name:** `ecommerce_prod`
   - **Category:** `inventory_management`
   - **Complexity:** `beginner`

9. Click **"Add Entry"**

10. Add 2-3 more questions

11. Click **"Create Collection"**

**Expected Result:**
- ✅ Collection created successfully
- ✅ All questions visible in collection preview
- ✅ No validation errors

**Screenshot Placeholder:**
```
[Screenshot: Manual population form with filled-in fields]
[Screenshot: Collection preview showing 3 questions]
```

### Step 12: Test LLM-Assisted Generation

**Prerequisites:**
1. MCP server must be running and connected
2. LLM configuration must be active (e.g., Google Gemini, Claude)
3. Profile must have access to MCP tools

**Via Web UI:**

1. Go to: **Setup → RAG Collections**

2. Click **"Create New Collection"**

3. Select **"Product Inventory Queries"** template

4. Choose **"Auto-Generate"** population mode

5. Configure generation parameters:
   - **Database Name:** `ecommerce_prod`
   - **Business Domain:** `inventory_management`
   - **Complexity Level:** `intermediate`
   - **Number of Questions:** `20` (start small for testing)

6. Click **"Generate Questions"**

7. **Wait 30-45 seconds** (progress indicator should show)

8. **Review generated questions:**
   - Check for duplicates
   - Verify SQL syntax
   - Ensure questions are relevant to business domain

9. If satisfied, click **"Create Collection"**

**Expected Output (Console Logs):**
```
[INFO] Starting question generation: 20 questions requested
[INFO] Batch 1/1: Generating 20 questions
[INFO] Retrieved database schema: 3 tables (products, categories, suppliers)
[INFO] LLM generation complete: 20 questions generated
[INFO] Deduplication: 20 unique questions (0 duplicates removed)
[INFO] Collection created: product_inventory_queries_20260206
```

**Sample Generated Questions:**
```json
[
  {
    "question": "Which products have less than 10 units in stock?",
    "sql_statement": "SELECT name, quantity, category FROM products WHERE quantity < 10 ORDER BY quantity ASC;",
    "category": "inventory_management",
    "complexity": "beginner"
  },
  {
    "question": "What is the total inventory value by product category?",
    "sql_statement": "SELECT c.name AS category, SUM(p.price * p.quantity) AS total_value FROM products p JOIN categories c ON p.category_id = c.id GROUP BY c.name ORDER BY total_value DESC;",
    "category": "sales_analysis",
    "complexity": "intermediate"
  }
]
```

**Screenshot Placeholder:**
```
[Screenshot: Auto-generate form with parameters filled]
[Screenshot: Generation progress indicator]
[Screenshot: Generated questions preview (20 questions)]
```

### Step 13: Validate Generated Data

**Check for Common Issues:**

**1. Duplicate Questions:**
```bash
# Export collection as JSON
curl -X GET "http://localhost:5050/api/v1/rag/collections/<collection_id>/export" \
  -H "Authorization: Bearer $JWT" > collection_export.json

# Check for duplicate questions
cat collection_export.json | jq -r '.entries[].question' | sort | uniq -d
```

**Expected:** No output (no duplicates)

**2. SQL Syntax Validation:**
```bash
# Extract all SQL queries
cat collection_export.json | jq -r '.entries[].sql_statement' > all_queries.sql

# Validate SQL (requires database connection)
psql -d ecommerce_prod -f all_queries.sql --dry-run
```

**Expected:** No syntax errors

**3. Metadata Completeness:**
```bash
# Check all entries have required fields
cat collection_export.json | jq '.entries[] | select(.question == null or .sql_statement == null or .database_name == null)'
```

**Expected:** No output (all entries complete)

---

## Deployment Phase

### Step 14: Restart Application

**Hot Reload (Recommended):**

```bash
# Call reload endpoint (requires admin JWT token)
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
  -H "Authorization: Bearer $JWT"
```

**Expected Response:**
```json
{
  "status": "success",
  "message": "Templates reloaded successfully",
  "templates_count": 6,
  "new_templates": ["product-inventory-queries"]
}
```

**Full Restart (Alternative):**

```bash
# Stop application
pkill -f "python -m trusted_data_agent.main"

# Restart
python -m trusted_data_agent.main
```

**Verification:**
- Check logs for: `✅ Loaded template: product-inventory-queries`
- Navigate to UI: Setup → RAG Collections → Template should appear in dropdown

### Step 15: Create Collection in UI

**Steps:**

1. **Navigate:** Setup → RAG Collections

2. **Click:** "Create New Collection"

3. **Select Template:** "Product Inventory Queries" (should now appear in dropdown with 📦 icon)

4. **Choose Population Mode:** Auto-Generate

5. **Configure:**
   - **Collection Name:** "Product Inventory - Prod Database"
   - **Database Name:** `ecommerce_prod`
   - **Business Domain:** `inventory_management`
   - **Complexity Level:** `intermediate`
   - **Number of Questions:** `50`

6. **Generate Questions:** Click "Generate Questions" and wait

7. **Review:** Scroll through generated questions (should auto-scroll to preview)

8. **Create:** Click "Create Collection"

**Expected Result:**
- ✅ Collection created with 50 questions
- ✅ Collection visible in collections list
- ✅ Preview shows first 5-10 questions

**Screenshot Placeholder:**
```
[Screenshot: Template dropdown showing new template with icon]
[Screenshot: Collection creation success message]
[Screenshot: Collections list with new collection]
```

### Step 16: Integrate with Profile

**Create RAG-Focused Profile:**

1. **Navigate:** Setup → Profiles

2. **Click:** "Create New Profile"

3. **Configure:**
   - **Profile Name:** "Product Inventory Assistant"
   - **Profile Tag:** `INVENTORY`
   - **Profile Type:** `rag_focused` (Knowledge Focused)
   - **Description:** "Answers questions about product inventory using RAG collection"

4. **Knowledge Configuration:**
   - **Primary Collection:** "Product Inventory - Prod Database"
   - **Retrieval Strategy:** `semantic_search`
   - **Top K Results:** `3`
   - **Min Similarity:** `0.6`

5. **LLM Configuration:**
   - **Provider:** Google (or your preferred provider)
   - **Model:** `gemini-2.0-flash-exp`

6. **Save Profile**

7. **Set as Default** (optional): Click "Set as Default" button

**Screenshot Placeholder:**
```
[Screenshot: Profile creation form with RAG configuration]
[Screenshot: Knowledge Configuration section with collection selected]
```

### Step 17: Test Retrieval

**Via Web UI (Interactive):**

1. **Create New Session:** Click "New Session" button

2. **Use Profile:** If not default, type `@INVENTORY` at start of query

3. **Submit Query:** "Show me products that need restocking"

4. **Observe Execution:**
   - Live Status window shows: "Retrieving champion cases from RAG collection"
   - Should display: "Retrieved 3 champion cases"
   - Response synthesizes answer using retrieved SQL queries

5. **Verify Results:**
   - Check that response includes specific product names
   - Verify SQL queries were executed
   - Confirm data comes from your database

**Expected Console Logs:**
```
[INFO] RAG retrieval started: collection=product_inventory_queries, query="Show me products that need restocking"
[INFO] Semantic search: 3 results with similarity > 0.6
[INFO] Retrieved champion cases:
  - "Which products have less than 10 units in stock?" (similarity: 0.92)
  - "What items need immediate restocking?" (similarity: 0.87)
  - "Show low inventory alerts by category" (similarity: 0.81)
[INFO] Executing SQL from champion case #1
[INFO] Query returned 7 products
```

**Screenshot Placeholder:**
```
[Screenshot: Chat interface with @INVENTORY query]
[Screenshot: Live Status showing RAG retrieval progress]
[Screenshot: Response with product data]
```

**Via REST API (Programmatic):**

```bash
# Create session with INVENTORY profile
SESSION_RESPONSE=$(curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "profile_tag": "INVENTORY"
  }')

SESSION_ID=$(echo "$SESSION_RESPONSE" | jq -r '.session_id')

# Submit query
TASK_RESPONSE=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Show me products that need restocking"
  }')

TASK_ID=$(echo "$TASK_RESPONSE" | jq -r '.task_id')

# Wait for completion
sleep 5

# Get results
curl -s -X GET "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT" | jq '.events[] | select(.event_type == "champion_cases_retrieved")'
```

**Expected Output:**
```json
{
  "event_type": "champion_cases_retrieved",
  "event_data": {
    "collection_id": "product_inventory_queries",
    "query": "Show me products that need restocking",
    "results_count": 3,
    "champion_cases": [
      {
        "question": "Which products have less than 10 units in stock?",
        "similarity": 0.92,
        "sql_statement": "SELECT name, quantity FROM products WHERE quantity < 10..."
      }
    ]
  }
}
```

---

## Troubleshooting

### Common Errors During Creation

#### Error: "Template JSON does not match schema for type 'sql_query'"

**Cause:** Template structure doesn't conform to planner template schema

**Solution:**
1. Validate `strategy_template` has required fields:
   - `phase_count` (integer)
   - `phases` (array)
2. Each phase must have:
   - `phase` (integer)
   - `goal` or `goal_template` (string)
   - `relevant_tools` or `relevant_tools_source` (array or string)
3. Compare against working example: `rag_templates/templates/sql-query-basic/sql_query_v1.json`

**Example Fix:**
```json
// ❌ WRONG
{
  "strategy_template": {
    "steps": [...]  // Should be "phases", not "steps"
  }
}

// ✅ CORRECT
{
  "strategy_template": {
    "phase_count": 2,
    "phases": [...]
  }
}
```

#### Error: "MCP tool 'base_readQuery' not found"

**Cause:** Profile not connected to MCP server or MCP server doesn't provide required tool

**Solution:**
1. Check MCP server configuration:
   - Setup → MCP Servers
   - Verify server is running (green status indicator)
   - Click "Test Connection"
2. Check tool availability:
   - Click "View Capabilities" on MCP server
   - Verify `base_readQuery` is listed under Tools
3. Update profile:
   - Setup → Profiles → Edit profile
   - Ensure correct MCP server selected

#### Error: "LLM generation failed: Output too long"

**Cause:** Requested too many questions at once (exceeds LLM output token limit)

**Solution:**
1. Reduce number of questions: Try 20 instead of 100
2. Or wait for batched generation (automatic if backend supports it)
3. Check backend logs for: `Batch 1/5: Generating 20 questions`

**Verification:**
```bash
# Check if batching is enabled
grep -r "BATCH_SIZE" src/trusted_data_agent/api/rest_routes.py
# Should show: BATCH_SIZE = 20
```

#### Error: "SQL syntax error: Table 'product' doesn't exist"

**Cause:** LLM generated SQL with incorrect table name (should be `products`, plural)

**Solution:**
1. **Immediate fix:** Manually edit generated question in UI before creating collection
2. **Long-term fix:** Improve prompt template in manifest.json:
```json
{
  "prompt_templates": {
    "critical_guidelines": [
      "DO NOT use placeholder table names - use EXACT table names from schema",
      "VALIDATE that all referenced tables exist in schema before generating SQL",
      "PREFER plural table names (products, orders, customers) over singular"
    ]
  }
}
```

### Common Errors During Deployment

#### Error: "Template not found in registry"

**Cause:** Template registry not reloaded after adding new template

**Solution:**
```bash
# Reload template registry
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
  -H "Authorization: Bearer $JWT"
```

**Verify:**
```bash
# List all templates
curl -X GET http://localhost:5050/api/v1/rag/templates \
  -H "Authorization: Bearer $JWT" | jq '.templates[] | .template_id'
```

**Expected Output:**
```
"sql_query_v1"
"product_inventory_v1"
...
```

#### Error: "Collection created but retrieval returns 0 results"

**Cause:** Collection created successfully but RAG retrieval not finding matches

**Debugging Steps:**

1. **Check collection has data:**
```bash
curl -X GET "http://localhost:5050/api/v1/rag/collections/<collection_id>" \
  -H "Authorization: Bearer $JWT" | jq '.entry_count'
# Should show: 50 (or your question count)
```

2. **Check ChromaDB embedding:**
```bash
# Check server logs for embedding creation
grep "Creating embeddings for collection" logs/app.log
```

3. **Test semantic search directly:**
```bash
curl -X POST "http://localhost:5050/api/v1/rag/collections/<collection_id>/search" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "low stock products",
    "top_k": 3
  }' | jq '.results'
```

4. **Lower similarity threshold:**
   - Setup → Profiles → Edit INVENTORY profile
   - Change "Min Similarity" from 0.6 to 0.4
   - Save and test again

### Common Errors During Retrieval

#### Error: "Profile uses wrong collection"

**Cause:** Profile configured with different collection than expected

**Solution:**
1. Navigate: Setup → Profiles
2. Edit profile: Click pencil icon
3. Knowledge Configuration section:
   - **Primary Collection:** Select "Product Inventory - Prod Database"
4. Save profile
5. Test again

#### Error: "RAG retrieval skipped"

**Cause:** Profile type doesn't support RAG retrieval

**Solution:**
1. Check profile type:
   - Setup → Profiles → View profile
   - Verify "Profile Type" is `rag_focused`
2. If `llm_only`:
   - Either change to `rag_focused`
   - Or change to `tool_enabled` and enable RAG retrieval in Advanced Configuration

**Profile Type Comparison:**

| Profile Type | RAG Retrieval | Use Case |
|--------------|---------------|----------|
| `rag_focused` | ✅ Always enabled | Pure knowledge retrieval + LLM synthesis |
| `tool_enabled` | ⚙️ Optional (champion cases) | Execution optimization via proven patterns |
| `llm_only` | ❌ Not supported | Pure conversation, no retrieval |

---

## Advanced Customization

### Modify Generation Prompt

**To customize how questions are generated**, edit `prompt_templates` in manifest.json:

**Example: Focus on procurement questions**

```json
{
  "prompt_templates": {
    "task_description": "Generate procurement-focused questions for inventory restocking, supplier management, and purchase order optimization. Questions should help procurement teams make data-driven purchasing decisions.",

    "requirements": [
      "Each question must relate to procurement operations",
      "Include supplier analysis, reorder point calculations, and lead time optimization",
      "SQL queries should join products with suppliers table",
      "Focus on actionable insights for purchasing decisions"
    ]
  }
}
```

### Add Custom Validation Rules

**To prevent certain SQL patterns**, add validation rules to template.json:

```json
{
  "validation_rules": [
    {
      "rule": "no_cross_database_queries",
      "field": "sql_statement",
      "type": "not_pattern",
      "pattern": "(?i)(USE\\s+|FROM\\s+[a-zA-Z0-9_]+\\.[a-zA-Z0-9_]+\\.)",
      "error_message": "Cross-database queries are not allowed"
    },
    {
      "rule": "must_use_products_table",
      "field": "sql_statement",
      "type": "pattern",
      "pattern": "(?i)FROM\\s+products",
      "error_message": "All queries must reference the products table"
    }
  ]
}
```

### Add Custom Metadata Extractors

**To extract additional metadata from SQL**, add extractors to template.json:

```json
{
  "metadata_extraction": {
    "extractors": [
      {
        "field": "uses_window_functions",
        "pattern": "(?i)(ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD)\\s*\\(",
        "type": "boolean",
        "description": "Detect advanced window function usage"
      },
      {
        "field": "estimated_complexity_score",
        "pattern": "(?i)(JOIN|GROUP BY|HAVING|SUBQUERY|WITH)",
        "type": "count",
        "description": "Count complexity indicators (higher = more complex)"
      }
    ]
  }
}
```

---

## Best Practices

### Question Quality

1. **Be specific:** "Which products have less than 10 units?" vs. "Low inventory products?"
2. **Include context:** "What is the total inventory VALUE..." vs. "What is the total inventory..."
3. **Use business terminology:** "Restocking recommendations" vs. "Products with quantity less than threshold"
4. **Vary complexity:** Mix simple SELECT with complex JOIN queries

### SQL Safety

1. **Read-only queries:** Only SELECT statements (no INSERT, UPDATE, DELETE)
2. **Avoid expensive operations:** No `SELECT *` on million-row tables without WHERE clause
3. **Use appropriate indexes:** Ensure WHERE clause columns are indexed in database
4. **Test before deployment:** Validate all SQL queries against actual database

### Collection Management

1. **Start small:** Create 20-50 questions first, validate quality, then scale to 100+
2. **Version collections:** "Product Inventory v1.0", "Product Inventory v1.1" for iterations
3. **Archive old collections:** Don't delete, mark as archived for rollback capability
4. **Monitor retrieval accuracy:** Check RAG retrieval logs for low similarity scores

### Profile Configuration

1. **Tune similarity threshold:** Start at 0.6, lower to 0.4 if too few results, raise to 0.75 for stricter matches
2. **Adjust Top K:** Use 3-5 for RAG-focused, 1-2 for champion cases
3. **Test with diverse queries:** Try synonyms, paraphrasing, different terminology
4. **Provide fallback:** Configure fallback response if no results found

---

## Next Steps

### Extend This Template

1. **Add more categories:**
   - Edit `business_domain` options in manifest.json
   - Add: `customer_analysis`, `shipping_logistics`, `pricing_optimization`

2. **Support multi-database:**
   - Modify `database_name` to support dropdown selection
   - Generate separate collections per database

3. **Add visualization:**
   - Extend Phase 2 to generate chart configurations
   - Use tools like `TDA_GenerateChart` (if available)

### Create Related Templates

1. **Customer Analytics Template:** Questions about customer behavior, purchase history
2. **Sales Performance Template:** Revenue analysis, top products, sales trends
3. **Supplier Management Template:** Supplier performance, lead times, quality metrics

### Integrate with Other Systems

1. **Export to BI Tools:** Use REST API to export collection data to Tableau, Power BI
2. **Automated Reports:** Schedule queries to run daily and email results
3. **Slack Bot Integration:** Allow team members to query inventory via Slack

---

## Summary Checklist

**Before Deployment:**
- [ ] Manifest.json validated (all required fields present)
- [ ] Template.json validated (strategy_template structure correct)
- [ ] README.md created (comprehensive documentation)
- [ ] Template added to registry (correct display_order and status)
- [ ] MCP server configured and tested
- [ ] LLM configuration active

**Testing Completed:**
- [ ] Manual population tested (3+ questions added successfully)
- [ ] Auto-generation tested (20+ questions generated without duplicates)
- [ ] SQL syntax validated (all queries executable)
- [ ] Metadata extraction verified (database_name, category extracted correctly)
- [ ] Validation rules tested (destructive operations blocked)

**Deployment Verified:**
- [ ] Template appears in UI dropdown
- [ ] Collection created successfully (50+ questions)
- [ ] Profile configured with collection
- [ ] RAG retrieval working (3+ champion cases retrieved)
- [ ] End-to-end query successful (question → retrieval → execution → response)

**Documentation Complete:**
- [ ] Template README.md complete with examples
- [ ] TROUBLESHOOTING.md updated with template-specific errors
- [ ] CLAUDE.md updated with template reference
- [ ] Team trained on template usage

---

## Conclusion

You've successfully created a production-ready RAG template! This template:

- ✅ Generates 50+ business intelligence questions automatically
- ✅ Validates SQL for safety (read-only, syntax-checked)
- ✅ Integrates with RAG-focused and tool-enabled profiles
- ✅ Supports both manual and auto-generation workflows
- ✅ Includes comprehensive documentation and troubleshooting

**Key Takeaways:**
1. **Planning is critical:** Choose the right template type and define clear input/output requirements
2. **Test incrementally:** Validate each component (manifest, template, generation) before deployment
3. **Document thoroughly:** README.md prevents 90% of support questions
4. **Monitor retrieval:** Check RAG logs to ensure quality matches are found

**Next Steps:**
- Create more templates for different business domains
- Fine-tune retrieval parameters based on user feedback
- Share templates with team via marketplace (if using Enterprise tier)

For additional support, see:
- [rag_templates/PLUGIN_MANIFEST_SCHEMA.md](../../rag_templates/PLUGIN_MANIFEST_SCHEMA.md) - Schema reference
- [docs/RAG_Templates/TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Error reference (created in Phase 4.8)
- [CLAUDE.md](../../CLAUDE.md) - Developer guide

Happy template building! 🚀
