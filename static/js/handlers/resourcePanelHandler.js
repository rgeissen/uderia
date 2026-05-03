/**
 * resourcePanelHandler.js
 *
 * Owns the three innovations of the new Resource Panel:
 *  1. Icon Rail — vertical icon bar that replaces the flat tab nav
 *  2. Execution Pulse Strip — live execution dashboard pinned above the list
 *  3. Compact List — single-line expandable rows (density-toggle aware)
 *
 * Zero changes to existing JS required for tab switching: the hidden
 * #resource-tabs nav is still there for capabilitiesManagement / ui.js / etc.
 * A MutationObserver watches .resource-tab class changes and mirrors them to
 * the rail, keeping both in sync regardless of which code path triggered the switch.
 */

// ── Resource-type colour map (IFOC + type-specific) ─────────────────────────
const TYPE_COLORS = {
    tools:              '#F15F22',
    prompts:            '#8b5cf6',
    connectors:         '#3b82f6',
    resources:          '#06b6d4',
    'knowledge-graphs': '#10b981',
    skills:             '#f59e0b',
    extensions:         '#6366f1',
    components:         '#ec4899',
    context:            '#64748b',
};

// ── SVG icon snippets used inside the Pulse Strip ───────────────────────────
const PULSE_ICONS = {
    running: `<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" opacity=".25"/><path d="M21 12a9 9 0 00-9-9"/></svg>`,
    done:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>`,
    next:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/></svg>`,
    error:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg>`,
};

// ── Module state ─────────────────────────────────────────────────────────────
let _pulseRows = [];      // [{toolName, phase, status, startMs, endMs}]
let _pulseVisible = false;
let _idleTimer = null;
let _densityMode = {};    // { [panelType]: 'compact' | 'card' }

// ── 1. INIT ──────────────────────────────────────────────────────────────────

export function initResourcePanel() {
    _setupRailClicks();
    _setupMutationObserver();
    _setupDensityToggles();
    _syncRailBadgesFromTabs();
    _watchTabTextChanges();
}

// ── 2. ICON RAIL ─────────────────────────────────────────────────────────────

function _setupRailClicks() {
    const rail = document.getElementById('resource-icon-rail');
    if (!rail) return;

    rail.addEventListener('click', (e) => {
        const btn = e.target.closest('.rail-item');
        if (!btn) return;
        const type = btn.dataset.type;
        if (!type) return;

        // Delegate to the hidden .resource-tab so ALL existing handlers fire
        const hiddenTab = document.querySelector(`.resource-tab[data-type="${type}"]`);
        if (hiddenTab) {
            hiddenTab.click();
        }
        // syncRailToActiveTab() is triggered by the MutationObserver below
    });
}

/**
 * Watch the hidden #resource-tabs for class changes on child buttons.
 * When .active moves, mirror it onto the rail.
 * Also watches text changes for count badge updates.
 */
function _setupMutationObserver() {
    const tabs = document.getElementById('resource-tabs');
    if (!tabs) return;

    const observer = new MutationObserver((mutations) => {
        for (const m of mutations) {
            if (m.type === 'attributes') {
                const target = m.target;
                if (!target.classList?.contains('resource-tab')) continue;
                const type = target.dataset.type;

                if (m.attributeName === 'class' && target.classList.contains('active')) {
                    _syncRailToActiveTab(type);
                }

                if (m.attributeName === 'style') {
                    // Mirror display:none / display:inline-block from hidden tab to rail item
                    const railItem = document.querySelector(`.rail-item[data-type="${type}"]`);
                    if (railItem) {
                        const isHidden = target.style.display === 'none';
                        railItem.classList.toggle('rail-item--hidden', isHidden);
                    }
                }
            }
            if (m.type === 'characterData' || m.type === 'childList') {
                _syncRailBadgesFromTabs();
            }
        }
    });

    observer.observe(tabs, {
        subtree: true,
        attributes: true,
        attributeFilter: ['class', 'style'],
        characterData: true,
        childList: true,
    });
}

function _syncRailToActiveTab(activeType) {
    document.querySelectorAll('.rail-item').forEach(item => {
        item.classList.toggle('active', item.dataset.type === activeType);
    });
}

/**
 * Parse count from tab button text like "Tools (50)*" → "50"
 * or "Prompts (11)" → "11"
 */
function _syncRailBadgesFromTabs() {
    document.querySelectorAll('.resource-tab').forEach(tab => {
        const type = tab.dataset.type;
        const badge = document.getElementById(`rail-badge-${type}`);
        if (!badge) return;

        const text = tab.textContent || '';
        const match = text.match(/\((\d+)\)/);
        const count = match ? match[1] : '';
        const hasModified = text.includes('*');

        badge.textContent = count;
        badge.className = 'rail-badge' + (hasModified ? ' rail-badge--modified' : '');

        // Also update panel-count span if it exists
        const panelCount = document.getElementById(`${type}-panel-count`) ||
                           document.getElementById('kg-panel-count');
        if (panelCount && count) {
            const suffix = hasModified ? '*' : '';
            panelCount.textContent = count + suffix;
        }
    });
}

function _watchTabTextChanges() {
    // Re-sync badges whenever any tab counter function runs
    // (updateToolsTabCounter, updatePromptsTabCounter, etc. set textContent directly)
    const tabs = document.getElementById('resource-tabs');
    if (!tabs) return;
    const obs = new MutationObserver(_syncRailBadgesFromTabs);
    obs.observe(tabs, { subtree: true, characterData: true, childList: true });
}

// ── 3. DENSITY TOGGLE ────────────────────────────────────────────────────────

function _setupDensityToggles() {
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.density-btn');
        if (!btn) return;
        const panelType = btn.dataset.panel;
        if (!panelType) return;

        const isCardMode = btn.classList.toggle('is-card-mode');
        _densityMode[panelType] = isCardMode ? 'card' : 'compact';

        // Re-render the active panel if it has compact items
        // (the individual panel handlers call getPanelDensity() before rendering)
        const container = document.getElementById(`${panelType}-panels-container`);
        if (container) {
            // Signal panel to re-render by dispatching a custom event
            container.dispatchEvent(new CustomEvent('density-changed', { bubbles: true, detail: { mode: _densityMode[panelType] } }));
        }
    });
}

export function getPanelDensity(panelType) {
    return _densityMode[panelType] || 'compact';
}

// ── 4. COMPACT LIST ITEM BUILDER ─────────────────────────────────────────────

/**
 * Build a compact single-line item (with inline expand-on-click).
 *
 * @param {object} opts
 *   name          string   — resource name (also used as data-tool-name)
 *   category      string   — category label shown as pill
 *   description   string   — shown in expanded detail area
 *   type          string   — resource type key (tools, prompts, …)
 *   isActive      boolean  — show active dot
 *   extraDetail   string   — additional HTML to put inside the detail pane
 *
 * @returns HTMLElement (.compact-item-wrap)
 */
export function buildCompactItem({ name, category = '', description = '', type = 'tools', isActive = false, extraDetail = '' }) {
    const color = TYPE_COLORS[type] || TYPE_COLORS.tools;

    const wrap = document.createElement('div');
    wrap.className = 'compact-item-wrap';

    const row = document.createElement('div');
    row.className = 'compact-item';
    row.dataset.toolName = name;  // keep data-tool-name for existing highlight functions

    // Left colour stripe
    const stripe = document.createElement('div');
    stripe.className = 'type-stripe';
    stripe.style.background = color;

    // Name
    const nameEl = document.createElement('span');
    nameEl.className = 'item-name';
    nameEl.textContent = name;
    nameEl.title = name;

    // Category pill (only if provided)
    const catEl = document.createElement('span');
    if (category) {
        catEl.className = 'item-category';
        catEl.textContent = category;
    }

    // Status dot
    const dot = document.createElement('span');
    dot.className = 'status-dot' + (isActive ? ' is-active' : '');

    row.appendChild(stripe);
    row.appendChild(nameEl);
    if (category) row.appendChild(catEl);
    row.appendChild(dot);

    // Inline detail pane
    const detail = document.createElement('div');
    detail.className = 'item-detail';
    if (description) {
        const desc = document.createElement('p');
        desc.style.cssText = 'margin:0 0 4px; color:var(--text-secondary); font-size:11px;';
        desc.textContent = description;
        detail.appendChild(desc);
    }
    if (extraDetail) {
        const extra = document.createElement('div');
        extra.innerHTML = extraDetail;
        detail.appendChild(extra);
    }

    wrap.appendChild(row);
    wrap.appendChild(detail);

    // Click: toggle expanded state
    row.addEventListener('click', () => {
        wrap.classList.toggle('is-open');
    });

    return wrap;
}

// ── 5. RESOURCE HIGHLIGHT (compact-aware) ────────────────────────────────────

/**
 * Highlight a resource item in the panel.
 *
 * state: 'executing' | 'selected'
 *
 * Called by:
 *   - eventHandlers.js (via window.resourcePanelHandler.onSSEEvent)
 *   - wraps existing highlightComponent / highlightResource
 */
export function highlightCompactItem(name, state = 'selected') {
    if (state === 'executing') {
        // Don't auto-complete previous rows — parallel phases run simultaneously.
        // Each row completes only when its own tool_result event arrives.
        // Leave existing resource-executing items highlighted (multi-tool parallel state).
    } else {
        // tool_result for a specific tool: clear only that item's executing state
        document.querySelectorAll('.compact-item.resource-selected').forEach(el => {
            el.classList.remove('resource-selected');
        });
        document.querySelectorAll('.compact-item.resource-executing').forEach(el => {
            el.classList.remove('resource-executing');
        });
    }

    const cssClass = state === 'executing' ? 'resource-executing' : 'resource-selected';
    const item = document.querySelector(`.compact-item[data-tool-name="${CSS.escape(name)}"]`);
    if (item) {
        item.classList.add(cssClass);
        setTimeout(() => item.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100);
    }

    if (state === 'executing') {
        _addPulseRow(name);
    } else if (state === 'selected') {
        _completePulseRow(name);
    }
}

// ── 6. EXECUTION PULSE STRIP ─────────────────────────────────────────────────

function _showPulseStrip(clearBody = false) {
    const strip = document.getElementById('execution-pulse-strip');
    if (!strip) return;
    strip.classList.remove('hidden', 'is-idle');
    _pulseVisible = true;
    if (_idleTimer) { clearTimeout(_idleTimer); _idleTimer = null; }
    if (clearBody) {
        const body = document.getElementById('pulse-strip-body');
        if (body) body.innerHTML = '';
    }
}

function _collapsePulseStrip() {
    const strip = document.getElementById('execution-pulse-strip');
    if (!strip) return;
    strip.classList.add('is-idle');
    _idleTimer = setTimeout(() => {
        strip.classList.add('hidden');
        strip.classList.remove('is-idle');
        _pulseVisible = false;
        _pulseRows = [];
        _renderPulseStrip();
    }, 3000);
}

function _addPulseRow(toolName) {
    _showPulseStrip();
    const now = Date.now();

    // Time-based parallel detection:
    // Tools started within 200ms of each other are genuinely parallel (asyncio.gather).
    // A running row older than 200ms belongs to a sequential phase that didn't emit
    // tool_result before the next phase started — auto-complete it now.
    _pulseRows.forEach(r => {
        if (r.status === 'running' && (now - r.startMs) > 200) {
            r.status = 'done';
            r.endMs = now;
        }
    });

    // Dedupe: don't add a second running row for the same tool
    const alreadyRunning = _pulseRows.find(r => r.toolName === toolName && r.status === 'running');
    if (!alreadyRunning) {
        // Cap at 6 visible rows — drop oldest done rows first
        while (_pulseRows.length >= 6) {
            const doneIdx = _pulseRows.findIndex(r => r.status === 'done');
            if (doneIdx !== -1) _pulseRows.splice(doneIdx, 1);
            else _pulseRows.shift();
        }
        _pulseRows.push({ toolName, status: 'running', startMs: now });
    }
    _renderPulseStrip();
}

function _completePulseRow(toolName) {
    const row = _pulseRows.find(r => r.toolName === toolName && r.status === 'running');
    if (row) {
        row.status = 'done';
        row.endMs = Date.now();
    }
    _renderPulseStrip();
}

function _markPulseRowError(toolName) {
    const row = _pulseRows.find(r => r.toolName === toolName);
    if (row) row.status = 'error';
    _renderPulseStrip();
}

function _renderPulseStrip() {
    const body = document.getElementById('pulse-strip-body');
    if (!body) return;

    if (_pulseRows.length === 0) {
        body.innerHTML = '';
        return;
    }

    const runningCount = _pulseRows.filter(r => r.status === 'running').length;

    let html = `<div class="pulse-header">
        <span class="pulse-header-label">Executing</span>
        <span class="pulse-header-phase">${runningCount > 0 ? `${runningCount} active` : 'complete'}</span>
    </div>`;

    for (const r of [..._pulseRows].reverse()) {
        const iconClass = r.status === 'running' ? 'is-running' : r.status === 'done' ? 'is-done' : r.status === 'error' ? 'is-error' : 'is-next';
        const icon = PULSE_ICONS[r.status === 'running' ? 'running' : r.status === 'done' ? 'done' : r.status === 'error' ? 'error' : 'next'];
        let meta = '';
        if (r.status === 'done' && r.endMs) {
            const ms = r.endMs - r.startMs;
            meta = ms > 999 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
        } else if (r.status === 'running') {
            meta = '...';
        }

        html += `<div class="pulse-row ${iconClass}">
            <span class="pulse-icon">${icon}</span>
            <span class="pulse-name">${_esc(r.toolName)}</span>
            <span class="pulse-meta">${meta}</span>
        </div>`;
    }

    body.innerHTML = html;
}

// ── 7. SSE EVENT HANDLER ─────────────────────────────────────────────────────

/**
 * Called from eventHandlers.js at the same sites that call UI.highlightResource().
 * Drives the pulse strip + compact item highlight based on SSE events.
 *
 * @param {string} eventType  — SSE event type ('notification', 'message', etc.)
 * @param {object} eventData  — parsed event data payload
 */
export function onSSEEvent(eventType, eventData) {
    if (!eventData) return;

    const type = eventData.type;
    const payload = eventData.payload || {};

    // ── Execution lifecycle ───────────────────────────────────────
    if (type === 'execution_start') {
        _pulseRows = [];
        _showPulseStrip(true);         // clear stale DOM immediately
        _renderPulseStrip();
        return;
    }

    if (type === 'conversation_agent_complete' || type === 'final_answer' ||
        type === 'execution_complete' || type === 'execution_error') {
        _pulseRows.forEach(r => { if (r.status === 'running') { r.status = 'done'; r.endMs = Date.now(); } });
        _renderPulseStrip();
        setTimeout(_collapsePulseStrip, 1800);
        document.querySelectorAll('.compact-item.resource-executing').forEach(el => {
            el.classList.remove('resource-executing');
            el.classList.add('resource-selected');
        });
        return;
    }

    // ── Conversation-agent profile tool events (llm_only + tools) ─
    if (type === 'conversation_tool_invoked') {
        const n = payload.tool_name || payload.name;
        if (n) { highlightCompactItem(n, 'executing'); }
        return;
    }
    if (type === 'conversation_tool_completed') {
        const n = payload.tool_name || payload.name;
        if (n) { highlightCompactItem(n, payload.success === false ? 'selected' : 'selected'); }
        return;
    }

    // ── Named SSE tool events (tool_enabled / Optimize profile) ──
    const toolName = payload.tool_name || payload.name || eventData.tool_name;
    if (!toolName) return;

    // Internal orchestration tools — skip highlights but show synthesis step
    const skipHighlight = ['TDA_CurrentDate', 'TDA_SystemLog', 'TDA_SystemOrchestration', 'TDA_LLMTask'];
    if (skipHighlight.includes(toolName)) return;

    // TDA_FinalReport: show in pulse strip as a synthesis step but don't highlight a panel card
    if (toolName === 'TDA_FinalReport') {
        if (type === 'tool_call' || type === 'tool_start' || eventType === 'tool_call') {
            _addPulseRow('Synthesizing report');
        } else if (type === 'tool_result' || type === 'tool_end') {
            _completePulseRow('Synthesizing report');
        }
        return;
    }

    if (type === 'tool_call' || type === 'tool_start' || eventType === 'tool_call') {
        highlightCompactItem(toolName, 'executing');
    } else if (type === 'tool_result' || type === 'tool_end') {
        const isError = payload.is_error || payload.error;
        if (isError) {
            _markPulseRowError(toolName);
        } else {
            highlightCompactItem(toolName, 'selected');
        }
    }
}

// ── 8. HELPERS ───────────────────────────────────────────────────────────────

function _esc(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── 9. GLOBAL EXPOSURE ───────────────────────────────────────────────────────
// Expose the handler on window so eventHandlers.js can call it without circular imports
window.resourcePanelHandler = {
    highlightCompactItem,
    onSSEEvent,
    getPanelDensity,
    buildCompactItem,
    syncRailBadges: _syncRailBadgesFromTabs,
};
