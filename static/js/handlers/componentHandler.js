/**
 * Component Handler
 *
 * Manages the top-level Components view (sidebar → Components):
 * - Fetches component list from GET /v1/components
 * - Renders card gallery with category/status filter pills
 * - Card selection → fetches detail from GET /v1/components/<id>
 * - Detail panel with capabilities table + tool arguments table
 * - Reload button for hot-reload from disk
 * - Import button governance (hidden when admin disables user components)
 */

let _componentSettings = {};
let _cachedComponents = [];
let _selectedComponentId = null;
let _initialized = false;

// ─── DOM IDs (top-level view) ───────────────────────────────────────────────
const GRID_ID = 'components-grid-top';
const DETAIL_ID = 'component-detail-panel';
const RELOAD_BTN_ID = 'reload-components-btn-top';
const IMPORT_BTN_ID = 'import-component-btn-top';
const CATEGORY_FILTERS_ID = 'component-category-filters-top';
const STATUS_FILTERS_ID = 'component-status-filters-top';

// ─── IFOC Methodology Naming ────────────────────────────────────────────────
// Canonical mapping from configurationHandler.js ifocTagConfig
const IFOC_CONFIG = {
    'llm_only':      { label: 'Ideate',     badgeClass: 'bg-green-500/20 text-green-300 comp-lt-green' },
    'rag_focused':   { label: 'Focus',      badgeClass: 'bg-blue-500/20 text-blue-300 comp-lt-blue' },
    'tool_enabled':  { label: 'Optimize',   badgeClass: 'bg-orange-500/20 text-orange-300 comp-lt-orange' },
    'genie':         { label: 'Coordinate', badgeClass: 'bg-purple-500/20 text-purple-300 comp-lt-purple' },
};
const IFOC_ORDER = ['llm_only', 'rag_focused', 'tool_enabled', 'genie'];

/**
 * Entry point called by ui.js performViewSwitch() when navigating to components-view.
 * Loads components and initializes handlers (once).
 */
export async function loadComponentsView() {
    if (!_initialized) {
        _initializeHandlers();
        _initialized = true;
    }
    await _loadComponents();
}

/**
 * Legacy export kept for backward compatibility if any caller still uses it.
 */
export async function loadComponents() {
    await _loadComponents();
}

/**
 * Fetch components from the API and render the card grid.
 */
async function _loadComponents() {
    const grid = document.getElementById(GRID_ID);
    if (!grid) return;

    grid.innerHTML = '<div class="col-span-full text-center text-gray-400 py-8">Loading components...</div>';

    try {
        const token = localStorage.getItem('tda_auth_token');
        const resp = await fetch('/api/v1/components', {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!resp.ok) {
            grid.innerHTML = '<div class="col-span-full text-center text-red-400 py-8">Failed to load components</div>';
            return;
        }

        const data = await resp.json();
        _cachedComponents = data.components || [];
        _componentSettings = data._settings || {};

        // Governance: show/hide Import button
        const importBtn = document.getElementById(IMPORT_BTN_ID);
        if (importBtn) {
            importBtn.style.display = _componentSettings.user_components_enabled ? '' : 'none';
        }

        if (_cachedComponents.length === 0) {
            grid.innerHTML = '<div class="col-span-full text-center text-gray-400 py-8">No components installed</div>';
            _hideDetailPanel();
            return;
        }

        grid.innerHTML = _cachedComponents.map(comp => _renderComponentCard(comp)).join('');

        // Attach click handlers to cards
        grid.querySelectorAll('.component-card').forEach(card => {
            card.addEventListener('click', () => _onCardClick(card.dataset.componentId));
            card.style.cursor = 'pointer';
        });

        // Auto-select first card if nothing selected
        if (!_selectedComponentId || !_cachedComponents.find(c => c.component_id === _selectedComponentId)) {
            _onCardClick(_cachedComponents[0].component_id);
        } else {
            // Re-select the previously selected card
            _onCardClick(_selectedComponentId);
        }

    } catch (err) {
        console.error('[ComponentHandler] Error loading components:', err);
        grid.innerHTML = '<div class="col-span-full text-center text-red-400 py-8">Error loading components</div>';
    }
}

/**
 * Render a single component card as an HTML string.
 */
function _renderComponentCard(comp) {
    const sourceClasses = {
        builtin: 'bg-violet-500/20 text-violet-300 comp-lt-violet',
        agent_pack: 'bg-cyan-500/20 text-cyan-300 comp-lt-cyan',
        user: 'bg-amber-500/20 text-amber-300 comp-lt-amber',
    };
    const typeClasses = {
        action: 'bg-blue-500/20 text-blue-300 comp-lt-blue',
        structural: 'bg-gray-500/20 text-gray-300 comp-lt-gray',
    };

    const sourceBadge = sourceClasses[comp.source] || sourceClasses.builtin;
    const typeBadge = typeClasses[comp.component_type] || typeClasses.action;
    const toolName = comp.tool_name ? `<span class="text-xs font-mono text-cyan-300 comp-lt-text-cyan">${comp.tool_name}</span>` : '';

    const renderTargets = (comp.render_targets?.supports || ['inline']).map(t =>
        `<span class="text-xs px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-300 comp-lt-gray">${t}</span>`
    ).join('');

    return `
        <div class="glass-panel rounded-lg p-4 flex flex-col gap-3 component-card transition-all duration-150"
             data-component-type="${comp.component_type}"
             data-component-source="${comp.source}"
             data-component-id="${comp.component_id}">
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <h4 class="text-sm font-semibold" style="color:var(--text-primary)">${comp.display_name}</h4>
                    <p class="text-xs mt-0.5" style="color:var(--text-muted)">${comp.description || ''}</p>
                </div>
                <div class="flex items-center gap-1.5 ml-2">
                    <span class="text-xs px-1.5 py-0.5 rounded ${sourceBadge}">${comp.source}</span>
                    <span class="text-xs px-1.5 py-0.5 rounded ${typeBadge}">${comp.component_type}</span>
                </div>
            </div>
            <div class="flex items-center justify-between text-xs">
                <div class="flex items-center gap-2">
                    ${toolName}
                    <span style="color:var(--text-muted)">v${comp.version}</span>
                </div>
                <div class="flex items-center gap-1">
                    ${renderTargets}
                </div>
            </div>
            ${comp.has_handler
                ? '<div class="flex items-center gap-1 text-xs text-green-400"><svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg> Handler loaded</div>'
                : '<div class="flex items-center gap-1 text-xs text-yellow-400"><svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg> No handler</div>'
            }
        </div>
    `;
}

// ─── Card Selection & Detail Panel ──────────────────────────────────────────

/**
 * Handle card click — highlight selected card and fetch detail.
 */
async function _onCardClick(componentId) {
    if (!componentId) return;
    _selectedComponentId = componentId;

    // Update selection outline (uses outline, not ring/box-shadow, to avoid
    // conflict with .glass-panel:hover box-shadow)
    const grid = document.getElementById(GRID_ID);
    if (grid) {
        grid.querySelectorAll('.component-card').forEach(card => {
            if (card.dataset.componentId === componentId) {
                card.style.outline = '2px solid rgba(34,211,238,0.6)';
                card.style.outlineOffset = '-2px';
            } else {
                card.style.outline = '';
                card.style.outlineOffset = '';
            }
        });
    }

    // Fetch full component detail
    try {
        const token = localStorage.getItem('tda_auth_token');
        const resp = await fetch(`/api/v1/components/${componentId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!resp.ok) {
            _showDetailError('Failed to load component details');
            return;
        }

        const data = await resp.json();
        _renderDetailPanel(data.component);

    } catch (err) {
        console.error('[ComponentHandler] Detail fetch error:', err);
        _showDetailError('Error loading component details');
    }
}

/**
 * Render the full detail panel for a selected component.
 */
function _renderDetailPanel(comp) {
    const panel = document.getElementById(DETAIL_ID);
    if (!panel) return;

    const manifest = comp.manifest || {};
    const toolDef = manifest.tool_definition || {};
    const renderTargets = comp.render_targets || manifest.render_targets || {};
    const profileDefaults = comp.profile_defaults || manifest.profile_defaults || {};
    const backend = manifest.backend || {};

    // ── Header Section ──
    const sourceClasses = {
        builtin: 'bg-violet-500/20 text-violet-300 comp-lt-violet',
        agent_pack: 'bg-cyan-500/20 text-cyan-300 comp-lt-cyan',
        user: 'bg-amber-500/20 text-amber-300 comp-lt-amber',
    };
    const typeClasses = {
        action: 'bg-blue-500/20 text-blue-300 comp-lt-blue',
        structural: 'bg-gray-500/20 text-gray-300 comp-lt-gray',
    };
    const sourceBadge = sourceClasses[comp.source] || sourceClasses.builtin;
    const typeBadge = typeClasses[comp.component_type] || typeClasses.action;

    const supportsStr = (renderTargets.supports || ['inline']).map(t =>
        `<span class="px-2 py-0.5 rounded bg-gray-500/20 text-gray-300 comp-lt-gray text-xs">${t}</span>`
    ).join('');

    const sortedEnabledFor = [...(profileDefaults.enabled_for || [])].sort(
        (a, b) => (IFOC_ORDER.indexOf(a) >>> 0) - (IFOC_ORDER.indexOf(b) >>> 0)
    );
    const enabledFor = sortedEnabledFor.map(p => {
        const ifoc = IFOC_CONFIG[p] || { label: p, badgeClass: 'bg-gray-500/20 text-gray-300 comp-lt-gray' };
        return `<span class="px-2 py-0.5 rounded ${ifoc.badgeClass} text-xs">${ifoc.label}</span>`;
    }).join('');

    const headerHTML = `
        <div class="flex items-start gap-4 mb-6">
            <div class="flex-shrink-0 w-12 h-12 rounded-lg bg-cyan-500/20 comp-lt-cyan flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-cyan-400 comp-lt-text-cyan" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                </svg>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-3 flex-wrap">
                    <h2 class="text-xl font-bold" style="color:var(--text-primary)">${comp.display_name}</h2>
                    <span class="text-sm" style="color:var(--text-muted)">v${comp.version}</span>
                    <span class="text-xs px-2 py-0.5 rounded ${sourceBadge}">${comp.source}</span>
                    <span class="text-xs px-2 py-0.5 rounded ${typeBadge}">${comp.component_type}</span>
                </div>
                <p class="text-sm mt-1" style="color:var(--text-muted)">${comp.description || ''}</p>
                <div class="flex items-center gap-4 mt-3 text-sm">
                    ${toolDef.name ? `<div class="flex items-center gap-1.5">
                        <span style="color:var(--text-muted)">Tool:</span>
                        <span class="font-mono text-cyan-300 comp-lt-text-cyan">${toolDef.name}</span>
                    </div>` : ''}
                    ${backend.fast_path ? `<div class="flex items-center gap-1 text-emerald-400 comp-lt-emerald" style="background:none">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                        Fast-path
                    </div>` : ''}
                    <div class="flex items-center gap-1.5">
                        <span style="color:var(--text-muted)">Render:</span>
                        ${supportsStr}
                    </div>
                </div>
                ${enabledFor ? `<div class="flex items-center gap-1.5 mt-2 text-sm">
                    <span style="color:var(--text-muted)">Profiles:</span>
                    ${enabledFor}
                </div>` : ''}
            </div>
        </div>
    `;

    // ── Capabilities Section (component-specific) ──
    const capabilitiesHTML = _renderCapabilities(manifest, comp);

    // ── Tool Arguments Section ──
    const toolArgsHTML = _renderToolArguments(toolDef);

    // ── Tabbed Layout ──
    const capIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"/></svg>`;
    const argsIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>`;
    const profIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/></svg>`;

    const tabs = [];
    const tabPanels = [];

    if (capabilitiesHTML) {
        tabs.push({ id: 'comp-tab-cap', label: 'Chart Types', icon: capIcon, panelId: 'comp-panel-cap' });
        tabPanels.push({ id: 'comp-panel-cap', html: capabilitiesHTML });
    }
    if (toolArgsHTML) {
        tabs.push({ id: 'comp-tab-args', label: 'Tool Arguments', icon: argsIcon, panelId: 'comp-panel-args' });
        tabPanels.push({ id: 'comp-panel-args', html: toolArgsHTML });
    }
    // Connections tab — only for the canvas component (SQL named connections)
    if (comp.component_id === 'canvas') {
        const connIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"/></svg>`;
        tabs.push({ id: 'comp-tab-conn', label: 'Connections', icon: connIcon, panelId: 'comp-panel-conn' });
        tabPanels.push({
            id: 'comp-panel-conn',
            html: `<div id="component-connections">
                <div class="flex items-center gap-2 mb-3">
                    <h3 class="text-lg font-semibold" style="color:var(--text-primary)">SQL Connections</h3>
                </div>
                <div class="text-sm" style="color:var(--text-muted)">Loading connections...</div>
            </div>`
        });
    }

    tabs.push({ id: 'comp-tab-prof', label: 'Profiles', icon: profIcon, panelId: 'comp-panel-prof' });
    tabPanels.push({
        id: 'comp-panel-prof',
        html: `<div id="component-profile-assignments">
            <div class="flex items-center gap-2 mb-3">
                <h3 class="text-lg font-semibold" style="color:var(--text-primary)">Profile Assignments</h3>
            </div>
            <div class="text-sm" style="color:var(--text-muted)">Loading profiles...</div>
        </div>`
    });

    const tabBarHTML = tabs.map((t, i) => `
        <button class="ind-tab ind-tab--underline ${i === 0 ? 'active' : ''}"
                style="--tab-color: 6, 182, 212"
                data-tab-target="${t.panelId}"
                id="${t.id}">
            ${t.icon}
            ${t.label}
        </button>
    `).join('');

    const panelsHTML = tabPanels.map((p, i) => `
        <div id="${p.id}" class="${i === 0 ? '' : 'hidden'}">
            ${p.html}
        </div>
    `).join('');

    // ── Assemble ──
    panel.innerHTML = `
        <div class="glass-panel rounded-xl p-6">
            ${headerHTML}
            <div class="flex gap-1 border-b border-white/10 mb-4 mt-2">
                ${tabBarHTML}
            </div>
            ${panelsHTML}
        </div>
    `;
    panel.classList.remove('hidden');

    // Wire tab switching
    panel.querySelectorAll('.ind-tab--underline').forEach(tab => {
        tab.addEventListener('click', () => {
            panel.querySelectorAll('.ind-tab--underline').forEach(t => t.classList.remove('active'));
            tabPanels.forEach(p => {
                const el = document.getElementById(p.id);
                if (el) el.classList.add('hidden');
            });
            tab.classList.add('active');
            const target = document.getElementById(tab.dataset.tabTarget);
            if (target) target.classList.remove('hidden');
        });
    });

    // Async-load profile assignments (doesn't block the detail render)
    _loadProfileAssignments(comp);

    // Async-load connections tab (canvas component only)
    if (comp.component_id === 'canvas') {
        _loadConnections();
    }
}

/**
 * Render the capabilities section based on component manifest.
 * - chart component: show chart_types table
 * - generic: show key manifest capabilities
 */
function _renderCapabilities(manifest, comp) {
    // Chart component — chart_types table
    if (manifest.chart_types && Object.keys(manifest.chart_types).length > 0) {
        const rows = Object.entries(manifest.chart_types).map(([type, info]) => {
            const required = (info.mapping_roles || []).join(', ') || '\u2014';
            const optional = (info.optional_roles || []).length > 0
                ? info.optional_roles.join(', ')
                : '\u2014';
            return `
                <tr class="border-t border-white/5">
                    <td class="py-2 pr-4 font-mono text-cyan-300 comp-lt-text-cyan">${type}</td>
                    <td class="py-2 pr-4" style="color:var(--text-secondary,#d1d5db)">${info.g2plot_type}</td>
                    <td class="py-2 pr-4" style="color:var(--text-muted)">${required}</td>
                    <td class="py-2" style="color:var(--text-muted)">${optional}</td>
                </tr>
            `;
        }).join('');

        return `
            <div>
                <div class="flex items-center gap-2 mb-3">
                    <h3 class="text-lg font-semibold" style="color:var(--text-primary)">Supported Chart Types</h3>
                    <span class="text-xs" style="color:var(--text-muted)">${Object.keys(manifest.chart_types).length} types</span>
                </div>
                <div class="overflow-x-auto max-h-72 overflow-y-auto">
                    <table class="w-full text-sm">
                        <thead class="sticky top-0 bg-[var(--card-bg,#1a1a2e)]">
                            <tr class="text-left text-xs uppercase tracking-wide" style="color:var(--text-muted)">
                                <th class="pb-2 pr-4">Type</th>
                                <th class="pb-2 pr-4">G2Plot</th>
                                <th class="pb-2 pr-4">Required Roles</th>
                                <th class="pb-2">Optional Roles</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rows}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    // Generic fallback: show key manifest info as property list
    const skipKeys = new Set([
        'component_id', 'display_name', 'description', 'version',
        'component_type', 'category', 'tool_definition', 'backend',
        'frontend', 'render_targets', 'profile_defaults', 'instructions'
    ]);

    const extraProps = Object.entries(manifest)
        .filter(([k]) => !skipKeys.has(k))
        .filter(([, v]) => v !== null && v !== undefined);

    if (extraProps.length === 0) return '';

    const propRows = extraProps.map(([key, value]) => {
        const displayValue = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
        return `
            <tr class="border-t border-white/5">
                <td class="py-2 pr-4 font-mono text-cyan-300 comp-lt-text-cyan">${key}</td>
                <td class="py-2" style="color:var(--text-secondary,#d1d5db)"><pre class="whitespace-pre-wrap text-xs">${_escapeHtml(displayValue)}</pre></td>
            </tr>
        `;
    }).join('');

    return `
        <div>
            <div class="flex items-center gap-2 mb-3">
                <h3 class="text-lg font-semibold" style="color:var(--text-primary)">Capabilities</h3>
            </div>
            <table class="w-full text-sm">
                <thead>
                    <tr class="text-left text-xs uppercase tracking-wide" style="color:var(--text-muted)">
                        <th class="pb-2 pr-4">Property</th>
                        <th class="pb-2">Value</th>
                    </tr>
                </thead>
                <tbody>
                    ${propRows}
                </tbody>
            </table>
        </div>
    `;
}

/**
 * Render the tool arguments table from the tool definition.
 */
function _renderToolArguments(toolDef) {
    if (!toolDef.args || Object.keys(toolDef.args).length === 0) return '';

    const rows = Object.entries(toolDef.args).map(([argName, argDef]) => {
        const required = argDef.required
            ? '<span class="text-emerald-400 comp-lt-emerald" style="background:none">&#10003;</span>'
            : `<span style="color:var(--text-muted)">\u2014</span>`;
        return `
            <tr class="border-t border-white/5">
                <td class="py-2 pr-4 font-mono text-cyan-300 comp-lt-text-cyan">${argName}</td>
                <td class="py-2 pr-4" style="color:var(--text-muted)">${argDef.type || 'string'}</td>
                <td class="py-2 pr-4 text-center">${required}</td>
                <td class="py-2 text-xs" style="color:var(--text-muted)">${argDef.description || ''}</td>
            </tr>
        `;
    }).join('');

    return `
        <div>
            <div class="flex items-center gap-2 mb-3">
                <h3 class="text-lg font-semibold" style="color:var(--text-primary)">Tool Arguments</h3>
                <span class="text-xs font-mono text-cyan-300 comp-lt-text-cyan">${toolDef.name || ''}</span>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-sm">
                    <thead>
                        <tr class="text-left text-xs uppercase tracking-wide" style="color:var(--text-muted)">
                            <th class="pb-2 pr-4">Argument</th>
                            <th class="pb-2 pr-4">Type</th>
                            <th class="pb-2 pr-4 text-center">Required</th>
                            <th class="pb-2">Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

// ─── Profile Assignments ────────────────────────────────────────────────────

/**
 * Async-load profiles and render the Profile Assignments section.
 * Called after the detail panel is rendered so it doesn't block.
 */
async function _loadProfileAssignments(comp) {
    const container = document.getElementById('component-profile-assignments');
    if (!container) return;

    try {
        const token = localStorage.getItem('tda_auth_token');
        const resp = await fetch('/api/v1/profiles', {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!resp.ok) {
            container.querySelector('div:last-child').textContent = 'Failed to load profiles';
            return;
        }

        const data = await resp.json();
        const profiles = data.profiles || [];

        if (profiles.length === 0) {
            container.querySelector('div:last-child').textContent = 'No profiles configured';
            return;
        }

        const isAction = comp.component_type === 'action';
        const componentId = comp.component_id;

        const sortedProfiles = [...profiles].sort((a, b) => {
            const ia = IFOC_ORDER.indexOf(a.profile_type);
            const ib = IFOC_ORDER.indexOf(b.profile_type);
            return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
        });

        const rowsHTML = sortedProfiles.map(profile => {
            const compConfig = (profile.componentConfig || {})[componentId] || {};
            const isEnabled = compConfig.enabled !== undefined ? compConfig.enabled : true;
            const intensity = compConfig.intensity || comp.profile_defaults?.default_intensity || 'medium';
            const ifocInfo = IFOC_CONFIG[profile.profile_type] || { label: profile.profile_type, badgeClass: 'bg-gray-500/20 text-gray-300 comp-lt-gray' };
            const typeBadge = ifocInfo.badgeClass;

            const intensityLevels = (comp.manifest?.instructions?.intensity_levels || ['none', 'medium', 'heavy'])
                .filter(l => l !== 'none');  // "none" is redundant — the enable toggle covers disabling
            const intensityOptions = intensityLevels.map(level => {
                const label = level.charAt(0).toUpperCase() + level.slice(1);
                return `<option value="${level}" ${intensity === level ? 'selected' : ''}>${label}</option>`;
            }).join('');
            const manifestTooltips = comp.manifest?.instructions?.intensity_tooltips || {};
            const intensityTooltip = intensityLevels
                .map(l => `${l.charAt(0).toUpperCase() + l.slice(1)} — ${manifestTooltips[l] || (l === 'medium' ? 'Use when appropriate' : 'Proactively use at every opportunity')}`)
                .join('\n');
            const intensitySelect = isAction ? `
                <select class="profile-comp-intensity text-xs bg-gray-800 border border-gray-600 text-gray-300 comp-lt-select rounded px-2 py-1"
                        data-profile-id="${profile.id}" ${!isEnabled ? 'disabled' : ''}
                        data-tooltip="${intensityTooltip}">
                    ${intensityOptions}
                </select>` : '';

            return `
                <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/30 border border-gray-700/20 comp-lt-row">
                    <div class="flex items-center gap-3 min-w-0">
                        <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300 comp-lt-cyan flex-shrink-0">@${_escapeHtml(profile.tag || '?')}</span>
                        <span class="text-sm truncate" style="color:var(--text-primary)">${_escapeHtml(profile.name || profile.id)}</span>
                        <span class="text-[10px] px-1.5 py-0.5 rounded ${typeBadge} uppercase tracking-wider flex-shrink-0">${ifocInfo.label}</span>
                    </div>
                    <div class="flex items-center gap-3 flex-shrink-0">
                        ${intensitySelect}
                        <label class="ind-toggle ind-toggle--sm">
                            <input type="checkbox" class="profile-comp-toggle"
                                   data-profile-id="${profile.id}" ${isEnabled ? 'checked' : ''}>
                            <span class="ind-track"></span>
                        </label>
                    </div>
                </div>
            `;
        }).join('');

        // Replace the loading placeholder, keep the header
        container.innerHTML = `
            <div class="flex items-center gap-2 mb-3">
                <h3 class="text-lg font-semibold" style="color:var(--text-primary)">Profile Assignments</h3>
                <span class="text-xs" style="color:var(--text-muted)">${profiles.length} profiles</span>
            </div>
            <div class="space-y-2">
                ${rowsHTML}
            </div>
        `;

        // Wire toggle handlers
        container.querySelectorAll('.profile-comp-toggle').forEach(toggle => {
            toggle.addEventListener('change', async (e) => {
                const profileId = e.target.dataset.profileId;
                const enabled = e.target.checked;
                const row = e.target.closest('.flex.items-center.justify-between');
                const intensitySelect = row?.querySelector('.profile-comp-intensity');
                if (intensitySelect) intensitySelect.disabled = !enabled;

                await _updateProfileComponentConfig(profileId, componentId, { enabled }, profiles);
            });
        });

        // Wire intensity handlers
        container.querySelectorAll('.profile-comp-intensity').forEach(select => {
            select.addEventListener('change', async (e) => {
                const profileId = e.target.dataset.profileId;
                const intensity = e.target.value;

                await _updateProfileComponentConfig(profileId, componentId, { intensity }, profiles);
            });
        });

    } catch (err) {
        console.error('[ComponentHandler] Error loading profiles:', err);
        const placeholder = container.querySelector('div:last-child');
        if (placeholder) placeholder.textContent = 'Error loading profiles';
    }
}

/**
 * Update a single component's config within a profile and save via PUT.
 */
async function _updateProfileComponentConfig(profileId, componentId, updates, profiles) {
    try {
        const profile = profiles.find(p => p.id === profileId);
        if (!profile) return;

        const config = { ...(profile.componentConfig || {}) };
        config[componentId] = { ...(config[componentId] || {}), ...updates };

        // Update the in-memory copy so subsequent changes stack correctly
        profile.componentConfig = config;

        const token = localStorage.getItem('tda_auth_token');
        const resp = await fetch(`/api/v1/profiles/${profileId}`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ componentConfig: config })
        });

        if (!resp.ok) {
            console.error('[ComponentHandler] Failed to update profile:', resp.status);
            if (window.showNotification) {
                window.showNotification('error', 'Failed to update profile');
            }
        } else if (window.configState?.loadProfiles) {
            window.configState.loadProfiles();  // fire-and-forget — sync shared cache
        }
    } catch (err) {
        console.error('[ComponentHandler] Error updating profile component config:', err);
        if (window.showNotification) {
            window.showNotification('error', 'Error updating profile');
        }
    }
}

// ─── SQL Connection Manager (Canvas component) ─────────────────────────────

const DRIVER_ICONS = {
    postgresql: `<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <ellipse cx="14" cy="8" rx="9" ry="4" stroke="#06b6d4" stroke-width="1.5" fill="none"/>
        <path d="M5 8v12c0 2.21 4.03 4 9 4s9-1.79 9-4V8" stroke="#06b6d4" stroke-width="1.5" fill="none"/>
        <path d="M5 14c0 2.21 4.03 4 9 4s9-1.79 9-4" stroke="#06b6d4" stroke-width="1.5" fill="none" opacity="0.5"/>
        <text x="14" y="22" text-anchor="middle" font-size="6" font-weight="700" font-family="monospace" fill="#06b6d4">PG</text>
    </svg>`,
    mysql: `<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <ellipse cx="14" cy="8" rx="9" ry="4" stroke="#f59e0b" stroke-width="1.5" fill="none"/>
        <path d="M5 8v12c0 2.21 4.03 4 9 4s9-1.79 9-4V8" stroke="#f59e0b" stroke-width="1.5" fill="none"/>
        <path d="M5 14c0 2.21 4.03 4 9 4s9-1.79 9-4" stroke="#f59e0b" stroke-width="1.5" fill="none" opacity="0.5"/>
        <text x="14" y="22" text-anchor="middle" font-size="6" font-weight="700" font-family="monospace" fill="#f59e0b">MY</text>
    </svg>`,
    sqlite: `<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <ellipse cx="14" cy="8" rx="9" ry="4" stroke="#a78bfa" stroke-width="1.5" fill="none"/>
        <path d="M5 8v12c0 2.21 4.03 4 9 4s9-1.79 9-4V8" stroke="#a78bfa" stroke-width="1.5" fill="none"/>
        <path d="M5 14c0 2.21 4.03 4 9 4s9-1.79 9-4" stroke="#a78bfa" stroke-width="1.5" fill="none" opacity="0.5"/>
        <text x="14" y="22" text-anchor="middle" font-size="5" font-weight="700" font-family="monospace" fill="#a78bfa">SQ</text>
    </svg>`,
    teradata: `<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <ellipse cx="14" cy="8" rx="9" ry="4" stroke="#F15F22" stroke-width="1.5" fill="none"/>
        <path d="M5 8v12c0 2.21 4.03 4 9 4s9-1.79 9-4V8" stroke="#F15F22" stroke-width="1.5" fill="none"/>
        <path d="M5 14c0 2.21 4.03 4 9 4s9-1.79 9-4" stroke="#F15F22" stroke-width="1.5" fill="none" opacity="0.5"/>
        <text x="14" y="22" text-anchor="middle" font-size="5" font-weight="700" font-family="monospace" fill="#F15F22">TD</text>
    </svg>`,
    jdbc: `<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <ellipse cx="14" cy="8" rx="9" ry="4" stroke="#94a3b8" stroke-width="1.5" fill="none"/>
        <path d="M5 8v12c0 2.21 4.03 4 9 4s9-1.79 9-4V8" stroke="#94a3b8" stroke-width="1.5" fill="none"/>
        <path d="M5 14c0 2.21 4.03 4 9 4s9-1.79 9-4" stroke="#94a3b8" stroke-width="1.5" fill="none" opacity="0.5"/>
        <text x="14" y="22" text-anchor="middle" font-size="4.5" font-weight="700" font-family="monospace" fill="#94a3b8">JDBC</text>
    </svg>`,
};

const CREDENTIAL_SCHEMA = [
    { id: 'driver', label: 'Database Driver', type: 'select', required: true, defaultValue: 'postgresql',
      options: [
        { value: 'postgresql', label: 'PostgreSQL' },
        { value: 'mysql', label: 'MySQL' },
        { value: 'sqlite', label: 'SQLite' },
        { value: 'teradata', label: 'Teradata' },
        { value: 'jdbc', label: 'JDBC (Generic)' },
      ] },
    { id: 'host', label: 'Host', type: 'text', placeholder: 'localhost', defaultValue: 'localhost', hideWhen: { field: 'driver', values: ['sqlite', 'jdbc'] } },
    { id: 'port', label: 'Port', type: 'text', placeholder: '5432', defaultValue: '5432', hideWhen: { field: 'driver', values: ['sqlite', 'jdbc'] } },
    { id: 'database', label: 'Database', type: 'text', placeholder: 'mydb (or file path for SQLite)', required: true, hideWhen: { field: 'driver', values: ['jdbc'] } },
    { id: 'user', label: 'Username', type: 'text', placeholder: 'postgres', hideWhen: { field: 'driver', values: ['sqlite'] } },
    { id: 'password', label: 'Password', type: 'password', placeholder: '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022', hideWhen: { field: 'driver', values: ['sqlite'] } },
    { id: 'ssl', label: 'Use SSL', type: 'checkbox', defaultValue: false, hideWhen: { field: 'driver', values: ['sqlite', 'teradata', 'jdbc'] } },
    { id: 'jdbc_url', label: 'JDBC URL', type: 'text', placeholder: 'jdbc:oracle:thin:@localhost:1521:xe', required: true, showWhen: { field: 'driver', values: ['jdbc'] } },
    { id: 'jdbc_driver_class', label: 'JDBC Driver Class', type: 'text', placeholder: 'oracle.jdbc.OracleDriver', required: true, showWhen: { field: 'driver', values: ['jdbc'] } },
    { id: 'jdbc_driver_path', label: 'JAR Path', type: 'text', placeholder: '/path/to/ojdbc8.jar', required: true, showWhen: { field: 'driver', values: ['jdbc'] } },
];

/**
 * Async-load and render the SQL Connections tab content.
 * Follows the same pattern as _loadProfileAssignments().
 */
async function _loadConnections() {
    const container = document.getElementById('component-connections');
    if (!container) return;
    _renderConnectionList(container);
}

/** Render the connection list view inside the given container. */
async function _renderConnectionList(container) {
    const token = localStorage.getItem('tda_auth_token');
    let connections = [];

    try {
        const resp = await fetch('/api/v1/canvas/connections', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (resp.ok) {
            const data = await resp.json();
            if (data.status === 'success') connections = data.connections;
        }
    } catch (err) {
        console.error('[ComponentHandler] Error loading connections:', err);
    }

    const emptyMsg = connections.length === 0
        ? `<div class="text-sm py-2" style="color:var(--text-muted)">No connections configured yet. Click "+ New Connection" to add one.</div>`
        : '';

    const cardsHTML = connections.map(conn => {
        const icon = DRIVER_ICONS[conn.driver] || DRIVER_ICONS.postgresql;
        const summary = conn.driver === 'jdbc'
            ? (conn.credentials.jdbc_url || '').substring(0, 50)
            : `${conn.credentials.host || ''}:${conn.credentials.port || ''}/${conn.credentials.database || ''}`;

        return `
            <div class="flex items-center justify-between py-2.5 px-3 rounded-lg bg-gray-800/30 border border-gray-700/20 comp-lt-row"
                 data-connection-id="${_escapeHtml(conn.connection_id)}">
                <div class="flex items-center gap-3 min-w-0">
                    <span class="flex-shrink-0" style="width:28px;height:28px;display:flex;align-items:center;justify-content:center;">${icon}</span>
                    <div class="min-w-0">
                        <div class="text-sm font-semibold truncate" style="color:var(--text-primary)">${_escapeHtml(conn.name)}</div>
                        <div class="text-xs truncate" style="color:var(--text-muted)">${_escapeHtml(summary)}</div>
                    </div>
                </div>
                <div class="flex items-center gap-2 flex-shrink-0">
                    <button class="conn-edit-btn text-xs px-2 py-1 rounded border border-cyan-500/30 text-cyan-300 comp-lt-text-cyan hover:bg-cyan-500/10 transition-colors"
                            data-connection-id="${_escapeHtml(conn.connection_id)}">Edit</button>
                    <button class="conn-del-btn text-xs px-2 py-1 rounded border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors"
                            data-connection-id="${_escapeHtml(conn.connection_id)}" data-connection-name="${_escapeHtml(conn.name)}">Del</button>
                </div>
            </div>`;
    }).join('');

    container.innerHTML = `
        <div class="flex items-center gap-2 mb-3">
            <h3 class="text-lg font-semibold" style="color:var(--text-primary)">SQL Connections</h3>
            <span class="text-xs" style="color:var(--text-muted)">${connections.length} connection${connections.length !== 1 ? 's' : ''}</span>
        </div>
        ${emptyMsg}
        <div class="space-y-2">${cardsHTML}</div>
        <button class="conn-new-btn mt-3 w-full py-2 rounded-lg border border-cyan-500/30 text-cyan-300 comp-lt-text-cyan text-sm font-semibold hover:bg-cyan-500/10 transition-colors">
            + New Connection
        </button>
    `;

    // Wire handlers
    container.querySelectorAll('.conn-edit-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const connId = btn.dataset.connectionId;
            const conn = connections.find(c => c.connection_id === connId);
            if (conn) _renderConnectionForm(container, connId, conn.credentials);
        });
    });
    container.querySelectorAll('.conn-del-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const connId = btn.dataset.connectionId;
            const connName = btn.dataset.connectionName;
            window.showConfirmation(
                'Delete Connection',
                `<p>Delete connection <strong>"${connName}"</strong>?</p>`,
                async () => {
                    try {
                        await fetch(`/api/v1/canvas/connections/${connId}`, {
                            method: 'DELETE',
                            headers: { 'Authorization': `Bearer ${token}` }
                        });
                        _renderConnectionList(container);
                    } catch (err) {
                        console.error('[ComponentHandler] Delete connection error:', err);
                    }
                }
            );
        });
    });
    container.querySelector('.conn-new-btn')?.addEventListener('click', () => {
        _renderConnectionForm(container, null, null);
    });
}

/** Render the connection create/edit form. */
function _renderConnectionForm(container, connectionId, existingCreds) {
    const inputClass = 'w-full px-3 py-2 text-sm rounded-lg border border-gray-600 bg-gray-800 text-gray-200 comp-lt-input placeholder-gray-500 focus:border-cyan-500 focus:outline-none transition-colors';
    const selectClass = inputClass;
    const btnClass = 'text-xs px-3 py-1.5 rounded border transition-colors';

    let formHTML = `
        <div class="flex items-center gap-2 mb-4">
            <button class="conn-back-btn text-sm text-cyan-300 comp-lt-text-cyan hover:underline">\u2190 Back to connections</button>
        </div>
        <div class="conn-status text-xs min-h-[1.5rem] px-3 py-1.5 rounded mb-3" style="color:var(--text-muted)"></div>
        <div class="space-y-3">
            <div>
                <label class="block text-xs font-medium mb-1" style="color:var(--text-muted)">Connection Name *</label>
                <input type="text" class="${inputClass}" id="conn-field-name" placeholder="e.g., Production PostgreSQL" value="${_escapeHtml(existingCreds?.name || '')}">
            </div>`;

    for (const field of CREDENTIAL_SCHEMA) {
        const val = existingCreds?.[field.id];
        const hideData = field.hideWhen ? `data-hide-when-field="${field.hideWhen.field}" data-hide-when-values="${field.hideWhen.values.join(',')}"` : '';
        const showData = field.showWhen ? `data-show-when-field="${field.showWhen.field}" data-show-when-values="${field.showWhen.values.join(',')}"` : '';

        formHTML += `<div class="conn-field-row" data-field-id="${field.id}" ${hideData} ${showData}>`;
        formHTML += `<label class="block text-xs font-medium mb-1" style="color:var(--text-muted)">${_escapeHtml(field.label)}${field.required ? ' *' : ''}</label>`;

        if (field.type === 'select') {
            const opts = (field.options || []).map(o => {
                const selected = (val !== undefined ? val : field.defaultValue) === o.value ? ' selected' : '';
                return `<option value="${o.value}"${selected}>${_escapeHtml(o.label)}</option>`;
            }).join('');
            formHTML += `<select class="${selectClass}" id="conn-field-${field.id}">${opts}</select>`;
        } else if (field.type === 'checkbox') {
            const checked = (val !== undefined ? val : field.defaultValue) ? ' checked' : '';
            formHTML += `<label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" id="conn-field-${field.id}" class="w-4 h-4 accent-cyan-500"${checked}><span class="text-sm" style="color:var(--text-primary)">Enable</span></label>`;
        } else {
            const inputType = field.type === 'password' ? 'password' : 'text';
            const inputVal = val !== undefined && val !== null ? _escapeHtml(String(val)) : (field.defaultValue !== undefined ? _escapeHtml(String(field.defaultValue)) : '');
            formHTML += `<input type="${inputType}" class="${inputClass}" id="conn-field-${field.id}" placeholder="${_escapeHtml(field.placeholder || '')}" value="${inputVal}">`;
        }
        formHTML += `</div>`;
    }

    formHTML += `</div>
        <div class="flex gap-2 mt-4 pt-3 border-t border-gray-700/30">
            <button class="conn-test-btn ${btnClass} border-gray-500 text-gray-300 hover:bg-gray-700/50">Test Connection</button>
            <button class="conn-save-btn ${btnClass} border-cyan-500/50 text-cyan-300 comp-lt-text-cyan font-semibold hover:bg-cyan-500/10">Save</button>
            ${connectionId ? `<button class="conn-delete-btn ${btnClass} border-red-500/30 text-red-400 hover:bg-red-500/10">Delete</button>` : ''}
        </div>`;

    container.innerHTML = formHTML;

    // Apply initial field visibility + wire driver change
    const applyVisibility = () => {
        const driverEl = document.getElementById('conn-field-driver');
        if (!driverEl) return;
        const driverVal = driverEl.value;

        container.querySelectorAll('.conn-field-row').forEach(row => {
            const hideField = row.dataset.hideWhenField;
            const showField = row.dataset.showWhenField;

            if (showField) {
                const vals = (row.dataset.showWhenValues || '').split(',');
                row.style.display = vals.includes(driverVal) ? '' : 'none';
            } else if (hideField) {
                const vals = (row.dataset.hideWhenValues || '').split(',');
                row.style.display = vals.includes(driverVal) ? 'none' : '';
            }
        });
    };
    const driverSelect = document.getElementById('conn-field-driver');
    if (driverSelect) driverSelect.addEventListener('change', applyVisibility);
    applyVisibility();

    // Collect form values
    const collectCreds = () => {
        const creds = { name: document.getElementById('conn-field-name')?.value || '' };
        for (const field of CREDENTIAL_SCHEMA) {
            const el = document.getElementById(`conn-field-${field.id}`);
            if (!el) continue;
            creds[field.id] = field.type === 'checkbox' ? el.checked : el.value;
        }
        return creds;
    };

    const showStatus = (ok, msg, info) => {
        const el = container.querySelector('.conn-status');
        if (!el) return;
        el.style.color = ok ? '#4ade80' : '#f87171';
        el.style.background = ok ? 'rgba(74,222,128,0.08)' : 'rgba(248,113,113,0.08)';
        el.textContent = info ? `${msg} — ${info}` : msg;
    };

    const token = localStorage.getItem('tda_auth_token');

    // Back
    container.querySelector('.conn-back-btn')?.addEventListener('click', () => _renderConnectionList(container));

    // Test
    container.querySelector('.conn-test-btn')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true; btn.textContent = 'Testing...';
        try {
            const resp = await fetch('/api/v1/canvas/connections/test', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ credentials: collectCreds() }),
            });
            const data = await resp.json();
            showStatus(data.valid, data.valid ? 'Connected' : (data.message || 'Connection failed'), data.server_info);
        } catch (err) {
            showStatus(false, err.message);
        } finally {
            btn.disabled = false; btn.textContent = 'Test Connection';
        }
    });

    // Save
    container.querySelector('.conn-save-btn')?.addEventListener('click', async (e) => {
        const creds = collectCreds();
        if (!creds.name?.trim()) { showStatus(false, 'Connection name is required'); return; }
        const btn = e.currentTarget;
        btn.disabled = true; btn.textContent = 'Saving...';
        try {
            const resp = await fetch('/api/v1/canvas/connections', {
                method: 'PUT',
                headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ connection_id: connectionId, credentials: creds }),
            });
            const data = await resp.json();
            if (data.status === 'success') {
                showStatus(true, 'Connection saved');
                setTimeout(() => _renderConnectionList(container), 600);
            } else {
                showStatus(false, data.message || 'Save failed');
            }
        } catch (err) {
            showStatus(false, err.message);
        } finally {
            btn.disabled = false; btn.textContent = 'Save';
        }
    });

    // Delete (edit mode only)
    container.querySelector('.conn-delete-btn')?.addEventListener('click', () => {
        const displayName = existingCreds?.name || connectionId;
        window.showConfirmation(
            'Delete Connection',
            `<p>Delete connection <strong>"${displayName}"</strong>?</p>`,
            async () => {
                try {
                    await fetch(`/api/v1/canvas/connections/${connectionId}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': `Bearer ${token}` }
                    });
                    _renderConnectionList(container);
                } catch (err) {
                    showStatus(false, err.message);
                }
            }
        );
    });
}

// ─── Detail Panel Helpers ───────────────────────────────────────────────────

function _hideDetailPanel() {
    const panel = document.getElementById(DETAIL_ID);
    if (panel) {
        panel.classList.add('hidden');
        panel.innerHTML = '';
    }
    _selectedComponentId = null;
}

function _showDetailError(message) {
    const panel = document.getElementById(DETAIL_ID);
    if (panel) {
        panel.innerHTML = `<div class="glass-panel rounded-xl p-6 text-center text-red-400">${message}</div>`;
        panel.classList.remove('hidden');
    }
}

function _escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ─── Event Handlers (Reload, Filters) ───────────────────────────────────────

/**
 * Initialize event handlers for the top-level Components view (once).
 */
function _initializeHandlers() {
    // Reload button
    const reloadBtn = document.getElementById(RELOAD_BTN_ID);
    if (reloadBtn) {
        reloadBtn.addEventListener('click', async () => {
            reloadBtn.disabled = true;
            try {
                const token = localStorage.getItem('tda_auth_token');
                const resp = await fetch('/api/v1/components/reload', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                if (resp.ok && data.status === 'success') {
                    if (window.showNotification) {
                        window.showNotification('success', `Reloaded ${data.loaded} component(s)`);
                    }
                    await _loadComponents();
                } else {
                    if (window.showNotification) {
                        window.showNotification('error', 'Failed to reload components');
                    }
                }
            } catch (err) {
                console.error('[ComponentHandler] Reload error:', err);
            } finally {
                reloadBtn.disabled = false;
            }
        });
    }

    // Category filter pills
    _setupFilterPills(CATEGORY_FILTERS_ID, (filter) => {
        _filterComponentCards('type', filter);
    });

    // Status filter pills
    _setupFilterPills(STATUS_FILTERS_ID, (filter) => {
        _filterComponentCards('status', filter);
    });
}

/**
 * Setup filter pill click handlers for a pill container.
 */
function _setupFilterPills(containerId, onFilter) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.querySelectorAll('.filter-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            container.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('filter-pill--active'));
            pill.classList.add('filter-pill--active');
            onFilter(pill.dataset.filter);
        });
    });
}

/**
 * Filter component cards by type or status.
 */
function _filterComponentCards(dimension, filter) {
    const grid = document.getElementById(GRID_ID);
    if (!grid) return;

    grid.querySelectorAll('.component-card').forEach(card => {
        let visible = true;

        if (dimension === 'type' && filter !== 'all') {
            visible = card.dataset.componentType === filter;
        }
        if (dimension === 'status' && filter !== 'all') {
            visible = filter === 'active';
        }

        card.style.display = visible ? '' : 'none';
    });
}
