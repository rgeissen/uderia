# Template Plugin Development Guide

## Overview

This guide explains how to create custom template plugins for the RAG system. Templates are modular, self-contained plugins that define strategies for generating RAG case studies.

## Plugin Structure

```
rag_templates/templates/
└── my-custom-template/              # Plugin directory
    ├── manifest.json                # Required: UI config & metadata
    ├── my_template_v1.json          # Required: Strategy definition
    └── README.md                    # Recommended: Documentation
```

## Step-by-Step: Create a Custom Template

### 1. Create Plugin Directory

```bash
cd rag_templates/templates
mkdir my-custom-template
cd my-custom-template
```

### 2. Create manifest.json

The manifest defines UI fields, validation rules, and metadata.

**Example: Basic SQL Template**
```json
{
  "name": "my-custom-template",
  "version": "1.0.0",
  "template_id": "my_custom_v1",
  "display_name": "My Custom SQL Template",
  "description": "Custom template for specific SQL queries",
  "author": "Your Name",
  "license": "MIT",
  "keywords": ["sql", "custom"],
  "compatibility": {
    "min_app_version": "1.0.0"
  },
  
  "population_modes": {
    "manual": {
      "enabled": true,
      "label": "Manual Entry",
      "description": "Manually enter SQL examples",
      "input_variables": {
        "database_name": {
          "required": true,
          "type": "string",
          "description": "Target database name",
          "example": "my_database"
        },
        "schema_name": {
          "required": false,
          "type": "string",
          "description": "Optional schema name",
          "example": "public"
        }
      }
    },
    
    "auto_generate": {
      "enabled": true,
      "label": "LLM-Assisted Generation",
      "description": "Generate examples using LLM",
      "input_variables": {
        "context_topic": {
          "required": true,
          "type": "string",
          "description": "Business context for generation",
          "example": "Customer analytics and reporting",
          "label": "Context Topic"
        },
        "num_examples": {
          "required": true,
          "type": "integer",
          "default": 5,
          "min": 1,
          "max": 1000,
          "description": "Number of examples to generate",
          "label": "Num Examples"
        },
        "database_name": {
          "required": true,
          "type": "string",
          "description": "Target database name",
          "label": "Database Name"
        }
      }
    }
  }
}
```

### 3. Create Template JSON (Strategy)

The template JSON defines the execution strategy with phases and tool calls.

**Example: Two-Phase SQL Strategy**
```json
{
  "template_id": "my_custom_v1",
  "template_version": "1.0.0",
  "template_name": "My Custom SQL Template",
  "strategy_template": {
    "strategy_name": "Custom SQL Query Strategy",
    "strategy_description": "Execute SQL query and generate report",
    
    "phases": [
      {
        "phase_number": 1,
        "phase_name": "Execute Query",
        "phase_description": "Execute the SQL query against the database",
        "tool": "base_readQuery",
        "arguments": [
          {
            "name": "sql",
            "type": "sql_statement",
            "required": true,
            "description": "The SQL query to execute (must include database name)"
          }
        ]
      },
      {
        "phase_number": 2,
        "phase_name": "Generate Report",
        "phase_description": "Generate natural language report from results",
        "tool": "TDA_FinalReport",
        "arguments": [
          {
            "name": "user_query",
            "type": "user_query",
            "required": true,
            "description": "The original user question"
          }
        ]
      }
    ],
    
    "output_config": {
      "format": "structured_json",
      "include_metadata": true
    }
  }
}
```

### 4. Register Template

Add your template to `rag_templates/template_registry.json`:

```json
{
  "templates": [
    {
      "template_id": "my_custom_v1",
      "template_file": "my-custom-template/my_template_v1.json",
      "plugin_directory": "my-custom-template",
      "status": "active",
      "priority": 10
    }
  ]
}
```

### 5. Restart Server

```bash
python -m trusted_data_agent.main
```

Your template will now appear in the UI!

## Field Types & Validation

### Input Variable Types

| Type | Description | Validation |
|------|-------------|------------|
| `string` | Text input | N/A |
| `integer` | Numeric input | `min`, `max` |
| `number` | Float input | `min`, `max` |
| `boolean` | Checkbox | N/A |

### Validation Properties

```json
{
  "field_name": {
    "required": true,           // Field is mandatory
    "type": "integer",          // Data type
    "default": 5,               // Default value
    "min": 1,                   // Minimum value (numbers)
    "max": 1000,                // Maximum value (numbers)
    "description": "Help text", // Tooltip/help text
    "label": "Display Name",    // UI label
    "example": "example_value"  // Placeholder text
  }
}
```

## Argument Types

Templates define arguments for each phase. Common types:

| Type | Used In | Description |
|------|---------|-------------|
| `sql_statement` | Phase 1 | SQL query to execute |
| `user_query` | Phase 2 | Original user question |
| `context` | Any | Additional context |
| `schema_info` | Any | Schema metadata |

## Advanced: Multi-Phase Templates

### Three-Phase Example: Document + SQL + Report

```json
{
  "phases": [
    {
      "phase_number": 1,
      "phase_description": "Retrieve relevant documentation",
      "tool": "retrieve_documentation",
      "arguments": [
        {
          "name": "query",
          "type": "user_query",
          "required": true
        }
      ]
    },
    {
      "phase_number": 2,
      "phase_description": "Execute SQL query",
      "tool": "base_readQuery",
      "arguments": [
        {
          "name": "sql",
          "type": "sql_statement",
          "required": true
        }
      ]
    },
    {
      "phase_number": 3,
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
```

## Best Practices

### ✅ DO

- **Use descriptive IDs**: `customer_analytics_v1` not `template1`
- **Version your templates**: Increment version for breaking changes
- **Validate inputs**: Set appropriate min/max for numeric fields
- **Document clearly**: Add comprehensive descriptions
- **Test thoroughly**: Try both manual and auto-generate modes
- **Keep it simple**: Start with 2-phase templates

### ❌ DON'T

- **Duplicate arguments**: Phase 1 should only have necessary args (not database_name if it's in SQL)
- **Hardcode values**: Use input variables instead
- **Skip validation**: Always set min/max for numeric inputs
- **Use generic names**: Be specific about what the template does
- **Forget to restart**: Server must restart to load new templates

## Common Patterns

### Pattern 1: Simple Query

```
Phase 1: Execute SQL
Phase 2: Format Results
```

### Pattern 2: Query with Context

```
Phase 1: Retrieve documentation/schema
Phase 2: Execute SQL with context
Phase 3: Generate enriched report
```

### Pattern 3: Multi-Step Workflow

```
Phase 1: Authenticate/Setup
Phase 2: Execute primary action
Phase 3: Post-process results
Phase 4: Generate report
```

## Troubleshooting

### Template Not Appearing in UI

1. Check `template_registry.json` syntax
2. Verify `template_id` matches in all files
3. Ensure `plugin_directory` path is correct
4. Restart the server
5. Check browser console for errors

### Validation Errors

1. Verify all `required` fields are provided
2. Check min/max ranges for numeric fields
3. Ensure field types match (`integer` vs `string`)
4. Restart server after manifest changes

### Generated Questions Poor Quality

1. Make context_topic more specific
2. Provide better schema information
3. Reduce num_examples for higher quality
4. Review and manually edit generated cases

## Migration from Legacy Templates

If you have old templates at the root level:

1. Create plugin directory: `templates/my-template/`
2. Move template JSON into plugin directory
3. Create manifest.json with UI configuration
4. Update template_registry.json
5. Remove old root-level template file
6. Restart server

**Key Changes:**
- Database name removed from Phase 1 arguments (embed in SQL)
- Manifest now required for UI integration
- Plugin directory structure required
- Validation rules in manifest, not hardcoded

## Example Templates

See existing templates for reference:
- `sql-query-basic/` - Basic SQL with business context
- `sql-query-doc-context/` - SQL with document retrieval

## Support

For questions or issues:
- GitHub: https://github.com/rgeissen/uderia
- Check server logs for template loading errors
- Validate JSON syntax in manifest and template files
