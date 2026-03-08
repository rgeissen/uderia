# Phase 1 Quick Reference Guide

## Quick Commands

### Validate Schema
```bash
python schema/validate_schema.py --validate-only
```

### Integrate into Database
```bash
# Development database
python schema/validate_schema.py --integrate /path/to/dev/tda_auth.db

# With test data
python schema/validate_schema.py --integrate /path/to/dev/tda_auth.db --with-test-data
```

### Check Database
```bash
# List all tables
sqlite3 tda_auth.db ".tables"

# Check schema version
sqlite3 tda_auth.db "SELECT * FROM schema_version;"

# Verify foreign keys
sqlite3 tda_auth.db "PRAGMA foreign_key_check;"

# Count prompt tables
sqlite3 tda_auth.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'prompt%' OR name LIKE '%parameter%';"
```

---

## File Reference

| File | Purpose | Key Info |
|------|---------|----------|
| `00_master.sql` | Schema version | Tracks schema version 1.0.0 |
| `01_core_tables.sql` | Core tables | Classes, prompts, versions, overrides |
| `02_parameters.sql` | Parameters | Global + local parameters |
| `03_profile_integration.sql` | Profiles | Profile → prompt mappings |
| `04_indexes.sql` | Indexes | 40+ performance indexes |
| `05_views.sql` | Views | 8 utility views |
| `validate_schema.py` | Integration | Validation & integration tool |
| `SCHEMA_DOCUMENTATION.md` | Reference | Complete schema documentation |
| `INTEGRATION_NOTES.md` | Guide | Integration instructions |
| `PHASE1_TEST_PLAN.md` | Tests | 10 test cases |
| `PHASE1_COMPLETION.md` | Summary | This phase summary |

---

## Key Schema Tables

### Core Tables (4)
- `prompt_classes` - Organizational categories
- `prompts` - Prompt content with parameters
- `prompt_versions` - Audit trail
- `prompt_overrides` - User/profile customizations

### Parameter Tables (4)
- `global_parameters` - System-wide parameters
- `global_parameter_overrides` - User/profile overrides
- `prompt_parameters` - Prompt-specific parameters
- `prompt_class_parameters` - Class-level parameters

### Profile Tables (3)
- `profile_prompt_assignments` - Profile → prompt by role
- `profile_prompt_parameter_values` - Profile param values
- `profile_class_assignments` - Profile → class mappings

### Metadata (1)
- `schema_version` - Version tracking

**Total:** 12 tables

---

## Important Concepts

### Profile IDs
- **Type:** TEXT (not INTEGER)
- **Format:** `"profile-1763993711628-vvbh23q09"` or `"1763819257473-ivpnukbbe-admin-default"`
- **Storage:** tda_config.json (NOT in database)
- **Validation:** Application code via ConfigManager
- **No FK:** No foreign key constraints on profile_id

### Prompt Roles
- `strategic` - Strategic planning prompts
- `tactical` - Execution prompts
- `recovery` - Error recovery prompts
- `report` - Report generation prompts
- `system` - System prompts (MASTER_SYSTEM_PROMPT, etc.)

### Parameter Types
- **Global:** System-wide (e.g., max_tokens, temperature)
  - System-managed (read-only)
  - User-configurable (editable)
- **Local:** Prompt-specific (e.g., planning_depth)

---

## Validation Checklist

Before integrating:
- [ ] Backup tda_auth.db
- [ ] Run `--validate-only` (must pass)
- [ ] Review INTEGRATION_NOTES.md
- [ ] Confirm development environment

After integrating:
- [ ] Check schema_version table
- [ ] Verify table count (12 new tables)
- [ ] Run `PRAGMA foreign_key_check;`
- [ ] Query views (all 8 should work)
- [ ] Execute test plan

---

## Common Queries

### Check Active Prompts
```sql
SELECT * FROM v_active_prompts;
```

### Find Profile Prompt Assignments
```sql
SELECT * FROM v_profile_prompt_config WHERE profile_id = 'your-profile-id';
```

### View Prompt Parameters
```sql
SELECT * FROM v_prompt_parameters_full WHERE prompt_name = 'MASTER_SYSTEM_PROMPT';
```

### Check Global Parameters
```sql
SELECT * FROM v_global_parameters_full;
```

### Audit Trail
```sql
SELECT * FROM v_prompt_version_history WHERE prompt_id = 1 ORDER BY created_at DESC;
```

### Find Orphaned Profile References
```sql
SELECT DISTINCT profile_id FROM (
    SELECT profile_id FROM profile_prompt_assignments
    UNION
    SELECT profile_id FROM profile_prompt_parameter_values
    UNION
    SELECT profile_id FROM profile_class_assignments
    UNION
    SELECT profile_id FROM global_parameter_overrides WHERE profile_id IS NOT NULL
);
-- Then validate each against ConfigManager.get_profiles()
```

---

## Troubleshooting

### "no such table: prompt_classes"
- Schema not integrated yet
- Run: `python schema/validate_schema.py --integrate /path/to/tda_auth.db`

### "FOREIGN KEY constraint failed"
- Trying to delete parent record with children
- Delete children first, or use CASCADE

### "no such column: assignment_id"
- Old schema version
- Re-integrate latest schema files

### Views returning empty results
- No data inserted yet
- Run with `--with-test-data` flag

### Profile validation errors
- Profile ID doesn't exist in tda_config.json
- Check ConfigManager.get_profiles()
- Update database or add profile to JSON

---

## Phase Status

- ✅ Schema files created and validated
- ✅ Documentation complete
- ✅ Integration script ready
- ⏳ Testing pending (PHASE1_TEST_PLAN.md)
- ⏳ Production integration pending

**Next Action:** Execute Phase 1 test plan

---

**Quick Reference Version:** 1.0  
**Last Updated:** 2025-12-18
