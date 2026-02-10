# Fusion Optimizer Hardening Guide

## Overview

This skill provides deep, implementation-level knowledge of the Uderia Fusion Optimizer (`tool_enabled` profile) execution pipeline. Use it to analyze execution traces, diagnose plan quality issues, identify which safeguards fired, detect anti-patterns, and suggest improvements.

**When to use this skill:**
- Analyzing session execution traces from `tool_enabled` profiles
- Debugging plan quality issues (wrong tools, missing phases, hallucinated arguments)
- Understanding why a query produced unexpected results
- Identifying optimization opportunities in the Fusion Optimizer pipeline
- Adding new plan rewrite passes or correction strategies
- Tuning the `WORKFLOW_META_PLANNING_PROMPT` or `WORKFLOW_TACTICAL_PROMPT`

**Core files:**
- `src/trusted_data_agent/agent/executor.py` - Main orchestrator, proactive re-planning, context distillation
- `src/trusted_data_agent/agent/planner.py` - Strategic planning, 9 rewrite passes, plan normalization
- `src/trusted_data_agent/agent/phase_executor.py` - Tactical execution, fast-path, 3-tier error recovery
- `src/trusted_data_agent/agent/orchestrators.py` - Date range, column iteration, hallucinated loop orchestrators
- `src/trusted_data_agent/agent/profile_prompt_resolver.py` - Profile-aware prompt resolution

---

## Section 0: Core Design Principles

### Principle 1: Deterministic vs Non-Deterministic

**This is the most important design decision in the Fusion Optimizer.**

> If something can be handled deterministically, it MUST be written as code.
> If something cannot be described deterministically, prompt engineering is the way forward.
> When it makes sense, **blend both approaches** — deterministic detection with non-deterministic resolution.
> System prompts must NOT be convoluted.

### Principle 2: Context Window Hygiene — Never Convolute the Chat Object

> The chat object (session context sent to the LLM) must stay lean. Every byte added to it is paid on EVERY subsequent LLM call for the life of the session.

**Rule:** When adding new data to the session file (workflow_history, turn summaries), always ask: **"Does the LLM need this for planning?"**

- **YES** → Include it in the turn summary (it flows into `_distill_conversation_context()`)
- **NO** → Add it to the `ui_only_fields` strip list in `_distill_conversation_context()` (planner.py:~102)

**The strip list** (`ui_only_fields`) removes fields that are stored on disk for UI replay, session analysis, or debugging — but are never sent to the LLM. Current members include: `genie_events`, `slave_sessions`, `provider`, `model`, `status`, `system_events`, `session_input_tokens`, `session_output_tokens`, `final_summary_html`, `tts_payload`, `raw_llm_plan`, and others.

**Example:** `raw_llm_plan` captures the LLM's plan before rewrite passes — essential for session analysis but useless to the LLM planner. It is stripped from context and only exists on disk.

**Why this matters:**
- Multi-turn sessions accumulate workflow history. Bloated turns compound across the session.
- Token cost scales linearly with context size on every planning and tactical call.
- Irrelevant context dilutes LLM attention on what actually matters (previous results, tool schemas, user query).

**Checklist for new session fields:**
1. Does the LLM need it to plan the next turn? → Keep
2. Is it only for UI display or replay? → Strip (`ui_only_fields`)
3. Is it only for debugging or session analysis? → Strip (`ui_only_fields`)
4. Is it already represented elsewhere in context? → Strip (avoid duplication)

### The Three Strategies

| Strategy | Detection | Resolution | Token Cost | Reliability | When to Use |
|----------|-----------|------------|------------|-------------|-------------|
| **Purely Deterministic** | Code (regex, schema, structure) | Code (rewrite, inject, remove) | Zero | 100% | Structural deficiencies, missing wiring, hallucinated args |
| **Hybrid** | Code (detect the pattern) | LLM (generate the fix) | Low (targeted call) | High | Pattern is clear but fix requires semantic understanding |
| **Purely Non-Deterministic** | LLM (understand intent) | LLM (generate solution) | High (in system prompt) | Variable | Conceptual issues, wrong tool choice, bad SQL logic |

**Prefer deterministic.** When that's not enough, use a hybrid approach — deterministic detection keeps reliability high while the LLM handles only the part that requires understanding. Only fall back to pure prompt engineering when the problem itself can't be described as a pattern.

### Decision Framework

When encountering a plan quality issue or execution failure, apply this test:

| Question | Answer | Action |
|----------|--------|--------|
| Can the pattern be detected AND fixed with code alone? | Yes | **Purely deterministic** — plan rewrite pass |
| Can the pattern be detected with code, but the fix needs LLM? | Yes | **Hybrid** — detect in code, call LLM for targeted resolution |
| Is it a content quality issue (wrong SQL, bad report text)? | Yes | **Hybrid or non-deterministic** — prompt directive or RAG example |
| Does the error come from a tool schema mismatch? | Yes | **Purely deterministic** — add to validation (Pass 5) |
| Does the error come from conceptual misunderstanding? | Yes | **Non-deterministic** — correction strategy or prompt directive |

### Rationale

- **Deterministic passes are reliable**: They fire 100% of the time when the pattern matches. No token cost. No LLM variability.
- **Hybrid passes get the best of both worlds**: Deterministic detection ensures the fix triggers reliably; LLM resolution handles the semantic complexity. The LLM call is targeted (small prompt, specific task) rather than embedded in a system prompt.
- **Prompt directives are fragile**: Adding more rules to system prompts can cause regression on other query types. Each directive competes for LLM attention.
- **System prompt size matters**: Every token in the system prompt is sent on EVERY planning call. Keeping prompts clean reduces cost and improves focus.

### Examples

| Issue | Strategy | Fix |
|-------|----------|-----|
| TDA_CurrentDate result not wired to data tool | **Purely deterministic** — pattern: "TDA_CurrentDate + data tool without date arg" | Pass 0: Temporal Data Flow Wiring (code only) |
| Missing TDA_CurrentDate for temporal query | **Purely deterministic** — regex detects temporal phrases | Pre-gen: `_inject_temporal_context` (code only) |
| LLM puts prompt in `relevant_tools` | **Purely deterministic** — compare against known prompt names | Pass 5: Deterministic Validation (code only) |
| LLM generates inefficient sequential SQL | **Hybrid** — detect consecutive SQL phases (code), merge them (LLM) | Pass 1: SQL Consolidation (detect in code, fix via LLM) |
| TDA_LLMTask loop needs aggregation vs synthesis classification | **Hybrid** — detect TDA_LLMTask in loop (code), classify (LLM) | Pass 3: LLMTask Loop Classification (detect in code, classify via LLM) |
| LLM picks wrong tool for a query | **Non-deterministic** — requires semantic understanding | Prompt directive or RAG example |
| LLM generates bad SQL WHERE clause | **Non-deterministic** — requires domain knowledge | Self-correction strategy (Tier 1-3) |

---

## Section 1: Architecture Deep Dive

### Complete Execution Flow

```
User Query
    |
    v
[1] PlanExecutor.run() (executor.py)
    |--- Initialize session state, set profile, load tools/prompts context
    |--- Create Planner instance with RAG retriever
    |--- Create PhaseExecutor instance
    |
    v
[2] Planner.generate_and_refine_plan() (planner.py:1573)
    |
    |--- [2a] _generate_meta_plan() (planner.py:1625)
    |       |--- Load MCP prompt if active_prompt_name set
    |       |--- Retrieve knowledge documents (if KNOWLEDGE_RAG_ENABLED + profile opt-in)
    |       |--- Retrieve RAG planner examples (few-shot champion cases)
    |       |--- Build planning prompt with 14+ template variables
    |       |--- LLM call -> JSON plan array
    |       |--- Parse JSON (handle ```json blocks, direct objects, conversational)
    |       |--- _normalize_plan_syntax() - Template canonicalization
    |       |--- _inject_temporal_context() - Add TDA_CurrentDate for temporal queries
    |
    |--- [2b-2j] 9 Plan Rewrite Passes (in order):
    |       0. _rewrite_plan_for_temporal_data_flow()
    |       1. _rewrite_plan_for_sql_consolidation()
    |       2. _rewrite_plan_for_multi_loop_synthesis()
    |       3. _rewrite_plan_for_corellmtask_loops()
    |       4. _rewrite_plan_for_date_range_loops()
    |       5. _validate_and_correct_plan()
    |       6. _hydrate_plan_from_previous_turn()
    |       7. _rewrite_plan_for_empty_context_report()
    |       8. _ensure_final_report_phase()
    |
    v
[3] Proactive Re-Planning Check (executor.py:~3989)
    |--- If plan mixes executable_prompts with tools: trigger re-plan
    |--- max_replans = 1 (one re-plan attempt allowed)
    |--- Re-plan goes through ALL 8 passes again
    |
    v
[4] Phase Execution Loop (executor.py:~4522)
    |--- For each phase in meta_plan:
    |       |
    |       |--- If delegated prompt phase: _run_sub_prompt()
    |       |--- If loop phase: PhaseExecutor._execute_looping_phase()
    |       |       |--- Extract loop items from workflow_state
    |       |       |--- Fast-path candidate? (single non-complex tool)
    |       |       |   |--- Yes: Direct tool execution per item (skip LLM)
    |       |       |   |--- No: _execute_standard_phase() per item (with LLM)
    |       |--- If standard phase: PhaseExecutor._execute_standard_phase()
    |               |--- Fast-path? (all required args present + single tool)
    |               |   |--- Yes: Execute directly, skip tactical LLM
    |               |   |--- No: _get_tactical_plan() -> LLM decides tool+args
    |               |--- Execute tool via _execute_action_with_orchestrators()
    |               |--- On error: Self-correction loop (max 3 retries)
    |
    v
[5] Response Synthesis
    |--- Final report tool produces formatted output
    |--- Save to session (conversation.json, workflow.json)
    |--- Accumulate token counts
```

### The 9 Plan Rewrite Passes

Each pass runs sequentially after `_generate_meta_plan()` returns. They modify `self.executor.meta_plan` in-place.

#### Pass 0: Temporal Data Flow Wiring (planner.py:~697)

**Trigger:** `TDA_CurrentDate` phase exists in plan AND query matches temporal patterns AND a data-gathering phase has no date-related argument AND the tool's schema has a date parameter.

**Action:** Injects the temporal phrase (e.g., "past 5 days") as the date argument value in the data tool's phase. This creates the trigger for the Date Range Orchestrator at execution time.

**LLM call:** No - entirely deterministic.

**Example:**
```
Before: Phase 1: TDA_CurrentDate
        Phase 2: dba_resusageSummary({dimensions: ["LogDate"]})
After:  Phase 1: TDA_CurrentDate
        Phase 2: dba_resusageSummary({dimensions: ["LogDate"], date: "past 5 days"})
        → Date Range Orchestrator now detects "date" param and iterates per day
```

**Design principle:** This is a deterministic code fix (not prompt engineering) because the pattern "TDA_CurrentDate + data tool without date arg + temporal query" can be reliably detected via regex and schema inspection.

**Trace signature:** "System Correction" with `correction_type: "temporal_data_flow_wiring"`.

---

#### Pass 1: SQL Consolidation (planner.py:1056)

**Trigger:** `APP_CONFIG.ENABLE_SQL_CONSOLIDATION_REWRITE` is True AND plan has 2+ consecutive phases where `relevant_tools[0]` is in `APP_CONFIG.SQL_OPTIMIZATION_TOOLS`.

**Action:** Calls LLM with `SQL_CONSOLIDATION_PROMPT` to merge sequential SQL queries into a single optimized query (using CTEs, subqueries, or JOINs).

**LLM call:** Yes.

**Example:**
```
Before: Phase 1: base_readQuery("SELECT * FROM dbc.databases")
        Phase 2: base_readQuery("SELECT * FROM dbc.tables WHERE db = ...")
After:  Phase 1: base_readQuery("SELECT t.* FROM dbc.tables t JOIN dbc.databases d ON ...")
```

**Trace signature:** TDA_SystemLog "Optimizing SQL Plan"

---

#### Pass 2: Multi-Loop Synthesis Injection (planner.py:668)

**Trigger:** Plan has 2+ consecutive loop phases with the same `loop_over` source, followed by a `TDA_LLMTask` summary phase.

**Action:** Inserts an intermediate distillation phase (TDA_LLMTask) between the parallel loops and the final summary. Converts raw voluminous data into per-item summaries before final synthesis.

**LLM call:** No - structural rewrite only.

**Example:**
```
Before: Phase 2 (loop): Get columns for each table
        Phase 3 (loop): Get stats for each table
        Phase 4: TDA_LLMTask - Summarize everything
After:  Phase 2 (loop): Get columns for each table
        Phase 3 (loop): Get stats for each table
        Phase 4: TDA_LLMTask - Distill data per table (NEW)
        Phase 5: TDA_LLMTask - Final summary (uses distilled data)
```

**Trace signature:** "System Correction" with "data distillation step" in details.

---

#### Pass 3: TDA_LLMTask Loop Classification (planner.py:757)

**Trigger:** Phase has `type: "loop"` AND `relevant_tools: ["TDA_LLMTask"]`.

**Action:** Calls LLM with `TASK_CLASSIFICATION_PROMPT` to classify as "aggregation" (can batch into single call) or "synthesis" (must iterate per item). If aggregation: removes `type: loop` and `loop_over`, moves loop source to `source_data` argument.

**LLM call:** Yes - classification call.

**Trace signature:** "Analyzing Plan Efficiency" event.

---

#### Pass 4: Date Range Loop Fix (planner.py:855)

**Trigger:** Phase has `TDA_DateRange` in tools AND next phase references `result_of_phase_N` (date range output) but is NOT typed as a loop.

**Action:** Converts next phase to `type: "loop"` with `loop_over: "result_of_phase_N"` and rewrites the date argument to `{"source": "loop_item", "key": "date"}`.

**LLM call:** No.

**Trace signature:** "System Correction" with "correctly process each item in the date range".

---

#### Pass 5: Deterministic Plan Validation (planner.py:251)

**Trigger:** Always runs. Checks every phase for 4 correction types.

**Corrections:**

1. **Invalid prompt cleanup (L268):** Removes `executable_prompt` values that are `None`, `'None'`, `'null'`, `''`, or `'undefined'`.

2. **Prompt misclassified as tool (L276):** If `relevant_tools[0]` matches a known MCP prompt name, moves it to `executable_prompt` and deletes `relevant_tools`.

3. **Tool misclassified as prompt (L292):** If `executable_prompt` matches a known MCP tool name, moves it to `relevant_tools` and deletes `executable_prompt`.

4. **Hallucinated arguments (L302):** Compares phase arguments against tool's actual schema (using `ARGUMENT_SYNONYM_MAP`). Removes unknown arguments. If required args missing after cleanup, sets `_needs_refinement: True`.

**LLM call:** No - entirely deterministic.

**Trace signature:** "Plan Optimization" with type "workaround" and specific correction message.

---

#### Pass 6: Plan Hydration (planner.py:181)

**Trigger:** Plan exists AND `previous_turn_data` exists AND first phase is `type: "loop"` with `loop_over` starting with `"result_of_phase_"` where the referenced phase number >= the looping phase (forward reference that can't exist yet).

**Action:** Searches previous turn's `execution_trace` for last successful result. Injects it into `workflow_state["injected_previous_turn_data"]`. Rewrites `loop_over` to point to injected key.

**LLM call:** No - data injection only.

**Token savings:** 30-50% on multi-turn queries.

**Trace signature:** "Plan Optimization" with "PLAN HYDRATION: Injected data from the previous turn".

---

#### Pass 7: Empty Context Report Synthesis (planner.py:925)

**Trigger:** Phase has `relevant_tools: ["TDA_ContextReport"]` AND `arguments.answer_from_context` is empty or missing.

**Action:** If knowledge context was retrieved during planning, calls LLM to synthesize answer and injects it into `arguments.answer_from_context`. If no knowledge context, injects generic fallback message.

**LLM call:** Yes (when knowledge context available).

**Trace signature:** "Synthesizing Knowledge Answer" event.

---

#### Pass 8: Final Report Guarantee (planner.py:386)

**Trigger:** Plan exists AND is not conversational AND last phase lacks TDA_FinalReport/TDA_ComplexPromptReport AND plan is not a synthesis plan (no TDA_ContextReport). Skips at depth > 0 unless `force_final_summary`.

**Action:** Appends final phase with `relevant_tools: ["TDA_FinalReport"]` (or `"TDA_ComplexPromptReport"` for prompt library sources).

**LLM call:** No.

**Trace signature:** "System Correction" with "The agent's plan was missing a final reporting step."

---

### Pre-Generation Transforms (Inside `_generate_meta_plan`)

These happen BEFORE the 8 passes:

1. **Plan Syntax Normalization** (planner.py:566): Immediately after JSON parsing. Converts all LLM template variations to canonical format:
   - `{{loop_item.key}}` → `{"source": "loop_item", "key": "key"}`
   - `{loop_item['key']}` → `{"source": "loop_item", "key": "key"}`
   - `{result_of_phase_1["key"]}` → `{"source": "result_of_phase_1", "key": "key"}`
   - `{KeyName}` (uppercase) → resolved from loop_item if available

2. **Temporal Context Injection** (planner.py:607): Detects temporal patterns via 8 regex patterns. If temporal AND no `TDA_CurrentDate` in plan, injects it as Phase 1 and renumbers all subsequent phases.

   Patterns matched:
   ```
   past \d+ (hours?|days?|weeks?|months?)
   last \d+ (hours?|days?|weeks?|months?)
   (yesterday|today|recent|latest)
   in the (last|past)
   for the (past|last)
   \d+ (hours?|days?|weeks?|months?) ago
   this (week|month|year)
   current (week|month|year)
   ```

---

### Fast-Path vs Slow-Path Decision Tree

```
Phase received from meta-plan
    |
    v
Is it a loop phase?
    |--- Yes: Extract loop items
    |     |--- Single non-complex tool?
    |     |     (not TDA_LLMTask, TDA_Charting, TDA_FinalReport, TDA_ComplexPromptReport)
    |     |     |--- Yes: LOOP FAST-PATH (direct execution per item)
    |     |     |--- No: LOOP SLOW-PATH (call _execute_standard_phase per item)
    |--- No: Standard phase
          |
          v
    Extract tool_name from relevant_tools[0]
    Get tool's required arguments (via ARGUMENT_SYNONYM_MAP)
          |
          v
    Are ALL required args present with non-null values?
        |--- No --> SLOW PATH (tactical LLM decides)
        |--- Yes --> FAST PATH
                      |--- Log "FASTPATH initiated for '{tool_name}'"
                      |--- Build action = {tool_name, arguments: strategic_args}
                      |--- Execute directly (skip tactical LLM call)
                      |--- Saves ~3K tokens per skipped call
```

### Error Recovery Chain (3 Tiers)

```
Tool Error Detected
    |
    v
Check DEFINITIVE_TOOL_ERRORS
    |--- "Invalid query" --> DefinitiveToolError (abort, no retry)
    |--- "3523" (permissions) --> DefinitiveToolError (abort)
    |
    v
If attempt < max_retries - 1 (max 2 correction attempts within 3 retries):
    |
    v
CorrectionHandler.attempt_correction() (phase_executor.py:268)
    |--- Iterates strategies in order:
    |
    |--- [Tier 1] TableNotFoundStrategy (L125)
    |       Regex: r"Object '([\w\.]+)' does not exist"
    |       Prompt: TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR
    |       Directive: "Don't guess. Use tool to LIST available tables."
    |
    |--- [Tier 2] ColumnNotFoundStrategy (L160)
    |       Regex: r"Column '(\w+)' does not exist"
    |       Prompt: TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR
    |       Directive: "Don't guess. Use tool to DESCRIBE table columns."
    |
    |--- [Tier 3] GenericCorrectionStrategy (L191)
    |       Always matches (fallback)
    |       Special case: JSON parsing error for report tools
    |         --> Redirects to TDA_LLMTask for text sanitization
    |       Normal case: TACTICAL_SELF_CORRECTION_PROMPT
    |       Full tool def + error context
    |
    v
Correction result:
    |--- "FINAL_ANSWER: text" --> Stop retrying, use as result
    |--- {prompt_name, arguments} --> Execute sub-prompt for recovery
    |--- {tool_name, arguments} --> Retry with corrected tool call
    |--- {arguments} --> Merge into failed action, retry
    |--- None --> Abort ("Unable to find a correction")
```

---

## Section 2: Enterprise Safeguards Reference

### Safeguard 1: Proactive Re-Planning

**What:** Detects mixed plans containing both `executable_prompt` phases and significant tool phases. Forces a re-plan to produce a pure tool-only workflow.

**Location:** `executor.py:~3989-4011`

**Trigger conditions (ALL must be true):**
- `execution_depth == 0` (top-level only)
- Plan has at least one `executable_prompt` phase
- Plan has at least one phase with tools other than `TDA_LLMTask`
- Plan is NOT a single-phase prompt-only plan
- Non-granted prompts exist (not in `APP_CONFIG.GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING`)
- `replan_attempt < max_replans` (max 1)

**Re-plan context:** Deconstructs non-granted prompts, explains why they were removed, preserves granted prompts, forces tool-based alternatives.

**Known limitations:**
- Only 1 re-plan attempt. If second plan still mixes, it proceeds as-is.
- Granted prompts bypass entirely (configurable).

**Cross-references:** Re-planned version goes through all 9 rewrite passes again.

**Trace signature:** "Re-planning for Efficiency" event.

---

### Safeguard 2: Intelligent Error Correction

**What:** 3-tier Strategy Pattern selecting the most appropriate error recovery approach based on error type.

**Location:** `phase_executor.py:39-264` (strategies), `phase_executor.py:268-289` (handler)

**Trigger:** Tool returns `status: "error"` AND error is NOT definitive AND `attempt < max_retries - 1`.

| Tier | Strategy | Regex Pattern | Recovery Action |
|------|----------|--------------|-----------------|
| 1 | TableNotFoundStrategy (L125) | `Object '([\w\.]+)' does not exist` | List tables, don't guess |
| 2 | ColumnNotFoundStrategy (L160) | `Column '(\w+)' does not exist` | Describe columns, don't guess |
| 3 | GenericCorrectionStrategy (L191) | Always True (fallback) | LLM analysis + correction |

**Special case in Tier 3:** JSON parsing errors for report tools redirect to TDA_LLMTask for text sanitization.

**Known limitations:**
- Only 3 total retries. Complex cascading errors may not resolve.
- Tiers 1-2 depend on specific MCP server error format matching the regex.

**Trace signature:** "System Self-Correction" events.

---

### Safeguard 3: Autonomous Recovery

**What:** When a phase fails after 5 slow-path iterations, invokes LLM to generate an entirely new plan using `ERROR_RECOVERY_PROMPT`.

**Location:** `phase_executor.py:~1891-1978` (`_recover_from_phase_failure`)

**Trigger:** `phase_attempts > max_phase_attempts` (5) in the slow-path loop.

**Recovery process:**
1. Extract last error and failed tool from `turn_action_history`
2. Add failed tool to `globally_skipped_tools` set
3. Distill workflow state for context
4. Call LLM with `ERROR_RECOVERY_PROMPT`
5. Parse response as new plan
6. Replace `meta_plan` and reset `current_phase_index` to 0
7. Log "RECOVERY_REPLAN" action

**Known limitations:**
- Recovery plan does NOT go through the 9 rewrite passes (potential quality gap).
- `globally_skipped_tools` only prevents the immediate failed tool.

**Trace signature:** "Attempting LLM-based Recovery" followed by "Recovery Plan Generated".

---

### Safeguard 4: Deterministic Plan Validation

**What:** 4 deterministic corrections applied without LLM calls: null prompt cleanup, prompt-as-tool fix, tool-as-prompt fix, hallucinated argument removal.

**Location:** `planner.py:251-384` (`_validate_and_correct_plan`)

**Trigger:** Always runs on every phase of every plan.

**Details:** See Pass 5 in Section 1 above.

**Known limitations:**
- Correction 4 (hallucinated args) depends on `ARGUMENT_SYNONYM_MAP` completeness.
- `_needs_refinement` flag requires slow-path executor to handle proactive argument refinement.

**Cross-references:** Correction 4 can interact with Safeguard 2 (if required args removed, tool may fail and trigger error correction).

**Trace signature:** "Plan Optimization" with type "workaround".

---

### Safeguard 5: Hallucination Prevention

**What:** Detects when the planner hallucinates a loop over literal strings instead of a data source reference. Corrects via semantic analysis.

**Location:** `orchestrators.py:294-353` (`execute_hallucinated_loop`), triggered from `phase_executor.py:~1143-1162`

**Trigger:** Phase has `type: "loop"` AND `loop_over` is a Python list of strings (not a `result_of_phase_N` reference).

**Process:**
1. Check if items contain date keywords -> redirect to date range orchestrator
2. Otherwise: LLM call to determine which tool argument the strings represent
3. Loop over items with corrected argument mapping

**Known limitations:**
- Relies on LLM correctly identifying the argument name.
- Does not validate that string items are actually valid values for that argument.

**Trace signature:** "System Correction" with "Planner hallucinated a loop."

---

### Safeguard 6: Context Distillation

**What:** Replaces large result sets with metadata summaries (row count + column names) before sending to LLM.

**Location:** `executor.py:~754-781` (`_distill_data_for_llm_context`)

**Trigger:** Called before tactical LLM calls and error recovery prompts. Activates when a `results` list exceeds `APP_CONFIG.CONTEXT_DISTILLATION_MAX_ROWS` OR `APP_CONFIG.CONTEXT_DISTILLATION_MAX_CHARS`.

**Example:**
```
Before: {"status": "success", "results": [... 500 rows ...]}
After:  {"status": "success", "metadata": {"row_count": 500, "columns": ["col1", "col2"]},
         "comment": "Full data is too large for context. This is a summary."}
```

**Token savings:** ~99% for large result sets.

**Known limitations:**
- Only distills `results` lists of dicts. Other large structures pass through.
- Distilled metadata may lack enough information for correct LLM decisions.

**Trace signature:** Not directly logged. Look for metadata summaries in workflow_state.

---

## Section 3: Execution Trace Analysis Guide

### Reading Execution Traces

Session files at: `tda_sessions/{user_uuid}/{session_id}.json`

Key path: `session.last_turn_data.workflow_history[N].execution_trace[]`

Each entry:
```json
{
  "action": {
    "tool_name": "string",
    "arguments": {},
    "metadata": {
      "phase_number": 1,
      "execution_depth": 0,
      "timestamp": "ISO-8601"
    }
  },
  "result": {
    "status": "success|error|skipped|info",
    "metadata": {},
    "results": []
  }
}
```

### TDA_SystemLog Message Catalog

| Message | Meaning | Safeguard |
|---------|---------|-----------|
| `"Calling LLM for Planning"` | Strategic meta-plan LLM call (tokens in details) | - |
| `"Strategic Meta-Plan Generated"` | Plan generation + all 9 rewrites complete | - |
| `"Plan Optimization" + "FASTPATH initiated for '...'"` | Fast-path activated, skipping tactical LLM | - |
| `"Plan Optimization" + "FASTPATH Data Expansion"` | Column-level iteration fast-path | - |
| `"Plan Optimization" + "PLAN HYDRATION"` | Previous turn data injected | Pass 6 |
| `"Calling LLM for Tactical Action"` | Slow-path tactical LLM call | - |
| `"System Correction" + type "workaround"` | A safeguard/rewrite fired | Various |
| `"System Self-Correction"` | Error recovery attempt | Safeguard 2 |
| `"Attempting LLM-based Recovery"` | Autonomous recovery triggered | Safeguard 3 |
| `"Re-planning for Efficiency"` | Proactive re-planning | Safeguard 1 |
| `"System Orchestration" + "date_range"` | Date range orchestrator activated | Orchestrator |
| `"Optimizing SQL Plan"` | SQL consolidation rewrite | Pass 1 |
| `"Analyzing Plan Efficiency"` | TDA_LLMTask loop classification | Pass 3 |
| `"Synthesizing Knowledge Answer"` | Empty context report synthesis | Pass 7 |
| `"Temporal preprocessing injected TDA_CurrentDate"` | Missing temporal context auto-fixed | Pre-gen |
| `"System Correction" + "temporal_data_flow_wiring"` | TDA_CurrentDate result wired to data tool | Pass 0 |
| `"Conversational Response Identified"` | No tool execution needed | - |

### How to Identify Which Safeguards Fired

Search the execution trace for these patterns:

**Safeguard 1 (Proactive Re-Planning):**
```
Look for: "Re-planning for Efficiency" in step field
Followed by: A second "Strategic Meta-Plan Generated" event
```

**Safeguard 2 (Error Correction):**
```
Look for: "System Self-Correction" in step field
Details will contain: strategy used, corrected action
```

**Safeguard 3 (Autonomous Recovery):**
```
Look for: "Attempting LLM-based Recovery" in step field
Followed by: "Recovery Plan Generated" with new plan structure
History entry: {"action": "RECOVERY_REPLAN", "result": {"status": "success"}}
```

**Safeguard 4 (Deterministic Validation):**
```
Look for: "Plan Optimization" with type "workaround"
Details contain: correction_type (invalid_prompt, prompt_as_tool, tool_as_prompt, extraneous_args)
```

**Safeguard 5 (Hallucination Prevention):**
```
Look for: "System Correction" with "Planner hallucinated a loop"
Or: TDA_SystemOrchestration entries in execution_trace
```

**Safeguard 6 (Context Distillation):**
```
Not directly logged. Look for metadata summaries in workflow_state:
{"metadata": {"row_count": N, "columns": [...]}, "comment": "Full data is too large..."}
```

### Red Flags in Traces

1. **Multiple "System Self-Correction" events for same phase** -> Excessive self-correction overhead
2. **Same tool called 3+ times with same arguments** -> Stuck retry loop
3. **TDA_FinalReport in execution_trace but no data-gathering tools before it** -> Empty report
4. **No TDA_CurrentDate for temporal query** -> Missing temporal context
5. **"RECOVERY_REPLAN" action** -> Phase failed 5+ times, something is seriously wrong
6. **High token count in "Calling LLM for Planning" details** -> Bloated planning context
7. **Loop phases with 0 items** -> Loop source returned empty, possible upstream failure
8. **executable_prompt in trace at depth > 3** -> Approaching recursion limit

---

## Section 4: Plan Quality Checklist

### For Temporal Queries
(queries with "past N days", "yesterday", "today", "recent", "this week", etc.)

- [ ] Is `TDA_CurrentDate` present as Phase 1?
  - Either from LLM (in original plan) or from `_inject_temporal_context` preprocessing
- [ ] If multi-day range: Is `TDA_DateRange` used OR date range orchestrator activated?
- [ ] Do data-gathering phases receive the date context?
- [ ] Is there a risk of double TDA_CurrentDate calls (preprocessing + orchestrator)?

### For Data Queries
(queries with "list", "show", "get", "count", "find")

- [ ] Is the plan "gather-then-synthesize"? (data tools first, TDA_FinalReport last)
- [ ] Are sequential SQL phases consolidated? (check if SQL consolidation rewrite fired)
- [ ] Does each phase have a single clear goal?
- [ ] Are arguments properly passed via `result_of_phase_N`?
- [ ] Is context distillation active for large result sets?
- [ ] Is the List -> Filter -> Act pattern used when filtering is needed?

### For Loop Queries
(queries involving "all tables", "every column", "each database")

- [ ] Is `loop_over` using canonical format? (`"result_of_phase_N"` string reference)
- [ ] Are loop arguments canonical? (`{"source": "loop_item", "key": "ColumnName"}`)
- [ ] If 2+ loops share same source: is a distillation phase inserted? (Pass 2)
- [ ] Is TDA_LLMTask loop classified correctly? (aggregation vs synthesis, Pass 3)
- [ ] Are loop items NOT literal strings? (if so, hallucinated loop orchestrator should fire)
- [ ] For column-scoped tools: is the column expansion fast-path activated?

### For Knowledge Queries
(queries about concepts, syntax, best practices with knowledge repos enabled)

- [ ] Is TDA_ContextReport used instead of database tools?
- [ ] Does `answer_from_context` have content? (if empty, Pass 7 should synthesize)
- [ ] Is `_ensure_final_report_phase` correctly skipping? (synthesis plans should NOT get TDA_FinalReport)
- [ ] Were knowledge documents actually retrieved?

### For Multi-Turn Queries
(follow-up questions in existing session)

- [ ] Is plan hydration working? (check for "PLAN HYDRATION" event)
- [ ] Are redundant data fetches skipped?
- [ ] Does `workflow_history` contain valid previous turns? (`isValid` not `false`)
- [ ] Is previous turn summary correctly scrubbed of TDA_SystemLog messages?
- [ ] Does Turn N+1 plan correctly reference data from Turn N?

---

## Section 5: Common Anti-Patterns and Fixes

### Anti-Pattern 1: Sequential SQL Phases

**Symptom:** Plan has Phase 1: `base_readQuery(SQL_A)`, Phase 2: `base_readQuery(SQL_B)`, Phase 3: `base_readQuery(SQL_C)`.

**Root cause:** LLM generates step-by-step SQL instead of consolidated query.

**Fix:** Enable `APP_CONFIG.ENABLE_SQL_CONSOLIDATION_REWRITE = True` and ensure `SQL_OPTIMIZATION_TOOLS` contains the relevant tools.

**Trace indicator:** Multiple consecutive phases with SQL tools and no "Optimizing SQL Plan" event.

---

### Anti-Pattern 2: Missing Final Report

**Symptom:** Query completes but user sees raw JSON data instead of formatted report.

**Root cause:** LLM omits TDA_FinalReport, and `_ensure_final_report_phase` was incorrectly bypassed (e.g., `is_synthesis_plan` was True due to TDA_ContextReport presence elsewhere).

**Fix:** Check `_ensure_final_report_phase` logic. Verify TDA_ContextReport is only present when intended.

**Trace indicator:** No TDA_FinalReport in execution_trace AND no "System Correction" about missing report.

---

### Anti-Pattern 3: Prompt Misclassified as Tool

**Symptom:** Phase fails with "tool not found" because an MCP prompt was placed in `relevant_tools`.

**Root cause:** LLM doesn't distinguish between tools and prompts in plan generation.

**Fix:** Handled by Pass 5 Correction 2. If still occurring, check that `mcp_prompts` registry is populated at startup.

**Trace indicator:** "Plan Optimization" with "Planner misclassified a prompt as a tool."

---

### Anti-Pattern 4: Loop Over Literal Strings

**Symptom:** Phase has `loop_over: ["tableA", "tableB", "tableC"]` instead of `"result_of_phase_1"`.

**Root cause:** LLM hallucinates a hardcoded list instead of referencing a data source.

**Fix:** Handled by Safeguard 5. If orchestrator produces incorrect results, check the semantic analysis LLM call.

**Trace indicator:** "System Correction" with "Planner hallucinated a loop."

---

### Anti-Pattern 5: Missing Temporal Context

**Symptom:** Temporal query returns data for wrong dates or uses system defaults.

**Root cause:** LLM omits TDA_CurrentDate AND temporal preprocessing regex doesn't match.

**Fix:** Add missing temporal pattern to `_inject_temporal_context()` (planner.py:607-633). Current patterns:
```
past \d+ (hours?|days?|weeks?|months?)
last \d+ (hours?|days?|weeks?|months?)
(yesterday|today|recent|latest)
in the (last|past)
for the (past|last)
\d+ (hours?|days?|weeks?|months?) ago
this (week|month|year)
current (week|month|year)
```

**Trace indicator:** No TDA_CurrentDate in trace AND no "Temporal preprocessing injected" event.

---

### Anti-Pattern 6: Redundant Data Fetches in Multi-Turn

**Symptom:** Turn 2 re-fetches data already retrieved in Turn 1.

**Root cause:** Plan hydration didn't activate. It requires first phase to be a loop with forward reference (`loop_over: "result_of_phase_N"` where N >= current phase).

**Fix:** For other patterns, improve the strategic planner prompt to reuse previous turn data, or add custom hydration logic.

**Trace indicator:** Same tool with same arguments across turns, no "PLAN HYDRATION" event.

---

### Anti-Pattern 7: Excessive Self-Correction Overhead

**Symptom:** Turn uses 3x-10x expected tokens due to repeated self-correction loops.

**Root cause:** Tool schema validation fails repeatedly (e.g., TDA_FinalReport expects `Observation` objects but LLM returns strings). Each retry re-sends full context.

**Fix:** Improve tool schema documentation in MCP server. Add examples to tool argument descriptions. Consider context compression for retry attempts.

**Trace indicator:** Multiple "System Self-Correction" events for same phase. Check correction types - if all `SchemaValidation`, it's a code issue not a prompt issue.

---

### Anti-Pattern 8: Mixed Plan Not Re-Planned

**Symptom:** Plan has both `executable_prompt` and `relevant_tools` phases but proactive re-planning didn't fire.

**Root cause:** One bypass condition was met:
- `execution_depth > 0` (sub-process)
- Single-phase prompt plan
- All prompts are in `GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING`
- No "significant" tool phases (only TDA_LLMTask)

**Fix:** Check `APP_CONFIG.GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING`. Ensure non-essential prompts are NOT in this set.

**Trace indicator:** Mixed plan in `original_plan` but no "Re-planning for Efficiency" event.

---

### Anti-Pattern 9: Disconnected Temporal Context

**Symptom:** Temporal query ("past 5 days") returns data for the full month/default range instead of the requested period. TDA_CurrentDate is present in the trace but its result is never consumed by the data-gathering tool.

**Root cause:** The LLM generates a plan with TDA_CurrentDate (Phase 1) and a data tool (Phase 2) but doesn't wire the date result into Phase 2's arguments. The 5-layer temporal chain has a gap:
1. LLM directive → generates TDA_CurrentDate (works)
2. `_inject_temporal_context` → sees it's already there (works)
3. `_rewrite_plan_for_date_range_loops` → only checks for TDA_DateRange, not TDA_CurrentDate (gap)
4. Date Range Orchestrator → needs a "date" argument in the action to trigger, but Phase 2 has no date arg (gap)
5. Hallucinated Loop Orchestrator → not applicable (gap)

**Fix:** Pass 0 (`_rewrite_plan_for_temporal_data_flow`) now bridges this gap deterministically by injecting the temporal phrase as a date argument into data-gathering phases. This triggers the Date Range Orchestrator at execution time.

**Trace indicator (before fix):** TDA_CurrentDate in trace + data tool returning too many rows + NO "System Orchestration: date_range" event + NO "temporal_data_flow_wiring" event.

**Trace indicator (after fix):** "System Correction" with `correction_type: "temporal_data_flow_wiring"` followed by "System Orchestration: date_range" event.

**Design principle:** This is a deterministic fix (code-based rewrite pass) because the pattern can be reliably detected via schema inspection without LLM involvement. See Section 0.

---

## Section 6: Prompt Engineering Guide

### Key Variables in WORKFLOW_META_PLANNING_PROMPT

Assembled in `_generate_meta_plan()` (planner.py:~1880):

| Variable | Source | Purpose |
|----------|--------|---------|
| `{workflow_goal}` | `executor.workflow_goal_prompt` | The goal/query to plan for |
| `{original_user_input}` | `executor.original_user_input` | Raw user query (may differ for prompt executions) |
| `{explicit_parameters_section}` | `executor.prompt_arguments` | Explicit params for prompt execution |
| `{turn_action_history}` | `_create_summary_from_history()` | Previous turn summaries (scrubbed, valid only) |
| `{execution_depth}` | `executor.execution_depth` | 0 for top-level, 1+ for sub-prompts |
| `{active_prompt_context_section}` | Built if `active_prompt_name` set | "You are executing prompt X" |
| `{mcp_system_name}` | Database `global_parameters` table | Name of connected system |
| `{replan_instructions}` | Proactive re-planning context | Re-plan directives (empty on first) |
| `{constraints_section}` | `dependencies['STATE']['constraints_context']` | Tool/resource constraints |
| `{sql_consolidation_rule}` | `APP_CONFIG.SQL_OPTIMIZATION_PROMPTS/TOOLS` | SQL consolidation directive |
| `{reporting_tool_name}` | `"TDA_FinalReport"` or `"TDA_ComplexPromptReport"` | Which report tool to use |
| `{rag_few_shot_examples}` | RAG planner retrieval | Champion cases with adaptive guidance |
| `{knowledge_context}` | Knowledge repository retrieval | Domain knowledge documents |
| `{available_tools}` | `APP_STATE['tools_context']` | Full tool descriptions |
| `{available_prompts}` | `APP_STATE['prompts_context']` | Full prompt descriptions |

### Key Variables in WORKFLOW_TACTICAL_PROMPT

Assembled in `_get_next_tactical_action()` (phase_executor.py:~1743):

| Variable | Purpose |
|----------|---------|
| `{workflow_goal}` | Overall goal |
| `{current_phase_goal}` | This phase's specific goal |
| `{strategic_arguments_section}` | Pre-filled arguments from strategic plan |
| `{permitted_tools_with_details}` | Detailed schema of allowed tools for phase |
| `{permitted_prompts_with_details}` | Prompt details if `executable_prompt` set |
| `{last_attempt_info}` | Error info from previous failed attempt |
| `{turn_action_history}` | Distilled action history |
| `{all_collected_data}` | Distilled workflow state |
| `{loop_context_section}` | Current loop item context (if in loop) |
| `{context_enrichment_section}` | Inferred args from conversation history |

### How to Add New Directives to the Strategic Planner

1. The `WORKFLOW_META_PLANNING_PROMPT` is stored in the database (loaded via `prompt_loader.py`).
2. Modify via System Prompts editor (PE/Enterprise tier) or edit the source `.txt` file and re-encrypt.
3. The prompt uses numbered directives (1-10). Add new directive at appropriate priority level.
4. Test with `profile-perf` skill to measure impact on plan quality and token usage.
5. New directives should be specific, actionable, and include examples.

### How to Add New Correction Strategies

1. Create new class inheriting from `CorrectionStrategy` in `phase_executor.py`.
2. Implement `can_handle(error_data_str)` with regex pattern for the error.
3. Implement `generate_correction(failed_action, error_result)` with recovery logic.
4. Add to `CorrectionHandler.__init__()` strategies list.
   **ORDER MATTERS:** More specific strategies first, `GenericCorrectionStrategy` always last.
5. Optionally create a new prompt in database for the correction LLM call.

### How to Add New Plan Rewrite Passes

1. Create new method in `Planner` class in `planner.py`.
2. Pattern: check trigger conditions, modify `self.executor.meta_plan` in-place, yield SSE events.
3. Add call to `generate_and_refine_plan()` at correct position in the sequence.
4. If pass requires LLM call: make it `async def` and use `async for` in the caller.
5. Log changes with "Plan Optimization" or "System Correction" events for trace visibility.

---

## Section 7: Interactive Analysis Workflow

When analyzing a Fusion Optimizer execution, follow these 6 steps:

### Step 1: Classify the Query

| Type | Indicators | Expected Tools |
|------|-----------|----------------|
| **Temporal** | "past X hours/days", "yesterday", "recent" | TDA_CurrentDate + data tools |
| **Analytical** | "summarize", "analyze", "report on" | Data gathering + TDA_FinalReport |
| **Procedural** | "list", "show", "get", "count" | Direct data tools + TDA_FinalReport |
| **Knowledge** | References docs/concepts, knowledge repos enabled | TDA_ContextReport |
| **Multi-step** | Complex request, multiple entities | 3+ phases with loops |
| **Conversational** | Greetings, thanks | Conversational plan (no tools) |

### Step 2: Predict Expected Plan

Based on query type:
- Expected number of phases
- Expected tools in each phase
- Expected loop structures
- Expected safeguards that should fire
- Expected fast-path vs slow-path per phase

### Step 3: Extract Actual Execution Trace

From session file, extract:
```
1. raw_llm_plan (workflow_history[N].raw_llm_plan)  ← LLM's actual output before any preprocessing/rewrites
2. original_plan (workflow_history[N].original_plan) ← Plan after all 9 rewrite passes (what was executed)
3. execution_trace (workflow_history[N].execution_trace)
4. Token counts (turn_input_tokens, turn_output_tokens)
5. tools_used list
6. duration_ms
```

**Comparing raw_llm_plan vs original_plan reveals exactly what the system corrected:**
- Phase added? → Temporal injection (`_inject_temporal_context`)
- Argument added? → Pass 0 (temporal data flow wiring) or Pass 5 (validation)
- Phases merged? → Pass 1 (SQL consolidation)
- Loop restructured? → Pass 2/3 (multi-loop synthesis, LLMTask classification)

### Step 4: Compare Expected vs Actual

For each phase:
- Was the correct tool selected?
- Did fast-path activate when it should have?
- Did any safeguards fire? Were they appropriate?
- Were there self-correction attempts? How many and what type?
- Was context distillation applied to large results?
- Were temporal patterns correctly handled?

### Step 5: Identify Safeguards That Fired (or Should Have)

Scan for all "System Correction", "Plan Optimization", and "workaround" events. Map each to corresponding safeguard using the catalog in Section 3.

Check for safeguards that SHOULD have fired but DIDN'T:
- Missing temporal context with no injection event
- Hallucinated arguments that passed validation
- Mixed plans that were not re-planned
- Large results that were not distilled

### Step 6: Propose Improvements

Recommend:
- **Prompt changes:** If plan structure is consistently wrong
- **Code changes:** If self-correction overhead is high
- **Configuration changes:** If SQL consolidation or temporal preprocessing needs adjustment
- **RAG changes:** If champion cases would improve planning for this query pattern
- **New rewrite passes:** If a recurring anti-pattern is not caught by existing passes
- **New correction strategies:** If a specific error type has no targeted recovery

### Worked Example

```
Query: "What is the system utilization for the past 5 days?"
Query type: Temporal + Analytical

EXPECTED PLAN:
  Phase 1: TDA_CurrentDate (temporal context)
  Phase 2: Data tool with date argument wired (looped for 5 days)
  Phase 3: TDA_FinalReport

CASE A — WITHOUT Pass 0 (the bug):

  LLM generates:
    Phase 1: TDA_CurrentDate
    Phase 2: dba_resusageSummary({dimensions: ["LogDate"]})  ← NO date arg!
    Phase 3: TDA_FinalReport

  ACTUAL TRACE:
    [1] TDA_CurrentDate -> "2026-02-05"
    [2] dba_resusageSummary({dimensions: ["LogDate"]}) -> 25 rows (FULL MONTH!)
    [3] TDA_FinalReport -> report covers all dates, not just past 5 days

  WHY DATE RANGE ORCHESTRATOR DIDN'T FIRE:
    _is_date_query_candidate() checks action argument NAMES for "date".
    Phase 2 args = {dimensions: ["LogDate"]} — "dimensions" doesn't contain "date".
    → Returns (False, None, False) → orchestrator never evaluated.

  ASSESSMENT:
    Plan quality: POOR — temporal context established but never consumed.
    Anti-Pattern 9: Disconnected Temporal Context

CASE B — WITH Pass 0 (the fix):

  LLM generates same plan, then Pass 0 fires:
    Phase 1: TDA_CurrentDate
    Phase 2: dba_resusageSummary({dimensions: ["LogDate"], date: "past 5 days"})  ← INJECTED
    Phase 3: TDA_FinalReport

  ACTUAL TRACE:
    [1] TDA_SystemLog: "System Correction" (temporal_data_flow_wiring)
        --> Pass 0 wired "past 5 days" into Phase 2 date argument
    [2] TDA_CurrentDate -> "2026-02-10"
    [3] TDA_SystemLog: "System Orchestration: date_range"
        --> _is_date_query_candidate now finds "date" param → orchestrator activates
    [4] dba_resusageSummary(date="2026-02-05") -> 10 rows
    [5] dba_resusageSummary(date="2026-02-06") -> 8 rows
    [6] dba_resusageSummary(date="2026-02-07") -> 12 rows
    [7] dba_resusageSummary(date="2026-02-08") -> 9 rows
    [8] dba_resusageSummary(date="2026-02-09") -> 11 rows
    [9] TDA_FinalReport -> report covers exactly past 5 days

  ASSESSMENT:
    Plan quality: GOOD (temporal context wired correctly)
    Safeguards fired: Pass 0 (temporal data flow), Date Range Orchestrator
    Fast-path: Activated for TDA_CurrentDate and TDA_FinalReport
    Self-corrections: 0
```

---

## Quick Reference: Key File Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| Main orchestrator | `executor.py` | proactive replan ~3989, phase loop ~4522, distillation ~754 |
| Strategic planner | `planner.py` | meta-plan L1625, rewrites L1573-1612, validation L251 |
| Plan normalization | `planner.py` | L566 |
| Temporal injection | `planner.py` | L607 |
| Temporal data flow wiring | `planner.py` | ~L697 |
| SQL consolidation | `planner.py` | L1056 |
| Multi-loop synthesis | `planner.py` | L668 |
| LLMTask classification | `planner.py` | L757 |
| Date range fix | `planner.py` | L855 |
| Empty context report | `planner.py` | L925 |
| Plan hydration | `planner.py` | L181 |
| Final report guarantee | `planner.py` | L386 |
| Error strategies | `phase_executor.py` | L39-264 |
| Fast-path | `phase_executor.py` | ~L847 |
| Slow-path tactical | `phase_executor.py` | ~L986 |
| Tool execution + retries | `phase_executor.py` | ~L1338 |
| Autonomous recovery | `phase_executor.py` | ~L1891 |
| Date range orchestrator | `orchestrators.py` | L23-211 |
| Column iteration | `orchestrators.py` | L213-292 |
| Hallucinated loop | `orchestrators.py` | L294-353 |

---

## Changelog

**v1.2.0 (2026-02-10)**
- Added **Principle 2: Context Window Hygiene** to Section 0 — never convolute the chat object; new session fields must be checked against the `ui_only_fields` strip list
- Added `raw_llm_plan` field to session workflow history — captures LLM's actual output before any preprocessing or rewrite passes (stripped from LLM context via `ui_only_fields`)
- Updated trace analysis guide (Step 3) to document `raw_llm_plan` vs `original_plan` comparison for identifying system corrections

**v1.1.0 (2026-02-10)**
- Added **Section 0: Core Design Principle** — deterministic vs non-deterministic decision framework
- Added **Pass 0: Temporal Data Flow Wiring** (`_rewrite_plan_for_temporal_data_flow`) — bridges the gap between TDA_CurrentDate and data-gathering tools
- Added **Anti-Pattern 9: Disconnected Temporal Context** — documents the temporal data flow gap and its fix
- Updated worked example to show before/after comparison of the temporal fix
- Updated pass count from 8 to 9 throughout
- Added `_extract_temporal_phrase()` helper documentation

**v1.0.0 (2026-02-10)**
- Initial skill creation
- Complete architecture deep dive with execution flow diagram
- All 8 plan rewrite passes documented with trigger conditions and examples
- Fast-path vs slow-path decision tree
- 3-tier error recovery chain with strategy pattern details
- 6 enterprise safeguards reference with file locations, triggers, limitations
- Execution trace analysis guide with TDA_SystemLog message catalog
- Plan quality checklists for 5 query types
- 8 common anti-patterns with fixes and trace indicators
- Prompt engineering guide for key system prompts
- Interactive 6-step analysis workflow with worked example
- Quick reference file location table
