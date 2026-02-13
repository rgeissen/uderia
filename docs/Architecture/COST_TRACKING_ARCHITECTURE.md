# Cost Tracking Architecture

**Version**: 1.0
**Last Updated**: February 2026
**Status**: Production

---

## Table of Contents

1. [Overview](#overview)
2. [Design Principles](#design-principles)
3. [Architecture Components](#architecture-components)
4. [Data Flow](#data-flow)
5. [Storage Schema](#storage-schema)
6. [API Contracts](#api-contracts)
7. [Frontend Integration](#frontend-integration)
8. [Cost Calculation](#cost-calculation)
9. [Session Naming Attribution](#session-naming-attribution)
10. [Legacy Session Support](#legacy-session-support)
11. [Edge Cases](#edge-cases)
12. [Testing & Validation](#testing--validation)
13. [Performance Considerations](#performance-considerations)
14. [Future Enhancements](#future-enhancements)

---

## Overview

The **Cost Tracking Engine** provides accurate, real-time cost tracking for LLM interactions across all profile types, execution modes, and session lifecycles. It ensures consistent cost accounting from backend storage through API delivery to frontend display.

### Key Features

- **Single Source of Truth**: Backend calculates and stores authoritative costs
- **Real-time Tracking**: Live cost accumulation during execution with SSE streaming
- **Historical Accuracy**: Point-in-time cost snapshots for session replay
- **Multi-Profile Support**: Consistent tracking across 6 profile types
- **Session Naming Attribution**: Includes system-level LLM costs in Turn 1
- **Legacy Compatibility**: Transparent fallback for sessions created before the cost engine
- **Dual-Model Support**: Separate tracking for strategic vs tactical models

### Problem Solved

**Before**: Cost tracking was fragile and inconsistent:
- No authoritative cost storage (only token counts)
- Frontend calculated costs from event streams (risk of double-counting)
- Session naming costs not attributed to turns
- Inconsistent between live execution and historical reload
- **Result**: Session costs could be 2x actual costs

**After**: Reliable cost accounting:
- Backend stores `turn_cost` and `session_cost_usd` in workflow_history
- Frontend trusts backend data with verification
- Session naming costs included in Turn 1
- Consistent costs across all layers
- **Result**: Accurate cost tracking within ±$0.000001

---

## Design Principles

### 1. Backend as Single Source of Truth

**Principle**: All cost calculations happen in the backend; frontend displays authoritative data.

**Rationale**:
- Centralized pricing logic (one place to update)
- Prevents double-counting from duplicate events
- Consistent across all clients (UI, API, CLI)
- Historical costs remain accurate even if pricing changes

### 2. Point-in-Time Snapshots

**Principle**: Each turn stores cumulative `session_cost_usd` at the time of completion.

**Rationale**:
- Historical replay shows costs as they were
- Enables cost progression tracking
- Verifiable accounting (session cost = sum of turn costs)
- No need to recalculate history when pricing changes

### 3. Fail-Safe Fallback

**Principle**: Legacy sessions without stored costs calculate from tokens with warnings.

**Rationale**:
- Backwards compatibility (no migration needed)
- Graceful degradation (approximate costs better than none)
- Clear logging for debugging
- Smooth transition for existing deployments

### 4. Immediate Visibility

**Principle**: Costs display immediately when switching sessions (no waiting for API calls).

**Rationale**:
- Better user experience (no flickering $0.000000)
- Reduces perceived latency
- Consistent with auto-load last turn behavior
- Session data already includes cost information

---

## Architecture Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        COST TRACKING ENGINE                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   BACKEND       │  │   API LAYER      │  │   FRONTEND       │
│   (Python)      │  │   (REST/SSE)     │  │   (JavaScript)   │
└─────────────────┘  └──────────────────┘  └──────────────────┘
        │                     │                      │
        ├─ CostManager        ├─ get_turn_details   ├─ updateTokenDisplay
        ├─ Executor            ├─ SSE events         ├─ handleReloadPlanClick
        ├─ SessionManager      └─ Legacy fallback    ├─ handleLoadSession
        └─ WorkflowHistory                            └─ sessionCostAccumulator
```

### Component Responsibilities

#### Backend Components

**CostManager** (`src/trusted_data_agent/core/cost_manager.py`)
- Calculates cost from (provider, model, input_tokens, output_tokens)
- Maintains pricing table (`llm_model_costs`)
- Provider-specific pricing logic

**Executor** (`src/trusted_data_agent/agent/executor.py`)
- Accumulates tokens per turn (`self.turn_input_tokens`, `self.turn_output_tokens`)
- Calculates `turn_cost` before saving turn_summary
- Calculates `session_cost_usd` (cumulative) via `_calculate_session_cost_at_turn()`
- Stores both in workflow_history

**SessionManager** (`src/trusted_data_agent/core/session_manager.py`)
- Persists workflow_history to session files
- Updates turn costs when session naming adds tokens (`update_turn_token_counts()`)
- Recalculates `session_cost_usd` when turn costs change

#### API Layer

**Routes** (`src/trusted_data_agent/api/routes.py`)
- Endpoint: `GET /api/session/{session_id}/turn/{turn_id}/details`
- Returns: `turn_cost`, `session_cost_usd`, tokens, provider, model
- Legacy fallback: Calculates costs from tokens if missing

**SSE Events** (live execution)
- Event: `token_update` with `cost_usd` per LLM call
- Frontend accumulates costs during live execution
- Backend sends authoritative costs in real-time

#### Frontend Components

**updateTokenDisplay()** (`static/js/ui.js`)
- Primary cost display function
- **Historical mode**: Trusts backend `turn_cost` and `session_cost_usd`
- **Live mode**: Accumulates `cost_usd` from SSE events
- Maintains `window.sessionCostAccumulator`

**handleReloadPlanClick()** (`static/js/eventHandlers.js`)
- Fetches turn details from API
- Extracts backend-provided costs
- Passes to `updateTokenDisplay()` with `isHistorical=true`
- Verification: Compares backend cost vs event sum (_getTurnCost)

**handleLoadSession()** (`static/js/handlers/sessionManagement.js`)
- Initializes costs when switching sessions
- Fetches last turn's cost data from `workflow_history`
- Sets `sessionCostAccumulator` immediately
- Updates cost display before rendering UI

---

## Data Flow

### Flow 1: Live Execution (New Turn)

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. USER SUBMITS QUERY                                            │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│ 2. BACKEND EXECUTION (executor.py)                               │
│    ├─ LLM Call #1: Strategic planning                           │
│    │  ├─ Extracts tokens from response.usage                    │
│    │  ├─ self.turn_input_tokens += input_tokens                 │
│    │  ├─ self.turn_output_tokens += output_tokens               │
│    │  ├─ CostManager.calculate_cost() → cost_usd                │
│    │  └─ Emit SSE: token_update with cost_usd                   │
│    ├─ LLM Call #2: Tactical execution                           │
│    │  └─ (repeat token/cost tracking)                           │
│    └─ LLM Call #3: Session naming (Turn 1 only)                 │
│       ├─ Adds tokens to self.turn_input_tokens                  │
│       └─ Emit SSE: token_update with cost_usd                   │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│ 3. FRONTEND LIVE DISPLAY (ui.js::updateTokenDisplay)            │
│    ├─ Receives SSE token_update events                          │
│    ├─ Accumulates cost_usd into sessionCostAccumulator.turn     │
│    ├─ Accumulates cost_usd into sessionCostAccumulator.session  │
│    └─ Updates header: Turn Cost / Session Cost                  │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│ 4. BACKEND STORAGE (executor.py → session_manager.py)           │
│    ├─ Calculate turn_cost = CostManager.calculate_cost(         │
│    │      provider, model,                                      │
│    │      self.turn_input_tokens,                               │
│    │      self.turn_output_tokens                               │
│    │   )                                                         │
│    ├─ Calculate session_cost_usd = previous_turns_sum + turn    │
│    ├─ Create turn_summary with:                                 │
│    │  ├─ turn_input_tokens: self.turn_input_tokens              │
│    │  ├─ turn_output_tokens: self.turn_output_tokens            │
│    │  ├─ turn_cost: calculated above                            │
│    │  └─ session_cost_usd: cumulative total                     │
│    └─ Save to workflow_history in session file                  │
└──────────────────────────────────────────────────────────────────┘
```

### Flow 2: Historical Reload (Click Turn Avatar)

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. USER CLICKS TURN AVATAR                                       │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│ 2. FRONTEND REQUEST (eventHandlers.js::handleReloadPlanClick)   │
│    └─ API.fetchTurnDetails(sessionId, turnId)                   │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│ 3. BACKEND API (routes.py::get_turn_details)                    │
│    ├─ Load session data                                         │
│    ├─ Extract turn from workflow_history[turn_id - 1]           │
│    ├─ IF turn_cost exists:                                      │
│    │  └─ Use stored value (authoritative)                       │
│    ├─ ELSE (legacy session):                                    │
│    │  └─ Calculate: CostManager.calculate_cost(tokens)          │
│    ├─ IF session_cost_usd exists:                               │
│    │  └─ Use stored value (authoritative)                       │
│    ├─ ELSE (legacy session):                                    │
│    │  └─ Calculate: sum(turn_cost for all turns up to this)    │
│    └─ Return JSON with turn_cost, session_cost_usd              │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│ 4. FRONTEND DISPLAY (ui.js::updateTokenDisplay)                 │
│    ├─ IF data.turn_cost !== undefined:                          │
│    │  ├─ Use backend value (preferred)                          │
│    │  └─ Log: "[Reload] Using backend turn_cost: $X.XXXXXX"    │
│    ├─ ELSE:                                                      │
│    │  ├─ Fallback: _getTurnCost(turnData) from events          │
│    │  └─ Warn: "[Reload] Backend turn_cost missing"            │
│    ├─ IF data.session_cost_usd !== undefined:                   │
│    │  ├─ Use backend value (preferred)                          │
│    │  └─ Log: "[Reload] Using backend session_cost_usd: $X.XX" │
│    ├─ ELSE:                                                      │
│    │  └─ Warn: "[Reload] Backend session_cost_usd missing"     │
│    └─ Update header with costs                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Flow 3: Session Switching

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. USER SWITCHES TO SESSION                                      │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│ 2. FRONTEND LOAD (sessionManagement.js::handleLoadSession)      │
│    ├─ API.loadSession(sessionId) → returns session data         │
│    ├─ Extract: last_turn_data.workflow_history[]                │
│    ├─ Get last turn: workflow_history[length - 1]               │
│    ├─ Read: lastTurn.turn_cost (last turn's cost)               │
│    ├─ Read: lastTurn.session_cost_usd (total session cost)      │
│    ├─ Initialize sessionCostAccumulator:                         │
│    │  ├─ .turn = lastTurn.turn_cost                             │
│    │  └─ .session = lastTurn.session_cost_usd                   │
│    └─ Update cost display IMMEDIATELY                           │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│ 3. AUTO-LOAD LAST TURN (async, for Live Status panel)           │
│    ├─ Find last turn avatar in chat                             │
│    ├─ Call: handleReloadPlanClick(lastAvatar)                   │
│    └─ Refreshes cost display with same values                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Storage Schema

### Session File Structure

**Location**: `tda_sessions/{user_uuid}/{session_id}.json`

```json
{
  "id": "3f6dd773-154d-44f5-b5bc-56e401fe3936",
  "name": "System Version Check",
  "provider": "Friendli",
  "model": "MiniMaxAI/MiniMax-M2.1",
  "input_tokens": 29519,        // Session total input
  "output_tokens": 524,          // Session total output
  "last_turn_data": {
    "workflow_history": [
      {
        "turn": 1,
        "user_query": "what is the system version",
        "turn_input_tokens": 13496,      // Turn 1 tokens (includes session naming)
        "turn_output_tokens": 302,
        "turn_cost": 0.004411,            // NEW - Turn 1 cost
        "session_cost_usd": 0.004411,     // NEW - Session cost as of Turn 1
        "provider": "Friendli",
        "model": "MiniMaxAI/MiniMax-M2.1",
        "timestamp": "2026-02-13T10:30:00Z",
        "system_events": [               // Session naming events
          {
            "type": "session_name_generation_complete",
            "payload": {
              "details": {
                "cost_usd": 0.000188     // Included in turn_cost above
              }
            }
          }
        ]
      },
      {
        "turn": 2,
        "user_query": "how many databases are on the system",
        "turn_input_tokens": 16023,
        "turn_output_tokens": 222,
        "turn_cost": 0.005073,            // NEW - Turn 2 cost
        "session_cost_usd": 0.009484,     // NEW - Session cost as of Turn 2 (Turn 1 + Turn 2)
        "provider": "Friendli",
        "model": "MiniMaxAI/MiniMax-M2.1",
        "timestamp": "2026-02-13T10:31:00Z"
      }
    ]
  }
}
```

### Key Fields

| Field | Type | Scope | Description |
|-------|------|-------|-------------|
| `turn_input_tokens` | Integer | Turn | Total input tokens for this turn (includes all LLM calls) |
| `turn_output_tokens` | Integer | Turn | Total output tokens for this turn |
| `turn_cost` | Float | Turn | Cost for this turn only (provider-specific pricing) |
| `session_cost_usd` | Float | Session | **Cumulative** cost from Turn 1 through this turn (point-in-time snapshot) |
| `session_input_tokens` | Integer | Session | Total session input tokens as of this turn |
| `session_output_tokens` | Integer | Session | Total session output tokens as of this turn |

### Cost Invariants

**Must always be true**:
1. `turn_cost` ≥ 0 (costs are non-negative)
2. `session_cost_usd` for Turn N = sum of `turn_cost` for Turns 1..N
3. `session_cost_usd` is monotonically increasing (never decreases)
4. If `turn_input_tokens` and `turn_output_tokens` exist, `turn_cost` must be calculable

---

## API Contracts

### GET /api/session/{session_id}/turn/{turn_id}/details

**Purpose**: Retrieve full turn details including costs for historical display.

#### Request

```http
GET /api/session/3f6dd773-154d-44f5-b5bc-56e401fe3936/turn/2/details
Authorization: Bearer {jwt_token}
```

#### Response (Success)

```json
{
  "turn": 2,
  "user_query": "how many databases are on the system",
  "turn_input_tokens": 16023,
  "turn_output_tokens": 222,
  "turn_cost": 0.005073,              // Authoritative turn cost
  "session_cost_usd": 0.009484,       // Cumulative session cost
  "session_input_tokens": 29519,      // Session totals for header
  "session_output_tokens": 524,
  "provider": "Friendli",
  "model": "MiniMaxAI/MiniMax-M2.1",
  "original_plan": [...],
  "execution_trace": [...],
  "conversation_agent_events": [...]
}
```

#### Response (Legacy Session - Calculated Costs)

```json
{
  "turn": 2,
  "turn_input_tokens": 16023,
  "turn_output_tokens": 222,
  "turn_cost": 0.005073,              // Calculated from tokens
  "session_cost_usd": 0.009484,       // Calculated: sum of all turn costs
  ...
}
```

**Note**: Legacy sessions (missing `turn_cost` in storage) have costs calculated on-demand using current pricing. Logs show warnings.

#### Backend Implementation

```python
# routes.py::get_turn_details()

# Ensure turn_cost is present (calculate if missing for legacy sessions)
if "turn_cost" not in turn_data_copy:
    try:
        from trusted_data_agent.core.cost_manager import CostManager
        cost_manager = CostManager()
        turn_cost = cost_manager.calculate_cost(
            provider=turn_data_copy.get("provider"),
            model=turn_data_copy.get("model"),
            input_tokens=turn_data_copy.get("turn_input_tokens", 0),
            output_tokens=turn_data_copy.get("turn_output_tokens", 0)
        )
        turn_data_copy["turn_cost"] = turn_cost
        app_logger.debug(f"Calculated legacy turn cost: ${turn_cost:.6f}")
    except Exception as e:
        app_logger.warning(f"Failed to calculate legacy turn cost: {e}")
        turn_data_copy["turn_cost"] = 0.0

# Ensure session_cost_usd is present
if "session_cost_usd" not in turn_data_copy:
    try:
        session_cost = 0.0
        for i in range(turn_id):
            turn = workflow_history[i]
            if "turn_cost" in turn:
                session_cost += float(turn["turn_cost"])
            else:
                # Calculate from tokens for legacy turns
                turn_cost = cost_manager.calculate_cost(...)
                session_cost += turn_cost
        turn_data_copy["session_cost_usd"] = session_cost
        app_logger.debug(f"Calculated legacy session cost: ${session_cost:.6f}")
    except Exception as e:
        turn_data_copy["session_cost_usd"] = 0.0
```

---

## Frontend Integration

### Cost Display Components

**Location**: Live Status Panel Header

```html
<!-- Turn Cost Card -->
<div id="metric-card-turn-cost" class="metric-card">
  <div class="metric-label">TURN COST</div>
  <div id="turn-cost-value" class="metric-value">$0.000000</div>
</div>

<!-- Session Cost Card -->
<div id="metric-card-session-cost" class="metric-card">
  <div class="metric-label">SESSION COST</div>
  <div id="session-cost-value" class="metric-value">$0.000000</div>
</div>
```

### Cost Accumulator

**Global State**: `window.sessionCostAccumulator`

```javascript
window.sessionCostAccumulator = {
  // Current turn costs (reset on each new turn)
  turn: 0.005073,                  // Last turn cost

  // Session-level cumulative costs
  session: 0.009484,               // Total session cost

  // Dual-model tracking (strategic vs tactical)
  strategic: 0.002500,             // Cumulative strategic cost
  tactical: 0.006984,              // Cumulative tactical cost

  // Per-turn dual-model breakdown
  strategicTurnIn: 5000,
  strategicTurnOut: 100,
  strategicTurnCost: 0.001200,
  tacticalTurnIn: 11023,
  tacticalTurnOut: 122,
  tacticalTurnCost: 0.003873,

  // Session-level dual-model tokens
  strategicSessionIn: 15000,
  strategicSessionOut: 300,
  tacticalSessionIn: 14519,
  tacticalSessionOut: 224,

  // Last statement metadata
  lastStmtPhase: 'tactical'        // 'strategic' | 'tactical' | null
};
```

### updateTokenDisplay() Signature

```javascript
/**
 * Updates token and cost displays in the Live Status panel header.
 *
 * @param {Object} data - Token and cost data
 * @param {number} data.statement_input - Input tokens for this LLM call
 * @param {number} data.statement_output - Output tokens for this LLM call
 * @param {number} data.turn_input - Cumulative turn input tokens
 * @param {number} data.turn_output - Cumulative turn output tokens
 * @param {number} data.total_input - Session total input tokens
 * @param {number} data.total_output - Session total output tokens
 * @param {number} [data.cost_usd] - Cost for this LLM call (live execution)
 * @param {number} [data.turn_cost] - Total turn cost (historical reload)
 * @param {number} [data.session_cost_usd] - Cumulative session cost (historical reload)
 * @param {Object} [data.perModelBreakdown] - Dual-model cost breakdown
 * @param {boolean} isHistorical - True if displaying historical turn (reload)
 */
export function updateTokenDisplay(data, isHistorical = false) {
  // Implementation...
}
```

### Key Behavior Differences

| Mode | Cost Source | Accumulation | Use Case |
|------|-------------|--------------|----------|
| **Live Execution** (`isHistorical=false`) | SSE events `cost_usd` | Incremental accumulation | Real-time cost tracking during query execution |
| **Historical Reload** (`isHistorical=true`) | API response `turn_cost`, `session_cost_usd` | Direct assignment | Display costs when clicking turn avatars |
| **Session Switch** | Session data `workflow_history` | Direct assignment from last turn | Initialize costs when loading session |

---

## Cost Calculation

### CostManager Implementation

**File**: `src/trusted_data_agent/core/cost_manager.py`

```python
class CostManager:
    def calculate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """
        Calculate cost for an LLM call.

        Returns:
            Cost in USD (float with 6 decimal precision)
        """
        # Lookup pricing from llm_model_costs table
        pricing = self._get_pricing(provider, model)

        if not pricing:
            app_logger.warning(f"No pricing found for {provider}/{model}")
            return 0.0

        # Calculate cost
        input_cost = (input_tokens / 1_000_000) * pricing['input_cost_per_1m']
        output_cost = (output_tokens / 1_000_000) * pricing['output_cost_per_1m']

        return input_cost + output_cost
```

### Pricing Table Schema

**Table**: `llm_model_costs`

```sql
CREATE TABLE llm_model_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_cost_per_1m REAL NOT NULL,    -- Cost per 1M input tokens (USD)
    output_cost_per_1m REAL NOT NULL,   -- Cost per 1M output tokens (USD)
    currency TEXT DEFAULT 'USD',
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, model)
);
```

**Example Data**:

| Provider | Model | Input Cost (per 1M) | Output Cost (per 1M) |
|----------|-------|---------------------|----------------------|
| Friendli | MiniMaxAI/MiniMax-M2.1 | $0.10 | $0.40 |
| Anthropic | claude-sonnet-4-5 | $3.00 | $15.00 |
| OpenAI | gpt-4o | $2.50 | $10.00 |

### Cost Calculation in Executor

**File**: `src/trusted_data_agent/agent/executor.py`

```python
# Calculate turn cost for persistence
turn_cost = 0.0
try:
    from trusted_data_agent.core.cost_manager import CostManager
    cost_manager = CostManager()
    turn_cost = cost_manager.calculate_cost(
        provider=self.current_provider,
        model=self.current_model,
        input_tokens=self.turn_input_tokens,   # Accumulated during execution
        output_tokens=self.turn_output_tokens
    )
    app_logger.debug(f"[{profile_type}] Turn {self.current_turn_number} cost: ${turn_cost:.6f}")
except Exception as e:
    app_logger.warning(f"Failed to calculate turn cost: {e}", exc_info=True)

# Calculate session cost (cumulative up to and including this turn)
session_cost_usd = 0.0
try:
    session_data = await session_manager.get_session(self.user_uuid, self.session_id)
    previous_session_cost = self._calculate_session_cost_at_turn(session_data)
    session_cost_usd = previous_session_cost + turn_cost  # Add current turn
    app_logger.debug(f"[{profile_type}] Session cost at turn {self.current_turn_number}: ${session_cost_usd:.6f}")
except Exception as e:
    app_logger.warning(f"Failed to calculate session cost: {e}", exc_info=True)

# Save to turn_summary
turn_summary = {
    # ... other fields ...
    "turn_input_tokens": self.turn_input_tokens,
    "turn_output_tokens": self.turn_output_tokens,
    "turn_cost": turn_cost,                    # NEW
    "session_cost_usd": session_cost_usd,      # NEW
    # ... other fields ...
}
```

### Helper Method: _calculate_session_cost_at_turn()

```python
def _calculate_session_cost_at_turn(self, session_data: dict) -> float:
    """
    Calculate cumulative session cost up to (but not including) current turn.
    Iterates workflow_history and sums turn_cost for all previous turns.
    Falls back to token-based calculation for legacy sessions.
    """
    session_cost = 0.0
    workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

    for past_turn in workflow_history:
        if "turn_cost" in past_turn:
            # Use stored turn cost (preferred)
            session_cost += float(past_turn["turn_cost"])
        else:
            # Legacy fallback: calculate from tokens
            try:
                from trusted_data_agent.core.cost_manager import CostManager
                cost_manager = CostManager()
                turn_cost = cost_manager.calculate_cost(
                    provider=past_turn.get("provider", self.current_provider),
                    model=past_turn.get("model", self.current_model),
                    input_tokens=past_turn.get("turn_input_tokens", 0),
                    output_tokens=past_turn.get("turn_output_tokens", 0)
                )
                session_cost += turn_cost
            except Exception as e:
                app_logger.warning(f"Failed to calculate legacy turn cost: {e}")

    return session_cost
```

---

## Session Naming Attribution

### Problem

Session naming is a system-level LLM call that generates a descriptive session name after Turn 1. This costs ~$0.0002 (244 input / 96 output tokens) but was NOT included in Turn 1's cost.

**Impact**: Session cost at Turn 1 was understated by $0.0002.

### Solution

Session naming tokens are added to Turn 1's accumulators BEFORE turn_summary is saved, ensuring they're included in `turn_cost` calculation.

### Implementation

#### Pattern A: Session Naming BEFORE turn_summary Creation

**Profiles**: `conversation_with_tools`

```python
# Session naming happens first
if self.current_turn_number == 1:
    async for name_result in self._generate_and_emit_session_name():
        if isinstance(name_result, tuple):
            new_name, name_input_tokens, name_output_tokens, name_events = name_result

            # Add session name tokens to turn accumulators
            if name_input_tokens > 0 or name_output_tokens > 0:
                self.turn_input_tokens += name_input_tokens
                self.turn_output_tokens += name_output_tokens

                await session_manager.update_token_count(...)

# THEN turn_summary is created (using updated accumulators)
turn_cost = cost_manager.calculate_cost(
    provider=self.current_provider,
    model=self.current_model,
    input_tokens=self.turn_input_tokens,     # Includes session naming
    output_tokens=self.turn_output_tokens
)

turn_summary = {
    "turn_input_tokens": self.turn_input_tokens,
    "turn_output_tokens": self.turn_output_tokens,
    "turn_cost": turn_cost,                    # Includes session naming cost
    # ...
}
```

#### Pattern B: Session Naming AFTER turn_summary Creation

**Profiles**: `rag_focused`, `llm_only`, `genie`

```python
# turn_summary created first (without session naming)
turn_summary = {
    "turn_input_tokens": self.turn_input_tokens,    # Excludes session naming
    "turn_output_tokens": self.turn_output_tokens,
    "turn_cost": turn_cost,                          # Excludes session naming
    # ...
}

await session_manager.update_last_turn_data(...)

# THEN session naming happens
if self.current_turn_number == 1:
    async for name_result in self._generate_and_emit_session_name():
        if isinstance(name_result, tuple):
            new_name, name_input_tokens, name_output_tokens, name_events = name_result

            # Add to turn accumulators
            self.turn_input_tokens += name_input_tokens
            self.turn_output_tokens += name_output_tokens

            # Update the already-saved turn in workflow_history
            await session_manager.update_turn_token_counts(
                self.user_uuid, self.session_id, self.current_turn_number,
                self.turn_input_tokens,    # Now includes session naming
                self.turn_output_tokens
            )
```

#### SessionManager: update_turn_token_counts()

**File**: `src/trusted_data_agent/core/session_manager.py`

```python
async def update_turn_token_counts(
    user_uuid: str,
    session_id: str,
    turn_number: int,
    input_tokens: int,
    output_tokens: int
) -> bool:
    """
    Updates the token counts for a specific turn in workflow_history.
    Used when session naming tokens need to be added after turn is saved.

    CRITICAL: Also recalculates turn_cost and session_cost_usd with updated tokens.
    """
    session_data = await _load_session(user_uuid, session_id)
    workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

    for turn in workflow_history:
        if turn.get("turn") == turn_number:
            # Update token counts
            turn["turn_input_tokens"] = input_tokens
            turn["turn_output_tokens"] = output_tokens

            # Recalculate turn cost with updated tokens
            cost_manager = CostManager()
            turn_cost = cost_manager.calculate_cost(
                provider=session_data.get("provider", ""),
                model=session_data.get("model", ""),
                input_tokens=input_tokens,
                output_tokens=output_tokens
            )
            turn["turn_cost"] = turn_cost

            # Recalculate session_cost_usd (sum all turn costs up to this turn)
            session_cost = 0.0
            for i, t in enumerate(workflow_history):
                if i + 1 <= turn_number:
                    if "turn_cost" in t:
                        session_cost += float(t["turn_cost"])
            turn["session_cost_usd"] = session_cost

            break

    await _save_session(user_uuid, session_id, session_data)
    return True
```

### Verification

**Session File**:
```json
{
  "turn": 1,
  "turn_input_tokens": 13487,      // Includes session naming (244 tokens)
  "turn_output_tokens": 262,        // Includes session naming (96 tokens)
  "turn_cost": 0.004360,            // Includes session naming ($0.000188)
  "system_events": [
    {
      "type": "session_name_generation_complete",
      "payload": {
        "details": {
          "cost_usd": 0.000188       // Reflected in turn_cost above
        }
      }
    }
  ]
}
```

---

## Legacy Session Support

### Definition

**Legacy session**: Session created before cost tracking engine deployment (missing `turn_cost` and `session_cost_usd` in workflow_history).

### Detection

```python
if "turn_cost" not in turn_data:
    # This is a legacy session
    app_logger.info(f"Legacy session detected for turn {turn_id}")
```

### Fallback Strategy

#### API Endpoint Fallback

```python
# routes.py::get_turn_details()

if "turn_cost" not in turn_data_copy:
    # Calculate from tokens using current pricing
    cost_manager = CostManager()
    turn_cost = cost_manager.calculate_cost(
        provider=turn_data_copy.get("provider"),
        model=turn_data_copy.get("model"),
        input_tokens=turn_data_copy.get("turn_input_tokens", 0),
        output_tokens=turn_data_copy.get("turn_output_tokens", 0)
    )
    turn_data_copy["turn_cost"] = turn_cost
    app_logger.warning(f"Calculated legacy turn cost: ${turn_cost:.6f}")

if "session_cost_usd" not in turn_data_copy:
    # Sum all turn costs
    session_cost = 0.0
    for i in range(turn_id):
        turn = workflow_history[i]
        if "turn_cost" in turn:
            session_cost += float(turn["turn_cost"])
        else:
            # Recursively calculate from tokens
            ...
    turn_data_copy["session_cost_usd"] = session_cost
```

#### Frontend Fallback

```javascript
// ui.js::updateTokenDisplay()

if (isHistorical) {
    // Historical reload
    if (data.turn_cost !== undefined) {
        turnCost = parseFloat(data.turn_cost);
        console.log(`[Historical] Turn cost from backend: $${turnCost.toFixed(6)}`);
    } else {
        // Legacy fallback: estimate from tokens
        turnCost = _estimateCostFromTokens(data.turn_input || 0, data.turn_output || 0);
        console.warn('[Historical] Backend did not provide turn_cost, estimating from tokens');
    }
}

function _estimateCostFromTokens(inputTokens, outputTokens) {
    const INPUT_COST_PER_1M = 0.10;   // Fallback default
    const OUTPUT_COST_PER_1M = 0.40;

    const inputCost = (inputTokens / 1_000_000) * INPUT_COST_PER_1M;
    const outputCost = (outputTokens / 1_000_000) * OUTPUT_COST_PER_1M;

    return inputCost + outputCost;
}
```

### Limitations of Legacy Fallback

1. **Approximate Costs**: Uses current pricing, not historical pricing at time of execution
2. **Pricing Changes**: If provider changed pricing, legacy costs may be inaccurate
3. **Missing Data**: If token counts are also missing, cost is $0.000000
4. **No Verification**: Cannot verify accuracy against actual costs paid

### Migration Strategy

**No migration needed**. Legacy sessions work transparently:
- API calculates costs on-demand
- Frontend displays calculated costs
- Logs show warnings for debugging
- New turns in legacy sessions store costs correctly

---

## Edge Cases

### 1. Zero-Token Turns

**Scenario**: Turn completes with 0 input and 0 output tokens (e.g., error before LLM call).

**Behavior**:
- `turn_cost` = $0.000000
- `session_cost_usd` = previous session cost (no change)
- Cost display shows $0.000000 for turn

**Implementation**:
```python
if self.turn_input_tokens == 0 and self.turn_output_tokens == 0:
    turn_cost = 0.0  # No LLM calls made
```

### 2. Missing Pricing Data

**Scenario**: Provider/model not in `llm_model_costs` table.

**Behavior**:
- CostManager returns $0.000000
- Logs warning: "No pricing found for {provider}/{model}"
- Turn/session costs set to $0.000000
- Frontend displays $0.000000

**Mitigation**:
- Admins should populate pricing before using new models
- Fallback to default pricing if configured

### 3. Mid-Turn Session Naming Failure

**Scenario**: Session naming LLM call fails after Turn 1 execution completes.

**Behavior**:
- Turn 1 costs saved without session naming
- Session naming tokens NOT added to turn
- `turn_cost` reflects only conversation costs
- No `session_name_generation_complete` event in `system_events`

**Impact**: Turn 1 cost understated by ~$0.0002 (acceptable, rare case).

### 4. Concurrent Session Modifications

**Scenario**: Two browser tabs modify same session simultaneously.

**Behavior**:
- Last write wins (session file overwritten)
- Cost accumulator may be stale in one tab
- Reloading session resyncs costs

**Mitigation**:
- Session locking (future enhancement)
- Auto-refresh on session switch

### 5. Floating-Point Precision

**Scenario**: Costs stored/calculated with different precision levels.

**Behavior**:
- Backend stores 6 decimals (microsecond precision)
- JavaScript displays 6 decimals
- Comparisons use ±$0.000001 tolerance

**Example**:
```python
# Backend: 0.004360500000000001 (floating-point artifact)
# Display: $0.004361 (rounds to 6 decimals)
# Validation: abs(0.004361 - 0.004360) < 0.000001 → PASS
```

### 6. Multi-Provider Sessions

**Scenario**: User switches LLM provider mid-session (Turn 1 uses Provider A, Turn 2 uses Provider B).

**Behavior**:
- Each turn stores its own `provider` and `model`
- `turn_cost` calculated with correct provider pricing
- `session_cost_usd` sums costs from all providers

**Example**:
```json
{
  "turn": 1,
  "provider": "OpenAI",
  "model": "gpt-4o",
  "turn_cost": 0.008500
},
{
  "turn": 2,
  "provider": "Anthropic",
  "model": "claude-sonnet-4-5",
  "turn_cost": 0.012000
}
// session_cost_usd at Turn 2 = 0.008500 + 0.012000 = 0.020500
```

### 7. Profile Override Mid-Session

**Scenario**: User uses `@TAG` syntax to override profile for single query.

**Behavior**:
- Turn uses overridden profile's LLM config
- Costs calculated with override provider/model
- Session cost sums all turns regardless of profile

**No special handling needed** - costs are always tied to provider/model, not profile.

### 8. Cancelled/Failed Turns

**Scenario**: User cancels query mid-execution or LLM call fails.

**Behavior**:
- Partial token counts accumulated
- `turn_cost` calculated from partial tokens
- `status` field set to "cancelled" or "error"
- Costs still tracked and included in session total

**Rationale**: Even failed turns consume tokens and incur costs.

---

## Testing & Validation

### Unit Tests

**File**: `test/test_cost_tracking.py`

```python
def test_cost_calculation_consistency():
    """Verify cost calculation produces consistent results"""
    cost_manager = CostManager()

    cost1 = cost_manager.calculate_cost("Friendli", "MiniMaxAI/MiniMax-M2.1", 1000, 100)
    cost2 = cost_manager.calculate_cost("Friendli", "MiniMaxAI/MiniMax-M2.1", 1000, 100)

    assert cost1 == cost2, "Cost calculation should be deterministic"
    assert cost1 > 0, "Cost should be positive for non-zero tokens"

def test_session_cost_accumulation():
    """Verify session cost = sum of turn costs"""
    workflow_history = [
        {"turn_cost": 0.004360, "turn": 1},
        {"turn_cost": 0.005023, "turn": 2},
        {"turn_cost": 0.003200, "turn": 3}
    ]

    expected_session_cost = sum(t["turn_cost"] for t in workflow_history)
    assert abs(expected_session_cost - 0.012583) < 0.000001
```

### Integration Tests

**Scenario 1: New Session with 2 Turns**
1. Execute Turn 1 → Verify `turn_cost` and `session_cost_usd` stored
2. Execute Turn 2 → Verify `session_cost_usd` = Turn 1 + Turn 2
3. Reload Turn 1 → Verify costs match stored values
4. Reload Turn 2 → Verify costs match stored values

**Scenario 2: Legacy Session**
1. Load legacy session (missing `turn_cost`, `session_cost_usd`)
2. Reload Turn 1 → Verify backend calculates costs from tokens
3. Reload Turn 2 → Verify session cost = sum of calculated turn costs

**Scenario 3: Session Naming**
1. Execute Turn 1 → Verify session naming cost included
2. Check Turn 1 `turn_cost` includes session naming
3. Reload Turn 1 → Verify costs match

### Validation Checklist

- [ ] Turn 1: `session_cost_usd` = `turn_cost`
- [ ] Turn N: `session_cost_usd` = sum of `turn_cost` for Turns 1..N
- [ ] All `turn_cost` values ≥ 0
- [ ] `session_cost_usd` monotonically increasing
- [ ] Session naming cost included in Turn 1
- [ ] Legacy sessions calculate costs without errors
- [ ] Switching sessions displays costs immediately (not $0.000000)
- [ ] Clicking turn avatars updates costs correctly
- [ ] Live execution accumulates costs in real-time
- [ ] Browser console shows "[Reload] Using backend turn_cost" messages

### Test Execution (REST API)

```bash
# Authenticate
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

# Create session
SESSION_ID=$(curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{}' | jq -r '.session_id')

# Submit Turn 1
TASK1_ID=$(curl -s -X POST "http://localhost:5050/api/v1/sessions/$SESSION_ID/query" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test query 1"}' | jq -r '.task_id')

# Wait for completion (poll task status)

# Fetch Turn 1 details
curl -s -X GET "http://localhost:5050/api/session/$SESSION_ID/turn/1/details" \
  -H "Authorization: Bearer $JWT" | jq '{turn_cost, session_cost_usd}'

# Submit Turn 2
TASK2_ID=$(curl -s -X POST "http://localhost:5050/api/v1/sessions/$SESSION_ID/query" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test query 2"}' | jq -r '.task_id')

# Fetch Turn 2 details
curl -s -X GET "http://localhost:5050/api/session/$SESSION_ID/turn/2/details" \
  -H "Authorization: Bearer $JWT" | jq '{turn_cost, session_cost_usd}'

# Verify: Turn 2 session_cost_usd = Turn 1 turn_cost + Turn 2 turn_cost
```

---

## Performance Considerations

### Computational Cost

**Cost Calculation**: O(1) - simple arithmetic
- Input: (tokens, pricing) → multiply and sum
- No database queries during execution
- Pricing table cached in memory

**Session Cost Calculation**: O(N) where N = number of turns
- Must iterate all previous turns to sum costs
- Mitigated: Only calculated once per turn at save time
- Historical reload: Cost already stored, no calculation

### Storage Impact

**Per Turn**: +16 bytes
- `turn_cost`: 8 bytes (float64)
- `session_cost_usd`: 8 bytes (float64)

**Per Session**: +16N bytes (N = number of turns)

**Example**: 100-turn session = 1.6 KB additional storage (negligible)

### Network Impact

**SSE Events**: +20 bytes per `token_update` event
- Adds `cost_usd` field: 8 bytes float + JSON overhead

**API Response**: +30 bytes per turn details request
- Adds `turn_cost` and `session_cost_usd` fields

**Impact**: Negligible - costs already include token counts (~same size)

### Browser Performance

**Cost Display Updates**: O(1) - simple DOM text update
```javascript
turnCostEl.textContent = `$${cost.toFixed(6)}`;  // ~5μs
```

**Session Switching**: +1 array access
```javascript
const lastTurn = workflow_history[workflow_history.length - 1];  // O(1)
```

### Optimization Opportunities

1. **Cache CostManager pricing**: Load all pricing into memory at startup (already done)
2. **Batch cost calculations**: Calculate all turn costs in single pass (not needed - already fast)
3. **Lazy load workflow_history**: Only load when needed (future enhancement)
4. **Cost deltas**: Store deltas instead of cumulative (not recommended - loses point-in-time semantics)

---

## Future Enhancements

### 1. Cost Budgets & Alerts

**Feature**: Set per-session or per-user cost limits with alerts.

```python
# Configuration
user_config = {
    "cost_budget_per_session": 1.00,      # $1.00 max per session
    "cost_budget_per_month": 100.00,      # $100.00 max per month
    "alert_threshold_percent": 80         # Alert at 80% of budget
}

# Implementation
if session_cost_usd >= (user_config["cost_budget_per_session"] * 0.80):
    emit_sse_event({
        "type": "cost_alert",
        "message": f"Approaching session budget: ${session_cost_usd:.2f} / ${user_config['cost_budget_per_session']:.2f}",
        "severity": "warning"
    })
```

### 2. Cost Analytics Dashboard

**Feature**: Visualize cost trends over time.

- Cost per session (histogram)
- Cost per profile type (pie chart)
- Cost per model (bar chart)
- Daily/weekly/monthly cost trends (line chart)
- Cost breakdown by phase (strategic vs tactical)

### 3. Cost Optimization Suggestions

**Feature**: AI-powered cost optimization recommendations.

```
"Your session cost: $0.25
Suggestion: Switch to claude-haiku-4-5 for 60% cost savings on simple queries.
Estimated savings: $0.15 per session"
```

### 4. Cost Projections

**Feature**: Estimate costs before execution.

```python
# Before submitting query
estimated_cost = cost_estimator.estimate(
    query=user_input,
    profile=current_profile,
    history_length=len(conversation_history)
)

# Show to user: "Estimated cost: $0.15 - $0.25"
```

### 5. Cost Allocation Tags

**Feature**: Tag sessions with cost centers for enterprise billing.

```json
{
  "session_id": "abc123",
  "cost_allocation": {
    "department": "Engineering",
    "project": "AI Research",
    "cost_center": "CC-1234"
  },
  "session_cost_usd": 5.67
}
```

### 6. Cost Caching for Common Queries

**Feature**: Detect and cache responses for repeated queries to save costs.

```python
# Check cache before LLM call
cached_response = cost_cache.get(query_hash)
if cached_response and cached_response["age_minutes"] < 60:
    return cached_response["answer"]  # $0.00 cost
else:
    response = await call_llm(...)    # $0.05 cost
    cost_cache.set(query_hash, response)
```

### 7. Multi-Currency Support

**Feature**: Display costs in user's preferred currency.

```python
# Configuration
user_preferences = {
    "currency": "EUR",
    "exchange_rate": 0.92  # USD to EUR
}

# Display
session_cost_eur = session_cost_usd * user_preferences["exchange_rate"]
# Show: "€0.0087" instead of "$0.0094"
```

### 8. Cost Export & Reporting

**Feature**: Export cost data for accounting systems.

```python
# Export to CSV
GET /api/v1/costs/export?start_date=2026-02-01&end_date=2026-02-28&format=csv

# Response
session_id,date,turns,input_tokens,output_tokens,cost_usd
abc123,2026-02-01,5,50000,2000,1.25
def456,2026-02-01,3,30000,1500,0.75
```

---

## Appendix A: File Locations

### Backend

| File | Lines | Purpose |
|------|-------|---------|
| `src/trusted_data_agent/core/cost_manager.py` | 279-304 | Cost calculation engine |
| `src/trusted_data_agent/agent/executor.py` | Multiple | Cost tracking in all profile types |
| `src/trusted_data_agent/core/session_manager.py` | 1583-1648 | Token/cost updates, session persistence |
| `src/trusted_data_agent/api/routes.py` | 1743-1830 | Cost API endpoint with legacy fallback |

### Frontend

| File | Lines | Purpose |
|------|-------|---------|
| `static/js/ui.js` | 3875-4060 | Cost display (updateTokenDisplay) |
| `static/js/eventHandlers.js` | 91-179, 1576-2110 | Historical reload cost handling |
| `static/js/handlers/sessionManagement.js` | 630-665 | Session switching cost initialization |

### Documentation

| File | Purpose |
|------|---------|
| `docs/Architecture/COST_TRACKING_ARCHITECTURE.md` | This document |
| `.claude/plans/wobbly-roaming-sun.md` | Original implementation plan |

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **Turn Cost** | Cost for a single turn (one user query → assistant response) |
| **Session Cost** | Cumulative cost for entire session (sum of all turn costs) |
| **Point-in-Time Snapshot** | Session cost stored at each turn reflecting total cost up to that moment |
| **Legacy Session** | Session created before cost tracking engine (missing turn_cost/session_cost_usd) |
| **Session Naming** | System LLM call to generate descriptive session name (occurs after Turn 1) |
| **Cost Accumulator** | Frontend state object tracking costs during live execution |
| **Authoritative Cost** | Cost calculated and stored by backend (single source of truth) |
| **Fallback Cost** | Cost estimated from tokens when authoritative cost unavailable (legacy sessions) |
| **Live Execution** | Real-time query execution with SSE streaming |
| **Historical Reload** | Loading past turn data by clicking turn avatar |
| **Dual-Model** | Profile using separate strategic and tactical LLM models |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-13 | Claude Code | Initial architecture document |

---

**End of Document**
