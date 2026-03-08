# Maintenance Scripts Audit - Orphaned and Redundant Scripts

**Date:** 5 December 2025  
**Branch:** Consumption-Profile-Activation

## Summary

This audit identifies maintenance scripts that are:
- **ORPHANED**: One-time migration scripts that have been executed and are no longer needed
- **DEBUGGING**: Temporary debugging scripts created for specific issues (now resolved)
- **REDUNDANT**: Scripts that duplicate functionality or have been superseded
- **ACTIVE**: Scripts that should be kept for ongoing maintenance

---

## 🗑️ SCRIPTS TO DELETE (Orphaned/Completed Migrations)

### Database Migration Scripts (One-Time Use)
These migrations have been applied and are no longer needed:

1. **migrate_consumption_profiles.py** - Created consumption_profiles table (completed)
2. **migrate_consumption_tracking.py** - Bootstrap consumption tracking from session files (completed)
3. **migrate_collections_to_db.py** - Moved collections from JSON to database (completed)
4. **migrate_user_unique_constraints.py** - Updated user table constraints (completed)
5. **migrate_llm_model_costs.py** - LLM cost migration (completed)
6. **migrate_marketplace_schema.py** - Marketplace schema migration (completed)
7. **migrate_repository_types.py** - Repository types migration (completed)
8. **migrate_template_defaults_table.py** - Template defaults migration (completed)
9. **migrate_consolidate_user_id.py** - User ID consolidation (completed)
10. **fix_all_table_schemas.py** - One-time schema fix (completed)

### Debugging Scripts (Issue-Specific)
Created for specific bugs that have been fixed:

11. **check_consumption_data.py** - Debug dashboard model distribution bug (FIXED: today)
12. **check_recent_turns.py** - Debug model attribution (FIXED: today)
13. **check_session_ownership.py** - Debug session ownership issue (FIXED: today)
14. **cleanup_incorrect_consumption.py** - Cleanup wrong model records (EXECUTED: today)
15. **debug_session_names.py** - Debug session names (issue resolved)
16. **backfill_session_names.py** - One-time backfill (completed)

### Data Cleanup Scripts (One-Time Operations)
17. **remove_db_param.py** - Removed database_name parameter from collection_1 cases (completed)
18. **fix_missing_repository_types.py** - Fixed repository types (completed)
19. **fix_template_metadata.py** - Fixed template metadata (completed)
20. **load_bootstrap_costs.py** - Initial cost data load (completed)

### Shell Scripts (Obsolete/Redundant)
21. **reload_collection_3.sh** - One-time collection reload (completed)
22. **setup_consumption_cron_jobs.sh** - Superseded by consumption_periodic_jobs.py
23. **remove_consumption_cron_jobs.sh** - Superseded by consumption_periodic_jobs.py
24. **test_consumption_jobs.sh** - Temporary testing script
25. **reset_consumption_db.sh** - Dangerous script, should not be kept in production

---

## ⚠️ SCRIPTS TO REVIEW (Potentially Obsolete)

### RAG/Collection Scripts
26. **identify_orphan_cases.py** - Check if still needed
27. **delete_orphan_cases.py** - Check if still needed
28. **list_rag_cases_by_user.py** - Utility, may be useful for debugging
29. **validate_knowledge_chunks.py** - Validation utility, may be useful
30. **rag_miner.py** - Check purpose and usage

### Old Setup Scripts
31. **create_default_collection.py** - Superseded by initialization in application
32. **create_knowledge_collection.py** - Check if still needed

### Token/Auth Cleanup
33. **cleanup_orphaned_tokens.py** - Check if orphaned tokens still occur
34. **cleanup_orphaned_collections.py** - Check if orphaned collections still occur

---

## ✅ SCRIPTS TO KEEP (Active Maintenance)

### Database Management
- **initialize_database.py** - Core database initialization (KEEP)
- **initialize_efficiency_tracker.py** - Initialize efficiency tracking (KEEP)

### Consumption Profile Management
- **consumption_periodic_jobs.py** - Active periodic maintenance (KEEP)
- **reconcile_consumption.py** - Data reconciliation utility (KEEP)
- **assign_unlimited_profiles.py** - Admin utility for profile assignment (KEEP)
- **reset_admin_to_unlimited.py** - Admin utility (KEEP)
- **set_unlimited_default.py** - Profile configuration (KEEP)
- **update_rate_limiting_defaults.py** - Rate limit configuration (KEEP)
- **test_rate_limit_config.py** - Testing utility (KEEP)

### User/Token Management
- **check_token_usage.py** - Active monitoring utility (KEEP)
- **check_user_profile.py** - Active debugging utility (KEEP)
- **regenerate_jwt_secret.py** - Security utility (KEEP)

### RAG/Vector Store Management
- **reload_collection.py** - Active utility for reloading collections (KEEP)
- **clean_vector_store.py** - Active maintenance (KEEP)
- **reset_chromadb.py** - Development utility (KEEP)
- **reupload_knowledge_doc.py** - Active utility (KEEP)

### MCP/Configuration
- **export_mcp_capabilities.py** - Documentation generation (KEEP)
- **auto_populate_endpoint.py** - Active utility (KEEP?)

### Shell Scripts
- **clean_tracked_files.sh** - Git cleanup utility (KEEP)
- **view_consumption_logs.sh** - Log viewing utility (KEEP)

### Documentation
- **MULTIUSER_MAINTENANCE_GUIDE.md** - Active documentation (KEEP)
- **RAG_MAINTENANCE_GUIDE.md** - Active documentation (KEEP)

---

## Recommended Actions

### Immediate Deletions (25 scripts)
Delete all migration scripts, debugging scripts, and one-time operations listed above.

### Create Archive (Optional)
If you want to preserve scripts for reference:
```bash
mkdir -p maintenance/archive/migrations
mkdir -p maintenance/archive/debugging
mkdir -p maintenance/archive/one-time-ops
```

### Cleanup Command
```bash
cd /Users/livin2rave/my_private_code/uderia/maintenance

# Move migrations to archive
mv migrate_*.py archive/migrations/
mv fix_all_table_schemas.py archive/migrations/
mv backfill_*.py archive/migrations/

# Move debugging scripts to archive
mv check_consumption_data.py archive/debugging/
mv check_recent_turns.py archive/debugging/
mv check_session_ownership.py archive/debugging/
mv cleanup_incorrect_consumption.py archive/debugging/
mv debug_*.py archive/debugging/

# Move one-time operations to archive
mv remove_db_param.py archive/one-time-ops/
mv fix_missing_*.py archive/one-time-ops/
mv fix_template_*.py archive/one-time-ops/
mv load_bootstrap_costs.py archive/one-time-ops/
mv reload_collection_3.sh archive/one-time-ops/

# Delete obsolete shell scripts
rm setup_consumption_cron_jobs.sh
rm remove_consumption_cron_jobs.sh
rm test_consumption_jobs.sh
rm reset_consumption_db.sh
```

---

## Notes

- **Migration scripts** should NEVER be deleted without first confirming they've been executed on all environments
- **Debugging scripts** created for specific bugs can be deleted once bugs are fixed
- **One-time operations** that have been completed can be archived or deleted
- Consider adding a `.archived` suffix to old scripts instead of deleting them completely
