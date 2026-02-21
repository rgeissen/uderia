/**
 * extensionHandler.js
 *
 * Handles extension listing, activation, deactivation, and configuration
 * via the /api/v1/extensions REST endpoints.
 *
 * Supports multiple activations of the same extension with different
 * default parameters. Each activation has a unique activation_name
 * (json, json2, json3, ...) that the user types as #name in the query box.
 *
 * Extension accent color: yellow/amber (#fbbf24)
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
    else console.log(`[Extension] ${type}: ${msg}`);
}

// ── Tier badge config ───────────────────────────────────────────────────────

const TIER_CONFIG = {
    convention: { label: 'Convention', color: '#9ca3af', bg: 'rgba(156, 163, 175, 0.12)', border: 'rgba(156, 163, 175, 0.25)' },
    simple:     { label: 'Simple',     color: '#60a5fa', bg: 'rgba(96, 165, 250, 0.12)',  border: 'rgba(96, 165, 250, 0.25)' },
    standard:   { label: 'Standard',   color: '#a78bfa', bg: 'rgba(167, 139, 250, 0.12)', border: 'rgba(167, 139, 250, 0.25)' },
    llm:        { label: 'LLM',        color: '#f472b6', bg: 'rgba(244, 114, 182, 0.12)', border: 'rgba(244, 114, 182, 0.25)' },
};

function _createTierBadge(tier) {
    const cfg = TIER_CONFIG[tier] || TIER_CONFIG.standard;
    const span = document.createElement('span');
    span.className = 'inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded';
    span.style.cssText = `background: ${cfg.bg}; border: 1px solid ${cfg.border}; color: ${cfg.color};`;
    span.textContent = cfg.label;
    return span;
}

function _createLlmWarning() {
    const span = document.createElement('span');
    span.className = 'inline-flex items-center gap-1 text-[10px] rounded px-1.5 py-0.5';
    span.style.cssText = 'background: rgba(244, 114, 182, 0.08); color: #f472b6;';
    span.title = 'This extension calls an LLM and consumes tokens';
    span.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
    </svg>LLM`;
    return span;
}

// ── API Calls ────────────────────────────────────────────────────────────────

async function fetchAllExtensions() {
    const res = await fetch('/api/v1/extensions', { headers: _headers(false) });
    if (!res.ok) throw new Error(`Failed to fetch extensions: ${res.status}`);
    const data = await res.json();
    return data.extensions || [];
}

async function fetchActivatedExtensions() {
    const res = await fetch('/api/v1/extensions/activated', { headers: _headers(false) });
    if (!res.ok) throw new Error(`Failed to fetch activated extensions: ${res.status}`);
    const data = await res.json();
    return data.extensions || [];
}

async function activateExtension(extId, defaultParam = null, config = null) {
    const body = {};
    if (defaultParam) body.default_param = defaultParam;
    if (config) body.config = config;

    const res = await fetch(`/api/v1/extensions/${extId}/activate`, {
        method: 'POST',
        headers: _headers(),
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`Failed to activate extension: ${res.status}`);
    return await res.json();
}

async function deactivateExtension(activationName) {
    const res = await fetch(`/api/v1/extensions/activations/${activationName}/deactivate`, {
        method: 'POST',
        headers: _headers(false),
    });
    if (!res.ok) throw new Error(`Failed to deactivate: ${res.status}`);
    return await res.json();
}

async function deleteActivation(activationName) {
    const res = await fetch(`/api/v1/extensions/activations/${activationName}`, {
        method: 'DELETE',
        headers: _headers(false),
    });
    if (!res.ok) throw new Error(`Failed to delete: ${res.status}`);
    return await res.json();
}

async function updateConfig(activationName, defaultParam, config) {
    const body = {};
    if (defaultParam !== undefined) body.default_param = defaultParam;
    if (config !== undefined) body.config = config;

    const res = await fetch(`/api/v1/extensions/activations/${activationName}/config`, {
        method: 'PUT',
        headers: _headers(),
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`Failed to update config: ${res.status}`);
    return await res.json();
}

async function renameActivation(activationName, newName) {
    const res = await fetch(`/api/v1/extensions/activations/${activationName}/rename`, {
        method: 'PUT',
        headers: _headers(),
        body: JSON.stringify({ new_name: newName }),
    });
    if (!res.ok) throw new Error(`Failed to rename: ${res.status}`);
    return await res.json();
}

async function fetchExtensionSource(name) {
    const res = await fetch(`/api/v1/extensions/${name}/source`, { headers: _headers(false) });
    if (!res.ok) throw new Error(`Failed to fetch source: ${res.status}`);
    return await res.json();
}

async function reloadExtensionsAPI() {
    const res = await fetch('/api/v1/extensions/reload', {
        method: 'POST',
        headers: _headers(false),
    });
    if (!res.ok) throw new Error(`Failed to reload: ${res.status}`);
    return await res.json();
}

// ── Scaffold API ────────────────────────────────────────────────────────────

async function scaffoldExtension(name, level, description) {
    const res = await fetch('/api/v1/extensions/scaffold', {
        method: 'POST',
        headers: _headers(),
        body: JSON.stringify({ name, level, description }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Scaffold failed: ${res.status}`);
    }
    return await res.json();
}

function showScaffoldModal() {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-50 flex items-center justify-center';
    overlay.style.cssText = 'background: rgba(0, 0, 0, 0.7); backdrop-filter: blur(4px);';
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

    const modal = document.createElement('div');
    modal.className = 'glass-panel rounded-xl p-6 max-w-lg w-full mx-4';
    modal.style.cssText = 'border: 1px solid rgba(251, 191, 36, 0.2);';

    modal.innerHTML = `
        <div class="flex items-center justify-between mb-5">
            <h3 class="text-base font-semibold text-white">Create Extension</h3>
            <button class="text-gray-400 hover:text-white transition-colors close-btn">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>

        <div class="space-y-4">
            <div>
                <label class="block text-xs text-gray-400 mb-1">Extension Name</label>
                <input id="scaffold-name" type="text" placeholder="my_extension"
                    class="w-full text-sm px-3 py-2 rounded-lg border bg-transparent text-gray-200 focus:outline-none"
                    style="border-color: rgba(148,163,184,0.2); font-family: 'JetBrains Mono','Fira Code',monospace;"
                    pattern="[a-z][a-z0-9_]*">
                <p class="text-[10px] text-gray-600 mt-1">Lowercase, underscores ok. This becomes the #name trigger.</p>
            </div>

            <div>
                <label class="block text-xs text-gray-400 mb-1">Level</label>
                <div id="scaffold-levels" class="grid grid-cols-2 gap-2">
                    <button data-level="convention" class="scaffold-level-btn selected text-left p-2.5 rounded-lg border text-xs transition-all"
                        style="border-color: rgba(251,191,36,0.4); background: rgba(251,191,36,0.08);">
                        <div class="font-medium text-white mb-0.5">Convention</div>
                        <div class="text-gray-500">Zero friction — plain function, no imports</div>
                    </button>
                    <button data-level="simple" class="scaffold-level-btn text-left p-2.5 rounded-lg border text-xs transition-all"
                        style="border-color: rgba(148,163,184,0.15); background: transparent;">
                        <div class="font-medium text-gray-300 mb-0.5">Simple</div>
                        <div class="text-gray-500">Class with transform() method</div>
                    </button>
                    <button data-level="standard" class="scaffold-level-btn text-left p-2.5 rounded-lg border text-xs transition-all"
                        style="border-color: rgba(148,163,184,0.15); background: transparent;">
                        <div class="font-medium text-gray-300 mb-0.5">Standard</div>
                        <div class="text-gray-500">Full context access, async execute()</div>
                    </button>
                    <button data-level="llm" class="scaffold-level-btn text-left p-2.5 rounded-lg border text-xs transition-all"
                        style="border-color: rgba(148,163,184,0.15); background: transparent;">
                        <div class="font-medium text-gray-300 mb-0.5">LLM</div>
                        <div class="text-gray-500">Calls your LLM with cost tracking</div>
                    </button>
                </div>
            </div>

            <div>
                <label class="block text-xs text-gray-400 mb-1">Description <span class="text-gray-600">(optional)</span></label>
                <input id="scaffold-desc" type="text" placeholder="What does this extension do?"
                    class="w-full text-sm px-3 py-2 rounded-lg border bg-transparent text-gray-200 focus:outline-none"
                    style="border-color: rgba(148,163,184,0.2);">
            </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
            <button class="ind-button ind-button--secondary ind-button--sm close-btn">Cancel</button>
            <button id="scaffold-create-btn" class="ind-button ind-button--sm"
                style="background: rgba(251,191,36,0.15); border: 1px solid rgba(251,191,36,0.3); color: #fbbf24;">
                Create Extension
            </button>
        </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Level selection
    let selectedLevel = 'convention';
    modal.querySelectorAll('.scaffold-level-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            modal.querySelectorAll('.scaffold-level-btn').forEach(b => {
                b.style.borderColor = 'rgba(148,163,184,0.15)';
                b.style.background = 'transparent';
                b.classList.remove('selected');
            });
            btn.style.borderColor = 'rgba(251,191,36,0.4)';
            btn.style.background = 'rgba(251,191,36,0.08)';
            btn.classList.add('selected');
            selectedLevel = btn.dataset.level;
        });
    });

    // Close handlers
    modal.querySelectorAll('.close-btn').forEach(btn => btn.addEventListener('click', () => overlay.remove()));
    const escHandler = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', escHandler); } };
    document.addEventListener('keydown', escHandler);

    // Create handler
    modal.querySelector('#scaffold-create-btn').addEventListener('click', async () => {
        const nameInput = modal.querySelector('#scaffold-name');
        const descInput = modal.querySelector('#scaffold-desc');
        const name = nameInput.value.trim();
        const desc = descInput.value.trim();

        if (!name) {
            nameInput.style.borderColor = 'rgba(239,68,68,0.5)';
            return;
        }
        if (!/^[a-z][a-z0-9_]*$/.test(name)) {
            nameInput.style.borderColor = 'rgba(239,68,68,0.5)';
            _notify('error', 'Name must start with a letter and contain only lowercase letters, numbers, underscores');
            return;
        }

        const createBtn = modal.querySelector('#scaffold-create-btn');
        try {
            createBtn.disabled = true;
            createBtn.textContent = 'Creating...';
            const result = await scaffoldExtension(name, selectedLevel, desc);
            overlay.remove();
            _notify('success', `Extension #${name} created (${selectedLevel}) — ${result.files.length} file(s) at ${result.path}`);
            await loadExtensions();
            if (window.loadActivatedExtensions) window.loadActivatedExtensions();
        } catch (err) {
            _notify('error', err.message);
        } finally {
            createBtn.disabled = false;
            createBtn.textContent = 'Create Extension';
        }
    });

    // Focus name input
    setTimeout(() => modal.querySelector('#scaffold-name')?.focus(), 100);
}

// ── Available Extension Card (registry item with Activate button) ────────────

function createAvailableExtensionCard(ext, activationCount) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-xl p-4 transition-all duration-300';
    card.style.borderLeft = '3px solid rgba(148, 163, 184, 0.2)';

    const header = document.createElement('div');
    header.className = 'flex items-center justify-between';

    const headerLeft = document.createElement('div');
    headerLeft.className = 'flex items-center gap-3';

    const badge = document.createElement('span');
    badge.className = 'inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded';
    badge.style.cssText = 'background: rgba(148, 163, 184, 0.1); border: 1px solid rgba(148, 163, 184, 0.2); color: #9ca3af; font-family: "JetBrains Mono", "Fira Code", monospace;';
    badge.textContent = `#${ext.extension_id}`;
    headerLeft.appendChild(badge);

    const name = document.createElement('span');
    name.className = 'text-white font-medium text-sm';
    name.textContent = ext.display_name || ext.extension_id;
    headerLeft.appendChild(name);

    if (ext.extension_tier) {
        headerLeft.appendChild(_createTierBadge(ext.extension_tier));
    }

    if (ext.requires_llm && ext.extension_tier !== 'llm') {
        headerLeft.appendChild(_createLlmWarning());
    }

    if (ext.category) {
        const cat = document.createElement('span');
        cat.className = 'text-xs px-2 py-0.5 rounded-full';
        cat.style.cssText = 'background: rgba(148, 163, 184, 0.1); color: #9ca3af;';
        cat.textContent = ext.category;
        headerLeft.appendChild(cat);
    }

    if (activationCount > 0) {
        const count = document.createElement('span');
        count.className = 'text-xs px-1.5 py-0.5 rounded-full';
        count.style.cssText = 'background: rgba(251, 191, 36, 0.15); color: #fbbf24;';
        count.textContent = `${activationCount} active`;
        headerLeft.appendChild(count);
    }

    header.appendChild(headerLeft);

    // Activate button (+ icon)
    const activateBtn = document.createElement('button');
    activateBtn.className = 'ind-button ind-button--secondary ind-button--sm';
    activateBtn.style.cssText = 'border-color: rgba(251, 191, 36, 0.3); color: #fbbf24;';
    activateBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
        </svg>
        Activate
    `;
    activateBtn.addEventListener('click', async () => {
        try {
            activateBtn.disabled = true;
            const result = await activateExtension(ext.extension_id);
            _notify('success', `Extension activated as #${result.activation_name}`);
            await loadExtensions();
            if (window.loadActivatedExtensions) window.loadActivatedExtensions();
        } catch (err) {
            _notify('error', err.message);
        } finally {
            activateBtn.disabled = false;
        }
    });
    header.appendChild(activateBtn);
    card.appendChild(header);

    // Description + footer on one line
    if (ext.description) {
        const desc = document.createElement('p');
        desc.className = 'text-xs text-gray-500 mt-2';
        desc.textContent = ext.description;
        card.appendChild(desc);
    }

    return card;
}

// ── Activation Card (user's activated instance) ──────────────────────────────

function createActivationCard(activation, extInfo) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-xl p-4 transition-all duration-300';
    card.style.borderLeft = '3px solid rgba(251, 191, 36, 0.6)';

    // Header: activation badge + extension name + actions
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between mb-2';

    const headerLeft = document.createElement('div');
    headerLeft.className = 'flex items-center gap-3';

    const badge = document.createElement('span');
    badge.className = 'inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded';
    badge.style.cssText = 'background: rgba(251, 191, 36, 0.15); border: 1px solid rgba(251, 191, 36, 0.3); color: #fbbf24; font-family: "JetBrains Mono", "Fira Code", monospace;';
    badge.textContent = `#${activation.activation_name}`;
    headerLeft.appendChild(badge);

    // Show base extension name if activation_name differs
    if (activation.activation_name !== activation.extension_id) {
        const baseName = document.createElement('span');
        baseName.className = 'text-xs text-gray-500';
        baseName.textContent = `(${extInfo?.display_name || activation.extension_id})`;
        headerLeft.appendChild(baseName);
    } else {
        const displayName = document.createElement('span');
        displayName.className = 'text-sm text-gray-300 font-medium';
        displayName.textContent = extInfo?.display_name || activation.extension_id;
        headerLeft.appendChild(displayName);
    }

    header.appendChild(headerLeft);

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'flex items-center gap-2';

    // View Script
    const viewBtn = document.createElement('button');
    viewBtn.className = 'text-xs text-gray-500 hover:text-white transition-colors';
    viewBtn.textContent = 'Script';
    viewBtn.addEventListener('click', () => showExtensionSource(activation.extension_id, extInfo?.display_name || activation.extension_id));
    actions.appendChild(viewBtn);

    // Delete button
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'text-xs text-gray-500 hover:text-red-400 transition-colors';
    deleteBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
    `;
    deleteBtn.title = 'Remove activation';
    deleteBtn.addEventListener('click', async () => {
        try {
            await deleteActivation(activation.activation_name);
            _notify('success', `#${activation.activation_name} removed`);
            await loadExtensions();
            if (window.loadActivatedExtensions) window.loadActivatedExtensions();
        } catch (err) {
            _notify('error', err.message);
        }
    });
    actions.appendChild(deleteBtn);

    header.appendChild(actions);
    card.appendChild(header);

    // Default parameter editor
    const paramRow = document.createElement('div');
    paramRow.className = 'flex items-center gap-2';

    const label = document.createElement('span');
    label.className = 'text-xs text-gray-500 whitespace-nowrap';
    label.textContent = 'Default param:';
    paramRow.appendChild(label);

    const input = document.createElement('input');
    input.type = 'text';
    input.value = activation.default_param || '';
    input.placeholder = 'none';
    input.className = 'flex-1 text-xs px-2 py-1 rounded border bg-transparent text-gray-300 focus:outline-none';
    input.style.cssText = 'border-color: rgba(148, 163, 184, 0.2); max-width: 200px;';
    input.addEventListener('focus', () => { input.style.borderColor = 'rgba(251, 191, 36, 0.4)'; });
    input.addEventListener('blur', () => { input.style.borderColor = 'rgba(148, 163, 184, 0.2)'; });
    paramRow.appendChild(input);

    const saveBtn = document.createElement('button');
    saveBtn.className = 'text-xs px-2 py-1 rounded';
    saveBtn.style.cssText = 'background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3);';
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', async () => {
        try {
            await updateConfig(activation.activation_name, input.value || null, null);
            _notify('success', `Default param updated for #${activation.activation_name}`);
            if (window.loadActivatedExtensions) window.loadActivatedExtensions();
        } catch (err) {
            _notify('error', err.message);
        }
    });
    paramRow.appendChild(saveBtn);

    card.appendChild(paramRow);

    // Footer: tier badge + LLM warning + output target + version
    if (extInfo) {
        const footer = document.createElement('div');
        footer.className = 'flex items-center gap-3 text-xs text-gray-600 mt-2 pt-2';
        footer.style.borderTop = '1px solid rgba(148, 163, 184, 0.06)';

        if (extInfo.extension_tier) {
            footer.appendChild(_createTierBadge(extInfo.extension_tier));
        }
        if (extInfo.requires_llm && extInfo.extension_tier !== 'llm') {
            footer.appendChild(_createLlmWarning());
        }
        if (extInfo.output_target) {
            const target = document.createElement('span');
            target.textContent = `Output: ${extInfo.output_target}`;
            footer.appendChild(target);
        }
        if (extInfo.version) {
            const ver = document.createElement('span');
            ver.textContent = `v${extInfo.version}`;
            footer.appendChild(ver);
        }
        if (extInfo.is_builtin) {
            const builtin = document.createElement('span');
            builtin.style.cssText = 'background: rgba(148, 163, 184, 0.08); padding: 1px 6px; border-radius: 4px;';
            builtin.textContent = 'built-in';
            footer.appendChild(builtin);
        }
        card.appendChild(footer);
    }

    return card;
}

// ── Source Viewer Modal ──────────────────────────────────────────────────────

async function showExtensionSource(extId, displayName) {
    try {
        const data = await fetchExtensionSource(extId);
        const source = data.source || 'No source available';

        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 z-50 flex items-center justify-center';
        overlay.style.cssText = 'background: rgba(0, 0, 0, 0.7); backdrop-filter: blur(4px);';
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

        const modal = document.createElement('div');
        modal.className = 'glass-panel rounded-xl p-6 max-w-3xl w-full mx-4 max-h-[80vh] flex flex-col';
        modal.style.cssText = 'border: 1px solid rgba(251, 191, 36, 0.2);';

        modal.innerHTML = `
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2">
                    <span class="text-sm font-semibold" style="color: #fbbf24;">#${extId}</span>
                    <span class="text-sm text-gray-400">${displayName}</span>
                </div>
                <button class="text-gray-400 hover:text-white transition-colors close-btn">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
        `;

        const codeContainer = document.createElement('div');
        codeContainer.className = 'flex-1 overflow-auto rounded-lg p-4';
        codeContainer.style.cssText = 'background: rgba(0, 0, 0, 0.3); font-family: "JetBrains Mono", "Fira Code", monospace; font-size: 0.8rem; line-height: 1.6;';
        const pre = document.createElement('pre');
        pre.className = 'text-gray-300 whitespace-pre';
        pre.textContent = source;
        codeContainer.appendChild(pre);
        modal.appendChild(codeContainer);

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        modal.querySelector('.close-btn').addEventListener('click', () => overlay.remove());
        const handler = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', handler); } };
        document.addEventListener('keydown', handler);
    } catch (err) {
        _notify('error', `Failed to load source: ${err.message}`);
    }
}

// ── Main Load Function ───────────────────────────────────────────────────────

export async function loadExtensions() {
    const container = document.getElementById('extensions-list');
    if (!container) return;

    try {
        const [all, activated] = await Promise.all([
            fetchAllExtensions(),
            fetchActivatedExtensions(),
        ]);

        // Build ext info lookup (registry)
        const extInfoLookup = {};
        for (const ext of all) {
            extInfoLookup[ext.extension_id] = ext;
        }

        // Count activations per extension_id
        const activationCounts = {};
        for (const act of activated) {
            activationCounts[act.extension_id] = (activationCounts[act.extension_id] || 0) + 1;
        }

        container.innerHTML = '';

        if (all.length === 0) {
            container.innerHTML = `
                <div class="text-center py-8">
                    <p class="text-gray-400 text-sm">No extensions available.</p>
                    <p class="text-gray-500 text-xs mt-1">Extensions are loaded from the extensions/ directory.</p>
                </div>
            `;
            return;
        }

        // Section 1: Available Extensions (from registry) with Create button
        const availableHeader = document.createElement('div');
        availableHeader.className = 'flex items-center justify-between mb-3';
        availableHeader.innerHTML = `
            <div>
                <h4 class="text-sm font-semibold text-gray-400 uppercase tracking-wide">Available Extensions</h4>
                <p class="text-xs text-gray-600 mt-0.5">Click Activate to create a new instance</p>
            </div>
        `;
        const createBtn = document.createElement('button');
        createBtn.className = 'ind-button ind-button--sm';
        createBtn.style.cssText = 'background: rgba(251,191,36,0.1); border: 1px solid rgba(251,191,36,0.3); color: #fbbf24; font-size: 0.75rem;';
        createBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
        </svg>Create Extension`;
        createBtn.addEventListener('click', () => showScaffoldModal());
        availableHeader.appendChild(createBtn);
        container.appendChild(availableHeader);

        for (const ext of all) {
            container.appendChild(createAvailableExtensionCard(ext, activationCounts[ext.extension_id] || 0));
        }

        // Section 2: User's Activations
        if (activated.length > 0) {
            const activationsHeader = document.createElement('div');
            activationsHeader.className = 'mt-6 mb-3';
            activationsHeader.innerHTML = `
                <h4 class="text-sm font-semibold text-gray-400 uppercase tracking-wide">Your Activations</h4>
                <p class="text-xs text-gray-600 mt-0.5">These are the #names you can use in the query box</p>
            `;
            container.appendChild(activationsHeader);

            for (const act of activated) {
                const extInfo = extInfoLookup[act.extension_id] || null;
                container.appendChild(createActivationCard(act, extInfo));
            }
        }

    } catch (err) {
        console.error('[Extensions] Load failed:', err);
        container.innerHTML = `
            <div class="text-center py-8">
                <p class="text-red-400 text-sm">Failed to load extensions.</p>
                <p class="text-gray-500 text-xs mt-1">${err.message}</p>
            </div>
        `;
    }
}

// ── Reload Button ────────────────────────────────────────────────────────────

export function initializeExtensionHandlers() {
    const reloadBtn = document.getElementById('reload-extensions-btn');
    if (reloadBtn) {
        reloadBtn.addEventListener('click', async () => {
            try {
                reloadBtn.disabled = true;
                await reloadExtensionsAPI();
                await loadExtensions();
                if (window.loadActivatedExtensions) window.loadActivatedExtensions();
                _notify('success', 'Extensions reloaded from disk');
            } catch (err) {
                _notify('error', `Reload failed: ${err.message}`);
            } finally {
                reloadBtn.disabled = false;
            }
        });
    }
}
