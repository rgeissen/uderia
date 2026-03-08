/**
 * Template Manager Module
 * 
 * Handles dynamic template loading, field rendering, and template-specific UI logic.
 * This module makes the frontend modular by loading templates from the backend API
 * instead of using hardcoded template types.
 */

class TemplateManager {
    constructor() {
        this.templates = [];
        this.currentTemplate = null;
        this.templateCache = new Map();
    }

    /**
     * Initialize the template manager and load available templates
     */
    async initialize() {
        try {
            await this.loadTemplates();
        } catch (error) {
            console.error('Failed to initialize template manager:', error);
            throw error;
        }
    }

    /**
     * Load all available templates from the API
     */
    async loadTemplates() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch('/api/v1/rag/templates/list', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                this.templates = data.templates || [];
            } else {
                throw new Error(data.message || 'Failed to load templates');
            }
        } catch (error) {
            console.error('Error loading templates:', error);
            throw error;
        }
    }

    /**
     * Get full template configuration including metadata and fields
     * @param {string} templateId - The template identifier
     * @returns {Promise<object>} Template configuration object
     */
    async getTemplateConfig(templateId) {
        // Check cache first
        if (this.templateCache.has(templateId)) {
            return this.templateCache.get(templateId);
        }

        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch(`/api/v1/rag/templates/${templateId}/config`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                this.templateCache.set(templateId, data.config);
                return data.config;
            } else {
                throw new Error(data.message || 'Failed to load template config');
            }
        } catch (error) {
            console.error(`Error loading config for template ${templateId}:`, error);
            throw error;
        }
    }

    /**
     * Get plugin manifest information for a template
     * @param {string} templateId - The template identifier
     * @returns {Promise<object>} Plugin manifest object
     */
    async getPluginInfo(templateId) {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch(`/api/v1/rag/templates/${templateId}/plugin-info`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                return data.plugin_info;
            } else {
                // Plugin info may not exist for legacy templates
                return null;
            }
        } catch (error) {
            console.error(`Error loading plugin info for template ${templateId}:`, error);
            return null;
        }
    }

    /**
     * Get a template by ID
     * @param {string} templateId - The template identifier
     * @returns {object|null} Template metadata object or null
     */
    getTemplate(templateId) {
        return this.templates.find(t => t.template_id === templateId) || null;
    }

    /**
     * Get all templates
     * @returns {Array} Array of template metadata objects
     */
    getAllTemplates() {
        return this.templates;
    }

    /**
     * Get active templates (status !== 'deprecated')
     * @returns {Array} Array of active template metadata objects
     */
    getActiveTemplates() {
        return this.templates.filter(t => t.status !== 'deprecated');
    }

    /**
     * Set the current template
     * @param {string} templateId - The template identifier
     */
    setCurrentTemplate(templateId) {
        this.currentTemplate = this.getTemplate(templateId);
        return this.currentTemplate;
    }

    /**
     * Clear the template cache (useful after reload)
     */
    clearCache() {
        this.templateCache.clear();
    }

    /**
     * Reload templates from the server
     */
    async reload() {
        this.clearCache();
        await this.loadTemplates();
    }

    /**
     * Populate a dropdown select element with available templates
     * @param {HTMLSelectElement} selectElement - The select element to populate
     * @param {object} options - Options for filtering and formatting
     */
    populateTemplateDropdown(selectElement, options = {}) {
        const {
            includeDeprecated = false,
            includeComingSoon = true,
            selectedTemplateId = null
        } = options;

        // Clear existing options
        selectElement.innerHTML = '';

        // Filter templates
        let templates = includeDeprecated ? this.templates : this.getActiveTemplates();

        // Add template options
        templates.forEach(template => {
            const option = document.createElement('option');
            option.value = template.template_id;
            option.textContent = template.template_name;
            
            if (template.status === 'deprecated') {
                option.textContent += ' (Deprecated)';
                option.disabled = true;
            } else if (template.status === 'coming_soon') {
                option.textContent += ' (Coming Soon)';
                option.disabled = true;
            }
            
            if (selectedTemplateId && template.template_id === selectedTemplateId) {
                option.selected = true;
            }
            
            selectElement.appendChild(option);
        });

        // Add "Coming Soon" placeholders if enabled
        if (includeComingSoon) {
            const comingSoonTemplates = [
                { id: 'api_call', name: 'API Call Template (Coming Soon)' },
                { id: 'custom', name: 'Custom Template (Coming Soon)' }
            ];

            comingSoonTemplates.forEach(template => {
                const option = document.createElement('option');
                option.value = template.id;
                option.textContent = template.name;
                option.disabled = true;
                selectElement.appendChild(option);
            });
        }
    }

    /**
     * Render template-specific fields dynamically based on template configuration
     * @param {string} templateId - The template identifier
     * @param {HTMLElement} containerElement - The container element to render fields into
     * @returns {Promise<void>}
     */
    async renderTemplateFields(templateId, containerElement) {
        try {
            const config = await this.getTemplateConfig(templateId);
            const pluginInfo = await this.getPluginInfo(templateId);

            // Clear container
            containerElement.innerHTML = '';

            // For SQL templates, render SQL-specific fields
            const template = this.getTemplate(templateId);
            if (template && template.template_type === 'sql_query') {
                this.renderSQLTemplateFields(containerElement, config, pluginInfo);
            } else {
                // Generic field rendering for other template types
                this.renderGenericTemplateFields(containerElement, config, pluginInfo);
            }
        } catch (error) {
            console.error(`Error rendering fields for template ${templateId}:`, error);
            containerElement.innerHTML = '<p class="text-red-400">Error loading template fields</p>';
        }
    }

    /**
     * Render SQL template specific fields
     * @private
     */
    renderSQLTemplateFields(container, config, pluginInfo) {
        const fieldsHTML = `
            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class="block text-xs text-gray-400 mb-1">Database Name</label>
                    <input type="text" id="rag-collection-template-db" 
                           class="w-full p-2 bg-gray-600 border border-gray-500 rounded-md focus:ring-2 focus:ring-teradata-orange outline-none text-white text-sm"
                           placeholder="e.g., production_db">
                </div>
                <div>
                    <label class="block text-xs text-gray-400 mb-1">MCP Tool Name</label>
                    <input type="text" id="rag-collection-template-tool" readonly
                           class="w-full p-2 bg-gray-600 border border-gray-500 rounded-md text-gray-400 text-sm"
                           placeholder="Loading..."
                           value="${config?.default_mcp_tool || ''}">
                    <p class="text-xs text-gray-500 mt-1">From template configuration</p>
                </div>
            </div>

            <!-- Examples -->
            <div>
                <label class="block text-xs text-gray-400 mb-1">Examples (SQL Queries)</label>
                <textarea id="rag-collection-template-examples" 
                          class="w-full p-2 bg-gray-600 border border-gray-500 rounded-md focus:ring-2 focus:ring-teradata-orange outline-none text-white text-sm font-mono"
                          rows="4"
                          placeholder="Enter SQL queries, one per line or separated by semicolons"></textarea>
                <p class="text-xs text-gray-500 mt-1">Provide example SQL queries for this collection</p>
            </div>

            <!-- MCP Context Prompt -->
            <div>
                <label class="block text-xs text-gray-400 mb-1">MCP Context Prompt</label>
                <textarea id="rag-collection-template-context" 
                          class="w-full p-2 bg-gray-600 border border-gray-500 rounded-md focus:ring-2 focus:ring-teradata-orange outline-none text-white text-sm"
                          rows="3"
                          placeholder="Prompt to retrieve database schema information">${config?.default_mcp_context_prompt || ''}</textarea>
                <p class="text-xs text-gray-500 mt-1">This prompt will be used to gather database context via MCP</p>
            </div>
        `;

        container.innerHTML = fieldsHTML;
        container.classList.remove('hidden');
    }

    /**
     * Render generic template fields (for future template types)
     * @private
     */
    renderGenericTemplateFields(container, config, pluginInfo) {
        const fieldsHTML = `
            <div class="space-y-3">
                <div>
                    <label class="block text-xs text-gray-400 mb-1">Template Configuration</label>
                    <textarea id="rag-collection-template-config" 
                              class="w-full p-2 bg-gray-600 border border-gray-500 rounded-md focus:ring-2 focus:ring-teradata-orange outline-none text-white text-sm font-mono"
                              rows="6"
                              placeholder="Template-specific configuration (JSON format)">${JSON.stringify(config, null, 2)}</textarea>
                </div>
            </div>
        `;

        container.innerHTML = fieldsHTML;
        container.classList.remove('hidden');
    }

    /**
     * Get template field values from the UI
     * @param {string} templateId - The template identifier
     * @returns {object} Object containing field values
     */
    getTemplateFieldValues(templateId) {
        const template = this.getTemplate(templateId);
        
        if (template && template.template_type === 'sql_query') {
            return this.getSQLTemplateFieldValues();
        } else {
            return this.getGenericTemplateFieldValues();
        }
    }

    /**
     * Get SQL template field values
     * @private
     */
    getSQLTemplateFieldValues() {
        const dbName = document.getElementById('rag-collection-template-db')?.value || '';
        const toolName = document.getElementById('rag-collection-template-tool')?.value || '';
        const examples = document.getElementById('rag-collection-template-examples')?.value || '';
        const contextPrompt = document.getElementById('rag-collection-template-context')?.value || '';

        return {
            database_name: dbName,
            mcp_tool_name: toolName,
            examples: examples,
            mcp_context_prompt: contextPrompt
        };
    }

    /**
     * Get generic template field values
     * @private
     */
    getGenericTemplateFieldValues() {
        const configText = document.getElementById('rag-collection-template-config')?.value || '{}';

        try {
            return JSON.parse(configText);
        } catch (error) {
            console.error('Failed to parse template configuration:', error);
            return {};
        }
    }

    /**
     * Hot-reload all template plugins without restarting the application
     * Useful for development and testing new templates
     * @returns {Promise<object>} Reload result with status and count
     */
    async reloadTemplates() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch('/api/v1/rag/templates/reload', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();

            if (data.status === 'success') {
                // Clear template cache
                this.templateCache.clear();

                // Reload template list
                await this.loadTemplates();

                return {
                    success: true,
                    count: data.count,
                    templates: data.templates,
                    message: data.message
                };
            } else {
                throw new Error(data.message || 'Failed to reload templates');
            }
        } catch (error) {
            console.error('Error reloading templates:', error);
            return {
                success: false,
                message: error.message
            };
        }
    }

    /**
     * Validate a template plugin package before installation
     * @param {string} pluginPath - Path to the template plugin directory
     * @returns {Promise<object>} Validation result with errors and warnings
     */
    async validateTemplate(pluginPath) {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch('/api/v1/rag/templates/validate', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    plugin_path: pluginPath
                })
            });
            const data = await response.json();

            if (data.status === 'success') {
                return {
                    success: true,
                    isValid: data.is_valid,
                    errors: data.errors || [],
                    warnings: data.warnings || []
                };
            } else {
                throw new Error(data.message || 'Failed to validate template');
            }
        } catch (error) {
            console.error('Error validating template:', error);
            return {
                success: false,
                message: error.message
            };
        }
    }
}

// Create and export singleton instance
const templateManager = new TemplateManager();

// Export for use in other modules
window.templateManager = templateManager;
