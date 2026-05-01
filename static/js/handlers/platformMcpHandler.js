/**
 * platformMcpHandler.js
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

function _pmcpuHeaders(json = true) {
    const h = {};
    if (json) h['Content-Type'] = 'application/json';
    const token = localStorage.getItem('tda_auth_token');
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
}

function _pmcpuNotify(type, msg) {
    if (window.showNotification) window.showNotification(type, msg);
    else console.log(`[PlatformMCP] ${type}: ${msg}`);
}

function _esc(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── State ──────────────────────────────────────────────────────────────────────

let _pmcpuServers        = [];   // admin-enabled platform servers
let _pmcpuProfiles       = [];   // current user's profiles
let _pmcpuSettings       = {};   // { server_id: { profile_id: {opted_in, user_tools} } }
let _pmcpuSelectedId     = null; // currently selected server id
let _pmcpuStatusFilter   = 'all';
let _pmcpuTypeFilter     = 'all';

// ── Entry point ────────────────────────────────────────────────────────────────

async function loadPlatformMcpPanel() {
    const container = document.getElementById('platform-mcp-container');
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
    const resp = await fetch('/api/v1/platform-mcp-servers', { headers: _pmcpuHeaders(false) });
    if (!resp.ok) throw new Error('Could not load platform servers');
    const data = await resp.json();
    _pmcpuServers = (data.servers || []).filter(s => s.enabled);
}

async function _fetchProfiles() {
    const resp = await fetch('/api/v1/profiles', { headers: _pmcpuHeaders(false) });
    if (!resp.ok) throw new Error('Could not load profiles');
    const data = await resp.json();
    _pmcpuProfiles = data.profiles || [];
}

async function _fetchAllProfileSettings() {
    _pmcpuSettings = {};
    await Promise.all(_pmcpuProfiles.map(async (profile) => {
        try {
            const resp = await fetch(
                `/api/v1/profiles/${profile.id}/platform-mcp-settings`,
                { headers: _pmcpuHeaders(false) }
            );
            if (!resp.ok) return;
            const data = await resp.json();
            (data.settings || []).forEach(s => {
                if (!_pmcpuSettings[s.server_id]) _pmcpuSettings[s.server_id] = {};
                _pmcpuSettings[s.server_id][profile.id] = s;
            });
        } catch (_) { /* silent */ }
    }));
}

// ── Render: full panel ─────────────────────────────────────────────────────────

function _renderFullPanel(container) {
    if (_pmcpuServers.length === 0) {
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
                    Ask your administrator to install and enable platform MCP servers in the Components admin panel.
                </p>
            </div>`;
        return;
    }

    container.innerHTML = `
        <!-- Filter pills -->
        <div class="flex items-center gap-6 mb-6" id="pmcp-filter-row">
            <div class="flex items-center gap-2">
                <span class="text-xs text-gray-400 uppercase tracking-wide">Type:</span>
                <div class="flex gap-1.5" id="pmcp-type-filters">
                    <button class="filter-pill filter-pill--active" data-filter="all"
                            onclick="window._pmcpSetTypeFilter('all', this)">All</button>
                    <button class="filter-pill" data-filter="builtin"
                            onclick="window._pmcpSetTypeFilter('builtin', this)">Built-in</button>
                    <button class="filter-pill" data-filter="remote"
                            onclick="window._pmcpSetTypeFilter('remote', this)">Remote</button>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <span class="text-xs text-gray-400 uppercase tracking-wide">Status:</span>
                <div class="flex gap-1.5" id="pmcp-status-filters">
                    <button class="filter-pill filter-pill--active" data-filter="all"
                            onclick="window._pmcpSetStatusFilter('all', this)">All</button>
                    <button class="filter-pill" data-filter="active"
                            onclick="window._pmcpSetStatusFilter('active', this)">Active</button>
                    <button class="filter-pill" data-filter="inactive"
                            onclick="window._pmcpSetStatusFilter('inactive', this)">Inactive</button>
                </div>
            </div>
        </div>

        <!-- Card grid -->
        <div id="${PMCP_GRID_ID}" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        </div>

        <!-- Detail panel (hidden until a card is selected) -->
        <div id="${PMCP_DETAIL_ID}" class="hidden transition-all duration-200">
        </div>`;

    _renderGrid();

    // Auto-select first visible card
    const firstVisible = _filteredServers()[0];
    if (firstVisible) _selectServer(firstVisible.id);
}

// ── Render: grid ───────────────────────────────────────────────────────────────

function _filteredServers() {
    return _pmcpuServers.filter(s => {
        // Type filter
        if (_pmcpuTypeFilter !== 'all') {
            const isBuiltin = (s.source_id || '').includes('builtin') || s.id.startsWith('uderia-');
            if (_pmcpuTypeFilter === 'builtin' && !isBuiltin) return false;
            if (_pmcpuTypeFilter === 'remote' && isBuiltin) return false;
        }
        // Status filter — "active" = user has ≥1 profile opted in
        if (_pmcpuStatusFilter !== 'all') {
            const isActive = _isServerActiveForAnyProfile(s);
            if (_pmcpuStatusFilter === 'active' && !isActive) return false;
            if (_pmcpuStatusFilter === 'inactive' && isActive) return false;
        }
        return true;
    });
}

function _isServerActiveForAnyProfile(server) {
    return _pmcpuProfiles.some(p => _isServerActiveForProfile(server, p.id));
}

function _isServerActiveForProfile(server, profileId) {
    const setting = (_pmcpuSettings[server.id] || {})[profileId];
    if (setting && setting.opted_in !== null && setting.opted_in !== undefined) {
        return !!setting.opted_in;
    }
    return !!server.auto_opt_in;
}

function _renderGrid() {
    const grid = document.getElementById(PMCP_GRID_ID);
    if (!grid) return;

    const servers = _filteredServers();
    if (servers.length === 0) {
        grid.innerHTML = `
            <div class="col-span-full text-center py-10 text-gray-400 text-sm">
                No servers match the current filter.
            </div>`;
        _hideDetailPanel();
        return;
    }

    grid.innerHTML = servers.map(s => _renderServerCard(s)).join('');

    // Attach click handlers
    grid.querySelectorAll('.pmcp-server-card').forEach(card => {
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => _selectServer(card.dataset.serverId));
    });

    // Re-apply selection highlight
    if (_pmcpuSelectedId) {
        _applyCardSelection(_pmcpuSelectedId);
    }
}

function _renderServerCard(server) {
    const isBuiltin = server.id.startsWith('uderia-');
    const isActive  = _isServerActiveForAnyProfile(server);

    let tools = [];
    try { tools = JSON.parse(server.available_tools || '[]'); } catch (_) {}

    const toolBadges = tools.slice(0, 3).map(t =>
        `<span class="text-[10px] font-mono px-1.5 py-0.5 rounded"
               style="background:rgba(255,255,255,0.06);color:#9ca3af">${_esc(t)}</span>`
    ).join('');
    const toolMore = tools.length > 3
        ? `<span class="text-[10px] text-gray-500">+${tools.length - 3} more</span>` : '';

    const activeCount = _pmcpuProfiles.filter(p => _isServerActiveForProfile(server, p.id)).length;

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
                    ${activeCount} of ${_pmcpuProfiles.length} profile${_pmcpuProfiles.length !== 1 ? 's' : ''} active
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
    _pmcpuSelectedId = serverId;
    _applyCardSelection(serverId);

    const server = _pmcpuServers.find(s => s.id === serverId);
    if (server) _renderDetailPanel(server);
}

function _applyCardSelection(serverId) {
    const grid = document.getElementById(PMCP_GRID_ID);
    if (!grid) return;
    grid.querySelectorAll('.pmcp-server-card').forEach(card => {
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

    let tools = [];
    try { tools = JSON.parse(server.available_tools || '[]'); } catch (_) {}

    const isBuiltin = server.id.startsWith('uderia-');
    const isGoogleServer = server.id === 'uderia-google' || (server.name || '').toLowerCase().includes('google');

    // ── Profile assignment rows ──
    const profileRows = _pmcpuProfiles.length === 0
        ? '<p class="text-gray-500 text-sm col-span-full">No profiles available.</p>'
        : _pmcpuProfiles.map(p => _renderDetailProfileRow(server, p)).join('');

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

    // ── Google OAuth section (Track C — not yet available) ──
    const googleSection = isGoogleServer ? `
        <div class="p-4 rounded-xl flex items-center gap-4 mb-2"
             style="background:rgba(251,191,36,0.05);border:1px solid rgba(251,191,36,0.15)">
            <svg class="w-6 h-6 flex-shrink-0 opacity-60" viewBox="0 0 24 24" fill="none">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
            <div class="flex-1 min-w-0">
                <p class="text-sm text-yellow-200/80 font-semibold">Google Account Connection</p>
                <p class="text-xs text-gray-500 mt-0.5">Per-user Google OAuth (Gmail &amp; Calendar) is coming in a future update.</p>
            </div>
            <span class="text-[10px] px-2 py-0.5 rounded font-medium flex-shrink-0"
                  style="background:rgba(251,191,36,0.1);color:#fbbf24;border:1px solid rgba(251,191,36,0.2)">
                Coming soon
            </span>
        </div>` : '';

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

            ${googleSection}

            <!-- Two-column body -->
            <div class="grid grid-cols-1 lg:grid-cols-5 gap-6">

                <!-- Left: tools -->
                <div class="lg:col-span-2">
                    <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">
                        Available Tools
                    </h3>
                    ${toolList}

                    ${server.requires_user_auth ? `
                    <div class="mt-4 flex items-center gap-2 text-xs text-yellow-400">
                        <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                  d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"/>
                        </svg>
                        Requires user authentication
                    </div>` : ''}

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
                        Tool-level configuration is available in Profile Edit → Platform MCP Servers.
                    </p>`}
                </div>
            </div>
        </div>`;
}

function _renderDetailProfileRow(server, profile) {
    const profileId   = profile.id;
    const serverId    = server.id;
    const setting     = (_pmcpuSettings[serverId] || {})[profileId];
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
                      onchange="window.togglePlatformMcpProfileAssignment('${_esc(serverId)}', '${_esc(profileId)}', this.checked)">
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
    _pmcpuTypeFilter = value;
    _updateFilterPills('pmcp-type-filters', value);
    _renderGrid();
    const first = _filteredServers()[0];
    if (first) _selectServer(first.id);
    else _hideDetailPanel();
}

function _pmcpSetStatusFilter(value, btn) {
    _pmcpuStatusFilter = value;
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

async function togglePlatformMcpProfileAssignment(serverId, profileId, enabled) {
    const toggle = document.getElementById(`pmcp-toggle-${serverId}-${profileId}`);
    if (toggle) toggle.disabled = true;

    try {
        const resp = await fetch(
            `/api/v1/profiles/${profileId}/platform-mcp-settings/${serverId}`,
            {
                method: 'PUT',
                headers: _pmcpuHeaders(),
                body: JSON.stringify({ opted_in: enabled ? 1 : 0 }),
            }
        );
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.message || 'Update failed');
        }
        // Update local cache
        if (!_pmcpuSettings[serverId]) _pmcpuSettings[serverId] = {};
        if (!_pmcpuSettings[serverId][profileId]) _pmcpuSettings[serverId][profileId] = {};
        _pmcpuSettings[serverId][profileId].opted_in = enabled ? 1 : 0;

        _pmcpuNotify('success', `Server ${enabled ? 'enabled' : 'disabled'} for profile`);

        // Refresh the card and detail panel to reflect updated counts
        _renderGrid();
        const server = _pmcpuServers.find(s => s.id === serverId);
        if (server && _pmcpuSelectedId === serverId) _renderDetailPanel(server);

    } catch (err) {
        _pmcpuNotify('error', err.message);
        if (toggle) toggle.checked = !enabled;
    } finally {
        if (toggle) toggle.disabled = false;
    }
}

// connectGoogleAccount: implemented in Track C (Google OAuth connector)

// ── Profile Edit Modal: Platform MCP Section ───────────────────────────────────

async function loadProfilePlatformMcpSection(modal, profileId) {
    const container = modal
        ? modal.querySelector('#profile-platform-mcp-content')
        : document.getElementById('profile-platform-mcp-content');
    const navItem = modal
        ? modal.querySelector('#profile-nav-platform-mcp')
        : document.getElementById('profile-nav-platform-mcp');

    if (!container) return;
    container.innerHTML = '<div class="text-center text-gray-500 text-sm py-4">Loading…</div>';

    try {
        const [serversResp, settingsResp] = await Promise.all([
            fetch('/api/v1/platform-mcp-servers', { headers: _pmcpuHeaders(false) }),
            fetch(`/api/v1/profiles/${profileId}/platform-mcp-settings`, { headers: _pmcpuHeaders(false) }),
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
                    <p class="text-gray-500 text-xs mt-1">Go to Platform Components → MCP Servers to assign servers.</p>
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
    let availableTools   = [];
    let userTools        = [];
    try { availableTools = JSON.parse(server.available_tools || '[]'); } catch (_) {}
    try { userTools      = JSON.parse((setting.user_tools) || '[]'); } catch (_) {}

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
                       onchange="window.updateProfilePlatformMcpTools('${_esc(server.id)}')">
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

async function updateProfilePlatformMcpTools(serverId) {
    const saveBtn  = document.getElementById('profile-modal-save');
    const profileId = saveBtn ? saveBtn.dataset.profileId : null;
    if (!profileId) return;

    const checks   = document.querySelectorAll(`.pmcp-profile-tool-check[data-server-id="${serverId}"]`);
    const selected = Array.from(checks).filter(c => c.checked).map(c => c.dataset.tool);
    const allTools = Array.from(checks).map(c => c.dataset.tool);
    const userTools = selected.length === allTools.length ? null : selected;

    try {
        await fetch(
            `/api/v1/profiles/${profileId}/platform-mcp-settings/${serverId}`,
            {
                method: 'PUT',
                headers: _pmcpuHeaders(),
                body: JSON.stringify({ user_tools: userTools }),
            }
        );
    } catch (err) {
        _pmcpuNotify('error', `Could not save tool selection: ${err.message}`);
    }
}

// ── Public API ─────────────────────────────────────────────────────────────────

window.loadPlatformMcpPanel           = loadPlatformMcpPanel;
window.renderPlatformMcpPanel         = () => _renderGrid();
window.togglePlatformMcpProfileAssignment = togglePlatformMcpProfileAssignment;
window.loadProfilePlatformMcpSection  = loadProfilePlatformMcpSection;
window.updateProfilePlatformMcpTools  = updateProfilePlatformMcpTools;
window._pmcpSetTypeFilter             = _pmcpSetTypeFilter;
window._pmcpSetStatusFilter           = _pmcpSetStatusFilter;
