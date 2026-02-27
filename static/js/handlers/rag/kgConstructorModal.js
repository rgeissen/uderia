/**
 * Knowledge Graph Constructor Modal
 *
 * Two-step workflow:
 *   Step 1 — Generate Context: Execute an MCP prompt to retrieve database schema
 *   Step 2 — Generate Knowledge Graph: Parse schema (structural) + optional LLM enrichment (semantic)
 *
 * Outputs entities/relationships into the Knowledge Graph (GraphStore) for a selected profile.
 */

import { generateKnowledgeGraph } from '../../api.js';
import { showAppBanner } from '../../bannerSystem.js';

// ── State ────────────────────────────────────────────────────────────────────

let _overlay = null;
let _generatedContext = '';
let _executionTrace = [];

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * Open the KG Constructor modal.
 * Called from the template system Deploy button handler.
 */
export function openKgConstructorModal(template, defaults = {}) {
    _generatedContext = '';
    _executionTrace = [];
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
                        <p class="text-xs text-gray-400">Auto-populate from database schema context</p>
                    </div>
                </div>
                <button id="kg-constructor-close-btn"
                        class="text-gray-400 hover:text-white transition-colors p-1">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>

            <!-- ─── Step 1: Generate Context ─── -->
            <div id="kg-step1" class="mb-6">
                <div class="flex items-center gap-2 mb-4">
                    <span class="flex items-center justify-center w-6 h-6 rounded-full bg-purple-500/30 text-purple-300 text-xs font-bold">1</span>
                    <h4 class="text-sm font-semibold text-white">Generate Context</h4>
                </div>

                <!-- Profile selector -->
                <div class="mb-3">
                    <label class="block text-xs text-gray-400 mb-1">Target Profile</label>
                    <select id="kg-constructor-profile" class="w-full bg-gray-800 border border-gray-600 rounded-lg p-2 text-sm text-white focus:ring-2 focus:ring-purple-500 focus:border-purple-500 outline-none">
                        <option value="">Select a profile...</option>
                    </select>
                </div>

                <!-- Database name -->
                <div class="mb-3">
                    <label class="block text-xs text-gray-400 mb-1">Database Name</label>
                    <input id="kg-constructor-dbname" type="text" placeholder="e.g. fitness_db"
                           class="w-full bg-gray-800 border border-gray-600 rounded-lg p-2 text-sm text-white focus:ring-2 focus:ring-purple-500 focus:border-purple-500 outline-none" />
                </div>

                <!-- MCP context prompt -->
                <div class="mb-3">
                    <label class="block text-xs text-gray-400 mb-1">MCP Context Prompt</label>
                    <input id="kg-constructor-mcp-prompt" type="text" value="base_databaseBusinessDesc"
                           class="w-full bg-gray-800 border border-gray-600 rounded-lg p-2 text-sm text-white focus:ring-2 focus:ring-purple-500 focus:border-purple-500 outline-none" />
                    <p class="text-xs text-gray-500 mt-1">MCP prompt name to execute for schema discovery</p>
                </div>

                <!-- Generate Context button -->
                <button id="kg-constructor-gen-context-btn"
                        class="card-btn card-btn--primary w-full flex items-center justify-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                    </svg>
                    Generate Context
                </button>

                <!-- Context status -->
                <div id="kg-context-status" class="hidden mt-3 text-xs text-gray-400 flex items-center gap-2">
                    <svg class="w-4 h-4 animate-spin text-purple-400" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    <span id="kg-context-status-text">Executing MCP prompt...</span>
                </div>
            </div>

            <!-- ─── Step 2: Generate Knowledge Graph (hidden until context ready) ─── -->
            <div id="kg-step2" class="hidden">
                <div class="my-4 border-t border-white/10"></div>

                <div class="flex items-center gap-2 mb-4">
                    <span class="flex items-center justify-center w-6 h-6 rounded-full bg-purple-500/30 text-purple-300 text-xs font-bold">2</span>
                    <h4 class="text-sm font-semibold text-white">Generate Knowledge Graph</h4>
                </div>

                <!-- Context preview -->
                <div class="mb-3">
                    <label class="block text-xs text-gray-400 mb-1">Database Schema Context</label>
                    <textarea id="kg-constructor-context-preview" rows="8"
                              class="w-full bg-gray-800 border border-gray-600 rounded-lg p-3 text-xs text-gray-300 font-mono focus:ring-2 focus:ring-purple-500 focus:border-purple-500 outline-none resize-y"></textarea>
                    <p class="text-xs text-gray-500 mt-1">Review and edit the schema context before extraction</p>
                </div>

                <!-- Semantic enrichment toggle -->
                <div class="mb-4 flex items-center gap-3">
                    <input id="kg-constructor-semantic-toggle" type="checkbox" checked
                           class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-purple-500 focus:ring-purple-500 focus:ring-offset-0" />
                    <label for="kg-constructor-semantic-toggle" class="text-sm text-gray-300">
                        Include semantic enrichment
                        <span class="text-xs text-gray-500 ml-1">(business concepts, metrics, taxonomies — requires LLM)</span>
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
                    <span id="kg-generate-status-text">Parsing schema...</span>
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

    // Step 1: Generate Context
    _overlay.querySelector('#kg-constructor-gen-context-btn').addEventListener('click', _handleGenerateContext);

    // Step 2: Generate Knowledge Graph
    _overlay.querySelector('#kg-constructor-generate-btn').addEventListener('click', _handleGenerateKG);
}

// ── Profile Dropdown ─────────────────────────────────────────────────────────

function _populateProfileDropdown() {
    const select = _overlay.querySelector('#kg-constructor-profile');
    select.innerHTML = '<option value="">Select a profile...</option>';

    const profiles = window.configState?.profiles || [];
    for (const p of profiles) {
        // Only show profiles that have an MCP server (tool_enabled or genie)
        if (p.profile_type !== 'tool_enabled' && p.profile_type !== 'genie') continue;
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = `@${p.tag || p.name} (${p.profile_type === 'tool_enabled' ? 'Optimize' : 'Coordinate'})`;
        select.appendChild(opt);
    }
}

// ── Step 1: Generate Context ─────────────────────────────────────────────────

async function _handleGenerateContext() {
    const profileId = _overlay.querySelector('#kg-constructor-profile').value;
    const dbName = _overlay.querySelector('#kg-constructor-dbname').value.trim();
    const mcpPrompt = _overlay.querySelector('#kg-constructor-mcp-prompt').value.trim() || 'base_databaseBusinessDesc';

    if (!profileId) {
        showAppBanner('Please select a target profile.', 'error');
        return;
    }
    if (!dbName) {
        showAppBanner('Please enter a database name.', 'error');
        return;
    }

    const contextBtn = _overlay.querySelector('#kg-constructor-gen-context-btn');
    const statusEl = _overlay.querySelector('#kg-context-status');
    const statusText = _overlay.querySelector('#kg-context-status-text');

    try {
        // Show loading
        contextBtn.disabled = true;
        contextBtn.classList.add('opacity-50');
        statusEl.classList.remove('hidden');
        statusText.textContent = `Executing ${mcpPrompt} prompt...`;

        // Find MCP server ID from the selected profile
        const profiles = window.configState?.profiles || [];
        const profile = profiles.find(p => p.id === profileId);
        const mcpServerId = profile?.mcpServerId || profile?.mcp_server_id || '';

        // Call the execute-raw endpoint
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/prompts/${mcpPrompt}/execute-raw`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                arguments: { database_name: dbName },
                ...(mcpServerId ? { mcp_server_id: mcpServerId } : {})
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }

        const result = await response.json();

        // Extract context text
        let contextText = result.final_answer_text || '';

        // If final answer is empty or looks like JSON, try execution trace
        if (!contextText || contextText.startsWith('[') || contextText.startsWith('{')) {
            for (let i = (result.execution_trace || []).length - 1; i >= 0; i--) {
                const trace = result.execution_trace[i];
                if (trace.action?.tool_name === 'TDA_FinalReport' &&
                    trace.result?.results?.[0]?.direct_answer) {
                    contextText = trace.result.results[0].direct_answer;
                    break;
                }
            }
        }

        // Also extract detailed schema from execution trace
        let schemaDetails = '';
        for (const trace of (result.execution_trace || [])) {
            if (!trace?.action || !trace?.result) continue;
            const toolName = trace.action.tool_name || '';
            if (toolName === 'TDA_SystemLog' || toolName === 'TDA_FinalReport') continue;
            for (const item of (trace.result.results || [])) {
                const content = item?.tool_output || item?.content || item?.['Request Text'] || '';
                if (content && typeof content === 'string' && content.length > 50) {
                    schemaDetails += '\n\n' + content;
                }
            }
        }

        if (schemaDetails) {
            contextText += '\n\n=== Detailed Schema Information ===' + schemaDetails;
        }

        _generatedContext = contextText;
        _executionTrace = result.execution_trace || [];

        // Show Step 2
        statusEl.classList.add('hidden');
        const step2 = _overlay.querySelector('#kg-step2');
        step2.classList.remove('hidden');

        const preview = _overlay.querySelector('#kg-constructor-context-preview');
        preview.value = contextText;

        showAppBanner('Database context generated successfully.', 'success');

    } catch (err) {
        console.error('[KG Constructor] Generate context failed:', err);
        statusText.textContent = `Error: ${err.message}`;
        showAppBanner(`Failed to generate context: ${err.message}`, 'error');
    } finally {
        contextBtn.disabled = false;
        contextBtn.classList.remove('opacity-50');
    }
}

// ── Step 2: Generate Knowledge Graph ─────────────────────────────────────────

async function _handleGenerateKG() {
    const profileId = _overlay.querySelector('#kg-constructor-profile').value;
    const dbName = _overlay.querySelector('#kg-constructor-dbname').value.trim();
    const contextText = _overlay.querySelector('#kg-constructor-context-preview').value.trim();
    const includeSemantic = _overlay.querySelector('#kg-constructor-semantic-toggle').checked;

    if (!contextText) {
        showAppBanner('No schema context available. Run Step 1 first.', 'error');
        return;
    }

    const generateBtn = _overlay.querySelector('#kg-constructor-generate-btn');
    const statusEl = _overlay.querySelector('#kg-generate-status');
    const statusText = _overlay.querySelector('#kg-generate-status-text');

    try {
        generateBtn.disabled = true;
        generateBtn.classList.add('opacity-50');
        statusEl.classList.remove('hidden');
        statusText.textContent = 'Parsing schema structure...';

        if (includeSemantic) {
            // Update status after a short delay to show semantic phase
            setTimeout(() => {
                if (!generateBtn.disabled) return; // already done
                statusText.textContent = 'Running semantic analysis (LLM)...';
            }, 2000);
        }

        const result = await generateKnowledgeGraph(
            profileId, contextText, _executionTrace, dbName, includeSemantic
        );

        // Hide status spinner
        statusEl.classList.add('hidden');

        // Show results
        const resultsEl = _overlay.querySelector('#kg-results');
        const resultsBody = _overlay.querySelector('#kg-results-body');
        resultsEl.classList.remove('hidden');

        const s = result.structural || {};
        const sem = result.semantic || {};
        const t = result.total || {};

        resultsBody.innerHTML = `
            <div class="flex justify-between py-1 border-b border-white/5">
                <span class="text-gray-400">Structural</span>
                <span class="text-green-400">${s.entities_added || 0} entities, ${s.relationships_added || 0} relationships</span>
            </div>
            ${includeSemantic ? `
            <div class="flex justify-between py-1 border-b border-white/5">
                <span class="text-gray-400">Semantic</span>
                <span class="text-purple-400">${sem.entities_added || 0} entities, ${sem.relationships_added || 0} relationships</span>
            </div>` : ''}
            <div class="flex justify-between py-1 font-bold">
                <span class="text-white">Total</span>
                <span class="text-white">${t.entities_added || 0} entities, ${t.relationships_added || 0} relationships</span>
            </div>
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
    // Reset step 2 and results to hidden
    const step2 = _overlay.querySelector('#kg-step2');
    const results = _overlay.querySelector('#kg-results');
    const contextStatus = _overlay.querySelector('#kg-context-status');
    const genStatus = _overlay.querySelector('#kg-generate-status');

    step2.classList.add('hidden');
    results.classList.add('hidden');
    contextStatus.classList.add('hidden');
    genStatus.classList.add('hidden');

    // Clear previous values
    _overlay.querySelector('#kg-constructor-context-preview').value = '';
    _overlay.querySelector('#kg-constructor-semantic-toggle').checked = true;

    // Re-enable buttons
    const contextBtn = _overlay.querySelector('#kg-constructor-gen-context-btn');
    const generateBtn = _overlay.querySelector('#kg-constructor-generate-btn');
    contextBtn.disabled = false;
    contextBtn.classList.remove('opacity-50');
    generateBtn.disabled = false;
    generateBtn.classList.remove('opacity-50');
}
