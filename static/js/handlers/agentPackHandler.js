/**
 * agentPackHandler.js
 *
 * Handles agent pack install, create, list, uninstall, and export via the
 * /api/v1/agent-packs REST endpoints.
 *
 * Exposed on window.agentPackHandler for inline onclick handlers.
 */

import { configState, renderProfiles } from './configurationHandler.js';
import { loadKnowledgeRepositories } from './knowledgeRepositoryHandler.js';

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

// ── Profile type display config ──────────────────────────────────────────────

const PROFILE_CLASS_CONFIG = {
    genie:        { label: 'Coordinator', color: '#F15F22', bgClass: 'bg-orange-500/10', textClass: 'text-orange-400' },
    tool_enabled: { label: 'Optimizer',   color: '#9333ea', bgClass: 'bg-purple-500/10', textClass: 'text-purple-400' },
    rag_focused:  { label: 'Knowledge',   color: '#3b82f6', bgClass: 'bg-blue-500/10',   textClass: 'text-blue-400'   },
    llm_only:     { label: 'Conversation',color: '#4ade80', bgClass: 'bg-green-500/10',  textClass: 'text-green-400'  },
};

const PACK_TYPE_BADGES = {
    genie:  { label: 'Coordinator', bgClass: 'bg-orange-500/15', textClass: 'text-orange-400' },
    bundle: { label: 'Bundle',      bgClass: 'bg-purple-500/15', textClass: 'text-purple-400' },
    single: { label: 'Single',      bgClass: 'bg-blue-500/15',   textClass: 'text-blue-400'   },
};

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
                <p class="text-sm mt-1">Click "Install" to upload an .agentpack file or "Create" to build one from your profiles</p>
            </div>`;
        return;
    }

    container.innerHTML = installedPacks.map(pack => {
        const installed = pack.installed_at
            ? new Date(pack.installed_at).toLocaleDateString()
            : '';

        const packType = pack.pack_type || 'genie';
        const badge = PACK_TYPE_BADGES[packType] || PACK_TYPE_BADGES.genie;
        const isOwned = pack.is_owned !== false;

        // Info line: show coordinator for genie packs, profile count for others
        let infoItems = '';
        if (pack.coordinator_tag) {
            infoItems += `<span>Coordinator: <span class="text-gray-300">@${_esc(pack.coordinator_tag)}</span></span>`;
        }
        if (packType === 'genie' && pack.experts_count != null) {
            infoItems += `<span>Experts: <span class="text-gray-300">${pack.experts_count}</span></span>`;
        } else if (pack.profiles_count != null) {
            infoItems += `<span>Profiles: <span class="text-gray-300">${pack.profiles_count}</span></span>`;
        }
        infoItems += `<span>Collections: <span class="text-gray-300">${pack.collections_count ?? '?'}</span></span>`;
        if (installed) {
            infoItems += `<span>Installed: <span class="text-gray-300">${installed}</span></span>`;
        }

        // Action buttons differ for owned vs subscribed packs
        let actionButtons = '';
        if (isOwned) {
            actionButtons = `
                    <button onclick="window.agentPackHandler.handleExportAgentPack(${pack.installation_id})"
                            class="card-btn card-btn--sm card-btn--cyan">
                        Export
                    </button>
                    ${pack.marketplace_pack_id
                        ? `<span class="px-3 py-1.5 text-xs rounded-lg bg-green-500/10 text-green-400 flex items-center gap-1">
                               <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                               Published (${pack.marketplace_visibility === 'targeted' ? 'Targeted' : 'Public'})
                           </span>
                           <button onclick="window.agentPackHandler.openPublishPackModal(${pack.installation_id}, '${_esc(pack.name)}')"
                                   class="card-btn card-btn--sm card-btn--neutral">
                               Edit
                           </button>
                           <button onclick="window.agentPackHandler.handleUnpublishFromMyAssets('${pack.marketplace_pack_id}')"
                                   class="card-btn card-btn--sm card-btn--secondary">
                               Unpublish
                           </button>`
                        : `<button onclick="window.agentPackHandler.openPublishPackModal(${pack.installation_id}, '${_esc(pack.name)}')"
                                  class="card-btn card-btn--sm card-btn--success">
                              Publish
                          </button>`
                    }
                    <button onclick="window.agentPackHandler.handleUninstallAgentPack(${pack.installation_id}, '${_esc(pack.name)}')"
                            class="card-btn card-btn--sm card-btn--danger">
                        Uninstall
                    </button>`;
        } else {
            // Subscribed pack — limited actions
            actionButtons = `
                    <span class="px-3 py-1.5 text-xs rounded-lg flex items-center gap-1" style="background:#4f46e5;color:#fff;">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>
                        Subscribed
                    </span>
                    ${pack.marketplace_pack_id
                        ? `<button onclick="window.agentPackHandler.handleUnsubscribeAgentPack('${pack.marketplace_pack_id}', '${_esc(pack.name)}')"
                                  class="card-btn card-btn--sm card-btn--warning">
                              Unsubscribe
                          </button>`
                        : ''
                    }`;
        }

        return `
        <div class="glass-panel rounded-lg p-5 mb-4 border border-white/5 hover:border-white/10 transition-colors">
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-1">
                        <h4 class="text-white font-semibold text-base">${_esc(pack.name)}</h4>
                        ${pack.version ? `<span class="text-xs px-2 py-0.5 rounded-full bg-white/10 text-gray-300">v${_esc(pack.version)}</span>` : ''}
                        <span class="text-xs px-2 py-0.5 rounded-full ${badge.bgClass} ${badge.textClass}">${badge.label}</span>
                    </div>
                    ${pack.author ? `<p class="text-xs text-gray-500 mb-2">by ${_esc(pack.author)}</p>` : ''}
                    ${pack.description ? `<p class="text-sm text-gray-400 mb-3">${_esc(pack.description)}</p>` : ''}
                    <div class="flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-500">
                        ${infoItems}
                    </div>
                </div>
                <div class="flex items-center gap-2 ml-4 shrink-0">
                    ${actionButtons}
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

    // iOS/iPadOS doesn't recognise custom extensions like .agentpack
    // (no UTI mapping), so the file picker greys them out.  Remove the
    // accept filter on touch devices; JSZip validation catches bad files.
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
                  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    if (isIOS) {
        fileInput.removeAttribute('accept');
    } else {
        fileInput.setAttribute('accept', '.agentpack,.zip');
    }

    fileInput.onchange = async () => {
        const file = fileInput.files[0];
        if (!file) return;

        // Read the ZIP client-side to check if any expert requires MCP
        let manifest = null;
        let requiresMcp = false;
        try {
            if (typeof JSZip !== 'undefined') {
                const zip = await JSZip.loadAsync(file);
                const manifestEntry = zip.file('manifest.json');
                if (manifestEntry) {
                    manifest = JSON.parse(await manifestEntry.async('text'));
                    // Check both v1.0 (experts) and v1.1 (profiles) formats
                    const profiles = manifest.profiles || manifest.experts || [];
                    requiresMcp = profiles.some(e => e.requires_mcp === true);
                }
            }
        } catch (e) {
            // If we can't read the ZIP client-side, fall back to always asking
            requiresMcp = true;
        }

        // Only show MCP picker if the pack actually needs it AND servers are available
        let mcpServerId = null;
        if (requiresMcp && window.configState?.mcpServers?.length > 0) {
            mcpServerId = await _showMcpServerPicker();
        }

        // ALWAYS show LLM config picker
        const llmConfigId = await _showLlmConfigPicker();
        if (!llmConfigId) {
            // User cancelled or prerequisite error (no default profile / no LLM configs)
            return;
        }

        // Check for tag conflicts client-side
        let conflictStrategy = null;
        if (manifest) {
            const packProfiles = manifest.profiles || manifest.experts || [];
            const packTags = packProfiles.map(p => p.tag).filter(Boolean);
            const existingTags = new Set(
                (configState.profiles || []).map(p => p.tag).filter(Boolean)
            );
            const conflicting = packTags.filter(t => existingTags.has(t));

            if (conflicting.length > 0) {
                conflictStrategy = await _showTagConflictDialog(conflicting);
                if (conflictStrategy === null) return; // User cancelled
            }
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
            formData.append('llm_configuration_id', llmConfigId);
            if (conflictStrategy) formData.append('conflict_strategy', conflictStrategy);

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

            let successMsg = `Agent pack installed: ${data.name || 'Unknown'} (${data.profiles_created || data.experts_created || 0} profiles, ${data.collections_created} collections)`;
            if (data.tag_remap && Object.keys(data.tag_remap).length > 0) {
                const remapList = Object.entries(data.tag_remap)
                    .map(([old, nw]) => `@${old} → @${nw}`)
                    .join(', ');
                successMsg += ` | Tags renamed: ${remapList}`;
            }
            _notify('success', successMsg);
            await loadAgentPacks();
            // Refresh profiles and knowledge repositories so new resources appear immediately
            await configState.loadProfiles();
            renderProfiles();
            loadKnowledgeRepositories();
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
                    <button id="mcp-picker-confirm" class="card-btn card-btn--info">Continue</button>
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

// ── LLM Configuration Picker (mandatory modal) ──────────────────────────────

function _showLlmConfigPicker() {
    return new Promise((resolve) => {
        const llmConfigs = window.configState?.llmConfigurations || [];

        // Guard: no LLM configurations at all
        if (llmConfigs.length === 0) {
            _notify('error', 'No LLM configurations available. Please add one in Setup first.');
            resolve(null);
            return;
        }

        // Guard: no default profile set
        const defaultProfileId = window.configState?.defaultProfileId;
        if (!defaultProfileId) {
            _notify('error', 'No default profile is set. Please set a default profile in Setup → Profiles before importing an agent pack.');
            resolve(null);
            return;
        }

        // Determine default selection from the default profile's LLM config
        const defaultProfile = (window.configState?.profiles || []).find(p => p.id === defaultProfileId);
        const defaultLlmConfigId = defaultProfile?.llmConfigurationId || '';

        // Build options HTML with provider + model info
        const optionsHtml = llmConfigs.map(c => {
            const selected = c.id === defaultLlmConfigId ? 'selected' : '';
            const label = `${_esc(c.name)} (${_esc(c.provider)} / ${_esc(c.model)})`;
            return `<option value="${_esc(c.id)}" ${selected}>${label}</option>`;
        }).join('');

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[10000]';
        overlay.innerHTML = `
            <div class="glass-panel rounded-xl p-6 w-full max-w-md border border-white/10 shadow-2xl">
                <h3 class="text-lg font-bold text-white mb-2">LLM Configuration</h3>
                <p class="text-sm text-gray-400 mb-4">Select which LLM configuration to use for all profiles created by this agent pack.</p>
                <select id="llm-config-picker-select" class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm mb-4 focus:outline-none focus:border-blue-500">
                    ${optionsHtml}
                </select>
                <div class="flex justify-end gap-3">
                    <button id="llm-picker-cancel" class="px-4 py-2 text-sm rounded-lg bg-white/5 text-gray-300 hover:bg-white/10 transition-colors">Cancel</button>
                    <button id="llm-picker-confirm" class="card-btn card-btn--info">Continue</button>
                </div>
            </div>`;

        document.body.appendChild(overlay);

        overlay.querySelector('#llm-picker-cancel').onclick = () => {
            overlay.remove();
            resolve(null);
        };
        overlay.querySelector('#llm-picker-confirm').onclick = () => {
            const val = overlay.querySelector('#llm-config-picker-select').value || null;
            overlay.remove();
            resolve(val);
        };
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) { overlay.remove(); resolve(null); }
        });
    });
}

// ── Tag Conflict Dialog ──────────────────────────────────────────────────────

function _showTagConflictDialog(conflictingTags) {
    return new Promise((resolve) => {
        const tagList = conflictingTags
            .map(t => `<span class="inline-block px-2 py-0.5 rounded bg-red-500/15 text-red-300 text-xs font-mono mr-1 mb-1">@${_esc(t)}</span>`)
            .join('');

        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[10000]';
        overlay.innerHTML = `
            <div class="glass-panel rounded-xl p-6 w-full max-w-lg border border-white/10 shadow-2xl">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-10 h-10 rounded-full bg-amber-500/15 flex items-center justify-center shrink-0">
                        <svg class="w-5 h-5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round"
                                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667
                                     1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34
                                     16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                    </div>
                    <h3 class="text-lg font-bold text-white">Tag Conflict</h3>
                </div>

                <p class="text-sm text-gray-400 mb-3">
                    The following tags in this agent pack already exist in your profiles:
                </p>
                <div class="mb-4">${tagList}</div>

                <p class="text-sm text-gray-400 mb-5">How would you like to proceed?</p>

                <div class="space-y-2 mb-5">
                    <button id="conflict-replace-btn"
                            class="w-full text-left px-4 py-3 rounded-lg border border-white/10
                                   hover:border-red-500/30 hover:bg-red-500/5 transition-colors group">
                        <div class="text-sm font-medium text-white group-hover:text-red-300">Replace Existing</div>
                        <div class="text-xs text-gray-500 mt-0.5">Delete the existing profiles with these tags and import the new ones</div>
                    </button>

                    <button id="conflict-expand-btn"
                            class="w-full text-left px-4 py-3 rounded-lg border border-white/10
                                   hover:border-blue-500/30 hover:bg-blue-500/5 transition-colors group">
                        <div class="text-sm font-medium text-white group-hover:text-blue-300">Expand Tags</div>
                        <div class="text-xs text-gray-500 mt-0.5">Auto-rename conflicting tags (e.g. @${_esc(conflictingTags[0])} → @${_esc(conflictingTags[0])}2) and update all references</div>
                    </button>
                </div>

                <div class="flex justify-end">
                    <button id="conflict-cancel-btn"
                            class="px-4 py-2 text-sm rounded-lg bg-white/5 text-gray-300
                                   hover:bg-white/10 transition-colors">Cancel</button>
                </div>
            </div>`;

        document.body.appendChild(overlay);

        overlay.querySelector('#conflict-replace-btn').onclick = () => {
            overlay.remove();
            resolve('replace');
        };
        overlay.querySelector('#conflict-expand-btn').onclick = () => {
            overlay.remove();
            resolve('expand');
        };
        overlay.querySelector('#conflict-cancel-btn').onclick = () => {
            overlay.remove();
            resolve(null);
        };
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) { overlay.remove(); resolve(null); }
        });
    });
}

// ── Create Agent Pack ───────────────────────────────────────────────────────

async function handleCreateAgentPack() {
    const profiles = window.configState?.profiles || [];
    if (profiles.length === 0) {
        _notify('error', 'No profiles available. Create at least one profile first.');
        return;
    }

    const result = await _showCreatePackModal(profiles);
    if (!result) return; // Cancelled

    const createBtn = document.getElementById('create-agent-pack-btn');
    const originalText = createBtn ? createBtn.innerHTML : '';
    if (createBtn) {
        createBtn.disabled = true;
        createBtn.innerHTML = `
            <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            Creating...`;
    }

    try {
        const res = await fetch('/api/v1/agent-packs/create', {
            method: 'POST',
            headers: _headers(true),
            body: JSON.stringify({
                profile_ids: result.profileIds,
                name: result.name,
                description: result.description,
            }),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.message || `Create failed (${res.status})`);
        }

        // Trigger download
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${result.name.replace(/\s+/g, '_')}.agentpack`;
        const cd = res.headers.get('content-disposition');
        if (cd) {
            const match = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
            if (match) a.download = match[1].replace(/['"]/g, '');
        }
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        _notify('success', `Agent pack "${result.name}" created and downloaded`);
    } catch (err) {
        _notify('error', `Create failed: ${err.message}`);
    } finally {
        if (createBtn) {
            createBtn.disabled = false;
            createBtn.innerHTML = originalText;
        }
    }
}

// ── Fetch Collections (for summary display) ─────────────────────────────────

async function _fetchCollections() {
    try {
        const res = await fetch('/api/v1/rag/collections', { headers: _headers(false) });
        if (!res.ok) return [];
        const data = await res.json();
        return data.collections || [];
    } catch { return []; }
}

// ── Create Pack Modal ────────────────────────────────────────────────────────

async function _showCreatePackModal(profiles) {
    // Fetch all collections once so we can resolve planner IDs to names
    const allCollections = await _fetchCollections();

    return new Promise((resolve) => {
        // Group profiles by profile_type
        const groups = {};
        for (const p of profiles) {
            const pt = p.profile_type || 'llm_only';
            if (!groups[pt]) groups[pt] = [];
            groups[pt].push(p);
        }

        const groupOrder = ['genie', 'tool_enabled', 'rag_focused', 'llm_only'];
        const activeClasses = groupOrder.filter(pt => groups[pt]?.length > 0);
        const initialClass = activeClasses[0] || 'llm_only';

        // Build lookup for child resolution
        const profileById = {};
        for (const p of profiles) { profileById[p.id] = p; }

        // Track selections across tab switches
        const selectedIds = new Set();
        let activeClass = initialClass;

        // Build class tab HTML
        const tabsHtml = activeClasses.map((pt, i) => {
            const cfg = PROFILE_CLASS_CONFIG[pt] || PROFILE_CLASS_CONFIG.llm_only;
            const total = groups[pt].length;
            return `
                <button data-class="${pt}"
                        class="create-pack-class-tab w-full flex items-center gap-2.5 px-4 py-3.5 text-left transition-colors border-l-2 ${i === 0 ? 'bg-white/10 border-white/40' : 'border-transparent hover:bg-white/5'}">
                    <div class="w-2.5 h-2.5 rounded-full shrink-0" style="background: ${cfg.color}"></div>
                    <span class="create-pack-tab-label text-sm font-medium ${i === 0 ? 'text-white' : 'text-gray-400'}">${cfg.label}</span>
                    <span class="text-xs text-gray-600 ml-0.5">(${total})</span>
                    <span class="ml-auto text-xs px-1.5 py-0.5 rounded-full bg-white/10 text-gray-500 create-pack-count-badge" data-class="${pt}">0</span>
                </button>`;
        }).join('');

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[10000]';
        overlay.innerHTML = `
            <div class="glass-panel rounded-xl p-6 w-full max-w-2xl border border-white/10 shadow-2xl max-h-[85vh] flex flex-col">
                <h3 class="text-lg font-bold text-white mb-4">Create Agent Pack</h3>

                <div class="space-y-4 flex-1 flex flex-col" style="min-height: 0;">
                    <!-- Name + Description row -->
                    <div class="flex gap-4">
                        <div class="flex-1">
                            <label class="block text-sm font-medium text-gray-300 mb-1">Pack Name <span class="text-red-400">*</span></label>
                            <input id="create-pack-name" type="text" placeholder="My Agent Pack"
                                   class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-blue-500" />
                        </div>
                        <div class="flex-1">
                            <label class="block text-sm font-medium text-gray-300 mb-1">Description</label>
                            <input id="create-pack-desc" type="text" placeholder="Optional description"
                                   class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-blue-500" />
                        </div>
                    </div>

                    <!-- Two-panel profile selection -->
                    <div class="flex-1 flex flex-col" style="min-height: 0;">
                        <label class="block text-sm font-medium text-gray-300 mb-2">Select Profiles</label>
                        <div class="flex rounded-lg border border-white/10 bg-white/[0.02] overflow-hidden flex-1" style="min-height: 200px; max-height: 320px;">
                            <!-- Left: class tabs -->
                            <div id="create-pack-class-tabs" class="w-52 shrink-0 border-r border-white/10 overflow-y-auto">
                                ${tabsHtml}
                            </div>
                            <!-- Right: profiles for selected class -->
                            <div id="create-pack-profile-list" class="flex-1 overflow-y-auto p-2"></div>
                        </div>
                    </div>

                    <!-- Summary strip -->
                    <div id="create-pack-summary" class="rounded-lg border border-white/10 bg-white/[0.02] px-4 py-2.5">
                        <div id="create-pack-summary-content" class="text-xs text-gray-500">No profiles selected</div>
                    </div>
                </div>

                <div class="flex justify-end gap-3 mt-4 pt-4 border-t border-white/5">
                    <button id="create-pack-cancel" class="px-4 py-2 text-sm rounded-lg bg-white/5 text-gray-300 hover:bg-white/10 transition-colors">Cancel</button>
                    <button id="create-pack-confirm" disabled
                            class="card-btn card-btn--neutral disabled:opacity-40 disabled:cursor-not-allowed">
                        Create
                    </button>
                </div>
            </div>`;

        document.body.appendChild(overlay);

        const nameInput = overlay.querySelector('#create-pack-name');
        const confirmBtn = overlay.querySelector('#create-pack-confirm');
        const profileListDiv = overlay.querySelector('#create-pack-profile-list');
        const summaryContent = overlay.querySelector('#create-pack-summary-content');
        const classTabs = overlay.querySelectorAll('.create-pack-class-tab');

        // Render profiles for a given class into the right panel (clickable cards)
        function renderProfileList(pt) {
            const grp = groups[pt] || [];
            const cfg = PROFILE_CLASS_CONFIG[pt] || PROFILE_CLASS_CONFIG.llm_only;

            if (grp.length === 0) {
                profileListDiv.innerHTML = `<div class="text-sm text-gray-500 py-8 text-center">No profiles in this class</div>`;
                return;
            }

            profileListDiv.innerHTML = grp.map(p => {
                const isSelected = selectedIds.has(p.id);
                return `
                    <div data-profile-id="${_esc(p.id)}" data-tag="${_esc(p.tag)}" data-type="${_esc(pt)}"
                         class="create-pack-profile-card flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-all"
                         style="border-left: 3px solid ${isSelected ? cfg.color : 'transparent'}; ${isSelected ? `background: ${cfg.color}10` : ''}">
                        <div class="flex-1 min-w-0">
                            <div class="text-sm ${isSelected ? 'text-white' : 'text-gray-300'}">
                                <span class="${isSelected ? 'text-gray-200' : 'text-gray-400'}">@${_esc(p.tag)}</span>
                                <span class="ml-1.5">${_esc(p.name || p.tag)}</span>
                            </div>
                            ${p.description ? `<div class="text-xs text-gray-500 mt-0.5 truncate">${_esc(p.description)}</div>` : ''}
                        </div>
                        ${isSelected ? `
                            <svg class="w-4 h-4 shrink-0" style="color: ${cfg.color}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                        ` : ''}
                    </div>`;
            }).join('');

            // Click handlers — toggle selection on card click
            profileListDiv.querySelectorAll('.create-pack-profile-card').forEach(card => {
                card.addEventListener('click', () => {
                    const pid = card.dataset.profileId;
                    if (selectedIds.has(pid)) selectedIds.delete(pid);
                    else selectedIds.add(pid);
                    renderProfileList(activeClass);
                    updateState();
                });
            });
        }

        // Switch active class tab
        function setActiveTab(pt) {
            activeClass = pt;
            classTabs.forEach(tab => {
                const isActive = tab.dataset.class === pt;
                tab.classList.toggle('bg-white/10', isActive);
                tab.classList.toggle('border-white/40', isActive);
                tab.classList.toggle('border-transparent', !isActive);
                tab.classList.toggle('hover:bg-white/5', !isActive);
                const label = tab.querySelector('.create-pack-tab-label');
                if (label) {
                    label.classList.toggle('text-white', isActive);
                    label.classList.toggle('text-gray-400', !isActive);
                }
            });
            renderProfileList(pt);
        }

        // Update badges, summary, and confirm button state
        function updateState() {
            const name = (nameInput.value || '').trim();
            confirmBtn.disabled = !name || selectedIds.size === 0;

            // Update count badges on each tab
            for (const pt of activeClasses) {
                const badge = overlay.querySelector(`.create-pack-count-badge[data-class="${pt}"]`);
                if (!badge) continue;
                const count = (groups[pt] || []).filter(p => selectedIds.has(p.id)).length;
                badge.textContent = count;
                badge.classList.toggle('bg-blue-500/20', count > 0);
                badge.classList.toggle('text-blue-400', count > 0);
                badge.classList.toggle('bg-white/10', count === 0);
                badge.classList.toggle('text-gray-500', count === 0);
            }

            // Calculate auto-includes
            const autoChildren = [];
            const allIds = new Set(selectedIds);

            for (const id of selectedIds) {
                const prof = profileById[id];
                if (!prof || prof.profile_type !== 'genie') continue;
                const childIds = prof.genieConfig?.slaveProfiles || [];
                for (const cid of childIds) {
                    if (!selectedIds.has(cid)) {
                        const child = profileById[cid];
                        if (child) {
                            autoChildren.push(`@${child.tag}`);
                            allIds.add(cid);
                        }
                    }
                }
            }

            // Collect knowledge and planner repository names
            const knowledgeRepos = new Set();
            const plannerRepos = new Set();
            for (const id of allIds) {
                const prof = profileById[id];
                if (!prof) continue;
                // Knowledge collections (objects with name)
                const kCollections = prof.knowledgeConfig?.collections || [];
                for (const kc of kCollections) {
                    if (kc.name) knowledgeRepos.add(kc.name);
                }
                // Planner collections (integer IDs — resolve to name)
                const plannerIds = prof.ragCollections || [];
                for (const pid of plannerIds) {
                    if (pid === '*') continue;
                    const coll = allCollections.find(c => c.id === pid);
                    if (coll) plannerRepos.add(coll.name || `Collection ${pid}`);
                }
            }

            // Build summary
            if (selectedIds.size === 0) {
                summaryContent.innerHTML = 'No profiles selected';
                return;
            }

            // Line 1: profile count + auto-includes
            let line1 = `<span class="text-gray-300 font-medium">${selectedIds.size}</span> profile${selectedIds.size !== 1 ? 's' : ''} selected`;
            if (autoChildren.length > 0) {
                line1 += ` &middot; <span class="text-gray-300 font-medium">+${autoChildren.length}</span> auto-included (${autoChildren.join(', ')})`;
            }

            // Line 2: repository names with color-coded dots
            const repoItems = [];
            for (const name of knowledgeRepos) repoItems.push(`<span class="text-blue-400">&#9679;</span> ${_esc(name)}`);
            for (const name of plannerRepos) repoItems.push(`<span class="text-purple-400">&#9679;</span> ${_esc(name)}`);

            if (repoItems.length > 0) {
                summaryContent.innerHTML = `
                    <div>${line1}</div>
                    <div class="mt-1 flex flex-wrap gap-x-4 gap-y-0.5">
                        ${repoItems.map(r => `<span>${r}</span>`).join('')}
                    </div>`;
            } else {
                summaryContent.innerHTML = line1;
            }
        }

        // Event listeners
        classTabs.forEach(tab => {
            tab.addEventListener('click', () => setActiveTab(tab.dataset.class));
        });
        nameInput.addEventListener('input', updateState);

        // Initial render
        setActiveTab(initialClass);
        updateState();

        // Cancel / close
        overlay.querySelector('#create-pack-cancel').onclick = () => {
            overlay.remove();
            resolve(null);
        };
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) { overlay.remove(); resolve(null); }
        });

        // Confirm
        confirmBtn.onclick = () => {
            const name = (nameInput.value || '').trim();
            const description = (overlay.querySelector('#create-pack-desc').value || '').trim();
            overlay.remove();
            resolve({ profileIds: Array.from(selectedIds), name, description });
        };

        // Focus name input
        setTimeout(() => nameInput.focus(), 100);
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

            // Show sessions archived notification if any
            const successMsg = data.sessions_archived > 0
                ? `Agent pack uninstalled (${data.profiles_deleted} profiles, ${data.collections_deleted} collections removed, ${data.sessions_archived} sessions archived)`
                : `Agent pack uninstalled (${data.profiles_deleted} profiles, ${data.collections_deleted} collections removed)`;

            _notify('success', successMsg);

            // Refresh sessions list if sessions were archived
            if (data.sessions_archived && data.sessions_archived > 0) {
                try {
                    // Auto-disable toggle (user uninstalled pack = cleanup intent)
                    const toggle = document.getElementById('sidebar-show-archived-sessions-toggle');
                    if (toggle && toggle.checked) {
                        toggle.checked = false;
                        localStorage.setItem('sidebarShowArchivedSessions', 'false');
                        console.log('[Agent Pack Uninstall] Auto-disabled "Show Archived" toggle');
                    }

                    // Full refresh: fetch + re-render + apply filters
                    const { refreshSessionsList } = await import('./configManagement.js');
                    await refreshSessionsList();

                    console.log('[Agent Pack Uninstall] Session list refreshed after archiving', data.sessions_archived, 'sessions');
                } catch (error) {
                    console.error('[Agent Pack Uninstall] Failed to refresh sessions:', error);
                    // Non-fatal: pack uninstalled successfully, just UI refresh failed
                }
            }

            await loadAgentPacks();
            // Refresh profiles and knowledge repositories so removed resources disappear immediately
            await configState.loadProfiles();
            renderProfiles();
            loadKnowledgeRepositories();
        } catch (err) {
            _notify('error', `Uninstall failed: ${err.message}`);
        }
    };

    // Check for active sessions before showing confirmation
    try {
        // MIGRATED: Use unified relationships endpoint instead of old check-sessions
        const checkRes = await fetch(`/api/v1/artifacts/agent-pack/${installationId}/relationships`, {
            headers: _headers(false),
        });
        const checkData = await checkRes.json();

        let message = `Are you sure you want to uninstall <strong>${_esc(packName)}</strong>? This will permanently delete all profiles and collections created by this pack.`;

        // Extract data from unified endpoint response structure
        const deletionInfo = checkData.deletion_info || {};
        const blockers = deletionInfo.blockers || [];
        const warnings = deletionInfo.warnings || [];
        const sessions = checkData.relationships?.sessions || {};
        const activeCount = sessions.active_count || 0;

        // Show blockers (prevent deletion)
        if (blockers.length > 0) {
            const blockerMessages = blockers
                .map(b => `• ${_esc(b.message || b)}`)
                .join('<br>');
            message += `<br><br><span style="color: #ef4444; font-weight: 600;">🚫 Cannot Uninstall:</span><br><span style="font-size: 0.9em;">${blockerMessages}</span>`;

            if (window.showConfirmation) {
                window.showConfirmation('Cannot Uninstall Agent Pack', message, null);
            } else {
                alert(message.replace(/<[^>]*>/g, ''));  // Strip HTML for fallback alert
            }
            return;
        }

        // Add dynamic warning if active sessions exist
        if (activeCount > 0) {
            const sessionWord = activeCount === 1 ? 'session' : 'sessions';
            message += `<br><br><span style="color: #f59e0b; font-weight: 600;">⚠️ Warning: ${activeCount} active ${sessionWord} will be archived.</span>`;

            // Show sample session names
            if (sessions.items && sessions.items.length > 0) {
                const activeSessions = sessions.items.filter(s => !s.is_archived);
                if (activeSessions.length > 0) {
                    const sessionNames = activeSessions
                        .map(s => `• ${_esc(s.session_name)}`)
                        .join('<br>');
                    message += `<br><br><span style="font-size: 0.9em;">Affected sessions:<br>${sessionNames}</span>`;

                    if (activeCount > activeSessions.length) {
                        message += `<br><span style="font-size: 0.9em; color: #9ca3af;">...and ${activeCount - activeSessions.length} more</span>`;
                    }
                }
            }
        }

        // Show additional warnings from deletion analysis
        if (warnings.length > 0) {
            const warningMessages = warnings
                .filter(w => !w.toLowerCase().includes('session'))  // Skip session warnings (already shown above)
                .map(w => `• ${_esc(w)}`)
                .join('<br>');
            if (warningMessages) {
                message += `<br><br><span style="color: #f59e0b; font-weight: 600;">⚠️ Additional Warnings:</span><br><span style="font-size: 0.9em;">${warningMessages}</span>`;
            }
        }

        if (window.showConfirmation) {
            window.showConfirmation('Uninstall Agent Pack', message, doUninstall);
        } else {
            if (confirm(`Uninstall "${packName}"? This will delete all profiles and collections.`)) {
                await doUninstall();
            }
        }
    } catch (err) {
        // Fallback to basic confirmation if check fails
        console.error('Failed to check active sessions:', err);
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
}

// ── Publish to Marketplace ────────────────────────────────────────────────────

let _publishPackModalInitialized = false;
let _packExistingTargetedUsers = [];  // Existing targeted users loaded on modal open

/**
 * Initialize the static publish pack modal (call once at startup).
 */
function initializePublishPackModal() {
    if (_publishPackModalInitialized) return;
    _publishPackModalInitialized = true;

    const modal = document.getElementById('publish-pack-modal-overlay');
    const closeBtn = document.getElementById('publish-pack-modal-close');
    const cancelBtn = document.getElementById('publish-pack-cancel');
    const form = document.getElementById('publish-pack-form');

    if (closeBtn) closeBtn.addEventListener('click', () => closePublishPackModal());
    if (cancelBtn) cancelBtn.addEventListener('click', () => closePublishPackModal());

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            await _handlePublishPack();
        });
    }

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closePublishPackModal();
        });
    }

    // Visibility change handler — show/hide user picker section + update button text
    const visibilitySelect = document.getElementById('publish-pack-visibility');
    if (visibilitySelect) {
        visibilitySelect.addEventListener('change', () => {
            const section = document.getElementById('publish-pack-users-section');
            if (!section) return;
            if (visibilitySelect.value === 'targeted') {
                section.classList.remove('hidden');
                _loadPackShareableUsers('');
            } else {
                section.classList.add('hidden');
            }
            _updatePublishPackButtonText();
        });
    }

    // Search input in user picker
    const searchInput = document.getElementById('publish-pack-users-search');
    if (searchInput) {
        let debounce = null;
        searchInput.addEventListener('input', () => {
            clearTimeout(debounce);
            debounce = setTimeout(() => _loadPackShareableUsers(searchInput.value), 300);
        });
    }
}

/**
 * Open the publish pack modal for a given installation.
 * Fetches current publish state to adaptively pre-select visibility and pre-check targeted users.
 */
async function openPublishPackModal(installationId, packName) {
    initializePublishPackModal();

    const modal = document.getElementById('publish-pack-modal-overlay');
    const modalContent = document.getElementById('publish-pack-modal-content');
    const packIdInput = document.getElementById('publish-pack-id');
    const marketplaceIdInput = document.getElementById('publish-pack-marketplace-id');
    const packNameEl = document.getElementById('publish-pack-name');
    const visibilitySelect = document.getElementById('publish-pack-visibility');
    const usersSection = document.getElementById('publish-pack-users-section');

    if (!modal || !modalContent) return;

    // Reset state
    _packExistingTargetedUsers = [];
    if (packIdInput) packIdInput.value = installationId;
    if (marketplaceIdInput) marketplaceIdInput.value = '';
    if (packNameEl) packNameEl.textContent = packName;
    if (visibilitySelect) visibilitySelect.value = '';
    if (usersSection) usersSection.classList.add('hidden');

    // Show modal with animation
    modal.classList.remove('hidden');
    setTimeout(() => {
        modal.classList.add('opacity-100');
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);

    // Fetch current pack data to determine adaptive state
    try {
        const packsRes = await fetch('/api/v1/agent-packs', { headers: _headers(false) });
        const packsData = await packsRes.json();
        const thisPack = (packsData.packs || []).find(p => p.installation_id === Number(installationId));
        const marketplacePackId = thisPack?.marketplace_pack_id;
        const marketplaceVisibility = thisPack?.marketplace_visibility;

        if (marketplacePackId) {
            // Already published — store marketplace ID for submit handler
            if (marketplaceIdInput) marketplaceIdInput.value = marketplacePackId;

            if (marketplaceVisibility === 'targeted') {
                // Fetch targeted users
                const res = await fetch(`/api/v1/marketplace/agent-packs/${marketplacePackId}/targeted-users`, { headers: _headers(false) });
                const data = await res.json();
                _packExistingTargetedUsers = (data.status === 'success' && data.users) ? data.users : [];

                if (visibilitySelect) visibilitySelect.value = 'targeted';
                if (usersSection) usersSection.classList.remove('hidden');
                await _loadPackShareableUsers('');
            } else {
                if (visibilitySelect) visibilitySelect.value = 'public';
            }
        }
    } catch { /* ignore, use defaults */ }

    _updatePublishPackButtonText();
}

/**
 * Close the publish pack modal.
 */
function closePublishPackModal() {
    const modal = document.getElementById('publish-pack-modal-overlay');
    const modalContent = document.getElementById('publish-pack-modal-content');
    const form = document.getElementById('publish-pack-form');

    if (!modal || !modalContent) return;

    modal.classList.remove('opacity-100');
    modalContent.classList.remove('scale-100', 'opacity-100');
    modalContent.classList.add('scale-95', 'opacity-0');

    setTimeout(() => {
        modal.classList.add('hidden');
        if (form) form.reset();
    }, 300);
}

/**
 * Handle publish pack form submission with grant sync.
 */
async function _handlePublishPack() {
    const installationId = document.getElementById('publish-pack-id')?.value;
    const visibility = document.getElementById('publish-pack-visibility')?.value;
    const submitBtn = document.getElementById('publish-pack-submit');

    if (!installationId || !visibility) {
        _notify('error', 'Please select a visibility option');
        return;
    }

    // For targeted: publish with user_ids or update targeted users
    if (visibility === 'targeted') {
        const selectedUserIds = [...document.querySelectorAll('.publish-pack-user-cb:checked')].map(cb => cb.value);
        if (selectedUserIds.length === 0) {
            _notify('error', 'Please select at least one user');
            return;
        }

        const existingMarketplaceId = document.getElementById('publish-pack-marketplace-id')?.value;
        const originalText = submitBtn?.textContent || 'Publish';
        if (submitBtn) { submitBtn.textContent = 'Publishing...'; submitBtn.disabled = true; }

        try {
            if (existingMarketplaceId) {
                // Already published — update targeted users list
                const res = await fetch(`/api/v1/marketplace/agent-packs/${existingMarketplaceId}/targeted-users`, {
                    method: 'PUT',
                    headers: _headers(true),
                    body: JSON.stringify({ user_ids: selectedUserIds }),
                });
                const data = await res.json();
                if (!res.ok || data.status === 'error') {
                    throw new Error(data.message || `Update failed (${res.status})`);
                }
                _notify('success', 'Targeted users updated');
            } else {
                // New targeted publish — creates marketplace record + targeted users
                const res = await fetch(`/api/v1/agent-packs/${installationId}/publish`, {
                    method: 'POST',
                    headers: _headers(true),
                    body: JSON.stringify({ visibility: 'targeted', user_ids: selectedUserIds }),
                });
                const data = await res.json();
                if (!res.ok || data.status === 'error') {
                    throw new Error(data.message || `Publish failed (${res.status})`);
                }
                _notify('success', 'Agent pack published to targeted users');
            }

            closePublishPackModal();
            await loadAgentPacks();
            if (window.refreshMarketplace) window.refreshMarketplace();
        } catch (err) {
            _notify('error', `Failed: ${err.message}`);
        } finally {
            if (submitBtn) { submitBtn.textContent = originalText; submitBtn.disabled = false; }
        }
        return;
    }

    // Public: publish to marketplace
    const originalText = submitBtn?.textContent || 'Publish Agent Pack';
    if (submitBtn) { submitBtn.textContent = 'Publishing...'; submitBtn.disabled = true; }

    try {
        const res = await fetch(`/api/v1/agent-packs/${installationId}/publish`, {
            method: 'POST',
            headers: _headers(true),
            body: JSON.stringify({ visibility }),
        });
        const data = await res.json();
        if (!res.ok || data.status === 'error') {
            throw new Error(data.message || `Publish failed (${res.status})`);
        }
        _notify('success', 'Agent pack published to marketplace');

        closePublishPackModal();
        await loadAgentPacks();
        if (window.refreshMarketplace) window.refreshMarketplace();
    } catch (err) {
        _notify('error', `Failed: ${err.message}`);
    } finally {
        if (submitBtn) { submitBtn.textContent = originalText; submitBtn.disabled = false; }
    }
}

/**
 * Load shareable users into the pack publish modal user picker.
 * Pre-checks users who have existing grants.
 */
async function _loadPackShareableUsers(search) {
    const listEl = document.getElementById('publish-pack-users-list');
    if (!listEl) return;

    try {
        const url = `/api/v1/marketplace/shareable-users${search ? `?search=${encodeURIComponent(search)}` : ''}`;
        const res = await fetch(url, { headers: _headers(false) });
        const data = await res.json();

        if (!res.ok || !data.users?.length) {
            listEl.innerHTML = '<p class="text-sm text-gray-500 text-center py-2">No eligible users found</p>';
            return;
        }

        // Preserve manual selections OR pre-check from existing targeted users
        const prevChecked = new Set();
        listEl.querySelectorAll('.publish-pack-user-cb:checked').forEach(cb => prevChecked.add(cb.value));
        const targetedUserIds = new Set(_packExistingTargetedUsers.map(t => t.user_id));

        listEl.innerHTML = data.users.map(u => {
            const isChecked = prevChecked.has(u.id) || targetedUserIds.has(u.id);
            return `
            <label class="flex items-center gap-2 p-1.5 rounded hover:bg-white/5 cursor-pointer">
                <input type="checkbox" value="${u.id}" class="publish-pack-user-cb accent-indigo-500"
                       ${isChecked ? 'checked' : ''}>
                <span class="text-sm text-white">${_esc(u.display_name)}</span>
                <span class="text-xs text-gray-500">${_esc(u.username)}</span>
                ${u.email ? `<span class="text-xs text-gray-600 ml-auto">${_esc(u.email)}</span>` : ''}
            </label>`;
        }).join('');

        // Update count on checkbox change
        listEl.querySelectorAll('.publish-pack-user-cb').forEach(cb => {
            cb.addEventListener('change', _updatePublishPackShareCount);
        });
        _updatePublishPackShareCount();
    } catch {
        listEl.innerHTML = '<p class="text-sm text-red-400 text-center py-2">Failed to load users</p>';
    }
}

function _updatePublishPackShareCount() {
    const countEl = document.getElementById('publish-pack-users-count');
    if (!countEl) return;
    const checked = document.querySelectorAll('.publish-pack-user-cb:checked').length;
    countEl.textContent = `${checked} user${checked !== 1 ? 's' : ''} selected`;
}

/**
 * Update the submit button text based on visibility and existing publish state.
 */
function _updatePublishPackButtonText() {
    const submitBtn = document.getElementById('publish-pack-submit');
    const visibility = document.getElementById('publish-pack-visibility')?.value;
    const existingMarketplaceId = document.getElementById('publish-pack-marketplace-id')?.value;
    if (!submitBtn) return;
    if (existingMarketplaceId) {
        // Already published — show "Save Changes"
        submitBtn.textContent = 'Save Changes';
    } else if (visibility === 'targeted') {
        submitBtn.textContent = 'Publish (Targeted)';
    } else {
        submitBtn.textContent = 'Publish Agent Pack';
    }
}

/**
 * Unpublish an agent pack from My Assets card.
 */
async function handleUnpublishFromMyAssets(marketplacePackId) {
    if (!confirm('Are you sure you want to unpublish this agent pack from the marketplace?')) return;
    try {
        const res = await fetch(`/api/v1/marketplace/agent-packs/${marketplacePackId}`, {
            method: 'DELETE',
            headers: _headers(false),
        });
        const data = await res.json();
        if (!res.ok || data.status === 'error') {
            throw new Error(data.message || `Unpublish failed (${res.status})`);
        }
        _notify('success', 'Agent pack unpublished from marketplace');
        await loadAgentPacks();
        if (window.refreshMarketplace) window.refreshMarketplace();
    } catch (err) {
        _notify('error', `Failed: ${err.message}`);
    }
}

// ── Unsubscribe from Agent Pack ───────────────────────────────────────────────

async function handleUnsubscribeAgentPack(marketplacePackId, packName) {
    const confirmed = window.showConfirmation
        ? await new Promise(resolve => {
            window.showConfirmation(
                'Unsubscribe from Agent Pack',
                `Are you sure you want to unsubscribe from "${packName}"?\n\nAll subscribed profiles and collection subscriptions from this pack will be removed.`,
                () => resolve(true),
                () => resolve(false)
            );
        })
        : confirm(`Unsubscribe from "${packName}"?`);

    if (!confirmed) return;

    try {
        const res = await fetch(`/api/v1/marketplace/agent-packs/${marketplacePackId}/subscribe`, {
            method: 'DELETE',
            headers: _headers(false),
        });
        const data = await res.json();
        if (!res.ok || data.status === 'error') {
            throw new Error(data.message || `Unsubscribe failed (${res.status})`);
        }
        _notify('success', `Unsubscribed from ${packName}`);
        await loadAgentPacks();
        if (window.refreshMarketplace) window.refreshMarketplace();
        // Refresh profiles and collections so unsubscribed resources disappear
        if (window.configState?.loadProfiles) {
            await window.configState.loadProfiles();
            if (window.renderProfiles) window.renderProfiles();
        }
        if (window.loadRagCollections) {
            window.loadRagCollections();
        }
    } catch (err) {
        _notify('error', `Failed: ${err.message}`);
    }
}

// ── Public API ───────────────────────────────────────────────────────────────

window.agentPackHandler = {
    loadAgentPacks,
    renderAgentPacks,
    handleInstallAgentPack,
    handleCreateAgentPack,
    handleExportAgentPack,
    handleUninstallAgentPack,
    handleUnsubscribeAgentPack,
    handleUnpublishFromMyAssets,
    openPublishPackModal,
    initializePublishPackModal,
    // Exposed for marketplace install flow reuse
    showMcpServerPicker: _showMcpServerPicker,
    showLlmConfigPicker: _showLlmConfigPicker,
    showTagConflictDialog: _showTagConflictDialog,
};

export {
    loadAgentPacks,
    renderAgentPacks,
    handleInstallAgentPack,
    handleCreateAgentPack,
    handleExportAgentPack,
    handleUninstallAgentPack,
    openPublishPackModal,
    initializePublishPackModal,
};
