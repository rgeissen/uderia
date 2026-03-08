/**
 * RAG Collection Management - Population Workflow
 * 
 * Handles the 2-level population flow:
 * Level 1: None vs Populate with Template
 * Level 2: Manual vs Auto-generate with LLM
 */

/**
 * Level 1: Handle population decision change (None vs With Template)
 * @param {object} elements - DOM elements {templateOptions, populationWithTemplate, templateType, switchFieldsCallback}
 */
export async function handlePopulationDecisionChange(elements) {
    const { templateOptions, populationWithTemplate, switchFieldsCallback } = elements;
    
    if (!templateOptions) return;
    
    // Hide template options by default
    templateOptions.classList.add('hidden');
    
    // Show template options if "Populate with Template" is selected
    if (populationWithTemplate && populationWithTemplate.checked) {
        templateOptions.classList.remove('hidden');
        // Load templates if not already loaded
        if (switchFieldsCallback) {
            await switchFieldsCallback();
        }
    }
}

/**
 * Level 2: Handle template population method change (Manual vs Auto-generate)
 * @param {object} elements - DOM elements {manualFields, llmFields, templateMethodManual, templateMethodLlm, templateType, examplesContainer, addExampleCallback}
 */
export async function handleTemplateMethodChange(elements) {
    const { 
        manualFields, 
        llmFields, 
        templateMethodManual, 
        templateMethodLlm,
        templateType,
        examplesContainer,
        addExampleCallback
    } = elements;
    
    if (!manualFields) return;
    
    // Get the LLM workflow container
    const llmWorkflowContainer = document.getElementById('rag-collection-llm-workflow');
    
    // Hide both method sections first
    manualFields.classList.add('hidden');
    if (llmWorkflowContainer) {
        llmWorkflowContainer.classList.add('hidden');
    }
    
    // Show the selected method fields
    if (templateMethodManual && templateMethodManual.checked) {
        manualFields.classList.remove('hidden');
        // Add initial example if none exist (only for SQL template)
        if (templateType && templateType.value && templateType.value.includes('sql_query') && 
            examplesContainer && examplesContainer.children.length === 0 && addExampleCallback) {
            addExampleCallback();
        }
    } else if (templateMethodLlm && templateMethodLlm.checked) {
        if (llmWorkflowContainer) {
            llmWorkflowContainer.classList.remove('hidden');
        }
    }
}

/**
 * Validate population inputs based on selected method
 * @param {string} method - Population method ('none', 'manual', 'llm')
 * @param {object} inputs - Input values to validate
 * @returns {object} {valid: boolean, error: string}
 */
export function validatePopulationInputs(method, inputs) {
    if (method === 'none') {
        return { valid: true };
    }
    
    if (method === 'manual') {
        if (!inputs.examples || inputs.examples.length === 0) {
            return { valid: false, error: 'Please add at least one example' };
        }
        return { valid: true };
    }
    
    if (method === 'llm') {
        if (!inputs.contextTopic || inputs.contextTopic.trim().length === 0) {
            return { valid: false, error: 'Context topic is required for LLM generation' };
        }
        if (!inputs.numExamples || inputs.numExamples < 1 || inputs.numExamples > 20) {
            return { valid: false, error: 'Number of examples must be between 1 and 20' };
        }
        return { valid: true };
    }
    
    return { valid: false, error: 'Invalid population method' };
}
