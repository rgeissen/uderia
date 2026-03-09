/**
 * Knowledge Graph Constructor Modal
 *
 * Single-step workflow: Select profile + enter database name → agent-driven
 * system session discovers structure via MCP tools and populates the KG.
 *
 * Turn 1: Agent discovers tables/columns via MCP tools → structural entities
 * Turn 2 (optional): Agent analyzes business concepts → semantic entities
 *
 * The system session is visible in the session gallery (purple border + gear badge).
 */

import { generateKnowledgeGraph } from '../../api.js';
import { showAppBanner } from '../../bannerSystem.js';

// ── State ────────────────────────────────────────────────────────────────────

let _overlay = null;

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * Open the KG Constructor modal.
 * Called from the template system Deploy button handler.
 */
export function openKgConstructorModal(template, defaults = {}) {
    _ensureModalExists();
    _populateProfileDropdown();
    _resetModalState();
    _showModal();
}

// ── Modal DOM Construction ───────────────────────────────────────────────────

function _ensureModalExists() {
    if (_overlay) return;

    _overlay = document.createElement('div');
    _overlay.id = 'kg-constructor-modal-overlay';
    _overlay.className = 'fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm hidden opacity-0 transition-opacity duration-200';

    _overlay.innerHTML = `
        <div id="kg-constructor-modal-content"
             class="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto p-8 transform scale-95 opacity-0 transition-all duration-200">

            <!-- Header -->
            <div class="flex items-center justify-between mb-6">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 bg-purple-500/20 rounded-lg flex items-center justify-center">
                        <svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                            <circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" />
                            <path stroke-linecap="round" stroke-linejoin="round" d="M12 7v4m-5.2 5.8L11 13m2 0l4.2 3.8" />
                        </svg>
                    </div>
                    <div>
                        <h3 class="text-xl font-bold text-white">Knowledge Graph Constructor</h3>
                        <p class="text-xs text-gray-400">Agent-driven database structure discovery</p>
                    </div>
                </div>
                <button id="kg-constructor-close-btn"
                        class="text-gray-400 hover:text-white transition-colors p-1">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>

            <!-- Configuration -->
            <div class="mb-6">
                <!-- Profile selector -->
                <div class="mb-3">
                    <label class="block text-xs text-gray-400 mb-1">Target Profile</label>
                    <select id="kg-constructor-profile" class="w-full p-2 text-sm text-white rounded-lg outline-none cursor-pointer appearance-none" style="background: rgba(30, 30, 40, 0.8); border: 1px solid rgba(147, 51, 234, 0.3); background-image: url('data:image/svg+xml;charset=UTF-8,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 12 12%22%3E%3Cpath fill=%22%239ca3af%22 d=%22M2 4l4 4 4-4%22/%3E%3C/svg%3E'); background-repeat: no-repeat; background-position: right 0.75rem center;">
                        <option value="">Select a profile...</option>
                    </select>
                </div>

                <!-- Database name -->
                <div class="mb-3">
                    <label class="block text-xs text-gray-400 mb-1">Database Name</label>
                    <input id="kg-constructor-dbname" type="text" placeholder="e.g. fitness_db"
                           class="w-full bg-gray-800 border border-gray-600 rounded-lg p-2 text-sm text-white focus:ring-2 focus:ring-purple-500 focus:border-purple-500 outline-none" />
                </div>

                <!-- Business analysis toggle -->
                <div class="mb-4 flex items-center gap-3">
                    <input id="kg-constructor-semantic-toggle" type="checkbox" checked
                           class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-purple-500 focus:ring-purple-500 focus:ring-offset-0" />
                    <label for="kg-constructor-semantic-toggle" class="text-sm text-gray-300">
                        Include business analysis
                        <span class="text-xs text-gray-500 ml-1">(business concepts, metrics, taxonomies)</span>
                    </label>
                </div>

                <!-- Generate KG button -->
                <button id="kg-constructor-generate-btn"
                        class="card-btn card-btn--primary w-full flex items-center justify-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" />
                        <path stroke-linecap="round" stroke-linejoin="round" d="M12 7v4m-5.2 5.8L11 13m2 0l4.2 3.8" />
                    </svg>
                    Generate Knowledge Graph
                </button>

                <!-- Generation status -->
                <div id="kg-generate-status" class="hidden mt-3 text-xs text-gray-400 flex items-center gap-2">
                    <svg class="w-4 h-4 animate-spin text-purple-400" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    <span id="kg-generate-status-text">Initializing...</span>
                </div>
            </div>

            <!-- ─── Results (hidden until generation complete) ─── -->
            <div id="kg-results" class="hidden">
                <div class="my-4 border-t border-white/10"></div>

                <div class="glass-panel rounded-xl p-4">
                    <h4 class="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                        <svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                        Knowledge Graph Generated
                    </h4>
                    <div id="kg-results-body" class="space-y-2 text-xs text-gray-300 font-mono"></div>
                </div>

                <button id="kg-constructor-done-btn"
                        class="mt-4 card-btn card-btn--neutral w-full">
                    Close
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(_overlay);
    _attachEventListeners();
}

// ── Event Listeners ──────────────────────────────────────────────────────────

function _attachEventListeners() {
    // Close button
    _overlay.querySelector('#kg-constructor-close-btn').addEventListener('click', _hideModal);

    // Overlay backdrop click
    _overlay.addEventListener('click', (e) => {
        if (e.target === _overlay) _hideModal();
    });

    // Done button (in results section)
    _overlay.querySelector('#kg-constructor-done-btn').addEventListener('click', _hideModal);

    // Generate Knowledge Graph
    _overlay.querySelector('#kg-constructor-generate-btn').addEventListener('click', _handleGenerateKG);
}

// ── Profile Dropdown ─────────────────────────────────────────────────────────

function _populateProfileDropdown() {
    const select = _overlay.querySelector('#kg-constructor-profile');
    select.innerHTML = '<option value="">Select a profile...</option>';

    const ifocLabels = {
        'llm_only': 'Ideate', 'rag_focused': 'Focus',
        'tool_enabled': 'Optimize', 'genie': 'Coordinate'
    };

    const profiles = window.configState?.profiles || [];
    for (const p of profiles) {
        // Require MCP server + tool-calling capability (tool_enabled or conversation with tools)
        if (!p.mcpServerId) continue;
        const hasToolCalling = p.profile_type === 'tool_enabled' || (p.profile_type === 'llm_only' && p.useMcpTools);
        if (!hasToolCalling) continue;
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = `@${p.tag || p.name} (${ifocLabels[p.profile_type] || p.profile_type})`;
        select.appendChild(opt);
    }
}

// ── Generate Knowledge Graph ─────────────────────────────────────────────────

async function _handleGenerateKG() {
    const profileId = _overlay.querySelector('#kg-constructor-profile').value;
    const dbName = _overlay.querySelector('#kg-constructor-dbname').value.trim();
    const includeSemantic = _overlay.querySelector('#kg-constructor-semantic-toggle').checked;

    if (!profileId) {
        showAppBanner('Please select a target profile.', 'error');
        return;
    }
    if (!dbName) {
        showAppBanner('Please enter a database name.', 'error');
        return;
    }

    const generateBtn = _overlay.querySelector('#kg-constructor-generate-btn');
    const statusEl = _overlay.querySelector('#kg-generate-status');
    const statusText = _overlay.querySelector('#kg-generate-status-text');

    // Progressive status messages
    const statusMessages = [
        { delay: 0, text: 'Creating system session...' },
        { delay: 3000, text: 'Discovering database structure via MCP tools...' },
        { delay: 15000, text: 'Agent is calling tools to list tables and columns...' },
        { delay: 30000, text: 'Parsing structural entities from tool results...' },
    ];
    if (includeSemantic) {
        statusMessages.push(
            { delay: 40000, text: 'Running business analysis (Turn 2)...' },
            { delay: 55000, text: 'Extracting semantic entities...' },
        );
    }
    statusMessages.push({ delay: 70000, text: 'Finalizing knowledge graph...' });

    const timers = [];

    try {
        generateBtn.disabled = true;
        generateBtn.classList.add('opacity-50');
        statusEl.classList.remove('hidden');

        // Schedule progressive status updates
        for (const msg of statusMessages) {
            const timer = setTimeout(() => {
                if (!generateBtn.disabled) return; // already done
                statusText.textContent = msg.text;
            }, msg.delay);
            timers.push(timer);
        }

        const result = await generateKnowledgeGraph(profileId, dbName, includeSemantic);

        // Clear timers
        timers.forEach(t => clearTimeout(t));

        // Hide status spinner
        statusEl.classList.add('hidden');

        // Show results
        const resultsEl = _overlay.querySelector('#kg-results');
        const resultsBody = _overlay.querySelector('#kg-results-body');
        resultsEl.classList.remove('hidden');

        const s = result.structural || {};
        const sem = result.semantic || {};
        const t = result.total || {};
        const sessionId = result.session_id || '';

        resultsBody.innerHTML = `
            <div class="flex justify-between py-1 border-b border-white/5">
                <span class="text-gray-400">Structural (tables, columns)</span>
                <span class="text-green-400">${s.entities_added || 0} entities, ${s.relationships_added || 0} relationships</span>
            </div>
            ${includeSemantic ? `
            <div class="flex justify-between py-1 border-b border-white/5">
                <span class="text-gray-400">Semantic (business concepts)</span>
                <span class="text-purple-400">${sem.entities_added || 0} entities, ${sem.relationships_added || 0} relationships</span>
            </div>` : ''}
            ${result.phase3_relationships ? `
            <div class="flex justify-between py-1 border-b border-white/5">
                <span class="text-gray-400">Gap-fill relationships</span>
                <span class="text-blue-400">${result.phase3_relationships}</span>
            </div>` : ''}
            <div class="flex justify-between py-1 font-bold">
                <span class="text-white">Total</span>
                <span class="text-white">${t.entities_added || 0} entities, ${t.relationships_added || 0} relationships</span>
            </div>
            ${sessionId ? `
            <div class="flex justify-between py-1 mt-2 border-t border-white/10 pt-2">
                <span class="text-gray-500">System session</span>
                <span class="text-indigo-400 text-xs cursor-pointer hover:underline" onclick="document.querySelector('[data-session-id=&quot;${sessionId}&quot;]')?.click()" title="Click to view the discovery session">${sessionId.substring(0, 8)}...</span>
            </div>` : ''}
        `;

        const statusLabel = result.status === 'partial' ? 'partially completed' : 'completed';
        showAppBanner(
            `Knowledge Graph ${statusLabel}: ${t.entities_added || 0} entities, ${t.relationships_added || 0} relationships imported.`,
            result.status === 'partial' ? 'info' : 'success'
        );

        // Refresh KG cards in the Intelligence tab
        try {
            const { loadKnowledgeGraphsIntelligenceTab } = await import('../knowledgeGraphPanelHandler.js');
            if (typeof loadKnowledgeGraphsIntelligenceTab === 'function') {
                loadKnowledgeGraphsIntelligenceTab();
            }
        } catch (_) { /* non-critical */ }

    } catch (err) {
        timers.forEach(t => clearTimeout(t));
        console.error('[KG Constructor] Generation failed:', err);
        statusText.textContent = `Error: ${err.message}`;
        showAppBanner(`Knowledge Graph generation failed: ${err.message}`, 'error');
    } finally {
        generateBtn.disabled = false;
        generateBtn.classList.remove('opacity-50');
    }
}

// ── Modal Show/Hide ──────────────────────────────────────────────────────────

function _showModal() {
    _overlay.classList.remove('hidden');
    requestAnimationFrame(() => {
        _overlay.classList.remove('opacity-0');
        const content = _overlay.querySelector('#kg-constructor-modal-content');
        content.classList.remove('scale-95', 'opacity-0');
        content.classList.add('scale-100', 'opacity-100');
    });
}

function _hideModal() {
    const content = _overlay.querySelector('#kg-constructor-modal-content');
    content.classList.add('scale-95', 'opacity-0');
    content.classList.remove('scale-100', 'opacity-100');
    _overlay.classList.add('opacity-0');
    setTimeout(() => _overlay.classList.add('hidden'), 200);
}

function _resetModalState() {
    // Reset results to hidden
    const results = _overlay.querySelector('#kg-results');
    const genStatus = _overlay.querySelector('#kg-generate-status');

    results.classList.add('hidden');
    genStatus.classList.add('hidden');

    // Reset toggle
    _overlay.querySelector('#kg-constructor-semantic-toggle').checked = true;

    // Re-enable button
    const generateBtn = _overlay.querySelector('#kg-constructor-generate-btn');
    generateBtn.disabled = false;
    generateBtn.classList.remove('opacity-50');
}
