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

    // Update selection ring
    const grid = document.getElementById(GRID_ID);
    if (grid) {
        grid.querySelectorAll('.component-card').forEach(card => {
            if (card.dataset.componentId === componentId) {
                card.classList.add('ring-2', 'ring-cyan-400/60');
            } else {
                card.classList.remove('ring-2', 'ring-cyan-400/60');
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

    const enabledFor = (profileDefaults.enabled_for || []).map(p =>
        `<span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 comp-lt-emerald text-xs">${p}</span>`
    ).join('');

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

        const profileTypeClasses = {
            tool_enabled: 'bg-orange-500/20 text-orange-300 comp-lt-orange',
            llm_only: 'bg-blue-500/20 text-blue-300 comp-lt-blue',
            rag_focused: 'bg-purple-500/20 text-purple-300 comp-lt-purple',
            genie: 'bg-pink-500/20 text-pink-300 comp-lt-pink',
        };

        const rowsHTML = profiles.map(profile => {
            const compConfig = (profile.componentConfig || {})[componentId] || {};
            const isEnabled = compConfig.enabled !== undefined ? compConfig.enabled : true;
            const intensity = compConfig.intensity || comp.profile_defaults?.default_intensity || 'medium';
            const typeBadge = profileTypeClasses[profile.profile_type] || 'bg-gray-500/20 text-gray-300 comp-lt-gray';

            const intensitySelect = isAction ? `
                <select class="profile-comp-intensity text-xs bg-gray-800 border border-gray-600 text-gray-300 comp-lt-select rounded px-2 py-1"
                        data-profile-id="${profile.id}" ${!isEnabled ? 'disabled' : ''}>
                    <option value="minimal" ${intensity === 'minimal' ? 'selected' : ''}>Minimal</option>
                    <option value="low" ${intensity === 'low' ? 'selected' : ''}>Low</option>
                    <option value="medium" ${intensity === 'medium' ? 'selected' : ''}>Medium</option>
                    <option value="high" ${intensity === 'high' ? 'selected' : ''}>High</option>
                </select>` : '';

            return `
                <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/30 border border-gray-700/20 comp-lt-row">
                    <div class="flex items-center gap-3 min-w-0">
                        <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300 comp-lt-cyan flex-shrink-0">@${_escapeHtml(profile.tag || '?')}</span>
                        <span class="text-sm truncate" style="color:var(--text-primary)">${_escapeHtml(profile.name || profile.id)}</span>
                        <span class="text-[10px] px-1.5 py-0.5 rounded ${typeBadge} uppercase tracking-wider flex-shrink-0">${profile.profile_type}</span>
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
