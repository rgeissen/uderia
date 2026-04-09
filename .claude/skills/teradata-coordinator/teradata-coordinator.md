# TDEXP Teradata Expert Coordinator — Developer Reference

This skill documents the TDEXP genie coordinator profile and its 4 expert sub-profiles. Use when helping tune, debug, or extend the Teradata expert system.

## Expert System Overview

| Tag | Type | Specialty | Data Access |
|-----|------|-----------|-------------|
| TDSQL | rag_focused | SQL syntax, query writing, optimization | Knowledge only (Collection 4: Teradata SQL Fundamentals, 424 chunks) |
| TDDIC | rag_focused | Teradata Data Dictionary (DBC.* views) | Knowledge only (Collection 3: Teradata Data Dictionary, 1006 chunks) |
| TDADM | rag_focused | System administration, TASM, workload mgmt | Knowledge only (Collection 5: Teradata Administration, 1107 chunks) |
| TDEXE | llm_only | Live SQL execution against fitness_db | 30 MCP tools (base_*, dba_*, sql_*, qlty_*) |
| TDEXP | genie | Coordinator for all 4 experts above | fitness_db KG active |

## Profile IDs (tda_auth.db → user_preferences)

```
TDSQL : profile-1775746202552-hsuoocmaj
TDDIC : profile-1775746108006-wh0syrzkr
TDADM : profile-1775746027109-w8yz7dlxr
TDEXE : profile-1775746606192-0tl5jhrt4
TDEXP : profile-1775746850745-1ddi65z0s
```

## Profile Descriptions (coordinator routing triggers)

**TDSQL:** Teradata SQL Expert. Provides guidance on SQL syntax, query construction and optimization, JOINs, subqueries, window functions, EXPLAIN plans, indexes, and SQL best practices. Consult for: writing or reviewing SQL statements, understanding SQL functions, query tuning, and SQL-related how-to questions. Does NOT execute queries against the database.

**TDDIC:** Teradata Data Dictionary Expert. Expert on Teradata system views (DBC.*), database objects (tables, views, macros, stored procedures), column definitions, access rights, statistics, data types, user/database metadata, and schema catalog exploration. Consult for: understanding what objects exist in the system, navigating DBC views, interpreting metadata, and any question about Teradata's internal catalog. Does NOT execute queries against the database.

**TDADM:** Teradata Administrator Expert. Expert in system administration: workload management (TASM, TIWM), resource groups, priority scheduling, session management, user/role/zone administration, backup and restore procedures, system monitoring, space management, system configuration, and operational DBA tasks. Consult for: administration how-to questions, operational procedures, system health analysis, and DBA responsibilities. Does NOT execute queries against the database.

**TDEXE:** Teradata SQL Executor. Executes live SQL queries against the fitness_db database and returns actual data. Use EXCLUSIVELY when: the user wants real data retrieved from the database, needs to verify actual table contents, requests row counts or data samples, or any task requiring live query execution. Can run SELECT, data quality checks, and analytical queries. This is the ONLY expert that accesses live data.

**TDEXP:** Teradata Expert Coordinator. Routes Teradata questions to the right specialist: TDSQL for SQL writing and optimization, TDDIC for data dictionary and schema metadata, TDADM for system administration and operations, TDEXE for live SQL execution against fitness_db. For complex questions, consults multiple experts and synthesizes their responses into a unified answer.

## Coordinator Skill (teradata-coordinator)

The `teradata-coordinator` skill is enabled on TDEXP and injected into its system prompt. It lives at:
- Platform skill: `~/.tda/skills/teradata-coordinator/`
- Registered in: `user_skills` table (user_uuid 472d2c9e-..., skill_id = teradata-coordinator)

**Routing rules injected:**
1. SQL syntax/writing → TDSQL
2. DBC views / metadata → TDDIC
3. Admin / operations → TDADM
4. Live data / execution → TDEXE
5. SQL + data → TDSQL + TDEXE
6. Multi-domain → all relevant experts, synthesize

## Knowledge Graph Assignments

fitness_db KG (owned by profile-1764006444002-z0hdduce9 / OPTIM) is active for:
- TDSQL ✅ — writes schema-specific SQL
- TDEXE ✅ — avoids schema-discovery tool calls before executing
- TDEXP ✅ — smarter routing with schema awareness
- TDDIC ❌ — DBC catalog specialist, not application schemas
- TDADM ❌ — system-wide, schema irrelevant

Managed in: `kg_profile_assignments` table

## fitness_db Schema (from KG)

Tables: Products, SaleDetails, ServiceTickets, Sales, Customers, StockQuantity (columns)

## Common Tuning Tasks

**To improve routing accuracy:** Edit descriptions in `tda_auth.db → user_preferences.preferences_json` for the relevant profile.

**To update coordinator instructions:** Edit `~/.tda/skills/teradata-coordinator/teradata-coordinator.md`, then reload via `POST /v1/skills/reload`.

**To add a new expert:** Create profile, add to TDEXP's `genieConfig.slaveProfiles`, update coordinator skill with new routing rule.

**To activate/deactivate KG for a profile:** Update `kg_profile_assignments.is_active` in `tda_auth.db`.
Note: unique constraint — only one active KG per profile.
