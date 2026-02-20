# Extension Architecture

> Post-processing pipeline that transforms non-deterministic LLM output into structured, machine-parseable formats for downstream workflow tools (n8n, Flowise, Airflow).

## Overview

Uderia's LLM answers are natural-language text — inherently non-deterministic. Downstream workflow tools need structured, deterministic output to branch on. The Extensions system adds a post-processing pipeline triggered by `#name:param` syntax that transforms LLM output into machine-parseable formats.

Extensions complement the existing `@TAG` input routing with `#Extension` output processing:

```
@PROFILE (how to answer) → Query → LLM Answer → #Extension (structured output) → n8n/Flowise
```

---

## System Architecture

### High-Level Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                        │
│                                                                              │
│  ┌──────────┐    ┌──────────────┐    ┌────────────────┐    ┌─────────────┐  │
│  │ # Auto-  │    │ Badge Mgmt   │    │ SSE Event      │    │ Tag Render  │  │
│  │ complete │───▶│ (amber chips) │───▶│ Handling       │◀───│ (clickable) │  │
│  │ Dropdown │    │ activeExts[] │    │ ext_start/     │    │ + Popover   │  │
│  └──────────┘    └──────────────┘    │ ext_complete/  │    └─────────────┘  │
│                         │            │ ext_results    │           ▲          │
│                         ▼            └────────────────┘           │          │
│                  ┌──────────────┐                          ┌─────────────┐  │
│                  │ Submit Query │                          │ Session     │  │
│                  │ extensions:  │                          │ Reload      │  │
│                  │ [{name,param}]                          │ (persisted) │  │
│                  └──────┬───────┘                          └─────────────┘  │
│                         │                                        ▲          │
└─────────────────────────┼────────────────────────────────────────┼──────────┘
                          │  HTTP / SSE                            │
┌─────────────────────────┼────────────────────────────────────────┼──────────┐
│                         ▼                              BACKEND   │          │
│                  ┌──────────────┐                                │          │
│                  │ API Routes   │                                │          │
│                  │ (SSE + REST) │                                │          │
│                  └──────┬───────┘                                │          │
│                         ▼                                        │          │
│  ┌──────────────────────────────────────────────────────┐        │          │
│  │           execution_service.py                        │        │          │
│  │                                                       │        │          │
│  │  1. Save user message (with extension_specs)          │        │          │
│  │  2. Execute main logic (PlanExecutor / Genie)         │        │          │
│  │  3. _run_extensions()                                 │        │          │
│  │     ├─ Lookup activated extensions (db.py)            │        │          │
│  │     ├─ Build ExtensionContext from final_payload      │        │          │
│  │     ├─ ExtensionRunner.run() — serial with chaining   │        │          │
│  │     └─ Emit extension_results SSE event               │        │          │
│  │  4. _persist_extension_results()                      │        │          │
│  │     ├─ Aggregate token costs                          │────────┘          │
│  │     ├─ Update session token counts                    │                   │
│  │     └─ append_extension_results_to_turn()             │                   │
│  └──────────────────────────────────────────────────────┘                   │
│                         │                                                    │
│           ┌─────────────┼──────────────┐                                    │
│           ▼             ▼              ▼                                     │
│  ┌──────────────┐ ┌───────────┐ ┌──────────────┐                           │
│  │ Extension    │ │ Extension │ │ Extension    │                           │
│  │ Manager      │ │ Runner    │ │ DB           │                           │
│  │ (singleton)  │ │ (serial)  │ │ (per-user)   │                           │
│  └──────┬───────┘ └───────────┘ └──────────────┘                           │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────────────────────────────┐                               │
│  │  Built-in Extensions                      │                               │
│  │  ┌──────┐ ┌──────────┐ ┌───────┐ ┌─────┐│                               │
│  │  │#json │ │#decision │ │#extract│ │#classify│                            │
│  │  └──────┘ └──────────┘ └───────┘ └─────┘│                               │
│  └──────────────────────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### File Structure

```
src/trusted_data_agent/extensions/
├── __init__.py              # Public API exports
├── models.py                # ExtensionContext, ExtensionResult, OutputTarget
├── base.py                  # Abstract Extension base class
├── manager.py               # Singleton discovery & loading (ExtensionManager)
├── runner.py                # Serial execution orchestrator (ExtensionRunner)
└── db.py                    # Per-user activation persistence (SQLite)

extensions/
├── extension_registry.json  # Central registry of all extensions
├── schemas/
│   └── extension-manifest-schema.json
└── builtin/
    ├── json/                # #json — Structured JSON output
    │   ├── manifest.json
    │   └── json_ext.py
    ├── decision/            # #decision — Workflow branching
    │   ├── manifest.json
    │   └── decision.py
    ├── extract/             # #extract — Data extraction
    │   ├── manifest.json
    │   └── extract.py
    └── classify/            # #classify — Answer classification
        ├── manifest.json
        └── classify.py

static/js/
├── main.js                  # # autocomplete, badge management
├── eventHandlers.js         # Extension parsing, SSE event handling, recall
├── ui.js                    # Extension tags on messages, click-to-view
├── notifications.js         # REST notification path (extension_specs)
└── handlers/
    ├── extensionHandler.js  # Extensions configuration tab UI
    └── sessionManagement.js # Session reload with extension_specs

static/css/main.css          # .extension-tag, .active-extension-badge, etc.
templates/index.html         # Extensions tab, autocomplete containers
```

---

## Core Data Models

### OutputTarget

Controls where extension output is displayed in the UI:

| Value | Behavior |
|-------|----------|
| `silent` | API-only — no UI display. Default for automation extensions. Result accessible via tag click popover or REST API. |
| `chat_append` | Appended below the LLM answer in the chat log. Visible immediately. |
| `status_panel` | Rendered in the Live Status panel. |

### ExtensionContext

Rich context passed to every extension's `execute()` method. Built from the final LLM result payload:

```python
@dataclass
class ExtensionContext:
    # Core answer data
    answer_text: str                    # Plain text LLM answer
    answer_html: str                    # HTML formatted answer
    original_query: str                 # User query including #tags
    clean_query: str                    # Query with #tags stripped (what LLM saw)

    # Session & turn identity
    session_id: str
    turn_id: int
    task_id: Optional[str]              # REST task ID (None for SSE)

    # Profile context
    profile_tag: Optional[str]          # e.g., "@OPTIM"
    profile_type: str                   # tool_enabled, llm_only, rag_focused, genie

    # LLM provider info
    provider: Optional[str]             # "anthropic", "google", "openai", etc.
    model: Optional[str]                # "claude-3-opus", "gemini-2.0-flash", etc.

    # Token & cost data
    turn_input_tokens: int
    turn_output_tokens: int
    total_input_tokens: int
    total_output_tokens: int

    # Execution trace (tool_enabled profiles)
    execution_trace: list               # Full phase/tool/result history
    tools_used: list[str]               # MCP tool names invoked
    collected_data: list                # Structured data from tool results

    # Serial chaining (auto-populated by runner)
    previous_extension_results: dict    # {name: ExtensionResult} from prior extensions
```

### ExtensionResult

Standardized output returned by every extension:

```python
@dataclass
class ExtensionResult:
    extension_name: str                 # Name of the extension
    content: Any                        # Primary output (dict for JSON, str for text)
    content_type: str = "application/json"
    success: bool = True
    error: Optional[str] = None
    output_target: str = "silent"       # Where to display in UI
    metadata: dict = field(default_factory=dict)

    # Cost KPI fields (for LLM-calling extensions)
    extension_input_tokens: int = 0
    extension_output_tokens: int = 0
    extension_cost_usd: float = 0.0
```

---

## Extension Base Class

All extensions must subclass `Extension` and implement `name` and `execute()`:

```python
class Extension(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier matching #name syntax. Lowercase, no spaces."""

    @property
    def output_target(self) -> OutputTarget:
        """Where output displays. Default: SILENT."""
        return OutputTarget.SILENT

    @abstractmethod
    async def execute(self, context: ExtensionContext, param: Optional[str] = None) -> ExtensionResult:
        """Transform the LLM answer into structured output."""

    def validate_param(self, param: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Optional parameter validation. Default: accept all."""
        return True, None
```

### Extension Manifest

Each extension directory contains a `manifest.json`:

```json
{
  "name": "json-output",
  "version": "1.0.0",
  "extension_id": "json",
  "display_name": "JSON Output",
  "description": "Wraps the LLM answer into a standardized JSON structure",
  "author": "TDA Core Team",
  "category": "Transform",
  "files": { "extension": "json_ext.py" },
  "output_target": "chat_append",
  "parameters": {
    "supported": true,
    "description": "Output detail level",
    "examples": ["minimal", "full"],
    "allowed_values": ["minimal", "full"]
  },
  "output_schema": { ... },
  "keywords": ["json", "structured", "n8n", "api"]
}
```

**Categories:** Transform, Automation, Export, Visualization, Custom

---

## Extension Manager (Singleton)

Discovers, loads, and manages extensions. Mirrors the `rag_template_manager.py` pattern.

```python
manager = get_extension_manager()      # Singleton accessor

manager.list_extensions()              # All extensions with metadata (for UI/autocomplete)
manager.get_extension("json")          # Get loaded extension by name
manager.get_all_names()                # ["json", "decision", "extract", "classify"]
manager.get_extension_source("json")   # Python source code (for "View Script")
manager.get_manifest("json")           # Full manifest dict
manager.reload()                       # Hot-reload from disk
```

**Discovery order:**
1. Built-in: `extensions/builtin/`
2. User: `~/.tda/extensions/` (overrides built-in)

**Dynamic loading:** Uses `importlib.util.spec_from_file_location()` to import Python modules at runtime. Scans for `Extension` subclasses in each module.

---

## Extension Runner (Serial Execution)

Orchestrates serial execution of extensions with result chaining:

```python
runner = ExtensionRunner(manager)
results = await runner.run(
    extension_specs=[
        {"name": "json", "extension_id": "json", "param": "minimal"},
        {"name": "decision", "extension_id": "decision", "param": "critical"}
    ],
    context=extension_context,
    event_handler=sse_emit_handler
)
```

**Execution flow per extension:**

```
1. Lookup extension by extension_id in manager
2. Validate parameter via ext.validate_param(param)
3. Inject previous results: context.previous_extension_results = {prior results}
4. Emit extension_start SSE event
5. Execute: await ext.execute(context, param)
6. Record execution_time_ms in metadata
7. Emit extension_complete SSE event
8. Store result keyed by activation_name
```

**Error handling:** Exceptions are caught per-extension and recorded as `ExtensionResult(success=False, error=str(e))`. Extensions never break the main answer.

**SSE event schema:**

```json
// extension_start
{"type": "extension_start", "payload": {"name": "json", "param": "minimal"}}

// extension_complete
{"type": "extension_complete", "payload": {"name": "json", "success": true, "content_type": "application/json", "output_target": "chat_append"}}

// extension_results (combined, after all extensions)
{"type": "extension_results", "payload": {"json": {...}, "decision": {...}}}
```

---

## Per-User Activation System

Extensions must be **activated** per-user before they appear in the `#` autocomplete. This supports multiple activations of the same extension with different default parameters.

### Database Schema (`user_extensions` table)

```sql
CREATE TABLE user_extensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_uuid VARCHAR(36) NOT NULL,
    extension_id VARCHAR(100) NOT NULL,       -- Base extension (json, decision, etc.)
    activation_name VARCHAR(100) NOT NULL,    -- User-facing #name
    is_active BOOLEAN NOT NULL DEFAULT 1,
    default_param VARCHAR(255),               -- Default param (e.g., "critical")
    config_json TEXT,                         -- Advanced config as JSON
    activated_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE(user_uuid, activation_name)
);
```

### Auto-Naming

When activating the same extension multiple times:

| Activation | activation_name | extension_id |
|-----------|-----------------|--------------|
| First | `json` | `json` |
| Second | `json2` | `json` |
| Third | `json3` | `json` |

The user types `#json` or `#json2` — each resolves to the same Python extension but with potentially different `default_param`.

### Activation vs Extension ID

```
activation_name = "json"       → User types #json      → Runs json extension with no default param
activation_name = "json2"      → User types #json2     → Runs json extension with default_param="full"
activation_name = "alertcheck" → User types #alertcheck → Runs decision extension with default_param="critical"
```

Query-time `#name:param` overrides the activation's `default_param`:
```
#json:minimal  → param="minimal" (overrides default)
#json          → param=default_param from activation (or null)
```

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/extensions` | GET | List all available extensions (registry) |
| `/v1/extensions/activated` | GET | List user's activated extensions |
| `/v1/extensions/<ext_id>/activate` | POST | Activate a new instance |
| `/v1/extensions/activations/<name>/deactivate` | POST | Soft-delete activation |
| `/v1/extensions/activations/<name>/config` | PUT | Update default_param/config |
| `/v1/extensions/activations/<name>/rename` | PUT | Rename activation |
| `/v1/extensions/activations/<name>` | DELETE | Hard-delete activation |
| `/v1/extensions/<name>/source` | GET | Get Python source code |
| `/v1/extensions/reload` | POST | Hot-reload from disk (admin) |

---

## Execution Service Integration

Extensions hook into the main execution pipeline in `execution_service.py`:

### Entry Point: `run_agent_execution()`

```python
async def run_agent_execution(
    user_uuid, session_id, user_input, event_handler,
    ...,
    extension_specs: list = None    # [{"name": "json", "param": "minimal"}]
)
```

**Integration flow:**

```
1. Save user message → add_message_to_histories(extension_specs=extension_specs)
2. Execute main logic (PlanExecutor or GenieCoordinator)
3. Capture final_result_payload
4. If extension_specs present:
   a. _run_extensions(specs, payload, ...)     → (serialized, events)
   b. _persist_extension_results(serialized, events, ...)
5. Return final_result_payload
```

### `_run_extensions()`

1. **Resolve specs:** Lookup user's activated extensions, merge `default_param` with query-time param
2. **Build context:** Create `ExtensionContext` from `final_result_payload`
3. **Wrap event handler:** `collecting_event_handler` forwards events to frontend AND captures lifecycle events for persistence
4. **Execute:** `runner.run(resolved_specs, context, collecting_handler)`
5. **Emit combined results:** Single `extension_results` SSE event
6. **Return:** `(serialized_results, collected_events)` tuple

### `_persist_extension_results()`

1. **Aggregate costs:** Sum `extension_input_tokens` / `extension_output_tokens` across all results
2. **Update session tokens:** If non-zero, call `session_manager.update_token_count()` and emit `token_update` SSE event
3. **Persist to session:** Call `session_manager.append_extension_results_to_turn()` — patches the already-saved turn in `workflow_history`

### Resulting Session Data

**User message** (in `session_history`):
```json
{
  "role": "user",
  "content": "What is the CPU usage?",
  "source": "text",
  "profile_tag": "OPTIM",
  "extension_specs": [
    {"name": "json", "param": "minimal"},
    {"name": "decision", "param": "critical"}
  ]
}
```

**Turn data** (in `workflow_history`):
```json
{
  "turn": 1,
  "user_query": "What is the CPU usage?",
  "extension_results": {
    "json": {
      "content": {"query": "...", "answer": "..."},
      "content_type": "application/json",
      "success": true,
      "output_target": "chat_append"
    },
    "decision": {
      "content": {"result": "threshold_exceeded", "severity": "critical", ...},
      "content_type": "application/json",
      "success": true,
      "output_target": "silent"
    }
  },
  "extension_events": [
    {"type": "extension_start", "payload": {"name": "json", "param": "minimal"}},
    {"type": "extension_complete", "payload": {"name": "json", "success": true}},
    {"type": "extension_start", "payload": {"name": "decision", "param": "critical"}},
    {"type": "extension_complete", "payload": {"name": "decision", "success": true}},
    {"type": "extension_results", "payload": {...}}
  ]
}
```

---

## Built-in Extensions

All built-in extensions use **deterministic processing** (no LLM calls, 0 tokens) for predictable output.

### #json — Structured JSON Output

| Property | Value |
|----------|-------|
| Category | Transform |
| Output Target | `chat_append` (visible in chat) |
| Parameters | `minimal`, `full` |

Wraps the LLM answer and execution metadata into a standardized JSON structure:

| Mode | Fields |
|------|--------|
| `#json` (default) | query, answer, session_id, turn_id, profile_tag, profile_type, provider, model, tokens, tools_used, timestamp |
| `#json:minimal` | query, answer |
| `#json:full` | All default fields + execution_trace, collected_data |

**Example output (default):**
```json
{
  "query": "Show me the top 5 tables",
  "answer": "The top 5 tables are...",
  "session_id": "sess_abc123",
  "turn_id": 1,
  "profile_tag": "@OPTIM",
  "provider": "anthropic",
  "model": "claude-3-opus",
  "tokens": {"input": 3250, "output": 187, "total_input": 5430, "total_output": 512},
  "tools_used": ["base_readQuery", "TDA_FinalReport"],
  "timestamp": "2026-02-20T15:30:45Z"
}
```

### #decision — Workflow Branching

| Property | Value |
|----------|-------|
| Category | Automation |
| Output Target | `silent` (API-only) |
| Parameters | `binary`, `critical`, `warning` |

Heuristic keyword analysis to produce branching output for n8n Switch nodes:

**Signal keywords:**

| Severity | Keywords |
|----------|----------|
| Critical | critical, urgent, failure, down, outage, crash, exceeded |
| Warning | warning, elevated, approaching, degraded, slow, spike |
| OK | normal, healthy, stable, optimal, below threshold |
| Action | recommend, should, suggest, action required |

**Example output (multi-branch):**
```json
{
  "result": "threshold_exceeded",
  "severity": "critical",
  "confidence": 0.78,
  "action_recommended": true,
  "branch_key": "threshold_exceeded_critical",
  "signal_counts": {"critical": 2, "warning": 0, "ok": 0, "action": 1},
  "reasoning": "Analyzed 1284 chars"
}
```

**Binary mode** (`#decision:binary`):
```json
{
  "result": "yes",
  "action_recommended": true,
  "branch_key": "yes"
}
```

**n8n integration:** Branch on `branch_key` or `severity` in Switch node.

### #extract — Structured Data Extraction

| Property | Value |
|----------|-------|
| Category | Transform |
| Output Target | `silent` (API-only) |
| Parameters | `numbers`, `percentages`, `entities` |

Regex-based extraction of structured data from LLM answers:

| Type | Pattern | Example Match |
|------|---------|---------------|
| Numbers | `label: 1,234 unit` | `{"label": "Active Connections", "value": 1234, "unit": ""}` |
| Percentages | `\d+(\.\d+)?%` | `[87.5, 92.1]` |
| Entities | `[A-Z][A-Z0-9_]{2,}` | `["CUSTOMER_TABLE", "SYS.ADMIN"]` |

**Example output (full):**
```json
{
  "numbers": [
    {"label": "CPU", "value": 94, "unit": "%"},
    {"label": "Memory", "value": 87.5, "unit": "GB"}
  ],
  "percentages": [94.0, 87.5],
  "entities": ["DW_PROD", "DW_DEV"],
  "source_length": 2847
}
```

### #classify — Answer Classification

| Property | Value |
|----------|-------|
| Category | Automation |
| Output Target | `silent` (API-only) |
| Parameters | None |

Keyword-scoring classification into predefined categories:

| Category | Keywords |
|----------|----------|
| alert | critical, urgent, failure, down, outage, crash, error |
| performance | cpu, memory, disk, throughput, latency, slow, bottleneck |
| data_quality | missing, null, duplicate, invalid, quality, corrupt |
| capacity | storage, space, growth, forecast, full, quota |
| security | access, permission, unauthorized, breach, audit |
| data_report | rows, records, table, column, query, result, count |
| informational | (fallback — no keywords matched, confidence 0.5) |

**Example output:**
```json
{
  "primary_category": "performance",
  "confidence": 0.82,
  "all_categories": {"performance": 4, "alert": 1},
  "branch_key": "performance",
  "query": "What is the CPU usage?"
}
```

---

## Frontend Architecture

### Query Input Flow

```
User types in input box
        │
        ├─ Starts with @ → Profile autocomplete dropdown (orange)
        ├─ Contains #     → Extension autocomplete dropdown (amber)
        └─ Other text     → RAG suggestions (if enabled)
```

### Extension Autocomplete

**Trigger:** User types `#` anywhere in the input.

**Data source:** `window.extensionState.activated` — loaded from `GET /v1/extensions/activated` on page load.

**Flow:**

```
1. User types "#dec"
2. Input handler detects /#(\w*)$/ pattern
3. Filters activated extensions by prefix match
4. Shows dropdown with amber-accented items
5. Keyboard: Arrow Up/Down to navigate, Enter/Tab to select, Escape to dismiss
6. On select:
   a. Remove "#dec" from input text
   b. Create amber badge chip in input area
   c. Track in activeExtensions[] array
7. Multiple extensions can be selected (multiple badges)
```

### Badge Management

When an extension is selected from the autocomplete, a styled amber badge appears in the input area (next to the profile badge):

```
┌─────────────────────────────────────────────────────────────┐
│ [📎] [@OPTIM ×] [#json ×] [#decision ×]  Ask about...     │
│       ▲ purple    ▲ amber    ▲ amber       ▲ text input    │
│       profile     extension  extension                      │
└─────────────────────────────────────────────────────────────┘
```

**State:**
- `activeExtensions[]` — array of `{name, param}` objects
- `window.activeExtensions` — global reference for cross-module access
- `window.clearExtensionBadges()` — clears all badges (called after submit)

**Backspace behavior (empty input):**
1. Remove last extension badge first
2. If no extension badges remain, remove profile badge

### Query Submission

On submit, extensions are collected from two sources and merged:

```javascript
// Source 1: Manual #tags in message text
"What is CPU usage? #json:full"  →  [{name: "json", param: "full"}]

// Source 2: Badge-based (from autocomplete selection)
window.activeExtensions          →  [{name: "decision", param: null}]

// Merged (deduplicated by name):
extensions: [{name: "json", param: "full"}, {name: "decision", param: null}]
```

The `#tags` are stripped from the message before sending to the LLM. Extensions are sent as a separate `extensions` array in the request body.

### SSE Event Rendering

| Event | UI Action |
|-------|-----------|
| `extension_start` | Live Status: "Running extension #json:minimal" |
| `extension_complete` | Live Status: "✓ Extension #json — Completed" |
| `extension_results` | Per-extension based on `output_target` |

**Output target rendering:**

| Target | Rendering |
|--------|-----------|
| `chat_append` | Appended as amber-bordered block below assistant message, with `data-ext-name` attribute |
| `status_panel` | Rendered in Live Status window |
| `silent` | No automatic rendering — accessible via tag click |

### Extension Tags on Chat Messages

User messages display amber clickable tags for each extension:

```
┌──────────────────────────────────────────────┐
│ You  [Rest Call] [#json:minimal] [#decision] │
│ What is the CPU usage?                       │
└──────────────────────────────────────────────┘
```

**Tag persistence:** `extension_specs` is stored on the user message object in `session_history`. On session reload, tags are re-rendered from persisted data.

**Click behavior:**

| Extension Target | Click Action |
|-----------------|--------------|
| `chat_append` | Scrolls to and flash-highlights the output block in the assistant message |
| `silent` / `status_panel` | Fetches turn details via API, shows result in inline popover below the tag |

**Popover toggle:** Clicking the same tag again removes the popover.

### Historical Turn Recall

When clicking a turn avatar to reload execution details, extension events are replayed:

1. Extension lifecycle events (`extension_start`, `extension_complete`) render in Live Status
2. Extension results display based on their `output_target`
3. `chat_append` results re-render below the chat message

### REST API Notification Path

When a REST API query completes, the `rest_task_complete` notification includes `extension_specs`:

```javascript
// Backend sends:
{type: "rest_task_complete", payload: {user_input, final_answer, profile_tag, extension_specs}}

// Frontend renders with tags:
UI.addMessage('user', user_input, turn_id, true, 'rest', profile_tag, false, extension_specs);
```

---

## Extensions Configuration Tab

The Extensions tab in the setup panel (`extensionHandler.js`) provides:

### Available Extensions

Cards for each extension in the registry:

```
┌──────────────────────────────────────────────────────────┐
│ [#json]  JSON Output  [Transform]  [2 activated]         │
│ Wraps the LLM answer into a standardized JSON structure  │
│                                          [+ Activate]    │
└──────────────────────────────────────────────────────────┘
```

### User Activations

Cards for each of the user's activated instances:

```
┌──────────────────────────────────────────────────────────┐
│ [#json]  (json)                    [View Script]  [✕]   │
│ Default param: [minimal      ] [Save]                    │
│                                                          │
│ Output: chat_append  •  v1.0.0  •  built-in             │
└──────────────────────────────────────────────────────────┘
```

Features:
- **View Script** — Opens modal with Python source code
- **Delete** — Removes activation
- **Default param** — Editable text field with Save button
- **Reload** — Hot-reload extensions from disk (admin button)

---

## CSS Design System

All extension UI elements use a consistent **amber/yellow accent** (`#fbbf24`):

| Element | Class | Colors |
|---------|-------|--------|
| Chat message tag | `.extension-tag` | `rgba(251, 191, 36, 0.2)` bg, `#fbbf24` text |
| Input badge | `.active-extension-badge` | Same amber palette, with × remove button |
| Autocomplete item | `.extension-item` | 4px amber left border on highlight |
| Result popover | `.ext-result-popover` | Dark bg, amber border |
| Flash highlight | `.ext-highlight` | `ext-flash` keyframe animation (1.5s) |

All use `font-family: 'JetBrains Mono', monospace` for extension names.

---

## Serial Chaining

Extensions execute in the order specified. Each extension sees results from all prior extensions:

```
Query: "Check health #json #decision:critical"

1. #json executes
   context.previous_extension_results = {}
   → Returns: {query, answer, tokens, ...}

2. #decision executes
   context.previous_extension_results = {"json": {content: {...}, success: true}}
   → Can use json output to make decisions
   → Returns: {result, severity, branch_key, ...}
```

This enables composition patterns where later extensions build on earlier results.

---

## Cost Tracking Integration

Extensions can optionally report token usage for the KPI pipeline:

```python
return ExtensionResult(
    extension_name="schema",
    content=transformed_output,
    extension_input_tokens=1500,     # LLM tokens consumed
    extension_output_tokens=800,
    extension_cost_usd=0.003
)
```

When non-zero:
1. `_persist_extension_results()` aggregates costs across all extensions
2. Calls `session_manager.update_token_count()` to update session totals
3. Emits `token_update` SSE event with `call_id: "extensions"`
4. Updates persisted turn data with adjusted token counts

Built-in extensions are all deterministic (0 tokens). Cost tracking is designed for future LLM-calling extensions (e.g., `#schema` for custom JSON schema enforcement).

---

## Creating Custom Extensions

### 1. Create Extension Directory

```
extensions/builtin/my_extension/
├── manifest.json
└── my_extension.py
```

### 2. Write manifest.json

```json
{
  "name": "my-extension",
  "version": "1.0.0",
  "extension_id": "myext",
  "display_name": "My Extension",
  "description": "Does something useful",
  "author": "Your Name",
  "category": "Transform",
  "files": {"extension": "my_extension.py"},
  "output_target": "silent",
  "parameters": {
    "supported": true,
    "description": "Control behavior",
    "examples": ["mode1", "mode2"]
  }
}
```

### 3. Implement Extension

```python
from trusted_data_agent.extensions.base import Extension
from trusted_data_agent.extensions.models import ExtensionContext, ExtensionResult, OutputTarget

class MyExtension(Extension):
    @property
    def name(self) -> str:
        return "myext"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT

    def validate_param(self, param=None):
        if param and param not in ("mode1", "mode2"):
            return False, f"Invalid param '{param}'"
        return True, None

    async def execute(self, context: ExtensionContext, param=None) -> ExtensionResult:
        output = {
            "query": context.clean_query,
            "result": "processed",
        }
        return ExtensionResult(
            extension_name="myext",
            content=output,
            content_type="application/json",
            metadata={"param": param},
        )
```

### 4. Register in Registry

Add to `extensions/extension_registry.json`:

```json
{
  "extension_id": "myext",
  "plugin_directory": "my_extension",
  "status": "active",
  "display_order": 5,
  "category": "Transform",
  "is_builtin": true
}
```

### 5. Reload

Either restart the application or call `POST /v1/extensions/reload` (admin).

### User-Provided Extensions

Place in `~/.tda/extensions/` with the same directory structure. User extensions override built-in extensions with the same `extension_id`.

---

## Verification & Testing

### REST API Test

```bash
# Authenticate
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

# Create session
SESSION_ID=$(curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" -d '{}' | jq -r '.session_id')

# Submit query with extensions
TASK_ID=$(curl -s -X POST "http://localhost:5050/api/v1/sessions/$SESSION_ID/query" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is the system status?",
    "extensions": [
      {"name": "json", "param": "minimal"},
      {"name": "decision", "param": "critical"}
    ]
  }' | jq -r '.task_id')

# Poll for results
sleep 10
curl -s "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT" | jq '.extension_results'
```

### Verification Checklist

| Test | Expected |
|------|----------|
| Submit with `#json` | Extension result in task response + chat_append block in UI |
| Submit with `#decision` | Extension result in task response, `output_target: silent` |
| Serial chain `#json #decision` | Decision sees json in `previous_extension_results` |
| Invalid extension name | Main answer delivered, error in extension_results |
| Session reload | Extension tags visible on user messages |
| Tag click (chat_append) | Scrolls to and highlights output block |
| Tag click (silent) | Shows inline popover with result |
| Backspace in input | Removes last extension badge, then profile badge |
| REST notification | Extension tags rendered on live REST messages |

---

## Design Principles

1. **Non-Breaking:** Extensions never break the main answer. Errors are isolated per-extension.
2. **Deterministic First:** Built-in extensions use regex/keyword analysis, not LLM calls. Fast and predictable.
3. **Serial Chaining:** Extensions execute in order; each sees all prior results.
4. **Per-User Activation:** Users control which extensions are available via `#` autocomplete.
5. **Multi-Activation:** Same extension can be activated multiple times with different default params.
6. **Flexible Output:** Extensions declare their display target (silent, chat_append, status_panel).
7. **Persistent:** Extension specs on messages and results on turns are persisted to session files.
8. **Cost-Aware:** LLM-calling extensions can report token usage for the KPI pipeline.
9. **Hot-Reloadable:** Extensions can be reloaded from disk without restart.

---

## File Reference

### Backend

| File | Purpose |
|------|---------|
| `src/trusted_data_agent/extensions/__init__.py` | Public API exports |
| `src/trusted_data_agent/extensions/models.py` | ExtensionContext, ExtensionResult, OutputTarget |
| `src/trusted_data_agent/extensions/base.py` | Abstract Extension base class |
| `src/trusted_data_agent/extensions/manager.py` | Singleton manager (discovery, loading, reload) |
| `src/trusted_data_agent/extensions/runner.py` | Serial execution orchestrator |
| `src/trusted_data_agent/extensions/db.py` | Per-user activation persistence (SQLite) |
| `src/trusted_data_agent/agent/execution_service.py` | `_run_extensions()`, `_persist_extension_results()` |
| `src/trusted_data_agent/api/rest_routes.py` | Extension REST endpoints, task result integration |
| `src/trusted_data_agent/api/routes.py` | SSE streaming path (extension_specs passthrough) |
| `src/trusted_data_agent/core/session_manager.py` | `append_extension_results_to_turn()`, message persistence |
| `src/trusted_data_agent/main.py` | ExtensionManager startup initialization |
| `schema/12_extensions.sql` | Database schema for user_extensions table |

### Frontend

| File | Purpose |
|------|---------|
| `static/js/main.js` | `#` autocomplete, badge management, keyboard handling |
| `static/js/eventHandlers.js` | Extension parsing, SSE events, historical recall |
| `static/js/ui.js` | Extension tags on messages, `_showExtensionResult()` click handler |
| `static/js/notifications.js` | REST notification path (extension_specs in payload) |
| `static/js/handlers/extensionHandler.js` | Extensions configuration tab UI |
| `static/js/handlers/sessionManagement.js` | Session reload with extension_specs |
| `static/css/main.css` | All extension CSS (.extension-tag, .active-extension-badge, etc.) |
| `templates/index.html` | Extensions tab, autocomplete containers, badge container |

### Extensions

| File | Purpose |
|------|---------|
| `extensions/extension_registry.json` | Central registry |
| `extensions/schemas/extension-manifest-schema.json` | Manifest validation schema |
| `extensions/builtin/json/` | #json — Structured JSON output |
| `extensions/builtin/decision/` | #decision — Workflow branching |
| `extensions/builtin/extract/` | #extract — Data extraction |
| `extensions/builtin/classify/` | #classify — Answer classification |
