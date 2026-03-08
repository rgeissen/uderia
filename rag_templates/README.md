# Planner Repository Constructor Library

This directory contains the constructor library for building **Planner Repositories** - specialized RAG collections that store execution strategies and planning patterns. These constructors enable automatic generation of proven execution traces that guide the agent's decision-making process.

**Repository Types:**
- **Planner Repositories** (built by these constructors): Execution patterns and strategies for proven task completion
  - Few-shot learning examples for RAG-based planning
  - Automatically captured from successful agent executions
  - Manually populated via constructor templates
  - Retrieved during `_generate_meta_plan()` for strategic guidance
  
- **Knowledge Repositories** (separate system): General documents and reference materials
  - Domain knowledge, technical documentation, and business context
  - Uploaded as PDF, TXT, DOCX, MD files with configurable chunking
  - Retrieved during `_retrieve_knowledge_for_planning()` for contextual enrichment
  - Fully integrated with planner (Phase 1 complete - Nov 2025)

## Structure

```
rag_templates/
├── README.md                      # This file
├── template_registry.json         # Template registry and metadata
└── templates/                     # Individual template definitions
    ├── sql_query_v1.json         # SQL Query Constructor - Database Context
    ├── api_request_v1.json       # (Future) API Request Template
    └── custom_workflow_v1.json   # (Future) Custom Workflow Template
```

## Template Registry

The `template_registry.json` file contains metadata about all available templates:

- **template_id**: Unique identifier for the template
- **template_file**: JSON file containing the template definition
- **status**: Template status (`active`, `beta`, `deprecated`, `draft`)
- **display_order**: Order in which templates appear in the UI

Only templates with `status: "active"` are loaded at startup.

## Template Definition Format

Each template JSON file contains:

### Required Sections

1. **Metadata**
   - `template_id`: Unique identifier
   - `template_name`: Display name
   - `template_type`: Type identifier (sql_query, api_request, etc.)
   - `description`: Brief description
   - `status`: Template status
   - `version`: Template version

2. **Input Variables**
   - User-provided parameters (e.g., user_query, sql_statement)
   - Each variable specifies: type, required, description, placeholder, validation rules
   
3. **Output Configuration**
   - Auto-generated values (session_id, tokens, feedback, etc.)
   - Marks which values are editable at runtime
   
4. **Strategy Template**
   - Phase definitions and goal templates
   - Tool mappings and argument configurations
   
5. **Metadata Mapping**
   - How input variables map to case metadata
   
6. **Validation Rules**
   - Input validation logic

## Template Usage

Templates are loaded automatically at application startup:

1. **Template Manager** loads `template_registry.json`
2. Loads all active template definitions from `templates/` directory
3. Validates template structure
4. Makes templates available via `get_template_manager()`

### Accessing Templates

```python
from trusted_data_agent.agent.rag_template_manager import get_template_manager

# Get template manager
manager = get_template_manager()

# List all templates
templates = manager.list_templates()

# Get specific template
sql_template = manager.get_template("sql_query_v1")

# Get editable configuration
config = manager.get_template_config("sql_query_v1")

# Update configuration (runtime only)
manager.update_template_config("sql_query_v1", {
    "default_mcp_tool": "custom_sql_executor",
    "estimated_input_tokens": 200,
    "estimated_output_tokens": 250
})
```

### Creating New Templates

#### Built-In Templates (System Templates)

1. Create a new JSON file in `templates/` directory
2. Follow the structure of `sql_query_v1.json`
3. Add entry to `template_registry.json`
4. Set status to `"active"` to enable
5. Restart application to load new template

#### User Templates (Custom Templates)

User-created templates can be placed in the **user template directory** for automatic discovery without modifying the system installation.

**Directory Location:** `~/.tda/templates/`

**Directory Structure:**
```
~/.tda/templates/
├── my-custom-template/
│   ├── manifest.json
│   ├── my_template_v1.json
│   └── README.md
└── another-template/
    ├── manifest.json
    ├── template.json
    └── README.md
```

**Template Discovery Process:**
1. **Built-in templates** loaded from `rag_templates/templates/` (system installation)
2. **User templates** loaded from `~/.tda/templates/` (user home directory)
3. User templates with the same `template_id` **override** built-in templates
4. Templates registered automatically on application startup
5. Use `POST /api/v1/rag/templates/reload` to hot-reload without restart

**Benefits:**
- ✅ **Separation of Concerns**: Keep custom templates separate from system templates
- ✅ **Persistence**: Templates survive application updates and reinstallations
- ✅ **Portability**: Share templates between users by copying directory
- ✅ **No System Modification**: Create templates without editing system files
- ✅ **Override System Templates**: Customize built-in templates for your environment

**Example: Creating a User Template**

1. Create directory:
```bash
mkdir -p ~/.tda/templates/product-inventory
cd ~/.tda/templates/product-inventory
```

2. Create manifest.json (minimal):
```json
{
  "name": "product-inventory-custom",
  "template_id": "product_inventory_v1",
  "template_type": "sql_query",
  "version": "1.0.0",
  "description": "Custom product inventory queries",
  "population_modes": {
    "manual": {"supported": true},
    "auto_generate": {"supported": true}
  }
}
```

3. Create template JSON file following the planner template schema

4. Reload templates:
```bash
curl -X POST http://localhost:5050/api/v1/rag/templates/reload \
  -H "Authorization: Bearer $JWT"
```

5. Verify template loaded:
- Navigate to Setup → RAG Collections
- Check if "Product Inventory Custom" appears in template dropdown

**User Template Registry:**
User templates are automatically registered when discovered. No need to manually edit `template_registry.json`.

## Runtime Configuration

Template configurations can be edited at runtime via the UI:

- Editable values are marked with `"editable": true` in the template
- Changes are stored in memory during the session
- To persist changes permanently, modify the template JSON file

## Best Practices

1. **Version Templates**: Use semantic versioning (v1.0.0, v1.1.0, v2.0.0)
2. **Maintain Backwards Compatibility**: Create new versions rather than breaking existing templates
3. **Validate Thoroughly**: Ensure all required fields are present
4. **Document Examples**: Include usage examples in the template
5. **Test Before Activating**: Use `"status": "beta"` for testing, then promote to `"active"`

## Example: SQL Query Constructor - Database Context

See `templates/sql_query_v1.json` for a complete example of a production-ready template.

Key features:
- Clear input variable definitions with validation
- Editable output configuration
- Dynamic phase goal generation
- Conditional argument inclusion
- Token estimation defaults
