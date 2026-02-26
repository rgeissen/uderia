# Canvas Component Architecture: Interactive Code & Document Workspace

> Modular capability-plugin workspace providing CodeMirror 6 editing, live preview, version tracking, diff view, inline AI modification, split-screen mode, MCP execution bridge, RAG-aware generation, and template gallery — all rendered from a single `TDA_Canvas` tool call.

## Overview

The Canvas component (`TDA_Canvas`) is a feature-rich interactive workspace that transforms LLM-generated code and documents into an editable, previewable, version-tracked environment. Unlike competitor implementations (Claude Artifacts, Gemini Canvas, ChatGPT Canvas), the Uderia Canvas uses a **modular capability plugin architecture** where each feature — editing, preview, diff, execution — is a self-contained plugin that can be added, removed, or replaced independently.

The canvas operates as a deterministic component: the backend handler passes content through without LLM transformation, while the frontend renderer orchestrates 11 registered capabilities and 4 execution connectors to deliver the full interactive experience.

---

## Table of Contents

- [File Structure](#file-structure)
- [System Architecture](#system-architecture)
  - [Data Flow](#data-flow)
  - [Capability Plugin System](#capability-plugin-system)
  - [State Management](#state-management)
- [Backend Architecture](#backend-architecture)
  - [Handler](#handler)
  - [Language Detection](#language-detection)
  - [REST API Endpoints](#rest-api-endpoints)
- [Frontend Architecture](#frontend-architecture)
  - [Renderer Core](#renderer-core)
  - [CodeMirror 6 Integration](#codemirror-6-integration)
  - [Capability Registry](#capability-registry)
- [Capabilities Reference](#capabilities-reference)
  - [execution_bridge — Connector-Aware Execution](#execution_bridge--connector-aware-execution)
  - [credentials — Connector Credential Management](#credentials--connector-credential-management)
  - [sources_badge — RAG Source Attribution](#sources_badge--rag-source-attribution)
  - [template_gallery — Starter Templates](#template_gallery--starter-templates)
  - [toolbar — Copy, Download, Expand, Info](#toolbar--copy-download-expand-info)
  - [code_editor — CodeMirror 6 Editor](#code_editor--codemirror-6-editor)
  - [html_preview — HTML Live Preview with Responsive Viewports](#html_preview--html-live-preview-with-responsive-viewports)
  - [markdown_preview — Markdown Rendering](#markdown_preview--markdown-rendering)
  - [svg_preview — SVG Rendering](#svg_preview--svg-rendering)
  - [diff_view — Side-by-Side Change Tracking](#diff_view--side-by-side-change-tracking)
  - [version_history — Turn-Based Version Management](#version_history--turn-based-version-management)
- [Version Tracking System](#version-tracking-system)
- [Diff Algorithm](#diff-algorithm)
- [Live Coding Animation](#live-coding-animation)
- [Inline AI Selection](#inline-ai-selection)
- [Canvas Split Mode Toggle](#canvas-split-mode-toggle)
- [Split-Screen Mode](#split-screen-mode)
- [Bidirectional Context](#bidirectional-context)
- [Template System](#template-system)
- [Integration Points](#integration-points)
  - [Profile Integration](#profile-integration)
  - [Fast-Path Execution](#fast-path-execution)
  - [Component Discovery](#component-discovery)
  - [SSE Event Pipeline](#sse-event-pipeline)
- [Security Considerations](#security-considerations)
- [Performance Characteristics](#performance-characteristics)
- [Extensibility](#extensibility)
- [File Reference](#file-reference)

---

## File Structure

```
components/builtin/canvas/
├── manifest.json           # Component metadata, tool definition, render targets
├── handler.py              # CanvasComponentHandler — deterministic pass-through
├── renderer.js             # Capability + connector-based renderer (~4600 lines)
├── instructions.json       # Intensity-keyed LLM guidance (none/medium/heavy)
├── templates.json          # 12 starter templates for template gallery
└── connectors/             # Backend execution connectors (Python)
    ├── __init__.py         # Connector registry — get_connector(), list_connectors()
    ├── base.py             # BaseCanvasConnector ABC, ExecutionResult, ConnectionTestResult
    └── sql.py              # SQLNativeConnector (PostgreSQL, MySQL, SQLite, Teradata)
```

---

## System Architecture

### Data Flow

```
LLM calls TDA_Canvas(content, language, title, sources?)
         │
         ▼
CanvasComponentHandler.process()
  → Validates/normalizes language
  → Computes metadata (line_count, previewable)
  → Returns ComponentRenderPayload(spec={...})
         │
         ▼
Execution path routes payload:
  tool_enabled  → phase_executor fast-path (skip tactical LLM)
  llm_only      → LangChain StructuredTool via agent
  rag_focused   → auto-upgrade to agent after retrieval
  genie         → coordinator tool merge
         │
         ▼
generate_component_html() embeds:
  <div data-component-id="canvas" data-spec='{...}'></div>
         │
         ▼
ui.js scans [data-component-id] → renderComponent('canvas', ...)
         │
         ▼
renderCanvas(containerId, payload):
  1. Inject CSS (once)
  2. Parse spec, record version
  3. Build canvas state object
  4. Build DOM (header, tab bar, toolbar, body)
  5. Filter capabilities for this language
  6. Initialize all active capabilities
  7. Create tab buttons and panels
  8. Render toolbar capabilities
  9. Activate default tab (code_editor)
  10. Return canvasState
```

### Capability Plugin System

Each capability implements a standard contract:

```javascript
{
    id: string,                    // Unique identifier (e.g., 'code_editor')
    label: string,                 // Tab/button text
    type: 'tab' | 'toolbar',      // Where it renders
    languages: string[],           // Which languages activate it ('*' = all)
    init(canvasState),             // Called during canvas creation
    render(panel, content, language, canvasState),  // Render into container
    destroy(),                     // Cleanup
    getState?(canvasState),        // Return current state (optional)
    refresh?(panel, content, language, canvasState),  // Refresh on tab switch (optional)
    shouldCreateTab?(canvasState), // Gate whether tab appears (optional)
}
```

Capabilities are registered via `registerCapability(cap)` and stored in the module-level `_capabilities` array. During `renderCanvas()`, capabilities are filtered by language match and partitioned by type:

- **Tab capabilities**: Create tab buttons in the header tab bar and corresponding panels in the body
- **Toolbar capabilities**: Render buttons/widgets into the header toolbar area

### State Management

The `canvasState` object is the central data contract shared across all capabilities:

```javascript
canvasState = {
    // Content
    content: string,           // Original content from backend
    language: string,          // Normalized language identifier
    title: string,             // Canvas title (default: 'Canvas')
    sources: string | null,    // RAG source documents (comma-separated)

    // Metadata
    previewable: boolean,      // Whether language supports preview (html, svg, markdown)
    lineCount: number,         // Line count
    fileExtension: string,     // Download extension (e.g., '.py')

    // DOM references
    container: HTMLElement,    // Root container
    _tabBar: HTMLElement,      // Tab bar container
    _toolbar: HTMLElement,     // Toolbar container
    _body: HTMLElement,        // Body container
    _panels: Object,          // Map of tabId → panel element

    // Editor
    activeTab: string,         // Currently active tab ID
    _editorView: EditorView,   // CodeMirror 6 instance (set by code_editor)

    // Version state
    versions: Array,           // All versions from _canvasVersions store
    previousContent: string,   // Content of previous version (for diff)
    versionNumber: number,     // Current version number

    // Inline AI
    _inlineAIBtn: HTMLElement,    // Floating "Ask AI" button
    _inlineAIPrompt: HTMLElement, // Prompt input container

    // Execution bridge
    _runBtn: HTMLElement,         // Run button reference
    _activeConnector: Object,     // Resolved connector for current language
    _activeConnectionId: string,  // Selected named connection ID (SQL only, null = MCP bridge)
    _connections: Array,          // Cached list of saved connections

    // Methods
    getContent(): string,      // Returns live content from CM6 editor
}
```

---

## Backend Architecture

### Handler

**File:** `components/builtin/canvas/handler.py`

The `CanvasComponentHandler` extends `BaseComponentHandler` with these key properties:

| Property | Value | Purpose |
|----------|-------|---------|
| `component_id` | `"canvas"` | Unique component identifier |
| `tool_name` | `"TDA_Canvas"` | LLM tool invocation name |
| `is_deterministic` | `True` | Bypasses tactical LLM in tool_enabled profiles |

The `process()` method performs minimal transformation:
1. Extract `content`, `language`, `title`, `sources` from arguments
2. Normalize language (lowercase, strip whitespace)
3. If language is unknown, attempt heuristic detection via `_detect_language()`
4. Compute metadata: `previewable` flag, `line_count`, `file_extension`
5. Return `ComponentRenderPayload` with spec dict

The handler is intentionally thin — all rendering logic lives in the frontend renderer.

### Language Detection

When the LLM provides an unrecognized language value, the handler falls back to heuristic detection:

| Heuristic | Detection |
|-----------|-----------|
| HTML | Starts with `<!DOCTYPE` or `<html`, or contains `<head` in first 200 chars |
| SVG | Starts with `<svg` |
| Mermaid | Starts with `graph ` or `sequenceDiagram` |
| Python | Contains `def ` in first 500 chars or `import ` in first 200 |
| SQL | Contains `SELECT `, `CREATE TABLE`, or `INSERT INTO` in first 300 chars (case-insensitive) |
| JSON | Starts with `{` and ends with `}` |
| Markdown | Starts with `# ` or contains `\n## ` |
| Default | Falls back to `html` if no heuristic matches |

**Supported languages:** html, css, javascript, python, sql, markdown, json, svg, mermaid

### REST API Endpoints

Three canvas-specific REST endpoints exist in `rest_routes.py`:

#### POST /v1/canvas/inline-ai

Lightweight LLM call for inline code modification. Does not use the planner/executor — calls `call_llm_api()` directly with `disabled_history=True`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `selected_code` | string | Yes | Code selected by user |
| `instruction` | string | Yes | Modification instruction |
| `full_content` | string | Yes | Full file content for context |
| `language` | string | Yes | Content language |

**Response:** `{ status, modified_code, input_tokens, output_tokens }`

#### POST /v1/canvas/execute

Execute SQL via MCP server connection. Currently SQL-only — returns 400 for other languages.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `code` | string | Yes | SQL query to execute |
| `language` | string | Yes | Must be `"sql"` |
| `session_id` | string | No | Session ID for MCP adapter resolution |

**Response:** `{ status, result, row_count, execution_time_ms }`

**Error responses:** 400 (unsupported language, SQL error), 401 (auth required), 503 (MCP not connected)

#### GET /v1/canvas/templates

Serve starter templates from `templates.json`. No authentication required.

**Response:** `{ status, templates: [...] }`

---

## Frontend Architecture

### Renderer Core

**File:** `components/builtin/canvas/renderer.js` (~2400 lines)

The renderer is a single ES module exporting three functions:

| Export | Purpose |
|--------|---------|
| `renderCanvas(containerId, payload)` | Main entry point — routes to split-panel or inline mode based on `window.__canvasSplitMode` |
| `getOpenCanvasState()` | Returns current split-panel canvas state for bidirectional context |
| `closeSplitPanel()` | Close the split-screen panel and clear bidirectional context |

The module self-contains all CSS (injected once via `injectStyles()`), all 10 capabilities, the diff algorithm, live animation engine, inline AI functions, split-screen management, version tracking, and split-mode routing logic.

### CodeMirror 6 Integration

CodeMirror 6 is loaded lazily via dynamic `import()` from `esm.sh` CDN. We import from **individual `@codemirror/*` sub-packages** (not the `codemirror` meta-package, which esm.sh serves as a UMD bundle that breaks named ESM exports).

```javascript
// Core packages (cached in _cmCache singleton):
@codemirror/view@6        → EditorView, lineNumbers, keymap, drawSelection, etc.
@codemirror/state@6       → EditorState, Compartment
@codemirror/commands@6    → defaultKeymap, history, historyKeymap
@codemirror/language@6    → syntaxHighlighting, bracketMatching, foldGutter, etc.
@codemirror/search@6      → searchKeymap, highlightSelectionMatches
@codemirror/autocomplete@6 → autocompletion, closeBrackets, completionKeymap
@codemirror/lint@6        → lintKeymap

// Language extensions:
@codemirror/lang-html@6   → html()
@codemirror/lang-javascript@6 → javascript()
@codemirror/lang-python@6 → python()
@codemirror/lang-sql@6    → sql()
@codemirror/lang-json@6   → json()
@codemirror/lang-css@6    → css()
@codemirror/lang-markdown@6 → markdown()

// Theme (chrome only — bg, cursor, selection, gutters):
@codemirror/theme-one-dark@6 → oneDarkTheme

// Syntax highlighting (custom "Oceanic" palette):
@lezer/highlight@1           → HighlightStyle, tags
```

All 16 modules are loaded in parallel via `Promise.all()`. The `basicSetup` extension array is **constructed manually** from the imported sub-package pieces (mirroring the official `codemirror/src/codemirror.ts` source) rather than imported from the meta-package. This avoids the UMD re-export issue on esm.sh.

**Syntax Color Palette ("Oceanic"):** We use `oneDarkTheme` for editor chrome (background, cursor, selection, gutters) but replace oneDark's red-heavy syntax highlighting with a custom `HighlightStyle` that uses blues, teals, and greens:

| Token | Color | Name |
|-------|-------|------|
| Keywords | `#c792ea` | Lavender |
| Names/variables | `#d6deeb` | Light slate |
| Properties | `#80cbc4` | Teal |
| Functions | `#82aaff` | Periwinkle |
| Strings | `#c3e88d` | Lime green |
| Numbers/types | `#ffcb6b` | Gold |
| Operators | `#89ddff` | Ice blue |
| Comments | `#637777` | Muted teal (italic) |
| Booleans/atoms | `#f78c6c` | Soft coral |

The Prism.js fallback uses matching token color overrides scoped to `.canvas-fallback-code .token.*` so both renderers look consistent.

The `_cmLoadPromise` singleton prevents duplicate loading attempts. If loading fails (network issue), the renderer falls back to Prism.js highlighting in a read-only `<pre><code>` block.

**Language extension mapping:**

| Language | CodeMirror Extension |
|----------|---------------------|
| html, svg | `langHtml()` |
| css | `langCss()` |
| javascript | `langJs()` |
| python | `langPy()` |
| sql | `langSql()` |
| json | `langJson()` |
| markdown, mermaid | `langMd()` |

### Capability Registry

Capabilities are registered in this exact order (which determines toolbar button order and tab order):

| # | ID | Type | Languages | Description |
|---|-----|------|-----------|-------------|
| 1 | `code_editor` | tab | `*` | CodeMirror 6 editor with live animation |
| 2 | `html_preview` | tab | `html` | Sandboxed iframe with responsive viewports |
| 3 | `markdown_preview` | tab | `markdown` | Lightweight markdown-to-HTML renderer |
| 4 | `svg_preview` | tab | `svg` | Sanitized inline SVG rendering |
| 5 | `diff_view` | tab | `*` | LCS-based side-by-side diff (conditional) |
| 6 | `credentials` | tab | `*` | Dynamic credentials form (conditional — only when connector has credentialSchema) |
| 7 | `version_history` | toolbar | `*` | Version dropdown with restore (conditional) |
| 8 | `execution_bridge` | toolbar | `*` | Connector-aware "Run" button for any executable language |
| 9 | `sources_badge` | toolbar | `*` | RAG knowledge source dropdown |
| 10 | `template_gallery` | toolbar | `*` | Starter template gallery modal |
| 11 | `toolbar` | toolbar | `*` | Copy, Download, Expand, info badge |

### Connector Registry

Execution connectors handle code execution for specific languages. Registered in this order:

| # | ID | Languages | Backend? | Named Connections | Description |
|---|-----|-----------|----------|-------------------|-------------|
| 1 | `javascript_worker` | `javascript` | No | None | Web Worker sandbox with console capture, 10s timeout |
| 2 | `html_sandbox` | `html`, `css` | No | None | HTML: Preview tab switch. CSS: Iframe with sample elements |
| 3 | `python_pyodide` | `python` | No | None | Pyodide WASM (~10MB lazy-load), persistent session |
| 4 | `sql_native` | `sql` | Yes | Driver, host, port, database, user, password, SSL, JDBC fields | Native DB drivers (asyncpg/aiomysql/aiosqlite/teradatasql/JayDeBeApi). Uses named connections selected via toolbar picker. Falls back to MCP bridge when no connection selected |

---

## Capabilities Reference

### execution_bridge — Connector-Aware Execution

**Type:** toolbar | **Languages:** `*` (all — guarded by connector availability)

Adds a green "▶ Run" button as the first toolbar item for any language that has a registered connector. For SQL canvases, a **connection picker** `<select>` dropdown appears next to the Run button, listing "MCP Bridge (default)" plus all saved named connections. The button's tooltip shows which connector will handle execution. Clicking it:
1. Reads current editor content via `state.getContent()`
2. Calls `executeViaConnector(state)` which dispatches to the active connector
3. The connector returns `{ result, error, stats: { rowCount, timeMs } }`
4. Results displayed in a console panel below the canvas body

**Connector dispatch flow:**
```
Run button click → executeViaConnector(state)
                      ↓
              state._activeConnector || getConnectorForLanguage(language)
                      ↓
              connector.execute(code, null, state)
                      ↓
              if state._activeConnectionId:
                  POST /v1/canvas/execute { connector_id, connection_id }
                  Backend reads encrypted creds for that connection_id
              else:
                  Legacy MCP bridge (executeSqlViaMcp)
                      ↓
              showConsolePanel(state, result/error, ...)
```

**Per-language execution:**
- **JavaScript**: Web Worker (browser sandbox, 10s timeout, console capture)
- **Python**: Pyodide WASM (lazy-loaded, persistent session, stdout/stderr capture)
- **SQL**: Named connection selected → `POST /v1/canvas/execute` with `connector_id` + `connection_id`; otherwise falls back to MCP bridge
- **HTML**: Switches to Preview tab
- **CSS**: Shows sample elements in iframe with user CSS applied

The console panel (`showConsolePanel()`) shows:
- Header: "Console" label, count badge (rows for SQL, lines for other languages), execution time, close button
- Body: Execution results as preformatted text
- Error state: Red text and "Error" badge

### credentials — Named Connection Manager

**Type:** tab | **Languages:** `*` (conditional — only shows when connector has `credentialSchema`)

Manages **named SQL connections** — multiple saved database connections per user. The tab has two views:

**List View (default):**
- Shows all saved connections as cards with driver icon, name, and connection summary
- Edit/Delete actions per card
- "New Connection" button to open the form

**Form View (edit/create):**
- "← Back" to return to list
- Connection Name field (required)
- Dynamic fields from connector's `credentialSchema` (driver, host, port, database, user, password, SSL)
- `hideWhen` conditional visibility (e.g., hide host/port for SQLite/JDBC)
- `showWhen` conditional visibility (e.g., show JDBC URL/Driver Class/JAR Path only for JDBC driver)
- Test Connection / Save / Delete buttons
- Status indicator

**Supported drivers:** PostgreSQL (asyncpg), MySQL (aiomysql), SQLite (aiosqlite), Teradata (teradatasql), JDBC (JayDeBeApi — requires Java runtime)

**Storage:** Named connections use the existing `encrypt_credentials`/`decrypt_credentials` system with provider key `canvas_conn_{connection_id}`. The connection name is stored inside the encrypted credentials dict.

**REST endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/canvas/connections` | List all saved connections (passwords masked) |
| GET | `/v1/canvas/connections/<connection_id>` | Get single connection (password masked) |
| PUT | `/v1/canvas/connections` | Save connection (create or update, encrypted via Fernet) |
| DELETE | `/v1/canvas/connections/<connection_id>` | Delete connection |
| POST | `/v1/canvas/connections/test` | Test connection (credentials in body, not stored) |

**Connection picker integration:** After save/delete, `_refreshConnectionPicker(state)` updates the toolbar dropdown to reflect the current connection list.

### sources_badge — RAG Source Attribution

**Type:** toolbar | **Languages:** `*` (all)

Only renders when `canvasState.sources` is non-null. Shows a purple "📚 Sources" button that toggles a dropdown listing the knowledge documents that informed the canvas content. Sources are passed as a comma-separated string in the `TDA_Canvas` tool call's `sources` argument.

The LLM is instructed (via `instructions.json`) to include sources when generating content based on knowledge repository documents.

### template_gallery — Starter Templates

**Type:** toolbar | **Languages:** `*` (all)

Adds a "Templates" button that opens a full-screen modal gallery:
1. Fetches templates from `GET /v1/canvas/templates` (cached in module-level `_templateCache`)
2. Groups templates by category (HTML, Python, SQL, Markdown, CSS, JavaScript)
3. Renders category tabs and a 2-column card grid
4. Clicking a card calls `applyTemplate()`:
   - Records current content as a version (for undo)
   - Replaces editor content via `restoreVersion()`
   - Closes modal

Modal dismissal: Escape key, close button, or overlay click.

**12 included templates:**

| ID | Category | Description |
|----|----------|-------------|
| html-landing | HTML | Responsive landing page with hero, features, CTA |
| html-dashboard | HTML | Admin dashboard with sidebar, stats cards, data table |
| html-form | HTML | Styled contact form with validation |
| python-cli | Python | argparse CLI with subcommands and logging |
| python-flask | Python | Minimal Flask REST API with CRUD endpoints |
| python-data | Python | Pandas data loading, cleaning, and visualization |
| sql-query | SQL | Common patterns: JOIN, GROUP BY, subqueries, window functions |
| sql-migration | SQL | Migration with CREATE, ALTER, and rollback |
| markdown-report | Markdown | Structured report with sections, tables, conclusions |
| markdown-docs | Markdown | API documentation with endpoints, parameters, examples |
| css-reset | CSS | Modern reset with custom properties and utility classes |
| js-module | JavaScript | ES module with class, async/await, error handling |

### toolbar — Copy, Download, Expand, Info

**Type:** toolbar | **Languages:** `*` (all)

Renders four toolbar elements:
- **Copy**: `navigator.clipboard.writeText()` with "Copied!" flash feedback
- **Download**: `Blob` + `URL.createObjectURL()` + dynamic `<a>` element with language-appropriate extension
- **Expand**: Opens split-screen panel via `popOutCanvas(state)` (visible when `#canvas-split-panel` exists in DOM)
- **Info badge**: `"{lineCount} lines · {language}"` pill

### code_editor — CodeMirror 6 Editor

**Type:** tab | **Languages:** `*` (all)

The primary capability. During `init()`, loads CodeMirror 6 asynchronously. During `render()`:

1. Determines if live coding animation is active (`window.__canvasLiveMode`)
2. Creates `EditorView` with extensions: `...basicSetup` (manually constructed array), theme chrome and syntax colors wrapped in `Compartment`s for live hot-swap (see Theme Awareness), language extension, line wrapping — all filtered via `.filter(Boolean)` for safety
3. In live mode: starts with empty document, read-only compartment, triggers `animateCodeInsertion()`
4. In normal mode: starts with full content, attaches inline AI selection listener
5. Falls back to Prism.js `<pre><code>` if CodeMirror fails to load

**Inline AI integration**: An `EditorView.updateListener` detects non-empty text selections and shows a floating "Ask AI" button. This listener is disabled during live animation (`!isLive` guard).

### html_preview — HTML Live Preview with Responsive Viewports

**Type:** tab | **Languages:** `html`

Renders HTML content in a sandboxed `<iframe srcdoc>` with `sandbox="allow-scripts"`. Includes a responsive viewport toggle bar with three presets:

| Viewport | Width | Height | Scaling |
|----------|-------|--------|---------|
| Desktop | 100% | 500px | None |
| Tablet | 768px | 1024px | `transform: scale()` to fit container |
| Mobile | 375px | 667px | `transform: scale()` to fit container |

The `refresh()` method re-renders the preview with the latest editor content when the user switches back to the Preview tab.

### markdown_preview — Markdown Rendering

**Type:** tab | **Languages:** `markdown`

Uses a built-in lightweight markdown-to-HTML renderer (`renderMarkdownToHtml()`) — no external dependencies. Supports:

- Headers (H1-H6)
- Bold, italic, bold+italic
- Inline code and fenced code blocks
- Links (opens in new tab)
- Blockquotes
- Unordered and ordered lists
- Horizontal rules
- Tables (with header row)
- Paragraphs

### svg_preview — SVG Rendering

**Type:** tab | **Languages:** `svg`

Renders SVG content as inline HTML after sanitization:
- Strips all `<script>` tags
- Removes all `on*` event handler attributes

Displayed in a centered white-background container with automatic scaling.

### diff_view — Side-by-Side Change Tracking

**Type:** tab | **Languages:** `*` (all) | **Conditional**: only appears when `previousContent` exists

Uses the LCS (Longest Common Subsequence) diff algorithm to compute line-by-line differences between the previous and current version. Renders a side-by-side view:

- **Left panel**: Previous version with red highlighting for removed lines
- **Right panel**: Current version with green highlighting for added lines
- **Header**: `+N added / −M removed` summary with version numbers
- **Synchronized scrolling**: Both panels scroll together

### version_history — Turn-Based Version Management

**Type:** toolbar | **Languages:** `*` (all) | **Conditional**: only appears when 2+ versions exist

Renders a "History" button with a version count badge. Clicking opens a dropdown listing all versions from newest to oldest, showing:
- Version number and current marker
- Turn index and timestamp
- "Restore" button for historical versions

Clicking a historical version previews it in the code editor. The "Restore" button replaces the editor content via a CodeMirror 6 transaction.

---

## Version Tracking System

Versions are stored in a module-level `Map` (`_canvasVersions`) keyed by normalized canvas title:

```
_canvasVersions: Map<string, Array<{
    content: string,
    language: string,
    timestamp: number,    // Date.now()
    turnIndex: number,    // _globalTurnCounter (monotonically increasing)
}>>
```

**`recordVersion(title, content, language)`**:
1. Normalizes title to lowercase key
2. Checks if latest version has identical content (deduplication)
3. Increments `_globalTurnCounter`
4. Appends new version entry
5. Returns `{ versions, previousContent, versionNumber }`

**Lifecycle**: Versions persist in memory across renders within the same page session. They are lost on page reload (not persisted to server). The global turn counter ensures consistent ordering across multiple canvases.

**`restoreVersion(state, content)`**: Replaces CodeMirror editor content via a single transaction (supports Ctrl+Z undo).

**`previewVersion(state, content, versionNum)`**: Same as restore, plus switches to the Code tab.

---

## Diff Algorithm

The `computeLineDiff(oldText, newText)` function implements a line-based LCS (Longest Common Subsequence) algorithm:

1. **Split** both texts into line arrays
2. **Build LCS table**: Dynamic programming matrix (`Uint16Array` for memory efficiency)
3. **Backtrack** to produce diff entries:
   - `equal`: Line exists in both versions (with old and new line numbers)
   - `added`: Line exists only in new version (green)
   - `removed`: Line exists only in old version (red)

**`diffStats(diff)`**: Counts added and removed lines for the summary header.

**Complexity**: O(m × n) time and space where m and n are line counts. The `Uint16Array` optimization limits maximum comparable file length to 65,535 lines.

---

## Live Coding Animation

**Problem**: Canvas content arrives complete in the `final_answer` SSE event. Competitors stream text token-by-token with no syntax highlighting during generation.

**Solution**: Simulated streaming using CodeMirror 6 transactions to insert content line-by-line after the full content arrives.

**Advantages over competitors:**

| Aspect | Claude Artifacts | Gemini Canvas | Uderia Canvas |
|--------|:---:|:---:|:---:|
| Syntax highlighting during streaming | No | No | **Yes** |
| Line numbers during streaming | No | No | **Yes** |
| Skip animation button | No | No | **Yes** |
| Progress indicator | No | Partial | **Yes** |
| Auto-preview after completion | Yes | Yes | **Yes** |

### Animation Flow

```
window.__canvasLiveMode = true  (set by eventHandlers.js)
         │
         ▼
renderCanvas() detects live mode
         │
         ▼
CodeEditor creates empty doc with read-only compartment
         │
         ▼
animateCodeInsertion(view, fullContent, canvasState, compartment, cm)
  │
  ├── Split content into lines
  ├── Calculate adaptive speed:
  │   ├── ≤30 lines: 1 line/80ms (~2.4s total)
  │   ├── 31-100 lines: 1 line/adaptive ms (~3s total)
  │   └── 100+ lines: N lines/batch/20ms (~2s total)
  │
  ├── Show progress bar with Skip button
  │
  ├── For each batch:
  │   ├── CM6 transaction: insert at doc end
  │   ├── Update progress: "42 / 128 lines"
  │   ├── Auto-scroll (unless user has scrolled up)
  │   └── await delay
  │
  └── On complete:
      ├── Remove progress bar
      ├── Reconfigure read-only compartment to writable
      └── If HTML → auto-switch to Preview tab (600ms delay)
```

### Cross-Module Communication

The `window.__canvasLiveMode` global flag solves a module isolation problem:
- `eventHandlers.js` imports from `../components/builtin/canvas/renderer.js` (filesystem path)
- `componentRenderers.js` imports from `/api/v1/components/canvas/renderer` (API-served path)
- The browser treats these as **separate module instances** with independent state
- A module-level flag set by one would be invisible to the other
- `window.__canvasLiveMode` is globally visible to both

The flag is set to `true` before `UI.addMessage()` in `eventHandlers.js` and cleared by `renderCanvas()` after consumption, with a 100ms `setTimeout` fallback for responses without canvas content.

---

## Inline AI Selection

**Purpose**: Select text in the editor → floating "Ask AI" button → type instruction → LLM modifies just that selection → result replaces selection atomically.

### Flow

```
User selects text in CodeMirror 6
         │
         ▼
EditorView.updateListener detects non-empty selection
  → showInlineAIButton(canvasState, view, coords)
  → Floating blue "Ask AI" button near selection end
         │
         ▼
User clicks → showInlineAIPrompt()
  → Input (260px) + "Go" button + cancel (✕)
  → Enter key submits, Escape cancels
         │
         ▼
executeInlineAI(canvasState, view, from, to, selectedText, instruction)
  → Loading state (disabled input, "..." button)
  → POST /v1/canvas/inline-ai
  → Body: { selected_code, instruction, full_content, language }
         │
         ▼
Backend: Direct call_llm_api(disabled_history=True)
  → System prompt: "Replace ONLY selected code, output ONLY replacement"
  → Returns { modified_code, input_tokens, output_tokens }
         │
         ▼
CM6 dispatch({ changes: { from, to, insert: modified_code } })
  → Single transaction = Ctrl+Z undoes atomically
  → showInlineAITokenBadge() (fades after 3s)
```

**Safeguards**:
- Selection listener disabled during live animation (`!isLive` guard)
- `mousedown` on prompt container prevents selection loss via `e.preventDefault()`
- Error handling: shows error in input placeholder, auto-clears after 3s
- Prism.js fallback mode: no inline AI (CM6-only feature)

---

## Canvas Split Mode Toggle

A `</>` toggle button in the conversation header controls how canvases render. Inspired by Claude Artifacts (inline card → side panel), ChatGPT Canvas (persistent side panel), and Gemini Canvas (explicit user toggle).

### Toggle Button

**Location:** `#canvas-mode-toggle` in `templates/index.html`, placed next to `#window-menu-button` in the header right section.

**Styling:** Defined in `static/css/main.css` as `#canvas-mode-toggle` with `[data-theme="light"]` variant. Active state uses the `.canvas-toggle-active` CSS class (toggled by `applyCanvasToggleStyle()`) which provides visible indicators in both dark mode (white glow/ring) and light mode (slate background/ring).

**State:** Persisted in `localStorage('canvasSplitMode')` and exposed via `window.__canvasSplitMode` (set by `setCanvasSplitMode()` in `state.js`).

### Two Rendering Modes

`renderCanvas()` reads `window.__canvasSplitMode` and routes accordingly:

#### Split Mode ON

1. **Inline:** `renderInlineCard()` — compact card with title, language badge, 3-line code preview, "View in Canvas →" link
2. **Split Panel:** `autoPopOutCanvas()` → `renderCanvasFull()` — full canvas with all capabilities (editable CM6, tabs, toolbar, inline AI, console, version history, diff)

If the panel is already open, new canvases **replace** the current content. Old inline card badges update accordingly.

#### Split Mode OFF

`renderInlineCompact()` — limited inline canvas with:
- Read-only CodeMirror (`EditorView.editable.of(false)` + `EditorState.readOnly.of(true)`)
- Copy button only
- 300px max-height with "Show more" expand
- No tabs, toolbar, inline AI, run, sources, version history, or diff

### Feature Comparison

| Feature | Split Panel | Inline Compact |
|---------|-------------|---------------|
| CodeMirror editor | Editable | Read-only |
| Tab bar (Code/Preview/Diff) | Yes | No |
| Copy / Download / Expand | Yes | Copy only |
| Inline AI editing | Yes | No |
| Run (SQL execution) | Yes | No |
| Sources / Version history | Yes | No |
| Bidirectional LLM context | Yes | No |
| Max height | Full panel | ~300px |

### Rendering Architecture

```
renderCanvas(containerId, payload)
    │
    ├── containerId starts with 'canvas-split-render-'?
    │   └── renderCanvasFull()  (internal, full capabilities)
    │
    ├── window.__canvasSplitMode === true?
    │   ├── renderInlineCard()       → compact card in chat
    │   └── autoPopOutCanvas()       → full canvas in split panel
    │
    └── else (split OFF)
        └── renderInlineCompact()    → read-only inline viewer
```

### State Flow

```
Toggle ON  → setCanvasSplitMode(true) → localStorage + window.__canvasSplitMode
Toggle OFF → setCanvasSplitMode(false) → closeSplitPanel() via dynamic import
```

### Files

- `templates/index.html` — Toggle button HTML
- `static/js/domElements.js` — `canvasModeToggle` reference
- `static/js/state.js` — `canvasSplitMode` state + `setCanvasSplitMode()`
- `static/js/eventHandlers.js` — Toggle initialization, `applyCanvasToggleStyle()`
- `components/builtin/canvas/renderer.js` — `renderInlineCard()`, `renderInlineCompact()`, `autoPopOutCanvas()`, `renderCanvasFull()`, routing in `renderCanvas()`

---

## Split-Screen Mode

**Design decision**: Originally planned as floating sub-windows (using `subWindowManager.js`), redesigned per user feedback to a side-by-side split-screen layout matching the Gemini Canvas / Claude Artifacts pattern.

### HTML Structure

```
#main-content
  └── div.flex-1.flex-col.min-h-0
       ├── #chat-canvas-split (flex-row wrapper)
       │    ├── main#chat-container (flex-1, scrollable chat)
       │    └── aside#canvas-split-panel (hidden by default, 50% when open)
       │         ├── .canvas-split-header (title + close/collapse buttons)
       │         └── #canvas-split-content (render target)
       └── footer#chat-footer
```

### Behavior

**Opening** — Two entry points:
- `popOutCanvas(state)` — Manual expand from toolbar button (takes canvasState)
- `autoPopOutCanvas(spec)` — Automatic from split mode toggle (takes raw spec, clears old card badges)

Both follow the same flow:
1. Update split panel title
2. Clear previous content
3. Create render target inside `#canvas-split-content`
4. Show panel with CSS transition (`width: 0` → `width: 50%`, `min-width: 320px`)
5. Call `renderCanvasFull()` to get full capability experience in the panel
6. Store reference in `_activeSplitCanvasState` for bidirectional context

**Closing** (`closeSplitPanel()`):
1. Clear `_activeSplitCanvasState` (stops bidirectional context)
2. Remove `canvas-split--open` class (triggers CSS transition)
3. On `transitionend`: hide panel, clear content DOM

**Split panel overrides**:
- No border/radius on `.canvas-container`
- Unlimited `max-height` on `.canvas-body` and `.cm-editor`

---

## Bidirectional Context

When a canvas is open in the split panel, user edits flow back to the LLM on every subsequent query.

### Data Flow

```
User edits code in split-panel CodeMirror
         │
         ▼
getOpenCanvasState()  [renderer.js]
  → Reads _activeSplitCanvasState._splitState.getContent()
  → Compares with originalContent to detect modifications
  → Returns { title, language, content, modified }
         │
         ▼
handleChatSubmit()  [eventHandlers.js]
  → canvas_context = getOpenCanvasState()
  → Included in POST /ask_stream body
         │
         ▼
routes.py / rest_routes.py
  → canvas_context = data.get("canvas_context")
  → Passed to execution_service.run_agent_execution()
         │
         ▼
execution_service.py → PlanExecutor(canvas_context=...)
         │
         ▼
PlanExecutor._format_canvas_context()  [executor.py]
  → Formats as structured text block:
    "# Open Canvas: {title}
     Language: {language} | Status: Modified/Unchanged
     ```{language}
     {content}
     ```"
         │
         ├── llm_only → prepended to user message
         ├── rag_focused → prepended to synthesis context
         ├── tool_enabled → prepended to strategic planning input
         └── conversation_with_tools → prepended to effective query
```

The `modified` flag tells the LLM whether the user has edited the canvas content, helping it decide whether to reference the canvas state.

### Instructions Guidance

The `instructions.json` (medium and heavy intensity) instructs the LLM:
- When an "Open Canvas" section appears in context, use `TDA_Canvas` with the **same title** to update it
- Always provide complete updated content (not just changed parts)
- The user can see what changed via the built-in diff view

---

## Template System

Templates are stored as static JSON in `components/builtin/canvas/templates.json` and served via `GET /v1/canvas/templates`. Each template has:

```json
{
    "id": "html-landing",
    "name": "Landing Page",
    "category": "HTML",
    "language": "html",
    "description": "Responsive landing page with hero, features, and CTA",
    "content": "<!DOCTYPE html>..."
}
```

Templates contain 30-100 lines of well-commented, production-quality starter code. The template gallery modal groups them by category with filterable tabs and a 2-column card grid.

When a template is applied:
1. Current editor content is recorded as a version (preserving undo capability)
2. Editor content is replaced via `restoreVersion()`
3. The `canvasState.language` is updated to match the template's language

---

## Integration Points

### Profile Integration

Canvas is enabled per-profile via `componentConfig` in `tda_config.json`:

```json
"componentConfig": {
    "canvas": { "enabled": true, "intensity": "medium" }
}
```

**Intensity levels** control LLM instruction aggressiveness:

| Level | Behavior |
|-------|----------|
| `none` | No instructions injected — LLM won't use TDA_Canvas |
| `medium` | Contextual guidance — use canvas for substantial content |
| `heavy` | Aggressive guidance — MUST use canvas for any code/document output |

Profiles without `componentConfig.canvas` get the component at default intensity (`medium`).

### Fast-Path Execution

In `tool_enabled` profiles, the `CanvasComponentHandler.is_deterministic = True` flag triggers the generic deterministic fast-path in `phase_executor.py`:

1. Strategic plan includes `TDA_Canvas` tool call with arguments
2. Phase executor detects deterministic component
3. Constructs `generic_action` from tool name + strategic arguments
4. Emits "Plan Optimization" SSE event
5. Executes via `_execute_action_with_orchestrators()` — bypasses tactical LLM entirely
6. Sets `_component_bypass_handled = True`

This saves one full LLM call (tactical planning) per canvas invocation.

### Component Discovery

The `ComponentManager` (singleton via `get_component_manager()`) auto-discovers the canvas component:

1. Scans `components/builtin/canvas/manifest.json`
2. Loads `CanvasComponentHandler` via `importlib`
3. Creates `StructuredTool` from manifest `tool_definition`
4. Injects intensity-keyed instructions from `instructions.json`
5. Registers renderer endpoint at `/v1/components/canvas/renderer`

No manual registration is needed. Adding the component directory is sufficient.

### SSE Event Pipeline

Canvas content flows through the standard SSE pipeline:
1. Handler returns `ComponentRenderPayload` with `render_target = INLINE`
2. `generate_component_html()` wraps spec in `<div data-component-id="canvas" data-spec='...'>`
3. The div is embedded in the `final_answer` SSE event
4. `ui.js` scans for `[data-component-id]` attributes after rendering
5. `renderComponent('canvas', containerId, spec)` is called from `componentRenderers.js`
6. `renderCanvas()` executes, creating the full interactive workspace

---

## Security Considerations

### HTML Preview Sandboxing

The HTML preview iframe uses `sandbox="allow-scripts"` — scripts can execute within the iframe but cannot:
- Access parent window DOM
- Navigate the parent window
- Open popups
- Submit forms
- Access `localStorage`/cookies of the parent origin

### SVG Sanitization

SVG content is sanitized before inline rendering:
- All `<script>` tags are stripped
- All `on*` event handler attributes are removed

### Inline AI

The inline AI endpoint:
- Requires JWT authentication
- Uses `disabled_history=True` — no conversation history leakage
- Uses `session_id=None` — no session state mutation
- Strips markdown code fences from LLM response

### MCP Execution

The execute endpoint:
- Requires JWT authentication
- Only supports SQL (other languages return 400)
- Uses the session's MCP adapter for SQL execution
- Returns raw result text — no client-side query construction

---

## Performance Characteristics

### Loading

| Operation | Time | Notes |
|-----------|------|-------|
| CSS injection | ~1ms | One-time, cached via `_stylesInjected` flag |
| CodeMirror 6 CDN load | 200-500ms | First load only, cached in `_cmCache` singleton |
| Canvas render | ~5ms | DOM construction + capability initialization |
| Live animation | 2-4s | Adaptive speed based on content length |
| Prism.js fallback | ~2ms | No network dependency |

### Memory

| Component | Footprint | Notes |
|-----------|-----------|-------|
| CodeMirror 6 modules (16 packages) | ~800KB | Loaded once, shared across all canvases |
| Version store | Variable | Proportional to content × versions per canvas |
| LCS diff table | O(m × n) | Created on demand, garbage collected after render |
| Template cache | ~50KB | Cached after first gallery open |

### CDN Dependency

CodeMirror 6 is loaded from `esm.sh` using 16 individual sub-package imports (15 `@codemirror/*` + 1 `@lezer/highlight`). The `codemirror` meta-package is **not used** because esm.sh serves it as a UMD bundle that doesn't expose named ESM exports (`EditorView` and `basicSetup` are both `undefined`). Instead, `basicSetup` is constructed manually from the sub-package exports.

CSP allows `https://esm.sh` in both `script-src` and `connect-src` directives (configured in `main.py`).

If the CDN is unreachable:
- Canvas still renders (Prism.js fallback)
- Editing is disabled (read-only `<pre><code>`)
- Preview, diff, toolbar, templates all work normally
- `_cmLoadPromise` is reset to `null` on failure, allowing retry on next canvas render

### Theme Awareness

The canvas is fully theme-aware across all three themes (legacy, modern, light):

1. **CSS Variables:** All backgrounds, borders, text colors, and hover states use CSS variable wrappers with dark-theme fallbacks — e.g., `var(--bg-secondary, rgba(0,0,0,0.15))`. This ensures the canvas adapts automatically when the theme changes.

2. **Light Theme Overrides:** A `.canvas-light` CSS class (~25 selectors) handles elements that need explicit light-theme treatment — header backgrounds, toolbar borders, template cards, split-panel chrome, etc. A `MutationObserver` on `document.body` watches `data-theme` attribute changes and toggles `.canvas-light` on all canvas elements in real time.

3. **Dual CodeMirror Themes:** Two complete theme sets are loaded:
   - **Dark:** `oneDarkTheme` (editor chrome) + `oceanicStyle` (blue/teal/green syntax palette)
   - **Light:** `oceanicLightTheme` (white bg, slate gutters, blue selection) + `oceanicLightStyle` (rich colors on white: purple keywords, teal properties, blue functions, emerald strings)

4. **Live Theme Hot-Swap:** CodeMirror theme and syntax-highlighting extensions are wrapped in `Compartment`s at creation time. A module-level `_liveEditors` registry tracks all live editor instances. When the theme changes, `reconfigureCmEditors()` iterates the registry and dispatches `compartment.reconfigure()` effects — switching between dark/light themes instantly without recreating editors. Editors are removed from the registry on destroy or when disconnected from the DOM.

---

## Extensibility

### Adding a New Capability

Create a capability object and call `registerCapability()`:

```javascript
registerCapability({
    id: 'my_capability',
    label: 'My Tab',
    type: 'tab',           // or 'toolbar'
    languages: ['python'],  // or ['*'] for all

    init(state) {
        // Called during canvas creation
    },

    render(panel, content, language, state) {
        // Render your UI into the panel
    },

    destroy() {
        // Cleanup
    },
});
```

No changes to CanvasCore, other capabilities, or backend handler are required.

### Adding a New Language

1. Add language to `SUPPORTED_LANGUAGES` set in `handler.py`
2. Add file extension to `EXTENSION_MAP` in `handler.py`
3. Add detection heuristic to `_detect_language()` in `handler.py`
4. Add `@codemirror/lang-*` import to `loadCodeMirror()` `Promise.all()` and add mapping to `getCmLanguageExt()` in `renderer.js`
5. Add preview capability if applicable (e.g., `mermaid_preview`)

### Adding a New Execution Connector

The connector plugin system makes adding new execution languages straightforward:

```javascript
registerConnector({
    id: 'my_connector',
    name: 'My Language',
    languages: ['mylang'],
    requiresBackend: false,    // true = calls /v1/canvas/execute with connector_id
    credentialSchema: null,    // or array of field definitions for Credentials tab

    async execute(code, credentials, state) {
        // Execute code and return normalized result
        return {
            result: 'output text',
            error: null,  // or error message string
            stats: { rowCount: 0, timeMs: 42 },
        };
    },

    // Optional: browser-side connection test
    async testConnection(credentials) {
        return { valid: true, message: 'Connected', server_info: 'v1.0' };
    },
});
```

The `execution_bridge` capability automatically picks up the new connector — no changes to existing code required. If `credentialSchema` is provided, the Credentials tab appears automatically.

For backend connectors, also create a Python connector class extending `BaseCanvasConnector` in `connectors/` and register it in `connectors/__init__.py`.

---

## File Reference

### Canvas Component Files

| File | Lines | Purpose |
|------|-------|---------|
| `components/builtin/canvas/manifest.json` | ~62 | Component metadata, TDA_Canvas tool definition |
| `components/builtin/canvas/handler.py` | ~120 | Deterministic pass-through handler |
| `components/builtin/canvas/renderer.js` | ~4600 | Full frontend: 11 capabilities, 4 connectors, CSS, animation, inline AI, split-screen |
| `components/builtin/canvas/instructions.json` | ~5 | LLM guidance at none/medium/heavy intensity |
| `components/builtin/canvas/templates.json` | ~800 | 12 starter templates |
| `components/builtin/canvas/connectors/__init__.py` | ~30 | Backend connector registry |
| `components/builtin/canvas/connectors/base.py` | ~50 | BaseCanvasConnector ABC, ExecutionResult, ConnectionTestResult |
| `components/builtin/canvas/connectors/sql.py` | ~250 | SQLNativeConnector (PostgreSQL, MySQL, SQLite, Teradata) |
| `schema/20_canvas_connectors.sql` | ~20 | canvas_connector_credentials table |

### Modified Integration Files

| File | Change |
|------|--------|
| `components/component_registry.json` | Canvas entry (active, Code category) |
| `static/js/componentRenderers.js` | Import + register `renderCanvas` |
| `tda_config.json` | Canvas in all 4 profile componentConfigs |
| `src/trusted_data_agent/agent/phase_executor.py` | Generic deterministic fast-path |
| `src/trusted_data_agent/api/rest_routes.py` | Connector-aware execute endpoint + credential CRUD + SQL test |
| `src/trusted_data_agent/auth/database.py` | Bootstrap `canvas_connector_credentials` table |
| `src/trusted_data_agent/main.py` | CSP: added `'wasm-unsafe-eval'` for Pyodide WASM |
| `requirements.txt` | Optional database drivers (asyncpg, aiomysql, aiosqlite, teradatasql) |
| `static/js/eventHandlers.js` | Live mode flag, canvas context collection |
| `src/trusted_data_agent/api/routes.py` | Accept `canvas_context` parameter |
| `src/trusted_data_agent/api/rest_routes.py` | Accept `canvas_context`, 3 canvas endpoints |
| `src/trusted_data_agent/agent/execution_service.py` | Thread `canvas_context` to PlanExecutor |
| `src/trusted_data_agent/agent/executor.py` | Format + inject canvas context for all profiles |
| `src/trusted_data_agent/agent/conversation_agent.py` | Accept canvas context, emit sub_window SSE |
| `src/trusted_data_agent/components/utils.py` | Skip sub_window payloads in HTML generation |
| `templates/index.html` | Split-screen HTML structure |
| `static/js/state.js` | Expose `window.__currentSessionId` |

### Automatic Integration (Zero Changes)

| System | Mechanism |
|--------|-----------|
| ComponentManager discovery | Auto-scans `components/builtin/canvas/manifest.json` |
| Handler loading | `importlib` auto-imports `CanvasComponentHandler` |
| LangChain tool creation | Auto-created `StructuredTool` from manifest args |
| Instruction injection | Auto-injected via `get_instructions_text()` |
| Tool merging (all profiles) | Auto-merged via component tool factories |
| MCP routing | `is_component_tool()` routes to handler |
| DOM rendering | `ui.js` scans `[data-component-id]` → `renderComponent()` |

---

## Competitive Comparison

| Feature | Gemini | Claude | ChatGPT | Uderia Canvas |
|---------|:------:|:------:|:-------:|:------------:|
| Syntax highlighting | Yes | Yes | Yes | **Yes** |
| Live HTML preview | Yes | Yes | Yes | **Yes** |
| Direct code editing | Yes | No | Limited | **Yes** (CM6) |
| Responsive viewport toggle | No | No | No | **Yes** |
| Diff view on LLM updates | No | No | No | **Yes** |
| Version history | No | No | No | **Yes** |
| Inline AI selection | No | No | Limited | **Yes** |
| Live coding animation with highlighting | No | No | No | **Yes** |
| Backend code execution | No | No | No | **Yes** (SQL via MCP) |
| RAG-aware source attribution | No | No | No | **Yes** |
| Template gallery | No | No | No | **Yes** |
| Modular plugin architecture | No | No | No | **Yes** |
| Profile-based intensity control | No | No | No | **Yes** |
| Bidirectional context (edits → LLM) | No | Partial | No | **Yes** |
| Graceful CM6 → Prism fallback | N/A | N/A | N/A | **Yes** |
| Works across 4 profile types | N/A | N/A | N/A | **Yes** |
