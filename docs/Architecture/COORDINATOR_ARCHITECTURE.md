# Coordinator Architecture

> **Multi-agent orchestration engine** — routes user queries to specialized child profiles, executes them as independent sessions, and synthesizes their results into a unified response.

The Coordinator (profile type `genie`) is the only profile type that does not interact with the LLM directly for domain tasks. Instead, it acts as an **agentic router**: a LangChain-based ReAct agent that analyzes a user query, determines which child profiles are best suited, invokes them via REST API calls, and synthesizes the collected results. Each child profile runs in its own session with full context preservation, enabling multi-turn coordination across heterogeneous profile types.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Core Architecture](#2-core-architecture)
3. [Execution Flow](#3-execution-flow)
4. [Child Session Management](#4-child-session-management)
5. [Nested Coordination](#5-nested-coordination)
6. [Configuration & Three-Tier Settings](#6-configuration--three-tier-settings)
7. [Prompt Resolution](#7-prompt-resolution)
8. [Component Integration](#8-component-integration)
9. [Event System & Observability](#9-event-system--observability)
10. [Frontend Architecture](#10-frontend-architecture)
11. [Database Schema](#11-database-schema)
12. [REST API Endpoints](#12-rest-api-endpoints)
13. [Safety Mechanisms](#13-safety-mechanisms)
14. [Pass-Through Optimisation](#14-pass-through-optimisation)
15. [Skills Injection](#15-skills-injection)
16. [File Reference](#16-file-reference)

---

## 1. System Overview

### What the Coordinator Does

The Coordinator receives a user query and orchestrates multiple specialized AI profiles to produce a unified answer. Unlike `tool_enabled`, `llm_only`, and `rag_focused` profiles which execute their own LLM pipelines, the Coordinator delegates execution to child profiles and focuses exclusively on **routing** and **synthesis**.

### Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Delegated Execution** | Coordinator never executes tools or retrieves knowledge directly — child profiles do |
| **Session Isolation** | Each child runs in its own session with independent context and history |
| **Context Reuse** | Subsequent calls to the same child profile reuse the existing session |
| **Profile Agnostic** | Can coordinate any profile type: `tool_enabled`, `llm_only`, `rag_focused`, or nested `genie` |
| **Progressive Routing** | Single-profile optimization when one expert suffices; multi-profile decomposition for complex queries |
| **Transparent Coordination** | All routing decisions, invocations, and synthesis steps visible in Live Status window |

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│ FRONTEND                                                             │
│                                                                      │
│  User submits query via @GENIE profile                              │
│       ↓                                                              │
│  submitQuestion() → POST /ask_stream                                │
│       ↓                                                              │
│  SSE stream receives genie_* events → Live Status window            │
│  (coordination details shown ONLY in status panel, not inline)      │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ BACKEND: execution_service.py                                        │
│                                                                      │
│  1. Detect profile_type == "genie" (line 478)                       │
│  2. Route to _run_genie_execution() (line 655)                      │
│  3. Validate genie config, resolve child profiles                   │
│  4. Create LangChain LLM from profile's llmConfigurationId         │
│  5. Build GenieCoordinator with child profile tools                 │
│  6. Load existing child sessions for context reuse                  │
│  7. Execute coordinator.execute(query, conversation_history)        │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ GENIE COORDINATOR: genie_coordinator.py                              │
│                                                                      │
│  ┌─────────────────────────────────────────────────────┐            │
│  │ LangGraph ReAct Agent                                │            │
│  │                                                      │            │
│  │  System Prompt (GENIE_COORDINATOR_PROMPT)            │            │
│  │  + Available profiles injected                       │            │
│  │  + Component instructions injected                   │            │
│  │  + KG enrichment context (if active)                 │            │
│  │                                                      │            │
│  │  Tools:                                              │            │
│  │  ├── invoke_CHAT    (SlaveSessionTool)               │            │
│  │  ├── invoke_RAG     (SlaveSessionTool)               │            │
│  │  ├── invoke_TDAT    (SlaveSessionTool)               │            │
│  │  ├── TDA_Charting   (Component Tool)                 │            │
│  │  └── ...                                             │            │
│  └─────────────────────────────────────────────────────┘            │
│       │                                                              │
│       ▼                                                              │
│  ROUTING DECISION → LLM analyzes query, selects profiles            │
│       │                                                              │
│       ▼                                                              │
│  CHILD INVOCATION → REST API calls to child sessions                │
│       │                                                              │
│       ▼                                                              │
│  SYNTHESIS → LLM combines results into unified response             │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ CHILD SESSIONS (independent, full-featured)                          │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ @CHAT         │  │ @RAG          │  │ @TDAT         │              │
│  │ llm_only      │  │ rag_focused   │  │ tool_enabled  │              │
│  │ Session: abc  │  │ Session: def  │  │ Session: ghi  │              │
│  │               │  │               │  │               │              │
│  │ Own context   │  │ Own context   │  │ Own context   │              │
│  │ Own history   │  │ Own history   │  │ Own history   │              │
│  │ Own LLM       │  │ Own LLM       │  │ Own LLM       │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│                                                                      │
│  Sessions reused across coordinator turns for context continuity     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Architecture

### Module Structure

```
src/trusted_data_agent/agent/
├── genie_coordinator.py       # GenieCoordinator, SlaveSessionTool
├── execution_service.py       # _run_genie_execution() routing
└── profile_prompt_resolver.py # get_genie_coordinator_prompt()

src/trusted_data_agent/core/
├── config_manager.py          # Genie validation, circular dependency detection
└── session_manager.py         # Genie session link management

static/js/
├── handlers/genieHandler.js   # Frontend coordination state tracking
├── eventHandlers.js           # Genie event title rendering
└── ui.js                      # _renderGenieStep() Live Status rendering

schema/
├── 07_genie_profiles.sql      # genie_session_links table
└── 08_genie_global_settings.sql # Global settings with admin locks
```

### Key Classes

#### SlaveSessionTool (`genie_coordinator.py:54-397`)

LangChain `BaseTool` subclass that wraps REST API calls to child sessions. Each child profile becomes a separate tool instance named `invoke_{PROFILE_TAG}`.

```python
class SlaveSessionTool(BaseTool):
    name: str          # e.g., "invoke_CHAT"
    description: str   # "@CHAT (Chatbot): General conversation. Type: llm_only"
    profile_id: str    # Profile ID for session creation
    profile_tag: str   # Profile tag for display
    user_uuid: str     # Session owner
    parent_session_id: str  # Parent Genie session
    base_url: str      # API base URL (default: localhost:5050)
    auth_token: str    # Internal authentication token
    query_timeout: float  # Timeout in seconds (default: 300)
    current_nesting_level: int  # Depth in nested hierarchy
```

**Key methods:**
- `_arun(query)` — Execute query via child session with context reuse (line 92)
- `_get_or_create_slave_session()` — Session cache lookup or REST API creation (line 181)
- `_execute_primer(session_id, primer)` — Execute session primer on first session creation (line 267)
- `_execute_and_poll(session_id, query)` — Submit query and poll `/api/v1/tasks/{task_id}` for completion (line 319)

#### GenieCoordinator (`genie_coordinator.py:400-1101`)

Main orchestration engine that builds and executes a LangGraph ReAct agent.

```python
class GenieCoordinator:
    def __init__(self, genie_profile, slave_profiles, user_uuid,
                 parent_session_id, auth_token, llm_instance,
                 base_url, event_callback, genie_config,
                 current_nesting_level):
        # Builds tools, merges component tools, creates agent executor

    async def execute(self, query, conversation_history=None) -> Dict:
        # Main execution: routing → invocation → synthesis

    def load_existing_slave_sessions(self, existing_sessions):
        # Pre-populate cache for context reuse across turns
```

---

## 3. Execution Flow

### 3.1 End-to-End Lifecycle

```
User Query: "What were our top customers last month and explain the trend?"
    │
    ▼
1. DETECTION (execution_service.py:478)
   profile_type == "genie" → route to _run_genie_execution()
    │
    ▼
2. VALIDATION (execution_service.py:688-723)
   ├── Check nesting depth limit
   ├── Validate genieConfig exists
   ├── Resolve child profile IDs to full profiles
   └── Verify LLM configuration exists
    │
    ▼
3. COORDINATOR INITIALIZATION (genie_coordinator.py:414-554)
   ├── Create SlaveSessionTool for each child profile
   ├── Merge component tools (TDA_Charting, etc.)
   ├── Load coordinator prompt (with profile overrides)
   ├── Inject available profiles into prompt
   ├── Build LangGraph ReAct agent
   └── Load existing child sessions into cache
    │
    ▼
4. EXECUTION (genie_coordinator.py:694-1006)
   ├── Emit execution_start event
   ├── Emit genie_coordination_start event
   ├── Apply KG enrichment to system prompt (if active)
   ├── Build message list: SystemMessage + history + HumanMessage
   │
   ├── astream_events loop:
   │   ├── on_llm_start → emit status_indicator_update (busy)
   │   ├── on_llm_end → track tokens, emit genie_llm_step
   │   │   ├── Step 1: "Routing Decision" (if has tool_calls)
   │   │   └── Step N: "Response Synthesis" (if no tool_calls)
   │   ├── on_tool_start → emit genie_component_invoked (if component)
   │   ├── on_tool_end → capture component payloads
   │   └── on_chain_end → extract final AI message
   │
   ├── Emit genie_synthesis_start
   ├── Emit genie_synthesis_complete (with response preview)
   ├── Emit genie_coordination_complete (with cost)
   └── Emit execution_complete
    │
    ▼
5. RESULT
   {
     coordinator_response: "Synthesized answer...",
     tools_used: ["invoke_TDAT", "invoke_CHAT"],
     slave_sessions: {"TDAT": "session-id-1", "CHAT": "session-id-2"},
     genie_events: [...],           // For plan reload
     component_payloads: [...],      // Chart/component render specs
     kg_enrichment_event: {...},     // KG data for persistence
     input_tokens: 5432,
     output_tokens: 1234,
     success: true
   }
```

### 3.2 Child Session Invocation Detail

When the LangGraph agent decides to invoke a child profile:

```
Agent calls invoke_TDAT("Show top customers last month")
    │
    ▼
SlaveSessionTool._arun() (line 92)
    │
    ├── Check if child is nested Genie → validate depth
    ├── Emit genie_slave_invoked event
    │
    ├── _get_or_create_slave_session() (line 181)
    │   ├── Check cache: _slave_session_cache[parent:profile_id]
    │   │   ├── HIT → reuse session_id (context preserved)
    │   │   └── MISS → POST /api/v1/sessions
    │   │       ├── Session created with genie_parent_session_id
    │   │       ├── Cache session_id for future reuse
    │   │       └── Execute session_primer if configured
    │   │
    ├── Emit genie_slave_progress (status: executing)
    │
    ├── _execute_and_poll() (line 319)
    │   ├── POST /api/v1/sessions/{id}/query
    │   ├── Poll GET /api/v1/tasks/{task_id}
    │   │   ├── completed → extract final_answer_text (clean text preferred over HTML)
    │   │   ├── failed → return error message
    │   │   └── timeout → return timeout message
    │   └── Forward child CCR events (rag_retrieval) to parent
    │
    ├── Emit genie_slave_completed (with duration, result)
    └── Return result text to agent
```

### 3.3 Session Context Reuse

The module-level `_slave_session_cache` dictionary enables context continuity across multiple coordinator turns:

```python
# Cache key: "{parent_session_id}:{child_profile_id}"
_slave_session_cache: Dict[str, str] = {}
```

**Turn 1:** Coordinator creates child session for @TDAT → cached.
**Turn 2:** Same coordinator session queries @TDAT again → reuses cached session. The child session retains its full conversation history from Turn 1.

At the start of each coordinator execution, `_run_genie_execution()` pre-populates the cache from the database:

```python
existing_slaves = await session_manager.get_genie_slave_sessions(session_id, user_uuid)
coordinator.load_existing_slave_sessions(existing_slaves)
```

---

## 4. Child Session Management

### Session Creation

Child sessions are created via REST API with genie metadata:

```python
POST /api/v1/sessions
{
    "profile_id": "child-profile-id",
    "genie_parent_session_id": "parent-session-id",
    "genie_slave_profile_id": "child-profile-id"
}
```

The session manager stores genie metadata on the session:

```python
# session_manager.py:273-278
"genie_metadata": {
    "is_genie_slave": True,
    "parent_session_id": "parent-session-id",
    "slave_profile_id": "child-profile-id",
    "slave_sequence_number": 0
}
```

### Session Link Recording

Parent-child relationships are persisted in `genie_session_links`:

```python
await record_genie_session_link(
    parent_session_id, slave_session_id,
    slave_profile_id, slave_profile_tag,
    user_uuid, execution_order, nesting_level
)
```

### Session Lifecycle Functions

| Function | Line | Purpose |
|----------|------|---------|
| `record_genie_session_link()` | 1796 | Persist parent-child relationship |
| `get_genie_slave_sessions()` | 1838 | Get all child sessions for a parent |
| `get_genie_parent_session()` | 1877 | Get parent info for a child session |
| `cleanup_genie_slave_sessions()` | 1915 | Cascade cleanup when parent deleted |
| `update_genie_slave_status()` | 1999 | Update child session status (active/completed/failed) |

### Session Primer Support

Child profiles can have a `session_primer` configuration that executes automatically when the session is first created (`SlaveSessionTool._get_or_create_slave_session()`, lines 221-263):

| Primer Format | Behavior |
|--------------|----------|
| String (legacy) | Execute as single query |
| Dict with `mode: "combined"` | Concatenate all statements, execute as one query |
| Dict with `mode: "sequential"` | Execute first statement only |
| Dict with `enabled: false` | Skip primer execution |

Primer failures are non-blocking — the main query proceeds regardless.

---

## 5. Nested Coordination

Genie profiles can coordinate other Genie profiles, creating multi-level AI orchestration.

### Depth Limiting

```
Level 0: @MASTER-GENIE (top-level coordinator)
    └── Level 1: @SUB-GENIE (child coordinator)
        └── Level 2: @EXPERT (leaf profile — can be any type)
            └── Level 3: BLOCKED (max depth reached)
```

**Compile-time validation** (`config_manager.py:1233-1322`):
- DFS traversal with path tracking detects circular dependencies
- Self-reference protection (profile cannot select itself as child)
- Maximum depth enforcement

**Runtime enforcement** (`genie_coordinator.py:103-123`):
- `SlaveSessionTool._arun()` checks `current_nesting_level + 1 >= max_depth`
- Blocked invocations emit `genie_slave_completed` with error

### Circular Dependency Detection

```python
def _detect_circular_genie_dependency(
    self, profile_id, slave_profiles, user_uuid,
    visited_path=None, depth=0, max_depth=3
) -> tuple[bool, str, int]:
```

**Algorithm:**
1. Maintain `visited_path` set (current traversal path)
2. Check if depth exceeds `max_depth`
3. For each child profile:
   - If `child_id in visited_path` → circular dependency detected
   - If child is `genie` type → recursive DFS with `visited_path.copy()`
4. Return `(has_error, error_message, max_depth_found)`

**Error messages include full cycle path:** `"Circular dependency detected: @MASTER → @SUB → @MASTER"`

---

## 6. Configuration & Three-Tier Settings

### Genie Profile Configuration

```json
{
    "id": "profile-genie-master",
    "profile_type": "genie",
    "name": "Master Coordinator",
    "tag": "GENIE",
    "description": "Coordinates multiple expert profiles",
    "llmConfigurationId": "llm-config-id",
    "genieConfig": {
        "slaveProfiles": ["profile-id-1", "profile-id-2"],
        "temperature": 0.7,
        "queryTimeout": 300,
        "maxIterations": 10
    }
}
```

### Three-Tier Resolution

Settings follow the standard Uderia three-tier configuration:

```
Admin Lock (is_locked = TRUE)
    → Enforced globally, no overrides
    ↓ (if not locked)
Profile Override (genieConfig)
    → Per-profile customization
    ↓ (if not set)
Global Default (genie_global_settings)
    → System-wide fallback
```

### Configuration Parameters

| Parameter | Global Default | Range | Description |
|-----------|---------------|-------|-------------|
| `temperature` | `0.7` | 0.0–1.0 | LLM temperature for coordinator reasoning |
| `queryTimeout` | `300` | 60–900 | Timeout per child session query (seconds) |
| `maxIterations` | `10` | 1–25 | Maximum LangGraph agent iterations |
| `maxNestingDepth` | `3` | 1–10 | Maximum nested Genie depth |

### Effective Config Resolution

`config_manager.get_effective_genie_config(genie_config)` merges profile-level overrides with global settings, respecting admin locks.

---

## 7. Prompt Resolution

### Coordinator System Prompt

The coordinator's system prompt is loaded via `ProfilePromptResolver`:

```python
resolver = ProfilePromptResolver(profile_id=genie_profile.get("id"))
system_prompt = resolver.get_genie_coordinator_prompt()
```

**Resolution chain** (`profile_prompt_resolver.py:180-195`):
1. Check profile-level prompt mapping for `genie_coordination.coordinator_prompt`
2. Fall back to default prompt name `GENIE_COORDINATOR_PROMPT`
3. Load from `default_prompts` database table

**Dynamic injection** (`genie_coordinator.py:631-643`):
- `{available_profiles}` → Tool descriptions for each child profile
- `{component_instructions_section}` → Component usage instructions (charting, etc.)

### Fallback Prompt

If database prompt is unavailable, a hardcoded fallback is used (`genie_coordinator.py:655-692`):

```
You are a Genie Coordinator that orchestrates specialized AI profiles...

### Coordination Rules
1. ANALYZE the user's question to determine best-suited profiles
2. ROUTE the query to appropriate profiles using invoke_* tools
3. SYNTHESIZE results into a coherent final response
4. SINGLE PROFILE OPTIMIZATION: Use only one profile if it suffices

### Important Behaviors
- Each tool invocation creates or reuses a real session
- Subsequent calls to the same profile reuse that session's context
- Be specific in sub-queries to get targeted results
```

### Tool Description Format

Each child profile is described to the LLM as:

```
@TAG (Profile Name): Description. Type: profile_type
```

Example: `@TDAT (Teradata Analyst): Queries Teradata databases for business data. Type: tool_enabled`

---

## 8. Component Integration

The coordinator can invoke component tools (e.g., `TDA_Charting`) directly, without routing through a child profile.

### Component Tool Merging

At initialization (`genie_coordinator.py:540-550`):

```python
from trusted_data_agent.components.manager import get_component_langchain_tools
component_tools = get_component_langchain_tools(profile_id, user_uuid, session_id)
self.tools.extend(component_tools)
self.component_tool_names = {t.name for t in component_tools}
```

### Component Event Emission

Component tool invocations emit dedicated events (`genie_coordinator.py:817-838`):
- `genie_component_invoked` — When a component tool starts
- `genie_component_completed` — When a component tool finishes (with `component_id`)

### Component Payload Capture

Component outputs (chart render specs, etc.) are captured via `extract_component_payload()` and returned in the result's `component_payloads` list for frontend rendering.

### Knowledge Graph Enrichment

Before execution, the coordinator checks for active Knowledge Graphs (`genie_coordinator.py:745-764`):

```python
kg_text, kg_details = await get_component_context_enrichment(
    query=query, profile_id=profile_id, user_uuid=user_uuid
)
if kg_text:
    self.system_prompt += f"\n\n{kg_text}"
```

KG enrichment data (entities, relationships) is emitted as a `kg_enrichment` event and persisted with turn data.

---

## 9. Event System & Observability

### Event Lifecycle

All events flow through a collecting callback that both forwards to SSE and stores for plan reload:

```python
def collecting_callback(event_type, payload):
    # Skip transient events (status_indicator_update, token_update)
    if event_type not in _TRANSIENT_EVENT_TYPES:
        self.collected_events.append({"type": event_type, "payload": dict(payload)})
    # Track profile invocations
    if event_type == "genie_slave_invoked":
        self.invoked_profiles.append(payload.get("profile_tag"))
    # Forward to SSE
    event_callback(event_type, payload)
```

### Event Types

| Event | Source | Payload Keys | When |
|-------|--------|-------------|------|
| `execution_start` | Coordinator | `profile_type`, `query`, `available_slaves` | Execution begins |
| `genie_coordination_start` | Coordinator | `session_id`, `profile_tag`, `slave_profiles[]` | Coordinator initialized |
| `genie_llm_step` | Coordinator | `step_number`, `step_name`, `input_tokens`, `output_tokens`, `cost_usd` | Each LLM call |
| `genie_slave_invoked` | SlaveSessionTool | `profile_tag`, `query`, `nesting_level`, `is_nested_genie` | Child profile invoked |
| `genie_slave_progress` | SlaveSessionTool | `profile_tag`, `slave_session_id`, `status`, `message` | Child execution progress |
| `genie_slave_completed` | SlaveSessionTool | `profile_tag`, `result`, `duration_ms`, `success` | Child execution done |
| `genie_component_invoked` | Coordinator | `tool_name` | Component tool started |
| `genie_component_completed` | Coordinator | `tool_name`, `component_id`, `success` | Component tool done |
| `genie_synthesis_start` | Coordinator | `profiles_consulted[]` | Synthesis phase begins |
| `genie_synthesis_complete` | Coordinator | `synthesized_response`, `success` | Synthesis done |
| `genie_coordination_complete` | Coordinator | `total_duration_ms`, `profiles_used[]`, `cost_usd`, `success` | Everything done |
| `execution_complete` | Coordinator | `experts_consulted`, `tools_used[]`, `duration_ms` | Lifecycle event |
| `execution_error` | Coordinator | `error_message`, `error_type` | On failure |
| `kg_enrichment` | Coordinator | `total_entities`, `total_relationships` | KG context injected |

### Cost Tracking

Coordinator LLM calls track cost independently from child session costs:

```python
cost_manager = CostManager()
call_cost = cost_manager.calculate_cost(
    provider=self.provider, model=self.model,
    input_tokens=input_tokens, output_tokens=output_tokens
)
```

Both per-call and per-turn cost are emitted via events and persisted to turn data.

### Error Classification

On execution failure, errors are classified for lifecycle events (`genie_coordinator.py:1029-1036`):

| Error Pattern | Classification |
|--------------|---------------|
| "rate limit" or "429" | `rate_limit` |
| "quota" or "insufficient" | `quota_exceeded` |
| "timeout" | `timeout` |
| Everything else | `coordination_error` |

---

## 10. Frontend Architecture

### State Management (`genieHandler.js`)

```javascript
export const genieState = {
    activeCoordination: null,      // Current coordination session ID
    slaveProgress: {},             // {profile_tag: {status, name, id, sessionId, startTime, duration}}
    startTime: null,               // Timestamp when coordination started
    availableProfiles: [],         // Profiles available for this coordination
    profilesInvoked: [],           // Profiles that have been invoked
    profileTag: null               // Profile tag (e.g., "GENIE")
};
```

### Event Handler Functions

| Function | Trigger Event | Action |
|----------|--------------|--------|
| `initGenieCoordination()` | `genie_start`, `genie_coordination_start` | Initialize state, auto-expand child sessions |
| `updateRoutingDecision()` | `genie_routing_decision` | Store selected profiles |
| `updateSlaveInvoked()` | `genie_slave_invoked` | Track invocation, add to invoked list |
| `updateSlaveProgress()` | `genie_slave_progress` | Update progress, add child session to UI list |
| `updateSlaveCompleted()` | `genie_slave_completed` | Record status, duration, result |
| `updateSynthesisStart()` | `genie_synthesis_start` | Mark synthesis phase |
| `completeCoordination()` | `genie_coordination_complete` | Cleanup state, keep sessions expanded |

### Visual Design

Coordination details are shown **only in the Live Status window**, not inline in chat. This keeps the conversation pane clean while the status panel shows the "how" (routing decisions, timing, child invocations).

**Session hierarchy in sidebar:**
- Parent Genie session shows a master badge
- Child sessions are nested below their parent with tree structure
- Child sessions can be collapsed/expanded (persisted via `localStorage`)
- Auto-expand during execution for visibility
- Visual feedback: orange highlight on start, green highlight on completion

### Event Title Rendering (`eventHandlers.js:759-813`)

| Event Type | Display Title |
|-----------|--------------|
| `genie_coordination_start` | "Coordinator Started" |
| `genie_llm_step` (routing) | "LLM Routing Execution" |
| `genie_llm_step` (synthesis) | "LLM Synthesis Execution" |
| `genie_slave_invoked` | "Invoking Expert: @{TAG}" |
| `genie_slave_completed` (success) | "Expert @{TAG} Completed (2.3s)" |
| `genie_slave_completed` (failed) | "Expert @{TAG} Failed" |
| `genie_synthesis_start` | "LLM Synthesis Started" |
| `genie_synthesis_complete` | "LLM Synthesis Results" |
| `genie_coordination_complete` | "Coordinator Complete" / "Coordinator Failed" |

### Split View Integration

Child sessions can be opened in split view for side-by-side inspection:

```javascript
export function openGenieSplitView(sessionId, profileTag) {
    window.dispatchEvent(new CustomEvent('openGenieSplitView', {
        detail: { sessionId, profileTag }
    }));
}
```

---

## 11. Database Schema

### `genie_session_links` Table (`schema/07_genie_profiles.sql`)

Tracks parent-child session relationships for coordination.

```sql
CREATE TABLE IF NOT EXISTS genie_session_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id TEXT NOT NULL,       -- Genie coordinator session
    slave_session_id TEXT NOT NULL,        -- Child session ID
    slave_profile_id TEXT NOT NULL,        -- Profile used for child
    slave_profile_tag TEXT,                -- Profile tag (e.g., @CHAT, @RAG)
    user_uuid TEXT NOT NULL,               -- User who owns both sessions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active',          -- active, completed, failed
    execution_order INTEGER DEFAULT 0,     -- Order in which child was invoked
    nesting_level INTEGER DEFAULT 0,       -- Depth in nested hierarchy
    archived BOOLEAN DEFAULT 0,            -- Archived flag
    UNIQUE(parent_session_id, slave_session_id)
);

CREATE INDEX IF NOT EXISTS idx_genie_parent ON genie_session_links(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_genie_slave ON genie_session_links(slave_session_id);
CREATE INDEX IF NOT EXISTS idx_genie_user ON genie_session_links(user_uuid);
CREATE INDEX IF NOT EXISTS idx_genie_nesting_level ON genie_session_links(nesting_level);
```

### `genie_global_settings` Table (`schema/08_genie_global_settings.sql`)

System-wide defaults with admin lock support.

```sql
CREATE TABLE IF NOT EXISTS genie_global_settings (
    id INTEGER PRIMARY KEY,
    setting_key TEXT NOT NULL UNIQUE,       -- Setting identifier
    setting_value TEXT NOT NULL,            -- Value stored as string
    is_locked BOOLEAN DEFAULT FALSE,        -- If TRUE, profile overrides disabled
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT                          -- User UUID who last updated
);

-- Default Genie settings
INSERT OR IGNORE INTO genie_global_settings (setting_key, setting_value, is_locked) VALUES
    ('temperature', '0.7', 0),
    ('queryTimeout', '300', 0),
    ('maxIterations', '10', 0),
    ('maxNestingDepth', '3', 0);
```

---

## 12. REST API Endpoints

### Genie Profile Resolution

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/profiles/{id}/tools` | GET | Returns empty tools + child profile metadata for genie profiles |

**Response for genie profile** (`routes.py:779-796`):

```json
{
    "tools": {},
    "profile_type": "genie",
    "profile_tag": "GENIE",
    "slave_profiles": [
        {"id": "profile-1", "name": "Chatbot", "tag": "CHAT"},
        {"id": "profile-2", "name": "Analyst", "tag": "TDAT"}
    ]
}
```

### Query Execution

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ask_stream` | POST | SSE streaming execution (routes to `_run_genie_execution`) |
| `/api/v1/sessions/{id}/query` | POST | REST execution (used by child session REST calls) |

### Child Session Internal API

Child sessions are created and queried via the standard session/task REST API:

| Endpoint | Method | Used By |
|----------|--------|---------|
| `/api/v1/sessions` | POST | `SlaveSessionTool._get_or_create_slave_session()` |
| `/api/v1/sessions/{id}/query` | POST | `SlaveSessionTool._execute_and_poll()` |
| `/api/v1/tasks/{id}` | GET | `SlaveSessionTool._execute_and_poll()` (polling) |

---

## 13. Safety Mechanisms

### Profile Validation (`config_manager.py:1176-1322`)

| Check | Scope | Action |
|-------|-------|--------|
| `genieConfig` required | Profile creation | Reject profile if missing |
| Self-reference | Profile creation | Reject if profile references itself as child |
| Circular dependency | Profile creation | DFS traversal detects A → B → A cycles |
| Max nesting depth | Profile creation | DFS traversal checks depth limit |
| Missing child profiles | Profile execution | Warning logged, profile skipped |
| No valid children | Profile execution | Error returned to user |
| No LLM configuration | Profile execution | Error returned to user |

### Runtime Safeguards

| Check | Location | Action |
|-------|----------|--------|
| Nesting depth at execution | `_run_genie_execution():691` | Block execution if `level >= max_depth` |
| Nesting depth at invocation | `SlaveSessionTool._arun():109` | Return error if child Genie would exceed depth |
| Query timeout | `SlaveSessionTool._execute_and_poll()` | Timeout after `queryTimeout` seconds |
| Agent iteration limit | `create_react_agent` config | `recursion_limit = maxIterations * 2` |
| Internal authentication | `_run_genie_execution():757` | Child REST calls use internally-generated auth tokens |

### Event Collection Safety

Transient UI-only events (`status_indicator_update`, `token_update`) are filtered from the collected events to prevent cluttering plan reload and turn data persistence.

---

## 14. Pass-Through Optimisation

When only **one expert** is consulted and the coordinator has **no prior conversation history** to weave, the coordinator skips the synthesis LLM call entirely and passes the expert's answer directly to the user. This halves token cost and latency for single-expert queries.

### Trigger Conditions

| Condition | Synthesis? | Reason |
|-----------|------------|--------|
| Single expert + no history | ❌ Pass through | Expert answer is already complete prose; no multi-source combining needed |
| Multiple experts (any mode) | ✅ Yes | Results from different domains must be combined |
| Single expert + history present (Full Context, turn 2+) | ✅ Yes | Coordinator weaves cross-turn context |

`conversation_history` is empty (triggering pass-through) in two situations:
- **Full Context mode, turn 1** — no prior turns exist yet
- **Turn Summaries mode, any turn** — history is always disabled in this mode

### Implementation

**File:** `genie_coordinator.py` — inside the `on_tool_end` event handler

```python
elif (
    _routing_tool_call_count == 1           # exactly one expert invoked
    and self.llm_call_count == 1            # no re-dispatch: still first LLM iteration
    and event_name not in self.component_tool_names  # it's a slave tool
    and not conversation_history             # no cross-turn context to weave
    and self.invoked_profiles               # expert tag captured
):
    # Break before synthesis LLM fires
    output = tool_output
    _passed_through = True
```

The condition `llm_call_count == 1` prevents the optimisation from firing when the coordinator re-dispatches to the same expert a second time (which increments `llm_call_count` to 2).

### Rich HTML Pass-Through

`tool_enabled` experts produce rich HTML output (tables, charts, formatted reports) but return only a plain-text summary (`final_answer_text`) to the coordinator's tool layer. To preserve the rich rendering, `SlaveSessionTool` caches the full HTML response keyed by `parent_session_id:profile_tag`. The pass-through path reads this cache and delivers the rich HTML to the user:

```python
# SlaveSessionTool._execute_and_poll()
html_response = result.get("final_answer") or final_response
if html_response and html_response != final_response:
    _slave_html_responses[f"{self.parent_session_id}:{self.profile_tag}"] = html_response

# GenieCoordinator pass-through path
html_key = f"{self.parent_session_id}:{invoked_tag}"
_passed_through_html = _slave_html_responses.pop(html_key, None)
```

### All Profile Types Qualify

`tool_enabled`, `llm_only`, `rag_focused`, and nested `genie` experts all qualify. `tool_enabled` experts run their own internal Fusion Optimizer synthesis — the coordinator receives a finished answer, not raw data — so there is no multi-source combining to perform.

---

## 15. Skills Injection

The Coordinator supports pre-processing skills just like other profile types. Skills can inject routing rules, domain expertise, or behavioral instructions directly into the coordinator's LLM context.

### How It Works

`execution_service.py` resolves skills for **all** profile types (including `genie`) before routing to the coordinator. The resolved `SkillResult` is passed to `GenieCoordinator.__init__()` as `skill_result`.

```python
# execution_service.py — skill resolution applies to genie profiles too
skill_result = skill_manager.resolve_skills(resolved_specs)
final_result_payload = await _run_genie_execution(
    ...,
    skill_result=skill_result,  # passed through to GenieCoordinator
)
```

Inside the coordinator, skill content is injected at two points:

**System prompt injection** (`genie_coordinator.py:686-698`):
```python
if self.skill_result and self.skill_result.has_content:
    skill_block = self.skill_result.get_system_prompt_block()
    if skill_block:
        system_prompt += f"\n\n{skill_block}"
```

**User context injection** (prepended to the query sent to the LangChain agent):
```python
uc_block = self.skill_result.get_user_context_block() if self.skill_result else ""
human_content = f"{uc_block}\n\n{query}" if uc_block else query
messages.append(HumanMessage(content=human_content))
```

### Typical Use Cases

| Skill Type | `injection_target` | Example |
|------------|-------------------|---------|
| Routing rules | `system_prompt` | `teradata-coordinator` — Teradata domain routing (TDSQL, TDDIC, TDADM, TDEXO) |
| Query pre-processing | `user_context` | `teradata-sql-expert` — SQL dialect rules prepended to the query |

### Skills are Transient

Skill content injected into the coordinator follows the same transience rules as all other profile types: it is injected into **local variables** per-request and never stored in `chat_object` or any persistent session file. See [Skill Architecture — Section 6](SKILL_ARCHITECTURE.md#6-skill-lifecycle--transience) for details.

### Profile Configuration

Skills are assigned to a genie profile via `skillsConfig.skills[]` in the profile configuration (same structure as other profile types). Skills with `active: true` are resolved and injected automatically. The coordinator profile's skills tab in the Setup UI provides the same skill assignment interface as other profiles.

---

## 16. File Reference

### Backend

| File | Purpose | Key Components |
|------|---------|---------------|
| `src/trusted_data_agent/agent/genie_coordinator.py` | Coordinator engine | `GenieCoordinator`, `SlaveSessionTool`, pass-through at `on_tool_end`, skill injection at lines 686-698 |
| `src/trusted_data_agent/agent/execution_service.py` | Genie routing | `_run_genie_execution()` (line 655), skill resolution for genie (line 479), `skill_result` passthrough (line 567) |
| `src/trusted_data_agent/agent/profile_prompt_resolver.py` | Prompt loading | `get_genie_coordinator_prompt()` (line 180) |
| `src/trusted_data_agent/agent/prompt_mapping.py` | Prompt mapping | `genie_coordination` category (line 124) |
| `src/trusted_data_agent/core/config_manager.py` | Profile validation | Genie validation (line 1176), circular dependency detection (line 1233) |
| `src/trusted_data_agent/core/session_manager.py` | Session lifecycle | Genie session link CRUD (lines 1796-1999) |
| `src/trusted_data_agent/api/routes.py` | REST endpoints | Genie profile tool resolution (line 779) |
| `src/trusted_data_agent/llm/langchain_adapter.py` | LLM creation | `create_langchain_llm()` for coordinator LLM |
| `src/trusted_data_agent/auth/security.py` | Internal auth | `create_internal_token()` for child REST calls |
| `src/trusted_data_agent/core/cost_manager.py` | Cost tracking | Coordinator LLM call cost calculation |

### Frontend

| File | Purpose | Key Components |
|------|---------|---------------|
| `static/js/handlers/genieHandler.js` | State tracking | `genieState`, event handler functions, split view |
| `static/js/eventHandlers.js` | Event rendering | `getGenieTitle()` (line 759), lifecycle titles |
| `static/js/ui.js` | Status rendering | `_renderGenieStep()` (line 1986), session hierarchy (line 473) |
| `static/js/notifications.js` | Event dispatch | Genie event routing to handler |

### Database

| File | Tables |
|------|--------|
| `schema/07_genie_profiles.sql` | `genie_session_links` |
| `schema/08_genie_global_settings.sql` | `genie_global_settings` |

---

## Related Documents

- [Nested Genie Upgrade Guide](NESTED_GENIE_UPGRADE_GUIDE.md) — Installation and configuration for nested coordination
- [Component Architecture](COMPONENT_ARCHITECTURE.md) — Component tools available to the coordinator
- [Context Window Architecture](CONTEXT_WINDOW_ARCHITECTURE.md) — Context window management for genie profile type
- [Knowledge Graph Architecture](KNOWLEDGE_GRAPH_ARCHITECTURE.md) — KG enrichment injected into coordinator context
- [Cost Tracking Architecture](COST_TRACKING_ARCHITECTURE.md) — Cost calculation for coordinator LLM calls
- [Skill Architecture](SKILL_ARCHITECTURE.md) — Full skill system documentation including coordinator injection (Section 5) and Agent Pack bundling (Section 14)
