/**
 * Component Handler
 *
 * Manages the Components Configuration tab UI:
 * - Fetches component list from GET /v1/components
 * - Renders card grid with category/status filter pills
 * - Reload button for hot-reload from disk
 * - Import button governance (hidden when admin disables user components)
 */

let _componentSettings = {};

/**
 * Load components from the API and render the card grid.
 */
export async function loadComponents() {
    const grid = document.getElementById('components-grid');
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
        const components = data.components || [];
        _componentSettings = data._settings || {};

        // Governance: show/hide Import button
        const importBtn = document.getElementById('import-component-btn');
        if (importBtn) {
            importBtn.style.display = _componentSettings.user_components_enabled ? '' : 'none';
        }

        if (components.length === 0) {
            grid.innerHTML = '<div class="col-span-full text-center text-gray-400 py-8">No components installed</div>';
            return;
        }

        grid.innerHTML = components.map(comp => _renderComponentCard(comp)).join('');

    } catch (err) {
        console.error('[ComponentHandler] Error loading components:', err);
        grid.innerHTML = '<div class="col-span-full text-center text-red-400 py-8">Error loading components</div>';
    }
}

/**
 * Render a single component card as an HTML string.
 */
function _renderComponentCard(comp) {
    const sourceColors = {
        builtin: 'bg-violet-500/20 text-violet-300',
        agent_pack: 'bg-cyan-500/20 text-cyan-300',
        user: 'bg-amber-500/20 text-amber-300',
    };
    const typeColors = {
        action: 'bg-blue-500/20 text-blue-300',
        structural: 'bg-gray-500/20 text-gray-300',
    };

    const sourceBadge = sourceColors[comp.source] || sourceColors.builtin;
    const typeBadge = typeColors[comp.component_type] || typeColors.action;
    const toolName = comp.tool_name ? `<span class="text-xs font-mono text-gray-500">${comp.tool_name}</span>` : '';

    const renderTargets = (comp.render_targets?.supports || ['inline']).map(t =>
        `<span class="text-xs px-1.5 py-0.5 rounded bg-gray-600/50 text-gray-400">${t}</span>`
    ).join('');

    return `
        <div class="glass-panel rounded-lg p-4 flex flex-col gap-3 component-card"
             data-component-type="${comp.component_type}"
             data-component-source="${comp.source}"
             data-component-id="${comp.component_id}">
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <h4 class="text-sm font-semibold text-white">${comp.display_name}</h4>
                    <p class="text-xs text-gray-400 mt-0.5">${comp.description || ''}</p>
                </div>
                <div class="flex items-center gap-1.5 ml-2">
                    <span class="text-xs px-1.5 py-0.5 rounded ${sourceBadge}">${comp.source}</span>
                    <span class="text-xs px-1.5 py-0.5 rounded ${typeBadge}">${comp.component_type}</span>
                </div>
            </div>
            <div class="flex items-center justify-between text-xs">
                <div class="flex items-center gap-2">
                    ${toolName}
                    <span class="text-gray-500">v${comp.version}</span>
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

/**
 * Initialize event handlers for the Components tab.
 */
export function initializeComponentHandlers() {
    // Reload button
    const reloadBtn = document.getElementById('reload-components-btn');
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
                    await loadComponents();
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
    _setupFilterPills('component-category-filters', (filter) => {
        _filterComponentCards('type', filter);
    });

    // Status filter pills
    _setupFilterPills('component-status-filters', (filter) => {
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
            // Update active state
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
    const grid = document.getElementById('components-grid');
    if (!grid) return;

    grid.querySelectorAll('.component-card').forEach(card => {
        let visible = true;

        if (dimension === 'type' && filter !== 'all') {
            visible = card.dataset.componentType === filter;
        }
        if (dimension === 'status' && filter !== 'all') {
            // For now, all loaded components are "active"
            visible = filter === 'active';
        }

        card.style.display = visible ? '' : 'none';
    });
}
