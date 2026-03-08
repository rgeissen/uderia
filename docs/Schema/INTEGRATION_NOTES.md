# Schema Integration with tda_auth.db - Changes Summary

**Date:** 2025-12-18  
**Phase:** Phase 1 - Foundation  
**Status:** Schema adjusted for integration

---

## Key Changes Made

### 1. Profile ID Type Change

**Issue:** Original schema assumed profiles were stored in database with INTEGER primary keys.

**Reality:** Profiles are stored in `tda_config.json` with TEXT string IDs.

**Changes Applied:**

#### File: `schema/02_parameters.sql`
- `global_parameter_overrides.profile_id`: Changed from `INTEGER` to `TEXT`
- Added comment: "TEXT string from tda_config.json"

#### File: `schema/03_profile_integration.sql`
- `profile_prompt_assignments.profile_id`: Changed from `INTEGER` to `TEXT`
- `profile_prompt_parameter_values.profile_id`: Changed from `INTEGER` to `TEXT`
- `profile_class_assignments.profile_id`: Changed from `INTEGER` to `TEXT`
- **Removed:** All FOREIGN KEY constraints on profile_id (no profiles table exists)
- Added comments: "Profile string ID from tda_config.json"

### 2. Documentation Updates

#### File: `schema/SCHEMA_DOCUMENTATION.md`
Added new section: **Database Integration**
- Documents integration with tda_auth.db
- Explains profile storage architecture (JSON-based)
- Describes profile ID format and structure
- Notes on referential integrity (no FK constraints for profiles)

### 3. Validation Script Updates

#### File: `schema/validate_schema.py`
- Renamed function: `create_database()` → `integrate_schema()`
- Changed behavior: Integrates with existing tda_auth.db instead of creating new file
- Added safety checks:
  - Warns user about modifying existing database
  - Checks for existing prompt tables
  - Offers to drop and recreate if tables exist
- Updated argument parser: `--create-database` → `--integrate`
- Added `00_master.sql` to SCHEMA_FILES list
- Enhanced reporting: Shows total tables vs prompt-specific tables

---

## Profile System Architecture

### Current Implementation

```
tda_config.json (file-based storage)
     ↓
ConfigManager class
     ↓
Profile operations: get_profiles(), add_profile(), update_profile(), remove_profile()
```

### Profile Structure
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

### Database References

Schema tables that reference profiles:
1. `global_parameter_overrides.profile_id` (TEXT, nullable)
2. `profile_prompt_assignments.profile_id` (TEXT, NOT NULL)
3. `profile_prompt_parameter_values.profile_id` (TEXT, NOT NULL)
4. `profile_class_assignments.profile_id` (TEXT, NOT NULL)

**Important:** No foreign key constraints exist for profile_id fields. Application code must validate profile IDs against ConfigManager.

---

## Integration Process

### Step 1: Validation
```bash
python schema/validate_schema.py --validate-only
```
Validates all schema files for:
- SQL syntax errors
- Foreign key integrity (except profiles)
- Index definitions
- View definitions
- Trigger definitions

### Step 2: Integration
```bash
python schema/validate_schema.py --integrate /path/to/tda_auth.db
```
Integrates schema into existing database:
1. Checks if database exists
2. Warns about modifications (requests backup confirmation)
3. Checks for existing prompt tables
4. Drops existing tables if confirmed
5. Executes all schema files in order
6. Adds schema_version record
7. Reports integration statistics

### Step 3: Test Data (Optional)
```bash
python schema/validate_schema.py --integrate /path/to/tda_auth.db --with-test-data
```
Includes test data for validation:
- Test prompt class
- Test prompt with parameters
- Test global parameter

---

## Validation Safeguards

### Profile Validation (Application Layer)

Since profiles have no FK constraints, application code MUST validate:

```python
from src.trusted_data_agent.config_manager import ConfigManager

def validate_profile_id(profile_id: str) -> bool:
    """Validate profile_id exists in tda_config.json"""
    config_manager = ConfigManager()
    profiles = config_manager.get_profiles()
    return any(p['id'] == profile_id for p in profiles)
```

### Orphaned Reference Detection

Query to find orphaned profile references:
```sql
-- Find profile IDs in database that may not exist in JSON
SELECT DISTINCT profile_id 
FROM (
    SELECT profile_id FROM global_parameter_overrides WHERE profile_id IS NOT NULL
    UNION
    SELECT profile_id FROM profile_prompt_assignments
    UNION
    SELECT profile_id FROM profile_prompt_parameter_values
    UNION
    SELECT profile_id FROM profile_class_assignments
) AS all_profile_refs
ORDER BY profile_id;
```

Then validate each ID against `ConfigManager.get_profiles()`.

---

## Database Structure After Integration

### Existing tda_auth.db Tables (23)
- users
- access_tokens
- consumption_profiles (for rate limiting)
- collections
- llm_model_costs
- ... (18 more)

### New Prompt Management Tables (12)
- schema_version
- prompt_classes
- prompts
- prompt_versions
- prompt_overrides
- global_parameters
- global_parameter_overrides
- prompt_parameters
- prompt_class_parameters
- profile_prompt_assignments
- profile_prompt_parameter_values
- profile_class_assignments

### New Views (8)
- v_active_prompts
- v_prompt_full_hierarchy
- v_prompt_with_parameters
- v_global_parameters_with_defaults
- v_profile_prompt_config
- v_user_effective_parameters
- v_prompt_version_history
- v_prompt_audit_trail

### New Indexes (40+)
See [schema/04_indexes.sql](04_indexes.sql) for complete list.

---

## Migration Strategy

### Phase 1: Schema Integration (Current)
- ✅ Schema files adjusted for tda_auth.db
- ✅ Profile ID type changed to TEXT
- ✅ Documentation updated
- ✅ Validation script updated
- 🔄 **Next:** Execute integration on development database

### Phase 2-10: Implementation
See main project plan for details.

---

## Testing Checklist

- [ ] Validate schema syntax: `python schema/validate_schema.py --validate-only`
- [ ] Backup production tda_auth.db
- [ ] Integrate on development database: `python schema/validate_schema.py --integrate /path/to/dev/tda_auth.db`
- [ ] Verify table creation: `sqlite3 tda_auth.db ".tables"`
- [ ] Check foreign keys: `PRAGMA foreign_key_check;`
- [ ] Insert test data: `--with-test-data` flag
- [ ] Query test views: `SELECT * FROM v_active_prompts;`
- [ ] Validate profile IDs in application code
- [ ] Check for orphaned references

---

## Rollback Plan

If integration fails or needs to be reverted:

```sql
-- Drop all prompt management tables
DROP TABLE IF EXISTS profile_class_assignments;
DROP TABLE IF EXISTS profile_prompt_parameter_values;
DROP TABLE IF EXISTS profile_prompt_assignments;
DROP TABLE IF EXISTS prompt_class_parameters;
DROP TABLE IF EXISTS prompt_parameters;
DROP TABLE IF EXISTS global_parameter_overrides;
DROP TABLE IF EXISTS global_parameters;
DROP TABLE IF EXISTS prompt_overrides;
DROP TABLE IF EXISTS prompt_versions;
DROP TABLE IF EXISTS prompts;
DROP TABLE IF EXISTS prompt_classes;
DROP TABLE IF EXISTS schema_version;

-- Drop all prompt management views
DROP VIEW IF EXISTS v_prompt_audit_trail;
DROP VIEW IF EXISTS v_prompt_version_history;
DROP VIEW IF EXISTS v_user_effective_parameters;
DROP VIEW IF EXISTS v_profile_prompt_config;
DROP VIEW IF EXISTS v_global_parameters_with_defaults;
DROP VIEW IF EXISTS v_prompt_with_parameters;
DROP VIEW IF EXISTS v_prompt_full_hierarchy;
DROP VIEW IF EXISTS v_active_prompts;

-- Restore from backup if needed
-- (Use external backup restoration process)
```

---

## Contact & Support

For questions about this integration:
1. Review [SCHEMA_DOCUMENTATION.md](SCHEMA_DOCUMENTATION.md)
2. Check validation output for detailed errors
3. Review profile structure in tda_config.json
4. Verify ConfigManager implementation

---

**Last Updated:** 2025-12-18  
**Next Review:** After Phase 1 testing completion
