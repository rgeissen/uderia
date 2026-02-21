# Extension Architecture

> Post-processing pipeline that transforms non-deterministic LLM output into structured, machine-parseable formats for downstream workflow tools (n8n, Flowise, Airflow).

## Overview

Uderia's LLM answers are natural-language text — inherently non-deterministic. Downstream workflow tools need structured, deterministic output to branch on. The Extensions system adds a post-processing pipeline triggered by `#name:param` syntax that transforms LLM output into machine-parseable formats.

Extensions complement the existing `@TAG` input routing with `#Extension` output processing:

```
@PROFILE (how to answer) → Query → LLM Answer → #Extension (structured output) → n8n/Flowise
```

### Design Principle: Progressive Disclosure

Maximum Python flexibility through progressive disclosure. Every friction point has a lower-friction alternative. Citizen users never see a class or import statement. Expert users get full async Python with rich context and LLM access.

| Level | Who | Friction | What they write |
|-------|-----|----------|-----------------|
| **Level 0 (Convention)** | Citizen users | Zero | A plain Python function + module constants |
| **Level 1 (SimpleExtension)** | Power users | Minimal | ~15 lines with class + `transform()` |
| **Level 2 (Extension)** | Developers | Standard | Full context access, async `execute()` |
| **Level 3 (LLMExtension)** | Advanced | Standard | Calls user's LLM with auto cost tracking |

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
│  │     ├─ Aggregate token costs (+ fallback calculation) │────────┘          │
│  │     ├─ Update session token counts (cumulative)       │                   │
│  │     ├─ Emit token_update SSE (call_id: "extensions")  │                   │
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
│  ┌───────────────────────────────────────────────────────────┐              │
│  │  Built-in Extensions                                       │              │
│  │  ┌──────┐ ┌──────────┐ ┌───────┐ ┌─────────┐ ┌─────────┐│              │
│  │  │#json │ │#decision │ │#extract│ │#classify│ │#summary ││              │
│  │  │Tier 2│ │ Tier 3   │ │Tier 1 │ │ Tier 3  │ │ Tier 3  ││              │
│  │  └──────┘ └──────────┘ └───────┘ └─────────┘ └─────────┘│              │
│  └───────────────────────────────────────────────────────────┘              │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────┐              │
│  │  Helpers Library                                           │              │
│  │  text.py │ json_utils.py │ regex.py │ result_builders.py  │              │
│  └───────────────────────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### File Structure

```
src/trusted_data_agent/extensions/
├── __init__.py              # Public API: SimpleExtension, Extension, LLMExtension
├── models.py                # ExtensionContext, ExtensionResult, OutputTarget
├── base.py                  # Three-tier base classes
├── manager.py               # Singleton discovery & loading (4 discovery modes)
├── runner.py                # Serial execution with LLM injection & token extraction
├── db.py                    # Per-user activation persistence (SQLite)
├── scaffolds.py             # Template generators for all 4 levels
└── helpers/                 # Shared utilities for extension authors
    ├── __init__.py          # Re-exports all helpers
    ├── text.py              # count_words, extract_sentences, extract_code_blocks, etc.
    ├── json_utils.py        # extract_json_from_text, safe_json_dumps
    ├── regex.py             # NUMBER_WITH_UNIT, PERCENTAGE, IDENTIFIER, etc.
    └── result_builders.py   # json_result, text_result, error_result

extensions/
├── extension_registry.json  # Central registry of built-in extensions
├── schemas/
│   └── extension-manifest-schema.json
└── builtin/
    ├── json/                # #json — Structured JSON output (Tier 2)
    │   ├── manifest.json
    │   └── json_ext.py
    ├── decision/            # #decision — LLM workflow branching (Tier 3)
    │   ├── manifest.json
    │   └── decision.py
    ├── extract/             # #extract — Regex data extraction (Tier 1)
    │   ├── manifest.json
    │   └── extract.py
    ├── classify/            # #classify — LLM semantic classification (Tier 3)
    │   ├── manifest.json
    │   └── classify.py
    └── summary/             # #summary — LLM executive summary (Tier 3)
        ├── manifest.json
        └── summary.py

~/.tda/extensions/           # User extensions (auto-discovered)
├── myext.py                 # Level 0: Convention-based (flat file)
├── wordcount/               # Level 1: SimpleExtension (no manifest)
│   └── wordcount.py
└── analyzer/                # Level 2-3: With manifest
    ├── manifest.json
    └── analyzer.py

static/js/
├── main.js                  # # autocomplete, badge management
├── eventHandlers.js         # Extension parsing, SSE events, historical recall
├── ui.js                    # Extension tags, _renderExtensionStep(), cost display
├── notifications.js         # REST notification dispatch (extension events)
└── handlers/
    ├── extensionHandler.js  # Extensions configuration tab, tier badges
    └── sessionManagement.js # Session reload with extension_specs
```

---

## Four-Tier Extension Hierarchy

### Input/Output Contract

Every extension transforms the LLM's answer into structured output. The tiers differ in what input you receive and how much the framework handles for you:

| | Level 0 (Convention) | Level 1 (Simple) | Level 2 (Standard) | Level 3 (LLM) |
|---|---|---|---|---|
| **You write** | A `transform()` function | A class with `transform()` | A class with async `execute()` | A class with async `execute()` + `call_llm()` |
| **Input you receive** | `answer_text: str`, `param: str \| None` | `answer_text: str`, `param: str \| None` | `context: ExtensionContext` (full), `param: str \| None` | `context: ExtensionContext` (full), `param: str \| None` |
| **What you return** | `dict` or `str` | `dict` or `str` | `ExtensionResult` | `ExtensionResult` |
| **Framework handles** | Class creation, manifest, result wrapping, error handling | Result wrapping, param validation, error handling | Error handling, SSE events | LLM config injection, token tracking, cost calculation, error handling |
| **Extra capabilities** | — | `allowed_params` set | Full context: tokens, tools, execution trace, session data | `self.call_llm()` with auto cost tracking |
| **Needs manifest?** | No | No | Yes | Yes |
| **Needs registry?** | No | No | No (auto-discovered) | No (auto-discovered) |
| **Can call LLM?** | No | No | No | Yes (automatic) |

**`answer_text`** is the LLM's plain-text response to the user's query, with any `#extension` tags already stripped. This is the primary input for all tiers — it's the text your extension transforms.

**`param`** is the optional parameter from `#name:param` syntax (e.g., `#decision:binary` → `param="binary"`). It's `None` when the user types just `#name`.

**`ExtensionContext`** (Tiers 2-3 only) wraps `answer_text` with rich metadata: session/turn IDs, profile info, provider/model, token counts, execution trace, tools used, and results from prior extensions in the chain. See [Core Data Models](#core-data-models) for the full field list.

**Return values:**
- **Tiers 0-1:** Return a `dict` (auto-serialized as JSON) or `str` (plain text). The framework wraps it into an `ExtensionResult` for you.
- **Tiers 2-3:** Return an `ExtensionResult` directly, giving you control over `content_type`, `output_target`, `metadata`, and error reporting.

---

### Level 0: Convention-Based (Zero Friction)

Drop a `.py` file in `~/.tda/extensions/`. No imports, no classes, no manifest, no registry.

```python
# ~/.tda/extensions/wordcount.py

EXTENSION_NAME = "wordcount"
EXTENSION_DESCRIPTION = "Counts words, sentences, and characters"
# ALLOWED_PARAMS = {"brief", "detailed"}   # Optional: restrict parameters
# OUTPUT_TARGET = "chat_append"            # Optional: default is "silent"

def transform(answer_text, param=None):
    """The only thing you write. Everything else is auto-wired."""
    words = answer_text.split()
    return {
        "word_count": len(words),
        "sentence_count": answer_text.count('.') + answer_text.count('!') + answer_text.count('?'),
        "char_count": len(answer_text),
    }
```

**How it works:** The Extension Manager's `_try_convention_wrap()` imports the file, reads module-level constants (`EXTENSION_NAME`, `EXTENSION_DESCRIPTION`, etc.), and dynamically creates a `SimpleExtension` subclass that delegates to the `transform()` function. An in-memory manifest is generated automatically.

**Required:** `EXTENSION_NAME` + `def transform(answer_text, param=None)`
**Optional:** `EXTENSION_DESCRIPTION`, `ALLOWED_PARAMS`, `CONTENT_TYPE`, `OUTPUT_TARGET`

### Level 1: SimpleExtension (Minimal Class)

For users who want a class but minimal boilerplate. ~15 lines total.

```python
# ~/.tda/extensions/wordcount/wordcount.py

from trusted_data_agent.extensions import SimpleExtension

class WordCountExtension(SimpleExtension):
    name = "wordcount"
    description = "Counts words, sentences, and characters"
    # allowed_params = {"brief", "detailed"}  # Optional

    def transform(self, answer_text, param=None):
        words = answer_text.split()
        return {
            "word_count": len(words),
            "char_count": len(answer_text),
        }
```

**Pre-implemented by SimpleExtension:**
- `execute()` — delegates to `transform()`, wraps result in `ExtensionResult`
- `validate_param()` — validates against `allowed_params` set (if defined)

**No manifest needed.** The Manager's `_try_auto_manifest()` reads class attributes and generates one in memory.

### Level 2: Extension (Full Context)

For developers who need access to the full `ExtensionContext` (tokens, execution trace, tools used, session data).

```python
from trusted_data_agent.extensions import Extension, ExtensionResult, ExtensionContext, OutputTarget

class MyExtension(Extension):
    @property
    def name(self) -> str:
        return "myext"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.CHAT_APPEND

    def validate_param(self, param=None):
        if param and param not in ("mode1", "mode2"):
            return False, f"Invalid param '{param}'"
        return True, None

    async def execute(self, context: ExtensionContext, param=None) -> ExtensionResult:
        output = {
            "query": context.clean_query,
            "tools_used": context.tools_used,
            "tokens": {"input": context.turn_input_tokens, "output": context.turn_output_tokens},
        }
        return ExtensionResult(
            extension_name="myext",
            content=output,
            content_type="application/json",
        )
```

**Requires:** `manifest.json` in the extension directory (or registry entry for builtins).

### Level 3: LLMExtension (Calls the User's LLM)

For extensions that need semantic analysis. Automatic token counting and cost tracking.

```python
from trusted_data_agent.extensions import LLMExtension, ExtensionResult, ExtensionContext
from trusted_data_agent.extensions.helpers import extract_json_from_text

class SentimentExtension(LLMExtension):
    name = "sentiment"
    description = "Analyzes sentiment using the session's LLM"

    async def execute(self, context, param=None):
        raw = await self.call_llm(
            prompt=f"Classify the sentiment:\n\n{context.answer_text}",
            system_prompt="Return JSON: {sentiment, confidence}",
            json_mode=True,
            temperature=0.2,
        )
        parsed = extract_json_from_text(raw) or {"sentiment": "unknown", "confidence": 0}

        return ExtensionResult(
            extension_name=self.name,
            content=parsed,
            content_type="application/json",
        )
```

**`call_llm()` signature:**

```python
async def call_llm(
    self,
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str
```

**Automatic behavior:**
- Uses the session's configured LLM (same provider/model as the main query)
- LLM config injected by `ExtensionRunner` before `execute()` is called
- Token accumulators (`_total_input_tokens`, `_total_output_tokens`, `_total_cost_usd`) reset per execution and accumulate across multiple `call_llm()` invocations
- Cost calculated via `CostManager` with provider-specific pricing
- Raises `RuntimeError` if no LLM configuration is available on the active profile

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

    # LLM config (for LLMExtension, injected by runner)
    user_uuid: Optional[str]            # User UUID for LLM credential resolution
    llm_config_id: Optional[str]        # LLM configuration ID from active profile
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

## Helpers Library

Shared utilities that extension authors import. Eliminates copy-paste between extensions.

```python
from trusted_data_agent.extensions.helpers import (
    extract_json_from_text, safe_json_dumps,       # JSON
    count_words, extract_sentences, truncate,       # Text
    extract_code_blocks, extract_tables,            # Text
    json_result, text_result, error_result,         # Result builders
)
from trusted_data_agent.extensions.helpers.regex import (
    NUMBER_WITH_UNIT, PERCENTAGE, IDENTIFIER,       # Regex patterns
    SQL_STATEMENT, KEY_VALUE, EMAIL, URL,
    ENTITY_STOPWORDS,
)
```

### JSON Utilities (`helpers/json_utils.py`)

| Function | Purpose | Returns |
|----------|---------|---------|
| `extract_json_from_text(text)` | Find and parse first JSON object/array in text. Handles markdown fences, bare JSON, nested brackets. | `dict`, `list`, or `None` |
| `safe_json_dumps(obj, indent=2)` | `json.dumps` with `default=str`, `ensure_ascii=False`. Handles datetime, UUID, Decimal. | `str` |

### Text Utilities (`helpers/text.py`)

| Function | Purpose | Returns |
|----------|---------|---------|
| `count_words(text)` | Count whitespace-separated words | `int` |
| `extract_sentences(text)` | Split on sentence boundaries (`.`, `!`, `?`) | `list[str]` |
| `extract_code_blocks(text)` | Extract markdown fenced code blocks | `list[{"language", "code"}]` |
| `extract_tables(text)` | Extract markdown tables | `list[list[list[str]]]` |
| `truncate(text, max_chars=1000)` | Truncate at word boundary with ellipsis | `str` |

### Regex Patterns (`helpers/regex.py`)

Pre-compiled patterns for structured data extraction:

| Pattern | Matches | Example |
|---------|---------|---------|
| `NUMBER_WITH_UNIT` | Labeled numbers | `"CPU Usage: 94.5%"`, `"Total: 1,234 rows"` |
| `PERCENTAGE` | Percentage values | `"94.5%"`, `"0.01%"` |
| `IDENTIFIER` | UPPER_CASE identifiers (3+ chars) | `"DATABASE_NAME"`, `"PROD_SERVER"` |
| `SQL_STATEMENT` | SQL queries | Multi-line SELECT/INSERT/UPDATE |
| `KEY_VALUE` | Key-value pairs | `"key: value"`, `"key = value"` |
| `EMAIL` | Email addresses | Standard email pattern |
| `URL` | HTTP(S) URLs | `"https://example.com"` |
| `ENTITY_STOPWORDS` | Set of common non-entity words to filter | `"THE"`, `"SQL"`, `"API"`, `"LLM"` |

### Result Builders (`helpers/result_builders.py`)

Convenience constructors for `ExtensionResult`:

```python
json_result(name, content, **metadata)   # → ExtensionResult(content_type="application/json")
text_result(name, content, **metadata)   # → ExtensionResult(content_type="text/plain")
error_result(name, error_msg)            # → ExtensionResult(success=False)
```

---

## Extension Manager (Singleton)

Discovers, loads, and manages extensions with four discovery modes.

```python
manager = get_extension_manager()      # Singleton accessor

manager.list_extensions()              # All extensions with metadata (for UI/autocomplete)
manager.get_extension("json")          # Get loaded extension by name
manager.get_all_names()                # ["json", "decision", "extract", "classify", "summary"]
manager.get_extension_source("json")   # Python source code (for "View Script")
manager.get_manifest("json")           # Full manifest dict
manager.reload()                       # Hot-reload from disk
```

### Four Discovery Modes

Discovery runs in order; later modes override earlier for the same extension ID. User directories always override builtins.

**Mode A — Flat convention file (Level 0, zero friction):**
```
~/.tda/extensions/wordcount.py     ← just a file, not a directory
```
Manager calls `_try_convention_wrap()`: imports the module, reads `EXTENSION_NAME` + `transform()`, creates a `SimpleExtension` wrapper, generates in-memory manifest.

**Mode B — Directory without manifest (Level 1, manifest-free):**
```
~/.tda/extensions/wordcount/
    wordcount.py                   ← SimpleExtension subclass, no manifest
```
Manager calls `_try_auto_manifest()`: imports the `.py`, finds any `Extension`/`SimpleExtension`/`LLMExtension` subclass, instantiates it, reads class attributes (`name`, `description`, `allowed_params`), generates in-memory manifest. Tier auto-detected from class hierarchy.

**Mode C — Directory with manifest (Level 1-3):**
```
~/.tda/extensions/myext/
    manifest.json                  ← auto-discovered, no registry needed
    myext.py
```
Standard manifest-based loading. No registry entry required for user extensions.

**Mode D — Registry (builtins):**
```
extensions/builtin/json/           ← registered in extension_registry.json
    manifest.json
    json_ext.py
```
Registry provides display order, category, and status. Used for all built-in extensions.

### Override Semantics

User extensions with the same `extension_id` as a builtin override the builtin. Discovery priority within user dir: Mode A → Mode B → Mode C (first match wins per ID). User dir always overrides builtin dir.

---

## Extension Runner (Serial Execution)

Orchestrates serial execution of extensions with result chaining and LLM config injection:

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

### Execution Flow Per Extension

```
1. Lookup extension by extension_id in manager
2. Validate parameter via ext.validate_param(param)
3. Inject chain context: context.previous_extension_results = {prior results}
4. Emit extension_start SSE event
5. [LLMExtension only] Inject LLM config from context:
   - ext._user_uuid, ext._llm_config_id, ext._provider, ext._model
   - Reset token accumulators to 0
6. Execute: result = await ext.execute(context, param)
7. Record execution_time_ms in metadata
8. [LLMExtension only] Extract accumulated tokens:
   - result.extension_input_tokens = ext._total_input_tokens
   - result.extension_output_tokens = ext._total_output_tokens
   - result.extension_cost_usd = ext._total_cost_usd
9. Emit extension_complete SSE event (includes tokens/cost if non-zero)
10. Store result keyed by activation_name
```

**Error handling:** Exceptions are caught per-extension and recorded as `ExtensionResult(success=False, error=str(e))`. Extensions never break the main answer.

### SSE Event Schema

```json
// extension_start
{"type": "extension_start", "payload": {"name": "decision", "param": "binary"}}

// extension_complete (deterministic extension)
{"type": "extension_complete", "payload": {
  "name": "extract", "success": true, "content_type": "application/json",
  "output_target": "silent", "execution_time_ms": 12
}}

// extension_complete (LLM extension — includes token/cost data)
{"type": "extension_complete", "payload": {
  "name": "decision", "success": true, "content_type": "application/json",
  "output_target": "silent", "execution_time_ms": 1155,
  "input_tokens": 621, "output_tokens": 68, "cost_usd": 0.000089
}}

// extension_results (combined, after all extensions)
{"type": "extension_results", "payload": {
  "decision": {"content": {...}, "success": true, "output_target": "silent", ...},
  "extract": {"content": {...}, "success": true, ...}
}}
```

---

## Cost Tracking Integration

LLM extensions automatically track token usage through the full KPI pipeline.

### Token Flow

```
LLMExtension.call_llm()
    │ Extracts usage_metadata from LLM response
    │ Accumulates _total_input_tokens, _total_output_tokens
    │ Calculates cost via CostManager (with warning on failure)
    ▼
ExtensionRunner.run()
    │ Copies accumulated tokens to ExtensionResult
    │ Emits extension_complete SSE with token/cost data
    ▼
execution_service._persist_extension_results()
    │ Aggregates costs across all extensions in the chain
    │ Cost fallback: recalculates via CostManager if extension cost was 0
    │ Backfills cost into ext_results and ext_events (for session persistence)
    │ Reads prior turn tokens from workflow_history (cumulative)
    │ Calls session_manager.update_token_count() with cumulative totals
    │ Emits token_update SSE event with call_id: "extensions"
    ▼
Frontend KPI Counters
    │ LAST STMT: extension tokens only (621 in / 68 out)
    │ LAST TURN: cumulative main + extension (3264 in / 552 out)
    │ SESSION TOTAL: running session total
    │ TURN COST / SESSION COST: accumulated cost
    ▼
Session Persistence
    │ append_extension_results_to_turn() patches workflow_history
    │ extension_results + extension_events stored per-turn
```

### Cost Fallback Mechanism

When `LLMExtension.call_llm()` successfully extracts tokens but cost calculation fails silently:

1. **Primary:** `call_llm()` calls `CostManager.calculate_cost()` — logs warning on failure
2. **Fallback:** `_persist_extension_results()` detects `total_ext_cost == 0` with non-zero tokens, recalculates using the session's `provider`/`model`
3. **Backfill:** Computed cost is written back into both `ext_results` (session file) and `ext_events` (reload renderer)

This ensures cost data is available even when the LLM provider's cost lookup fails during extension execution.

### token_update Event (Extensions)

```json
{
  "call_id": "extensions",
  "cost_usd": 0.000089,
  "statement_input": 621,
  "statement_output": 68,
  "total_input": 3264,
  "total_output": 552,
  "turn_input": 3264,
  "turn_output": 552
}
```

`turn_input`/`turn_output` are **cumulative** (main execution + extensions), not extension-only. This ensures the LAST TURN KPI counter shows the complete turn total.

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

Query-time `#name:param` overrides the activation's `default_param`:
```
#json:minimal  → param="minimal" (overrides default)
#json          → param=default_param from activation (or null)
```

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/extensions` | GET | List all available extensions (registry + auto-discovered) |
| `/v1/extensions/activated` | GET | List user's activated extensions |
| `/v1/extensions/<ext_id>/activate` | POST | Activate a new instance |
| `/v1/extensions/activations/<name>/deactivate` | POST | Soft-delete activation |
| `/v1/extensions/activations/<name>/config` | PUT | Update default_param/config |
| `/v1/extensions/activations/<name>/rename` | PUT | Rename activation |
| `/v1/extensions/activations/<name>` | DELETE | Hard-delete activation |
| `/v1/extensions/<name>/source` | GET | Get Python source code |
| `/v1/extensions/<name>/source` | PUT | Save edited source code (user extensions only) |
| `/v1/extensions/reload` | POST | Hot-reload from disk (admin) |
| `/v1/extensions/scaffold` | POST | Generate extension skeleton and write to disk |
| `/v1/extensions/scaffold/preview` | POST | Preview scaffold output without writing |

---

## Scaffolding & Editor API

### Scaffold — Create Extension Skeleton

**Endpoint:** `POST /v1/extensions/scaffold`

```json
{
  "name": "myext",
  "level": "convention",
  "description": "Does something useful"
}
```

| Level | What gets created | User action after |
|-------|-------------------|-------------------|
| `convention` | `~/.tda/extensions/myext.py` (flat file) | Edit the `transform()` function |
| `simple` | `~/.tda/extensions/myext/myext.py` | Edit the `transform()` method |
| `standard` | `~/.tda/extensions/myext/myext.py` + `manifest.json` | Edit `execute()` method |
| `llm` | `~/.tda/extensions/myext/myext.py` + `manifest.json` | Edit `execute()` + LLM prompts |

**Response:**
```json
{
  "status": "success",
  "path": "~/.tda/extensions/myext.py",
  "files": ["myext.py"],
  "level": "convention",
  "loaded": true
}
```

Auto-reloads extension manager after writing — no separate reload call needed.

### Preview — Generate Without Writing

**Endpoint:** `POST /v1/extensions/scaffold/preview`

Same request body as scaffold. Returns generated file contents **without writing to disk**. Useful for previewing code before committing.

**Response:**
```json
{
  "status": "success",
  "path": "~/.tda/extensions/myext.py",
  "files": { "myext.py": "# Generated source code..." },
  "level": "convention"
}
```

### Save Source — Edit Extension Code

**Endpoint:** `PUT /v1/extensions/<name>/source`

Saves edited Python source code for a user extension. Security-restricted to extensions under `~/.tda/extensions/` — built-in extensions cannot be modified.

```json
{
  "source": "# Updated extension code...\ndef transform(answer_text, param=None):\n    ..."
}
```

**Response:**
```json
{
  "status": "success",
  "name": "myext",
  "loaded": true
}
```

Auto-reloads extension manager after saving. `loaded: false` indicates a syntax or import error in the saved code.

---

## Extension Editor UI

The frontend provides a two-phase guided editor for creating and editing extensions.

### Phase 1: Configure (Create Extension Modal)

- **Name input**: Live regex validation (`[a-z][a-z0-9_]*`), uniqueness check, character counter
- **Tier selector**: 4-button grid (Convention / Simple / Standard / LLM) with tier-specific accent colors
- **Tier info panel**: Dynamically updates when tier selection changes, showing:
  - Three-column contract summary: **You Receive** | **You Return** | **Framework Handles**
  - File structure preview with actual extension name
  - Manifest required / LLM access indicators
- **"Create & Open Editor"** button: Scaffolds files, then opens the code editor

### Phase 2: Code Editor (Near-Fullscreen)

Near-fullscreen overlay with three areas:

**Left sidebar (220px)** — Requirements Checklist:
- Progress bar with completion percentage
- Tier-specific requirements validated in real-time (300ms debounce) via regex patterns against code
- Contract summary: input types, output types, LLM availability, manifest status

**Main area** — Code Editor:
- `<textarea>` with Prism.js syntax highlighting (Python + JSON grammars)
- Line numbers gutter with scroll sync
- Tab key inserts 4 spaces
- Ctrl/Cmd+S keyboard shortcut to save

**Header + Footer**:
- Extension name badge, tier badge, file path, read-only/new indicators
- Save button (enabled only when changes detected)
- "Unsaved changes" indicator, line count, requirements summary

### Editing Existing Extensions

Clicking "Script" on any activation card opens the same editor:
- **User extensions** (`~/.tda/extensions/`): Opens read-write with Save enabled
- **Built-in extensions** (`extensions/builtin/`): Opens read-only

### Tier-Specific Requirements (Validated in Editor)

| Tier | Requirements |
|------|-------------|
| Convention | `EXTENSION_NAME` defined, `transform()` function |
| Simple | Extension class extending `SimpleExtension`, `name` attribute, `transform()` method |
| Standard | Extension class extending `Extension`, `name` property/attribute, `async execute()`, returns `ExtensionResult` |
| LLM | Extension class extending `LLMExtension`, `name` attribute, `async execute()`, uses `self.call_llm()`, returns `ExtensionResult` |

Requirements are informational (green/gray checklist) — they do not block saving. The scaffold generates valid boilerplate that meets all requirements by default.

**Implementation:** `static/js/handlers/extensionHandler.js` — `TIER_INFO`, `showScaffoldModal()`, `showExtensionEditor()`

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
2. **Build context:** Create `ExtensionContext` from `final_result_payload`, inject `user_uuid`, `llm_config_id`
3. **Wrap event handler:** `collecting_event_handler` forwards events to frontend AND captures lifecycle events for persistence
4. **Execute:** `runner.run(resolved_specs, context, collecting_handler)`
5. **Emit combined results:** Single `extension_results` SSE event
6. **Return:** `(serialized_results, collected_events)` tuple

### `_persist_extension_results()`

1. **Aggregate costs:** Sum `extension_input_tokens` / `extension_output_tokens` across all results
2. **Cost fallback:** If total cost is 0 but tokens exist, recalculate via CostManager using provider/model from the turn's workflow_history
3. **Read prior turn tokens:** From `session.last_turn_data.workflow_history[-1]` (reliable across all profile types)
4. **Update session tokens:** Emit `token_update` SSE event with cumulative `turn_input` = prior + extension tokens
5. **Persist to session:** Call `session_manager.append_extension_results_to_turn()` — patches the already-saved turn

---

## Built-in Extensions

### #json — Structured JSON Output (Tier 2: Extension)

| Property | Value |
|----------|-------|
| Tier | Standard (Extension) — needs full ExtensionContext |
| Output Target | `chat_append` (visible in chat) |
| LLM Calls | None (deterministic) |
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
  "profile_type": "tool_enabled",
  "provider": "anthropic",
  "model": "claude-3-opus",
  "tokens": {"input": 3250, "output": 187, "total_input": 5430, "total_output": 512},
  "tools_used": ["base_readQuery", "TDA_FinalReport"],
  "timestamp": "2026-02-20T15:30:45+00:00"
}
```

### #decision — Workflow Branching (Tier 3: LLMExtension)

| Property | Value |
|----------|-------|
| Tier | LLM (LLMExtension) — calls session's configured LLM |
| Output Target | `silent` (API-only) |
| LLM Calls | 1 per execution |
| Parameters | `binary`, or severity focus (e.g., `critical`) |

LLM-powered semantic analysis to produce branching output for n8n/Flowise Switch nodes.

**Standard mode** (`#decision` or `#decision:critical`):
```json
{
  "result": "threshold_exceeded",
  "severity": "critical",
  "confidence": 0.92,
  "action_recommended": true,
  "branch_key": "threshold_exceeded_critical",
  "reasoning": "CPU usage at 94% exceeds the critical threshold of 90%",
  "query": "What is the CPU usage?"
}
```

| Field | Values |
|-------|--------|
| `result` | `threshold_exceeded`, `approaching_threshold`, `action_required`, `nominal` |
| `severity` | `critical`, `warning`, `info`, `ok` |
| `branch_key` | `{result}_{severity}` (e.g., `"threshold_exceeded_critical"`) |

**Binary mode** (`#decision:binary`):
```json
{
  "result": "yes",
  "action_recommended": true,
  "branch_key": "yes",
  "reasoning": "The answer confirms shoes are relevant for fitness"
}
```

**n8n integration:** Branch on `branch_key` or `severity` in Switch node.

### #extract — Structured Data Extraction (Tier 1: SimpleExtension)

| Property | Value |
|----------|-------|
| Tier | Simple (SimpleExtension) — deterministic regex extraction |
| Output Target | `silent` (API-only) |
| LLM Calls | None (deterministic, 0 tokens) |
| Parameters | `numbers`, `percentages`, `entities` |

Regex-based extraction of structured data from LLM answers using patterns from `helpers/regex.py`:

**Example output (full — no param):**
```json
{
  "numbers": [
    {"label": "CPU", "value": 94.0, "unit": "%"},
    {"label": "Memory", "value": 87.5, "unit": "GB"}
  ],
  "percentages": [94.0, 87.5],
  "entities": ["DW_PROD", "DW_DEV"],
  "source_length": 2847
}
```

With param, returns only the specified type: `#extract:numbers` → `{"numbers": [...]}`.

### #classify — Answer Classification (Tier 3: LLMExtension)

| Property | Value |
|----------|-------|
| Tier | LLM (LLMExtension) — calls session's configured LLM |
| Output Target | `silent` (API-only) |
| LLM Calls | 1 per execution |
| Parameters | None |

LLM-powered semantic classification into predefined categories:

| Category | Use Case |
|----------|----------|
| `alert` | Critical issues, failures, outages, errors |
| `performance` | CPU, memory, throughput, latency metrics |
| `data_quality` | Missing data, nulls, duplicates, validation |
| `capacity` | Storage, growth, forecasting, quotas |
| `security` | Access control, permissions, audit |
| `data_report` | Query results, tables, records, summaries |
| `informational` | General information (fallback) |

**Example output:**
```json
{
  "primary_category": "performance",
  "confidence": 0.87,
  "all_categories": {"performance": 8, "alert": 3, "data_report": 2},
  "branch_key": "performance",
  "query": "What is the CPU usage?",
  "reasoning": "The answer discusses CPU utilization metrics and performance thresholds"
}
```

### #summary — Executive Summary (Tier 3: LLMExtension)

| Property | Value |
|----------|-------|
| Tier | LLM (LLMExtension) — calls session's configured LLM |
| Output Target | `chat_append` (visible in chat) |
| LLM Calls | 1 per execution |
| Parameters | `brief` (default), `detailed` |

LLM-powered executive summary of the LLM answer.

**Brief mode** (`#summary` or `#summary:brief`):
```json
{
  "summary": "System health is nominal with CPU at 45% and memory at 62%...",
  "key_points": [
    "CPU usage is within normal range at 45%",
    "Memory utilization stable at 62%",
    "No active alerts or warnings"
  ],
  "action_items": []
}
```

**Detailed mode** (`#summary:detailed`):
```json
{
  "summary": "Comprehensive system analysis reveals...",
  "key_points": ["...", "...", "...", "...", "..."],
  "sections": {
    "System Health": "All metrics within normal thresholds.",
    "Performance": "CPU and memory stable, no bottlenecks detected."
  },
  "action_items": ["Schedule capacity review for Q3"],
  "data_highlights": ["CPU: 45%", "Memory: 62%", "Disk: 78%"]
}
```

---

## Serial Chaining

Extensions execute in the order specified. Each extension sees results from all prior extensions:

```
Query: "Check health #extract #decision:critical"

1. #extract executes
   context.previous_extension_results = {}
   → Returns: {numbers: [...], percentages: [...], entities: [...]}

2. #decision executes (LLM call)
   context.previous_extension_results = {"extract": {content: {...}, success: true}}
   → LLM can use extracted data to inform decision
   → Returns: {result, severity, branch_key, ...}
```

This enables composition patterns where later extensions build on earlier results.

---

## Extension Manifest Schema

Each extension directory may contain a `manifest.json`. Validated against `extensions/schemas/extension-manifest-schema.json`.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Kebab-case identifier (`^[a-z][a-z0-9-]*$`) |
| `version` | string | SemVer (`^\d+\.\d+\.\d+$`) |
| `extension_id` | string | Lowercase trigger name (`^[a-z][a-z0-9_]*$`) |
| `display_name` | string | Human-readable name |
| `description` | string | Short description |
| `files.extension` | string | Python file path |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `extension_tier` | string | `"standard"` | `convention`, `simple`, `standard`, `llm` |
| `requires_llm` | boolean | `false` | Enables UI cost warnings |
| `category` | string | `"General"` | Transform, Automation, Analysis, Export, Visualization, Custom |
| `output_target` | string | `"silent"` | `silent`, `chat_append`, `status_panel` |
| `parameters.supported` | boolean | — | Whether extension accepts parameters |
| `parameters.allowed_values` | array | — | Restrict to specific values |
| `parameters.examples` | array | — | Suggested values (freeform accepted) |
| `output_schema` | object | — | JSON Schema for output validation |
| `compatibility.min_app_version` | string | — | Minimum app version |
| `dependencies.python_packages` | array | — | Required pip packages |

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

```
┌─────────────────────────────────────────────────────────────┐
│ [📎] [@OPTIM ×] [#json ×] [#decision ×]  Ask about...     │
│       ▲ purple    ▲ amber    ▲ amber       ▲ text input    │
│       profile     extension  extension                      │
└─────────────────────────────────────────────────────────────┘
```

### Inline Parameter Editing

After selecting an extension, typing `:` opens a parameter picker:

| Manifest Field | Behavior |
|---------------|----------|
| `supported: false` | Shows "does not accept parameters" hint |
| `allowed_values: [...]` | **Strict mode** — dropdown with amber "Required" badge |
| `examples: [...]` | **Suggested mode** — dropdown with gray "Suggested" badge |
| `supported: true`, no hints | Freeform input accepted |

### SSE Event Rendering

Events are rendered in the Live Status window using the amber-accented `_renderExtensionStep()` renderer in `ui.js`:

| Event | Live Rendering |
|-------|----------------|
| `extension_start` | "Running extension #decision:binary" with processing indicator |
| `extension_complete` | "Extension #decision" with tokens, cost, and timing metrics |
| `extension_results` | Per-extension based on `output_target` |

**Metrics display on extension_complete (LLM extensions):**
```
✓ #decision — 621 in / 68 out · $0.000089 · 1155ms
```

**Reload rendering:** Historical extension events use `_renderExtensionEventsForReload()` in `eventHandlers.js`, which shows the same token/cost/time metrics.

### REST API Notification Path

When queries are submitted via REST API, extension events flow through the notification channel:

```
ExtensionRunner → execution_service → rest_routes.py event_handler
    → notification_queues → /api/notifications/subscribe SSE
    → notifications.js _dispatchRestEvent() → UI.updateStatusWindow('extension')
```

The `_dispatchRestEvent()` function in `notifications.js` handles all three extension event types (`extension_start`, `extension_complete`, `extension_results`) and routes them to the same amber-accented renderer used by the direct SSE stream.

### Extension Tags on Chat Messages

User messages display amber clickable tags:

```
┌──────────────────────────────────────────────┐
│ You  [Rest Call] [#json:minimal] [#decision] │
│ What is the CPU usage?                       │
└──────────────────────────────────────────────┘
```

**Click behavior:**

| Extension Target | Click Action |
|-----------------|--------------|
| `chat_append` | Scrolls to and flash-highlights the output block |
| `silent` / `status_panel` | Shows result in inline popover below the tag |

### Extensions Configuration Tab

The Extensions tab (`extensionHandler.js`) shows:

**Available extensions** with tier badges:
```
┌──────────────────────────────────────────────────────────────┐
│ [#decision]  Workflow Branching  [Automation] [Tier: LLM]    │
│ LLM-powered binary/multi-branch decision output              │
│ ⚠ This extension makes LLM calls and consumes tokens         │
│                                          [+ Activate]        │
└──────────────────────────────────────────────────────────────┘
```

**User activations** with configuration:
```
┌──────────────────────────────────────────────────────────────┐
│ [#json]  (json)                    [View Script]  [✕]       │
│ Default param: [minimal      ] [Save]                        │
│ Output: chat_append  •  v1.0.0  •  Tier: Standard            │
└──────────────────────────────────────────────────────────────┘
```

---

## Session Persistence

### User Message

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

### Turn Data (workflow_history)

```json
{
  "turn": 1,
  "user_query": "What is the CPU usage?",
  "extension_results": {
    "json": {
      "content": {"query": "...", "answer": "..."},
      "content_type": "application/json",
      "success": true,
      "output_target": "chat_append",
      "extension_input_tokens": 0,
      "extension_output_tokens": 0,
      "extension_cost_usd": 0.0
    },
    "decision": {
      "content": {"result": "threshold_exceeded", "severity": "critical", ...},
      "content_type": "application/json",
      "success": true,
      "output_target": "silent",
      "extension_input_tokens": 621,
      "extension_output_tokens": 68,
      "extension_cost_usd": 0.000089
    }
  },
  "extension_events": [
    {"type": "extension_start", "payload": {"name": "json", "param": "minimal"}},
    {"type": "extension_complete", "payload": {"name": "json", "success": true, "execution_time_ms": 5}},
    {"type": "extension_start", "payload": {"name": "decision", "param": "critical"}},
    {"type": "extension_complete", "payload": {"name": "decision", "success": true, "input_tokens": 621, "output_tokens": 68, "cost_usd": 0.000089, "execution_time_ms": 1155}},
    {"type": "extension_results", "payload": {...}}
  ]
}
```

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
| Live Status step | `_renderExtensionStep()` | Amber `#fbbf24` accent, compact layout |

All use `font-family: 'JetBrains Mono', monospace` for extension names.

---

## Creating Custom Extensions

### Quickest Path (Level 0 — Convention)

1. Create `~/.tda/extensions/myext.py` with `EXTENSION_NAME` + `transform()`
2. Call `POST /v1/extensions/reload`
3. Activate via Extensions tab in Setup

Or use the scaffold API:
```bash
curl -X POST "http://localhost:5050/api/v1/extensions/scaffold" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "myext", "level": "convention", "description": "My extension"}'
```

### Level 1 — SimpleExtension (No Manifest)

1. Create directory `~/.tda/extensions/myext/`
2. Create `myext.py` with a `SimpleExtension` subclass
3. Reload + activate

### Level 2-3 — With Manifest

1. Create directory `~/.tda/extensions/myext/`
2. Create `manifest.json` + `myext.py`
3. Reload + activate

### Using Helpers

```python
from trusted_data_agent.extensions import SimpleExtension
from trusted_data_agent.extensions.helpers import (
    extract_json_from_text,
    count_words,
    extract_sentences,
    json_result,
)

class MyExtension(SimpleExtension):
    name = "myext"

    def transform(self, answer_text, param=None):
        return {
            "words": count_words(answer_text),
            "sentences": len(extract_sentences(answer_text)),
        }
```

---

## Design Principles

1. **Non-Breaking:** Extensions never break the main answer. Errors are isolated per-extension.
2. **Progressive Disclosure:** Four tiers from zero-friction (drop a file) to full-power (LLM calls).
3. **Deterministic + Semantic:** Simple extensions use regex/text analysis; LLM extensions provide real semantic understanding.
4. **Serial Chaining:** Extensions execute in order; each sees all prior results.
5. **Per-User Activation:** Users control which extensions are available via `#` autocomplete.
6. **Multi-Activation:** Same extension can be activated multiple times with different default params.
7. **Flexible Output:** Extensions declare their display target (silent, chat_append, status_panel).
8. **Persistent:** Extension specs on messages and results on turns are persisted to session files.
9. **Cost-Aware:** LLM extensions automatically track tokens and cost through the full KPI pipeline.
10. **Hot-Reloadable:** Extensions can be reloaded from disk without restart.
11. **Auto-Discovery:** User extensions don't need registry entries or even manifests.

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

# Submit query with profile override and extensions
TASK_ID=$(curl -s -X POST "http://localhost:5050/api/v1/sessions/$SESSION_ID/query" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "are shoes relevant for fitness?",
    "profile_id": "profile-default-rag",
    "extensions": [
      {"name": "decision", "param": "binary"}
    ]
  }' | jq -r '.task_id')

# Poll for results (extension_results promoted to top-level)
sleep 15
curl -s "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT" | jq '.extension_results'
```

**Note:** The REST API does NOT parse `@TAG` or `#extension` syntax from prompt text. Use explicit `profile_id` and `extensions` parameters.

### Verification Checklist

| Test | Expected |
|------|----------|
| Submit with `#json` | Extension result in task response + chat_append block in UI |
| Submit with `#decision` | LLM-powered analysis, tokens tracked, `output_target: silent` |
| Submit with `#summary:detailed` | Executive summary appended to chat |
| Serial chain `#extract #decision` | Decision sees extract in `previous_extension_results` |
| Invalid extension name | Main answer delivered, error in extension_results |
| Session reload | Extension tags visible, click to see results with metrics |
| Tag click (chat_append) | Scrolls to and highlights output block |
| Tag click (silent) | Shows inline popover with result |
| REST API live events | extension_start/complete appear in Live Status during execution |
| KPI counters (LLM ext) | LAST TURN shows cumulative tokens, cost reflects extensions |
| Convention extension | Drop `.py` in `~/.tda/extensions/`, reload, appears in list |
| Scaffold API | `POST /v1/extensions/scaffold` creates working skeleton |

---

## File Reference

### Backend

| File | Purpose |
|------|---------|
| `src/trusted_data_agent/extensions/__init__.py` | Public API: SimpleExtension, Extension, LLMExtension |
| `src/trusted_data_agent/extensions/models.py` | ExtensionContext, ExtensionResult, OutputTarget |
| `src/trusted_data_agent/extensions/base.py` | Three-tier base classes |
| `src/trusted_data_agent/extensions/manager.py` | Singleton manager (4 discovery modes, reload) |
| `src/trusted_data_agent/extensions/runner.py` | Serial execution, LLM injection, token extraction |
| `src/trusted_data_agent/extensions/db.py` | Per-user activation persistence (SQLite) |
| `src/trusted_data_agent/extensions/scaffolds.py` | Template generators for all 4 levels |
| `src/trusted_data_agent/extensions/helpers/__init__.py` | Helper re-exports |
| `src/trusted_data_agent/extensions/helpers/text.py` | Text analysis utilities |
| `src/trusted_data_agent/extensions/helpers/json_utils.py` | JSON extraction from text |
| `src/trusted_data_agent/extensions/helpers/regex.py` | Shared regex patterns |
| `src/trusted_data_agent/extensions/helpers/result_builders.py` | ExtensionResult convenience constructors |
| `src/trusted_data_agent/agent/execution_service.py` | `_run_extensions()`, `_persist_extension_results()` |
| `src/trusted_data_agent/api/rest_routes.py` | Extension REST endpoints, scaffold, task integration |
| `src/trusted_data_agent/api/routes.py` | SSE streaming path (extension_specs passthrough) |
| `src/trusted_data_agent/core/session_manager.py` | `append_extension_results_to_turn()` |
| `src/trusted_data_agent/main.py` | ExtensionManager startup initialization |
| `schema/12_extensions.sql` | Database schema for user_extensions table |

### Frontend

| File | Purpose |
|------|---------|
| `static/js/main.js` | `#` autocomplete, badge management, keyboard handling |
| `static/js/eventHandlers.js` | Extension SSE events, historical recall, reload renderer |
| `static/js/ui.js` | `_renderExtensionStep()`, extension tags, cost display |
| `static/js/notifications.js` | REST notification dispatch for extension events |
| `static/js/handlers/extensionHandler.js` | Extensions config tab, tier badges, LLM warnings |
| `static/js/handlers/sessionManagement.js` | Session reload with extension_specs |
| `static/css/main.css` | .extension-tag, .active-extension-badge, etc. |
| `templates/index.html` | Extensions tab, autocomplete containers |

### Extensions

| File | Purpose |
|------|---------|
| `extensions/extension_registry.json` | Central registry (5 built-in extensions) |
| `extensions/schemas/extension-manifest-schema.json` | Manifest validation schema |
| `extensions/builtin/json/` | #json — Structured JSON output (Tier 2) |
| `extensions/builtin/decision/` | #decision — LLM workflow branching (Tier 3) |
| `extensions/builtin/extract/` | #extract — Regex data extraction (Tier 1) |
| `extensions/builtin/classify/` | #classify — LLM semantic classification (Tier 3) |
| `extensions/builtin/summary/` | #summary — LLM executive summary (Tier 3) |
