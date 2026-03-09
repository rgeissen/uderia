/**
 * Template Edit Modal
 * Allows users to customize template parameter defaults
 */

export class TemplateEditModal {
    constructor() {
        this.modal = null;
        this.currentTemplate = null;
        this.currentDefaults = {};
        this.isDirty = false;
    }

    /**
     * Open edit modal for a template
     * @param {string} templateId - Template ID
     * @param {object} template - Full template manifest object
     */
    async open(templateId, template) {
        console.log('Opening modal for template:', templateId);
        console.log('Template manifest received:', template);
        
        // Store the full template manifest
        this.currentTemplate = template;
        this.templateType = template.template_type;
        
        console.log('Template type:', this.templateType);
        
        // Load existing defaults
        await this.loadDefaults(templateId);
        
        // Create and show modal
        this.createModal();
        this.renderParameters();
        this.modal.classList.add('show');
    }

    /**
     * Load existing defaults from backend
     */
    async loadDefaults(templateId) {
        try {
            const response = await fetch(`/api/v1/rag/templates/${templateId}/defaults`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('tda_auth_token')}` }
            });
            
            if (!response.ok) {
                console.warn('No existing defaults found, using template defaults');
                this.currentDefaults = {};
                return;
            }
            
            const data = await response.json();
            this.currentDefaults = data.defaults || {};
            
        } catch (error) {
            console.error('Error loading defaults:', error);
            this.currentDefaults = {};
        }
    }

    /**
     * Create modal DOM structure
     */
    createModal() {
        // Remove existing modal if present
        const existingModal = document.getElementById('template-edit-modal');
        if (existingModal) {
            existingModal.remove();
        }

        const modalHtml = `
            <div class="tpl-modal-overlay" id="template-edit-modal" tabindex="-1" role="dialog">
                <div class="tpl-modal-dialog" role="document">
                    <div class="tpl-modal-content">
                        <div class="tpl-modal-header">
                            <h5 class="tpl-modal-title">
                                Edit Template: ${this.currentTemplate.template_name || this.currentTemplate.template_id}
                            </h5>
                            <button type="button" class="close tpl-modal-close" data-dismiss="modal">
                                <span>&times;</span>
                            </button>
                        </div>
                        <div class="tpl-modal-body">
                            <!-- Tab Navigation -->
                            <div class="tpl-modal-tabs">
                                <button class="template-tab ind-tab ind-tab--underline active" data-tab="basic-params">
                                    Basic Parameters
                                </button>
                                <button class="template-tab ind-tab ind-tab--underline" data-tab="advanced-params">
                                    Advanced
                                </button>
                                <button class="template-tab ind-tab ind-tab--underline" data-tab="info-params">
                                    System Info
                                </button>
                            </div>

                            <!-- Tab Content -->
                            <div class="tab-content">
                                <div class="tab-pane" id="basic-params" style="display: block;">
                                    <div id="basic-parameters-container"></div>
                                </div>
                                <div class="tab-pane" id="advanced-params" style="display: none;">
                                    <div id="advanced-parameters-container"></div>
                                </div>
                                <div class="tab-pane" id="info-params" style="display: none;">
                                    <div id="info-parameters-container"></div>
                                </div>
                            </div>
                        </div>
                        <div class="tpl-modal-footer">
                            <button type="button" class="card-btn card-btn--neutral" id="reset-defaults-btn">Reset to System Defaults</button>
                            <button type="button" class="card-btn card-btn--neutral" id="cancel-modal-btn" data-dismiss="modal">Cancel</button>
                            <button type="button" class="card-btn card-btn--primary" id="save-defaults-btn">Save Defaults</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
        this.modal = document.getElementById('template-edit-modal');

        // Attach event listeners
        this.attachEventListeners();
    }

    /**
     * Render parameter form fields
     */
    renderParameters() {
        console.log('=== renderParameters called ===');
        console.log('Current template:', this.currentTemplate);
        console.log('Template type:', this.templateType);
        
        // Add visual debug indicator
        const basicContainer = document.getElementById('basic-parameters-container');
        if (basicContainer) {
            basicContainer.innerHTML = '<p class="tpl-form-help">Loading parameters...</p>';
        }
        
        if (this.templateType === 'knowledge_repository') {
            console.log('Rendering knowledge parameters');
            this.renderKnowledgeParameters();
        } else if (this.templateType === 'sql_query') {
            console.log('Rendering planner parameters');
            this.renderPlannerParameters();
        } else {
            console.error('Unknown template type:', this.templateType);
        }
    }

    /**
     * Render Knowledge Repository parameters
     */
    renderKnowledgeParameters() {
        console.log('renderKnowledgeParameters called');
        const config = this.currentTemplate.repository_configuration || {};
        console.log('Config:', config);

        // Basic parameters
        const basicContainer = document.getElementById('basic-parameters-container');
        console.log('Basic container:', basicContainer);

        if (!config.chunking_strategy && !config.embedding_model) {
            basicContainer.innerHTML = `<p class="tpl-form-help">No editable parameters found for this template.</p>`;
            console.error('No parameters found in repository_configuration');
            console.log('Full template:', this.currentTemplate);
            return;
        }

        console.log('Rendering parameters - chunking_strategy exists:', !!config.chunking_strategy);
        console.log('Rendering parameters - embedding_model exists:', !!config.embedding_model);

        basicContainer.innerHTML = `
            ${config.chunking_strategy ? `
            <div class="tpl-form-group">
                <label for="chunking_strategy" class="tpl-form-label">Chunking Strategy</label>
                <select id="chunking_strategy" data-param="chunking_strategy" class="tpl-form-input">
                    ${this.renderOptions('chunking_strategy', config.chunking_strategy)}
                </select>
                <small class="tpl-form-help">${config.chunking_strategy.description || ''}</small>
            </div>
            ` : ''}

            ${config.embedding_model ? `
            <div class="tpl-form-group">
                <label for="embedding_model" class="tpl-form-label">Embedding Model</label>
                <select id="embedding_model" data-param="embedding_model" class="tpl-form-input">
                    ${this.renderOptions('embedding_model', config.embedding_model)}
                </select>
                <small class="tpl-form-help">${config.embedding_model.description || ''}</small>
            </div>
            ` : ''}

            ${config.chunk_size ? `
            <div id="chunk_size_group" class="tpl-form-group" style="display: none;">
                <label for="chunk_size" class="tpl-form-label">Chunk Size (characters)</label>
                <input type="number" id="chunk_size" data-param="chunk_size" class="tpl-form-input"
                       min="${config.chunk_size.min || 100}" max="${config.chunk_size.max || 5000}"
                       value="${this.getDefaultValue('chunk_size', config.chunk_size.default || 1000)}">
                <small class="tpl-form-help">${config.chunk_size.description || ''}</small>
            </div>
            ` : ''}

            ${config.chunk_overlap ? `
            <div id="chunk_overlap_group" class="tpl-form-group" style="display: none;">
                <label for="chunk_overlap" class="tpl-form-label">Chunk Overlap (characters)</label>
                <input type="number" id="chunk_overlap" data-param="chunk_overlap" class="tpl-form-input"
                       min="${config.chunk_overlap.min || 0}" max="${config.chunk_overlap.max || 500}"
                       value="${this.getDefaultValue('chunk_overlap', config.chunk_overlap.default || 200)}">
                <small class="tpl-form-help">${config.chunk_overlap.description || ''}</small>
            </div>
            ` : ''}
        `;

        console.log('Basic container HTML set, innerHTML length:', basicContainer.innerHTML.length);

        // Advanced parameters (empty for now)
        const advancedContainer = document.getElementById('advanced-parameters-container');
        advancedContainer.innerHTML = `
            <p class="tpl-form-help">No advanced parameters available for this template type.</p>
        `;

        // System info
        this.renderSystemInfo();

        // Show/hide conditional fields
        this.setupConditionalFields();
    }

    /**
     * Render Planner (SQL) parameters
     */
    renderPlannerParameters() {
        console.log('renderPlannerParameters called');
        const config = this.currentTemplate.input_variables || {};
        console.log('Input variables config:', config);

        // Basic parameters
        const basicContainer = document.getElementById('basic-parameters-container');
        console.log('Basic container:', basicContainer);

        let hasParams = false;
        let paramsHtml = '';

        console.log('Checking for mcp_tool_name:', !!config.mcp_tool_name);
        console.log('Checking for mcp_context_prompt:', !!config.mcp_context_prompt);
        console.log('Checking for target_database:', !!config.target_database);

        if (config.mcp_tool_name) {
            hasParams = true;
            paramsHtml += `
            <div class="tpl-form-group">
                <label for="mcp_tool_name" class="tpl-form-label">MCP Tool Name</label>
                <input type="text" id="mcp_tool_name" data-param="mcp_tool_name" class="tpl-form-input"
                       value="${this.getDefaultValue('mcp_tool_name', config.mcp_tool_name.default || '')}"
                       placeholder="${config.mcp_tool_name.placeholder || ''}">
                <small class="tpl-form-help">${config.mcp_tool_name.description || ''}</small>
            </div>`;
        }

        if (config.mcp_context_prompt) {
            hasParams = true;
            paramsHtml += `
            <div class="tpl-form-group">
                <label for="mcp_context_prompt" class="tpl-form-label">MCP Context Prompt</label>
                <input type="text" id="mcp_context_prompt" data-param="mcp_context_prompt" class="tpl-form-input"
                       value="${this.getDefaultValue('mcp_context_prompt', config.mcp_context_prompt.default || '')}"
                       placeholder="${config.mcp_context_prompt.placeholder || ''}">
                <small class="tpl-form-help">${config.mcp_context_prompt.description || ''}</small>
            </div>`;
        }

        if (config.target_database) {
            hasParams = true;
            paramsHtml += `
            <div class="tpl-form-group">
                <label for="target_database" class="tpl-form-label">Target Database</label>
                <input type="text" id="target_database" data-param="target_database" class="tpl-form-input"
                       value="${this.getDefaultValue('target_database', config.target_database.default || 'Teradata')}"
                       placeholder="${config.target_database.placeholder || 'Teradata'}">
                <small class="tpl-form-help">${config.target_database.description || ''}</small>
            </div>`;
        }

        basicContainer.innerHTML = hasParams ? paramsHtml : `<p class="tpl-form-help">No editable basic parameters found for this template.</p>`;

        console.log('Basic container HTML set, innerHTML length:', basicContainer.innerHTML.length);
        console.log('Has params:', hasParams);

        // Advanced parameters
        const advancedContainer = document.getElementById('advanced-parameters-container');
        const outputConfig = this.currentTemplate.output_configuration || {};
        console.log('Output configuration:', outputConfig);

        advancedContainer.innerHTML = `
            ${outputConfig.is_most_efficient ? `
            <div class="tpl-form-group">
                <label class="tpl-form-checkbox-label">
                    <input type="checkbox" id="is_most_efficient" data-param="is_most_efficient"
                           ${this.getDefaultValue('is_most_efficient', outputConfig.is_most_efficient.value) ? 'checked' : ''}>
                    Mark as Champion (Most Efficient)
                </label>
                <small class="tpl-form-help">${outputConfig.is_most_efficient.description || ''}</small>
            </div>
            ` : ''}

            ${outputConfig.estimated_tokens ? `
            <div class="tpl-form-group">
                <label for="input_tokens" class="tpl-form-label">Estimated Input Tokens</label>
                <input type="number" id="input_tokens" data-param="input_tokens" class="tpl-form-input"
                       value="${this.getDefaultValue('input_tokens', outputConfig.estimated_tokens.input_tokens.value || 150)}">
                <small class="tpl-form-help">${outputConfig.estimated_tokens.input_tokens.description || ''}</small>
            </div>

            <div class="tpl-form-group">
                <label for="output_tokens" class="tpl-form-label">Estimated Output Tokens</label>
                <input type="number" id="output_tokens" data-param="output_tokens" class="tpl-form-input"
                       value="${this.getDefaultValue('output_tokens', outputConfig.estimated_tokens.output_tokens.value || 180)}">
                <small class="tpl-form-help">${outputConfig.estimated_tokens.output_tokens.description || ''}</small>
            </div>
            ` : ''}
        `;

        // System info
        this.renderSystemInfo();
    }

    /**
     * Render system information (read-only)
     */
    renderSystemInfo() {
        const infoContainer = document.getElementById('info-parameters-container');
        const template = this.currentTemplate;

        infoContainer.innerHTML = `
            <div class="tpl-info-alert">
                <strong>System Parameters (Read-Only)</strong>
                <p>These parameters are managed by the system and cannot be edited.</p>
            </div>

            <table class="tpl-info-table">
                <tbody>
                    <tr>
                        <td><strong>Template ID:</strong></td>
                        <td><code class="tpl-info-code">${template.template_id}</code></td>
                    </tr>
                    <tr>
                        <td><strong>Template Type:</strong></td>
                        <td><code class="tpl-info-code">${this.templateType}</code></td>
                    </tr>
                    <tr>
                        <td><strong>Version:</strong></td>
                        <td>${template.template_version || 'N/A'}</td>
                    </tr>
                    <tr>
                        <td><strong>Description:</strong></td>
                        <td>${template.description || 'N/A'}</td>
                    </tr>
                    ${template.repository_configuration ? `
                    <tr>
                        <td><strong>Max File Size:</strong></td>
                        <td>${template.document_configuration?.max_file_size_mb || 50} MB</td>
                    </tr>
                    <tr>
                        <td><strong>Supported Types:</strong></td>
                        <td>${(template.document_configuration?.supported_types || []).join(', ')}</td>
                    </tr>
                    ` : ''}
                    ${template.strategy_template ? `
                    <tr>
                        <td><strong>Phase Count:</strong></td>
                        <td>${template.strategy_template.phase_count}</td>
                    </tr>
                    ` : ''}
                </tbody>
            </table>
        `;
    }

    /**
     * Render select options from template config
     */
    renderOptions(paramName, paramConfig) {
        if (!paramConfig || !paramConfig.options) return '';
        
        const currentValue = this.getDefaultValue(paramName, paramConfig.default);
        const options = paramConfig.options;
        
        return options.map(opt => {
            const value = typeof opt === 'object' ? opt.value : opt;
            const label = typeof opt === 'object' ? opt.label : opt;
            const selected = value === currentValue ? 'selected' : '';
            return `<option value="${value}" ${selected}>${label}</option>`;
        }).join('');
    }

    /**
     * Get default value for a parameter
     */
    getDefaultValue(paramName, fallback) {
        return this.currentDefaults[paramName] !== undefined 
            ? this.currentDefaults[paramName] 
            : fallback;
    }

    /**
     * Setup conditional field visibility (e.g., chunk_size only for fixed_size)
     */
    setupConditionalFields() {
        const chunkingSelect = document.getElementById('chunking_strategy');
        if (chunkingSelect) {
            const updateVisibility = () => {
                const value = chunkingSelect.value;
                const sizeGroup = document.getElementById('chunk_size_group');
                const overlapGroup = document.getElementById('chunk_overlap_group');
                
                if (sizeGroup && overlapGroup) {
                    const show = value === 'fixed_size';
                    sizeGroup.style.display = show ? 'block' : 'none';
                    overlapGroup.style.display = show ? 'block' : 'none';
                }
            };
            
            chunkingSelect.addEventListener('change', updateVisibility);
            updateVisibility(); // Initial state
        }
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        console.log('attachEventListeners called');
        
        // Save button
        const saveBtn = document.getElementById('save-defaults-btn');
        console.log('Save button:', saveBtn);
        if (saveBtn) {
            saveBtn.addEventListener('click', () => {
                console.log('Save button clicked');
                this.saveDefaults();
            });
        } else {
            console.error('Save button not found!');
        }

        // Reset button
        const resetBtn = document.getElementById('reset-defaults-btn');
        console.log('Reset button:', resetBtn);
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                console.log('Reset button clicked');
                this.resetDefaults();
            });
        } else {
            console.error('Reset button not found!');
        }

        // Track changes for dirty flag
        this.modal.addEventListener('change', (e) => {
            if (e.target.hasAttribute('data-param')) {
                this.isDirty = true;
            }
        });

        // Cancel button
        const cancelBtn = document.getElementById('cancel-modal-btn');
        console.log('Cancel button:', cancelBtn);
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                console.log('Cancel button clicked');
                this.closeModal();
            });
        } else {
            console.error('Cancel button not found!');
        }
        
        // X close button
        const closeBtn = this.modal.querySelector('.close');
        console.log('Close X button:', closeBtn);
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                console.log('Close X button clicked');
                this.closeModal();
            });
        } else {
            console.error('Close X button not found!');
        }

        // Tab switching
        const tabs = this.modal.querySelectorAll('.template-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetTabId = tab.getAttribute('data-tab');
                
                // Update tab buttons
                tabs.forEach(t => {
                    t.classList.remove('active');
                });
                tab.classList.add('active');
                
                // Update tab panes
                const panes = this.modal.querySelectorAll('.tab-pane');
                panes.forEach(pane => {
                    pane.style.display = 'none';
                });
                const targetPane = document.getElementById(targetTabId);
                if (targetPane) {
                    targetPane.style.display = 'block';
                }
            });
        });
    }

    /**
     * Collect current form values
     */
    collectFormValues() {
        const values = {};
        const inputs = this.modal.querySelectorAll('[data-param]');
        
        inputs.forEach(input => {
            const paramName = input.getAttribute('data-param');
            
            if (input.type === 'checkbox') {
                values[paramName] = input.checked;
            } else if (input.type === 'number') {
                values[paramName] = parseInt(input.value, 10);
            } else {
                values[paramName] = input.value;
            }
        });
        
        return values;
    }

    /**
     * Save defaults to backend
     */
    async saveDefaults() {
        console.log('saveDefaults called');
        const saveBtn = document.getElementById('save-defaults-btn');
        if (!saveBtn) {
            console.error('Save button not found in saveDefaults');
            return;
        }
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

        try {
            const defaults = this.collectFormValues();
            
            const response = await fetch(`/api/v1/rag/templates/${this.currentTemplate.template_id}/defaults`, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('tda_auth_token')}`
                },
                body: JSON.stringify({ defaults })
            });

            if (!response.ok) {
                throw new Error('Failed to save defaults');
            }

            const data = await response.json();
            
            const showMsg = window.showToast || window.showNotification;
            if (showMsg) showMsg('success', `Saved ${data.updated_count} parameter defaults`);
            this.isDirty = false;
            
            // Close modal
            this.closeModal();
            
        } catch (error) {
            console.error('Error saving defaults:', error);
            const showMsg = window.showToast || window.showNotification;
            if (showMsg) showMsg('error', 'Failed to save template defaults');
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save Defaults';
        }
    }

    /**
     * Reset to system defaults
     */
    async resetDefaults() {
        console.log('resetDefaults called');
        window.showConfirmation(
            'Reset Customizations',
            '<p>Reset all customizations to system defaults?</p><p class="mt-2 text-sm text-gray-400">This cannot be undone.</p>',
            async () => {
                try {
                    const response = await fetch(`/api/v1/rag/templates/${this.currentTemplate.template_id}/defaults`, {
                        method: 'DELETE',
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('tda_auth_token')}` }
                    });

                    if (!response.ok) {
                        throw new Error('Failed to reset defaults');
                    }

                    const showMsg = window.showToast || window.showNotification;
                    if (showMsg) showMsg('success', 'Reset to system defaults');

                    // Reload defaults and re-render
                    await this.loadDefaults(this.currentTemplate.template_id);
                    this.renderParameters();
                    this.isDirty = false;

                } catch (error) {
                    console.error('Error resetting defaults:', error);
                    const showMsg = window.showToast || window.showNotification;
                    if (showMsg) showMsg('error', 'Failed to reset defaults');
                }
            }
        );
    }

    /**
     * Close the modal
     */
    closeModal() {
        console.log('closeModal called, isDirty:', this.isDirty);

        const doClose = () => {
            if (this.modal) {
                console.log('Removing modal from DOM');
                this.modal.remove();
                this.modal = null;
            }
        };

        if (this.isDirty) {
            window.showConfirmation(
                'Unsaved Changes',
                '<p>You have unsaved changes. Close anyway?</p>',
                () => { doClose(); }
            );
            return;
        }
        doClose();
    }
}

// Export singleton instance
export const templateEditModal = new TemplateEditModal();
