# Context Window Architecture: Comprehensive Analysis

## Overview

This document provides a detailed analysis of how the Uderia platform manages session context windows, including generation, contribution, consumption, storage, and optimization opportunities.

---

## 1. Context Window Generation

### 1.1 System Prompt Construction

**File:** `src/trusted_data_agent/llm/handler.py` (lines 358-507)
**Function:** `_get_full_system_prompt()`

The system prompt is dynamically assembled from multiple sources:

| Component | Source | Token Estimate |
|-----------|--------|----------------|
| Base system prompt | `PROVIDER_SYSTEM_PROMPTS` or DB override | ~500-1,000 |
| Tools context | MCP adapter discovery | ~2,000-4,000 |
| Prompts context | MCP prompts list | ~500-1,000 |
| Charting instructions | Config flag | ~200 (if enabled) |
| MCP system name | Database config | ~50 |

**Generation Flow:**
```
1. Load base prompt (provider-specific or user override)
2. Fetch tools from MCP adapter
3. Format tools (full descriptions OR names-only based on full_context_sent)
4. Fetch available prompts from MCP
5. Inject optional sections (charting, custom instructions)
6. Substitute placeholders: {tools_context}, {prompts_context}, etc.
```

### 1.2 Conversation History Assembly

**File:** `src/trusted_data_agent/core/session_manager.py` (lines 1038-1134)
**Function:** `add_message_to_histories()`

Each message added to context includes:
```python
{
    "role": "user" | "assistant",
    "content": "plain text content",
    "turn_number": int,
    "isValid": bool
}
```

### 1.3 RAG Context Injection

**File:** `src/trusted_data_agent/agent/planner.py` (lines 2230-2586)

Champion cases are retrieved and formatted:
```
1. Query ChromaDB for similar patterns
2. Filter by efficiency score and user feedback
3. Format as few-shot examples
4. Inject with adaptive header (instruct LLM to adapt, not copy)
```

### 1.4 Plan Hydration Context

**File:** `src/trusted_data_agent/agent/planner.py` (lines 182-250)

Previous turn results injected into workflow state:
```
1. Extract results from previous turn's execution trace
2. Store metadata summaries (not full data)
3. Modify meta-plan loop source to reference injected data
```

---

## 2. Context Contributors

### 2.1 Primary Contributors

| Contributor | What It Adds | When | Tokens |
|-------------|--------------|------|--------|
| **MCP Adapter** | Tool schemas, descriptions, arguments | Every LLM call | 2,000-4,000 |
| **Prompt Loader** | System prompts from DB | Every LLM call | 500-1,000 |
| **Session Manager** | Conversation history (`chat_object`) | Every LLM call | Variable (grows) |
| **RAG Retriever** | Champion cases, knowledge chunks | Strategic planning | 500-1,500 |
| **Planner** | Turn summaries, workflow history | Multi-turn queries | 500-2,000 |
| **Phase Executor** | Previous phase results | Within-turn phases | 200-1,000 |

### 2.2 Secondary Contributors

| Contributor | What It Adds | When | Tokens |
|-------------|--------------|------|--------|
| **Config Manager** | Custom instructions, MCP system name | Session init | 50-200 |
| **Profile Resolver** | Profile-specific prompt overrides | Profile switch | 200-500 |
| **Cost Manager** | Token tracking metadata | Logging only | 0 (metadata) |

### 2.3 Contributor Data Flow

```
                    ┌─────────────────┐
                    │   MCP Adapter   │
                    │  (Tool Schemas) │
                    └────────┬────────┘
                             │
┌─────────────────┐          │          ┌─────────────────┐
│  Prompt Loader  │          │          │  RAG Retriever  │
│ (System Prompts)│          │          │(Champion Cases) │
└────────┬────────┘          │          └────────┬────────┘
         │                   │                   │
         │                   ▼                   │
         │         ┌─────────────────┐           │
         └────────►│  LLM Handler    │◄──────────┘
                   │ (Context Assembly)│
                   └────────┬────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Session Manager │ │    Planner      │ │ Phase Executor  │
│  (Chat History) │ │(Turn Summaries) │ │ (Phase Results) │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

---

## 3. Context Consumers

### 3.1 Primary Consumers

| Consumer | What It Consumes | Purpose |
|----------|------------------|---------|
| **LLM Providers** | Full assembled context | Generate responses |
| **Strategic Planner** | System prompt + RAG + history | Create meta-plan |
| **Tactical Planner** | Phase goal + tools + history | Select tool per phase |
| **Phase Executor** | Tactical plan + previous results | Execute tool calls |
| **Response Synthesizer** | All phase results | Generate final answer |

### 3.2 Consumer Context Requirements

| Consumer | Required Context | Optional Context |
|----------|------------------|------------------|
| **Google Gemini** | ChatSession history (auto-managed) | System prompt (concatenated) |
| **Anthropic Claude** | messages array + system param | - |
| **OpenAI/Azure** | messages array (system at index 0) | - |
| **Strategic Planner** | tools, history, RAG cases | Turn summaries |
| **Tactical Planner** | phase goal, relevant tools, phase results | Full history |

### 3.3 Consumer-Specific Formatting

**File:** `src/trusted_data_agent/llm/handler.py` (lines 740-887)

```
Google:     ChatSession.send_message_async(prompt)
            └── History managed internally by ChatSession object

Anthropic:  messages.create(system=X, messages=[...])
            └── System prompt separate, messages as array

OpenAI:     chat.completions.create(messages=[{role:"system",...}, ...])
            └── System prompt as first message in array

Bedrock:    invoke_model(body={...})
            └── Provider-specific formatting (Anthropic, Titan, etc.)
```

---

## 4. Context Storage & Maintenance

### 4.1 Storage Locations

| Data | Location | Format | Lifecycle |
|------|----------|--------|-----------|
| **Session Data** | `tda_sessions/{user_uuid}/{session_id}.json` | JSON | Per-session |
| **Chat Object** | `session_data['chat_object']` | Array of messages | Grows per turn |
| **Session History** | `session_data['session_history']` | Array (HTML) | Grows per turn |
| **Workflow History** | `session_data['last_turn_data']['workflow_history']` | Array of turns | Grows per turn |
| **RAG Collections** | ChromaDB (`chroma_db/`) | Vector embeddings | Persistent |
| **System Prompts** | `tda_auth.db` (prompts table) | Encrypted text | Persistent |

### 4.2 Session File Structure

```json
{
  "session_id": "uuid",
  "user_uuid": "uuid",
  "created_at": "ISO timestamp",
  "last_updated": "ISO timestamp",

  "provider": "Anthropic",
  "model": "claude-opus",
  "profile_tag": "@OPTIMIZER",

  "chat_object": [
    {"role": "user", "content": "...", "turn_number": 1, "isValid": true},
    {"role": "assistant", "content": "...", "turn_number": 1, "isValid": true}
  ],

  "session_history": [
    {"role": "user", "content": "<html>...</html>", "turn_number": 1, "isValid": true},
    {"role": "assistant", "content": "<html>...</html>", "turn_number": 1, "isValid": true}
  ],

  "last_turn_data": {
    "workflow_history": [
      {
        "turn": 1,
        "user_query": "...",
        "original_plan": {...},
        "execution_trace": [...],
        "final_summary_text": "...",
        "turn_input_tokens": 8000,
        "turn_output_tokens": 500,
        "isValid": true
      }
    ]
  },

  "input_tokens": 15000,
  "output_tokens": 2000,
  "models_used": ["Anthropic/claude-opus"],
  "profile_tags_used": ["@OPTIMIZER"],
  "full_context_sent": true
}
```

### 4.3 Maintenance Operations

| Operation | Function | File | Lines |
|-----------|----------|------|-------|
| **Add message** | `add_message_to_histories()` | session_manager.py | 1038-1134 |
| **Update tokens** | `update_token_count()` | session_manager.py | 1174-1210 |
| **Update turn data** | `update_last_turn_data()` | session_manager.py | 1268-1395 |
| **Toggle validity** | `toggle_turn_validity()` | session_manager.py | 1468-1532 |
| **Purge memory** | `purge_session_memory()` | session_manager.py | 1398-1465 |
| **Condense history** | `_condense_and_clean_history()` | handler.py | 253-355 |

### 4.4 Context Growth Pattern

```
Turn 1:  System(3K) + Tools(3K) + Query(100) = ~6K input tokens
Turn 2:  System(3K) + Tools(1K condensed) + History(1K) + Query(100) = ~5K
Turn 3:  System(3K) + Tools(1K) + History(2K) + Query(100) = ~6K
Turn 4:  System(3K) + Tools(1K) + History(3K) + Query(100) = ~7K
...
Turn N:  Linear growth in history portion
```

---

## 5. Current Optimization Mechanisms

### 5.1 Implemented Optimizations

| Optimization | Mechanism | Savings | File:Lines |
|--------------|-----------|---------|------------|
| **Tool condensation** | Names-only after first turn | 60-70% of tool context | handler.py:423-437 |
| **History condensation** | Remove duplicates, clean capabilities | 10-20% of history | handler.py:253-355 |
| **Context distillation** | Summarize large tool outputs (metadata-only) | 99%+ of large results | executor.py:975-1015 |
| **Analytical distillation L1** | Column statistics + stratified samples per result set | 80-90% of large results | adapter.py:25-320 |
| **Analytical distillation L2** | Aggressive stratified reduction on total budget | 95%+ when budget exceeded | adapter.py:293-320 |
| **Document truncation** | Per-file + total char limits on uploads | Prevents unbounded doc context | executor.py:41-100 |
| **Plan hydration** | Inject previous results, skip re-fetch | 1-2 tool calls saved | planner.py:182-250 |
| **Turn validity toggle** | Exclude invalid turns from context | Variable | session_manager.py:1468-1532 |
| **Memory purge** | Reset chat_object, keep audit trail | 100% of history | session_manager.py:1398-1465 |

### 5.2 Optimization Trigger Conditions

| Optimization | Trigger |
|--------------|---------|
| Tool condensation | `full_context_sent == True` (after turn 1) |
| History condensation | `CONDENSE_SYSTEMPROMPT_HISTORY` config flag |
| Context distillation | Result > `CONTEXT_DISTILLATION_MAX_ROWS` (500) rows OR > `CONTEXT_DISTILLATION_MAX_CHARS` (10,000) chars |
| Analytical distillation L1 | Per-result > `REPORT_DISTILLATION_MAX_ROWS` (100) rows OR > `REPORT_DISTILLATION_MAX_CHARS` (50,000) chars |
| Analytical distillation L2 | Total distilled JSON > `REPORT_DISTILLATION_TOTAL_BUDGET` (200,000) chars |
| Document truncation | Per-file > `DOCUMENT_PER_FILE_MAX_CHARS` (20,000) chars or total > `DOCUMENT_CONTEXT_MAX_CHARS` (50,000) chars |
| Plan hydration | Previous turn has reusable data for current phase |
| Turn validity | User toggles turn via UI |
| Memory purge | User clicks "Clear Memory" |

### 5.3 Analytical Distillation (Two-Level)

**File:** `src/trusted_data_agent/mcp_adapter/adapter.py` (lines 25-320)

Analytical distillation operates separately from context distillation (Section 5.1). While context distillation replaces large results with **metadata-only** summaries during tactical execution, analytical distillation computes **column statistics on the full dataset** and selects **stratified representative samples** for the final report generation phase. This gives the report LLM precise quantitative data (min/max/mean/percentiles/distributions) without requiring the full dataset in context.

**Core Components:**

| Function | Purpose |
|----------|---------|
| `_compute_column_statistics()` | Per-column stats on FULL data: numeric (min/max/mean/median/P25/P75/stddev/sum), temporal (date range, top-10), categorical (distinct count, top-10 with %) |
| `_select_representative_sample()` | Stratified sampling: first K + evenly spaced interior + last K (replaces naive first-N) |
| `_distill_value_for_report()` | Orchestrates: compute stats → select sample → annotate metadata |

**Column Type Detection:**
- **Numeric**: `float()` conversion on first 50 values; >80% success → numeric stats
- **Temporal**: Column name heuristic (contains "date", "time", "timestamp", "logdate", etc.)
- **Categorical**: Everything else → value distributions with top-10

**Level 1 — Per-Result-Set Analytical Distillation:**
- **Function:** `_distill_workflow_for_report()` (line 25)
- **Helper:** `_distill_value_for_report()` (line 233) — recursively processes nested data structures
- **Trigger:** Each result set checked against `APP_CONFIG.REPORT_DISTILLATION_MAX_ROWS` (default 100) and `APP_CONFIG.REPORT_DISTILLATION_MAX_CHARS` (default 50,000)
- **Action:** Computes column_statistics on full data, selects stratified sample rows, annotates metadata

**Level 2 — Total Budget Enforcement:**
- **Trigger:** Total distilled JSON exceeds `APP_CONFIG.REPORT_DISTILLATION_TOTAL_BUDGET` (default 200,000 chars)
- **Function:** `_aggressive_distill()` (line 293)
- **Helper:** `_reduce_samples()` (line 303) — reduces sample count with stratified selection
- **Action:** Reduces to `APP_CONFIG.REPORT_DISTILLATION_AGGRESSIVE_ROWS` (default 25) rows; **column_statistics are preserved** (computed on full data during L1)

**Example Output (heatmap data, 166 rows → 100 stratified samples):**
```json
{
  "results": ["... 100 rows covering full date range (stratified) ..."],
  "metadata": {
    "total_row_count": 166,
    "sample_rows_included": 100,
    "sampling_method": "stratified",
    "columns": ["LogDate", "hourOfDay", "Request Count", "CPU Seconds"],
    "column_statistics": {
      "Request Count": {"type": "numeric", "min": 0, "max": 5234, "mean": 1847, "p75": 2891},
      "LogDate": {"type": "temporal", "range": {"min": "2026-02-07", "max": "2026-02-16"}, "distinct_count": 10},
      "hourOfDay": {"type": "numeric", "min": 0, "max": 23, "mean": 11.5}
    }
  }
}
```

**LLM Prompt Integration:**
Both TDA_FinalReport and TDA_ComplexPromptReport prompts include a `STATISTICAL DATA USAGE` guideline instructing the LLM to use `column_statistics` for precise quantitative claims (covering the full dataset) rather than estimating from sample rows.

**Comparison with Context Distillation:**

| Aspect | Context Distillation (executor) | Analytical Distillation (adapter) |
|--------|--------------------------------|----------------------------------|
| **When** | During tactical phase execution | Before report generation |
| **Output** | Metadata-only (0 rows) | Column statistics + stratified samples |
| **Purpose** | Minimize context for tool selection | Provide analytical data for reports |
| **Statistics** | None (row count + column names) | Full per-column (min/max/mean/percentiles/distributions) |
| **Sampling** | N/A | Stratified (first + evenly spaced + last) |
| **Thresholds** | 500 rows / 10K chars | L1: 100 rows / 50K chars; L2: 200K total |
| **Token overhead** | Minimal | ~200-500 tokens per distilled result set |

### 5.4 Document Context Processing

**File:** `src/trusted_data_agent/agent/executor.py` (lines 41-100)
**Function:** `load_document_context()`

Uploaded document attachments (PDFs, text files) are loaded and truncated before injection into LLM context. This is a module-level function shared by both the PlanExecutor and genie execution paths.

**Processing:**
```
1. Load extracted text from session attachment files
2. Per-file truncation: Trim to APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS (default 20,000)
3. Append "[Document truncated...]" suffix to trimmed files
4. Format as context block: "--- UPLOADED DOCUMENTS ---\n{content}"
5. Prepend to user query before sending to LLM
```

**Configuration:**
- Per-file limit: `APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS` (default 20,000 chars)
- Total limit: `APP_CONFIG.DOCUMENT_CONTEXT_MAX_CHARS` (default 50,000 chars)

All values are admin-configurable via Administration → App Config → System Operations → Document Context.

---

## 6. Areas for Improvement / Optimization

### 6.1 Dynamic Context Adjustment Based on RAG

**Current State:** Context size is static regardless of RAG retrieval
**Opportunity:** Reduce tool descriptions when high-confidence champion case is found

```python
# Proposed logic
if champion_case and champion_case.confidence > 0.85:
    tools_context = condensed_tools  # Names only
    planning_instructions = "Adapt this pattern: {champion_case}"
else:
    tools_context = full_tool_descriptions
    planning_instructions = full_planning_guide
```

**Estimated Savings:** 30-50% input tokens when champion case is highly relevant

---

### 6.2 Sliding Window for Long Conversations

**Current State:** Full `chat_object` sent every turn (linear growth)
**Opportunity:** Implement sliding window with summarization

```python
# Proposed logic
MAX_HISTORY_TOKENS = 4000

if estimate_tokens(chat_object) > MAX_HISTORY_TOKENS:
    # Keep recent N turns verbatim
    recent_turns = chat_object[-6:]  # Last 3 exchanges

    # Summarize older turns
    older_summary = llm_summarize(chat_object[:-6])

    # Compose: [summary] + [recent turns]
    context_history = [{"role": "system", "content": older_summary}] + recent_turns
```

**Estimated Savings:** Caps history at ~4K tokens regardless of conversation length

---

### 6.3 Tool Schema Caching Per Profile

**Current State:** Tool schemas fetched and formatted every LLM call
**Opportunity:** Cache formatted tool context per profile

```python
# Proposed cache structure
tool_context_cache = {
    "profile_id": {
        "full": "formatted full tool descriptions",
        "condensed": "formatted names-only list",
        "hash": "schema_hash_for_invalidation"
    }
}
```

**Estimated Savings:** Reduces CPU overhead, enables smarter caching strategies

---

### 6.4 Semantic History Compression

**Current State:** History stored as verbatim text
**Opportunity:** Compress semantically similar exchanges

```python
# Example: Multiple similar queries
Turn 1: "Show products under $50" → [results]
Turn 2: "Show products under $30" → [results]
Turn 3: "Show products under $20" → [results]

# Compressed representation:
"User performed 3 product price queries (thresholds: $50, $30, $20).
 Results: 45, 28, 12 products respectively."
```

**Estimated Savings:** 50-80% for repetitive query patterns

---

### 6.5 Lazy Loading of Context Components

**Current State:** All context components loaded upfront
**Opportunity:** Load only what's needed for current operation

| Operation | Required Context | Can Skip |
|-----------|------------------|----------|
| Simple chat | System prompt, history | Full tool schemas |
| Tool execution | Tool schemas | RAG cases |
| RAG query | RAG context | Tool schemas |

**Estimated Savings:** 20-40% for specialized query types

---

### 6.6 Token Budget Allocation

**Current State:** No explicit token budget management
**Opportunity:** Allocate token budget across components

```python
TOTAL_BUDGET = 8000  # Target input tokens

budget_allocation = {
    "system_prompt": 1000,      # Fixed
    "tools_context": 2000,      # Flexible
    "history": 3000,            # Flexible, can summarize
    "rag_cases": 1000,          # Flexible, can limit k
    "current_query": 1000       # Fixed
}

# Dynamic adjustment
if history_tokens > budget_allocation["history"]:
    summarize_history(target=budget_allocation["history"])

if rag_tokens > budget_allocation["rag_cases"]:
    reduce_rag_examples(k=1)  # Fewer examples
```

**Estimated Savings:** Predictable costs, prevents context overflow

---

### 6.7 Profile-Specific Context Strategies

> **Status:** Partially implemented — see Section 9 for current per-profile context handling. The base infrastructure for profile-specific context strategies is in place. The remaining opportunity is further optimization *within* each profile type.

**Current State:** Basic profile-specific context assembly implemented (Section 9)
**Opportunity:** Further optimize per profile type

| Profile Type | Optimization |
|--------------|--------------|
| `tool_enabled` (Optimizer) | Full tools, RAG cases, plan hydration |
| `llm_only` (Chat) | Minimal tools (if any), no RAG, full history |
| `rag_focused` (Knowledge) | No tools, full RAG context, condensed history |
| `genie` (Multi-profile) | Dynamic based on sub-profile being called |

**Estimated Savings:** 30-60% depending on profile type

---

### 6.8 Incremental History Sync

**Current State:** Full session JSON read/written on every update
**Opportunity:** Append-only log with periodic compaction

```python
# Current: Read full file, modify, write full file
session = read_json(session_file)
session['chat_object'].append(message)
write_json(session_file, session)

# Proposed: Append to log, compact periodically
append_line(session_log, json.dumps(message))

if turn_count % 10 == 0:
    compact_log_to_snapshot(session_log, session_snapshot)
```

**Estimated Savings:** Reduced I/O for high-frequency updates

---

### 6.9 IFOC Methodology Context Isolation (Data Sovereignty)

**Current State:** All methodology phases share the same context window
**Opportunity:** Implement isolated context snippets per IFOC methodology stage

#### The IFOC Methodology

IFOC (Ideate → Focus → Operate → Complete) represents distinct cognitive phases in problem-solving workflows. Each phase has different context requirements and should maintain separation of concerns:

| Phase | Purpose | Context Needs |
|-------|---------|---------------|
| **Ideate** | Brainstorm, explore possibilities | Broad context, creative prompts, minimal constraints |
| **Focus** | Narrow down, select approach | Decision-making context, evaluation criteria |
| **Operate** | Execute the chosen approach | Execution context, tool schemas, operational data |
| **Complete** | Finalize, validate, synthesize | Results context, validation criteria, summary |

#### The Problem

When transitioning between phases (e.g., Ideate → Focus → back to Ideate):
- **Focus phase artifacts pollute Ideate context** - Decisions made during Focus should not bias subsequent Ideation
- **Cross-contamination reduces creativity** - Seeing implementation details during brainstorming constrains thinking
- **Data sovereignty violations** - Sensitive operational data from Focus/Operate may leak into Ideate

#### Proposed Implementation

```python
# Session structure with phase-isolated context windows
{
    "session_id": "uuid",
    "active_phase": "ideate",

    # Phase-isolated context windows
    "phase_contexts": {
        "ideate": {
            "chat_object": [...],           # Ideation-only history
            "workflow_history": [...],       # Ideation traces
            "visibility_rules": {
                "can_see": ["ideate"],       # Only own context
                "hidden_from": ["focus", "operate", "complete"]
            }
        },
        "focus": {
            "chat_object": [...],           # Focus-only history
            "workflow_history": [...],
            "visibility_rules": {
                "can_see": ["ideate", "focus"],  # Can reference ideation
                "hidden_from": ["ideate"]         # Hidden from ideation
            }
        },
        "operate": {
            "chat_object": [...],
            "visibility_rules": {
                "can_see": ["focus", "operate"],  # Can reference focus decisions
                "hidden_from": ["ideate", "focus"]
            }
        },
        "complete": {
            "chat_object": [...],
            "visibility_rules": {
                "can_see": ["operate", "complete"],
                "hidden_from": ["ideate", "focus", "operate"]
            }
        }
    },

    # Controlled phase transitions
    "phase_transitions": [
        {"from": "ideate", "to": "focus", "timestamp": "...", "summary": "..."},
        {"from": "focus", "to": "ideate", "timestamp": "...", "carry_forward": null}
    ]
}
```

#### Context Assembly by Phase

```python
def get_phase_context(session_data: dict, current_phase: str) -> list:
    """Assemble context window respecting phase isolation."""
    phase_config = session_data["phase_contexts"][current_phase]
    visibility_rules = phase_config["visibility_rules"]

    context = []

    # Only include context from visible phases
    for visible_phase in visibility_rules["can_see"]:
        phase_context = session_data["phase_contexts"][visible_phase]
        context.extend(phase_context["chat_object"])

    return context
```

#### Phase Transition with Controlled Carry-Forward

```python
def transition_phase(session_data: dict, from_phase: str, to_phase: str,
                     carry_forward: Optional[str] = None) -> dict:
    """
    Transition between IFOC phases with optional summary carry-forward.

    Args:
        carry_forward: Optional summary to inject into new phase context
                      (allows controlled information transfer)
    """
    # Record transition for audit
    session_data["phase_transitions"].append({
        "from": from_phase,
        "to": to_phase,
        "timestamp": datetime.now().isoformat(),
        "carry_forward": carry_forward
    })

    # If returning to earlier phase (e.g., Focus → Ideate)
    # DO NOT carry any Focus context back to Ideate
    if is_backward_transition(from_phase, to_phase):
        # Clear any forward-phase visibility
        # Ideate phase remains pristine
        pass

    # If moving forward (e.g., Ideate → Focus)
    # Optionally carry a summary (not full context)
    if carry_forward and is_forward_transition(from_phase, to_phase):
        to_context = session_data["phase_contexts"][to_phase]
        to_context["chat_object"].insert(0, {
            "role": "system",
            "content": f"Summary from {from_phase} phase: {carry_forward}",
            "phase_origin": from_phase
        })

    session_data["active_phase"] = to_phase
    return session_data
```

#### Data Sovereignty Benefits

1. **Clean Creative Space** - Ideation phase never sees implementation constraints
2. **Audit Trail** - All phase transitions recorded with what was (and wasn't) shared
3. **Compliance** - Operational data stays in Operate phase, not visible to earlier phases
4. **Reproducibility** - Can replay any phase with its isolated context
5. **Cost Efficiency** - Each phase only loads relevant context (smaller windows)

#### Integration with Existing Architecture

This feature would integrate with:
- **Profile system** - Phases could map to different profiles (Ideate → llm_only, Operate → tool_enabled)
- **Turn validity** - Phase transitions could mark previous phase turns as `isValid: false` for that phase
- **Session manager** - New `phase_contexts` structure alongside existing `chat_object`

**Estimated Impact:**
- High value for data sovereignty and enterprise compliance
- Medium-high effort (new session structure, UI for phase management)
- Priority: **P0** for enterprise deployments

---

## 7. Optimization Priority Matrix

| Optimization | Impact | Effort | Priority |
|--------------|--------|--------|----------|
| **IFOC methodology context isolation** | High | High | **P0** (Enterprise) |
| Dynamic RAG context adjustment | High | Medium | **P1** |
| Sliding window for history | High | Medium | **P1** |
| Token budget allocation | High | High | **P2** |
| Profile-specific strategies | Medium | Medium | **P2** |
| Tool schema caching | Medium | Low | **P3** |
| Semantic history compression | Medium | High | **P3** |
| Lazy context loading | Low | Medium | **P4** |
| Incremental history sync | Low | Medium | **P4** |

---

## 8. Metrics for Monitoring

### 8.1 Key Metrics to Track

| Metric | Current Tracking | Location |
|--------|------------------|----------|
| Input tokens per turn | Yes | session_manager.py |
| Output tokens per turn | Yes | session_manager.py |
| Context size breakdown | **No** | - |
| RAG retrieval hit rate | Partial | rag_retriever.py |
| Tool condensation savings | **No** | - |
| History growth rate | **No** | - |

### 8.2 Proposed Instrumentation

```python
context_metrics = {
    "turn_id": turn_number,
    "components": {
        "system_prompt_tokens": X,
        "tools_context_tokens": X,
        "history_tokens": X,
        "rag_context_tokens": X,
        "query_tokens": X
    },
    "optimizations_applied": ["tool_condensation", "history_filter"],
    "savings_estimate": X
}
```

---

## 9. Profile-Specific Context Handling

### 9.1 Context Strategy by Profile Type

| Aspect | tool_enabled | llm_only | rag_focused | genie |
|--------|--------------|----------|-------------|-------|
| **Planning** | Multi-phase planner | None (bypass) | None | ReAct agent |
| **Tools in Context** | Full MCP tools + structured | Empty `{}` | Empty `{}` | Child profile descriptions |
| **Knowledge** | Optional planner RAG | Optional knowledge RAG | Mandatory semantic search | Delegated to children |
| **History Source** | Workflow history + turn summaries | Session history | Session history | Parent session (last 10 msgs) |
| **System Prompt** | Strategic + tactical prompts | `CONVERSATION_EXECUTION` | `RAG_FOCUSED_EXECUTION` | Coordinator prompt |
| **Context Size** | Large (tools + history + RAG) | Medium (history + optional knowledge) | Medium (knowledge docs) | Small (child descriptions) |
| **Token Optimization** | Context distillation, plan hydration | N/A | Token-limited doc retrieval | Tool routing |

### 9.2 tool_enabled (Optimizer) Profile

**File:** `src/trusted_data_agent/agent/executor.py` (lines 4365-4405)

**Context Building:**
```python
# Full execution context including:
- APP_STATE.get('mcp_tools')           # All MCP tool schemas
- Structured prompts and categories     # From MCP adapter
- Workflow history                      # For multi-turn planning
- RAG champion cases                    # From planner repositories
- Previous turn data                    # For plan hydration
```

**Unique Features:**
- Uses `rebuild_tools_and_prompts_context()` to dynamically refresh tool context
- Filters disabled tools and prompts before context assembly
- Provides full tool metadata including arguments and descriptions to planner

### 9.3 llm_only (Chat) Profile

**File:** `src/trusted_data_agent/agent/executor.py` (lines 2238-2980)

**Context Building:**
```python
# Minimal context - bypasses planner entirely
clean_dependencies = {
    'STATE': {
        'llm': self.dependencies['STATE']['llm'],
        'mcp_tools': {},              # Empty - no tools
        'structured_tools': {},        # Empty - no structured tools
    }
}
```

**Unique Features:**
- Direct execution path via `ConversationAgentExecutor`
- Optional knowledge retrieval if `knowledge_enabled` flag set
- Uses `CONVERSATION_EXECUTION` prompt (no strategic/tactical planning prompts)
- Stateless, loop-based execution without planner overhead

### 9.4 rag_focused (Knowledge) Profile

**File:** `src/trusted_data_agent/agent/executor.py` (lines 3005-3814)

**Context Building:**
```python
# Three-tier configuration for knowledge retrieval:
1. Global defaults from APP_CONFIG
2. Profile-level overrides from profile config
3. Lock settings for compliance

# Mandatory knowledge retrieval:
all_results = self.rag_retriever.retrieve_examples(
    query=self.original_user_input,
    k=max_docs * len(knowledge_collections),
    min_score=min_relevance,
    repository_type="knowledge"  # Only knowledge, not planner
)
```

**Unique Features:**
- Zero MCP tools (no planning overhead)
- Semantic search with reranking capability
- Token-limited document formatting (`KNOWLEDGE_MAX_TOKENS = 2000`)
- Tracks accessed collections for replay/audit

### 9.5 genie (Multi-Profile Coordinator)

**File:** `src/trusted_data_agent/agent/genie_coordinator.py` (lines 399-898)

**Context Building:**
```python
# Conversation history from parent session (limited):
history_messages = chat_object[-11:]  # Last 10 messages for context

# Filter priming messages and invalid turns:
priming_messages = {"You are a helpful assistant.", "Understood."}
for msg in history_messages:
    if msg.get("isValid") is False:
        continue  # Skip invalid
```

**Unique Features:**
- Routes queries to multiple child profiles using LangChain ReAct agent
- Caches child sessions for reuse: `_slave_session_cache[parent:profile]`
- Builds tool descriptions from child profiles for routing decisions
- Collects events from children for plan reload/synthesis

### 9.6 ProfilePromptResolver

**File:** `src/trusted_data_agent/agent/profile_prompt_resolver.py` (lines 32-249)

All profile types use this class for prompt selection:

```python
class ProfilePromptResolver:
    def get_master_system_prompt(self) -> Optional[str]
    def get_workflow_prompt(self, subcategory: str) -> Optional[str]
    def get_genie_coordination_prompt(self, subcategory: str) -> Optional[str]
    def get_conversation_execution_prompt(self, subcategory: str) -> Optional[str]
```

**Prompt Categories by Profile:**
- `master_system_prompts` - LLM provider-specific (all profiles)
- `workflow_classification` - Strategic planning (tool_enabled only)
- `error_recovery` - Self-correction (tool_enabled only)
- `conversation_execution` - Chat responses (llm_only)
- `genie_coordination` - Multi-profile routing (genie only)
- `visualization` - Charting guidelines (all profiles)

---

## 10. Token Estimation & Tracking System

### 10.1 Token Extraction from LLM Responses

**File:** `src/trusted_data_agent/llm/handler.py`

| Provider | Input Tokens | Output Tokens |
|----------|--------------|---------------|
| **Google Gemini** | `usage.prompt_token_count` | `usage.candidates_token_count` |
| **Anthropic** | `response.usage.input_tokens` | `response.usage.output_tokens` |
| **OpenAI/Azure/Friendli** | `response.usage.prompt_tokens` | `response.usage.completion_tokens` |
| **Ollama** | `response.get('prompt_eval_count')` | `response.get('eval_count')` |
| **Bedrock (Anthropic)** | `usage.input_tokens` | `usage.output_tokens` |
| **Bedrock (Amazon Titan)** | `inputTextTokenCount` OR `usage.inputTokens` | `results[0].tokenCount` OR `usage.outputTokens` |
| **Bedrock (Meta/Cohere/Mistral/AI21)** | Returns 0 (not provided) | Returns 0 (not provided) |

**Key Insight:** The system does NOT pre-estimate tokens. It extracts actual counts from provider responses.

### 10.2 Cost Calculation

**File:** `src/trusted_data_agent/core/cost_manager.py` (lines 251-276)

```python
def calculate_cost(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    costs = self.get_model_cost(provider, model)
    if not costs:
        costs = self.get_fallback_cost()  # Default: ($0.10, $0.40) per 1M tokens

    input_cost_per_million, output_cost_per_million = costs
    input_cost = (input_tokens / 1_000_000) * input_cost_per_million
    output_cost = (output_tokens / 1_000_000) * output_cost_per_million
    return input_cost + output_cost
```

**Pricing Sources (Priority Order):**
1. Explicit model match in `llm_model_costs` table
2. Normalized model name (strips ARN prefixes, regional identifiers)
3. Fallback: $0.10 input / $0.40 output per 1M tokens

**Cost Storage Format:**
- Database: Integer (USD per 1M tokens)
- Consumption tracking: Micro-dollars (USD × 1,000,000) for precision

### 10.3 Token Quota Enforcement

**File:** `src/trusted_data_agent/auth/token_quota.py`

**Pre-Request Check:**
```python
def check_token_quota(user_id: str, input_tokens: int, output_tokens: int) -> Tuple[bool, str, Dict]:
    # Returns (is_allowed, error_message, quota_info)
    # NULL values in limits = unlimited
```

**Post-Request Recording:**
```python
def record_token_usage(user_id: str, input_tokens: int, output_tokens: int) -> bool:
    period = get_current_period()  # YYYY-MM format
    usage.input_tokens_used += input_tokens
    usage.output_tokens_used += output_tokens
```

### 10.4 Consumption Tracking

**File:** `src/trusted_data_agent/auth/consumption_manager.py`

**Tracked Metrics:**
- **Token Tracking:** `total_input_tokens`, `total_output_tokens`, `total_tokens`
- **Quality Metrics:** `successful_turns`, `failed_turns`, success rate
- **RAG Metrics:** `rag_guided_turns`, `rag_output_tokens_saved`, `rag_activation_rate`
- **Cost:** `estimated_cost_usd` (micro-dollars)
- **Rate Limiting:** `requests_this_hour`, `requests_today`
- **Model Usage:** JSON tracking distributions

### 10.5 RAG Efficiency Tracking

**File:** `src/trusted_data_agent/core/efficiency_tracker.py`

```python
def record_improvement(session_id, turn_index,
                       previous_output_tokens, current_output_tokens,
                       had_rag, cost_per_output_token, user_uuid):
    tokens_saved = previous_output_tokens - current_output_tokens
    # Only counts if RAG was used AND tokens decreased
```

**Metrics Available:**
- `total_output_tokens_saved`
- `total_rag_improvements`
- `cumulative_cost_saved`
- `avg_tokens_saved_per_improvement`

---

## 11. Error Handling & Edge Cases

### 11.1 Context Overflow Prevention

**Configuration:** `src/trusted_data_agent/core/config.py`

All values below are admin-configurable via Administration → Optimizer Settings / App Config / Knowledge Repository.

```python
# Context distillation (executor-level, metadata-only summaries)
CONTEXT_DISTILLATION_MAX_ROWS = 500        # Trigger metadata-only summary (rows)
CONTEXT_DISTILLATION_MAX_CHARS = 10_000    # Trigger metadata-only summary (chars)

# Analytical distillation (adapter-level, column statistics + stratified samples)
REPORT_DISTILLATION_MAX_ROWS = 100         # L1: per-result-set stratified sample rows
REPORT_DISTILLATION_MAX_CHARS = 50_000     # L1: per-result-set char limit
REPORT_DISTILLATION_TOTAL_BUDGET = 200_000 # L2: total budget trigger
REPORT_DISTILLATION_AGGRESSIVE_ROWS = 25   # L2: aggressive row limit (stats preserved)

# Document context processing
DOCUMENT_CONTEXT_MAX_CHARS = 50_000        # Total char limit for uploaded documents
DOCUMENT_PER_FILE_MAX_CHARS = 20_000       # Per-document truncation limit

# Execution limits
MAX_EXECUTION_DEPTH = 5                    # Maximum recursive execution depth
MAX_PHASE_RETRY_ATTEMPTS = 5              # Maximum self-correction retries per phase

# Knowledge chunking
KNOWLEDGE_CHUNK_SIZE = 1_000               # Default chunk size for knowledge repositories
KNOWLEDGE_CHUNK_OVERLAP = 200              # Default overlap between chunks

# LLM output
LLM_MAX_OUTPUT_TOKENS = 16_384            # Max output tokens (all providers)

# Knowledge context
KNOWLEDGE_MAX_TOKENS = 2_000               # Knowledge context budget per retrieval
```

**Mechanisms:**

| Mechanism | Trigger | Action |
|-----------|---------|--------|
| **Context Distillation** | Result > 500 rows OR > 10K chars | Replace with metadata-only summary |
| **Report Distillation L1** | Per-result > 100 rows OR > 50K chars | Truncate to sample rows |
| **Report Distillation L2** | Total > 200K chars | Reduce to 25 rows per result set |
| **Document Truncation** | Per-file > 20K chars or total > 50K chars | Truncate with "[Document truncated...]" suffix |
| **Knowledge Truncation** | Accumulated chars > limit | Stop adding documents mid-iteration |
| **System Prompt Condensation** | `full_context_sent == True` | Names-only tool list (60-70% savings) |
| **LLM Output Cap** | All provider calls | Limit response to 8,192 tokens (100 for session names) |

### 11.2 Malformed Data Recovery

**JSON Parsing with Sanitization:** `handler.py:69-156`
```python
def parse_and_coerce_llm_response(response_text: str, target_model: BaseModel):
    # 1. Sanitize (remove control characters)
    # 2. Extract JSON from markdown blocks OR raw
    # 3. Validate against Pydantic model
    # 4. Auto-correct common issues (list→objects, numbers→strings)
```

**Session Corruption:** `session_manager.py:103-110`
```python
except (json.JSONDecodeError, OSError) as e:
    app_logger.error(f"Error loading session file: {e}")
    return None  # Graceful degradation
```

### 11.3 Retry Logic

**LLM API Retries:** `handler.py:610-1041`
```python
for attempt in range(APP_CONFIG.LLM_API_MAX_RETRIES):
    try:
        # Attempt LLM call
        break
    except (RateLimitError, InternalServerError) as e:
        delay = (base_delay * (2 ** attempt)) + random.uniform(0, 1)
        await asyncio.sleep(delay)
```

**ChromaDB Collection Recovery:** `rag_retriever.py:438-454`
```python
except KeyError as e:
    if "'_type'" in str(e):
        # Delete corrupted collection, recreate with proper config
        self.client.delete_collection(name=coll_name)
        collection = self.client.create_collection(name=coll_name, ...)
```

### 11.4 Response Truncation Detection

**Google API:** `handler.py:699-727`
```python
finish_reason_name = candidate.finish_reason.name
# MAX_TOKENS: Response truncated (log warning, return partial)
# SAFETY: Content blocked (log with safety ratings)
# RECITATION: Copyright detected (log warning)
```

### 11.5 History Validity Control

**Turn Toggle:** `session_manager.py:1468-1532`
- Toggle `isValid` flag across all three histories
- Invalid turns automatically excluded from LLM context
- Preserves data for auditing

**Memory Purge:** `session_manager.py:1398-1465`
- Marks all history as `isValid: false`
- Resets `chat_object` to empty
- Resets `full_context_sent` flag
- Keeps audit trail in `session_history` and `workflow_history`

### 11.6 Edge Case Summary

| Edge Case | Detection | Recovery | Logging |
|-----------|-----------|----------|---------|
| Context exceeds limit | Row/char thresholds | Distill to metadata | INFO |
| Truncated response | `finish_reason == MAX_TOKENS` | Return partial, warn | WARNING |
| Malformed JSON | `JSONDecodeError` | Sanitize, auto-correct | ERROR → DEBUG |
| Corrupted session | Parse error on load | Create placeholder | ERROR |
| Corrupted ChromaDB | KeyError `_type` | Delete & recreate | ERROR + recovery |
| Rate limit | `RateLimitError` | Exponential backoff | WARNING per retry |
| Invalid history | `isValid == false` | Skip during context build | DEBUG |

---

## 12. Summary

The Uderia context window system is well-architected with multiple optimization layers already in place. With the introduction of the **Context Window System Component** (Section 13), many of the original improvement areas have been addressed:

1. **IFOC methodology context isolation** (P0 for Enterprise) — The module architecture supports this naturally via `AssemblyContext` with isolated session data per phase. No code changes needed — the design is already phase-aware.

2. ~~Dynamic adjustment based on RAG confidence~~ — **Implemented** via dynamic adjustment rules in context window types (`high_confidence_rag` condition).

3. ~~Sliding window for long conversations~~ — **Implemented** via `conversation_history` module's `condense()` method using sliding window strategy.

4. ~~Token budget management~~ — **Implemented** via four-pass orchestrator with per-module budget allocation (target/min/max percentages), redistribution, and condensation.

5. ~~Profile-aware context optimization~~ — **Implemented** via module `applies_to()` filtering and profile-bound context window types.

---

## 13. Context Window System Component

### 13.1 Overview

The Context Window System Component introduces **programmatic context management** as a first-class system component within the Uderia component architecture. It replaces scattered context assembly logic with a centralized, modular, observable orchestrator.

```
Setup Entities:
├── LLM Configurations       (which provider/model)
├── MCP Servers               (which data sources)
├── Context Window Types      (which modules, how budget is allocated)  ← NEW
└── Profiles                  (binds: LLM + MCP + Context Window Type)
```

### 13.2 Architecture — Three Layers

#### Layer 1: Context Modules (Plugin System)

A context module is a self-contained unit that contributes content to the LLM context window. Each module knows how to produce its content, declares condensation capabilities, and specifies profile applicability.

**Module Discovery (same pattern as ComponentManager):**
```
Discovery order (later overrides earlier):
1. Built-in modules:     components/builtin/context_window/modules/
2. Agent pack modules:   installed via agent packs (future)
3. User modules:         ~/.tda/context_modules/
```

Each module directory contains:
```
modules/system_prompt/
├── manifest.json        # Module metadata, capabilities, profile applicability
└── handler.py           # Python class implementing ContextModule ABC
```

**Module Interface (ABC):**

```python
class ContextModule(ABC):
    @property
    @abstractmethod
    def module_id(self) -> str: ...

    @abstractmethod
    def applies_to(self, profile_type: str) -> bool: ...

    @abstractmethod
    async def contribute(self, budget: int, ctx: AssemblyContext) -> Contribution: ...

    async def condense(self, content: str, target_tokens: int, ctx: AssemblyContext) -> Contribution: ...
    async def purge(self, session_id: str, user_uuid: str) -> dict: ...
    def get_status(self) -> dict: ...
```

**Built-In Modules (9 shipped):**

| Module ID | Priority | Target % | Condensable | Purgeable | Profile Applicability |
|-----------|:--------:|:--------:|:-----------:|:---------:|----------------------|
| `system_prompt` | 95 | 10% | No | No | All |
| `tool_definitions` | 85 | 22% | Yes (full → names-only) | No | tool_enabled, genie |
| `conversation_history` | 80 | 22% | Yes (sliding window) | Yes | All |
| `rag_context` | 75 | 15% | Yes (fewer examples) | Yes | tool_enabled |
| `knowledge_context` | 70 | 10% | Yes (fewer docs) | Yes | tool_enabled, llm_only, rag_focused |
| `plan_hydration` | 65 | 8% | Yes (summary) | Yes | tool_enabled |
| `document_context` | 60 | 5% | Yes (truncation) | Yes | tool_enabled, llm_only, rag_focused |
| `component_instructions` | 55 | 4% | Yes (intensity) | No | All |
| `workflow_history` | 50 | 4% | Yes (fewer turns) | Yes | tool_enabled |

**Module Lifecycle:**

| Operation | Description | When |
|-----------|-------------|------|
| **Install** | Module discovered and registered | Startup, hot-reload, agent pack install |
| **Activate** | Module enabled in a context window type | Setup UI toggle |
| **Deactivate** | Module disabled in a context window type | Setup UI toggle |
| **Purge** | Clear cached/accumulated data | Admin action |
| **Uninstall** | Module removed from registry (user modules only) | Admin action |

#### Layer 2: Context Window Types (Compositions)

A context window type is a **named composition** of active modules with per-module budget allocations:

```json
{
  "id": "cwt-default-balanced",
  "name": "Balanced",
  "description": "Default balanced allocation for general use",
  "is_default": true,
  "output_reserve_pct": 12,
  "modules": {
    "system_prompt": { "active": true, "target_pct": 10, "min_pct": 5, "max_pct": 15, "priority": 95 },
    "tool_definitions": { "active": true, "target_pct": 22, "min_pct": 0, "max_pct": 40, "priority": 85 },
    "...": "..."
  },
  "condensation_order": ["workflow_history", "component_instructions", "..."],
  "dynamic_adjustments": [
    { "condition": "high_confidence_rag", "action": { "reduce": "tool_definitions", "by_pct": 50 } },
    { "condition": "no_documents_attached", "action": { "transfer": "document_context", "to": "conversation_history" } }
  ]
}
```

**Default Types Shipped:**

| Name | Intent | Key Config |
|------|--------|------------|
| **Balanced** (default) | General purpose | All 9 modules active, even distribution |
| **Knowledge Heavy** | RAG/knowledge focus | knowledge 40%, rag 20%, tools deactivated |
| **Conversation First** | Chat focus | history 50%, knowledge 15%, tools deactivated |
| **Token Efficient** | Minimum context | Low targets, tight maxes, 4 modules deactivated |

Profiles bind to a context window type via `contextWindowTypeId` (same pattern as `llmConfigurationId` and `mcpServerId`).

#### Layer 3: Orchestrator (Five-Pass Assembly)

**File:** `components/builtin/context_window/handler.py`

The `ContextWindowHandler` orchestrates budget allocation using the profile's bound context window type:

```
Pass 1: RESOLVE ACTIVE MODULES
  For each module in the context window type:
    if module.active == false → skip (deactivated by user)
    if not module.applies_to(profile_type) → skip (not applicable)
  Redistribute budget from skipped modules proportionally

Pass 2: APPLY DYNAMIC ADJUSTMENTS
  Evaluate each dynamic_adjustment rule against runtime conditions
  Adjust target_pct values (reduce, transfer, force_full, condense)
  Must run BEFORE allocation so adjusted percentages drive budget calculation

Pass 3: ALLOCATE AND ASSEMBLE (priority order, highest first)
  available_budget = model_limit - output_reserve
  For each active module:
    allocation = available_budget * adjusted_target_pct
    allocation = clamp(allocation, min_tokens, max_tokens)
    result = module.contribute(allocation, context)
    snapshot.record(module_id, allocation, result.tokens_used)

Pass 3b: REALLOCATE SURPLUS
  Identify donors: modules with utilization < 30% of allocation
  Identify recipients: modules with utilization > 80% AND condensable
  Calculate surplus = allocated - used for each donor
  Distribute surplus proportionally to recipients (by priority, capped at max_pct)
  Re-run contribute() on recipients with increased budget

Pass 4: CONDENSE IF OVER BUDGET
  If total_used > available_budget:
    For each module in condensation_order:
      if module.condensable:
        condensed = module.condense(content, target, context)
        snapshot.record_condensation(module_id, before, after)
      if total_used <= available_budget: break
```

**Design rationale**: Dynamic adjustments (Pass 2) must run before allocation (Pass 3) because adjustment rules modify `target_pct` values on `ActiveModule` objects. If adjustments ran after allocation, modules would already have called `contribute()` with their original percentages, making the adjustments inert. Reallocation (Pass 3b) runs after assembly to capture actual utilization and redistribute surplus from modules that used far less than allocated.

**Model Context Limit Resolution:**

The orchestrator resolves the actual model context window size from `litellm.model_cost` metadata (e.g., Claude = 200K, Gemini = 1M, GPT-4o = 128K). Falls back to 128K if metadata unavailable.

**Context Limit Override Chain:**

The effective context limit is resolved through a priority chain (lowest wins):

1. **Model default** -- from `litellm.model_cost` metadata (e.g., Gemini 2.0 Flash = 1M)
2. **Profile override** -- `contextLimitOverride` in profile config (persistent, affects all sessions using the profile)
3. **Session override** -- `session_context_limit_override` in session JSON (temporary, applies to current session only)

Both overrides can only **reduce** the limit below the model default, never increase it. The session override takes precedence over the profile override.

Applied in `executor.py:_run_context_window_assembly()` and `execution_service.py` (Genie coordinator) before `AssemblyContext` construction.

### 13.3 Observability

#### ContextWindowSnapshot (SSE Event)

After each orchestrator assembly, a `context_window_snapshot` SSE event is emitted:

```python
@dataclass
class ContextWindowSnapshot:
    context_window_type_id: str
    context_window_type_name: str
    model_context_limit: int
    output_reserve: int
    available_budget: int
    total_used: int
    utilization_pct: float
    context_limit_override: Optional[int]            # Profile-level override
    session_context_limit_override: Optional[int]    # Session-level override
    contributions: List[ContributionMetric]      # Per-module metrics
    condensations: List[CondensationEvent]        # Condensation events
    dynamic_adjustments_fired: List[str]          # Rules that fired
    reallocation_events: List[dict]               # Surplus reallocation records
    skipped_contributors: List[str]               # Modules that didn't apply
```

#### Resource Panel — "Context" Tab

Shows the bound context window type's module composition:
- Stacked horizontal bar chart of target allocations
- Per-module budget cards with color coding
- Active/inactive module indicators
- Last query snapshot metrics (when available)
- **Session Context Limit slider** -- temporary override (session-scoped) between header and allocation bars

Updates dynamically when the active profile changes (via "Set as Default" or @TAG override).

#### Live Status — Runtime Events

`context_window_snapshot` events render as compact horizontal bars in the event stream showing actual token consumption per module, utilization percentage, and condensation events.

### 13.4 Feature Flag & ContextBuilder Integration

**Flag:** `APP_CONFIG.USE_CONTEXT_WINDOW_MANAGER` (default: `True`)

When enabled, the orchestrator drives **actual context assembly** for all 4 profile types. Module output replaces the previous hardcoded context logic:

| Profile Type | Integration Point | What CW Modules Control |
|---|---|---|
| `tool_enabled` | `ContextBuilder` in `planner.py` | system_prompt, tool_definitions, conversation_history, rag_context, knowledge_context, plan_hydration, document_context, component_instructions, workflow_history |
| `llm_only` | `executor.py` pre-LLM assembly | conversation_history (window size), document_context (char limit), component_instructions (pre-computed) |
| `rag_focused` | `executor.py` RAG synthesis path | conversation_history (window size), document_context (char limit), component_instructions (pre-computed) |
| `genie` | `execution_service.py` coordinator | conversation_history (window size), document_context (char limit) |

The `ContextBuilder` class (in `planner.py`) is the bridge for `tool_enabled` profiles. It consumes `AssembledContext.contributions` and maps each module's output to the appropriate position in the planner/executor message list. For non-tool profiles, executor code extracts specific values (e.g., `cw_history_window`, `cw_document_max_chars`) from the assembled context and passes them to existing code paths.

**Token estimation** uses tiktoken (`cl100k_base` encoding) when available for accurate BPE token counts. Falls back to a character-based heuristic (~4 chars/token) if tiktoken is not installed.

### 13.5 REST API

See [REST API Documentation — Section 3.24](../RestAPI/restAPI.md) for complete endpoint reference.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/context-window-types` | GET | List all context window types |
| `/v1/context-window-types` | POST | Create new type |
| `/v1/context-window-types/{id}` | GET | Get single type |
| `/v1/context-window-types/{id}` | PUT | Update type |
| `/v1/context-window-types/{id}` | DELETE | Delete type |
| `/v1/context-window/modules` | GET | List installed modules |
| `/v1/context-window/modules/{id}/purge` | POST | Purge module data |
| `/v1/context-window/active/{profile_id}` | GET | Get resolved type for profile |

### 13.6 File Structure

```
components/builtin/context_window/
├── manifest.json                       # System component manifest
├── handler.py                          # ContextWindowHandler (orchestrator)
├── module_registry.py                  # Module discovery, install/uninstall, hot-reload
├── base.py                             # ContextModule ABC, Contribution, AssemblyContext
├── snapshot.py                         # ContextWindowSnapshot dataclass + SSE formatting
├── token_estimator.py                  # Token estimation (tiktoken BPE + heuristic fallback)
├── renderer.js                         # Resource Panel renderer
│
├── modules/                            # Built-in context modules
│   ├── system_prompt/                  # Wraps ProfilePromptResolver
│   ├── tool_definitions/               # Wraps tool schema formatting + condensation
│   ├── conversation_history/           # Wraps chat_object + validity filtering
│   ├── rag_context/                    # Wraps RAGRetriever
│   ├── knowledge_context/              # Wraps knowledge document retrieval
│   ├── plan_hydration/                 # Wraps previous turn data injection
│   ├── document_context/               # Wraps document upload context
│   ├── component_instructions/         # Wraps ComponentManager instructions
│   └── workflow_history/               # Wraps turn summary assembly
│
└── __init__.py

# User-contributed modules (auto-discovered):
~/.tda/context_modules/
└── <module_id>/
    ├── manifest.json
    └── handler.py
```

---

## Appendix: Key File References

| Component | File | Key Lines |
|-----------|------|-----------|
| System prompt construction | `llm/handler.py` | 358-507 |
| History condensation | `llm/handler.py` | 253-355 |
| Context distillation | `agent/executor.py` | 956-983 |
| Analytical distillation | `mcp_adapter/adapter.py` | 25-320 |
| Document context processing | `agent/executor.py` | 41-100 |
| Session management | `core/session_manager.py` | 1038-1134, 1398-1465 |
| Profile detection | `agent/executor.py` | 1302-1324 |
| Genie coordination | `agent/genie_coordinator.py` | 399-898 |
| RAG retrieval | `agent/rag_retriever.py` | 1288+ |
| Token tracking | `core/cost_manager.py` | 251-276 |
| Consumption tracking | `auth/consumption_manager.py` | 194-296 |
| Profile prompt resolution | `agent/profile_prompt_resolver.py` | 32-249 |
| Context Window orchestrator | `components/builtin/context_window/handler.py` | Full file |
| Context Module ABC | `components/builtin/context_window/base.py` | Full file |
| Module registry | `components/builtin/context_window/module_registry.py` | Full file |
| Snapshot dataclass | `components/builtin/context_window/snapshot.py` | Full file |
| Token estimator | `components/builtin/context_window/token_estimator.py` | Full file |
| Context Window REST API | `api/rest_routes.py` | 5414-5653 |
| Context Panel (frontend) | `static/js/handlers/contextPanelHandler.js` | Full file |
| Context Window Setup UI | `static/js/handlers/contextWindowHandler.js` | Full file |
