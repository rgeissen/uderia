# Phase 1 Test Plan - Schema Foundation

**Version:** 1.0  
**Date:** 2025-12-18  
**Status:** Ready for Execution  
**Database:** tda_auth.db

---

## Test Environment Setup

### Prerequisites
- [x] Python 3.x installed
- [x] SQLite3 CLI available
- [x] Backup of production tda_auth.db created
- [ ] Development copy of tda_auth.db available
- [ ] Schema files validated (run validation first)

### File Locations
- Schema files: `/Users/livin2rave/my_private_code/uderia/schema/*.sql`
- Validation script: `/Users/livin2rave/my_private_code/uderia/schema/validate_schema.py`
- Target database: `/path/to/tda_auth.db` (specify before testing)

---

## Phase 1 Validation Results

### ✅ Pre-Integration Validation

```bash
python schema/validate_schema.py --validate-only
```

**Expected Output:**
- ✓ All 6 schema files syntax valid (00_master, 01-05)
- ✓ 12 foreign key constraints validated
- ✓ 40 indexes defined correctly
- ✓ 8 views created successfully
- ✓ 8 triggers validated
- ✓ "Schema is ready for Phase 2 implementation"

**Status:** ✅ PASSED (2025-12-18 12:08:30)

---

## Test Suite

### Test 1: Schema Validation
**Objective:** Ensure all SQL files are syntactically correct and logically consistent

**Steps:**
1. Run validation tool: `python schema/validate_schema.py --validate-only`
2. Verify all checks pass
3. Review foreign key relationships
4. Verify index coverage

**Expected Results:**
- ✅ 0 syntax errors
- ✅ 0 foreign key violations
- ✅ 40 indexes created
- ✅ 8 views queryable
- ✅ 8 triggers defined

**Status:** ✅ PASSED

---

### Test 2: Schema Integration (Development Database)
**Objective:** Integrate prompt schema into a development copy of tda_auth.db

**Prerequisites:**
- Development copy of tda_auth.db exists
- Backup of development database created

**Steps:**
```bash
# 1. Create backup
cp /path/to/dev/tda_auth.db /path/to/dev/tda_auth.db.backup

# 2. Run integration
python schema/validate_schema.py --integrate /path/to/dev/tda_auth.db

# 3. Respond 'yes' to confirmation prompts
```

**Expected Results:**
- ✅ Integration completes without errors
- ✅ 12 new tables added to database
- ✅ 8 views created
- ✅ 40 indexes created
- ✅ schema_version table updated to 1.0.0

**Verification Queries:**
```sql
-- Check schema version
SELECT * FROM schema_version;
-- Expected: version='1.0.0', description='Initial prompt management system...'

-- Count prompt tables
SELECT COUNT(*) FROM sqlite_master 
WHERE type='table' AND name IN (
    'prompt_classes', 'prompts', 'prompt_versions', 'prompt_overrides',
    'global_parameters', 'global_parameter_overrides', 'prompt_parameters',
    'prompt_class_parameters', 'profile_prompt_assignments',
    'profile_prompt_parameter_values', 'profile_class_assignments',
    'schema_version'
);
-- Expected: 12

-- Check foreign keys enabled
PRAGMA foreign_keys;
-- Expected: 1 (ON)

-- Verify no FK violations
PRAGMA foreign_key_check;
-- Expected: 0 rows (no violations)
```

**Status:** [ ] Pending execution

---

### Test 3: Profile ID Validation
**Objective:** Verify profile_id fields accept TEXT strings (not INTEGER)

**Prerequisites:**
- Schema integrated into development database
- Access to tda_config.json

**Steps:**
```sql
-- 1. Create test data with TEXT profile IDs
INSERT INTO profile_prompt_assignments (profile_id, prompt_role, prompt_id)
VALUES ('test-profile-123-abc', 'system', 1);

-- 2. Verify insertion
SELECT * FROM profile_prompt_assignments WHERE profile_id = 'test-profile-123-abc';

-- 3. Test with real profile ID from tda_config.json
-- (Replace with actual profile ID)
INSERT INTO global_parameter_overrides (parameter_name, profile_id, override_value)
VALUES ('test_param', 'profile-1763993711628-vvbh23q09', 'test_value');

-- 4. Verify no FK constraint errors
SELECT * FROM global_parameter_overrides WHERE profile_id IS NOT NULL;

-- 5. Cleanup
DELETE FROM profile_prompt_assignments WHERE profile_id LIKE 'test-%';
DELETE FROM global_parameter_overrides WHERE parameter_name = 'test_param';
```

**Expected Results:**
- ✅ TEXT profile IDs accepted without errors
- ✅ No foreign key constraint violations
- ✅ Queries execute successfully

**Status:** [ ] Pending execution

---

### Test 4: Foreign Key Integrity
**Objective:** Verify foreign key constraints work correctly

**Prerequisites:**
- Schema integrated into development database

**Steps:**
```sql
-- Test 1: Insert valid data
INSERT INTO prompt_classes (name, display_name, description, class_type)
VALUES ('TestClass', 'Test Class', 'Test description', 'standalone');

INSERT INTO prompts (name, display_name, content, class_id, role, version)
VALUES ('TEST', 'Test Prompt', 'Test content', last_insert_rowid(), 'system', 1);

-- Test 2: Try to delete class with dependent prompt (should fail)
DELETE FROM prompt_classes WHERE name = 'TestClass';
-- Expected: FOREIGN KEY constraint failed

-- Test 3: Cleanup (delete in correct order)
DELETE FROM prompts WHERE name = 'TEST';
DELETE FROM prompt_classes WHERE name = 'TestClass';
-- Expected: Success
```

**Expected Results:**
- ✅ Valid inserts succeed
- ✅ FK violations are caught and prevented
- ✅ Proper deletion order works

**Status:** [ ] Pending execution

---

### Test 5: View Functionality
**Objective:** Verify all views return correct data

**Prerequisites:**
- Schema integrated with test data (`--with-test-data` flag)

**Steps:**
```sql
-- Test each view
SELECT * FROM v_active_prompts LIMIT 5;
SELECT * FROM v_prompt_full_hierarchy LIMIT 5;  
SELECT * FROM v_prompt_with_parameters LIMIT 5;
SELECT * FROM v_global_parameters_with_defaults LIMIT 5;
SELECT * FROM v_profile_prompt_config LIMIT 5;
SELECT * FROM v_user_effective_parameters LIMIT 5;
SELECT * FROM v_prompt_version_history LIMIT 5;
SELECT * FROM v_prompt_audit_trail LIMIT 5;
```

**Expected Results:**
- ✅ All views execute without errors
- ✅ No SQL syntax errors
- ✅ Results contain expected columns
- ✅ Data matches underlying tables

**Status:** [ ] Pending execution

---

### Test 6: Trigger Functionality
**Objective:** Verify automatic timestamp updates work

**Prerequisites:**
- Schema integrated into development database

**Steps:**
```sql
-- Test 1: Create a prompt class
INSERT INTO prompt_classes (name, display_name, description, class_type)
VALUES ('TriggerTest', 'Trigger Test', 'Test triggers', 'standalone');

-- Check timestamps
SELECT created_at, updated_at FROM prompt_classes WHERE name = 'TriggerTest';
-- Expected: created_at = updated_at (both recent timestamps)

-- Wait 2 seconds
SELECT '...waiting...';

-- Test 2: Update the class
UPDATE prompt_classes SET description = 'Updated description' WHERE name = 'TriggerTest';

-- Check timestamps again
SELECT created_at, updated_at FROM prompt_classes WHERE name = 'TriggerTest';
-- Expected: updated_at > created_at

-- Cleanup
DELETE FROM prompt_classes WHERE name = 'TriggerTest';
```

**Expected Results:**
- ✅ created_at set automatically on insert
- ✅ updated_at set automatically on insert
- ✅ updated_at changes on update
- ✅ created_at remains unchanged on update

**Status:** [ ] Pending execution

---

### Test 7: Index Performance
**Objective:** Verify indexes improve query performance

**Prerequisites:**
- Schema integrated with test data

**Steps:**
```sql
-- Enable query plan output
.eqp on

-- Test indexed queries
EXPLAIN QUERY PLAN
SELECT * FROM prompts WHERE name = 'TEST_PROMPT';
-- Expected: Uses idx_prompts_name

EXPLAIN QUERY PLAN
SELECT * FROM prompts WHERE role = 'strategic' AND is_active = 1;
-- Expected: Uses idx_prompts_role or idx_prompts_active

EXPLAIN QUERY PLAN  
SELECT * FROM profile_prompt_assignments WHERE profile_id = 'test-123';
-- Expected: Uses idx_profile_assignments_profile

.eqp off
```

**Expected Results:**
- ✅ Query plans show index usage (not SCAN TABLE)
- ✅ Appropriate indexes selected by optimizer
- ✅ No full table scans for indexed columns

**Status:** [ ] Pending execution

---

### Test 8: Profile Integration Without FK
**Objective:** Verify profile references work without foreign key constraints

**Prerequisites:**
- Schema integrated into development database
- tda_config.json contains profiles

**Steps:**
```python
# Python validation script
from src.trusted_data_agent.config_manager import ConfigManager
import sqlite3

# Load profiles from JSON
config_mgr = ConfigManager()
profiles = config_mgr.get_profiles()
print(f"Found {len(profiles)} profiles in tda_config.json")

# Get profile IDs from database
conn = sqlite3.connect('/path/to/dev/tda_auth.db')
cursor = conn.cursor()

cursor.execute("""
    SELECT DISTINCT profile_id FROM (
        SELECT profile_id FROM profile_prompt_assignments
        UNION
        SELECT profile_id FROM profile_prompt_parameter_values
        UNION  
        SELECT profile_id FROM profile_class_assignments
        UNION
        SELECT profile_id FROM global_parameter_overrides WHERE profile_id IS NOT NULL
    )
""")

db_profile_ids = [row[0] for row in cursor.fetchall()]
json_profile_ids = [p['id'] for p in profiles]

# Check for orphaned references
orphaned = set(db_profile_ids) - set(json_profile_ids)
print(f"Orphaned profile references: {orphaned if orphaned else 'None'}")

# Check for valid references
valid = set(db_profile_ids) & set(json_profile_ids)
print(f"Valid profile references: {len(valid)}")

conn.close()
```

**Expected Results:**
- ✅ Profiles loaded from tda_config.json successfully
- ✅ Profile IDs in database are TEXT strings
- ✅ No orphaned profile references (or documented if expected)
- ✅ All database profile IDs validate against JSON

**Status:** [ ] Pending execution

---

### Test 9: Test Data Insertion
**Objective:** Verify test data can be inserted successfully

**Prerequisites:**
- Schema integrated into development database

**Steps:**
```bash
# Run integration with test data
python schema/validate_schema.py --integrate /path/to/dev/tda_auth.db --with-test-data
```

**Verification Queries:**
```sql
-- Check test class
SELECT * FROM prompt_classes WHERE name LIKE 'Test%';
-- Expected: 1 row (TestStrategicPlanner)

-- Check test prompt  
SELECT * FROM prompts WHERE name = 'TEST_PROMPT';
-- Expected: 1 row with content containing {param1} and {param2}

-- Check test parameters
SELECT * FROM prompt_parameters WHERE prompt_id IN (SELECT id FROM prompts WHERE name = 'TEST_PROMPT');
-- Expected: 2 rows (param1, param2)

-- Check test global parameter
SELECT * FROM global_parameters WHERE parameter_name = 'test_global';
-- Expected: 1 row with default_value = 'global_default'
```

**Expected Results:**
- ✅ Test data inserted without errors
- ✅ All test records present
- ✅ Foreign keys correctly linked
- ✅ Data structure matches expected format

**Status:** [ ] Pending execution

---

### Test 10: Rollback Capability
**Objective:** Verify database can be rolled back if needed

**Prerequisites:**
- Backup of development database exists

**Steps:**
```bash
# 1. Note current state
sqlite3 /path/to/dev/tda_auth.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table';"

# 2. Restore from backup
cp /path/to/dev/tda_auth.db.backup /path/to/dev/tda_auth.db

# 3. Verify restoration
sqlite3 /path/to/dev/tda_auth.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table';"

# 4. Re-integrate
python schema/validate_schema.py --integrate /path/to/dev/tda_auth.db
```

**Expected Results:**
- ✅ Backup restoration successful
- ✅ Table count returns to pre-integration state
- ✅ Re-integration works after rollback
- ✅ No data corruption

**Status:** [ ] Pending execution

---

## Test Execution Summary

### Checklist
- [x] Test 1: Schema Validation (PASSED)
- [ ] Test 2: Schema Integration
- [ ] Test 3: Profile ID Validation
- [ ] Test 4: Foreign Key Integrity
- [ ] Test 5: View Functionality
- [ ] Test 6: Trigger Functionality
- [ ] Test 7: Index Performance
- [ ] Test 8: Profile Integration Without FK
- [ ] Test 9: Test Data Insertion
- [ ] Test 10: Rollback Capability

### Test Results Summary
```
Total Tests: 10
Passed: 1
Failed: 0
Pending: 9
Success Rate: 10% (awaiting execution)
```

---

## Issues & Resolutions

### Known Issues
None currently.

### Resolved Issues
1. ✅ **Issue:** profile_id was INTEGER, should be TEXT
   - **Resolution:** Changed all profile_id columns to TEXT in schema files
   - **Files affected:** 02_parameters.sql, 03_profile_integration.sql

2. ✅ **Issue:** View referenced non-existent assignment_id column
   - **Resolution:** Updated v_profile_prompt_parameters view to use profile_id + prompt_id
   - **File affected:** 05_views.sql

3. ✅ **Issue:** Index file failing standalone validation
   - **Resolution:** Changed validation to cumulative execution
   - **File affected:** validate_schema.py

---

## Production Deployment Checklist

**DO NOT proceed to production until ALL tests pass!**

- [ ] All Phase 1 tests passed (10/10)
- [ ] Development database tested thoroughly
- [ ] Production database backup created
- [ ] Backup verified and restorable
- [ ] Integration plan approved
- [ ] Rollback plan tested
- [ ] Stakeholders notified
- [ ] Maintenance window scheduled
- [ ] Post-integration validation planned

---

## Next Steps

After Phase 1 testing complete:
1. Document any issues found during testing
2. Update schema if needed based on test results
3. Re-run validation after any changes
4. Get approval for production integration
5. Proceed to Phase 2 implementation

---

**Test Plan Status:** Ready for Execution  
**Last Updated:** 2025-12-18  
**Next Review:** After test execution
