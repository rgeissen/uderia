/**
 * platformConnectorAdminHandler.js
 *
 * Admin Panel — "Components" tab → "Connectors" section
 * Governs platform-level capability connectors (browser, files, shell, web, google).
 * Strictly separate from user-configured data source servers (Configuration → MCP Servers).
 *
 * Layout: filter chips + compact card list (left) | governance detail panel (right)
 * Browse Registry modal: source tabs with inline "+ Add Registry" form tab.
 */

// ── Helpers ───────────────────────────────────────────────────────────────────

function _pconnHeaders(json = true) {
    const h = {};
    if (json) h['Content-Type'] = 'application/json';
    const token = localStorage.getItem('tda_auth_token');
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
}

function _pconnNotify(type, msg) {
    if (window.showNotification) window.showNotification(type, msg);
    else console.log(`[PlatformConnector] ${type}: ${msg}`);
}

function _pconnConfirm(message, onConfirm) {
    if (window.showConfirmation) {
        window.showConfirmation(message, onConfirm);
    } else {
        if (confirm(message)) onConfirm();
    }
}

// ── State ─────────────────────────────────────────────────────────────────────

let _pconnRegistrySources   = [];
let _pconnInstalledServers  = [];
let _pconnActiveSource      = 'builtin';
let _pconnBrowseResults     = [];
let _pconnNextCursor        = '';
let _pconnSearchTimeout     = null;
let _pconnCredentialsServerId = null;
let _pconnLoadingMore       = false;
let _pconnCurrentSearch     = '';
let _pmcpActiveTag          = null;  // null = All; string = active tag filter

// Admin split-panel state
let _paTypeFilter   = 'all';   // 'all' | 'platform' | 'user'
let _paStatusFilter = 'all';   // 'all' | 'enabled' | 'disabled'
let _paSelectedId   = null;    // selected connector id

// ── Status badge ──────────────────────────────────────────────────────────────

const INSTALL_STATUS = {
    not_installed: { label: 'Not installed', color: 'text-gray-400',   bg: 'bg-gray-400/10',   ring: 'ring-gray-400/20'   },
    installing:    { label: 'Installing…',   color: 'text-yellow-400', bg: 'bg-yellow-400/10', ring: 'ring-yellow-400/20' },
    installed:     { label: 'Installed',     color: 'text-emerald-400', bg: 'bg-emerald-400/10', ring: 'ring-emerald-400/20' },
    unavailable:   { label: 'Unavailable',   color: 'text-red-400',    bg: 'bg-red-400/10',    ring: 'ring-red-400/20'   },
    error:         { label: 'Error',         color: 'text-red-400',    bg: 'bg-red-400/10',    ring: 'ring-red-400/20'   },
};

function _statusBadge(status) {
    const cfg = INSTALL_STATUS[status] || INSTALL_STATUS.not_installed;
    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ring-1 ${cfg.bg} ${cfg.color} ${cfg.ring}">${cfg.label}</span>`;
}

// ── Load & render entry point ─────────────────────────────────────────────────

async function loadPlatformConnectorAdminPanel() {
    const container = document.getElementById('platform-connector-admin-container');
    if (container) {
        container.innerHTML = `
            <div class="flex items-center gap-3 py-6 text-gray-400">
                <svg class="animate-spin h-5 w-5 text-indigo-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                <span class="text-sm">Loading platform connectors…</span>
            </div>`;
    }
    await Promise.all([_loadRegistrySources(), _loadInstalledServers()]);
    // Auto-select first installed connector
    if (!_paSelectedId && _pconnInstalledServers.length > 0) {
        _paSelectedId = _pconnInstalledServers[0].id;
    }
    renderPlatformConnectorAdminPanel();
}

async function _loadRegistrySources() {
    try {
        const r = await fetch('/api/v1/connector-registry/sources', { headers: _pconnHeaders(false) });
        if (r.ok) _pconnRegistrySources = (await r.json()).sources || [];
    } catch (e) { console.error('Failed to load connector registry sources', e); }
}

async function _loadInstalledServers() {
    try {
        const r = await fetch('/api/v1/platform-connectors', { headers: _pconnHeaders(false) });
        if (r.ok) _pconnInstalledServers = (await r.json()).servers || [];
    } catch (e) { console.error('Failed to load installed platform connectors', e); }
}

// ── Main render ───────────────────────────────────────────────────────────────

function renderPlatformConnectorAdminPanel() {
    const container = document.getElementById('platform-connector-admin-container');
    if (!container) return;

    const filtered = _paFilteredServers();

    container.innerHTML = `
        <!-- Header -->
        <div class="flex items-center justify-between mb-5">
            <div>
                <h3 class="text-sm font-semibold text-white">Platform Connectors</h3>
                <p class="text-xs text-gray-400 mt-0.5">
                    ${_pconnInstalledServers.length} installed · Manage governance, credentials, and access per connector
                </p>
            </div>
            <button onclick="openPlatformConnectorMarketplace()"
                    class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-all hover:bg-indigo-500/20"
                    style="background:rgba(129,140,248,0.12);border:1px solid rgba(129,140,248,0.3);color:#818cf8">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
                </svg>
                Browse Registry
            </button>
        </div>

        <!-- Filter chips -->
        <div class="flex flex-wrap items-center gap-4 mb-4">
            <div class="flex items-center gap-1">
                <span class="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mr-1">Type</span>
                ${_paFilterChip('pa-type-filters', 'all',      'All',      _paTypeFilter,   'setPaTypeFilter')}
                ${_paFilterChip('pa-type-filters', 'platform', 'Platform', _paTypeFilter,   'setPaTypeFilter')}
                ${_paFilterChip('pa-type-filters', 'user',     'User',     _paTypeFilter,   'setPaTypeFilter')}
            </div>
            <div class="flex items-center gap-1">
                <span class="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mr-1">Status</span>
                ${_paFilterChip('pa-status-filters', 'all',      'All',      _paStatusFilter, 'setPaStatusFilter')}
                ${_paFilterChip('pa-status-filters', 'enabled',  'Enabled',  _paStatusFilter, 'setPaStatusFilter')}
                ${_paFilterChip('pa-status-filters', 'disabled', 'Disabled', _paStatusFilter, 'setPaStatusFilter')}
            </div>
        </div>

        ${_pconnInstalledServers.length === 0
            ? _renderAdminEmptyState()
            : `<div class="flex gap-4" style="min-height:420px">
                   <!-- Left: card list -->
                   <div id="pa-card-list" class="flex-shrink-0 space-y-1.5 overflow-y-auto" style="width:230px">
                       ${filtered.length === 0
                           ? `<p class="text-xs text-gray-500 py-3 px-1">No connectors match the current filter.</p>`
                           : filtered.map(_renderAdminCardItem).join('')}
                   </div>
                   <!-- Right: detail panel -->
                   <div id="pa-detail-panel" class="flex-1 min-w-0 overflow-y-auto">
                       ${_renderAdminDetailPanel(filtered.find(s => s.id === _paSelectedId) || null)}
                   </div>
               </div>`
        }

        ${_renderMarketplaceModal()}
        ${_renderCredentialsModal()}
    `;

    // Apply selection highlight on the rendered cards
    if (_paSelectedId) _applyAdminCardSelection(_paSelectedId);
}

// ── Filter helpers ────────────────────────────────────────────────────────────

function _paFilterChip(groupId, value, label, active, handler) {
    const isActive = active === value;
    return `<button onclick="${handler}('${value}')"
                    class="px-2.5 py-1 rounded-full text-[11px] font-medium transition-all"
                    style="${isActive
                        ? 'background:rgba(129,140,248,0.18);border:1px solid rgba(129,140,248,0.40);color:#818cf8'
                        : 'background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);color:#6b7280'}">
                ${label}
            </button>`;
}

function _paFilteredServers() {
    return _pconnInstalledServers.filter(s => {
        if (_paTypeFilter === 'platform' &&  s.requires_user_auth) return false;
        if (_paTypeFilter === 'user'     && !s.requires_user_auth) return false;
        if (_paStatusFilter === 'enabled'  && !s.enabled) return false;
        if (_paStatusFilter === 'disabled' &&  s.enabled) return false;
        return true;
    });
}

function setPaTypeFilter(value) {
    _paTypeFilter = value;
    _rerenderAdminLists();
}

function setPaStatusFilter(value) {
    _paStatusFilter = value;
    _rerenderAdminLists();
}

function _rerenderAdminLists() {
    // Re-render only filters + card list + detail panel (no full repaint)
    const filtered = _paFilteredServers();
    const cardList = document.getElementById('pa-card-list');
    if (cardList) {
        cardList.innerHTML = filtered.length === 0
            ? `<p class="text-xs text-gray-500 py-3 px-1">No connectors match the current filter.</p>`
            : filtered.map(_renderAdminCardItem).join('');
        if (_paSelectedId) _applyAdminCardSelection(_paSelectedId);
    }
    // Re-render filter chips
    const container = document.getElementById('platform-connector-admin-container');
    if (container) {
        container.querySelectorAll('.pa-filter-chip').forEach(btn => btn.remove());
    }
    // Simplest approach: just call renderPlatformConnectorAdminPanel for filter chip refresh
    // but preserve modal open state — actually just re-render fully:
    renderPlatformConnectorAdminPanel();
}

// ── Admin card list item ──────────────────────────────────────────────────────

function _renderAdminCardItem(server) {
    const isSelected = server.id === _paSelectedId;
    const typeLabel  = server.requires_user_auth ? 'User' : 'Platform';
    const typeColor  = server.requires_user_auth ? 'rgba(251,191,36,0.15)' : 'rgba(129,140,248,0.15)';
    const typeText   = server.requires_user_auth ? '#fbbf24' : '#818cf8';

    return `
        <div class="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all admin-connector-card"
             data-connector-id="${_paEsc(server.id)}"
             onclick="selectAdminConnector('${_paEsc(server.id)}')"
             style="${isSelected
                ? 'background:rgba(129,140,248,0.12);outline:2px solid rgba(129,140,248,0.5);outline-offset:-2px'
                : 'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06)'}">
            <!-- Icon -->
            <div class="w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center"
                 style="background:rgba(129,140,248,0.1)">
                ${_paServerIcon(server.id)}
            </div>
            <!-- Name + badges -->
            <div class="flex-1 min-w-0">
                <p class="text-xs font-semibold truncate" style="color:var(--text-primary)">${_paEsc(server.display_name || server.name)}</p>
                <div class="flex items-center gap-1.5 mt-0.5">
                    <span class="text-[10px] px-1.5 py-0.5 rounded font-medium"
                          style="background:${typeColor};color:${typeText}">${typeLabel}</span>
                    <span class="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0"
                          style="background:${server.enabled ? '#34d399' : '#6b7280'}"></span>
                    <span class="text-[10px]" style="color:${server.enabled ? '#34d399' : '#6b7280'}">${server.enabled ? 'Enabled' : 'Disabled'}</span>
                </div>
            </div>
        </div>`;
}

function selectAdminConnector(serverId) {
    _paSelectedId = serverId;
    _applyAdminCardSelection(serverId);
    const server = _pconnInstalledServers.find(s => s.id === serverId);
    const detailPanel = document.getElementById('pa-detail-panel');
    if (detailPanel && server) {
        detailPanel.innerHTML = _renderAdminDetailPanel(server);
    }
}

function _applyAdminCardSelection(serverId) {
    document.querySelectorAll('.admin-connector-card').forEach(card => {
        if (card.dataset.connectorId === serverId) {
            card.style.background    = 'rgba(129,140,248,0.12)';
            card.style.outline       = '2px solid rgba(129,140,248,0.5)';
            card.style.outlineOffset = '-2px';
            card.style.border        = 'none';
        } else {
            card.style.background    = 'rgba(255,255,255,0.03)';
            card.style.outline       = '';
            card.style.outlineOffset = '';
            card.style.border        = '1px solid rgba(255,255,255,0.06)';
        }
    });
}

// ── Admin detail panel ────────────────────────────────────────────────────────

function _renderAdminDetailPanel(server) {
    if (!server) {
        return `<div class="flex flex-col items-center justify-center h-full py-16 text-center">
                    <div class="w-12 h-12 rounded-full flex items-center justify-center mb-3"
                         style="background:rgba(129,140,248,0.08)">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5"/>
                        </svg>
                    </div>
                    <p class="text-sm text-gray-400">Select a connector to configure it</p>
                </div>`;
    }

    const enabled        = !!server.enabled;
    const autoOptIn      = !!server.auto_opt_in;
    const userCanOptOut  = !!server.user_can_opt_out;
    const userCanCfgTools = !!server.user_can_configure_tools;
    const allTools       = _getBuiltinToolsForServer(server.id);
    const permitted      = Array.isArray(server.available_tools) ? new Set(server.available_tools) : null;

    return `
        <div class="glass-panel rounded-xl overflow-hidden">

            <!-- Detail header -->
            <div class="p-5 flex items-start gap-4">
                <div class="w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center ring-1"
                     style="background:rgba(129,140,248,0.1);ring-color:rgba(129,140,248,0.2)">
                    ${_paServerIcon(server.id)}
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="text-sm font-bold" style="color:var(--text-primary)">${_paEsc(server.display_name || server.name)}</span>
                        <span class="text-xs text-gray-500">v${_paEsc(server.version || '0.0.0')}</span>
                        ${_statusBadge(server.install_status || 'installed')}
                        ${server.requires_user_auth
                            ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ring-1 bg-yellow-400/10 text-yellow-400 ring-yellow-400/20">OAuth per user</span>'
                            : ''}
                    </div>
                    <p class="text-xs text-gray-400 mt-1">${_paEsc(server.description || '')}</p>
                </div>
                <!-- Master enable toggle -->
                <div class="flex-shrink-0 flex items-center gap-2">
                    <span class="text-xs ${enabled ? 'text-emerald-400' : 'text-gray-500'}">${enabled ? 'Enabled' : 'Disabled'}</span>
                    <label class="ind-toggle ind-toggle--primary">
                        <input type="checkbox" ${enabled ? 'checked' : ''}
                               onchange="togglePlatformConnector('${server.id}', this.checked)">
                        <span class="ind-track"></span>
                    </label>
                </div>
            </div>

            ${enabled ? `
            <!-- Governance section -->
            <div class="border-t border-white/5 px-5 py-4 space-y-4">

                <div>
                    <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-3">Access Governance</p>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
                        ${_govToggle(server.id, 'auto_opt_in',              autoOptIn,       'Auto opt-in',        'Active on all profiles by default')}
                        ${_govToggle(server.id, 'user_can_opt_out',         userCanOptOut,   'User can opt out',   'Users may disable per profile')}
                        ${_govToggle(server.id, 'user_can_configure_tools', userCanCfgTools, 'User selects tools', 'Users may pick individual tools')}
                    </div>
                </div>

                <div>
                    <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">Permitted Tools
                        <span class="normal-case font-normal text-gray-600 ml-1">(all checked = no restriction)</span>
                    </p>
                    <div class="flex flex-wrap gap-2">
                        ${allTools.length === 0
                            ? '<span class="text-xs text-gray-500">No tool list available</span>'
                            : allTools.map(t => {
                                const on = permitted === null || permitted.has(t);
                                return `<label class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium cursor-pointer transition-all ring-1
                                                ${on ? 'bg-indigo-500/10 text-indigo-300 ring-indigo-500/30' : 'bg-gray-700/60 text-gray-500 ring-white/5'}"
                                               title="${on ? 'Click to restrict' : 'Click to allow'}">
                                            <input type="checkbox" ${on ? 'checked' : ''} class="sr-only"
                                                   onchange="togglePlatformConnectorAvailableTool('${server.id}', '${t}', this.checked)">
                                            <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 ${on ? 'text-indigo-400' : 'text-gray-600'}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                                                ${on
                                                    ? '<path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>'
                                                    : '<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>'}
                                            </svg>
                                            ${_paEsc(t)}
                                        </label>`;
                              }).join('')
                        }
                    </div>
                </div>
            </div>
            ` : `
            <!-- Disabled hint -->
            <div class="border-t border-white/5 px-5 py-3">
                <p class="text-xs text-gray-500">${server.requires_user_auth
                    ? 'Set OAuth credentials below, then enable this connector to make it available to users.'
                    : 'Enable this connector to configure governance settings and make it available to users.'}</p>
            </div>
            `}

            <!-- Footer actions -->
            <div class="border-t border-white/5 px-5 py-3 flex items-center justify-between">
                <button onclick="openPlatformConnectorCredentials('${server.id}')"
                        class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all hover:bg-indigo-500/10"
                        style="border:1px solid rgba(129,140,248,0.25);color:#818cf8">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"/>
                    </svg>
                    ${server.requires_user_auth ? 'OAuth Credentials' : 'Credentials &amp; env vars'}
                </button>
                <button onclick="_pconnConfirmRemove('${server.id}')"
                        class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all hover:bg-red-500/10 text-red-400"
                        style="border:1px solid rgba(248,113,113,0.2)">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                    Remove
                </button>
            </div>
        </div>`;
}

function _govToggle(serverId, field, checked, label, description) {
    return `
        <div class="p-2.5 rounded-lg" style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06)">
            <div class="flex items-center justify-between gap-2">
                <div class="flex-1 min-w-0">
                    <p class="text-xs font-medium text-white">${label}</p>
                    <p class="text-[10px] text-gray-500 mt-0.5 leading-snug">${description}</p>
                </div>
                <label class="ind-toggle flex-shrink-0">
                    <input type="checkbox" ${checked ? 'checked' : ''}
                           onchange="updatePlatformConnectorGovernance('${serverId}', '${field}', this.checked ? 1 : 0)">
                    <span class="ind-track"></span>
                </label>
            </div>
        </div>`;
}

// ── Empty states ──────────────────────────────────────────────────────────────

function _renderAdminEmptyState() {
    return `
        <div class="glass-panel rounded-xl p-10 flex flex-col items-center gap-4 text-center">
            <div class="w-14 h-14 rounded-full flex items-center justify-center"
                 style="background:rgba(129,140,248,0.1);border:1px solid rgba(129,140,248,0.2)">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"/>
                </svg>
            </div>
            <div>
                <p class="text-white font-semibold">No platform connectors installed</p>
                <p class="text-sm text-gray-400 mt-1">Browse the registry to add capability connectors like web search, file access, or shell execution.</p>
            </div>
            <button onclick="openPlatformConnectorMarketplace()"
                    class="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all hover:bg-indigo-500/20"
                    style="background:rgba(129,140,248,0.12);border:1px solid rgba(129,140,248,0.3);color:#818cf8">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
                </svg>
                Browse Registry
            </button>
        </div>`;
}

// ── Browse Registry modal (with inline "+ Add Registry" tab) ──────────────────

function _renderMarketplaceModal() {
    return `
        <div id="pmcp-marketplace-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4"
             style="background:rgba(0,0,0,0.7)" onclick="if(event.target===this)closePlatformConnectorMarketplace()">
            <div class="w-full max-w-2xl rounded-2xl shadow-2xl flex flex-col" style="background:var(--bg-secondary);max-height:84vh;border:1px solid var(--border-primary)">

                <!-- Header -->
                <div class="flex items-center justify-between px-6 py-4 border-b" style="border-color:var(--border-primary)">
                    <div>
                        <h2 class="text-base font-bold text-white">Connector Registry</h2>
                        <p class="text-xs text-gray-400 mt-0.5">Browse and install platform capability connectors</p>
                    </div>
                    <button onclick="closePlatformConnectorMarketplace()"
                            class="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>

                <!-- Source tabs row — rendered dynamically -->
                <div class="flex items-center gap-1 px-6 pt-4 pb-0 flex-wrap" id="pmcp-source-tabs"></div>

                <!-- Search bar (hidden when "+ Add Registry" tab is active) -->
                <div id="pmcp-search-bar" class="px-6 pt-3 pb-1">
                    <div class="relative">
                        <svg xmlns="http://www.w3.org/2000/svg" class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                        </svg>
                        <input id="pmcp-search-input" type="text" placeholder="Search connectors…"
                               class="w-full pl-9 pr-4 py-2 rounded-lg text-sm"
                               style="background:var(--bg-primary);border:1px solid var(--border-primary);color:var(--text-primary)"
                               oninput="onPmcpSearchInput(this.value)"/>
                    </div>
                </div>

                <!-- Tag filter bar (rendered dynamically when results load) -->
                <div id="pmcp-tag-bar" class="hidden px-6 pb-2 pt-1 flex flex-wrap gap-1.5"></div>

                <!-- Results area OR Add-Registry form (switched by tab) -->
                <div class="flex-1 overflow-y-auto px-6 py-3 space-y-2" id="pmcp-browse-results">
                    <div class="text-center py-8 text-sm text-gray-400">Loading…</div>
                </div>
            </div>
        </div>`;
}

function _renderCredentialsModal() {
    return `
        <div id="pmcp-credentials-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4"
             style="background:rgba(0,0,0,0.7)" onclick="if(event.target===this)closePlatformConnectorCredentials()">
            <div class="w-full max-w-lg rounded-2xl shadow-2xl" style="background:var(--bg-secondary);border:1px solid var(--border-primary)">
                <div class="flex items-center justify-between px-6 py-4 border-b" style="border-color:var(--border-primary)">
                    <div>
                        <h2 class="text-base font-bold text-white" id="pmcp-cred-title">Connector Credentials</h2>
                        <p class="text-xs text-gray-400 mt-0.5">Stored encrypted. Never returned to the browser after saving.</p>
                    </div>
                    <button onclick="closePlatformConnectorCredentials()"
                            class="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
                <div id="pmcp-cred-fields" class="px-6 py-5 space-y-4"></div>
                <div class="flex justify-end gap-2 px-6 py-4 border-t" style="border-color:var(--border-primary)">
                    <button onclick="closePlatformConnectorCredentials()"
                            class="px-4 py-2 text-sm rounded-lg text-gray-400 hover:text-white transition-colors">Cancel</button>
                    <button onclick="savePlatformConnectorCredentials()"
                            class="px-4 py-2 text-sm font-medium rounded-lg transition-all hover:bg-indigo-500/20 flex items-center gap-2"
                            style="background:rgba(129,140,248,0.12);border:1px solid rgba(129,140,248,0.3);color:#818cf8">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                        </svg>
                        Save encrypted
                    </button>
                </div>
            </div>
        </div>`;
}

// ── Marketplace open/close & tab rendering ────────────────────────────────────

const ADD_REGISTRY_TAB_ID = '__add_registry__';

function openPlatformConnectorMarketplace() {
    const modal = document.getElementById('pmcp-marketplace-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    _renderSourceTabs();
    _browseRegistry(_pconnActiveSource, '');
}

function closePlatformConnectorMarketplace() {
    const modal = document.getElementById('pmcp-marketplace-modal');
    if (modal) modal.classList.add('hidden');
}

function _renderSourceTabs() {
    const container = document.getElementById('pmcp-source-tabs');
    if (!container) return;

    const tabs = _pconnRegistrySources.map(s => {
        const active = _pconnActiveSource === s.id;
        const removeBtn = !s.is_builtin
            ? `<button onclick="event.stopPropagation();deleteRegistrySource('${s.id}')"
                       class="ml-1 w-4 h-4 rounded-full flex items-center justify-center text-gray-500 hover:text-red-400 hover:bg-red-400/10 transition-colors"
                       title="Remove registry">
                   <svg class="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                       <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                   </svg>
               </button>`
            : '';
        return `<button onclick="selectPmcpSource('${s.id}')"
                        class="inline-flex items-center px-3 py-1.5 text-xs rounded-lg mr-1 mb-1 transition-all font-medium"
                        style="${active
                            ? 'background:rgba(129,140,248,0.15);border:1px solid rgba(129,140,248,0.35);color:#818cf8'
                            : 'background:transparent;border:1px solid var(--border-primary);color:var(--text-muted)'}">
                    ${_paEsc(s.name)}
                    ${removeBtn}
                </button>`;
    });

    // "+ Add Registry" tab
    const addActive = _pconnActiveSource === ADD_REGISTRY_TAB_ID;
    tabs.push(`<button onclick="selectPmcpSource('${ADD_REGISTRY_TAB_ID}')"
                       class="inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg mr-1 mb-1 transition-all font-medium"
                       style="${addActive
                           ? 'background:rgba(129,140,248,0.15);border:1px solid rgba(129,140,248,0.35);color:#818cf8'
                           : 'background:transparent;border:1px dashed rgba(129,140,248,0.3);color:#6b7280'}">
                   <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                       <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
                   </svg>
                   Add Registry
               </button>`);

    container.innerHTML = tabs.join('');
}

function selectPmcpSource(sourceId) {
    _pconnActiveSource = sourceId;
    _renderSourceTabs();
    if (sourceId === ADD_REGISTRY_TAB_ID) {
        _showAddRegistryForm();
    } else {
        const searchBar = document.getElementById('pmcp-search-bar');
        if (searchBar) searchBar.classList.remove('hidden');
        const search = document.getElementById('pmcp-search-input');
        _browseRegistry(sourceId, search ? search.value : '');
    }
}

function _showAddRegistryForm() {
    const searchBar = document.getElementById('pmcp-search-bar');
    if (searchBar) searchBar.classList.add('hidden');
    const tagBar = document.getElementById('pmcp-tag-bar');
    if (tagBar) { tagBar.classList.add('hidden'); tagBar.innerHTML = ''; }

    const resultsEl = document.getElementById('pmcp-browse-results');
    if (!resultsEl) return;

    resultsEl.innerHTML = `
        <div class="max-w-md mx-auto py-4">
            <h3 class="text-sm font-semibold text-white mb-1">Add Enterprise Registry</h3>
            <p class="text-xs text-gray-400 mb-5">
                Point to a private connector registry that exposes the standard
                <code class="text-indigo-400">GET /v0.1/servers</code> endpoint.
            </p>
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-medium text-gray-400 mb-1.5">Registry name</label>
                    <input id="pmcp-source-name" type="text" placeholder="My Company Registry"
                           class="w-full px-3 py-2 rounded-lg text-sm"
                           style="background:var(--bg-primary);border:1px solid var(--border-primary);color:var(--text-primary)"/>
                </div>
                <div>
                    <label class="block text-xs font-medium text-gray-400 mb-1.5">URL</label>
                    <input id="pmcp-source-url" type="text" placeholder="https://mcp.yourcompany.com"
                           class="w-full px-3 py-2 rounded-lg text-sm"
                           style="background:var(--bg-primary);border:1px solid var(--border-primary);color:var(--text-primary)"/>
                </div>
            </div>
            <div class="flex justify-end gap-2 mt-6">
                <button onclick="closePlatformConnectorMarketplace()"
                        class="px-4 py-2 text-sm rounded-lg text-gray-400 hover:text-white transition-colors">Cancel</button>
                <button onclick="submitAddRegistrySource()"
                        class="px-4 py-2 text-sm font-medium rounded-lg transition-all hover:bg-indigo-500/20"
                        style="background:rgba(129,140,248,0.12);border:1px solid rgba(129,140,248,0.3);color:#818cf8">
                    Add Registry
                </button>
            </div>
        </div>`;
}

// Legacy compat — redirect old modal calls to the Browse Registry modal
function openAddRegistrySourceModal() {
    openPlatformConnectorMarketplace();
    // Small delay to let the modal render before switching to add tab
    setTimeout(() => selectPmcpSource(ADD_REGISTRY_TAB_ID), 50);
}
function closeAddRegistrySourceModal() { closePlatformConnectorMarketplace(); }

// ── Browse results ────────────────────────────────────────────────────────────

function onPmcpSearchInput(value) {
    clearTimeout(_pconnSearchTimeout);
    _pconnSearchTimeout = setTimeout(() => _browseRegistry(_pconnActiveSource, value), 350);
}

async function _browseRegistry(sourceId, search) {
    if (sourceId === ADD_REGISTRY_TAB_ID) return;
    const resultsEl = document.getElementById('pmcp-browse-results');
    if (!resultsEl) return;
    _pconnBrowseResults = [];
    _pconnNextCursor = '';
    _pmcpActiveTag = null;
    const tagBar = document.getElementById('pmcp-tag-bar');
    if (tagBar) { tagBar.classList.add('hidden'); tagBar.innerHTML = ''; }
    resultsEl.innerHTML = '<div class="text-center py-8 text-sm text-gray-400">Loading…</div>';
    try {
        const batch = await _fetchRegistryPage(sourceId, search, '');
        _pconnBrowseResults = batch.servers;
        _pconnNextCursor = batch.nextCursor;
        _renderBrowseResults(resultsEl);
    } catch (e) {
        resultsEl.innerHTML = `<div class="text-center py-6 text-sm text-red-400">Failed to load: ${_paEsc(e.message)}</div>`;
    }
}

async function _loadMoreRegistry() {
    if (_pconnLoadingMore || !_pconnNextCursor) return;
    _pconnLoadingMore = true;
    const btn = document.getElementById('pmcp-load-more-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
    try {
        const batch = await _fetchRegistryPage(_pconnActiveSource, _pconnCurrentSearch || '', _pconnNextCursor);
        _pconnBrowseResults = [..._pconnBrowseResults, ...batch.servers];
        _pconnNextCursor = batch.nextCursor;
        const resultsEl = document.getElementById('pmcp-browse-results');
        if (resultsEl) _renderBrowseResults(resultsEl);
    } catch (_) {
        const btn2 = document.getElementById('pmcp-load-more-btn');
        if (btn2) { btn2.disabled = false; btn2.textContent = 'Load more'; }
    } finally {
        _pconnLoadingMore = false;
    }
}

async function _fetchRegistryPage(sourceId, search, cursor) {
    _pconnCurrentSearch = search;
    const params = new URLSearchParams({ source: sourceId, search, page: 1 });
    if (cursor) params.set('cursor', cursor);
    const r = await fetch(`/api/v1/connector-registry/servers?${params}`, { headers: _pconnHeaders(false) });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    const nextCursor = (data.metadata && data.metadata.nextCursor) || '';
    const allNormalised = (data.servers || [])
        .filter(s => s != null)
        .map(_normaliseRegistryServer)
        .filter(s => s != null);
    const hasVersioning = allNormalised.some(s => s._is_latest === true);
    const servers = hasVersioning
        ? allNormalised.filter(s => s._is_latest !== false)
        : allNormalised;
    return { servers, nextCursor };
}

/**
 * Normalise a connector entry from any registry source.
 * Handles:
 *   1. Uderia built-in:  { id, display_name, name, version, tools, description, ... }
 *   2. Official Registry v0.1: { server: {...}, _meta: {...} }
 */
function _normaliseRegistryServer(raw) {
    if (!raw || typeof raw !== 'object') return null;

    const s    = (raw.server && typeof raw.server === 'object') ? raw.server : raw;
    const meta = raw._meta || {};

    const id          = s.id || s.name || `ext-${Math.random().toString(36).slice(2)}`;
    const displayName = s.display_name || s.title || s.name || id;
    const version     = s.version || (s.version_detail && s.version_detail.version) || '—';
    const rawTools    = Array.isArray(s.tools) ? s.tools : [];
    const tools       = rawTools.map(t => (typeof t === 'string' ? t : (t && t.name) || String(t)));

    let transportTag = null;
    if (Array.isArray(s.remotes) && s.remotes.length) {
        transportTag = 'Remote';
    } else if (Array.isArray(s.packages) && s.packages.length) {
        const rt = (s.packages[0].registryType || '').toLowerCase();
        if (rt === 'npm')       transportTag = 'npm';
        else if (rt === 'pypi') transportTag = 'Python';
        else if (rt === 'oci')  transportTag = 'Docker';
        else if (rt)            transportTag = rt;
    } else if (s.security_acknowledgment_required) {
        transportTag = 'Docker';
    }

    const requiresCredentials = Array.isArray(s.packages) &&
        s.packages.some(p => Array.isArray(p.environmentVariables) && p.environmentVariables.some(e => e.isRequired));

    const officialMeta = Object.values(meta)[0] || {};
    const isOfficial   = !!(officialMeta.status === 'active');

    return {
        ...s,
        id,
        display_name: displayName,
        version,
        tools,
        description: s.description || '',
        _transport_tag: transportTag,
        _requires_credentials: requiresCredentials,
        _is_official: isOfficial,
        _is_latest: Object.keys(meta).length ? !!(officialMeta.isLatest) : undefined,
    };
}

function _collectTags(servers) {
    const counts = {};
    for (const s of servers) {
        for (const tag of (s.tags || [])) {
            counts[tag] = (counts[tag] || 0) + 1;
        }
    }
    // Sort by frequency desc, then alphabetically
    return Object.entries(counts)
        .sort(([a, ca], [b, cb]) => cb - ca || a.localeCompare(b))
        .map(([tag]) => tag);
}

function _renderTagBar(allServers) {
    const tagBar = document.getElementById('pmcp-tag-bar');
    if (!tagBar) return;
    const tags = _collectTags(allServers);
    if (!tags.length) {
        tagBar.classList.add('hidden');
        tagBar.innerHTML = '';
        return;
    }
    tagBar.classList.remove('hidden');
    const allActive = _pmcpActiveTag === null;
    const chips = [null, ...tags].map(tag => {
        const isActive = tag === null ? allActive : _pmcpActiveTag === tag;
        const label = tag === null ? 'All' : tag;
        const matchCount = tag === null ? allServers.length : allServers.filter(s => (s.tags || []).includes(tag)).length;
        return `<button onclick="setPmcpTagFilter(${tag === null ? 'null' : `'${_paEsc(tag)}'`})"
                        class="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] rounded-full transition-all font-medium"
                        style="${isActive
                            ? 'background:rgba(129,140,248,0.2);border:1px solid rgba(129,140,248,0.45);color:#a5b4fc'
                            : 'background:rgba(255,255,255,0.04);border:1px solid var(--border-primary);color:var(--text-muted)'}">
                    ${_paEsc(label)}
                    <span class="text-[10px] opacity-60">${matchCount}</span>
                </button>`;
    });
    tagBar.innerHTML = chips.join('');
}

function setPmcpTagFilter(tag) {
    _pmcpActiveTag = tag;
    const container = document.getElementById('pmcp-browse-results');
    if (container) _renderBrowseResults(container);
}

function _renderBrowseResults(container) {
    const allServers = (_pconnBrowseResults || []).filter(s => s != null);
    if (!allServers.length) {
        container.innerHTML = '<div class="text-center py-8 text-sm text-gray-400">No connectors found.</div>';
        const tagBar = document.getElementById('pmcp-tag-bar');
        if (tagBar) { tagBar.classList.add('hidden'); tagBar.innerHTML = ''; }
        return;
    }

    // Update tag bar with all results (before filtering)
    _renderTagBar(allServers);

    // Apply active tag filter
    const servers = _pmcpActiveTag
        ? allServers.filter(s => (s.tags || []).includes(_pmcpActiveTag))
        : allServers;

    if (!servers.length) {
        container.innerHTML = '<div class="text-center py-8 text-sm text-gray-400">No connectors match this tag.</div>';
        return;
    }

    const installedIds = new Set((_pconnInstalledServers || []).filter(s => s).map(s => s.id));
    const cardsHtml = servers.map(s => {
        const isInstalled = installedIds.has(s.id);
        const tools = (s.tools || []).slice(0, 5);
        const extra = (s.tools || []).length - tools.length;
        return `
            <div class="rounded-xl p-4 flex items-start gap-3 transition-colors hover:bg-white/3"
                 style="background:var(--bg-primary);border:1px solid var(--border-primary)">
                <div class="w-9 h-9 rounded-lg flex-shrink-0 flex items-center justify-center ring-1 ring-indigo-500/20"
                     style="background:rgba(129,140,248,0.1)">
                    ${_paServerIcon(s.id)}
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="text-sm font-semibold text-white">${_paEsc(s.display_name)}</span>
                        ${s.version && s.version !== '—' ? `<span class="text-[11px] text-gray-500">v${_paEsc(s.version)}</span>` : ''}
                        ${_transportBadge(s._transport_tag)}
                        ${s._requires_credentials ? '<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-400/10 text-amber-400 ring-1 ring-amber-400/20">API key</span>' : ''}
                        ${s.requires_user_auth ? '<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-400/10 text-yellow-400 ring-1 ring-yellow-400/20">OAuth</span>' : ''}
                        ${s._is_latest === false ? '<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-500/15 text-gray-400 ring-1 ring-gray-500/20">older</span>' : ''}
                    </div>
                    ${s.id !== s.display_name ? `<p class="text-[10px] text-gray-600 font-mono mt-0.5 truncate">${_paEsc(s.id)}</p>` : ''}
                    <p class="text-xs text-gray-400 mt-0.5 line-clamp-2">${_paEsc(s.description || '')}</p>
                    ${tools.length ? `
                        <div class="flex flex-wrap gap-1 mt-2">
                            ${tools.map(t => `<span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/8 text-indigo-400 ring-1 ring-indigo-500/20">${_paEsc(String(t))}</span>`).join('')}
                            ${extra > 0 ? `<span class="text-[10px] text-gray-500">+${extra} more</span>` : ''}
                        </div>` : ''}
                </div>
                <div class="flex-shrink-0">
                    ${isInstalled
                        ? `<span class="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-emerald-400/10 text-emerald-400 ring-1 ring-emerald-400/20">
                               <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
                               Installed
                           </span>`
                        : `<button onclick="installPlatformConnector('${_paEsc(s.id)}')"
                                   class="text-xs px-3 py-1.5 rounded-lg font-medium transition-all hover:bg-indigo-500/20"
                                   style="background:rgba(129,140,248,0.12);border:1px solid rgba(129,140,248,0.3);color:#818cf8">
                               Install
                           </button>`
                    }
                </div>
            </div>`;
    }).join('');

    const filteredCount = servers.length;
    const totalCount = allServers.length;
    const countLabel = _pmcpActiveTag && filteredCount !== totalCount
        ? `${filteredCount} of ${totalCount} connector${totalCount !== 1 ? 's' : ''}`
        : `${totalCount} connector${totalCount !== 1 ? 's' : ''}`;

    const loadMoreHtml = _pconnNextCursor ? `
        <div class="pt-2 pb-1 text-center">
            <button id="pmcp-load-more-btn"
                    onclick="window._loadMoreRegistry()"
                    class="text-xs px-5 py-2 rounded-lg font-medium transition-all"
                    style="background:rgba(129,140,248,0.1);border:1px solid rgba(129,140,248,0.25);color:#818cf8">
                Load more
            </button>
            <p class="text-[10px] text-gray-600 mt-1">${totalCount} connectors loaded</p>
        </div>` : `
        <p class="text-center text-[10px] text-gray-600 py-2">${countLabel}</p>`;

    container.innerHTML = cardsHtml + loadMoreHtml;
}

// ── Server icons ──────────────────────────────────────────────────────────────

function _transportBadge(tag) {
    if (!tag) return '';
    const styles = {
        'Remote': 'bg-emerald-400/10 text-emerald-400 ring-emerald-400/25',
        'npm':    'bg-red-400/10 text-red-300 ring-red-400/20',
        'Python': 'bg-blue-400/10 text-blue-300 ring-blue-400/20',
        'Docker': 'bg-cyan-400/10 text-cyan-300 ring-cyan-400/20',
    };
    const cls = styles[tag] || 'bg-gray-400/10 text-gray-400 ring-gray-400/20';
    return `<span class="text-[10px] px-1.5 py-0.5 rounded-full ring-1 ${cls}">${_paEsc(tag)}</span>`;
}

function _paServerIcon(serverId) {
    const icons = {
        'uderia-web':     `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9"/></svg>`,
        'uderia-files':   `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>`,
        'uderia-browser': `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>`,
        'uderia-google':  `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>`,
        'uderia-teams':   `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>`,
        'uderia-outlook': `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>`,
        'uderia-slack':       `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"/></svg>`,
        'uderia-sharepoint': `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z"/></svg>`,
        'uderia-shell':   `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>`,
    };
    return icons[serverId] || `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2"/></svg>`;
}

// ── Credential schema ─────────────────────────────────────────────────────────

const CREDENTIAL_SCHEMAS = {
    'uderia-web':    [
        { key: 'BRAVE_API_KEY',  label: 'Brave Search API Key', hint: 'From https://brave.com/search/api/', type: 'password' },
        { key: 'SERPER_API_KEY', label: 'Serper API Key (alt)', hint: 'Alternative to Brave Search',        type: 'password' },
    ],
    'uderia-google': [
        { key: 'GOOGLE_CLIENT_ID',     label: 'Google OAuth Client ID',     hint: 'From Google Cloud Console → Credentials', type: 'text'     },
        { key: 'GOOGLE_CLIENT_SECRET', label: 'Google OAuth Client Secret', hint: 'Keep this secret',                        type: 'password' },
    ],
    'uderia-teams': [
        { key: 'AZURE_CLIENT_ID',     label: 'Azure App (Client) ID',     hint: 'Azure Portal → App registrations → your app → Overview', type: 'text'     },
        { key: 'AZURE_CLIENT_SECRET', label: 'Azure Client Secret',       hint: 'Azure Portal → App registrations → Certificates & secrets', type: 'password' },
    ],
    'uderia-outlook': [
        { key: 'AZURE_CLIENT_ID',     label: 'Azure App (Client) ID',     hint: 'Azure Portal → App registrations → your app → Overview', type: 'text'     },
        { key: 'AZURE_CLIENT_SECRET', label: 'Azure Client Secret',       hint: 'Azure Portal → App registrations → Certificates & secrets', type: 'password' },
    ],
    'uderia-slack': [
        { key: 'SLACK_CLIENT_ID',     label: 'Slack App Client ID',     hint: 'api.slack.com/apps → your app → Basic Information → App Credentials', type: 'text'     },
        { key: 'SLACK_CLIENT_SECRET', label: 'Slack App Client Secret', hint: 'Keep this secret',                                                      type: 'password' },
    ],
    'uderia-sharepoint': [
        { key: 'AZURE_CLIENT_ID',     label: 'Azure App (Client) ID',     hint: 'Azure Portal → App registrations → your app → Overview', type: 'text'     },
        { key: 'AZURE_CLIENT_SECRET', label: 'Azure Client Secret',       hint: 'Azure Portal → App registrations → Certificates & secrets', type: 'password' },
    ],
    'uderia-shell':  [
        { key: 'ALLOWED_COMMANDS', label: 'Allowed commands (CSV)', hint: 'e.g. python,pip,ls,cat — leave empty to allow all', type: 'text' },
        { key: 'DOCKER_IMAGE',     label: 'Docker image',           hint: 'Default: python:3.11-slim',                         type: 'text' },
    ],
};

const SETUP_GUIDES = {
    'uderia-google': {
        title: 'Google Cloud Console setup',
        steps: () => {
            const callbackUri = `${window.location.origin}/api/v1/connectors/google/callback`;
            return [
                'Go to <a href="https://console.cloud.google.com" target="_blank" rel="noopener" style="color:#818cf8;text-decoration:underline">console.cloud.google.com</a> and create a project',
                'Enable the <strong>Gmail API</strong> and <strong>Google Calendar API</strong> (APIs &amp; Services → Library)',
                'Create OAuth 2.0 credentials (APIs &amp; Services → Credentials → Create → OAuth client ID → Web application)',
                `Add <code style="font-size:10px;background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">${callbackUri}</code> as an Authorised redirect URI`,
                'Copy the Client ID and Client Secret below',
            ];
        },
    },
    'uderia-teams': {
        title: 'Azure App Registration setup (Teams)',
        steps: () => {
            const callbackUri = `${window.location.origin}/api/v1/connectors/teams/callback`;
            return [
                'Go to <a href="https://portal.azure.com" target="_blank" rel="noopener" style="color:#818cf8;text-decoration:underline">portal.azure.com</a> → Azure Active Directory → App registrations → New registration',
                'Set <strong>Supported account types</strong> to "Accounts in any organizational directory and personal Microsoft accounts"',
                `Add <code style="font-size:10px;background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">${callbackUri}</code> as a Redirect URI (Web platform)`,
                'Under <strong>API permissions</strong> add: Team.ReadBasic.All, Channel.ReadBasic.All, ChannelMessage.Read.All, ChannelMessage.Send, OnlineMeetings.ReadWrite, User.Read (all Delegated)',
                'Under <strong>Certificates &amp; secrets</strong> create a new client secret',
                'Copy the Application (client) ID from Overview and the client secret value below',
            ];
        },
    },
    'uderia-outlook': {
        title: 'Azure App Registration setup (Outlook)',
        steps: () => {
            const callbackUri = `${window.location.origin}/api/v1/connectors/outlook/callback`;
            return [
                'Go to <a href="https://portal.azure.com" target="_blank" rel="noopener" style="color:#818cf8;text-decoration:underline">portal.azure.com</a> → Azure Active Directory → App registrations → New registration',
                'Set <strong>Supported account types</strong> to "Accounts in any organizational directory and personal Microsoft accounts"',
                `Add <code style="font-size:10px;background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">${callbackUri}</code> as a Redirect URI (Web platform)`,
                'Under <strong>API permissions</strong> add: Mail.Read, Mail.Send, Mail.ReadWrite, Calendars.ReadWrite, Contacts.Read, User.Read (all Delegated)',
                'Under <strong>Certificates &amp; secrets</strong> create a new client secret',
                'Copy the Application (client) ID from Overview and the client secret value below',
            ];
        },
    },
    'uderia-slack': {
        title: 'Slack App setup',
        steps: () => {
            const callbackUri = `${window.location.origin}/api/v1/connectors/slack/callback`;
            return [
                'Go to <a href="https://api.slack.com/apps" target="_blank" rel="noopener" style="color:#818cf8;text-decoration:underline">api.slack.com/apps</a> → Create New App → From scratch',
                'Under <strong>OAuth &amp; Permissions</strong> → Redirect URLs, add: <code style="font-size:10px;background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">' + callbackUri + '</code>',
                'Add <strong>Bot Token Scopes</strong>: channels:read, channels:history, chat:write, users:read, files:read',
                'Add <strong>User Token Scopes</strong>: identity.basic, identity.email, search:read',
                'Under <strong>Basic Information</strong> copy the Client ID and Client Secret below',
                'Install the app to your workspace (OAuth &amp; Permissions → Install to Workspace)',
            ];
        },
    },
    'uderia-sharepoint': {
        title: 'Azure App Registration setup (SharePoint)',
        steps: () => {
            const callbackUri = `${window.location.origin}/api/v1/connectors/sharepoint/callback`;
            return [
                'Go to <a href="https://portal.azure.com" target="_blank" rel="noopener" style="color:#818cf8;text-decoration:underline">portal.azure.com</a> → Azure Active Directory → App registrations → New registration',
                'Set <strong>Supported account types</strong> to "Accounts in any organizational directory and personal Microsoft accounts"',
                `Add <code style="font-size:10px;background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">${callbackUri}</code> as a Redirect URI (Web platform)`,
                'Under <strong>API permissions</strong> add: Files.Read.All, Files.ReadWrite.All, Sites.Read.All, Sites.ReadWrite.All, User.Read (all Delegated)',
                'Under <strong>Certificates &amp; secrets</strong> create a new client secret',
                'Copy the Application (client) ID from Overview and the client secret value below',
            ];
        },
    },
};

function openPlatformConnectorCredentials(serverId) {
    _pconnCredentialsServerId = serverId;
    const server = _pconnInstalledServers.find(s => s.id === serverId);
    const name   = server ? (server.display_name || server.name) : serverId;
    const schema = CREDENTIAL_SCHEMAS[serverId] || [
        { key: 'API_KEY', label: 'API Key', hint: 'Sensitive — stored encrypted', type: 'password' },
    ];

    const modal = document.getElementById('pmcp-credentials-modal');
    if (!modal) return;

    document.getElementById('pmcp-cred-title').textContent = `${name} — Credentials`;

    const guide = SETUP_GUIDES[serverId];
    const guideHtml = guide ? `
        <div class="rounded-xl p-4 mb-1" style="background:rgba(129,140,248,0.06);border:1px solid rgba(129,140,248,0.15)">
            <p class="text-xs font-semibold mb-2" style="color:#a5b4fc">${_paEsc(guide.title)}</p>
            <ol class="space-y-1.5 list-none pl-0">
                ${guide.steps().map((step, i) => `
                    <li class="flex items-start gap-2 text-xs" style="color:var(--text-muted)">
                        <span class="flex-shrink-0 w-4 h-4 rounded-full text-[10px] font-bold flex items-center justify-center mt-0.5"
                              style="background:rgba(129,140,248,0.2);color:#818cf8">${i + 1}</span>
                        <span>${step}</span>
                    </li>`).join('')}
            </ol>
        </div>` : '';

    document.getElementById('pmcp-cred-fields').innerHTML = guideHtml + schema.map(f => `
        <div>
            <label class="block text-xs font-medium text-gray-300 mb-1.5">${_paEsc(f.label)}</label>
            <input type="${f.type || 'text'}" id="pmcp-cred-${f.key}"
                   placeholder="${f.type === 'password' ? '••••••••' : _paEsc(f.hint || '')}"
                   class="w-full px-3 py-2 rounded-lg text-sm"
                   style="background:var(--bg-primary);border:1px solid var(--border-primary);color:var(--text-primary)"/>
            ${f.hint ? `<p class="text-[11px] text-gray-500 mt-1">${_paEsc(f.hint)}</p>` : ''}
        </div>
    `).join('');

    modal.classList.remove('hidden');
}

function closePlatformConnectorCredentials() {
    const modal = document.getElementById('pmcp-credentials-modal');
    if (modal) modal.classList.add('hidden');
    _pconnCredentialsServerId = null;
}

async function savePlatformConnectorCredentials() {
    if (!_pconnCredentialsServerId) return;
    const schema = CREDENTIAL_SCHEMAS[_pconnCredentialsServerId] || [{ key: 'API_KEY' }];
    const creds = {};
    let hasValue = false;
    for (const f of schema) {
        const el = document.getElementById(`pmcp-cred-${f.key}`);
        if (el && el.value.trim()) { creds[f.key] = el.value.trim(); hasValue = true; }
    }
    if (!hasValue) { _pconnNotify('error', 'Enter at least one credential value'); return; }
    try {
        const r = await fetch(`/api/v1/platform-connectors/${_pconnCredentialsServerId}`, {
            method: 'PUT', headers: _pconnHeaders(),
            body: JSON.stringify({ credentials: creds }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Save failed');
        _pconnNotify('success', 'Credentials saved (encrypted)');
        closePlatformConnectorCredentials();
    } catch (e) {
        _pconnNotify('error', `Failed to save credentials: ${e.message}`);
    }
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function installPlatformConnector(serverId) {
    const serverData = _pconnBrowseResults.find(s => s.id === serverId);
    if (!serverData) return;
    try {
        const r = await fetch('/api/v1/connector-registry/servers/install', {
            method: 'POST', headers: _pconnHeaders(),
            body: JSON.stringify({ source_id: _pconnActiveSource, server_id: serverId, server_data: serverData }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Install failed');
        _pconnNotify('success', `${serverData.display_name || serverId} installed`);
        closePlatformConnectorMarketplace();
        _paSelectedId = serverId;
        await loadPlatformConnectorAdminPanel();
    } catch (e) {
        _pconnNotify('error', `Install failed: ${e.message}`);
    }
}

async function togglePlatformConnector(serverId, enabled) {
    try {
        const r = await fetch(`/api/v1/platform-connectors/${serverId}`, {
            method: 'PUT', headers: _pconnHeaders(),
            body: JSON.stringify({ enabled: enabled ? 1 : 0 }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Update failed');
        await _loadInstalledServers();
        renderPlatformConnectorAdminPanel();
    } catch (e) {
        _pconnNotify('error', `Failed to update connector: ${e.message}`);
    }
}

async function updatePlatformConnectorGovernance(serverId, field, value) {
    try {
        const r = await fetch(`/api/v1/platform-connectors/${serverId}`, {
            method: 'PUT', headers: _pconnHeaders(),
            body: JSON.stringify({ [field]: value }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Update failed');
    } catch (e) {
        _pconnNotify('error', `Failed to update governance: ${e.message}`);
    }
}

async function togglePlatformConnectorAvailableTool(serverId, toolName, enabled) {
    const server   = _pconnInstalledServers.find(s => s.id === serverId);
    if (!server) return;
    const allTools = _getBuiltinToolsForServer(serverId);
    let current = Array.isArray(server.available_tools) ? [...server.available_tools] : [...allTools];
    if (enabled) { if (!current.includes(toolName)) current.push(toolName); }
    else { current = current.filter(t => t !== toolName); }
    const updatedTools = current.length === allTools.length ? null : current;
    try {
        const r = await fetch(`/api/v1/platform-connectors/${serverId}`, {
            method: 'PUT', headers: _pconnHeaders(),
            body: JSON.stringify({ available_tools: updatedTools }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Update failed');
        const idx = _pconnInstalledServers.findIndex(s => s.id === serverId);
        if (idx >= 0) _pconnInstalledServers[idx].available_tools = updatedTools;
    } catch (e) {
        _pconnNotify('error', `Failed to update tools: ${e.message}`);
    }
}

function _pconnConfirmRemove(serverId) {
    const server = _pconnInstalledServers.find(s => s.id === serverId);
    const name   = server ? (server.display_name || server.name) : serverId;
    _pconnConfirm(
        `Remove "${name}"? This will clear all profile assignments for this connector.`,
        () => deletePlatformConnector(serverId)
    );
}

async function deletePlatformConnector(serverId) {
    const server = _pconnInstalledServers.find(s => s.id === serverId);
    const name   = server ? (server.display_name || server.name) : serverId;
    try {
        const r = await fetch(`/api/v1/platform-connectors/${serverId}`, {
            method: 'DELETE', headers: _pconnHeaders(false),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Delete failed');
        _pconnNotify('success', `${name} removed`);
        // Clear selection if removed connector was selected
        if (_paSelectedId === serverId) _paSelectedId = null;
        await loadPlatformConnectorAdminPanel();
    } catch (e) {
        _pconnNotify('error', `Failed to remove connector: ${e.message}`);
    }
}

// ── Registry source management ────────────────────────────────────────────────

async function submitAddRegistrySource() {
    const name = document.getElementById('pmcp-source-name')?.value.trim();
    const url  = document.getElementById('pmcp-source-url')?.value.trim();
    if (!name || !url) { _pconnNotify('error', 'Name and URL are required'); return; }
    try {
        const r = await fetch('/api/v1/connector-registry/sources', {
            method: 'POST', headers: _pconnHeaders(),
            body: JSON.stringify({ name, url }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Failed');
        _pconnNotify('success', `Registry "${name}" added`);
        await _loadRegistrySources();
        // Switch back to the new registry tab
        _pconnActiveSource = (_pconnRegistrySources.find(s => s.name === name) || {}).id || 'builtin';
        _renderSourceTabs();
        const searchBar = document.getElementById('pmcp-search-bar');
        if (searchBar) searchBar.classList.remove('hidden');
        _browseRegistry(_pconnActiveSource, '');
    } catch (e) {
        _pconnNotify('error', `Failed to add registry: ${e.message}`);
    }
}

async function deleteRegistrySource(sourceId) {
    const source = _pconnRegistrySources.find(s => s.id === sourceId);
    _pconnConfirm(`Remove registry "${source?.name || sourceId}"?`, async () => {
        try {
            const r = await fetch(`/api/v1/connector-registry/sources/${sourceId}`, {
                method: 'DELETE', headers: _pconnHeaders(false),
            });
            if (!r.ok) throw new Error((await r.json()).error || 'Delete failed');
            _pconnNotify('success', 'Registry removed');
            await _loadRegistrySources();
            // Fall back to builtin tab if the active source was deleted
            if (_pconnActiveSource === sourceId) _pconnActiveSource = 'builtin';
            _renderSourceTabs();
            _browseRegistry(_pconnActiveSource, '');
        } catch (e) {
            _pconnNotify('error', `Failed to remove registry: ${e.message}`);
        }
    });
}

// ── Platform Components admin sub-tab switcher ────────────────────────────────

function switchPlatformComponentsAdminTab(tabName) {
    document.querySelectorAll('.platform-comp-subtab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.platformTab === tabName);
    });
    document.querySelectorAll('.platform-comp-panel').forEach(panel => {
        panel.classList.toggle('hidden', panel.id !== `platform-comp-panel-${tabName}`);
    });
    if ((tabName === 'mcp-servers' || tabName === 'connectors') && typeof loadPlatformConnectorAdminPanel === 'function') {
        loadPlatformConnectorAdminPanel();
    }
    if (tabName === 'task-scheduler') {
        loadSchedulerAdminPanel();
    }
}

// ── Utility ───────────────────────────────────────────────────────────────────

function _getBuiltinToolsForServer(serverId) {
    const MAP = {
        'uderia-web':     ['web_search', 'web_fetch', 'web_extract'],
        'uderia-files':   ['read_file', 'write_file', 'list_dir', 'search_files'],
        'uderia-browser': ['navigate', 'click', 'fill_form', 'screenshot', 'scrape', 'extract_data'],
        'uderia-google':  ['read_emails', 'send_email', 'search_emails', 'list_calendar', 'create_event', 'get_contacts'],
        'uderia-teams':      ['list_teams', 'list_channels', 'get_messages', 'send_message', 'create_meeting'],
        'uderia-outlook':    ['read_emails', 'send_email', 'search_emails', 'list_calendar', 'create_event', 'get_contacts'],
        'uderia-slack':      ['list_channels', 'get_messages', 'send_message', 'search_messages', 'list_users'],
        'uderia-sharepoint': ['list_sites', 'list_libraries', 'list_files', 'read_file', 'upload_file', 'search_files'],
        'uderia-shell':   ['exec_command', 'run_script', 'list_processes', 'kill_process'],
    };
    return MAP[serverId] || [];
}

function _paEsc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Scheduler admin panel ─────────────────────────────────────────────────────

async function loadSchedulerAdminPanel() {
    const container = document.getElementById('scheduler-admin-container');
    if (!container) return;

    container.innerHTML = `<div class="flex items-center gap-2 py-4 text-gray-400 text-sm">
        <svg class="animate-spin h-4 w-4 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        Loading scheduler status…
    </div>`;

    let status = { running: false, globally_enabled: true, job_count: 0 };
    let apschedulerAvailable = true;
    try {
        const r = await fetch('/api/v1/scheduler/status', { headers: _pconnHeaders(false) });
        if (r.ok) status = await r.json();
        else apschedulerAvailable = false;
    } catch (e) {
        apschedulerAvailable = false;
    }

    const isEnabled = status.globally_enabled !== false;

    container.innerHTML = `
        <div class="space-y-4">
            <div class="glass-panel rounded-xl p-5 flex items-center gap-5">
                <div class="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0"
                     style="background:rgba(168,85,247,0.12);border:1px solid rgba(168,85,247,0.25)">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                </div>
                <div class="flex-1">
                    <div class="flex items-center gap-3 flex-wrap">
                        <span class="text-white font-semibold">Task Scheduler</span>
                        ${apschedulerAvailable
                            ? (status.running
                                ? `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-400/10 text-emerald-400 ring-1 ring-emerald-400/20">
                                       <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse inline-block"></span>Running
                                   </span>`
                                : `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-400/10 text-gray-400 ring-1 ring-gray-400/20">Stopped</span>`)
                            : `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-400/10 text-amber-400 ring-1 ring-amber-400/20">APScheduler not installed</span>`
                        }
                    </div>
                    <p class="text-xs text-gray-400 mt-1">
                        ${apschedulerAvailable
                            ? `${status.job_count} active job${status.job_count !== 1 ? 's' : ''} registered`
                            : 'Install APScheduler to enable: <code class="font-mono bg-gray-800 px-1 rounded">pip install apscheduler>=3.10</code>'
                        }
                    </p>
                </div>
                <div class="flex-shrink-0 flex items-center gap-2">
                    <span class="text-xs ${isEnabled ? 'text-emerald-400' : 'text-gray-500'}">${isEnabled ? 'Enabled' : 'Disabled'}</span>
                    <label class="ind-toggle ind-toggle--primary">
                        <input type="checkbox" id="scheduler-global-toggle" ${isEnabled ? 'checked' : ''}
                               onchange="window._toggleSchedulerGlobal(this.checked)">
                        <span class="ind-track"></span>
                    </label>
                </div>
            </div>

            <div class="glass-panel rounded-xl p-5 space-y-3">
                <p class="text-xs font-medium text-gray-400 uppercase tracking-wider">Admin controls</p>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs text-gray-300">
                    <div class="flex items-start gap-2">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-purple-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                        <span>Toggle above globally enables or disables the Task Scheduler component for all users.</span>
                    </div>
                    <div class="flex items-start gap-2">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-purple-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
                        </svg>
                        <span>Users enable the scheduler per-profile via Platform Components, then create tasks in the component's detail panel.</span>
                    </div>
                    <div class="flex items-start gap-2">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-purple-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                        </svg>
                        <span>Task results can be delivered via <strong>email</strong> (SMTP) or <strong>webhook</strong> per task.</span>
                    </div>
                    <div class="flex items-start gap-2">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-purple-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                        </svg>
                        <span>Supports <strong>cron expressions</strong> and <strong>interval scheduling</strong>. Overlap policy and per-task token budgets are user-configurable.</span>
                    </div>
                </div>
            </div>

            ${!apschedulerAvailable ? `
            <div class="glass-panel rounded-xl p-4 border border-amber-400/20 bg-amber-400/5">
                <div class="flex items-start gap-3">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-amber-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.464 0L3.34 16.5c-.77.833.193 2.5 1.732 2.5z"/>
                    </svg>
                    <div>
                        <p class="text-sm font-medium text-amber-400">APScheduler not installed</p>
                        <p class="text-xs text-gray-400 mt-1">The Task Scheduler component requires APScheduler. Install it and restart Uderia:</p>
                        <code class="block text-xs font-mono mt-2 px-3 py-2 rounded-lg bg-gray-900/60 text-purple-300 border border-white/5">pip install apscheduler>=3.10.0</code>
                    </div>
                </div>
            </div>` : ''}
        </div>
    `;
}

window._toggleSchedulerGlobal = async function(enabled) {
    try {
        const r = await fetch('/api/v1/admin/component-settings', { headers: _pconnHeaders(false) });
        const d = r.ok ? await r.json() : {};
        let disabled = (d.settings && d.settings.disabled_components) || [];
        if (enabled) {
            disabled = disabled.filter(id => id !== 'scheduler');
        } else {
            if (!disabled.includes('scheduler')) disabled.push('scheduler');
        }
        await fetch('/api/v1/admin/component-settings', {
            method: 'POST', headers: _pconnHeaders(),
            body: JSON.stringify({ disabled_components: disabled }),
        });
        _pconnNotify('success', `Task Scheduler ${enabled ? 'enabled' : 'disabled'} globally.`);
    } catch (e) {
        _pconnNotify('error', 'Failed to update scheduler setting.');
        const toggle = document.getElementById('scheduler-global-toggle');
        if (toggle) toggle.checked = !enabled;
    }
};

// ── Exports ───────────────────────────────────────────────────────────────────

window.loadPlatformConnectorAdminPanel        = loadPlatformConnectorAdminPanel;
window.renderPlatformConnectorAdminPanel      = renderPlatformConnectorAdminPanel;
window.switchPlatformComponentsAdminTab       = switchPlatformComponentsAdminTab;
window.openPlatformConnectorMarketplace       = openPlatformConnectorMarketplace;
window.closePlatformConnectorMarketplace      = closePlatformConnectorMarketplace;
window.selectPmcpSource                       = selectPmcpSource;
window.onPmcpSearchInput                      = onPmcpSearchInput;
window._loadMoreRegistry                      = _loadMoreRegistry;
window.installPlatformConnector               = installPlatformConnector;
window.togglePlatformConnector                = togglePlatformConnector;
window.updatePlatformConnectorGovernance      = updatePlatformConnectorGovernance;
window.togglePlatformConnectorAvailableTool   = togglePlatformConnectorAvailableTool;
window.deletePlatformConnector                = deletePlatformConnector;
window._pconnConfirmRemove                    = _pconnConfirmRemove;
window.openPlatformConnectorCredentials       = openPlatformConnectorCredentials;
window.closePlatformConnectorCredentials      = closePlatformConnectorCredentials;
window.savePlatformConnectorCredentials       = savePlatformConnectorCredentials;
window.openAddRegistrySourceModal             = openAddRegistrySourceModal;
window.closeAddRegistrySourceModal            = closeAddRegistrySourceModal;
window.submitAddRegistrySource                = submitAddRegistrySource;
window.deleteRegistrySource                   = deleteRegistrySource;
window.selectAdminConnector                   = selectAdminConnector;
window.setPaTypeFilter                        = setPaTypeFilter;
window.setPaStatusFilter                      = setPaStatusFilter;
