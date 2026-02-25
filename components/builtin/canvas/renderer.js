/**
 * Canvas Component Renderer
 *
 * Interactive code/document workspace with modular capability plugins.
 * Provides CodeMirror 6 editing, language-aware preview, and toolbar actions.
 *
 * Architecture: CanvasCore (container, state, lifecycle) + registered capabilities.
 * Each capability implements: { id, label, type, languages, init, render, destroy, getState }
 */

// ─── Capability Registry ─────────────────────────────────────────────────────

/** @type {Array<Object>} Registered capability plugins */
const _capabilities = [];

/**
 * Register a capability plugin with the canvas.
 * @param {Object} cap - Capability implementing the plugin contract
 */
function registerCapability(cap) {
    _capabilities.push(cap);
}

// ─── Version Store (session-scoped, persists across renders) ─────────────────

/**
 * Module-level version store — keyed by normalized canvas title.
 * Tracks all versions of each canvas across conversation turns.
 * @type {Map<string, Array<{content: string, language: string, timestamp: number, turnIndex: number}>>}
 */
const _canvasVersions = new Map();
let _globalTurnCounter = 0;

/**
 * Record a new version and return the version history for this canvas.
 * @returns {{ versions: Array, previousContent: string|null, versionNumber: number }}
 */
function recordVersion(title, content, language) {
    const key = title.toLowerCase().trim();
    if (!_canvasVersions.has(key)) {
        _canvasVersions.set(key, []);
    }
    const versions = _canvasVersions.get(key);

    // Avoid duplicate consecutive versions (same content)
    const last = versions[versions.length - 1];
    if (last && last.content === content) {
        return {
            versions,
            previousContent: versions.length > 1 ? versions[versions.length - 2].content : null,
            versionNumber: versions.length,
        };
    }

    _globalTurnCounter++;
    versions.push({
        content,
        language,
        timestamp: Date.now(),
        turnIndex: _globalTurnCounter,
    });

    return {
        versions,
        previousContent: versions.length > 1 ? versions[versions.length - 2].content : null,
        versionNumber: versions.length,
    };
}

// ─── Line-Based Diff Algorithm ───────────────────────────────────────────────

/**
 * Compute a line-based diff between two strings using LCS.
 * Returns an array of { type: 'equal'|'added'|'removed', line: string } entries.
 */
function computeLineDiff(oldText, newText) {
    const oldLines = oldText.split('\n');
    const newLines = newText.split('\n');

    // Build LCS table
    const m = oldLines.length;
    const n = newLines.length;
    const dp = Array.from({ length: m + 1 }, () => new Uint16Array(n + 1));

    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            if (oldLines[i - 1] === newLines[j - 1]) {
                dp[i][j] = dp[i - 1][j - 1] + 1;
            } else {
                dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
            }
        }
    }

    // Backtrack to produce diff
    const diff = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
            diff.unshift({ type: 'equal', line: oldLines[i - 1], oldLineNum: i, newLineNum: j });
            i--; j--;
        } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
            diff.unshift({ type: 'added', line: newLines[j - 1], newLineNum: j });
            j--;
        } else {
            diff.unshift({ type: 'removed', line: oldLines[i - 1], oldLineNum: i });
            i--;
        }
    }

    return diff;
}

/**
 * Compute summary stats from a diff result.
 */
function diffStats(diff) {
    let added = 0, removed = 0;
    for (const d of diff) {
        if (d.type === 'added') added++;
        else if (d.type === 'removed') removed++;
    }
    return { added, removed };
}

// ─── CodeMirror 6 Lazy Loader ────────────────────────────────────────────────

let _cmCache = null;
let _cmLoadPromise = null;

async function loadCodeMirror() {
    if (_cmCache) return _cmCache;
    if (_cmLoadPromise) return _cmLoadPromise;

    // NOTE: We import from individual @codemirror/* sub-packages instead of
    // the 'codemirror' meta-package. esm.sh serves the meta-package as a UMD
    // bundle that doesn't expose named ESM exports (EditorView, basicSetup
    // are both undefined). By importing sub-packages directly, we construct
    // our own basicSetup equivalent from the pieces.
    _cmLoadPromise = (async () => {
        try {
            const [
                cmView,
                cmState,
                cmCommands,
                cmLanguage,
                cmSearch,
                cmAutocomplete,
                cmLint,
                { html: langHtml },
                { javascript: langJs },
                { python: langPy },
                { sql: langSql },
                { json: langJson },
                { css: langCss },
                { markdown: langMd },
                { oneDarkTheme },
                cmHighlight,
            ] = await Promise.all([
                import('https://esm.sh/@codemirror/view@6'),
                import('https://esm.sh/@codemirror/state@6'),
                import('https://esm.sh/@codemirror/commands@6'),
                import('https://esm.sh/@codemirror/language@6'),
                import('https://esm.sh/@codemirror/search@6'),
                import('https://esm.sh/@codemirror/autocomplete@6'),
                import('https://esm.sh/@codemirror/lint@6'),
                import('https://esm.sh/@codemirror/lang-html@6'),
                import('https://esm.sh/@codemirror/lang-javascript@6'),
                import('https://esm.sh/@codemirror/lang-python@6'),
                import('https://esm.sh/@codemirror/lang-sql@6'),
                import('https://esm.sh/@codemirror/lang-json@6'),
                import('https://esm.sh/@codemirror/lang-css@6'),
                import('https://esm.sh/@codemirror/lang-markdown@6'),
                import('https://esm.sh/@codemirror/theme-one-dark@6'),
                import('https://esm.sh/@lezer/highlight@1'),
            ]);

            const { EditorView, lineNumbers, highlightSpecialChars, drawSelection,
                    highlightActiveLine, dropCursor, rectangularSelection,
                    crosshairCursor, highlightActiveLineGutter, keymap } = cmView;
            const { EditorState, Compartment } = cmState;
            const { defaultKeymap, history, historyKeymap } = cmCommands;
            const { syntaxHighlighting, defaultHighlightStyle, indentOnInput,
                    bracketMatching, foldGutter, foldKeymap } = cmLanguage;
            const { searchKeymap, highlightSelectionMatches } = cmSearch;
            const { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } = cmAutocomplete;
            const { lintKeymap } = cmLint;

            if (!EditorView) {
                throw new Error('EditorView not found in @codemirror/view');
            }

            // Custom "Oceanic" highlight style — replaces oneDark's red-heavy
            // palette with blues, teals, and greens that complement the dark
            // slate background.  oneDarkTheme provides editor chrome (bg,
            // cursor, selection); this style handles syntax token colors.
            const { HighlightStyle } = cmLanguage;
            const { tags: t } = cmHighlight;
            const oceanicStyle = syntaxHighlighting(HighlightStyle.define([
                { tag: t.keyword, color: '#c792ea' },                                          // lavender
                { tag: [t.name, t.deleted, t.character, t.macroName], color: '#d6deeb' },       // light slate
                { tag: t.propertyName, color: '#80cbc4' },                                      // teal
                { tag: [t.function(t.variableName), t.labelName], color: '#82aaff' },           // periwinkle
                { tag: [t.color, t.constant(t.name), t.standard(t.name)], color: '#d19a66' },   // whiskey
                { tag: [t.definition(t.name), t.separator], color: '#bec5d4' },                 // silver
                { tag: [t.typeName, t.className, t.number, t.changed,
                        t.annotation, t.modifier, t.self, t.namespace], color: '#ffcb6b' },     // gold
                { tag: [t.operator, t.operatorKeyword, t.url, t.escape,
                        t.regexp, t.link, t.special(t.string)], color: '#89ddff' },             // ice blue
                { tag: [t.meta, t.comment], color: '#637777', fontStyle: 'italic' },            // muted teal
                { tag: t.strong, fontWeight: 'bold' },
                { tag: t.emphasis, fontStyle: 'italic' },
                { tag: t.strikethrough, textDecoration: 'line-through' },
                { tag: t.link, color: '#637777', textDecoration: 'underline' },
                { tag: [t.atom, t.bool, t.special(t.variableName)], color: '#f78c6c' },        // soft coral
                { tag: [t.processingInstruction, t.string, t.inserted], color: '#c3e88d' },     // lime green
                { tag: t.invalid, color: '#ff5370' },
            ]));

            // Construct basicSetup equivalent (mirrors codemirror/src/codemirror.ts)
            const basicSetup = [
                lineNumbers(),
                highlightActiveLineGutter(),
                highlightSpecialChars(),
                history(),
                foldGutter(),
                drawSelection(),
                dropCursor(),
                EditorState.allowMultipleSelections.of(true),
                indentOnInput(),
                syntaxHighlighting(defaultHighlightStyle, {fallback: true}),
                bracketMatching(),
                closeBrackets(),
                autocompletion(),
                rectangularSelection(),
                crosshairCursor(),
                highlightActiveLine(),
                highlightSelectionMatches(),
                keymap.of([
                    ...closeBracketsKeymap,
                    ...defaultKeymap,
                    ...searchKeymap,
                    ...historyKeymap,
                    ...foldKeymap,
                    ...completionKeymap,
                    ...lintKeymap,
                ]),
            ].filter(Boolean); // Safety: filter out any undefined extensions

            console.log('[Canvas] CodeMirror 6 loaded successfully from sub-packages',
                { EditorView: !!EditorView, basicSetup: basicSetup.length, oneDarkTheme: !!oneDarkTheme });

            _cmCache = { EditorView, basicSetup, oneDarkTheme, oceanicStyle, langHtml, langJs, langPy, langSql, langJson, langCss, langMd, Compartment, EditorState };
            return _cmCache;
        } catch (err) {
            console.warn('[Canvas] CodeMirror 6 load failed, using Prism.js fallback:', err);
            _cmLoadPromise = null;
            return null;
        }
    })();

    return _cmLoadPromise;
}

/** Map language string to CodeMirror 6 language extension */
function getCmLanguageExt(cm, language) {
    const map = {
        html: cm.langHtml, css: cm.langCss, javascript: cm.langJs,
        python: cm.langPy, sql: cm.langSql, json: cm.langJson,
        markdown: cm.langMd, svg: cm.langHtml, mermaid: cm.langMd,
    };
    const factory = map[language];
    return factory ? [factory()] : [];
}

// ─── Inline Styles ───────────────────────────────────────────────────────────

const CANVAS_STYLES = `
.canvas-container {
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    border-radius: 0.75rem;
    overflow: hidden;
    background: var(--card-bg, rgba(15,23,42,0.6));
    margin: 0.5rem 0;
}
.canvas-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 1rem;
    border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: var(--bg-secondary, rgba(0,0,0,0.15));
}
.canvas-header-left {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-width: 0;
}
.canvas-title {
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary, #e2e8f0);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.canvas-tab-bar {
    display: flex;
    gap: 0.25rem;
}
.canvas-tab {
    padding: 0.3rem 0.75rem;
    border-radius: 0.375rem;
    font-size: 0.8rem;
    cursor: pointer;
    color: var(--text-muted, #94a3b8);
    background: transparent;
    border: none;
    transition: all 0.15s ease;
    user-select: none;
}
.canvas-tab:hover {
    background: var(--hover-bg, rgba(255,255,255,0.06));
    color: var(--text-primary, #e2e8f0);
}
.canvas-tab--active {
    background: rgba(59, 130, 246, 0.15);
    color: rgb(96, 165, 250);
}
.canvas-toolbar {
    display: flex;
    gap: 0.5rem;
    align-items: center;
}
.canvas-toolbar-btn {
    padding: 0.25rem 0.5rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    color: var(--text-muted, #94a3b8);
    cursor: pointer;
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: transparent;
    transition: all 0.15s ease;
    white-space: nowrap;
}
.canvas-toolbar-btn:hover {
    background: var(--hover-bg, rgba(255,255,255,0.08));
    color: var(--text-primary, #e2e8f0);
}
.canvas-info-badge {
    font-size: 0.7rem;
    color: var(--text-muted, #94a3b8);
    padding: 0.2rem 0.5rem;
    background: var(--hover-bg, rgba(255,255,255,0.04));
    border-radius: 0.375rem;
    white-space: nowrap;
}
.canvas-body {
    min-height: 120px;
    max-height: 600px;
    overflow: auto;
    position: relative;
}
.canvas-panel {
    display: none;
    height: 100%;
}
.canvas-panel--active {
    display: block;
}
/* CodeMirror integration */
.canvas-body .cm-editor {
    height: 100%;
    font-size: 0.85rem;
    max-height: 600px;
}
.canvas-body .cm-editor .cm-scroller {
    overflow: auto;
}
.canvas-body .cm-editor .cm-gutters {
    background: rgba(0,0,0,0.2);
    border-right: 1px solid var(--border-primary, rgba(255,255,255,0.1));
}
/* Prism.js fallback */
.canvas-fallback-code {
    margin: 0;
    padding: 1rem;
    font-size: 0.85rem;
    line-height: 1.5;
    overflow: auto;
    max-height: 600px;
    background: transparent !important;
}
.canvas-fallback-code code {
    background: transparent !important;
}
/* Oceanic token overrides for Prism.js fallback (matches CM6 palette) */
.canvas-fallback-code .token.keyword,
.canvas-fallback-code .token.control,
.canvas-fallback-code .token.important { color: #c792ea; }
.canvas-fallback-code .token.string,
.canvas-fallback-code .token.attr-value,
.canvas-fallback-code .token.template-string { color: #c3e88d; }
.canvas-fallback-code .token.comment,
.canvas-fallback-code .token.prolog,
.canvas-fallback-code .token.doctype { color: #637777; font-style: italic; }
.canvas-fallback-code .token.function { color: #82aaff; }
.canvas-fallback-code .token.class-name,
.canvas-fallback-code .token.number { color: #ffcb6b; }
.canvas-fallback-code .token.operator,
.canvas-fallback-code .token.entity,
.canvas-fallback-code .token.url { color: #89ddff; }
.canvas-fallback-code .token.boolean,
.canvas-fallback-code .token.constant { color: #f78c6c; }
.canvas-fallback-code .token.property,
.canvas-fallback-code .token.builtin,
.canvas-fallback-code .token.symbol { color: #80cbc4; }
.canvas-fallback-code .token.punctuation { color: #89ddff; }
.canvas-fallback-code .token.tag { color: #7fdbca; }
.canvas-fallback-code .token.attr-name { color: #addb67; }
.canvas-fallback-code .token.selector { color: #c792ea; }
.canvas-fallback-code .token.regex { color: #80cbc4; }
.canvas-fallback-code .token.variable { color: #d6deeb; }
/* Preview iframe */
.canvas-preview-iframe {
    width: 100%;
    height: 500px;
    border: none;
    border-radius: 0 0 0.75rem 0.75rem;
    background: #fff;
}
/* Responsive preview */
.canvas-responsive-bar {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.4rem 0.75rem;
    border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: var(--bg-secondary, rgba(0,0,0,0.1));
}
.canvas-viewport-btn {
    padding: 0.2rem 0.5rem;
    border-radius: 0.3rem;
    font-size: 0.7rem;
    color: var(--text-muted, #94a3b8);
    cursor: pointer;
    border: 1px solid transparent;
    background: transparent;
    transition: all 0.15s ease;
    display: flex;
    align-items: center;
    gap: 0.25rem;
}
.canvas-viewport-btn:hover {
    background: var(--hover-bg, rgba(255,255,255,0.06));
    color: var(--text-primary, #e2e8f0);
}
.canvas-viewport-btn--active {
    background: rgba(59, 130, 246, 0.12);
    color: rgb(96, 165, 250);
    border-color: rgba(59, 130, 246, 0.25);
}
.canvas-viewport-label {
    font-size: 0.65rem;
    color: var(--text-muted, #94a3b8);
    margin-left: auto;
    white-space: nowrap;
}
.canvas-responsive-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    overflow: auto;
    background: #e5e7eb;
    border-radius: 0 0 0.75rem 0.75rem;
    min-height: 400px;
    padding: 1rem;
}
.canvas-responsive-wrapper .canvas-preview-iframe {
    border-radius: 0.5rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    transform-origin: top center;
    transition: width 0.3s ease, transform 0.3s ease;
}
/* Markdown preview */
.canvas-md-preview {
    padding: 1.25rem;
    color: var(--text-primary, #e2e8f0);
    line-height: 1.7;
    font-size: 0.9rem;
}
.canvas-md-preview h1 { font-size: 1.5rem; font-weight: 700; margin: 1rem 0 0.5rem; border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.1)); padding-bottom: 0.3rem; }
.canvas-md-preview h2 { font-size: 1.3rem; font-weight: 600; margin: 0.9rem 0 0.4rem; }
.canvas-md-preview h3 { font-size: 1.1rem; font-weight: 600; margin: 0.8rem 0 0.3rem; }
.canvas-md-preview h4, .canvas-md-preview h5, .canvas-md-preview h6 { font-size: 1rem; font-weight: 600; margin: 0.7rem 0 0.3rem; }
.canvas-md-preview p { margin: 0.5rem 0; }
.canvas-md-preview a { color: rgb(96, 165, 250); text-decoration: underline; }
.canvas-md-preview code { background: var(--hover-bg, rgba(255,255,255,0.08)); padding: 0.15rem 0.35rem; border-radius: 0.25rem; font-size: 0.85em; }
.canvas-md-preview pre { background: var(--code-bg, rgba(0,0,0,0.3)); padding: 0.75rem; border-radius: 0.5rem; overflow-x: auto; margin: 0.5rem 0; }
.canvas-md-preview pre code { background: transparent; padding: 0; }
.canvas-md-preview blockquote { border-left: 3px solid rgba(96,165,250,0.5); padding-left: 0.75rem; margin: 0.5rem 0; color: var(--text-muted, #94a3b8); }
.canvas-md-preview ul, .canvas-md-preview ol { padding-left: 1.5rem; margin: 0.4rem 0; }
.canvas-md-preview li { margin: 0.2rem 0; }
.canvas-md-preview hr { border: none; border-top: 1px solid var(--border-primary, rgba(255,255,255,0.1)); margin: 1rem 0; }
.canvas-md-preview table { border-collapse: collapse; margin: 0.5rem 0; width: 100%; }
.canvas-md-preview th, .canvas-md-preview td { border: 1px solid var(--border-primary, rgba(255,255,255,0.15)); padding: 0.4rem 0.6rem; text-align: left; }
.canvas-md-preview th { background: var(--hover-bg, rgba(255,255,255,0.05)); font-weight: 600; }
/* SVG preview */
.canvas-svg-preview {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    background: #ffffff;
    border-radius: 0 0 0.75rem 0.75rem;
    min-height: 200px;
}
.canvas-svg-preview svg {
    max-width: 100%;
    max-height: 500px;
}
/* Diff view */
.canvas-diff-container {
    display: flex;
    flex-direction: column;
    height: 100%;
}
.canvas-diff-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0.75rem;
    background: var(--bg-secondary, rgba(0,0,0,0.2));
    border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    font-size: 0.8rem;
}
.canvas-diff-stat {
    display: flex;
    gap: 0.75rem;
}
.canvas-diff-stat-added {
    color: #4ade80;
}
.canvas-diff-stat-removed {
    color: #f87171;
}
.canvas-diff-panels {
    display: flex;
    flex: 1;
    overflow: auto;
    max-height: 560px;
}
.canvas-diff-panel {
    flex: 1;
    overflow-x: auto;
    font-family: 'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    min-width: 0;
}
.canvas-diff-panel--old {
    border-right: 1px solid var(--border-primary, rgba(255,255,255,0.1));
}
.canvas-diff-line {
    display: flex;
    padding: 0 0.5rem;
    white-space: pre;
    min-height: 1.5em;
}
.canvas-diff-line--added {
    background: rgba(74, 222, 128, 0.1);
}
.canvas-diff-line--removed {
    background: rgba(248, 113, 113, 0.1);
}
.canvas-diff-line--empty {
    background: rgba(255,255,255,0.02);
}
.canvas-diff-linenum {
    display: inline-block;
    min-width: 2.5rem;
    text-align: right;
    padding-right: 0.75rem;
    color: var(--text-muted, #94a3b8);
    opacity: 0.5;
    user-select: none;
    flex-shrink: 0;
}
.canvas-diff-text {
    flex: 1;
    min-width: 0;
}
.canvas-diff-text--added { color: #4ade80; }
.canvas-diff-text--removed { color: #f87171; }
.canvas-diff-label {
    font-size: 0.75rem;
    color: var(--text-muted, #94a3b8);
    font-weight: 600;
}
/* ─── Split-Screen Panel ──────────────────────────────────────── */
#canvas-split-panel {
    width: 0;
    min-width: 0;
    max-width: 55%;
    flex-shrink: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background: var(--card-bg, rgba(15,23,42,0.6));
    border-left: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    transition: width 0.3s ease, min-width 0.3s ease;
}
#canvas-split-panel.canvas-split--open {
    width: 50%;
    min-width: 320px;
}
.canvas-split-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: var(--bg-secondary, rgba(0,0,0,0.15));
    flex-shrink: 0;
}
.canvas-split-title-text {
    font-weight: 600;
    font-size: 0.8rem;
    color: var(--text-primary, #e2e8f0);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.canvas-split-header-actions {
    display: flex;
    gap: 0.25rem;
    align-items: center;
}
.canvas-split-action-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 0.25rem;
    border: none;
    background: transparent;
    color: var(--text-muted, #94a3b8);
    cursor: pointer;
    transition: all 0.15s ease;
}
.canvas-split-action-btn:hover {
    background: var(--hover-bg-strong, rgba(255,255,255,0.1));
    color: var(--text-primary, #e2e8f0);
}
.canvas-split-body {
    flex: 1;
    overflow: auto;
    padding: 0;
}
/* When canvas is in split panel, remove inline card styling */
.canvas-split-body .canvas-container {
    border: none;
    border-radius: 0;
    margin: 0;
    background: transparent;
}
.canvas-split-body .canvas-body {
    max-height: none;
}
.canvas-split-body .cm-editor {
    max-height: none;
}
/* Version history dropdown */
.canvas-version-wrapper {
    position: relative;
}
.canvas-version-btn {
    padding: 0.25rem 0.5rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    color: var(--text-muted, #94a3b8);
    cursor: pointer;
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: transparent;
    transition: all 0.15s ease;
    white-space: nowrap;
}
.canvas-version-btn:hover {
    background: var(--hover-bg, rgba(255,255,255,0.08));
    color: var(--text-primary, #e2e8f0);
}
.canvas-version-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.1rem;
    height: 1.1rem;
    border-radius: 50%;
    background: rgba(59, 130, 246, 0.25);
    color: rgb(96, 165, 250);
    font-size: 0.65rem;
    font-weight: 700;
    margin-left: 0.3rem;
}
.canvas-version-dropdown {
    display: none;
    position: absolute;
    top: 100%;
    right: 0;
    margin-top: 0.35rem;
    min-width: 260px;
    max-height: 300px;
    overflow-y: auto;
    background: var(--card-bg, rgba(15,23,42,0.95));
    border: 1px solid var(--border-primary, rgba(255,255,255,0.15));
    border-radius: 0.5rem;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    z-index: 50;
    padding: 0.35rem 0;
}
.canvas-version-dropdown--open {
    display: block;
}
.canvas-version-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.4rem 0.75rem;
    cursor: pointer;
    font-size: 0.78rem;
    color: var(--text-primary, #e2e8f0);
    transition: background 0.1s;
}
.canvas-version-item:hover {
    background: var(--hover-bg, rgba(255,255,255,0.06));
}
.canvas-version-item--current {
    background: rgba(59, 130, 246, 0.1);
}
.canvas-version-item-label {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
}
.canvas-version-item-title {
    font-weight: 500;
}
.canvas-version-item-time {
    font-size: 0.68rem;
    color: var(--text-muted, #94a3b8);
}
.canvas-version-item-restore {
    padding: 0.15rem 0.4rem;
    border-radius: 0.25rem;
    font-size: 0.68rem;
    color: rgb(96, 165, 250);
    border: 1px solid rgba(59, 130, 246, 0.3);
    background: transparent;
    cursor: pointer;
    transition: all 0.1s;
}
.canvas-version-item-restore:hover {
    background: rgba(59, 130, 246, 0.15);
}
/* ─── Live Coding Animation ──────────────────────────────────── */
.canvas-progress-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.25rem 0.75rem;
    border-top: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: var(--bg-secondary, rgba(0,0,0,0.1));
    font-size: 0.75rem;
    color: var(--text-muted, #94a3b8);
}
.canvas-progress-fill {
    flex: 1;
    height: 3px;
    background: var(--hover-bg, rgba(255,255,255,0.08));
    border-radius: 2px;
    overflow: hidden;
}
.canvas-progress-fill-inner {
    height: 100%;
    background: rgb(59, 130, 246);
    border-radius: 2px;
    transition: width 0.1s ease;
}
.canvas-progress-text {
    white-space: nowrap;
    min-width: 80px;
    text-align: right;
}
.canvas-skip-btn {
    padding: 0.15rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.7rem;
    color: var(--text-muted, #94a3b8);
    cursor: pointer;
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: transparent;
    transition: all 0.15s ease;
}
.canvas-skip-btn:hover {
    background: var(--hover-bg, rgba(255,255,255,0.08));
    color: var(--text-primary, #e2e8f0);
}
/* ─── Inline AI (M7) ──────────────────────────────────────────── */
.canvas-inline-ai-btn {
    position: absolute;
    z-index: 20;
    padding: 0.2rem 0.5rem;
    border-radius: 0.375rem;
    font-size: 0.72rem;
    font-weight: 500;
    color: rgb(96, 165, 250);
    background: var(--card-bg, rgba(15,23,42,0.95));
    border: 1px solid rgba(59, 130, 246, 0.3);
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    transition: all 0.15s ease;
}
.canvas-inline-ai-btn:hover {
    background: rgba(59, 130, 246, 0.15);
    border-color: rgba(59, 130, 246, 0.5);
}
.canvas-inline-ai-prompt {
    position: absolute;
    z-index: 25;
    display: flex;
    gap: 0.25rem;
    padding: 0.35rem;
    background: var(--card-bg, rgba(15,23,42,0.95));
    border: 1px solid rgba(59, 130, 246, 0.3);
    border-radius: 0.5rem;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
}
.canvas-inline-ai-input {
    width: 260px;
    padding: 0.3rem 0.5rem;
    border-radius: 0.375rem;
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: var(--input-bg, rgba(0,0,0,0.2));
    color: var(--text-primary, #e2e8f0);
    font-size: 0.78rem;
    outline: none;
}
.canvas-inline-ai-input:focus {
    border-color: rgba(59, 130, 246, 0.5);
}
.canvas-inline-ai-input::placeholder {
    color: var(--text-muted, #94a3b8);
}
.canvas-inline-ai-submit {
    padding: 0.3rem 0.6rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    font-weight: 500;
    color: #fff;
    background: rgb(59, 130, 246);
    border: none;
    cursor: pointer;
    transition: background 0.15s;
}
.canvas-inline-ai-submit:hover {
    background: rgb(37, 99, 235);
}
.canvas-inline-ai-submit:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
.canvas-inline-ai-cancel {
    padding: 0.3rem 0.4rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    color: var(--text-muted, #94a3b8);
    background: transparent;
    border: none;
    cursor: pointer;
}
.canvas-inline-ai-cancel:hover {
    color: var(--text-primary, #e2e8f0);
}
.canvas-inline-ai-token-badge {
    position: absolute;
    z-index: 20;
    padding: 0.15rem 0.4rem;
    border-radius: 0.25rem;
    font-size: 0.65rem;
    color: var(--text-muted, #94a3b8);
    background: var(--card-bg, rgba(15,23,42,0.9));
    border: 1px solid var(--border-primary, rgba(255,255,255,0.08));
    pointer-events: none;
    animation: canvasFadeInOut 3s ease forwards;
}
@keyframes canvasFadeInOut {
    0% { opacity: 0; transform: translateY(4px); }
    15% { opacity: 1; transform: translateY(0); }
    75% { opacity: 1; }
    100% { opacity: 0; }
}
/* ─── M8.1: Console Panel (Execution Bridge) ─── */
.canvas-console-panel {
    border-top: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: var(--code-bg, rgba(0,0,0,0.3));
    max-height: 300px;
    overflow: auto;
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 0.8rem;
}
.canvas-console-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.375rem 0.75rem;
    border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    font-size: 0.75rem;
    color: var(--text-muted, #94a3b8);
    position: sticky;
    top: 0;
    background: var(--code-bg, rgba(0,0,0,0.4));
    z-index: 1;
}
.canvas-console-label {
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
}
.canvas-console-badge {
    padding: 0.1rem 0.4rem;
    border-radius: 0.25rem;
    background: rgba(74, 222, 128, 0.15);
    color: #4ade80;
    font-size: 0.7rem;
}
.canvas-console-badge--error {
    background: rgba(248, 113, 113, 0.15);
    color: #f87171;
}
.canvas-console-time {
    color: var(--text-muted, #64748b);
    font-size: 0.7rem;
}
.canvas-console-close {
    margin-left: auto;
    cursor: pointer;
    color: var(--text-muted, #94a3b8);
    background: none;
    border: none;
    font-size: 1rem;
    padding: 0 0.25rem;
    line-height: 1;
}
.canvas-console-close:hover { color: var(--text-primary, #e2e8f0); }
.canvas-console-body {
    padding: 0.5rem 0.75rem;
    white-space: pre-wrap;
    color: var(--text-primary, #e2e8f0);
    line-height: 1.5;
}
.canvas-console-body--error { color: #f87171; }
.canvas-run-btn { color: #4ade80 !important; font-weight: 600; }
/* ─── M8.2: Sources Badge ─── */
.canvas-sources-wrapper { position: relative; }
.canvas-sources-badge { color: #c084fc !important; }
.canvas-sources-dropdown {
    position: absolute;
    top: 100%;
    right: 0;
    z-index: 50;
    min-width: 220px;
    max-width: 360px;
    max-height: 200px;
    overflow-y: auto;
    background: var(--card-bg, #1e293b);
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    border-radius: 0.5rem;
    padding: 0.5rem 0;
    box-shadow: 0 10px 25px rgba(0,0,0,0.3);
    margin-top: 0.25rem;
}
.canvas-sources-item {
    padding: 0.375rem 0.75rem;
    font-size: 0.8rem;
    color: var(--text-primary, #e2e8f0);
    border-bottom: 1px solid rgba(255,255,255,0.05);
    line-height: 1.4;
}
.canvas-sources-item:last-child { border-bottom: none; }
/* ─── M8.3: Template Gallery ─── */
.canvas-template-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0,0,0,0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(4px);
}
.canvas-template-modal {
    width: 90%;
    max-width: 700px;
    max-height: 80vh;
    background: var(--card-bg, #1e293b);
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    border-radius: 0.75rem;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 60px rgba(0,0,0,0.4);
}
.canvas-template-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.1));
}
.canvas-template-header h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
}
.canvas-template-close {
    background: none;
    border: none;
    color: var(--text-muted, #94a3b8);
    font-size: 1.25rem;
    cursor: pointer;
    padding: 0.25rem;
    line-height: 1;
}
.canvas-template-close:hover { color: var(--text-primary, #e2e8f0); }
.canvas-template-categories {
    display: flex;
    gap: 0.25rem;
    padding: 0.75rem 1.25rem;
    border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    overflow-x: auto;
}
.canvas-template-cat {
    padding: 0.375rem 0.75rem;
    border-radius: 0.375rem;
    font-size: 0.8rem;
    cursor: pointer;
    color: var(--text-muted, #94a3b8);
    background: transparent;
    border: 1px solid transparent;
    transition: all 0.15s;
    white-space: nowrap;
}
.canvas-template-cat:hover {
    background: var(--hover-bg, rgba(255,255,255,0.05));
    color: var(--text-primary, #e2e8f0);
}
.canvas-template-cat--active {
    background: rgba(59, 130, 246, 0.15);
    color: rgb(96, 165, 250);
    border-color: rgba(59, 130, 246, 0.3);
}
.canvas-template-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    padding: 1rem 1.25rem;
    overflow-y: auto;
    flex: 1;
}
.canvas-template-card {
    padding: 0.875rem;
    border-radius: 0.5rem;
    cursor: pointer;
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    background: var(--hover-bg, rgba(255,255,255,0.03));
    transition: all 0.15s;
}
.canvas-template-card:hover {
    background: var(--hover-bg-strong, rgba(255,255,255,0.08));
    border-color: rgba(59, 130, 246, 0.4);
}
.canvas-template-card-name {
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary, #e2e8f0);
    margin-bottom: 0.25rem;
}
.canvas-template-card-desc {
    font-size: 0.8rem;
    color: var(--text-muted, #94a3b8);
    line-height: 1.4;
}
.canvas-template-card-lang {
    display: inline-block;
    margin-top: 0.5rem;
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.7rem;
    background: rgba(59, 130, 246, 0.1);
    color: rgb(96, 165, 250);
}
/* Collapsed inline canvas — shown when split panel is open */
.canvas--collapsed .canvas-body,
.canvas--collapsed .canvas-tab-bar,
.canvas--collapsed .canvas-toolbar {
    display: none !important;
}
.canvas--collapsed {
    position: relative;
}
.canvas-collapsed-overlay {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 1rem;
    color: var(--text-muted, #94a3b8);
    font-size: 0.8rem;
}
.canvas-collapsed-info {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}
.canvas-collapsed-title {
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
}
.canvas-collapsed-meta {
    color: var(--text-muted, #94a3b8);
    font-size: 0.75rem;
}
.canvas-collapsed-badge {
    color: rgb(96, 165, 250);
    font-size: 0.75rem;
    white-space: nowrap;
}
/* ─── Light Theme Overrides ──────────────────────────────────── */
[data-theme="light"] .canvas-container {
    border-color: var(--border-primary);
    background: var(--card-bg);
}
[data-theme="light"] .canvas-header {
    background: var(--bg-tertiary);
    border-bottom-color: var(--border-primary);
}
[data-theme="light"] .canvas-toolbar-btn {
    border-color: var(--border-primary);
    color: var(--text-muted);
}
[data-theme="light"] .canvas-toolbar-btn:hover {
    background: var(--hover-bg-strong);
    color: var(--text-primary);
}
[data-theme="light"] .canvas-body {
    background: var(--code-bg);
}
[data-theme="light"] .canvas-fallback-code {
    background: var(--code-bg) !important;
    color: #e2e8f0;
}
[data-theme="light"] .canvas-console-panel {
    background: var(--code-bg);
}
[data-theme="light"] .canvas-console-header {
    background: var(--code-bg);
}
[data-theme="light"] .canvas-diff-header {
    background: var(--code-bg);
}
[data-theme="light"] .canvas-diff-panel {
    background: var(--code-bg);
}
[data-theme="light"] .canvas-progress-bar {
    background: var(--bg-tertiary);
    color: var(--text-muted);
}
[data-theme="light"] .canvas-collapsed-overlay {
    color: var(--text-muted);
}
[data-theme="light"] .canvas-collapsed-title {
    color: var(--text-primary);
}
[data-theme="light"] .canvas-template-modal {
    background: var(--card-bg);
    border-color: var(--border-primary);
}
[data-theme="light"] .canvas-template-card {
    border-color: var(--border-primary);
    background: var(--bg-secondary);
}
[data-theme="light"] .canvas-template-card:hover {
    background: var(--hover-bg-strong);
}
[data-theme="light"] .canvas-sources-dropdown {
    background: var(--card-bg);
    border-color: var(--border-primary);
}
[data-theme="light"] .canvas-inline-ai-btn {
    background: var(--card-bg);
    border-color: var(--border-primary);
}
[data-theme="light"] .canvas-inline-ai-input {
    background: var(--input-bg);
    color: var(--text-primary);
    border-color: var(--border-primary);
}
[data-theme="light"] #canvas-split-panel {
    background: var(--card-bg);
    border-left-color: var(--border-primary);
}
[data-theme="light"] .canvas-split-header {
    background: var(--bg-tertiary);
    border-bottom-color: var(--border-primary);
}
[data-theme="light"] .canvas-responsive-bar {
    background: var(--bg-tertiary);
    border-bottom-color: var(--border-primary);
}
[data-theme="light"] .canvas-version-dropdown {
    background: var(--card-bg);
    border-color: var(--border-primary);
}
[data-theme="light"] .canvas-md-preview code {
    background: var(--hover-bg-strong);
}
/* ─── Inline Card (Split Mode ON — compact summary in chat) ──── */
.canvas-inline-card {
    border: 1px solid rgba(96, 165, 250, 0.15);
    border-radius: 8px;
    background: linear-gradient(135deg, rgba(15,23,42,0.85) 0%, rgba(30,41,59,0.7) 100%);
    padding: 0;
    cursor: pointer;
    transition: all 0.25s ease;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.03);
}
.canvas-inline-card:hover {
    border-color: rgba(96, 165, 250, 0.4);
    box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.12), 0 4px 16px rgba(0,0,0,0.25), 0 0 20px rgba(96, 165, 250, 0.06);
    transform: translateY(-1px);
}
.canvas-inline-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.6rem 0.85rem;
    background: rgba(0,0,0,0.2);
    border-bottom: 1px solid rgba(96, 165, 250, 0.08);
}
.canvas-inline-card-title {
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    font-size: 0.78rem;
    display: flex;
    align-items: center;
    gap: 0.45rem;
    letter-spacing: 0.01em;
}
.canvas-inline-card-title svg {
    width: 15px;
    height: 15px;
    color: rgb(96, 165, 250);
    flex-shrink: 0;
    filter: drop-shadow(0 0 2px rgba(96, 165, 250, 0.4));
}
.canvas-inline-card-meta {
    color: rgba(148, 163, 184, 0.8);
    font-size: 0.6rem;
    white-space: nowrap;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-weight: 600;
    background: rgba(96, 165, 250, 0.08);
    padding: 0.15rem 0.45rem;
    border-radius: 3px;
    border: 1px solid rgba(96, 165, 250, 0.1);
}
.canvas-inline-card-preview {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.68rem;
    line-height: 1.6;
    color: rgba(148, 163, 184, 0.7);
    white-space: pre;
    overflow-y: auto;
    overflow-x: auto;
    max-height: 11rem;
    padding: 0.5rem 0.85rem;
    background: rgba(0,0,0,0.15);
    border-bottom: 1px solid rgba(255,255,255,0.03);
}
.canvas-inline-card-action {
    color: rgb(96, 165, 250);
    font-size: 0.7rem;
    font-weight: 600;
    text-align: center;
    padding: 0.45rem 0.85rem;
    background: rgba(96, 165, 250, 0.04);
    letter-spacing: 0.03em;
    transition: all 0.2s ease;
}
.canvas-inline-card:hover .canvas-inline-card-action {
    background: rgba(96, 165, 250, 0.1);
    color: rgb(147, 197, 253);
}
/* ─── Inline Compact (Split Mode OFF — limited code viewer) ──── */
.canvas-inline-compact {
    border: 1px solid var(--border-primary, rgba(255,255,255,0.06));
    border-radius: 6px;
    background: var(--card-bg, rgba(15,23,42,0.6));
    overflow: hidden;
    transition: border-color 0.2s;
}
.canvas-inline-compact-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.45rem 0.75rem;
    background: var(--bg-secondary, rgba(0,0,0,0.15));
    border-bottom: 1px solid var(--border-primary, rgba(255,255,255,0.04));
}
.canvas-inline-compact-title {
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    letter-spacing: 0.01em;
}
.canvas-inline-compact-badge {
    color: var(--text-muted, #94a3b8);
    font-size: 0.65rem;
    font-weight: 500;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}
.canvas-inline-compact-actions {
    display: flex;
    align-items: center;
    gap: 0.35rem;
}
.canvas-inline-compact-btn {
    background: none;
    border: 1px solid var(--border-primary, rgba(255,255,255,0.08));
    color: var(--text-muted, #94a3b8);
    padding: 3px 8px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.7rem;
    font-weight: 500;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    gap: 4px;
}
.canvas-inline-compact-btn:hover {
    background: var(--hover-bg, rgba(255,255,255,0.06));
    color: var(--text-primary, #e2e8f0);
    border-color: rgba(255,255,255,0.15);
}
.canvas-inline-compact-open {
    color: rgb(96, 165, 250);
    border-color: rgba(96, 165, 250, 0.2);
}
.canvas-inline-compact-open:hover {
    background: rgba(96, 165, 250, 0.1);
    color: rgb(147, 197, 253);
    border-color: rgba(96, 165, 250, 0.35);
}
.canvas-inline-compact-open svg {
    display: block;
}
.canvas-inline-compact-body {
    max-height: 300px;
    overflow: hidden;
    position: relative;
}
.canvas-inline-compact-body.expanded {
    max-height: none;
}
.canvas-inline-compact-body .cm-editor {
    max-height: inherit;
}
.canvas-inline-compact-showmore {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0.4rem;
    background: linear-gradient(to bottom, transparent, var(--card-bg, rgba(15,23,42,0.9)) 50%);
    color: rgb(96, 165, 250);
    font-size: 0.7rem;
    font-weight: 500;
    letter-spacing: 0.02em;
    cursor: pointer;
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 2.5rem;
    transition: color 0.15s;
}
.canvas-inline-compact-showmore:hover {
    color: rgb(147, 197, 253);
}
.canvas-inline-compact-body.expanded .canvas-inline-compact-showmore {
    position: static;
    background: var(--bg-secondary, rgba(0,0,0,0.12));
}
/* Light theme overrides for inline modes */
[data-theme="light"] .canvas-inline-card {
    border-color: rgba(59, 130, 246, 0.2);
    background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
    box-shadow: 0 1px 3px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.8);
}
[data-theme="light"] .canvas-inline-card:hover {
    border-color: rgba(59, 130, 246, 0.4);
    box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.12), 0 4px 12px rgba(0,0,0,0.1);
}
[data-theme="light"] .canvas-inline-card-header {
    background: rgba(0,0,0,0.03);
    border-bottom-color: rgba(59, 130, 246, 0.1);
}
[data-theme="light"] .canvas-inline-card-title svg {
    filter: none;
}
[data-theme="light"] .canvas-inline-card-meta {
    background: rgba(59, 130, 246, 0.06);
    border-color: rgba(59, 130, 246, 0.12);
    color: rgba(71, 85, 105, 0.9);
}
[data-theme="light"] .canvas-inline-card-preview {
    background: rgba(0,0,0,0.02);
    color: rgba(71, 85, 105, 0.6);
    border-bottom-color: rgba(0,0,0,0.04);
}
[data-theme="light"] .canvas-inline-card-action {
    background: rgba(59, 130, 246, 0.03);
}
[data-theme="light"] .canvas-inline-compact {
    border-color: var(--border-primary);
    background: var(--card-bg);
}
[data-theme="light"] .canvas-inline-compact-header {
    background: var(--bg-tertiary);
    border-bottom-color: var(--border-primary);
}
[data-theme="light"] .canvas-inline-compact-body {
    background: var(--code-bg);
}
`;

// Inject styles once
let _stylesInjected = false;
function injectStyles() {
    if (_stylesInjected) return;
    const style = document.createElement('style');
    style.textContent = CANVAS_STYLES;
    document.head.appendChild(style);
    _stylesInjected = true;
}

// ─── Lightweight Markdown Renderer ───────────────────────────────────────────

function renderMarkdownToHtml(md) {
    let html = md
        // Escape HTML entities
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // Code blocks (``` ... ```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
        return `<pre><code class="language-${lang || 'text'}">${code.trim()}</code></pre>`;
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Headers
    html = html.replace(/^######\s+(.+)$/gm, '<h6>$1</h6>');
    html = html.replace(/^#####\s+(.+)$/gm, '<h5>$1</h5>');
    html = html.replace(/^####\s+(.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');

    // Horizontal rule
    html = html.replace(/^---+$/gm, '<hr>');

    // Bold and italic
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // Blockquotes
    html = html.replace(/^&gt;\s+(.+)$/gm, '<blockquote>$1</blockquote>');

    // Unordered lists
    html = html.replace(/^[\s]*[-*]\s+(.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>(\n|$))+/g, (match) => `<ul>${match}</ul>`);

    // Ordered lists
    html = html.replace(/^[\s]*\d+\.\s+(.+)$/gm, '<li>$1</li>');

    // Paragraphs (lines not already wrapped in block elements)
    html = html.replace(/^(?!<[hupboa]|<li|<hr|<pre|<bl)(.+)$/gm, '<p>$1</p>');

    // Clean up empty paragraphs
    html = html.replace(/<p>\s*<\/p>/g, '');

    return html;
}

// ─── Canvas Split Mode Rendering ─────────────────────────────────────────────

/**
 * Activate split mode from an inline compact card click.
 * Turns on the header toggle, sets global state, and opens the full canvas in the split panel.
 */
async function activateSplitModeFromCard(spec) {
    // Set global state
    window.__canvasSplitMode = true;

    // Update the header toggle button appearance and localStorage
    const toggleBtn = document.getElementById('canvas-mode-toggle');
    if (toggleBtn) {
        toggleBtn.classList.add('bg-white/15', 'text-white', 'ring-1', 'ring-white/20');
        toggleBtn.classList.remove('text-gray-300');
        toggleBtn.title = 'Canvas Split Mode (On)';
    }
    localStorage.setItem('canvasSplitMode', 'on');

    // Dispatch a custom event so eventHandlers.js can sync its state object
    window.dispatchEvent(new CustomEvent('canvas-split-mode-changed', { detail: { on: true } }));

    // Open the full canvas in the split panel
    await autoPopOutCanvas(spec);
}

/**
 * Render a compact card in the chat when split mode is ON.
 * Shows title, language badge, 3-line preview, and "View in Canvas" link.
 */
function renderInlineCard(container, spec) {
    const { content, language, title, line_count } = spec;
    const lineCount = line_count || (content.match(/\n/g) || []).length + 1;
    const escaped = content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

    const card = document.createElement('div');
    card.className = 'canvas-inline-card';
    card.innerHTML = `
        <div class="canvas-inline-card-header">
            <span class="canvas-inline-card-title">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5"/>
                </svg>
                ${title || 'Canvas'}
            </span>
            <span class="canvas-inline-card-meta">${(language || '').toUpperCase()} &middot; ${lineCount} LINES</span>
        </div>
        <div class="canvas-inline-card-preview">${escaped}</div>
        <div class="canvas-inline-card-action">Expanded in side panel &rarr;</div>
    `;

    // Prevent card click when user is scrolling inside the preview area
    const previewEl = card.querySelector('.canvas-inline-card-preview');
    if (previewEl) {
        previewEl.addEventListener('click', (e) => e.stopPropagation());
    }

    card.addEventListener('click', async () => {
        const panel = document.getElementById('canvas-split-panel');
        if (panel && panel.classList.contains('canvas-split--open')) {
            panel.scrollIntoView({ behavior: 'smooth' });
        } else {
            await autoPopOutCanvas(spec);
        }
        const action = card.querySelector('.canvas-inline-card-action');
        if (action) action.textContent = 'Expanded in side panel \u2192';
    });

    container.appendChild(card);
    return card;
}

/**
 * Render a limited inline canvas when split mode is OFF.
 * Read-only CodeMirror, copy button, language badge, max-height with expand.
 */
async function renderInlineCompact(container, spec) {
    const { content, language, title, line_count } = spec;
    const lineCount = line_count || (content.match(/\n/g) || []).length + 1;

    const wrapper = document.createElement('div');
    wrapper.className = 'canvas-inline-compact';

    // Header with title + copy button
    const header = document.createElement('div');
    header.className = 'canvas-inline-compact-header';
    header.innerHTML = `
        <span class="canvas-inline-compact-title">
            ${title || 'Canvas'}
            <span class="canvas-inline-compact-badge">${language} &middot; ${lineCount} lines</span>
        </span>
    `;

    const actions = document.createElement('div');
    actions.className = 'canvas-inline-compact-actions';

    // Open in Canvas button — activates split mode + opens full canvas
    const openBtn = document.createElement('button');
    openBtn.className = 'canvas-inline-compact-btn canvas-inline-compact-open';
    openBtn.title = 'Open in Canvas';
    openBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5"/></svg>`;
    openBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        // Activate split mode globally
        activateSplitModeFromCard(spec);
    });
    actions.appendChild(openBtn);

    // Copy button
    const copyBtn = document.createElement('button');
    copyBtn.className = 'canvas-inline-compact-btn';
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(content).then(() => {
            copyBtn.textContent = 'Copied!';
            setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
        });
    });
    actions.appendChild(copyBtn);
    header.appendChild(actions);
    wrapper.appendChild(header);

    // Body — read-only code display
    const body = document.createElement('div');
    body.className = 'canvas-inline-compact-body';

    const codeTarget = document.createElement('div');
    codeTarget.style.cssText = 'min-height: 40px;';
    body.appendChild(codeTarget);

    // Show more overlay (only if content likely exceeds 300px)
    const needsExpand = lineCount > 15;
    if (needsExpand) {
        const showMore = document.createElement('div');
        showMore.className = 'canvas-inline-compact-showmore';
        showMore.textContent = `Show more (${lineCount} lines)`;
        showMore.addEventListener('click', () => {
            const isExpanded = body.classList.toggle('expanded');
            showMore.textContent = isExpanded ? 'Show less' : `Show more (${lineCount} lines)`;
        });
        body.appendChild(showMore);
    }

    wrapper.appendChild(body);
    container.appendChild(wrapper);

    // Load CM6 for read-only display
    try {
        const cm = await loadCodeMirror();
        const langMap = {
            python: cm.langPy, javascript: cm.langJs, html: cm.langHtml,
            css: cm.langCss, sql: cm.langSql, json: cm.langJson, markdown: cm.langMd,
        };
        const langExt = [];
        const langFn = langMap[language];
        if (langFn) langExt.push(langFn());

        const extensions = [
            ...cm.basicSetup,
            cm.oneDarkTheme,
            cm.oceanicStyle,
            ...langExt,
            cm.EditorView.lineWrapping,
            cm.EditorView.editable.of(false),
            cm.EditorState.readOnly.of(true),
        ].filter(Boolean);

        new cm.EditorView({
            state: cm.EditorState.create({ doc: content, extensions }),
            parent: codeTarget,
        });
    } catch (err) {
        // Fallback: plain <pre> block
        console.warn('[Canvas] CM6 failed for inline compact, using fallback:', err);
        codeTarget.innerHTML = `<pre style="margin:0; padding:0.75rem; color:#e2e8f0; font-size:0.8rem; font-family:'JetBrains Mono',monospace; white-space:pre-wrap;">${content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</pre>`;
    }

    return wrapper;
}

/**
 * Auto-open the split panel and render a full canvas there.
 * If the panel is already open, replaces the current content.
 */
async function autoPopOutCanvas(spec) {
    const panel = document.getElementById('canvas-split-panel');
    const contentArea = document.getElementById('canvas-split-content');
    const titleEl = document.getElementById('canvas-split-title');

    if (!panel || !contentArea) {
        console.error('[Canvas] Split panel elements not found');
        return;
    }

    // Update title
    if (titleEl) titleEl.textContent = spec.title || 'Canvas';

    // Clear previous inline card badges (remove "Expanded in side panel" from old cards)
    document.querySelectorAll('.canvas-inline-card-action').forEach(el => {
        if (el.textContent.includes('Expanded')) {
            el.textContent = 'View in Canvas \u2192';
        }
    });
    // Also clear any collapsed overlays from previous full canvases
    if (_collapsedSourceWrapper) {
        _collapsedSourceWrapper.classList.remove('canvas--collapsed');
        const overlay = _collapsedSourceWrapper.querySelector('.canvas-collapsed-overlay');
        if (overlay) overlay.remove();
        _collapsedSourceWrapper = null;
    }

    // Clear previous content
    contentArea.innerHTML = '';

    // Create render target
    const renderTarget = document.createElement('div');
    renderTarget.id = `canvas-split-render-${Date.now()}`;
    contentArea.appendChild(renderTarget);

    // Show the panel with animation
    panel.style.display = 'flex';
    panel.offsetHeight; // Force reflow
    panel.classList.add('canvas-split--open');

    // Render a full canvas into the split panel
    const splitCanvasState = await renderCanvasFull(renderTarget.id, spec);

    // Track split-panel canvas state for bidirectional context
    _activeSplitCanvasState = {
        title: spec.title,
        language: spec.language,
        originalContent: spec.content,
        _splitState: splitCanvasState,
        getContent() {
            if (this._splitState) return this._splitState.getContent();
            return this.originalContent;
        }
    };

    // Wire up close / pop-in buttons (once)
    if (!_splitPanelWired) {
        _splitPanelWired = true;

        const closeBtn = document.getElementById('canvas-split-close');
        const popInBtn = document.getElementById('canvas-split-pop-in');

        if (closeBtn) closeBtn.addEventListener('click', closeSplitPanel);
        if (popInBtn) popInBtn.addEventListener('click', closeSplitPanel);
    }

    // Mark the newest inline card as "expanded"
    const allCards = document.querySelectorAll('.canvas-inline-card-action');
    if (allCards.length > 0) {
        const lastCard = allCards[allCards.length - 1];
        lastCard.textContent = 'Expanded in side panel \u2192';
    }
}

// ─── Canvas Core ─────────────────────────────────────────────────────────────

/**
 * Public entry point: renders canvas with split-mode routing.
 * - Split ON: inline card in chat + full canvas in split panel
 * - Split OFF: inline compact (read-only viewer with copy)
 * - When called from split panel internals: full canvas (container starts with 'canvas-split-')
 *
 * @param {string} containerId - DOM element ID to render into
 * @param {object|string} payload - ComponentRenderPayload.spec from the backend
 */
export async function renderCanvas(containerId, payload) {
    injectStyles();

    const spec = typeof payload === 'string' ? JSON.parse(payload) : payload;

    // If called from inside the split panel, always render full
    if (containerId.startsWith('canvas-split-render-')) {
        return renderCanvasFull(containerId, spec);
    }

    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`[Canvas] Container #${containerId} not found`);
        return;
    }

    // Check global split mode state (exposed by state.js via window.__canvasSplitMode)
    const splitModeOn = window.__canvasSplitMode || false;

    if (splitModeOn) {
        // Record version even in card mode (keeps history consistent)
        recordVersion(spec.title || 'Canvas', spec.content, spec.language);

        // Render compact card inline
        renderInlineCard(container, spec);

        // Auto-open full canvas in split panel
        await autoPopOutCanvas(spec);

        return null; // No canvasState for inline cards
    } else {
        // Record version
        recordVersion(spec.title || 'Canvas', spec.content, spec.language);

        // Render inline compact (read-only viewer)
        await renderInlineCompact(container, spec);

        return null; // No editable canvasState for compact mode
    }
}

/**
 * Render the full-featured canvas (all capabilities, tabs, toolbar).
 * Used directly by the split panel and by legacy non-split-mode codepaths.
 *
 * @param {string} containerId - DOM element ID to render into
 * @param {object} spec - Parsed canvas spec
 */
async function renderCanvasFull(containerId, spec) {
    const { content, language, title, previewable, line_count, file_extension, sources } = spec;

    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`[Canvas] Container #${containerId} not found`);
        return;
    }

    // Version tracking
    const canvasTitle = title || 'Canvas';
    const versionInfo = recordVersion(canvasTitle, content, language);

    // Canvas state — shared across all capabilities
    const canvasState = {
        content,
        language,
        title: canvasTitle,
        previewable: !!previewable,
        lineCount: line_count || (content.match(/\n/g) || []).length + 1,
        fileExtension: file_extension || '.txt',
        sources: sources || null,
        container,
        activeTab: 'code',
        _editorView: null,
        // Version state
        versions: versionInfo.versions,
        previousContent: versionInfo.previousContent,
        versionNumber: versionInfo.versionNumber,
        getContent() {
            if (this._editorView) {
                return this._editorView.state.doc.toString();
            }
            return this.content;
        },
    };

    // Build the DOM structure
    const wrapper = document.createElement('div');
    wrapper.className = 'canvas-container';

    // Header
    const header = document.createElement('div');
    header.className = 'canvas-header';

    const headerLeft = document.createElement('div');
    headerLeft.className = 'canvas-header-left';

    const titleEl = document.createElement('span');
    titleEl.className = 'canvas-title';
    titleEl.textContent = canvasState.title;
    headerLeft.appendChild(titleEl);

    // Tab bar
    const tabBar = document.createElement('div');
    tabBar.className = 'canvas-tab-bar';
    headerLeft.appendChild(tabBar);

    header.appendChild(headerLeft);

    // Toolbar area
    const toolbar = document.createElement('div');
    toolbar.className = 'canvas-toolbar';
    header.appendChild(toolbar);

    wrapper.appendChild(header);

    // Body (panels go here)
    const body = document.createElement('div');
    body.className = 'canvas-body';
    wrapper.appendChild(body);

    container.appendChild(wrapper);

    // Store references in state
    canvasState._tabBar = tabBar;
    canvasState._toolbar = toolbar;
    canvasState._body = body;
    canvasState._panels = {};

    // Filter capabilities for this language
    const activeCaps = _capabilities.filter(
        cap => cap.languages.includes('*') || cap.languages.includes(language)
    );

    // Initialize capabilities
    for (const cap of activeCaps) {
        if (cap.init) {
            await cap.init(canvasState);
        }
    }

    // Create tabs for tab-type capabilities (respecting shouldCreateTab if defined)
    const tabCaps = activeCaps.filter(c =>
        c.type === 'tab' && (!c.shouldCreateTab || c.shouldCreateTab(canvasState))
    );
    for (const cap of tabCaps) {
        // Create tab button
        const tabBtn = document.createElement('button');
        tabBtn.className = 'canvas-tab';
        tabBtn.textContent = cap.label;
        tabBtn.dataset.tabId = cap.id;
        tabBtn.addEventListener('click', () => switchTab(canvasState, cap.id, tabCaps));
        tabBar.appendChild(tabBtn);

        // Create panel
        const panel = document.createElement('div');
        panel.className = 'canvas-panel';
        panel.dataset.tabId = cap.id;
        body.appendChild(panel);
        canvasState._panels[cap.id] = panel;
    }

    // Render toolbar capabilities
    const toolbarCaps = activeCaps.filter(c => c.type === 'toolbar');
    for (const cap of toolbarCaps) {
        if (cap.render) {
            cap.render(toolbar, content, language, canvasState);
        }
    }

    // Activate default tab (code_editor)
    if (tabCaps.length > 0) {
        const defaultTab = tabCaps[0].id;
        switchTab(canvasState, defaultTab, tabCaps);
    }

    // Clear live mode flag after canvas is set up (animation runs async)
    if (window.__canvasLiveMode) {
        window.__canvasLiveMode = false;
    }

    return canvasState;
}

/**
 * Switch active tab in the canvas.
 */
function switchTab(canvasState, tabId, tabCaps) {
    canvasState.activeTab = tabId;

    // Update tab button styles
    const tabButtons = canvasState._tabBar.querySelectorAll('.canvas-tab');
    tabButtons.forEach(btn => {
        btn.classList.toggle('canvas-tab--active', btn.dataset.tabId === tabId);
    });

    // Show/hide panels and render if needed
    for (const cap of tabCaps) {
        const panel = canvasState._panels[cap.id];
        if (!panel) continue;

        if (cap.id === tabId) {
            panel.classList.add('canvas-panel--active');
            // Render panel content if it hasn't been rendered yet
            if (!panel.dataset.rendered && cap.render) {
                try {
                    cap.render(panel, canvasState.getContent(), canvasState.language, canvasState);
                } catch (err) {
                    console.error(`[Canvas] Capability '${cap.id}' render failed:`, err);
                }
                panel.dataset.rendered = 'true';
            } else if (cap.id !== 'code_editor' && cap.refresh) {
                // Refresh preview panels with latest content from editor
                try {
                    cap.refresh(panel, canvasState.getContent(), canvasState.language, canvasState);
                } catch (err) {
                    console.error(`[Canvas] Capability '${cap.id}' refresh failed:`, err);
                }
            }
        } else {
            panel.classList.remove('canvas-panel--active');
        }
    }
}

// ─── Live Coding Animation Engine ───────────────────────────────────────────

/**
 * Animate code insertion line-by-line into a CodeMirror 6 editor.
 * Provides syntax-highlighted streaming — better than competitors
 * which show plain text during generation.
 *
 * @param {EditorView} view - CodeMirror 6 editor (starts empty)
 * @param {string} fullContent - Complete code to animate
 * @param {Object} canvasState - Canvas state for progress UI + tab switching
 * @param {Object} readOnlyCompartment - CM6 Compartment for toggling read-only
 * @param {Object} cm - CodeMirror modules cache
 * @returns {Promise<void>}
 */
async function animateCodeInsertion(view, fullContent, canvasState, readOnlyCompartment, cm) {
    const lines = fullContent.split('\n');
    const totalLines = lines.length;

    // Adaptive speed: aim for 2-4 seconds total animation
    let batchSize, delayMs;
    if (totalLines <= 30) {
        batchSize = 1;
        delayMs = 80;
    } else if (totalLines <= 100) {
        batchSize = 1;
        delayMs = Math.max(20, Math.floor(3000 / totalLines));
    } else {
        batchSize = Math.ceil(totalLines / 100);
        delayMs = 20;
    }

    // Build progress bar UI
    const progressBar = document.createElement('div');
    progressBar.className = 'canvas-progress-bar';
    progressBar.innerHTML = `
        <div class="canvas-progress-fill">
            <div class="canvas-progress-fill-inner" style="width: 0%"></div>
        </div>
        <span class="canvas-progress-text">0 / ${totalLines} lines</span>
        <button class="canvas-skip-btn">Skip</button>
    `;

    // Insert progress bar after the canvas body
    const body = canvasState._body;
    if (body && body.parentElement) {
        body.parentElement.insertBefore(progressBar, body.nextSibling);
    }

    const fillInner = progressBar.querySelector('.canvas-progress-fill-inner');
    const progressText = progressBar.querySelector('.canvas-progress-text');
    const skipBtn = progressBar.querySelector('.canvas-skip-btn');

    let skipped = false;
    skipBtn.addEventListener('click', () => { skipped = true; });

    let insertedLines = 0;
    let userHasScrolled = false;

    // Detect manual scroll (disable auto-scroll if user scrolls up)
    const cmScroller = view.dom.querySelector('.cm-scroller');
    const scrollHandler = () => {
        if (!cmScroller) return;
        const atBottom = cmScroller.scrollHeight - cmScroller.scrollTop - cmScroller.clientHeight < 40;
        userHasScrolled = !atBottom;
    };
    if (cmScroller) cmScroller.addEventListener('scroll', scrollHandler);

    // Insert lines in batches
    for (let i = 0; i < totalLines && !skipped; i += batchSize) {
        const batch = lines.slice(i, Math.min(i + batchSize, totalLines));
        const text = (i === 0 ? '' : '\n') + batch.join('\n');

        // CM6 transaction: insert at end of document
        const docLen = view.state.doc.length;
        view.dispatch({
            changes: { from: docLen, insert: text },
        });

        insertedLines = Math.min(i + batchSize, totalLines);
        const pct = Math.round((insertedLines / totalLines) * 100);
        fillInner.style.width = `${pct}%`;
        progressText.textContent = `${insertedLines} / ${totalLines} lines`;

        // Auto-scroll to bottom (unless user scrolled up)
        if (!userHasScrolled && cmScroller) {
            cmScroller.scrollTop = cmScroller.scrollHeight;
        }

        await new Promise(r => setTimeout(r, delayMs));
    }

    // If skipped, insert remaining content at once
    if (skipped && insertedLines < totalLines) {
        const remaining = lines.slice(insertedLines);
        const text = (insertedLines === 0 ? '' : '\n') + remaining.join('\n');
        const docLen = view.state.doc.length;
        view.dispatch({
            changes: { from: docLen, insert: text },
        });
    }

    // Clean up progress bar
    progressBar.remove();

    // Remove scroll listener
    if (cmScroller) cmScroller.removeEventListener('scroll', scrollHandler);

    // Make editor writable after animation
    if (readOnlyCompartment && cm) {
        view.dispatch({
            effects: readOnlyCompartment.reconfigure(cm.EditorState.readOnly.of(false)),
        });
    }

    // Auto-switch to Preview tab for HTML after brief delay
    if (canvasState.language === 'html' && canvasState._tabBar) {
        setTimeout(() => {
            const previewBtn = canvasState._tabBar.querySelector('[data-tab-id="html_preview"]');
            if (previewBtn) previewBtn.click();
        }, 600);
    }
}

// ─── Inline AI Selection (M7) ───────────────────────────────────────────────

/**
 * Show the floating "Ask AI" button near the end of a text selection.
 */
function showInlineAIButton(canvasState, view, coords) {
    let btn = canvasState._inlineAIBtn;
    if (!btn) {
        btn = document.createElement('button');
        btn.className = 'canvas-inline-ai-btn';
        btn.textContent = 'Ask AI';
        btn.addEventListener('mousedown', (e) => {
            e.preventDefault(); // Prevent selection from being lost
            showInlineAIPrompt(canvasState, view);
        });
        canvasState._inlineAIBtn = btn;
    }

    // Position relative to editor container
    const editorRect = view.dom.getBoundingClientRect();
    btn.style.left = `${coords.left - editorRect.left}px`;
    btn.style.top = `${coords.bottom - editorRect.top + 4}px`;

    if (!btn.parentElement) {
        view.dom.style.position = 'relative';
        view.dom.appendChild(btn);
    }
    btn.style.display = '';
}

/**
 * Hide the floating "Ask AI" button and dismiss any open prompt.
 */
function hideInlineAIButton(canvasState) {
    if (canvasState._inlineAIBtn) {
        canvasState._inlineAIBtn.style.display = 'none';
    }
    hideInlineAIPrompt(canvasState);
}

/**
 * Show the inline AI prompt input near the selection.
 */
function showInlineAIPrompt(canvasState, view) {
    // Hide the button
    if (canvasState._inlineAIBtn) {
        canvasState._inlineAIBtn.style.display = 'none';
    }

    const sel = view.state.selection.main;
    if (sel.empty) return;

    const coords = view.coordsAtPos(sel.to);
    if (!coords) return;
    const editorRect = view.dom.getBoundingClientRect();

    let prompt = canvasState._inlineAIPrompt;
    if (!prompt) {
        prompt = document.createElement('div');
        prompt.className = 'canvas-inline-ai-prompt';
        prompt.innerHTML = `
            <input type="text" class="canvas-inline-ai-input"
                   placeholder="e.g. Add error handling, Make async..." />
            <button class="canvas-inline-ai-submit">Go</button>
            <button class="canvas-inline-ai-cancel">\u2715</button>
        `;
        canvasState._inlineAIPrompt = prompt;

        const input = prompt.querySelector('.canvas-inline-ai-input');
        const submitBtn = prompt.querySelector('.canvas-inline-ai-submit');
        const cancelBtn = prompt.querySelector('.canvas-inline-ai-cancel');

        const submit = () => {
            const instruction = input.value.trim();
            if (!instruction) return;
            const currentSel = view.state.selection.main;
            const selectedText = view.state.doc.sliceString(currentSel.from, currentSel.to);
            if (!selectedText) return;
            executeInlineAI(canvasState, view, currentSel.from, currentSel.to, selectedText, instruction);
        };

        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); submit(); }
            if (e.key === 'Escape') hideInlineAIPrompt(canvasState);
        });
        // Prevent mousedown from blurring editor and losing selection
        prompt.addEventListener('mousedown', e => e.preventDefault());
        submitBtn.addEventListener('click', submit);
        cancelBtn.addEventListener('click', () => hideInlineAIPrompt(canvasState));
    }

    // Position
    prompt.style.left = `${coords.left - editorRect.left}px`;
    prompt.style.top = `${coords.bottom - editorRect.top + 4}px`;

    if (!prompt.parentElement) {
        view.dom.appendChild(prompt);
    }
    prompt.style.display = '';

    const input = prompt.querySelector('.canvas-inline-ai-input');
    input.value = '';
    input.placeholder = 'e.g. Add error handling, Make async...';
    input.disabled = false;
    const submitBtn = prompt.querySelector('.canvas-inline-ai-submit');
    submitBtn.textContent = 'Go';
    submitBtn.disabled = false;

    // Focus after a microtask to avoid CM6 re-focus
    setTimeout(() => input.focus(), 0);
}

/**
 * Hide the inline AI prompt input.
 */
function hideInlineAIPrompt(canvasState) {
    if (canvasState._inlineAIPrompt) {
        canvasState._inlineAIPrompt.style.display = 'none';
    }
}

/**
 * Execute an inline AI modification: send selected code + instruction to the
 * lightweight backend endpoint and replace the selection with the result.
 */
async function executeInlineAI(canvasState, view, from, to, selectedText, instruction) {
    const prompt = canvasState._inlineAIPrompt;
    const input = prompt.querySelector('.canvas-inline-ai-input');
    const submitBtn = prompt.querySelector('.canvas-inline-ai-submit');

    // Loading state
    input.disabled = true;
    submitBtn.textContent = '...';
    submitBtn.disabled = true;

    try {
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch('/api/v1/canvas/inline-ai', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                selected_code: selectedText,
                instruction,
                full_content: canvasState.getContent(),
                language: canvasState.language,
            }),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ message: response.statusText }));
            throw new Error(err.message || 'Request failed');
        }

        const result = await response.json();
        const modifiedCode = result.modified_code;

        // Apply replacement as a single CM6 transaction (Ctrl+Z undoes atomically)
        view.dispatch({
            changes: { from, to, insert: modifiedCode },
        });

        // Show token feedback badge
        showInlineAITokenBadge(view, from, result.input_tokens, result.output_tokens);

        hideInlineAIPrompt(canvasState);

    } catch (err) {
        // Show error in the input field
        input.value = '';
        input.placeholder = `Error: ${err.message}`;
        input.disabled = false;
        submitBtn.textContent = 'Go';
        submitBtn.disabled = false;
        setTimeout(() => {
            input.placeholder = 'e.g. Add error handling, Make async...';
        }, 3000);
    }
}

/**
 * Show a brief token count badge near the edit position, fading out after 3s.
 */
function showInlineAITokenBadge(view, pos, inputTokens, outputTokens) {
    const coords = view.coordsAtPos(Math.min(pos, view.state.doc.length));
    if (!coords) return;

    const badge = document.createElement('span');
    badge.className = 'canvas-inline-ai-token-badge';
    badge.textContent = `${inputTokens} in / ${outputTokens} out`;

    const editorRect = view.dom.getBoundingClientRect();
    badge.style.left = `${coords.left - editorRect.left}px`;
    badge.style.top = `${coords.bottom - editorRect.top + 4}px`;

    view.dom.appendChild(badge);
    setTimeout(() => badge.remove(), 3000);
}

// ─── Capability: CodeEditor ──────────────────────────────────────────────────

registerCapability({
    id: 'code_editor',
    label: 'Code',
    type: 'tab',
    languages: ['*'],

    _cm: null,

    async init(state) {
        this._cm = await loadCodeMirror();
    },

    render(panel, content, language, state) {
        if (this._cm) {
            try {
                const isLive = window.__canvasLiveMode === true;
                const langExt = getCmLanguageExt(this._cm, language);

                // For live mode: create a read-only compartment so we can toggle after animation
                const readOnlyCompartment = isLive ? new this._cm.Compartment() : null;
                // basicSetup is an array of extensions (constructed in loadCodeMirror)
                // oneDarkTheme = editor chrome (bg, cursor, selection, gutters)
                // oceanicStyle = syntax token colors (blue/teal palette)
                const extensions = [
                    ...this._cm.basicSetup,
                    this._cm.oneDarkTheme,
                    this._cm.oceanicStyle,
                    ...langExt,
                    this._cm.EditorView.lineWrapping,
                ].filter(Boolean); // Remove any undefined entries

                if (isLive && readOnlyCompartment) {
                    extensions.push(readOnlyCompartment.of(this._cm.EditorState.readOnly.of(true)));
                }

                // Inline AI: selection listener (skip during live animation)
                if (!isLive && this._cm.EditorView.updateListener) {
                    const cm = this._cm;
                    extensions.push(cm.EditorView.updateListener.of(update => {
                        if (update.selectionSet) {
                            const sel = update.state.selection.main;
                            if (sel.empty) {
                                hideInlineAIButton(state);
                            } else {
                                const coords = update.view.coordsAtPos(sel.to);
                                if (coords) {
                                    showInlineAIButton(state, update.view, coords);
                                }
                            }
                        }
                    }));
                }

                // CodeMirror 6 — start empty for live animation, full content otherwise
                const view = new this._cm.EditorView({
                    doc: isLive ? '' : content,
                    extensions,
                    parent: panel,
                });
                state._editorView = view;

                // Trigger live coding animation
                if (isLive && content) {
                    animateCodeInsertion(view, content, state, readOnlyCompartment, this._cm);
                }
                return; // CM6 succeeded
            } catch (err) {
                console.error('[Canvas] CodeMirror 6 render failed, falling back to Prism.js:', err);
                panel.innerHTML = ''; // Clear any partial CM6 DOM
                // Fall through to Prism.js fallback below
            }
        }

        // Prism.js fallback — read-only with syntax highlighting
        const pre = document.createElement('pre');
        pre.className = 'canvas-fallback-code';
        const code = document.createElement('code');
        code.className = `language-${language}`;
        code.textContent = content;
        pre.appendChild(code);
        panel.appendChild(pre);

        // Highlight if Prism is available
        if (typeof Prism !== 'undefined') {
            try { Prism.highlightElement(code); } catch (_) {}
        }
    },

    getState(state) {
        return { content: state.getContent() };
    },

    destroy(state) {
        if (state._editorView) {
            state._editorView.destroy();
            state._editorView = null;
        }
    },
});

// ─── Capability: HtmlPreview (with Responsive Viewport Toggle) ──────────────

const VIEWPORTS = [
    { id: 'desktop', label: 'Desktop', icon: '🖥', width: null, height: 500, description: '100%' },
    { id: 'tablet',  label: 'Tablet',  icon: '⊟', width: 768,  height: 1024, description: '768 × 1024' },
    { id: 'mobile',  label: 'Mobile',  icon: '⊡', width: 375,  height: 667,  description: '375 × 667' },
];

registerCapability({
    id: 'html_preview',
    label: 'Preview',
    type: 'tab',
    languages: ['html'],

    _viewport: 'desktop',

    init() {
        this._viewport = 'desktop';
    },

    render(panel, content) {
        // Viewport toggle bar
        const bar = document.createElement('div');
        bar.className = 'canvas-responsive-bar';

        const dimensionLabel = document.createElement('span');
        dimensionLabel.className = 'canvas-viewport-label';

        for (const vp of VIEWPORTS) {
            const btn = document.createElement('button');
            btn.className = `canvas-viewport-btn${vp.id === this._viewport ? ' canvas-viewport-btn--active' : ''}`;
            btn.textContent = `${vp.icon} ${vp.label}`;
            btn.dataset.viewport = vp.id;
            btn.addEventListener('click', () => {
                this._viewport = vp.id;
                // Update button states
                bar.querySelectorAll('.canvas-viewport-btn').forEach(b =>
                    b.classList.toggle('canvas-viewport-btn--active', b.dataset.viewport === vp.id)
                );
                this._applyViewport(wrapper, iframe, vp.id, dimensionLabel);
            });
            bar.appendChild(btn);
        }

        bar.appendChild(dimensionLabel);
        panel.appendChild(bar);

        // Wrapper for scaling
        const wrapper = document.createElement('div');
        wrapper.className = 'canvas-responsive-wrapper';

        const iframe = document.createElement('iframe');
        iframe.className = 'canvas-preview-iframe';
        iframe.sandbox = 'allow-scripts';
        iframe.srcdoc = content;

        wrapper.appendChild(iframe);
        panel.appendChild(wrapper);

        // Apply initial viewport
        this._applyViewport(wrapper, iframe, this._viewport, dimensionLabel);
    },

    _applyViewport(wrapper, iframe, viewportId, dimensionLabel) {
        const vp = VIEWPORTS.find(v => v.id === viewportId);
        if (!vp) return;

        if (!vp.width) {
            // Desktop — full width, no scaling
            iframe.style.width = '100%';
            iframe.style.height = `${vp.height}px`;
            iframe.style.transform = 'none';
            dimensionLabel.textContent = 'Desktop — 100%';
        } else {
            // Constrained viewport — set fixed width, scale to fit
            const containerWidth = wrapper.clientWidth - 32; // minus padding
            const scale = Math.min(1, containerWidth / vp.width);

            iframe.style.width = `${vp.width}px`;
            iframe.style.height = `${vp.height}px`;
            iframe.style.transform = `scale(${scale})`;
            iframe.style.transformOrigin = 'top center';

            // Adjust wrapper height to account for scale
            wrapper.style.minHeight = `${vp.height * scale + 32}px`;

            const pct = Math.round(scale * 100);
            dimensionLabel.textContent = `${vp.description} (${pct}%)`;
        }
    },

    refresh(panel, content) {
        panel.innerHTML = '';
        panel.dataset.rendered = '';
        this.render(panel, content);
        panel.dataset.rendered = 'true';
    },

    destroy() {},
});

// ─── Capability: MarkdownPreview ─────────────────────────────────────────────

registerCapability({
    id: 'markdown_preview',
    label: 'Preview',
    type: 'tab',
    languages: ['markdown'],

    init() {},

    render(panel, content) {
        const div = document.createElement('div');
        div.className = 'canvas-md-preview';
        div.innerHTML = renderMarkdownToHtml(content);
        panel.appendChild(div);
    },

    refresh(panel, content) {
        panel.innerHTML = '';
        panel.dataset.rendered = '';
        this.render(panel, content);
        panel.dataset.rendered = 'true';
    },

    destroy() {},
});

// ─── Capability: SvgPreview ──────────────────────────────────────────────────

registerCapability({
    id: 'svg_preview',
    label: 'Preview',
    type: 'tab',
    languages: ['svg'],

    init() {},

    render(panel, content) {
        // Sanitize: strip script tags and event handlers
        const sanitized = content
            .replace(/<script[\s\S]*?<\/script>/gi, '')
            .replace(/\bon\w+\s*=\s*["'][^"']*["']/gi, '');
        const div = document.createElement('div');
        div.className = 'canvas-svg-preview';
        div.innerHTML = sanitized;
        panel.appendChild(div);
    },

    refresh(panel, content) {
        panel.innerHTML = '';
        panel.dataset.rendered = '';
        this.render(panel, content);
        panel.dataset.rendered = 'true';
    },

    destroy() {},
});

// ─── Capability: DiffView ────────────────────────────────────────────────────

registerCapability({
    id: 'diff_view',
    label: 'Changes',
    type: 'tab',
    languages: ['*'],

    _hasPrevious: false,

    init(state) {
        // Only register this tab if there is a previous version to diff against
        this._hasPrevious = !!state.previousContent;
    },

    // Override: only create tab when there's something to diff
    shouldCreateTab(state) {
        return this._hasPrevious;
    },

    render(panel, content, language, state) {
        if (!state.previousContent) {
            panel.innerHTML = '<div style="padding:1rem;color:var(--text-muted)">No previous version to compare.</div>';
            return;
        }

        const diff = computeLineDiff(state.previousContent, content);
        const stats = diffStats(diff);

        const container = document.createElement('div');
        container.className = 'canvas-diff-container';

        // Header with stats
        const header = document.createElement('div');
        header.className = 'canvas-diff-header';
        header.innerHTML = `
            <div class="canvas-diff-stat">
                <span class="canvas-diff-stat-added">+${stats.added} added</span>
                <span class="canvas-diff-stat-removed">\u2212${stats.removed} removed</span>
            </div>
            <div style="display:flex;gap:4rem;">
                <span class="canvas-diff-label">Previous (v${state.versionNumber - 1})</span>
                <span class="canvas-diff-label">Current (v${state.versionNumber})</span>
            </div>
        `;
        container.appendChild(header);

        // Side-by-side panels
        const panels = document.createElement('div');
        panels.className = 'canvas-diff-panels';

        const oldPanel = document.createElement('div');
        oldPanel.className = 'canvas-diff-panel canvas-diff-panel--old';

        const newPanel = document.createElement('div');
        newPanel.className = 'canvas-diff-panel canvas-diff-panel--new';

        // Build line-by-line display
        for (const entry of diff) {
            if (entry.type === 'equal') {
                oldPanel.appendChild(makeDiffLine(entry.oldLineNum, entry.line, 'equal'));
                newPanel.appendChild(makeDiffLine(entry.newLineNum, entry.line, 'equal'));
            } else if (entry.type === 'removed') {
                oldPanel.appendChild(makeDiffLine(entry.oldLineNum, entry.line, 'removed'));
                newPanel.appendChild(makeDiffLine('', '', 'empty'));
            } else if (entry.type === 'added') {
                oldPanel.appendChild(makeDiffLine('', '', 'empty'));
                newPanel.appendChild(makeDiffLine(entry.newLineNum, entry.line, 'added'));
            }
        }

        panels.appendChild(oldPanel);
        panels.appendChild(newPanel);
        container.appendChild(panels);
        panel.appendChild(container);

        // Synchronized scrolling
        let syncing = false;
        const syncScroll = (source, target) => {
            if (syncing) return;
            syncing = true;
            target.scrollTop = source.scrollTop;
            target.scrollLeft = source.scrollLeft;
            syncing = false;
        };
        oldPanel.addEventListener('scroll', () => syncScroll(oldPanel, newPanel));
        newPanel.addEventListener('scroll', () => syncScroll(newPanel, oldPanel));
    },

    destroy() {},
});

function makeDiffLine(lineNum, text, type) {
    const line = document.createElement('div');
    line.className = `canvas-diff-line canvas-diff-line--${type}`;

    const num = document.createElement('span');
    num.className = 'canvas-diff-linenum';
    num.textContent = lineNum;

    const txt = document.createElement('span');
    txt.className = `canvas-diff-text canvas-diff-text--${type}`;
    txt.textContent = text;

    line.appendChild(num);
    line.appendChild(txt);
    return line;
}

// ─── Capability: VersionHistory ──────────────────────────────────────────────

registerCapability({
    id: 'version_history',
    label: '',
    type: 'toolbar',
    languages: ['*'],

    init() {},

    render(toolbar, content, language, state) {
        // Only show when there are multiple versions
        if (!state.versions || state.versions.length < 2) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'canvas-version-wrapper';

        // Button with version count badge
        const btn = document.createElement('button');
        btn.className = 'canvas-version-btn';
        btn.innerHTML = `History <span class="canvas-version-badge">${state.versions.length}</span>`;

        // Dropdown
        const dropdown = document.createElement('div');
        dropdown.className = 'canvas-version-dropdown';

        for (let i = state.versions.length - 1; i >= 0; i--) {
            const v = state.versions[i];
            const isCurrent = i === state.versions.length - 1;
            const item = document.createElement('div');
            item.className = `canvas-version-item${isCurrent ? ' canvas-version-item--current' : ''}`;

            const label = document.createElement('div');
            label.className = 'canvas-version-item-label';

            const titleSpan = document.createElement('span');
            titleSpan.className = 'canvas-version-item-title';
            titleSpan.textContent = `Version ${i + 1}${isCurrent ? ' (current)' : ''}`;

            const timeSpan = document.createElement('span');
            timeSpan.className = 'canvas-version-item-time';
            const date = new Date(v.timestamp);
            timeSpan.textContent = `Turn ${v.turnIndex} \u00b7 ${date.toLocaleTimeString()}`;

            label.appendChild(titleSpan);
            label.appendChild(timeSpan);
            item.appendChild(label);

            // Restore button for non-current versions
            if (!isCurrent) {
                const restoreBtn = document.createElement('button');
                restoreBtn.className = 'canvas-version-item-restore';
                restoreBtn.textContent = 'Restore';
                restoreBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    restoreVersion(state, v.content);
                    dropdown.classList.remove('canvas-version-dropdown--open');
                });
                item.appendChild(restoreBtn);
            }

            // Click to view version (sets editor content read-only preview)
            item.addEventListener('click', () => {
                if (!isCurrent) {
                    previewVersion(state, v.content, i + 1);
                }
                dropdown.classList.remove('canvas-version-dropdown--open');
            });

            dropdown.appendChild(item);
        }

        // Toggle dropdown
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('canvas-version-dropdown--open');
        });

        // Close on outside click
        document.addEventListener('click', () => {
            dropdown.classList.remove('canvas-version-dropdown--open');
        });
        wrapper.addEventListener('click', (e) => e.stopPropagation());

        wrapper.appendChild(btn);
        wrapper.appendChild(dropdown);
        toolbar.appendChild(wrapper);
    },

    destroy() {},
});

/**
 * Restore a previous version into the editor.
 */
function restoreVersion(state, content) {
    if (state._editorView) {
        const transaction = state._editorView.state.update({
            changes: {
                from: 0,
                to: state._editorView.state.doc.length,
                insert: content,
            },
        });
        state._editorView.dispatch(transaction);
    }
    state.content = content;
}

/**
 * Preview a historical version (temporarily replace editor content).
 */
function previewVersion(state, content, versionNum) {
    if (state._editorView) {
        const transaction = state._editorView.state.update({
            changes: {
                from: 0,
                to: state._editorView.state.doc.length,
                insert: content,
            },
        });
        state._editorView.dispatch(transaction);
    }

    // Switch to code tab to show the version
    const codeTab = state._tabBar?.querySelector('[data-tab-id="code_editor"]');
    if (codeTab) codeTab.click();
}

// ─── Split-Screen Panel Management ──────────────────────────────────────────

/** Track whether split-panel close/pop-in listeners are wired up */
let _splitPanelWired = false;

/** Track the active split-panel canvas state for bidirectional context */
let _activeSplitCanvasState = null;
/** Track the collapsed inline canvas wrapper for restore on split-panel close */
let _collapsedSourceWrapper = null;

/**
 * Open the canvas in the side-by-side split-screen panel.
 * Re-renders the full canvas (with all capabilities) into #canvas-split-content.
 */
async function popOutCanvas(state) {
    const panel = document.getElementById('canvas-split-panel');
    const contentArea = document.getElementById('canvas-split-content');
    const titleEl = document.getElementById('canvas-split-title');

    if (!panel || !contentArea) {
        console.error('[Canvas] Split panel elements not found');
        return;
    }

    // Update title
    if (titleEl) titleEl.textContent = state.title || 'Canvas';

    // Clear previous content
    contentArea.innerHTML = '';

    // Create a render target inside the split panel
    const renderTarget = document.createElement('div');
    renderTarget.id = `canvas-split-render-${Date.now()}`;
    contentArea.appendChild(renderTarget);

    // Show the panel with animation
    panel.style.display = 'flex';
    // Force reflow so transition triggers
    panel.offsetHeight; // eslint-disable-line no-unused-expressions
    panel.classList.add('canvas-split--open');

    // Render a full canvas into the split panel
    const spec = {
        content: state.getContent(),
        language: state.language,
        title: state.title,
        previewable: state.previewable,
        line_count: state.lineCount,
        file_extension: state.fileExtension,
    };

    // Use renderCanvas to get the full capability experience in the split panel
    const splitCanvasState = await renderCanvas(renderTarget.id, spec);

    // Track split-panel canvas state for bidirectional context
    _activeSplitCanvasState = {
        title: state.title,
        language: state.language,
        originalContent: state.getContent(),
        _splitState: splitCanvasState,
        getContent() {
            // Read live content from the split-panel's CodeMirror editor
            if (this._splitState) return this._splitState.getContent();
            return this.originalContent;
        }
    };

    // Wire up close / pop-in buttons (once)
    if (!_splitPanelWired) {
        _splitPanelWired = true;

        const closeBtn = document.getElementById('canvas-split-close');
        const popInBtn = document.getElementById('canvas-split-pop-in');

        if (closeBtn) {
            closeBtn.addEventListener('click', closeSplitPanel);
        }
        if (popInBtn) {
            popInBtn.addEventListener('click', closeSplitPanel);
        }
    }

    // Collapse the source inline canvas to a compact overview card
    const sourceWrapper = state.container?.querySelector('.canvas-container');
    if (sourceWrapper) {
        // Remove any previous overlay (in case of re-expand)
        const existingOverlay = sourceWrapper.querySelector('.canvas-collapsed-overlay');
        if (existingOverlay) existingOverlay.remove();

        const overlay = document.createElement('div');
        overlay.className = 'canvas-collapsed-overlay';
        overlay.innerHTML = `
            <div class="canvas-collapsed-info">
                <span class="canvas-collapsed-title">${state.title || 'Canvas'}</span>
                <span class="canvas-collapsed-meta">${state.language} · ${state.lineCount} lines</span>
            </div>
            <span class="canvas-collapsed-badge">Expanded in side panel →</span>
        `;
        overlay.style.cursor = 'pointer';
        overlay.addEventListener('click', () => {
            document.getElementById('canvas-split-panel')?.scrollIntoView({ behavior: 'smooth' });
        });

        sourceWrapper.appendChild(overlay);
        sourceWrapper.classList.add('canvas--collapsed');
        _collapsedSourceWrapper = sourceWrapper;
    }
}

/**
 * Close the split-screen canvas panel.
 */
export function closeSplitPanel() {
    const panel = document.getElementById('canvas-split-panel');
    if (!panel) return;

    // Clear bidirectional context tracking
    _activeSplitCanvasState = null;

    // Restore collapsed inline canvas
    if (_collapsedSourceWrapper) {
        _collapsedSourceWrapper.classList.remove('canvas--collapsed');
        const overlay = _collapsedSourceWrapper.querySelector('.canvas-collapsed-overlay');
        if (overlay) overlay.remove();
        _collapsedSourceWrapper = null;
    }

    panel.classList.remove('canvas-split--open');

    // After transition, hide completely and clear content
    const onTransitionEnd = () => {
        panel.removeEventListener('transitionend', onTransitionEnd);
        if (!panel.classList.contains('canvas-split--open')) {
            panel.style.display = 'none';
            const contentArea = document.getElementById('canvas-split-content');
            if (contentArea) contentArea.innerHTML = '';
        }
    };
    panel.addEventListener('transitionend', onTransitionEnd);
}

// ─── MCP Execution Bridge (M8.1) ─────────────────────────────────────────────

/**
 * Execute canvas code via MCP server (SQL only).
 * Sends code to POST /v1/canvas/execute and displays results in console panel.
 */
async function executeCode(state) {
    const code = state.getContent();
    if (!code.trim()) return;

    if (state._runBtn) {
        state._runBtn.textContent = '\u23F3 Running...';
        state._runBtn.disabled = true;
    }

    const sessionId = window.__currentSessionId || null;

    try {
        const resp = await fetch('/api/v1/canvas/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code: code,
                language: state.language,
                session_id: sessionId,
            }),
        });
        const data = await resp.json();

        if (data.status === 'success') {
            showConsolePanel(state, data.result, data.row_count, data.execution_time_ms, false);
        } else {
            showConsolePanel(state, data.message || 'Execution failed', 0, 0, true);
        }
    } catch (err) {
        showConsolePanel(state, `Network error: ${err.message}`, 0, 0, true);
    } finally {
        if (state._runBtn) {
            state._runBtn.textContent = '\u25B6 Run';
            state._runBtn.disabled = false;
        }
    }
}

/**
 * Show execution results in a console panel below the canvas body.
 */
function showConsolePanel(state, result, rowCount, timeMs, isError) {
    // Remove existing console panel if any
    const existing = state.container?.querySelector('.canvas-console-panel');
    if (existing) existing.remove();

    const panel = document.createElement('div');
    panel.className = 'canvas-console-panel';

    // Header
    const header = document.createElement('div');
    header.className = 'canvas-console-header';

    const label = document.createElement('span');
    label.className = 'canvas-console-label';
    label.textContent = 'Console';

    const badge = document.createElement('span');
    badge.className = `canvas-console-badge${isError ? ' canvas-console-badge--error' : ''}`;
    badge.textContent = isError ? 'Error' : `${rowCount} row${rowCount !== 1 ? 's' : ''}`;

    header.appendChild(label);
    header.appendChild(badge);

    if (timeMs > 0) {
        const time = document.createElement('span');
        time.className = 'canvas-console-time';
        time.textContent = `${timeMs}ms`;
        header.appendChild(time);
    }

    const closeBtn = document.createElement('button');
    closeBtn.className = 'canvas-console-close';
    closeBtn.textContent = '\u00d7';
    closeBtn.title = 'Close console';
    closeBtn.addEventListener('click', () => panel.remove());
    header.appendChild(closeBtn);

    // Body
    const body = document.createElement('div');
    body.className = `canvas-console-body${isError ? ' canvas-console-body--error' : ''}`;
    body.textContent = result;

    panel.appendChild(header);
    panel.appendChild(body);

    // Insert after the canvas wrapper (inside the canvas container)
    const wrapper = state.container?.querySelector('.canvas-wrapper') || state.container;
    if (wrapper && wrapper.parentElement) {
        wrapper.parentElement.appendChild(panel);
    }
}

registerCapability({
    id: 'execution_bridge',
    label: '',
    type: 'toolbar',
    languages: ['sql'],

    init() {},

    render(toolbar, content, language, state) {
        const runBtn = document.createElement('button');
        runBtn.className = 'canvas-toolbar-btn canvas-run-btn';
        runBtn.textContent = '\u25B6 Run';
        runBtn.title = 'Execute SQL via MCP server';
        runBtn.addEventListener('click', () => executeCode(state));
        toolbar.insertBefore(runBtn, toolbar.firstChild);
        state._runBtn = runBtn;
    },

    destroy() {},
});

// ─── Sources Badge (M8.2) ────────────────────────────────────────────────────

registerCapability({
    id: 'sources_badge',
    label: '',
    type: 'toolbar',
    languages: ['*'],

    init() {},

    render(toolbar, content, language, state) {
        if (!state.sources) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'canvas-sources-wrapper';

        const badge = document.createElement('button');
        badge.className = 'canvas-toolbar-btn canvas-sources-badge';
        badge.textContent = '\uD83D\uDCDA Sources';
        badge.title = 'Knowledge sources that informed this content';

        const sourceList = state.sources.split(',').map(s => s.trim()).filter(Boolean);

        const dropdown = document.createElement('div');
        dropdown.className = 'canvas-sources-dropdown';
        dropdown.style.display = 'none';
        sourceList.forEach(src => {
            const item = document.createElement('div');
            item.className = 'canvas-sources-item';
            item.textContent = src;
            dropdown.appendChild(item);
        });

        badge.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
        });

        document.addEventListener('click', () => { dropdown.style.display = 'none'; });
        wrapper.addEventListener('click', (e) => e.stopPropagation());

        wrapper.appendChild(badge);
        wrapper.appendChild(dropdown);
        toolbar.appendChild(wrapper);
    },

    destroy() {},
});

// ─── Template Gallery (M8.3) ─────────────────────────────────────────────────

/** Cached templates fetched from server */
let _templateCache = null;

/**
 * Open the template gallery modal.
 */
async function openTemplateGallery(state) {
    // Fetch templates (with cache)
    if (!_templateCache) {
        try {
            const resp = await fetch('/api/v1/canvas/templates');
            const data = await resp.json();
            _templateCache = data.templates || [];
        } catch (err) {
            console.error('[Canvas] Failed to load templates:', err);
            _templateCache = [];
        }
    }

    if (_templateCache.length === 0) {
        console.warn('[Canvas] No templates available');
        return;
    }

    // Build category list
    const categories = [...new Set(_templateCache.map(t => t.category))];

    // Create modal overlay
    const overlay = document.createElement('div');
    overlay.className = 'canvas-template-overlay';

    const modal = document.createElement('div');
    modal.className = 'canvas-template-modal';

    // Header
    const header = document.createElement('div');
    header.className = 'canvas-template-header';
    const h3 = document.createElement('h3');
    h3.textContent = 'Starter Templates';
    const closeBtn = document.createElement('button');
    closeBtn.className = 'canvas-template-close';
    closeBtn.textContent = '\u00d7';
    closeBtn.addEventListener('click', () => overlay.remove());
    header.appendChild(h3);
    header.appendChild(closeBtn);

    // Category tabs
    const catBar = document.createElement('div');
    catBar.className = 'canvas-template-categories';

    // "All" tab
    const allTab = document.createElement('button');
    allTab.className = 'canvas-template-cat canvas-template-cat--active';
    allTab.textContent = 'All';
    allTab.dataset.category = '__all__';
    catBar.appendChild(allTab);

    categories.forEach(cat => {
        const tab = document.createElement('button');
        tab.className = 'canvas-template-cat';
        tab.textContent = cat;
        tab.dataset.category = cat;
        catBar.appendChild(tab);
    });

    // Template grid
    const grid = document.createElement('div');
    grid.className = 'canvas-template-grid';

    function renderGrid(filterCat) {
        grid.innerHTML = '';
        const filtered = filterCat === '__all__'
            ? _templateCache
            : _templateCache.filter(t => t.category === filterCat);

        filtered.forEach(tmpl => {
            const card = document.createElement('div');
            card.className = 'canvas-template-card';

            const name = document.createElement('div');
            name.className = 'canvas-template-card-name';
            name.textContent = tmpl.name;

            const desc = document.createElement('div');
            desc.className = 'canvas-template-card-desc';
            desc.textContent = tmpl.description;

            const lang = document.createElement('span');
            lang.className = 'canvas-template-card-lang';
            lang.textContent = tmpl.language;

            card.appendChild(name);
            card.appendChild(desc);
            card.appendChild(lang);

            card.addEventListener('click', () => {
                applyTemplate(state, tmpl);
                overlay.remove();
            });

            grid.appendChild(card);
        });
    }

    // Category tab switching
    catBar.addEventListener('click', (e) => {
        const tab = e.target.closest('.canvas-template-cat');
        if (!tab) return;
        catBar.querySelectorAll('.canvas-template-cat').forEach(t => t.classList.remove('canvas-template-cat--active'));
        tab.classList.add('canvas-template-cat--active');
        renderGrid(tab.dataset.category);
    });

    renderGrid('__all__');

    modal.appendChild(header);
    modal.appendChild(catBar);
    modal.appendChild(grid);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Close on overlay click (not modal click)
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });

    // Close on Escape
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            overlay.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

/**
 * Apply a template to the canvas editor.
 * Records current content as a version first (for undo via version history).
 */
function applyTemplate(state, template) {
    // Record current content as a version before replacing
    const currentContent = state.getContent();
    if (currentContent && currentContent.trim()) {
        recordVersion(state.title, currentContent, state.language);
    }

    // Replace editor content
    restoreVersion(state, template.content);

    // Update language if different
    if (template.language !== state.language) {
        state.language = template.language;
    }
}

registerCapability({
    id: 'template_gallery',
    label: '',
    type: 'toolbar',
    languages: ['*'],

    init() {},

    render(toolbar, content, language, state) {
        const btn = document.createElement('button');
        btn.className = 'canvas-toolbar-btn';
        btn.textContent = 'Templates';
        btn.title = 'Browse starter templates';
        btn.addEventListener('click', () => openTemplateGallery(state));
        toolbar.appendChild(btn);
    },

    destroy() {},
});

// ─── Capability: Toolbar ─────────────────────────────────────────────────────

registerCapability({
    id: 'toolbar',
    label: '',
    type: 'toolbar',
    languages: ['*'],

    init() {},

    render(toolbar, content, language, state) {
        // Copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'canvas-toolbar-btn';
        copyBtn.textContent = 'Copy';
        copyBtn.addEventListener('click', () => {
            const text = state.getContent();
            navigator.clipboard.writeText(text).then(() => {
                copyBtn.textContent = 'Copied!';
                setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
            }).catch(() => {
                // Fallback for non-HTTPS or older browsers
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.cssText = 'position:fixed;left:-9999px';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                copyBtn.textContent = 'Copied!';
                setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
            });
        });
        toolbar.appendChild(copyBtn);

        // Download button
        const dlBtn = document.createElement('button');
        dlBtn.className = 'canvas-toolbar-btn';
        dlBtn.textContent = 'Download';
        dlBtn.addEventListener('click', () => {
            const text = state.getContent();
            const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${(state.title || 'canvas').replace(/[^a-zA-Z0-9_-]/g, '_')}${state.fileExtension}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
        toolbar.appendChild(dlBtn);

        // Pop Out button — opens canvas in the split-screen side panel
        const popOutBtn = document.createElement('button');
        popOutBtn.className = 'canvas-toolbar-btn';
        popOutBtn.textContent = 'Expand';
        popOutBtn.title = 'Open in side panel';
        popOutBtn.addEventListener('click', () => {
            popOutCanvas(state);
        });
        toolbar.appendChild(popOutBtn);

        // Info badge
        const badge = document.createElement('span');
        badge.className = 'canvas-info-badge';
        badge.textContent = `${state.lineCount} lines \u00b7 ${language}`;
        toolbar.appendChild(badge);
    },

    destroy() {},
});

// ─── Bidirectional Context API ──────────────────────────────────────────────

/**
 * Get the current open canvas state for bidirectional context injection.
 * Returns the content from the split-panel canvas (if open) so the LLM
 * can reference and update the user's current working canvas.
 *
 * @returns {Object|null} Canvas state or null if no canvas is open
 */
export function getOpenCanvasState() {
    if (!_activeSplitCanvasState) return null;

    const panel = document.getElementById('canvas-split-panel');
    if (!panel || !panel.classList.contains('canvas-split--open')) return null;

    const currentContent = _activeSplitCanvasState.getContent();
    const modified = currentContent !== _activeSplitCanvasState.originalContent;

    return {
        title: _activeSplitCanvasState.title,
        language: _activeSplitCanvasState.language,
        content: currentContent,
        modified,
    };
}
