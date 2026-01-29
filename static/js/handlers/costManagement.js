/**
 * Cost Management Handler
 * 
 * Manages LLM model cost configuration and analytics visualization.
 * - Displays cost analytics dashboard with KPIs
 * - Syncs pricing from LiteLLM
 * - Manages manual cost entries
 * - Configures fallback pricing
 */

class CostManagementHandler {
    constructor() {
        this.costs = [];
        this.filteredCosts = [];
        this.analytics = null;
        this.currentPage = 1;
        this.pageSize = 20; // Match HTML default
        this.searchTerm = '';
        this.isLoadingMore = false;
        this.lastScrollTop = 0;
        this.autoRefreshInterval = null;
        this.autoRefreshEnabled = false;
        this.init();
    }

    init() {
        console.log('[CostManagement] Initializing cost management handler');
        this.attachEventListeners();

        // Sync pageSize with dropdown value on init
        const pageSizeSelect = document.getElementById('costs-page-size');
        if (pageSizeSelect && pageSizeSelect.value) {
            this.pageSize = parseInt(pageSizeSelect.value);
        }

        // Load auto-refresh preference
        const savedAutoRefresh = localStorage.getItem('costAutoRefresh');
        if (savedAutoRefresh === 'true') {
            this.autoRefreshEnabled = true;
            const toggle = document.getElementById('cost-auto-refresh-toggle');
            if (toggle) toggle.checked = true;
        }
    }

    attachEventListeners() {
        // Refresh button
        const refreshBtn = document.getElementById('refresh-costs-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.refreshData());
        }

        // Auto-refresh toggle
        const autoRefreshToggle = document.getElementById('cost-auto-refresh-toggle');
        if (autoRefreshToggle) {
            autoRefreshToggle.addEventListener('change', (e) => this.toggleAutoRefresh(e.target.checked));
        }

        // Sync from LiteLLM button
        const syncBtn = document.getElementById('sync-litellm-costs-btn');
        if (syncBtn) {
            syncBtn.addEventListener('click', () => this.syncFromLiteLLM());
        }

        // Add manual cost entry button
        const addBtn = document.getElementById('add-manual-cost-btn');
        if (addBtn) {
            addBtn.addEventListener('click', () => this.showAddCostModal());
        }

        // Save fallback cost button
        const saveFallbackBtn = document.getElementById('save-fallback-cost-btn');
        if (saveFallbackBtn) {
            saveFallbackBtn.addEventListener('click', () => this.saveFallbackCost());
        }

        // Search input
        const searchInput = document.getElementById('costs-search-input');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.searchTerm = e.target.value.toLowerCase();
                this.currentPage = 1;
                this.filterAndRenderCosts();
            });
        }

        // Page size selector
        const pageSizeSelect = document.getElementById('costs-page-size');
        if (pageSizeSelect) {
            pageSizeSelect.addEventListener('change', (e) => {
                this.pageSize = parseInt(e.target.value);
                this.currentPage = 1;
                this.filterAndRenderCosts();
            });
        }

        // Infinite scroll will be attached when tab is activated
        this.scrollHandler = () => {
            if (this.isLoadingMore) return;
            
            const tableContainer = document.querySelector('#cost-management-tab .overflow-x-auto');
            if (!tableContainer) return;
            
            const scrollTop = tableContainer.scrollTop;
            const scrollHeight = tableContainer.scrollHeight;
            const clientHeight = tableContainer.clientHeight;
            
            // Only trigger if user actually scrolled down (not just content expanding)
            if (scrollTop <= this.lastScrollTop && this.lastScrollTop > 0) {
                this.lastScrollTop = scrollTop;
                return;
            }
            this.lastScrollTop = scrollTop;
            
            // Only load more if we have scrollable content and are near the bottom (200px threshold)
            const distanceFromBottom = scrollHeight - (scrollTop + clientHeight);
            
            if (scrollHeight > clientHeight && distanceFromBottom <= 200) {
                this.loadMoreRows();
            }
        };

        // Tab activation - load data when Cost tab is shown
        const costTab = document.querySelector('[data-tab="cost-management-tab"]');
        if (costTab) {
            costTab.addEventListener('click', async () => {
                await this.loadCostData();
                await this.loadCostAnalytics();

                // Start auto-refresh if enabled
                if (this.autoRefreshEnabled) {
                    this.startAutoRefresh();
                }
            });
        }

        // Stop auto-refresh when switching away from Cost tab
        document.querySelectorAll('.admin-tab').forEach(tab => {
            if (tab.dataset.tab !== 'cost-management-tab') {
                tab.addEventListener('click', () => {
                    this.stopAutoRefresh();
                });
            }
        });
    }

    attachScrollListener() {
        const tableContainer = document.querySelector('#cost-management-tab .overflow-x-auto');
        if (tableContainer) {
            // Remove existing listener if any
            tableContainer.removeEventListener('scroll', this.scrollHandler);
            // Attach new listener with passive option for better performance
            tableContainer.addEventListener('scroll', this.scrollHandler, { passive: true });
        }
    }

    async syncFromLiteLLM() {
        const btn = document.getElementById('sync-litellm-costs-btn');
        const originalHTML = btn.innerHTML;
        
        try {
            btn.disabled = true;
            btn.innerHTML = '<svg class="animate-spin h-5 w-5 inline-block mr-1" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Syncing...';

            const response = await fetch('/api/v1/costs/sync', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${window.authClient.getToken()}`
                }
            });

            const data = await response.json();

            if (response.ok) {
                window.showNotification(
                    `Sync completed: ${data.synced_count} models processed (${data.new_models.length} new, ${data.updated_models.length} updated)`,
                    data.errors.length > 0 ? 'warning' : 'success'
                );

                if (data.errors.length > 0) {
                    console.warn('[CostManagement] Sync errors:', data.errors);
                }

                // Reload cost data and analytics
                await this.loadCostData();
                await this.loadCostAnalytics();
            } else {
                window.showNotification(`Sync failed: ${data.message || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('[CostManagement] Sync error:', error);
            window.showNotification(`Sync failed: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    }

    async loadCostData() {
        try {
            const response = await fetch('/api/v1/costs/models?include_fallback=true', {
                headers: {
                    'Authorization': `Bearer ${window.authClient.getToken()}`
                }
            });

            const data = await response.json();
            console.log('[CostManagement] Loaded cost data:', { 
                count: data.costs?.length, 
                status: data.status,
                responseOk: response.ok,
                statusCode: response.status 
            });

            if (response.ok) {
                this.costs = data.costs || [];
                console.log('[CostManagement] Costs array set:', {
                    costsLength: this.costs.length,
                    firstCost: this.costs[0]
                });
                this.filterAndRenderCosts();
                this.updateFallbackInputs();
            } else {
                console.error('[CostManagement] Failed to load costs:', {
                    status: response.status,
                    data: data
                });
                window.showNotification(`Failed to load cost data: ${data.message || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('[CostManagement] Load costs error:', error);
            window.showNotification(`Failed to load cost data: ${error.message}`, 'error');
        }
    }

    filterAndRenderCosts() {
        // Filter costs (exclude fallback)
        const nonFallbackCosts = this.costs.filter(cost => !cost.is_fallback);
        
        // Apply search filter
        if (this.searchTerm) {
            this.filteredCosts = nonFallbackCosts.filter(cost => {
                const provider = cost.provider.toLowerCase();
                const model = cost.model.toLowerCase();
                return provider.includes(this.searchTerm) || model.includes(this.searchTerm);
            });
        } else {
            this.filteredCosts = nonFallbackCosts;
        }

        // Sort: config_default first, then manual entries, then LiteLLM entries
        this.filteredCosts.sort((a, b) => {
            // Priority order: config_default > manual > litellm
            const getPriority = (cost) => {
                if (cost.source === 'config_default') return 0;
                if (cost.is_manual_entry || cost.source === 'manual') return 1;
                return 2; // litellm or other
            };
            
            const priorityA = getPriority(a);
            const priorityB = getPriority(b);
            
            if (priorityA !== priorityB) {
                return priorityA - priorityB;
            }
            
            // Within same priority, sort by provider then model
            if (a.provider !== b.provider) {
                return a.provider.localeCompare(b.provider);
            }
            return a.model.localeCompare(b.model);
        });

        console.log('[CostManagement] Filtered costs:', { 
            total: this.costs.length, 
            nonFallback: nonFallbackCosts.length,
            filtered: this.filteredCosts.length,
            manualEntries: this.filteredCosts.filter(c => c.is_manual_entry).length,
            searchTerm: this.searchTerm 
        });

        this.renderCostsTable();
        this.updatePaginationControls();
        
        // Reset scroll position tracking
        this.lastScrollTop = 0;
        
        // Attach scroll listener after rendering (need to wait for DOM update)
        setTimeout(() => this.attachScrollListener(), 100);
    }

    renderCostsTable() {
        const tbody = document.getElementById('costs-table-body');
        if (!tbody) {
            console.error('[CostManagement] Table body element not found');
            return;
        }

        if (this.filteredCosts.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="px-4 py-8 text-center text-gray-400">
                        ${this.searchTerm ? 'No matching entries found.' : 'No cost data available. Click "Sync from LiteLLM" to load pricing data.'}
                    </td>
                </tr>
            `;
            return;
        }

        // Calculate pagination
        const startIndex = (this.currentPage - 1) * this.pageSize;
        const endIndex = Math.min(startIndex + this.pageSize, this.filteredCosts.length);
        const pageData = this.filteredCosts.slice(startIndex, endIndex);

        tbody.innerHTML = pageData
            .map(cost => this.renderCostRow(cost))
            .join('');
    }

    loadMoreRows() {
        if (this.isLoadingMore) return;
        
        const totalEntries = this.filteredCosts.length;
        const currentlyShown = this.currentPage * this.pageSize;
        
        if (currentlyShown >= totalEntries) return; // All loaded
        
        this.isLoadingMore = true;
        this.currentPage++;
        
        const start = (this.currentPage - 1) * this.pageSize;
        const end = Math.min(start + this.pageSize, totalEntries);
        const newRows = this.filteredCosts.slice(start, end);
        
        this.appendCostRows(newRows);
        this.updatePaginationControls();
        
        // Small delay before allowing next load
        setTimeout(() => {
            this.isLoadingMore = false;
        }, 100);
    }
    
    appendCostRows(costs) {
        const tbody = document.getElementById('costs-table-body');
        if (!tbody) return;
        
        const rowsHtml = costs.map(cost => this.renderCostRow(cost)).join('');
        tbody.insertAdjacentHTML('beforeend', rowsHtml);
    }

    updatePaginationControls() {
        const totalEntries = this.filteredCosts.length;
        const currentlyShown = Math.min(this.currentPage * this.pageSize, totalEntries);
        
        // Update showing text
        this.updateElement('costs-showing-start', totalEntries > 0 ? 1 : 0);
        this.updateElement('costs-showing-end', currentlyShown);
        this.updateElement('costs-total-count', totalEntries);

        // Update page info to show loaded count
        this.updateElement('costs-page-info', `Loaded ${currentlyShown} of ${totalEntries}`);

        // Hide pagination buttons for infinite scroll
        const prevBtn = document.getElementById('costs-prev-page');
        const nextBtn = document.getElementById('costs-next-page');

        if (prevBtn) prevBtn.style.display = 'none';
        if (nextBtn) nextBtn.style.display = 'none';
    }

    renderCostRow(cost) {
        const sourceColors = {
            'litellm': 'text-blue-400',
            'manual': 'text-green-400',
            'system_default': 'text-gray-400'
        };

        const sourceColor = sourceColors[cost.source] || 'text-gray-400';
        const lastUpdated = new Date(cost.last_updated).toLocaleDateString();
        
        // Highlight manual entries with distinct styling
        const rowClass = cost.is_manual_entry 
            ? 'bg-green-500/5 border-l-2 border-l-green-500 hover:bg-green-500/10 transition-colors' 
            : 'hover:bg-white/5 transition-colors';

        return `
            <tr class="${rowClass}">
                <td class="px-4 py-3 text-white font-medium">
                    ${cost.is_manual_entry ? '<span class="inline-block w-2 h-2 bg-green-500 rounded-full mr-2" title="Manual Entry"></span>' : ''}
                    ${this.escapeHtml(cost.provider)}
                </td>
                <td class="px-4 py-3 text-gray-300 font-mono text-xs">${this.escapeHtml(cost.model)}</td>
                <td class="px-4 py-3 text-gray-300">
                    <input type="number" step="0.001" min="0" value="${cost.input_cost_per_million}" 
                        data-cost-id="${cost.id}" data-field="input"
                        class="cost-edit-input w-24 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white text-xs">
                </td>
                <td class="px-4 py-3 text-gray-300">
                    <input type="number" step="0.001" min="0" value="${cost.output_cost_per_million}" 
                        data-cost-id="${cost.id}" data-field="output"
                        class="cost-edit-input w-24 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white text-xs">
                </td>
                <td class="px-4 py-3">
                    ${cost.is_manual_entry 
                        ? '<span class="px-1.5 py-0.5 bg-green-500/20 border border-green-500/30 rounded text-xs text-green-400 font-semibold">MANUAL</span>'
                        : `<span class="${sourceColor} text-xs font-medium uppercase">${cost.source}</span>`
                    }
                </td>
                <td class="px-4 py-3 text-gray-400 text-xs">${lastUpdated}</td>
                <td class="px-4 py-3">
                    <div class="flex gap-2">
                        <button onclick="window.costManager.updateCost('${cost.id}')" 
                            class="px-2 py-1 bg-blue-600 hover:bg-blue-700 rounded text-white text-xs">
                            Save
                        </button>
                        ${!cost.is_fallback ? `
                            <button onclick="window.costManager.deleteCost('${cost.id}')" 
                                class="px-2 py-1 bg-red-600 hover:bg-red-700 rounded text-white text-xs">
                                Delete
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
    }

    updateFallbackInputs() {
        const fallbackCost = this.costs.find(c => c.is_fallback);
        if (fallbackCost) {
            const inputField = document.getElementById('fallback-input-cost');
            const outputField = document.getElementById('fallback-output-cost');
            
            if (inputField) inputField.value = fallbackCost.input_cost_per_million;
            if (outputField) outputField.value = fallbackCost.output_cost_per_million;
        }
    }

    async updateCost(costId) {
        const inputField = document.querySelector(`input[data-cost-id="${costId}"][data-field="input"]`);
        const outputField = document.querySelector(`input[data-cost-id="${costId}"][data-field="output"]`);

        if (!inputField || !outputField) return;

        const inputCost = parseFloat(inputField.value);
        const outputCost = parseFloat(outputField.value);

        if (isNaN(inputCost) || isNaN(outputCost) || inputCost < 0 || outputCost < 0) {
            window.showNotification('Invalid cost values', 'error');
            return;
        }

        try {
            const response = await fetch(`/api/v1/costs/models/${costId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${window.authClient.getToken()}`
                },
                body: JSON.stringify({
                    input_cost: inputCost,
                    output_cost: outputCost,
                    notes: 'Updated via admin interface'
                })
            });

            const data = await response.json();

            if (response.ok) {
                window.showNotification('Cost updated successfully', 'success');
                await this.loadCostData();
            } else {
                window.showNotification(`Update failed: ${data.message || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('[CostManagement] Update cost error:', error);
            window.showNotification(`Update failed: ${error.message}`, 'error');
        }
    }

    async deleteCost(costId) {
        if (!confirm('Are you sure you want to delete this cost entry?')) {
            return;
        }

        try {
            const response = await fetch(`/api/v1/costs/models/${costId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${window.authClient.getToken()}`
                }
            });

            const data = await response.json();

            if (response.ok) {
                window.showNotification('Cost entry deleted', 'success');
                await this.loadCostData();
            } else {
                window.showNotification(`Delete failed: ${data.message || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('[CostManagement] Delete cost error:', error);
            window.showNotification(`Delete failed: ${error.message}`, 'error');
        }
    }

    async saveFallbackCost() {
        const inputField = document.getElementById('fallback-input-cost');
        const outputField = document.getElementById('fallback-output-cost');

        if (!inputField || !outputField) return;

        const inputCost = parseFloat(inputField.value);
        const outputCost = parseFloat(outputField.value);

        if (isNaN(inputCost) || isNaN(outputCost) || inputCost < 0 || outputCost < 0) {
            window.showNotification('Invalid fallback cost values', 'error');
            return;
        }

        try {
            const response = await fetch('/api/v1/costs/fallback', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${window.authClient.getToken()}`
                },
                body: JSON.stringify({
                    input_cost: inputCost,
                    output_cost: outputCost
                })
            });

            const data = await response.json();

            if (response.ok) {
                window.showNotification('Fallback cost updated successfully', 'success');
                await this.loadCostData();
            } else {
                window.showNotification(`Update failed: ${data.message || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('[CostManagement] Save fallback cost error:', error);
            window.showNotification(`Update failed: ${error.message}`, 'error');
        }
    }

    showAddCostModal() {
        const provider = prompt('Enter provider name (e.g., Friendli, Google, Anthropic):\n\nNote: Manual entries are protected from LiteLLM sync and will appear at the top of the list.');
        if (!provider || !provider.trim()) return;

        const model = prompt(`Enter model name for ${provider} (e.g., Llama-3.3-70B-Instruct, gpt-4):`);
        if (!model || !model.trim()) return;

        const inputCost = prompt(`Enter INPUT cost per 1M tokens for ${provider}/${model}:\n\nExample: 0.09 means $0.09 per 1 million input tokens`);
        if (!inputCost || inputCost.trim() === '') return;

        const outputCost = prompt(`Enter OUTPUT cost per 1M tokens for ${provider}/${model}:\n\nExample: 0.16 means $0.16 per 1 million output tokens`);
        if (!outputCost || outputCost.trim() === '') return;

        const notes = prompt(`Optional: Add notes about this pricing (e.g., "Friendli serverless endpoint pricing"):`);

        this.addManualCost(
            provider.trim(), 
            model.trim(), 
            parseFloat(inputCost), 
            parseFloat(outputCost),
            notes ? notes.trim() : null
        );
    }

    async addManualCost(provider, model, inputCost, outputCost, notes = null) {
        if (isNaN(inputCost) || isNaN(outputCost) || inputCost < 0 || outputCost < 0) {
            window.showNotification('Invalid cost values - must be positive numbers', 'error');
            return;
        }

        try {
            const response = await fetch('/api/v1/costs/models', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${window.authClient.getToken()}`
                },
                body: JSON.stringify({
                    provider,
                    model,
                    input_cost: inputCost,
                    output_cost: outputCost,
                    notes: notes || 'Added via admin interface'
                })
            });

            const data = await response.json();

            if (response.ok) {
                window.showNotification(`Manual cost entry added for ${provider}/${model}`, 'success');
                await this.loadCostData();
                await this.loadCostAnalytics();
            } else {
                window.showNotification(`Add failed: ${data.message || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('[CostManagement] Add manual cost error:', error);
            window.showNotification(`Add failed: ${error.message}`, 'error');
        }
    }

    async loadCostAnalytics() {
        try {
            const response = await fetch('/api/v1/costs/analytics', {
                headers: {
                    'Authorization': `Bearer ${window.authClient.getToken()}`
                }
            });

            const data = await response.json();

            if (response.ok) {
                this.analytics = data;
                this.renderCostAnalytics();
            } else {
                console.error('[CostManagement] Failed to load analytics:', data);
            }
        } catch (error) {
            console.error('[CostManagement] Load analytics error:', error);
        }
    }

    renderCostAnalytics() {
        if (!this.analytics) return;

        // Update KPI cards
        this.updateElement('cost-total', `$${this.analytics.total_cost.toFixed(2)}`);
        this.updateElement('cost-avg-session', `$${this.analytics.avg_cost_per_session.toFixed(4)}`);
        this.updateElement('cost-avg-turn', `$${this.analytics.avg_cost_per_turn.toFixed(4)}`);
        this.updateElement('cost-total-sessions', this.analytics.total_sessions);

        // Render cost by provider chart
        this.renderProviderChart();

        // Render cost by model chart
        this.renderModelChart();
    }

    renderProviderChart() {
        const container = document.getElementById('cost-by-provider-chart');
        if (!container || !this.analytics) return;

        const providers = Object.entries(this.analytics.cost_by_provider);
        if (providers.length === 0) {
            container.innerHTML = '<p class="text-sm text-gray-400 text-center py-4">No data available</p>';
            return;
        }

        const maxCost = Math.max(...providers.map(([_, cost]) => cost));

        container.innerHTML = providers.map(([provider, cost]) => {
            const percentage = (cost / maxCost) * 100;
            return `
                <div class="mb-3">
                    <div class="flex justify-between mb-1">
                        <span class="text-sm text-gray-300">${this.escapeHtml(provider)}</span>
                        <span class="text-sm font-semibold text-white">$${cost.toFixed(2)}</span>
                    </div>
                    <div class="w-full bg-gray-700 rounded-full h-2">
                        <div class="bg-gradient-to-r from-blue-500 to-purple-500 h-2 rounded-full transition-all" 
                            style="width: ${percentage}%"></div>
                    </div>
                </div>
            `;
        }).join('');
    }

    renderModelChart() {
        const container = document.getElementById('cost-by-model-chart');
        if (!container || !this.analytics) return;

        const models = Object.entries(this.analytics.cost_by_model).slice(0, 5);
        if (models.length === 0) {
            container.innerHTML = '<p class="text-sm text-gray-400 text-center py-4">No data available</p>';
            return;
        }

        const maxCost = Math.max(...models.map(([_, cost]) => cost));

        container.innerHTML = models.map(([model, cost]) => {
            const percentage = (cost / maxCost) * 100;
            return `
                <div class="mb-3">
                    <div class="flex justify-between mb-1">
                        <span class="text-xs text-gray-300 font-mono truncate">${this.escapeHtml(model)}</span>
                        <span class="text-sm font-semibold text-white ml-2">$${cost.toFixed(4)}</span>
                    </div>
                    <div class="w-full bg-gray-700 rounded-full h-2">
                        <div class="bg-gradient-to-r from-green-500 to-yellow-500 h-2 rounded-full transition-all" 
                            style="width: ${percentage}%"></div>
                    </div>
                </div>
            `;
        }).join('');
    }

    updateElement(id, value) {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = value;
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async refreshData() {
        console.log('[CostManagement] Manual refresh triggered');
        const refreshBtn = document.getElementById('refresh-costs-btn');

        // Add spinning animation to refresh icon
        if (refreshBtn) {
            const icon = refreshBtn.querySelector('svg');
            if (icon) {
                icon.style.animation = 'spin 1s linear';
            }
        }

        try {
            await Promise.all([
                this.loadCostData(),
                this.loadCostAnalytics()
            ]);
            window.showNotification('Cost data refreshed', 'success');
        } catch (error) {
            console.error('[CostManagement] Refresh error:', error);
            window.showNotification('Failed to refresh cost data', 'error');
        } finally {
            // Remove animation
            if (refreshBtn) {
                const icon = refreshBtn.querySelector('svg');
                if (icon) {
                    icon.style.animation = '';
                }
            }
        }
    }

    toggleAutoRefresh(enabled) {
        this.autoRefreshEnabled = enabled;
        localStorage.setItem('costAutoRefresh', enabled.toString());

        if (enabled) {
            console.log('[CostManagement] Auto-refresh enabled (30s interval)');
            this.startAutoRefresh();
            window.showNotification('Auto-refresh enabled', 'success');
        } else {
            console.log('[CostManagement] Auto-refresh disabled');
            this.stopAutoRefresh();
            window.showNotification('Auto-refresh disabled', 'info');
        }
    }

    startAutoRefresh() {
        this.stopAutoRefresh(); // Clear any existing interval

        console.log('[CostManagement] Starting auto-refresh interval (30s)');
        this.autoRefreshInterval = setInterval(async () => {
            console.log('[CostManagement] Auto-refresh triggered at', new Date().toLocaleTimeString());
            try {
                await Promise.all([
                    this.loadCostData(),
                    this.loadCostAnalytics()
                ]);
                console.log('[CostManagement] Auto-refresh completed successfully');
            } catch (error) {
                console.error('[CostManagement] Auto-refresh error:', error);
            }
        }, 30000); // 30 seconds

        console.log('[CostManagement] Auto-refresh interval ID:', this.autoRefreshInterval);
    }

    stopAutoRefresh() {
        if (this.autoRefreshInterval) {
            console.log('[CostManagement] Stopping auto-refresh (interval ID:', this.autoRefreshInterval, ')');
            clearInterval(this.autoRefreshInterval);
            this.autoRefreshInterval = null;
        }
    }
}

// Initialize cost management handler
window.addEventListener('DOMContentLoaded', () => {
    window.costManager = new CostManagementHandler();
});
