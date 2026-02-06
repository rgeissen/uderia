/**
 * RAG Collection Management Handler
 * Manages the Add RAG Collection modal and collection operations
 */

import { state } from '../state.js';
import { loadRagCollections } from '../ui.js';
import * as DOM from '../domElements.js';
// Note: configState is accessed via window.configState to avoid circular imports

// RAG Module Imports
import * as RagUtils from './rag/utils.js';
import * as TemplateSystem from './rag/templateSystem.js';
import * as PopulationWorkflow from './rag/populationWorkflow.js';

/**
 * Escape HTML special characters to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Updates the CCR (Champion Case Retrieval) indicator based on current status
 */
async function updateCcrIndicator() {
    if (!DOM.ccrStatusDot || !state.appConfig.rag_enabled) {
        return;
    }

    try {
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch('/api/status', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const status = await response.json();

        if (status.rag_active) {
            DOM.ccrStatusDot.classList.remove('disconnected');
            DOM.ccrStatusDot.classList.add('connected');
        } else {
            DOM.ccrStatusDot.classList.remove('connected');
            DOM.ccrStatusDot.classList.add('disconnected');
        }
    } catch (error) {
        console.error('Failed to update CCR indicator:', error);
    }
}

// Use imported showNotification from RagUtils module
const showNotification = RagUtils.showNotification;

// Modal Elements
// Note: add-rag-collection-btn removed - templates now have Edit/Deploy buttons
const addRagCollectionModalOverlay = document.getElementById('add-rag-collection-modal-overlay');
const addRagCollectionModalContent = document.getElementById('add-rag-collection-modal-content');
const addRagCollectionModalClose = document.getElementById('add-rag-collection-modal-close');
const addRagCollectionCancel = document.getElementById('add-rag-collection-cancel');
const addRagCollectionForm = document.getElementById('add-rag-collection-form');
const addRagCollectionSubmit = document.getElementById('add-rag-collection-submit');

// Form Fields
const ragCollectionNameInput = document.getElementById('rag-collection-name');
const ragCollectionMcpServerSelect = document.getElementById('rag-collection-mcp-server');
const ragCollectionDescriptionInput = document.getElementById('rag-collection-description');

// Level 1: Population Decision Radio Buttons
const ragPopulationNone = document.getElementById('rag-population-none');
const ragPopulationWithTemplate = document.getElementById('rag-population-with-template');

// Level 2: Template Population Options
const ragCollectionTemplateOptions = document.getElementById('rag-collection-template-options');
const ragCollectionTemplateType = document.getElementById('rag-collection-template-type');

// Level 2: Population Method (Manual vs Auto-generate)
const ragTemplateMethodManual = document.getElementById('rag-template-method-manual');
const ragTemplateMethodLlm = document.getElementById('rag-template-method-llm');
const ragTemplateMethodLlmLabel = document.getElementById('rag-template-method-llm-label');
const ragTemplateMethodLlmBadge = document.getElementById('rag-template-method-llm-badge');

// Manual Entry Fields
const ragCollectionManualFields = document.getElementById('rag-collection-manual-fields');
const ragCollectionTemplateDb = document.getElementById('rag-collection-template-db');
const ragCollectionTemplateTool = document.getElementById('rag-collection-template-tool');
const ragCollectionTemplateExamples = document.getElementById('rag-collection-template-examples');
const ragCollectionTemplateAddExample = document.getElementById('rag-collection-template-add-example');

// Auto-generate with LLM Fields
const ragCollectionLlmFields = document.getElementById('rag-collection-llm-fields');
const ragCollectionLlmContextTopic = document.getElementById('rag-collection-llm-context-topic');
const ragCollectionLlmDocumentContent = document.getElementById('rag-collection-llm-document-content');
const ragCollectionLlmConversionRules = document.getElementById('rag-collection-llm-conversion-rules');
const ragCollectionLlmDb = document.getElementById('rag-collection-llm-db');
const ragCollectionLlmCount = document.getElementById('rag-collection-llm-count');

// RAG collection workflow UI elements
// NOTE: These elements support the 3-phase RAG collection creation workflow:
// Phase 1: Select template, Phase 2: Generate context, Phase 3: Generate questions
const ragCollectionGenerateContextBtn = document.getElementById('rag-collection-generate-context');
const ragCollectionGenerateQuestionsBtn = document.getElementById('rag-collection-generate-questions-btn');
// Removed: ragCollectionPopulateBtn - button no longer needed (Create Collection does everything)
const ragCollectionRefreshPromptBtn = document.getElementById('rag-collection-refresh-prompt');
const ragCollectionContextResult = document.getElementById('rag-collection-context-result');
const ragCollectionContextContent = document.getElementById('rag-collection-context-content');
const ragCollectionContextClose = document.getElementById('rag-collection-context-close');
const ragCollectionQuestionsResult = document.getElementById('rag-collection-questions-result');
const ragCollectionQuestionsList = document.getElementById('rag-collection-questions-list');
const ragCollectionQuestionsCount = document.getElementById('rag-collection-questions-count');
const ragCollectionQuestionsClose = document.getElementById('rag-collection-questions-close');
const ragCollectionLlmSubject = null;
const ragCollectionLlmTargetDb = null;
const ragCollectionLlmPromptPreview = document.getElementById('rag-collection-llm-prompt-preview');

// Context Result Modal Elements
const contextResultModalOverlay = document.getElementById('context-result-modal-overlay');
const contextResultModalContent = document.getElementById('context-result-modal-content');
const contextResultModalClose = document.getElementById('context-result-modal-close');
const contextResultModalOk = document.getElementById('context-result-modal-ok');
const contextResultPromptText = document.getElementById('context-result-prompt-text');
const contextResultFinalAnswer = document.getElementById('context-result-final-answer');
const contextResultExecutionTrace = document.getElementById('context-result-execution-trace');
const contextResultInputTokens = document.getElementById('context-result-input-tokens');
const contextResultOutputTokens = document.getElementById('context-result-output-tokens');
const contextResultTotalTokens = document.getElementById('context-result-total-tokens');

// Store the last generated context and questions for the workflow
let lastGeneratedContext = null;
let lastGeneratedQuestions = null;

let addCollectionExampleCounter = 0;

// Use imported template system functions from TemplateSystem module
const initializeTemplateSystem = async () => {
    await TemplateSystem.initializeTemplateSystem(ragCollectionTemplateType, switchTemplateFields);
};

const loadTemplateCards = TemplateSystem.loadTemplateCards;

/**
 * Original loadTemplateCards implementation - now handled by module
 * (keeping this comment for reference during migration)
 */
async function loadTemplateCards_DEPRECATED() {
    const container = document.getElementById('rag-templates-container');
    if (!container) {
        return;
    }
    
    try {
        if (!window.templateManager) {
            console.error('[Template Cards] templateManager not initialized');
            container.innerHTML = '<div class="col-span-full text-red-400 text-sm">Template manager not initialized</div>';
            return;
        }
        
        const templates = window.templateManager.getAllTemplates();
        
        if (!templates || templates.length === 0) {
            container.innerHTML = '<div class="col-span-full text-gray-400 text-sm">No templates available</div>';
            return;
        }
        
        container.innerHTML = '';
        
        templates.forEach((template, index) => {
            try {
                const card = createTemplateCard(template, index);
                container.appendChild(card);
            } catch (cardError) {
                console.error(`[Template Cards] Failed to create card for template ${template.template_id}:`, cardError);
            }
        });
        
    } catch (error) {
        console.error('[Template Cards] Failed to load:', error);
        container.innerHTML = '<div class="col-span-full text-red-400 text-sm">Failed to load templates: ' + error.message + '</div>';
    }
}

// Use imported createTemplateCard from TemplateSystem module
const createTemplateCard = TemplateSystem.createTemplateCard;

// Use imported getTemplateIcon from TemplateSystem module
const getTemplateIcon = TemplateSystem.getTemplateIcon;

/**
 * Reload template configuration from server to get latest settings
 */
async function reloadTemplateConfiguration() {
    try {
        const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
        const templateId = ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
        // Add cache-busting parameter to force fresh load
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/rag/templates/${templateId}/config?_=${Date.now()}`, {
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

/**
 * Generate and display the question generation prompt preview
 */
async function refreshQuestionGenerationPrompt() {
    if (!ragCollectionLlmPromptPreview) return;
    
    // Get selected template
    const selectedTemplateId = ragCollectionTemplateType?.value;
    if (!selectedTemplateId) {
        ragCollectionLlmPromptPreview.value = 'Please select a template first...';
        return;
    }
    
    // Get values from dynamically generated fields
    const contextTopicEl = document.getElementById('rag-collection-llm-context-topic');
    const numExamplesEl = document.getElementById('rag-collection-llm-num-examples');
    const databaseNameEl = document.getElementById('rag-collection-llm-database-name');
    const conversionRulesEl = document.getElementById('rag-collection-llm-conversion-rules');
    
    const subject = contextTopicEl ? contextTopicEl.value.trim() : '';
    const count = numExamplesEl ? numExamplesEl.value : '5';
    const databaseName = databaseNameEl ? databaseNameEl.value.trim() : '';
    const targetDatabase = 'Teradata'; // Default target database
    const conversionRules = conversionRulesEl ? conversionRulesEl.value.trim() : '';
    
    if (!subject) {
        ragCollectionLlmPromptPreview.value = 'Please enter a Context Topic first...';
        return;
    }
    
    if (!databaseName) {
        ragCollectionLlmPromptPreview.value = 'Please enter a Database Name first...';
        return;
    }
    
    try {
        // Fetch template plugin info to get prompt configuration
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/rag/templates/${selectedTemplateId}/plugin-info`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await response.json();
        const promptConfig = data.plugin_info?.prompt_templates?.question_generation;
        
        if (!promptConfig) {
            throw new Error('No prompt template found in manifest');
        }
        
        // Build conversion rules section if provided
        let conversionRulesSection = '';
        if (conversionRules) {
            const reqCount = promptConfig.requirements?.length || 0;
            conversionRulesSection = `\n${reqCount + 1}. CRITICAL: Follow these explicit ${targetDatabase} conversion rules:\n${conversionRules}\n`;
        }
        
        // Build requirements list
        let requirementsText = '';
        if (promptConfig.requirements) {
            promptConfig.requirements.forEach((req, idx) => {
                const reqText = req
                    .replace(/{count}/g, count)
                    .replace(/{subject}/g, subject)
                    .replace(/{target_database}/g, targetDatabase)
                    .replace(/{database_name}/g, databaseName);
                requirementsText += `${idx + 1}. ${reqText}\n`;
            });
        }
        
        // Add conversion rules if present
        if (conversionRulesSection) {
            requirementsText += conversionRulesSection;
        }
        
        // Add output format requirement
        if (promptConfig.output_format) {
            const outputFormatText = promptConfig.output_format.replace(/{database_name}/g, databaseName);
            requirementsText += `${promptConfig.requirements.length + (conversionRules ? 2 : 1)}. ${outputFormatText}`;
        }
        
        // Build approach section if present
        let approachSection = '';
        if (promptConfig.approach_instructions) {
            const approachText = promptConfig.approach_instructions
                .replace(/{target_database}/g, targetDatabase)
                .replace(/{database_name}/g, databaseName);
            approachSection = `\n${approachText}\n\n`;
        }
        
        // Build critical guidelines
        let guidelinesText = '';
        if (promptConfig.critical_guidelines) {
            guidelinesText = promptConfig.critical_guidelines.map(g => 
                `- ${g.replace(/{count}/g, count)}`
            ).join('\n');
        }
        
        // Determine context label based on template
        const contextLabel = selectedTemplateId.includes('doc_context') ? 
            'Technical Documentation' : 'Database Context';
        const contextPlaceholder = selectedTemplateId.includes('doc_context') ?
            '[Document content will be extracted from uploaded files]' :
            '[Database schema and table descriptions will be inserted here from Step 1]';
        
        // Build task description
        const taskDescription = promptConfig.task_description
            ?.replace(/{count}/g, count)
            ?.replace(/{subject}/g, subject) || '';
        
        // Construct final prompt preview
        const promptTemplate = `${promptConfig.system_role || ''}

${taskDescription}
${approachSection}
${contextLabel}:
${contextPlaceholder}

Requirements:
${requirementsText}

CRITICAL GUIDELINES:
${guidelinesText}`;
        
        ragCollectionLlmPromptPreview.value = promptTemplate;
        
    } catch (error) {
        console.error('Failed to load prompt from template:', error);
        ragCollectionLlmPromptPreview.value = `Error loading prompt template: ${error.message}`;
    }
}

/**
 * Open the Add RAG Collection modal
 */
async function openAddRagCollectionModal() {
    // Update modal title for Planner Repository
    const modalTitle = addRagCollectionModalContent.querySelector('h2');
    if (modalTitle) {
        modalTitle.textContent = 'Add Planner Repository';
    }
    
    // Populate MCP server dropdown
    populateMcpServerDropdown();
    
    // Check LLM configuration and enable/disable LLM option
    await checkLlmConfiguration();
    
    // Reset population method to none
    if (ragPopulationNone) {
        ragPopulationNone.checked = true;
    }
    
    // Reset and hide all population options
    addCollectionExampleCounter = 0;
    if (ragCollectionTemplateExamples) {
        ragCollectionTemplateExamples.innerHTML = '';
    }
    if (ragCollectionTemplateOptions) {
        ragCollectionTemplateOptions.classList.add('hidden');
    }
    if (ragCollectionManualFields) {
        ragCollectionManualFields.classList.add('hidden');
    }
    
    // Hide the entire LLM workflow container
    const llmWorkflowContainer = document.getElementById('rag-collection-llm-workflow');
    if (llmWorkflowContainer) {
        llmWorkflowContainer.classList.add('hidden');
    }
    
    // Reset and hide context result
    if (ragCollectionContextResult) {
        ragCollectionContextResult.classList.add('hidden');
    }
    if (ragCollectionContextContent) {
        ragCollectionContextContent.textContent = '';
    }
    lastGeneratedContext = null;
    
    // Reset and hide Step 2 section
    const step2Section = document.getElementById('rag-collection-step2-section');
    if (step2Section) {
        step2Section.classList.add('hidden');
    }
    
    // Reset and hide questions result
    if (ragCollectionQuestionsResult) {
        ragCollectionQuestionsResult.classList.add('hidden');
    }
    lastGeneratedQuestions = null;

    // Initially disable Create Collection button (will be enabled after successful generation)
    if (addRagCollectionSubmit) {
        addRagCollectionSubmit.disabled = true;
        addRagCollectionSubmit.title = 'Generate questions first to enable this button';
    }

    // Clear uploaded documents
    uploadedDocuments = [];
    const docList = document.getElementById('rag-collection-doc-list');
    if (docList) {
        docList.classList.add('hidden');
        docList.innerHTML = '';
    }
    
    // Reload template configuration to get latest default_mcp_context_prompt
    await reloadTemplateConfiguration();
    
    // Show modal with animation
    addRagCollectionModalOverlay.classList.remove('hidden');
    
    // Trigger animation after a frame
    requestAnimationFrame(() => {
        addRagCollectionModalOverlay.classList.remove('opacity-0');
        addRagCollectionModalContent.classList.remove('scale-95', 'opacity-0');
        addRagCollectionModalContent.classList.add('scale-100', 'opacity-100');
    });
}

/**
 * Close the Add RAG Collection modal
 */
function closeAddRagCollectionModal() {
    // Animate out
    addRagCollectionModalOverlay.classList.add('opacity-0');
    addRagCollectionModalContent.classList.remove('scale-100', 'opacity-100');
    addRagCollectionModalContent.classList.add('scale-95', 'opacity-0');
    
    // Hide after animation
    setTimeout(() => {
        addRagCollectionModalOverlay.classList.add('hidden');
        // Reset form
        addRagCollectionForm.reset();
    }, 200);
}

// Use imported populateMcpServerDropdown from RagUtils module
const populateMcpServerDropdown = () => {
    RagUtils.populateMcpServerDropdown(ragCollectionMcpServerSelect);
};

/**
 * Handle Add RAG Collection form submission
 */
async function handleAddRagCollection(event) {
    event.preventDefault();
    console.log('[Create Collection] Form submitted, handler called');
    
    // Get form values
    const name = ragCollectionNameInput.value.trim();
    const mcpServerId = ragCollectionMcpServerSelect.value;
    const description = ragCollectionDescriptionInput.value.trim();
    console.log('[Create Collection] Name:', name, 'MCP Server ID:', mcpServerId, 'Description:', description);
    
    
    // Determine population method
    let populationMethod = 'none';
    let templateMethod = 'manual';
    
    // Re-query the radio buttons in case they were recreated
    const llmMethodRadio = document.getElementById('rag-template-method-llm');
    const manualMethodRadio = document.getElementById('rag-template-method-manual');
    
    console.log('[Create Collection] llmMethodRadio element:', llmMethodRadio);
    console.log('[Create Collection] llmMethodRadio.checked:', llmMethodRadio?.checked);
    console.log('[Create Collection] manualMethodRadio.checked:', manualMethodRadio?.checked);
    
    if (ragPopulationWithTemplate && ragPopulationWithTemplate.checked) {
        populationMethod = 'template';
        // Determine if manual or auto-generate - check fresh element
        if (llmMethodRadio && llmMethodRadio.checked) {
            templateMethod = 'llm';
            console.log('[Create Collection] LLM method detected');
        } else {
            console.log('[Create Collection] Manual method (llmMethodRadio not checked)');
        }
    }
    
    
    // Validate
    if (!name) {
        showNotification('error', 'Collection name is required');
        return;
    }
    
    if (!mcpServerId) {
        showNotification('error', 'Please select an MCP server');
        return;
    }
    
    
    // Validate template examples if template population is selected
    let templateExamples = [];
    if (populationMethod === 'template') {
        console.log('[Create Collection] Population method: template');
        console.log('[Create Collection] Template method:', templateMethod);
        console.log('[Create Collection] lastGeneratedQuestions:', lastGeneratedQuestions);
        console.log('[Create Collection] lastGeneratedQuestions length:', lastGeneratedQuestions?.length);
        
        // If using LLM method with generated questions, use those
        if (templateMethod === 'llm' && lastGeneratedQuestions && lastGeneratedQuestions.length > 0) {
            console.log('[Create Collection] Using generated questions');
            templateExamples = lastGeneratedQuestions.map(q => ({
                user_query: q.question,
                sql_statement: q.sql
            }));
        } else {
            console.log('[Create Collection] Looking for manual examples');
            // Otherwise, get examples from manual entry form
            const exampleDivs = ragCollectionTemplateExamples.querySelectorAll('[data-add-example-id]');
            exampleDivs.forEach(div => {
                const exampleId = div.dataset.addExampleId;
                const queryInput = document.getElementById(`add-example-${exampleId}-query`);
                const sqlInput = document.getElementById(`add-example-${exampleId}-sql`);
                
                if (queryInput && sqlInput && queryInput.value.trim() && sqlInput.value.trim()) {
                    templateExamples.push({
                        user_query: queryInput.value.trim(),
                        sql_statement: sqlInput.value.trim()
                    });
                }
            });
        }
        
        
        if (templateExamples.length === 0) {
            showNotification('error', 'Please add at least one template example');
            return;
        }
    }
    
    // Validate LLM fields if LLM population is selected
    let llmSubject, llmCount, llmDbName;
    if (populationMethod === 'template' && templateMethod === 'llm') {
        // If questions are already generated, skip field validation
        if (!lastGeneratedQuestions || lastGeneratedQuestions.length === 0) {
            
            // Validate all number input fields first
            const llmFieldsContainer = document.getElementById('rag-collection-llm-fields');
            if (llmFieldsContainer) {
                const numberInputs = llmFieldsContainer.querySelectorAll('input[type="number"]');
                for (const input of numberInputs) {
                    if (!validateNumberInput(input)) {
                        showNotification('error', 'Please correct the validation errors in the form');
                        return;
                    }
                }
            }
            
            // Get values from dynamically created fields
            const contextTopicEl = document.getElementById('rag-collection-llm-context-topic');
            const numExamplesEl = document.getElementById('rag-collection-llm-num-examples');
            const databaseNameEl = document.getElementById('rag-collection-llm-database-name');
            
            llmSubject = contextTopicEl ? contextTopicEl.value.trim() : '';
            llmCount = numExamplesEl ? parseInt(numExamplesEl.value, 10) : 5;
            llmDbName = databaseNameEl ? databaseNameEl.value.trim() : '';
            
            if (!llmSubject) {
                showNotification('error', 'Please provide a context topic for question generation');
                return;
            }
            
            // Validate num_examples using its configured min/max
            if (numExamplesEl) {
                const min = parseInt(numExamplesEl.dataset.min) || 1;
                const max = parseInt(numExamplesEl.dataset.max) || 1000;
                if (!llmCount || llmCount < min || llmCount > max) {
                    showNotification('error', `Number of examples must be between ${min} and ${max}`);
                    return;
                }
            }
            
            if (!llmDbName) {
                showNotification('error', 'Database name is required');
                return;
            }
        } else {
            // Use values from generated questions
            const databaseNameEl = document.getElementById('rag-collection-llm-database-name');
            llmDbName = databaseNameEl ? databaseNameEl.value.trim() : '';
        }
    }
    
    // Disable submit button
    addRagCollectionSubmit.disabled = true;
    const buttonText = populationMethod === 'none' ? 'Creating...' : 'Creating & Populating...';
    addRagCollectionSubmit.textContent = buttonText;
    
    try {
        // Step 1: Create the collection
        const authToken = localStorage.getItem('tda_auth_token');
        const headers = {
            'Content-Type': 'application/json'
        };
        if (authToken) {
            headers['Authorization'] = `Bearer ${authToken}`;
        }
        
        const createResponse = await fetch('/api/v1/rag/collections', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({
                name: name,
                mcp_server_id: mcpServerId,
                description: description || ''
            })
        });
        
        const createData = await createResponse.json();
        
        if (!createResponse.ok) {
            showNotification('error', `Failed to create collection: ${createData.error || 'Unknown error'}`);
            return;
        }
        
        const collectionId = createData.collection_id;
        showNotification('success', `Collection "${name}" created (ID: ${collectionId})`);
        
        // Step 2: Populate based on selected method
        if (populationMethod === 'template' && templateExamples.length > 0) {
            addRagCollectionSubmit.textContent = 'Populating with template...';
            
            // Get selected template ID from dropdown
            const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
            const selectedTemplateId = ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
            
            const templatePayload = {
                template_type: 'sql_query',  // Keep for backward compatibility
                template_id: selectedTemplateId,
                examples: templateExamples
            };
            
            // For LLM method, use the database name from LLM fields
            if (templateMethod === 'llm' && llmDbName) {
                templatePayload.database_name = llmDbName;
            } else {
                // For manual method, use values from manual form fields
                const dbName = ragCollectionTemplateDb.value.trim();
                const toolName = ragCollectionTemplateTool.value.trim();
                
                if (dbName) templatePayload.database_name = dbName;
                if (toolName) templatePayload.mcp_tool_name = toolName;
            }
            
            
            const populateResponse = await fetch(`/api/v1/rag/collections/${collectionId}/populate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(templatePayload)
            });
            
            const populateData = await populateResponse.json();
            
            
            if (populateResponse.ok && populateData.status === 'success') {
                showNotification('success', `Populated ${populateData.results.successful} cases successfully!`);
            } else {
                showNotification('warning', `Collection created but population failed: ${populateData.message || 'Unknown error'}`);
            }
        }
        
        // Close modal and refresh
        closeAddRagCollectionModal();
        await loadRagCollections();
        
    } catch (error) {
        console.error('Error creating RAG collection:', error);
        showNotification('error', 'Failed to create collection. Check console for details.');
    } finally {
        // Re-enable submit button
        addRagCollectionSubmit.disabled = false;
        addRagCollectionSubmit.textContent = 'Create Collection';
    }
}

/**
 * Toggle a RAG collection's enabled state
 */
async function toggleRagCollection(collectionId, currentState) {
    try {
        // Toggle the state: if currently enabled, disable it; if disabled, enable it
        const newState = !currentState;
        
        const token = localStorage.getItem('tda_auth_token');
        const headers = {
            'Content-Type': 'application/json'
        };
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        const response = await fetch(`/api/v1/rag/collections/${collectionId}/toggle`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({
                enabled: newState
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            const newState = data.enabled ? 'enabled' : 'disabled';
            showNotification('success', `Collection ${newState} successfully`);
            
            // Refresh collections list
            await loadRagCollections();
            
            // Update CCR indicator status
            await updateCcrIndicator();
        } else {
            // Backend returns 'message' field for errors
            showNotification('error', data.message || 'Failed to toggle collection');
        }
    } catch (error) {
        console.error('Error toggling RAG collection:', error);
        showNotification('error', 'Failed to toggle collection. Check console for details.');
    }
}

/**
 * Delete a RAG collection
 */
async function deleteRagCollection(collectionId, collectionName) {
    // Use custom confirmation modal
    if (!window.showConfirmation) {
        console.error('Confirmation system not available');
        return;
    }

    // Helper function for HTML escaping
    const escapeHtml = (str) => {
        if (!str) return '';
        const el = document.createElement('span');
        el.textContent = str;
        return el.innerHTML;
    };

    // Function to perform the actual deletion
    const doDelete = async () => {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch(`/api/v1/rag/collections/${collectionId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            const data = await response.json();

            if (response.ok) {
                // Show success message with archive information
                const archivedCount = data.sessions_archived || 0;
                let message = `Collection "${collectionName}" deleted successfully`;

                if (archivedCount > 0) {
                    message += `\n\n${archivedCount} session(s) using this collection have been archived.`;
                    message += `\n\nArchived sessions can be viewed in the Sessions panel by enabling "Show Archived".`;
                }

                showNotification('success', message);

                // Refresh collections list
                await loadRagCollections();

                // Refresh sessions list if sessions were archived
                if (archivedCount > 0) {
                    try {
                        // Auto-disable toggle (user deleted artifact = cleanup intent)
                        const toggle = document.getElementById('sidebar-show-archived-sessions-toggle');
                        if (toggle && toggle.checked) {
                            toggle.checked = false;
                            localStorage.setItem('sidebarShowArchivedSessions', 'false');
                            console.log('[Collection Delete] Auto-disabled "Show Archived" toggle');
                        }

                        // Full refresh: fetch + re-render + apply filters
                        const { refreshSessionsList } = await import('./configManagement.js');
                        await refreshSessionsList();

                        console.log('[Collection Delete] Session list refreshed after archiving', archivedCount, 'sessions');
                    } catch (error) {
                        console.error('[Collection Delete] Failed to refresh sessions:', error);
                        // Non-fatal: collection deleted successfully, just UI refresh failed
                    }
                }
            } else {
                showNotification('error', `Failed to delete collection: ${data.message || data.error || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Error deleting RAG collection:', error);
            showNotification('error', 'Failed to delete collection. Check console for details.');
        }
    };

    // Check for relationships before showing confirmation
    try {
        const token = localStorage.getItem('tda_auth_token');
        const checkRes = await fetch(`/api/v1/artifacts/collection/${collectionId}/relationships`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const checkData = await checkRes.json();

        let message = `Are you sure you want to delete the collection <strong>${escapeHtml(collectionName)}</strong>?<br><br>This will remove all RAG cases associated with this collection.`;

        // Check for blockers (e.g., agent pack management)
        const deletionInfo = checkData.deletion_info || {};
        const blockers = deletionInfo.blockers || [];
        const warnings = deletionInfo.warnings || [];
        const sessions = checkData.relationships?.sessions || {};
        const activeCount = sessions.active_count || 0;

        // Show blockers (prevent deletion)
        if (blockers.length > 0) {
            const blockerMessages = blockers
                .map(b => `• ${escapeHtml(b.message || 'Unknown blocker')}`)
                .join('<br>');
            message += `<br><br><span style="color: #ef4444; font-weight: 600;">🚫 Cannot Delete:</span><br><span style="font-size: 0.9em;">${blockerMessages}</span>`;

            window.showConfirmation('Cannot Delete Collection', message, null);
            return;
        }

        // Show warnings (sessions will be archived, profiles affected, etc.)
        if (warnings.length > 0) {
            const warningMessages = warnings
                .map(w => `• ${escapeHtml(w)}`)
                .join('<br>');
            message += `<br><br><span style="color: #f59e0b; font-weight: 600;">⚠️ Warning:</span><br><span style="font-size: 0.9em;">${warningMessages}</span>`;
        }

        // Show sample session names if active sessions exist
        if (activeCount > 0 && sessions.items && sessions.items.length > 0) {
            const sessionNames = sessions.items
                .filter(s => !s.archived)  // Only show active sessions
                .map(s => `• ${escapeHtml(s.session_name)}`)
                .join('<br>');
            if (sessionNames) {
                message += `<br><br><span style="font-size: 0.9em;">Affected active sessions:<br>${sessionNames}</span>`;

                if (activeCount > sessions.items.filter(s => !s.archived).length) {
                    message += `<br><span style="font-size: 0.9em; color: #9ca3af;">...and ${activeCount - sessions.items.filter(s => !s.archived).length} more</span>`;
                }
            }
        }

        window.showConfirmation('Delete Knowledge Repository', message, doDelete);
    } catch (err) {
        // Fallback to basic confirmation if check fails
        console.error('Failed to check relationships:', err);
        window.showConfirmation(
            'Delete Knowledge Repository',
            `Are you sure you want to delete the collection <strong>${escapeHtml(collectionName)}</strong>?<br><br>This will remove all RAG cases associated with this collection.`,
            doDelete
        );
    }
}

/**
 * Open Edit RAG Collection modal
 */
function openEditCollectionModal(collection) {
    // Get edit modal elements
    const editModalOverlay = document.getElementById('edit-rag-collection-modal-overlay');
    const editModalContent = document.getElementById('edit-rag-collection-modal-content');
    const editCollectionIdInput = document.getElementById('edit-rag-collection-id');
    const editCollectionNameInput = document.getElementById('edit-rag-collection-name');
    const editCollectionMcpServerSelect = document.getElementById('edit-rag-collection-mcp-server');
    const editCollectionDescriptionInput = document.getElementById('edit-rag-collection-description');
    
    // Populate MCP server dropdown for edit modal
    editCollectionMcpServerSelect.innerHTML = '<option value="">Select an MCP Server...</option>';
    if (window.configState && window.configState.mcpServers && Array.isArray(window.configState.mcpServers)) {
        window.configState.mcpServers.forEach(server => {
            const option = document.createElement('option');
            option.value = server.id;
            option.textContent = server.name;
            // Check if this server is the one assigned to the collection
            if (server.id === collection.mcp_server_id) {
                option.selected = true;
            }
            editCollectionMcpServerSelect.appendChild(option);
        });
    }
    
    // Populate form with collection data
    editCollectionIdInput.value = collection.id;
    editCollectionNameInput.value = collection.name;
    editCollectionDescriptionInput.value = collection.description || '';
    
    // Show modal with animation
    editModalOverlay.classList.remove('hidden');
    requestAnimationFrame(() => {
        editModalOverlay.classList.remove('opacity-0');
        editModalContent.classList.remove('scale-95', 'opacity-0');
        editModalContent.classList.add('scale-100', 'opacity-100');
    });
}

/**
 * Close Edit RAG Collection modal
 */
function closeEditCollectionModal() {
    const editModalOverlay = document.getElementById('edit-rag-collection-modal-overlay');
    const editModalContent = document.getElementById('edit-rag-collection-modal-content');
    const editForm = document.getElementById('edit-rag-collection-form');
    
    // Animate out
    editModalOverlay.classList.add('opacity-0');
    editModalContent.classList.remove('scale-100', 'opacity-100');
    editModalContent.classList.add('scale-95', 'opacity-0');
    
    // Hide after animation
    setTimeout(() => {
        editModalOverlay.classList.add('hidden');
        editForm.reset();
    }, 200);
}

/**
 * Handle Edit RAG Collection form submission
 */
async function handleEditRagCollection(event) {
    event.preventDefault();
    
    const editCollectionIdInput = document.getElementById('edit-rag-collection-id');
    const editCollectionNameInput = document.getElementById('edit-rag-collection-name');
    const editCollectionMcpServerSelect = document.getElementById('edit-rag-collection-mcp-server');
    const editCollectionDescriptionInput = document.getElementById('edit-rag-collection-description');
    const editSubmitBtn = document.getElementById('edit-rag-collection-submit');
    
    // Get form values
    const collectionId = parseInt(editCollectionIdInput.value);
    const name = editCollectionNameInput.value.trim();
    const mcpServerId = editCollectionMcpServerSelect.value;  // This is now the server ID
    const description = editCollectionDescriptionInput.value.trim();
    
    // Validate
    if (!name) {
        showNotification('error', 'Collection name is required');
        return;
    }
    
    if (!mcpServerId) {
        showNotification('error', 'Please select an MCP server');
        return;
    }
    
    // Disable submit button
    editSubmitBtn.disabled = true;
    editSubmitBtn.textContent = 'Saving...';
    
    try {
        // Call API with mcp_server_id
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/rag/collections/${collectionId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                name: name,
                mcp_server_id: mcpServerId,  // Send ID instead of name
                description: description || ''
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showNotification('success', `Collection "${name}" updated successfully`);
            
            // Close modal
            closeEditCollectionModal();
            
            // Refresh RAG collections list
            await loadRagCollections();
        } else {
            showNotification('error', `Failed to update collection: ${data.error || data.message || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Error updating RAG collection:', error);
        showNotification('error', 'Failed to update collection. Check console for details.');
    } finally {
        // Re-enable submit button
        editSubmitBtn.disabled = false;
        editSubmitBtn.textContent = 'Save Changes';
    }
}

/**
 * Refresh a RAG collection's vector store
 */
async function refreshRagCollection(collectionId, collectionName) {
    try {
        showNotification('info', `Refreshing collection "${collectionName}"...`);
        
        const response = await fetch(`/api/v1/rag/collections/${collectionId}/refresh`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showNotification('success', `Collection "${collectionName}" refreshed successfully`);
        } else {
            showNotification('error', `Failed to refresh collection: ${data.error || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Error refreshing RAG collection:', error);
        showNotification('error', 'Failed to refresh collection. Check console for details.');
    }
}

// Event Listeners
// Note: addRagCollectionBtn removed - templates now have Edit/Deploy buttons instead

// Knowledge Repository handlers are initialized in knowledgeRepositoryHandler.js

// SQL Template Card Event Listeners
const sqlTemplateCard = document.getElementById('sqlTemplateCard');
if (sqlTemplateCard) {
    sqlTemplateCard.addEventListener('click', () => window.openSqlTemplatePopulator());
}

const sqlDocContextTemplateCard = document.getElementById('sqlDocContextTemplateCard');
if (sqlDocContextTemplateCard) {
    sqlDocContextTemplateCard.addEventListener('click', () => {
        // For now, open the same modal but we could create a document-specific one later
        window.openSqlTemplatePopulator();
    });
}

if (addRagCollectionModalClose) {
    addRagCollectionModalClose.addEventListener('click', closeAddRagCollectionModal);
}

if (addRagCollectionCancel) {
    addRagCollectionCancel.addEventListener('click', closeAddRagCollectionModal);
}

if (addRagCollectionModalOverlay) {
    addRagCollectionModalOverlay.addEventListener('click', (e) => {
        // Close if clicking on overlay background (not content)
        if (e.target === addRagCollectionModalOverlay) {
            closeAddRagCollectionModal();
        }
    });
}

if (addRagCollectionForm) {
    console.log('[Init] Attaching submit handler to add-rag-collection-form');
    addRagCollectionForm.addEventListener('submit', handleAddRagCollection);
} else {
    console.error('[Init] add-rag-collection-form element not found!');
}

// Edit Modal Event Listeners
const editRagCollectionModalClose = document.getElementById('edit-rag-collection-modal-close');
const editRagCollectionCancel = document.getElementById('edit-rag-collection-cancel');
const editRagCollectionModalOverlay = document.getElementById('edit-rag-collection-modal-overlay');
const editRagCollectionForm = document.getElementById('edit-rag-collection-form');

if (editRagCollectionModalClose) {
    editRagCollectionModalClose.addEventListener('click', closeEditCollectionModal);
}

if (editRagCollectionCancel) {
    editRagCollectionCancel.addEventListener('click', closeEditCollectionModal);
}

if (editRagCollectionModalOverlay) {
    editRagCollectionModalOverlay.addEventListener('click', (e) => {
        // Close if clicking on overlay background (not content)
        if (e.target === editRagCollectionModalOverlay) {
            closeEditCollectionModal();
        }
    });
}

if (editRagCollectionForm) {
    editRagCollectionForm.addEventListener('submit', handleEditRagCollection);
}

/**
 * Calculate and display RAG impact KPIs
 * 
 * KPI Methodology:
 * -----------------
 * 
 * 1. CHAMPION STRATEGIES (Self-Healing Events):
 *    - Counts cases marked as `is_most_efficient = true` in ChromaDB
 *    - These are the "best-in-class" strategies that RAG retrieves and injects
 *    - When RAG finds a champion case, it adds it as a few-shot example to the prompt
 *    - This enables "self-healing" by providing proven solutions upfront
 * 
 * 2. COST SAVINGS:
 *    - Calculated based on champion cases preventing trial-and-error execution
 *    - Formula: (champion_cases × avg_tokens_per_case × 0.5) / 1M × $15
 *    - Assumes 50% token reduction when using champion strategy vs exploration
 *    - Uses $15 per 1M output tokens (typical GPT-4 class pricing)
 * 
 * 3. SPEED IMPROVEMENT:
 *    - Estimated at 65% faster when champion strategy is available
 *    - Champion cases eliminate: exploration cycles, error correction, plan revisions
 *    - Typical execution: 1.4s with RAG vs 4.0s without RAG
 * 
 * RAG RETRIEVAL TRACKING:
 * - When planner calls `retrieve_examples()`, it emits a `rag_retrieval` event
 * - This event contains the champion case_id that was injected
 * - The turn is then enhanced with the champion strategy in the prompt
 * - If turn succeeds more efficiently, it may become new champion
 */
async function calculateRagImpactKPIs() {
    
    try {
        // Fetch all collections to calculate metrics
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch('/api/v1/rag/collections', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (!response.ok) {
            console.error('[RAG KPI] Failed to fetch collections:', response.status, response.statusText);
            updateKPIDisplay({
                selfHealingEvents: 'N/A',
                selfHealingTrend: 'Error loading collections',
                costSavings: 'N/A',
                tokensSaved: 'N/A',
                speedImprovement: 'N/A',
                speedWith: 'N/A',
                speedWithout: 'N/A'
            });
            return;
        }
        
        const responseData = await response.json();
        
        // Extract collections array from response
        const collections = responseData.collections || responseData;
        
        if (!Array.isArray(collections) || collections.length === 0) {
            updateKPIDisplay({
                selfHealingEvents: 0,
                selfHealingTrend: 'Create collections and add cases to see metrics',
                costSavings: '0.00',
                tokensSaved: '0',
                speedImprovement: '--',
                speedWith: '--',
                speedWithout: '--'
            });
            return;
        }
        
        // Count collections with cases
        const collectionsWithCases = collections.filter(c => c.count && c.count > 0);
        
        // Calculate total cases across all collections
        let totalCases = 0;
        let championCases = 0; // Cases marked as most efficient (used for RAG retrieval)
        let recentCases = 0;
        let totalOutputTokens = 0;
        let totalInputTokens = 0;
        let positivelyRatedCases = 0;
        let ragEnhancedTurns = 0; // Count of turns that had RAG assistance
        let totalTurns = 0; // Total turns across all sessions
        
        const oneWeekAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
        
        for (const collection of collections) {

                // Skip knowledge repositories - they have chunks, not case rows
                const repositoryType = collection.repository_type || 'planner';
                if (repositoryType === 'knowledge') {
                    console.log(`[RAG KPI] Skipping knowledge repository: ${collection.name} (ID: ${collection.id})`);
                    continue;
                }

            if (collection.count) {
                totalCases += collection.count;

                // Fetch all rows for accurate metrics (not limited) - only for planner repositories
                try {
                    const token = localStorage.getItem('tda_auth_token');
                    const detailResponse = await fetch(`/api/v1/rag/collections/${collection.id}/rows?limit=10000&light=true`, {
                        headers: {
                            'Authorization': `Bearer ${token}`
                        }
                    });
                    if (detailResponse.ok) {
                        const data = await detailResponse.json();
                        const rows = data.rows || [];
                        
                        rows.forEach((row, index) => {
                            // Row already has flattened metadata fields
                            
                            // Debug first row structure
                            if (index === 0) {
                            }
                            
                            // Count champion cases (these are the ones RAG retrieves for self-healing)
                            if (row.is_most_efficient === true) {
                                championCases++;
                            }
                            
                            // Count positively rated cases
                            if (row.user_feedback_score > 0) {
                                positivelyRatedCases++;
                            }
                            
                            // Count recent cases (this week)
                            const timestamp = new Date(row.timestamp);
                            if (!isNaN(timestamp.getTime()) && timestamp.getTime() > oneWeekAgo) {
                                recentCases++;
                            }
                            
                            // Sum output tokens for all cases
                            if (row.output_tokens) {
                                totalOutputTokens += parseInt(row.output_tokens) || 0;
                            }
                        });
                    } else {
                    }
                } catch (detailError) {
                }
            }
        }
        
        // If no cases found, show helpful message
        if (totalCases === 0) {
            updateKPIDisplay({
                selfHealingEvents: 0,
                selfHealingTrend: `${collections.length} collection(s) ready - Start using the agent to accumulate cases`,
                activationRate: '--',
                enhancedCount: 0,
                totalTasks: 0,
                costSavings: '0.00',
                tokensSaved: '0',
                speedImprovement: '--',
                speedWith: '--',
                speedWithout: '--'
            });
            return;
        }
        
        // Calculate KPIs based on champion cases (most efficient strategies available for RAG retrieval)
        const selfHealingEvents = championCases; // Number of champion strategies available for self-healing
        
        // Build trend message
        let trendMessage;
        if (recentCases > 0) {
            trendMessage = `${recentCases} cases this week`;
        } else if (positivelyRatedCases > 0) {
            trendMessage = `${positivelyRatedCases} highly-rated strategies`;
        } else {
            trendMessage = `${totalCases} strategies available`;
        }
        
        // Fetch REAL RAG usage metrics from session analytics
        let ragMetrics = {
            rag_guided_turns: 0,
            total_turns: 0,
            activation_rate: 0,
            avg_rag_tokens: 0,
            avg_non_rag_tokens: 0,
            efficiency_gain: 0,
            tokens_saved: 0,
            cost_saved: 0.0
        };
        
        let isAdmin = false;
        let globalMetrics = null;

        try {
            // Determine which endpoint to use based on current view
            const isSystemView = (typeof intelligenceCurrentView !== 'undefined') && intelligenceCurrentView === 'system';
            const endpoint = isSystemView
                ? '/api/v1/consumption/system-summary'
                : '/api/v1/consumption/summary';

            const analyticsResponse = await fetch(endpoint, {
                headers: { 'Authorization': `Bearer ${window.authClient.getToken()}` }
            });
            if (analyticsResponse.ok) {
                const consumptionData = await analyticsResponse.json();

                // Extract RAG metrics from consumption data
                ragMetrics = {
                    rag_guided_turns: consumptionData.rag_guided_turns || 0,
                    total_turns: consumptionData.total_turns || 0,
                    activation_rate: consumptionData.rag_activation_rate_percent || 0,
                    avg_rag_tokens: 0,
                    avg_non_rag_tokens: 0,
                    efficiency_gain: consumptionData.rag_activation_rate_percent || 0,
                    tokens_saved: consumptionData.rag_output_tokens_saved || 0,
                    cost_saved: consumptionData.rag_cost_saved_usd || 0.0
                };

                // Check if user is admin
                isAdmin = (typeof isIntelligenceAdmin !== 'undefined') ? isIntelligenceAdmin : false;

                // Store global metrics for reference
                globalMetrics = {
                    tokensSaved: ragMetrics.tokens_saved,
                    costSaved: ragMetrics.cost_saved,
                    totalImprovements: ragMetrics.rag_guided_turns,
                    totalSessions: consumptionData.total_sessions || 0,
                    totalUsers: consumptionData.total_users || 0  // Only available in system view
                };
            }
        } catch (error) {
            console.warn('Failed to fetch RAG metrics:', error);
        }
        
        const activationRateDisplay = ragMetrics.activation_rate > 0 ? `${ragMetrics.activation_rate}` : '--';
        
        // Speed improvement calculation based on efficiency gain
        // If RAG shows 29% efficiency gain in tokens, estimate similar speed improvement
        const avgSpeedImprovement = ragMetrics.efficiency_gain > 0 ? `${Math.round(ragMetrics.efficiency_gain)}` : '--';
        
        // Estimate time savings: if 29% fewer tokens, ~29% faster execution
        let avgTimeWithRag = '--';
        let avgTimeWithoutRag = '--';
        if (ragMetrics.efficiency_gain > 0) {
            const baselineTime = 4.0; // Assume 4 seconds baseline
            const ragTime = baselineTime * (1 - ragMetrics.efficiency_gain / 100);
            avgTimeWithRag = ragTime.toFixed(1);
            avgTimeWithoutRag = baselineTime.toFixed(1);
        }
        
        const kpiData = {
            selfHealingEvents,
            selfHealingTrend: trendMessage,
            activationRate: activationRateDisplay,
            enhancedCount: ragMetrics.rag_guided_turns,
            totalTasks: ragMetrics.total_turns,
            costSavings: ragMetrics.cost_saved >= 0.01 ? ragMetrics.cost_saved.toFixed(2) : ragMetrics.cost_saved.toFixed(4),
            tokensSaved: ragMetrics.tokens_saved.toLocaleString(),
            speedImprovement: avgSpeedImprovement,
            speedWith: avgTimeWithRag,
            speedWithout: avgTimeWithoutRag,
            totalCases,
            championCases,
            positivelyRatedCases,
            efficiencyGain: ragMetrics.efficiency_gain,
            isAdmin,
            globalMetrics
        };
        
        
        // Update UI
        updateKPIDisplay(kpiData);
        
    } catch (error) {
        console.error('Error calculating RAG KPIs:', error);
        // Display error state in KPIs
        updateKPIDisplay({
            selfHealingEvents: 'N/A',
            selfHealingTrend: 'Error loading data',
            costSavings: 'N/A',
            tokensSaved: 'N/A',
            speedImprovement: 'N/A',
            speedWith: 'N/A',
            speedWithout: 'N/A'
        });
    }
}

/**
 * Update KPI display elements
 */
function updateKPIDisplay(kpis) {
    // Update scope indicator based on current tab view
    const scopeIndicator = document.getElementById('rag-kpi-scope-indicator');
    if (scopeIndicator) {
        const isSystemView = (typeof intelligenceCurrentView !== 'undefined') && intelligenceCurrentView === 'system';
        if (isSystemView) {
            const userCount = kpis.globalMetrics?.totalUsers || '';
            scopeIndicator.textContent = userCount
                ? `System-Wide Performance (${userCount} Users)`
                : 'System-Wide Performance (All Users)';
        } else {
            scopeIndicator.textContent = 'Your Learning Performance';
        }
    }

    // Show System Performance tab for admins
    if (kpis.isAdmin) {
        const systemTab = document.getElementById('intel-tab-system-performance');
        if (systemTab) {
            systemTab.classList.remove('hidden');
        }
    }

    // Champion Strategies
    const healingCountEl = document.getElementById('rag-kpi-healing-count');
    const healingTrendEl = document.getElementById('rag-kpi-healing-trend');
    
    if (healingCountEl) {
        healingCountEl.textContent = kpis.selfHealingEvents;
    }
    if (healingTrendEl) {
        healingTrendEl.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            <span>${kpis.selfHealingTrend}</span>
        `;
    }
    
    // RAG Activation Rate
    const activationRateEl = document.getElementById('rag-kpi-activation-rate');
    const enhancedCountEl = document.getElementById('rag-kpi-enhanced-count');
    const totalTasksEl = document.getElementById('rag-kpi-total-tasks');
    if (activationRateEl) {
        activationRateEl.textContent = `${kpis.activationRate}%`;
    }
    if (enhancedCountEl) {
        enhancedCountEl.textContent = kpis.enhancedCount || '--';
    }
    if (totalTasksEl) {
        totalTasksEl.textContent = kpis.totalTasks || '--';
    }
    
    // Cost Savings
    const costSavingsEl = document.getElementById('rag-kpi-cost-savings');
    const tokensSavedEl = document.getElementById('rag-kpi-tokens-saved');
    if (costSavingsEl) {
        costSavingsEl.textContent = `$${kpis.costSavings}`;
    }
    if (tokensSavedEl) {
        tokensSavedEl.textContent = `${kpis.tokensSaved} tokens saved`;
    }
    
    // Speed Improvement
    const speedImprovementEl = document.getElementById('rag-kpi-speed-improvement');
    const speedWithEl = document.getElementById('rag-kpi-speed-with');
    const speedWithoutEl = document.getElementById('rag-kpi-speed-without');
    if (speedImprovementEl) {
        speedImprovementEl.textContent = `${kpis.speedImprovement}%`;
    }
    if (speedWithEl) {
        speedWithEl.textContent = `${kpis.speedWith}s`;
    }
    if (speedWithoutEl) {
        speedWithoutEl.textContent = `${kpis.speedWithout}s`;
    }
}

// =============================================================================
// SQL TEMPLATE POPULATOR
// =============================================================================

// Modal Elements
const sqlTemplateModalOverlay = document.getElementById('sql-template-populator-modal-overlay');
const sqlTemplateModalContent = document.getElementById('sql-template-populator-modal-content');
const sqlTemplateModalClose = document.getElementById('sql-template-populator-modal-close');
const sqlTemplateForm = document.getElementById('sql-template-populator-form');
const sqlTemplateCancel = document.getElementById('sql-template-populator-cancel');
const sqlTemplateSubmit = document.getElementById('sql-template-populator-submit');
const sqlTemplateCollectionSelect = document.getElementById('sql-template-collection-select');
const sqlTemplateExamplesContainer = document.getElementById('sql-template-examples-container');
const sqlTemplateAddExampleBtn = document.getElementById('sql-template-add-example');
const sqlTemplateResults = document.getElementById('sql-template-results');
const sqlTemplateResultsContent = document.getElementById('sql-template-results-content');

let exampleCounter = 0;

/**
 * Open SQL Template Populator Modal
 */
window.openSqlTemplatePopulator = async function() {
    await openSqlTemplatePopulatorWithDefaults(null, {});
};

/**
 * Open SQL Template Populator Modal with template defaults pre-filled
 * @param {object} template - Template metadata (optional)
 * @param {object} defaults - Saved default parameters
 */
window.openSqlTemplatePopulatorWithDefaults = async function(template, defaults = {}) {
    // Reset form
    sqlTemplateForm.reset();
    exampleCounter = 0;
    sqlTemplateExamplesContainer.innerHTML = '';
    sqlTemplateResults.classList.add('hidden');
    
    // Add initial example
    addSqlExample();
    
    // Load template config to set placeholder
    const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
    const selectedTemplateId = template?.template_id || ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
    const templateConfig = await window.templateManager.getTemplateConfig(selectedTemplateId);
    
    // Pre-fill form fields with defaults
    const mcpToolInput = document.getElementById('sql-template-mcp-tool');
    if (mcpToolInput) {
        if (defaults.mcp_tool_name) {
            mcpToolInput.value = defaults.mcp_tool_name;
        } else if (templateConfig?.default_mcp_tool) {
            mcpToolInput.placeholder = templateConfig.default_mcp_tool;
        }
    }
    
    const targetDbInput = document.getElementById('sql-template-target-database');
    if (targetDbInput && defaults.target_database) {
        targetDbInput.value = defaults.target_database;
    }
    
    const mcpContextInput = document.getElementById('sql-template-mcp-context-prompt');
    if (mcpContextInput && defaults.mcp_context_prompt) {
        mcpContextInput.value = defaults.mcp_context_prompt;
    }
    
    const contextTopicInput = document.getElementById('sql-template-context-topic');
    if (contextTopicInput && defaults.context_topic) {
        contextTopicInput.value = defaults.context_topic;
    }
    
    // Add template indicator if template provided
    const modalTitle = document.querySelector('#sql-template-modal-content h3');
    if (modalTitle && template) {
        const originalText = modalTitle.textContent;
        modalTitle.innerHTML = `
            <div class="flex items-center gap-2">
                <span>${originalText}</span>
                <span class="text-xs px-2 py-1 bg-blue-500/20 text-blue-400 rounded">
                    From Template: ${template.display_name || template.template_id}
                </span>
            </div>
        `;
    }
    
    // Show modal with animation
    sqlTemplateModalOverlay.classList.remove('hidden');
    requestAnimationFrame(() => {
        sqlTemplateModalOverlay.classList.remove('opacity-0');
        sqlTemplateModalContent.classList.remove('scale-95', 'opacity-0');
    });
    
    // Populate collection dropdown (async)
    await populateCollectionDropdown();
};

/**
 * Close SQL Template Populator Modal
 */
function closeSqlTemplateModal() {
    sqlTemplateModalOverlay.classList.add('opacity-0');
    sqlTemplateModalContent.classList.add('scale-95', 'opacity-0');
    
    setTimeout(() => {
        sqlTemplateModalOverlay.classList.add('hidden');
    }, 300);
}

/**
 * Populate collection dropdown with available collections
 */
async function populateCollectionDropdown() {
    if (!sqlTemplateCollectionSelect) return;
    
    // Clear existing options (except first)
    sqlTemplateCollectionSelect.innerHTML = '<option value="">Loading collections...</option>';
    
    try {
        // Fetch collections from API
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch('/api/v1/rag/collections', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await response.json();
        const collections = (data && data.collections) ? data.collections : [];
        
        // Clear and add placeholder
        sqlTemplateCollectionSelect.innerHTML = '<option value="">Select a collection...</option>';
        
        if (collections.length === 0) {
            sqlTemplateCollectionSelect.innerHTML = '<option value="">No collections available</option>';
            return;
        }
        
        // Add collection options
        collections.forEach(collection => {
            const option = document.createElement('option');
            option.value = collection.id;
            option.textContent = `${collection.name} (ID: ${collection.id})`;
            sqlTemplateCollectionSelect.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading collections:', error);
        sqlTemplateCollectionSelect.innerHTML = '<option value="">Error loading collections</option>';
    }
}

/**
 * Add a new SQL example row
 */
function addSqlExample() {
    exampleCounter++;
    
    const exampleDiv = document.createElement('div');
    exampleDiv.className = 'bg-gray-700/50 rounded-lg p-4 space-y-3';
    exampleDiv.dataset.exampleId = exampleCounter;
    
    exampleDiv.innerHTML = `
        <div class="flex items-center justify-between mb-2">
            <span class="text-sm font-medium text-gray-300">Example #${exampleCounter}</span>
            <button type="button" class="text-red-400 hover:text-red-300 text-sm" onclick="removeSqlExample(${exampleCounter})">
                Remove
            </button>
        </div>
        <div>
            <label class="block text-xs text-gray-400 mb-1">User Question</label>
            <input type="text" 
                   name="example_${exampleCounter}_query" 
                   required
                   class="w-full p-2 bg-gray-600 border border-gray-500 rounded-md focus:ring-2 focus:ring-teradata-orange focus:border-teradata-orange outline-none text-white text-sm"
                   placeholder="e.g., Show me all users older than 25">
        </div>
        <div>
            <label class="block text-xs text-gray-400 mb-1">SQL Statement</label>
            <textarea name="example_${exampleCounter}_sql" 
                      required
                      rows="3"
                      class="w-full p-2 bg-gray-600 border border-gray-500 rounded-md focus:ring-2 focus:ring-teradata-orange focus:border-teradata-orange outline-none text-white text-sm font-mono resize-none"
                      placeholder="SELECT * FROM users WHERE age > 25"></textarea>
        </div>
    `;
    
    sqlTemplateExamplesContainer.appendChild(exampleDiv);
}

/**
 * Remove an SQL example row
 */
window.removeSqlExample = function(exampleId) {
    const exampleDiv = sqlTemplateExamplesContainer.querySelector(`[data-example-id="${exampleId}"]`);
    if (exampleDiv) {
        exampleDiv.remove();
    }
    
    // Ensure at least one example remains
    if (sqlTemplateExamplesContainer.children.length === 0) {
        addSqlExample();
    }
};

/**
 * Handle SQL template form submission
 */
async function handleSqlTemplateSubmit(e) {
    e.preventDefault();
    
    const formData = new FormData(sqlTemplateForm);
    const collectionId = formData.get('collection_id');
    const databaseName = formData.get('database_name');
    
    // Get MCP tool name from form or load default from template config
    let mcpToolName = formData.get('mcp_tool_name');
    if (!mcpToolName) {
        const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
        const selectedTemplateId = ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
        if (selectedTemplateId) {
            const templateConfig = await window.templateManager.getTemplateConfig(selectedTemplateId);
            mcpToolName = templateConfig?.default_mcp_tool || '';
        }
    }
    
    // Collect examples
    const examples = [];
    const exampleDivs = sqlTemplateExamplesContainer.querySelectorAll('[data-example-id]');
    
    exampleDivs.forEach((div) => {
        const exampleId = div.dataset.exampleId;
        const query = formData.get(`example_${exampleId}_query`);
        const sql = formData.get(`example_${exampleId}_sql`);
        
        if (query && sql) {
            examples.push({
                user_query: query.trim(),
                sql_statement: sql.trim()
            });
        }
    });
    
    if (examples.length === 0) {
        showNotification('error', 'Please add at least one example');
        return;
    }
    
    // Get selected template ID
    const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
    const selectedTemplateId = ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
    
    // Build request payload
    const payload = {
        template_type: 'sql_query',  // Keep for backward compatibility
        template_id: selectedTemplateId,
        examples: examples
    };
    
    if (databaseName) {
        payload.database_name = databaseName;
    }
    
    if (mcpToolName) {
        payload.mcp_tool_name = mcpToolName;
    }
    
    // Disable submit button
    sqlTemplateSubmit.disabled = true;
    sqlTemplateSubmit.textContent = 'Populating...';
    
    try {
        const response = await fetch(`/api/v1/rag/collections/${collectionId}/populate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        
        const result = await response.json();
        
        if (response.ok && result.status === 'success') {
            // Show results
            sqlTemplateResults.classList.remove('hidden');
            sqlTemplateResultsContent.innerHTML = `
                <div class="flex items-center gap-2 text-green-400">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                    <span class="font-medium">Successfully populated ${result.results.successful} cases!</span>
                </div>
                <div class="mt-2 text-xs space-y-1">
                    <div>Collection: ${result.results.collection_name}</div>
                    <div>Total Examples: ${result.results.total_examples}</div>
                    <div>Successful: ${result.results.successful}</div>
                    <div>Failed: ${result.results.failed}</div>
                </div>
            `;
            
            if (result.results.failed > 0 && result.results.errors) {
                const errorsList = result.results.errors.map(err => 
                    `<li>Example ${err.example_index}: ${err.error}</li>`
                ).join('');
                sqlTemplateResultsContent.innerHTML += `
                    <div class="mt-3 text-red-400">
                        <div class="font-medium mb-1">Errors:</div>
                        <ul class="list-disc list-inside text-xs">${errorsList}</ul>
                    </div>
                `;
            }
            
            showNotification('success', `Successfully populated ${result.results.successful} cases`);
            
            // Reload collections after a delay
            setTimeout(() => {
                loadRagCollections();
                closeSqlTemplateModal();
            }, 3000);
            
        } else {
            // Show error
            const errorMessage = result.message || 'Failed to populate collection';
            sqlTemplateResults.classList.remove('hidden');
            sqlTemplateResultsContent.innerHTML = `
                <div class="flex items-center gap-2 text-red-400">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                    <span class="font-medium">Error: ${errorMessage}</span>
                </div>
            `;
            
            if (result.validation_issues) {
                const issuesList = result.validation_issues.map(issue => 
                    `<li>Example ${issue.example_index} (${issue.field}): ${issue.issue}</li>`
                ).join('');
                sqlTemplateResultsContent.innerHTML += `
                    <div class="mt-2 text-xs">
                        <div class="font-medium mb-1">Validation Issues:</div>
                        <ul class="list-disc list-inside">${issuesList}</ul>
                    </div>
                `;
            }
            
            showNotification('error', errorMessage);
        }
        
    } catch (error) {
        console.error('Error populating collection:', error);
        sqlTemplateResults.classList.remove('hidden');
        sqlTemplateResultsContent.innerHTML = `
            <div class="flex items-center gap-2 text-red-400">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                <span class="font-medium">Error: ${error.message}</span>
            </div>
        `;
        showNotification('error', 'Failed to populate collection');
    } finally {
        sqlTemplateSubmit.disabled = false;
        sqlTemplateSubmit.textContent = 'Populate Collection';
    }
}

// =============================================================================
// ADD COLLECTION TEMPLATE HELPERS
// =============================================================================

/**
 * Add example to Add Collection modal
 */
function addCollectionTemplateExample() {
    addCollectionExampleCounter++;
    
    const exampleDiv = document.createElement('div');
    exampleDiv.className = 'bg-gray-600/50 rounded p-3 space-y-2';
    exampleDiv.dataset.addExampleId = addCollectionExampleCounter;
    
    exampleDiv.innerHTML = `
        <div class="flex items-center justify-between mb-1">
            <span class="text-xs font-medium text-gray-300">Example #${addCollectionExampleCounter}</span>
            <button type="button" class="text-red-400 hover:text-red-300 text-xs" onclick="removeCollectionTemplateExample(${addCollectionExampleCounter})">
                Remove
            </button>
        </div>
        <input type="text" 
               id="add-example-${addCollectionExampleCounter}-query"
               class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-teradata-orange outline-none text-white text-xs"
               placeholder="User question">
        <textarea id="add-example-${addCollectionExampleCounter}-sql"
                  rows="2"
                  class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-teradata-orange outline-none text-white text-xs font-mono resize-none"
                  placeholder="SQL statement"></textarea>
    `;
    
    ragCollectionTemplateExamples.appendChild(exampleDiv);
}

/**
 * Remove example from Add Collection modal
 */
window.removeCollectionTemplateExample = function(exampleId) {
    const exampleDiv = ragCollectionTemplateExamples.querySelector(`[data-add-example-id="${exampleId}"]`);
    if (exampleDiv) {
        exampleDiv.remove();
    }
    
    // Ensure at least one example if template is checked
    if (ragCollectionUseTemplateCheckbox && ragCollectionUseTemplateCheckbox.checked && 
        ragCollectionTemplateExamples.children.length === 0) {
        addCollectionTemplateExample();
    }
};

/**
 * Toggle template options visibility
 */
/**
 * Check if LLM is configured and enable/disable the LLM population option
 */
async function checkLlmConfiguration() {
    // Check if there are any active profiles available (not just default profile)
    let isLlmConfigured = false;
    
    try {
        // Check if user has any profiles configured
        const token = localStorage.getItem('tda_auth_token');
        const profilesResponse = await fetch('/api/v1/profiles', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (profilesResponse.ok) {
            const profilesData = await profilesResponse.json();
            // LLM is configured if user has at least one profile
            isLlmConfigured = profilesData.profiles && profilesData.profiles.length > 0;
        }
    } catch (error) {
        console.error('Failed to check LLM configuration:', error);
        isLlmConfigured = false;
    }
    
    if (ragTemplateMethodLlm && ragTemplateMethodLlmLabel && ragTemplateMethodLlmBadge) {
        if (isLlmConfigured) {
            ragTemplateMethodLlm.disabled = false;
            ragTemplateMethodLlmLabel.classList.remove('opacity-50', 'cursor-not-allowed');
            ragTemplateMethodLlmLabel.classList.add('cursor-pointer');
            ragTemplateMethodLlmBadge.classList.add('hidden');
        } else {
            ragTemplateMethodLlm.disabled = true;
            ragTemplateMethodLlmLabel.classList.add('opacity-50', 'cursor-not-allowed');
            ragTemplateMethodLlmLabel.classList.remove('cursor-pointer');
            ragTemplateMethodLlmBadge.classList.remove('hidden');
            ragTemplateMethodLlmBadge.textContent = 'LLM Not Configured';
        }
    }
}

/**
 * Handle Generate Context button click
 */
async function handleGenerateContext() {
    // Check if conversation mode is fully initialized
    console.log('[Generate Context] Checking conversation initialization...');
    
    // Helper: derive initialization if global state is missing
    const deriveInitState = () => {
        const conversationView = document.getElementById('conversation-view');
        const isConversationVisible = conversationView && !conversationView.classList.contains('hidden');
        const hasSessionLoaded = window.state && window.state.sessionLoaded === true;
        const mcpDot = document.getElementById('mcp-status-dot');
        const llmDot = document.getElementById('llm-status-dot');
        const ctxDot = document.getElementById('context-status-dot');
        const sseDot = document.getElementById('sse-status-dot');
        const indicatorsGreen = [mcpDot, llmDot, ctxDot, sseDot].every(dot => dot ? dot.classList.contains('connected') || dot.classList.contains('idle') : true);
        return { initialized: Boolean(isConversationVisible && hasSessionLoaded && indicatorsGreen) };
    };
    
    // Use global init state if present, otherwise derive
    const initState = window.__conversationInitState || deriveInitState();
    console.log('[Generate Context] Initialization state:', initState);
    
    // Only proceed if explicitly initialized
    if (!initState || !initState.initialized) {
        console.log('[Generate Context] Conversation not initialized');
        if (window.showAppBanner) {
            window.showAppBanner(
                'Please initialize the system first. Go to Setup and click "Save & Connect", or go to Conversations and click "Start Conversation".',
                'info'
            );
        }
        return;
    }
    
    console.log('[Generate Context] System fully initialized, proceeding...');
    
    try {
        // Get the database name from dynamically generated field
        const databaseNameEl = document.getElementById('rag-collection-llm-database-name');
        const databaseName = databaseNameEl ? databaseNameEl.value.trim() : '';
        
        // Get the MCP context prompt name from user input (falls back to template default)
        const mcpPromptEl = document.getElementById('rag-collection-llm-mcp-prompt');
        let contextPromptName = mcpPromptEl ? mcpPromptEl.value.trim() : '';
        
        // If user didn't specify, fall back to template configuration
        if (!contextPromptName) {
            try {
                // Get selected template ID
                const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
                const selectedTemplateId = ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
                
                // Add cache-busting parameter to ensure fresh data
                const token = localStorage.getItem('tda_auth_token');
                const configResponse = await fetch(`/api/v1/rag/templates/${selectedTemplateId}/config?_=${Date.now()}`, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });
                
                if (configResponse.ok) {
                    const responseData = await configResponse.json();
                    
                    // Handle both response formats: {config: {...}} or direct {...}
                    const configData = responseData.config || responseData;
                    
                    if (configData.default_mcp_context_prompt) {
                        contextPromptName = configData.default_mcp_context_prompt;
                    }
                }
            } catch (error) {
                console.error('[MCP Prompt] Error loading template config:', error);
            }
        }
        
        // Final fallback if still no prompt name
        if (!contextPromptName) {
            contextPromptName = 'base_databaseBusinessDesc';
        }
        
        
        // Disable button and show loading state
        ragCollectionGenerateContextBtn.disabled = true;
        const originalButtonContent = ragCollectionGenerateContextBtn.innerHTML;
        ragCollectionGenerateContextBtn.innerHTML = `
            <svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
            </svg>
            <span>Generating...</span>
        `;
        
        showNotification('info', `Executing ${contextPromptName} prompt...`);
        
        // Build request body with arguments
        const requestBody = {
            arguments: {}
        };
        
        if (databaseName) {
            requestBody.arguments.database_name = databaseName;
        }
        
        // Get selected MCP server from the modal and include it in request
        const mcpServerSelect = document.getElementById('rag-collection-mcp-server');
        if (mcpServerSelect && mcpServerSelect.value) {
            requestBody.mcp_server_id = mcpServerSelect.value;
            console.log('[Generate Context] Using MCP server ID:', mcpServerSelect.value);
        }
        
        // Call the execute-raw endpoint
        const authToken = localStorage.getItem('tda_auth_token');
        const headers = {
            'Content-Type': 'application/json'
        };
        if (authToken) {
            headers['Authorization'] = `Bearer ${authToken}`;
        }
        
        const response = await fetch(`/api/v1/prompts/${contextPromptName}/execute-raw`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(requestBody)
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || 'Failed to execute context prompt');
        }
        
        const result = await response.json();
        
        // Extract final answer from execution trace if needed
        let finalAnswer = result.final_answer_text || '';
        
        // If final_answer_text is missing or looks like JSON, extract from execution_trace
        if (!finalAnswer || finalAnswer.startsWith('[') || finalAnswer.startsWith('{')) {
            if (result.execution_trace && Array.isArray(result.execution_trace)) {
                // Find the last TDA_FinalReport or TDA_SystemLog with direct_answer
                for (let i = result.execution_trace.length - 1; i >= 0; i--) {
                    const trace = result.execution_trace[i];
                    if (trace.action?.tool_name === 'TDA_FinalReport' && trace.result?.results?.[0]?.direct_answer) {
                        finalAnswer = trace.result.results[0].direct_answer;
                        break;
                    }
                    if (trace.action?.tool_name === 'TDA_SystemLog' && trace.action?.arguments?.details) {
                        const details = trace.action.arguments.details;
                        if (typeof details === 'string' && details.includes('database') && details.length > 50) {
                            finalAnswer = details;
                            break;
                        }
                    }
                }
            }
        }
        
        // Update result with clean final answer
        result.final_answer_text = finalAnswer;
        
        // Store the result for later use
        lastGeneratedContext = result;
        
        // Log the generated context for debugging
        
        // Show summary in inline result
        if (ragCollectionContextResult && ragCollectionContextContent) {
            const summary = finalAnswer || 'Context generated successfully';
            const truncated = summary.length > 200 ? summary.substring(0, 200) + '...' : summary;
            ragCollectionContextContent.textContent = truncated;
            ragCollectionContextResult.classList.remove('hidden');
            
        }
        
        // Show Step 2 section
        const step2Section = document.getElementById('rag-collection-step2-section');
        if (step2Section) {
            step2Section.classList.remove('hidden');
        }
        
        // Show full result in modal
        openContextResultModal(result);
        
        showNotification('success', 'Database context generated successfully');
        
    } catch (error) {
        console.error('Error generating context:', error);
        showNotification('error', `Failed to generate context: ${error.message}`);
    } finally {
        // Re-enable button
        ragCollectionGenerateContextBtn.disabled = false;
        ragCollectionGenerateContextBtn.innerHTML = `
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path>
            </svg>
            <span>Generate Context</span>
        `;
    }
}

/**
 * Extract formatted context from execution trace (same logic as backend)
 */
function extractQuestionGenerationContext(executionTrace) {
    if (!executionTrace || !Array.isArray(executionTrace)) {
        return '';
    }
    
    let context = '';
    
    for (const traceItem of executionTrace) {
        if (!traceItem || typeof traceItem !== 'object') continue;
        
        const action = traceItem.action || {};
        const result = traceItem.result || {};
        const toolName = action.tool_name || '';
        
        // Skip system log messages (clutter)
        if (toolName === 'TDA_SystemLog') continue;
        
        const resultsArray = result.results || [];
        if (!Array.isArray(resultsArray)) continue;
        
        for (const item of resultsArray) {
            if (!item || typeof item !== 'object') continue;
            
            // Handle TDA_FinalReport
            if (toolName === 'TDA_FinalReport') {
                if (item.direct_answer) {
                    context += `\n\n${item.direct_answer}`;
                }
                if (item.key_observations && Array.isArray(item.key_observations)) {
                    for (const obs of item.key_observations) {
                        if (obs && obs.text) {
                            context += `\n- ${obs.text}`;
                        }
                    }
                }
                continue;
            }
            
            // Handle TDA_LLMTask
            if (toolName === 'TDA_LLMTask' && item.response) {
                context += `\n\n${item.response}`;
                continue;
            }
            
            // Handle other tools - look for common fields
            const content = item.tool_output || item.content || item['Request Text'] || '';
            if (content && typeof content === 'string' && content.trim().length > 20) {
                // Clean up formatting
                const cleaned = content.replace(/\r/g, ' ').replace(/\n/g, ' ').replace(/\s+/g, ' ');
                context += `\n\n${cleaned}`;
            }
        }
    }
    
    return context.trim();
}

/**
 * Open the Context Result Modal
 */
function openContextResultModal(result) {
    if (!contextResultModalOverlay || !contextResultModalContent) {
        console.error('Context result modal elements not found');
        return;
    }
    
    // Populate modal with result data
    if (contextResultPromptText) {
        contextResultPromptText.textContent = result.prompt_text || 'N/A';
    }
    
    if (contextResultFinalAnswer) {
        contextResultFinalAnswer.textContent = result.final_answer_text || 'N/A';
    }
    
    // Show formatted context for question generation instead of raw trace
    const contextForQuestions = document.getElementById('context-result-question-context');
    if (contextForQuestions) {
        const fullContext = result.final_answer_text || '';
        const extractedDetails = extractQuestionGenerationContext(result.execution_trace);
        
        let displayContext = fullContext;
        if (extractedDetails) {
            displayContext += '\n\n=== Detailed Schema Information ===\n' + extractedDetails;
        }
        
        contextForQuestions.textContent = displayContext || 'No context extracted';
    }
    
    if (contextResultInputTokens) {
        contextResultInputTokens.textContent = result.token_usage?.input || 0;
    }
    
    if (contextResultOutputTokens) {
        contextResultOutputTokens.textContent = result.token_usage?.output || 0;
    }
    
    if (contextResultTotalTokens) {
        contextResultTotalTokens.textContent = result.token_usage?.total || 0;
    }
    
    // Show modal with animation
    contextResultModalOverlay.classList.remove('hidden');
    
    requestAnimationFrame(() => {
        contextResultModalOverlay.classList.remove('opacity-0');
        contextResultModalContent.classList.remove('scale-95', 'opacity-0');
        contextResultModalContent.classList.add('scale-100', 'opacity-100');
    });
}

/**
 * Close the Context Result Modal
 */
function closeContextResultModal() {
    if (!contextResultModalOverlay || !contextResultModalContent) {
        return;
    }
    
    // Animate out
    contextResultModalOverlay.classList.add('opacity-0');
    contextResultModalContent.classList.remove('scale-100', 'opacity-100');
    contextResultModalContent.classList.add('scale-95', 'opacity-0');
    
    // Hide after animation
    setTimeout(() => {
        contextResultModalOverlay.classList.add('hidden');
        
        // Scroll to show the Generate Questions button in the form
        const generateQuestionsBtn = document.getElementById('rag-collection-generate-questions-btn');
        if (generateQuestionsBtn) {
            setTimeout(() => {
                generateQuestionsBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 100);
        }
    }, 200);
}

/**
 * Handle Generate Questions Button Click
 * Uses the generated database context to create question/SQL pairs
 */
async function handleGenerateQuestions() {
    try {
        // Determine which template is selected
        const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
        const selectedTemplateId = ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
        
        // Fetch template configuration
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/rag/templates/${selectedTemplateId}/plugin-info`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await response.json();
        const autoGenConfig = data.plugin_info?.population_modes?.auto_generate || {};
        
        const requiresMcpContext = autoGenConfig.requires_mcp_context !== false;
        const inputMethod = autoGenConfig.input_method || 'mcp_context';
        
        // For templates requiring MCP context, validate it was generated
        if (requiresMcpContext && !lastGeneratedContext) {
            showNotification('error', 'Please generate database context first (Step 1)');
            return;
        }
        
        // For templates using document upload, require documents
        if (inputMethod === 'document_upload' && (!uploadedDocuments || uploadedDocuments.length === 0)) {
            showNotification('error', 'Please upload at least one document');
            return;
        }
        
        // Get parameters from dynamically generated fields
        const contextTopicEl = document.getElementById('rag-collection-llm-context-topic');
        const numExamplesEl = document.getElementById('rag-collection-llm-num-examples');
        const databaseNameEl = document.getElementById('rag-collection-llm-database-name');
        const conversionRulesEl = document.getElementById('rag-collection-llm-conversion-rules');
        
        const subject = contextTopicEl ? contextTopicEl.value.trim() : '';
        const count = numExamplesEl ? parseInt(numExamplesEl.value) : 5;
        const databaseName = databaseNameEl ? databaseNameEl.value.trim() : '';
        const targetDatabase = 'Teradata'; // Default target database
        const conversionRules = conversionRulesEl ? conversionRulesEl.value.trim() : '';
        
        if (!subject) {
            showNotification('error', 'Please enter a subject/context topic');
            return;
        }
        
        if (!databaseName) {
            showNotification('error', 'Please enter a database name');
            return;
        }
        
        // Disable button and show loading state
        ragCollectionGenerateQuestionsBtn.disabled = true;
        const originalButtonContent = ragCollectionGenerateQuestionsBtn.innerHTML;
        ragCollectionGenerateQuestionsBtn.innerHTML = `
            <svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
            </svg>
            <span>Generating...</span>
        `;
        
        showNotification('info', `Generating ${count} ${targetDatabase} question/SQL pairs...`);
        
        let apiResponse;
        const endpoint = autoGenConfig.generation_endpoint || '/api/v1/rag/generate-questions';
        
        if (inputMethod === 'document_upload') {
            // Document-based generation: Upload documents and generate questions
            const formData = new FormData();
            formData.append('subject', subject);
            formData.append('count', count.toString());
            formData.append('database_name', databaseName);
            formData.append('target_database', targetDatabase);
            if (conversionRules) {
                formData.append('conversion_rules', conversionRules);
            }
            
            // Add all uploaded documents
            uploadedDocuments.forEach(file => {
                formData.append('files', file);
            });
            
            // Get authentication token (JWT stored after login)
            const token = localStorage.getItem('tda_auth_token');
            
            // Call the generation endpoint from template config
            apiResponse = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                },
                body: formData  // No Content-Type header - browser sets it with boundary
            });
            
        } else {
            // MCP context-based generation: Use generated database context
            const requestBody = {
                subject: subject,
                count: count,
                database_context: lastGeneratedContext.final_answer_text,
                execution_trace: lastGeneratedContext.execution_trace,
                database_name: databaseName,
                target_database: targetDatabase,
                conversion_rules: conversionRules
            };
            
            // Get authentication token (JWT stored after login)
            const token = localStorage.getItem('tda_auth_token');
            
            apiResponse = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(requestBody)
            });
        }
        
        if (!apiResponse.ok) {
            const errorData = await apiResponse.json();
            throw new Error(errorData.message || 'Failed to generate questions');
        }
        
        const result = await apiResponse.json();
        
        // Store questions for later use
        lastGeneratedQuestions = result.questions;

        // Enable Create Collection button now that questions are generated
        if (addRagCollectionSubmit) {
            addRagCollectionSubmit.disabled = false;
            addRagCollectionSubmit.title = 'Create collection with generated questions';
        }

        // Display questions preview
        displayQuestionsPreview(result.questions);

        // Show success message and scroll to Create Collection button
        const successMsg = document.getElementById('rag-collection-questions-success');
        if (successMsg) {
            successMsg.classList.remove('hidden');
        }

        // Scroll to Create Collection button
        setTimeout(() => {
            if (addRagCollectionSubmit) {
                addRagCollectionSubmit.scrollIntoView({ behavior: 'smooth', block: 'center' });

                // Highlight the button
                addRagCollectionSubmit.classList.add('ring-4', 'ring-green-400', 'shadow-lg', 'shadow-green-400/50');
                addRagCollectionSubmit.style.transform = 'scale(1.05)';
                addRagCollectionSubmit.style.transition = 'all 0.3s ease';

                setTimeout(() => {
                    addRagCollectionSubmit.classList.remove('ring-4', 'ring-green-400', 'shadow-lg', 'shadow-green-400/50');
                    addRagCollectionSubmit.style.transform = 'scale(1)';
                }, 3000);
            }
        }, 300);

        showNotification('success', `Generated ${result.count} questions successfully - scroll down to create collection`);

    } catch (error) {
        console.error('Error generating questions:', error);
        showNotification('error', `Failed to generate questions: ${error.message}`);

        // Keep Create Collection button disabled on error
        if (addRagCollectionSubmit) {
            addRagCollectionSubmit.disabled = true;
            addRagCollectionSubmit.title = 'Generate questions first to enable this button';
        }
    } finally {
        // Re-enable button
        if (ragCollectionGenerateQuestionsBtn) {
            ragCollectionGenerateQuestionsBtn.disabled = false;
            ragCollectionGenerateQuestionsBtn.innerHTML = `
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                <span>Generate Questions</span>
            `;
        }
    }
}

/**
 * Display generated questions in the preview area
 */
function displayQuestionsPreview(questions) {
    if (!ragCollectionQuestionsList || !ragCollectionQuestionsResult) {
        console.error('Questions preview elements not found');
        return;
    }
    
    // Update count
    if (ragCollectionQuestionsCount) {
        ragCollectionQuestionsCount.textContent = `${questions.length} Questions Generated`;
    }
    
    // Clear previous content
    ragCollectionQuestionsList.innerHTML = '';
    
    // Add each question as a preview item
    questions.forEach((q, index) => {
        const questionDiv = document.createElement('div');
        questionDiv.className = 'bg-gray-900/50 rounded p-3 border border-gray-700';
        
        questionDiv.innerHTML = `
            <div class="text-xs font-semibold text-blue-300 mb-1">Question ${index + 1}</div>
            <div class="text-sm text-white mb-2">${escapeHtml(q.question)}</div>
            <div class="text-xs text-gray-400 font-mono bg-black/30 rounded p-2 overflow-x-auto">
                ${escapeHtml(q.sql.substring(0, 100))}${q.sql.length > 100 ? '...' : ''}
            </div>
        `;
        
        ragCollectionQuestionsList.appendChild(questionDiv);
    });
    
    // Show the questions result area
    ragCollectionQuestionsResult.classList.remove('hidden');
}

/**
 * REMOVED: handlePopulateCollection
 * This function is no longer needed because "Create Collection" now handles
 * both creating the collection and populating it in a single step.
 * The old "Populate Collection" button was redundant and confusing.
 */

/**
 * Handle population method radio button changes
 */
// Use imported handlePopulationDecisionChange from PopulationWorkflow module
const handlePopulationDecisionChange = () => {
    const elements = {
        templateOptions: ragCollectionTemplateOptions,
        populationWithTemplate: ragPopulationWithTemplate,
        switchFieldsCallback: switchTemplateFields
    };

    // Update Create Collection button state based on population mode
    if (addRagCollectionSubmit) {
        if (ragPopulationNone && ragPopulationNone.checked) {
            // "None" mode: Enable button (no generation needed)
            addRagCollectionSubmit.disabled = false;
            addRagCollectionSubmit.title = 'Create empty collection';
        } else if (ragPopulationWithTemplate && ragPopulationWithTemplate.checked) {
            // "With Template" mode: Check which method is selected
            if (ragTemplateMethodManual && ragTemplateMethodManual.checked) {
                addRagCollectionSubmit.disabled = false;
                addRagCollectionSubmit.title = 'Add manual examples, then create collection';
            } else {
                // LLM method: Disable until questions generated
                addRagCollectionSubmit.disabled = true;
                addRagCollectionSubmit.title = 'Generate questions first to enable this button';
            }
        }
    }

    return PopulationWorkflow.handlePopulationDecisionChange(elements);
};

// Use imported handleTemplateMethodChange from PopulationWorkflow module
const handleTemplateMethodChange = () => {
    const elements = {
        manualFields: ragCollectionManualFields,
        llmFields: ragCollectionLlmFields,
        templateMethodManual: ragTemplateMethodManual,
        templateMethodLlm: ragTemplateMethodLlm,
        templateType: ragCollectionTemplateType,
        examplesContainer: ragCollectionTemplateExamples,
        addExampleCallback: addCollectionTemplateExample
    };

    // Update Create Collection button state based on method
    if (addRagCollectionSubmit) {
        if (ragTemplateMethodManual && ragTemplateMethodManual.checked) {
            // Manual mode: Enable button (users can add examples immediately)
            addRagCollectionSubmit.disabled = false;
            addRagCollectionSubmit.title = 'Add manual examples, then create collection';
        } else if (ragTemplateMethodLlm && ragTemplateMethodLlm.checked) {
            // LLM mode: Disable until questions are generated
            addRagCollectionSubmit.disabled = true;
            addRagCollectionSubmit.title = 'Generate questions first to enable this button';
            // Clear previously generated questions when switching to LLM mode
            lastGeneratedQuestions = null;
        }
    }

    return PopulationWorkflow.handleTemplateMethodChange(elements);
};

/**
 * Unlock Phase 2 (Context Generation)
 */
function unlockPhase2() {
    const phase2Section = document.getElementById('phase-2-section');
    const phase2Indicator = document.getElementById('phase-indicator-2');
    
    if (phase2Section) {
        phase2Section.classList.remove('opacity-50', 'pointer-events-none');
        phase2Section.querySelector('.w-8').classList.remove('bg-gray-600', 'text-gray-400');
        phase2Section.querySelector('.w-8').classList.add('bg-teradata-orange', 'text-white');
    }
    
    if (phase2Indicator) {
        phase2Indicator.classList.remove('opacity-50');
        phase2Indicator.querySelector('.w-8').classList.remove('bg-gray-600', 'text-gray-400');
        phase2Indicator.querySelector('.w-8').classList.add('bg-teradata-orange', 'text-white');
        phase2Indicator.querySelector('.text-sm').classList.remove('text-gray-400');
        phase2Indicator.querySelector('.text-sm').classList.add('text-white');
    }
}

/**
 * Unlock Phase 3 (Question Generation)
 */
function unlockPhase3() {
    const phase3Section = document.getElementById('phase-3-section');
    const phase3Indicator = document.getElementById('phase-indicator-3');
    const phase2StatusBadge = document.getElementById('phase-2-status-badge');
    const subjectDisplay = document.getElementById('phase-3-subject-display');
    const llmSubject = document.getElementById('rag-collection-llm-subject');
    
    if (phase3Section) {
        phase3Section.classList.remove('hidden', 'opacity-50', 'pointer-events-none');
        phase3Section.querySelector('.w-8').classList.remove('bg-gray-600', 'text-gray-400');
        phase3Section.querySelector('.w-8').classList.add('bg-teradata-orange', 'text-white');
    }
    
    if (phase3Indicator) {
        phase3Indicator.classList.remove('opacity-50');
        phase3Indicator.querySelector('.w-8').classList.remove('bg-gray-600', 'text-gray-400');
        phase3Indicator.querySelector('.w-8').classList.add('bg-teradata-orange', 'text-white');
        phase3Indicator.querySelector('.text-sm').classList.remove('text-gray-400');
        phase3Indicator.querySelector('.text-sm').classList.add('text-white');
    }
    
    // Show Phase 2 completion badge
    if (phase2StatusBadge) {
        phase2StatusBadge.classList.remove('hidden');
    }
    
    // Update subject display in Phase 3
    if (subjectDisplay && llmSubject) {
        subjectDisplay.textContent = llmSubject.value || 'your specified subject';
    }
}

/**
 * Load template configuration for LLM auto-generation informative fields
 */
async function loadLlmTemplateInfo() {
    const contextToolInput = document.getElementById('rag-collection-llm-context-tool');
    const mcpToolInput = document.getElementById('rag-collection-llm-mcp-tool');
    
    if (!contextToolInput || !mcpToolInput) return;
    
    try {
        // Get selected template ID
        const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
        const selectedTemplateId = ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
        
        if (!selectedTemplateId) {
            console.warn('[LLM Setup] No template selected or available');
            return;
        }
        
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/rag/templates/${selectedTemplateId}/config`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (response.ok) {
            const result = await response.json();
            if (result.status === 'success' && result.config) {
                // Use template configuration - no hardcoded fallbacks
                contextToolInput.value = result.config.mcp_prompt_context_generator || '';
                mcpToolInput.value = result.config.default_mcp_tool || '';
            } else {
                console.warn('[LLM Setup] Template config missing auto_generate fields');
            }
        } else {
            console.error('[LLM Setup] Failed to load template config');
        }
    } catch (error) {
        console.error('[LLM Setup] Error loading template info:', error);
    }
}

/**
 * Test the MCP Prompt Context Generator
 */
// Global variable to store generated database context
let generatedDatabaseContext = null;

/**
 * Create database context (Phase 2 - mandatory step)
 */
async function createDatabaseContext() {
    const createContextBtn = document.getElementById('rag-collection-llm-create-context');
    const contextResult = document.getElementById('rag-collection-context-result');
    const contextContent = document.getElementById('rag-collection-context-content');
    const contextTitle = document.getElementById('rag-collection-context-title');
    
    if (!createContextBtn || !contextResult || !contextContent) return;
    
    // Get the MCP server selection
    const mcpServerSelect = document.getElementById('rag-collection-mcp-server');
    const mcpServerId = mcpServerSelect?.value?.trim();
    
    if (!mcpServerId) {
        contextTitle.textContent = 'Database Context Error';
        contextContent.textContent = 'Error: Please select an MCP server first.';
        contextResult.classList.remove('hidden');
        return;
    }
    
    // Get the database name and context generator prompt name
    const databaseName = ragCollectionLlmDb?.value?.trim();
    const contextToolInput = document.getElementById('rag-collection-llm-context-tool');
    const promptName = contextToolInput?.value?.trim();
    
    if (!databaseName) {
        contextTitle.textContent = 'Database Context Error';
        contextContent.textContent = 'Error: Please enter a database name first.';
        contextResult.classList.remove('hidden');
        return;
    }
    
    if (!promptName) {
        contextTitle.textContent = 'Database Context Error';
        contextContent.textContent = 'Error: Context generator prompt not configured in template.';
        contextResult.classList.remove('hidden');
        return;
    }
    
    if (!databaseName) {
        contextTitle.textContent = 'Database Context Error';
        contextContent.textContent = 'Error: Please enter a database name first.';
        contextResult.classList.remove('hidden');
        return;
    }
    
    // Show loading state
    const originalText = createContextBtn.textContent;
    createContextBtn.disabled = true;
    createContextBtn.innerHTML = `
        <svg class="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Creating...
    `;
    
    try {
        // Execute the prompt with the LLM
        const response = await fetch(`/api/v1/prompts/${promptName}/execute`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                arguments: {
                    database_name: databaseName
                }
            })
        });
        
        if (!response.ok) {
            throw new Error(`Failed to execute prompt: ${response.statusText}`);
        }
        
        const result = await response.json();
        
        
        contextTitle.textContent = 'Database Context Generated ✓';
        if (result.status === 'success' && result.response) {
            // Use the clean text response from backend (without HTML formatting)
            const cleanContext = result.response_text || result.response;
            
            // Store the clean context globally for Phase 3
            generatedDatabaseContext = cleanContext;
            
            // Display the full HTML response in UI for user viewing
            contextContent.textContent = result.response;
            contextResult.classList.remove('hidden');
            
            // SUCCESS: Unlock Phase 3
            unlockPhase3();
            showNotification('success', 'Database context created successfully! You can now proceed to Phase 3.');
        } else {
            contextContent.textContent = `Error: ${result.message || 'Failed to execute prompt'}`;
            contextResult.classList.remove('hidden');
            showNotification('error', 'Failed to create database context');
        }
        
    } catch (error) {
        console.error('Error creating database context:', error);
        contextTitle.textContent = 'Database Context Error';
        contextContent.textContent = `Error: ${error.message}`;
        contextResult.classList.remove('hidden');
        showNotification('error', `Context creation failed: ${error.message}`);
    } finally {
        // Restore button state
        createContextBtn.disabled = false;
        createContextBtn.innerHTML = originalText;
    }
}

/**
 * Generate question/SQL pairs (Phase 3)
 */
async function generateQuestions() {
    
    if (!ragCollectionGenerateQuestionsBtn || !generatedDatabaseContext) {
        console.error('[RAG Phase 3] Missing requirements - button:', !!ragCollectionGenerateQuestionsBtn, 'context:', !!generatedDatabaseContext);
        showNotification('error', 'Please complete Phase 2 (Create Context) first');
        return;
    }
    
    const subject = ragCollectionLlmSubject?.value?.trim();
    const count = ragCollectionLlmCount?.value || 5;
    const database = ragCollectionLlmDb?.value?.trim();
    
    if (!subject) {
        showNotification('error', 'Please enter a subject/topic');
        return;
    }
    
    if (!database) {
        showNotification('error', 'Please select a database');
        return;
    }
    
    // Show loading state
    const originalText = ragCollectionGenerateQuestionsBtn.textContent;
    ragCollectionGenerateQuestionsBtn.disabled = true;
    ragCollectionGenerateQuestionsBtn.innerHTML = `
        <svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Generating...
    `;
    
    try {
        showNotification('info', `Generating ${count} question/SQL pairs for "${subject}"...`);
        
        // Call backend endpoint to generate questions
        const response = await fetch('/api/v1/rag/generate-questions', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                subject: subject,
                count: parseInt(count),
                database_context: generatedDatabaseContext,
                database_name: database
            })
        });
        
        const result = await response.json();
        
        if (result.status === 'error') {
            throw new Error(result.message || 'Failed to generate questions');
        }
        
        if (!result.questions || result.questions.length === 0) {
            throw new Error('No questions were generated');
        }
        
        // Display the generated questions
        displayGeneratedQuestions(result.questions);
        showNotification('success', `Generated ${result.questions.length} question/SQL pairs successfully!`);
        
    } catch (error) {
        console.error('Error generating questions:', error);
        showNotification('error', `Failed to generate questions: ${error.message}`);
    } finally {
        // Restore button state
        ragCollectionGenerateQuestionsBtn.disabled = false;
        ragCollectionGenerateQuestionsBtn.innerHTML = originalText;
    }
}

/**
 * Display generated question/SQL pairs
 */
function displayGeneratedQuestions(questions) {
    if (!ragCollectionQuestionsResult || !ragCollectionQuestionsContent || !ragCollectionQuestionsCount) return;
    
    // Update count badge
    ragCollectionQuestionsCount.textContent = `${questions.length} pairs`;
    
    // Clear previous content
    ragCollectionQuestionsContent.innerHTML = '';
    
    // Add each question/SQL pair
    questions.forEach((item, index) => {
        const pairDiv = document.createElement('div');
        pairDiv.className = 'bg-gray-700/50 rounded-lg p-3 border border-gray-600';
        pairDiv.innerHTML = `
            <div class="flex items-start justify-between mb-2">
                <span class="text-xs font-semibold text-blue-400">Pair ${index + 1}</span>
            </div>
            <div class="space-y-2">
                <div>
                    <label class="text-xs text-gray-400">Question:</label>
                    <p class="text-sm text-gray-200 mt-1">${item.question}</p>
                </div>
                <div>
                    <label class="text-xs text-gray-400">SQL:</label>
                    <pre class="text-xs text-green-300 bg-gray-900 rounded p-2 mt-1 overflow-x-auto">${item.sql}</pre>
                </div>
            </div>
        `;
        ragCollectionQuestionsContent.appendChild(pairDiv);
    });
    
    // Show the result section
    ragCollectionQuestionsResult.classList.remove('hidden');
    
    // Mark Phase 3 as completed
    const phase3StatusBadge = document.getElementById('phase-3-status-badge');
    if (phase3StatusBadge) {
        phase3StatusBadge.classList.remove('hidden');
    }
}

/**
 * Preview the generation prompt template
 */
function previewGenerationPrompt() {
    if (!ragCollectionLlmPreviewBtn || !ragCollectionContextResult || !ragCollectionContextContent || !ragCollectionContextTitle) return;
    
    // Get form values
    const subject = ragCollectionLlmSubject?.value?.trim() || '';
    const count = ragCollectionLlmCount?.value?.trim() || '5';
    const databaseName = ragCollectionLlmDb?.value?.trim() || '';
    
    // Validation
    if (!subject) {
        ragCollectionContextTitle.textContent = 'Preview Generation Prompt';
        ragCollectionContextContent.textContent = 'Error: Please enter a subject first.';
        ragCollectionContextResult.classList.remove('hidden');
        return;
    }
    
    // Build the prompt template
    const promptTemplate = `You are an expert SQL analyst and database designer. Your task is to generate realistic question/SQL query pairs for a RAG (Retrieval Augmented Generation) system.

**Context:**
{database_context}

**Target Audience:** ${subject}

**Task:** Generate exactly ${count} question/SQL query pairs that would be relevant for the target audience described above.

**Requirements:**
1. Each question should be a natural language question that someone from the target audience would realistically ask
2. Each SQL query must:
   - Be valid SQL syntax
   - Use tables and columns from the database context provided above
   - Actually answer the question asked
   - Be optimized and follow best practices
3. Questions should cover a diverse range of use cases for the target audience
${databaseName ? `4. All queries must use the database: ${databaseName}` : ''}

**Output Format:**
Return ONLY a valid JSON array with no additional text or markdown. Each object should have exactly two fields:
[
  {
    "question": "Natural language question here",
    "sql": "SELECT ... FROM ... WHERE ..."
  },
  ...
]

Generate ${count} question/SQL pairs now.`;
    
    // Display the template
    ragCollectionContextTitle.textContent = 'Generation Prompt Template';
    ragCollectionContextContent.textContent = promptTemplate;
    ragCollectionContextResult.classList.remove('hidden');
}

/**
 * Switch template-specific fields based on selected template type
 * Renders both manual and LLM fields dynamically from template manifest
 */
async function switchTemplateFields() {
    const selectedTemplateId = ragCollectionTemplateType?.value;
    if (!selectedTemplateId) return;
    
    const sqlFields = document.getElementById('rag-collection-sql-template-fields');
    if (!sqlFields) return;
    
    try {
        // Fetch template plugin info to check population modes
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/rag/templates/${selectedTemplateId}/plugin-info`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await response.json();
        const populationModes = data.plugin_info?.population_modes || {};
        
        // Check if manual entry is supported from template manifest
        const manualSupported = populationModes.manual?.supported !== false;
        
        // Get the manual entry radio button and its label
        const manualEntryRadio = document.getElementById('rag-template-method-manual');
        const manualEntryLabel = manualEntryRadio?.closest('label');
        const llmRadio = document.getElementById('rag-template-method-llm');
        
        if (!manualSupported) {
            // Disable manual entry option based on template manifest
            if (manualEntryRadio) {
                manualEntryRadio.disabled = true;
                manualEntryRadio.checked = false;
            }
            if (manualEntryLabel) {
                manualEntryLabel.classList.add('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
                manualEntryLabel.classList.remove('hover:border-teradata-orange/50');
            }
            
            // Auto-select LLM generation
            if (llmRadio) {
                llmRadio.checked = true;
            }
        } else {
            // Re-enable manual entry for templates that support it
            if (manualEntryRadio) {
                manualEntryRadio.disabled = false;
            }
            if (manualEntryLabel) {
                manualEntryLabel.classList.remove('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
                manualEntryLabel.classList.add('hover:border-teradata-orange/50');
            }
        }
        
        // Use templateManager to render manual input fields dynamically
        await window.templateManager.renderTemplateFields(selectedTemplateId, sqlFields);
        
        // Render LLM auto-generate fields dynamically
        await renderLlmFieldsForTemplate(selectedTemplateId);
        
        // Trigger population method change to show the right UI
        await handleTemplateMethodChange();
    } catch (error) {
        console.error('[Template Fields] Failed to render template fields:', error);
        sqlFields.innerHTML = '<p class="text-red-400 text-sm">Error loading template fields</p>';
    }
}

/**
 * Validate number input fields in real-time
 */
function validateNumberInput(inputElement) {
    const min = parseInt(inputElement.dataset.min);
    const max = parseInt(inputElement.dataset.max);
    const value = parseInt(inputElement.value);
    const errorElement = document.getElementById(`${inputElement.id}-error`);
    
    if (!errorElement) return;
    
    if (isNaN(value)) {
        errorElement.textContent = 'Please enter a valid number';
        errorElement.classList.remove('hidden');
        inputElement.classList.add('border-red-500');
        return false;
    }
    
    if (value < min) {
        errorElement.textContent = `Value must be at least ${min}`;
        errorElement.classList.remove('hidden');
        inputElement.classList.add('border-red-500');
        return false;
    }
    
    if (value > max) {
        errorElement.textContent = `Value must be at most ${max}`;
        errorElement.classList.remove('hidden');
        inputElement.classList.add('border-red-500');
        return false;
    }
    
    // Valid input
    errorElement.classList.add('hidden');
    inputElement.classList.remove('border-red-500');
    return true;
}

/**
 * Validate and update the Generate Context button state
 * Template-aware validation based on required fields for each template
 */
function validateGenerateContextButton() {
    const generateContextBtn = document.getElementById('rag-collection-generate-context');
    if (!generateContextBtn) return;
    
    // Get current template
    const templateSelect = document.getElementById('rag-collection-template-select');
    const selectedTemplate = templateSelect ? templateSelect.value : '';
    
    let isValid = false;
    
    // Template-specific validation
    if (selectedTemplate === 'sql_query_doc_context_v1') {
        // SQL Query Constructor - Document Context
        // Required: user_query, sql_statement, context_topic, AND (document_file OR document_content)
        const userQueryEl = document.getElementById('rag-collection-llm-user-query');
        const sqlStatementEl = document.getElementById('rag-collection-llm-sql-statement');
        const contextTopicEl = document.getElementById('rag-collection-llm-context-topic');
        const documentContentEl = document.getElementById('rag-collection-llm-document-content');
        const documentList = document.getElementById('rag-collection-doc-list');
        
        const userQuery = userQueryEl ? userQueryEl.value.trim() : '';
        const sqlStatement = sqlStatementEl ? sqlStatementEl.value.trim() : '';
        const contextTopic = contextTopicEl ? contextTopicEl.value.trim() : '';
        const documentContent = documentContentEl ? documentContentEl.value.trim() : '';
        const hasUploadedFiles = documentList && !documentList.classList.contains('hidden') && documentList.children.length > 0;
        
        // Check minimum lengths per validation rules
        const userQueryValid = userQuery.length >= 5;
        const sqlStatementValid = sqlStatement.length >= 10;
        const contextTopicValid = contextTopic.length >= 3;
        const documentValid = documentContent.length >= 100 || hasUploadedFiles;
        
        isValid = userQueryValid && sqlStatementValid && contextTopicValid && documentValid;
    } else {
        // Default validation for other templates (Database Context, etc.)
        // Required: database_name AND mcp_prompt
        const databaseNameEl = document.getElementById('rag-collection-llm-database-name');
        const mcpPromptEl = document.getElementById('rag-collection-llm-mcp-prompt');
        
        const databaseName = databaseNameEl ? databaseNameEl.value.trim() : '';
        const mcpPrompt = mcpPromptEl ? mcpPromptEl.value.trim() : '';
        
        isValid = databaseName !== '' && mcpPrompt !== '';
    }
    
    // Update button state
    if (isValid) {
        generateContextBtn.disabled = false;
        generateContextBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        generateContextBtn.classList.add('hover:bg-blue-500');
    } else {
        generateContextBtn.disabled = true;
        generateContextBtn.classList.add('opacity-50', 'cursor-not-allowed');
        generateContextBtn.classList.remove('hover:bg-blue-500');
    }
}

/**
 * Dynamically render LLM input fields from template manifest
 */
async function renderLlmFieldsForTemplate(templateId) {
    const llmFieldsContainer = document.getElementById('rag-collection-llm-fields');
    if (!llmFieldsContainer) {
        return;
    }
    
    try {
        // Fetch template plugin info (includes manifest)
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/rag/templates/${templateId}/plugin-info`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (!response.ok) {
            throw new Error(`Failed to fetch template info: ${response.status}`);
        }
        
        const data = await response.json();
        const inputVariables = data.plugin_info?.population_modes?.auto_generate?.input_variables || {};
        
        // Clear existing fields
        llmFieldsContainer.innerHTML = '';
        
        // Store field metadata for later retrieval
        window._llmFieldMetadata = inputVariables;
        
        // Render each input variable as a form field
        for (const [varName, varConfig] of Object.entries(inputVariables)) {
            const fieldHtml = createLlmInputField(varName, varConfig);
            llmFieldsContainer.insertAdjacentHTML('beforeend', fieldHtml);
        }
        
        // Get template configuration for UI behavior
        const autoGenConfig = data.plugin_info?.population_modes?.auto_generate || {};
        const inputMethod = autoGenConfig.input_method || 'mcp_context';
        const requiresMcpContext = autoGenConfig.requires_mcp_context !== false;
        
        // Hide/show Step 1 (Generate Context) based on template requirements
        const step1Section = document.getElementById('rag-collection-step1-section');
        if (step1Section) {
            if (requiresMcpContext) {
                step1Section.classList.remove('hidden');
            } else {
                step1Section.classList.add('hidden');
            }
        }
        
        // For templates without MCP context, show Step 2 immediately and renumber it as Step 1
        const step2Section = document.getElementById('rag-collection-step2-section');
        if (step2Section) {
            if (!requiresMcpContext) {
                step2Section.classList.remove('hidden');
                // Update step number from 2 to 1
                const stepBadge = step2Section.querySelector('.bg-blue-600');
                if (stepBadge) {
                    stepBadge.textContent = '1';
                }
                const stepTitle = step2Section.querySelector('h4');
                if (stepTitle) {
                    stepTitle.textContent = 'Generate Questions';
                }
                const stepDescription = step2Section.querySelector('.text-xs.text-gray-400');
                if (stepDescription) {
                    stepDescription.textContent = 'Create question/SQL pairs from documents';
                }
            } else {
                // Reset to Step 2 for MCP-based templates
                const stepBadge = step2Section.querySelector('.bg-blue-600');
                if (stepBadge) {
                    stepBadge.textContent = '2';
                }
                const stepTitle = step2Section.querySelector('h4');
                if (stepTitle) {
                    stepTitle.textContent = 'Generate Questions';
                }
                const stepDescription = step2Section.querySelector('.text-xs.text-gray-400');
                if (stepDescription) {
                    stepDescription.textContent = 'Create question/SQL pairs';
                }
            }
        }
        
        if (inputMethod === 'document_upload') {
            // Add document upload field for Document Context template
            const documentUploadHtml = `
                <div class="bg-gray-800/50 rounded-lg p-4 border border-gray-600">
                    <label class="block text-sm font-medium text-gray-300 mb-2">
                        Upload Documents
                        <span class="text-red-400">*</span>
                    </label>
                    <div class="border-2 border-dashed border-gray-600 rounded-lg p-4 text-center hover:border-teradata-orange/50 transition-colors">
                        <input type="file" id="rag-collection-doc-upload" 
                               accept=".pdf,.txt,.doc,.docx" 
                               multiple
                               class="hidden">
                        <label for="rag-collection-doc-upload" class="cursor-pointer">
                            <div class="flex flex-col items-center gap-2">
                                <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path>
                                </svg>
                                <div class="text-sm text-gray-300">Click to upload or drag and drop</div>
                                <div class="text-xs text-gray-400">PDF, TXT, DOC, DOCX (Max 50MB each)</div>
                            </div>
                        </label>
                    </div>
                    <div id="rag-collection-doc-list" class="mt-3 space-y-2 hidden">
                        <!-- Uploaded files will be listed here -->
                    </div>
                    <p class="text-xs text-gray-400 mt-2">Upload technical documentation, requirements, or business context documents. The LLM will analyze these to generate relevant question/SQL pairs.</p>
                </div>
            `;
            llmFieldsContainer.insertAdjacentHTML('beforeend', documentUploadHtml);
            
            // Add event listener for file upload using event delegation
            // Wait a bit longer to ensure DOM is fully ready
            setTimeout(() => {
                const fileInput = document.getElementById('rag-collection-doc-upload');
                if (fileInput) {
                    console.log('[Document Upload] Attaching event listener to file input');
                    // Remove any existing listener first
                    fileInput.removeEventListener('change', handleDocumentUpload);
                    // Add the listener
                    fileInput.addEventListener('change', handleDocumentUpload);
                    console.log('[Document Upload] Event listener attached successfully');
                } else {
                    console.error('[Document Upload] File input element not found');
                }
            }, 100);
        } else if (inputMethod === 'mcp_context') {
            // Add MCP Context Prompt field for MCP-based templates
            const mcpPromptFieldHtml = `
                <div class="bg-gray-800/50 rounded-lg p-3 border border-gray-600">
                    <label class="block text-sm font-medium text-gray-300 mb-2">
                        MCP Context Prompt
                        <span class="text-red-400">*</span>
                    </label>
                    <input type="text" id="rag-collection-llm-mcp-prompt" 
                           class="w-full p-3 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-teradata-orange focus:border-teradata-orange outline-none text-white text-sm"
                           placeholder="e.g., base_databaseBusinessDesc"
                           value="${data.plugin_info?.input_variables?.mcp_context_prompt?.default || 'base_databaseBusinessDesc'}">
                    <p class="text-xs text-gray-400 mt-1">Prompt used to retrieve database schema and context for question generation.</p>
                </div>
            `;
            llmFieldsContainer.insertAdjacentHTML('beforeend', mcpPromptFieldHtml);
            
            // Add validation listener to MCP prompt field after it's created
            setTimeout(() => {
                const mcpPromptEl = document.getElementById('rag-collection-llm-mcp-prompt');
                if (mcpPromptEl) {
                    mcpPromptEl.addEventListener('input', validateGenerateContextButton);
                    // Run validation immediately to set initial state
                    validateGenerateContextButton();
                }
            }, 50);
        }
        
        // Attach event listeners to newly created fields for prompt preview auto-refresh
        for (const varName of Object.keys(inputVariables)) {
            const fieldId = `rag-collection-llm-${varName.replace(/_/g, '-')}`;
            const fieldElement = document.getElementById(fieldId);
            if (fieldElement) {
                fieldElement.addEventListener('input', refreshQuestionGenerationPrompt);
                
                // Add validation listener for required fields
                if (varName === 'database_name' || 
                    varName === 'user_query' || 
                    varName === 'sql_statement' || 
                    varName === 'context_topic' ||
                    varName === 'document_content') {
                    fieldElement.addEventListener('input', validateGenerateContextButton);
                }
                
                // Add real-time validation for number inputs
                if (fieldElement.type === 'number') {
                    fieldElement.addEventListener('input', function() {
                        validateNumberInput(fieldElement);
                    });
                    fieldElement.addEventListener('blur', function() {
                        validateNumberInput(fieldElement);
                    });
                }
            }
        }
        
        // Run initial validation after all fields are created
        setTimeout(() => {
            validateGenerateContextButton();
        }, 100);
        
    } catch (error) {
        console.error('[LLM Fields] Failed to render:', error);
        llmFieldsContainer.innerHTML = '<p class="text-red-400 text-sm">Error loading LLM fields</p>';
    }
}

/**
 * Create HTML for a single LLM input field based on variable configuration
 */
function createLlmInputField(varName, varConfig) {
    const required = varConfig.required ? '<span class="text-red-400">*</span>' : '';
    const placeholder = varConfig.example || varConfig.description || '';
    const description = varConfig.description || '';
    const type = varConfig.type || 'string';
    
    // Determine field ID (use existing IDs for compatibility)
    const fieldId = `rag-collection-llm-${varName.replace(/_/g, '-')}`;
    
    // Build label with proper capitalization
    const label = varName.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    
    if (type === 'integer' || type === 'number') {
        const min = varConfig.min || 1;
        const max = varConfig.max || 1000;
        const defaultVal = varConfig.default || 5;
        
        return `
            <div>
                <label class="block text-sm font-medium text-gray-300 mb-2">
                    ${label} ${required}
                </label>
                <input type="number" id="${fieldId}" 
                       value="${defaultVal}" min="${min}" max="${max}"
                       class="w-full p-2 bg-gray-600 border border-gray-500 rounded-md focus:ring-2 focus:ring-teradata-orange outline-none text-white text-sm"
                       placeholder="${placeholder}"
                       data-min="${min}" data-max="${max}">
                <p id="${fieldId}-error" class="text-xs text-red-400 mt-1 hidden"></p>
                ${description ? `<p class="text-xs text-gray-400 mt-1">${description}</p>` : ''}
            </div>
        `;
    } else if (varName.includes('content') || varName.includes('rules') || varName.includes('context')) {
        // Multi-line textarea for content fields
        return `
            <div>
                <label class="block text-sm font-medium text-gray-300 mb-2">
                    ${label} ${required}
                </label>
                <textarea id="${fieldId}" rows="3"
                          class="w-full p-3 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-teradata-orange focus:border-teradata-orange outline-none text-white text-sm resize-none"
                          placeholder="${placeholder}"></textarea>
                ${description ? `<p class="text-xs text-gray-400 mt-1">${description}</p>` : ''}
            </div>
        `;
    } else {
        // Single-line input for other fields
        return `
            <div>
                <label class="block text-sm font-medium text-gray-300 mb-2">
                    ${label} ${required}
                </label>
                <input type="text" id="${fieldId}" 
                       class="w-full p-3 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-teradata-orange focus:border-teradata-orange outline-none text-white text-sm"
                       placeholder="${placeholder}">
                ${description ? `<p class="text-xs text-gray-400 mt-1">${description}</p>` : ''}
            </div>
        `;
    }
}

/**
 * Handle document upload for Document Context template
 */
let uploadedDocuments = [];

function handleDocumentUpload(event) {
    console.log('[Document Upload] ===== HANDLER CALLED =====');
    console.log('[Document Upload] Event:', event);
    console.log('[Document Upload] Event type:', event.type);
    console.log('[Document Upload] Target:', event.target);
    console.log('[Document Upload] Target files:', event.target.files);
    
    const files = Array.from(event.target.files);
    console.log('[Document Upload] Files array:', files);
    console.log('[Document Upload] Files count:', files.length);
    
    if (files.length === 0) {
        console.warn('[Document Upload] No files selected!');
        return;
    }
    
    const docList = document.getElementById('rag-collection-doc-list');
    console.log('[Document Upload] Document list element:', docList);
    
    if (!docList) {
        console.error('[Document Upload] Document list element not found');
        return;
    }
    
    // Filter valid files (max 50MB each)
    const validFiles = files.filter(file => {
        const maxSize = 50 * 1024 * 1024; // 50MB
        console.log(`[Document Upload] Checking file: ${file.name}, size: ${file.size} bytes`);
        if (file.size > maxSize) {
            console.warn(`[Document Upload] File ${file.name} exceeds 50MB`);
            showNotification('warning', `File ${file.name} exceeds 50MB and was skipped`);
            return false;
        }
        return true;
    });
    
    console.log('[Document Upload] Valid files count:', validFiles.length);
    
    if (validFiles.length === 0) {
        console.warn('[Document Upload] No valid files after filtering');
        return;
    }
    
    // Add new files to existing ones (allows multiple uploads)
    console.log('[Document Upload] Current uploadedDocuments:', uploadedDocuments);
    uploadedDocuments = [...uploadedDocuments, ...validFiles];
    console.log('[Document Upload] Updated uploadedDocuments:', uploadedDocuments);
    
    // Show document list
    console.log('[Document Upload] Showing document list');
    docList.classList.remove('hidden');
    docList.innerHTML = '';
    
    // Render each uploaded document
    console.log('[Document Upload] Rendering document list UI');
    uploadedDocuments.forEach((file, index) => {
        console.log(`[Document Upload] Rendering file ${index}: ${file.name}`);
        const fileItem = `
            <div class="flex items-center justify-between p-2 bg-gray-700 rounded border border-gray-600">
                <div class="flex items-center gap-2">
                    <svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    <div>
                        <div class="text-sm text-white">${file.name}</div>
                        <div class="text-xs text-gray-400">${(file.size / 1024).toFixed(1)} KB</div>
                    </div>
                </div>
                <button type="button" class="text-red-400 hover:text-red-300" onclick="removeUploadedDocument(${index})">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
        `;
        docList.insertAdjacentHTML('beforeend', fileItem);
    });
    
    console.log('[Document Upload] Document list rendered successfully');
    console.log('[Document Upload] Showing success notification');
    showNotification('success', `${validFiles.length} document(s) uploaded`);
    
    // Reset the file input so the same files can be selected again
    event.target.value = '';
    console.log('[Document Upload] File input reset');
    
    // Trigger validation to update Generate Context button
    validateGenerateContextButton();
    
    console.log('[Document Upload] ===== HANDLER COMPLETE =====');
}

/**
 * Remove an uploaded document
 */
function removeUploadedDocument(index) {
    console.log(`[Document Upload] Removing document at index ${index}`);
    uploadedDocuments.splice(index, 1);
    
    const docList = document.getElementById('rag-collection-doc-list');
    if (!docList) return;
    
    // If no documents left, hide the list
    if (uploadedDocuments.length === 0) {
        docList.classList.add('hidden');
        docList.innerHTML = '';
        showNotification('info', 'All documents removed');
        return;
    }
    
    // Re-render the document list
    docList.innerHTML = '';
    uploadedDocuments.forEach((file, idx) => {
        const fileItem = `
            <div class="flex items-center justify-between p-2 bg-gray-700 rounded border border-gray-600">
                <div class="flex items-center gap-2">
                    <svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    <div>
                        <div class="text-sm text-white">${file.name}</div>
                        <div class="text-xs text-gray-400">${(file.size / 1024).toFixed(1)} KB</div>
                    </div>
                </div>
                <button type="button" class="text-red-400 hover:text-red-300" onclick="removeUploadedDocument(${idx})">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
        `;
        docList.insertAdjacentHTML('beforeend', fileItem);
    });
    
    showNotification('success', 'Document removed');
    
    // Trigger validation to update Generate Context button
    validateGenerateContextButton();
    
    // Reset the file input so the same file can be selected again
    const fileInput = document.getElementById('rag-collection-doc-upload');
    if (fileInput) {
        fileInput.value = '';
    }
}

// Make removeUploadedDocument globally accessible
window.removeUploadedDocument = removeUploadedDocument;

/**
 * Load MCP tool name from template configuration
 * Note: This is now handled by renderTemplateFields, but kept for backwards compatibility
 */
async function loadTemplateToolName(templateId) {
    const toolInput = document.getElementById('rag-collection-template-tool');
    if (!toolInput) return;
    
    try {
        const config = await window.templateManager.getTemplateConfig(templateId);
        if (config && config.default_mcp_tool) {
            toolInput.value = config.default_mcp_tool;
        } else {
            toolInput.value = 'base_readQuery'; // Fallback default
        }
    } catch (error) {
        console.error('Error loading template tool name:', error);
        toolInput.value = 'base_readQuery';
    }
}

// Level 1: Event Listeners for Population Decision (None vs With Template)
if (ragPopulationNone) {
    ragPopulationNone.addEventListener('change', handlePopulationDecisionChange);
}
if (ragPopulationWithTemplate) {
    ragPopulationWithTemplate.addEventListener('change', handlePopulationDecisionChange);
}

// Level 2: Event Listeners for Template Population Method (Manual vs Auto-generate)
if (ragTemplateMethodManual) {
    ragTemplateMethodManual.addEventListener('change', handleTemplateMethodChange);
}
if (ragTemplateMethodLlm) {
    ragTemplateMethodLlm.addEventListener('change', handleTemplateMethodChange);
}

// Event Listeners for Template Options
if (ragCollectionTemplateType) {
    ragCollectionTemplateType.addEventListener('change', async () => {
        await switchTemplateFields();
        // Don't reset radio buttons - let them keep their current state
        // (Deploy button sets LLM method, manual entry can set manual method)
    });
}

if (ragCollectionTemplateAddExample) {
    ragCollectionTemplateAddExample.addEventListener('click', addCollectionTemplateExample);
}

// Event Listener for Generate Context button
if (ragCollectionGenerateContextBtn) {
    ragCollectionGenerateContextBtn.addEventListener('click', handleGenerateContext);
}

// Event Listener for Generate Questions button
if (ragCollectionGenerateQuestionsBtn) {
    ragCollectionGenerateQuestionsBtn.addEventListener('click', handleGenerateQuestions);
}

// REMOVED: Event listener for Populate Collection button (button no longer exists)

// Close button for context result (collapses the content but keeps the section visible)
if (ragCollectionContextClose) {
    ragCollectionContextClose.addEventListener('click', () => {
        const contextContent = document.getElementById('rag-collection-context-content');
        if (contextContent) {
            // Just collapse the content display, not the entire result div
            contextContent.classList.add('hidden');
            // Hide the close button itself
            ragCollectionContextClose.classList.add('hidden');
        }
    });
}

// Close button for questions result
if (ragCollectionQuestionsClose) {
    ragCollectionQuestionsClose.addEventListener('click', () => {
        if (ragCollectionQuestionsResult) {
            ragCollectionQuestionsResult.classList.add('hidden');
        }
    });
}

// Event Listener for Refresh Prompt button
if (ragCollectionRefreshPromptBtn) {
    ragCollectionRefreshPromptBtn.addEventListener('click', refreshQuestionGenerationPrompt);
}

// Auto-refresh prompt when LLM fields change
if (ragCollectionLlmSubject) {
    ragCollectionLlmSubject.addEventListener('input', refreshQuestionGenerationPrompt);
}
if (ragCollectionLlmCount) {
    ragCollectionLlmCount.addEventListener('input', refreshQuestionGenerationPrompt);
}
if (ragCollectionLlmDb) {
    ragCollectionLlmDb.addEventListener('input', refreshQuestionGenerationPrompt);
}

// Event Listeners for Context Result Modal
if (contextResultModalClose) {
    contextResultModalClose.addEventListener('click', closeContextResultModal);
}

if (contextResultModalOk) {
    contextResultModalOk.addEventListener('click', closeContextResultModal);
}

if (contextResultModalOverlay) {
    contextResultModalOverlay.addEventListener('click', (e) => {
        if (e.target === contextResultModalOverlay) {
            closeContextResultModal();
        }
    });
}

// Event Listeners for SQL Template Modal
if (sqlTemplateModalClose) {
    sqlTemplateModalClose.addEventListener('click', closeSqlTemplateModal);
}

// ============================================================================
// Template Editor Functions
// ============================================================================

/**
 * Open the Template Editor modal with dynamic template rendering
 * @param {string} templateId - The template ID to edit (defaults to current selection)
 */
async function editTemplate(templateId = null) {
    const modal = document.getElementById('template-editor-modal-overlay');
    const content = document.getElementById('template-editor-modal-content');
    
    if (!modal || !content) return;
    
    try {
        // Get template ID from parameter or current selection
        const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
        const selectedTemplateId = templateId || ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
        
        // Store current template ID for form submission
        modal.setAttribute('data-template-id', selectedTemplateId);
        
        // Load template metadata
        const template = window.templateManager.getTemplate(selectedTemplateId);
        if (!template) {
            showNotification(`Template '${selectedTemplateId}' not found`, 'error');
            return;
        }
        
        // Populate template info section
        document.getElementById('template-editor-template-name').textContent = template.display_name;
        document.getElementById('template-editor-template-description').textContent = template.description || '';
        
        // Load template configuration
        const config = await window.templateManager.getTemplateConfig(selectedTemplateId);
        
        if (!config) {
            showNotification('Failed to load template configuration', 'error');
            return;
        }
        
        // Render input variables section
        const inputVarsContainer = document.getElementById('template-editor-input-vars-content');
        const inputVarsSection = document.getElementById('template-editor-input-variables');
        
        if (config.input_variables && config.input_variables.length > 0) {
            inputVarsContainer.innerHTML = '';
            
            config.input_variables.forEach(variable => {
                const badge = document.createElement('span');
                badge.className = 'inline-flex items-center px-3 py-1 rounded-full text-sm bg-blue-100 text-blue-800 border border-blue-200';
                badge.innerHTML = `
                    <svg class="w-3.5 h-3.5 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"></path>
                    </svg>
                    ${variable.name}
                    ${variable.required ? '<span class="ml-1 text-red-600">*</span>' : ''}
                `;
                inputVarsContainer.appendChild(badge);
            });
            
            inputVarsSection.classList.remove('hidden');
        } else {
            inputVarsSection.classList.add('hidden');
        }
        
        // Render configuration fields dynamically
        const configContainer = document.getElementById('template-editor-config-content');
        configContainer.innerHTML = '';
        
        // Create fields based on template configuration structure
        if (config.default_mcp_tool !== undefined) {
            configContainer.appendChild(createConfigField(
                'template-default-mcp-tool',
                'Default MCP Tool Name',
                config.default_mcp_tool,
                'text',
                'The default MCP tool to use for this template'
            ));
        }
        
        if (config.default_mcp_context_prompt !== undefined) {
            configContainer.appendChild(createConfigField(
                'template-default-mcp-context-prompt',
                'Default MCP Context Prompt',
                config.default_mcp_context_prompt,
                'text',
                'The default context prompt tool to use'
            ));
        }
        
        if (config.estimated_input_tokens !== undefined) {
            configContainer.appendChild(createConfigField(
                'template-input-tokens',
                'Estimated Input Tokens',
                config.estimated_input_tokens,
                'number',
                'Estimated token count for input'
            ));
        }
        
        if (config.estimated_output_tokens !== undefined) {
            configContainer.appendChild(createConfigField(
                'template-output-tokens',
                'Estimated Output Tokens',
                config.estimated_output_tokens,
                'number',
                'Estimated token count for output'
            ));
        }
        
        // Show modal with animation
        modal.classList.remove('hidden');
        requestAnimationFrame(() => {
            modal.classList.remove('opacity-0');
            content.classList.remove('scale-95', 'opacity-0');
            content.classList.add('scale-100', 'opacity-100');
        });
        
    } catch (error) {
        console.error('Failed to load template for editing:', error);
        showNotification('Failed to load template configuration', 'error');
    }
}

/**
 * Create a configuration field element
 */
function createConfigField(id, label, value, type = 'text', description = '') {
    const fieldDiv = document.createElement('div');
    fieldDiv.className = 'mb-4';
    
    const labelEl = document.createElement('label');
    labelEl.htmlFor = id;
    labelEl.className = 'block text-sm font-medium text-gray-700 mb-1';
    labelEl.textContent = label;
    
    const inputEl = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    inputEl.id = id;
    inputEl.className = 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors';
    
    if (type === 'textarea') {
        inputEl.rows = 3;
        inputEl.value = value || '';
    } else {
        inputEl.type = type;
        inputEl.value = value || '';
        if (type === 'number') {
            inputEl.min = '0';
            inputEl.step = '1';
        }
    }
    
    fieldDiv.appendChild(labelEl);
    fieldDiv.appendChild(inputEl);
    
    if (description) {
        const descEl = document.createElement('p');
        descEl.className = 'mt-1 text-xs text-gray-500';
        descEl.textContent = description;
        fieldDiv.appendChild(descEl);
    }
    
    return fieldDiv;
}

// Backward compatibility alias
async function editSqlTemplate() {
    const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
    await editTemplate(getDefaultTemplateId('planner'));
}

/**
 * Close the Template Editor modal
 */
function closeTemplateEditorModal() {
    const modal = document.getElementById('template-editor-modal-overlay');
    const content = document.getElementById('template-editor-modal-content');
    
    if (!modal || !content) return;
    
    // Animate out
    modal.classList.add('opacity-0');
    content.classList.remove('scale-100', 'opacity-100');
    content.classList.add('scale-95', 'opacity-0');
    
    // Hide after animation
    setTimeout(() => {
        modal.classList.add('hidden');
    }, 200);
}

/**
 * Handle Template Editor form submission (template-agnostic)
 */
async function handleTemplateEditorSubmit(event) {
    event.preventDefault();
    
    try {
        // Get template ID from modal
        const modal = document.getElementById('template-editor-modal-overlay');
        const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
        const templateId = modal.getAttribute('data-template-id') || getDefaultTemplateId('planner');
        
        if (!templateId) {
            showNotification('No template selected', 'error');
            return;
        }
        
        // Load current configuration to know which fields exist
        const currentConfig = await window.templateManager.getTemplateConfig(templateId);
        
        if (!currentConfig) {
            showNotification('Failed to load template configuration', 'error');
            return;
        }
        
        // Build configuration payload dynamically based on existing fields
        const configPayload = {};
        
        // Collect values from dynamically created fields
        if (currentConfig.default_mcp_tool !== undefined) {
            const toolInput = document.getElementById('template-default-mcp-tool');
            if (toolInput) {
                const value = toolInput.value.trim();
                if (!value) {
                    showNotification('Default MCP tool name cannot be empty', 'error');
                    return;
                }
                configPayload.default_mcp_tool = value;
            }
        }
        
        if (currentConfig.default_mcp_context_prompt !== undefined) {
            const promptInput = document.getElementById('template-default-mcp-context-prompt');
            if (promptInput) {
                const value = promptInput.value.trim();
                if (!value) {
                    showNotification('Default MCP context prompt cannot be empty', 'error');
                    return;
                }
                configPayload.default_mcp_context_prompt = value;
            }
        }
        
        if (currentConfig.estimated_input_tokens !== undefined) {
            const inputTokensEl = document.getElementById('template-input-tokens');
            if (inputTokensEl) {
                configPayload.estimated_input_tokens = parseInt(inputTokensEl.value) || 0;
            }
        }
        
        if (currentConfig.estimated_output_tokens !== undefined) {
            const outputTokensEl = document.getElementById('template-output-tokens');
            if (outputTokensEl) {
                configPayload.estimated_output_tokens = parseInt(outputTokensEl.value) || 0;
            }
        }
        
        // Save configuration to backend
        const response = await fetch(`/api/v1/rag/templates/${templateId}/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configPayload)
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showNotification('Template configuration updated successfully', 'success');
            
            // Clear cache to force reload
            window.templateManager.clearCache();
            
            closeTemplateEditorModal();
        } else {
            showNotification(result.message || 'Failed to update template configuration', 'error');
        }
    } catch (error) {
        console.error('Failed to save template configuration:', error);
        showNotification('Failed to save template configuration', 'error');
    }
}

// Event Listeners for Template Editor
const templateEditorModalClose = document.getElementById('template-editor-modal-close');
const templateEditorCancel = document.getElementById('template-editor-cancel');
const templateEditorForm = document.getElementById('template-editor-form');

if (templateEditorModalClose) {
    templateEditorModalClose.addEventListener('click', closeTemplateEditorModal);
}

if (templateEditorCancel) {
    templateEditorCancel.addEventListener('click', closeTemplateEditorModal);
}

if (templateEditorForm) {
    templateEditorForm.addEventListener('submit', handleTemplateEditorSubmit);
}

// Event Listener for Edit Template Button (modular)
const editSqlTemplateBtn = document.getElementById('edit-sql-template-btn');
if (editSqlTemplateBtn) {
    editSqlTemplateBtn.addEventListener('click', async (event) => {
        event.stopPropagation(); // Prevent card click from triggering
        // Get current template selection
        const { getDefaultTemplateId } = await import('./rag/templateSystem.js');
        const currentTemplateId = ragCollectionTemplateType?.value || getDefaultTemplateId('planner');
        if (currentTemplateId) {
            editTemplate(currentTemplateId);
        }
    });
}

// Make template editing functions globally available
window.editTemplate = editTemplate;
window.editSqlTemplate = editSqlTemplate; // Backward compatibility alias

if (sqlTemplateCancel) {
    sqlTemplateCancel.addEventListener('click', closeSqlTemplateModal);
}

if (sqlTemplateModalOverlay) {
    sqlTemplateModalOverlay.addEventListener('click', (e) => {
        if (e.target === sqlTemplateModalOverlay) {
            closeSqlTemplateModal();
        }
    });
}

if (sqlTemplateAddExampleBtn) {
    sqlTemplateAddExampleBtn.addEventListener('click', addSqlExample);
}

if (sqlTemplateForm) {
    sqlTemplateForm.addEventListener('submit', handleSqlTemplateSubmit);
}

// Initialize template system on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeTemplateSystem);
} else {
    // DOM already loaded
    initializeTemplateSystem();
}

// ========================================
// Repository Tab Switching
// ========================================

/**
 * Initialize repository tabs for Planner Repositories and Knowledge Repositories
 */
function initializeRepositoryTabs() {
    const plannerRepoTab = document.getElementById('planner-repo-tab');
    const knowledgeRepoTab = document.getElementById('knowledge-repo-tab');
    const plannerRepoContent = document.getElementById('planner-repo-content');
    const knowledgeRepoContent = document.getElementById('knowledge-repo-content');
    
    if (!plannerRepoTab || !knowledgeRepoTab || !plannerRepoContent || !knowledgeRepoContent) {
        console.warn('[Repository Tabs] Tab elements not found');
        return;
    }
    
    // Tab click handler
    const switchTab = (activeTab, activeContent, inactiveTab, inactiveContent) => {
        // Update tab styling
        activeTab.classList.add('active');
        inactiveTab.classList.remove('active');

        // Update content visibility
        activeContent.classList.remove('hidden');
        inactiveContent.classList.add('hidden');
    };
    
    // Planner Repositories tab click
    plannerRepoTab.addEventListener('click', () => {
        switchTab(plannerRepoTab, plannerRepoContent, knowledgeRepoTab, knowledgeRepoContent);
    });
    
    // Knowledge Repositories tab click
    knowledgeRepoTab.addEventListener('click', () => {
        switchTab(knowledgeRepoTab, knowledgeRepoContent, plannerRepoTab, plannerRepoContent);
        
        // Load Knowledge repositories when tab is clicked
        if (window.knowledgeRepositoryHandler) {
            window.knowledgeRepositoryHandler.loadKnowledgeRepositories();
        }
    });
    
    console.log('[Repository Tabs] Initialized successfully');
}

/**
 * Initialize Knowledge repository handlers
 */
async function initializeKnowledgeRepositoryHandlers() {
    try {
        const { initializeKnowledgeRepositoryHandlers, loadKnowledgeRepositories, deleteKnowledgeRepository, openUploadDocumentsModal } = await import('./knowledgeRepositoryHandler.js');

        // Initialize handlers
        initializeKnowledgeRepositoryHandlers();

        // Store functions globally for tab switching and card actions
        window.knowledgeRepositoryHandler = {
            loadKnowledgeRepositories,
            deleteKnowledgeRepository,
            openUploadDocumentsModal
        };

        console.log('[Knowledge] Knowledge repository handlers loaded');
    } catch (error) {
        console.error('[Knowledge] Failed to load Knowledge repository handlers:', error);
    }
}

// Initialize repository tabs and Knowledge handlers on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initializeRepositoryTabs();
        initializeKnowledgeRepositoryHandlers();
    });
} else {
    initializeRepositoryTabs();
    initializeKnowledgeRepositoryHandlers();
}

// Export functions for use in other modules
// Auto-refresh state for Intelligence KPIs
let ragKpiRefreshInterval = null;
const RAG_KPI_REFRESH_INTERVAL_MS = 30000; // 30 seconds

function startAutoRefresh() {
    if (ragKpiRefreshInterval) {
        clearInterval(ragKpiRefreshInterval);
    }
    
    ragKpiRefreshInterval = setInterval(() => {
        console.log('[Intelligence] Auto-refreshing KPIs...');
        calculateRagImpactKPIs();
    }, RAG_KPI_REFRESH_INTERVAL_MS);
}

function stopAutoRefresh() {
    if (ragKpiRefreshInterval) {
        clearInterval(ragKpiRefreshInterval);
        ragKpiRefreshInterval = null;
    }
}

// Setup event listeners for Intelligence Performance auto-refresh controls
function setupIntelligenceRefreshControls() {
    // Manual refresh button
    const refreshBtn = document.getElementById('refresh-intelligence-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            console.log('[Intelligence] Manual refresh triggered');
            calculateRagImpactKPIs();
        });
    }

    // Auto-refresh toggle
    const autoRefreshToggle = document.getElementById('intelligence-auto-refresh-toggle');
    if (autoRefreshToggle) {
        // Load saved preference (default to enabled)
        const savedAutoRefresh = localStorage.getItem('intelligenceAutoRefresh');
        const isEnabled = savedAutoRefresh !== null ? savedAutoRefresh === 'true' : true;

        autoRefreshToggle.checked = isEnabled;

        if (isEnabled) {
            startAutoRefresh();
        }

        autoRefreshToggle.addEventListener('change', (e) => {
            const enabled = e.target.checked;
            localStorage.setItem('intelligenceAutoRefresh', enabled.toString());

            if (enabled) {
                console.log('[Intelligence] Auto-refresh enabled (30s interval)');
                startAutoRefresh();
                window.showNotification?.('Auto-refresh enabled', 'success');
            } else {
                console.log('[Intelligence] Auto-refresh disabled');
                stopAutoRefresh();
                window.showNotification?.('Auto-refresh disabled', 'info');
            }
        });
    }
}

// Initialize controls when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupIntelligenceRefreshControls);
} else {
    setupIntelligenceRefreshControls();
}

// ============================================================================
// INTELLIGENCE PERFORMANCE TABS (My Performance / System Performance)
// ============================================================================

// State for Intelligence tabs
let intelligenceCurrentView = 'my'; // 'my' or 'system'
let isIntelligenceAdmin = false;

/**
 * Initialize Intelligence Performance tabs
 * Checks if user is admin and shows System Performance tab accordingly
 */
async function initIntelligenceTabs() {
    try {
        // Check if user has VIEW_ALL_SESSIONS feature (same approach as Execution Dashboard)
        const response = await fetch('/api/v1/auth/me/features', {
            headers: {
                'Authorization': `Bearer ${window.authClient?.getToken() || localStorage.getItem('tda_auth_token')}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            if (data.status === 'success' && data.features) {
                isIntelligenceAdmin = data.features.includes('view_all_sessions');

                if (isIntelligenceAdmin) {
                    // Show System Performance tab for admins
                    const systemTab = document.getElementById('intel-tab-system-performance');
                    if (systemTab) {
                        systemTab.classList.remove('hidden');
                    }
                    console.log('[Intelligence] Admin detected - showing System Performance tab');
                }
            }
        }
    } catch (error) {
        console.warn('[Intelligence] Could not check admin status:', error);
        isIntelligenceAdmin = false;
    }
}

/**
 * Switch between My Performance and System Performance tabs
 * @param {string} view - 'my' or 'system'
 */
async function switchIntelligenceTab(view) {
    if (view === 'system' && !isIntelligenceAdmin) {
        console.warn('[Intelligence] System performance view is admin-only');
        return;
    }

    intelligenceCurrentView = view;

    // Update tab styling
    const myTab = document.getElementById('intel-tab-my-performance');
    const systemTab = document.getElementById('intel-tab-system-performance');

    if (view === 'my') {
        myTab.classList.add('active');
        if (systemTab) {
            systemTab.classList.remove('active');
        }
    } else {
        if (systemTab) {
            systemTab.classList.add('active');
        }
        myTab.classList.remove('active');
    }

    // Update scope indicator
    const scopeIndicator = document.getElementById('rag-kpi-scope-indicator');
    if (scopeIndicator) {
        scopeIndicator.textContent = view === 'system'
            ? 'System-Wide Performance (All Users)'
            : 'Your Learning Performance';
    }

    // Refresh KPIs with new view
    await calculateRagImpactKPIs();

    console.log(`[Intelligence] Switched to ${view} performance view`);
}

/**
 * Fetch system-wide metrics for System Performance view (admin only)
 */
async function fetchSystemIntelligenceMetrics() {
    try {
        const response = await fetch('/api/v1/consumption/system-summary', {
            headers: {
                'Authorization': `Bearer ${window.authClient?.getToken() || localStorage.getItem('tda_auth_token')}`
            }
        });

        if (!response.ok) {
            console.error('[Intelligence] Failed to fetch system metrics:', response.status);
            return null;
        }

        return await response.json();
    } catch (error) {
        console.error('[Intelligence] Error fetching system metrics:', error);
        return null;
    }
}

// Initialize tabs on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initIntelligenceTabs);
} else {
    initIntelligenceTabs();
}

window.ragCollectionManagement = {
    toggleRagCollection,
    deleteRagCollection,
    refreshRagCollection,
    openEditCollectionModal,
    calculateRagImpactKPIs,
    openAddRagCollectionModal,
    startAutoRefresh,
    stopAutoRefresh,
    switchIntelligenceTab,
    initIntelligenceTabs
};
