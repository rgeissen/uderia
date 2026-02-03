/**
 * agentPackHandler.js
 *
 * Handles agent pack install, list, uninstall, and export via the
 * /api/v1/agent-packs REST endpoints.
 *
 * Exposed on window.agentPackHandler for inline onclick handlers.
 */

// ── Helpers ──────────────────────────────────────────────────────────────────

function _headers(json = true) {
    const h = {};
    if (json) h['Content-Type'] = 'application/json';
    const token = localStorage.getItem('tda_auth_token');
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
}

function _notify(type, msg) {
    if (window.showNotification) window.showNotification(type, msg);
    else console.log(`[AgentPack] ${type}: ${msg}`);
}

// ── State ────────────────────────────────────────────────────────────────────

let installedPacks = [];

// ── Render ───────────────────────────────────────────────────────────────────

function renderAgentPacks() {
    const container = document.getElementById('agent-packs-list');
    if (!container) return;

    if (!installedPacks || installedPacks.length === 0) {
        container.innerHTML = `
            <div class="text-center py-12 text-gray-400">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-16 w-16 mx-auto mb-4 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                </svg>
                <p class="text-lg font-medium">No agent packs installed</p>
                <p class="text-sm mt-1">Click "Install" to upload an .agentpack file</p>
            </div>`;
        return;
    }

    container.innerHTML = installedPacks.map(pack => {
        const installed = pack.installed_at
            ? new Date(pack.installed_at).toLocaleDateString()
            : '';
        return `
        <div class="glass-panel rounded-lg p-5 mb-4 border border-white/5 hover:border-white/10 transition-colors">
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-1">
                        <h4 class="text-white font-semibold text-base">${_esc(pack.name)}</h4>
                        ${pack.version ? `<span class="text-xs px-2 py-0.5 rounded-full bg-white/10 text-gray-300">v${_esc(pack.version)}</span>` : ''}
                    </div>
                    ${pack.author ? `<p class="text-xs text-gray-500 mb-2">by ${_esc(pack.author)}</p>` : ''}
                    ${pack.description ? `<p class="text-sm text-gray-400 mb-3">${_esc(pack.description)}</p>` : ''}
                    <div class="flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-500">
                        <span>Coordinator: <span class="text-gray-300">@${_esc(pack.coordinator_tag)}</span></span>
                        <span>Experts: <span class="text-gray-300">${pack.experts_count ?? '?'}</span></span>
                        <span>Collections: <span class="text-gray-300">${pack.collections_count ?? '?'}</span></span>
                        ${installed ? `<span>Installed: <span class="text-gray-300">${installed}</span></span>` : ''}
                    </div>
                </div>
                <div class="flex items-center gap-2 ml-4 shrink-0">
                    <button onclick="window.agentPackHandler.handleExportAgentPack(${pack.installation_id})"
                            class="px-3 py-1.5 text-xs rounded-lg bg-white/5 text-gray-300 hover:bg-white/10 transition-colors">
                        Export
                    </button>
                    <button onclick="window.agentPackHandler.handleUninstallAgentPack(${pack.installation_id}, '${_esc(pack.name)}')"
                            class="px-3 py-1.5 text-xs rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors">
                        Uninstall
                    </button>
                </div>
            </div>
        </div>`;
    }).join('');
}

function _esc(s) {
    if (!s) return '';
    const el = document.createElement('span');
    el.textContent = s;
    return el.innerHTML;
}

// ── Load / Refresh ───────────────────────────────────────────────────────────

async function loadAgentPacks() {
    try {
        const res = await fetch('/api/v1/agent-packs', { headers: _headers(false) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        installedPacks = data.packs || [];
        renderAgentPacks();
    } catch (err) {
        console.error('[AgentPack] Failed to load packs:', err);
        installedPacks = [];
        renderAgentPacks();
    }
}

// ── Install ──────────────────────────────────────────────────────────────────

async function handleInstallAgentPack() {
    const fileInput = document.getElementById('agent-pack-file-input');
    if (!fileInput) return;

    // Reset and trigger file picker
    fileInput.value = '';
    fileInput.onchange = async () => {
        const file = fileInput.files[0];
        if (!file) return;

        // Read the ZIP to preview manifest
        let manifest = null;
        try {
            // We only need to check if requires_mcp, so try to read manifest
            // Using JSZip would be ideal, but we can also just upload and let server validate
            // For simplicity, proceed directly to upload and optionally ask for MCP
        } catch (e) { /* ignore preview errors */ }

        // Check if we need MCP server selection
        // We'll ask the user to optionally provide an MCP server ID
        let mcpServerId = null;

        // Simple approach: show a prompt if user wants to bind to an MCP server
        // In a full implementation, we'd parse the manifest first.
        // For now, ask if they have an MCP server to bind planner repos to.
        if (window.configState && window.configState.mcpServers && window.configState.mcpServers.length > 0) {
            mcpServerId = await _showMcpServerPicker();
        }

        // Upload
        const installBtn = document.getElementById('install-agent-pack-btn');
        const originalText = installBtn ? installBtn.innerHTML : '';
        if (installBtn) {
            installBtn.disabled = true;
            installBtn.innerHTML = `
                <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                Installing...`;
        }

        try {
            const formData = new FormData();
            formData.append('file', file);
            if (mcpServerId) formData.append('mcp_server_id', mcpServerId);

            const token = localStorage.getItem('tda_auth_token');
            const res = await fetch('/api/v1/agent-packs/import', {
                method: 'POST',
                headers: token ? { 'Authorization': `Bearer ${token}` } : {},
                body: formData,
            });

            const data = await res.json();
            if (!res.ok || data.status === 'error') {
                throw new Error(data.message || `Import failed (${res.status})`);
            }

            _notify('success', `Agent pack installed: ${data.name || 'Unknown'} (${data.experts_created} experts, ${data.collections_created} collections)`);
            await loadAgentPacks();
        } catch (err) {
            _notify('error', `Install failed: ${err.message}`);
        } finally {
            if (installBtn) {
                installBtn.disabled = false;
                installBtn.innerHTML = originalText;
            }
        }
    };
    fileInput.click();
}

// ── MCP Server Picker (simple modal) ────────────────────────────────────────

function _showMcpServerPicker() {
    return new Promise((resolve) => {
        const servers = window.configState?.mcpServers || [];
        if (servers.length === 0) { resolve(null); return; }

        // Build options HTML
        const optionsHtml = servers.map(s =>
            `<option value="${_esc(s.id)}">${_esc(s.name || s.id)}</option>`
        ).join('');

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[10000]';
        overlay.innerHTML = `
            <div class="glass-panel rounded-xl p-6 w-full max-w-md border border-white/10 shadow-2xl">
                <h3 class="text-lg font-bold text-white mb-2">MCP Server Binding</h3>
                <p class="text-sm text-gray-400 mb-4">If this agent pack contains tool-enabled profiles or planner repositories, select which MCP server to bind them to. Leave as "None" if not applicable.</p>
                <select id="mcp-server-picker-select" class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm mb-4 focus:outline-none focus:border-blue-500">
                    <option value="">None (skip MCP binding)</option>
                    ${optionsHtml}
                </select>
                <div class="flex justify-end gap-3">
                    <button id="mcp-picker-cancel" class="px-4 py-2 text-sm rounded-lg bg-white/5 text-gray-300 hover:bg-white/10 transition-colors">Cancel</button>
                    <button id="mcp-picker-confirm" class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors">Continue</button>
                </div>
            </div>`;

        document.body.appendChild(overlay);

        overlay.querySelector('#mcp-picker-cancel').onclick = () => {
            overlay.remove();
            resolve(null);
        };
        overlay.querySelector('#mcp-picker-confirm').onclick = () => {
            const val = overlay.querySelector('#mcp-server-picker-select').value || null;
            overlay.remove();
            resolve(val);
        };
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) { overlay.remove(); resolve(null); }
        });
    });
}

// ── Export ────────────────────────────────────────────────────────────────────

async function handleExportAgentPack(installationId) {
    try {
        // First get pack details to find coordinator_profile_id
        const detailRes = await fetch(`/api/v1/agent-packs/${installationId}`, { headers: _headers(false) });
        if (!detailRes.ok) throw new Error(`Failed to get pack details (${detailRes.status})`);
        const detail = await detailRes.json();
        const coordProfileId = detail.coordinator_profile_id;
        if (!coordProfileId) throw new Error('No coordinator profile found for this pack');

        _notify('info', 'Exporting agent pack...');

        const res = await fetch('/api/v1/agent-packs/export', {
            method: 'POST',
            headers: _headers(true),
            body: JSON.stringify({ coordinator_profile_id: coordProfileId }),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.message || `Export failed (${res.status})`);
        }

        // Trigger download
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `agent_pack_${installationId}.agentpack`;
        // Try to extract filename from content-disposition
        const cd = res.headers.get('content-disposition');
        if (cd) {
            const match = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
            if (match) a.download = match[1].replace(/['"]/g, '');
        }
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        _notify('success', 'Agent pack exported successfully');
    } catch (err) {
        _notify('error', `Export failed: ${err.message}`);
    }
}

// ── Uninstall ────────────────────────────────────────────────────────────────

async function handleUninstallAgentPack(installationId, packName) {
    const doUninstall = async () => {
        try {
            _notify('info', 'Uninstalling agent pack...');
            const res = await fetch(`/api/v1/agent-packs/${installationId}`, {
                method: 'DELETE',
                headers: _headers(false),
            });
            const data = await res.json();
            if (!res.ok || data.status === 'error') {
                throw new Error(data.message || `Uninstall failed (${res.status})`);
            }
            _notify('success', `Agent pack uninstalled (${data.profiles_deleted} profiles, ${data.collections_deleted} collections removed)`);
            await loadAgentPacks();
        } catch (err) {
            _notify('error', `Uninstall failed: ${err.message}`);
        }
    };

    if (window.showConfirmation) {
        window.showConfirmation(
            'Uninstall Agent Pack',
            `Are you sure you want to uninstall <strong>${_esc(packName)}</strong>? This will permanently delete all profiles and collections created by this pack.`,
            doUninstall
        );
    } else {
        if (confirm(`Uninstall "${packName}"? This will delete all profiles and collections.`)) {
            await doUninstall();
        }
    }
}

// ── Public API ───────────────────────────────────────────────────────────────

window.agentPackHandler = {
    loadAgentPacks,
    renderAgentPacks,
    handleInstallAgentPack,
    handleExportAgentPack,
    handleUninstallAgentPack,
};

export {
    loadAgentPacks,
    renderAgentPacks,
    handleInstallAgentPack,
    handleExportAgentPack,
    handleUninstallAgentPack,
};
