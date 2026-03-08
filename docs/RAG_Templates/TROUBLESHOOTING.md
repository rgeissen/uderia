# RAG Template Troubleshooting Guide

Comprehensive error reference for diagnosing and fixing template creation, validation, and deployment issues.

---

## Table of Contents

1. [JSON Schema Validation Errors](#json-schema-validation-errors)
2. [Manifest Validation Errors](#manifest-validation-errors)
3. [Template Definition Errors](#template-definition-errors)
4. [MCP Tool Validation Errors](#mcp-tool-validation-errors)
5. [Generation Errors](#generation-errors)
6. [Deployment Errors](#deployment-errors)
7. [Retrieval Errors](#retrieval-errors)
8. [Common Workflows](#common-workflows)

---

## JSON Schema Validation Errors

### Error: "Unexpected token in JSON at position X"

**Full Error Message:**
```
JSONDecodeError: Unexpected token } in JSON at position 1247
```

**Cause:** Invalid JSON syntax (missing comma, unclosed bracket, trailing comma, etc.)

**Common Mistakes:**

```json
// ❌ WRONG: Missing comma between fields
{
  "name": "my-template"
  "version": "1.0.0"
}

// ✅ CORRECT: Comma added
{
  "name": "my-template",
  "version": "1.0.0"
}
```

```json
// ❌ WRONG: Trailing comma in last field
{
  "name": "my-template",
  "version": "1.0.0",
}

// ✅ CORRECT: No trailing comma
{
  "name": "my-template",
  "version": "1.0.0"
}
```

```json
// ❌ WRONG: Unclosed bracket
{
  "phases": [
    {"phase": 1}

}

// ✅ CORRECT: Properly closed
{
  "phases": [
    {"phase": 1}
  ]
}
```

**Solution:**
1. Use a JSON validator: https://jsonlint.com/
2. Use IDE with JSON syntax highlighting (VS Code, Sublime Text)
3. Check the specific position mentioned in error message
4. Validate with command line:
```bash
jq . manifest.json
# If valid, prints formatted JSON
# If invalid, shows specific error
```

---

### Error: "Expected string but got integer"

**Full Error Message:**
```
ValidationError: 'version' expected string but got integer: 1
```

**Cause:** Field type mismatch (string vs number vs boolean)

**Example:**

```json
// ❌ WRONG: version should be string
{
  "version": 1.0
}

// ✅ CORRECT: version as string
{
  "version": "1.0.0"
}
```

```json
// ❌ WRONG: required should be boolean
{
  "input_variables": [
    {
      "name": "database_name",
      "required": "true"  // String instead of boolean
    }
  ]
}

// ✅ CORRECT: boolean value
{
  "input_variables": [
    {
      "name": "database_name",
      "required": true  // Boolean (no quotes)
    }
  ]
}
```

**Common Type Rules:**

| Field | Type | Example |
|-------|------|---------|
| `version` | string | `"1.0.0"` (not `1.0`) |
| `required` | boolean | `true` (not `"true"`) |
| `phase_count` | integer | `2` (not `"2"`) |
| `max_length` | integer | `64` (not `"64"`) |
| `display_order` | integer | `5` (not `"5"`) |

**Solution:**
1. Check schema documentation for expected types
2. Remove quotes for booleans and numbers
3. Add quotes for strings
4. Validate with JSON schema validator

---

### Error: "Additional properties are not allowed"

**Full Error Message:**
```
ValidationError: Additional properties are not allowed ('extra_field' was unexpected)
```

**Cause:** Field name not recognized by schema (typo or deprecated field)

**Example:**

```json
// ❌ WRONG: Typo in field name
{
  "template_id": "my_template_v1",
  "templete_type": "sql_query"  // Typo: "templete" instead of "template"
}

// ✅ CORRECT: Proper field name
{
  "template_id": "my_template_v1",
  "template_type": "sql_query"
}
```

**Common Typos:**

| ❌ Wrong | ✅ Correct |
|---------|-----------|
| `templete_type` | `template_type` |
| `input_varibles` | `input_variables` |
| `requeired` | `required` |
| `discription` | `description` |
| `phase_discription` | `phase_description` |

**Solution:**
1. Compare field names against schema documentation
2. Use autocomplete in IDE (VS Code with JSON schema)
3. Copy field names from working examples
4. Check for extra spaces: `"name "` vs `"name"`

---

## Manifest Validation Errors

### Error: "Missing required field: 'template_id'"

**Full Error Message:**
```
ValidationError: Missing required field: 'template_id' in manifest
```

**Cause:** Required field not present in manifest.json

**Required Fields in manifest.json:**

```json
{
  "name": "my-template",              // ✅ Required
  "template_id": "my_template_v1",    // ✅ Required
  "template_type": "sql_query",       // ✅ Required
  "repository_type": "planner",       // ✅ Required
  "version": "1.0.0",                 // ✅ Required
  "description": "...",               // ✅ Required
  "input_variables": [...],           // ✅ Required
  "output_configuration": {...},      // ✅ Required
  "population_modes": {...}           // ✅ Required
}
```

**Solution:**
1. Check schema reference: [PLUGIN_MANIFEST_SCHEMA.md](../../rag_templates/PLUGIN_MANIFEST_SCHEMA.md)
2. Copy complete template from working example
3. Ensure all required top-level fields are present
4. Validate with schema validator before deployment

---

### Error: "Unsupported template_type: 'custom_workflow'"

**Full Error Message:**
```
ValidationError: Unsupported template_type: 'custom_workflow'. Allowed values: ['sql_query', 'api_request']
```

**Cause:** Using a template_type that doesn't exist or isn't registered

**Valid template_type Values:**

| template_type | Description | Use Case |
|---------------|-------------|----------|
| `sql_query` | SQL query planner template | Database queries with 2-phase execution |
| `api_request` | API call planner template | REST API calls with request/response |
| *(Future)* `custom_workflow` | Custom multi-phase workflow | Complex orchestration |

**Solution:**
1. Use one of the supported template_type values
2. If creating new type, update type taxonomy first
3. For custom templates, extend existing types instead of creating new ones
4. Check [TYPE_TAXONOMY.md](../../rag_templates/TYPE_TAXONOMY.md) for full type system

---

### Error: "population_modes.auto_generate requires 'generation_endpoint'"

**Full Error Message:**
```
ValidationError: auto_generate mode enabled but 'generation_endpoint' not specified
```

**Cause:** Auto-generate mode configured without required endpoint

**Example:**

```json
// ❌ WRONG: Missing generation_endpoint
{
  "population_modes": {
    "auto_generate": {
      "supported": true,
      "requires_llm": true
      // Missing: generation_endpoint
    }
  }
}

// ✅ CORRECT: Endpoint specified
{
  "population_modes": {
    "auto_generate": {
      "supported": true,
      "requires_llm": true,
      "generation_endpoint": "/api/v1/rag/generate-questions-from-documents"
    }
  }
}
```

**Valid Endpoints:**

| Endpoint | Input Method | Use Case |
|----------|--------------|----------|
| `/api/v1/rag/generate-questions` | MCP context (schema) | Generate from database schema |
| `/api/v1/rag/generate-questions-from-documents` | Document upload | Generate from PDFs/docs |

**Solution:**
1. Add `generation_endpoint` field to auto_generate configuration
2. Use one of the valid endpoint paths
3. Ensure endpoint matches `input_method` (mcp_context vs document_upload)

---

### Error: "Input variable 'database_name' missing required fields"

**Full Error Message:**
```
ValidationError: Input variable 'database_name' missing required fields: ['type', 'description', 'required']
```

**Cause:** Incomplete input variable definition

**Example:**

```json
// ❌ WRONG: Missing required fields
{
  "input_variables": [
    {
      "name": "database_name"
      // Missing: type, description, required
    }
  ]
}

// ✅ CORRECT: All required fields present
{
  "input_variables": [
    {
      "name": "database_name",
      "type": "string",
      "description": "Name of the target database",
      "required": true
    }
  ]
}
```

**Required Fields for Input Variables:**

```json
{
  "name": "variable_name",          // ✅ Required: Unique identifier
  "type": "string",                 // ✅ Required: Data type
  "description": "Description",     // ✅ Required: User-facing explanation
  "required": true,                 // ✅ Required: Is field mandatory?
  "default": "",                    // ⚙️ Optional: Default value
  "validation": {...}               // ⚙️ Optional: Validation rules
}
```

**Supported Types:**

| Type | UI Control | Example Value |
|------|------------|---------------|
| `string` | Text input | `"ecommerce_prod"` |
| `text` | Textarea | `"Long description..."` |
| `integer` | Number input | `50` |
| `select` | Dropdown | `"intermediate"` |
| `boolean` | Checkbox | `true` |
| `code` | Code editor | `"SELECT * FROM..."` |

**Solution:**
1. Ensure every input variable has `name`, `type`, `description`, `required`
2. Add validation rules for data quality
3. Provide sensible defaults for optional fields
4. Use appropriate type for UI control

---

## Template Definition Errors

### Error: "Template JSON does not match schema for type 'sql_query'"

**Full Error Message:**
```
ValidationError: Template JSON does not match schema for type 'sql_query'
Missing required field: 'strategy_template'
```

**Cause:** Template structure doesn't conform to planner template schema

**Required Structure for Planner Templates:**

```json
{
  "template_id": "my_template_v1",
  "template_type": "sql_query",
  "template_version": "1.0.0",
  "description": "...",

  "input_variables": [...],        // ✅ Required
  "output_configuration": {...},   // ✅ Required
  "strategy_template": {           // ✅ Required: The execution strategy
    "phase_count": 2,              // ✅ Required: Number of phases
    "phases": [...]                // ✅ Required: Phase definitions
  }
}
```

**Common Mistakes:**

```json
// ❌ WRONG: Using "steps" instead of "phases"
{
  "strategy_template": {
    "steps": [...]  // Should be "phases"
  }
}

// ❌ WRONG: Missing phase_count
{
  "strategy_template": {
    "phases": [...]  // Missing "phase_count"
  }
}

// ✅ CORRECT: Proper structure
{
  "strategy_template": {
    "phase_count": 2,
    "phases": [
      {
        "phase": 1,
        "goal": "Execute SQL query",
        "relevant_tools": ["base_readQuery"]
      },
      {
        "phase": 2,
        "goal": "Generate report",
        "relevant_tools": ["TDA_FinalReport"]
      }
    ]
  }
}
```

**Solution:**
1. Compare against working example: [sql_query_v1.json](../../rag_templates/templates/sql-query-basic/sql_query_v1.json)
2. Ensure `strategy_template.phases` is an array
3. Verify `phase_count` matches array length
4. Check each phase has required fields

---

### Error: "Phase 1 missing required field: 'goal' or 'goal_template'"

**Full Error Message:**
```
ValidationError: Phase 1 missing required field: 'goal' or 'goal_template'
```

**Cause:** Phase definition incomplete

**Required Fields Per Phase:**

```json
{
  "phase": 1,                              // ✅ Required: Phase number (integer)
  "goal": "Static goal description",       // ✅ Required (OR goal_template)
  // OR
  "goal_template": "Goal with {variable}", // ✅ Required (OR goal)

  "relevant_tools": ["tool_name"],         // ✅ Required (OR relevant_tools_source)
  // OR
  "relevant_tools_source": "mcp_tool_name", // ✅ Required (OR relevant_tools)

  "description": "What this phase does",   // ⚙️ Optional but recommended
  "arguments": {...}                       // ⚙️ Optional: Tool arguments
}
```

**Example:**

```json
// ❌ WRONG: Missing goal
{
  "phase": 1,
  "relevant_tools": ["base_readQuery"]
  // Missing: goal or goal_template
}

// ✅ CORRECT: Static goal
{
  "phase": 1,
  "goal": "Execute SQL query against database",
  "relevant_tools": ["base_readQuery"]
}

// ✅ CORRECT: Dynamic goal with variables
{
  "phase": 1,
  "goal_template": "Execute SQL query: {sql_preview}",
  "goal_variables": ["business_context", "database_context"],
  "relevant_tools": ["base_readQuery"]
}
```

**Solution:**
1. Add `goal` field with static description
2. OR add `goal_template` with `{variable}` placeholders
3. If using `goal_template`, define `goal_variables` array
4. Ensure phase numbering is sequential (1, 2, 3...)

---

### Error: "Unknown transformation: 'invalid_transform'"

**Full Error Message:**
```
ValidationError: Unknown transformation 'invalid_transform' for field 'sql_statement'
```

**Cause:** Using unsupported transformation in output_configuration

**Supported Transformations:**

| Transformation | Effect | Example Input → Output |
|----------------|--------|------------------------|
| `trim` | Remove leading/trailing whitespace | `"  hello  "` → `"hello"` |
| `lowercase` | Convert to lowercase | `"Hello"` → `"hello"` |
| `uppercase` | Convert to uppercase | `"hello"` → `"HELLO"` |
| `truncate:N` | Truncate to N characters | `truncate:10` → `"hello worl"` |
| `normalize_whitespace` | Replace multiple spaces with single space | `"hello    world"` → `"hello world"` |

**Example:**

```json
// ❌ WRONG: Invalid transformation
{
  "output_configuration": {
    "fields": [
      {
        "name": "sql_statement",
        "source": "input.sql_statement",
        "transformations": ["capitalize"]  // Not supported
      }
    ]
  }
}

// ✅ CORRECT: Supported transformations
{
  "output_configuration": {
    "fields": [
      {
        "name": "sql_statement",
        "source": "input.sql_statement",
        "transformations": ["trim", "normalize_whitespace"]
      },
      {
        "name": "sql_preview",
        "source": "input.sql_statement",
        "transformations": ["truncate:50", "uppercase"]
      }
    ]
  }
}
```

**Solution:**
1. Check supported transformations list
2. Remove unsupported transformations
3. Chain multiple transformations (applied in order)
4. Use `truncate:N` with specific number

---

### Error: "Conditional syntax error: 'if invalid_variable'"

**Full Error Message:**
```
ValidationError: Conditional 'if invalid_variable' references undefined variable
```

**Cause:** Conditional logic references variable that doesn't exist

**Conditional Syntax:**

```json
{
  "goal_variables": [
    {
      "name": "database_context",
      "value_template": "Database: {database_name}",
      "condition": "if database_name"  // ✅ Valid: checks if variable exists
    },
    {
      "name": "category_context",
      "value_template": "Category: {category}",
      "condition": "if_not category"  // ✅ Valid: checks if variable is empty
    },
    {
      "name": "complexity_badge",
      "value_template": "Advanced Query",
      "condition": "if_equals complexity advanced"  // ✅ Valid: checks value
    }
  ]
}
```

**Supported Operators:**

| Operator | Syntax | Description | Example |
|----------|--------|-------------|---------|
| `if` | `if <variable>` | Include if variable is not empty | `if database_name` |
| `if_not` | `if_not <variable>` | Include if variable is empty/missing | `if_not optional_field` |
| `if_equals` | `if_equals <variable> <value>` | Include if variable equals value | `if_equals tier enterprise` |

**Example:**

```json
// ❌ WRONG: Variable doesn't exist
{
  "goal_variables": [
    {
      "name": "context",
      "value_template": "DB: {db_name}",
      "condition": "if db_name"  // Error: db_name not defined in input_variables
    }
  ]
}

// ✅ CORRECT: Variable exists
{
  "input_variables": [
    {"name": "database_name", "type": "string", "required": false}
  ],
  "goal_variables": [
    {
      "name": "database_context",
      "value_template": "Database: {database_name}",
      "condition": "if database_name"  // ✅ Valid: database_name defined above
    }
  ]
}
```

**Solution:**
1. Verify variable exists in `input_variables`
2. Check spelling matches exactly (case-sensitive)
3. Use only supported conditional operators
4. Test conditional logic with empty/missing values

---

## MCP Tool Validation Errors

### Error: "MCP tool 'base_readQuery' not found"

**Full Error Message:**
```
ToolValidationError: MCP tool 'base_readQuery' not found in connected MCP server
```

**Cause:** Template references MCP tool that doesn't exist or isn't available

**Common Causes:**
1. **MCP server not connected**: Profile doesn't have MCP server configured
2. **Tool doesn't exist**: MCP server doesn't provide that tool
3. **Typo in tool name**: `base_ReadQuery` vs `base_readQuery` (case-sensitive)
4. **MCP server offline**: Server not running or unreachable

**Debugging Steps:**

**Step 1: Check Profile Configuration**
```
UI: Setup → Profiles → Edit Profile
Check: "MCP Server" dropdown has server selected
```

**Step 2: Verify MCP Server Status**
```
UI: Setup → MCP Servers
Check: Server status is green (connected)
Click: "Test Connection" button
```

**Step 3: List Available Tools**
```bash
# Get JWT token
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

# List MCP server tools
curl -X GET "http://localhost:5050/api/v1/mcp-servers/<server_id>/tools" \
  -H "Authorization: Bearer $JWT" | jq '.tools[] | .name'
```

**Step 4: Check Tool Name Spelling**
```
Common typos:
❌ base_ReadQuery (uppercase R)
✅ base_readQuery (lowercase r)

❌ base_read_query (underscore)
✅ base_readQuery (camelCase)
```

**Solution:**
1. Connect profile to MCP server
2. Start MCP server if offline
3. Fix tool name typo in template
4. Use tool name exactly as returned by MCP server
5. Add fallback tool in template if primary tool unavailable

---

### Error: "Tool 'base_readQuery' missing required argument: 'sql'"

**Full Error Message:**
```
ArgumentValidationError: Tool 'base_readQuery' missing required argument: 'sql'
```

**Cause:** Tool call doesn't provide required argument

**Example:**

```json
// ❌ WRONG: Missing required argument
{
  "phase": 1,
  "relevant_tools": ["base_readQuery"],
  "arguments": {
    "database": {
      "source": "database_name"
    }
    // Missing: sql argument (required by base_readQuery)
  }
}

// ✅ CORRECT: All required arguments provided
{
  "phase": 1,
  "relevant_tools": ["base_readQuery"],
  "arguments": {
    "sql": {
      "source": "sql_statement",
      "description": "SQL query to execute",
      "validation": {
        "required": true,
        "type": "string"
      }
    },
    "database": {
      "source": "database_name",
      "validation": {
        "required": false
      }
    }
  }
}
```

**How to Find Required Arguments:**

**Method 1: Check MCP Server Documentation**
- Read MCP server's tool documentation
- Check which arguments are marked as required

**Method 2: Query Tool Schema via API**
```bash
# Get tool schema
curl -X GET "http://localhost:5050/api/v1/mcp-servers/<server_id>/tools/base_readQuery/schema" \
  -H "Authorization: Bearer $JWT" | jq '.parameters.required'

# Output: ["sql"]  (required arguments)
```

**Method 3: Test Tool Manually**
```
UI: Sessions → New Session
Try: Use tool manually to see required/optional arguments
Error message will indicate missing required arguments
```

**Solution:**
1. Add missing argument to phase's `arguments` object
2. Set `validation.required: true` for required arguments
3. Provide `source` (input variable name) or `value` (static value)
4. Test template with collection creation

---

### Error: "Argument type mismatch: expected 'string' but got 'integer'"

**Full Error Message:**
```
TypeError: Argument 'limit' expected type 'string' but got 'integer': 100
```

**Cause:** Argument value has wrong data type

**Example:**

```json
// ❌ WRONG: limit should be integer but provided as string
{
  "arguments": {
    "limit": {
      "value": "100",  // String instead of integer
      "validation": {
        "type": "integer"
      }
    }
  }
}

// ✅ CORRECT: Proper type
{
  "arguments": {
    "limit": {
      "value": 100,  // Integer (no quotes)
      "validation": {
        "type": "integer"
      }
    }
  }
}
```

**Type Conversion Table:**

| Expected Type | ❌ Wrong | ✅ Correct |
|---------------|---------|-----------|
| `string` | `123` | `"123"` |
| `integer` | `"100"` | `100` |
| `boolean` | `"true"` | `true` |
| `array` | `"[1,2,3]"` | `[1, 2, 3]` |
| `object` | `"{}"` | `{}` |

**Solution:**
1. Check MCP tool schema for expected argument types
2. Remove quotes for numbers and booleans
3. Add quotes for strings
4. Validate JSON types match schema

---

## Generation Errors

### Error: "LLM generation failed: Output too long"

**Full Error Message:**
```
GenerationError: LLM output exceeded token limit (16384 tokens). Requested 100 questions but output truncated.
```

**Cause:** Requested too many questions in single generation (exceeds LLM output token limit)

**Token Limits by Provider:**

| Provider | Output Limit | Recommended Batch Size |
|----------|-------------|------------------------|
| Google Gemini | 8,192 tokens | 20 questions |
| Claude | 16,384 tokens | 30 questions |
| GPT-4 | 16,384 tokens | 30 questions |
| Azure OpenAI | 16,384 tokens | 30 questions |

**Solution:**

**Option 1: Reduce Question Count**
```
Instead of: 100 questions
Try: 20 questions first
Then: Generate more batches if needed
```

**Option 2: Use Batched Generation (Automatic)**

Modern implementation automatically batches large requests:

```python
# Backend automatically batches into groups of 20
BATCH_SIZE = 20
num_batches = (100 + BATCH_SIZE - 1) // BATCH_SIZE  # = 5 batches

for batch_num in range(num_batches):
    # Generate 20 questions per batch
    # Deduplicate across batches
    # Total: 100 unique questions
```

**Check if batching is enabled:**
```bash
# Check server logs for batching
tail -100 logs/app.log | grep "Batch"

# Expected output:
# [INFO] Batch 1/5: Generating 20 questions
# [INFO] Batch 2/5: Generating 20 questions
# ...
```

**If batching not available:**
- Upgrade to latest version
- Or manually generate in smaller batches (20 at a time)

---

### Error: "LLM generated invalid JSON"

**Full Error Message:**
```
GenerationError: LLM response is not valid JSON
Output: "Here are some questions:\n[{...incomplete..."
```

**Cause:** LLM didn't return proper JSON format

**Common LLM Output Issues:**
1. **Wrapped in markdown**: `` ```json {...} ``` ``
2. **Incomplete JSON**: Output truncated mid-object
3. **Extra text**: Explanation before/after JSON
4. **Wrong format**: CSV instead of JSON

**Example Bad Outputs:**

```
❌ Wrapped in markdown:
```json
[{"question": "...", "sql": "..."}]
```

❌ Incomplete:
[{"question": "Show products", "sql": "SELECT * FROM prod

❌ Extra text:
Here are 10 questions for your database:
[{"question": "...", "sql": "..."}]
Hope this helps!
```

**Solution:**

**Immediate Fix:**
1. Click "Regenerate" to try again
2. Or manually fix JSON (remove markdown, complete truncated objects)

**Long-Term Fix - Improve Prompt:**

Edit `prompt_templates` in manifest.json:

```json
{
  "prompt_templates": {
    "output_format": "Return ONLY a JSON array with no additional text, markdown formatting, or explanations. Do not wrap in ```json code blocks. Start output with [ and end with ].",

    "critical_guidelines": [
      "CRITICAL: Return ONLY raw JSON - no markdown, no explanations",
      "Start response with [ and end with ]",
      "Ensure JSON is complete (no truncation)",
      "Validate JSON syntax before returning"
    ]
  }
}
```

---

### Error: "Generated SQL has syntax error"

**Full Error Message:**
```
SQLSyntaxError: SQL syntax error in generated query
Query: "SELECT * FROM product WHERE quantity < 10"
Error: Table 'product' doesn't exist (did you mean 'products'?)
```

**Cause:** LLM generated SQL with incorrect table/column names

**Common SQL Generation Errors:**

| Error Type | Example | Cause |
|------------|---------|-------|
| **Wrong table name** | `product` instead of `products` | LLM used singular instead of plural |
| **Missing table** | `SELECT * FROM sales` | Table doesn't exist in schema |
| **Wrong column name** | `SELECT user_name` | Column is actually `username` |
| **Wrong SQL dialect** | `TOP 10` (SQL Server) | Database is PostgreSQL (use `LIMIT 10`) |
| **Missing JOIN** | `SELECT * FROM orders WHERE customer.name = 'John'` | Should JOIN customers table |

**Solution:**

**Improve Prompt with Schema Context:**

```json
{
  "prompt_templates": {
    "task_description": "Generate SQL queries using ONLY the exact table and column names from the provided schema. Do not use assumed table names.",

    "critical_guidelines": [
      "DO NOT use placeholder table names - use EXACT names from schema",
      "VALIDATE that all referenced tables exist in the schema",
      "VALIDATE that all referenced columns exist in their tables",
      "Use proper SQL dialect for the target database (PostgreSQL, MySQL, etc.)",
      "For table 'products' (plural), do NOT use 'product' (singular)"
    ]
  }
}
```

**Provide Better Schema Context:**

```bash
# Before generation, execute comprehensive schema query
# PostgreSQL example:
SELECT
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

**Manual Review:**
- Always review generated SQL before creating collection
- Test queries against actual database
- Fix table/column names manually if needed

---

## Deployment Errors

### Error: "Template not found in registry"

**Full Error Message:**
```
TemplateNotFoundError: Template 'product_inventory_v1' not found in registry
```

**Cause:** Template not loaded or registry not reloaded after creation

**Solution:**

**Option 1: Hot Reload (Recommended)**
```bash
# Get JWT token
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

# Reload templates
curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
  -H "Authorization: Bearer $JWT"
```

**Expected Response:**
```json
{
  "status": "success",
  "templates_count": 7,
  "new_templates": ["product_inventory_v1"]
}
```

**Option 2: Full Restart**
```bash
# Stop application
pkill -f "python -m trusted_data_agent.main"

# Start application
python -m trusted_data_agent.main
```

**Verify Template Loaded:**
```bash
# List all templates
curl -X GET http://localhost:5050/api/v1/rag/templates \
  -H "Authorization: Bearer $JWT" | jq '.templates[] | .template_id'
```

**Check Server Logs:**
```bash
# Check for template loading errors
tail -100 logs/app.log | grep -i "template"

# Look for:
✅ "Loaded template: product_inventory_v1"
❌ "Error loading template: ..."
```

---

### Error: "Collection created but no data"

**Full Error Message:**
```
CollectionError: Collection 'my_collection' created successfully but contains 0 entries
```

**Cause:** Collection created but population step failed

**Debugging Steps:**

**Step 1: Check Server Logs**
```bash
tail -200 logs/app.log | grep -A 10 "populate"
```

**Look for:**
- ✅ `Successfully populated collection with 50 entries`
- ❌ `Population failed: Invalid template structure`
- ❌ `Validation error: Missing required field`

**Step 2: Verify Generation Completed**
```
Check UI:
1. Did "Generate Questions" complete successfully?
2. Was preview shown with generated questions?
3. Did you click "Create Collection" after generation?
```

**Step 3: Check Collection Entry Count**
```bash
curl -X GET "http://localhost:5050/api/v1/rag/collections/<collection_id>" \
  -H "Authorization: Bearer $JWT" | jq '.entry_count'

# Expected: 50 (or your question count)
# Actual: 0 (indicates population failed)
```

**Common Causes:**

| Cause | Symptom | Solution |
|-------|---------|----------|
| **Didn't click populate** | Generated questions but never clicked "Create Collection" | Click "Create Collection" button |
| **Validation failed** | Questions failed validation during population | Check logs for validation errors |
| **Template mismatch** | Template structure doesn't match collection type | Verify template_id matches |
| **Database error** | ChromaDB failed to insert | Check ChromaDB logs |

**Solution:**
1. Review server logs for population errors
2. Ensure "Generate Questions" completed
3. Click "Create Collection" after generation
4. Verify generated questions passed validation
5. If failed, fix validation errors and regenerate

---

## Retrieval Errors

### Error: "RAG retrieval returned 0 results"

**Full Error Message:**
```
RetrievalWarning: RAG retrieval for query "Show low inventory products" returned 0 results
Collection: product_inventory_queries (50 entries)
Min Similarity: 0.6
```

**Cause:** Semantic search not finding matches above similarity threshold

**Debugging Steps:**

**Step 1: Check Collection Has Data**
```bash
curl -X GET "http://localhost:5050/api/v1/rag/collections/<collection_id>" \
  -H "Authorization: Bearer $JWT" | jq '.entry_count'

# Expected: > 0 (should have entries)
```

**Step 2: Test Search Directly**
```bash
curl -X POST "http://localhost:5050/api/v1/rag/collections/<collection_id>/search" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show low inventory products",
    "top_k": 10,
    "min_similarity": 0.3
  }' | jq '.results'
```

**Step 3: Check Similarity Scores**
```bash
# Lower min_similarity to see what's being filtered out
curl -X POST "http://localhost:5050/api/v1/rag/collections/<collection_id>/search" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show low inventory products",
    "top_k": 10,
    "min_similarity": 0.0
  }' | jq '.results[] | {question: .question, similarity: .similarity}'

# Check similarity scores:
# 0.8-1.0 = Excellent match
# 0.6-0.8 = Good match
# 0.4-0.6 = Moderate match
# 0.0-0.4 = Poor match
```

**Common Causes:**

| Cause | Similarity | Solution |
|-------|------------|----------|
| **No semantic overlap** | < 0.3 | Collection doesn't contain similar questions |
| **Threshold too high** | 0.55 (below 0.6 threshold) | Lower min_similarity in profile |
| **Different terminology** | 0.45 | Add synonyms to collection |
| **Empty collection** | N/A | Verify collection populated |

**Solutions:**

**Solution 1: Lower Similarity Threshold**
```
UI: Setup → Profiles → Edit Profile
Knowledge Configuration:
  Min Similarity: 0.6 → 0.4
```

**Solution 2: Add More Diverse Questions**
```
Generate more questions covering different phrasings:
- "Show low inventory products"
- "Which products need restocking?"
- "List items with insufficient stock"
- "Products running out"
```

**Solution 3: Improve Query Phrasing**
```
Instead of: "low inventory"
Try: "products with low stock" (matches question phrasing)
```

---

### Error: "Profile uses wrong collection"

**Full Error Message:**
```
ProfileError: Profile 'INVENTORY' configured with collection 'old_collection' but expected 'product_inventory_queries'
```

**Cause:** Profile pointing to incorrect collection

**Solution:**

**Step 1: Check Profile Configuration**
```
UI: Setup → Profiles → Edit Profile
Knowledge Configuration section:
  Primary Collection: [Dropdown showing current collection]
```

**Step 2: Update Collection**
```
1. Click dropdown under "Primary Collection"
2. Select "Product Inventory - Prod Database"
3. Click "Save Profile"
4. Verify: "Profile updated successfully"
```

**Step 3: Test Retrieval**
```
1. Create new session
2. Submit query: "@INVENTORY Show low inventory products"
3. Check Live Status window:
   ✅ "Retrieved 3 champion cases from collection: product_inventory_queries"
   ❌ "Retrieved 0 champion cases" (still wrong collection)
```

**Verify via API:**
```bash
# Get profile configuration
curl -X GET "http://localhost:5050/api/v1/profiles/<profile_id>" \
  -H "Authorization: Bearer $JWT" | jq '.knowledgeConfig.collections[]'

# Should show: "product_inventory_queries"
```

---

## Common Workflows

### Workflow 1: Create New Template from Scratch

**Steps:**

1. **Plan** (see COMPLETE_EXAMPLE.md Planning Phase)
   - Identify use case
   - Choose template type
   - Define input/output variables

2. **Create Files**
   ```bash
   mkdir -p ~/.tda/templates/my-template
   cd ~/.tda/templates/my-template
   touch manifest.json
   touch my_template_v1.json
   touch README.md
   ```

3. **Define manifest.json**
   - Copy from working example
   - Customize input_variables
   - Configure population_modes
   - Add validation rules

4. **Define template JSON**
   - Create strategy_template
   - Define phases (goal, tools, arguments)
   - Add metadata extraction
   - Configure validation

5. **Reload Templates**
   ```bash
   curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
     -H "Authorization: Bearer $JWT"
   ```

6. **Test in UI**
   - Setup → RAG Collections → Create New Collection
   - Select your template
   - Test manual population first
   - Then test auto-generation

7. **Troubleshoot**
   - Check logs: `tail -100 logs/app.log`
   - Validate JSON syntax
   - Fix validation errors
   - Iterate

---

### Workflow 2: Fix "LLM Generation Failed" Error

**Symptoms:**
- Generation starts but fails partway through
- LLM returns invalid JSON or incomplete data
- Error: "Output too long" or "Invalid JSON"

**Fix Steps:**

1. **Reduce Question Count**
   ```
   Try: 20 questions instead of 100
   Verify: Generation completes successfully
   ```

2. **Improve Output Format Instructions**
   ```json
   {
     "prompt_templates": {
       "output_format": "Return ONLY a valid JSON array. No markdown, no explanations, no code blocks. Start with [ and end with ].",
       "critical_guidelines": [
         "CRITICAL: Return raw JSON only",
         "Do NOT wrap in ```json blocks",
         "Ensure JSON is complete (no truncation)"
       ]
     }
   }
   ```

3. **Test Manually**
   ```
   1. Setup → RAG Collections
   2. Select template
   3. Enter: Count = 10 (small test)
   4. Generate
   5. Review output
   6. If successful, increase to 20, then 50
   ```

4. **Check Server Logs**
   ```bash
   tail -200 logs/app.log | grep -A 20 "Generation"
   # Look for:
   # - LLM response preview
   # - JSON parsing errors
   # - Validation failures
   ```

5. **Try Different LLM Provider**
   ```
   Some providers better at JSON:
   ✅ Claude (best structured output)
   ✅ GPT-4 (good JSON compliance)
   ⚠️ Gemini (sometimes adds markdown)
   ```

---

### Workflow 3: Debug "No RAG Results" Issue

**Symptoms:**
- Collection created successfully
- Query submitted but 0 results retrieved
- Live Status: "Retrieved 0 champion cases"

**Fix Steps:**

1. **Verify Collection Has Data**
   ```bash
   curl -X GET "http://localhost:5050/api/v1/rag/collections/<collection_id>" \
     -H "Authorization: Bearer $JWT" | jq '.entry_count'
   # Expected: 50 (not 0)
   ```

2. **Test Search with Low Threshold**
   ```bash
   curl -X POST "http://localhost:5050/api/v1/rag/collections/<collection_id>/search" \
     -H "Authorization: Bearer $JWT" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "your query here",
       "top_k": 10,
       "min_similarity": 0.0
     }' | jq '.results[] | {similarity, question}'
   ```

3. **Check Similarity Scores**
   ```
   If highest similarity is 0.55:
   - Profile min_similarity is 0.6
   - No results returned (0.55 < 0.6)
   - Solution: Lower threshold to 0.4
   ```

4. **Update Profile Threshold**
   ```
   UI: Setup → Profiles → Edit
   Knowledge Configuration:
     Min Similarity: 0.6 → 0.4
   ```

5. **Test Again**
   ```
   Create new session
   Submit query
   Check: "Retrieved 3 champion cases" (success!)
   ```

---

## Quick Reference: Error Code → Solution

| Error Code | Error Type | Quick Fix |
|------------|------------|-----------|
| `JSONDecodeError` | Invalid JSON syntax | Validate with `jq .` |
| `ValidationError` | Schema validation failed | Check required fields |
| `TemplateNotFoundError` | Template not loaded | Reload templates via API |
| `ToolValidationError` | MCP tool not found | Check tool name spelling |
| `ArgumentValidationError` | Missing required argument | Add to phase arguments |
| `GenerationError` | LLM generation failed | Reduce question count |
| `SQLSyntaxError` | Invalid SQL generated | Improve schema context |
| `CollectionError` | Population failed | Check validation logs |
| `RetrievalWarning` | No search results | Lower similarity threshold |
| `ProfileError` | Wrong collection | Update profile config |

---

## Additional Resources

- **Complete Example**: [COMPLETE_EXAMPLE.md](COMPLETE_EXAMPLE.md) - End-to-end template creation tutorial
- **Schema Reference**: [PLUGIN_MANIFEST_SCHEMA.md](../../rag_templates/PLUGIN_MANIFEST_SCHEMA.md) - Full manifest schema
- **Type Taxonomy**: [TYPE_TAXONOMY.md](../../rag_templates/TYPE_TAXONOMY.md) - Template type system
- **Developer Guide**: [CLAUDE.md](../../CLAUDE.md) - System architecture

---

## Getting Help

**Check Logs:**
```bash
# Application logs
tail -200 logs/app.log | grep -i "error"

# Template loading logs
tail -100 logs/app.log | grep -i "template"

# Generation logs
tail -100 logs/app.log | grep -i "generation"
```

**Validate Files:**
```bash
# Validate manifest JSON
jq . ~/.tda/templates/my-template/manifest.json

# Validate template JSON
jq . ~/.tda/templates/my-template/my_template_v1.json
```

**Test Components:**
```bash
# Test MCP server connection
curl -X GET "http://localhost:5050/api/v1/mcp-servers/<server_id>/test" \
  -H "Authorization: Bearer $JWT"

# Test template reload
curl -X POST "http://localhost:5050/api/v1/rag/templates/reload" \
  -H "Authorization: Bearer $JWT"

# Test search
curl -X POST "http://localhost:5050/api/v1/rag/collections/<id>/search" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 3, "min_similarity": 0.0}'
```

**Community:**
- GitHub Issues: https://github.com/rgeissen/uderia/issues
- Documentation: `docs/RAG_Templates/`
