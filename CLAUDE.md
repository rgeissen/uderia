# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Uderia Platform** - Enterprise-grade AI orchestration platform with cloud-level reasoning and zero-trust privacy. The platform provides a multi-provider LLM agent system with MCP (Model Context Protocol) integration, RAG-powered continuous improvement, and comprehensive multi-user authentication.

## Development Commands

### Running the Application

```bash
python -m trusted_data_agent.main

# Access at: http://localhost:5050
# Default credentials: admin / admin (CHANGE IMMEDIATELY!)
```

**Note:** When adding LLM configurations, use the model filter toggle (Recommended/All) to switch between recommended models and all available models from the provider.

### Testing Functionality via REST API

The REST API provides a programmatic way to test features without using the UI. This is especially useful for:
- Automated testing of token counting, cost tracking, and other analytics
- Validating fixes for specific providers (e.g., FriendliAI, Azure, etc.)
- Integration testing with external systems
- Performance benchmarking

#### Quick Test Workflow

```bash
# 1. Start the server in background
python -m trusted_data_agent.main > /tmp/uderia_server.log 2>&1 &
sleep 5  # Wait for startup

# 2. Authenticate and get JWT token
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

echo "JWT obtained: ${JWT:0:50}..."

# 3. Create a session (uses default profile)
SESSION_RESPONSE=$(curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{}')

SESSION_ID=$(echo "$SESSION_RESPONSE" | jq -r '.session_id')
echo "Session created: $SESSION_ID"

# 4. Submit a query
TASK_RESPONSE=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How many databases are on the system?"}')

TASK_ID=$(echo "$TASK_RESPONSE" | jq -r '.task_id')
echo "Task submitted: $TASK_ID"

# 5. Poll for results (wait for completion)
sleep 5

RESULT=$(curl -s -X GET "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT")

# 6. Extract and verify token counts
echo "$RESULT" | python3 -c "
import json, sys
data = json.load(sys.stdin)

print('\n=== TOKEN COUNTING VERIFICATION ===\n')

# Extract LLM step events
llm_steps = [e for e in data['events'] if e['event_type'] == 'notification' and
             e.get('event_data', {}).get('type') == 'conversation_llm_step']

for i, step in enumerate(llm_steps, 1):
    payload = step['event_data']['payload']
    print(f'Step #{i}: {payload[\"step_name\"]}')
    print(f'  Input tokens:  {payload[\"input_tokens\"]:,}')
    print(f'  Output tokens: {payload[\"output_tokens\"]:,}')

# Extract totals
token_updates = [e for e in data['events'] if e['event_type'] == 'token_update']
if token_updates:
    final = token_updates[-1]['event_data']
    print(f'\nTOTAL TOKENS: {final[\"total_input\"]:,} in / {final[\"total_output\"]:,} out')
"

# 7. Cleanup
pkill -f "python -m trusted_data_agent.main"
```

#### Testing Specific Features

**Test Token Counting for a Specific Provider:**
```bash
# After creating session, check which provider is being used
curl -s -X GET "http://localhost:5050/api/v1/sessions/$SESSION_ID" \
  -H "Authorization: Bearer $JWT" | jq '.profile_id, .provider'

# Submit query and verify token counts are non-zero
# This is especially useful for testing FriendliAI, Azure, or new providers
```

**Test RAG Collection Retrieval:**
```bash
# Create session, then submit a query that should trigger RAG
TASK_RESPONSE=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Show me all products with low inventory"}')

# Check events for champion_cases_retrieved event
curl -s -X GET "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT" | jq '.events[] | select(.event_type == "champion_cases_retrieved")'
```

**Test Profile Override:**
```bash
# Submit query with temporary profile override using @TAG syntax
TASK_RESPONSE=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "@CHAT What is the capital of France?"}')

# Verify profile was overridden
curl -s -X GET "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT" | jq '.events[] | select(.event_type == "notification") | select(.event_data.type == "user_message_profile_tag")'
```

**Test Cost Tracking:**
```bash
# After query completion, check cost calculation
curl -s -X GET "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT" | jq '.events[] | select(.event_type == "notification") | select(.event_data.type == "conversation_agent_complete") | .event_data.payload | {input_tokens, output_tokens}'

# Check server logs for cost calculation
tail -50 /tmp/uderia_server.log | grep "Cost Tracking"
```

#### Common Testing Patterns

**Batch Testing Multiple Queries:**
```bash
for query in "List databases" "Show tables" "Count rows"; do
  TASK_RESPONSE=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
    -H "Authorization: Bearer $JWT" \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"$query\"}")

  TASK_ID=$(echo "$TASK_RESPONSE" | jq -r '.task_id')
  echo "Submitted: $query (Task: $TASK_ID)"
  sleep 3
done
```

**Verify Session Persistence:**
```bash
# Submit first query
curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What databases are available?"}'

sleep 5

# Submit follow-up query (should have context from first)
curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Show me the tables in the first one"}'

# Check session files for conversation history
cat tda_sessions/$SESSION_ID/conversation.json | jq '.chat_object | length'
```

**Debug Server Logs:**
```bash
# Watch logs in real-time during testing
tail -f /tmp/uderia_server.log | grep -E "(Token|usage_metadata|Cost Tracking)"

# Check for specific errors or warnings
grep -A 5 "ERROR" /tmp/uderia_server.log | tail -30
grep -A 2 "Found usage_metadata" /tmp/uderia_server.log
```

#### Prerequisites for REST Testing

Before running REST tests, ensure:
1. **Default profile is configured** - Set via UI: Setup → Profiles → Set as Default
2. **LLM credentials are valid** - Test via UI: Setup → LLM Configurations → Test Connection
3. **MCP server is accessible** - Check logs for "MCP server initialized" message
4. **Database is bootstrapped** - First run auto-creates schema from `schema/*.sql`

For full REST API documentation, see [docs/RestAPI/restAPI.md](docs/RestAPI/restAPI.md).

### Installation & Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install in editable mode (REQUIRED - must be run from project root)
pip install -e .

# Regenerate JWT secret (CRITICAL SECURITY STEP)
python maintenance/regenerate_jwt_secret.py
```

### Testing

```bash
# Run specific test files
python test/test_access_tokens.py
python test/test_bedrock_connectivity.py
python schema/dev/test_prompt_encryption.py

# Test with PYTHONPATH
PYTHONPATH=/Users/livin2rave/my_private_code/uderia/src python test/<test_file>.py
```

### Database Management

```bash
# Database files
tda_auth.db              # User authentication, credentials, configuration
tda_sessions/            # Session data per user
schema/*.sql             # Schema definitions (read-only)

# Bootstrap encrypted prompts
schema/default_prompts.dat  # Encrypted system prompts (84KB)
```

## Architecture Overview

### High-Level System Design

```
┌──────────┐      ┌─────────────┐      ┌──────────┐      ┌─────┐      ┌─────────┐
│  Browser │ SSE  │   Backend   │ HTTP │   LLM    │ HTTP │ MCP │ SQL  │ Data    │
│   (UI)   │◄────►│   (Quart)   │─────►│ Provider │      │ Svr │─────►│ Source  │
└──────────┘      └─────────────┘      └──────────┘      └─────┘      └─────────┘
```

### Core Module Structure

- **`src/trusted_data_agent/agent/`** - Agent execution engine
  - `executor.py` - Main orchestrator with Fusion Optimizer
  - `planner.py` - Strategic & tactical planning logic
  - `phase_executor.py` - Individual phase execution
  - `orchestrators.py` - Specialized execution patterns
  - `formatter.py` - Response formatting & rendering
  - `prompt_loader.py` - Database-backed prompt system with tier-based access
  - `prompt_encryption.py` - License-based encryption (runtime vs UI access)
  - `profile_prompt_resolver.py` - Profile-specific prompt resolution
  - `rag_retriever.py` - RAG case retrieval
  - `repository_constructor.py` - RAG template plugins

- **`src/trusted_data_agent/llm/`** - Multi-provider LLM integration
  - `handler.py` - Unified LLM interface with profile support
  - `client_factory.py` - Provider-specific client creation

- **`src/trusted_data_agent/mcp_adapter/`** - MCP protocol client
  - `adapter.py` - Tool/prompt/resource discovery & execution

- **`src/trusted_data_agent/api/`** - REST & SSE endpoints
  - `routes.py` - Interactive UI endpoints (SSE streaming)
  - `rest_routes.py` - Async REST API (task-based)
  - `auth_routes.py` - Authentication (JWT + OAuth)
  - `admin_routes.py` - User management
  - `system_prompts_routes.py` - Prompt editing (PE/Enterprise only)
  - `knowledge_routes.py` - Knowledge repository management

- **`src/trusted_data_agent/auth/`** - Authentication & authorization
  - `database.py` - User database initialization
  - `middleware.py` - JWT validation & decorators
  - `encryption.py` - Fernet credential encryption
  - `oauth_handlers.py` - Google/GitHub OAuth
  - `email_verification.py` - Email verification flow
  - `consumption_enforcer.py` - Rate limiting & quotas
  - `rate_limiter.py` - Token-bucket rate limiting

- **`src/trusted_data_agent/core/`** - Configuration & state
  - `config.py` - Global configuration (APP_CONFIG, APP_STATE)
  - `config_manager.py` - Database-backed config management
  - `session_manager.py` - Session persistence & context
  - `cost_manager.py` - LLM cost tracking & analytics
  - `collection_db.py` - ChromaDB RAG collections

- **`static/js/`** - Frontend JavaScript
  - `adminManager.js` - User tier management UI
  - `handlers/` - Feature-specific handlers (RAG, marketplace, etc.)

### Key Architectural Patterns

#### 1. License-Based Prompt Encryption

**Critical Understanding**: The system has tier-based access for system prompts:

- **Runtime access** (all tiers): All users can decrypt prompts for LLM conversations
- **UI access** (PE/Enterprise only): Only privileged tiers can view/edit prompts in UI

Functions:
- `can_access_prompts(tier)` - Always returns True (runtime decryption)
- `can_access_prompts_ui(tier)` - Returns True only for PE/Enterprise (UI editing)

Files: `src/trusted_data_agent/agent/prompt_encryption.py`, `prompt_loader.py`

#### 2. Profile System Architecture

**Profiles combine MCP Server + LLM Provider** into reusable configurations:

- **Default profile**: Used for all queries unless overridden
- **Temporary override**: `@TAG` syntax for single-query profile switching
- **Profile classification**: Light (filter-based) vs Full (LLM-assisted)

**The platform supports 4 profile types:**

1. **Efficiency Focused (Optimizer)** - `tool_enabled`
   - Runs through Planner/Executor Architecture
   - Strategic & tactical planning with RAG-powered learning
   - Token-optimized with plan hydration
   - Best for: Database queries, complex workflows, multi-step operations

2. **Conversation Focused (LLM)** - `llm_only`
   - Direct LLM conversation
   - Optional tool calling via LangChain (useMcpTools flag)
   - No strategic planning overhead
   - Best for: Chat, document Q&A, lightweight tasks

3. **Knowledge Focused (RAG)** - `rag_focused`
   - Semantic search over knowledge repositories
   - LLM synthesis of retrieved documents
   - No MCP tools or Planner/Executor
   - Best for: Documentation search, reference lookups

4. **Genie (Multi-Profile)** - `genie`
   - Coordinates multiple sub-profiles
   - Routes queries to specialized experts
   - Synthesizes results across profiles
   - Best for: Complex multi-domain questions

Session data tracks:
- `profile_id` - Current active profile
- `profile_tag` - Current profile tag
- `profile_tags_used[]` - History of all profiles used
- `models_used[]` - History of all LLM providers/models used

Files: `src/trusted_data_agent/agent/executor.py`, `profile_prompt_resolver.py`

#### 3. Multi-User Authentication Flow

```
1. User login → JWT issued (24h) or OAuth flow
2. Credentials encrypted (Fernet) → Stored per-user in tda_auth.db
3. Profiles associated with user account
4. Session isolation by user UUID
5. Bootstrap configuration copied on first login
```

- **JWT tokens**: Web UI sessions (24-hour expiry)
- **Access tokens**: Long-lived REST API tokens (90 days or never)
- **User tiers**: `user`, `developer`, `admin` (controls feature access)

Files: `src/trusted_data_agent/auth/middleware.py`, `database.py`, `auth_routes.py`

#### 4. RAG System (Retrieval-Augmented Generation)

**Two repository types**:
- **Planner Repositories**: Execution strategies and proven patterns
- **Knowledge Repositories**: Reference documents and domain knowledge

**Template plugins** (`rag_templates/`):
- Self-contained modules with manifests
- SQL query templates, document Q&A
- Auto-generation via LLM assistance

Files: `src/trusted_data_agent/agent/rag_retriever.py`, `repository_constructor.py`, `rag_template_manager.py`

#### 5. Fusion Optimizer Execution Flow

```
User Query → Strategic Plan → Tactical Execution → Tool Calls → Response Synthesis
                  ↓                    ↓
              RAG Retrieval     Plan Hydration
              (champion cases)  (context injection)
```

- **Strategic planning**: High-level meta-plan (phases)
- **Tactical execution**: Single-step tool selection (per phase)
- **Self-correction**: Error recovery with targeted prompts
- **Plan hydration**: Inject previous turn results to skip redundant calls

Files: `src/trusted_data_agent/agent/executor.py`, `planner.py`, `phase_executor.py`

#### 6. Context Window Management

The platform maintains sophisticated context window management to optimize token usage, ensure data isolation, and enable multi-turn conversations.

**Three-History System:**
Each session maintains three synchronized histories:
- **`chat_object`**: Plain text for LLM context (what gets sent to providers)
- **`session_history`**: HTML-formatted for UI display
- **`workflow_history`**: Execution traces for planner context

**Context Modes:**
- **Full Context** (default): Sends entire `chat_object` history to LLM
- **Turn Summaries**: Sends only workflow summaries (hold `Alt` for single query, `Shift+Alt` to lock)

**Implemented Optimizations:**

| Optimization | Mechanism | Savings |
|--------------|-----------|---------|
| Tool condensation | Names-only after first turn | 60-70% of tool context |
| History condensation | Remove duplicates, clean capabilities | 10-20% of history |
| Context distillation | Summarize large tool outputs (>500 rows) | 99%+ of large results |
| Plan hydration | Inject previous results, skip re-fetch | 30-50% on multi-turn |

**Profile-Specific Context:**

| Profile Type | Context Strategy |
|--------------|------------------|
| `tool_enabled` | Full tools + RAG cases + workflow history |
| `llm_only` | Empty tools, session history only |
| `rag_focused` | No tools, mandatory knowledge retrieval |
| `genie` | Child profile descriptions, limited parent history |

**Token Tracking:**
- Actual tokens extracted from LLM provider responses (not pre-estimated)
- Per-turn and per-session accumulation
- Cost calculation with provider-specific pricing

**Future: IFOC Methodology Context Isolation (P0 Enterprise)**
Planned feature for isolated context windows per methodology phase (Ideate/Focus/Operate/Complete) to ensure data sovereignty. When transitioning between phases (especially backward transitions), earlier phases remain pristine without visibility into later phase artifacts.

**Detailed Documentation:** [docs/Architecture/CONTEXT_WINDOW_ARCHITECTURE.md](docs/Architecture/CONTEXT_WINDOW_ARCHITECTURE.md)

Files: `src/trusted_data_agent/llm/handler.py`, `core/session_manager.py`, `agent/executor.py`

#### 6.1. Date Range Orchestrator

**Execution-Time Optimization** for temporal queries:

The Date Range Orchestrator automatically handles queries with relative time periods ("past 2 days", "last week", "yesterday", "today") by:
1. Calling `TDA_CurrentDate` to establish temporal context
2. Iterating the selected tool across each date in the range
3. Consolidating results and returning to the planner

**Example Execution:**

```
User Query: "Show system utilization for the past 2 days"

Strategic Plan Phase:
{
  "goal": "Get system usage",
  "relevant_tools": ["dba_resusageSummary"],
  "arguments": {"date": {"source": "date_range", "duration": 2}}
}

Orchestrator Execution:
1. TDA_CurrentDate → "2026-02-09"
2. dba_resusageSummary(date="2026-02-07") → 10 rows
3. dba_resusageSummary(date="2026-02-08") → 0 rows
4. Consolidate → Return merged results to planner
```

**Implementation:** `src/trusted_data_agent/agent/orchestrators.py` (lines 23-211: execute_date_range_orchestrator)

**Session File Impact:**

Orchestrated calls appear in `execution_trace` wrapped by `TDA_SystemOrchestration` events. Performance testing frameworks must parse this structure to accurately count tool usage:

```json
{
  "execution_trace": [
    {
      "action": {
        "tool_name": "TDA_SystemOrchestration",
        "orchestrator_type": "date_range",
        "wrapped_tool_calls": [
          {"tool": "TDA_CurrentDate", "result": "2026-02-09"},
          {"tool": "dba_resusageSummary", "date": "2026-02-07"},
          {"tool": "dba_resusageSummary", "date": "2026-02-08"}
        ]
      }
    }
  ]
}
```

**Plan Quality Validation:**

The testing framework (profile-perf skill) no longer flags missing `TDA_CurrentDate` when the Date Range Orchestrator handles temporal context at execution time. This is properly annotated as an INFO-level event (not an error) indicating the optimization is functioning correctly.

**Other Orchestrators:**
- **Column Iteration Orchestrator**: Iterates tool calls across table columns for comprehensive analysis
- **Hallucinated Loop Orchestrator**: Processes LLM-generated loop structures when the LLM creates a loop that wasn't in the strategic plan

Files: `src/trusted_data_agent/agent/orchestrators.py`, `phase_executor.py`

---

### 7. Session Isolation & Live Status Panel

The platform supports **concurrent session execution** — users can submit queries in multiple sessions and switch between them while execution is in progress. Full isolation ensures each session's UI state (chat canvas, Live Status window, token counters, execution indicators) remains independent.

#### Dual SSE Channel Architecture

Two event channels deliver real-time updates to the frontend:

| Channel | Mechanism | Scope | Session Guard |
|---------|-----------|-------|---------------|
| `/ask_stream` | `fetch()` per request | Per-request stream | `processStream()` checks `state.currentSessionId === originSessionId` before rendering |
| `/api/notifications/subscribe` | `EventSource` singleton | Per-user (all sessions) | Event-type guards check `state.activeStreamSessions` and `payload.session_id` |

The per-request stream (`processStream` in `eventHandlers.js`) is the primary rendering path. It skips all DOM writes when the user is viewing a different session. The notification channel (`notifications.js`) carries duplicate and supplementary events; guards prevent cross-session pollution by skipping `status_indicator_update`, `rag_retrieval`, and `knowledge_retrieval*` events when streams are active or when the event's `session_id` doesn't match the viewed session.

#### Session UI Cache (Active Streams)

When switching **away** from a session that is still executing (`state.activeStreamSessions`), the frontend snapshots the full UI context into `state.sessionUiCache[sessionId]`:

| Cached State | Contents |
|-------------|----------|
| `chatHTML` | Full chat log `innerHTML` |
| `statusHTML` | Status window content `innerHTML` |
| `headerState` | Title, task ID, prompt/model display, thinking indicator, knowledge banner, all 6 token counters |
| `executionState` | `currentStatusId`, mode flags (`isGenieCoordinationActive`, `isConversationAgentActive`, `isInFastPath`, etc.), provider/model, pending events |
| `handlerState` | Module-level state from `genieHandler.js` (coordination progress, profiles invoked/consulted) and `conversationAgentHandler.js` (tool progress, tools used) |

When switching **back** to that session, the cache is restored in full — DOM, header, execution flags, handler state — and `processStream` resumes live rendering of new events.

When a stream **completes while viewing another session**, the `finally` block deletes the stale cache without touching global state (which belongs to the viewed session). The next switch to the completed session goes through the normal server load path.

#### Normal Load Path (Idle Sessions)

When switching to a session that is **not** actively streaming (no entry in `activeStreamSessions`, no cache), the session is loaded fresh from the server via `handleLoadSession()`:

1. Session history fetched from `/api/v1/sessions/{id}`
2. Chat messages rendered into `DOM.chatLog`
3. Status window reset to clean slate (title → "Live Status", tokens → session totals, knowledge banner hidden, all execution flags zeroed)
4. Handler module state reset via `cleanupCoordination()` and `cleanupExecution()`
5. **Auto-load last turn**: The last `.clickable-avatar[data-turn-id]` element in the rendered chat is found and `handleReloadPlanClick()` is called fire-and-forget. This fetches the turn's execution data from the API and populates the Live Status window with the appropriate visualization (plan trace, genie coordination events, agent tool steps, or RAG retrieval results depending on profile type).

This ensures users always see meaningful data in the Live Status panel — never a blank "Waiting for a new request..." when there is prior execution history.

#### Key State Variables

| Variable | Location | Purpose |
|----------|----------|---------|
| `state.activeStreamSessions` | `state.js` | `Set` of session IDs with running `processStream` loops |
| `state.sessionUiCache` | `state.js` | Per-session snapshots: `{ chatHTML, statusHTML, headerState, executionState, handlerState }` |
| `genieState` | `genieHandler.js` | Module singleton tracking genie coordination progress |
| `conversationAgentState` | `conversationAgentHandler.js` | Module singleton tracking conversation agent tool progress |

#### Files

- `static/js/handlers/sessionManagement.js` — Cache save/restore helpers, normal load path reset, auto-load last turn
- `static/js/eventHandlers.js` — `processStream()` session guard, `handleReloadPlanClick()` for historical turn loading
- `static/js/notifications.js` — Notification channel event guards
- `static/js/handlers/genieHandler.js` — `genieState` + `cleanupCoordination()`
- `static/js/handlers/conversationAgentHandler.js` — `conversationAgentState` + `cleanupExecution()`
- `static/js/state.js` — `activeStreamSessions`, `sessionUiCache`

---

## Deep Dive: Planner/Executor Architecture

### Overview

The Uderia agent uses a sophisticated **two-level planning architecture** that combines strategic planning (meta-plan) with tactical execution (per-phase tool selection). This design enables efficient token usage, RAG-powered learning, and robust error handling.

### Core Components

#### 1. Executor (`executor.py`)
**Main orchestrator** that coordinates the entire query execution lifecycle.

**Key Responsibilities:**
- Manages session state and conversation history
- Coordinates planner and phase executor
- Handles RAG retrieval for champion cases
- Implements plan hydration (context injection)
- Orchestrates multi-turn conversations

**Entry Point:**
```python
async def execute_query(
    query: str,
    session_id: str,
    user_uuid: str,
    dependencies: dict,
    ...
) -> AsyncGenerator:
    # Main execution loop
```

#### 2. Planner (`planner.py`)
**Strategic planning engine** that creates high-level execution plans.

**Two Planning Modes:**

**Strategic Planning (Meta-Plan):**
- Creates multi-phase execution plan
- Defines goals for each phase
- Identifies tool categories needed
- Example: "Phase 1: Execute SQL query, Phase 2: Generate report"

**Tactical Planning (Per-Phase):**
- Selects specific tool for current phase
- Determines exact arguments
- Fast-path mode: Skip LLM if pattern matches

**Key Functions:**
```python
async def plan_strategy(query, tools, ...) -> dict:
    """Create high-level multi-phase plan"""

async def plan_tactical(phase, tools, ...) -> dict:
    """Select tool for specific phase"""
```

#### 3. Phase Executor (`phase_executor.py`)
**Per-phase execution engine** that runs individual plan steps.

**Responsibilities:**
- Execute tool calls via MCP adapter
- Handle tool errors and retries
- Collect results for next phase
- Update phase status

**Execution Flow:**
```python
async def execute_phase(phase_info, tools, ...) -> dict:
    # 1. Get tool selection (from tactical planner)
    # 2. Execute tool via MCP
    # 3. Handle success/error
    # 4. Return results
```

#### 4. RAG Retriever (`rag_retriever.py`)
**Retrieves champion cases** from planner repositories.

**Two Repository Types:**

**Planner Repositories:**
- Store successful execution strategies
- SQL query templates with proven patterns
- Semantic search via ChromaDB

**Knowledge Repositories:**
- Store reference documents
- Domain knowledge base
- Document chunking with embeddings

**Retrieval Process:**
```python
async def retrieve_champion_cases(query, collection_id, ...) -> List[dict]:
    # 1. Semantic search in ChromaDB
    # 2. Filter by metadata (database, template_type)
    # 3. Extract strategy from top matches
    # 4. Return plan structure
```

---

### Execution Flow: Step-by-Step

#### Turn 1: Fresh Query (No RAG)

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. User Query: "Show me all products with low inventory"           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 2. RAG Retrieval (rag_retriever.py)                                │
│    - Search ChromaDB for similar queries                           │
│    - No matches found (new query pattern)                          │
│    - Return empty list                                             │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 3. Strategic Planning (planner.py)                                 │
│    LLM Call: plan_strategy()                                       │
│    Prompt: System prompts + query + available tools               │
│                                                                     │
│    LLM Response:                                                   │
│    {                                                               │
│      "phase_count": 2,                                            │
│      "phases": [                                                  │
│        {                                                          │
│          "phase": 1,                                             │
│          "goal": "Execute SQL query for low inventory",          │
│          "relevant_tools": ["base_readQuery"]                    │
│        },                                                         │
│        {                                                          │
│          "phase": 2,                                             │
│          "goal": "Generate report",                              │
│          "relevant_tools": ["TDA_FinalReport"]                   │
│        }                                                          │
│      ]                                                            │
│    }                                                              │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 4. Phase 1 Execution                                               │
│                                                                     │
│    4a. Tactical Planning (planner.py)                             │
│        LLM Call: plan_tactical(phase=1)                           │
│        Prompt: Phase goal + tools + conversation history         │
│                                                                     │
│        LLM Response:                                              │
│        {                                                          │
│          "tool_name": "base_readQuery",                          │
│          "arguments": {                                          │
│            "sql": "SELECT * FROM products WHERE quantity < 10"   │
│          }                                                        │
│        }                                                          │
│                                                                     │
│    4b. Tool Execution (phase_executor.py)                         │
│        - Call MCP: base_readQuery(sql="...")                     │
│        - Receive results: 15 products                            │
│        - Store in phase_results                                  │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 5. Phase 2 Execution                                               │
│                                                                     │
│    5a. Tactical Planning (planner.py)                             │
│        LLM Call: plan_tactical(phase=2)                           │
│        Prompt: Phase goal + Phase 1 results + tools              │
│                                                                     │
│        LLM Response:                                              │
│        {                                                          │
│          "tool_name": "TDA_FinalReport",                         │
│          "arguments": {                                          │
│            "report": "Found 15 products with low inventory..."   │
│          }                                                        │
│        }                                                          │
│                                                                     │
│    5b. Tool Execution                                             │
│        - Generate formatted report                               │
│        - Return to user                                          │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 6. Save to Session (session_manager.py)                           │
│    - conversation.json: Full chat for UI                         │
│    - workflow.json: Turn summary for planner                     │
│    - llm_conversation.json: Raw LLM messages                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Token Usage (Turn 1):**
- Strategic planning: ~8,000 input tokens, ~500 output tokens
- Tactical phase 1: ~3,000 input tokens, ~200 output tokens
- Tactical phase 2: ~4,000 input tokens, ~300 output tokens
- **Total: ~15,000 input, ~1,000 output**

---

#### Turn 2: Similar Query (RAG-Powered)

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. User Query: "Show me products running out of stock"             │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 2. RAG Retrieval (rag_retriever.py)                                │
│    - Search ChromaDB: semantic similarity to query                 │
│    - MATCH FOUND: Previous "low inventory" case                    │
│    - Extract strategy from champion case                           │
│                                                                     │
│    Champion Case Strategy:                                         │
│    {                                                               │
│      "phase_count": 2,                                            │
│      "phases": [                                                  │
│        {                                                          │
│          "phase": 1,                                             │
│          "goal": "Execute SQL query...",                         │
│          "relevant_tools": ["base_readQuery"],                   │
│          "successful_tool": "base_readQuery",                    │
│          "arguments": {"sql": "SELECT * FROM products..."}       │
│        },                                                         │
│        {...phase 2...}                                           │
│      ]                                                            │
│    }                                                              │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 3. Plan Hydration (executor.py)                                    │
│    - Champion strategy injected into context                       │
│    - LLM sees proven pattern                                       │
│    - Can reuse/adapt successful approach                           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 4. Strategic Planning (planner.py)                                 │
│    LLM Call: plan_strategy()                                       │
│    Prompt: System + query + tools + CHAMPION STRATEGY             │
│                                                                     │
│    LLM adapts champion strategy:                                  │
│    - Reuses 2-phase structure                                     │
│    - Modifies SQL for new query context                           │
│    - Faster planning (champion provides template)                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 5. Phase Execution                                                 │
│    - Execute adapted plan                                          │
│    - Leverage proven tool selections                               │
│    - Higher success rate                                           │
└─────────────────────────────────────────────────────────────────────┘
```

**Token Savings (Turn 2 with RAG):**
- Strategic planning: ~6,000 input (champion provides structure)
- Tactical planning: Often skipped via fast-path
- **Total: ~40% token reduction**

---

### Key Optimization Techniques

#### 1. Plan Hydration

**What:** Inject previous turn results into context to skip redundant calls.

**Example:**
```
Turn 1:
  Phase 1: Get database schema → Returns table definitions
  Phase 2: Execute query → Uses schema from Phase 1

Turn 2 (same session):
  Phase 1: SKIPPED (schema already in context via hydration)
  Phase 2: Execute query → Uses hydrated schema
```

**Implementation:**
```python
# executor.py
if previous_phase_results:
    context += f"\n\nPrevious results available:\n{previous_phase_results}"
```

**Benefits:**
- Reduces redundant tool calls
- Saves 30-50% tokens on multi-turn conversations
- Faster response times

#### 2. Tactical Fast-Path

**What:** Skip LLM for tactical planning when pattern matches.

**When Triggered:**
- Simple tool selection (only 1 relevant tool)
- Arguments can be inferred from phase goal
- No complex decision needed

**Example:**
```python
# planner.py
if len(relevant_tools) == 1 and is_simple_pattern(phase_goal):
    # Fast-path: Skip LLM call
    return {
        "tool_name": relevant_tools[0],
        "arguments": extract_args_from_goal(phase_goal)
    }
```

**Token Savings:**
- ~3,000 tokens per skipped tactical call
- 20-30% reduction on simple queries

#### 3. RAG-Powered Learning

**What:** Retrieve proven strategies from past successes.

**Storage:**
- Templates: Pre-built patterns (SQL Query Constructor)
- Runtime cases: Successful executions saved to ChromaDB

**Retrieval:**
```python
# rag_retriever.py
results = collection.query(
    query_texts=[user_query],
    n_results=3,
    where={
        "database_name": current_db,
        "template_type": "sql_query"
    }
)
```

**Benefits:**
- 40% faster planning (template reuse)
- Higher success rate (proven patterns)
- Continuous improvement (learns from each success)

#### 4. Context Distillation

**What:** Summarize large tool outputs to save tokens.

**Example:**
```python
# phase_executor.py
if len(tool_result) > 5000:
    # Distill large result
    summary = f"Returned {count} rows with columns: {columns}"
    context += summary
else:
    context += tool_result
```

---

### RAG Template System

> **Related Documentation:**
> - `rag_templates/TYPE_TAXONOMY.md` - **Comprehensive type system documentation** covering template_type, repository_type, and category classification
> - `rag_templates/PLUGIN_MANIFEST_SCHEMA.md` - Complete manifest.json schema and field specifications
> - `rag_templates/schemas/README.md` - JSON schema validation details for template files
> - `docs/RAG_Templates/README.md` - User guide for creating and using RAG templates

#### Template Structure

**Location:** `rag_templates/templates/`

**Two Template Types:**

**1. SQL Query Constructor - Database Context** (`sql_query_v1`)
- **Context Source**: MCP server (database schema)
- **Use Case**: Business queries from schema
- **Files:**
  - `manifest.json` - UI configuration, population modes
  - `sql_query_v1.json` - Template definition with phase structure

**2. SQL Query Constructor - Document Context** (`sql_query_doc_context_v1`)
- **Context Source**: Uploaded PDFs (DBA guides)
- **Use Case**: Operational queries from documentation
- **Dependencies**: `PyPDF2`, `pdfplumber`

#### Template Components

**manifest.json:**
```json
{
  "name": "sql-query-basic",
  "template_id": "sql_query_v1",
  "population_modes": {
    "manual": {
      "supported": true,
      "required_fields": ["user_query", "sql_statement"]
    },
    "auto_generate": {
      "supported": true,
      "requires_llm": true,
      "requires_mcp_context": true,
      "generation_endpoint": "/api/v1/rag/generate-questions"
    }
  }
}
```

**Template Definition (sql_query_v1.json):**
```json
{
  "template_id": "sql_query_v1",
  "template_type": "sql_query",
  "strategy_template": {
    "phase_count": 2,
    "phases": [
      {
        "phase": 1,
        "goal_template": "Execute SQL query: {sql_preview}",
        "relevant_tools_source": "mcp_tool_name",
        "arguments": {
          "sql": {"source": "sql_statement"}
        }
      },
      {
        "phase": 2,
        "goal": "Generate the final report",
        "relevant_tools": ["TDA_FinalReport"]
      }
    ]
  }
}
```

#### Question Generation with Batching

**Problem:** LLMs have output token limits (8K-16K). Generating 100 questions would truncate mid-JSON.

**Solution:** Automatic batching with context awareness.

**Implementation** (`rest_routes.py`):
```python
BATCH_SIZE = 20  # Safe size to avoid token limits
num_batches = (count + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num in range(num_batches):
    # Build context of previous questions
    if batch_num > 0:
        previous_questions_context = f"""
IMPORTANT - AVOID DUPLICATES:
The following {len(all_questions)} questions have ALREADY been generated.
Generate {batch_count} NEW and DIFFERENT questions.

Previously Generated:
{show_first_10_questions()}
"""

    # Generate batch with context
    result = await llm_handler.call_llm_api(
        prompt=base_prompt + previous_questions_context,
        ...
    )
    all_questions.extend(result.questions)

# Deduplicate
unique_questions = remove_duplicates(all_questions)
```

**Deduplication:**
```python
# Remove exact duplicates (case-insensitive)
seen_questions = set()
seen_sql = set()

for q in all_questions:
    question_lower = q['question'].lower()
    sql_normalized = ' '.join(q['sql'].lower().split())

    if question_lower not in seen_questions and sql_normalized not in seen_sql:
        deduplicated.append(q)
        seen_questions.add(question_lower)
        seen_sql.add(sql_normalized)
```

**Benefits:**
- Generate unlimited questions (batched in groups of 20)
- Context awareness prevents duplicates across batches
- Programmatic deduplication catches any LLM-missed duplicates
- Transparent progress tracking

---

### Frontend Integration

#### Repository Management UI

**Location:** `static/js/handlers/ragCollectionManagement.js`

**Key Features:**

**1. Button State Management**
- **Planner Repositories**: "Create Collection" disabled until questions generated
- **Knowledge Repositories**: "Create Repository" disabled until documents uploaded
- Dynamic tooltips show requirements

**2. Question Generation Flow**
```javascript
// User clicks "Generate Questions"
async function handleGenerateQuestions() {
    // Disable button during generation
    submitBtn.disabled = true;

    // Call batched generation endpoint
    const result = await fetch('/api/v1/rag/generate-questions', {
        body: JSON.stringify({count: 100, ...})
    });

    // Store questions
    lastGeneratedQuestions = result.questions;

    // Enable Create Collection button
    submitBtn.disabled = false;
    submitBtn.title = `Create with ${result.count} questions`;

    // Auto-scroll to button with highlight
    submitBtn.scrollIntoView({behavior: 'smooth'});
}
```

**3. Removed Redundant "Populate Collection" Button**
- Old workflow: Generate → Populate → Create (confusing)
- New workflow: Generate → Create (clear)
- "Create Collection" now does both create AND populate

**4. Consistent Delete Confirmations**
- Both repository types use `showConfirmation()` styled modal
- No more browser-native `confirm()` dialogs
- Consistent UX across all delete operations

---

### Error Handling & Recovery

#### Self-Correction Loop

**Mechanism:**
```python
# phase_executor.py
for attempt in range(MAX_RETRIES):
    result = await execute_tool(tool_name, args)

    if result.success:
        return result
    else:
        # Self-correct via LLM
        corrected_args = await planner.fix_tool_call(
            error=result.error,
            previous_args=args
        )
        args = corrected_args
```

**Example:**
```
Attempt 1:
  Tool: base_readQuery
  SQL: "SELECT * FROM product WHERE quantity < 10"
  Error: "Table 'product' doesn't exist"

Self-Correction:
  LLM analyzes error
  Fixes: "product" → "products" (correct table name)

Attempt 2:
  SQL: "SELECT * FROM products WHERE quantity < 10"
  Success: Returns 15 rows
```

---

### Performance Metrics

**Typical Query Breakdown:**

| Operation | Tokens (Input) | Tokens (Output) | Time |
|-----------|---------------|-----------------|------|
| Strategic Planning | 8,000 | 500 | 2-3s |
| Tactical Phase 1 | 3,000 | 200 | 1-2s |
| Tactical Phase 2 | 4,000 | 300 | 1-2s |
| Tool Execution | - | - | 1-5s |
| **Total (No RAG)** | **15,000** | **1,000** | **5-12s** |
| **Total (With RAG)** | **9,000** | **700** | **3-8s** |

**RAG Impact:**
- 40% token reduction
- 30% faster execution
- Higher success rate (proven patterns)

---

### Best Practices

#### When Building RAG Templates

1. **Keep phases focused**: Each phase should have ONE clear goal
2. **Use variable substitution**: `{sql_preview}`, `{database_name}` for flexibility
3. **Provide examples**: Include `usage_examples` in template definition
4. **Test batching**: Ensure templates work with 100+ question generation
5. **Metadata extraction**: Use regex to extract searchable metadata

#### When Working with Executor

1. **Always await async calls**: Executor is fully async
2. **Check session state**: Use `session_manager` for persistence
3. **Log strategic decisions**: Use `logger.info()` for plan steps
4. **Handle errors gracefully**: Self-correction loop, not immediate failure
5. **Leverage RAG**: Enable retrieval for performance gains

#### When Modifying UI

1. **Button states**: Disable until prerequisites met (files, questions)
2. **Tooltips**: Show clear guidance on what's needed
3. **Auto-scroll**: Guide user to next action
4. **Consistent modals**: Use `showConfirmation()` not `confirm()`
5. **Remove redundancy**: One button per action, clear workflow

---

### Debugging Tips

**Enable Verbose Logging:**
```python
# executor.py
logger.setLevel(logging.DEBUG)
```

**Check Session Files:**
```bash
cat tda_sessions/{session_id}/workflow.json  # Turn summaries
cat tda_sessions/{session_id}/conversation.json  # Full chat
```

**Inspect RAG Retrieval:**
```python
# In rag_retriever.py, add:
logger.info(f"RAG retrieved {len(cases)} champion cases")
for case in cases:
    logger.info(f"  - {case['metadata']['template_type']}")
```

**Monitor Token Usage:**
```bash
# Check cost_manager logs
grep "Token count" logs/app.log
```

---

### File Reference Summary

**Core Engine:**
- [executor.py](src/trusted_data_agent/agent/executor.py) - Main orchestrator
- [planner.py](src/trusted_data_agent/agent/planner.py) - Strategic & tactical planning
- [phase_executor.py](src/trusted_data_agent/agent/phase_executor.py) - Per-phase execution

**RAG System:**
- [rag_retriever.py](src/trusted_data_agent/agent/rag_retriever.py) - Champion case retrieval
- [rag_template_manager.py](src/trusted_data_agent/agent/rag_template_manager.py) - Template loading
- [rag_template_generator.py](src/trusted_data_agent/agent/rag_template_generator.py) - Case generation

**Templates:**
- [sql_query_v1.json](rag_templates/templates/sql-query-basic/sql_query_v1.json) - Basic SQL template
- [manifest.json](rag_templates/templates/sql-query-basic/manifest.json) - UI configuration

**API Endpoints:**
- [rest_routes.py](src/trusted_data_agent/api/rest_routes.py) - Batched question generation
- [routes.py](src/trusted_data_agent/api/routes.py) - SSE streaming execution

**Frontend:**
- [ragCollectionManagement.js](static/js/handlers/ragCollectionManagement.js) - Repository UI
- [knowledgeRepositoryHandler.js](static/js/handlers/knowledgeRepositoryHandler.js) - Knowledge repo UI

## Critical Implementation Details

### Database Schema Migration

**The system migrated from file-based config to database schema (Dec 2024)**:

- Old: `tda_config.json` (read-write user config)
- New: Database tables in `tda_auth.db`
- Bootstrap: `tda_config.json` is now a read-only template copied on first user login

Schema files in `schema/`:
- `00_master.sql` - Database initialization
- `01_core_tables.sql` - Prompts, users, profiles
- `02_parameters.sql` - Prompt parameters & overrides
- `03_profile_integration.sql` - Profile-prompt mappings
- `04_indexes.sql` - Database indexes for performance
- `05_views.sql` - Database views
- `06_prompt_mappings.sql` - Provider-specific prompt routing
- `07_genie_profiles.sql` - Genie coordinator profiles
- `08_genie_global_settings.sql` - Genie system settings
- `09_agent_packs.sql` - Agent pack installations
- `10_marketplace_agent_packs.sql` - Marketplace agent packs
- `11_marketplace_sharing.sql` - Sharing and permissions

### Prompt Management System

**System prompts** are stored encrypted in database:

1. **Bootstrap encryption**: `schema/default_prompts.dat` encrypted with key from `tda_keys/public_key.pem`
2. **Database encryption**: Re-encrypted with tier-specific key (from license signature + tier)
3. **Runtime decryption**: All tiers can decrypt for LLM usage
4. **UI restrictions**: Only PE/Enterprise can view/edit via System Prompts editor

**Prompt override hierarchy** (highest to lowest priority):
1. User-level override (PE/Enterprise only)
2. Profile-level override
3. Base prompt from database

### Session Management

**Session persistence** in `tda_sessions/{session_id}/`:
- `conversation.json` - Chat history for UI rendering
- `workflow.json` - Turn summaries for planner context
- `llm_conversation.json` - Raw LLM conversation history

**Context modes**:
- **Full Context**: Sends entire conversation history
- **Turn Summaries**: Sends only workflow summaries (stateless)

Activation: Hold `Alt` for single query, `Shift+Alt` to lock mode

### Unified Artifact Relationships System

The platform provides a unified endpoint for analyzing relationships between artifacts (collections, profiles, MCP servers, LLM configurations, agent packs) and sessions. This system creates a **single source of truth** for relationship detection used by both frontend warnings and backend session archiving.

**Key Features:**

1. **Single Source of Truth**: All relationship detection logic centralized in one endpoint
2. **Comprehensive Detection**: Finds direct, historical, and profile-based relationships
3. **Deletion Safety Analysis**: Provides blockers, warnings, and cascade effect predictions
4. **Active vs Archived Tracking**: Separately tracks active and archived sessions
5. **Extensible Design**: Easy to add new artifact types via detector pattern

**Architecture:**

```
Frontend Warning → Unified Endpoint → Relationship Analyzer → Artifact Detectors
Backend Archive  ↗                    ↘ Deletion Safety        ↘
                                       Analysis                Collection | Profile | MCP | LLM | AgentPack
```

**Supported Artifact Types:**

| Type | Description | Example Use Case |
|------|-------------|------------------|
| `collection` | RAG/knowledge repositories | "Which sessions use this knowledge base?" |
| `profile` | Execution profiles | "Which sessions use the @FOCUS profile?" |
| `agent-pack` | Installed agent packs | "What resources does this pack manage?" |
| `mcp-server` | MCP server configurations | "Which profiles connect to this server?" |
| `llm-config` | LLM provider configurations | "Which sessions use GPT-4?" |

**Detection Methods:**

**Collection Relationships:**
1. Direct: `session.rag_collection_id` (rag_focused profiles)
2. Workflow: `session.workflow_history[].collection_id` (historical queries)
3. Profile: `session.profile.knowledgeConfig.collections[]` (profile configuration)

**Profile Relationships:**
1. Current: `session.profile_id` (active profile)
2. Historical: `session.profile_tags_used[]` (past profiles)
3. Genie Child: `session.genie_metadata.slave_profile_id` (child sessions)

**MCP/LLM Relationships:**
- Indirect via profile: Session → Profile → MCP Server / LLM Config

**Usage Example:**

```bash
# Get relationships for a collection
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

curl -X GET "http://localhost:5050/api/v1/artifacts/collection/12/relationships" \
  -H "Authorization: Bearer $JWT" | jq '.deletion_info'

# Output:
# {
#   "can_delete": true,
#   "warnings": ["2 active sessions will be archived"],
#   "cascade_effects": {
#     "active_sessions_archived": 2,
#     "profiles_affected": 1
#   }
# }
```

**Implementation Files:**

**Core Modules:**
- `src/trusted_data_agent/core/artifact_detectors.py` - Detector implementations (~850 lines)
- `src/trusted_data_agent/core/relationship_analyzer.py` - Analysis orchestration (~150 lines)

**API Endpoint:**
- `src/trusted_data_agent/api/rest_routes.py` - Unified endpoint at `/api/v1/artifacts/<type>/<id>/relationships`

**Archive Integration:**
- `src/trusted_data_agent/core/session_manager.py` - Archive functions call unified endpoint via HTTP

**Frontend Integration:**
- `static/js/handlers/ragCollectionManagement.js` - Collection deletion warnings
- `static/js/handlers/knowledgeRepositoryHandler.js` - Repository deletion warnings

**Session Archiving Flow:**

When an artifact is deleted, the system automatically archives affected sessions:

```
User Deletes Collection
       ↓
DELETE /api/v1/rag/collections/{id}
       ↓
archive_sessions_by_collection()
       ↓
GET /api/v1/artifacts/collection/{id}/relationships (internal HTTP call)
       ↓
Returns affected sessions
       ↓
Archive each session
       ↓
Set archived_reason metadata
       ↓
Complete deletion
```

**Archived Session Metadata:**
```json
{
  "id": "session_id",
  "archived": true,
  "archived_reason": "Collection '12' was deleted",
  "archived_at": "2026-02-06T17:30:00Z"
}
```

**Archive Triggers:**
- Profile deletion → Archives sessions using that profile
- Collection deletion → Archives sessions using that collection (direct, workflow, or profile-based)
- MCP server deletion → Archives sessions using profiles connected to that server
- LLM config deletion → Archives sessions using profiles with that configuration
- Agent pack uninstall → Archives sessions using pack-managed resources

**Benefits Over Previous Architecture:**

**Before Unification:**
- 3 separate check-sessions endpoints with duplicate logic (~300 lines of duplicated code)
- Archive functions had different detection logic than frontend warnings
- Missed profile-based relationships
- No support for MCP server or LLM config deletions

**After Unification:**
- 1 unified endpoint used everywhere
- Frontend warnings and backend archiving use identical logic
- All relationship types detected correctly
- All artifact types support session archiving
- ~300 lines of code eliminated
- Single source of truth
- Easier to maintain and extend

**Adding New Artifact Types:**

To add support for a new artifact type:

1. **Create Detector Class** in `artifact_detectors.py`:
```python
class MyArtifactDetector(BaseDetector):
    async def find_sessions(self, artifact_id, user_uuid, include_archived):
        # Detection logic
        return {"active": [...], "archived": [...]}

    async def find_profiles(self, artifact_id, user_uuid):
        # Profile relationships
        return [...]

    async def find_agent_packs(self, artifact_id, user_uuid):
        # Agent pack relationships
        return [...]
```

2. **Register Detector** in `DETECTORS` registry:
```python
DETECTORS = {
    # ... existing detectors ...
    "my-artifact": MyArtifactDetector,
}
```

3. **Add Archive Function** in `session_manager.py`:
```python
async def archive_sessions_by_my_artifact(artifact_id, user_uuid):
    # Call unified endpoint via HTTP
    # Archive returned sessions
```

4. **Update Deletion Endpoint** to call archive function before deletion

**Testing:**

Test the unified endpoint with REST API:
```bash
# Test collection relationships
python3 test_unified_relationships.py

# Extensive validation test
python3 test_extensive_unified_relationships.py
```

Files: `src/trusted_data_agent/core/artifact_detectors.py`, `relationship_analyzer.py`, `session_manager.py`, `rest_routes.py`

---

#### Deprecated: Legacy check-sessions Endpoints (Feb 2026, removal Q2 2026)

**Old:** `GET /v1/profiles/<id>/check-sessions`, `GET /v1/agent-packs/<id>/check-sessions`
**New:** `GET /v1/artifacts/<type>/<id>/relationships` (unified endpoint)
**Migrated:** `configurationHandler.js`, `agentPackHandler.js`
**Rule:** Always use unified endpoint for new deletion warnings

---

### Cost Management

**Real-time cost tracking**:
- Token counting per turn (input + output)
- Provider-specific pricing from `llm_model_costs` table
- LiteLLM integration for automatic pricing sync
- Manual overrides preserved during sync

Files: `src/trusted_data_agent/core/cost_manager.py`

### Security Considerations

1. **Credential encryption**: All API keys encrypted with Fernet (stored in `tda_auth.db`)
2. **JWT secrets**: Regenerate `tda_keys/jwt_secret.key` on installation
3. **License validation**: `tda_keys/license.key` verified on startup
4. **Rate limiting**: Configurable per-user quotas (disabled by default)
5. **OAuth**: Google/GitHub integration with email verification

### Agent Packs System

**Purpose:** Portable bundles containing profiles, collections, and MCP servers for quick deployment.

**Key Features:**
- Export/import complete agent configurations as `.agentpack` files
- Publish to marketplace for sharing
- Install from marketplace with one click
- Automatic dependency resolution (profiles, collections, MCP servers)
- Version management and update notifications

**Files:**
- `src/trusted_data_agent/core/agent_pack_manager.py` - Pack creation and installation
- `src/trusted_data_agent/core/agent_pack_db.py` - Database operations
- `src/trusted_data_agent/api/agent_pack_routes.py` - REST endpoints
- `static/js/handlers/agentPackHandler.js` - UI integration
- Schema: `09_agent_packs.sql`, `10_marketplace_agent_packs.sql`, `11_marketplace_sharing.sql`

**REST Endpoints:**
- `POST /v1/agent-packs/create` - Create pack from resources
- `POST /v1/agent-packs/import` - Install pack from file
- `POST /v1/agent-packs/export` - Export pack to file
- `POST /v1/marketplace/agent-packs/<id>/publish` - Publish to marketplace
- `GET /v1/marketplace/agent-packs` - Browse marketplace

**See:** `docs/RestAPI/restAPI.md` section 3.14 for full API documentation

## Common Development Tasks

### Adding a New LLM Provider

1. Update `src/trusted_data_agent/llm/client_factory.py` with provider-specific client
2. Add provider to `src/trusted_data_agent/core/provider_colors.py`
3. Update UI dropdown in `templates/index.html`
4. Add pricing data to `llm_model_costs` table

### Modifying System Prompts

> **📚 Deep Dive:** Use the `system-prompts` skill for comprehensive guide on development workflow, production deployment, encryption troubleshooting, and recovery procedures.

**For PE/Enterprise tiers (via UI)**:
1. UI: Setup → System Prompts → Edit prompt
2. Database: Prompts stored encrypted in `prompts` table
3. Versioning: Changes saved to `prompt_versions` table

**For development (source files)**:
1. Edit plain text files in `trusted-data-agent-license/default_prompts/`
   - `.txt` files for string prompts
   - `.json` files for dictionary prompts (e.g., CHARTING_INSTRUCTIONS)
2. Encrypt: `python encrypt_default_prompts.py` (creates `schema/default_prompts.dat`)
3. Test locally or deploy to production

**Deploying Prompt Updates to Production**:

Use the `update_prompt.py` script for **zero-downtime** prompt deployments:

```bash
# Navigate to license repo
cd /path/to/trusted-data-agent-license

# Update a single prompt
python update_prompt.py \
  --app-root /path/to/uderia \
  --prompt WORKFLOW_META_PLANNING_PROMPT

# Update all prompts
python update_prompt.py \
  --app-root /path/to/uderia \
  --all
```

**What `update_prompt.py` does:**
1. ✅ Compares existing vs new content (skips unchanged)
2. ✅ Encrypts using tier-specific format (matching bootstrap)
3. ✅ Syncs global parameters from `tda_config.json`
4. ✅ Syncs profile prompt mappings
5. ✅ Invalidates runtime cache via API (no restart needed!)
6. ✅ Creates version history for audit trail

**Key Implementation Details:**

**Encryption Format (CRITICAL)**:
- Dictionary prompts: Encrypted as `encrypt(json_string)` → single encrypted blob
- String prompts: Encrypted as `encrypt(string)` → single encrypted blob
- **NOT** JSON with individually encrypted values (old format)

**Synchronization Steps**:
```python
# Parameters: New template variables added to global_parameters table
sync_parameters_from_config(app_root, db_path)

# Mappings: Profile routing updated for all categories
sync_prompt_mappings(app_root, db_path)

# Cache: Invalidated via POST /v1/admin/prompts/clear-cache
invalidate_cache_via_api(app_root)
```

**Troubleshooting**:

If deployment causes instability:
- **Symptom**: Dictionary prompts return `[ENCRYPTED CONTENT]`
- **Cause**: Wrong encryption format (individually encrypted values vs encrypted JSON string)
- **Fix**: Ensure `update_prompt.py` uses `encrypt_prompt(json.dumps(dict), key)` not `json.dumps({k: encrypt(v)})`

If parameters missing:
- **Symptom**: Prompt templates show `{undefined_param}`
- **Cause**: New parameters not synced from `tda_config.json`
- **Fix**: Check `global_parameters` table, manually run `sync_parameters_from_config()`

If cache not invalidated:
- **Symptom**: Old prompts still served after update
- **Cause**: Application not running or authentication failed
- **Fix**: Restart application (cache cleared on startup) or fix admin credentials

**Files**:
- Source: `trusted-data-agent-license/default_prompts/*.{txt,json}`
- Encrypted: `schema/default_prompts.dat` (committed to repo)
- Deploy script: `trusted-data-agent-license/update_prompt.py`
- REST endpoint: `POST /v1/admin/prompts/clear-cache` (cache invalidation)

### Creating RAG Template Plugins

1. Create directory in `rag_templates/templates/<your-template>/`
2. Add `manifest.json` with template metadata
3. Add template definition JSON (e.g., `my_template_v1.json`)
4. Templates auto-discovered on reload (no manual registration needed)

See: `rag_templates/README.md`, `rag_templates/PLUGIN_MANIFEST_SCHEMA.md`
User templates: `~/.tda/templates/` (overrides system)

### Managing Templates (Admin UI)

**Location:** Administration → Templates tab (Feb 2026)

**Features:**
- **Hot-Reload:** `POST /v1/rag/templates/reload` - Reload templates without restart
- **Validate:** `POST /v1/rag/templates/validate` - Validate plugin before install

**Template Locations:**
- User: `~/.tda/templates/` (overrides system)
- System: `rag_templates/templates/`

**Files:** `templateManager.js`, `adminManager.js`, `index.html`, `rest_routes.py`
**Docs:** `docs/RAG_Templates/TROUBLESHOOTING.md`, `rag_templates/PLUGIN_MANIFEST_SCHEMA.md`

---

### Performance Testing

Two testing frameworks exist for different purposes:

**Profile Comparison** (`profile-perf` skill): Compare two profiles against each other on the same query. Measures token efficiency, execution time, self-correction overhead, and plan quality.

```bash
python test/performance/profile_performance_test.py \
  --query "your test query" --profile1 @IDEAT --profile2 @OPTIM
```

**Documentation:** [.claude/skills/profile-perf/profile-perf.md](.claude/skills/profile-perf/profile-perf.md)

**MCP Prompt Testing** (`fusion-hardening` skill, Section 8): Validate individual MCP prompt execution quality with parameter handling. Creates real sessions visible in the UI. Analyzes self-corrections, plan quality, safeguards, and orchestrator behavior.

```bash
python test/performance/mcp_prompt_test.py --profile-tag OPTIM --verbose
python test/performance/mcp_prompt_test.py --discover  # List available prompts
```

**Documentation:** [.claude/skills/fusion-hardening/fusion-hardening.md](.claude/skills/fusion-hardening/fusion-hardening.md) (Section 8)

---

### Working with Multi-User Features

**User creation**:
- UI: Administration → User Management
- API: `POST /api/v1/admin/users`

**User tiers** (controls feature access):
- `user` - Basic conversation access
- `developer` - Additional tools/debugging
- `admin` - Full system access

**Profile tiers** (separate from user tiers):
- Controls prompt override capabilities
- Defined in profile tier system (User → Developer → Admin)

## Important Files & Locations

### Configuration Files

```
tda_config.json          # Read-only bootstrap template
tda_auth.db              # User database (credentials, config, prompts)
tda_keys/
  ├── license.key        # License validation (JSON)
  ├── public_key.pem     # Signature verification + bootstrap encryption
  └── jwt_secret.key     # JWT token signing (regenerate on install!)
```

### Entry Points

```
src/trusted_data_agent/main.py              # Application startup
templates/index.html                         # Single-page UI
static/js/main.js                           # Frontend initialization
```

### Documentation

```
docs/
  ├── Architecture/
  │   ├── CONTEXT_WINDOW_ARCHITECTURE.md    # Context window management (comprehensive)
  │   ├── PROMPT_ENCRYPTION.md              # Encryption architecture
  │   └── NESTED_GENIE_UPGRADE_GUIDE.md     # Genie coordinator guide
  ├── RestAPI/restAPI.md                    # REST API reference
  ├── RAG/RAG.md                            # RAG system guide
  ├── Marketplace/MARKETPLACE_COMPLETE_GUIDE.md
  └── OAuth/OAUTH.md                        # OAuth setup
```

## Troubleshooting

### ModuleNotFoundError

**Problem**: Python can't find `trusted_data_agent` module

**Solution**:
1. Ensure you're in project root directory
2. Run `pip install -e .` in your active virtual environment
3. Verify `pyproject.toml` exists with correct `[tool.setuptools.packages.find]`

### License Validation Errors

**Problem**: App won't start, license errors in logs

**Check**:
1. `tda_keys/license.key` exists and is valid JSON
2. `tda_keys/public_key.pem` exists
3. License not expired (`expires_at` field)

### Database Schema Issues

**Problem**: Missing tables, column errors

**Solution**:
1. Delete `tda_auth.db`
2. Restart application (auto-creates from `schema/*.sql`)
3. Default admin account recreated: `admin` / `admin`

### Prompt Decryption Failures

**Problem**: Standard tier users get `[ENCRYPTED CONTENT]` in conversations

**This is now FIXED**: All tiers can decrypt for runtime LLM usage. If this occurs:
1. Check `can_access_prompts()` in `prompt_encryption.py` returns True
2. Verify license signature in database matches file
3. Check logs for decryption errors

### Self-Correction Loops with None Values (Feb 2026 - FIXED)

**Problem**: Excessive self-correction events during FASTPATH execution with errors like:
- `"Input validation error: None is not of type 'string'"`
- `"Input validation error: 'column_name' is a required property"`
- Tools failing with schema validation, then succeeding on retry
- Wasted tokens on unnecessary LLM correction calls (~30,000 tokens per affected query)

**Root Causes**:
1. **None Values in Arguments** (executor.py:1012): Explicitly set `resolved_args[key] = None` when placeholder resolution failed
2. **Column Iterator Missing for Single-Tool Phases** (phase_executor.py): Column orchestrator only ran for multi-tool phases, bypassing single-tool phases entirely

**Fixes Applied** (Feb 2026):

**Phase 1: None Value Fixes**
- **Priority 1**: `executor.py:1006-1012` - Removed `resolved_args[key] = None` line, arguments now omitted when resolution fails
- **Priority 2**: `executor.py:1029-1038` - Added None-value filter (defense in depth) before returning resolved arguments
- **Priority 3**: `phase_executor.py:1258-1266` - Enhanced refinement check to treat None-valued required arguments as missing

**Phase 2: Column Iterator Fix (Architectural)**
- **Location**: `phase_executor.py:1149-1180` - Added column orchestrator check inside `_execute_action_with_orchestrators()`
- **Problem**: Single-tool phases bypassed Scope-Aware Dispatcher (line 699), never reaching column orchestrator check (line 724)
- **Solution**: Column check now runs in shared execution method called by both FASTPATH and tactical LLM paths
- **Impact**:
  - Zero self-corrections for column-scoped tools in single-tool phases
  - ~30,000 token savings per affected MCP prompt execution
  - Consistent behavior across multi-tool and single-tool paths

**How Column Iterator Works**:
```python
# When tool is column-scoped but missing column_name:
# 1. Detect: tool_scope == 'column' and not has_column_arg
# 2. Call base_columnDescription to get all columns
# 3. Iterate tool across each column
# 4. Return consolidated results (no self-correction needed)
```

**Expected Behavior After Fix**:
- Optional parameters omitted from dict when unresolved (not set to None)
- Column-scoped tools automatically trigger column iteration (no manual intervention)
- FASTPATH executions succeed on first attempt without self-correction
- Zero unnecessary LLM correction calls for both None values and missing column names
- Existing safety nets (refinement LLM, self-correction) remain available for genuine errors

**Affected MCP Prompts**:
- `qlty_databaseQuality` (uses `qlty_univariateStatistics`, `qlty_rowsWithMissingValues`)
- Any single-tool phase using column-scoped tools (requires `database_name`, `object_name`, `column_name`)

**Files Modified**:
- `src/trusted_data_agent/agent/executor.py` - Root cause fix + defense filter (Priority 1/2)
- `src/trusted_data_agent/agent/phase_executor.py` - Enhanced None value detection (Priority 3) + Column orchestrator fix

### Frontend Build Issues

**Note**: The application uses CDN-loaded Tailwind CSS (no build step required)

For production: Consider building Tailwind locally:
```bash
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss build
```

## Project-Specific Conventions

### Code Organization

- **Async/await**: All API routes and LLM calls are async (Quart framework)
- **Type hints**: Used throughout Python codebase
- **Logging**: Use `logger = logging.getLogger("quart.app")`
- **Error handling**: Graceful degradation with user-facing error messages

### Naming Conventions

- **Database tables**: `snake_case` (e.g., `llm_model_costs`)
- **Python classes**: `PascalCase` (e.g., `PromptLoader`)
- **Python functions**: `snake_case` (e.g., `can_access_prompts_ui`)
- **JavaScript**: `camelCase` (e.g., `renderUsersTable`)
- **API routes**: `/api/v1/<resource>/<action>`

### Git Workflow

- **Recent commits** focus on:
  - License problem fixes
  - Admin UI improvements
  - Docker deployment enhancements
- **Branch**: `main` (default)

## External Integrations

### MCP (Model Context Protocol)

- Connect to external MCP servers for tools/prompts/resources
- Dynamic capability discovery at runtime
- Credential passthrough (no server-side storage)

### LLM Providers Supported

- Google (Gemini 2.0)
- Anthropic (Claude)
- OpenAI (GPT-4o)
- Azure OpenAI
- AWS Bedrock
- Friendli.AI
- Ollama (local, offline)

### Apache Airflow Integration

- DAG examples in `docs/Airflow/`
- Async polling pattern for long-running tasks
- Session reuse via `tda_session_id` variable

### Flowise Integration

- Visual workflow builder
- Pre-built TDA agent flows
- Import-ready JSON templates in `docs/Flowise/`

## Claude Skills

**Location:** `.claude/skills/`

Custom Claude Code skills provide specialized knowledge for complex integration tasks. Skills are automatically discovered and available for invocation.

### Available Skills

#### n8n-uderia (`n8n-uderia/`)
**Purpose:** Comprehensive guide for n8n workflow automation integration with Uderia Platform

**When to use:**
- Developing n8n workflows for Uderia queries
- Testing workflows (local vs production environments)
- Deploying workflows with Docker containers
- Troubleshooting n8n + Uderia integration issues
- Configuring reverse proxy with WebSocket support
- Understanding REST API vs UI profile override differences

**Key topics covered:**
- Architecture and three-step pattern (Session → Query → Poll)
- Development workflow with ultra-clean pattern (avoiding n8n bugs)
- Testing strategies and deployment procedures
- **Critical:** REST API profile override method (`profile_id` parameter vs `@TAG` syntax)
- Docker networking (cross-container communication)
- Reverse proxy configuration (Synology + nginx)
- Common pitfalls with solutions (8 documented scenarios)
- Complete workflow examples (Simple Query, Scheduled Report, Slack Integration)

**Documentation:** `.claude/skills/n8n-uderia/n8n.md` (44KB comprehensive guide)

#### fusion-hardening (`fusion-hardening/`)
**Purpose:** Deep knowledge skill for analyzing and hardening the Fusion Optimizer (tool_enabled) execution pipeline

**When to use:**
- Analyzing execution traces from tool_enabled profile sessions
- Diagnosing plan quality issues in strategic meta-plans
- Identifying which enterprise safeguards fired during execution
- Detecting anti-patterns (missing temporal context, hallucinated arguments, excessive self-correction)
- Evaluating fast-path vs slow-path decision correctness
- Adding new plan rewrite passes or correction strategies
- Tuning WORKFLOW_META_PLANNING_PROMPT or WORKFLOW_TACTICAL_PROMPT

**Key topics covered:**
- Complete execution flow (strategic planning → 9 rewrite passes → tactical execution → response)
- Core design principle: deterministic vs non-deterministic decision framework
- All 6 enterprise safeguards with file:line locations, trigger conditions, and known limitations
- TDA_SystemLog message catalog for execution trace analysis
- Plan quality checklists for 5 query types (temporal, data, loop, knowledge, multi-turn)
- 9 common anti-patterns with fixes and trace indicators
- Prompt engineering guide for all template variables
- Interactive 6-step analysis workflow with worked examples

**Documentation:** `.claude/skills/fusion-hardening/fusion-hardening.md` (40KB comprehensive guide)

### Using Skills

Skills are invoked automatically by Claude Code when relevant to the task. You can also explicitly reference them when asking questions about specific integrations:

```
Example: "Using the n8n-uderia skill, how do I configure profile override in a workflow?"
```

## Performance & Scalability

### Token Optimization

- **Plan hydration**: Reuses previous turn results
- **Tactical fast path**: Skips LLM for simple tool calls
- **Context distillation**: Summarizes large tool outputs
- **RAG efficiency**: Learns from past successes

### Deployment Options

- **Single-user**: Local Python process
- **Multi-user**: Docker container with volume mounts
- **Load balanced**: Multiple containers (ports 5050, 5051, 5052...)

### Rate Limiting

- **Disabled by default** for single-user installs
- **Configurable** via UI: Administration → App Config → Security
- **Per-user quotas**: Prompts/hour, tokens/month, config changes
- **Consumption profiles**: Free, Pro, Enterprise, Unlimited

## Recent Major Changes

- **Feb 2026**: Agent Packs system - install/export/publish agent packs with marketplace
- **Feb 2026**: Template Management UI - hot-reload and validation in admin panel
- **Feb 2026**: Unified Relationships API Migration - deprecated legacy check-sessions endpoints
- **Feb 2026**: Event harmonization - standardized event structure across system
- **Jan 2026**: OAuth (Google/GitHub), email verification
- **Dec 2025**: Prompt encryption to database, enhanced bootstrapping
- **Dec 2025**: Consumption profile enforcement, financial governance
- **Nov 2025**: Multi-user auth, profile system, RAG constructors
- **Nov 2025**: Knowledge repositories, marketplace integration
- **Sep 2025**: Text to Speech integration (ongoing enhancements)
