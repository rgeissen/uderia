# Context Window Architecture: Comprehensive Analysis

## Overview

This document provides a detailed analysis of how the Uderia platform manages session context windows, including generation, contribution, consumption, storage, and optimization opportunities.

---

## 1. Context Window Generation

### 1.1 System Prompt Construction

**File:** `src/trusted_data_agent/llm/handler.py` (lines 325-497)
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

**File:** `src/trusted_data_agent/core/session_manager.py` (lines 582-668)
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

**File:** `src/trusted_data_agent/agent/planner.py` (lines 1760-1833)

Champion cases are retrieved and formatted:
```
1. Query ChromaDB for similar patterns
2. Filter by efficiency score and user feedback
3. Format as few-shot examples
4. Inject with adaptive header (instruct LLM to adapt, not copy)
```

### 1.4 Plan Hydration Context

**File:** `src/trusted_data_agent/agent/planner.py` (lines 200-249)

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

**File:** `src/trusted_data_agent/llm/handler.py` (lines 569-717)

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
| **Add message** | `add_message_to_histories()` | session_manager.py | 582-668 |
| **Update tokens** | `update_token_count()` | session_manager.py | 708-744 |
| **Update turn data** | `update_last_turn_data()` | session_manager.py | 781-908 |
| **Toggle validity** | `toggle_turn_validity()` | session_manager.py | 981-1046 |
| **Purge memory** | `purge_session_memory()` | session_manager.py | 911-978 |
| **Condense history** | `_condense_and_clean_history()` | handler.py | 220-322 |

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
| **Tool condensation** | Names-only after first turn | 60-70% of tool context | handler.py:394-401 |
| **History condensation** | Remove duplicates, clean capabilities | 10-20% of history | handler.py:220-322 |
| **Context distillation** | Summarize large tool outputs | 99%+ of large results | executor.py:522-549 |
| **Plan hydration** | Inject previous results, skip re-fetch | 1-2 tool calls saved | planner.py:200-249 |
| **Turn validity toggle** | Exclude invalid turns from context | Variable | session_manager.py:981-1046 |
| **Memory purge** | Reset chat_object, keep audit trail | 100% of history | session_manager.py:911-978 |

### 5.2 Optimization Trigger Conditions

| Optimization | Trigger |
|--------------|---------|
| Tool condensation | `full_context_sent == True` (after turn 1) |
| History condensation | `CONDENSE_SYSTEMPROMPT_HISTORY` config flag |
| Context distillation | Result > 500 rows OR > 10,000 chars |
| Plan hydration | Previous turn has reusable data for current phase |
| Turn validity | User toggles turn via UI |
| Memory purge | User clicks "Clear Memory" |

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

**Current State:** Same context assembly for all profile types
**Opportunity:** Optimize per profile type

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

**File:** `src/trusted_data_agent/agent/executor.py` (lines 4291+)

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

**File:** `src/trusted_data_agent/agent/executor.py` (lines 1690-2180)

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

**File:** `src/trusted_data_agent/agent/executor.py` (lines 2201-2905)

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

**File:** `src/trusted_data_agent/agent/genie_coordinator.py` (lines 365-823)

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

**File:** `src/trusted_data_agent/agent/profile_prompt_resolver.py` (lines 100-249)

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
```python
CONTEXT_DISTILLATION_MAX_ROWS = 500        # Trigger distillation
CONTEXT_DISTILLATION_MAX_CHARS = 10000     # Character threshold
KNOWLEDGE_MAX_TOKENS = 2000                # Knowledge context budget
```

**Mechanisms:**

| Mechanism | Trigger | Action |
|-----------|---------|--------|
| **Data Distillation** | Result > 500 rows OR > 10K chars | Replace with metadata summary |
| **Knowledge Truncation** | Accumulated chars > limit | Stop adding documents mid-iteration |
| **System Prompt Condensation** | `full_context_sent == True` | Names-only tool list (60-70% savings) |

### 11.2 Malformed Data Recovery

**JSON Parsing with Sanitization:** `handler.py:72-111`
```python
def parse_and_coerce_llm_response(response_text: str, target_model: BaseModel):
    # 1. Sanitize (remove control characters)
    # 2. Extract JSON from markdown blocks OR raw
    # 3. Validate against Pydantic model
    # 4. Auto-correct common issues (list→objects, numbers→strings)
```

**Session Corruption:** `session_manager.py:103-105`
```python
except (json.JSONDecodeError, OSError) as e:
    app_logger.error(f"Error loading session file: {e}")
    return None  # Graceful degradation
```

### 11.3 Retry Logic

**LLM API Retries:** `handler.py:569-886`
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

**Google API:** `handler.py:616-643`
```python
finish_reason_name = candidate.finish_reason.name
# MAX_TOKENS: Response truncated (log warning, return partial)
# SAFETY: Content blocked (log with safety ratings)
# RECITATION: Copyright detected (log warning)
```

### 11.5 History Validity Control

**Turn Toggle:** `session_manager.py:981-1046`
- Toggle `isValid` flag across all three histories
- Invalid turns automatically excluded from LLM context
- Preserves data for auditing

**Memory Purge:** `session_manager.py:911-978`
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

The Uderia context window system is well-architected with multiple optimization layers already in place. The primary opportunities for improvement are:

1. **IFOC methodology context isolation** (P0 for Enterprise) - Implement isolated context windows per methodology phase (Ideate/Focus/Operate/Complete) to ensure data sovereignty and separation of concerns. When transitioning between phases (especially backward transitions like Focus → Ideate), the earlier phase must not have visibility into artifacts generated by later phases.

2. **Dynamic adjustment based on RAG confidence** - Currently context is static regardless of retrieval success

3. **Sliding window for long conversations** - History grows linearly without bounds

4. **Token budget management** - No explicit allocation or enforcement

5. **Profile-aware context optimization** - Currently same assembly logic for all profile types

These improvements would provide:
- **Data sovereignty** - Phase isolation prevents cross-contamination of sensitive information
- **Predictable costs** - Token budget allocation and sliding windows
- **Better scaling** - Long conversations handled efficiently
- **Cleaner cognitive spaces** - Each IFOC phase operates with appropriate context only

---

## Appendix: Key File References

| Component | File | Key Lines |
|-----------|------|-----------|
| System prompt construction | `llm/handler.py` | 325-497 |
| History condensation | `llm/handler.py` | 220-322 |
| Context distillation | `agent/executor.py` | 522-549 |
| Session management | `core/session_manager.py` | 582-668, 911-978 |
| Profile detection | `agent/executor.py` | 1670-1687 |
| Genie coordination | `agent/genie_coordinator.py` | 365-823 |
| RAG retrieval | `agent/rag_retriever.py` | 1227-1397 |
| Token tracking | `core/cost_manager.py` | 251-276 |
| Consumption tracking | `auth/consumption_manager.py` | 194-296 |
| Profile prompt resolution | `agent/profile_prompt_resolver.py` | 100-249 |
