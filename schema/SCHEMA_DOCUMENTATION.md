# Uderia Prompt Management System - Schema Documentation

**Version:** 1.0  
**Database:** tda_auth.db (integrated with existing authentication/configuration database)  
**Created:** 2025-12-18  
**Status:** Phase 1 - Foundation

---

## Table of Contents

1. [Overview](#overview)
2. [Database Integration](#database-integration)
3. [Schema Architecture](#schema-architecture)
4. [Table Reference](#table-reference)
5. [Parameter System](#parameter-system)
6. [Profile Integration](#profile-integration)
7. [Query Examples](#query-examples)
8. [Migration Notes](#migration-notes)

---

## Overview

The Prompt Management System migrates Uderia from file-based prompt storage (`prompts.dat` + `prompt_overrides/`) to a flexible, database-backed system with:

- **Encrypted storage** using SQLCipher with license-based keys in **tda_auth.db**
- **Global and local parameters** with validation
- **Prompt classes** for organization and template reuse
- **Profile integration** for persona-specific prompts (profiles stored in tda_config.json)
- **Version history** for audit trails and rollback
- **Tier-gated maintenance** (read-only for all, edit for Prompt Engineer/Enterprise)

---

## Database Integration

### Integration with tda_auth.db

The prompt management tables are added to the existing `tda_auth.db` database:

- **Database File:** `/path/to/tda_auth.db` (existing authentication/configuration database)
- **Encryption:** SQLCipher with license-based `prompt_key`
- **Table Count:** Adds 13 new tables to existing 23 tables
- **Foreign Keys:** References existing `users` table for audit trails

### Profile Storage Architecture

**IMPORTANT:** Profiles are NOT stored in this database. They are managed separately:

- **Storage Location:** `tda_config.json` (JSON file)
- **Management:** ConfigManager class (`get_profiles()`, `add_profile()`, `update_profile()`, etc.)
- **Profile ID Format:** TEXT strings (e.g., `"profile-1763993711628-vvbh23q09"`, `"1763819257473-ivpnukbbe-admin-default"`)
- **Schema References:** All `profile_id` columns are TEXT type with NO foreign key constraints
- **Profile Structure:**
  ```json
  {
    "id": "profile-1763993711628-vvbh23q09",
    "name": "Data Science Profile",
    "tag": "@datascience",
    "llmConfigurationId": "config-123",
    "mcpServerId": "server-456",
    "isDefault": false,
    "classification_mode": "auto",
    "tools": [],
    "prompts": {...},
    "ragCollections": []
  }
  ```

### Referential Integrity

- ✅ **Users:** FK to `users.id` (INTEGER, in tda_auth.db)
- ✅ **Prompts/Classes:** Internal FKs within new schema
- ❌ **Profiles:** NO FK constraints - profile_id is TEXT without referential integrity
  - Validation must be done in application code (check ConfigManager.get_profiles())
  - Orphaned profile_id references possible if profiles deleted from JSON

---

## Schema Architecture

### Core Components

```
┌─────────────────────┐
│  Prompt Classes     │  (Organization & Templates)
│  - Categories       │
│  - Inheritance      │
└──────────┬──────────┘
           │
           │ belongs to
           ↓
┌─────────────────────┐
│     Prompts         │  (Actual Content)
│  - Content          │
│  - Role             │
│  - Provider         │
└──────────┬──────────┘
           │
           ├──→ Prompt Versions (History)
           ├──→ Prompt Overrides (User/Profile Custom)
           └──→ Prompt Parameters (Local)
```

### Parameter System

```
┌──────────────────────┐
│  Global Parameters   │  (System-wide)
│  - System-managed    │  (auto-populated)
│  - User-configurable │  (can override)
└──────────┬───────────┘
           │
           ├──→ Global Parameter Overrides (Profile/User)
           │
┌──────────┴───────────┐
│  Local Parameters    │  (Prompt-specific)
│  - Per-prompt config │
│  - Validation rules  │
└──────────────────────┘
```

### Profile Integration

```
┌─────────────┐
│  Profile    │
└──────┬──────┘
       │
       ├──→ Profile Prompt Assignments (role → prompt)
       │    └──→ Profile Prompt Parameter Values
       │
       └──→ Profile Class Assignments (optional)
            └──→ Profile Class Parameter Overrides
```

---

## Table Reference

### Core Tables

#### `prompt_classes`
Organizes prompts into categories and enables template inheritance.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Unique identifier |
| `name` | TEXT UNIQUE | System name (e.g., 'StrategicPlanningTemplates') |
| `display_name` | TEXT | Human-readable name |
| `class_type` | TEXT | 'category' or 'template' |
| `parent_class_id` | INTEGER FK | Parent class for inheritance |
| `is_active` | BOOLEAN | Active status |

**Indexes:**
- `idx_prompt_classes_active` - Active classes
- `idx_prompt_classes_type` - Class type filtering
- `idx_prompt_classes_parent` - Hierarchy queries

---

#### `prompts`
Stores actual prompt content with metadata.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Unique identifier |
| `name` | TEXT UNIQUE | System name (e.g., 'MASTER_SYSTEM_PROMPT') |
| `display_name` | TEXT | Human-readable name |
| `content` | TEXT | Prompt text with {parameter} placeholders |
| `class_id` | INTEGER FK | Class membership |
| `role` | TEXT | 'strategic', 'tactical', 'recovery', 'report', 'system' |
| `provider` | TEXT | NULL (universal) or specific provider |
| `version` | INTEGER | Current version number |
| `is_template` | BOOLEAN | Base template flag |
| `is_system_default` | BOOLEAN | System-wide default flag |

**Indexes:**
- `idx_prompts_name` - Name lookup
- `idx_prompts_active` - Active prompts
- `idx_prompts_role` - Role filtering
- `idx_prompts_provider` - Provider filtering

**Triggers:**
- `update_prompts_timestamp` - Auto-update timestamp
- `create_prompt_version_on_update` - Auto-create version history

---

#### `prompt_versions`
Audit trail for all prompt changes.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Unique identifier |
| `prompt_id` | INTEGER FK | Parent prompt |
| `version` | INTEGER | Version number |
| `content` | TEXT | Snapshot of content |
| `changed_by` | TEXT | User who changed it |
| `change_reason` | TEXT | Why it was changed |

**Indexes:**
- `idx_prompt_versions_prompt` - By prompt
- `idx_prompt_versions_created` - By date

---

#### `prompt_overrides`
User or profile-specific custom prompts.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Unique identifier |
| `prompt_id` | INTEGER FK | Base prompt |
| `user_uuid` | TEXT | User identifier (nullable) |
| `profile_id` | INTEGER | Profile identifier (nullable) |
| `content` | TEXT | Custom prompt content |

**Priority:** profile > user > system default

**Indexes:**
- `idx_prompt_overrides_user` - User lookups
- `idx_prompt_overrides_profile` - Profile lookups

---

### Parameter Tables

#### `global_parameters`
System-wide parameters available to all prompts.

| Column | Type | Description |
|--------|------|-------------|
| `parameter_name` | TEXT PK | Unique parameter name |
| `parameter_type` | TEXT | 'string', 'integer', 'boolean', 'json', 'enum' |
| `is_system_managed` | BOOLEAN | Auto-populated by system |
| `is_user_configurable` | BOOLEAN | Users can override |
| `default_value` | TEXT | Default (as string) |
| `allowed_values` | TEXT | JSON array for enum types |

**Examples:**
- System-managed: `mcp_system_name`, `tools_context`, `current_provider`
- User-configurable: `default_verbosity`, `enable_cost_warnings`

---

#### `global_parameter_overrides`
Custom values for global parameters per user/profile.

| Column | Type | Description |
|--------|------|-------------|
| `parameter_name` | TEXT FK | Global parameter |
| `user_uuid` | TEXT | User (nullable) |
| `profile_id` | INTEGER | Profile (nullable) |
| `override_value` | TEXT | Custom value |

---

#### `prompt_parameters`
Prompt-specific local parameters with validation.

| Column | Type | Description |
|--------|------|-------------|
| `prompt_id` | INTEGER FK | Parent prompt |
| `parameter_name` | TEXT | Parameter name |
| `parameter_type` | TEXT | Data type |
| `is_required` | BOOLEAN | Must be provided |
| `default_value` | TEXT | Default if not provided |
| `allowed_values` | TEXT | Enum options (JSON) |
| `validation_regex` | TEXT | String validation |
| `min_value` / `max_value` | NUMERIC | Numeric bounds |

**Example:**
```json
{
  "prompt_id": 1,
  "parameter_name": "planning_depth",
  "parameter_type": "enum",
  "allowed_values": ["shallow", "medium", "deep"],
  "default_value": "medium"
}
```

---

#### `prompt_class_parameters`
Class-level parameters inherited by all prompts in class.

Similar structure to `prompt_parameters` but at class level.

---

### Profile Integration Tables

#### `profile_prompt_assignments`
Maps profiles to prompts by role.

| Column | Type | Description |
|--------|------|-------------|
| `profile_id` | INTEGER | Profile identifier |
| `prompt_role` | TEXT | 'strategic', 'tactical', 'recovery', 'report', 'system' |
| `prompt_id` | INTEGER FK | Prompt to use |

**Constraint:** One prompt per role per profile (UNIQUE on profile_id + prompt_role)

**Example:**
```sql
-- @DBA profile uses SQL-optimized strategic planner
INSERT INTO profile_prompt_assignments (profile_id, prompt_role, prompt_id)
VALUES (5, 'strategic', 10);  -- profile 5 = @DBA, prompt 10 = STRATEGIC_SQL_OPTIMIZER
```

---

#### `profile_prompt_parameter_values`
Profile-specific values for prompt parameters.

| Column | Type | Description |
|--------|------|-------------|
| `assignment_id` | INTEGER FK | Profile prompt assignment |
| `parameter_name` | TEXT | Parameter to set |
| `parameter_value` | TEXT | Value for this profile |

**Example:**
```sql
-- @DBA profile sets planning_depth to 'deep'
INSERT INTO profile_prompt_parameter_values (assignment_id, parameter_name, parameter_value)
VALUES (1, 'planning_depth', 'deep');
```

---

## Parameter System

### Parameter Types

1. **Global Parameters**
   - Available to ALL prompts
   - Two subtypes:
     - **System-managed:** Auto-populated (`tools_context`, `mcp_system_name`)
     - **User-configurable:** Can be overridden (`default_verbosity`)

2. **Local Parameters**
   - Specific to individual prompts
   - Define prompt behavior
   - Include validation rules

3. **Class Parameters**
   - Defined at class level
   - Inherited by all prompts in class
   - Can be overridden at prompt level

### Parameter Resolution Order

1. Profile-specific local parameter value
2. Prompt default local parameter value
3. Class inherited parameter value
4. Profile override of global parameter
5. User override of global parameter
6. Global parameter default
7. System-managed global parameter (runtime)

### Example Parameter Usage

```text
Prompt Content:
"You are analyzing data from {mcp_system_name}. 
Available tools: {tools_context}
Planning depth: {planning_depth}
Optimization focus: {optimization_focus}"

Global Parameters (system-managed):
- mcp_system_name = "Teradata" (from APP_CONFIG)
- tools_context = "base_readQuery, base_tableList..." (from STATE)

Local Parameters (prompt-specific):
- planning_depth = "deep" (from profile parameter value)
- optimization_focus = "performance" (from prompt default)

Final Rendered:
"You are analyzing data from Teradata.
Available tools: base_readQuery, base_tableList...
Planning depth: deep
Optimization focus: performance"
```

---

## Profile Integration

### How Profiles Use Prompts

Each profile defines which prompts to use for each execution stage:

```
@DBA Profile:
├─ strategic → STRATEGIC_SQL_OPTIMIZER
│  └─ planning_depth: deep
│  └─ optimization_focus: performance
├─ tactical → TACTICAL_QUERY_EXECUTOR
├─ recovery → RECOVERY_SQL_ERROR
└─ system → MASTER_SYSTEM_PROMPT

@ANALYST Profile:
├─ strategic → STRATEGIC_BUSINESS_PLANNER
│  └─ planning_depth: medium
│  └─ visualization_emphasis: high
├─ tactical → TACTICAL_QUERY_EXECUTOR
├─ report → REPORT_EXECUTIVE_SUMMARY
└─ system → GOOGLE_MASTER_SYSTEM_PROMPT
```

### Profile-Prompt Assignment Flow

1. User selects @DBA profile
2. System looks up profile_prompt_assignments for profile_id = 5
3. For strategic phase, uses prompt_id = 10 (STRATEGIC_SQL_OPTIMIZER)
4. Fetches prompt content
5. Resolves parameters (global + local + profile overrides)
6. Renders final prompt with all parameters substituted
7. Sends to LLM

---

## Query Examples

### Get Prompt with All Parameters

```sql
-- Get strategic prompt for profile 5 (@DBA)
SELECT 
    p.content,
    pppv.parameter_name,
    pppv.parameter_value
FROM profile_prompt_assignments ppa
JOIN prompts p ON ppa.prompt_id = p.id
LEFT JOIN profile_prompt_parameter_values pppv ON ppa.id = pppv.assignment_id
WHERE ppa.profile_id = 5 
  AND ppa.prompt_role = 'strategic'
  AND ppa.is_active = 1;
```

### Get All Global Parameters with Overrides

```sql
-- For profile 5, user 'user-123'
SELECT 
    gp.parameter_name,
    gp.default_value,
    COALESCE(
        profile_override.override_value,
        user_override.override_value,
        gp.default_value
    ) as effective_value
FROM global_parameters gp
LEFT JOIN global_parameter_overrides profile_override 
    ON gp.parameter_name = profile_override.parameter_name 
    AND profile_override.profile_id = 5
    AND profile_override.is_active = 1
LEFT JOIN global_parameter_overrides user_override
    ON gp.parameter_name = user_override.parameter_name 
    AND user_override.user_uuid = 'user-123'
    AND user_override.profile_id IS NULL
    AND user_override.is_active = 1;
```

### Find Which Profiles Use a Prompt

```sql
SELECT 
    ppa.profile_id,
    ppa.prompt_role,
    p.name as prompt_name
FROM profile_prompt_assignments ppa
JOIN prompts p ON ppa.prompt_id = p.id
WHERE p.name = 'STRATEGIC_SQL_OPTIMIZER'
  AND ppa.is_active = 1;
```

### Get Prompt Version History

```sql
SELECT 
    version,
    changed_by,
    change_reason,
    created_at,
    LENGTH(content) as content_size
FROM prompt_versions
WHERE prompt_id = (SELECT id FROM prompts WHERE name = 'MASTER_SYSTEM_PROMPT')
ORDER BY version DESC
LIMIT 10;
```

---

## Migration Notes

### From Current System

**Current:**
- `prompts.dat` (encrypted file with all prompts)
- `prompt_overrides/` (file system overrides)
- Hardcoded parameter substitution in `llm/handler.py`

**Migration Path:**
1. Decrypt `prompts.dat` using license key
2. Parse JSON structure
3. Insert into `prompts` table
4. Scan `prompt_overrides/` directory
5. Insert into `prompt_overrides` table
6. Define global parameters from current system
7. Map existing profile behavior to prompt assignments

### Data Mapping

```
prompts.dat["MASTER_SYSTEM_PROMPT"] 
    → prompts table (name='MASTER_SYSTEM_PROMPT', role='system')

prompt_overrides/MASTER_SYSTEM_PROMPT.txt
    → prompt_overrides table (user-level override)

APP_CONFIG.MCP_SYSTEM_NAME
    → global_parameters table (parameter_name='mcp_system_name', is_system_managed=1)
```

---

## Schema Validation

Run validation script:
```bash
python schema/validate_schema.py --validate-only
```

Create database:
```bash
python schema/validate_schema.py --create-database prompts.db
```

---

## Next Steps (Phase 2)

1. Create `PromptReader` class (read-only)
2. Integrate SQLCipher encryption
3. Build migration script from `prompts.dat`
4. Modify `prompts.py` for dual-mode operation
5. Test backward compatibility

---

**Schema Version:** 1.0.0  
**Last Updated:** 2025-12-18
