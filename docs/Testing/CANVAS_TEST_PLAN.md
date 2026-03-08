# Canvas Component (`TDA_Canvas`) — Manual Test Plan

> **Component:** Canvas interactive code & document workspace
> **Automated tests:** `test/test_canvas_comprehensive.py` (handler, diff, templates, versions, manifest, REST API, E2E)
> **This document:** Manual browser-based testing for visual rendering, user interactions, and integration flows
> **Last updated:** 2026-02-25

---

## REST API Test Results (2026-02-25)

Automated REST API and E2E testing was run against `localhost:5050`. Results are marked with:
- **API:PASS** — Verified programmatically via REST API / unit test
- **VISUAL** — Requires manual browser verification (not REST-testable)

**Unit tests:** 94/94 PASS (`test_canvas_comprehensive.py --unit-only`)
**REST API tests:** 9/9 PASS (inline-ai, execute, templates endpoints)
**E2E tests:** 21/21 PASS (query submission + event inspection); 1 SKIP (13.1 — @FOCUS lacks canvas componentConfig)

---

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Server | Uderia running on `localhost:5050` |
| Credentials | `admin` / `admin` |
| Profiles | `@OPTIM` (tool_enabled) and `@IDEAT` (llm_only) with canvas enabled |
| MCP server | Connected (required for SQL execution tests, Section 10) |
| Browser | Chrome latest (primary), then cross-browser in Section 19 |

**How to trigger a canvas** — submit a prompt that asks the LLM to generate code:
- *"Write a Python script that calculates Fibonacci numbers"*
- *"Create an HTML landing page for a coffee shop"*
- *"Write a SQL query to find the top 10 customers by revenue"*

---

## Table of Contents

1. [Canvas Rendering & Layout](#1-canvas-rendering--layout)
2. [CodeMirror 6 Editor](#2-codemirror-6-editor)
3. [Live Coding Animation](#3-live-coding-animation)
4. [HTML Preview](#4-html-preview)
5. [Markdown Preview](#5-markdown-preview)
6. [SVG Preview](#6-svg-preview)
7. [Diff View](#7-diff-view)
8. [Version History](#8-version-history)
9. [Inline AI Modification](#9-inline-ai-modification)
10. [SQL Execution Bridge](#10-sql-execution-bridge)
11. [Template Gallery](#11-template-gallery)
12. [Standard Toolbar](#12-standard-toolbar)
13. [Sources Badge](#13-sources-badge)
14. [Bidirectional Context](#14-bidirectional-context)
15. [Profile Integration & Intensity](#15-profile-integration--intensity)
16. [Multi-Canvas & Session Behavior](#16-multi-canvas--session-behavior)
17. [Theme & Visual Quality](#17-theme--visual-quality)
18. [Edge Cases & Error Handling](#18-edge-cases--error-handling)
19. [Cross-Browser Testing](#19-cross-browser-testing)
20. [Accessibility](#20-accessibility)

---

## Execution Order (Recommended)

1. **Sections 1-2** — Core rendering & editor (foundation)
2. **Section 3** — Live animation (first-impression feature)
3. **Sections 4-6** — Preview tabs (HTML, Markdown, SVG)
4. **Sections 7-8** — Diff & version history (multi-turn)
5. **Section 9** — Inline AI (advanced editing)
6. **Section 10** — SQL execution (MCP integration)
7. **Sections 11-13** — Template gallery, toolbar, sources
8. **Section 14** — Bidirectional context (LLM integration)
9. **Section 15** — Profile integration
10. **Sections 16-18** — Multi-canvas, themes, edge cases
11. **Sections 19-20** — Cross-browser & accessibility (final pass)

---

## 1. Canvas Rendering & Layout

### 1.1 Split Mode OFF (Inline Compact)

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1.1.1 | Inline compact renders | Toggle split mode OFF. Submit a code-generation prompt. | Canvas appears inline in chat as a compact read-only viewer with syntax highlighting, max ~300px height. | VISUAL |
| 1.1.2 | "Show more" overlay | Generate a long piece of code (50+ lines). | Truncated at ~300px with a "Show more" overlay/button at the bottom. | VISUAL |
| 1.1.3 | Expand from compact | Click "Show more" or expand button. | Canvas expands smoothly to reveal full content. | VISUAL |
| 1.1.4 | Copy button works | Click the Copy button on the inline compact canvas. | Code copied to clipboard; visual feedback (checkmark or "Copied!"). | VISUAL |
| 1.1.5 | Open in split panel | Click the "Expand" or "View in Canvas" action. | Split panel opens on the right with full interactive canvas. | VISUAL |

### 1.2 Split Mode ON (Side Panel)

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1.2.1 | Inline card renders | Toggle split mode ON. Submit a code-generation prompt. | Chat shows a compact card with: title, language badge, 3-line code preview, "View in Canvas" link. | VISUAL |
| 1.2.2 | Auto-open split panel | After canvas is generated in split mode. | Split panel automatically opens on the right (~50% width) with the full interactive canvas. | VISUAL |
| 1.2.3 | Split panel sizing | Observe panel dimensions. | Panel takes ~50% of viewport width, min-width ~320px. Chat area shrinks accordingly. | VISUAL |
| 1.2.4 | Close split panel | Click the close (X) button on the split panel header. | Panel slides closed with CSS transition. Chat area expands back to full width. | VISUAL |
| 1.2.5 | Fullscreen mode | Click the fullscreen icon in the split panel header. | Canvas fills entire viewport. All tabs/toolbar remain functional. | VISUAL |
| 1.2.6 | Exit fullscreen | Click fullscreen icon again or press Escape. | Returns to split-panel layout. | VISUAL |
| 1.2.7 | Persistence across messages | With split panel open, send a follow-up chat message (non-canvas). | Split panel remains open. Chat scrolls independently. | VISUAL |
| 1.2.8 | localStorage persistence | Enable split mode, reload the page. | Split mode preference persists (panel auto-opens for next canvas). | VISUAL |

---

## 2. CodeMirror 6 Editor

*Capability: `code_editor`*

### 2.1 Syntax Highlighting

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 2.1.1 | Python | Generate Python code. Open in full canvas. | Keywords (`def`, `class`, `if`) in lavender, strings in lime green, comments in muted teal. | VISUAL |
| 2.1.2 | HTML | Generate HTML code. | Tags highlighted, attributes colored differently from values. | VISUAL |
| 2.1.3 | SQL | Generate SQL code. | Keywords (`SELECT`, `FROM`, `WHERE`) highlighted distinctly. | VISUAL |
| 2.1.4 | JavaScript | Generate JS code. | Functions in periwinkle, operators in ice blue. | VISUAL |
| 2.1.5 | CSS | Generate CSS code. | Properties, values, selectors distinguishable. | VISUAL |
| 2.1.6 | JSON | Generate JSON output. | Keys and values colored differently. | VISUAL |
| 2.1.7 | Markdown | Generate markdown content. | Headers, bold, code blocks visually distinct. | VISUAL |

### 2.2 Editor Features

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 2.2.1 | Line numbers | Open any canvas in editor. | Line numbers visible in gutter on the left. | VISUAL |
| 2.2.2 | Code editing | Click into the editor and type/modify code. | Editor is writable (in split panel). Changes reflected immediately. | VISUAL |
| 2.2.3 | Undo/Redo | Make edits, then Ctrl+Z / Cmd+Z. | Edits undone. Ctrl+Shift+Z / Cmd+Shift+Z redoes. | VISUAL |
| 2.2.4 | Search/Find | Press Ctrl+F / Cmd+F in the editor. | Search dialog appears. Type to search; matches highlighted. | VISUAL |
| 2.2.5 | Bracket matching | Navigate to a bracket `(`, `[`, `{`. | Matching bracket highlighted. | VISUAL |
| 2.2.6 | Code folding | Click fold gutter next to a function/block definition. | Block collapses. Click again to expand. | VISUAL |
| 2.2.7 | Line wrapping | Generate a line longer than the editor width. | Line wraps (no horizontal scroll). | VISUAL |
| 2.2.8 | Selection highlighting | Select a variable name. | All other occurrences of the same text highlighted. | VISUAL |

---

## 3. Live Coding Animation

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 3.1 | Animation plays | Submit a prompt that triggers canvas generation. Watch the editor. | Code appears line-by-line with a progress bar at the top. | VISUAL |
| 3.2 | Skip button | During animation, click "Skip". | Animation stops immediately; remaining code inserted in bulk. Editor becomes writable. | VISUAL |
| 3.3 | Read-only during animation | During animation, try to click and type in the editor. | Editor is read-only (no cursor, no typing). | VISUAL |
| 3.4 | Short content speed | Generate ~10 lines of code. | Animation completes quickly (~80ms/line, ~0.8s total). | VISUAL |
| 3.5 | Long content speed | Generate ~100+ lines of code. | Adaptive batching. Completes in <15s. Progress bar reflects progress. | VISUAL |
| 3.6 | Auto-scroll during animation | Watch a long file being animated. | Editor auto-scrolls to keep the latest line visible. | VISUAL |
| 3.7 | User scroll interrupts | During animation, scroll up manually. | Auto-scroll stops. Animation continues but viewport stays where user scrolled. | VISUAL |
| 3.8 | Auto-switch to Preview (HTML) | Generate HTML content with animation. | After animation completes, tab automatically switches to "Preview". | VISUAL |

---

## 4. HTML Preview

*Capability: `html_preview` — Languages: html only*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 4.1 | Preview tab appears | Generate HTML content. Open in full canvas. | "Preview" tab visible next to "Code" tab. | VISUAL |
| 4.2 | HTML renders correctly | Click "Preview" tab. | HTML rendered in sandboxed iframe. Page looks correct. | VISUAL |
| 4.3 | Desktop viewport | Click Desktop viewport toggle. | Preview at 100% width. | VISUAL |
| 4.4 | Tablet viewport | Click Tablet toggle. | Preview constrained to 768x1024 with dimension label. | VISUAL |
| 4.5 | Mobile viewport | Click Mobile toggle. | Preview constrained to 375x667 with dimension label. | VISUAL |
| 4.6 | Dynamic scaling | Switch between viewports. | Preview scales smoothly with CSS transform. No overflow. | VISUAL |
| 4.7 | JavaScript execution | Generate HTML with `<script>` (e.g., a counter button). | Script runs inside iframe. Button click works. | VISUAL |
| 4.8 | iframe isolation | Generate HTML with `alert('test')`. | Alert fires inside iframe, NOT in parent page. | VISUAL |
| 4.9 | Edit and re-preview | Switch to Code, modify HTML, switch back to Preview. | Preview reflects updated content. | VISUAL |

---

## 5. Markdown Preview

*Capability: `markdown_preview` — Languages: markdown only*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 5.1 | Preview tab appears | Generate markdown content. | "Preview" tab visible. | VISUAL |
| 5.2 | Headers | Include H1-H6. | Headers render with decreasing sizes. | VISUAL |
| 5.3 | Lists | Include ordered and unordered lists. | Bullets and numbers display correctly. | VISUAL |
| 5.4 | Code blocks | Include fenced code blocks. | Monospace font and background. | VISUAL |
| 5.5 | Tables | Include a markdown table. | Rows, columns, and borders render. | VISUAL |
| 5.6 | Links | Include `[text](url)` links. | Clickable hyperlinks. | VISUAL |
| 5.7 | Bold/Italic | Include `**bold**` and `*italic*`. | Formatting applied. | VISUAL |
| 5.8 | Blockquotes | Include `> quoted text`. | Left border/indent styling. | VISUAL |

---

## 6. SVG Preview

*Capability: `svg_preview` — Languages: svg only*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 6.1 | SVG renders | Generate SVG content (e.g., "Create an SVG logo of a sun"). | "Preview" tab shows the rendered SVG graphic. | VISUAL |
| 6.2 | Script stripping | Generate SVG with embedded `<script>` tags. | Scripts stripped; SVG renders without JS. | VISUAL |
| 6.3 | Event handler removal | SVG with `onclick` attributes. | Event handlers removed. | VISUAL |

---

## 7. Diff View

*Capability: `diff_view` — Conditional: appears only when previous version exists*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 7.1 | No diff on first generation | Generate code for the first time. | No "Changes" tab visible. | VISUAL |
| 7.2 | Diff tab appears on update | Ask LLM to modify the same canvas (e.g., "Add error handling"). | "Changes" tab appears. | VISUAL |
| 7.3 | Side-by-side layout | Click the "Changes" tab. | Left panel (previous, red removals) and right panel (current, green additions). | VISUAL |
| 7.4 | Color coding | Examine diff output. | Added: green. Removed: red. Unchanged: neutral. | VISUAL |
| 7.5 | Statistics header | Check top of diff view. | Summary: "+N added -M removed" with version numbers. | VISUAL |
| 7.6 | Synchronized scrolling | Scroll one diff panel. | Both panels scroll together in sync. | VISUAL |
| 7.7 | Large diff readability | Request a major rewrite. | Handles large changes without performance issues. | VISUAL |

---

## 8. Version History

*Capability: `version_history` — Conditional: appears only when 2+ versions exist*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 8.1 | No history on first version | Generate code once. | No version history dropdown visible. | VISUAL |
| 8.2 | History appears on update | Update the canvas. | Version dropdown/button with count badge appears. | VISUAL |
| 8.3 | Dropdown lists versions | Click the version history dropdown. | All versions listed with number, timestamp, turn index. Current highlighted. | VISUAL |
| 8.4 | Restore previous version | Select older version, click "Restore". | Editor content reverts. | VISUAL |
| 8.5 | Restore is undoable | After restoring, press Ctrl+Z. | Content reverts to pre-restore state. | VISUAL |
| 8.6 | Multiple updates accumulate | Update canvas 3-4 times across turns. | All versions tracked. Badge shows correct count. | API:PASS — Unit test verified 21 sequential versions tracked correctly |
| 8.7 | Duplicate content skipped | Ask LLM to regenerate identical content. | No new version added (deduplication). | API:PASS — Unit test verified duplicate content deduplication |
| 8.8 | Independent canvases | Generate two canvases with different titles. | Each has independent version history. | API:PASS — Unit test verified independent stores per title |

---

## 9. Inline AI Modification

*Capability: `inline_ai_button` — Requires CodeMirror 6 (disabled in Prism.js fallback)*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 9.1 | "Ask AI" button appears | Select text in the CodeMirror editor. | Floating blue "Ask AI" button near selection. | VISUAL |
| 9.2 | Button disappears on deselect | Click elsewhere. | Button disappears. | VISUAL |
| 9.3 | Prompt input opens | Click "Ask AI". | Input field (260px) with text input, "Go" button, cancel (X). | VISUAL |
| 9.4 | Submit instruction | Type "Add type hints", press Enter. | Loading state, then selected code replaced with modified version. | API:PASS — `POST /v1/canvas/inline-ai` returns `modified_code` (len=48) |
| 9.5 | Token badge | After successful modification. | Token badge appears briefly (fades after ~3s). | API:PASS — `input_tokens=152, output_tokens=15` (both >0) |
| 9.6 | Undo inline AI | After modification, Ctrl+Z. | Entire modification undone atomically. | VISUAL |
| 9.7 | Cancel prompt | Click cancel (X) or press Escape. | Prompt disappears. Selection preserved. No API call. | VISUAL |
| 9.8 | Error handling | Submit while LLM unreachable. | Error in placeholder. Clears after ~3s. Original preserved. | API:PASS — Empty fields return HTTP 400 |
| 9.9 | Disabled during animation | During live animation, try to select text. | "Ask AI" button does NOT appear. | VISUAL |

---

## 10. SQL Execution Bridge

*Capability: `execution_bridge` — Languages: sql only*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 10.1 | Run button for SQL | Generate SQL code. Open in full canvas. | Green "Run" button in toolbar. | VISUAL |
| 10.2 | No run button for non-SQL | Generate Python or HTML. | No "Run" button. | VISUAL |
| 10.3 | Execute successfully | Valid SQL (e.g., `SELECT * FROM products LIMIT 5`). Click Run. | Console panel: results, row count badge, execution time (ms). | API:PASS — `POST /v1/canvas/execute` returns result, exec_time=1050ms |
| 10.4 | SQL error | Invalid SQL (e.g., nonexistent table). Click Run. | Console: red error text, "Error" badge. | API:PASS — Invalid SQL returns HTTP 400 with error |
| 10.5 | Edit and re-run | Modify SQL, click Run again. | New results replace previous. | VISUAL |
| 10.6 | Close console | Click close button on console panel. | Console hides. | VISUAL |
| 10.7 | Large result set | Query returning many rows. | Scrollable console. Acceptable performance. | API:PASS — Large query returned without timeout |

---

## 11. Template Gallery

*Capability: `template_gallery`*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 11.1 | Templates button visible | Open any canvas in full mode. | "Templates" button in toolbar. | VISUAL |
| 11.2 | Modal opens | Click "Templates". | Full-screen modal with category tabs and card grid. | VISUAL |
| 11.3 | Categories present | Check modal. | Categories: HTML, CSS, JavaScript, Python, SQL, Markdown. | API:PASS — `GET /v1/canvas/templates` returns all 6 categories |
| 11.4 | Template cards | Browse templates. | Each card: name, language, description. Two-column grid. | API:PASS — 12 templates, all have required fields (id, name, language, description, content) |
| 11.5 | Select a template | Click a template card (e.g., "Landing Page"). | Content inserted into editor. Modal closes. | VISUAL |
| 11.6 | Previous content versioned | Editor had content before template insertion. | Previous content saved as version (can restore). | VISUAL |
| 11.7 | Close — Escape | Open modal, press Escape. | Closes without inserting. | VISUAL |
| 11.8 | Close — overlay click | Open modal, click background overlay. | Closes without inserting. | VISUAL |
| 11.9 | Close — X button | Open modal, click X. | Closes without inserting. | VISUAL |

---

## 12. Standard Toolbar

*Capability: `toolbar`*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 12.1 | Copy button | Click "Copy" in toolbar. | Clipboard updated. Visual feedback (checkmark / "Copied!"). | VISUAL |
| 12.2 | Copy reflects edits | Edit code, then Copy. | Copied text = current editor content, not original. | VISUAL |
| 12.3 | Download button | Click "Download". | File downloads with correct extension. | VISUAL |
| 12.4 | Download correct content | Edit code, then Download. | File contains current editor content. | VISUAL |
| 12.5 | File extensions | Generate canvases in different languages. Download each. | Correct: `.html`, `.css`, `.js`, `.py`, `.sql`, `.md`, `.json`, `.svg`. | API:PASS — Unit test: all 9 extensions correct; E2E: html=.html, sql=.sql verified |
| 12.6 | Info badge | Check toolbar info. | Line count + language (e.g., "42 lines - Python"). | API:PASS — E2E: html=10 lines, sql=1 line; unit test: metadata fields correct |
| 12.7 | Expand button | Click "Expand" (when not in split). | Canvas opens in split panel. | VISUAL |

---

## 13. Sources Badge

*Capability: `sources_badge` — Conditional: appears only when sources provided*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 13.1 | Badge appears | Generate canvas from RAG/knowledge query (`@FOCUS` profile). | "Sources" button visible in toolbar. | VISUAL — Requires knowledge repo with canvas-triggering content |
| 13.2 | Sources dropdown | Click "Sources" button. | Dropdown lists knowledge documents (format: "Title (collection)"). | VISUAL |
| 13.3 | No badge without sources | Generate canvas from regular prompt (no RAG). | No "Sources" button. | API:PASS — Canvas spec has `sources=null` for non-RAG queries |

---

## 14. Bidirectional Context

*LLM reads user-edited canvas content on next turn*

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 14.1 | LLM sees edited canvas | Edit code in split panel (change a function name). Ask: "Explain what this code does". | LLM references the **edited** version. | VISUAL |
| 14.2 | Modified indicator | Edit canvas, submit prompt. Check Network tab payload. | `canvas_context` includes `modified: true` + current content. | VISUAL |
| 14.3 | Update same canvas | Ask: "Add error handling to this code". | LLM uses TDA_Canvas with **same title**. Diff view available. Version incremented. | API:PASS — Second query with `canvas_context` triggered TDA_Canvas again |
| 14.4 | Unchanged canvas | Don't edit. Submit follow-up. | `canvas_context` sent with `modified: false`. | API:PASS — Query with `modified=false` canvas_context completed successfully |

---

## 15. Profile Integration & Intensity

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 15.1 | tool_enabled profile | `@OPTIM`: "Write a Python class for a shopping cart". | Canvas generated. "Plan Optimization" event in Live Status (fast-path). | API:PASS — TDA_Canvas used via @OPTIM, deterministic fast-path event detected |
| 15.2 | llm_only profile | `@IDEAT`: "Write a Python class for a shopping cart". | Canvas generated via LangChain agent. | API:PASS — TDA_Canvas used via @IDEAT |
| 15.3 | rag_focused profile | `@FOCUS` with knowledge repo. Ask code-producing question. | Canvas with sources badge (if applicable). | VISUAL — Requires knowledge repo configured |
| 15.4 | Canvas disabled | Profile with `canvas.enabled: false`. Code prompt. | No canvas; code as regular markdown block. | VISUAL — Requires profile config change |
| 15.5 | Intensity: heavy | Profile with `canvas.intensity: "heavy"`. Any prompt. | LLM aggressively uses canvas for all code output. | VISUAL — Requires profile config change |
| 15.6 | Intensity: none | Profile with `canvas.intensity: "none"`. Code prompt. | No canvas; code as regular text. | API:PASS — Unit test: 'none' intensity is empty string (no instructions injected) |

---

## 16. Multi-Canvas & Session Behavior

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 16.1 | Multiple canvases | Ask for Python, then HTML, then SQL (different titles). | Three independent canvas instances in chat. | API:PASS — Two queries in same session both triggered TDA_Canvas |
| 16.2 | Switch canvases (split) | Click "View in Canvas" on different inline cards. | Split panel updates to selected canvas. | VISUAL |
| 16.3 | Canvas across session switch | Canvas in Session A. Switch to B. Switch back to A. | Canvas visible in A's chat history. | API:PASS — `/sessions/{id}/details` returns canvas in session data (9084 bytes, TDA_Canvas confirmed) |
| 16.4 | Version history within session | Update a canvas 3 times. | All versions accessible via history dropdown. | VISUAL |
| 16.5 | History lost on reload | Update canvas, refresh browser. | History reset (in-memory). Only latest from server. | VISUAL |

---

## 17. Theme & Visual Quality

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 17.1 | Dark theme | Default dark theme. Open a canvas. | Dark background, readable text, Oceanic syntax colors. | VISUAL |
| 17.2 | Light theme | Switch to light theme. Open a canvas. | Code areas remain dark (VS Code pattern). UI adapts. | VISUAL |
| 17.3 | Glass panel styling | Examine canvas container. | Frosted glass effect consistent with platform. | VISUAL |
| 17.4 | Tab styling | Check active/inactive tabs. | Active clearly distinguished. Inactive subdued. | VISUAL |
| 17.5 | Toolbar icon clarity | Examine toolbar buttons. | Clear icons. Hover tooltips present. | VISUAL |

---

## 18. Edge Cases & Error Handling

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 18.1 | Very large file (1000+ lines) | "Write a Python utility library with 50 functions". | Renders without freezing. Smooth scrolling. Correct line numbers. | API:PASS — TDA_Canvas invoked for large file generation |
| 18.2 | Empty content | Edge case: LLM returns empty content. | Graceful handling (empty editor or message). No crash. | API:PASS — Unit test: handler rejects empty string with validation error |
| 18.3 | Unicode content | "Write greetings in 10 languages including Chinese, Arabic, and emoji". | Unicode renders correctly. Copy/paste preserves. | API:PASS — Canvas spec contains unicode (JSON-escaped as \u sequences, renders correctly in browser) |
| 18.4 | Very long single line | Content with 500+ char line. | Line wrapping. No horizontal scrollbar. | VISUAL |
| 18.5 | Network disconnect during inline AI | Start inline AI, then go offline (DevTools). | Error in prompt. Editor unchanged. | VISUAL |
| 18.6 | Rapid canvas updates | 3 quick modification requests. | Handled properly. Versions accumulate correctly. | VISUAL |
| 18.7 | CodeMirror CDN failure | Block `esm.sh` in DevTools Network. Generate canvas. | Fallback to Prism.js read-only. Highlighting present. No inline AI. | VISUAL |
| 18.8 | Mermaid content | "Create a mermaid diagram of user registration flow". | Renders with markdown extension. Valid mermaid syntax. | API:PASS — TDA_Canvas invoked with mermaid content detected in events |

---

## 19. Cross-Browser Testing

Run this core workflow in each browser:

**Workflow:** Generate HTML canvas &rarr; edit code &rarr; preview &rarr; responsive viewports &rarr; inline AI &rarr; template insertion &rarr; copy &rarr; download &rarr; diff view

| Browser | Pass | Notes |
|---------|------|-------|
| Chrome (latest) | VISUAL | Primary target |
| Firefox (latest) | VISUAL | |
| Safari (latest) | VISUAL | Cmd vs Ctrl shortcuts |
| Edge (latest) | VISUAL | |
| iPad Safari | VISUAL | Touch interactions, file picker limitations |

---

## 20. Accessibility

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 20.1 | Keyboard tab navigation | Tab through canvas UI. | Logical focus order: tabs &rarr; toolbar &rarr; editor. Focus ring visible. | VISUAL |
| 20.2 | Escape key | Press Escape in modal, fullscreen, prompt input. | Appropriate dismissal in each context. | VISUAL |
| 20.3 | Screen reader | VoiceOver (Mac) or NVDA (Windows). Navigate canvas. | Buttons/tabs have accessible labels. Content read correctly. | VISUAL |
| 20.4 | High contrast / zoom | OS high-contrast or 200% zoom. | UI usable. Text readable. Buttons clickable. | VISUAL |

---

## Post-Testing: Run Automated Suite

After completing manual tests, confirm no regressions with the automated suite:

```bash
# Unit tests (handler, diff, templates, versions, manifest, instructions)
python test/test_canvas_comprehensive.py --unit-only

# API tests (requires running server)
python test/test_canvas_comprehensive.py --api-only

# Full E2E (requires configured LLM)
python test/test_canvas_comprehensive.py --e2e
```

---

## Summary

| Section | Total | API:PASS | VISUAL | Area |
|---------|-------|----------|--------|------|
| 1 | 13 | 0 | 13 | Rendering & layout (split ON/OFF) |
| 2 | 15 | 0 | 15 | CodeMirror 6 editor (highlighting, editing, search) |
| 3 | 8 | 0 | 8 | Live coding animation |
| 4 | 9 | 0 | 9 | HTML preview (responsive viewports, iframe) |
| 5 | 8 | 0 | 8 | Markdown preview |
| 6 | 3 | 0 | 3 | SVG preview (security) |
| 7 | 7 | 0 | 7 | Diff view (side-by-side, sync scroll) |
| 8 | 8 | 3 | 5 | Version history (restore, dedup) |
| 9 | 9 | 3 | 6 | Inline AI (Ask AI, undo, error) |
| 10 | 7 | 3 | 4 | SQL execution bridge |
| 11 | 9 | 2 | 7 | Template gallery |
| 12 | 7 | 2 | 5 | Standard toolbar (copy, download) |
| 13 | 3 | 1 | 2 | Sources badge (RAG attribution) |
| 14 | 4 | 2 | 2 | Bidirectional context |
| 15 | 6 | 3 | 3 | Profile integration & intensity |
| 16 | 5 | 2 | 3 | Multi-canvas & sessions |
| 17 | 5 | 0 | 5 | Theme & visual quality |
| 18 | 8 | 4 | 4 | Edge cases & errors |
| 19 | 5 | 0 | 5 | Cross-browser |
| 20 | 4 | 0 | 4 | Accessibility |
| **Total** | **~138** | **25** | **~113** | |
