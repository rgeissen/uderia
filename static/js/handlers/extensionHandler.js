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

// ── Tier contract data (drives info panel + requirements checklist) ──────────

const TIER_INFO = {
    convention: {
        title: 'Level 0 — Convention',
        subtitle: 'Zero friction. Drop a .py file, done.',
        youWrite: 'A transform() function',
        youReceive: ['answer_text: str', 'param: str | None'],
        youReturn: 'dict or str',
        frameworkHandles: ['Class creation', 'Manifest generation', 'Result wrapping', 'Error handling'],
        needsManifest: false,
        canCallLLM: false,
        fileStructure: '~/.tda/extensions/{name}.py',
        fileNote: 'flat file — no directory needed',
        requirements: [
            { id: 'ext_name', label: 'EXTENSION_NAME defined', pattern: /EXTENSION_NAME\s*=/ },
            { id: 'transform', label: 'transform() function', pattern: /def transform\s*\(/ },
        ],
    },
    simple: {
        title: 'Level 1 — Simple',
        subtitle: 'Class-based with auto-wired validation.',
        youWrite: 'A class with transform() method',
        youReceive: ['answer_text: str', 'param: str | None'],
        youReturn: 'dict or str',
        frameworkHandles: ['Result wrapping', 'Param validation via allowed_params', 'Error handling'],
        needsManifest: false,
        canCallLLM: false,
        fileStructure: '~/.tda/extensions/{name}/{name}.py',
        fileNote: 'directory with single .py file',
        requirements: [
            { id: 'class', label: 'Extension class defined', pattern: /class \w+\(SimpleExtension\)/ },
            { id: 'name', label: 'name attribute set', pattern: /name\s*=\s*["']/ },
            { id: 'transform', label: 'transform() method', pattern: /def transform\s*\(self/ },
        ],
    },
    standard: {
        title: 'Level 2 — Standard',
        subtitle: 'Full context access with ExtensionContext.',
        youWrite: 'A class with async execute()',
        youReceive: ['context: ExtensionContext', 'param: str | None'],
        youReturn: 'ExtensionResult',
        frameworkHandles: ['Error handling', 'SSE event emission', 'Serial chaining context'],
        needsManifest: true,
        canCallLLM: false,
        fileStructure: '~/.tda/extensions/{name}/{name}.py + manifest.json',
        fileNote: 'directory with .py + manifest',
        requirements: [
            { id: 'class', label: 'Extension class defined', pattern: /class \w+\(Extension\)/ },
            { id: 'name_prop', label: 'name property or attribute', pattern: /def name\(self\)|name\s*=\s*["']/ },
            { id: 'execute', label: 'async execute() method', pattern: /async def execute\s*\(/ },
            { id: 'return', label: 'Returns ExtensionResult', pattern: /ExtensionResult\s*\(/ },
        ],
    },
    llm: {
        title: 'Level 3 — LLM',
        subtitle: 'Calls your LLM with automatic cost tracking.',
        youWrite: 'A class with async execute() + call_llm()',
        youReceive: ['context: ExtensionContext', 'param: str | None'],
        youReturn: 'ExtensionResult',
        frameworkHandles: ['LLM config injection', 'Token tracking', 'Cost calculation', 'Error handling'],
        needsManifest: true,
        canCallLLM: true,
        fileStructure: '~/.tda/extensions/{name}/{name}.py + manifest.json',
        fileNote: 'directory with .py + manifest',
        requirements: [
            { id: 'class', label: 'Extension class defined', pattern: /class \w+\(LLMExtension\)/ },
            { id: 'name', label: 'name attribute set', pattern: /name\s*=\s*["']/ },
            { id: 'execute', label: 'async execute() method', pattern: /async def execute\s*\(/ },
            { id: 'call_llm', label: 'Uses self.call_llm()', pattern: /self\.call_llm\s*\(|await self\.call_llm/ },
            { id: 'return', label: 'Returns ExtensionResult', pattern: /ExtensionResult\s*\(/ },
        ],
    },
};

function _buildTierInfoPanel(tier, name = '{name}') {
    const info = TIER_INFO[tier];
    if (!info) return '';
    const cfg = TIER_CONFIG[tier] || TIER_CONFIG.standard;
    const filePath = info.fileStructure.replace(/\{name\}/g, name || '{name}');

    return `
        <div class="tier-info-panel rounded-lg p-3 mt-3 transition-all duration-300" style="background: ${cfg.bg}; border: 1px solid ${cfg.border};">
            <div class="flex items-center justify-between mb-2">
                <div>
                    <span class="text-xs font-semibold" style="color: ${cfg.color};">${info.title}</span>
                    <span class="text-[10px] text-gray-500 ml-2">${info.subtitle}</span>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-2 text-[10px] mb-2">
                <div class="rounded p-2" style="background: rgba(0,0,0,0.15);">
                    <div class="font-semibold text-gray-400 mb-1 uppercase tracking-wider" style="font-size: 9px;">You Receive</div>
                    ${info.youReceive.map(r => `<div class="text-gray-300 font-mono">${r}</div>`).join('')}
                </div>
                <div class="rounded p-2" style="background: rgba(0,0,0,0.15);">
                    <div class="font-semibold text-gray-400 mb-1 uppercase tracking-wider" style="font-size: 9px;">You Return</div>
                    <div class="text-gray-300 font-mono">${info.youReturn}</div>
                </div>
                <div class="rounded p-2" style="background: rgba(0,0,0,0.15);">
                    <div class="font-semibold text-gray-400 mb-1 uppercase tracking-wider" style="font-size: 9px;">Framework Handles</div>
                    ${info.frameworkHandles.map(h => `<div class="text-gray-400">${h}</div>`).join('')}
                </div>
            </div>

            <div class="flex items-center gap-4 text-[10px] text-gray-500">
                <span class="font-mono" style="color: ${cfg.color};">${filePath}</span>
                <span class="flex items-center gap-1">
                    <span style="color: ${info.needsManifest ? '#fbbf24' : '#6b7280'};">${info.needsManifest ? '&#10003;' : '&#10005;'}</span>
                    manifest
                </span>
                <span class="flex items-center gap-1">
                    <span style="color: ${info.canCallLLM ? '#f472b6' : '#6b7280'};">${info.canCallLLM ? '&#10003;' : '&#10005;'}</span>
                    LLM access
                </span>
            </div>
        </div>
    `;
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
    // Cache existing extension names for uniqueness check
    let existingNames = [];
    fetchAllExtensions().then(exts => { existingNames = exts.map(e => e.extension_id); }).catch(() => {});

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-50 flex items-center justify-center';
    overlay.style.cssText = 'background: rgba(0, 0, 0, 0.7); backdrop-filter: blur(4px);';
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

    const modal = document.createElement('div');
    modal.className = 'glass-panel rounded-xl p-6 max-w-2xl w-full mx-4';
    modal.style.cssText = 'border: 1px solid rgba(251, 191, 36, 0.2); max-height: 90vh; overflow-y: auto;';

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
            <!-- Name input -->
            <div>
                <label class="block text-xs text-gray-400 mb-1">Extension Name</label>
                <input id="scaffold-name" type="text" placeholder="my_extension" maxlength="30"
                    class="w-full text-sm px-3 py-2 rounded-lg border bg-transparent text-gray-200 focus:outline-none"
                    style="border-color: rgba(148,163,184,0.2); font-family: 'JetBrains Mono','Fira Code',monospace;"
                    pattern="[a-z][a-z0-9_]*">
                <div class="flex items-center justify-between mt-1">
                    <p id="scaffold-name-hint" class="text-[10px] text-gray-600">Lowercase, underscores ok. This becomes the <span class="font-mono" style="color: #fbbf24;">#name</span> trigger.</p>
                    <span id="scaffold-name-counter" class="text-[10px] text-gray-600">0/30</span>
                </div>
                <p id="scaffold-name-error" class="text-[10px] mt-0.5 hidden" style="color: #ef4444;"></p>
                <p id="scaffold-name-warning" class="text-[10px] mt-0.5 hidden" style="color: #fbbf24;"></p>
            </div>

            <!-- Tier selector -->
            <div>
                <label class="block text-xs text-gray-400 mb-1">Extension Level</label>
                <div id="scaffold-levels" class="grid grid-cols-4 gap-2">
                    <button data-level="convention" class="scaffold-level-btn selected text-left p-2 rounded-lg border text-xs transition-all"
                        style="border-color: rgba(156,163,175,0.4); background: rgba(156,163,175,0.08);">
                        <div class="font-medium text-white mb-0.5" style="font-size: 11px;">Convention</div>
                        <div class="text-gray-500" style="font-size: 9px;">Plain function</div>
                    </button>
                    <button data-level="simple" class="scaffold-level-btn text-left p-2 rounded-lg border text-xs transition-all"
                        style="border-color: rgba(148,163,184,0.15); background: transparent;">
                        <div class="font-medium text-gray-300 mb-0.5" style="font-size: 11px;">Simple</div>
                        <div class="text-gray-500" style="font-size: 9px;">Class + transform()</div>
                    </button>
                    <button data-level="standard" class="scaffold-level-btn text-left p-2 rounded-lg border text-xs transition-all"
                        style="border-color: rgba(148,163,184,0.15); background: transparent;">
                        <div class="font-medium text-gray-300 mb-0.5" style="font-size: 11px;">Standard</div>
                        <div class="text-gray-500" style="font-size: 9px;">Full context</div>
                    </button>
                    <button data-level="llm" class="scaffold-level-btn text-left p-2 rounded-lg border text-xs transition-all"
                        style="border-color: rgba(148,163,184,0.15); background: transparent;">
                        <div class="font-medium text-gray-300 mb-0.5" style="font-size: 11px;">LLM</div>
                        <div class="text-gray-500" style="font-size: 9px;">Calls your LLM</div>
                    </button>
                </div>
            </div>

            <!-- Tier info panel (dynamic) -->
            <div id="scaffold-tier-info">${_buildTierInfoPanel('convention')}</div>

            <!-- Description -->
            <div>
                <label class="block text-xs text-gray-400 mb-1">Description <span class="text-gray-600">(optional)</span></label>
                <input id="scaffold-desc" type="text" placeholder="What does this extension do?" maxlength="200"
                    class="w-full text-sm px-3 py-2 rounded-lg border bg-transparent text-gray-200 focus:outline-none"
                    style="border-color: rgba(148,163,184,0.2);">
                <div class="flex justify-end mt-0.5">
                    <span id="scaffold-desc-counter" class="text-[10px] text-gray-600">0/200</span>
                </div>
            </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
            <button class="ind-button ind-button--secondary ind-button--sm close-btn">Cancel</button>
            <button id="scaffold-create-btn" class="ind-button ind-button--sm flex items-center gap-1.5"
                style="background: rgba(251,191,36,0.15); border: 1px solid rgba(251,191,36,0.3); color: #fbbf24;">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                Create & Open Editor
            </button>
        </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    requestAnimationFrame(() => { modal.style.opacity = '1'; modal.style.transform = 'scale(1)'; });

    // Level selection with dynamic tier info
    let selectedLevel = 'convention';
    const tierInfoContainer = modal.querySelector('#scaffold-tier-info');

    modal.querySelectorAll('.scaffold-level-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const level = btn.dataset.level;
            const cfg = TIER_CONFIG[level] || TIER_CONFIG.standard;

            modal.querySelectorAll('.scaffold-level-btn').forEach(b => {
                b.style.borderColor = 'rgba(148,163,184,0.15)';
                b.style.background = 'transparent';
                b.classList.remove('selected');
            });
            btn.style.borderColor = `${cfg.color}66`;
            btn.style.background = cfg.bg;
            btn.classList.add('selected');
            selectedLevel = level;

            // Update tier info panel with animation
            tierInfoContainer.style.opacity = '0';
            setTimeout(() => {
                const nameVal = modal.querySelector('#scaffold-name').value.trim() || '{name}';
                tierInfoContainer.innerHTML = _buildTierInfoPanel(level, nameVal);
                tierInfoContainer.style.opacity = '1';
            }, 150);
        });
    });

    // Name input validation
    const nameInput = modal.querySelector('#scaffold-name');
    const nameError = modal.querySelector('#scaffold-name-error');
    const nameWarning = modal.querySelector('#scaffold-name-warning');
    const nameCounter = modal.querySelector('#scaffold-name-counter');

    nameInput.addEventListener('input', () => {
        const val = nameInput.value;
        nameCounter.textContent = `${val.length}/30`;
        nameError.classList.add('hidden');
        nameWarning.classList.add('hidden');
        nameInput.style.borderColor = 'rgba(148,163,184,0.2)';

        if (val && !/^[a-z][a-z0-9_]*$/.test(val)) {
            nameError.textContent = 'Must start with a letter; only lowercase letters, numbers, underscores.';
            nameError.classList.remove('hidden');
            nameInput.style.borderColor = 'rgba(239,68,68,0.5)';
        } else if (val && existingNames.includes(val)) {
            nameWarning.textContent = `Extension "${val}" already exists — creating will override it.`;
            nameWarning.classList.remove('hidden');
            nameInput.style.borderColor = 'rgba(251,191,36,0.5)';
        } else if (val) {
            nameInput.style.borderColor = 'rgba(34,197,94,0.4)';
        }

        // Update file path in tier info
        const panel = tierInfoContainer.querySelector('.tier-info-panel .font-mono');
        if (panel) {
            const info = TIER_INFO[selectedLevel];
            panel.textContent = info.fileStructure.replace(/\{name\}/g, val || '{name}');
        }
    });

    // Description counter
    const descInput = modal.querySelector('#scaffold-desc');
    const descCounter = modal.querySelector('#scaffold-desc-counter');
    descInput.addEventListener('input', () => { descCounter.textContent = `${descInput.value.length}/200`; });

    // Close handlers
    modal.querySelectorAll('.close-btn').forEach(btn => btn.addEventListener('click', () => overlay.remove()));
    const escHandler = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', escHandler); } };
    document.addEventListener('keydown', escHandler);

    // Create & Open Editor handler
    modal.querySelector('#scaffold-create-btn').addEventListener('click', async () => {
        const name = nameInput.value.trim();
        const desc = descInput.value.trim();

        if (!name) {
            nameInput.style.borderColor = 'rgba(239,68,68,0.5)';
            nameInput.focus();
            return;
        }
        if (!/^[a-z][a-z0-9_]*$/.test(name)) {
            nameInput.style.borderColor = 'rgba(239,68,68,0.5)';
            nameError.textContent = 'Must start with a letter; only lowercase letters, numbers, underscores.';
            nameError.classList.remove('hidden');
            nameInput.focus();
            return;
        }

        const createBtn = modal.querySelector('#scaffold-create-btn');
        try {
            createBtn.disabled = true;
            createBtn.innerHTML = `<svg class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Creating...`;
            const result = await scaffoldExtension(name, selectedLevel, desc);
            overlay.remove();
            _notify('success', `Extension #${name} created (${selectedLevel})`);
            await loadExtensions();
            if (window.loadActivatedExtensions) window.loadActivatedExtensions();

            // Open the code editor for the newly created extension
            try {
                const sourceData = await fetchExtensionSource(name);
                showExtensionEditor(name, sourceData.source || '', selectedLevel, true);
            } catch (_) {
                // Editor open failed — extension was still created successfully
            }
        } catch (err) {
            _notify('error', err.message);
            createBtn.disabled = false;
            createBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" /></svg> Create & Open Editor`;
        }
    });

    // Focus name input
    setTimeout(() => nameInput?.focus(), 100);
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

// ── Extension Editor (Phase 2 — full code editor with requirements) ─────────

function _detectTierFromSource(source) {
    if (/class \w+\(LLMExtension\)/.test(source)) return 'llm';
    if (/class \w+\(SimpleExtension\)/.test(source)) return 'simple';
    if (/class \w+\(Extension\)/.test(source)) return 'standard';
    if (/EXTENSION_NAME\s*=/.test(source) && /def transform\s*\(/.test(source)) return 'convention';
    return 'standard'; // fallback
}

function _validateRequirements(source, tier) {
    const info = TIER_INFO[tier];
    if (!info) return [];
    return info.requirements.map(req => ({
        ...req,
        met: req.pattern.test(source),
    }));
}

function _buildRequirementsSidebar(source, tier) {
    const results = _validateRequirements(source, tier);
    const metCount = results.filter(r => r.met).length;
    const total = results.length;
    const pct = total > 0 ? Math.round((metCount / total) * 100) : 0;
    const info = TIER_INFO[tier] || TIER_INFO.standard;
    const cfg = TIER_CONFIG[tier] || TIER_CONFIG.standard;

    let html = `
        <div class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Requirements</div>
        <div class="flex items-center gap-2 mb-2">
            <span class="text-sm font-semibold" style="color: ${metCount === total ? '#22c55e' : cfg.color};">${metCount} of ${total}</span>
            <span class="text-[10px] text-gray-500">met</span>
        </div>
        <div class="w-full h-1.5 rounded-full mb-4" style="background: rgba(255,255,255,0.06);">
            <div class="h-full rounded-full transition-all duration-500" style="width: ${pct}%; background: ${metCount === total ? '#22c55e' : cfg.color};"></div>
        </div>
        <div class="space-y-2 mb-6">
    `;

    for (const req of results) {
        const icon = req.met
            ? `<svg class="h-3.5 w-3.5 flex-shrink-0" style="color: #22c55e;" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>`
            : `<svg class="h-3.5 w-3.5 flex-shrink-0" style="color: #4b5563;" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>`;
        html += `
            <div class="flex items-start gap-2">
                ${icon}
                <span class="text-[11px] ${req.met ? 'text-gray-300' : 'text-gray-500'}">${req.label}</span>
            </div>
        `;
    }

    html += `</div>`;

    // Contract summary
    html += `
        <div style="border-top: 1px solid rgba(148,163,184,0.08);" class="pt-4 mt-2">
            <div class="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Contract</div>
            <div class="space-y-1.5 text-[10px]">
                <div>
                    <span class="text-gray-500">Input:</span>
                    <span class="text-gray-400 font-mono">${info.youReceive.join(', ')}</span>
                </div>
                <div>
                    <span class="text-gray-500">Output:</span>
                    <span class="text-gray-400 font-mono">${info.youReturn}</span>
                </div>
                ${info.canCallLLM ? `<div>
                    <span class="text-gray-500">LLM:</span>
                    <span class="font-mono" style="color: #f472b6;">self.call_llm()</span>
                </div>` : ''}
                <div>
                    <span class="text-gray-500">Manifest:</span>
                    <span class="text-gray-400">${info.needsManifest ? 'Required' : 'Not needed'}</span>
                </div>
            </div>
        </div>
    `;

    return html;
}

function showExtensionEditor(name, source, tier, isNew = false, readOnly = false) {
    if (!tier) tier = _detectTierFromSource(source);
    const cfg = TIER_CONFIG[tier] || TIER_CONFIG.standard;
    const info = TIER_INFO[tier] || TIER_INFO.standard;
    let originalSource = source;
    let hasChanges = false;

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-50 flex items-center justify-center';
    overlay.style.cssText = 'background: rgba(0, 0, 0, 0.8); backdrop-filter: blur(6px);';

    const editor = document.createElement('div');
    editor.className = 'glass-panel rounded-xl flex flex-col mx-4 my-4';
    editor.style.cssText = `border: 1px solid ${cfg.border}; width: calc(100vw - 3rem); height: calc(100vh - 3rem); max-width: 1400px;`;

    // ── Header ──
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between px-5 py-3 flex-shrink-0';
    header.style.borderBottom = '1px solid rgba(148,163,184,0.08)';

    header.innerHTML = `
        <div class="flex items-center gap-3">
            <span class="inline-flex items-center px-2.5 py-0.5 text-sm font-semibold rounded" style="background: rgba(251,191,36,0.15); border: 1px solid rgba(251,191,36,0.3); color: #fbbf24; font-family: 'JetBrains Mono', monospace;">#${name}</span>
            <span class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded" style="background: ${cfg.bg}; border: 1px solid ${cfg.border}; color: ${cfg.color};">${info.title}</span>
            ${readOnly ? '<span class="text-[10px] text-gray-500 px-1.5 py-0.5 rounded" style="background: rgba(148,163,184,0.08);">read-only</span>' : ''}
            ${isNew ? '<span class="text-[10px] px-1.5 py-0.5 rounded" style="background: rgba(34,197,94,0.1); color: #22c55e;">new</span>' : ''}
        </div>
        <div class="flex items-center gap-2">
            <span id="editor-status" class="text-[10px] text-gray-600 mr-2"></span>
            ${!readOnly ? `<button id="editor-save-btn" class="ind-button ind-button--sm flex items-center gap-1.5" style="background: rgba(251,191,36,0.15); border: 1px solid rgba(251,191,36,0.3); color: #fbbf24; opacity: 0.5;" disabled>
                <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                </svg>
                Save
            </button>` : ''}
            <button class="text-gray-400 hover:text-white transition-colors close-btn p-1">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>
    `;
    editor.appendChild(header);

    // ── Body: sidebar + code area ──
    const body = document.createElement('div');
    body.className = 'flex flex-1 min-h-0';

    // Sidebar
    const sidebar = document.createElement('div');
    sidebar.className = 'flex-shrink-0 p-4 overflow-y-auto';
    sidebar.style.cssText = 'width: 220px; border-right: 1px solid rgba(148,163,184,0.08); background: rgba(0,0,0,0.1);';
    sidebar.innerHTML = _buildRequirementsSidebar(source, tier);
    body.appendChild(sidebar);

    // Code area
    const codeArea = document.createElement('div');
    codeArea.className = 'flex-1 flex flex-col min-w-0';

    // File path bar
    const pathBar = document.createElement('div');
    pathBar.className = 'flex items-center gap-2 px-4 py-1.5 text-[10px] flex-shrink-0';
    pathBar.style.cssText = 'background: rgba(0,0,0,0.15); border-bottom: 1px solid rgba(148,163,184,0.06);';
    pathBar.innerHTML = `<span class="text-gray-500 font-mono">${info.fileStructure.replace(/\{name\}/g, name)}</span>`;
    codeArea.appendChild(pathBar);

    // Editor container with line numbers + textarea + syntax highlight overlay
    const editorContainer = document.createElement('div');
    editorContainer.className = 'flex-1 relative overflow-hidden';
    editorContainer.style.cssText = 'background: rgba(0,0,0,0.2);';

    const editorWrapper = document.createElement('div');
    editorWrapper.className = 'flex h-full';

    // Line numbers gutter
    const lineGutter = document.createElement('div');
    lineGutter.className = 'flex-shrink-0 text-right select-none overflow-hidden';
    lineGutter.style.cssText = 'width: 50px; padding: 12px 8px 12px 0; font-family: "JetBrains Mono", "Fira Code", monospace; font-size: 0.75rem; line-height: 1.6; color: rgba(148,163,184,0.25); background: rgba(0,0,0,0.1);';

    function updateLineNumbers(text) {
        const lines = text.split('\n').length;
        lineGutter.innerHTML = Array.from({ length: lines }, (_, i) => `<div>${i + 1}</div>`).join('');
    }
    updateLineNumbers(source);

    editorWrapper.appendChild(lineGutter);

    // Scrollable code container
    const codeScroller = document.createElement('div');
    codeScroller.className = 'flex-1 relative overflow-auto';
    codeScroller.style.cssText = 'min-width: 0;';

    // Syntax-highlighted backdrop (shows when textarea not focused)
    const highlightPre = document.createElement('pre');
    highlightPre.className = 'absolute inset-0 pointer-events-none';
    highlightPre.style.cssText = 'padding: 12px; margin: 0; font-family: "JetBrains Mono", "Fira Code", monospace; font-size: 0.75rem; line-height: 1.6; overflow: hidden; white-space: pre; background: transparent;';
    const highlightCode = document.createElement('code');
    highlightCode.className = 'language-python';
    highlightPre.appendChild(highlightCode);

    function updateHighlight(text) {
        highlightCode.textContent = text;
        if (window.Prism) {
            Prism.highlightElement(highlightCode);
        }
    }
    updateHighlight(source);

    // Textarea (actual editable area)
    const textarea = document.createElement('textarea');
    textarea.className = 'w-full h-full resize-none focus:outline-none';
    textarea.style.cssText = `padding: 12px; margin: 0; font-family: "JetBrains Mono", "Fira Code", monospace; font-size: 0.75rem; line-height: 1.6; background: transparent; color: rgba(209, 213, 219, 0.9); caret-color: #fbbf24; border: none; white-space: pre; overflow: auto; tab-size: 4; -moz-tab-size: 4; min-height: 100%;`;
    textarea.value = source;
    textarea.spellcheck = false;
    textarea.autocomplete = 'off';
    textarea.autocorrect = 'off';
    textarea.autocapitalize = 'off';
    if (readOnly) textarea.readOnly = true;

    // Tab key inserts spaces
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
            e.preventDefault();
            const start = textarea.selectionStart;
            const end = textarea.selectionEnd;
            textarea.value = textarea.value.substring(0, start) + '    ' + textarea.value.substring(end);
            textarea.selectionStart = textarea.selectionEnd = start + 4;
            textarea.dispatchEvent(new Event('input'));
        }
    });

    // Sync scroll between textarea and highlight
    textarea.addEventListener('scroll', () => {
        highlightPre.scrollTop = textarea.scrollTop;
        highlightPre.scrollLeft = textarea.scrollLeft;
        lineGutter.scrollTop = textarea.scrollTop;
    });

    // When focused: make textarea text visible, hide highlight
    textarea.addEventListener('focus', () => {
        textarea.style.color = 'rgba(209, 213, 219, 0.9)';
        highlightPre.style.display = 'none';
    });
    textarea.addEventListener('blur', () => {
        textarea.style.color = 'transparent';
        highlightPre.style.display = 'block';
        updateHighlight(textarea.value);
    });

    // Start with highlight visible, textarea text transparent
    textarea.style.color = 'transparent';

    codeScroller.appendChild(highlightPre);
    codeScroller.appendChild(textarea);
    editorWrapper.appendChild(codeScroller);
    editorContainer.appendChild(editorWrapper);
    codeArea.appendChild(editorContainer);
    body.appendChild(codeArea);
    editor.appendChild(body);

    // ── Footer ──
    const footer = document.createElement('div');
    footer.className = 'flex items-center justify-between px-5 py-2 text-[10px] flex-shrink-0';
    footer.style.cssText = 'border-top: 1px solid rgba(148,163,184,0.08); background: rgba(0,0,0,0.1);';
    const reqResults = _validateRequirements(source, tier);
    const metCount = reqResults.filter(r => r.met).length;
    footer.innerHTML = `
        <div class="flex items-center gap-3">
            <span id="editor-req-summary" class="text-gray-500">${metCount}/${reqResults.length} requirements met</span>
            <span class="text-gray-600">|</span>
            <span id="editor-line-count" class="text-gray-600">${source.split('\n').length} lines</span>
        </div>
        <div id="editor-change-indicator" class="text-gray-600" style="display: none;">Unsaved changes</div>
    `;
    editor.appendChild(footer);

    overlay.appendChild(editor);
    document.body.appendChild(overlay);

    // ── Live validation (debounced) ──
    const statusEl = editor.querySelector('#editor-status');
    const saveBtn = editor.querySelector('#editor-save-btn');
    const changeIndicator = editor.querySelector('#editor-change-indicator');
    const reqSummary = editor.querySelector('#editor-req-summary');
    const lineCount = editor.querySelector('#editor-line-count');

    let debounceTimer = null;
    textarea.addEventListener('input', () => {
        const val = textarea.value;
        hasChanges = val !== originalSource;

        // Update line numbers
        updateLineNumbers(val);
        lineCount.textContent = `${val.split('\n').length} lines`;

        // Change indicator
        if (changeIndicator) changeIndicator.style.display = hasChanges ? 'block' : 'none';
        if (changeIndicator && hasChanges) changeIndicator.style.color = '#fbbf24';

        // Enable save button
        if (saveBtn) {
            saveBtn.disabled = !hasChanges;
            saveBtn.style.opacity = hasChanges ? '1' : '0.5';
        }

        // Debounced requirements check
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            const results = _validateRequirements(val, tier);
            const met = results.filter(r => r.met).length;
            sidebar.innerHTML = _buildRequirementsSidebar(val, tier);
            if (reqSummary) reqSummary.textContent = `${met}/${results.length} requirements met`;
        }, 300);
    });

    // ── Save handler ──
    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            try {
                saveBtn.disabled = true;
                saveBtn.innerHTML = `<svg class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Saving...`;
                if (statusEl) { statusEl.textContent = 'Saving...'; statusEl.style.color = '#fbbf24'; }

                const res = await fetch(`/api/v1/extensions/${name}/source`, {
                    method: 'PUT',
                    headers: _headers(),
                    body: JSON.stringify({ source: textarea.value }),
                });

                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.error || `Save failed: ${res.status}`);
                }

                const result = await res.json();
                originalSource = textarea.value;
                hasChanges = false;

                if (changeIndicator) changeIndicator.style.display = 'none';
                saveBtn.disabled = true;
                saveBtn.style.opacity = '0.5';

                if (statusEl) {
                    statusEl.textContent = result.loaded ? 'Saved & loaded' : 'Saved (load error)';
                    statusEl.style.color = result.loaded ? '#22c55e' : '#f59e0b';
                    setTimeout(() => { statusEl.textContent = ''; }, 3000);
                }

                _notify('success', `Extension #${name} saved${result.loaded ? ' & reloaded' : ''}`);
                await loadExtensions();
                if (window.loadActivatedExtensions) window.loadActivatedExtensions();
            } catch (err) {
                _notify('error', err.message);
                if (statusEl) { statusEl.textContent = 'Save failed'; statusEl.style.color = '#ef4444'; }
            } finally {
                saveBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" /></svg> Save`;
                if (hasChanges) { saveBtn.disabled = false; saveBtn.style.opacity = '1'; }
            }
        });
    }

    // ── Close handlers ──
    const closeEditor = () => {
        if (hasChanges) {
            if (!confirm('You have unsaved changes. Close anyway?')) return;
        }
        overlay.remove();
        document.removeEventListener('keydown', escHandler);
    };
    editor.querySelectorAll('.close-btn').forEach(btn => btn.addEventListener('click', closeEditor));
    const escHandler = (e) => { if (e.key === 'Escape') closeEditor(); };
    document.addEventListener('keydown', escHandler);

    // Ctrl+S / Cmd+S to save
    textarea.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            if (saveBtn && !saveBtn.disabled) saveBtn.click();
        }
    });
}

// ── Source Viewer (delegates to editor) ──────────────────────────────────────

async function showExtensionSource(extId, displayName) {
    try {
        const data = await fetchExtensionSource(extId);
        const source = data.source || 'No source available';
        const manifest = data.manifest || {};
        const tier = manifest.extension_tier || _detectTierFromSource(source);

        // Check if user extension (editable) or built-in (read-only)
        const sourcePath = manifest._source_path || '';
        const isUserExt = sourcePath.includes('.tda/extensions');

        showExtensionEditor(extId, source, tier, false, !isUserExt);
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
