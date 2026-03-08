# Template Plugin Manifest Schema

## Overview

The `manifest.json` file describes metadata, dependencies, and configuration for a template plugin. This enables modular distribution, versioning, and community-developed templates.

> **Note:** Template files themselves are validated using JSON schemas in `schemas/` directory:
> - `schemas/planner-schema.json` - For execution strategy templates (sql_query, api_request, etc.)
> - `schemas/knowledge-template-schema.json` - For document storage templates
>
> **Related Documentation:**
> - `schemas/README.md` - Template validation details and JSON schema specifications
> - `TYPE_TAXONOMY.md` - **Comprehensive type system documentation** covering template_type, repository_type, and category concepts
> - `template_registry.json` - Registry of available templates with metadata and display ordering

## Template Structure Overview

Templates consist of two main files:

1. **`manifest.json`** (this schema) - Plugin metadata and configuration
2. **`template.json`** - Template definition, validated by JSON schemas:
   - **Planner templates**: Validated against `schemas/planner-schema.json`
   - **Knowledge templates**: Validated against `schemas/knowledge-template-schema.json`

### Template Type Determination
```python
# The template_type field determines which schema validates the template
if template_data.get("template_type") == "knowledge_repository":
    # Use schemas/knowledge-template-schema.json
    schema_type = "knowledge"
else:
    # Use schemas/planner-schema.json for all execution strategies
    schema_type = "planner"
```

See `schemas/README.md` for complete template validation rules.

---

## Manifest Schema Definition

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["name", "version", "template_id", "display_name", "author"],
  "properties": {
    "name": {
      "type": "string",
      "pattern": "^[a-z0-9-]+$",
      "description": "Package name (lowercase, hyphens only)"
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$",
      "description": "Semantic version (e.g., 1.0.0)"
    },
    "template_id": {
      "type": "string",
      "pattern": "^[a-z0-9_]+_v\\d+$",
      "description": "Unique template identifier (e.g., sql_query_v1)"
    },
    "display_name": {
      "type": "string",
      "description": "Human-readable template name"
    },
    "description": {
      "type": "string",
      "description": "Brief description of template functionality"
    },
    "author": {
      "type": "string",
      "description": "Author name or organization"
    },
    "license": {
      "type": "string",
      "description": "SPDX license identifier (e.g., MIT, Apache-2.0)"
    },
    "homepage": {
      "type": "string",
      "format": "uri",
      "description": "Project homepage URL"
    },
    "repository": {
      "type": "object",
      "properties": {
        "type": {
          "type": "string",
          "enum": ["git", "svn", "hg"]
        },
        "url": {
          "type": "string",
          "format": "uri"
        }
      }
    },
    "keywords": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Search keywords for marketplace"
    },
    "compatibility": {
      "type": "object",
      "properties": {
        "min_app_version": {
          "type": "string",
          "description": "Minimum TDA version required"
        },
        "max_app_version": {
          "type": "string",
          "description": "Maximum TDA version supported"
        }
      }
    },
    "dependencies": {
      "type": "object",
      "properties": {
        "templates": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "Required template dependencies"
        },
        "python_packages": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "Required Python packages (pip format)"
        }
      }
    },
    "files": {
      "type": "object",
      "required": ["template"],
      "properties": {
        "template": {
          "type": "string",
          "description": "Path to template.json (relative to manifest)"
        },
        "ui_config": {
          "type": "string",
          "description": "Path to custom UI config panel HTML"
        },
        "ui_script": {
          "type": "string",
          "description": "Path to custom UI JavaScript"
        },
        "validator": {
          "type": "string",
          "description": "Path to custom Python validator"
        },
        "icon": {
          "type": "string",
          "description": "Path to template icon (SVG, PNG)"
        }
      }
    },
    "permissions": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["database_access", "mcp_tools", "file_system", "network"]
      },
      "description": "Required permissions for template execution"
    },
    "ui_components": {
      "type": "object",
      "properties": {
        "config_panel": {
          "type": "boolean",
          "description": "Has custom configuration panel"
        },
        "preview_renderer": {
          "type": "boolean",
          "description": "Has custom preview renderer"
        },
        "file_upload": {
          "type": "boolean",
          "description": "Supports file upload (e.g., PDFs for context)"
        }
      }
    },
    "population_modes": {
      "type": "object",
      "description": "Supported methods for populating RAG collections with this template",
      "properties": {
        "manual": {
          "type": "object",
          "properties": {
            "supported": {
              "type": "boolean",
              "description": "Whether manual entry mode is supported"
            },
            "description": {
              "type": "string",
              "description": "Description of manual entry workflow"
            },
            "required_fields": {
              "type": "array",
              "items": {
                "type": "string"
              },
              "description": "Required template variables for manual entry"
            }
          }
        },
        "auto_generate": {
          "type": "object",
          "properties": {
            "supported": {
              "type": "boolean",
              "description": "Whether LLM auto-generation is supported"
            },
            "requires_llm": {
              "type": "boolean",
              "description": "Whether LLM configuration is required"
            },
            "requires_mcp_context": {
              "type": "boolean",
              "description": "Whether MCP server context (schema, tools) is required for generation"
            },
            "requires_pdf": {
              "type": "boolean",
              "description": "Whether PDF processing capabilities are required"
            },
            "input_method": {
              "type": "string",
              "enum": ["mcp_context", "document_upload", "hybrid"],
              "description": "How context is provided: 'mcp_context' (database schema via MCP), 'document_upload' (PDF files), or 'hybrid' (both)"
            },
            "generation_endpoint": {
              "type": "string",
              "pattern": "^/api/v1/.*",
              "description": "REST API endpoint for question/answer generation (e.g., /api/v1/rag/generate-questions)"
            },
            "description": {
              "type": "string",
              "description": "Description of auto-generation workflow"
            },
            "input_variables": {
              "type": "object",
              "description": "Input variables required for auto-generation",
              "additionalProperties": {
                "type": "object",
                "properties": {
                  "required": {
                    "type": "boolean"
                  },
                  "type": {
                    "type": "string",
                    "enum": ["string", "integer", "boolean", "file"]
                  },
                  "default": {},
                  "min": {
                    "type": "number"
                  },
                  "max": {
                    "type": "number"
                  },
                  "description": {
                    "type": "string"
                  },
                  "example": {
                    "type": "string"
                  }
                }
              }
            }
          }
        }
      }
    },
    "prompt_templates": {
      "type": "object",
      "description": "LLM prompt templates for auto-generation modes. Each key represents a generation task.",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "system_role": {
            "type": "string",
            "description": "System message defining LLM's role and expertise"
          },
          "task_description": {
            "type": "string",
            "description": "Main task instruction for the LLM with variable placeholders (e.g., {count}, {subject})"
          },
          "requirements": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "List of specific requirements and constraints for generation"
          },
          "output_format": {
            "type": "string",
            "description": "Expected output structure and format specification"
          },
          "critical_guidelines": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "Critical guidelines that must be followed for successful generation"
          }
        }
      }
    },
    "metadata": {
      "type": "object",
      "description": "Additional metadata for UI organization and analytics",
      "properties": {
        "category": {
          "type": "string",
          "description": "UI category for template grouping (e.g., 'Database', 'API Integration', 'Knowledge Management')"
        },
        "difficulty": {
          "type": "string",
          "enum": ["beginner", "intermediate", "advanced", "expert"],
          "description": "Complexity level for user guidance"
        },
        "estimated_tokens": {
          "type": "object",
          "description": "Token cost estimates for different phases",
          "properties": {
            "planning": {
              "type": "integer",
              "description": "Estimated tokens for strategic planning phase"
            },
            "execution": {
              "type": "integer",
              "description": "Estimated tokens for tactical execution phase"
            }
          }
        },
        "tags": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "Searchable tags for filtering and discovery"
        }
      }
    }
  }
}
```

---

## Detailed Field Explanations

### Prompt Templates Configuration

The `prompt_templates` object configures LLM prompts for auto-generation modes. Only required when `auto_generate.supported = true` and `auto_generate.requires_llm = true`.

**Structure**:
```json
{
  "prompt_templates": {
    "generation_task_name": {
      "system_role": "System message defining LLM expertise",
      "task_description": "Main task with variable placeholders",
      "requirements": ["Requirement 1", "Requirement 2"],
      "output_format": "Expected structure specification",
      "critical_guidelines": ["Critical rule 1", "Critical rule 2"]
    }
  }
}
```

**Field Descriptions**:

- **`system_role`** (string, required): Defines the LLM's role and expertise domain
  - Example: `"You are a SQL expert helping to generate test questions and queries for a RAG system."`
  - Best practice: Be specific about expertise and context

- **`task_description`** (string, required): Main instruction with variable placeholders
  - Variables use `{variable_name}` syntax: `{count}`, `{subject}`, `{database_name}`
  - Example: `"Generate {count} diverse business questions about \"{subject}\" with SQL queries."`
  - Variables are replaced at runtime with actual values from `input_variables`

- **`requirements`** (array of strings, optional): Specific requirements and constraints
  - Used for: Quality control, validation rules, format specifications
  - Example: `["Generate EXACTLY {count} pairs", "Use only tables in schema"]`

- **`output_format`** (string, required): Expected output structure
  - Example: `"Return JSON array: [{ \"question\": \"...\", \"sql\": \"...\" }]"`
  - Critical for parsing LLM responses correctly

- **`critical_guidelines`** (array of strings, optional): Must-follow rules for successful generation
  - Example: `["Write COMPLETE SQL queries", "Response must be ONLY JSON"]`
  - Used to prevent common LLM errors (truncation, extra text, incomplete output)

**Variable Substitution**:
Variables in prompt templates are replaced with values from:
- `input_variables` provided by user (e.g., `subject`, `database_name`)
- System-provided values (e.g., `count` from `num_examples`)
- MCP context (e.g., database schema injected automatically)

**Example Usage**:
```json
{
  "prompt_templates": {
    "question_generation": {
      "system_role": "You are a SQL expert.",
      "task_description": "Generate {count} SQL queries for {subject}",
      "requirements": [
        "Use {database_name} database",
        "Follow {target_database} syntax"
      ],
      "output_format": "JSON array with question/sql pairs"
    }
  }
}
```

At runtime with `subject="sales"`, `count=5`, `database_name="prod"`:
```
Task: "Generate 5 SQL queries for sales"
Requirements: ["Use prod database", "Follow Teradata syntax"]
```

---

### Metadata Configuration

The `metadata` object provides additional information for UI organization, analytics, and user guidance.

**Structure**:
```json
{
  "metadata": {
    "category": "Database",
    "difficulty": "beginner",
    "estimated_tokens": {
      "planning": 150,
      "execution": 180
    },
    "tags": ["sql", "built-in", "data-retrieval"]
  }
}
```

**Field Descriptions**:

- **`category`** (string, optional): UI grouping category
  - Standard categories: `"Database"`, `"API Integration"`, `"Knowledge Management"`, `"Data Processing"`, `"Custom Workflow"`
  - Used for: Template discovery UI, marketplace filtering
  - Best practice: Use existing categories when possible

- **`difficulty`** (enum, optional): Complexity level for user guidance
  - Values: `"beginner"`, `"intermediate"`, `"advanced"`, `"expert"`
  - Used for: Filtering, sorting, user recommendations
  - Criteria:
    - `beginner`: Single-phase, simple inputs, no customization needed
    - `intermediate`: Multi-phase, moderate inputs, some configuration
    - `advanced`: Complex logic, advanced inputs, significant configuration
    - `expert`: Highly customizable, deep technical knowledge required

- **`estimated_tokens`** (object, optional): Token cost estimates for budget planning
  - **`planning`** (integer): Estimated tokens for strategic planning phase
  - **`execution`** (integer): Estimated tokens for tactical execution phase
  - Used for: Cost forecasting, consumption profile enforcement
  - Note: These are estimates; actual token usage varies by query complexity

- **`tags`** (array of strings, optional): Searchable keywords for discovery
  - Example: `["sql", "built-in", "data-retrieval", "teradata"]`
  - Used for: Search, filtering, related template suggestions
  - Best practice: Include technology names, use cases, and distinctive features

**Usage in UI**:
- Category determines template grouping in "Add Collection" wizard
- Difficulty shows badge/icon for user guidance
- Tags enable search filtering
- Token estimates shown in cost preview

---

### Advanced Auto-Generate Fields

When `auto_generate.supported = true`, additional fields control how context is provided and generation is performed.

#### `requires_mcp_context` (boolean)

Indicates whether MCP server context (database schema, available tools) is required for generation.

- **`true`**: Template needs live MCP server connection to retrieve schema/tools
  - Example: SQL templates need database schema to generate valid queries
  - Frontend validates MCP server is configured before allowing generation

- **`false`**: Template generates from user inputs only
  - Example: Generic text templates that don't need external context

**Implementation Note**:
When `true`, the backend calls `mcp_adapter.get_resources()` to fetch schema before generation.

#### `input_method` (enum)

Defines how context is provided to the LLM for generation.

- **`"mcp_context"`**: Use MCP server resources (database schema, API specs)
  - Backend fetches schema/tools from configured MCP server
  - Schema injected into LLM prompt automatically
  - Example: SQL templates querying database structure

- **`"document_upload"`**: Use uploaded PDF/document files
  - User uploads PDF files (DBA guides, API docs)
  - Backend extracts text and chunks documents
  - Chunks injected into LLM prompt as context
  - Example: SQL templates using DBA documentation

- **`"hybrid"`**: Combine both MCP context and documents
  - Useful for: Complex scenarios requiring both schema and documentation
  - Example: API templates using OpenAPI spec + developer guides

**Workflow Impact**:
- `mcp_context`: UI shows database/schema selection dropdown
- `document_upload`: UI shows file upload interface
- `hybrid`: UI shows both controls

#### `generation_endpoint` (string)

REST API endpoint for question/answer generation.

- **Format**: `/api/v1/...`
- **Standard endpoints**:
  - `/api/v1/rag/generate-questions` - For MCP-context generation
  - `/api/v1/rag/generate-questions-from-documents` - For document-upload generation
- **Custom endpoints**: Templates can specify custom generation logic

**Usage**:
Frontend calls this endpoint with:
```json
{
  "collection_id": 123,
  "template_id": "sql_query_v1",
  "count": 20,
  "subject": "customer analytics",
  "database_name": "production",
  "conversion_rules": "Use Teradata syntax"
}
```

Backend response:
```json
{
  "questions": [
    {"question": "...", "sql": "..."},
    ...
  ],
  "count": 20
}
```

---

## Template.json: Goal Variables & Conditional Logic

While `manifest.json` (documented above) describes the plugin metadata, `template.json` defines the actual execution strategy. This section documents advanced features used in template files.

> **Note**: Full template.json validation is handled by JSON schemas (`schemas/planner-schema.json` and `schemas/knowledge-template-schema.json`). This section explains specific advanced features not obvious from schema alone.

### Goal Variables with Conditional Logic

Goal variables allow dynamic construction of phase goals based on available input variables. They support conditional inclusion and value transformation.

**Basic Structure**:
```json
{
  "goal_variables": {
    "variable_name": {
      "condition": "if some_input_variable",
      "format": "Template {variable_value}",
      "source": "input_variable_name",
      "transform": "truncate",
      "max_length": 100
    }
  }
}
```

#### Conditional Operators

**`condition` Field Syntax**:

| Operator | Syntax | Description | Example |
|----------|--------|-------------|---------|
| **if** | `"if variable_name"` | Include if variable is not empty/null | `"if database_name"` |
| **if_not** | `"if_not variable_name"` | Include if variable is empty/null | `"if_not use_cache"` |
| **if_equals** | `"if_equals variable_name value"` | Include if variable equals specific value | `"if_equals db_type teradata"` |
| **if_not_equals** | `"if_not_equals variable_name value"` | Include if variable does not equal value | `"if_not_equals mode production"` |
| **if_contains** | `"if_contains variable_name substring"` | Include if variable contains substring | `"if_contains query SELECT"` |

**Conditional Examples**:

**Example 1: Optional Database Context**
```json
{
  "goal_variables": {
    "database_context": {
      "condition": "if database_name",
      "format": " on {database_name}"
    }
  }
}
```

**Runtime Behavior**:
- If `database_name = "production"`: Goal includes `" on production"`
- If `database_name = null`: Variable omitted from goal entirely

**Example 2: Database-Specific SQL Syntax**
```json
{
  "goal_variables": {
    "limit_syntax": {
      "condition": "if_equals database_type teradata",
      "format": "Use TOP {limit_value} instead of LIMIT"
    }
  }
}
```

**Runtime Behavior**:
- If `database_type = "teradata"`: Includes Teradata-specific instruction
- If `database_type = "postgresql"`: Variable omitted

**Example 3: Negative Condition**
```json
{
  "goal_variables": {
    "cache_instruction": {
      "condition": "if_not use_cache",
      "format": "Execute query without caching"
    }
  }
}
```

**Runtime Behavior**:
- If `use_cache = false` or `null`: Includes instruction
- If `use_cache = true`: Variable omitted

#### Value Transformations

The `transform` field applies processing to variable values before insertion.

**Available Transforms**:

| Transform | Description | Use Case | Example |
|-----------|-------------|----------|---------|
| **truncate** | Truncate to `max_length` characters | Long SQL queries in goal preview | `"transform": "truncate", "max_length": 100` |
| **uppercase** | Convert to uppercase | Database names, keywords | `"transform": "uppercase"` |
| **lowercase** | Convert to lowercase | Table names, identifiers | `"transform": "lowercase"` |
| **trim** | Remove leading/trailing whitespace | User inputs | `"transform": "trim"` |
| **escape_quotes** | Escape single/double quotes | SQL string literals | `"transform": "escape_quotes"` |

**Example: SQL Preview with Truncation**
```json
{
  "goal_variables": {
    "sql_preview": {
      "source": "sql_statement",
      "transform": "truncate",
      "max_length": 500,
      "format": "Execute SQL: {sql_preview}"
    }
  }
}
```

**Runtime Behavior**:
```
Input: sql_statement = "SELECT * FROM products WHERE category IN ('Electronics', 'Furniture', 'Clothing', ...) AND price > 100 AND stock > 0 ORDER BY price DESC LIMIT 100"
Output: "Execute SQL: SELECT * FROM products WHERE category IN ('Electronics', 'Furniture', 'Clothing', ...) AND price > 100 AND stock > 0 ORDER BY pric..."
```

#### Multiple Conditions (Advanced)

For complex scenarios, use nested objects with multiple conditions:

```json
{
  "goal_variables": {
    "optimization_hint": {
      "conditions": [
        {"type": "if_equals", "variable": "database_type", "value": "teradata"},
        {"type": "if", "variable": "enable_optimization"}
      ],
      "logic": "AND",
      "format": "Use Teradata query optimizer hints"
    }
  }
}
```

**Runtime Behavior**: Included only if BOTH conditions are true.

#### Complete Example: SQL Query Template

```json
{
  "template_id": "sql_query_v1",
  "template_type": "sql_query",
  "strategy_template": {
    "phase_count": 2,
    "phases": [
      {
        "phase": 1,
        "goal_template": "Execute SQL query{database_context}: {sql_preview}",
        "goal_variables": {
          "database_context": {
            "condition": "if database_name",
            "format": " on {database_name}"
          },
          "sql_preview": {
            "source": "sql_statement",
            "transform": "truncate",
            "max_length": 500
          }
        },
        "relevant_tools_source": "mcp_tool_name",
        "arguments": {
          "sql": {
            "source": "sql_statement"
          }
        }
      }
    ]
  }
}
```

**Goal Construction Process**:
1. Start with `goal_template`: `"Execute SQL query{database_context}: {sql_preview}"`
2. Evaluate conditional `database_context`:
   - If `database_name = "prod"` → `database_context = " on prod"`
   - If `database_name = null` → `database_context = ""` (empty)
3. Apply transform to `sql_preview`:
   - Take `sql_statement` value
   - Truncate to 500 characters
4. Substitute variables:
   - `"Execute SQL query on prod: SELECT * FROM products WHERE..."`

#### Use Cases for Conditional Logic

**1. Optional Context Injection**
Include database/schema context only when specified:
```json
{
  "database_context": {
    "condition": "if database_name",
    "format": " on {database_name}"
  }
}
```

**2. Database-Specific Syntax**
Provide dialect-specific instructions based on database type:
```json
{
  "syntax_hint": {
    "condition": "if_equals db_type teradata",
    "format": "Use Teradata-specific SQL syntax"
  }
}
```

**3. Conversion Rules**
Apply conversion rules when specified:
```json
{
  "conversion_note": {
    "condition": "if conversion_rules",
    "format": "Apply rules: {conversion_rules}"
  }
}
```

**4. Provider-Specific Arguments**
Include provider-specific MCP tool arguments:
```json
{
  "timeout_arg": {
    "condition": "if timeout_seconds",
    "format": "--timeout {timeout_seconds}"
  }
}
```

#### Validation

Template validators check:
- ✅ Condition syntax is valid (supported operators)
- ✅ Referenced variables exist in `input_variables`
- ✅ Transform types are supported
- ✅ `max_length` is positive integer (for truncate)
- ✅ Format strings don't have unmatched braces

**Common Errors**:
```json
// ❌ BAD: Unknown operator
{
  "condition": "if_greater_than count 10"  // Not supported
}

// ✅ GOOD: Use equals for numeric comparison
{
  "condition": "if_equals count 10"
}

// ❌ BAD: Variable not defined
{
  "condition": "if undefined_variable"  // Variable doesn't exist
}

// ✅ GOOD: Variable defined in input_variables
{
  "condition": "if database_name"  // Defined in manifest
}
```

---

## Example: SQL Query Constructor - Database Context Manifest

```json
{
  "name": "sql-query-basic",
  "version": "1.0.0",
  "template_id": "sql_query_v1",
  "display_name": "SQL Query Constructor - Database Context",
  "description": "Two-phase strategy: Execute SQL statement and generate final report",
  "author": "TDA Core Team",
  "license": "AGPL-3.0",
  "homepage": "https://github.com/rgeissen/uderia",
  "repository": {
    "type": "git",
    "url": "https://github.com/rgeissen/uderia"
  },
  "keywords": ["sql", "database", "query", "teradata", "postgresql"],
  "compatibility": {
    "min_app_version": "1.0.0",
    "max_app_version": "2.x.x"
  },
  "dependencies": {
    "templates": [],
    "python_packages": []
  },
  "files": {
    "template": "sql_query_v1.json",
    "icon": "sql_icon.svg"
  },
  "permissions": [
    "database_access",
    "mcp_tools"
  ],
  "ui_components": {
    "config_panel": false,
    "preview_renderer": false
  },
  "population_modes": {
    "manual": {
      "supported": true,
      "description": "User manually enters question/SQL pairs through the template interface",
      "required_fields": ["user_query", "sql_statement"]
    },
    "auto_generate": {
      "supported": true,
      "requires_llm": true,
      "requires_mcp_context": true,
      "input_method": "mcp_context",
      "generation_endpoint": "/api/v1/rag/generate-questions",
      "description": "LLM generates question/SQL pairs from database schema and business context",
      "input_variables": {
        "context_topic": {
          "required": true,
          "description": "Business domain or subject area",
          "example": "customer analytics, sales reporting"
        },
        "conversion_rules": {
          "required": false,
          "description": "SQL dialect conversion rules for target database",
          "example": "Use TOP instead of LIMIT, convert boolean true/false to 1/0"
        },
        "database_name": {
          "required": false,
          "description": "Target database name",
          "example": "production_db"
        },
        "num_examples": {
          "required": true,
          "type": "integer",
          "default": 5,
          "min": 1,
          "max": 100,
          "description": "Number of question/SQL pairs to generate"
        }
      }
    }
  },
  "prompt_templates": {
    "question_generation": {
      "system_role": "You are a SQL expert helping to generate test questions and queries for a RAG system.",
      "task_description": "Based on the database context, generate {count} diverse business questions about \"{subject}\" with SQL queries.",
      "requirements": [
        "Generate EXACTLY {count} question/SQL pairs",
        "Questions should be natural language business questions",
        "SQL queries must be valid for the database schema shown",
        "ONLY use tables and columns explicitly listed in the schema"
      ],
      "output_format": "Return JSON array: [{ \"question\": \"...\", \"sql\": \"...\" }]",
      "critical_guidelines": [
        "Write COMPLETE SQL queries without truncation",
        "Response must be ONLY the JSON array",
        "Include all {count} pairs requested"
      ]
    }
  },
  "metadata": {
    "category": "Database",
    "difficulty": "beginner",
    "estimated_tokens": {
      "planning": 150,
      "execution": 180
    },
    "tags": ["built-in", "sql", "data-retrieval"]
  }
}
```

## Example: Advanced Template with Custom UI

```json
{
  "name": "api-rest-advanced",
  "version": "2.1.0",
  "template_id": "api_rest_v2",
  "display_name": "Advanced REST API Template",
  "description": "Multi-step REST API workflow with authentication and retry logic",
  "author": "community-developer",
  "license": "MIT",
  "homepage": "https://github.com/community-dev/api-rest-template",
  "repository": {
    "type": "git",
    "url": "https://github.com/community-dev/api-rest-template"
  },
  "keywords": ["api", "rest", "http", "authentication", "oauth"],
  "compatibility": {
    "min_app_version": "1.5.0",
    "max_app_version": "2.x.x"
  },
  "dependencies": {
    "templates": [],
    "python_packages": ["requests>=2.28.0", "oauthlib>=3.2.0"]
  },
  "files": {
    "template": "api_rest_v2.json",
    "ui_config": "ui/config-panel.html",
    "ui_script": "ui/config-panel.js",
    "validator": "validators/api_validator.py",
    "icon": "api_icon.svg"
  },
  "permissions": [
    "network",
    "mcp_tools"
  ],
  "ui_components": {
    "config_panel": true,
    "preview_renderer": true
  }
}
```

## Directory Structure

```
template-plugin-name/
├── manifest.json              # This file - plugin metadata
├── template.json              # Template definition (required)
├── README.md                  # Documentation
├── LICENSE                    # License file
├── icon.svg                   # Template icon (optional)
├── ui/                        # Custom UI components (optional)
│   ├── config-panel.html      # Custom configuration UI
│   └── config-panel.js        # UI logic
└── validators/                # Custom validators (optional)
    └── validator.py           # Input validation logic
```

## Usage

### For Template Developers

1. Create `manifest.json` in your template directory
2. Ensure all paths in `files` section are correct
3. Test locally before distribution
4. Package as `.tar.gz` or publish to git repository

### For End Users

Templates with manifests can be:
- Installed from marketplace (future feature)
- Installed from git URL
- Installed from local directory
- Hot-reloaded without app restart

## Population Modes

Templates can support two modes for populating RAG collections:

### 1. Manual Entry Mode
User manually enters question/answer pairs through the template interface.
- **Use case**: Precision control, custom examples, small datasets
- **Workflow**: User fills in template variables for each example
- **Required**: List of required template fields in `required_fields`

### 2. Auto-generate Mode
LLM automatically generates question/answer pairs from provided context.
- **Use case**: Rapid prototyping, large datasets, documentation-driven
- **Workflow**: User provides context (topic, documents, etc.) → LLM generates examples
- **Required**: LLM configuration, `input_variables` specification

### Population Flow (UI)
```
Add RAG Collection
  ├─ Step 1: Collection Details (name, description, MCP server)
  ├─ Step 2: Population Decision
  │    ├─ Option A: No Population (empty collection)
  │    └─ Option B: Populate with Template
  │         ├─ Select Template Type
  │         └─ Step 3: Population Method
  │              ├─ Manual Entry → Fill template fields
  │              └─ Auto-generate → Provide context + LLM generates
  └─ Create Collection
```

### Example: SQL Template with Both Modes

**Manual Mode:**
- User enters: `user_query`, `sql_statement`, `database_name`
- Creates individual RAG cases one by one
- Good for: Verified examples, edge cases, compliance-critical queries

**Auto-generate Mode:**
- User enters: `context_topic` (e.g., "customer analytics"), `document_content` (optional)
- LLM generates: 5-20 question/SQL pairs based on context
- Good for: Training data, documentation coverage, initial seeding

## Validation

### Manifest Validation
The application validates manifests on load:
- Required fields present
- Version format valid
- File paths exist
- Dependencies resolvable
- Permissions declared
- Population modes configuration valid

### Template File Validation
Template files referenced in manifests are validated using JSON schemas:

**For Planner Templates** (sql_query, api_request, etc.):
```python
# Validated against: schemas/planner-schema.json
from rag_templates.exceptions import SchemaValidationError

try:
    manager.get_template("sql_query_v1")
except SchemaValidationError as e:
    print(f"Schema errors: {e.schema_errors}")
    # Example errors:
    # - 'input_variables' is a required property
    # - 'template_id' does not match '^[a-z0-9_]+_v\d+$'
```

**For Knowledge Templates** (knowledge_repository):
```python
# Validated against: schemas/knowledge-template-schema.json
try:
    manager.get_template("knowledge_repo_v1")
except SchemaValidationError as e:
    print(f"Schema errors: {e.schema_errors}")
```

### Type Taxonomy Validation
Templates must correctly use three type concepts:

1. **template_type** (Strategy) - How template executes
   - Planner types: `sql_query`, `api_request`, `custom_workflow`
   - Knowledge type: `knowledge_repository`

2. **repository_type** (Storage) - How data is stored (derived from template_type)
   - `planner` - For execution strategy templates
   - `knowledge` - For document storage templates

3. **category** (UI Grouping) - How templates are organized
   - Examples: `Database`, `Knowledge Management`, `API Integration`

See `TYPE_TAXONOMY.md` for detailed explanation of these concepts.

## Error Handling

Templates use standardized exception hierarchy for consistent error reporting:

```python
from rag_templates.exceptions import (
    TemplateError,              # Base exception
    TemplateNotFoundError,      # Template doesn't exist
    TemplateValidationError,    # Validation failed
    SchemaValidationError,      # JSON schema validation failed
    ToolValidationError,        # Invalid MCP tool references
    TemplateRegistryError,      # Registry issues
    TemplateLoadError          # File loading failed
)

# Example: Handle missing template
try:
    template = manager.get_template("missing_v1")
except TemplateNotFoundError as e:
    print(f"Template {e.template_id} not found")

# Example: Handle validation errors
try:
    manager._validate_template(template_data)
except SchemaValidationError as e:
    print(f"Template: {e.template_id}")
    print(f"Errors: {e.schema_errors}")
except ToolValidationError as e:
    print(f"Invalid tools: {e.invalid_tools}")
```

All exceptions include rich context (template_id, details, original_error) for debugging.

## Security Considerations

- Custom validators run in restricted environment
- File system access limited to template directory
- Network access requires explicit permission
- Code scanning for malicious patterns
- Optional cryptographic signature verification
- MCP tool names validated against whitelist and live server capabilities

## Current Implementation Status

### ✅ Implemented
- **JSON Schema Validation** - Templates validated at load time (schemas/planner-schema.json, knowledge-template-schema.json)
- **Type Taxonomy** - Clear separation of template_type, repository_type, category
- **Error Handling** - Custom exception hierarchy with rich context
- **Tool Validation** - MCP tool names validated against TDA core tools and live server
- **Template Registry** - Central registry with metadata and status
- **Hot Reload** - Templates reload without app restart

### 🚧 Partially Implemented
- **Population Modes** - Manual and auto-generate modes defined in manifest
- **Category System** - Categories defined in registry, UI integration pending
- **Permission System** - Defined in manifest, enforcement pending

### 📋 Planned
- Digital signatures for verified publishers
- Dependency version constraints
- Backward compatibility declarations
- Update channels (stable, beta, nightly)
- Analytics hooks (opt-in)
- Template marketplace
- Version migration tools

---

## Template Registry Integration

### Overview

The `template_registry.json` file serves as the central discovery mechanism for all template plugins. Templates must be registered here to be discoverable by the UI and accessible through the API.

**Registry File Location**: `rag_templates/template_registry.json`

### Registry Structure

```json
{
  "registry_version": "2.0.0",
  "last_updated": "2025-11-29T00:00:00Z",
  "templates": [
    {
      "template_id": "sql_query_v1",
      "plugin_directory": "sql-query-basic",
      "template_file": "sql-query-basic/sql_query_v1.json",
      "manifest_file": "sql-query-basic/manifest.json",
      "status": "active",
      "display_order": 1,
      "category": "Database",
      "is_builtin": true,
      "notes": "Planner template: template_type=sql_query → repository_type=planner"
    }
  ],
  "template_status_definitions": {
    "active": "Template is ready for use",
    "beta": "Available but still being tested",
    "deprecated": "Being phased out",
    "draft": "Not yet available",
    "coming_soon": "Under development"
  }
}
```

### Registry Entry Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `template_id` | string | ✅ | Unique identifier matching template's `template_id` field (e.g., `sql_query_v1`) |
| `plugin_directory` | string | ✅ | Relative path to plugin directory from `rag_templates/templates/` |
| `template_file` | string | ✅ | Path to template.json file relative to `rag_templates/` |
| `manifest_file` | string | ✅ | Path to manifest.json file relative to `rag_templates/` |
| `status` | enum | ✅ | Template availability: `active`, `beta`, `deprecated`, `draft`, `coming_soon` |
| `display_order` | integer | ✅ | UI sort order (lower numbers appear first, e.g., 1=first, 2=second) |
| `category` | string | ✅ | UI grouping category (must match manifest `metadata.category`) |
| `is_builtin` | boolean | ✅ | `true` for system templates, `false` for user/community templates |
| `notes` | string | ❌ | Optional notes about template type relationships |

### Adding a New Template to Registry

**Step 1: Create Template Plugin Directory**
```bash
cd rag_templates/templates/
mkdir my-custom-template
cd my-custom-template
```

**Step 2: Create Required Files**
```
my-custom-template/
├── manifest.json        # Plugin metadata (required)
├── my_template_v1.json  # Template definition (required)
├── README.md            # Documentation (recommended)
└── LICENSE              # License file (recommended)
```

**Step 3: Add Registry Entry**

Edit `rag_templates/template_registry.json` and add your template to the `templates` array:

```json
{
  "template_id": "my_template_v1",
  "plugin_directory": "my-custom-template",
  "template_file": "my-custom-template/my_template_v1.json",
  "manifest_file": "my-custom-template/manifest.json",
  "status": "active",
  "display_order": 10,
  "category": "Custom Workflow",
  "is_builtin": false,
  "notes": "Custom template for specific use case"
}
```

**Step 4: Restart Application**
```bash
# Registry is loaded at startup
python -m trusted_data_agent.main
```

**Step 5: Verify Registration**
```bash
# Check logs for successful template loading
grep "Loaded template: my_template_v1" logs/app.log
```

### Display Order Guidelines

The `display_order` field controls UI sort order:

- **1-9**: Reserved for built-in templates
  - 1: Primary SQL template (database context)
  - 2: Secondary SQL template (document context)
  - 3: Knowledge repository template
  - 4-9: Future built-in templates

- **10-99**: User templates
  - Use increments of 10 for flexibility
  - Example: 10, 20, 30 (allows insertion at 15, 25, etc.)

- **100+**: Experimental/draft templates

**Example Ordering**:
```json
[
  {"template_id": "sql_query_v1", "display_order": 1},        // Built-in, first
  {"template_id": "sql_query_doc_v1", "display_order": 2},    // Built-in, second
  {"template_id": "knowledge_repo_v1", "display_order": 3},   // Built-in, third
  {"template_id": "my_api_template", "display_order": 10},    // User, first
  {"template_id": "my_workflow_template", "display_order": 20} // User, second
]
```

### Template Status Lifecycle

Templates progress through these statuses:

```
draft → coming_soon → beta → active → deprecated
```

- **`draft`**: Template is being developed, not shown in UI
- **`coming_soon`**: Template shown in UI but not selectable (with "Coming Soon" badge)
- **`beta`**: Template available but shows beta warning in UI
- **`active`**: Template fully available and recommended
- **`deprecated`**: Template still functional but shows deprecation warning

**UI Behavior by Status**:
- `active`: Normal display
- `beta`: Shows "Beta" badge, requires confirmation before use
- `deprecated`: Shows "Deprecated" badge, suggests alternatives
- `draft`/`coming_soon`: Shown but disabled in template selection dropdown

### Built-in vs. User Templates

**Built-in Templates** (`is_builtin: true`):
- Shipped with application
- Located in `rag_templates/templates/` (version-controlled)
- Cannot be deleted or modified by users
- Updated during application upgrades
- Examples: `sql-query-basic`, `knowledge-repository-basic`

**User Templates** (`is_builtin: false`):
- Created by users or installed from community
- Located in `rag_templates/templates/` or `~/.tda/templates/`
- Can be deleted or modified
- Persisted across application updates
- Examples: Custom API templates, domain-specific workflows

### Category System

Categories organize templates in the UI:

**Standard Categories**:
- `Database` - SQL queries, database operations
- `Knowledge Management` - Document storage and retrieval
- `API Integration` - REST API, GraphQL, webhook templates
- `Data Processing` - ETL, transformation workflows
- `Custom Workflow` - User-defined multi-step processes

**Category Guidelines**:
1. Use existing categories when possible
2. Category in registry must match `manifest.metadata.category`
3. Create new categories sparingly (coordinate with team)
4. Category determines UI grouping in template selection wizard

### Registry Validation

The system validates registry entries on load:

**Checks Performed**:
- ✅ `template_id` is unique across all entries
- ✅ `plugin_directory` exists on filesystem
- ✅ `template_file` exists and is valid JSON
- ✅ `manifest_file` exists and is valid JSON
- ✅ `status` is one of allowed values
- ✅ `display_order` is positive integer
- ✅ `category` matches manifest

**Validation Failure Behavior**:
- Invalid entries logged as warnings
- Template skipped (not loaded)
- Application continues (non-fatal error)
- Check logs: `grep "Template validation failed" logs/app.log`

### Hot Reload

Templates can be reloaded without restarting the application:

**API Endpoint**: `POST /api/v1/rag/templates/reload`

**Usage**:
```bash
curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
  -H "Authorization: Bearer $TOKEN"
```

**What Gets Reloaded**:
- Registry file (`template_registry.json`)
- All manifest files
- All template files
- Schema validations re-run

**Use Cases**:
- Testing new templates during development
- Updating template metadata without restart
- Fixing validation errors

### Example: Complete New Template Integration

**Scenario**: Add a custom REST API template

**1. Create Plugin Directory**
```bash
mkdir -p rag_templates/templates/api-rest-v1
cd rag_templates/templates/api-rest-v1
```

**2. Create manifest.json**
```json
{
  "name": "api-rest-v1",
  "version": "1.0.0",
  "template_id": "api_rest_v1",
  "display_name": "REST API Call Template",
  "description": "Execute REST API calls with authentication",
  "author": "My Name",
  "license": "MIT",
  "files": {
    "template": "api_rest_v1.json"
  },
  "population_modes": {
    "manual": {
      "supported": true,
      "required_fields": ["endpoint", "method"]
    }
  },
  "metadata": {
    "category": "API Integration",
    "difficulty": "intermediate",
    "tags": ["api", "rest", "http"]
  }
}
```

**3. Create api_rest_v1.json**
```json
{
  "template_id": "api_rest_v1",
  "template_type": "api_request",
  "input_variables": [...],
  "strategy_template": {...}
}
```

**4. Register in template_registry.json**
```json
{
  "template_id": "api_rest_v1",
  "plugin_directory": "api-rest-v1",
  "template_file": "api-rest-v1/api_rest_v1.json",
  "manifest_file": "api-rest-v1/manifest.json",
  "status": "active",
  "display_order": 10,
  "category": "API Integration",
  "is_builtin": false,
  "notes": "Custom REST API template for external integrations"
}
```

**5. Reload Templates**
```bash
curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
  -H "Authorization: Bearer $TOKEN"
```

**6. Verify in UI**
- Open "Add Collection" wizard
- Check "API Integration" category
- Template should appear with display_order=10

---

## Related Documentation

- **`TYPE_TAXONOMY.md`** - Understanding template_type, repository_type, and category
- **`schemas/README.md`** - JSON schema validation details
- **`schemas/planner-schema.json`** - Schema for execution strategy templates
- **`schemas/knowledge-template-schema.json`** - Schema for document storage templates
- **`exceptions.py`** - Custom exception classes for error handling
- **`IMPROVEMENTS_LOG.md`** - History of system improvements and current health score
