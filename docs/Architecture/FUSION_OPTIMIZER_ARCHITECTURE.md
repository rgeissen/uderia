# Fusion Optimizer Architecture

## Overview

The Trusted Data Agent operates on a two-tier execution model: a **Strategic Planner** generates multi-phase plans, and a **Tactical Executor** carries them out phase-by-phase. Between these two layers — and woven throughout them — sits the **Fusion Optimizer**: six interconnected subsystems that collectively transform a raw LLM-generated plan into a production-grade execution pipeline.

These subsystems are not isolated features. They form a **connected optimization mesh** where each subsystem's outputs feed, guard, or trigger others. Plan Validation prevents hallucinations that would otherwise require Error Correction. Context Distillation serves every LLM call made by Error Recovery and Re-planning. Re-planning consumes error patterns surfaced by Error Correction. Together, they enforce a design contract:

> **Every plan is validated before execution, every execution is monitored for correction, every correction preserves context budget, and every recovery learns from prior failures.**

```
                        FUSION OPTIMIZER ARCHITECTURE
                        =============================

    USER QUERY
        |
        v
  +-----------------------+
  |   STRATEGIC PLANNER   |--- generates raw meta_plan (LLM output)
  |   planner.py          |
  +-----------------------+
        |
        | raw plan
        v
  +=======================================================================+
  |                   FUSION OPTIMIZER — Pre-Execution                    |
  |                                                                       |
  |   +---------------------+     +---------------------+                 |
  |   | [S1] DETERMINISTIC  |     | [S3] HALLUCINATION  |                 |
  |   | PLAN VALIDATION     |---->| PREVENTION          |                 |
  |   |                     |     |                     |                 |
  |   | 5 structural passes |     | Orchestrator guards |                 |
  |   | + 7 rewrite passes  |     | Plan hydration      |                 |
  |   +---------------------+     | Turn validity       |                 |
  |           |                   +---------------------+                 |
  |           v                           |                               |
  |   +---------------------+            |                                |
  |   | [S2] PROACTIVE      |<-----------+                                |
  |   | RE-PLANNING         |                                             |
  |   |                     |     +---------------------+                 |
  |   | Prompt->Tool rewrite|     | [S6] CONTEXT        |                 |
  |   | max 1 replan        |     | DISTILLATION        |                 |
  |   +---------------------+     |                     |                 |
  |                               | Serves ALL LLM calls|                 |
  |                               | 5-pass budget       |                 |
  |                               | 2-level analytical  |                 |
  |                               +---------------------+                 |
  +=======================================================================+
        |
        | validated + optimized plan
        v
  +-----------------------+
  |   TACTICAL EXECUTOR   |--- executes phase-by-phase
  |   phase_executor.py   |
  +-----------------------+
        |
        | per-tool execution
        v
  +=======================================================================+
  |                     FUSION OPTIMIZER — Runtime                        |
  |                                                                       |
  |   +---------------------+     +---------------------+                 |
  |   | [S4] INTELLIGENT    |     | [S5] AUTONOMOUS     |                 |
  |   | ERROR CORRECTION    |---->| RECOVERY            |                 |
  |   |                     |     |                     |                 |
  |   | Strategy Pattern    |     | Triggered after 5   |                 |
  |   | 3 retries per tool  |     | phase retries       |                 |
  |   | Profile-aware       |     | New plan from LLM   |                 |
  |   +---------------------+     | globally_skipped    |                 |
  |           ^                   +---------------------+                 |
  |           |                           |                               |
  |           +--- [S6] Context Distillation feeds recovery prompts       |
  |           +--- [S3] Orchestrator guards prevent hallucinated loops    |
  +=======================================================================+
        |
        v
    FINAL RESULT
```

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [The Optimization Pipeline](#2-the-optimization-pipeline)
3. [Subsystem 1: Deterministic Plan Validation](#3-subsystem-1-deterministic-plan-validation)
4. [Subsystem 2: Proactive Re-planning](#4-subsystem-2-proactive-re-planning)
5. [Subsystem 3: Hallucination Prevention](#5-subsystem-3-hallucination-prevention)
6. [Subsystem 4: Intelligent Error Correction](#6-subsystem-4-intelligent-error-correction)
7. [Subsystem 5: Autonomous Recovery](#7-subsystem-5-autonomous-recovery)
8. [Subsystem 6: Context Distillation](#8-subsystem-6-context-distillation)
9. [Cross-Cutting Concerns](#9-cross-cutting-concerns)
10. [Observability & Event System](#10-observability--event-system)
11. [System Prompt Reference](#11-system-prompt-reference)
12. [Configuration Reference](#12-configuration-reference)
13. [File Reference](#13-file-reference)
14. [Recent Improvements](#14-recent-improvements-engine-modularization-branch)

---

## 1. Design Philosophy

Four governing principles emerge from the architecture and are enforced across all six subsystems:

### 1.1 Deterministic Before LLM

Every correction that can be made with code — regex matching, schema validation, fuzzy string matching, datetime arithmetic — is made before invoking the LLM. This saves tokens, reduces latency, and produces predictable, reproducible results.

**Examples:**
- Plan Validation's 5 structural correction passes are entirely deterministic (`planner.py:252-451`)
- The Date Range Orchestrator uses `_resolve_temporal_phrase_deterministic()` for 12 common temporal patterns before falling back to LLM (`orchestrators.py:16-97`)
- Argument synonym mapping uses `AppConfig.ARGUMENT_SYNONYM_MAP` for automatic renaming (`config.py`)

### 1.2 Fail-Fast for Definitive Errors

Errors classified as definitive — permission denied, fundamentally invalid query syntax — are not retried. The `DEFINITIVE_TOOL_ERRORS` dictionary in `phase_executor.py:29-32` halts execution immediately with a clear, user-facing message. Only errors in `RECOVERABLE_TOOL_ERRORS` (table not found, column not found) enter the correction pipeline.

### 1.3 Progressive Escalation

The system escalates through increasingly expensive interventions, exhausting cheaper options first:

```
Deterministic Fix (free)
    → Tactical Retry (1 LLM call)
        → Self-Correction Strategy (1 LLM call)
            → Phase Retry (N LLM calls)
                → Autonomous Recovery (1 LLM call + full replan)
                    → Re-planning (1 LLM call + full replan)
```

### 1.4 Budget-Aware Everything

Every subsystem that touches the LLM context window is aware of token budgets. The Context Window Handler's 5-pass algorithm, the ExecutionContextDistiller's configurable thresholds, and the 2-level analytical distillation in the adapter all enforce strict budget compliance.

---

## 2. The Optimization Pipeline

### 2.1 Execution Lifecycle with Optimization Checkpoints

```
  Phase 0: PLAN GENERATION
  ┌──────────────────────────────────────────────────────────────────┐
  │ Planner._generate_meta_plan()                                   │
  │   [LLM generates raw plan from WORKFLOW_META_PLANNING_PROMPT]   │
  └──────────────┬───────────────────────────────────────────────────┘
                 │
  Phase 1: PLAN REFINEMENT PIPELINE (generate_and_refine_plan)
  ┌──────────────┴───────────────────────────────────────────────────┐
  │ Pass 1:  _rewrite_plan_for_temporal_data_flow()       [S1/S3]   │
  │ Pass 2:  _rewrite_plan_for_sql_consolidation()        [S1]      │
  │ Pass 3:  _rewrite_plan_for_multi_loop_synthesis()     [S1/S3]   │
  │ Pass 4:  _rewrite_plan_for_corellmtask_loops()        [S3]      │
  │ Pass 5:  _rewrite_plan_for_date_range_loops()         [S1/S3]   │
  │ Pass 6:  _validate_and_correct_plan()                 [S1]      │
  │ Pass 7:  _rewrite_plan_collapse_chart_data_refetch()  [S1]      │
  │ Pass 8:  _rewrite_plan_for_charting_phases()          [S1/S3]   │
  │ Pass 9:  _hydrate_plan_from_previous_turn()           [S3]      │
  │ Pass 10: _rewrite_plan_for_empty_context_report()     [S1]      │
  │ Pass 11: _ensure_final_report_phase()                 [S1]      │
  └──────────────┬───────────────────────────────────────────────────┘
                 │
  Phase 2: EFFICIENCY RE-PLANNING CHECK
  ┌──────────────┴───────────────────────────────────────────────────┐
  │ Does plan mix prompts + tools?                        [S2]      │
  │   YES + non-granted prompts + multi-phase + depth 0             │
  │     → Loop back to Phase 0 with replan_context                  │
  │     → max_replans = 1                                           │
  │   NO → proceed to execution                                    │
  └──────────────┬───────────────────────────────────────────────────┘
                 │
  Phase 3: EXECUTION WITH RUNTIME GUARDS
  ┌──────────────┴───────────────────────────────────────────────────┐
  │ For each phase in meta_plan:                                    │
  │                                                                 │
  │   [S6] Context distillation on workflow_state                   │
  │        before any tactical LLM call                             │
  │                                                                 │
  │   [S3] Orchestrator guards:                                     │
  │        - Date Range: validates temporal phrases                  │
  │        - Column Iteration: validates type compatibility          │
  │        - Hallucinated Loop: detects string literal lists         │
  │                                                                 │
  │   [S4] On tool error:                                           │
  │        - DEFINITIVE errors → halt immediately                   │
  │        - RECOVERABLE errors → CorrectionHandler                 │
  │          → 3 retries with corrected arguments                   │
  │                                                                 │
  │   [S5] After MAX_PHASE_RETRY_ATTEMPTS (5) exhausted:            │
  │        → _recover_from_phase_failure()                          │
  │        → Distill workflow state [S6]                            │
  │        → LLM generates entirely new plan                        │
  │        → Failed tool added to globally_skipped_tools            │
  │        → meta_plan swapped, restart from phase 1                │
  └─────────────────────────────────────────────────────────────────┘
```

### 2.2 Walkthrough Scenario

**User asks:** "Show me customer orders for the past 7 days as a pie chart"

1. **Strategic Planner** generates a 3-phase plan: Phase 1 = `TDA_CurrentDate`, Phase 2 = `base_customerOrders` (no date arg), Phase 3 = `TDA_Charting` (with hallucinated `mapping` args)
2. **[S1] Temporal Data Flow Rewrite** detects `TDA_CurrentDate` is not wired to Phase 2, injects `"past 7 days"` as the date argument
3. **[S1/S3] Chart Argument Cleanup** strips the hallucinated `mapping` and `data` from Phase 3
4. **[S1] Plan Validation** checks Phase 2's tool schema — no extraneous args remain
5. **[S2]** Plan passes the Re-planning check (no executable prompts in plan)
6. **Execution begins**: Phase 2's temporal date arg triggers the **[S3] Date Range Orchestrator**, which deterministically resolves "past 7 days" to 7 concrete dates without an LLM call
7. Phase 2 returns 500 rows — **[S6] Context Distillation** replaces raw data with metadata summary for Phase 3's tactical LLM prompt
8. If Phase 2 had failed with "Table 'CustomerOrders' does not exist", **[S4] TableNotFoundStrategy** would fire, asking the LLM for the correct table name, then retry with corrected args
9. If 5 retries failed, **[S5] Autonomous Recovery** would generate an entirely new plan, adding the failed tool to `globally_skipped_tools`

---

## 3. Subsystem 1: Deterministic Plan Validation

**What:** A multi-pass pipeline of deterministic corrections applied to the raw LLM-generated plan before any execution begins.

**Why:** LLMs generate plans with predictable error patterns — misclassifying prompts as tools, hallucinating argument names, forgetting to wire data flow between phases. These errors are detectable by code and correctable without LLM cost.

### 3.1 The 5 Structural Correction Passes

**File:** `src/trusted_data_agent/agent/planner.py:252-451` — `_validate_and_correct_plan()`

| Pass | Error Pattern | Detection | Correction |
|------|--------------|-----------|------------|
| 1 | Invalid `executable_prompt` values | Value in `[None, 'None', 'null', '', 'undefined']` | Delete the key |
| 2 | Prompt misclassified as tool | `relevant_tools[0]` found in `mcp_prompts` dict | Move to `executable_prompt`, delete `relevant_tools` |
| 3 | Tool misclassified as prompt | `executable_prompt` value found in `mcp_tools` dict | Move to `relevant_tools`, delete `executable_prompt` |
| 4 | Hallucinated/extraneous arguments | Arg names not in tool schema (incl. `ARGUMENT_SYNONYM_MAP`) | Remove extraneous; flag `_needs_refinement` if required args now missing |
| 5 | Parameter name mismatches | `difflib.SequenceMatcher` ratio > 0.7 against schema params | Rename arg to matching schema parameter |

### 3.2 The Semantic Rewrite Passes

**File:** `src/trusted_data_agent/agent/planner.py` — `generate_and_refine_plan()` (lines 2395-2424)

| Pass | Method | Purpose |
|------|--------|---------|
| 1 | `_rewrite_plan_for_temporal_data_flow()` | Wire `TDA_CurrentDate` results to downstream tool date arguments |
| 2 | `_rewrite_plan_for_sql_consolidation()` | Consolidate redundant sequential SQL queries (via `SQL_CONSOLIDATION_PROMPT`) |
| 3 | `_rewrite_plan_for_multi_loop_synthesis()` | Insert intermediate distillation phase between parallel loops and final summary |
| 4 | `_rewrite_plan_for_corellmtask_loops()` | Correct plans where `TDA_LLMTask` is unnecessarily placed inside loops |
| 5 | `_rewrite_plan_for_date_range_loops()` | Convert `TDA_DateRange` + flat reference into proper loop; or wire `start_date`/`end_date` for range tools |
| 6 | `_rewrite_plan_collapse_chart_data_refetch()` | Eliminate redundant data re-fetch phases before charting |
| 7 | `_rewrite_plan_for_charting_phases()` | Strip hallucinated `mapping` and `data` args from `TDA_Charting` phases |

**Additional passes** (non-rewrite but part of the pipeline):
- `_hydrate_plan_from_previous_turn()` — Cross-turn data injection with source validation
- `_rewrite_plan_for_empty_context_report()` — Synthesize answer from knowledge context when no tools needed
- `_ensure_final_report_phase()` — Guarantee terminal report phase exists

### 3.3 Interconnections

- **Feeds S2**: A validated plan is checked for efficiency by Proactive Re-planning
- **Prevents work for S4**: Eliminating hallucinated args and misclassified tools means fewer runtime errors
- **Coordinates with S3**: Several rewrite passes (temporal flow, date range loops, charting cleanup) explicitly prevent hallucination patterns

---

## 4. Subsystem 2: Proactive Re-planning

**What:** After plan validation, the system evaluates whether the plan is structurally inefficient — specifically, whether it mixes high-level executable prompts (which spawn nested `PlanExecutor` sub-plans) with direct tool calls. If so, it forces a replan using only tools.

**Why:** Executable prompts create nested execution sub-plans (recursive `PlanExecutor` instantiation via `execution_depth`). When a plan already contains direct tool calls alongside prompts, the prompt phases represent unnecessary LLM overhead — the same goal can typically be achieved with direct tool calls at lower cost and latency.

**File:** `src/trusted_data_agent/agent/executor.py:5094-5173`

### 4.1 Trigger Conditions

All must be true:

1. **`plan_has_prompt`**: At least one phase has `executable_prompt`
2. **`has_other_significant_tool`**: At least one phase is a non-prompt, non-`TDA_LLMTask` tool call
3. **`not is_single_phase_prompt`**: Plan has more than one phase
4. **`non_granted_prompts` exist**: The prompt is not in `GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING`
5. **`execution_depth == 0`**: Only at the top level (prevents recursive replan loops)
6. **`replan_attempt < max_replans`**: At most one replan attempt (max_replans = 1)

### 4.2 Replan Context Injection

For each non-granted prompt, the system:
- Extracts the prompt's `description` via `_get_prompt_info()`
- Injects a `CRITICAL REPLANNING DIRECTIVE` telling the planner to replicate the goal using only basic tools
- Granted prompts receive a `CRITICAL PRESERVATION RULE` requiring they remain as plan phases

### 4.3 Configuration

| Key | Default | Purpose |
|-----|---------|---------|
| `GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING` | `["base_teradataQuery"]` | Prompts exempt from efficiency re-planning (too complex to decompose into basic tools) |

---

## 5. Subsystem 3: Hallucination Prevention

**What:** A collection of guards distributed across planning and execution that detect and neutralize LLM hallucinations — not just in text output, but in plan structure, data references, and loop constructs.

**Why:** LLMs hallucinate at the structural level: inventing table columns that do not exist, creating loops over string literals instead of data references, injecting unresolved placeholder objects as arguments, and referencing plan phases that have not succeeded.

### 5.1 Date Range Orchestrator

**File:** `src/trusted_data_agent/agent/orchestrators.py:108-465`

Executes a tool over a calculated date range. Supports two modes:
- **Single-date tools** (`tool_supports_range=False`): Iterates the tool once per day
- **Range tools** (`tool_supports_range=True`): Calls tool once with `start_date`/`end_date`

**Guards:**

| Guard | Detection | Action |
|-------|-----------|--------|
| Unresolved placeholder | Date arg is `dict` with `source`/`key` keys not resolvable from `workflow_state` | Raises `ValueError` → forces tactical replanning |
| Single-date recursion | Date arg matches `YYYY-MM-DD` pattern | Executes directly, returns (prevents infinite recursion) |
| Empty date phrase | `date_phrase` is empty/None | Attempts regex extraction from `phase.goal`; raises `RuntimeError` if unrecoverable |

**Deterministic Temporal Resolution** (`_resolve_temporal_phrase_deterministic`, lines 16-97):

Handles 12 temporal patterns without any LLM call:

| Pattern | Example |
|---------|---------|
| `today` | Current date |
| `yesterday` | Current date - 1 |
| `last/past N days` | N days back to yesterday |
| `last/past N weeks` | N weeks back to yesterday |
| `last/past N months` | N months back to yesterday |
| `this week` / `current week` | Monday to today |
| `last week` | Previous Monday to Sunday |
| `this month` / `current month` | 1st to today |
| `last month` | 1st to last day of previous month |
| `this year` / `current year` | Jan 1 to today |
| `last year` | Jan 1 to Dec 31 of previous year |

Falls back to LLM only for unrecognized temporal phrases.

**Plan-aware optimization:** When a previous phase has already calculated a date list and stored it in `workflow_state`, the orchestrator reuses it — bypassing both deterministic resolution and LLM calls entirely (lines 134-145).

### 5.2 Column Iteration Orchestrator

**File:** `src/trusted_data_agent/agent/orchestrators.py:467-555`

| Step | Action |
|------|--------|
| 1 | Fetches actual column metadata via `base_columnDescription` tool |
| 2 | Queries tool constraints for required data type (numeric/character) |
| 3 | For each column: checks type compatibility, skips incompatible with explicit `"skipped"` result |
| 4 | Replaces placeholder `column_name` synonyms with actual column name per iteration |
| 5 | Consolidates all results |

### 5.3 Hallucinated Loop Orchestrator

**File:** `src/trusted_data_agent/agent/orchestrators.py:556-619`

**Problem:** Planner generates `loop_over: ["revenue", "expenses", "profit"]` — string literals instead of a data source reference.

**Detection & correction:**

```
loop_over contains string items (not "result_of_phase_N")?
    |
    v
Single item with date keyword? ("day", "week", "month", etc.)
    |
  YES → Route to Date Range Orchestrator
    |
   NO → LLM semantic analysis:
        "What single tool argument do these items represent?"
        → Returns e.g. {"argument_name": "table_name"}
        → Execute tool once per item with correct arg name
```

### 5.4 Plan Hydration Validation

**File:** `src/trusted_data_agent/agent/planner.py:182-250`

When a plan references data from a previous turn:
1. Validates source phase exists in previous turn's execution trace
2. Checks `result_summary.get("status") == "success"`
3. Only injects data if validation passes
4. Modifies `loop_over` to reference `"injected_previous_turn_data"` key

### 5.5 Turn Validity Filtering

**File:** `src/trusted_data_agent/core/session_manager.py`

- Users can mark turns as invalid via UI (`isValid: false`)
- Invalid turns are filtered from planning context: `turn.get("isValid", True) is not False`
- Prevents the LLM from learning from its own failed attempts
- Invalid turns remain in audit trail but do not influence future execution

---

## 6. Subsystem 4: Intelligent Error Correction

**What:** A Strategy Pattern-based error correction system that intercepts tool execution failures, classifies them, and either generates corrected arguments via LLM or halts execution for definitive errors.

**Why:** Tool calls can fail for many reasons, and the optimal recovery strategy differs per error type. A table-not-found error requires different handling than a column-not-found error or a JSON parsing error.

**File:** `src/trusted_data_agent/agent/phase_executor.py:29-293`

### 6.1 Error Taxonomy

**Definitive errors** — halt immediately, never retried:

```python
DEFINITIVE_TOOL_ERRORS = {
    "Invalid query": "The generated query was invalid and could not be run against the database.",
    "3523": "The user does not have the necessary permissions for the requested object."
}
```

**Recoverable errors** — matched by regex, trigger correction strategies:

```python
RECOVERABLE_TOOL_ERRORS = {
    "table_not_found": r"Object '([\w\.]+)' does not exist",
    "column_not_found": r"Column '(\w+)' does not exist"
}
```

### 6.2 The Strategy Pattern

```
Tool Error Detected
    |
    v
Is it DEFINITIVE? (permission, invalid query)
    |
  YES → Raise DefinitiveToolError → Halt & Summarize
    |
   NO → CorrectionHandler.attempt_correction()
        |
        v
    Strategy chain (first match wins):
    ┌─────────────────────────────────┐
    │ 1. TableNotFoundStrategy        │  regex: "Object '...' does not exist"
    ├─────────────────────────────────┤
    │ 2. ColumnNotFoundStrategy       │  regex: "Column '...' does not exist"
    ├─────────────────────────────────┤
    │ 3. GenericCorrectionStrategy    │  always matches (fallback)
    └─────────────────────────────────┘
        |
        v
    LLM generates corrected action
        |
        v
    Retry with corrected arguments (up to 3 times)
```

### 6.3 Strategy Details

| Strategy | Trigger | Recovery Approach | Prompt |
|----------|---------|-------------------|--------|
| `TableNotFoundStrategy` (lines 129-162) | Regex match on table name | Instructs LLM to use `listTables` tool — **"DO NOT GUESS ANOTHER TABLE NAME"** | `TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR` |
| `ColumnNotFoundStrategy` (lines 164-193) | Regex match on column name | Instructs LLM to use `describeColumns` tool — **"DO NOT GUESS ANOTHER COLUMN NAME"** | `TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR` |
| `GenericCorrectionStrategy` (lines 195-269) | Always (fallback) | Sub-handler for JSON parsing errors in report tools → routes to `TDA_LLMTask` for text sanitization. Otherwise, generic correction with full tool definition | `TACTICAL_SELF_CORRECTION_PROMPT` |

### 6.4 Ground Truth Enforcement

The table and column error prompts are specifically designed to prevent the LLM from guessing:

- **Table error:** *"Your primary rule is: DO NOT GUESS ANOTHER TABLE NAME. You must work only with the facts."*
- **Column error:** *"Substituting a semantically similar column (e.g., using an 'address' column for a 'zip_code' request) is a forbidden action."*

This forces the LLM to use discovery tools (`listTables`, `describeColumns`) rather than inventing new names.

### 6.5 LLM Correction Output Parsing

The `_call_correction_llm()` method (lines 55-127) parses LLM responses into four possible outcomes:

| Response Format | Action |
|----------------|--------|
| `FINAL_ANSWER:` prefix | Task complete — halt retries, return answer |
| JSON with `prompt_name` + `arguments` | Switch to different prompt (escalation) |
| JSON with `tool_name` + `arguments` | Retry with different tool or corrected args |
| JSON with just `arguments` | Retry same tool with corrected args |

Special handling: When the LLM proposes `TDA_LLMTask`, the system auto-injects required context args (`extra_args_for_llm_task`).

### 6.6 Profile-Aware Prompt Resolution

All correction strategies use `executor.prompt_resolver` (a `ProfilePromptResolver` instance) to load correction prompts. This allows different profiles to customize recovery behavior — for example, a profile for Teradata databases could use different correction prompts than one for PostgreSQL.

---

## 7. Subsystem 5: Autonomous Recovery

**What:** A last-resort recovery mechanism that, when all phase retries and error corrections have failed, asks the LLM to generate an entirely new plan from scratch.

**Why:** Some failures cannot be recovered by adjusting arguments — the entire approach may be wrong (wrong tool, wrong sequence, missing prerequisite). Autonomous recovery represents the system's ability to "step back" and try a fundamentally different approach.

**File:** `src/trusted_data_agent/agent/phase_executor.py` — trigger at lines 1405-1415, implementation at lines 2685-2799

### 7.1 Trigger

```python
phase_attempts > APP_CONFIG.MAX_PHASE_RETRY_ATTEMPTS  # default: 5
```

### 7.2 Recovery Steps

```
Phase fails after 5 retries
    |
    v
1. Identify failed tool (scan turn_action_history in reverse)
    |
    v
2. Blacklist failed tool → globally_skipped_tools set
   (persists for remainder of turn)
    |
    v
3. Distill workflow state [S6 interconnection]
   → _distill_data_for_llm_context() on deep copy
   → Emits context optimization SSE events
    |
    v
4. Build recovery prompt (ERROR_RECOVERY_PROMPT)
   → user_question, error_message, failed_tool_name,
     all_collected_data, workflow_goal_and_plan
    |
    v
5. LLM generates new plan (JSON list of phases)
    |
    v
6. Swap: executor.meta_plan = new_plan
   Reset: executor.current_phase_index = 0
   → Execution restarts from phase 1
```

### 7.3 Recovery Prompt Design

From `ERROR_RECOVERY_PROMPT.txt`:

> *"Your goal is to recover from this error by generating a new, complete, multi-phase plan to achieve the original user's question. Do NOT re-call the failed tool in the first step of your new plan."*

The prompt receives the full context: original question, error message, all collected data, and the workflow goal. This enables the LLM to make informed decisions about alternative approaches.

### 7.4 Safety Mechanisms

- **Audit trail:** Recovery emits a `RECOVERY_REPLAN` action to `turn_action_history`
- **Tool blacklisting:** `globally_skipped_tools` persists across recovery, preventing circular failures
- **Parse safety:** If the LLM's recovery response cannot be parsed as valid JSON, a `RuntimeError` is raised — the system does not silently continue

---

## 8. Subsystem 6: Context Distillation

**What:** A multi-layered data reduction system that protects the LLM context window from overflow while preserving maximum analytical fidelity.

**Why:** Tool results frequently return hundreds or thousands of rows. Injecting raw data into LLM prompts would exceed context limits and degrade response quality. The distillation system ensures every LLM call operates within its token budget.

### 8.1 Architecture

```
  CONTEXT DISTILLATION — THREE LAYERS
  =====================================

  Layer 1: Execution Context Distillation (intra-turn)
  ┌────────────────────────────────────────────────────────────┐
  │  ExecutionContextDistiller (distiller.py)                  │
  │                                                            │
  │  Trigger: results[] > max_rows (500) OR > max_chars (10K) │
  │  Action:  Recursive traversal of nested dicts/lists        │
  │           Replace large results with metadata summary      │
  │  Used by: Tactical planning, TDA_LLMTask, error recovery  │
  └────────────────────────────────────────────────────────────┘

  Layer 2: Analytical Distillation (report generation)
  ┌────────────────────────────────────────────────────────────┐
  │  _distill_workflow_for_report() (adapter.py:27-320)       │
  │                                                            │
  │  L1 Trigger: >100 rows OR >50K chars per result set       │
  │  L1 Action:  Column statistics on FULL dataset             │
  │              + Stratified sample (boundary + spaced)       │
  │                                                            │
  │  L2 Trigger: Total distilled size > 200K chars             │
  │  L2 Action:  Aggressive reduction to 25 rows               │
  │              Column statistics PRESERVED (computed on full) │
  └────────────────────────────────────────────────────────────┘

  Layer 3: Context Window Budget Assembly (per-LLM-call)
  ┌────────────────────────────────────────────────────────────┐
  │  ContextWindowHandler (handler.py)                        │
  │                                                            │
  │  Pass 1: Resolve active modules (skip deactivated)        │
  │  Pass 2: Apply dynamic adjustments (condition-based)      │
  │  Pass 3: Allocate per-module budgets + assemble           │
  │  Pass 3b: Reallocate surplus (under→over utilization)     │
  │  Pass 4: Condense if over budget (lowest priority first)  │
  └────────────────────────────────────────────────────────────┘
```

### 8.2 Layer 1: Execution Context Distiller

**File:** `components/builtin/context_window/distiller.py`

```python
class ExecutionContextDistiller:
    def __init__(self, max_rows=500, max_chars=10_000):
        # Configurable thresholds from context window type

    def distill(self, data, events=None):
        # Recursive traversal of nested dicts/lists
        # results[] > max_rows OR > max_chars
        # → Replace with {status, metadata{row_count, columns}, comment}
```

**Used at three points:**
1. Tactical planning — before the tactical LLM call
2. `TDA_LLMTask` focused payloads — custom data preparation
3. Multi-loop error recovery — simplify context for self-correction prompts

### 8.3 Layer 2: Analytical Distillation

**File:** `src/trusted_data_agent/mcp_adapter/adapter.py:27-320`

**Two-level system:**

| Level | Trigger | Action | Preserves |
|-------|---------|--------|-----------|
| L1 | >100 rows OR >50K chars per result set | Compute per-column statistics on FULL dataset + stratified sample | Full statistical profile |
| L2 | Total distilled size >200K chars | Aggressive reduction to 25 rows per result set | Column statistics (computed on full data during L1) |

**Stratified sampling algorithm:**
```
Take boundary rows (first 5, last 5)
Fill interior with evenly-spaced samples
→ Ensures head/tail/middle coverage instead of naive first-N truncation
```

**Column statistics by type:**

| Type | Detection | Statistics Computed |
|------|-----------|-------------------|
| Numeric | >80% successful `float()` conversion | min, max, mean, sum, median, p25, p75, stddev |
| Temporal | Column name heuristics ("date", "time", "timestamp") | range, distinct count, top-10 values with frequency |
| Categorical | Fallback (everything else) | distinct count, top-10 distribution with percentages |

### 8.4 Layer 3: Context Window Budget Assembly

**File:** `components/builtin/context_window/handler.py`

The ContextWindowHandler implements a 5-pass budget assembly algorithm:

| Pass | Purpose |
|------|---------|
| Pass 1 | Resolve active modules — skip deactivated/inapplicable, redistribute budget |
| Pass 2 | Apply dynamic adjustments — condition-based reallocation (first_turn, no_documents, long_conversation) |
| Pass 3 | Allocate and assemble — per-module budget = available × target_pct / 100, clamped to [min_pct, max_pct] |
| Pass 3b | Reallocate surplus — donors (utilization < 30%) → recipients (utilization > 80%) |
| Pass 4 | Condense if over budget — process modules in `condensation_order` (lowest priority first) |

See [Context Window Architecture](CONTEXT_WINDOW_ARCHITECTURE.md) for detailed analysis.

---

## 9. Cross-Cutting Concerns

### 9.1 The Escalation Chain

```
Tool fails
    |
    v
[S4] Is error definitive? ── YES ──> HALT (DefinitiveToolError)
    |
   NO
    |
    v
[S4] CorrectionHandler.attempt_correction()
    |
    v
Correction succeeded? ── YES ──> Retry tool (up to 3x)
    |
   NO (or 3 retries exhausted)
    |
    v
[Tactical Executor] Phase retry (up to 5x)
    |
    v
Phase retry exhausted?
    |
   YES
    |
    v
[S5] _recover_from_phase_failure()
    |
    v
[S6] Distill workflow state for recovery prompt
    |
    v
LLM generates new plan
    |
    v
[S1] New plan enters execution loop
    |
    v
Execution restarts from phase 1
```

### 9.2 Context Distillation as Universal Service

Every subsystem that touches the LLM depends on S6:

| Subsystem | How It Uses Context Distillation |
|-----------|--------------------------------|
| S1 Plan Validation | Rewrite passes may trigger LLM calls routed through context-managed prompts |
| S2 Re-planning | Replan LLM call via `_call_llm_and_update_tokens` respects ContextWindowHandler budgets |
| S3 Hallucination Prevention | Orchestrator LLM fallbacks (date resolution, semantic classification) use managed context |
| S4 Error Correction | `_call_correction_llm` routes through `_call_llm_and_update_tokens` |
| S5 Autonomous Recovery | Explicitly calls `_distill_data_for_llm_context()` on workflow_state before recovery prompt |

### 9.3 Plan Validation Prevents Downstream Errors

S1 eliminates entire classes of errors that would otherwise trigger S4:

| Validation Pass | Error Class Prevented |
|----------------|----------------------|
| Pass 2 (prompt as tool) | Tool execution would fail with "tool not found" |
| Pass 3 (tool as prompt) | Prompt execution would fail with "prompt not found" |
| Pass 4 (extraneous args) | Tool would reject unrecognized arguments |
| Pass 5 (param name fix) | Tool would receive wrong parameter names |
| Charting cleanup | Tactical planner would waste a refinement cycle hallucinating column mappings |
| Temporal data flow | Date Range Orchestrator would receive unresolved placeholder |

### 9.4 Profile-Awareness Thread

The `ProfilePromptResolver` (from `profile_prompt_resolver.py`) threads through multiple subsystems, allowing different profiles to customize behavior:

| Subsystem | Prompt Method |
|-----------|--------------|
| S4 | `get_tactical_self_correction_prompt()` |
| S4 | `get_tactical_self_correction_table_error_prompt()` |
| S4 | `get_tactical_self_correction_column_error_prompt()` |
| S5 | `get_error_recovery_base_prompt()` |
| S6 | Context window type determines distillation thresholds |

---

## 10. Observability & Event System

All subsystems emit SSE events via `executor._format_sse_with_depth()` and persist to `turn_action_history` via `executor._log_system_event()`.

### 10.1 SSE Event Types by Subsystem

| Subsystem | Event Type | Step Text | When |
|-----------|-----------|-----------|------|
| S1 | `workaround` | "Plan Optimization" | Structural correction applied |
| S1 | `plan_optimization` | "Plan Optimization" | Semantic rewrite pass applied |
| S2 | `plan_optimization` | "Re-planning for Efficiency" | Efficiency replan triggered |
| S3 | `workaround` | "System Orchestration" / "System Correction" | Orchestrator guard activated |
| S4 | `system_message` | "Calling LLM for Self-Correction" | Correction LLM call |
| S4 | `workaround` | "System Self-Correction" | Corrected action applied |
| S5 | `system_message` | "Attempting LLM-based Recovery" | Recovery LLM call |
| S5 | `system_message` | "Recovery Plan Generated" | New plan from recovery |
| S6 | `context_optimization` | "Context Optimization" | Data distilled |
| All | `token_update` | — | Every LLM call (tokens + cost) |

### 10.2 System Event Log Format

```python
{
    "action": {
        "tool_name": "TDA_SystemLog",
        "arguments": {"message": "<step>", "details": "<details>"},
        "metadata": {
            "execution_depth": N,
            "type": "<event_type>",
            "timestamp": "<ISO 8601>"
        }
    },
    "result": {"status": "info" | "error" | "cancelled"}
}
```

### 10.3 Token Tracking

Every LLM call emits a `token_update` SSE event:

| Field | Scope |
|-------|-------|
| `statement_input` / `statement_output` | This LLM call |
| `turn_input` / `turn_output` | Accumulated for this turn |
| `total_input` / `total_output` | Session cumulative |
| `call_id` | UUID for correlation |
| `cost_usd` | Computed cost for this call |

---

## 11. System Prompt Reference

| Subsystem | Prompt File | Purpose |
|-----------|-------------|---------|
| S1, S2 | `WORKFLOW_META_PLANNING_PROMPT.txt` | Strategic plan generation with all critical directives |
| Tactical | `WORKFLOW_TACTICAL_PROMPT.txt` | Single-phase execution with argument prioritization |
| S1 | `SQL_CONSOLIDATION_PROMPT.txt` | Consolidate inefficient sequential SQL queries |
| S4 | `TACTICAL_SELF_CORRECTION_PROMPT.txt` | Generic error correction with tool/prompt switching |
| S4 | `TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR.txt` | Table-not-found recovery with ground truth enforcement |
| S4 | `TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR.txt` | Column-not-found recovery with ground truth enforcement |
| S5 | `ERROR_RECOVERY_PROMPT.txt` | Autonomous replanning after persistent failure |

**Prompt location:** `default_prompts/` directory (configurable per-profile via prompt mapping)

---

## 12. Configuration Reference

| Config Key | Default | Subsystem | Description |
|-----------|---------|-----------|-------------|
| `MAX_PHASE_RETRY_ATTEMPTS` | 5 | S4, S5 | Phase retries before autonomous recovery |
| `MAX_EXECUTION_DEPTH` | 5 | S2 | Maximum nested PlanExecutor depth |
| `GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING` | `["base_teradataQuery"]` | S2 | Prompts exempt from efficiency re-planning |
| `ENABLE_SQL_CONSOLIDATION_REWRITE` | `True` | S1 | Enable SQL consolidation rewrite pass (enabled by default) |
| `LLM_CALL_TIMEOUT_SECONDS` | 120 | All | asyncio timeout for every LLM call (0 = disabled) |
| `PARALLEL_PHASE_ENABLED` | `True` | OptimizeEngine | Execute independent phases concurrently via asyncio.gather |
| `CONTEXT_DISTILLATION_MAX_ROWS` | 500 | S6 | Execution context distiller row limit |
| `CONTEXT_DISTILLATION_MAX_CHARS` | 10,000 | S6 | Execution context distiller char limit |
| `REPORT_DISTILLATION_MAX_ROWS` | 100 | S6 | L1 per-result-set row limit |
| `REPORT_DISTILLATION_MAX_CHARS` | 50,000 | S6 | L1 per-result-set char limit |
| `REPORT_DISTILLATION_TOTAL_BUDGET` | 200,000 | S6 | L2 trigger: total char budget |
| `REPORT_DISTILLATION_AGGRESSIVE_ROWS` | 25 | S6 | L2 aggressive row limit per result set |
| `DOCUMENT_CONTEXT_MAX_CHARS` | 50,000 | S6 | Total char limit for uploaded documents |
| `DOCUMENT_PER_FILE_MAX_CHARS` | 20,000 | S6 | Per-document char truncation limit |
| `CONDENSE_SYSTEMPROMPT_HISTORY` | `True` | S6 | Names-only tool context after first turn |
| `USE_CONTEXT_WINDOW_MANAGER` | `True` | S6 | Use budget-aware ContextWindowHandler |

Context Window Type overrides (in `tda_config.json`):
- `distillation` block — per-CWT overrides for distiller thresholds
- `modules` — module activation, priority, `target_pct`, `min/max`
- `dynamic_adjustments` — condition-based budget reallocation rules
- `condensation_order` — priority order for over-budget condensation

---

## 13. File Reference

| File | Subsystems | Key Classes / Functions |
|------|-----------|------------------------|
| `src/trusted_data_agent/agent/engines/optimize_engine.py` | All | `OptimizeEngine` — full Planner/Executor pipeline (extracted from executor.py) |
| `src/trusted_data_agent/agent/engines/` | — | Engine package: `IdeateEngine`, `FocusEngine`, `CoordinateEngine`, `ConversationEngine`, `EngineRegistry` |
| `src/trusted_data_agent/agent/planner.py` | S1, S3 | `Planner`, `_validate_and_correct_plan()`, 9 rewrite methods, `_hydrate_plan_from_previous_turn()` |
| `src/trusted_data_agent/agent/executor.py` | S2, S6 | `PlanExecutor`, replan loop, `_distill_data_for_llm_context()`, engine dispatch |
| `src/trusted_data_agent/agent/phase_executor.py` | S4, S5 | `PhaseExecutor`, `CorrectionHandler`, `CorrectionStrategy` subclasses, `_recover_from_phase_failure()`, `_stream_parallel_phases()` |
| `src/trusted_data_agent/agent/orchestrators.py` | S3 | `execute_date_range_orchestrator()` (parallelised), `execute_column_iteration()`, `execute_hallucinated_loop()`, `_resolve_temporal_phrase_deterministic()` |
| `components/builtin/context_window/distiller.py` | S6 | `ExecutionContextDistiller` |
| `components/builtin/context_window/handler.py` | S6 | `ContextWindowHandler`, 5-pass assembly algorithm |
| `components/builtin/context_window/context_builder.py` | S6 | `ContextBuilder` — format bridge between orchestrator and LLM call sites |
| `src/trusted_data_agent/mcp_adapter/adapter.py` | S6 | `_distill_workflow_for_report()`, `_compute_column_statistics()`, `_select_representative_sample()` |
| `src/trusted_data_agent/agent/profile_prompt_resolver.py` | S4, S5 | `ProfilePromptResolver` |
| `src/trusted_data_agent/core/config.py` | All | `AppConfig` with all threshold constants |
| `src/trusted_data_agent/core/session_manager.py` | S3 | Turn validity filtering (`isValid` flag) |
| `src/trusted_data_agent/auth/consumption_enforcer.py` | Security | Consumption enforcement (fail-closed with user-visible warning event) |
| `rag_templates/schemas/planner-schema.json` | S1 | JSON schema defining plan structure |

---

## 14. Recent Improvements (engine-modularization branch)

### 14.1 Engine Modularization

`PlanExecutor.run()` was a 6,800-line monolith containing all four IFOC profile execution paths inline. Each path has been extracted into a dedicated engine class in `src/trusted_data_agent/agent/engines/`. The executor is now a shared infrastructure hub (~3,160 lines) that dispatches to engines. See [Engine Modularization Architecture](ENGINE_MODULARIZATION_ARCHITECTURE.md) for the full design.

### 14.2 Independent Phase Parallelization

`OptimizeEngine._stream_parallel_phases()` uses `asyncio.gather()` to execute independent plan phases concurrently. Phases are eligible for parallelization when the planner marks them without data dependencies on each other. For plans with N parallel data-gathering phases, wall-clock time is reduced from `N × phase_latency` to `1 × phase_latency`.

Events are collected per phase (not interleaved) using a collect-then-yield pattern, so the Live Status panel receives clean per-phase event sequences that render correctly with `renderHistoricalTrace()`. A stable post-sort on `turn_action_history` by `phase_num` ensures historical replay is deterministic even when asyncio scheduling interleaves `_log_system_event()` calls.

### 14.3 Date Range Orchestrator Parallelization

`execute_date_range_orchestrator()` in `orchestrators.py` now executes all per-day tool calls concurrently via `asyncio.gather()`. For a 30-day range, latency drops from `30 × tool_latency` to `1 × tool_latency` (plus result consolidation). Results are ordered by date after gathering.

### 14.4 SQL Consolidation Enabled by Default

`ENABLE_SQL_CONSOLIDATION_REWRITE` changed from `False` to `True`. The SQL consolidation rewrite pass (Pass 2 in the plan refinement pipeline) now fires automatically when the plan contains two or more consecutive phases using SQL tools, merging them into a single optimised query (CTE / JOIN). Individual profiles can opt out via their configuration.

### 14.5 LLM Call Timeout

Every LLM call is now wrapped with `asyncio.wait_for(timeout=LLM_CALL_TIMEOUT_SECONDS)`. If the provider hangs (network partition, service outage), the call raises `asyncio.TimeoutError` after the configured timeout rather than blocking indefinitely. The timeout is configurable per-instance (default: 120 seconds; set to 0 to disable).

### 14.6 Cycle Detection for Recursive Prompt Chains

Sub-executors are spawned up to `MAX_EXECUTION_DEPTH` levels deep. A `visited_prompts` set is now threaded through the execution tree: if prompt A calls prompt B which calls prompt A, the cycle is detected at the second invocation and the prompt is skipped with a warning rather than recursing until depth limit. This eliminates runaway token consumption from circular prompt graphs.

### 14.7 RAG Over-Retrieval Fix

`rag_retriever.py` previously fetched `k × 10` candidates from ChromaDB and discarded 90% after client-side filtering. The multiplier is now `k × 3`, reducing ChromaDB query + deserialization cost by ~67% while still providing sufficient candidates for filtering. No change to final result quality.

### 14.8 Plan Rewrite Diff Events

After each of the 9 plan rewrite passes, `planner.py` emits a `plan_rewrite_diff` event into `turn_action_history` capturing:
- Which pass fired
- The plan state before and after the pass
- A human-readable diff summary

This makes the historical trace fully auditable: the Live Status panel can show exactly which pass changed what, rather than only the final plan vs. the raw LLM output.

### 14.9 Consumption Enforcement Hardening

The consumption quota check in `executor.py` was previously fail-open: any exception silently bypassed all rate limits. The check is now fail-closed — enforcement failures surface a visible `consumption_warning` SSE event to the user and increment a bypass counter in the audit log. Genuine quota violations still block execution; the audit trail records all bypass incidents.

### 14.10 Genie Coordinator State Fixes

Five targeted fixes to `genie_coordinator.py` address module-level shared state issues that could cause session context leakage under concurrent parent sessions:

1. **Lock creation atomicity:** `dict.setdefault()` replaces TOCTOU check-then-set in `_get_slave_session_lock()`, preventing duplicate lock objects under concurrent dispatch.
2. **Memory leak:** `_cleanup_session_state()` is called in a `finally` block after each coordinator turn, removing `_event_callbacks` and `_provenance_chains` entries that previously grew indefinitely.
3. **`clear_session_cache()` scope:** Was modifying local variables instead of the module-level dicts. Now correctly removes only entries for the current parent session.
4. **`get_used_slave_sessions()` scope:** Previously returned the entire global cache (all coordinators, all users). Now filters to the current parent session only.
5. **Sequential primer mode:** Was silently executing only the first statement in the `statements` list. Now iterates all statements in order, with per-statement error handling.

### 14.11 Live Status Event Sequencing (Parallel Phases)

Three fixes ensure the Live Status panel renders parallel phase executions correctly in both live and historical (plan reload) modes:

1. **FASTPATH events positioned in phase** (`phase_executor.py`): FASTPATH `plan_optimization` events now include `phase_num` in their `details` dict, enabling the post-sort in `_stream_parallel_phases` to place them inside their correct phase container rather than after the last sequential phase.

2. **Phase Completed footer in historical replay** (`phase_executor.py`): The tactical LLM slow path's `phase_end` emission was the only one of 6 sites that called `_format_sse_with_depth()` without also calling `_log_system_event()`. The missing history write caused `renderHistoricalTrace()` to never see the `phase_end` event and therefore never render the "Phase N/M Completed" footer. Both calls are now made consistently.

3. **Defensive footer in `renderHistoricalTrace()`** (`ui.js`): Phase containers store `phase_num`, `total_phases`, and `depth` as `dataset` attributes at creation time. The two cleanup `while` loops (triggered when a same-depth phase starts, and at end-of-trace) now call `_addDefensivePhaseFooter()` to render a Completed footer if no explicit `phase_end` event was processed — ensuring correct display even if backend tracing regresses.

---

## Related Documents

- [Context Window Architecture](CONTEXT_WINDOW_ARCHITECTURE.md) — Detailed analysis of context generation, contribution, and optimization
- [Knowledge Retrieval Architecture](KNOWLEDGE_RETRIEVAL_ARCHITECTURE.md) — RAG pipeline, scoring, and retrieval
- [Engine Modularization Architecture](ENGINE_MODULARIZATION_ARCHITECTURE.md) — How execution paths are modularised into engine classes
- [Component Architecture](COMPONENT_ARCHITECTURE.md) — Extension system and component lifecycle
