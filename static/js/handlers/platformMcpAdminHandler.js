/**
 * platformMcpAdminHandler.js
 *
 * Admin Panel — "Components" tab → "MCP Servers" section
 * Governs platform-level capability MCP servers (browser, files, shell, web, google).
 * Strictly separate from user-configured data source servers (Configuration → MCP Servers).
 */

// ── Helpers ───────────────────────────────────────────────────────────────────

function _pmcpHeaders(json = true) {
    const h = {};
    if (json) h['Content-Type'] = 'application/json';
    const token = localStorage.getItem('tda_auth_token');
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
}

function _pmcpNotify(type, msg) {
    if (window.showNotification) window.showNotification(type, msg);
    else console.log(`[PlatformMCP] ${type}: ${msg}`);
}

function _pmcpConfirm(message, onConfirm) {
    if (window.showConfirmation) {
        window.showConfirmation(message, onConfirm);
    } else {
        if (confirm(message)) onConfirm();
    }
}

// ── State ─────────────────────────────────────────────────────────────────────

let _pmcpRegistrySources = [];
let _pmcpInstalledServers = [];
let _pmcpActiveSource = 'builtin';
let _pmcpBrowseResults = [];
let _pmcpNextCursor = '';       // cursor for next page (official registry)
let _pmcpSearchTimeout = null;
let _pmcpCredentialsServerId = null;
let _pmcpLoadingMore = false;

// ── Status badge ──────────────────────────────────────────────────────────────

const INSTALL_STATUS = {
    not_installed: { label: 'Not installed', color: 'text-gray-400',  bg: 'bg-gray-400/10',  ring: 'ring-gray-400/20' },
    installing:    { label: 'Installing…',   color: 'text-yellow-400', bg: 'bg-yellow-400/10', ring: 'ring-yellow-400/20' },
    installed:     { label: 'Installed',     color: 'text-emerald-400', bg: 'bg-emerald-400/10', ring: 'ring-emerald-400/20' },
    unavailable:   { label: 'Unavailable',   color: 'text-red-400',   bg: 'bg-red-400/10',   ring: 'ring-red-400/20' },
    error:         { label: 'Error',         color: 'text-red-400',   bg: 'bg-red-400/10',   ring: 'ring-red-400/20' },
};

function _statusBadge(status) {
    const cfg = INSTALL_STATUS[status] || INSTALL_STATUS.not_installed;
    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ring-1 ${cfg.bg} ${cfg.color} ${cfg.ring}">${cfg.label}</span>`;
}

// ── Load & render ─────────────────────────────────────────────────────────────

async function loadPlatformMcpAdminPanel() {
    const container = document.getElementById('platform-mcp-admin-container');
    if (container) {
        container.innerHTML = `
            <div class="flex items-center gap-3 py-6 text-gray-400">
                <svg class="animate-spin h-5 w-5 text-indigo-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                <span class="text-sm">Loading platform MCP servers…</span>
            </div>`;
    }
    await Promise.all([_loadRegistrySources(), _loadInstalledServers()]);
    renderPlatformMcpAdminPanel();
}

async function _loadRegistrySources() {
    try {
        const r = await fetch('/api/v1/mcp-registry/sources', { headers: _pmcpHeaders(false) });
        if (r.ok) _pmcpRegistrySources = (await r.json()).sources || [];
    } catch (e) { console.error('Failed to load MCP registry sources', e); }
}

async function _loadInstalledServers() {
    try {
        const r = await fetch('/api/v1/platform-mcp-servers', { headers: _pmcpHeaders(false) });
        if (r.ok) _pmcpInstalledServers = (await r.json()).servers || [];
    } catch (e) { console.error('Failed to load installed platform MCP servers', e); }
}

function renderPlatformMcpAdminPanel() {
    const container = document.getElementById('platform-mcp-admin-container');
    if (!container) return;

    container.innerHTML = `
        <div class="space-y-3">
            ${_renderInstalledSections()}
            ${_renderCollapsibleSection({
                id:        'pmcp-section-sources',
                open:      false,
                icon:      `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M3 10h18M3 14h18M10 3v18M14 3v18"/>
                            </svg>`,
                title:     'Registry Sources',
                subtitle:  `${_pmcpRegistrySources.length} source${_pmcpRegistrySources.length !== 1 ? 's' : ''} configured`,
                body:      _renderRegistrySourcesBody(),
            })}
        </div>
        ${_renderMarketplaceModal()}
        ${_renderAddSourceModal()}
        ${_renderCredentialsModal()}
    `;
}

function _renderInstalledSections() {
    const platformServers = _pmcpInstalledServers.filter(s => !s.requires_user_auth);
    const userServers     = _pmcpInstalledServers.filter(s =>  s.requires_user_auth);

    const platformIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2"/>
    </svg>`;
    const userIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
    </svg>`;

    const platformSection = _renderCollapsibleSection({
        id:       'pmcp-section-platform',
        open:     true,
        icon:     platformIcon,
        title:    'Platform Connectors',
        subtitle: 'Authenticated by admin — shared credentials, available to all authorised users',
        body:     platformServers.length === 0
                      ? `<p class="text-sm text-gray-500 py-2">No platform connectors installed. Browse the registry to add one.</p>`
                      : `<div class="space-y-3">${platformServers.map(_renderServerCard).join('')}</div>`,
    });

    const userSection = _renderCollapsibleSection({
        id:       'pmcp-section-user',
        open:     true,
        icon:     userIcon,
        title:    'User Connectors',
        subtitle: 'Authenticated per user — each user connects their own account via OAuth',
        body:     userServers.length === 0
                      ? `<p class="text-sm text-gray-500 py-2">No user connectors installed. Browse the registry to add one.</p>`
                      : `<div class="space-y-3">${userServers.map(_renderServerCard).join('')}</div>`,
    });

    return platformSection + userSection;
}

function _renderCollapsibleSection({ id, open, icon, title, subtitle, body }) {
    return `
        <div class="glass-panel rounded-xl overflow-hidden">
            <details id="${id}" ${open ? 'open' : ''} class="group">
                <summary class="flex items-center justify-between gap-4 px-5 py-4 cursor-pointer list-none select-none
                                hover:bg-white/2 transition-colors">
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center"
                             style="background:rgba(129,140,248,0.1)">
                            ${icon}
                        </div>
                        <div class="min-w-0">
                            <h3 class="text-sm font-semibold text-white">${title}</h3>
                            <p class="text-xs text-gray-400 mt-0.5">${subtitle}</p>
                        </div>
                    </div>
                    <svg xmlns="http://www.w3.org/2000/svg"
                         class="h-4 w-4 text-gray-400 flex-shrink-0 transition-transform duration-200 group-open:rotate-180"
                         fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
                    </svg>
                </summary>
                <div class="border-t border-white/5 px-5 py-4">
                    ${body}
                </div>
            </details>
        </div>`;
}

// ── Empty state ───────────────────────────────────────────────────────────────

function _renderEmptyState() {
    return `
        <div class="glass-panel rounded-xl p-10 flex flex-col items-center gap-4 text-center">
            <div class="w-14 h-14 rounded-full bg-indigo-500/10 ring-1 ring-indigo-500/20 flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
                </svg>
            </div>
            <div>
                <p class="text-white font-semibold">No platform servers installed</p>
                <p class="text-sm text-gray-400 mt-1">Browse the registry to add capability servers like web search, file access, or shell execution.</p>
            </div>
            <button onclick="openPlatformMcpMarketplace()"
                    class="mt-1 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all hover:bg-indigo-500/20"
                    style="background:rgba(129,140,248,0.12);border:1px solid rgba(129,140,248,0.3);color:#818cf8">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
                </svg>
                Browse Registry
            </button>
        </div>`;
}

// ── Server card ───────────────────────────────────────────────────────────────

function _renderServerCard(server) {
    const enabled        = !!server.enabled;
    const autoOptIn      = !!server.auto_opt_in;
    const userCanOptOut  = !!server.user_can_opt_out;
    const userCanCfgTools = !!server.user_can_configure_tools;
    const allTools       = _getBuiltinToolsForServer(server.id);
    const permitted      = Array.isArray(server.available_tools) ? new Set(server.available_tools) : null;

    return `
        <div class="glass-panel rounded-xl overflow-hidden">
            <!-- Card header -->
            <div class="p-5 flex items-start gap-4">
                <!-- Server icon -->
                <div class="w-10 h-10 rounded-lg flex-shrink-0 flex items-center justify-center ring-1"
                     style="background:rgba(129,140,248,0.1);ring-color:rgba(129,140,248,0.2)">
                    ${_serverIcon(server.id)}
                </div>

                <!-- Name + description -->
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="text-white font-semibold text-sm">${_esc(server.display_name || server.name)}</span>
                        <span class="text-xs text-gray-500">v${server.version || '0.0.0'}</span>
                        ${_statusBadge(server.install_status || 'installed')}
                        ${server.requires_user_auth ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ring-1 bg-yellow-400/10 text-yellow-400 ring-yellow-400/20">OAuth per user</span>' : ''}
                    </div>
                    <p class="text-xs text-gray-400 mt-1 line-clamp-2">${_esc(server.description || '')}</p>
                </div>

                <!-- Master enable toggle -->
                <div class="flex-shrink-0 flex items-center gap-2">
                    <span class="text-xs ${enabled ? 'text-emerald-400' : 'text-gray-500'}">${enabled ? 'Enabled' : 'Disabled'}</span>
                    <label class="ind-toggle ind-toggle--primary">
                        <input type="checkbox" ${enabled ? 'checked' : ''}
                               onchange="togglePlatformMcpServer('${server.id}', this.checked)">
                        <span class="ind-track"></span>
                    </label>
                </div>
            </div>

            ${enabled ? `
            <!-- Governance section -->
            <div class="border-t border-white/5 px-5 py-4 space-y-5">

                <!-- Governance toggles -->
                <div>
                    <p class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Access Governance</p>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        ${_govToggle(server.id, 'auto_opt_in',              autoOptIn,      'Auto opt-in',      'Active on all profiles by default')}
                        ${_govToggle(server.id, 'user_can_opt_out',         userCanOptOut,  'User can opt out',  'Users may disable per profile')}
                        ${_govToggle(server.id, 'user_can_configure_tools', userCanCfgTools, 'User selects tools', 'Users may pick individual tools')}
                    </div>
                </div>

                <!-- Permitted tools -->
                <div>
                    <p class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Permitted Tools
                        <span class="normal-case font-normal text-gray-500 ml-1">(all enabled = no restriction)</span>
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
                                                   onchange="togglePlatformMcpAvailableTool('${server.id}', '${t}', this.checked)">
                                            <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 ${on ? 'text-indigo-400' : 'text-gray-600'}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                                                ${on ? '<path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>' : '<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>'}
                                            </svg>
                                            ${_esc(t)}
                                        </label>`;
                              }).join('')
                        }
                    </div>
                </div>

                <!-- Credentials + delete actions -->
                <div class="flex items-center justify-between pt-1">
                    <button onclick="openPlatformMcpCredentials('${server.id}')"
                            class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all hover:bg-indigo-500/10"
                            style="border:1px solid rgba(129,140,248,0.25);color:#818cf8">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                        </svg>
                        Credentials &amp; env vars
                    </button>
                    <button onclick="_pmcpConfirmRemove('${server.id}')"
                            class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all hover:bg-red-500/10 text-red-400"
                            style="border:1px solid rgba(248,113,113,0.2)">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                        Remove server
                    </button>
                </div>
            </div>
            ` : `
            <!-- Disabled hint -->
            <div class="border-t border-white/5 px-5 py-3">
                <p class="text-xs text-gray-500">Enable this server to configure governance settings and make it available to users.</p>
            </div>
            `}
        </div>`;
}

function _govToggle(serverId, field, checked, label, description) {
    return `
        <div class="p-3 rounded-lg bg-gray-700/30 border border-white/5">
            <div class="flex items-center justify-between gap-2">
                <div class="flex-1 min-w-0">
                    <p class="text-xs font-medium text-white">${label}</p>
                    <p class="text-[11px] text-gray-500 mt-0.5">${description}</p>
                </div>
                <label class="ind-toggle flex-shrink-0">
                    <input type="checkbox" ${checked ? 'checked' : ''}
                           onchange="updatePlatformMcpGovernance('${serverId}', '${field}', this.checked ? 1 : 0)">
                    <span class="ind-track"></span>
                </label>
            </div>
        </div>`;
}

// ── Registry sources body (used inside collapsible section) ──────────────────

function _renderRegistrySourcesBody() {
    const rows = _pmcpRegistrySources.map(source => `
        <div class="flex items-center gap-3 px-4 py-3 rounded-lg"
             style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06)">
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                    <span class="text-sm text-white font-medium">${_esc(source.name)}</span>
                    ${source.is_builtin ? '<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 ring-1 ring-indigo-500/20">built-in</span>' : ''}
                </div>
                <p class="text-xs text-gray-500 mt-0.5 truncate font-mono">${_esc(source.url)}</p>
            </div>
            ${!source.is_builtin ? `
                <button onclick="deleteRegistrySource('${source.id}')"
                        class="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded transition-colors hover:bg-red-500/10 flex-shrink-0">
                    Remove
                </button>` : ''}
        </div>`).join('');

    return `
        <div class="space-y-2">
            ${rows}
            <button onclick="openAddRegistrySourceModal()"
                    class="w-full py-2.5 text-xs rounded-lg border border-dashed transition-colors hover:bg-indigo-500/5"
                    style="border-color:rgba(129,140,248,0.25);color:#818cf8">
                + Add enterprise registry URL
            </button>
        </div>`;
}

// ── Marketplace modal ─────────────────────────────────────────────────────────

function _renderMarketplaceModal() {
    return `
        <div id="pmcp-marketplace-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4"
             style="background:rgba(0,0,0,0.7)" onclick="if(event.target===this)closePlatformMcpMarketplace()">
            <div class="w-full max-w-2xl rounded-2xl shadow-2xl flex flex-col" style="background:var(--bg-secondary);max-height:82vh;border:1px solid var(--border-primary)">

                <!-- Header -->
                <div class="flex items-center justify-between px-6 py-4 border-b" style="border-color:var(--border-primary)">
                    <div>
                        <h2 class="text-base font-bold text-white">MCP Server Registry</h2>
                        <p class="text-xs text-gray-400 mt-0.5">Browse and install platform capability servers</p>
                    </div>
                    <button onclick="closePlatformMcpMarketplace()"
                            class="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>

                <!-- Source tabs -->
                <div class="flex gap-1 px-6 pt-4" id="pmcp-source-tabs"></div>

                <!-- Search -->
                <div class="px-6 pt-3 pb-1">
                    <div class="relative">
                        <svg xmlns="http://www.w3.org/2000/svg" class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                        </svg>
                        <input id="pmcp-search-input" type="text" placeholder="Search servers…"
                               class="w-full pl-9 pr-4 py-2 rounded-lg text-sm"
                               style="background:var(--bg-primary);border:1px solid var(--border-primary);color:var(--text-primary)"
                               oninput="onPmcpSearchInput(this.value)"/>
                    </div>
                </div>

                <!-- Results -->
                <div class="flex-1 overflow-y-auto px-6 py-3 space-y-2" id="pmcp-browse-results">
                    <div class="text-center py-8 text-sm text-gray-400">Loading…</div>
                </div>
            </div>
        </div>`;
}

// ── Add source modal ──────────────────────────────────────────────────────────

function _renderAddSourceModal() {
    return `
        <div id="pmcp-add-source-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4"
             style="background:rgba(0,0,0,0.7)" onclick="if(event.target===this)closeAddRegistrySourceModal()">
            <div class="w-full max-w-md rounded-2xl shadow-2xl p-6" style="background:var(--bg-secondary);border:1px solid var(--border-primary)">
                <h2 class="text-base font-bold text-white mb-1">Add Enterprise Registry</h2>
                <p class="text-xs text-gray-400 mb-5">Point to a private MCP registry that exposes the standard <code class="text-indigo-400">GET /v0.1/servers</code> endpoint.</p>
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
                    <button onclick="closeAddRegistrySourceModal()"
                            class="px-4 py-2 text-sm rounded-lg text-gray-400 hover:text-white transition-colors">Cancel</button>
                    <button onclick="submitAddRegistrySource()"
                            class="px-4 py-2 text-sm font-medium rounded-lg transition-all hover:bg-indigo-500/20"
                            style="background:rgba(129,140,248,0.12);border:1px solid rgba(129,140,248,0.3);color:#818cf8">
                        Add Registry
                    </button>
                </div>
            </div>
        </div>`;
}

// ── Credentials modal ─────────────────────────────────────────────────────────

function _renderCredentialsModal() {
    return `
        <div id="pmcp-credentials-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4"
             style="background:rgba(0,0,0,0.7)" onclick="if(event.target===this)closePlatformMcpCredentials()">
            <div class="w-full max-w-lg rounded-2xl shadow-2xl" style="background:var(--bg-secondary);border:1px solid var(--border-primary)">
                <!-- Header -->
                <div class="flex items-center justify-between px-6 py-4 border-b" style="border-color:var(--border-primary)">
                    <div>
                        <h2 class="text-base font-bold text-white" id="pmcp-cred-title">Server Credentials</h2>
                        <p class="text-xs text-gray-400 mt-0.5">Stored encrypted. Never returned to the browser after saving.</p>
                    </div>
                    <button onclick="closePlatformMcpCredentials()"
                            class="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>

                <!-- Credential fields (injected dynamically) -->
                <div id="pmcp-cred-fields" class="px-6 py-5 space-y-4"></div>

                <div class="flex justify-end gap-2 px-6 py-4 border-t" style="border-color:var(--border-primary)">
                    <button onclick="closePlatformMcpCredentials()"
                            class="px-4 py-2 text-sm rounded-lg text-gray-400 hover:text-white transition-colors">Cancel</button>
                    <button onclick="savePlatformMcpCredentials()"
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

// ── Marketplace browse results ────────────────────────────────────────────────

function openPlatformMcpMarketplace() {
    const modal = document.getElementById('pmcp-marketplace-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    _renderSourceTabs();
    _browseRegistry(_pmcpActiveSource, '');
}

function closePlatformMcpMarketplace() {
    const modal = document.getElementById('pmcp-marketplace-modal');
    if (modal) modal.classList.add('hidden');
}

function _renderSourceTabs() {
    const container = document.getElementById('pmcp-source-tabs');
    if (!container) return;
    container.innerHTML = _pmcpRegistrySources.map(s => {
        const active = _pmcpActiveSource === s.id;
        return `<button onclick="selectPmcpSource('${s.id}')" id="pmcp-tab-${s.id}"
                        class="px-3 py-1.5 text-xs rounded-lg mr-1 transition-all font-medium"
                        style="${active
                            ? 'background:rgba(129,140,248,0.15);border:1px solid rgba(129,140,248,0.35);color:#818cf8'
                            : 'background:transparent;border:1px solid var(--border-primary);color:var(--text-muted)'}">
                    ${_esc(s.name)}
                </button>`;
    }).join('');
}

function selectPmcpSource(sourceId) {
    _pmcpActiveSource = sourceId;
    _renderSourceTabs();
    const search = document.getElementById('pmcp-search-input');
    _browseRegistry(sourceId, search ? search.value : '');
}

function onPmcpSearchInput(value) {
    clearTimeout(_pmcpSearchTimeout);
    _pmcpSearchTimeout = setTimeout(() => _browseRegistry(_pmcpActiveSource, value), 350);
}

async function _browseRegistry(sourceId, search) {
    const resultsEl = document.getElementById('pmcp-browse-results');
    if (!resultsEl) return;
    // Reset state for a fresh search
    _pmcpBrowseResults = [];
    _pmcpNextCursor = '';
    resultsEl.innerHTML = '<div class="text-center py-8 text-sm text-gray-400">Loading…</div>';
    try {
        const batch = await _fetchRegistryPage(sourceId, search, '');
        _pmcpBrowseResults = batch.servers;
        _pmcpNextCursor = batch.nextCursor;
        _renderBrowseResults(resultsEl);
    } catch (e) {
        resultsEl.innerHTML = `<div class="text-center py-6 text-sm text-red-400">Failed to load: ${_esc(e.message)}</div>`;
    }
}

async function _loadMoreRegistry() {
    if (_pmcpLoadingMore || !_pmcpNextCursor) return;
    _pmcpLoadingMore = true;
    const btn = document.getElementById('pmcp-load-more-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
    try {
        const batch = await _fetchRegistryPage(_pmcpActiveSource, _pmcpCurrentSearch || '', _pmcpNextCursor);
        _pmcpBrowseResults = [..._pmcpBrowseResults, ...batch.servers];
        _pmcpNextCursor = batch.nextCursor;
        const resultsEl = document.getElementById('pmcp-browse-results');
        if (resultsEl) _renderBrowseResults(resultsEl);
    } catch (e) {
        const btn2 = document.getElementById('pmcp-load-more-btn');
        if (btn2) { btn2.disabled = false; btn2.textContent = 'Load more'; }
    } finally {
        _pmcpLoadingMore = false;
    }
}

let _pmcpCurrentSearch = '';

async function _fetchRegistryPage(sourceId, search, cursor) {
    _pmcpCurrentSearch = search;
    const params = new URLSearchParams({ source: sourceId, search, page: 1 });
    if (cursor) params.set('cursor', cursor);
    const r = await fetch(`/api/v1/mcp-registry/servers?${params}`, { headers: _pmcpHeaders(false) });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    // Extract next cursor from official registry metadata
    const nextCursor = (data.metadata && data.metadata.nextCursor) || '';
    const allNormalised = (data.servers || [])
        .filter(s => s != null)
        .map(_normaliseRegistryServer)
        .filter(s => s != null);
    // Keep only latest versions when the registry includes multiple versions per server
    const hasVersioning = allNormalised.some(s => s._is_latest === true || s._is_latest === false);
    const servers = hasVersioning
        ? allNormalised.filter(s => s._is_latest !== false)
        : allNormalised;
    return { servers, nextCursor };
}

/**
 * Normalise a server entry from any registry source to the shape _renderBrowseResults expects.
 *
 * Handles two formats:
 *   1. Uderia built-in:  { id, display_name, name, version, tools, description, ... }
 *   2. Official MCP Registry v0.1: { server: { name, title, description, version, ... }, _meta: {...} }
 *      — each array entry wraps the actual server under a "server" key.
 */
function _normaliseRegistryServer(raw) {
    if (!raw || typeof raw !== 'object') return null;

    // Unwrap official MCP Registry envelope: { server: {...}, _meta: {...} }
    const s = (raw.server && typeof raw.server === 'object') ? raw.server : raw;
    const meta = raw._meta || {};

    // id: built-in uses s.id; official registry uses s.name (the slug, e.g. "ai.example/tool")
    const id = s.id || s.name || `ext-${Math.random().toString(36).slice(2)}`;

    // Display name: built-in uses display_name; official registry uses title
    const displayName = s.display_name || s.title || s.name || id;

    // Version: built-in uses version directly; version_detail.version is a legacy fallback
    const version = s.version || (s.version_detail && s.version_detail.version) || '—';

    // Tools: not present in the registry listing endpoint for external registries
    const rawTools = Array.isArray(s.tools) ? s.tools : [];
    const tools = rawTools.map(t => (typeof t === 'string' ? t : (t && t.name) || String(t)));

    // Provenance badge (is_official from _meta)
    const officialMeta = Object.values(meta)[0] || {};
    const isOfficial = !!(officialMeta.status === 'active');

    return {
        ...s,
        id,
        display_name: displayName,
        version,
        tools,
        description: s.description || '',
        _is_official: isOfficial,
        _is_latest: !!(officialMeta.isLatest),
    };
}

function _renderBrowseResults(container) {
    // Filter out any remaining nulls after normalisation
    const servers = (_pmcpBrowseResults || []).filter(s => s != null);
    if (!servers.length) {
        container.innerHTML = '<div class="text-center py-8 text-sm text-gray-400">No servers found.</div>';
        return;
    }
    const installedIds = new Set((_pmcpInstalledServers || []).filter(s => s).map(s => s.id));
    const cardsHtml = servers.map(s => {
        const isInstalled = installedIds.has(s.id);
        const tools = (s.tools || []).slice(0, 5);
        const extra = (s.tools || []).length - tools.length;
        return `
            <div class="rounded-xl p-4 flex items-start gap-3 transition-colors hover:bg-white/3"
                 style="background:var(--bg-primary);border:1px solid var(--border-primary)">
                <div class="w-9 h-9 rounded-lg flex-shrink-0 flex items-center justify-center ring-1 ring-indigo-500/20"
                     style="background:rgba(129,140,248,0.1)">
                    ${_serverIcon(s.id)}
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="text-sm font-semibold text-white">${_esc(s.display_name)}</span>
                        ${s.version && s.version !== '—' ? `<span class="text-[11px] text-gray-500">v${_esc(s.version)}</span>` : ''}
                        ${s._is_official ? '<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 ring-1 ring-indigo-500/25">official</span>' : ''}
                        ${s._is_latest === false ? '<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-500/15 text-gray-400 ring-1 ring-gray-500/20">older</span>' : ''}
                        ${s.security_acknowledgment_required ? '<span class="text-[11px] px-1.5 py-0.5 rounded-full bg-red-400/10 text-red-400 ring-1 ring-red-400/20">Docker</span>' : ''}
                        ${s.requires_user_auth ? '<span class="text-[11px] px-1.5 py-0.5 rounded-full bg-yellow-400/10 text-yellow-400 ring-1 ring-yellow-400/20">OAuth</span>' : ''}
                    </div>
                    ${s.id !== s.display_name ? `<p class="text-[10px] text-gray-600 font-mono mt-0.5 truncate">${_esc(s.id)}</p>` : ''}
                    <p class="text-xs text-gray-400 mt-0.5 line-clamp-2">${_esc(s.description || '')}</p>
                    ${tools.length ? `
                        <div class="flex flex-wrap gap-1 mt-2">
                            ${tools.map(t => `<span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/8 text-indigo-400 ring-1 ring-indigo-500/20">${_esc(String(t))}</span>`).join('')}
                            ${extra > 0 ? `<span class="text-[10px] text-gray-500">+${extra} more</span>` : ''}
                        </div>` : ''}
                </div>
                <div class="flex-shrink-0">
                    ${isInstalled
                        ? `<span class="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-emerald-400/10 text-emerald-400 ring-1 ring-emerald-400/20">
                               <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
                               Installed
                           </span>`
                        : `<button onclick="installPlatformMcpServer('${_esc(s.id)}')"
                                   class="text-xs px-3 py-1.5 rounded-lg font-medium transition-all hover:bg-indigo-500/20"
                                   style="background:rgba(129,140,248,0.12);border:1px solid rgba(129,140,248,0.3);color:#818cf8">
                               Install
                           </button>`
                    }
                </div>
            </div>`;
    }).join('');

    // Load more button (shown only when next cursor available)
    const loadMoreHtml = _pmcpNextCursor ? `
        <div class="pt-2 pb-1 text-center">
            <button id="pmcp-load-more-btn"
                    onclick="window._loadMoreRegistry()"
                    class="text-xs px-5 py-2 rounded-lg font-medium transition-all"
                    style="background:rgba(129,140,248,0.1);border:1px solid rgba(129,140,248,0.25);color:#818cf8">
                Load more
            </button>
            <p class="text-[10px] text-gray-600 mt-1">${servers.length} servers loaded</p>
        </div>` : `
        <p class="text-center text-[10px] text-gray-600 py-2">${servers.length} server${servers.length !== 1 ? 's' : ''} total</p>`;

    container.innerHTML = cardsHtml + loadMoreHtml;
}

// ── Server icons ──────────────────────────────────────────────────────────────

function _serverIcon(serverId) {
    const icons = {
        'uderia-web':     `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9"/></svg>`,
        'uderia-files':   `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>`,
        'uderia-browser': `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>`,
        'uderia-google':  `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>`,
        'uderia-shell':   `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>`,
    };
    return icons[serverId] || `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2"/></svg>`;
}

// ── Credential schema per server ──────────────────────────────────────────────

const CREDENTIAL_SCHEMAS = {
    'uderia-web':    [
        { key: 'BRAVE_API_KEY',   label: 'Brave Search API Key',  hint: 'From https://brave.com/search/api/', type: 'password' },
        { key: 'SERPER_API_KEY',  label: 'Serper API Key (alt)',   hint: 'Alternative to Brave Search',        type: 'password' },
    ],
    'uderia-google': [
        { key: 'GOOGLE_CLIENT_ID',     label: 'Google OAuth Client ID',     hint: 'From Google Cloud Console → Credentials', type: 'text'     },
        { key: 'GOOGLE_CLIENT_SECRET', label: 'Google OAuth Client Secret', hint: 'Keep this secret',                        type: 'password' },
    ],
    'uderia-shell':  [
        { key: 'ALLOWED_COMMANDS', label: 'Allowed commands (CSV)',  hint: 'e.g. python,pip,ls,cat — leave empty to allow all', type: 'text' },
        { key: 'DOCKER_IMAGE',     label: 'Docker image',            hint: 'Default: python:3.11-slim',                         type: 'text' },
    ],
};

function openPlatformMcpCredentials(serverId) {
    _pmcpCredentialsServerId = serverId;
    const server = _pmcpInstalledServers.find(s => s.id === serverId);
    const name = server ? (server.display_name || server.name) : serverId;
    const schema = CREDENTIAL_SCHEMAS[serverId] || [
        { key: 'API_KEY', label: 'API Key', hint: 'Sensitive — stored encrypted', type: 'password' },
    ];

    const modal = document.getElementById('pmcp-credentials-modal');
    if (!modal) return;

    document.getElementById('pmcp-cred-title').textContent = `${name} — Credentials`;
    document.getElementById('pmcp-cred-fields').innerHTML = schema.map(f => `
        <div>
            <label class="block text-xs font-medium text-gray-300 mb-1.5">${_esc(f.label)}</label>
            <input type="${f.type || 'text'}" id="pmcp-cred-${f.key}"
                   placeholder="${f.type === 'password' ? '••••••••' : _esc(f.hint || '')}"
                   class="w-full px-3 py-2 rounded-lg text-sm"
                   style="background:var(--bg-primary);border:1px solid var(--border-primary);color:var(--text-primary)"/>
            ${f.hint && f.type !== 'password' ? `<p class="text-[11px] text-gray-500 mt-1">${_esc(f.hint)}</p>` : ''}
        </div>
    `).join('');

    modal.classList.remove('hidden');
}

function closePlatformMcpCredentials() {
    const modal = document.getElementById('pmcp-credentials-modal');
    if (modal) modal.classList.add('hidden');
    _pmcpCredentialsServerId = null;
}

async function savePlatformMcpCredentials() {
    if (!_pmcpCredentialsServerId) return;
    const schema = CREDENTIAL_SCHEMAS[_pmcpCredentialsServerId] || [{ key: 'API_KEY' }];
    const creds = {};
    let hasValue = false;
    for (const f of schema) {
        const el = document.getElementById(`pmcp-cred-${f.key}`);
        if (el && el.value.trim()) { creds[f.key] = el.value.trim(); hasValue = true; }
    }
    if (!hasValue) { _pmcpNotify('error', 'Enter at least one credential value'); return; }

    try {
        const r = await fetch(`/api/v1/platform-mcp-servers/${_pmcpCredentialsServerId}`, {
            method: 'PUT', headers: _pmcpHeaders(),
            body: JSON.stringify({ credentials: creds }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Save failed');
        _pmcpNotify('success', 'Credentials saved (encrypted)');
        closePlatformMcpCredentials();
    } catch (e) {
        _pmcpNotify('error', `Failed to save credentials: ${e.message}`);
    }
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function installPlatformMcpServer(serverId) {
    const serverData = _pmcpBrowseResults.find(s => s.id === serverId);
    if (!serverData) return;
    try {
        const r = await fetch('/api/v1/mcp-registry/servers/install', {
            method: 'POST', headers: _pmcpHeaders(),
            body: JSON.stringify({ source_id: _pmcpActiveSource, server_id: serverId, server_data: serverData }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Install failed');
        _pmcpNotify('success', `${serverData.display_name || serverId} installed`);
        closePlatformMcpMarketplace();
        await loadPlatformMcpAdminPanel();
    } catch (e) {
        _pmcpNotify('error', `Install failed: ${e.message}`);
    }
}

async function togglePlatformMcpServer(serverId, enabled) {
    try {
        const r = await fetch(`/api/v1/platform-mcp-servers/${serverId}`, {
            method: 'PUT', headers: _pmcpHeaders(),
            body: JSON.stringify({ enabled: enabled ? 1 : 0 }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Update failed');
        await _loadInstalledServers();
        renderPlatformMcpAdminPanel();
    } catch (e) {
        _pmcpNotify('error', `Failed to update server: ${e.message}`);
    }
}

async function updatePlatformMcpGovernance(serverId, field, value) {
    try {
        const r = await fetch(`/api/v1/platform-mcp-servers/${serverId}`, {
            method: 'PUT', headers: _pmcpHeaders(),
            body: JSON.stringify({ [field]: value }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Update failed');
    } catch (e) {
        _pmcpNotify('error', `Failed to update governance: ${e.message}`);
    }
}

async function togglePlatformMcpAvailableTool(serverId, toolName, enabled) {
    const server = _pmcpInstalledServers.find(s => s.id === serverId);
    if (!server) return;
    const allTools = _getBuiltinToolsForServer(serverId);
    let current = Array.isArray(server.available_tools) ? [...server.available_tools] : [...allTools];
    if (enabled) { if (!current.includes(toolName)) current.push(toolName); }
    else { current = current.filter(t => t !== toolName); }
    const updatedTools = current.length === allTools.length ? null : current;
    try {
        const r = await fetch(`/api/v1/platform-mcp-servers/${serverId}`, {
            method: 'PUT', headers: _pmcpHeaders(),
            body: JSON.stringify({ available_tools: updatedTools }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Update failed');
        const idx = _pmcpInstalledServers.findIndex(s => s.id === serverId);
        if (idx >= 0) _pmcpInstalledServers[idx].available_tools = updatedTools;
    } catch (e) {
        _pmcpNotify('error', `Failed to update tools: ${e.message}`);
    }
}

function _pmcpConfirmRemove(serverId) {
    const server = _pmcpInstalledServers.find(s => s.id === serverId);
    const name = server ? (server.display_name || server.name) : serverId;
    _pmcpConfirm(
        `Remove "${name}"? This will clear all profile assignments for this server.`,
        () => deletePlatformMcpServer(serverId)
    );
}

async function deletePlatformMcpServer(serverId) {
    const server = _pmcpInstalledServers.find(s => s.id === serverId);
    const name = server ? (server.display_name || server.name) : serverId;
    try {
        const r = await fetch(`/api/v1/platform-mcp-servers/${serverId}`, {
            method: 'DELETE', headers: _pmcpHeaders(false),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Delete failed');
        _pmcpNotify('success', `${name} removed`);
        await loadPlatformMcpAdminPanel();
    } catch (e) {
        _pmcpNotify('error', `Failed to remove server: ${e.message}`);
    }
}

// ── Registry source management ────────────────────────────────────────────────

function openAddRegistrySourceModal() {
    const modal = document.getElementById('pmcp-add-source-modal');
    if (modal) modal.classList.remove('hidden');
}

function closeAddRegistrySourceModal() {
    const modal = document.getElementById('pmcp-add-source-modal');
    if (modal) modal.classList.add('hidden');
}

async function submitAddRegistrySource() {
    const name = document.getElementById('pmcp-source-name')?.value.trim();
    const url  = document.getElementById('pmcp-source-url')?.value.trim();
    if (!name || !url) { _pmcpNotify('error', 'Name and URL are required'); return; }
    try {
        const r = await fetch('/api/v1/mcp-registry/sources', {
            method: 'POST', headers: _pmcpHeaders(),
            body: JSON.stringify({ name, url }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Failed');
        _pmcpNotify('success', `Registry "${name}" added`);
        closeAddRegistrySourceModal();
        await _loadRegistrySources();
        renderPlatformMcpAdminPanel();
    } catch (e) {
        _pmcpNotify('error', `Failed to add registry: ${e.message}`);
    }
}

async function deleteRegistrySource(sourceId) {
    const source = _pmcpRegistrySources.find(s => s.id === sourceId);
    _pmcpConfirm(`Remove registry "${source?.name || sourceId}"?`, async () => {
        try {
            const r = await fetch(`/api/v1/mcp-registry/sources/${sourceId}`, {
                method: 'DELETE', headers: _pmcpHeaders(false),
            });
            if (!r.ok) throw new Error((await r.json()).error || 'Delete failed');
            _pmcpNotify('success', 'Registry removed');
            await _loadRegistrySources();
            renderPlatformMcpAdminPanel();
        } catch (e) {
            _pmcpNotify('error', `Failed to remove registry: ${e.message}`);
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
    if (tabName === 'mcp-servers' && typeof loadPlatformMcpAdminPanel === 'function') {
        loadPlatformMcpAdminPanel();
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
        'uderia-shell':   ['exec_command', 'run_script', 'list_processes', 'kill_process'],
    };
    return MAP[serverId] || [];
}

function _esc(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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
        const r = await fetch('/api/v1/scheduler/status', { headers: _pmcpHeaders(false) });
        if (r.ok) status = await r.json();
        else apschedulerAvailable = false;
    } catch (e) {
        apschedulerAvailable = false;
    }

    // Global enable state (admin can disable via disabled_components)
    const isEnabled = status.globally_enabled !== false;

    container.innerHTML = `
        <div class="space-y-4">

            <!-- Status overview card -->
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

            <!-- What this controls section -->
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
                        <span>Task results can be delivered via <strong>email</strong> (SMTP) or <strong>webhook</strong> per task. Google Mail delivery requires Track C (Google connector).</span>
                    </div>
                    <div class="flex items-start gap-2">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-purple-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                        </svg>
                        <span>Supports <strong>cron expressions</strong> and <strong>interval scheduling</strong>. Overlap policy (skip/queue/allow) and per-task token budgets are user-configurable.</span>
                    </div>
                </div>
            </div>

            ${!apschedulerAvailable ? `
            <!-- Install prompt -->
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
        // Read current disabled_components list and add/remove 'scheduler'
        const r = await fetch('/api/v1/admin/component-settings', { headers: _pmcpHeaders(false) });
        const d = r.ok ? await r.json() : {};
        let disabled = (d.settings && d.settings.disabled_components) || [];
        if (enabled) {
            disabled = disabled.filter(id => id !== 'scheduler');
        } else {
            if (!disabled.includes('scheduler')) disabled.push('scheduler');
        }
        await fetch('/api/v1/admin/component-settings', {
            method: 'POST',
            headers: _pmcpHeaders(),
            body: JSON.stringify({ disabled_components: disabled })
        });
        _pmcpNotify('success', `Task Scheduler ${enabled ? 'enabled' : 'disabled'} globally.`);
    } catch (e) {
        _pmcpNotify('error', 'Failed to update scheduler setting.');
        // Revert toggle
        const toggle = document.getElementById('scheduler-global-toggle');
        if (toggle) toggle.checked = !enabled;
    }
};

// ── Exports ───────────────────────────────────────────────────────────────────

window.loadPlatformMcpAdminPanel        = loadPlatformMcpAdminPanel;
window.renderPlatformMcpAdminPanel      = renderPlatformMcpAdminPanel;
window.switchPlatformComponentsAdminTab = switchPlatformComponentsAdminTab;
window.openPlatformMcpMarketplace       = openPlatformMcpMarketplace;
window.closePlatformMcpMarketplace      = closePlatformMcpMarketplace;
window.selectPmcpSource                 = selectPmcpSource;
window.onPmcpSearchInput                = onPmcpSearchInput;
window._loadMoreRegistry                = _loadMoreRegistry;
window.installPlatformMcpServer         = installPlatformMcpServer;
window.togglePlatformMcpServer          = togglePlatformMcpServer;
window.updatePlatformMcpGovernance      = updatePlatformMcpGovernance;
window.togglePlatformMcpAvailableTool   = togglePlatformMcpAvailableTool;
window.deletePlatformMcpServer          = deletePlatformMcpServer;
window._pmcpConfirmRemove               = _pmcpConfirmRemove;
window.openPlatformMcpCredentials       = openPlatformMcpCredentials;
window.closePlatformMcpCredentials      = closePlatformMcpCredentials;
window.savePlatformMcpCredentials       = savePlatformMcpCredentials;
window.openAddRegistrySourceModal       = openAddRegistrySourceModal;
window.closeAddRegistrySourceModal      = closeAddRegistrySourceModal;
window.submitAddRegistrySource          = submitAddRegistrySource;
window.deleteRegistrySource             = deleteRegistrySource;
