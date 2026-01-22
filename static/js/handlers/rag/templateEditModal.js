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
            <div class="modal fade show" id="template-edit-modal" tabindex="-1" role="dialog" style="display: block; background: rgba(0,0,0,0.5); position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 1050; overflow-y: auto;">
                <div class="modal-dialog modal-lg" role="document" style="max-width: 800px; margin: 1.75rem auto; position: relative;">
                    <div class="modal-content" style="background: #1a1d29; border: 1px solid rgba(255,255,255,0.1); border-radius: 0.5rem; box-shadow: 0 10px 40px rgba(0,0,0,0.5); color: #fff;">
                        <div class="modal-header" style="border-bottom: 1px solid rgba(255,255,255,0.1); padding: 1rem 1.5rem;">
                            <h5 class="modal-title" style="color: #fff; font-size: 1.25rem; font-weight: 600;">
                                <i class="fas fa-sliders-h"></i>
                                Edit Template: ${this.currentTemplate.template_name || this.currentTemplate.template_id}
                            </h5>
                            <button type="button" class="close" data-dismiss="modal" style="color: #fff; opacity: 0.7; background: none; border: none; font-size: 1.5rem; line-height: 1; cursor: pointer;">
                                <span>&times;</span>
                            </button>
                        </div>
                        <div class="modal-body" style="padding: 1.5rem; max-height: 60vh; overflow-y: auto;">
                            <!-- Tab Navigation -->
                            <div style="border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 1rem;">
                                <div style="display: flex; gap: 1rem;">
                                    <button class="template-tab active" data-tab="basic-params" style="padding: 0.75rem 1rem; background: none; border: none; border-bottom: 2px solid #F15F22; color: #F15F22; cursor: pointer; font-weight: 500;">
                                        Basic Parameters
                                    </button>
                                    <button class="template-tab" data-tab="advanced-params" style="padding: 0.75rem 1rem; background: none; border: none; border-bottom: 2px solid transparent; color: #9ca3af; cursor: pointer; font-weight: 500;">
                                        Advanced
                                    </button>
                                    <button class="template-tab" data-tab="info-params" style="padding: 0.75rem 1rem; background: none; border: none; border-bottom: 2px solid transparent; color: #9ca3af; cursor: pointer; font-weight: 500;">
                                        System Info
                                    </button>
                                </div>
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
                        <div class="modal-footer" style="border-top: 1px solid rgba(255,255,255,0.1); padding: 1rem 1.5rem; display: flex; gap: 0.5rem; justify-content: flex-end;">
                            <button type="button" class="btn btn-secondary" id="reset-defaults-btn" style="padding: 0.5rem 1rem; background: #6c757d; color: #fff; border: none; border-radius: 0.375rem; cursor: pointer; font-weight: 500;">
                                <i class="fas fa-undo"></i> Reset to System Defaults
                            </button>
                            <button type="button" class="btn btn-secondary" id="cancel-modal-btn" data-dismiss="modal" style="padding: 0.5rem 1rem; background: #6c757d; color: #fff; border: none; border-radius: 0.375rem; cursor: pointer; font-weight: 500;">Cancel</button>
                            <button type="button" class="btn btn-primary" id="save-defaults-btn" style="padding: 0.5rem 1rem; background: #F15F22; color: #fff; border: none; border-radius: 0.375rem; cursor: pointer; font-weight: 500;">
                                <i class="fas fa-save"></i> Save Defaults
                            </button>
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
            basicContainer.innerHTML = '<p style="color: yellow; font-size: 1rem;">DEBUG: renderParameters() was called, rendering...</p>';
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
        
        const formGroupStyle = 'margin-bottom: 1.5rem;';
        const labelStyle = 'display: block; margin-bottom: 0.5rem; color: #e5e7eb; font-weight: 500; font-size: 0.875rem;';
        const inputStyle = 'width: 100%; padding: 0.5rem 0.75rem; background: #2d3748; border: 1px solid rgba(255,255,255,0.1); border-radius: 0.375rem; color: #fff; font-size: 0.875rem;';
        const smallStyle = 'display: block; margin-top: 0.25rem; color: #9ca3af; font-size: 0.75rem;';
        
        // Basic parameters
        const basicContainer = document.getElementById('basic-parameters-container');
        console.log('Basic container:', basicContainer);
        
        if (!config.chunking_strategy && !config.embedding_model) {
            basicContainer.innerHTML = `<p style="${smallStyle}; color: red; font-size: 1rem;">DEBUG: No editable parameters found for this template.</p>`;
            console.error('No parameters found in repository_configuration');
            console.log('Full template:', this.currentTemplate);
            return;
        }
        
        console.log('Rendering parameters - chunking_strategy exists:', !!config.chunking_strategy);
        console.log('Rendering parameters - embedding_model exists:', !!config.embedding_model);
        
        basicContainer.innerHTML = `
            ${config.chunking_strategy ? `
            <div style="${formGroupStyle}">
                <label for="chunking_strategy" style="${labelStyle}">Chunking Strategy</label>
                <select id="chunking_strategy" data-param="chunking_strategy" style="${inputStyle}">
                    ${this.renderOptions('chunking_strategy', config.chunking_strategy)}
                </select>
                <small style="${smallStyle}">${config.chunking_strategy.description || ''}</small>
            </div>
            ` : ''}

            ${config.embedding_model ? `
            <div style="${formGroupStyle}">
                <label for="embedding_model" style="${labelStyle}">Embedding Model</label>
                <select id="embedding_model" data-param="embedding_model" style="${inputStyle}">
                    ${this.renderOptions('embedding_model', config.embedding_model)}
                </select>
                <small style="${smallStyle}">${config.embedding_model.description || ''}</small>
            </div>
            ` : ''}

            ${config.chunk_size ? `
            <div id="chunk_size_group" style="display: none; ${formGroupStyle}">
                <label for="chunk_size" style="${labelStyle}">Chunk Size (characters)</label>
                <input type="number" id="chunk_size" data-param="chunk_size" style="${inputStyle}"
                       min="${config.chunk_size.min || 100}" max="${config.chunk_size.max || 5000}"
                       value="${this.getDefaultValue('chunk_size', config.chunk_size.default || 1000)}">
                <small style="${smallStyle}">${config.chunk_size.description || ''}</small>
            </div>
            ` : ''}

            ${config.chunk_overlap ? `
            <div id="chunk_overlap_group" style="display: none; ${formGroupStyle}">
                <label for="chunk_overlap" style="${labelStyle}">Chunk Overlap (characters)</label>
                <input type="number" id="chunk_overlap" data-param="chunk_overlap" style="${inputStyle}"
                       min="${config.chunk_overlap.min || 0}" max="${config.chunk_overlap.max || 500}"
                       value="${this.getDefaultValue('chunk_overlap', config.chunk_overlap.default || 200)}">
                <small style="${smallStyle}">${config.chunk_overlap.description || ''}</small>
            </div>
            ` : ''}
        `;
        
        console.log('Basic container HTML set, innerHTML length:', basicContainer.innerHTML.length);

        // Advanced parameters (empty for now)
        const advancedContainer = document.getElementById('advanced-parameters-container');
        advancedContainer.innerHTML = `
            <p style="${smallStyle}">No advanced parameters available for this template type.</p>
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
        
        const formGroupStyle = 'margin-bottom: 1.5rem;';
        const labelStyle = 'display: block; margin-bottom: 0.5rem; color: #e5e7eb; font-weight: 500; font-size: 0.875rem;';
        const inputStyle = 'width: 100%; padding: 0.5rem 0.75rem; background: #2d3748; border: 1px solid rgba(255,255,255,0.1); border-radius: 0.375rem; color: #fff; font-size: 0.875rem;';
        const smallStyle = 'display: block; margin-top: 0.25rem; color: #9ca3af; font-size: 0.75rem;';
        
        let hasParams = false;
        let paramsHtml = '';
        
        console.log('Checking for mcp_tool_name:', !!config.mcp_tool_name);
        console.log('Checking for mcp_context_prompt:', !!config.mcp_context_prompt);
        console.log('Checking for target_database:', !!config.target_database);
        
        if (config.mcp_tool_name) {
            hasParams = true;
            paramsHtml += `
            <div style="${formGroupStyle}">
                <label for="mcp_tool_name" style="${labelStyle}">MCP Tool Name</label>
                <input type="text" id="mcp_tool_name" data-param="mcp_tool_name" style="${inputStyle}"
                       value="${this.getDefaultValue('mcp_tool_name', config.mcp_tool_name.default || '')}"
                       placeholder="${config.mcp_tool_name.placeholder || ''}">
                <small style="${smallStyle}">${config.mcp_tool_name.description || ''}</small>
            </div>`;
        }
        
        if (config.mcp_context_prompt) {
            hasParams = true;
            paramsHtml += `
            <div style="${formGroupStyle}">
                <label for="mcp_context_prompt" style="${labelStyle}">MCP Context Prompt</label>
                <input type="text" id="mcp_context_prompt" data-param="mcp_context_prompt" style="${inputStyle}"
                       value="${this.getDefaultValue('mcp_context_prompt', config.mcp_context_prompt.default || '')}"
                       placeholder="${config.mcp_context_prompt.placeholder || ''}">
                <small style="${smallStyle}">${config.mcp_context_prompt.description || ''}</small>
            </div>`;
        }
        
        if (config.target_database) {
            hasParams = true;
            paramsHtml += `
            <div style="${formGroupStyle}">
                <label for="target_database" style="${labelStyle}">Target Database</label>
                <input type="text" id="target_database" data-param="target_database" style="${inputStyle}"
                       value="${this.getDefaultValue('target_database', config.target_database.default || 'Teradata')}"
                       placeholder="${config.target_database.placeholder || 'Teradata'}">
                <small style="${smallStyle}">${config.target_database.description || ''}</small>
            </div>`;
        }
        
        basicContainer.innerHTML = hasParams ? paramsHtml : `<p style="${smallStyle}">No editable basic parameters found for this template.</p>`;
        
        console.log('Basic container HTML set, innerHTML length:', basicContainer.innerHTML.length);
        console.log('Has params:', hasParams);

        // Advanced parameters
        const advancedContainer = document.getElementById('advanced-parameters-container');
        const outputConfig = this.currentTemplate.output_configuration || {};
        console.log('Output configuration:', outputConfig);
        
        const checkboxStyle = 'margin-right: 0.5rem;';
        const checkboxLabelStyle = 'color: #e5e7eb; font-weight: 500; font-size: 0.875rem;';
        
        advancedContainer.innerHTML = `
            ${outputConfig.is_most_efficient ? `
            <div style="${formGroupStyle}">
                <label style="${checkboxLabelStyle}">
                    <input type="checkbox" id="is_most_efficient" data-param="is_most_efficient" style="${checkboxStyle}"
                           ${this.getDefaultValue('is_most_efficient', outputConfig.is_most_efficient.value) ? 'checked' : ''}>
                    Mark as Champion (Most Efficient)
                </label>
                <small style="${smallStyle}">${outputConfig.is_most_efficient.description || ''}</small>
            </div>
            ` : ''}

            ${outputConfig.estimated_tokens ? `
            <div style="${formGroupStyle}">
                <label for="input_tokens" style="${labelStyle}">Estimated Input Tokens</label>
                <input type="number" id="input_tokens" data-param="input_tokens" style="${inputStyle}"
                       value="${this.getDefaultValue('input_tokens', outputConfig.estimated_tokens.input_tokens.value || 150)}">
                <small style="${smallStyle}">${outputConfig.estimated_tokens.input_tokens.description || ''}</small>
            </div>

            <div style="${formGroupStyle}">
                <label for="output_tokens" style="${labelStyle}">Estimated Output Tokens</label>
                <input type="number" id="output_tokens" data-param="output_tokens" style="${inputStyle}"
                       value="${this.getDefaultValue('output_tokens', outputConfig.estimated_tokens.output_tokens.value || 180)}">
                <small style="${smallStyle}">${outputConfig.estimated_tokens.output_tokens.description || ''}</small>
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
        
        const alertStyle = 'padding: 1rem; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 0.375rem; margin-bottom: 1rem;';
        const tableStyle = 'width: 100%; border-collapse: collapse;';
        const tdStyle = 'padding: 0.5rem; border-bottom: 1px solid rgba(255,255,255,0.1); color: #e5e7eb;';
        const codeStyle = 'background: #2d3748; padding: 0.125rem 0.375rem; border-radius: 0.25rem; color: #F15F22; font-family: monospace; font-size: 0.875rem;';
        const badgeStyle = 'display: inline-block; padding: 0.25rem 0.5rem; background: #3b82f6; color: white; border-radius: 0.25rem; font-size: 0.75rem; font-weight: 600;';
        
        infoContainer.innerHTML = `
            <div style="${alertStyle}">
                <strong style="color: #60a5fa;">System Parameters (Read-Only)</strong>
                <p style="margin: 0.5rem 0 0 0; color: #9ca3af; font-size: 0.875rem;">These parameters are managed by the system and cannot be edited.</p>
            </div>

            <table style="${tableStyle}">
                <tbody>
                    <tr>
                        <td style="${tdStyle}"><strong>Template ID:</strong></td>
                        <td style="${tdStyle}"><code style="${codeStyle}">${template.template_id}</code></td>
                    </tr>
                    <tr>
                        <td style="${tdStyle}"><strong>Template Type:</strong></td>
                        <td style="${tdStyle}"><code style="${codeStyle}">${this.templateType}</code></td>
                    </tr>
                    <tr>
                        <td style="${tdStyle}"><strong>Version:</strong></td>
                        <td style="${tdStyle}">${template.template_version || 'N/A'}</td>
                    </tr>
                    <tr>
                        <td style="${tdStyle}"><strong>Description:</strong></td>
                        <td style="${tdStyle}">${template.description || 'N/A'}</td>
                    </tr>
                    ${template.repository_configuration ? `
                    <tr>
                        <td style="${tdStyle}"><strong>Max File Size:</strong></td>
                        <td style="${tdStyle}">${template.document_configuration?.max_file_size_mb || 50} MB</td>
                    </tr>
                    <tr>
                        <td style="${tdStyle}"><strong>Supported Types:</strong></td>
                        <td style="${tdStyle}">${(template.document_configuration?.supported_types || []).join(', ')}</td>
                    </tr>
                    ` : ''}
                    ${template.strategy_template ? `
                    <tr>
                        <td style="${tdStyle}"><strong>Phase Count:</strong></td>
                        <td style="${tdStyle}">${template.strategy_template.phase_count}</td>
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
                    t.style.borderBottomColor = 'transparent';
                    t.style.color = '#9ca3af';
                });
                tab.classList.add('active');
                tab.style.borderBottomColor = '#F15F22';
                tab.style.color = '#F15F22';
                
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
            saveBtn.innerHTML = '<i class="fas fa-save"></i> Save Defaults';
        }
    }

    /**
     * Reset to system defaults
     */
    async resetDefaults() {
        console.log('resetDefaults called');
        if (!confirm('Reset all customizations to system defaults?')) {
            console.log('User cancelled reset');
            return;
        }

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

    /**
     * Close the modal
     */
    closeModal() {
        console.log('closeModal called, isDirty:', this.isDirty);
        
        if (this.isDirty && !confirm('You have unsaved changes. Close anyway?')) {
            console.log('User cancelled close due to unsaved changes');
            return;
        }
        
        if (this.modal) {
            console.log('Removing modal from DOM');
            this.modal.remove();
            this.modal = null;
        }
    }
}

// Export singleton instance
export const templateEditModal = new TemplateEditModal();
