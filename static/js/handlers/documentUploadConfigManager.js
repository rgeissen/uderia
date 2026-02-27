/**
 * Document Upload Configuration Manager
 * Handles admin UI for managing document upload capabilities per LLM provider
 */

const DocumentUploadConfigManager = {
    currentConfigs: [],
    currentProvider: null,

    /**
     * Initialize the document upload config manager
     */
    init() {
        console.log('[DocumentUploadConfigManager] Initializing...');
        this.setupEventListeners();
    },

    /**
     * Setup event listeners
     */
    setupEventListeners() {
        // Refresh button
        const refreshBtn = document.getElementById('refresh-document-upload-config-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadConfigurations());
        }

        // Modal close buttons
        const modalClose = document.getElementById('doc-upload-config-modal-close');
        if (modalClose) {
            modalClose.addEventListener('click', () => this.hideConfigModal());
        }

        const modalCancel = document.getElementById('doc-upload-config-cancel');
        if (modalCancel) {
            modalCancel.addEventListener('click', () => this.hideConfigModal());
        }

        // Modal reset button
        const resetBtn = document.getElementById('doc-upload-config-reset-btn');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => this.resetProviderConfig());
        }

        // Form submission
        const form = document.getElementById('doc-upload-config-form');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.saveConfiguration();
            });
        }
    },

    /**
     * Load all document upload configurations
     */
    async loadConfigurations() {
        console.log('[DocumentUploadConfigManager] Loading configurations...');
        
        const tbody = document.getElementById('document-upload-config-tbody');
        if (!tbody) {
            console.error('[DocumentUploadConfigManager] Table body not found');
            return;
        }

        // Show loading state
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="px-4 py-8 text-center text-gray-400">
                    <div class="flex flex-col items-center gap-2">
                        <svg class="animate-spin h-8 w-8 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        <span class="text-sm">Loading configurations...</span>
                    </div>
                </td>
            </tr>
        `;

        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch('/api/v1/admin/config/document-upload', {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            
            if (data.status === 'success') {
                this.currentConfigs = data.configs || [];
                this.renderConfigTable();
            } else {
                throw new Error(data.message || 'Failed to load configurations');
            }

        } catch (error) {
            console.error('[DocumentUploadConfigManager] Error loading configurations:', error);
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="px-4 py-8 text-center text-red-400">
                        <div class="flex flex-col items-center gap-2">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            <span class="text-sm">Failed to load configurations</span>
                            <span class="text-xs text-gray-500">${error.message}</span>
                        </div>
                    </td>
                </tr>
            `;
        }
    },

    /**
     * Render configuration table
     */
    renderConfigTable() {
        const tbody = document.getElementById('document-upload-config-tbody');
        if (!tbody) return;

        if (this.currentConfigs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="px-4 py-8 text-center text-gray-400">
                        <span class="text-sm">No configurations found</span>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.currentConfigs.map(config => {
            const capabilityBadge = this.getCapabilityBadge(config.capability);
            const statusBadge = this.getStatusBadge(config);
            
            return `
                <tr class="hover:bg-gray-700/30 transition-colors">
                    <td class="px-4 py-3 text-sm font-medium text-white">${config.provider}</td>
                    <td class="px-4 py-3 text-sm">${capabilityBadge}</td>
                    <td class="px-4 py-3 text-sm">
                        <span class="px-2 py-1 rounded text-xs font-medium ${config.enabled ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}">
                            ${config.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-sm">
                        <span class="px-2 py-1 rounded text-xs font-medium ${config.use_native_upload ? 'bg-blue-500/20 text-blue-400' : 'bg-gray-500/20 text-gray-400'}">
                            ${config.use_native_upload ? 'Yes' : 'No (Text Extract)'}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-300">${config.max_file_size_mb || 'N/A'}</td>
                    <td class="px-4 py-3 text-sm">${statusBadge}</td>
                    <td class="px-4 py-3 text-center">
                        <button onclick="DocumentUploadConfigManager.showConfigModal('${config.provider}')" 
                                class="card-btn card-btn--sm card-btn--primary">
                            Configure
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    },

    /**
     * Get capability badge HTML
     */
    getCapabilityBadge(capability) {
        const badges = {
            'native_full': 'bg-green-500/20 text-green-400',
            'native_vision': 'bg-yellow-500/20 text-yellow-400',
            'text_extraction': 'bg-blue-500/20 text-blue-400',
            'not_supported': 'bg-gray-500/20 text-gray-400'
        };

        const colorClass = badges[capability] || badges['not_supported'];
        return `<span class="px-2 py-1 rounded text-xs font-medium ${colorClass}">${capability}</span>`;
    },

    /**
     * Get status badge HTML
     */
    getStatusBadge(config) {
        if (config.has_overrides) {
            return '<span class="px-2 py-1 bg-orange-500/20 text-orange-400 rounded text-xs font-medium">Modified</span>';
        }
        return '<span class="px-2 py-1 bg-gray-500/20 text-gray-400 rounded text-xs font-medium">Default</span>';
    },

    /**
     * Show configuration modal for a provider
     */
    async showConfigModal(provider) {
        this.currentProvider = provider;
        const config = this.currentConfigs.find(c => c.provider === provider);
        
        if (!config) {
            console.error('[DocumentUploadConfigManager] Config not found for provider:', provider);
            return;
        }

        // Populate form
        document.getElementById('doc-upload-config-provider').value = provider;
        document.getElementById('doc-upload-config-provider-name').textContent = provider;
        
        // Capability badge
        const capabilityEl = document.getElementById('doc-upload-config-capability');
        capabilityEl.textContent = config.capability;
        capabilityEl.className = `ml-2 px-2 py-1 rounded text-xs font-medium ${this.getCapabilityBadge(config.capability).match(/class="([^"]+)"/)[1]}`;
        
        // Form fields
        document.getElementById('doc-upload-config-enabled').checked = config.enabled;
        document.getElementById('doc-upload-config-use-native').checked = config.use_native_upload;
        document.getElementById('doc-upload-config-max-size').value = config.has_overrides && config.max_file_size_mb ? config.max_file_size_mb : '';
        document.getElementById('doc-upload-config-default-size').textContent = `(Default: ${config.max_file_size_mb}MB)`;
        
        // Formats
        const formatsInput = document.getElementById('doc-upload-config-formats');
        formatsInput.value = '';
        
        const defaultFormats = document.getElementById('doc-upload-config-default-formats');
        defaultFormats.textContent = config.supported_formats && config.supported_formats.length > 0 
            ? `Default formats: ${config.supported_formats.join(', ')}`
            : 'No default formats';
        
        // Notes
        document.getElementById('doc-upload-config-notes').value = config.notes || '';

        // Show modal
        const overlay = document.getElementById('doc-upload-config-modal-overlay');
        overlay.classList.remove('hidden');
    },

    /**
     * Hide configuration modal
     */
    hideConfigModal() {
        const overlay = document.getElementById('doc-upload-config-modal-overlay');
        overlay.classList.add('hidden');
        this.currentProvider = null;
    },

    /**
     * Save configuration
     */
    async saveConfiguration() {
        if (!this.currentProvider) {
            console.error('[DocumentUploadConfigManager] No provider selected');
            return;
        }

        const formData = {
            enabled: document.getElementById('doc-upload-config-enabled').checked,
            use_native_upload: document.getElementById('doc-upload-config-use-native').checked,
            max_file_size_mb: document.getElementById('doc-upload-config-max-size').value ? 
                parseInt(document.getElementById('doc-upload-config-max-size').value) : null,
            supported_formats_override: document.getElementById('doc-upload-config-formats').value ? 
                document.getElementById('doc-upload-config-formats').value.split(',').map(f => f.trim()) : null,
            notes: document.getElementById('doc-upload-config-notes').value || null
        };

        console.log('[DocumentUploadConfigManager] Saving configuration for', this.currentProvider, formData);

        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch(`/api/v1/admin/config/document-upload/${this.currentProvider}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            
            if (data.status === 'success') {
                console.log('[DocumentUploadConfigManager] Configuration saved successfully');
                this.hideConfigModal();
                await this.loadConfigurations();
                
                // Show success message
                this.showToast('Configuration saved successfully', 'success');
            } else {
                throw new Error(data.message || 'Failed to save configuration');
            }

        } catch (error) {
            console.error('[DocumentUploadConfigManager] Error saving configuration:', error);
            this.showToast(`Failed to save configuration: ${error.message}`, 'error');
        }
    },

    /**
     * Reset provider configuration to defaults
     */
    async resetProviderConfig() {
        if (!this.currentProvider) {
            console.error('[DocumentUploadConfigManager] No provider selected');
            return;
        }

        const provider = this.currentProvider;
        window.showConfirmation(
            'Reset Configuration',
            `<p>Reset configuration for <strong>${provider}</strong> to defaults?</p>`,
            async () => {
                console.log('[DocumentUploadConfigManager] Resetting configuration for', provider);

                try {
                    const token = localStorage.getItem('tda_auth_token');
                    const response = await fetch(`/api/v1/admin/config/document-upload/${provider}/reset`, {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json'
                        }
                    });

                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }

                    const data = await response.json();

                    if (data.status === 'success') {
                        console.log('[DocumentUploadConfigManager] Configuration reset successfully');
                        this.hideConfigModal();
                        await this.loadConfigurations();

                        // Show success message
                        this.showToast('Configuration reset to defaults', 'success');
                    } else {
                        throw new Error(data.message || 'Failed to reset configuration');
                    }

                } catch (error) {
                    console.error('[DocumentUploadConfigManager] Error resetting configuration:', error);
                    this.showToast(`Failed to reset configuration: ${error.message}`, 'error');
                }
            }
        );
        return;
    },

    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
        // Use existing banner system if available
        if (window.showAppBanner) {
            window.showAppBanner(message, type);
        } else {
            console.log(`[Toast] ${type.toUpperCase()}: ${message}`);
        }
    }
};

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        DocumentUploadConfigManager.init();
    });
} else {
    DocumentUploadConfigManager.init();
}
