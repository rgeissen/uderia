/**
 * RAG Collection Management - Template System
 * 
 * Handles template loading, card rendering, and template field switching.
 */

import { showNotification } from './utils.js';

/**
 * Get default template ID based on type
 * @param {string} type - 'planner' or 'knowledge'
 * @returns {string|null} Default template ID or null if none available
 */
export function getDefaultTemplateId(type = 'planner') {
    if (!window.templateManager) {
        console.warn('[Template System] templateManager not available');
        return null;
    }
    
    const allTemplates = window.templateManager.getAllTemplates();
    if (!allTemplates || allTemplates.length === 0) {
        console.warn('[Template System] No templates available');
        return null;
    }
    
    // Filter templates by type
    const templates = allTemplates.filter(template => {
        const templateType = template.template_type || '';
        if (type === 'knowledge_graph') {
            return templateType === 'knowledge_graph';
        } else if (type === 'knowledge') {
            return templateType === 'knowledge_repository';
        } else {
            return templateType !== 'knowledge_repository' && templateType !== 'knowledge_graph';
        }
    });
    
    if (templates.length === 0) {
        console.warn(`[Template System] No ${type} templates available`);
        return null;
    }
    
    // Return first available template of the requested type
    return templates[0].template_id;
}

/**
 * Initialize template system on page load
 * @param {HTMLSelectElement} templateDropdown - Template type dropdown element
 * @param {Function} switchFieldsCallback - Callback to switch template fields
 */
export async function initializeTemplateSystem(templateDropdown, switchFieldsCallback) {
    try {
        if (!window.templateManager) {
            console.error('[Template System] templateManager not available on window object');
            return;
        }
        
        // Initialize template manager
        await window.templateManager.initialize();
        
        // Populate template dropdown
        if (templateDropdown) {
            const defaultTemplateId = getDefaultTemplateId('planner');
            window.templateManager.populateTemplateDropdown(templateDropdown, {
                includeDeprecated: false,
                includeComingSoon: true,
                selectedTemplateId: defaultTemplateId
            });
            
            // Trigger initial field rendering
            if (switchFieldsCallback) {
                await switchFieldsCallback();
            }
        }
        
        // Load template cards dynamically
        await loadTemplateCards();
    } catch (error) {
        console.error('[Template System] Failed to initialize:', error);
        console.error('[Template System] Error stack:', error.stack);
        showNotification('error', 'Failed to load templates: ' + error.message);
    }
}

/**
 * Load template cards dynamically from backend
 */
export async function loadTemplateCards() {
    // Load Planner repository templates
    const plannerContainer = document.getElementById('rag-templates-container');
    if (plannerContainer) {
        await loadTemplateCardsIntoContainer(plannerContainer, 'planner');
    }

    // Load Knowledge repository templates
    const knowledgeContainer = document.getElementById('knowledge-constructors-container');
    if (knowledgeContainer) {
        await loadTemplateCardsIntoContainer(knowledgeContainer, 'knowledge');
    }

    // Load Knowledge Graph constructor templates
    const kgContainer = document.getElementById('kg-constructors-container');
    if (kgContainer) {
        await loadTemplateCardsIntoContainer(kgContainer, 'knowledge_graph');
    }
}

/**
 * Load template cards into a specific container
 * @param {HTMLElement} container - Container element
 * @param {string} filterType - 'planner' or 'knowledge'
 */
async function loadTemplateCardsIntoContainer(container, filterType) {
    try {
        if (!window.templateManager) {
            console.error(`[Template Cards] templateManager not initialized for ${filterType}`);
            container.innerHTML = '<div class="col-span-full text-red-400 text-sm">Template manager not initialized</div>';
            return;
        }
        
        const allTemplates = window.templateManager.getAllTemplates();
        
        // Filter templates by type
        const templates = allTemplates.filter(template => {
            const templateType = template.template_type || '';
            if (filterType === 'knowledge_graph') {
                return templateType === 'knowledge_graph';
            } else if (filterType === 'knowledge') {
                return templateType === 'knowledge_repository';
            } else {
                // Planner templates: anything that's not knowledge or knowledge_graph
                return templateType !== 'knowledge_repository' && templateType !== 'knowledge_graph';
            }
        });
        
        if (!templates || templates.length === 0) {
            container.innerHTML = `<div class="col-span-full text-gray-400 text-sm">No ${filterType} templates available</div>`;
            return;
        }
        
        container.innerHTML = '';
        
        templates.forEach((template, index) => {
            try {
                const card = createTemplateCard(template, index, filterType);
                container.appendChild(card);
            } catch (cardError) {
                console.error(`[Template Cards] Failed to create card for template ${template.template_id}:`, cardError);
            }
        });
        
    } catch (error) {
        console.error(`[Template Cards] Failed to load ${filterType} templates:`, error);
        container.innerHTML = `<div class="col-span-full text-red-400 text-sm">Failed to load templates: ${error.message}</div>`;
    }
}

/**
 * Create a template card element
 * @param {object} template - Template metadata
 * @param {number} index - Template index for color rotation
 * @param {string} filterType - 'planner' or 'knowledge'
 * @returns {HTMLElement} Template card element
 */
export function createTemplateCard(template, index, filterType = 'planner') {
    const isComingSoon = template.status === 'coming_soon';
    const isKnowledge = filterType === 'knowledge' || template.template_type === 'knowledge_repository';
    const isKnowledgeGraph = filterType === 'knowledge_graph' || template.template_type === 'knowledge_graph';

    const card = document.createElement('div');
    card.className = `glass-panel rounded-xl p-6 transition-colors ${isComingSoon ? 'opacity-50 cursor-not-allowed' : 'hover:border-[#F15F22] cursor-pointer'}`;
    card.setAttribute('data-template-id', template.template_id);

    // Icon colors array — purple/violet for KG, green for knowledge, blue/orange for planner
    const iconColors = isKnowledgeGraph ? ['purple', 'violet', 'fuchsia'] : isKnowledge ? ['green', 'emerald', 'teal'] : ['blue', 'purple', 'orange', 'pink', 'indigo'];
    const colorIndex = index % iconColors.length;
    const color = iconColors[colorIndex];
    
    card.innerHTML = `
        <div class="flex items-start justify-between mb-4">
            <div class="w-12 h-12 bg-${color}-500/20 rounded-lg flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-${color}-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    ${getTemplateIcon(template.template_type)}
                </svg>
            </div>
            <div class="flex items-center gap-2">
                <span class="px-2 py-1 ${isComingSoon ? 'bg-gray-500/20 text-gray-400' : 'bg-green-500/20 text-green-400'} text-xs font-medium rounded">${isComingSoon ? 'Coming Soon' : 'Ready'}</span>
            </div>
        </div>
        <h3 class="text-lg font-bold text-white mb-2">${template.display_name || template.template_name}</h3>
        <p class="text-sm text-gray-400 mb-4">${template.description || 'No description available'}</p>
        <div class="space-y-2 text-xs text-gray-500">
            <div class="flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                <span>Template ID: ${template.template_id}</span>
            </div>
        </div>
        <div class="mt-4 pt-4 border-t border-white/10">
            <div class="flex gap-2">
                <button class="template-edit-btn card-btn card-btn--neutral flex-1 flex items-center justify-center gap-2" ${isComingSoon ? 'disabled' : ''}>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                    </svg>
                    Edit
                </button>
                <button class="template-deploy-btn card-btn card-btn--primary flex-1 flex items-center justify-center gap-2" ${isComingSoon ? 'disabled' : ''}>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                    </svg>
                    Deploy
                </button>
            </div>
        </div>
    `;
    
    // Add button handlers (only for active templates)
    if (!isComingSoon) {
        const editBtn = card.querySelector('.template-edit-btn');
        const deployBtn = card.querySelector('.template-deploy-btn');
        
        // Edit button - Open edit modal
        editBtn.addEventListener('click', async (e) => {
            e.stopPropagation(); // Prevent card click
            
            try {
                // Load full template from API
                const token = localStorage.getItem('tda_auth_token');
                const response = await fetch(`/api/v1/rag/templates/${template.template_id}/full`, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });
                if (!response.ok) {
                    throw new Error(`Failed to load template: ${response.statusText}`);
                }
                
                const data = await response.json();
                if (data.status !== 'success') {
                    throw new Error(data.message || 'Failed to load template');
                }
                
                const fullTemplate = data.template;
                console.log('Full template loaded:', fullTemplate);
                
                // Import and open edit modal with full template manifest (with cache busting)
                const { templateEditModal } = await import(`./templateEditModal.js?v=${Date.now()}`);
                await templateEditModal.open(template.template_id, fullTemplate);
                
            } catch (error) {
                console.error('Error opening edit modal:', error);
                if (window.showToast) {
                    window.showToast('error', 'Failed to open template editor');
                }
            }
        });
        
        // Deploy button - Execute template with defaults
        deployBtn.addEventListener('click', async (e) => {
            e.stopPropagation(); // Prevent card click
            console.log('[Deploy] ========== DEPLOY BUTTON CLICKED ==========');
            console.log('[Deploy] Button clicked for template:', template.template_id);
            console.log('[Deploy] Template type:', template.template_type);
            console.log('[Deploy] isKnowledge:', isKnowledge);
            console.log('[Deploy] Full template object:', template);
            
            try {
                // Check if conversation mode is fully initialized
                console.log('[Deploy] Checking conversation initialization...');
                
                // Helper: derive initialization if global state is missing
                const deriveInitState = () => {
                    // Consider initialized if conversation view is active and a session is loaded
                    const conversationView = document.getElementById('conversation-view');
                    const isConversationVisible = conversationView && !conversationView.classList.contains('hidden');
                    const hasSessionLoaded = window.state && window.state.sessionLoaded === true;
                    // Also check header dots for connected state
                    const mcpDot = document.getElementById('mcp-status-dot');
                    const llmDot = document.getElementById('llm-status-dot');
                    const ctxDot = document.getElementById('context-status-dot');
                    const sseDot = document.getElementById('sse-status-dot');
                    const indicatorsGreen = [mcpDot, llmDot, ctxDot, sseDot].every(dot => dot ? dot.classList.contains('connected') || dot.classList.contains('idle') : true);
                    return { initialized: Boolean(isConversationVisible && hasSessionLoaded && indicatorsGreen) };
                };
                
                // Use global init state if present, otherwise derive
                const initState = window.__conversationInitState || deriveInitState();
                console.log('[Deploy] Initialization state:', initState);
                
                // Only proceed if explicitly initialized
                if (!initState || !initState.initialized) {
                    console.log('[Deploy] Conversation not initialized');
                    if (window.showAppBanner) {
                        window.showAppBanner(
                            'Please initialize the system first. Go to Setup and click "Save & Connect", or go to Conversations and click "Start Conversation".',
                            'info'
                        );
                    }
                    return;
                }
                
                console.log('[Deploy] System fully initialized, proceeding...');
                
                // Load saved defaults with authentication
                console.log('[Deploy] Fetching defaults...');
                const response = await fetch(`/api/v1/rag/templates/${template.template_id}/defaults`, {
                    headers: {
                        'Authorization': `Bearer ${localStorage.getItem('tda_auth_token')}`
                    }
                });
                console.log('[Deploy] Defaults response status:', response.status);
                const defaultsData = response.ok ? await response.json() : { defaults: {} };
                console.log('[Deploy] Defaults data:', defaultsData);
                
                // Store defaults for the template system to use
                if (Object.keys(defaultsData.defaults || {}).length > 0) {
                    console.log('[Deploy] Storing template defaults:', defaultsData.defaults);
                    window.templateDefaults = defaultsData.defaults;
                }
                
                // Open modal - different modal for knowledge_graph vs knowledge vs planner templates
                console.log('[Deploy] Opening modal...');
                if (isKnowledgeGraph) {
                    // Open KG constructor modal
                    console.log('[Deploy] Opening knowledge graph constructor modal');
                    try {
                        const { openKgConstructorModal } = await import(`./kgConstructorModal.js?v=${Date.now()}`);
                        openKgConstructorModal(template, defaultsData.defaults || {});
                    } catch (err) {
                        console.error('[Deploy] Failed to load KG constructor modal:', err);
                        if (window.showToast) {
                            window.showToast('error', 'Knowledge Graph constructor modal not available');
                        }
                    }
                } else if (isKnowledge) {
                    // Open knowledge repository modal with template defaults
                    console.log('[Deploy] Opening knowledge repository modal');
                    if (window.openKnowledgeRepositoryModalWithTemplate) {
                        window.openKnowledgeRepositoryModalWithTemplate(template, defaultsData.defaults || {});
                    } else {
                        console.error('[Deploy] openKnowledgeRepositoryModalWithTemplate not found');
                        if (window.showToast) {
                            window.showToast('error', 'Knowledge repository modal not available');
                        }
                    }
                } else if (window.ragCollectionManagement && window.ragCollectionManagement.openAddRagCollectionModal) {
                    // Open planner collection modal
                    console.log('[Deploy] Opening planner collection modal');
                    await window.ragCollectionManagement.openAddRagCollectionModal();
                    
                    // Enable template population, then select the template
                    setTimeout(() => {
                        // First enable template population
                        const templateRadio = document.getElementById('rag-population-with-template');
                        if (templateRadio) {
                            templateRadio.checked = true;
                            templateRadio.dispatchEvent(new Event('change', { bubbles: true }));
                            console.log('[Deploy] Enabled template population');
                        }
                        
                        // Enable LLM method (for auto-generation workflow)
                        const llmMethodRadio = document.getElementById('rag-template-method-llm');
                        if (llmMethodRadio) {
                            llmMethodRadio.checked = true;
                            console.log('[Deploy] Enabled LLM method');
                        }
                        
                        // Then select the template (slight delay to let radio change take effect)
                        setTimeout(() => {
                            const templateDropdown = document.getElementById('rag-collection-template-type');
                            if (templateDropdown) {
                                templateDropdown.value = template.template_id;
                                templateDropdown.dispatchEvent(new Event('change', { bubbles: true }));
                                console.log('[Deploy] Template selected:', template.template_id);
                                
                                // After template loads, show LLM workflow and hide manual fields
                                setTimeout(() => {
                                    const manualFields = document.getElementById('rag-collection-manual-fields');
                                    const llmWorkflow = document.getElementById('rag-collection-llm-workflow');
                                    
                                    if (manualFields) {
                                        manualFields.classList.add('hidden');
                                        console.log('[Deploy] Hidden manual fields');
                                    }
                                    
                                    if (llmWorkflow) {
                                        llmWorkflow.classList.remove('hidden');
                                        console.log('[Deploy] Showing LLM workflow');
                                    }
                                }, 100);
                            }
                        }, 50);
                    }, 100);
                } else {
                    console.error('[Deploy] openAddRagCollectionModal not found');
                }
                
            } catch (error) {
                console.error('[Deploy] Error deploying template:', error);
                if (window.showToast) {
                    window.showToast('error', 'Failed to deploy template');
                }
            }
        });
        console.log('[Deploy] Event listener attached to Deploy button');
        
        // Card click handler - for planner templates, open the Add Planner Repository modal
        if (!isKnowledge) {
            card.addEventListener('click', (e) => {
                // Only trigger if not clicking on a button
                if (!e.target.closest('button')) {
                    console.log('[Card Click] Planner template card clicked, opening Add Planner Repository modal...');
                    // Open the Add Planner Repository modal
                    const modal = document.getElementById('add-rag-collection-modal-overlay');
                    if (modal) {
                        modal.classList.remove('hidden');
                        // Trigger animations
                        requestAnimationFrame(() => {
                            modal.classList.remove('opacity-0');
                            const modalContent = document.getElementById('add-rag-collection-modal-content');
                            if (modalContent) {
                                modalContent.classList.remove('opacity-0', 'scale-95');
                            }
                        });
                        console.log('[Card Click] Modal opened');
                        
                        // Set the template ID in the hidden field and trigger template load
                        setTimeout(() => {
                            const templateTypeField = document.getElementById('rag-collection-template-type');
                            if (templateTypeField) {
                                templateTypeField.value = template.template_id;
                                console.log('[Card Click] Set template type to:', template.template_id);
                                // Trigger change event to load template fields
                                templateTypeField.dispatchEvent(new Event('change', { bubbles: true }));
                                
                                // Show manual entry fields by default for card clicks
                                setTimeout(() => {
                                    const manualFields = document.getElementById('rag-collection-manual-fields');
                                    if (manualFields) {
                                        manualFields.classList.remove('hidden');
                                    }
                                    const llmWorkflow = document.getElementById('rag-collection-llm-workflow');
                                    if (llmWorkflow) {
                                        llmWorkflow.classList.add('hidden');
                                    }
                                }, 150);
                            }
                        }, 100);
                    } else {
                        console.error('[Card Click] Modal not found: add-rag-collection-modal-overlay');
                    }
                }
            });
        }
    }
    
    return card;
}

/**
 * Get SVG path for template icon based on type
 * @param {string} templateType - Template type identifier
 * @returns {string} SVG path string
 */
export function getTemplateIcon(templateType) {
    const icons = {
        'sql_query': '<path stroke-linecap="round" stroke-linejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />',
        'api_request': '<path stroke-linecap="round" stroke-linejoin="round" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />',
        'knowledge_repository': '<path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />',
        'knowledge_graph': '<circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" /><path stroke-linecap="round" stroke-linejoin="round" d="M12 7v4m-5.2 5.8L11 13m2 0l4.2 3.8" />',
        'default': '<path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />'
    };
    
    return icons[templateType] || icons['default'];
}

/**
 * Reload template configuration from server
 * @param {string} templateId - Template ID to reload
 * @returns {Promise<object|null>} Template configuration or null if failed
 */
export async function reloadTemplateConfiguration(templateId) {
    try {
        const id = templateId || getDefaultTemplateId('planner');
        // Add cache-busting parameter to force fresh load
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/rag/templates/${id}/config?_=${Date.now()}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (response.ok) {
            const configData = await response.json();
            return configData;
        } else {
            return null;
        }
    } catch (error) {
        console.error('[Template Config] Error reloading configuration:', error);
        return null;
    }
}
