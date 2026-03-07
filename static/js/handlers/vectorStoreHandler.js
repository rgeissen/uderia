/**
 * vectorStoreHandler.js
 *
 * Manages centralized vector store configurations in the Configuration → Vector Stores tab.
 * IIFE pattern (same as agentPackHandler.js) — exposes via window.vectorStoreHandler.
 */
(function () {
    'use strict';

    let configurations = [];
    let loaded = false;
    let connectionTested = false;
    let activeBackendFilter = 'all';
    let allowedBackends = ['chromadb', 'teradata', 'qdrant']; // governance — updated on load

    const vectorStoreColors = {
        'all':      '#6b7280',
        'chromadb': '#22c55e',
        'teradata': '#F15F22',
        'qdrant':   '#a78bfa',
    };

    // ── API helpers ──────────────────────────────────────────────────────────

    function getAuthHeaders() {
        const token = localStorage.getItem('tda_auth_token');
        return {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        };
    }

    async function apiGet(url) {
        const res = await fetch(url, { headers: getAuthHeaders() });
        return res.json();
    }

    async function apiPost(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify(body)
        });
        return { status: res.status, data: await res.json() };
    }

    async function apiPut(url, body) {
        const res = await fetch(url, {
            method: 'PUT',
            headers: getAuthHeaders(),
            body: JSON.stringify(body)
        });
        return { status: res.status, data: await res.json() };
    }

    async function apiDelete(url) {
        const res = await fetch(url, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        return { status: res.status, data: await res.json() };
    }

    // ── Load & Render ────────────────────────────────────────────────────────

    async function loadVectorStoreConfigurations() {
        const container = document.getElementById('vector-stores-container');
        if (!container) return;

        container.innerHTML = '<p class="text-gray-400 text-center py-8">Loading vector stores...</p>';

        try {
            // Fetch allowed backends for current user's tier
            try {
                const govResult = await apiGet('/api/v1/vectorstore/allowed-backends');
                if (govResult.status === 'success' && Array.isArray(govResult.allowed_backends)) {
                    allowedBackends = govResult.allowed_backends;
                }
            } catch (_) { /* governance endpoint unavailable — allow all */ }

            const result = await apiGet('/api/v1/vectorstore/configurations');
            if (result.status === 'success') {
                configurations = result.configurations || [];
                resetBackendTabs();
                renderConfigurations(container);
                loaded = true;
            } else {
                container.innerHTML = `<p class="text-red-400 text-center py-8">Error: ${result.message}</p>`;
            }
        } catch (e) {
            container.innerHTML = `<p class="text-red-400 text-center py-8">Failed to load vector stores: ${e.message}</p>`;
        }
    }

    function renderConfigurations(container) {
        const filtered = activeBackendFilter === 'all'
            ? configurations
            : configurations.filter(c => c.backend_type === activeBackendFilter);

        if (filtered.length === 0) {
            const filterLabel = activeBackendFilter === 'all' ? '' : ` for ${activeBackendFilter}`;
            container.innerHTML = `
                <div class="flex flex-col items-center justify-center py-16 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-16 w-16 text-gray-600 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                    </svg>
                    <p class="text-gray-400 text-lg font-medium">No vector stores configured${filterLabel}</p>
                    <p class="text-gray-500 text-sm mt-2">Click "Add Vector Store" to create a configuration.</p>
                </div>`;
            return;
        }

        container.innerHTML = filtered.map(config => renderCard(config)).join('');
    }

    function renderCard(config) {
        const isDefault = config.id === 'vs-default-chromadb' || config.id === 'vs-default-teradata' || config.id === 'vs-default-qdrant';
        const isChromaDB = config.backend_type === 'chromadb';
        const isQdrant = config.backend_type === 'qdrant';
        const collCount = config.collection_count || 0;
        const isRestricted = !allowedBackends.includes(config.backend_type);

        let typeBadge;
        if (isChromaDB) {
            typeBadge = '<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">ChromaDB</span>';
        } else if (isQdrant) {
            typeBadge = '<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30">Qdrant Cloud</span>';
        } else {
            typeBadge = '<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30">Teradata</span>';
        }

        const defaultBadge = isDefault
            ? '<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-500/20 text-gray-400 border border-gray-500/30">Default</span>'
            : '';

        const restrictedBadge = isRestricted
            ? '<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30">Restricted</span>'
            : '';

        const host = config.backend_config?.host || config.backend_config?.url || '';
        const database = config.backend_config?.database || '';
        let details;
        if (isChromaDB) {
            details = '<span class="text-gray-500">Local embedded database</span>';
        } else if (isQdrant) {
            details = `<span class="text-gray-400">${escapeHtml(host)}</span>`;
        } else {
            details = `<span class="text-gray-400">${escapeHtml(host)}${database ? ' / ' + escapeHtml(database) : ''}</span>`;
        }

        const iconBg = isChromaDB ? 'bg-green-500/10' : (isQdrant ? 'bg-purple-500/10' : 'bg-blue-500/10');
        const iconColor = isChromaDB ? 'text-green-400' : (isQdrant ? 'text-purple-400' : 'text-blue-400');

        const actions = [];
        if (isRestricted) {
            actions.push('<span class="text-xs text-red-400 italic">Backend restricted by admin</span>');
        } else {
            if (!isChromaDB) {
                actions.push(`<button onclick="window.vectorStoreHandler.testConnection('${config.id}')" class="px-3 py-1.5 rounded-lg border border-white/10 text-gray-300 hover:bg-white/5 text-sm transition-colors" title="Test connection">Test</button>`);
            }
            actions.push(`<button onclick="window.vectorStoreHandler.showEditModal('${config.id}')" class="px-3 py-1.5 rounded-lg border border-white/10 text-gray-300 hover:bg-white/5 text-sm transition-colors">Edit</button>`);
            if (!isDefault) {
                actions.push(`<button onclick="window.vectorStoreHandler.deleteConfig('${config.id}')" class="px-3 py-1.5 rounded-lg border border-red-500/30 text-red-400 hover:bg-red-500/10 text-sm transition-colors">Delete</button>`);
            }
        }

        return `
            <div class="glass-panel rounded-xl p-4 border border-white/5 hover:border-white/10 transition-colors ${isRestricted ? 'opacity-50' : ''}" data-vs-id="${config.id}">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-lg flex items-center justify-center ${iconBg}">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 ${iconColor}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                            </svg>
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="text-white font-medium">${escapeHtml(config.name)}</span>
                                ${typeBadge}
                                ${defaultBadge}
                                ${restrictedBadge}
                            </div>
                            <div class="text-sm mt-0.5">${details}</div>
                            <div class="text-xs text-gray-500 mt-0.5">${collCount} collection${collCount !== 1 ? 's' : ''}</div>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        ${actions.join('')}
                    </div>
                </div>
            </div>`;
    }

    // ── Modal ────────────────────────────────────────────────────────────────

    function showAddModal() {
        document.getElementById('vector-store-modal-title').textContent = 'Add Vector Store';
        document.getElementById('vs-edit-id').value = '';
        document.getElementById('vs-name').value = '';
        const backendSelect = document.getElementById('vs-backend-type');
        backendSelect.value = 'chromadb';
        backendSelect.disabled = false;

        // Disable backend options restricted by governance
        Array.from(backendSelect.options).forEach(opt => {
            const restricted = !allowedBackends.includes(opt.value);
            opt.disabled = restricted;
            opt.textContent = opt.textContent.replace(/ \(Restricted\)$/, '');
            if (restricted) opt.textContent += ' (Restricted)';
        });
        // If current selection is restricted, pick first allowed
        if (!allowedBackends.includes(backendSelect.value)) {
            const firstAllowed = Array.from(backendSelect.options).find(o => !o.disabled);
            if (firstAllowed) backendSelect.value = firstAllowed.value;
        }

        clearRemoteFields();
        connectionTested = false;
        clearTestResults();
        toggleBackendFields();
        document.getElementById('vector-store-modal').classList.remove('hidden');
    }

    async function showEditModal(configId) {
        document.getElementById('vector-store-modal-title').textContent = 'Edit Vector Store';
        document.getElementById('vs-edit-id').value = configId;

        try {
            const result = await apiGet(`/api/v1/vectorstore/configurations/${configId}`);
            if (result.status !== 'success') return;

            const config = result.configuration;
            document.getElementById('vs-name').value = config.name || '';
            document.getElementById('vs-backend-type').value = config.backend_type || 'chromadb';
            document.getElementById('vs-backend-type').disabled = (configId === 'vs-default-chromadb' || configId === 'vs-default-teradata' || configId === 'vs-default-qdrant');

            const bc = config.backend_config || {};
            const creds = config.credentials || {};
            document.getElementById('vs-host').value = bc.host || '';
            document.getElementById('vs-base-url').value = bc.base_url || '';
            document.getElementById('vs-database').value = bc.database || '';
            document.getElementById('vs-username').value = creds.username || '';
            document.getElementById('vs-password').value = creds.password || '';
            document.getElementById('vs-pat-token').value = creds.pat_token || '';
            document.getElementById('vs-pem-key-name').value = creds.pem_key_name || '';
            document.getElementById('vs-pem-content').value = creds.pem_content || '';
            // Qdrant fields
            document.getElementById('vs-qdrant-url').value = bc.url || '';
            document.getElementById('vs-qdrant-api-key').value = creds.api_key || '';
            document.getElementById('vs-qdrant-grpc').checked = !!bc.prefer_grpc;
            // Existing saved config — mark as tested so user can save without re-testing
            // unless they change credentials (tracked by input listeners)
            connectionTested = (config.backend_type === 'teradata' || config.backend_type === 'qdrant');
            clearTestResults();
            toggleBackendFields();
            // Restore embedding model from backend_config (after toggleBackendFields populates options)
            if (bc.embedding_model) {
                const embSel = document.getElementById('vs-embedding-model');
                if (embSel && [...embSel.options].some(o => o.value === bc.embedding_model)) {
                    embSel.value = bc.embedding_model;
                }
            }
            document.getElementById('vector-store-modal').classList.remove('hidden');
        } catch (e) {
            showToast(`Failed to load configuration: ${e.message}`, 'error');
        }
    }

    function closeModal() {
        document.getElementById('vector-store-modal').classList.add('hidden');
    }

    function clearRemoteFields() {
        ['vs-host', 'vs-base-url', 'vs-database', 'vs-username', 'vs-password',
         'vs-pat-token', 'vs-pem-key-name', 'vs-pem-content',
         'vs-qdrant-url', 'vs-qdrant-api-key'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        const grpc = document.getElementById('vs-qdrant-grpc');
        if (grpc) grpc.checked = false;
    }

    function toggleBackendFields() {
        const backendType = document.getElementById('vs-backend-type').value;
        const teradataFields = document.getElementById('vs-teradata-fields');
        const qdrantFields = document.getElementById('vs-qdrant-fields');
        if (teradataFields) teradataFields.classList.toggle('hidden', backendType !== 'teradata');
        if (qdrantFields) qdrantFields.classList.toggle('hidden', backendType !== 'qdrant');
        const testBtn = document.getElementById('vs-test-btn');
        if (testBtn) testBtn.classList.toggle('hidden', backendType === 'chromadb');
        // Update embedding model options for selected backend
        updateEmbeddingOptions(backendType);
        // Reset test state when switching backend type
        connectionTested = false;
        clearTestResults();
    }

    function updateEmbeddingOptions(backendType) {
        const sel = document.getElementById('vs-embedding-model');
        if (!sel) return;
        const prev = sel.value;
        if (backendType === 'teradata') {
            sel.innerHTML =
                '<option value="amazon.titan-embed-text-v1">amazon.titan-embed-text-v1 (AWS Bedrock)</option>' +
                '<option value="amazon.titan-embed-text-v2:0">amazon.titan-embed-text-v2:0 (AWS Bedrock v2)</option>' +
                '<option value="text-embedding-ada-002">text-embedding-ada-002 (Azure OpenAI)</option>';
        } else {
            sel.innerHTML =
                '<option value="all-MiniLM-L6-v2">all-MiniLM-L6-v2 (fast, lightweight)</option>' +
                '<option value="all-mpnet-base-v2">all-mpnet-base-v2 (balanced)</option>' +
                '<option value="all-distilroberta-v1">all-distilroberta-v1 (high quality)</option>';
        }
        // Restore previous selection if still available
        if ([...sel.options].some(o => o.value === prev)) sel.value = prev;
    }

    function clearTestResults() {
        const el = document.getElementById('vs-test-results');
        if (el) {
            el.classList.add('hidden');
            el.innerHTML = '';
        }
    }

    // ── Modal Test Connection ─────────────────────────────────────────────────

    async function testModalConnection() {
        const backendType = document.getElementById('vs-backend-type').value;
        if (backendType === 'qdrant') {
            return testQdrantConnection();
        }
        const host = document.getElementById('vs-host').value.trim();
        const baseUrl = document.getElementById('vs-base-url').value.trim();
        const database = document.getElementById('vs-database').value.trim();
        const username = document.getElementById('vs-username').value.trim();
        const password = document.getElementById('vs-password').value.trim();
        const patToken = document.getElementById('vs-pat-token').value.trim();
        const pemKeyName = document.getElementById('vs-pem-key-name').value.trim();
        const pemContent = document.getElementById('vs-pem-content').value.trim();

        // Client-side validation
        if (!host) {
            showTestResult(false, 'Host is required.');
            return;
        }
        if (!(username && password) && !patToken) {
            showTestResult(false, 'Provide username/password or a PAT token.');
            return;
        }
        if (pemContent && !pemKeyName) {
            showTestResult(false, 'PEM Key Name is required when providing PEM content (the key name from VantageCloud Lake Console).');
            return;
        }

        const testBtn = document.getElementById('vs-test-btn');
        const originalText = testBtn.textContent;
        testBtn.textContent = 'Testing...';
        testBtn.disabled = true;
        clearTestResults();

        const payload = {
            backend_type: 'teradata',
            backend_config: {},
            credentials: {}
        };
        if (host) payload.backend_config.host = host;
        if (baseUrl) payload.backend_config.base_url = baseUrl;
        if (database) payload.backend_config.database = database;
        if (username) payload.credentials.username = username;
        if (password) payload.credentials.password = password;
        if (patToken) payload.credentials.pat_token = patToken;
        if (pemKeyName) payload.credentials.pem_key_name = pemKeyName;
        if (pemContent) payload.credentials.pem_content = pemContent;

        try {
            const result = await apiPost('/api/v1/vectorstore/test-connection', payload);
            if (result.data.status === 'success') {
                connectionTested = true;
                showTestResult(true, result.data.message || 'Connection successful');
            } else {
                connectionTested = false;
                showTestResult(false, result.data.message || 'Connection failed');
            }
        } catch (e) {
            connectionTested = false;
            showTestResult(false, `Test failed: ${e.message}`);
        } finally {
            testBtn.textContent = originalText;
            testBtn.disabled = false;
        }
    }

    function showTestResult(success, message) {
        const el = document.getElementById('vs-test-results');
        if (!el) return;
        el.classList.remove('hidden');
        if (success) {
            el.className = 'rounded-lg p-3 text-sm bg-green-500/10 border border-green-500/30 text-green-400';
            el.innerHTML = `<span class="mr-1">&#10003;</span> ${escapeHtml(message)}`;
        } else {
            el.className = 'rounded-lg p-3 text-sm bg-red-500/10 border border-red-500/30 text-red-400';
            el.innerHTML = `<span class="mr-1">&#10007;</span> ${escapeHtml(message)}`;
        }
    }

    // ── Qdrant Cloud Test Connection ─────────────────────────────────────────

    async function testQdrantConnection() {
        const url = document.getElementById('vs-qdrant-url').value.trim();
        const apiKey = document.getElementById('vs-qdrant-api-key').value.trim();
        const preferGrpc = document.getElementById('vs-qdrant-grpc').checked;

        if (!url) { showTestResult(false, 'Qdrant Cloud URL is required.'); return; }
        if (!apiKey) { showTestResult(false, 'API Key is required.'); return; }

        const testBtn = document.getElementById('vs-test-btn');
        const originalText = testBtn.textContent;
        testBtn.textContent = 'Testing...';
        testBtn.disabled = true;
        clearTestResults();

        try {
            const result = await apiPost('/api/v1/vectorstore/test-connection', {
                backend_type: 'qdrant',
                backend_config: { url, prefer_grpc: preferGrpc },
                credentials: { api_key: apiKey }
            });
            if (result.data.status === 'success') {
                connectionTested = true;
                showTestResult(true, result.data.message || 'Connection successful');
            } else {
                connectionTested = false;
                showTestResult(false, result.data.message || 'Connection failed');
            }
        } catch (e) {
            connectionTested = false;
            showTestResult(false, `Test failed: ${e.message}`);
        } finally {
            testBtn.textContent = originalText;
            testBtn.disabled = false;
        }
    }

    // ── Credential change tracking ────────────────────────────────────────────

    function initCredentialChangeTracking() {
        const credentialFields = ['vs-host', 'vs-username', 'vs-password', 'vs-pat-token', 'vs-pem-key-name', 'vs-pem-content', 'vs-qdrant-url', 'vs-qdrant-api-key'];
        credentialFields.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', () => {
                    connectionTested = false;
                    clearTestResults();
                });
            }
        });
    }

    // ── Backend Type Tabs ──────────────────────────────────────────────────

    function initBackendTabs() {
        const tabs = document.querySelectorAll('.vs-backend-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                activeBackendFilter = tab.dataset.backend;
                tabs.forEach(t => {
                    if (t === tab) {
                        t.classList.remove('text-gray-400', 'border-transparent', 'hover:border-white/20');
                        t.classList.add('text-white');
                        t.style.borderColor = vectorStoreColors[t.dataset.backend] || '#6b7280';
                    } else {
                        t.classList.remove('text-white');
                        t.classList.add('text-gray-400', 'border-transparent', 'hover:border-white/20');
                        t.style.borderColor = '';
                    }
                });
                const container = document.getElementById('vector-stores-container');
                if (container) renderConfigurations(container);
            });
        });
    }

    function resetBackendTabs() {
        activeBackendFilter = 'all';
        const tabs = document.querySelectorAll('.vs-backend-tab');
        tabs.forEach(t => {
            if (t.dataset.backend === 'all') {
                t.classList.remove('text-gray-400', 'border-transparent', 'hover:border-white/20');
                t.classList.add('text-white');
                t.style.borderColor = vectorStoreColors['all'];
            } else {
                t.classList.remove('text-white');
                t.classList.add('text-gray-400', 'border-transparent', 'hover:border-white/20');
                t.style.borderColor = '';
            }
        });
    }

    // ── Form Submit ──────────────────────────────────────────────────────────

    function initForm() {
        const form = document.getElementById('vector-store-form');
        if (!form) return;

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const editId = document.getElementById('vs-edit-id').value;
            const name = document.getElementById('vs-name').value.trim();
            const backendType = document.getElementById('vs-backend-type').value;

            if (!name) {
                showToast('Name is required', 'error');
                return;
            }

            const payload = { name, backend_type: backendType };

            // Embedding model applies to all backend types
            const embeddingModel = document.getElementById('vs-embedding-model')?.value;

            if (backendType === 'teradata') {
                payload.backend_config = {
                    host: document.getElementById('vs-host').value.trim(),
                    base_url: document.getElementById('vs-base-url').value.trim(),
                    database: document.getElementById('vs-database').value.trim(),
                };
                // Remove empty values
                Object.keys(payload.backend_config).forEach(k => {
                    if (!payload.backend_config[k]) delete payload.backend_config[k];
                });

                const username = document.getElementById('vs-username').value.trim();
                const password = document.getElementById('vs-password').value.trim();
                const patToken = document.getElementById('vs-pat-token').value.trim();
                const pemKeyName = document.getElementById('vs-pem-key-name').value.trim();
                const pemContent = document.getElementById('vs-pem-content').value.trim();
                if (username || password || patToken || pemContent) {
                    payload.credentials = {};
                    if (username) payload.credentials.username = username;
                    if (password) payload.credentials.password = password;
                    if (patToken) payload.credentials.pat_token = patToken;
                    if (pemKeyName) payload.credentials.pem_key_name = pemKeyName;
                    if (pemContent) payload.credentials.pem_content = pemContent;
                }

                // Gate: must test connection before saving Teradata credentials
                if (payload.credentials && !connectionTested) {
                    showToast('Please test the connection before saving.', 'error');
                    const testBtn = document.getElementById('vs-test-btn');
                    if (testBtn) {
                        testBtn.classList.add('ring-2', 'ring-blue-400');
                        setTimeout(() => testBtn.classList.remove('ring-2', 'ring-blue-400'), 2000);
                    }
                    return;
                }

                if (connectionTested) {
                    payload.connection_tested = true;
                }
            } else if (backendType === 'qdrant') {
                const url = document.getElementById('vs-qdrant-url').value.trim();
                const apiKey = document.getElementById('vs-qdrant-api-key').value.trim();
                const preferGrpc = document.getElementById('vs-qdrant-grpc').checked;

                payload.backend_config = { url };
                if (preferGrpc) payload.backend_config.prefer_grpc = true;

                if (apiKey) {
                    payload.credentials = { api_key: apiKey };
                }

                // Gate: must test connection before saving
                if (payload.credentials && !connectionTested) {
                    showToast('Please test the connection before saving.', 'error');
                    const testBtn = document.getElementById('vs-test-btn');
                    if (testBtn) {
                        testBtn.classList.add('ring-2', 'ring-blue-400');
                        setTimeout(() => testBtn.classList.remove('ring-2', 'ring-blue-400'), 2000);
                    }
                    return;
                }

                if (connectionTested) {
                    payload.connection_tested = true;
                }
            } else {
                payload.backend_config = {};
            }

            // Inject embedding model into backend_config for all backends
            if (embeddingModel) {
                if (!payload.backend_config) payload.backend_config = {};
                payload.backend_config.embedding_model = embeddingModel;
            }

            try {
                let result;
                if (editId) {
                    result = await apiPut(`/api/v1/vectorstore/configurations/${editId}`, payload);
                } else {
                    const suffix = Math.random().toString(36).substring(2, 10);
                    payload.id = `vs-${Date.now()}-${suffix}`;
                    result = await apiPost('/api/v1/vectorstore/configurations', payload);
                }

                if (result.data.status === 'success') {
                    showToast(editId ? 'Vector store updated' : 'Vector store created', 'success');
                    closeModal();
                    await loadVectorStoreConfigurations();
                } else {
                    showToast(result.data.message || 'Failed to save', 'error');
                }
            } catch (e) {
                showToast(`Error: ${e.message}`, 'error');
            }
        });

        initCredentialChangeTracking();
        initBackendTabs();
    }

    // ── Delete ───────────────────────────────────────────────────────────────

    async function deleteConfig(configId) {
        const config = configurations.find(c => c.id === configId);
        const name = config ? config.name : configId;

        if (typeof window.showConfirmation === 'function') {
            window.showConfirmation(
                `Delete "${name}"?`,
                'This will remove the vector store configuration. Collections using it will fall back to inline configuration.',
                async () => {
                    await performDelete(configId);
                }
            );
        } else if (confirm(`Delete "${name}"?`)) {
            await performDelete(configId);
        }
    }

    async function performDelete(configId) {
        try {
            const result = await apiDelete(`/api/v1/vectorstore/configurations/${configId}`);
            if (result.data.status === 'success') {
                showToast('Vector store deleted', 'success');
                await loadVectorStoreConfigurations();
            } else {
                showToast(result.data.message || 'Failed to delete', 'error');
            }
        } catch (e) {
            showToast(`Error: ${e.message}`, 'error');
        }
    }

    // ── Test Connection (card-level, saved config) ────────────────────────────

    async function testConnection(configId) {
        const card = document.querySelector(`[data-vs-id="${configId}"]`);
        const testBtn = card?.querySelector('button[title="Test connection"]');
        const originalText = testBtn?.textContent;
        if (testBtn) {
            testBtn.textContent = 'Testing...';
            testBtn.disabled = true;
        }

        try {
            const result = await apiPost(`/api/v1/vectorstore/configurations/${configId}/test`, {});
            if (result.data.status === 'success') {
                showToast('Connection successful', 'success');
            } else {
                showToast(result.data.message || 'Connection failed', 'error');
            }
        } catch (e) {
            showToast(`Connection test failed: ${e.message}`, 'error');
        } finally {
            if (testBtn) {
                testBtn.textContent = originalText;
                testBtn.disabled = false;
            }
        }
    }

    // ── Utilities ────────────────────────────────────────────────────────────

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function showToast(message, type) {
        if (typeof window.showNotification === 'function') {
            window.showNotification(message, type);
        } else if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }

    // ── Public API ───────────────────────────────────────────────────────────

    window.vectorStoreHandler = {
        load: loadVectorStoreConfigurations,
        showAddModal,
        showEditModal,
        closeModal,
        toggleBackendFields,
        deleteConfig,
        testConnection,
        testModalConnection,
        getConfigurations: () => configurations,
        isLoaded: () => loaded,
    };

    // Initialize form listener on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initForm);
    } else {
        initForm();
    }
})();
