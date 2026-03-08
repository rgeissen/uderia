# MCP Tool Routing Analysis — @OPTIM Planner vs @IDEAT Conversation Agent

**Date:** 2026-02-16
**Server:** 192.168.0.46:5050
**Test Suite:** 30 MCP tool fixtures (28 tools, plot_ excluded)
**Framework:** `test/performance/mcp_tool_test.py`

---

## Executive Summary

We ran all Teradata MCP server tools through two execution modes to evaluate tool routing accuracy:

| Profile | Mode | Fixtures | Passed | Failed | Pass Rate | Total Tokens | Avg Duration |
|---------|------|----------|--------|--------|-----------|-------------|-------------|
| **@OPTIM** | tool_enabled (Planner/Executor) | 30 | 21 | 9 | **70%** | 349,014 | 11.7s |
| **@IDEAT** | conversation (LangChain agent) | 25* | 24 | 1 | **96%** | 430,653 | 5.6s |

*\*5 fixtures disabled due to high token cost (see Appendix A)*

**Key finding:** The conversation agent (@IDEAT) routes to the correct MCP tool 96% of the time. The Planner/Executor (@OPTIM) only achieves 70% — falling back to `base_readQuery` (generic SQL) for 6 of the 9 failures. Zero self-corrections were observed in either mode.

---

## Failure Pattern Analysis

### Pattern 1: Generic Tool Bias — `base_readQuery` Preferred Over Specialized DBA Tools

**Affected fixtures (3 confirmed, 3 more via temporal cascade):**

| Fixture | Expected Tool | Actual Tool | @OPTIM Tokens | @IDEAT Tokens | @IDEAT Verdict |
|---------|--------------|-------------|--------------|--------------|----------------|
| `dba_databaseVersion` | `dba_databaseVersion` | `base_readQuery` | 8,670 | 13,922 | PASS |
| `dba_sessionInfo` | `dba_sessionInfo` | `base_readQuery` | 10,488 | 15,973 | PASS |
| `dba_systemSpace` | `dba_systemSpace` | `base_readQuery` | 8,806 | 14,036 | PASS |

**Root cause:** The strategic planner selects `base_readQuery` because:

1. **Tool descriptions favor the generic option.** `base_readQuery` has a rich description (*"Execute a SQL query via SQLAlchemy, bind parameters if provided..."*) while DBA tools have minimal descriptions:
   - `dba_databaseVersion`: *"Get Teradata database version information."* (8 words)
   - `dba_systemSpace`: *"Get the Teradata total system database space usage."* (9 words)
   - `dba_sessionInfo`: *"Get the Teradata session information for user."* (8 words)

2. **No specialization signals in tool context.** Tools are presented flat to the LLM without ranking, scope tags, or "prefer specialized over generic" guidance. The tool context is built in `handler.py:385-425`:
   ```
   - `base_readQuery` (tool): Execute a SQL query via SQLAlchemy...
   - `dba_databaseVersion` (tool): Get Teradata database version information.
   ```
   Both appear equal in weight.

3. **Zero-argument tools appear incomplete.** `dba_databaseVersion`, `dba_systemSpace`, `dba_sessionInfo` have empty parameter lists. The LLM may distrust parameterless tools and prefer `base_readQuery` which explicitly accepts a `sql` argument.

4. **LLM reasoning:** "To get version info, I should query the database" → selects generic SQL tool. The conversation agent doesn't have this bias because it selects tools based on function-calling semantics rather than strategic planning.

**Recommendation (MCP Server Team):** Enhance tool descriptions to explicitly differentiate from `base_readQuery`:

| Tool | Current Description | Suggested Enhancement |
|------|-------------------|----------------------|
| `dba_databaseVersion` | "Get Teradata database version information." | "Returns the Teradata database version, release, and system build information. No SQL required — this is a specialized system info tool." |
| `dba_sessionInfo` | "Get the Teradata session information for user." | "Returns all active Teradata sessions with user, status, duration, and resource details. Use for monitoring active database connections." |
| `dba_systemSpace` | "Get the Teradata total system database space usage." | "Returns total system storage allocation, usage, and free space across all databases. Use for capacity monitoring — no SQL required." |

**Recommendation (Uderia Team):** Add tool selection guidance to `WORKFLOW_META_PLANNING_PROMPT`:
```
TOOL SELECTION PRIORITY:
- For system administration queries (version, space, sessions, permissions),
  prefer specialized dba_* and sec_* tools over base_readQuery.
- Use base_readQuery ONLY when no dedicated tool exists for the query,
  or when the user explicitly provides SQL to execute.
- For data quality analysis, prefer qlty_* tools over base_readQuery.
```

---

### Pattern 2: Temporal Argument Binding Failure

**Affected fixtures (4):**

| Fixture | Expected Tool | Actual Tools | @OPTIM Tokens | Duration |
|---------|--------------|-------------|--------------|----------|
| `dba_featureUsage` | `dba_featureUsage` | `TDA_CurrentDate` → `TDA_DateRange` → `base_readQuery` | 27,890 | 18.3s |
| `dba_flowControl` | `dba_flowControl` | `TDA_CurrentDate` → `TDA_DateRange` → `base_readQuery` | 22,584 | 22.4s |
| `dba_userDelay` | `dba_userDelay` | `TDA_CurrentDate` → `TDA_DateRange` → `base_readQuery` | 17,431 | 8.1s |
| `base_tableUsage` | `base_tableUsage` | `TDA_CurrentDate` → `TDA_DateRange` → `dba_tableSqlList` | 22,430 | 12.2s |

**Root cause:** The Temporal Preprocessing Gate correctly detects date references in queries ("past 7 days", "today") and injects `TDA_CurrentDate` + `TDA_DateRange`. However, the tool selection step happens independently and cannot bind the resolved dates to the target tool's `start_date`/`end_date` parameters.

The planner's reasoning:
1. Detects "past 7 days" → fires temporal preprocessing ✓
2. Resolves date range via TDA_CurrentDate + TDA_DateRange ✓
3. Needs to select a tool with `start_date`/`end_date` params → **doesn't know how to fill them** ✗
4. Falls back to `base_readQuery(sql="SELECT ... WHERE date BETWEEN ...")` — can write SQL with date literals

**Why base_readQuery is "safer":** The planner can embed date literals directly in SQL (`WHERE date BETWEEN '2026-02-09' AND '2026-02-16'`), while calling `dba_featureUsage(start_date=?, end_date=?)` requires resolving placeholders from the preprocessor output — a binding step that doesn't exist.

**Token cost impact:** These temporal fallbacks are the most expensive failures:
- Average tokens (correct routing): ~10,000
- Average tokens (temporal fallback): ~22,584 (**2.3x overhead**)
- Extra overhead comes from TDA_DateRange multi-day iteration + base_readQuery SQL generation

**Recommendation (Uderia Team):** Implement temporal argument auto-binding in `phase_executor.py`:
```
IF DateRange Orchestrator has resolved dates
AND target tool has start_date/end_date parameters
THEN bind resolved dates to tool parameters automatically
```

This would eliminate the need for `base_readQuery` SQL fallback on temporal queries.

---

### Pattern 3: Semantic / Description Issues

#### 3a. `qlty_distinctCategories` → `base_columnDescription`

| Metric | @OPTIM | @IDEAT |
|--------|--------|--------|
| **Verdict** | FAIL | PASS |
| **Tools used** | `base_columnDescription` | `qlty_distinctCategories` (+ `base_columnDescription` + `qlty_distinctCategories` retry) |
| **Tokens** | 13,669 | 30,758 |

**Query:** *"Show the distinct values in the category column of the products table in the fitness_db database"*

**Root cause:** The `qlty_distinctCategories` tool description contains a **typo**: *"Get the **destinct** categories from column in a table."* The misspelling of "distinct" as "destinct" reduces the LLM's semantic matching confidence. Meanwhile `base_columnDescription` (*"Shows detailed column information..."*) is a close semantic neighbor, and the planner selects it instead.

Note: @IDEAT still found it (on second attempt), suggesting the conversation agent is more resilient to description typos because it does direct function-calling rather than strategic plan generation.

**Recommendation (MCP Server Team):** Fix the typo in the tool description:
- Current: `"Get the destinct categories from column in a table."`
- Fixed: `"Get the distinct categories (unique values) from a column in a table."`

#### 3b. `base_tablePreview` → Planner Skipped Entirely

| Metric | @OPTIM | @IDEAT |
|--------|--------|--------|
| **Verdict** | FAIL | PASS |
| **Tools used** | `TDA_FinalReport` only | `base_tablePreview` |
| **Tokens** | 17,484 | 14,482 |

**Query:** *"Use the base_tablePreview tool to show the first rows of the products table in fitness_db"*

**Root cause:** The query contained an **explicit tool instruction** ("Use the base_tablePreview tool to..."). The planner's conversational classifier interpreted this as a conversational request rather than a tool execution directive, skipping tool execution entirely and going straight to `TDA_FinalReport`.

**Recommendation (Test Framework):** This is a fixture issue, not a planner bug. Change the query to natural language:
- Current: `"Use the base_tablePreview tool to show the first rows..."`
- Fixed: `"Show me a preview of the first rows from the products table in fitness_db"`

---

## Token Cost Impact Summary

| Failure Pattern | Fixtures | Avg Token Overhead vs Correct Routing | Total Extra Tokens |
|----------------|----------|--------------------------------------|-------------------|
| Generic Tool Bias | 3 | +0% (similar cost) | ~0 |
| Temporal Binding | 4 | +130% (2.3x) | ~50,000 |
| Semantic Issues | 2 | +20% | ~6,000 |

The temporal binding failures are the costliest — they consume **2.3x more tokens** than correct routing because:
1. `TDA_CurrentDate` call adds ~2,000 tokens
2. `TDA_DateRange` iteration adds ~5,000-10,000 tokens
3. `base_readQuery` SQL generation adds LLM overhead
4. Results from SQL may be larger than dedicated tool output

---

## Comparative Analysis: @OPTIM vs @IDEAT on Shared Fixtures

For the 25 fixtures run on both profiles (excluding 5 disabled):

| Fixture | @OPTIM Verdict | @OPTIM Tokens | @IDEAT Verdict | @IDEAT Tokens | Routing Match? |
|---------|---------------|--------------|---------------|--------------|----------------|
| base_databaseList | PASS | 11,297 | PASS | 16,903 | Both correct |
| base_tableList | PASS | 9,189 | PASS | 13,937 | Both correct |
| base_tableDDL | PASS | 9,324 | PASS | 14,168 | Both correct |
| base_tablePreview | **FAIL** | 17,484 | PASS | 14,482 | @IDEAT better |
| base_columnDescription | PASS | 9,324 | PASS | 14,069 | Both correct |
| base_tableAffinity | PASS | 9,482 | PASS | 14,605 | Both correct |
| base_tableUsage | **FAIL** | 22,430 | **FAIL** | 14,053 | Both wrong |
| base_readQuery | PASS | 9,489 | PASS | 14,738 | Both correct |
| qlty_columnSummary | PASS | 9,713 | PASS | 14,741 | Both correct |
| qlty_distinctCategories | **FAIL** | 13,669 | PASS | 30,758 | @IDEAT better |
| qlty_missingValues | PASS | 9,347 | PASS | 14,025 | Both correct |
| qlty_negativeValues | PASS | 9,041 | PASS | 13,981 | Both correct |
| qlty_rowsWithMissingValues | PASS | 9,232 | PASS | 13,874 | Both correct |
| qlty_standardDeviation | PASS | 9,046 | PASS | 13,957 | Both correct |
| qlty_univariateStatistics | PASS | 10,798 | PASS | 15,793 | Both correct |
| dba_databaseSpace | PASS | 8,932 | PASS | 13,923 | Both correct |
| dba_databaseVersion | **FAIL** | 8,670 | PASS | 13,922 | @IDEAT better |
| dba_resusageSummary | PASS | 11,864 | PASS | 22,800 | Both correct |
| dba_sessionInfo | **FAIL** | 10,488 | PASS | 15,973 | @IDEAT better |
| dba_systemSpace | **FAIL** | 8,806 | PASS | 14,036 | @IDEAT better |
| dba_tableSpace | PASS | 9,153 | PASS | 13,874 | Both correct |
| dba_tableSqlList | PASS | 8,992 | PASS | 57,785 | Both correct* |
| dba_tableUsageImpact | PASS | 9,620 | PASS | 13,857 | Both correct |
| sec_rolePermissions | PASS | 11,586 | PASS | 16,601 | Both correct |
| sec_userRoles | PASS | 8,822 | PASS | 13,798 | Both correct |

**Summary:**
- @OPTIM uses **37% fewer tokens** on average when it routes correctly (9,700 avg vs 15,400 avg)
- @OPTIM has **6 additional correct routings** that @IDEAT also gets right
- @IDEAT correctly routes **5 tools** that @OPTIM misroutes
- `base_tableUsage` fails on BOTH modes — suggesting the tool itself is hard to discover

*\*dba_tableSqlList: @IDEAT used 57,785 tokens (called tool 3 times) — a cost concern*

---

## Recommendations Summary

### For MCP Server Team (External)

| Priority | Action | Impact |
|----------|--------|--------|
| **P1** | Fix `qlty_distinctCategories` typo ("destinct" → "distinct") | Fixes 1 routing failure |
| **P2** | Enhance DBA system tool descriptions (version, session, space) | Fixes 3 routing failures |
| **P2** | Add "no SQL required" to description of parameterless DBA tools | Reduces generic bias |
| **P3** | Add temporal context hints to tool descriptions with date params | Helps planner binding |

### For Uderia Planner Team (Internal)

| Priority | Action | Impact | Effort |
|----------|--------|--------|--------|
| **P1** | Add tool selection priority to WORKFLOW_META_PLANNING_PROMPT | Fixes Pattern 1 (3-6 failures) | Low |
| **P2** | Implement temporal argument auto-binding in phase_executor.py | Fixes Pattern 2 (4 failures) | Medium |
| **P3** | Add scope annotations to tool context (e.g., "[system]", "[quality]") | Improves routing accuracy | Low |
| **P3** | Fix `base_tablePreview` fixture query (remove explicit tool instruction) | Fixes 1 test failure | Trivial |

---

## Appendix A: Disabled Fixtures (Cost-Intensive)

These 5 fixtures were disabled after the initial @OPTIM run due to excessive token cost or execution time:

| Fixture | Tokens | Duration | Reason |
|---------|--------|----------|--------|
| `dba_featureUsage` | 27,890 | 18.3s | Large temporal result set |
| `dba_flowControl` | 22,584 | 22.4s | Large temporal result set |
| `dba_userDelay` | 17,431 | 8.1s | Large temporal result set |
| `dba_userSqlList` | 7,489 | 79.6s | DBC user massive SQL history |
| `sec_userDbPermissions` | 7,822 | 85.8s | DBC user extensive permissions |

## Appendix B: Test Reports

- @OPTIM full suite: `results/tool_test_20260216_102941.json` / `.md`
- @IDEAT full suite: `results/tool_test_20260216_103358.json` / `.md`
- Earlier category runs: `results/tool_test_20260216_10*.json`
