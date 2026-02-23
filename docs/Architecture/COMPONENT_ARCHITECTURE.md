# Component Architecture: Generative UI Component Library

> Modular, profile-aware component system that transforms LLM tool calls into rich UI elements — charts, sub-windows, media players, and more — with per-profile toggling, admin governance, and third-party extensibility.

## Overview

The Uderia platform renders LLM output through a **component library** where each content type (chart, table, audio, code editor) is a self-contained module with its own prompt instructions, backend handler, and frontend renderer. Components are toggled per-profile, dynamically injected into LLM prompts at runtime, and rendered on the conversation canvas via tool calls or data-driven detection.

This architecture replaces the monolithic approach where charting, table rendering, and other content types were hardcoded throughout the codebase. The chart component serves as the reference implementation — migrated from the legacy charting system into the first fully self-contained component.

---

## Table of Contents

- [Design Philosophy](#design-philosophy)
- [System Architecture](#system-architecture)
  - [High-Level Data Flow](#high-level-data-flow)
  - [Component Categories](#component-categories)
  - [Render Targets](#render-targets)
- [Component Anatomy](#component-anatomy)
  - [Directory Structure](#directory-structure)
  - [Manifest Schema](#manifest-schema)
  - [Instructions System](#instructions-system)
- [Backend Architecture](#backend-architecture)
  - [Base Classes](#base-classes)
  - [Component Definition](#component-definition)
  - [Component Manager](#component-manager)
  - [Admin Governance Settings](#admin-governance-settings)
- [Chart Component: Reference Implementation](#chart-component-reference-implementation)
- [Frontend Architecture](#frontend-architecture)
  - [Component Renderer Registry](#component-renderer-registry)
  - [Sub-Window Manager](#sub-window-manager)
  - [Components Configuration Tab](#components-configuration-tab)
- [Integration Points](#integration-points)
  - [Prompt Injection Pipeline](#prompt-injection-pipeline)
  - [Tool Call Routing](#tool-call-routing)
  - [Component Fast-Path](#component-fast-path)
  - [DOM Rendering](#dom-rendering)
  - [SSE Event Handling](#sse-event-handling)
- [REST API](#rest-api)
  - [User Endpoints](#user-endpoints)
  - [Admin Endpoints](#admin-endpoints)
- [Database Schema](#database-schema)
- [Admin Governance](#admin-governance)
- [Third-Party Components](#third-party-components)
- [File Reference](#file-reference)

---

## Design Philosophy

### 1. Self-Contained Components

Each component is a single directory containing everything needed to function — manifest, prompt instructions, backend handler, and frontend renderer. No changes to core files are required to add a new component.

### 2. Two Handler Tiers

| Tier | Base Class | LLM Involvement | Example |
|------|-----------|-----------------|---------|
| **Action** | `BaseComponentHandler` | LLM calls `TDA_*` tool | Chart, Audio, Code Editor |
| **Structural** | `StructuralHandler` | Automatic from data type | Table, Code Block, Key Metric |

Action components receive prompt instructions and tool definitions injected into the LLM context. Structural components render automatically based on `collected_data` item types — no tool call required.

### 3. Profile-Aware

Components are toggled per-profile via the `componentConfig` key on the profile JSON dict (same pattern as `knowledgeConfig`, `dualModelConfig`). A data analyst profile might enable charts and tables; a chat-only profile might disable everything except markdown. Backward compatible: profiles without `componentConfig` get all components active.

### 4. Deterministic Fast-Path

Components that produce deterministic output (e.g., chart rendering from structured data) declare `is_deterministic = True` and bypass the tactical LLM entirely during phase execution — saving tokens and latency.

### 5. Admin Governance

Administrators control component availability at the platform level (all/selective mode, user imports, marketplace access), while profile owners control per-profile enablement. This mirrors the Extension system governance pattern.

---

## System Architecture

### Three Tool Classes

The platform separates tools into three distinct classes with different lifecycles and availability:

| Class | Examples | Lifecycle | Availability |
|-------|----------|-----------|--------------|
| **System** | TDA_FinalReport, TDA_CurrentDate, TDA_DateRange, TDA_LLMFilter, TDA_LLMTask, TDA_ContextReport, TDA_ComplexPromptReport | Static, always on | `tool_enabled` only (planner infrastructure) |
| **Component** | TDA_Charting (today), future TDA_CodeEditor, etc. | Dynamic, per-profile `componentConfig` | **ALL profile types** (platform feature) |
| **MCP** | base_readQuery, dba_resusageSummary, etc. | Dynamic, per MCP server | `tool_enabled` + `llm_only` with tools |

**Key principle:** Component tools are a **platform feature** — they must be available (selectable by the LLM) for all profile types, not just `tool_enabled`. The `ComponentManager` is the single module all profile classes call into; no component logic lives in profile-specific code.

### High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              RUNTIME FLOW                                    │
│                                                                              │
│  Profile Config                                                              │
│       │                                                                      │
│       ├──────────────────────────────────────────────────────────────┐       │
│       │                                                              │       │
│       ▼                                                              ▼       │
│  get_instructions_text()                              get_langchain_tools()  │
│       │                                                    │                 │
│       ▼                                                    ▼                 │
│  {component_instructions_section}                    LangChain tools         │
│  → injected into MASTER_SYSTEM_PROMPT                (StructuredTool)        │
│                                                            │                 │
│  get_tool_definitions()                                    │                 │
│       │                                                    │                 │
│       ▼                                                    │                 │
│  "Component Tools" category                                │                 │
│  → injected into {tools_context}                           │                 │
│       │                                                    │                 │
│       ├─── tool_enabled: planner sees category ────────────│                 │
│       │                                                    │                 │
│       │    llm_only + tools: merged with MCP tools ◄───────┤                 │
│       │    llm_only (direct): auto-upgrade to agent ◄──────┤                 │
│       │    rag_focused: auto-upgrade after retrieval ◄─────┤                 │
│       │    genie: merged with invoke_* profile tools ◄─────┘                 │
│       │                                                                      │
│       ▼                                                                      │
│  LLM plans/executes → calls TDA_Charting, TDA_Audio, TDA_CodeEditor, etc.   │
│       │                                                                      │
│       ├── Fast-Path (deterministic) → ComponentManager.get_handler()         │
│       │       │                        → handler.process() directly          │
│       │       ▼                                                              │
│       │   ComponentRenderPayload                                             │
│       │                                                                      │
│       ├── Agent Path → LangChain StructuredTool.func() → handler.process()   │
│       │       │         (llm_only, rag_focused, genie)                       │
│       │       ▼                                                              │
│       │   ComponentRenderPayload (JSON)                                      │
│       │                                                                      │
│       └── Standard Path → MCP Adapter routes to handler                      │
│               │             (tool_enabled tactical)                           │
│               ▼                                                              │
│           ComponentRenderPayload                                             │
│               │                                                              │
│               ▼                                                              │
│  Formatter embeds: <div data-component-id="chart" data-spec='...'>           │
│         or                                                                   │
│  SSE event: component_render → sub-window creation                           │
│               │                                                              │
│               ▼                                                              │
│  Frontend: ComponentRendererRegistry.renderComponent() → DOM                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Categories

| Category | LLM Involvement | Prompt Injection | Tool Definition | Examples |
|----------|-----------------|------------------|-----------------|----------|
| **Action** | LLM explicitly calls `TDA_*` tool | Instructions injected | Tool definition injected | Chart, Audio, Image, Code Editor |
| **Structural** | Automatic from data type | None | None | Table, Code Block, Key Metric, Markdown |

### Render Targets

Components declare which render targets they support via the manifest:

| Target | Location | Behavior | Example |
|--------|----------|----------|---------|
| `inline` | Inside chat message bubble | Renders as part of the response HTML | Table, chart, key metric |
| `sub_window` | Persistent panel on canvas | Stays open until user closes; survives new messages | Code editor, HTML preview |
| `status_panel` | Live Status panel | Renders in the status visualization area | Progress indicators |

A single component can support multiple targets. The chart component renders `inline` by default but supports `sub_window` for interactive exploration.

---

## Component Anatomy

### Directory Structure

Each component is a self-contained directory:

```
components/builtin/chart/
├── manifest.json         # Metadata, tool definition, dependencies, render targets
├── instructions.json     # LLM prompt text (intensity-keyed for chart)
├── guidelines.txt        # Supplementary prompt text (G2Plot guidelines)
├── handler.py            # Python: process tool args → ComponentRenderPayload
└── renderer.js           # JS: render payload into DOM element
```

**File:** `components/builtin/chart/manifest.json` (71 lines)

### Manifest Schema

**File:** `components/schemas/component_manifest_v1.schema.json` (185 lines)

Every component must include a `manifest.json` validated against the JSON Schema. Key sections:

```json
{
  "component_id": "chart",                    // Required: ^[a-z][a-z0-9_]*$
  "display_name": "Data Visualization",       // Required: human-readable name
  "version": "1.0.0",                         // Required: semver ^\d+\.\d+\.\d+$
  "component_type": "action",                 // Required: "action" | "structural"
  "description": "...",                        // Optional
  "category": "Visualization",                // Optional: Visualization|Media|Code|Layout|General

  "tool_definition": {                        // Action components only
    "name": "TDA_Charting",                   // Must start with TDA_
    "description": "...",
    "args": { ... }                           // Parameter schema
  },

  "instructions": {                           // Prompt injection config
    "file": "instructions.json",              // Relative to component directory
    "format": "intensity_keyed",              // "plain" | "intensity_keyed"
    "placeholder_substitutions": {            // Optional: inject supplementary files
      "{G2PLOT_GUIDELINES}": "guidelines.txt"
    }
  },

  "backend": {
    "handler_file": "handler.py",             // Required
    "handler_class": "ChartComponentHandler", // Optional: auto-detected if omitted
    "fast_path": true                         // Hint for executor optimization
  },

  "frontend": {
    "renderer_file": "renderer.js",           // Required
    "renderer_export": "renderChart",         // Required: exported function name
    "cdn_dependencies": [{                    // Optional: external libraries
      "name": "G2Plot",
      "url": "https://unpkg.com/@antv/g2plot@2.4.31/dist/g2plot.min.js",
      "global": "G2Plot"
    }]
  },

  "render_targets": {
    "default": "inline",                      // Default render target
    "supports": ["inline", "sub_window"],     // All supported targets
    "sub_window": {                           // Sub-window configuration
      "title_template": "{chart_type} Chart: {title}",
      "default_size": { "width": 600, "height": 400 },
      "resizable": true,
      "interactive": false
    }
  },

  "profile_defaults": {
    "enabled_for": ["tool_enabled", "llm_only", "rag_focused", "genie"],  // All profile types supported
    "default_intensity": "medium"                   // Instruction intensity
  }
}
```

### Instructions System

Components can provide LLM instructions in two formats:

**Plain text** (`format: "plain"`): Single string injected as-is.

**Intensity-keyed** (`format: "intensity_keyed"`): JSON object mapping intensity levels to instruction variants:

```json
{
  "minimal": "Brief charting hint...",
  "low": "Basic charting instructions...",
  "medium": "Standard charting instructions with examples...",
  "high": "Comprehensive charting instructions with all chart types..."
}
```

The profile's `componentConfig[component_id].intensity` setting selects which variant to inject. Default: `"medium"`.

**Placeholder substitution**: The manifest's `placeholder_substitutions` field maps placeholders to supplementary files. For example, `{G2PLOT_GUIDELINES}` is replaced with the contents of `guidelines.txt` at instruction load time.

---

## Backend Architecture

### Base Classes

**File:** `src/trusted_data_agent/components/base.py` (219 lines)

#### RenderTarget Enum (line 28)

```python
class RenderTarget(Enum):
    INLINE = "inline"
    SUB_WINDOW = "sub_window"
    STATUS_PANEL = "status_panel"
```

#### ComponentRenderPayload (line 39)

Dataclass that represents the output of a component handler — the bridge between backend processing and frontend rendering:

| Field | Type | Purpose |
|-------|------|---------|
| `component_id` | `str` | Component identifier (e.g., `"chart"`) |
| `render_target` | `RenderTarget` | Where to render (inline, sub_window, status_panel) |
| `spec` | `Optional[dict]` | JSON spec for frontend renderer |
| `html` | `Optional[str]` | Pre-rendered HTML (structural components) |
| `container_id` | `Optional[str]` | Target DOM container ID |
| `title` | `Optional[str]` | Display title |
| `metadata` | `Optional[dict]` | Additional metadata |
| `tts_text` | `Optional[str]` | Text-to-speech content |
| `window_id` | `Optional[str]` | Sub-window identifier |
| `window_action` | `Optional[str]` | Sub-window action: create/update/close |
| `interactive` | `bool` | Whether sub-window accepts user edits |

Key methods:
- `to_collected_data()` (line 98) — Format for formatter integration into `collected_data`
- `to_sse_event()` (line 114) — Format for SSE `component_render` event streaming

#### BaseComponentHandler (line 132)

Abstract base class for action components (LLM-invoked via tool call):

```python
class BaseComponentHandler(ABC):
    @property
    @abstractmethod
    def component_id(self) -> str: ...       # Line 148: Unique identifier

    @property
    @abstractmethod
    def tool_name(self) -> str: ...          # Line 153: TDA_* tool name

    @property
    def is_deterministic(self) -> bool:      # Line 157: Default True (fast-path)
        return True

    @abstractmethod
    async def process(                        # Line 165: Core processing
        self,
        arguments: dict,
        context: Optional[dict] = None
    ) -> ComponentRenderPayload: ...

    def validate_arguments(                   # Line 184: Optional validation
        self,
        arguments: dict
    ) -> tuple[bool, str]: ...
```

#### StructuralHandler (line 203)

Base class for non-tool-driven components (table, code block, key metric). Overrides `tool_name` to return `""` and `is_deterministic` to return `True`.

### Component Definition

**File:** `src/trusted_data_agent/components/models.py` (206 lines)

The `ComponentDefinition` dataclass (line 18) is the runtime representation of a loaded component:

**Identity fields** (lines 27-49): `component_id`, `display_name`, `description`, `version`, `component_type`, `category`, `source` (builtin|agent_pack|user), `agent_pack_id`

**File path fields** (lines 51-62): `directory`, `manifest_path`, `handler_path`, `renderer_path`

**Manifest data fields** (lines 64-81): `manifest` (full JSON), `tool_definition`, `instructions_config`, `render_targets`, `frontend_config`, `profile_defaults`

**Runtime fields** (lines 83-88): `handler` (instantiated handler instance), `_instructions_cache`

Key methods:

| Method | Line | Purpose |
|--------|------|---------|
| `get_instructions(intensity)` | 90 | Load and cache instructions with intensity resolution and placeholder substitution |
| `get_tool_name()` | 156 | Extract tool name from manifest |
| `get_cdn_dependencies()` | 162 | Extract CDN dependency list |
| `get_default_render_target()` | 166 | Default render target from manifest |
| `supports_render_target(target)` | 170 | Check if target is supported |
| `to_api_dict()` | 175 | Serialize for REST API responses |
| `to_frontend_manifest()` | 196 | Minimal manifest for frontend registry |

### Component Manager

**File:** `src/trusted_data_agent/components/manager.py` (~620 lines)

Singleton that discovers, loads, and manages all components. Mirrors the `ExtensionManager` pattern from `src/trusted_data_agent/extensions/manager.py`. **All profile classes call into ComponentManager** — no component logic lives in profile-specific code.

#### Singleton Access

```python
get_component_manager(components_dir=None, user_dir=None)  # Line 37
reset_component_manager()                                    # Line 53
```

#### Discovery and Loading

The constructor (line 74) resolves directory paths and triggers discovery:

```
components_dir  → {project_root}/components/
builtin_dir     → {project_root}/components/builtin/
registry_file   → {project_root}/components/component_registry.json
schemas_dir     → {project_root}/components/schemas/
user_dir        → ~/.tda/components/
```

Three-phase discovery (`_discover_and_load()`, line 138):

```
Phase 1: Built-in registry → component_registry.json
         Load components listed explicitly in the registry file
         Source: "builtin"

Phase 2: Built-in auto-discover → components/builtin/*/manifest.json
         Discover components not in registry (new additions)
         Source: "builtin"

Phase 3: User auto-discover → ~/.tda/components/*/manifest.json
         Third-party and user-installed components
         Source: "user"
```

Later phases override earlier ones — a user component with the same `component_id` replaces the built-in version.

Each component is loaded via `_load_component()` (line 187):
1. Parse and validate `manifest.json`
2. Dynamically import handler via `importlib.util` (`_load_handler()`, line 263)
3. If `handler_class` is omitted, auto-detect first `BaseComponentHandler` subclass
4. Register in `_components` dict and `_tool_to_component` lookup

#### Public API

**Access methods:**

| Method | Line | Returns | Purpose |
|--------|------|---------|---------|
| `get_component(id)` | 320 | `ComponentDefinition` \| `None` | Get single component by ID |
| `get_handler(tool_name)` | 324 | `BaseComponentHandler` \| `None` | Get handler by tool name |
| `is_component_tool(tool_name)` | 333 | `bool` | Check if tool belongs to a component |
| `get_all_components()` | 337 | `List[ComponentDefinition]` | All loaded components |
| `get_builtin_components()` | 341 | `List[ComponentDefinition]` | Built-in only |

**Profile-aware methods:**

| Method | Line | Purpose |
|--------|------|---------|
| `get_active_components(profile_config)` | 349 | Filter by `profile_config.componentConfig[id].enabled` |
| `get_tool_definitions(profile_config)` | 377 | Extract tool definitions for active action components |
| `get_instructions_text(profile_config, session_data)` | 394 | Assemble all active component instructions with intensity resolution |
| `has_active_tool_components(profile_config)` | — | Quick boolean: does this profile have active action components? |
| `get_langchain_tools(profile_config)` | — | Create LangChain `StructuredTool` objects from active action components |

**Module-level convenience functions** (parallel to `get_component_instructions_for_prompt()`):

| Function | Purpose |
|----------|---------|
| `get_component_instructions_for_prompt(profile_id, user_uuid, session_data)` | Resolve profile → assemble instruction text (existing) |
| `get_component_langchain_tools(profile_id, user_uuid)` | Resolve profile → create LangChain tools (new) |

These convenience functions handle profile resolution internally so profile classes need only one call.

**Frontend methods:**

| Method | Line | Returns |
|--------|------|---------|
| `get_frontend_manifest()` | 437 | `List[Dict]` — minimal manifests for `ComponentRendererRegistry` |

**Hot-reload:**

`reload()` clears all registries and re-runs discovery. Returns new component count.

#### LangChain Tool Factory

`get_langchain_tools()` wraps each active action component's handler as a LangChain `StructuredTool`:

```python
def get_langchain_tools(self, profile_config: Dict) -> List[StructuredTool]:
    # 1. Filter active action components with handlers
    # 2. For each: create async wrapper around handler.process()
    # 3. Return list of StructuredTool objects
```

The async wrapper serializes the `ComponentRenderPayload` to JSON so the LLM agent receives structured output. This enables component tools to work with `ConversationAgentExecutor` (LangGraph-based) across all profile types.

#### Auto-Upgrade Pattern

When a non-tool profile (llm_only direct, rag_focused) has active component tools, the executor automatically routes through `ConversationAgentExecutor` instead of a direct LLM call. The check:

```python
manager = get_component_manager()
if manager.has_active_tool_components(profile_config):
    # Auto-upgrade: use ConversationAgentExecutor with component tools only
```

This is transparent to the user — the profile type doesn't change, but the execution path gains tool-calling capability.

### Admin Governance Settings

**File:** `src/trusted_data_agent/components/settings.py` (142 lines)

Mirrors `src/trusted_data_agent/extensions/settings.py` exactly.

**Settings stored in `component_settings` table:**

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `components_mode` | `"all"` \| `"selective"` | `"all"` | Whether all components available or admin selects |
| `disabled_components` | JSON array | `[]` | Component IDs disabled in selective mode |
| `user_components_enabled` | boolean | `true` | Allow importing custom components |
| `user_components_marketplace_enabled` | boolean | `true` | Enable marketplace browsing |

**Predicate functions:**

| Function | Line | Purpose |
|----------|------|---------|
| `is_component_available(component_id)` | 122 | Returns `True` if mode is `"all"`, else checks disabled list |
| `are_user_components_enabled()` | 134 | Whether custom import is allowed |
| `is_component_marketplace_enabled()` | 139 | Whether marketplace is accessible |

---

## Chart Component: Reference Implementation

**Directory:** `components/builtin/chart/`

The chart component is the first fully migrated component and serves as the reference implementation for the component library. It was extracted from three locations in the legacy codebase:

| Legacy Location | Extracted To |
|-----------------|-------------|
| `src/trusted_data_agent/mcp_adapter/adapter.py:1691` (`_build_g2plot_spec()`) | `components/builtin/chart/handler.py` |
| `static/js/utils.js:245` (`renderChart()`) | `components/builtin/chart/renderer.js` |
| `trusted-data-agent-license/default_prompts/CHARTING_INSTRUCTIONS.json` | `components/builtin/chart/instructions.json` |
| `trusted-data-agent-license/default_prompts/G2PLOT_GUIDELINES.txt` | `components/builtin/chart/guidelines.txt` |

### ChartComponentHandler

**File:** `components/builtin/chart/handler.py` (259 lines)

```python
class ChartComponentHandler(BaseComponentHandler):        # Line 20
    component_id = "chart"                                 # Line 24
    tool_name = "TDA_Charting"                            # Line 28
    is_deterministic = True                                # Line 32

    async def process(self, arguments, context=None):     # Line 45
        # 1. Transform/normalize data (handle LLM hallucinations)
        # 2. Build G2Plot spec from semantic roles
        # 3. Return ComponentRenderPayload with spec
```

**Data normalization** (`_transform_chart_data()`, line 99): Handles five LLM hallucination patterns:

| Pattern | Lines | Correction |
|---------|-------|------------|
| Nested `{results: [...]}` wrapper | 109-119 | Flatten to top-level array |
| `{labels: [...], values: [...]}` | 122-133 | Convert to array of dicts |
| `{columns: [...], rows: [...]}` | 136-141 | Convert to array of dicts |
| `ColumnName` key (qlty_distinctCategories) | 144-160 | Rename to `SourceColumnName` |
| String numeric values | 219-239 | Coerce to float |

**G2Plot spec generation** (`_build_g2plot_spec()`, line 165): Maps LLM semantic roles to G2Plot chart configuration:

| LLM Semantic Role | G2Plot Field | Chart Types |
|-------------------|-------------|-------------|
| `x_axis` | `xField` | Column, Line, Area, Bar |
| `y_axis` | `yField` | Column, Line, Area, Bar |
| `color` / `series` | `seriesField` | All (grouping) |
| `angle` / `value` | `angleField` | Pie, Donut |
| `size` | `sizeField` | Scatter |

### Chart Renderer

**File:** `components/builtin/chart/renderer.js` (41 lines)

```javascript
export function renderChart(containerId, payload) {
    // 1. Parse spec from payload (JSON string or object)
    // 2. Validate spec.type, spec.options, G2Plot availability
    // 3. Instantiate G2Plot[spec.type](container, spec.options)
    // 4. Call plot.render()
}
```

**CDN dependency:** G2Plot loaded from `https://unpkg.com/@antv/g2plot@2.4.31/dist/g2plot.min.js` (declared in manifest, loaded by `ComponentRendererRegistry`).

---

## Frontend Architecture

### Component Renderer Registry

**File:** `static/js/componentRenderers.js` (158 lines)

Central registry mapping `component_id` → renderer function. Handles CDN dependency loading, renderer registration, and render dispatch.

**Internal state:**

| Variable | Line | Type | Purpose |
|----------|------|------|---------|
| `_renderers` | 18 | `Map<string, Function>` | component_id → renderer function |
| `_loadedDeps` | 21 | `Set<string>` | Loaded CDN dependency URLs |
| `_loadingDeps` | 24 | `Map<string, Promise>` | In-flight CDN loads (dedup) |

**Pre-registered:** The chart renderer is pre-registered at line 31:
```javascript
_renderers.set('chart', renderChart);
```

**Exported functions:**

| Function | Line | Signature | Purpose |
|----------|------|-----------|---------|
| `renderComponent` | 45 | `(componentId, containerId, payload)` | Parse payload → call renderer |
| `registerComponent` | 74 | `(componentId, renderer)` | Add renderer to registry |
| `hasRenderer` | 81 | `(componentId) → bool` | Check if renderer exists |
| `loadCDNDependency` | 92 | `(url, globalName) → Promise` | Load external JS with dedup |
| `registerFromManifest` | 132 | `(manifest) → Promise` | Load deps → dynamically import renderer → register |

**`renderComponent()` flow:**
1. Look up renderer in `_renderers` Map
2. If not found, display warning in container
3. Parse `payload` (JSON string → object if needed)
4. Call `renderer(containerId, payload)`
5. Catch errors and display in container with `text-red-400` styling

**`registerFromManifest()` flow** (for dynamic third-party components):
1. Load all CDN dependencies via `loadCDNDependency()`
2. Dynamically import renderer JS module
3. Extract renderer export by name
4. Register in `_renderers` Map

### Sub-Window Manager

**File:** `static/js/subWindowManager.js` (221 lines)

Manages persistent, resizable panels on the conversation canvas. Sub-windows stay open until explicitly closed by the user, even as new chat messages flow in.

**Internal state:**

`_openWindows` (line 22): `Map<string, {componentId, title, state, interactive, element}>`

**DOM structure:**

```
<div id="sub-window-container">               ← Container in index.html
  <div class="sub-window glass-panel" id="{windowId}">
    <div class="sub-window-header">
      <span class="sub-window-title">{title}</span>
      <div class="sub-window-controls">
        <button class="sw-minimize">─</button>
        <button class="sw-close">✕</button>
      </div>
    </div>
    <div class="sub-window-body" id="{windowId}-body">
      <!-- Component renderer fills this -->
    </div>
  </div>
</div>
```

**Exported functions:**

| Function | Line | Signature | Purpose |
|----------|------|-----------|---------|
| `createSubWindow` | 40 | `(windowId, componentId, options) → HTMLElement` | Create and mount sub-window |
| `updateSubWindow` | 105 | `(windowId, payload)` | Update existing sub-window content |
| `closeSubWindow` | 126 | `(windowId)` | Remove sub-window from DOM and registry |
| `minimizeSubWindow` | 137 | `(windowId)` | Collapse to title bar only |
| `restoreSubWindow` | 150 | `(windowId)` | Restore from minimized state |
| `getSubWindowState` | 166 | `(windowId) → object` | Read current state (for context injection) |
| `getAllOpenWindows` | 183 | `() → Map` | All open windows (for bidirectional context) |
| `closeAllSubWindows` | 199 | `()` | Close all windows (session cleanup) |
| `getOpenWindowCount` | 208 | `() → number` | Count of open windows |

**Bidirectional context flow:**

When the user sends a new message, the query submission handler calls `getAllOpenWindows()` to collect the current state of all open sub-windows. This state is injected into the query payload as `sub_window_context`, allowing the LLM to reference and update existing sub-windows:

```
LLM → TDA_CodeEditor tool call → sub-window created with code
User edits code in sub-window
User sends next message → sub-window state injected into LLM context
LLM references/updates the sub-window by window_id
```

### Components Configuration Tab

**File:** `static/js/handlers/componentHandler.js` (193 lines)

Provides the "Components" tab in the Configuration page — a card grid with filters for browsing, enabling, and managing components.

**Tab location in Configuration page:**
```
MCP Servers | LLM Providers | Agent Profiles | Skills | Extensions | Components | Agent Packs | Advanced
                                                                      ^^^^^^^^^
```

**Exported functions:**

| Function | Line | Purpose |
|----------|------|---------|
| `loadComponents()` | 16 | Fetch `GET /v1/components`, render card grid, apply governance |
| `initializeComponentHandlers()` | 113 | Wire filter pills, Import/Reload buttons |

**Card rendering** (`_renderComponentCard()`, line 59):

Each component renders as a glass-panel card with:
- Component name and version
- Source badge (built-in → violet, agent_pack → cyan, user → amber)
- Type badge (action → blue, structural → gray)
- Description text
- Enable/disable toggle
- Intensity selector (if applicable)

**Data attributes on cards:** `data-component-type`, `data-component-source`, `data-component-id`

**Filter system** (`_setupFilterPills()`, line 158): Category and status filter pills with `.filter-pill` / `.filter-pill--active` CSS classes.

**Governance enforcement:** When `_componentSettings.user_components_enabled === false`, the Import button is hidden.

---

## Integration Points

### Prompt Injection Pipeline

**File:** `src/trusted_data_agent/llm/handler.py` (lines 429-554)

When building the system prompt, the LLM handler assembles component instructions:

```
Line 429:  component_instructions_section = ""
Line 433:  from trusted_data_agent.components.manager import get_component_manager
Line 436:  Resolve profile_config via config_manager using active_profile_id + user_uuid
Line 443:  comp_manager.get_instructions_text(profile_config, session_data)
Line 448:  Wrap in markdown formatting
Line 554:  .replace('{component_instructions_section}', component_instructions_section)
```

**Profile config resolution**: The handler resolves the actual profile dict from `config_manager.get_profile(active_profile_id, user_uuid)`, not from `session_data` (which never carries `profile_config`). This ensures per-profile component filtering works correctly. The `_get_full_system_prompt()` function receives `user_uuid` as a parameter, passed from `call_llm_api()`.

The `{component_instructions_section}` placeholder in `MASTER_SYSTEM_PROMPT.txt` is replaced with the assembled instructions. The `ComponentManager.get_instructions_text()` method:

1. Filters components by profile config (`get_active_components()`)
2. For each active action component, loads instructions at the profile's intensity level
3. Assembles into a single text block with component headers
4. Uses the `full_context_sent` flag: full instructions on first turn, condensed names-only on subsequent turns

### Tool Call Routing

Component tools are routed differently depending on the profile type:

#### tool_enabled Path (Planner/Executor)

**File:** `src/trusted_data_agent/mcp_adapter/adapter.py` (lines 1691-1712)

When the MCP adapter receives a tool call, it checks if the tool belongs to a component:

```python
if comp_manager.is_component_tool(tool_name):
    handler = comp_manager.get_handler(tool_name)
    payload = await handler.process(arguments)
    return component_result
```

This intercepts component tool calls before they reach MCP server dispatch. The handler returns a `ComponentRenderPayload` which is formatted into the tool result.

#### llm_only + tools Path (Conversation Agent)

**File:** `src/trusted_data_agent/agent/executor.py` (~line 1398)

Component LangChain tools are merged with MCP tools:

```python
component_tools = get_component_langchain_tools(self.active_profile_id, self.user_uuid)
all_tools = mcp_tools + component_tools  # MCP tools optional when components present
agent = ConversationAgentExecutor(..., mcp_tools=all_tools, ...)
```

MCP server is no longer required when component tools are present — a profile with only component tools can still use the conversation agent path.

#### llm_only Direct Path (Auto-Upgrade)

**File:** `src/trusted_data_agent/agent/executor.py` (~line 2441)

Pure conversation profiles (no MCP tools) automatically upgrade to agent execution when component tools are active:

```python
has_component_tools = comp_manager.has_active_tool_components(profile_config)
is_llm_only = (profile_type == "llm_only" and not use_mcp_tools and not has_component_tools)
is_conversation_with_tools = (profile_type == "llm_only" and (use_mcp_tools or has_component_tools))
```

When `has_component_tools` is True, the profile routes through `ConversationAgentExecutor` with only component tools (no MCP, no system tools).

#### rag_focused Path (Auto-Upgrade)

**File:** `src/trusted_data_agent/agent/executor.py` (~line 3622)

After RAG retrieval builds knowledge context, if component tools are active, synthesis uses an agent instead of direct LLM:

```python
rag_component_tools = get_component_langchain_tools(self.active_profile_id, self.user_uuid)
if rag_component_tools:
    # Agent-based synthesis with component tools + RAG knowledge context
    rag_agent = ConversationAgentExecutor(..., mcp_tools=rag_component_tools, ...)
else:
    # Standard direct synthesis (no tools)
```

#### genie Path (Coordinator)

**File:** `src/trusted_data_agent/agent/genie_coordinator.py` (~line 530)

Component tools are merged with the coordinator's invoke_* profile tools:

```python
component_tools = get_component_langchain_tools(self.genie_profile.get("id"), self.user_uuid)
if component_tools:
    self.tools.extend(component_tools)
    self.component_tool_names = {t.name for t in component_tools}
```

The coordinator can then call component tools (e.g., TDA_Charting) when synthesizing results from sub-profiles. Component tool invocations emit explicit Live Status events:

| Event | When | Payload |
|-------|------|---------|
| `genie_component_invoked` | `on_tool_start` when tool is in `component_tool_names` | `{tool_name, session_id}` |
| `genie_component_completed` | `on_tool_end` when payload extraction succeeds | `{tool_name, component_id, success, session_id}` |

These events are routed through `eventHandlers.js` → `genieHandler.js` and rendered as dedicated cards in the Live Status panel. Payload extraction uses the shared `extract_component_payload()` utility; HTML generation uses `generate_component_html()` — both from `components/utils.py`.

### Component Fast-Path

**File:** `src/trusted_data_agent/agent/phase_executor.py` (lines 1066-1156)

Deterministic components bypass the tactical LLM entirely during phase execution (`tool_enabled` path only). This is the most significant performance optimization — saving an entire LLM round-trip per component invocation.

```
Line 1066:  # --- COMPONENT FAST-PATH: Deterministic component handlers ---
Line 1074:  from trusted_data_agent.components.manager import get_component_manager
Line 1076:  if comp_manager.is_component_tool(tool_name):
Line 1078:      if comp_handler.is_deterministic:
Line 1082:          # Chart-specific: resolve data from collected_data, generate mapping
Line 1144:          # Generic deterministic: future components
Line 1156:  # --- END COMPONENT FAST-PATH ---
```

The chart-specific fast-path (lines 1082-1142):
1. Resolves data from `collected_data` (previous phase results)
2. Calls `_generate_charting_mapping()` to determine chart type and field mappings
3. Executes the handler directly with resolved arguments
4. Skips tactical LLM entirely → saves ~3,000 tokens per chart

The `_component_bypass_handled` flag pattern ensures graceful fallback — if the fast-path fails for any reason, execution falls through to the standard tactical LLM path.

### DOM Rendering

**File:** `static/js/ui.js` (lines 10, 1361-1377)

When a message is added to the chat log, `ui.js` scans for component containers:

```javascript
// Line 10: Import
import { renderComponent, hasRenderer } from './componentRenderers.js';

// Lines 1361-1369: Generalized component rendering
const componentContainers = messageContent.querySelectorAll('[data-component-id]');
componentContainers.forEach(container => {
    const componentId = container.dataset.componentId;
    const spec = container.dataset.spec;
    if (componentId && spec && hasRenderer(componentId)) {
        renderComponent(componentId, container.id, spec);
    }
});

// Lines 1371-1377: Legacy fallback for .chart-render-target without data-component-id
const chartContainers = messageContent.querySelectorAll(
    '.chart-render-target:not([data-component-id])'
);
chartContainers.forEach(container => {
    if (container.dataset.spec) {
        renderChart(container.id, container.dataset.spec);
    }
});
```

The shared utility `generate_component_html()` (`components/utils.py`) embeds component output as:
```html
<div class="response-card mb-4">
  <div id="component-{uuid12}" data-component-id="chart"
       data-spec='{"type":"Column","options":{...}}'></div>
</div>
```

All profile types (llm_only, rag_focused, genie) call this single function — there is no profile-specific HTML generation logic.

### SSE Event Handling

#### Inline Components

Inline components (`render_target: "inline"`) are embedded in the `final_answer` HTML and rendered during `UI.appendMessage()` — no dedicated SSE event required.

#### Sub-Window Components

**File:** `static/js/eventHandlers.js` (lines 25-26, 1271-1305)

Sub-window components are delivered via SSE `component_render` events during streaming:

```javascript
// Lines 25-26: Imports
import { renderComponent, hasRenderer } from './componentRenderers.js';
import { createSubWindow, updateSubWindow, closeSubWindow } from './subWindowManager.js';

// Lines 1271-1305: Event handler in processStream()
} else if (eventName === 'component_render') {
    const { component_id, window_id, action, spec, title, render_target } = eventData;

    if (render_target === 'sub_window') {
        if (action === 'close')       → closeSubWindow(window_id)
        else if (action === 'update') → updateSubWindow(window_id, spec)
        else                          → createSubWindow() + renderComponent()
    }

    // Update Live Status panel
    UI.updateStatusWindow({
        step: `Component: ${title || component_id}`,
        details: { component_id, render_target, action },
        type: 'component_render'
    });
}
```

**SSE event payload schema:**
```json
{
  "component_id": "chart",
  "window_id": "sw-abc123",
  "action": "create",
  "spec": { "type": "Column", "options": { ... } },
  "title": "Revenue by Quarter",
  "render_target": "sub_window"
}
```

#### Genie Component Events

**File:** `static/js/eventHandlers.js` (~line 1325), `static/js/ui.js` (`_renderGenieStep`)

When the genie coordinator calls component tools directly (not through a child profile), it emits dedicated Live Status events:

| SSE Event | Trigger | Live Status Card |
|-----------|---------|------------------|
| `genie_component_invoked` | `on_tool_start` for component tool | "Component: TDA_Charting" (amber, active) |
| `genie_component_completed` | `on_tool_end` with successful payload extraction | "Component Complete: chart" (green, completed) |

These events are routed through the genie event handler path (`eventHandlers.js` → `genieHandler.js` → `ui.js:_renderGenieStep`) and rendered as cards in the genie coordination trace. They are also persisted in `genie_events` for plan reload.

---

## REST API

### User Endpoints

**File:** `src/trusted_data_agent/api/rest_routes.py` (lines 11530-11672)

| Method | Path | Line | Purpose |
|--------|------|------|---------|
| `GET` | `/v1/components` | 11530 | List all installed components with status and governance |
| `POST` | `/v1/components/reload` | 11572 | Hot-reload components from disk |
| `GET` | `/v1/components/<id>` | 11594 | Get component details + full manifest |
| `GET` | `/v1/components/<id>/renderer` | 11623 | Serve renderer JS file for dynamic loading |
| `GET` | `/v1/components/manifest` | 11652 | Get frontend manifests for all active components |

**`GET /v1/components` response shape:**
```json
{
  "components": [
    {
      "component_id": "chart",
      "display_name": "Data Visualization",
      "version": "1.0.0",
      "component_type": "action",
      "category": "Visualization",
      "source": "builtin",
      "is_active": true,
      "render_targets": { "default": "inline", "supports": ["inline", "sub_window"] }
    }
  ],
  "_settings": {
    "user_components_enabled": true,
    "marketplace_enabled": true
  }
}
```

The `_settings` blob enables frontend governance enforcement (hiding Import button when user components disabled).

### Admin Endpoints

**File:** `src/trusted_data_agent/api/admin_routes.py` (lines 2609-2690)

| Method | Path | Line | Purpose |
|--------|------|------|---------|
| `GET` | `/v1/admin/component-settings` | 2609 | Get governance settings + built-in component list for checklist |
| `POST` | `/v1/admin/component-settings` | 2650 | Save governance settings (requires admin role) |

---

## Database Schema

### Component Tables

**File:** `schema/18_components.sql` (46 lines)

**`installed_components`** (lines 10-21): Registry of all installed components.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Auto-increment |
| `component_id` | TEXT UNIQUE | Component identifier |
| `display_name` | TEXT | Human-readable name |
| `version` | TEXT | Semver version |
| `source` | TEXT | `builtin` \| `agent_pack` \| `user` |
| `agent_pack_id` | TEXT | FK to agent pack (if source=agent_pack) |
| `is_active` | BOOLEAN | Whether component is active |
| `manifest_json` | TEXT | Full manifest for reference |
| `installed_at` | TIMESTAMP | Installation time |
| `updated_at` | TIMESTAMP | Last update time |

**Per-profile component configuration** is stored on the profile JSON dict as `componentConfig` (not in a separate database table). This follows the same pattern as `knowledgeConfig`, `dualModelConfig`, and `genieConfig`:

```json
{
  "componentConfig": {
    "chart": { "enabled": true, "intensity": "medium" }
  }
}
```

Backward compatible: when `componentConfig` is absent, `ComponentManager.get_active_components()` returns all components (no filtering).

**`installed_components` is populated automatically** by `ComponentManager._sync_to_database()` at startup and on hot-reload. Components no longer on disk are marked `is_active = 0`.

### Component Settings Table

**File:** `schema/19_component_settings.sql` (29 lines)

**`component_settings`** (lines 11-17): Admin governance settings.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Auto-increment |
| `setting_key` | TEXT UNIQUE | Setting identifier |
| `setting_value` | TEXT | Setting value (string, JSON, or boolean) |
| `updated_at` | TIMESTAMP | Last update time |
| `updated_by` | TEXT | Admin who changed the setting |

Default values inserted at lines 20-24.

### Table Creation in Bootstrap

**File:** `src/trusted_data_agent/auth/database.py`

| Function | Lines | Purpose |
|----------|-------|---------|
| `_create_components_tables()` | 842-898 | Load `18_components.sql`, create tables with inline fallback |
| `_create_component_settings_table()` | 901-960 | Load `19_component_settings.sql`, bootstrap from `tda_config.json` |

---

## Admin Governance

The admin governance system controls component availability at the platform level. It mirrors the Extension governance pattern exactly.

### Administration UI

**File:** `static/js/adminManager.js` (lines 2835-2942)

Located in Administration → App Config → Features panel, the "Component Management" section provides:

```
┌─ Component Management ──────────────────────────────────────────┐
│  Control component availability and custom components           │
│                                                                 │
│  Component Availability                                         │
│  ● All components available (default)                          │
│  ○ Selective — Choose which built-in components are available   │
│    ┌──────────────────────────────────────────┐                │
│    │ ☑ Data Visualization (chart)             │                │
│    │ ☐ Audio/TTS (audio_tts)                  │                │
│    │ ...                                       │                │
│    └──────────────────────────────────────────┘                │
│                                                                 │
│  🟢 Allow users to import custom components                    │
│  🟢 Enable component marketplace                               │
└─────────────────────────────────────────────────────────────────┘
```

**Functions:**
- `loadComponentSettings()` (line 2835) — Populates radio buttons + checklist + toggles
- `saveComponentSettings()` (line 2887) — POSTs payload to admin endpoint

### Enforcement Chain

```
Admin sets "selective" mode + disables "audio_tts"
    ↓
component_settings table updated
    ↓
GET /v1/components → is_component_available("audio_tts") returns False
    ↓
Audio component filtered from response
    ↓
ComponentManager.get_active_components() excludes it
    ↓
No audio instructions injected into LLM prompt
    ↓
LLM has no knowledge of TDA_Audio → never calls it
```

### Backward Compatibility

Profiles without `componentConfig` get all built-in components enabled by default. The `APP_CONFIG.CHARTING_ENABLED` flag is still respected as a global override for the chart component specifically.

---

## Third-Party Components

### Component Sources

| Source | Location | Discovery | Example |
|--------|----------|-----------|---------|
| `builtin` | `components/builtin/` | Registry + auto-discover | Chart, Table |
| `agent_pack` | Extracted from `.agentpack` files | `AgentPackManager.install()` | Pack-bundled components |
| `user` | `~/.tda/components/` | Auto-discover | User-installed |

### Installation Flow

```
User clicks Import → selects component directory/zip
    ↓
POST /v1/components/import
    ↓
Validate manifest against JSON Schema
    ↓
Copy to ~/.tda/components/{component_id}/
    ↓
ComponentManager.reload()
    ↓
Handler loaded via importlib, renderer registered
    ↓
Component appears in Components tab
```

### Security Model

| Layer | Mechanism |
|-------|-----------|
| Backend handlers | Same trust model as extensions (`importlib` dynamic loading) |
| Frontend renderers | Served via `/v1/components/<id>/renderer` endpoint |
| CDN dependencies | Declared in manifest, loaded via `<script>` tag |
| CSP headers | Restrict script sources to platform origin + declared CDN deps |

### Agent Pack Integration

Agent pack manifests (v1.2+) include a `components` array. When a pack is installed:
1. `AgentPackManager.install()` extracts component directories to `~/.tda/components/`
2. `installed_components.agent_pack_id` links component to pack
3. Pack uninstall removes associated components

---

## File Reference

### New Files (Component System)

| File | Lines | Purpose |
|------|-------|---------|
| `src/trusted_data_agent/components/__init__.py` | 21 | Package init, exports `get_component_manager` |
| `src/trusted_data_agent/components/base.py` | 219 | `RenderTarget`, `ComponentRenderPayload`, `BaseComponentHandler`, `StructuralHandler` |
| `src/trusted_data_agent/components/models.py` | 206 | `ComponentDefinition` dataclass |
| `src/trusted_data_agent/components/manager.py` | ~620 | `ComponentManager` singleton (discovery, registry, hot-reload, LangChain tool factory) |
| `src/trusted_data_agent/components/settings.py` | 142 | Admin governance predicates |
| `src/trusted_data_agent/components/utils.py` | 63 | Shared utilities: `generate_component_html()`, `extract_component_payload()` |
| `components/builtin/chart/manifest.json` | 71 | Chart component manifest |
| `components/builtin/chart/handler.py` | 259 | `ChartComponentHandler` (data normalization + G2Plot spec) |
| `components/builtin/chart/renderer.js` | 41 | `renderChart()` (G2Plot instantiation) |
| `components/builtin/chart/instructions.json` | — | Intensity-keyed LLM instructions |
| `components/builtin/chart/guidelines.txt` | — | G2Plot guidelines (placeholder substitution) |
| `components/schemas/component_manifest_v1.schema.json` | 185 | JSON Schema for manifest validation |
| `schema/18_components.sql` | 30 | `installed_components` table (profile config is on profile JSON dict) |
| `schema/19_component_settings.sql` | 29 | `component_settings` table |
| `static/js/componentRenderers.js` | 158 | `ComponentRendererRegistry` (renderer map, CDN loading) |
| `static/js/subWindowManager.js` | 221 | Sub-window lifecycle (create, update, close, state) |
| `static/js/handlers/componentHandler.js` | 193 | Components Configuration tab UI |

### Modified Files (Integration Points)

| File | Lines Modified | Change |
|------|---------------|--------|
| `src/trusted_data_agent/llm/handler.py` | 429-554 | Component instructions pipeline with profile_config resolution via config_manager |
| `src/trusted_data_agent/mcp_adapter/adapter.py` | 330-437, 1691-1712 | System tools in `CLIENT_SIDE_TOOLS` (TDA_Charting removed); route component tools through `ComponentManager.get_handler()` |
| `src/trusted_data_agent/core/configuration_service.py` | ~240 | Inject "Component Tools" category into `APP_STATE['structured_tools']` for planner visibility |
| `src/trusted_data_agent/agent/executor.py` | ~1398, ~1785, ~2441, ~3072, ~3622, ~3838 | Component tool merge; auto-upgrade llm_only/rag_focused paths; HTML generation via `generate_component_html()` |
| `src/trusted_data_agent/agent/execution_service.py` | ~854 | Genie component HTML generation via `generate_component_html()`; session name token persistence |
| `src/trusted_data_agent/agent/conversation_agent.py` | ~617 | Component payload extraction via `extract_component_payload()` |
| `src/trusted_data_agent/agent/genie_coordinator.py` | ~530, ~791, ~799 | Merge component tools; emit `genie_component_invoked`/`completed` events; payload extraction via `extract_component_payload()` |
| `src/trusted_data_agent/agent/phase_executor.py` | 1066-1156 | Component fast-path for deterministic handlers |
| `src/trusted_data_agent/llm/langchain_adapter.py` | ~508 | Removed `TDA_*` auto-include filter (component tools no longer flow through MCP path) |
| `src/trusted_data_agent/api/rest_routes.py` | 11530-11672 | Five component REST endpoints |
| `src/trusted_data_agent/api/admin_routes.py` | 2609-2690 | Two admin governance endpoints |
| `src/trusted_data_agent/auth/database.py` | 842-960 | Component table creation in bootstrap |
| `static/js/ui.js` | 10, 1361-1377 | `[data-component-id]` rendering + legacy fallback |
| `static/js/eventHandlers.js` | 25-26, 1271-1305, ~1325 | `component_render` SSE event handler; `genie_component_invoked`/`completed` routing and title generation |
| `static/js/handlers/configurationHandler.js` | — | Component toggle section in profile modal (populate, restore, collect on save) |
| `static/js/adminManager.js` | 2835-2942 | Component Management section in Features panel |
| `templates/index.html` | — | Components tab, sub-window container, `#component-config-section` in profile modal |
| `tda_config.json` | — | `component_settings` block + `componentConfig` on default profiles |
| `MASTER_SYSTEM_PROMPT.txt` | — | `{component_instructions_section}` placeholder |
