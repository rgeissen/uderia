# Template JSON Schemas

This directory contains JSON Schema definitions for validating RAG template files.

## Overview

Templates are validated against JSON schemas during loading to catch structural errors before runtime. This provides:

- **Early error detection** - Catch missing required fields at load time
- **Type safety** - Ensure values match expected types
- **Format validation** - Validate patterns (e.g., template_id format)
- **Better error messages** - Clear indication of what's wrong

## Schemas

### `planner-schema.json`
JSON schema for **planner repository templates** (execution strategy templates).

**Used for templates with:**
- `template_type`: Any value except `knowledge_repository`
- Examples: `sql_query`, `api_request`, `custom_workflow`

**Required fields:**
- `template_id` - Must match pattern `^[a-z0-9_]+_v\d+$`
- `template_name` - Human-readable name
- `template_type` - Strategy type identifier
- `input_variables` - User-provided parameters
- `output_configuration` - Generated metadata
- `strategy_template` - Execution phases definition

**Key validation rules:**
- Phase numbers must be >= 1
- Phases array must not be empty
- Each phase must have either `goal` or `goal_template`
- Input variable names must match `^[a-z_][a-z0-9_]*$`
- Template IDs must end with `_vN` version suffix

### `knowledge-template-schema.json`
JSON schema for **knowledge repository templates** (document storage templates).

**Used for templates with:**
- `template_type`: `knowledge_repository`

**Required fields:**
- `template_id` - Must match pattern `^[a-z0-9_]+_v\d+$`
- `template_name` - Human-readable name
- `template_type` - Must be `knowledge_repository`
- `repository_configuration` - Storage and chunking config

**Key validation rules:**
- `repository_type` must be `knowledge`
- `requires_mcp_server` must be boolean
- Chunking strategy options validated
- Embedding model configuration validated

## Validation Behavior

### Automatic Validation
Templates are automatically validated when:
1. Application starts and loads templates
2. Templates are hot-reloaded via `/v1/rag/templates/reload`
3. New templates are added to registry

### Validation Process
```python
# 1. Determine schema type based on template_type
if template_type == "knowledge_repository":
    schema = "knowledge"
else:
    schema = "planner"

# 2. Validate against JSON schema (if available)
validator = Draft7Validator(schema)
errors = validator.iter_errors(template_data)

# 3. If validation fails, template is rejected
if errors:
    logger.error("Template validation failed")
    return False

# 4. Template is loaded and available for use
```

### Fallback Validation
If `jsonschema` library is not available, falls back to basic field validation:
- Checks for required top-level fields only
- Does not validate structure or formats
- Less comprehensive but ensures basic functionality

## Testing Validation

### Test Valid Template
```python
from src.trusted_data_agent.agent.rag_template_manager import RAGTemplateManager

manager = RAGTemplateManager()

valid_template = {
    "template_id": "test_v1",
    "template_name": "Test Template",
    "template_type": "sql_query",
    "input_variables": {
        "user_query": {
            "type": "string",
            "required": True,
            "description": "User question"
        }
    },
    "output_configuration": {
        "session_id": {"type": "constant", "value": "00000000-0000-0000-0000-000000000000"}
    },
    "strategy_template": {
        "phases": [
            {"phase": 1, "goal": "Test", "relevant_tools": [], "arguments": {}}
        ]
    }
}

is_valid = manager._validate_template(valid_template)
print(f"Valid: {is_valid}")  # Should print: Valid: True
```

### Test Invalid Template
```python
broken_template = {
    "template_id": "broken",  # Invalid format (missing _vN)
    "template_name": "Broken Template",
    "template_type": "sql_query"
    # Missing required fields: input_variables, output_configuration, strategy_template
}

is_valid = manager._validate_template(broken_template)
print(f"Valid: {is_valid}")  # Should print: Valid: False
# Logs will show specific validation errors
```

## Common Validation Errors

### Error: `'strategy_template' is a required property`
**Cause:** Planner template missing strategy definition  
**Fix:** Add `strategy_template` object with `phases` array

### Error: `'template_id' does not match pattern`
**Cause:** Template ID doesn't follow naming convention  
**Fix:** Use format `lowercase_name_v1`, e.g., `sql_query_v1`

### Error: `'phases' should be non-empty`
**Cause:** Strategy has empty phases array  
**Fix:** Add at least one phase to `strategy_template.phases`

### Error: `'repository_configuration' is a required property`
**Cause:** Knowledge template missing repository config  
**Fix:** Add `repository_configuration` object

### Error: Invalid type for field
**Cause:** Field value doesn't match expected type  
**Fix:** Check schema for correct type (string, integer, boolean, etc.)

## Extending Schemas

### Adding New Fields
1. Edit appropriate schema file (`planner-schema.json` or `knowledge-template-schema.json`)
2. Add field to `properties` section
3. Optionally add to `required` array if mandatory
4. Define validation rules (type, pattern, min/max, etc.)
5. Test with valid and invalid examples

### Example: Add New Field
```json
{
  "properties": {
    "new_field": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "description": "Description of new field"
    }
  },
  "required": ["template_id", "template_name", "new_field"]
}
```

## Schema Standards

### JSON Schema Version
- Using **JSON Schema Draft 7**
- Full specification: https://json-schema.org/draft-07/schema

### Naming Conventions
- Schema files: `{type}-schema.json`
- Template IDs: `^[a-z0-9_]+_v\d+$` (e.g., `sql_query_v1`)
- Variable names: `^[a-z_][a-z0-9_]*$` (e.g., `user_query`)

### Best Practices
1. **Use descriptive field names** - Clear, self-documenting
2. **Add descriptions** - Help text for all fields
3. **Provide examples** - Show valid values
4. **Set appropriate constraints** - min/max, patterns, enums
5. **Test thoroughly** - Both valid and invalid cases

## Troubleshooting

### Schema not loading
**Check:**
- Schema file exists in `rag_templates/schemas/`
- File has valid JSON syntax
- File has read permissions

### Validation not active
**Check:**
- `jsonschema` library installed (`pip install jsonschema`)
- No errors in logs during schema loading
- Template manager initialized properly

### False positives (valid templates rejected)
**Check:**
- Template matches schema structure exactly
- All required fields present
- Field types match schema definitions
- Review validation error messages for specifics

## References

- JSON Schema Documentation: https://json-schema.org/
- Python jsonschema Library: https://python-jsonschema.readthedocs.io/
- Template Development Guide: `../../docs/RAG_Templates/TEMPLATE_PLUGIN_DEVELOPMENT.md`
