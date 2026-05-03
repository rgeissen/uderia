/**
 * platformConnectorHandler.js
 *
 * Platform Components panel — "MCP Servers" tab (user-facing)
 * Shows admin-enabled platform capability servers; users assign them to their profiles.
 * Fine-grained tool selection lives in Profile Edit.
 *
 * Layout: filter pills → card grid → detail panel (card-grid + detail pattern
 * matching the UI Components tab).
 *
 * Strictly separate from Configuration → MCP Servers (user data source servers).
 */

// ── Constants ──────────────────────────────────────────────────────────────────

const PMCP_GRID_ID    = 'platform-mcp-grid';
const PMCP_DETAIL_ID  = 'platform-mcp-detail-panel';
const PMCP_ACCENT     = '#818cf8';  // indigo

// ── Helpers ────────────────────────────────────────────────────────────────────

function _pconnuHeaders(json = true) {
    const h = {};
    if (json) h['Content-Type'] = 'application/json';
    const token = localStorage.getItem('tda_auth_token');
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
}

function _pconnuNotify(type, msg) {
    if (window.showNotification) window.showNotification(type, msg);
    else console.log(`[PlatformMCP] ${type}: ${msg}`);
}

function _esc(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── State ──────────────────────────────────────────────────────────────────────

let _pconnuServers        = [];   // admin-enabled platform servers
let _pconnuProfiles       = [];   // current user's profiles
let _pconnuSettings       = {};   // { server_id: { profile_id: {opted_in, user_tools} } }
let _pconnuSelectedId     = null; // currently selected server id
let _pconnuStatusFilter   = 'all';
let _pconnuTypeFilter     = 'all';

// ── Entry point ────────────────────────────────────────────────────────────────

async function loadPlatformConnectorPanel() {
    const container = document.getElementById('platform-connector-container');
    if (!container) return;

    container.innerHTML = `
        <div class="flex items-center justify-center py-16">
            <div class="flex flex-col items-center gap-3">
                <div class="w-8 h-8 border-2 border-indigo-400/60 border-t-transparent rounded-full animate-spin"></div>
                <p class="text-sm text-gray-400">Loading platform servers…</p>
            </div>
        </div>`;

    try {
        await Promise.all([_fetchServers(), _fetchProfiles()]);
        await _fetchAllProfileSettings();
        _renderFullPanel(container);
        // Sync filter pill visual state in case values were changed before last tab switch
        _updateFilterPills('pmcp-type-filters',   _pconnuTypeFilter);
        _updateFilterPills('pmcp-status-filters', _pconnuStatusFilter);
    } catch (err) {
        container.innerHTML = `
            <div class="text-center py-12">
                <p class="text-red-400 font-medium">Failed to load platform servers</p>
                <p class="text-gray-500 text-sm mt-1">${_esc(err.message)}</p>
            </div>`;
    }
}

// ── Data fetching ──────────────────────────────────────────────────────────────

async function _fetchServers() {
    const resp = await fetch('/api/v1/platform-connectors', { headers: _pconnuHeaders(false) });
    if (!resp.ok) throw new Error('Could not load platform servers');
    const data = await resp.json();
    _pconnuServers = (data.servers || []).filter(s => s.enabled);
}

async function _fetchProfiles() {
    const resp = await fetch('/api/v1/profiles', { headers: _pconnuHeaders(false) });
    if (!resp.ok) throw new Error('Could not load profiles');
    const data = await resp.json();
    _pconnuProfiles = data.profiles || [];
}

async function _fetchAllProfileSettings() {
    _pconnuSettings = {};
    await Promise.all(_pconnuProfiles.map(async (profile) => {
        try {
            const resp = await fetch(
                `/api/v1/profiles/${profile.id}/connector-settings`,
                { headers: _pconnuHeaders(false) }
            );
            if (!resp.ok) return;
            const data = await resp.json();
            (data.settings || []).forEach(s => {
                if (!_pconnuSettings[s.server_id]) _pconnuSettings[s.server_id] = {};
                _pconnuSettings[s.server_id][profile.id] = s;
            });
        } catch (_) { /* silent */ }
    }));
}

// ── Render: full panel ─────────────────────────────────────────────────────────

function _renderFullPanel(container) {
    if (_pconnuServers.length === 0) {
        container.innerHTML = `
            <div class="flex flex-col items-center justify-center py-20">
                <div class="w-16 h-16 rounded-full flex items-center justify-center mb-4"
                     style="background:rgba(129,140,248,0.08)">
                    <svg class="w-8 h-8" fill="none" stroke="${PMCP_ACCENT}" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                              d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2"/>
                    </svg>
                </div>
                <p class="text-gray-300 font-medium mb-1">No platform servers available</p>
                <p class="text-gray-500 text-sm text-center max-w-sm">
                    Ask your administrator to install and enable platform connector servers in the Components admin panel.
                </p>
            </div>`;
        return;
    }

    container.innerHTML = `
        <!-- Platform connectors section -->
        <div id="pmcp-section-platform" class="mb-6">
            <div class="flex items-center gap-2 mb-3">
                <svg class="w-4 h-4 text-indigo-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2"/>
                </svg>
                <span class="text-xs font-semibold uppercase tracking-wider" style="color:var(--text-muted)">Platform Connectors</span>
                <span class="text-xs" style="color:var(--text-muted)">— authenticated by admin, shared across users</span>
            </div>
            <div id="${PMCP_GRID_ID}-platform" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            </div>
        </div>

        <!-- User connectors section -->
        <div id="pmcp-section-user" class="mb-6">
            <div class="flex items-center gap-2 mb-3">
                <svg class="w-4 h-4 text-yellow-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                </svg>
                <span class="text-xs font-semibold uppercase tracking-wider" style="color:var(--text-muted)">User Connectors</span>
                <span class="text-xs" style="color:var(--text-muted)">— each user connects their own account</span>
            </div>
            <div id="${PMCP_GRID_ID}-user" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            </div>
        </div>

        <!-- Detail panel (hidden until a card is selected) -->
        <div id="${PMCP_DETAIL_ID}" class="hidden transition-all duration-200">
        </div>`;

    _renderGrid();

    // Auto-select first available card (platform first, then user)
    const firstVisible = _pconnuServers[0];
    if (firstVisible) _selectServer(firstVisible.id);
}

// ── Render: grid ───────────────────────────────────────────────────────────────

function _filteredServers() {
    return _pconnuServers.filter(s => {
        if (_pconnuTypeFilter !== 'all') {
            // "platform" = shared admin credentials; "user" = per-user auth
            if (_pconnuTypeFilter === 'platform' &&  s.requires_user_auth) return false;
            if (_pconnuTypeFilter === 'user'     && !s.requires_user_auth) return false;
        }
        if (_pconnuStatusFilter !== 'all') {
            const isActive = _isServerActiveForAnyProfile(s);
            if (_pconnuStatusFilter === 'active'   && !isActive) return false;
            if (_pconnuStatusFilter === 'inactive' &&  isActive) return false;
        }
        return true;
    });
}

function _isServerActiveForAnyProfile(server) {
    return _pconnuProfiles.some(p => _isServerActiveForProfile(server, p.id));
}

function _isServerActiveForProfile(server, profileId) {
    const setting = (_pconnuSettings[server.id] || {})[profileId];
    if (setting && setting.opted_in !== null && setting.opted_in !== undefined) {
        return !!setting.opted_in;
    }
    return !!server.auto_opt_in;
}

function _renderGrid() {
    const platformGrid    = document.getElementById(`${PMCP_GRID_ID}-platform`);
    const userGrid        = document.getElementById(`${PMCP_GRID_ID}-user`);
    const platformSection = document.getElementById('pmcp-section-platform');
    const userSection     = document.getElementById('pmcp-section-user');
    if (!platformGrid || !userGrid) return;

    const showPlatform = _pconnuTypeFilter !== 'user';
    const showUser     = _pconnuTypeFilter !== 'platform';

    if (platformSection) platformSection.classList.toggle('hidden', !showPlatform);
    if (userSection)     userSection.classList.toggle('hidden', !showUser);

    const _applyStatus = (servers) => servers.filter(s => {
        if (_pconnuStatusFilter === 'all') return true;
        const isActive = _isServerActiveForAnyProfile(s);
        return _pconnuStatusFilter === 'active' ? isActive : !isActive;
    });

    const emptyMsg = `<div class="col-span-full text-sm py-2" style="color:var(--text-muted)">None available.</div>`;

    if (showPlatform) {
        const servers = _applyStatus(_pconnuServers.filter(s => !s.requires_user_auth));
        platformGrid.innerHTML = servers.length === 0
            ? emptyMsg
            : servers.map(s => _renderServerCard(s)).join('');
    }
    if (showUser) {
        const servers = _applyStatus(_pconnuServers.filter(s => s.requires_user_auth));
        userGrid.innerHTML = servers.length === 0
            ? emptyMsg
            : servers.map(s => _renderServerCard(s)).join('');
    }

    // Attach click handlers across both grids
    [platformGrid, userGrid].forEach(grid => {
        grid.querySelectorAll('.pmcp-server-card').forEach(card => {
            card.style.cursor = 'pointer';
            card.addEventListener('click', () => _selectServer(card.dataset.serverId));
        });
    });

    // Re-apply selection highlight
    if (_pconnuSelectedId) {
        _applyCardSelection(_pconnuSelectedId);
    }
}

function _renderServerCard(server) {
    const isBuiltin = server.id.startsWith('uderia-');
    const isActive  = _isServerActiveForAnyProfile(server);

    const tools = _resolveTools(server);

    const toolBadges = tools.slice(0, 3).map(t =>
        `<span class="text-[10px] font-mono px-1.5 py-0.5 rounded"
               style="background:rgba(255,255,255,0.06);color:#9ca3af">${_esc(t)}</span>`
    ).join('');
    const toolMore = tools.length > 3
        ? `<span class="text-[10px] text-gray-500">+${tools.length - 3} more</span>` : '';

    const activeCount = _pconnuProfiles.filter(p => _isServerActiveForProfile(server, p.id)).length;

    return `
        <div class="glass-panel rounded-lg p-4 flex flex-col gap-3 pmcp-server-card transition-all duration-150"
             data-server-id="${_esc(server.id)}"
             data-server-type="${isBuiltin ? 'builtin' : 'remote'}"
             data-server-status="${isActive ? 'active' : 'inactive'}">

            <!-- Header row: icon + name + badges -->
            <div class="flex items-start justify-between gap-2">
                <div class="flex items-start gap-3 min-w-0">
                    <div class="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                         style="background:rgba(129,140,248,0.12)">
                        ${_serverIcon(server)}
                    </div>
                    <div class="min-w-0">
                        <h4 class="text-sm font-semibold truncate" style="color:var(--text-primary)">
                            ${_esc(server.display_name || server.name)}
                        </h4>
                        <p class="text-xs mt-0.5 line-clamp-2" style="color:var(--text-muted)">
                            ${_esc(server.description || '')}
                        </p>
                    </div>
                </div>
                <div class="flex flex-col items-end gap-1 flex-shrink-0">
                    <span class="text-[10px] px-1.5 py-0.5 rounded font-medium"
                          style="background:${isBuiltin ? 'rgba(129,140,248,0.15)' : 'rgba(6,182,212,0.15)'};
                                 color:${isBuiltin ? '#818cf8' : '#22d3ee'}">
                        ${isBuiltin ? 'built-in' : 'remote'}
                    </span>
                    ${server.auto_opt_in ? `
                    <span class="text-[10px] px-1.5 py-0.5 rounded font-medium"
                          style="background:rgba(52,211,153,0.12);color:#34d399">
                        auto
                    </span>` : ''}
                </div>
            </div>

            <!-- Tool badges -->
            ${tools.length > 0 ? `
            <div class="flex flex-wrap gap-1">
                ${toolBadges}${toolMore}
            </div>` : ''}

            <!-- Footer: profile count + status -->
            <div class="flex items-center justify-between text-xs mt-auto pt-1 border-t border-white/5">
                <span style="color:var(--text-muted)">
                    ${activeCount} of ${_pconnuProfiles.length} profile${_pconnuProfiles.length !== 1 ? 's' : ''} active
                </span>
                <div class="flex items-center gap-1.5">
                    <span class="inline-block w-2 h-2 rounded-full"
                          style="background:${isActive ? '#34d399' : '#6b7280'}"></span>
                    <span style="color:${isActive ? '#34d399' : '#6b7280'}">
                        ${isActive ? 'Active' : 'Inactive'}
                    </span>
                </div>
            </div>
        </div>`;
}

// ── Card selection & detail panel ──────────────────────────────────────────────

function _selectServer(serverId) {
    if (!serverId) return;
    _pconnuSelectedId = serverId;
    _applyCardSelection(serverId);

    const server = _pconnuServers.find(s => s.id === serverId);
    if (server) _renderDetailPanel(server);
}

function _applyCardSelection(serverId) {
    document.querySelectorAll('.pmcp-server-card').forEach(card => {
        if (card.dataset.serverId === serverId) {
            card.style.outline       = `2px solid rgba(129,140,248,0.65)`;
            card.style.outlineOffset = '-2px';
        } else {
            card.style.outline       = '';
            card.style.outlineOffset = '';
        }
    });
}

function _hideDetailPanel() {
    const panel = document.getElementById(PMCP_DETAIL_ID);
    if (panel) panel.classList.add('hidden');
}

function _renderDetailPanel(server) {
    const panel = document.getElementById(PMCP_DETAIL_ID);
    if (!panel) return;

    const tools = _resolveTools(server);
    const isBuiltin = server.id.startsWith('uderia-');

    // ── Profile assignment rows ──
    const profileRows = _pconnuProfiles.length === 0
        ? '<p class="text-gray-500 text-sm col-span-full">No profiles available.</p>'
        : _pconnuProfiles.map(p => _renderDetailProfileRow(server, p)).join('');

    // ── Tool list ──
    const toolList = tools.length > 0
        ? `<div class="flex flex-wrap gap-1.5">
               ${tools.map(t => `
               <span class="inline-flex items-center px-2 py-0.5 text-xs font-mono rounded"
                     style="background:rgba(129,140,248,0.1);color:#a5b4fc;border:1px solid rgba(129,140,248,0.2)">
                   ${_esc(t)}
               </span>`).join('')}
           </div>`
        : '<p class="text-gray-500 text-sm">No tools defined.</p>';

    // ── User-auth connector section ──
    // Rendered as a loading spinner; replaced after DOM insert by _loadConnectorAuthSection.
    const authSectionHtml = server.requires_user_auth && server.auth_schema
        ? _buildAuthSectionPlaceholder()
        : '';

    panel.classList.remove('hidden');
    panel.innerHTML = `
        <div class="glass-panel rounded-xl p-6" style="border-color:rgba(129,140,248,0.2)">

            <!-- Detail header -->
            <div class="flex items-start gap-5 mb-6">
                <div class="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0"
                     style="background:rgba(129,140,248,0.14)">
                    ${_serverIcon(server, true)}
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-3 flex-wrap">
                        <h2 class="text-xl font-bold" style="color:var(--text-primary)">
                            ${_esc(server.display_name || server.name)}
                        </h2>
                        ${server.version ? `<span class="text-sm text-gray-400">v${_esc(server.version)}</span>` : ''}
                        <span class="text-xs px-2 py-0.5 rounded font-medium"
                              style="background:${isBuiltin ? 'rgba(129,140,248,0.15)' : 'rgba(6,182,212,0.15)'};
                                     color:${isBuiltin ? '#818cf8' : '#22d3ee'}">
                            ${isBuiltin ? 'built-in' : 'remote'}
                        </span>
                        ${server.auto_opt_in ? `
                        <span class="text-xs px-2 py-0.5 rounded font-medium"
                              style="background:rgba(52,211,153,0.12);color:#34d399">
                            auto-enabled
                        </span>` : ''}
                    </div>
                    <p class="text-sm mt-2" style="color:var(--text-muted)">
                        ${_esc(server.description || '')}
                    </p>
                </div>
            </div>

            ${authSectionHtml}

            <!-- Two-column body -->
            <div class="grid grid-cols-1 lg:grid-cols-5 gap-6">

                <!-- Left: tools -->
                <div class="lg:col-span-2">
                    <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">
                        Available Tools
                    </h3>
                    ${toolList}

                    ${!server.user_can_opt_out && server.auto_opt_in ? `
                    <div class="mt-4 flex items-center gap-2 text-xs text-gray-400">
                        <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                  d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                        </svg>
                        Admin-enforced on all profiles
                    </div>` : ''}
                </div>

                <!-- Right: profile assignment -->
                <div class="lg:col-span-3">
                    <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">
                        Profile Assignment
                    </h3>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        ${profileRows}
                    </div>
                    ${!server.user_can_configure_tools ? '' : `
                    <p class="text-[11px] text-gray-500 mt-3">
                        Tool-level configuration is available in Profile Edit → Connectors.
                    </p>`}
                </div>
            </div>
        </div>`;

    // Fetch and render live connector status after the DOM is inserted
    if (server.requires_user_auth && server.auth_schema) {
        requestAnimationFrame(() => _loadConnectorAuthSection(server));
    }
}

// ── Dynamic connector auth section ────────────────────────────────────────────
// Driven by server.auth_schema.type.  Supported types:
//   oauth2    — existing OAuth popup flow (e.g. Google)
//   token     — user pastes a personal access token
//   api_key   — user pastes an API key
// Adding support for a new auth type requires only adding a manifest auth_schema
// with the appropriate type; no JS changes needed for the dispatch path.

function _buildAuthSectionPlaceholder() {
    return `<div id="pmcp-connector-auth-section" class="mb-4">
        <div class="flex items-center gap-2 text-xs py-2" style="color:var(--text-muted)">
            <svg class="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
            </svg>
            Loading connection status…
        </div>
    </div>`;
}

async function _loadConnectorAuthSection(server) {
    const section = document.getElementById('pmcp-connector-auth-section');
    if (!section) return;
    const authSchema = server.auth_schema;
    if (!authSchema) { section.innerHTML = ''; return; }
    const platform = server.id.startsWith('uderia-') ? server.id.slice('uderia-'.length) : server.id;
    if (authSchema.type === 'oauth2') {
        await _loadConnectorOAuthContent(platform, server, authSchema);
    } else if (authSchema.type === 'token' || authSchema.type === 'api_key') {
        await _loadConnectorTokenContent(platform, server, authSchema);
    }
}

// ── OAuth2 flow ──────────────────────────────────────────────────────────────

async function _loadConnectorOAuthContent(platform, server, authSchema) {
    const section = document.getElementById('pmcp-connector-auth-section');
    if (!section) return;
    try {
        const resp = await fetch(
            `/api/v1/connectors/${encodeURIComponent(platform)}/status`,
            { headers: _pconnuHeaders(false) }
        );
        if (!resp.ok) throw new Error(`Status ${resp.status}`);
        const status = await resp.json();
        section.innerHTML = _renderConnectorOAuthCard(platform, server.id, status, authSchema);
        _wireConnectorOAuthCard(platform, server, authSchema);
    } catch (err) {
        const display = (authSchema && authSchema.display_name) || _titleCase(platform);
        section.innerHTML = `<p class="text-xs py-1" style="color:var(--text-muted)">Could not load ${_esc(display)} connection status.</p>`;
    }
}

function _connectorIcon(iconKey) {
    const key = (iconKey || '').toLowerCase();
    if (key === 'google') {
        return `<svg class="w-6 h-6 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
        </svg>`;
    }
    if (key === 'microsoft') {
        return `<svg class="w-6 h-6 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <rect x="1" y="1" width="10.5" height="10.5" fill="#F25022"/>
            <rect x="12.5" y="1" width="10.5" height="10.5" fill="#7FBA00"/>
            <rect x="1" y="12.5" width="10.5" height="10.5" fill="#00A4EF"/>
            <rect x="12.5" y="12.5" width="10.5" height="10.5" fill="#FFB900"/>
        </svg>`;
    }
    if (key === 'slack') {
        return `<svg class="w-6 h-6 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52z" fill="#E01E5A"/>
            <path d="M6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313z" fill="#E01E5A"/>
            <path d="M8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834z" fill="#36C5F0"/>
            <path d="M8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312z" fill="#36C5F0"/>
            <path d="M18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834z" fill="#2EB67D"/>
            <path d="M17.687 8.834a2.528 2.528 0 0 1-2.521 2.521 2.527 2.527 0 0 1-2.521-2.521V2.522A2.527 2.527 0 0 1 15.166 0a2.528 2.528 0 0 1 2.521 2.522v6.312z" fill="#2EB67D"/>
            <path d="M15.166 18.956a2.528 2.528 0 0 1 2.521 2.522A2.528 2.528 0 0 1 15.166 24a2.527 2.527 0 0 1-2.521-2.522v-2.522h2.521z" fill="#ECB22E"/>
            <path d="M15.166 17.687a2.527 2.527 0 0 1-2.521-2.521 2.526 2.526 0 0 1 2.521-2.521h6.312A2.528 2.528 0 0 1 24 15.166a2.528 2.528 0 0 1-2.522 2.521h-6.312z" fill="#ECB22E"/>
        </svg>`;
    }
    return `<svg class="w-6 h-6 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round"
              d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244"/>
    </svg>`;
}

function _renderConnectorOAuthCard(platform, serverId, status, authSchema) {
    const display = (authSchema && authSchema.display_name) || _titleCase(platform);
    const icon = _connectorIcon((authSchema && authSchema.icon) || platform);

    if (!status.configured) {
        return `
        <div class="p-4 rounded-xl flex items-center gap-4 mb-4"
             style="background:rgba(251,191,36,0.05);border:1px solid rgba(251,191,36,0.15)">
            ${icon}
            <div class="flex-1 min-w-0">
                <p class="text-sm font-semibold" style="color:#fbbf24">${_esc(display)} Account Connection</p>
                <p class="text-xs mt-0.5" style="color:var(--text-muted)">
                    Admin must configure OAuth credentials in the Connectors admin panel
                    before users can connect their ${_esc(display)} accounts.
                </p>
            </div>
        </div>`;
    }

    if (status.connected) {
        return `
        <div class="p-4 rounded-xl flex items-center gap-4 mb-4"
             style="background:rgba(52,211,153,0.05);border:1px solid rgba(52,211,153,0.2)">
            ${icon}
            <div class="flex-1 min-w-0">
                <p class="text-sm font-semibold" style="color:#34d399">${_esc(display)} Account Connected</p>
                <p class="text-xs mt-0.5" style="color:var(--text-muted)">${_esc(status.email || '')}</p>
            </div>
            <button id="pmcp-connector-disconnect-btn"
                    class="flex-shrink-0 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
                    style="background:rgba(248,113,113,0.12);color:#f87171;border:1px solid rgba(248,113,113,0.25)">
                Disconnect
            </button>
        </div>`;
    }

    return `
    <div class="p-4 rounded-xl flex items-center gap-4 mb-4"
         style="background:rgba(129,140,248,0.05);border:1px solid rgba(129,140,248,0.2)">
        ${icon}
        <div class="flex-1 min-w-0">
            <p class="text-sm font-semibold" style="color:var(--text-primary)">${_esc(display)} Account Connection</p>
            <p class="text-xs mt-0.5" style="color:var(--text-muted)">
                ${_esc((authSchema && authSchema.description) || `Connect your ${display} account to enable its tools.`)}
            </p>
        </div>
        <button id="pmcp-connector-connect-btn"
                class="flex-shrink-0 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
                style="background:rgba(129,140,248,0.15);color:#a5b4fc;border:1px solid rgba(129,140,248,0.3)">
            Connect ${_esc(display)}
        </button>
    </div>`;
}

function _wireConnectorOAuthCard(platform, server, authSchema) {
    const serverId = server.id;
    const connectBtn = document.getElementById('pmcp-connector-connect-btn');
    if (connectBtn) {
        connectBtn.addEventListener('click', () => _connectAccount(platform, authSchema));
    }
    const disconnectBtn = document.getElementById('pmcp-connector-disconnect-btn');
    if (disconnectBtn) {
        disconnectBtn.addEventListener('click', () => _disconnectAccount(platform, server, authSchema));
    }
    // Listen for OAuth success from popup
    const listenerKey = `_connectorOAuthListener_${platform}`;
    if (window[listenerKey]) window.removeEventListener('message', window[listenerKey]);
    window[listenerKey] = (event) => {
        if (event.data && event.data.type === `${platform}_oauth_success`) {
            window.removeEventListener('message', window[listenerKey]);
            window[listenerKey] = null;
            _loadConnectorOAuthContent(platform, server, authSchema);
        }
    };
    window.addEventListener('message', window[listenerKey]);
}

async function _connectAccount(platform, authSchema) {
    const display = (authSchema && authSchema.display_name) || _titleCase(platform);
    const btn = document.getElementById('pmcp-connector-connect-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Opening…'; }
    try {
        const resp = await fetch(
            `/api/v1/connectors/${encodeURIComponent(platform)}/auth`,
            { headers: _pconnuHeaders(false) }
        );
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${resp.status}`);
        }
        const { auth_url } = await resp.json();
        const popup = window.open(auth_url, `${platform}_oauth`, 'width=520,height=640,menubar=no,toolbar=no,location=no');
        if (!popup) throw new Error('Popup was blocked. Please allow popups for this site and try again.');
    } catch (err) {
        if (btn) { btn.disabled = false; btn.textContent = `Connect ${display}`; }
        alert(`Could not start ${display} authorization:\n${err.message}`);
    }
}

async function _disconnectAccount(platform, server, authSchema) {
    const display = (authSchema && authSchema.display_name) || _titleCase(platform);
    if (!confirm(`Disconnect your ${display} account? Its tools will stop working.`)) return;
    const btn = document.getElementById('pmcp-connector-disconnect-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Disconnecting…'; }
    try {
        await fetch(
            `/api/v1/connectors/${encodeURIComponent(platform)}/connection`,
            { method: 'DELETE', headers: _pconnuHeaders(false) }
        );
        await _loadConnectorOAuthContent(platform, server, authSchema);
    } catch (err) {
        if (btn) { btn.disabled = false; btn.textContent = 'Disconnect'; }
    }
}

// ── Token / API-key flow ──────────────────────────────────────────────────────

async function _loadConnectorTokenContent(platform, server, authSchema) {
    const section = document.getElementById('pmcp-connector-auth-section');
    if (!section) return;
    try {
        const resp = await fetch(
            `/api/v1/connectors/${encodeURIComponent(platform)}/status`,
            { headers: _pconnuHeaders(false) }
        );
        if (!resp.ok) throw new Error(`Status ${resp.status}`);
        const status = await resp.json();
        section.innerHTML = _renderConnectorTokenCard(platform, server.id, status, authSchema);
        _wireConnectorTokenCard(platform, server, authSchema);
    } catch (err) {
        const display = (authSchema && authSchema.display_name) || _titleCase(platform);
        section.innerHTML = `<p class="text-xs py-1" style="color:var(--text-muted)">Could not load ${_esc(display)} status.</p>`;
    }
}

function _renderConnectorTokenCard(platform, serverId, status, authSchema) {
    const display     = (authSchema && authSchema.display_name) || _titleCase(platform);
    const description = (authSchema && authSchema.description) || `Enter your ${_esc(display)} ${authSchema && authSchema.type === 'api_key' ? 'API key' : 'token'} to enable its tools.`;
    const placeholder = (authSchema && authSchema.placeholder) || '';
    const label       = (authSchema && authSchema.type === 'api_key') ? 'API Key' : 'Access Token';
    const icon        = _connectorIcon((authSchema && authSchema.icon) || platform);

    if (status.connected) {
        return `
        <div class="p-4 rounded-xl flex items-center gap-4 mb-4"
             style="background:rgba(52,211,153,0.05);border:1px solid rgba(52,211,153,0.2)">
            ${icon}
            <div class="flex-1 min-w-0">
                <p class="text-sm font-semibold" style="color:#34d399">${_esc(display)} ${_esc(label)} Active</p>
                <p class="text-xs mt-0.5" style="color:var(--text-muted)">${_esc(label)} saved and encrypted.</p>
            </div>
            <button id="pmcp-connector-token-clear-btn"
                    class="flex-shrink-0 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
                    style="background:rgba(248,113,113,0.12);color:#f87171;border:1px solid rgba(248,113,113,0.25)">
                Remove
            </button>
        </div>`;
    }

    return `
    <div class="p-4 rounded-xl flex flex-col gap-3 mb-4"
         style="background:rgba(129,140,248,0.05);border:1px solid rgba(129,140,248,0.2)">
        <div class="flex items-center gap-3">
            ${icon}
            <div class="flex-1 min-w-0">
                <p class="text-sm font-semibold" style="color:var(--text-primary)">${_esc(display)} ${_esc(label)}</p>
                <p class="text-xs mt-0.5" style="color:var(--text-muted)">${_esc(description)}</p>
            </div>
        </div>
        <div class="flex gap-2">
            <input type="password" id="pmcp-connector-token-input"
                   placeholder="${_esc(placeholder)}"
                   autocomplete="off" spellcheck="false"
                   class="flex-1 text-xs px-3 py-1.5 rounded-lg outline-none font-mono"
                   style="background:rgba(255,255,255,0.06);color:var(--text-primary);border:1px solid rgba(255,255,255,0.1)">
            <button id="pmcp-connector-token-save-btn"
                    class="flex-shrink-0 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
                    style="background:rgba(129,140,248,0.15);color:#a5b4fc;border:1px solid rgba(129,140,248,0.3)">
                Save
            </button>
        </div>
    </div>`;
}

function _wireConnectorTokenCard(platform, server, authSchema) {
    const saveBtn = document.getElementById('pmcp-connector-token-save-btn');
    if (saveBtn) saveBtn.addEventListener('click', () => _saveConnectorToken(platform, server, authSchema));
    const clearBtn = document.getElementById('pmcp-connector-token-clear-btn');
    if (clearBtn) clearBtn.addEventListener('click', () => _deleteConnectorToken(platform, server, authSchema));

    const input = document.getElementById('pmcp-connector-token-input');
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') _saveConnectorToken(platform, server, authSchema);
        });
    }
}

async function _saveConnectorToken(platform, server, authSchema) {
    const input   = document.getElementById('pmcp-connector-token-input');
    const btn     = document.getElementById('pmcp-connector-token-save-btn');
    const value   = (input && input.value || '').trim();
    if (!value) {
        if (input) { input.style.borderColor = 'rgba(248,113,113,0.5)'; }
        return;
    }
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
    try {
        const resp = await fetch(
            `/api/v1/connectors/${encodeURIComponent(platform)}/token`,
            {
                method: 'POST',
                headers: _pconnuHeaders(),
                body: JSON.stringify({ token: value }),
            }
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        await _loadConnectorTokenContent(platform, server, authSchema);
    } catch (err) {
        if (btn) { btn.disabled = false; btn.textContent = 'Save'; }
        _pconnuNotify('error', `Could not save token: ${err.message}`);
    }
}

async function _deleteConnectorToken(platform, server, authSchema) {
    const label = (authSchema && authSchema.type === 'api_key') ? 'API key' : 'token';
    if (!confirm(`Remove your saved ${label}? Its tools will stop working.`)) return;
    const btn = document.getElementById('pmcp-connector-token-clear-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Removing…'; }
    try {
        await fetch(
            `/api/v1/connectors/${encodeURIComponent(platform)}/token`,
            { method: 'DELETE', headers: _pconnuHeaders(false) }
        );
        await _loadConnectorTokenContent(platform, server, authSchema);
    } catch (err) {
        if (btn) { btn.disabled = false; btn.textContent = 'Remove'; }
    }
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function _titleCase(str) {
    return (str || '').charAt(0).toUpperCase() + (str || '').slice(1);
}

function _resolveTools(server) {
    // Prefer available_tools (admin-governed subset); fall back to manifest_tools (full list).
    const at = server.available_tools;
    if (Array.isArray(at) && at.length) return at;
    if (Array.isArray(server.manifest_tools) && server.manifest_tools.length) return server.manifest_tools;
    return [];
}

function _renderDetailProfileRow(server, profile) {
    const profileId   = profile.id;
    const serverId    = server.id;
    const setting     = (_pconnuSettings[serverId] || {})[profileId];
    const isLocked    = server.auto_opt_in && !server.user_can_opt_out;
    const isActive    = _isServerActiveForProfile(server, profileId);

    const profileType = profile.profile_type || profile.type || 'llm_only';
    const ifocLabel   = { llm_only: 'Ideate', rag_focused: 'Focus', tool_enabled: 'Optimize', genie: 'Coordinate' };
    const ifocColor   = { llm_only: '#4ade80', rag_focused: '#3b82f6', tool_enabled: '#F15F22', genie: '#9333ea' };
    const label       = ifocLabel[profileType] || profileType;
    const color       = ifocColor[profileType] || '#9ca3af';
    const tag         = profile.tag || profile.id;

    const lockSvg = `
        <svg class="w-3.5 h-3.5 text-gray-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
        </svg>`;

    const toggleHtml = isLocked
        ? `<div class="flex items-center gap-1.5 opacity-50" title="Auto-enabled — cannot opt out">
               ${lockSvg}
               <label class="ind-toggle ind-toggle--sm opacity-50 pointer-events-none">
                   <input type="checkbox" checked disabled>
                   <span class="ind-track"></span>
               </label>
           </div>`
        : `<label class="ind-toggle ind-toggle--sm">
               <input type="checkbox"
                      id="pmcp-toggle-${_esc(serverId)}-${_esc(profileId)}"
                      ${isActive ? 'checked' : ''}
                      onchange="window.togglePlatformConnectorProfileAssignment('${_esc(serverId)}', '${_esc(profileId)}', this.checked)">
               <span class="ind-track"></span>
           </label>`;

    return `
        <div class="flex items-center justify-between gap-2 px-3 py-2.5 rounded-lg"
             style="background:rgba(255,255,255,0.04)">
            <div class="flex items-center gap-2 min-w-0">
                <span class="inline-block w-2 h-2 rounded-full flex-shrink-0"
                      style="background:${color}"></span>
                <span class="text-xs font-medium text-gray-200 truncate">${_esc(tag)}</span>
                <span class="text-[10px] px-1.5 rounded flex-shrink-0"
                      style="background:${color}20;color:${color}">${label}</span>
            </div>
            ${toggleHtml}
        </div>`;
}

// ── Filter handlers ────────────────────────────────────────────────────────────

function _pmcpSetTypeFilter(value, btn) {
    _pconnuTypeFilter = value;
    _updateFilterPills('pmcp-type-filters', value);
    _renderGrid();
    const first = _filteredServers()[0];
    if (first) _selectServer(first.id);
    else _hideDetailPanel();
}

function _pmcpSetStatusFilter(value, btn) {
    _pconnuStatusFilter = value;
    _updateFilterPills('pmcp-status-filters', value);
    _renderGrid();
    const first = _filteredServers()[0];
    if (first) _selectServer(first.id);
    else _hideDetailPanel();
}

function _updateFilterPills(containerId, activeValue) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.querySelectorAll('.filter-pill').forEach(pill => {
        pill.classList.toggle('filter-pill--active', pill.dataset.filter === activeValue);
    });
}

// ── Server icon ────────────────────────────────────────────────────────────────

function _serverIcon(server, large = false) {
    const sz   = large ? 'w-6 h-6' : 'w-5 h-5';
    const name = (server.id || '').toLowerCase();

    if (name.includes('web') || name.includes('search')) return `
        <svg class="${sz}" fill="none" stroke="${PMCP_ACCENT}" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9"/>
        </svg>`;

    if (name.includes('file')) return `
        <svg class="${sz}" fill="none" stroke="${PMCP_ACCENT}" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z"/>
        </svg>`;

    if (name.includes('browser')) return `
        <svg class="${sz}" fill="none" stroke="${PMCP_ACCENT}" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
        </svg>`;

    if (name.includes('google')) return `
        <svg class="${sz}" viewBox="0 0 24 24" fill="none">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
        </svg>`;

    if (name.includes('shell') || name.includes('exec')) return `
        <svg class="${sz}" fill="none" stroke="${PMCP_ACCENT}" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
        </svg>`;

    // Generic server icon
    return `
        <svg class="${sz}" fill="none" stroke="${PMCP_ACCENT}" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"/>
        </svg>`;
}

// ── Actions ────────────────────────────────────────────────────────────────────

async function togglePlatformConnectorProfileAssignment(serverId, profileId, enabled) {
    const toggle = document.getElementById(`pmcp-toggle-${serverId}-${profileId}`);
    if (toggle) toggle.disabled = true;

    try {
        const resp = await fetch(
            `/api/v1/profiles/${profileId}/connector-settings/${serverId}`,
            {
                method: 'PUT',
                headers: _pconnuHeaders(),
                body: JSON.stringify({ opted_in: enabled ? 1 : 0 }),
            }
        );
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.message || 'Update failed');
        }
        // Update local cache
        if (!_pconnuSettings[serverId]) _pconnuSettings[serverId] = {};
        if (!_pconnuSettings[serverId][profileId]) _pconnuSettings[serverId][profileId] = {};
        _pconnuSettings[serverId][profileId].opted_in = enabled ? 1 : 0;

        _pconnuNotify('success', `Server ${enabled ? 'enabled' : 'disabled'} for profile`);

        // Refresh the card and detail panel to reflect updated counts
        _renderGrid();
        const server = _pconnuServers.find(s => s.id === serverId);
        if (server && _pconnuSelectedId === serverId) _renderDetailPanel(server);

    } catch (err) {
        _pconnuNotify('error', err.message);
        if (toggle) toggle.checked = !enabled;
    } finally {
        if (toggle) toggle.disabled = false;
    }
}


// ── Profile Edit Modal: Platform Connector Section ───────────────────────────────────

async function loadProfileConnectorSection(modal, profileId) {
    const container = modal
        ? modal.querySelector('#profile-connector-content')
        : document.getElementById('profile-connector-content');
    const navItem = modal
        ? modal.querySelector('#profile-nav-platform-connector')
        : document.getElementById('profile-nav-platform-connector');

    if (!container) return;
    container.innerHTML = '<div class="text-center text-gray-500 text-sm py-4">Loading…</div>';

    try {
        const [serversResp, settingsResp] = await Promise.all([
            fetch('/api/v1/platform-connectors', { headers: _pconnuHeaders(false) }),
            fetch(`/api/v1/profiles/${profileId}/connector-settings`, { headers: _pconnuHeaders(false) }),
        ]);

        const serversData  = serversResp.ok  ? await serversResp.json()  : { servers: [] };
        const settingsData = settingsResp.ok ? await settingsResp.json() : { settings: [] };

        const enabledServers = (serversData.servers || []).filter(s => s.enabled);
        const settingsMap    = {};
        (settingsData.settings || []).forEach(s => { settingsMap[s.server_id] = s; });

        const activeServers = enabledServers.filter(server => {
            const setting = settingsMap[server.id];
            if (setting && setting.opted_in !== null && setting.opted_in !== undefined) return !!setting.opted_in;
            return !!server.auto_opt_in;
        });

        if (navItem) navItem.classList.toggle('hidden', activeServers.length === 0);

        if (activeServers.length === 0) {
            container.innerHTML = `
                <div class="text-center py-6">
                    <p class="text-gray-400 text-sm">No platform servers are enabled for this profile.</p>
                    <p class="text-gray-500 text-xs mt-1">Go to Platform Components → Connectors to assign servers.</p>
                </div>`;
            return;
        }

        container.innerHTML = `<div class="space-y-4">
            ${activeServers.map(s => _renderProfileMcpServerCard(s, settingsMap[s.id] || {})).join('')}
        </div>`;

    } catch (err) {
        container.innerHTML = `<div class="text-red-400 text-sm py-4">Failed to load: ${_esc(err.message)}</div>`;
    }
}

function _renderProfileMcpServerCard(server, setting) {
    const isLocked       = server.auto_opt_in && !server.user_can_opt_out;
    const canConfigTools = !!server.user_can_configure_tools;
    const availableTools = _resolveTools(server);
    let userTools = [];
    try { userTools = JSON.parse(setting.user_tools || '[]'); } catch (_) {}

    const lockBadge = isLocked ? `
        <span class="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded"
              style="background:rgba(156,163,175,0.12);color:#9ca3af;border:1px solid rgba(156,163,175,0.25)">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
            </svg>
            Admin-enforced
        </span>` : '';

    let toolSection = '';
    if (canConfigTools && availableTools.length > 0) {
        const checkboxes = availableTools.map(tool => {
            const isChecked = userTools.length === 0 || userTools.includes(tool);
            return `
            <label class="flex items-center gap-2 py-1 px-2 rounded hover:bg-white/5 cursor-pointer group">
                <input type="checkbox" class="pmcp-profile-tool-check w-4 h-4 rounded"
                       style="accent-color:#818cf8"
                       data-server-id="${_esc(server.id)}"
                       data-tool="${_esc(tool)}"
                       ${isChecked ? 'checked' : ''}
                       onchange="window.updateProfileConnectorTools('${_esc(server.id)}')">
                <span class="font-mono text-xs text-gray-300 group-hover:text-white">${_esc(tool)}</span>
            </label>`;
        }).join('');
        toolSection = `
            <div class="mt-3">
                <p class="text-[11px] text-gray-500 uppercase tracking-wide font-medium mb-2">Active Tools for this Profile</p>
                <div class="space-y-0.5">${checkboxes}</div>
            </div>`;
    } else if (!canConfigTools && availableTools.length > 0) {
        toolSection = `
            <div class="mt-2 flex flex-wrap gap-1">
                ${availableTools.map(t => `
                <span class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono rounded"
                      style="background:rgba(255,255,255,0.06);color:#9ca3af">${_esc(t)}</span>`).join('')}
                <span class="text-[10px] text-gray-500 self-center">— all tools active</span>
            </div>`;
    }

    return `
        <div class="glass-panel rounded-lg p-4" style="border-color:rgba(129,140,248,0.12)"
             data-server-id="${_esc(server.id)}">
            <div class="flex items-center gap-2 mb-1">
                <span class="text-sm font-semibold text-white">${_esc(server.display_name || server.name)}</span>
                ${lockBadge}
            </div>
            <p class="text-xs text-gray-400 mb-2">${_esc(server.description || '')}</p>
            ${toolSection}
        </div>`;
}

async function updateProfileConnectorTools(serverId) {
    const saveBtn  = document.getElementById('profile-modal-save');
    const profileId = saveBtn ? saveBtn.dataset.profileId : null;
    if (!profileId) return;

    const checks   = document.querySelectorAll(`.pmcp-profile-tool-check[data-server-id="${serverId}"]`);
    const selected = Array.from(checks).filter(c => c.checked).map(c => c.dataset.tool);
    const allTools = Array.from(checks).map(c => c.dataset.tool);
    const userTools = selected.length === allTools.length ? null : selected;

    try {
        await fetch(
            `/api/v1/profiles/${profileId}/connector-settings/${serverId}`,
            {
                method: 'PUT',
                headers: _pconnuHeaders(),
                body: JSON.stringify({ user_tools: userTools }),
            }
        );
    } catch (err) {
        _pconnuNotify('error', `Could not save tool selection: ${err.message}`);
    }
}

// ── Public API ─────────────────────────────────────────────────────────────────

window.loadPlatformConnectorPanel           = loadPlatformConnectorPanel;
window.renderPlatformConnectorPanel         = () => _renderGrid();
window.togglePlatformConnectorProfileAssignment = togglePlatformConnectorProfileAssignment;
window.loadProfileConnectorSection  = loadProfileConnectorSection;
window.updateProfileConnectorTools  = updateProfileConnectorTools;
window._pmcpSetTypeFilter             = _pmcpSetTypeFilter;
window._pmcpSetStatusFilter           = _pmcpSetStatusFilter;
