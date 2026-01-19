/**
 * eventHandlers.js
 * * This module sets up all the event listeners for the application.
 * It connects user interactions (clicks, form submissions, etc.) to the corresponding application logic.
 */

import * as DOM from './domElements.js';
import { state } from './state.js';
import * as API from './api.js';
import * as UI from './ui.js';
import { handleViewSwitch, toggleSideNav } from './ui.js';
import * as Utils from './utils.js';
import { copyToClipboard, copyTableToClipboard, classifyConfirmation } from './utils.js';
import { renameSession, deleteSession } from './api.js'; // Import the rename/delete API functions
import { startRecognition, stopRecognition, startConfirmationRecognition } from './voice.js';
import {
    handleStartNewSession,
    handleLoadSession,
    handleDeleteSessionClick,
    renameActiveSession
} from './handlers/sessionManagement.js?v=3.2';
import { handleGenieEvent } from './handlers/genieHandler.js?v=3.4';
import { handleConversationAgentEvent } from './handlers/conversationAgentHandler.js?v=1.0';
import {
    // handleCloseConfigModalRequest, // REMOVED
    // handleConfigActionButtonClick, // REMOVED
    finalizeConfiguration,
    handleConfigFormSubmit,
    loadCredentialsAndModels,
    handleProviderChange,
    handleModelChange,
    handleRefreshModelsClick,
    openPromptEditor,
    closePromptEditor,
    saveSystemPromptChanges,
    resetSystemPrompt,
    handleIntensityChange
} from './handlers/configManagement.js';


// --- Stream Processing ---

/**
 * Get human-readable step title for genie coordination events.
 * @deprecated Use getGenieTitle() from harmonized functions instead
 * This function now delegates to the harmonized implementation
 */
function _getGenieStepTitle(eventType, payload) {
    // Delegate to harmonized function (defined below) for consistent terminology
    return getGenieTitle(eventType, payload);
}

/**
 * Get human-readable step title for conversation agent events.
 * @deprecated Use profile-specific harmonized functions instead
 * This function now delegates to the harmonized implementation
 */
function _getConversationAgentStepTitle(eventType, payload) {
    // Route to appropriate harmonized function based on event type
    // conversation_* events → llm_only profile
    if (eventType.startsWith('conversation_') || eventType.startsWith('llm_execution')) {
        return getLlmOnlyTitle(eventType, payload);
    }

    // knowledge_* events → rag_focused profile (uses "Stage" terminology)
    // This is used for rag_focused profiles and knowledge retrieval in other profiles
    if (eventType.startsWith('knowledge_') || eventType === 'rag_llm_step' || eventType === 'tool_result') {
        return getRagFocusedTitle(eventType, payload);
    }

    // Fallback for unknown events
    return eventType;
}

// ============================================================================
// HARMONIZED EVENT TITLE GENERATION (Phase 1: Terminology Harmonization)
// ============================================================================

/**
 * Generate harmonized display title for tool_enabled profile events
 * @param {string} eventType - Backend event type
 * @param {object} payload - Event payload data
 * @returns {string} Harmonized display title
 */
function getToolEnabledTitle(eventType, payload) {
    switch (eventType) {
        case 'phase_start':
            return `Phase ${payload.phase_num}/${payload.total_phases}: ${payload.goal}`;
        case 'phase_end':
            return `Phase ${payload.phase_num}/${payload.total_phases} Completed`;
        case 'system_message':
            if (payload.message?.includes('LLM')) {
                return `Calling LLM: ${payload.purpose || 'Planning'}`;
            }
            return payload.message;
        case 'plan_generated':
            return 'Strategic Plan Generated';
        case 'plan_optimization':
            return 'Optimizing Plan';
        case 'knowledge_retrieval_start': {
            const collections = payload.collections || [];
            return `Searching Knowledge (${collections.length} ${collections.length === 1 ? 'collection' : 'collections'})`;
        }
        case 'knowledge_reranking_start': {
            const collection = payload.collection || 'Unknown';
            return `Reranking Documents (${collection})`;
        }
        case 'knowledge_reranking_complete': {
            const collection = payload.collection || 'Unknown';
            const count = payload.reranked_count || 0;
            return `Reranked ${count} documents (${collection})`;
        }
        case 'knowledge_retrieval_complete': {
            const docCount = payload.document_count || 0;
            const duration = payload.duration_ms || 0;
            return `Knowledge Retrieved (${docCount} ${docCount === 1 ? 'chunk' : 'chunks'} in ${duration}ms)`;
        }
        case 'rag_llm_step': {
            // Token counts are shown in the Tool Execution Result step, so don't duplicate them here
            return `Calling LLM: Knowledge Synthesis`;
        }
        case 'knowledge_search_complete': {
            const collections = payload.collections_searched || 0;
            const docs = payload.documents_retrieved || 0;
            const totalTime = payload.total_time_ms || 0;
            const timeSeconds = (totalTime / 1000).toFixed(1);
            return `Knowledge Search Complete (${collections} ${collections === 1 ? 'collection' : 'collections'}, ${docs} ${docs === 1 ? 'document' : 'documents'} in ${timeSeconds}s)`;
        }
        case 'workaround':
            return 'System Correction';
        case 'error':
            return payload.error_message || 'Error';
        case 'cancelled':
            return 'Planner Execution Stopped';
        case 'session_name_generation_start':
            return 'Generating Session Name';
        case 'session_name_generation_complete':
            return payload.name ? `Session Named: ${payload.name}` : 'Session Name Generated';
        default:
            return eventType;
    }
}

/**
 * Generate harmonized display title for llm_only profile events
 * Uses "Action" terminology instead of "LLM Step"
 * @param {string} eventType - Backend event type
 * @param {object} payload - Event payload data
 * @returns {string} Harmonized display title
 */
function getLlmOnlyTitle(eventType, payload) {
    switch (eventType) {
        case 'conversation_agent_start': {
            const toolCount = payload.available_tools?.length || 0;
            return `Conversation Started (${toolCount} tools available)`;
        }
        case 'conversation_llm_step': {
            // Change from "LLM Step #N" to "Calling LLM: {purpose}"
            const stepName = payload.step_name || 'Decision Making';
            return `Calling LLM: ${stepName}`;
        }
        case 'conversation_tool_invoked':
            return `Executing Tool: ${payload.tool_name || 'tool'}`;
        case 'conversation_tool_completed': {
            const status = payload.success ? 'Completed' : 'Failed';
            const duration = payload.duration_ms ? ` (${(payload.duration_ms / 1000).toFixed(1)}s)` : '';
            return `Tool Completed: ${payload.tool_name || 'Tool'}${duration}`;
        }
        case 'conversation_agent_complete': {
            const toolCount = payload.tools_used?.length || 0;
            const duration = payload.total_duration_ms ? ` in ${(payload.total_duration_ms / 1000).toFixed(1)}s` : '';
            return payload.success
                ? `Conversation Complete (${toolCount} tools executed${duration})`
                : 'Conversation Failed';
        }
        case 'llm_execution':
            return 'Calling LLM: Execution';
        case 'llm_execution_complete': {
            const inputTokens = payload.input_tokens || 0;
            const outputTokens = payload.output_tokens || 0;
            return `LLM Execution Complete (${inputTokens} in / ${outputTokens} out)`;
        }
        case 'session_name_generation_start':
            return 'Generating Session Name';
        case 'session_name_generation_complete':
            return payload.name ? `Session Named: ${payload.name}` : 'Session Name Generated';
        default:
            return eventType;
    }
}

/**
 * Generate harmonized display title for rag_focused profile events
 * Uses "Stage" terminology to reflect pipeline stages
 * @param {string} eventType - Backend event type
 * @param {object} payload - Event payload data
 * @returns {string} Harmonized display title
 */
function getRagFocusedTitle(eventType, payload) {
    switch (eventType) {
        case 'knowledge_retrieval_start': {
            const collections = payload.collections || [];
            return `Stage: Retrieval - Searching Knowledge (${collections.length} ${collections.length === 1 ? 'collection' : 'collections'})`;
        }
        case 'knowledge_reranking_start': {
            const collection = payload.collection || 'Unknown';
            return `Stage: Reranking - Optimizing Results (${collection})`;
        }
        case 'knowledge_reranking_complete': {
            const collection = payload.collection || 'Unknown';
            const count = payload.reranked_count || 0;
            return `Stage: Reranking - ${count} documents processed (${collection})`;
        }
        case 'knowledge_retrieval_complete': {
            const docCount = payload.document_count || 0;
            const duration = payload.duration_ms || 0;
            return `Stage: Retrieval - ${docCount} ${docCount === 1 ? 'chunk' : 'chunks'} retrieved in ${duration}ms`;
        }
        case 'rag_llm_step': {
            // Token counts are shown in the Tool Execution Result step, so don't duplicate them here
            return `Stage: Synthesis - Calling LLM`;
        }
        case 'knowledge_search_complete': {
            const collections = payload.collections_searched || 0;
            const docs = payload.documents_retrieved || 0;
            const totalTime = payload.total_time_ms || 0;
            const timeSeconds = (totalTime / 1000).toFixed(1);
            return `Stage: Complete - ${collections} ${collections === 1 ? 'collection' : 'collections'}, ${docs} ${docs === 1 ? 'document' : 'documents'} in ${timeSeconds}s`;
        }
        case 'knowledge_retrieval': {
            const docCount = payload.document_count || 0;
            return `Knowledge Retrieved (${docCount} chunks)`;
        }
        case 'tool_result': {
            // Tool Execution Result event for RAG synthesis
            return 'Tool Execution Result';
        }
        case 'session_name_generation_start':
            return 'Generating Session Name';
        case 'session_name_generation_complete':
            return payload.name ? `Session Named: ${payload.name}` : 'Session Name Generated';
        default:
            return eventType;
    }
}

/**
 * Generate harmonized display title for genie profile events
 * Uses "Coordination Step" terminology for coordinator steps
 * @param {string} eventType - Backend event type
 * @param {object} payload - Event payload data
 * @returns {string} Harmonized display title
 */
function getGenieTitle(eventType, payload) {
    switch (eventType) {
        case 'genie_start':
            return 'Coordinator Activated';
        case 'genie_routing': {
            const slaveCount = payload.slave_profiles?.length || 0;
            return `Consulting ${slaveCount} expert${slaveCount > 1 ? 's' : ''}`;
        }
        case 'genie_coordination_start':
            return 'Coordinator Started';
        case 'genie_llm_step': {
            const stepName = payload.step_name || 'LLM Processing';
            return `Calling LLM: ${stepName}`;
        }
        case 'genie_routing_decision': {
            const profileCount = payload.selected_profiles?.length || 0;
            return `Routing to ${profileCount} expert${profileCount > 1 ? 's' : ''}`;
        }
        case 'genie_slave_invoked':
            return `Invoking Expert: @${payload.profile_tag || 'PROFILE'}`;
        case 'genie_slave_progress':
            return `Expert @${payload.profile_tag || 'PROFILE'}: ${payload.message || 'Processing'}`;
        case 'genie_slave_completed': {
            const status = payload.success ? 'Completed' : 'Failed';
            const duration = payload.duration_ms ? ` (${(payload.duration_ms / 1000).toFixed(1)}s)` : '';
            return `Expert @${payload.profile_tag || 'PROFILE'} ${status}${duration}`;
        }
        case 'genie_synthesis_start':
            return 'Synthesizing Response';
        case 'genie_coordination_complete':
            return payload.success ? 'Coordinator Complete' : 'Coordinator Failed';
        case 'session_name_generation_start':
            return 'Generating Session Name';
        case 'session_name_generation_complete':
            return payload.name ? `Session Named: ${payload.name}` : 'Session Name Generated';
        default:
            return eventType;
    }
}

/**
 * Main harmonized event title generator - routes to profile-specific functions
 * @param {string} profileType - 'tool_enabled', 'llm_only', 'rag_focused', 'genie'
 * @param {string} eventType - Backend event type (e.g., 'phase_start', 'conversation_tool_invoked')
 * @param {object} payload - Event payload data
 * @returns {string} Harmonized display title
 */
function getHarmonizedEventTitle(profileType, eventType, payload) {
    // Handle universal lifecycle events (Phase 2 - not implemented yet)
    if (eventType === 'execution_start') {
        return `${getProfileDisplayName(profileType)} Execution Started`;
    }
    if (eventType === 'execution_complete') {
        return `${getProfileDisplayName(profileType)} Execution Complete`;
    }
    if (eventType === 'execution_error') {
        return `${getProfileDisplayName(profileType)} Execution Failed: ${payload.error_message || 'Unknown error'}`;
    }
    if (eventType === 'execution_cancelled') {
        return `${getProfileDisplayName(profileType)} Execution Stopped`;
    }

    // Route to profile-specific title functions
    switch (profileType) {
        case 'tool_enabled':
            return getToolEnabledTitle(eventType, payload);
        case 'llm_only':
            return getLlmOnlyTitle(eventType, payload);
        case 'rag_focused':
            return getRagFocusedTitle(eventType, payload);
        case 'genie':
            return getGenieTitle(eventType, payload);
        default:
            // Fallback to old functions if profile type unknown
            return eventType;
    }
}

/**
 * Helper function to get human-readable profile display name
 * @param {string} profileType - Profile type identifier
 * @returns {string} Display name
 */
function getProfileDisplayName(profileType) {
    const names = {
        'tool_enabled': 'Planner',
        'llm_only': 'Conversation',
        'rag_focused': 'Knowledge',
        'genie': 'Coordinator'
    };
    return names[profileType] || 'Agent';
}

// ============================================================================
// END: Harmonized Event Title Generation
// ============================================================================

async function processStream(responseBody) {
    const reader = responseBody.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const messages = buffer.split('\n\n');
        buffer = messages.pop();

        for (const message of messages) {
            if (!message) continue;

            let eventName = 'message';
            let dataLine = '';

            const lines = message.split('\n');
            for(const line of lines) {
                if (line.startsWith('data:')) {
                    dataLine = line.substring(5).trim();
                } else if (line.startsWith('event:')) {
                    eventName = line.substring(6).trim();
                }
            }

            if (dataLine) {
                try {
                    const eventData = JSON.parse(dataLine);

                    if (eventData.task_id && state.currentTaskId !== eventData.task_id) {
                        state.currentTaskId = eventData.task_id;
                        UI.updateTaskIdDisplay(eventData.task_id);
                    }

                    // --- Event Handling Logic ---
                    if (eventName === 'status_indicator_update') {
                        const { target, state: statusState } = eventData;
                        let dot;
                        if (target === 'db') dot = DOM.mcpStatusDot;
                        else if (target === 'llm') dot = DOM.llmStatusDot;
                        // Handle LLM thinking indicator separately
                        if (target === 'llm') UI.setThinkingIndicator(statusState === 'busy');

                        if (dot) {
                            if (statusState === 'busy') {
                                dot.classList.replace('idle', 'busy') || dot.classList.replace('connected', 'busy');
                                dot.classList.add('pulsing');
                            } else {
                                dot.classList.remove('pulsing');
                                dot.classList.replace('busy', target === 'db' ? 'connected' : 'idle');
                            }
                        }
                    } else if (eventName === 'context_state_update') {
                         // Currently no specific UI update needed, but could add visual feedback here
                    } else if (eventName === 'token_update') {
                        UI.updateTokenDisplay(eventData);
                        if (eventData.call_id && state.currentProvider !== 'Amazon') {
                            const metricsEl = document.querySelector(`.per-call-metrics[data-call-id="${eventData.call_id}"]`);
                            if (metricsEl) {
                                metricsEl.innerHTML = `(LLM Call: ${eventData.statement_input.toLocaleString()} in / ${eventData.statement_output.toLocaleString()} out)`;
                                metricsEl.classList.remove('hidden');
                            }
                        }
                    } else if (eventName === 'notification') {
                        // Handle notifications sent during execution stream
                        console.log('[notification] Received during execution:', eventData.type, eventData);
                        if (eventData.type === 'profile_override_failed') {
                            const { override_profile_name, override_profile_tag, default_profile_tag, error_message } = eventData.payload;
                            // Show banner - import the function from notifications.js
                            const banner = document.getElementById('profile-override-warning-banner');
                            const message = document.getElementById('profile-override-warning-message');
                            if (banner && message) {
                                const displayMessage = `Profile @${override_profile_tag}: Missing credentials. Using @${default_profile_tag} instead.`;
                                message.textContent = displayMessage;
                                banner.classList.remove('hidden');
                                
                                // Auto-dismiss after 5 seconds
                                setTimeout(() => {
                                    banner.classList.add('hidden');
                                }, 5000);
                                
                                // Manual dismiss button still works
                                const dismissBtn = document.getElementById('dismiss-profile-warning');
                                if (dismissBtn) {
                                    dismissBtn.onclick = () => banner.classList.add('hidden');
                                }
                            }
                        } else if (eventData.type === 'session_model_update') {
                            // Handle session metadata updates during execution
                            const { session_id, models_used, profile_tags_used, last_updated, provider, model, name } = eventData.payload;
                            console.log('[session_model_update] Received during execution:', {
                                session_id,
                                models_used,
                                profile_tags_used,
                                provider,
                                model,
                                current_session: state.currentSessionId,
                                is_current: session_id === state.currentSessionId
                            });
                            UI.updateSessionModels(session_id, models_used, profile_tags_used);
                            if (session_id === state.currentSessionId) {
                                console.log('[session_model_update] Updating Live Status with:', provider, model);
                                state.currentProvider = provider;
                                state.currentModel = model;
                                UI.updateStatusPromptName();
                            } else {
                                console.log('[session_model_update] Not updating Live Status - wrong session');
                            }
                        } else if (eventData.type === 'conversation_agent_start' ||
                                   eventData.type === 'conversation_llm_step' ||
                                   eventData.type === 'conversation_tool_invoked' ||
                                   eventData.type === 'conversation_tool_completed' ||
                                   eventData.type === 'conversation_agent_complete') {
                            // Handle conversation agent events during execution stream
                            const payload = eventData.payload || {};
                            // Only handle events for current session
                            if (payload.session_id && payload.session_id !== state.currentSessionId) {
                                console.log('[ConversationAgent] Ignoring event for different session:', payload.session_id);
                            } else {
                                // IMPORTANT: Update status window BEFORE calling handler for completion event
                                // because handler sets isConversationAgentActive=false which would trigger a reset
                                const stepTitle = _getConversationAgentStepTitle(eventData.type, payload);
                                UI.updateStatusWindow({
                                    step: stepTitle,
                                    details: payload,
                                    type: eventData.type
                                }, eventData.type === 'conversation_agent_complete', 'conversation_agent');
                                // Delegate to conversation agent handler for state tracking (after UI update)
                                handleConversationAgentEvent(eventData.type, payload);
                            }
                        } else if (eventData.type === 'llm_execution' ||
                                   eventData.type === 'llm_execution_complete' ||
                                   eventData.type === 'knowledge_retrieval' ||
                                   eventData.type === 'knowledge_retrieval_start' ||
                                   eventData.type === 'knowledge_reranking_start' ||
                                   eventData.type === 'knowledge_reranking_complete' ||
                                   eventData.type === 'knowledge_retrieval_complete' ||
                                   eventData.type === 'rag_llm_step') {
                            // Handle all LLM execution and knowledge retrieval events during execution
                            const payload = eventData.payload || {};

                            // HARMONIZE rag_llm_step title
                            const stepTitle = eventData.type === 'rag_llm_step'
                                ? getRagFocusedTitle('rag_llm_step', payload)
                                : _getConversationAgentStepTitle(eventData.type, payload);

                            console.log(`[${eventData.type}] Received during execution:`, payload);

                            // Update knowledge indicator for completion events
                            if (eventData.type === 'knowledge_retrieval_complete' || eventData.type === 'knowledge_retrieval') {
                                const collections = payload.collections || [];
                                const documentCount = payload.document_count || 0;
                                UI.blinkKnowledgeDot();
                                UI.updateKnowledgeIndicator(collections, documentCount);
                                // Store the knowledge event for potential replay
                                state.pendingKnowledgeRetrievalEvent = payload;
                            }

                            // Always update status window for these events
                            // For conversation_with_tools, these arrive BEFORE conversation_agent_start
                            // so we render them directly without checking isConversationAgentActive
                            UI.updateStatusWindow({
                                step: stepTitle,
                                details: payload,
                                type: eventData.type
                            }, false, 'knowledge_retrieval');  // Use existing knowledge_retrieval rendering for all
                        }
                    } else if (eventName === 'rag_retrieval') {
                        state.lastRagCaseData = eventData; // Store the full RAG case data
                        UI.blinkRagDot();
                    } else if (eventName === 'llm_execution') {
                        // LLM execution event for llm_only profile (emitted with specific event name like genie)
                        const { details, step, type } = eventData;
                        console.log(`[${eventName}] Received:`, details);

                        UI.updateStatusWindow({
                            step: getLlmOnlyTitle(type || eventName, details || {}),
                            details: details || {},
                            type: type || eventName
                        }, false, 'knowledge_retrieval');  // Reuse knowledge_retrieval rendering
                    } else if (eventName === 'llm_execution_complete') {
                        // LLM execution complete event (shows token counts like RAG's rag_llm_step)
                        const { details, step, type } = eventData;
                        console.log(`[${eventName}] Received:`, details);

                        UI.updateStatusWindow({
                            step: step || _getConversationAgentStepTitle('llm_execution_complete', details),
                            details: details || {},
                            type: type || eventName
                        }, false, 'knowledge_retrieval');  // Reuse knowledge_retrieval rendering
                    } else if (eventName === 'knowledge_retrieval') {
                        // Knowledge retrieval event (emitted with specific event name like genie)
                        const { details, step, type } = eventData;
                        console.log(`[${eventName}] Received:`, details);

                        // Update knowledge indicator if we have collection info
                        if (details && details.collections) {
                            const collections = details.collections || [];
                            const documentCount = details.document_count || 0;
                            UI.blinkKnowledgeDot();
                            UI.updateKnowledgeIndicator(collections, documentCount);
                        }

                        UI.updateStatusWindow({
                            step: step || 'Knowledge Retrieved',
                            details: details || {},
                            type: type || eventName
                        }, false, 'knowledge_retrieval');  // Reuse knowledge_retrieval rendering
                    } else if (eventName === 'session_name_generation_start' ||
                               eventName === 'session_name_generation_complete') {
                        // Route session name generation events to status window with proper rendering
                        const { details, step, type } = eventData;

                        console.log(`[${eventName}] Received:`, details);

                        // Update status window with formatted rendering (existing renderers in ui.js will be called)
                        UI.updateStatusWindow({
                            step: step || (eventName === 'session_name_generation_start'
                                            ? 'Generating Session Name'
                                            : 'Session Name Generated'),
                            details: details || {},
                            type: type || eventName
                        }, eventName === 'session_name_generation_complete', 'session_name');
                    } else if (eventName === 'session_name_update') {
                        const { session_id, newName } = eventData;
                        UI.updateSessionListItemName(session_id, newName);
                    } else if (eventName === 'session_model_update') {
                        const { session_id, models_used, profile_tags_used, last_updated } = eventData;
                        UI.updateSessionModels(session_id, models_used, profile_tags_used);
                        UI.updateSessionTimestamp(session_id, last_updated);
                    } else if (eventName === 'request_user_input') {
                        UI.updateStatusWindow({ step: "Action Required", details: "Waiting for user to correct parameters.", type: 'workaround' });
                        UI.setExecutionState(false);
                        openCorrectionModal(eventData.details);
                    } else if (eventName === 'session_update') {
                        // Logic to potentially update session list if needed
                    } else if (eventName === 'llm_thought') {
                        UI.updateStatusWindow({ step: "Parser has generated the final answer", ...eventData });
                    } else if (eventName === 'prompt_selected') {
                        UI.updateStatusWindow(eventData);
                        if (eventData.prompt_name) UI.highlightResource(eventData.prompt_name, 'prompts');
                    } else if (eventName === 'tool_result' || eventName === 'tool_error' || eventName === 'tool_intent') {
                        UI.updateStatusWindow(eventData);
                        if (eventData.tool_name) {
                            const toolType = eventData.tool_name.startsWith('generate_') ? 'charts' : 'tools';
                            UI.highlightResource(eventData.tool_name, toolType);
                        }
                    // --- Genie Coordination Events ---
                    } else if (eventName === 'genie_start' || eventName === 'genie_routing' ||
                               eventName === 'genie_coordination_start' || eventName === 'genie_llm_step' ||
                               eventName === 'genie_routing_decision' ||
                               eventName === 'genie_slave_invoked' || eventName === 'genie_slave_progress' ||
                               eventName === 'genie_slave_completed' || eventName === 'genie_synthesis_start' ||
                               eventName === 'genie_coordination_complete') {
                        // Handle genie coordination events - delegate to genieHandler
                        console.log('[SSE] Genie event received:', eventName, eventData);
                        handleGenieEvent(eventName, eventData);
                        // Also update status window
                        const genieStepTitle = _getGenieStepTitle(eventName, eventData);
                        UI.updateStatusWindow({
                            step: genieStepTitle,
                            details: eventData,
                            type: eventName
                        }, eventName === 'genie_coordination_complete', 'genie');
                    } else if (eventName === 'cancelled') {
                        const lastStep = document.getElementById(`status-step-${state.currentStatusId}`);
                        if (lastStep) {
                            lastStep.classList.remove('active');
                            lastStep.classList.add('cancelled');
                        }
                        UI.updateStatusWindow({ step: "Execution Stopped", details: eventData.message || "Process cancelled by user.", type: 'cancelled'}, true);

                        // Create a cancelled message in the chat so the turn badge is clickable
                        if (eventData.turn_id) {
                            // Only add if this is for the current session
                            if (!eventData.session_id || eventData.session_id === state.currentSessionId) {
                                const cancelledMessage = `<span class="cancelled-tag">CANCELLED</span> Execution was stopped by user.`;
                                UI.addMessage('assistant', cancelledMessage, eventData.turn_id, true);
                            }
                        }

                        UI.setExecutionState(false);
                    } else if (eventName === 'final_answer') {
                        // Check if this event is for the current session (prevents cross-session message leakage during Genie execution)
                        if (eventData.session_id && eventData.session_id !== state.currentSessionId) {
                            console.log('[final_answer] Ignoring event for different session:', eventData.session_id, 'current:', state.currentSessionId);
                            // Don't add message to UI, but still reset execution state
                            UI.setExecutionState(false);
                            continue; // Skip to next event
                        }
                        // All new messages are valid by default, so we don't need to pass `true`
                        // Pass is_session_primer flag for Primer badge display
                        UI.addMessage('assistant', eventData.final_answer, eventData.turn_id, true, null, null, eventData.is_session_primer || false);
                        UI.updateStatusWindow({ step: "Finished", details: "Response sent to chat." }, true);
                        UI.setExecutionState(false);

                        // Auto-focus input field so user can immediately type next question
                        if (DOM.userInput) {
                            DOM.userInput.focus();
                        }

                        if (eventData.source === 'voice' && eventData.tts_payload) {
                           const { direct_answer, key_observations } = eventData.tts_payload;

                            if (direct_answer) {
                                const directAnswerAudio = await API.synthesizeText(direct_answer);
                                if (directAnswerAudio) {
                                    const audioUrl = URL.createObjectURL(directAnswerAudio);
                                    const audio = new Audio(audioUrl);
                                    await new Promise(resolve => {
                                        audio.onended = resolve;
                                        audio.onerror = resolve;
                                        audio.play().catch(resolve);
                                    });
                                }
                            }

                            if (key_observations) {
                                switch (state.keyObservationsMode) {
                                    case 'autoplay-off':
                                        state.ttsState = 'AWAITING_OBSERVATION_CONFIRMATION';
                                        state.ttsObservationBuffer = key_observations;
                                        UI.updateVoiceModeUI();

                                        const confirmationQuestion = "Do you want to hear the key observations?";
                                        const questionAudio = await API.synthesizeText(confirmationQuestion);

                                        if (questionAudio) {
                                            const questionUrl = URL.createObjectURL(questionAudio);
                                            const questionPlayer = new Audio(questionUrl);
                                            await new Promise(resolve => {
                                                questionPlayer.onended = resolve;
                                                questionPlayer.onerror = resolve;
                                                questionPlayer.play().catch(resolve);
                                            });
                                            startConfirmationRecognition(handleObservationConfirmation);
                                        } else {
                                            state.ttsState = 'IDLE';
                                            UI.updateVoiceModeUI();
                                        }
                                        break;

                                    case 'autoplay-on':
                                        const observationAudio = await API.synthesizeText(key_observations);
                                        if (observationAudio) {
                                            const audioUrl = URL.createObjectURL(observationAudio);
                                            const audio = new Audio(audioUrl);
                                            await new Promise(resolve => {
                                                audio.onended = resolve;
                                                audio.onerror = resolve;
                                                audio.play().catch(resolve);
                                            });
                                        }

                                    case 'off':
                                        if (state.isVoiceModeLocked) {
                                            setTimeout(() => startRecognition(), 100);
                                        }
                                        break;
                                }
                            } else if (state.isVoiceModeLocked) {
                                setTimeout(() => startRecognition(), 100);
                            }
                        }


                    } else if (eventName === 'error') {
                        // Include turn_id so badge is created and clickable
                        const errorTurnId = eventData.turn_id || null;
                        // Only add if this is for the current session
                        if (!eventData.session_id || eventData.session_id === state.currentSessionId) {
                            const errorMessage = `<span class="error-tag">ERROR</span> ${eventData.error || 'Unknown error'}`;
                            UI.addMessage('assistant', errorMessage, errorTurnId, true);
                        }
                        UI.updateStatusWindow({ step: "Error", details: eventData.details || eventData.error, type: 'error' }, true);
                        UI.setExecutionState(false);
                    } else if (eventName === 'rest_task_update') {
                        const { task_id, session_id, event } = eventData.payload; // eslint-disable-line no-unused-vars
                        UI.updateStatusWindow(event, false, 'rest', task_id);
                    } else if (eventName === 'task_start') { // Handle the new task_start event
                        UI.updateTaskIdDisplay(eventData.task_id);
                    } else if (eventData.type === 'system_message' && eventData.details?.summary === 'Synthesizing answer from retrieved knowledge') {
                        // SKIP this event - it's redundant and fires BEFORE the LLM call (no data)
                        // The actual rag_llm_step event will follow with correct token/model data
                        console.log('[RAG Synthesis] Skipping redundant system_message preview event - waiting for rag_llm_step with data');
                        // Don't call updateStatusWindow - skip this event entirely
                    } else {
                        UI.updateStatusWindow(eventData);
                    }
                } catch (e) {
                    console.error("Error parsing SSE data line:", dataLine, e);
                }
            }
        }
    }
    if (buffer.trim()) {
    }
}


async function handleObservationConfirmation(transcribedText) {
    const classification = Utils.classifyConfirmation(transcribedText);

    if (classification === 'yes' && state.ttsObservationBuffer) {
        const observationAudio = await API.synthesizeText(state.ttsObservationBuffer);
        if (observationAudio) {
            const audioUrl = URL.createObjectURL(observationAudio);
            const audio = new Audio(audioUrl);
            await new Promise(resolve => {
                audio.onended = resolve;
                audio.play();
            });
        }
    }
    if (state.isVoiceModeLocked) {
        setTimeout(() => startRecognition(), 100);
    }
}


export async function handleStreamRequest(endpoint, body) {
    if (body.message) {
        // Only add user message if it's NOT a replay initiated by the replay button
        if (!body.is_replay) {
            // Extract profile tag - use explicit @tag override if present, otherwise use default profile
            let profileTag = null;
            if (window.activeTagPrefix) {
                profileTag = window.activeTagPrefix.replace('@', '').trim();
            } else if (window.configState?.defaultProfileId && window.configState?.profiles) {
                const defaultProfile = window.configState.profiles.find(p => p.id === window.configState.defaultProfileId);
                profileTag = defaultProfile?.tag || null;
            }
            UI.addMessage('user', body.message, null, true, 'text', profileTag, body.is_session_primer || false);
        } else {
        }
    } else {
        // Extract profile tag - use explicit @tag override if present, otherwise use default profile
        let profileTag = null;
        if (window.activeTagPrefix) {
            profileTag = window.activeTagPrefix.replace('@', '').trim();
        } else if (window.configState?.defaultProfileId && window.configState?.profiles) {
            const defaultProfile = window.configState.profiles.find(p => p.id === window.configState.defaultProfileId);
            profileTag = defaultProfile?.tag || null;
        }
        UI.addMessage('user', `Executing prompt: ${body.prompt_name}`, null, true, 'text', profileTag);
    }
    DOM.userInput.value = '';
    UI.setExecutionState(true);
    UI.resetStatusWindowForNewTask();

    // This call remains to set the prompt name specifically for the new execution
    UI.updateStatusPromptName();

    const useLastTurnMode = state.isLastTurnModeLocked || state.isTempLastTurnMode;
    body.disabled_history = useLastTurnMode || body.is_replay; // Disable if last turn mode OR replay


    DOM.contextStatusDot.classList.remove('history-disabled-preview');

    try {
        const response = await API.startStream(endpoint, body);
        if (response && response.ok && response.body) {
            await processStream(response.body);
        }
    } catch (error) {
        UI.addMessage('assistant', `Sorry, a stream processing error occurred: ${error.message}`);
        UI.updateStatusWindow({ step: "Error", details: error.stack, type: 'error' }, true);
    } finally {
        UI.setExecutionState(false);
        UI.updateHintAndIndicatorState();
    }
}


// --- Event Handlers ---

export async function handleChatSubmit(e, source = 'text') {
    e.preventDefault();
    
    // Get the active tag prefix from main.js if badge is showing
    const activeTagPrefix = window.activeTagPrefix || '';
    const rawMessage = DOM.userInput.value.trim();
    
    // Reconstruct full message with tag if badge was active
    const message = activeTagPrefix ? activeTagPrefix + rawMessage : rawMessage;
    
    if (!message || !state.currentSessionId) return;
    
    // Check for @TAG profile override
    let profileOverrideId = null;
    let cleanedMessage = message;
    const tagMatch = message.match(/^@(\w+)\s+(.+)/);
    
    if (tagMatch && window.configState?.profiles) {
        const tag = tagMatch[1].toUpperCase();
        console.log('🔍 Tag detected:', tag);
        const overrideProfile = window.configState.profiles.find(p => p.tag === tag);
        if (overrideProfile) {
            profileOverrideId = overrideProfile.id;
            cleanedMessage = tagMatch[2]; // Strip @TAG from message
            console.log(`✅ Profile override found: ${overrideProfile.name} (${profileOverrideId})`);
            console.log(`📝 Cleaned message: "${cleanedMessage}"`);
            // Store the active profile override for autocomplete to use
            window.activeProfileOverrideId = profileOverrideId;
        } else {
            console.log(`❌ No profile found with tag: ${tag}`);
        }
    } else {
        console.log('ℹ️  No @TAG detected or profiles not loaded');
    }
    
    handleStreamRequest('/ask_stream', {
        message: cleanedMessage,
        session_id: state.currentSessionId,
        source: source,
        profile_override_id: profileOverrideId
        // is_replay is implicitly false here
    });
}

async function handleStopExecutionClick() {
    if (!state.currentSessionId) {
        return;
    }

    // CRITICAL: Keep button enabled but show visual feedback
    if(DOM.stopExecutionButton) {
        const originalText = DOM.stopExecutionButton.textContent;
        DOM.stopExecutionButton.textContent = 'Stopping...';
        DOM.stopExecutionButton.classList.add('opacity-75', 'cursor-wait');

        // Store original text for restoration
        DOM.stopExecutionButton.dataset.originalText = originalText;
    }

    // Set a failsafe timeout - button MUST re-enable after 10 seconds
    const failsafeTimer = setTimeout(() => {
        console.warn('[FAILSAFE] Stop button timeout - forcing UI reset');
        forceResetExecutionState();
    }, 10000);

    try {
        const result = await API.cancelStream(state.currentSessionId);
        console.log('[StopButton] Cancellation API response:', result);

        // Success - wait for backend to emit 'cancelled' event
        // But also set a backup timer in case event never arrives
        setTimeout(() => {
            if (DOM.stopExecutionButton && !DOM.stopExecutionButton.classList.contains('hidden')) {
                console.warn('[FAILSAFE] Backend cancelled event never arrived - forcing reset');
                forceResetExecutionState();
            }
        }, 5000);

    } catch (error) {
        console.error("Error sending cancellation request:", error);
        UI.addMessage('assistant', `Error trying to stop execution: ${error.message}`);
        // Force reset immediately on error
        forceResetExecutionState();
    } finally {
        clearTimeout(failsafeTimer);
    }
}

/**
 * Force reset execution state - ensures UI is always recoverable.
 * This is a failsafe function that guarantees the stop button never stays disabled.
 */
function forceResetExecutionState() {
    console.log('[FORCE RESET] Resetting execution state');

    // Reset button state
    if(DOM.stopExecutionButton) {
        const originalText = DOM.stopExecutionButton.dataset.originalText || 'Stop';
        DOM.stopExecutionButton.textContent = originalText;
        DOM.stopExecutionButton.classList.remove('opacity-75', 'cursor-wait');
        DOM.stopExecutionButton.disabled = false;
        DOM.stopExecutionButton.classList.add('hidden');
        delete DOM.stopExecutionButton.dataset.originalText;
    }

    // Reset execution state
    UI.setExecutionState(false);

    // Reset status window with error message
    UI.updateStatusWindow({
        step: "Execution Stopped (Forced)",
        details: "Process forcibly terminated after timeout.",
        type: 'error'
    }, true);
}

/**
 * Handles clicks on the "Reload Plan" button or user avatar. Fetches and displays the full turn details.
 * @param {HTMLElement} element - The element that was clicked (button or avatar div).
 */
async function handleReloadPlanClick(element) {
    const turnId = element.dataset.turnId; // Get turnId from data attribute
    const sessionId = state.currentSessionId;
    if (!turnId || !sessionId) {
        console.error("Missing turnId or sessionId for reloading plan details.");
        return;
    }

    // Indicate loading in the status window
    DOM.statusWindowContent.innerHTML = `<p class="p-4 text-gray-400">Loading details for Turn ${turnId}...</p>`;
    // Scroll to top of status window
    DOM.statusWindowContent.scrollTop = 0;
    // Ensure status panel is open
    const statusCheckbox = document.getElementById('toggle-status-checkbox');
    if (statusCheckbox && !statusCheckbox.checked) {
        statusCheckbox.checked = true;
        // Manually trigger the toggle logic if checkbox change doesn't automatically do it
        const event = new Event('change');
        statusCheckbox.dispatchEvent(event);
    }


    try {
        // Fetch the full turn details (plan + trace)
        const turnData = await API.fetchTurnDetails(sessionId, turnId);

        console.log('[ReloadPlan] Turn data received:', turnData);
        console.log('[ReloadPlan] System events in turn data:', turnData?.system_events);

        // Handle cancelled or error turns FIRST (before profile-specific handling)
        // These turns have partial data and need special display regardless of profile type
        if (turnData && (turnData.status === 'cancelled' || turnData.status === 'error')) {
            DOM.statusWindowContent.innerHTML = '';

            // Update status title
            const statusTitle = DOM.statusTitle || document.getElementById('status-title');
            if (statusTitle) {
                const statusLabel = turnData.status === 'cancelled' ? 'Cancelled' : 'Error';
                statusTitle.textContent = `${statusLabel} Turn ${turnId} (Partial)`;
            }

            // Create header with status indicator
            const headerEl = document.createElement('div');
            headerEl.className = `p-4 status-step ${turnData.status}`;

            const statusIcon = turnData.status === 'cancelled' ?
                '<svg class="w-5 h-5 text-yellow-400 inline mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>' :
                '<svg class="w-5 h-5 text-red-400 inline mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';

            const title = turnData.status === 'cancelled' ? 'Execution Cancelled' : 'Execution Error';

            headerEl.innerHTML = `
                <h4 class="font-bold text-sm text-white mb-2">${statusIcon}${title}</h4>
                <p class="text-xs text-gray-300 mb-2">${turnData.error_message || 'Turn did not complete.'}</p>
                ${turnData.error_details ? `<p class="text-xs text-gray-500 mt-1"><em>${turnData.error_details}</em></p>` : ''}
                <div class="mt-3 p-3 bg-gray-800/30 rounded border border-white/10">
                    <p class="text-xs text-gray-400"><strong>Provider:</strong> ${turnData.provider || 'N/A'}</p>
                    <p class="text-xs text-gray-400"><strong>Model:</strong> ${turnData.model || 'N/A'}</p>
                    <p class="text-xs text-gray-400"><strong>Input Tokens:</strong> ${(turnData.turn_input_tokens || 0).toLocaleString()}</p>
                    <p class="text-xs text-gray-400"><strong>Output Tokens:</strong> ${(turnData.turn_output_tokens || 0).toLocaleString()}</p>
                </div>
            `;
            DOM.statusWindowContent.appendChild(headerEl);

            // Render the plan and partial execution trace using the standard historical trace renderer
            // This properly shows Plan Steps and execution progress
            if (turnData.original_plan || turnData.execution_trace) {
                UI.renderHistoricalTrace(
                    turnData.original_plan || [],
                    turnData.execution_trace || [],
                    turnId,
                    turnData.user_query,
                    turnData.knowledge_retrieval_event || null,
                    {
                        turn_input_tokens: turnData.turn_input_tokens || 0,
                        turn_output_tokens: turnData.turn_output_tokens || 0
                    },
                    turnData.system_events || []  // Pass system events (session name generation, etc.)
                );
            }

            // Update token display with partial data (isHistorical = true for plan reloads)
            UI.updateTokenDisplay({
                statement_input: turnData.turn_input_tokens || 0,
                statement_output: turnData.turn_output_tokens || 0,
                turn_input: turnData.turn_input_tokens || 0,
                turn_output: turnData.turn_output_tokens || 0,
                total_input: turnData.session_input_tokens || 0,
                total_output: turnData.session_output_tokens || 0
            }, true);

            // Hide replay buttons for partial turns
            if (DOM.headerReplayPlannedButton) DOM.headerReplayPlannedButton.classList.add('hidden');
            if (DOM.headerReplayOptimizedButton) DOM.headerReplayOptimizedButton.classList.add('hidden');

            return;
        }

        // Check if this is a genie profile (coordination profile)
        if (turnData && (turnData.genie_coordination || turnData.profile_type === 'genie')) {
            DOM.statusWindowContent.innerHTML = '';

            // If we have detailed genie_events, replay them for full UI experience
            const genieEvents = turnData.genie_events || [];
            if (genieEvents.length > 0) {
                // Update status title to indicate historical view
                const statusTitle = DOM.statusTitle || document.getElementById('status-title');
                if (statusTitle) {
                    statusTitle.textContent = `Genie Coordination - Turn ${turnId}`;
                }

                // Replay each event using the same renderer as live execution
                genieEvents.forEach((event, index) => {
                    const isFinal = index === genieEvents.length - 1;
                    // Check if payload is already a complete event (has 'step' field)
                    // or if it's just details that need to be wrapped
                    let eventData;
                    if (event.payload && typeof event.payload === 'object' && 'step' in event.payload) {
                        // Payload is complete event_dict (session name events)
                        eventData = event.payload;
                    } else {
                        // Payload is just details (coordinator events) - reconstruct eventData
                        eventData = {
                            step: _getGenieStepTitle(event.type, event.payload),
                            details: event.payload,
                            type: event.type
                        };
                    }
                    UI.renderGenieStepForReload(eventData, DOM.statusWindowContent, isFinal);
                });

                // Update token counts from historical turn data (isHistorical = true)
                const inputTokens = turnData.turn_input_tokens || turnData.input_tokens || 0;
                const outputTokens = turnData.turn_output_tokens || turnData.output_tokens || 0;
                UI.updateTokenDisplay({
                    statement_input: inputTokens,
                    statement_output: outputTokens,
                    turn_input: inputTokens,
                    turn_output: outputTokens,
                    total_input: turnData.session_input_tokens || 0,
                    total_output: turnData.session_output_tokens || 0
                }, true);
            } else {
                // Fallback: Show simple summary if no detailed events available
                const genieInfoEl = document.createElement('div');
                genieInfoEl.className = 'p-4 status-step info';

                const toolsUsed = turnData.tools_used || [];
                const profilesConsulted = toolsUsed.length;
                const success = turnData.success !== false;
                const profileTags = toolsUsed.map(t => t.replace('invoke_', '')).join(', ');

                genieInfoEl.innerHTML = `
                    <h4 class="font-bold text-sm text-white mb-2">🔮 Genie Coordination</h4>
                    <p class="text-xs text-gray-300 mb-2">${success ? 'Coordination completed successfully.' : 'Coordination encountered errors.'}</p>
                    <div class="mt-3 p-3 bg-gray-800/30 rounded border border-white/10">
                        <p class="text-xs text-gray-400"><strong>Provider:</strong> ${turnData.provider || 'N/A'}</p>
                        <p class="text-xs text-gray-400"><strong>Model:</strong> ${turnData.model || 'N/A'}</p>
                        <p class="text-xs text-gray-400"><strong>Profiles Consulted:</strong> ${profilesConsulted}</p>
                        ${profileTags ? `<p class="text-xs text-gray-400"><strong>Profiles:</strong> @${profileTags.replace(/, /g, ', @')}</p>` : ''}
                        <p class="text-xs text-gray-400 mt-2"><strong>Note:</strong> Detailed event history not available for this turn.</p>
                    </div>
                `;
                DOM.statusWindowContent.appendChild(genieInfoEl);
            }

            // Hide replay buttons for genie profiles (no plan to replay)
            if (DOM.headerReplayPlannedButton) {
                DOM.headerReplayPlannedButton.classList.add('hidden');
            }
            if (DOM.headerReplayOptimizedButton) {
                DOM.headerReplayOptimizedButton.classList.add('hidden');
            }

            return; // Exit early
        }

        // Check if this is a conversation_with_tools profile (LangChain agent)
        if (turnData && turnData.profile_type === 'conversation_with_tools') {
            DOM.statusWindowContent.innerHTML = '';

            // If we have detailed conversation_agent_events, replay them for full UI experience
            const agentEvents = turnData.conversation_agent_events || [];

            // Also check for knowledge retrieval event (renders first)
            if (turnData.knowledge_retrieval_event) {
                // Use knowledge_retrieval_complete type to show duration if available
                const eventType = turnData.knowledge_retrieval_event.duration_ms ? 'knowledge_retrieval_complete' : 'knowledge_retrieval';
                const knowledgeEventData = {
                    step: _getConversationAgentStepTitle(eventType, turnData.knowledge_retrieval_event),
                    details: turnData.knowledge_retrieval_event,
                    type: eventType
                };
                UI.renderConversationAgentStepForReload(knowledgeEventData, DOM.statusWindowContent, false);
            }

            if (agentEvents.length > 0) {
                // Update status title to indicate historical view
                const statusTitle = DOM.statusTitle || document.getElementById('status-title');
                if (statusTitle) {
                    statusTitle.textContent = `Conversation Agent - Turn ${turnId}`;
                }

                // Replay each event using the same renderer as live execution
                agentEvents.forEach((event, index) => {
                    const isFinal = index === agentEvents.length - 1;
                    // Check if payload is already a complete event (has 'step' field)
                    // or if it's just details that need to be wrapped
                    let eventData;
                    if (event.payload && typeof event.payload === 'object' && 'step' in event.payload) {
                        // Payload is complete event_dict (session name events)
                        eventData = event.payload;
                    } else {
                        // Payload is just details (agent events) - reconstruct eventData
                        eventData = {
                            step: _getConversationAgentStepTitle(event.type, event.payload),
                            details: event.payload,
                            type: event.type
                        };
                    }
                    UI.renderConversationAgentStepForReload(eventData, DOM.statusWindowContent, isFinal);
                });

                // Update token counts from historical turn data (isHistorical = true)
                const inputTokens = turnData.turn_input_tokens || turnData.input_tokens || 0;
                const outputTokens = turnData.turn_output_tokens || turnData.output_tokens || 0;
                UI.updateTokenDisplay({
                    statement_input: inputTokens,
                    statement_output: outputTokens,
                    turn_input: inputTokens,
                    turn_output: outputTokens,
                    total_input: turnData.session_input_tokens || 0,
                    total_output: turnData.session_output_tokens || 0
                }, true);
            } else {
                // Fallback: Show simple summary if no detailed events available
                const agentInfoEl = document.createElement('div');
                agentInfoEl.className = 'p-4 status-step info';

                const toolsUsed = turnData.tools_used || [];
                const toolCount = toolsUsed.length;
                const success = turnData.status !== 'failed';

                agentInfoEl.innerHTML = `
                    <h4 class="font-bold text-sm text-white mb-2">Conversation Agent</h4>
                    <p class="text-xs text-gray-300 mb-2">${success ? 'Agent execution completed successfully.' : 'Agent execution encountered errors.'}</p>
                    <div class="mt-3 p-3 bg-gray-800/30 rounded border border-white/10">
                        <p class="text-xs text-gray-400"><strong>Provider:</strong> ${turnData.provider || 'N/A'}</p>
                        <p class="text-xs text-gray-400"><strong>Model:</strong> ${turnData.model || 'N/A'}</p>
                        <p class="text-xs text-gray-400"><strong>Tools Used:</strong> ${toolCount}</p>
                        ${toolsUsed.length > 0 ? `<p class="text-xs text-gray-400"><strong>Tools:</strong> ${toolsUsed.join(', ')}</p>` : ''}
                        ${turnData.knowledge_accessed ? `<p class="text-xs text-gray-400"><strong>Knowledge:</strong> ${turnData.knowledge_accessed.length} collection(s) accessed</p>` : ''}
                        <p class="text-xs text-gray-400 mt-2"><strong>Note:</strong> Detailed event history not available for this turn.</p>
                    </div>
                `;
                DOM.statusWindowContent.appendChild(agentInfoEl);
            }

            // Hide replay buttons for conversation_with_tools (no plan to replay)
            if (DOM.headerReplayPlannedButton) {
                DOM.headerReplayPlannedButton.classList.add('hidden');
            }
            if (DOM.headerReplayOptimizedButton) {
                DOM.headerReplayOptimizedButton.classList.add('hidden');
            }

            return; // Exit early
        }

        // Check if this is an llm_only or rag_focused profile (non-tool profiles)
        if (turnData && (turnData.profile_type === 'llm_only' || turnData.profile_type === 'rag_focused')) {
            DOM.statusWindowContent.innerHTML = '';
            const isRagFocused = turnData.profile_type === 'rag_focused';

            // Check for detailed knowledge events (similar to genie_events and conversation_agent_events)
            const knowledgeEvents = turnData.knowledge_events || [];

            if (knowledgeEvents.length > 0) {
                // Update status title to indicate historical view
                const statusTitle = DOM.statusTitle || document.getElementById('status-title');
                if (statusTitle) {
                    statusTitle.textContent = `${isRagFocused ? 'RAG Focused' : 'Conversation'} Profile - Turn ${turnId}`;
                }

                // Replay each event using the same renderer as live execution
                knowledgeEvents.forEach((event, index) => {
                    const isFinal = index === knowledgeEvents.length - 1;
                    // Build eventData in the format expected by _renderConversationAgentStep
                    const eventData = {
                        step: _getConversationAgentStepTitle(event.type, event.payload),
                        details: event.payload,
                        type: event.type
                    };
                    UI.renderConversationAgentStepForReload(eventData, DOM.statusWindowContent, isFinal);
                });

                // Render system events (session name generation, etc.) after knowledge events
                const systemEvents = turnData.system_events || [];
                if (systemEvents.length > 0) {
                    systemEvents.forEach((event, index) => {
                        const isFinal = index === systemEvents.length - 1;
                        // Check if payload is already a complete event (has 'step' field)
                        // or if it's just details that need to be wrapped
                        let eventData;
                        if (event.payload && typeof event.payload === 'object' && 'step' in event.payload) {
                            // Payload is complete event_dict (session name events)
                            eventData = event.payload;
                        } else {
                            // Payload is just details - reconstruct eventData
                            eventData = {
                                step: _getConversationAgentStepTitle(event.type, event.payload),
                                details: event.payload,
                                type: event.type
                            };
                        }
                        UI.renderConversationAgentStepForReload(eventData, DOM.statusWindowContent, isFinal);
                    });
                }

                // Add profile info after knowledge events
                const profileInfoEl = document.createElement('div');
                profileInfoEl.className = 'p-4 status-step info mt-4';
                // Removed emoji icons - using clean SVG icons instead
                const title = isRagFocused ? 'RAG Focused Profile' : 'Conversation Profile';
                profileInfoEl.innerHTML = `
                    <h4 class="font-bold text-sm text-white mb-2">${title}</h4>
                    <div class="mt-2 p-3 bg-gray-800/30 rounded border border-white/10">
                        <p class="text-xs text-gray-400"><strong>Provider:</strong> ${turnData.provider || 'N/A'}</p>
                        <p class="text-xs text-gray-400"><strong>Model:</strong> ${turnData.model || 'N/A'}</p>
                        <p class="text-xs text-gray-400 mt-2"><strong>Note:</strong> ${isRagFocused ? 'RAG focused profiles retrieve documents from knowledge repositories and synthesize answers from those sources only.' : 'Conversation profiles bypass the planner and execute directly via LLM without tool calls.'}</p>
                    </div>
                `;
                DOM.statusWindowContent.appendChild(profileInfoEl);
            } else if (turnData.knowledge_retrieval_event && (turnData.knowledge_chunks_ui || turnData.knowledge_retrieval_event.chunks)) {
                // Fallback: Use old rendering method if no detailed events
                // Get chunks from new location (knowledge_chunks_ui) or fall back to old location for backwards compatibility
                const chunks = turnData.knowledge_chunks_ui || turnData.knowledge_retrieval_event.chunks || [];
                const knowledgeEventWithChunks = {
                    ...turnData.knowledge_retrieval_event,
                    chunks: chunks  // Add chunks from appropriate source
                };

                // Use the standard renderHistoricalTrace function to show detailed knowledge retrieval
                UI.renderHistoricalTrace(
                    [], // No plan for non-tool profiles
                    [], // No execution trace for non-tool profiles
                    turnId,
                    turnData.user_query || 'N/A',
                    knowledgeEventWithChunks, // Pass the knowledge event with chunks
                    {  // Pass turn tokens for display
                        turn_input_tokens: turnData.turn_input_tokens || 0,
                        turn_output_tokens: turnData.turn_output_tokens || 0
                    }
                );

                // Add profile info after knowledge details
                const profileInfoEl = document.createElement('div');
                profileInfoEl.className = 'p-4 status-step info mt-4';
                // Removed emoji icons - using clean SVG icons instead
                const title = isRagFocused ? 'RAG Focused Profile' : 'Conversation Profile';
                profileInfoEl.innerHTML = `
                    <h4 class="font-bold text-sm text-white mb-2">${title}</h4>
                    <div class="mt-2 p-3 bg-gray-800/30 rounded border border-white/10">
                        <p class="text-xs text-gray-400"><strong>Provider:</strong> ${turnData.provider || 'N/A'}</p>
                        <p class="text-xs text-gray-400"><strong>Model:</strong> ${turnData.model || 'N/A'}</p>
                        <p class="text-xs text-gray-400 mt-2"><strong>Note:</strong> ${isRagFocused ? 'RAG focused profiles retrieve documents from knowledge repositories and synthesize answers from those sources only.' : 'Conversation profiles bypass the planner and execute directly via LLM without tool calls.'}</p>
                    </div>
                `;
                DOM.statusWindowContent.appendChild(profileInfoEl);
            } else {
                // Fallback: Show simple summary if no detailed knowledge data
                // Removed emoji icons - using clean SVG icons instead
                const title = isRagFocused ? 'RAG Focused Profile' : 'Conversation Profile';
                const message = isRagFocused
                    ? 'This turn used a RAG focused profile with mandatory knowledge retrieval.'
                    : 'This turn used a conversation profile (LLM-only).';
                const note = isRagFocused
                    ? 'RAG focused profiles retrieve documents from knowledge repositories and synthesize answers from those sources only.'
                    : 'Conversation profiles bypass the planner and execute directly via LLM without tool calls.';

                DOM.statusWindowContent.innerHTML = `
                    <div class="p-4 status-step info">
                        <h4 class="font-bold text-sm text-white mb-2">${title}</h4>
                        <p class="text-xs text-gray-300 mb-2">${turnData.message || message}</p>
                        <div class="mt-3 p-3 bg-gray-800/30 rounded border border-white/10">
                            <p class="text-xs text-gray-400"><strong>Provider:</strong> ${turnData.provider || 'N/A'}</p>
                            <p class="text-xs text-gray-400"><strong>Model:</strong> ${turnData.model || 'N/A'}</p>
                            ${isRagFocused && turnData.knowledge_retrieval_event ? `
                                <p class="text-xs text-gray-400"><strong>Documents Retrieved:</strong> ${turnData.knowledge_retrieval_event.document_count || 0}</p>
                                <p class="text-xs text-gray-400"><strong>Collections:</strong> ${turnData.knowledge_retrieval_event.collections?.join(', ') || 'N/A'}</p>
                            ` : ''}
                            <p class="text-xs text-gray-400 mt-2"><strong>Note:</strong> ${note}</p>
                        </div>
                    </div>`;
            }

            // Update token counts from historical turn data (isHistorical = true)
            const inputTokens = turnData.turn_input_tokens || turnData.input_tokens || 0;
            const outputTokens = turnData.turn_output_tokens || turnData.output_tokens || 0;
            UI.updateTokenDisplay({
                statement_input: inputTokens,
                statement_output: outputTokens,
                turn_input: inputTokens,
                turn_output: outputTokens,
                total_input: turnData.session_input_tokens || 0,
                total_output: turnData.session_output_tokens || 0
            }, true);

            // Hide replay buttons for non-tool profiles (no plan to replay)
            if (DOM.headerReplayPlannedButton) {
                DOM.headerReplayPlannedButton.classList.add('hidden');
            }
            if (DOM.headerReplayOptimizedButton) {
                DOM.headerReplayOptimizedButton.classList.add('hidden');
            }

            return; // Exit early
        }

        // Check if data is valid for tool-enabled profiles
        if (!turnData || (!turnData.original_plan && !turnData.execution_trace)) {
            throw new Error("Received empty or invalid turn details from the server.");
        }

        // Render the historical trace using the new UI function
        // Pass knowledge_retrieval_event so it renders FIRST (before execution trace)
        UI.renderHistoricalTrace(
            turnData.original_plan || [],
            turnData.execution_trace || [],
            turnId,
            turnData.user_query,
            turnData.knowledge_retrieval_event || null,  // Pass knowledge event for proper ordering
            {  // Pass turn tokens for display
                turn_input_tokens: turnData.turn_input_tokens || 0,
                turn_output_tokens: turnData.turn_output_tokens || 0
            },
            turnData.system_events || []  // Pass system events (session name generation, etc.)
        );

        // --- MODIFICATION START: Update task ID display for reloaded turn ---
        // Prioritize task_id if available in turnData, otherwise use turnId as fallback
        const taskIdToDisplay = turnData.task_id || turnId;
        UI.updateTaskIdDisplay(taskIdToDisplay);
        // --- MODIFICATION END ---

        // --- MODIFICATION START: Update model display for reloaded turn ---
        // After rendering, update the model display to reflect the turn's actual model
        if (turnData.provider && turnData.model) {
            // --- MODIFICATION: Pass historical data directly to UI function ---
            UI.updateStatusPromptName(turnData.provider, turnData.model, true);
        }
        // --- MODIFICATION END ---

        // Update token counts for tool-enabled profile reloads (isHistorical = true)
        const inputTokens = turnData.turn_input_tokens || 0;
        const outputTokens = turnData.turn_output_tokens || 0;
        UI.updateTokenDisplay({
            statement_input: inputTokens,
            statement_output: outputTokens,
            turn_input: inputTokens,
            turn_output: outputTokens,
            total_input: turnData.session_input_tokens || 0,
            total_output: turnData.session_output_tokens || 0
        }, true);

        // --- MODIFICATION START: Synchronize header buttons ---
        // After successfully rendering the trace, update the header buttons
        if (DOM.headerReplayPlannedButton) {
            DOM.headerReplayPlannedButton.classList.remove('hidden');
            DOM.headerReplayPlannedButton.disabled = false;
            DOM.headerReplayPlannedButton.dataset.turnId = turnId;
        }
        if (DOM.headerReplayOptimizedButton) {
            DOM.headerReplayOptimizedButton.classList.remove('hidden');
            DOM.headerReplayOptimizedButton.disabled = false;
            DOM.headerReplayOptimizedButton.dataset.turnId = turnId;
        }
        // --- MODIFICATION END ---

    } catch (error) {
        console.error(`Error loading details for turn ${turnId}:`, error);
        DOM.statusWindowContent.innerHTML = `<div class="p-4 status-step error"><h4 class="font-bold text-sm text-white mb-2">Error Loading Details</h4><p class="text-xs">${error.message}</p></div>`;
    }
}

/**
 * Handles clicks on the "Replay Original Query" button. Fetches the original query
 * text for that turn and re-submits it, triggering a NEW PLAN.
 * @param {HTMLButtonElement} buttonEl - The button element that was clicked.
 */
export async function handleReplayQueryClick(buttonEl) {
    const turnId = buttonEl.dataset.turnId;
    const sessionId = state.currentSessionId;
    if (!turnId || !sessionId) {
        console.error("Missing turnId or sessionId for replaying query.");
        return;
    }

    try {
        // 1. Fetch ONLY the original query text
        const queryData = await API.fetchTurnQuery(sessionId, turnId);
        const originalQuery = queryData.query;

        if (!originalQuery) {
            throw new Error("Could not retrieve the original query for this turn.");
        }

        const displayMessage = `Replaying **query** from Turn ${turnId}: ${originalQuery}`;
        // Add a message indicating a *query* replay
        UI.addMessage('user', displayMessage, null, true, 'text');

        // 2. Re-submit using handleStreamRequest, *without* a plan
        handleStreamRequest('/ask_stream', {
            message: originalQuery,      // Used for original_user_input on backend
            display_message: displayMessage, // The message to be saved in history
            session_id: sessionId,
            source: 'text',
            is_replay: true,             // Ensures logging and disables history for planning
            plan_to_execute: null        // Explicitly null. This forces a new plan.
        });

    } catch (error) {
        console.error(`Error replaying query for turn ${turnId}:`, error);
        UI.addMessage('assistant', `Sorry, could not replay the query from Turn ${turnId}. Error: ${error.message}`);
    }
}

/**
 * Handles clicks on the "Replay Planned Query" button. Fetches the original query *and*
 * the original plan for that turn, then re-submits *the plan* for execution.
 * @param {HTMLButtonElement} buttonEl - The button element that was clicked.
 */
async function handleReplayPlanClick(buttonEl) {
    const turnId = buttonEl.dataset.turnId;
    const sessionId = state.currentSessionId;
    if (!turnId || !sessionId) {
        console.error("Missing turnId or sessionId for replaying plan.");
        return;
    }

    try {
        // 1. Fetch BOTH the original query (for context) and the original plan
        const [queryData, planData] = await Promise.all([
            API.fetchTurnQuery(sessionId, turnId),
            API.fetchTurnPlan(sessionId, turnId)
        ]);

        const originalQuery = queryData.query;
        const originalPlan = planData.plan;

        if (!originalQuery) {
            throw new Error("Could not retrieve the original query for this turn.");
        }
        if (!originalPlan) {
            throw new Error("Could not retrieve the original plan for this turn.");
        }

        const displayMessage = `Replaying **plan** from Turn ${turnId}: ${originalQuery}`;
        // Add a message indicating a *plan* replay
        UI.addMessage('user', displayMessage, null, true, 'text');

        // 2. Re-submit using handleStreamRequest, passing the plan_to_execute
        handleStreamRequest('/ask_stream', {
            message: originalQuery,      // Used for original_user_input on backend
            display_message: displayMessage, // The message to be saved in history
            session_id: sessionId,
            source: 'text',
            is_replay: true,             // Ensures logging and disables history for planning (which is skipped anyway)
            plan_to_execute: originalPlan  // This tells the backend to skip planning and execute this plan
        });

    } catch (error) {
        console.error(`Error replaying plan for turn ${turnId}:`, error);
        UI.addMessage('assistant', `Sorry, could not replay the plan from Turn ${turnId}. Error: ${error.message}`);
    }
}

/**
 * Handles clicks on the "Context" status dot to purge agent memory.
 */
async function handleContextPurgeClick() {
    if (!state.currentSessionId) {
        return;
    }

    // Use the existing UI.showConfirmation
    UI.showConfirmation(
        'Purge Agent Memory?',
        "Are you sure you want to archive the context of all past turns? This will force the agent to re-evaluate the next query from scratch. Your chat log and replay ability will be preserved.",
        async () => {
            try {
                // Call the new API endpoint
                await API.purgeSessionMemory(state.currentSessionId);
                // Blink the dot on success
                UI.blinkContextDot();
                
                // --- START NEW LOGIC ---
                // Visually invalidate all existing turns in the DOM
                const allBadges = DOM.chatLog.querySelectorAll('.turn-badge');
                allBadges.forEach(badge => {
                    badge.classList.add('context-invalid');
                });
        
                // Update avatar titles to reflect archived state
                const allClickableAvatars = DOM.chatLog.querySelectorAll('.clickable-avatar');
                allClickableAvatars.forEach(avatar => {
                    // Remove old title text if present and add the new one
                    avatar.title = avatar.title.replace(' (Archived Context)', '') + ' (Archived Context)';
                });
                
                // --- END NEW LOGIC ---

            } catch (error) {
                console.error(`Failed to purge agent memory:`, error);
                // Optionally show an error to the user
                if (window.showAppBanner) {
                    window.showAppBanner(`Error: Could not purge agent memory. ${error.message}`, 'error');
                }
            }
        }
    );
}


export async function handleLoadResources(type) {
    const tabButton = document.querySelector(`.resource-tab[data-type="${type}"]`);
    const categoriesContainer = document.getElementById(`${type}-categories`);
    const panelsContainer = document.getElementById(`${type}-panels-container`);
    const typeCapitalized = type.charAt(0).toUpperCase() + type.slice(1);

    try {
        let data = await API.loadResources(type);

        // Handle new response format with profile metadata for special profiles
        // Backend returns { tools: {}, profile_type: 'rag_focused', ... } for rag_focused/genie profiles
        if (data && data.profile_type) {
            const profileType = data.profile_type;

            if (profileType === 'rag_focused') {
                state.activeRagProfile = {
                    tag: data.profile_tag,
                    knowledgeCollections: data.knowledge_collections || []
                };
                state.activeGenieProfile = null;
                console.log(`📚 Default profile is RAG-focused: @${data.profile_tag}`);
            } else if (profileType === 'genie') {
                state.activeGenieProfile = {
                    tag: data.profile_tag,
                    slaveProfiles: data.slave_profiles || []
                };
                state.activeRagProfile = null;
                console.log(`🧞 Default profile is Genie coordinator: @${data.profile_tag}`);
            }

            // Extract the actual tools/prompts from the wrapper
            data = data[type] || {};
        }

        if (!data || Object.keys(data).length === 0) {
            if(tabButton) {
                tabButton.style.display = 'none';
            }
            // Still render the panel for special profiles to show the message
            if (state.activeRagProfile || state.activeGenieProfile) {
                if (window.capabilitiesModule) {
                    window.capabilitiesModule.renderResourcePanel(type);
                }
            }
            return;
        }

        tabButton.style.display = 'inline-block';
        state.resourceData[type] = data;

        if (type === 'prompts') {
            UI.updatePromptsTabCounter();
        } else if (type === 'tools') {
            UI.updateToolsTabCounter();
        } else {
            const totalCount = Object.values(data).reduce((acc, items) => acc + items.length, 0);
            tabButton.textContent = `${typeCapitalized} (${totalCount})`;
        }

        categoriesContainer.innerHTML = '';
        panelsContainer.innerHTML = '';

        Object.keys(data).forEach(category => {
            const categoryTab = document.createElement('button');
            categoryTab.className = 'category-tab px-4 py-2 rounded-md font-semibold text-sm transition-colors hover:bg-[#D9501A]';
            categoryTab.textContent = category;
            categoryTab.dataset.category = category;
            categoryTab.dataset.type = type;
            categoriesContainer.appendChild(categoryTab);

            const panel = document.createElement('div');
            panel.id = `panel-${type}-${category}`;
            panel.className = 'category-panel px-4 space-y-2';
            panel.dataset.category = category;

            data[category].forEach(resource => {
                const itemEl = UI.createResourceItem(resource, type);
                panel.appendChild(itemEl);
            });
            panelsContainer.appendChild(panel);
        });

        document.querySelectorAll(`#${type}-categories .category-tab`).forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll(`#${type}-categories .category-tab`).forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                document.querySelectorAll(`#${type}-panels-container .category-panel`).forEach(p => {
                    p.classList.toggle('open', p.dataset.category === tab.dataset.category);
                });
            });
        });

        if (categoriesContainer.querySelector('.category-tab')) {
            categoriesContainer.querySelector('.category-tab').click();
        }

    } catch (error) {
        console.error(`Failed to load ${type}: ${error.message}`);
        if(tabButton) {
            tabButton.textContent = `${typeCapitalized} (Error)`;
            tabButton.style.display = 'inline-block';
        }
        categoriesContainer.innerHTML = '';
        panelsContainer.innerHTML = `<div class="p-4 text-center text-red-400">Failed to load ${type}.</div>`;
    }
}


function handleResourceTabClick(e) {
    if (e.target.classList.contains('resource-tab')) {
        const type = e.target.dataset.type;
        document.querySelectorAll('.resource-tab').forEach(tab => tab.classList.remove('active'));
        e.target.classList.add('active');

        document.querySelectorAll('.resource-panel').forEach(panel => {
            panel.style.display = panel.id === `${type}-panel` ? 'flex' : 'none';
        });
    }
}

function openPromptModal(prompt) {
    DOM.promptModalOverlay.classList.remove('hidden', 'opacity-0');
    DOM.promptModalContent.classList.remove('scale-95', 'opacity-0');
    DOM.promptModalTitle.textContent = prompt.name;
    DOM.promptModalForm.dataset.promptName = prompt.name;
    DOM.promptModalInputs.innerHTML = '';
    DOM.promptModalForm.querySelector('button[type="submit"]').textContent = 'Run Prompt';

    if (prompt.arguments && prompt.arguments.length > 0) {
        prompt.arguments.forEach(arg => {
            const inputGroup = document.createElement('div');
            const label = document.createElement('label');
            label.htmlFor = `prompt-arg-${arg.name}`;
            label.className = 'block text-sm font-medium text-gray-300 mb-1';
            label.textContent = arg.name + (arg.required ? ' *' : '');

            const input = document.createElement('input');
            input.type = 'text';
            input.id = `prompt-arg-${arg.name}`;
            input.name = arg.name;
            input.className = 'w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none';
            input.placeholder = arg.description || `Enter value for ${arg.name}`;
            if (arg.required) input.required = true;

            inputGroup.appendChild(label);
            inputGroup.appendChild(input);
            DOM.promptModalInputs.appendChild(inputGroup);
        });
    } else {
        DOM.promptModalInputs.innerHTML = '<p class="text-gray-400">This prompt requires no arguments.</p>';
    }

    DOM.promptModalForm.onsubmit = (e) => {
        e.preventDefault();
        const promptName = e.target.dataset.promptName;
        const formData = new FormData(e.target);
        const arugments = Object.fromEntries(formData.entries());

        UI.closePromptModal();
        handleStreamRequest('/invoke_prompt_stream', {
            session_id: state.currentSessionId,
            prompt_name: promptName,
            arguments: arugments
        });
    };
}

function openCorrectionModal(data) {
    DOM.promptModalOverlay.classList.remove('hidden', 'opacity-0');
    DOM.promptModalContent.classList.remove('scale-95', 'opacity-0');

    const spec = data.specification;
    DOM.promptModalTitle.textContent = `Correction for: ${spec.name}`;
    DOM.promptModalForm.dataset.toolName = spec.name;
    DOM.promptModalInputs.innerHTML = '';
    DOM.promptModalForm.querySelector('button[type="submit"]').textContent = 'Run Correction';

    const messageEl = document.createElement('p');
    messageEl.className = 'text-yellow-300 text-sm mb-4 p-3 bg-yellow-500/10 rounded-lg';
    messageEl.textContent = data.message;
    DOM.promptModalInputs.appendChild(messageEl);

    spec.arguments.forEach(arg => {
        const inputGroup = document.createElement('div');
        const label = document.createElement('label');
        label.htmlFor = `correction-arg-${arg.name}`;
        label.className = 'block text-sm font-medium text-gray-300 mb-1';
        label.textContent = arg.name + (arg.required ? ' *' : '');

        const input = document.createElement('input');
        input.type = 'text';
        input.id = `correction-arg-${arg.name}`;
        input.name = arg.name;
        input.className = 'w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none';
        input.placeholder = arg.description || `Enter value for ${arg.name}`;
        if (arg.required) input.required = true;

        inputGroup.appendChild(label);
        inputGroup.appendChild(input);
        DOM.promptModalInputs.appendChild(inputGroup);
    });

    DOM.promptModalForm.onsubmit = (e) => {
        e.preventDefault();
        const toolName = e.target.dataset.toolName;
        const formData = new FormData(e.target);
        const userArgs = Object.fromEntries(formData.entries());

        const correctedPrompt = `Please run the tool '${toolName}' with the following corrected parameters: ${JSON.stringify(userArgs)}`;

        UI.closePromptModal();

        handleStreamRequest('/ask_stream', { message: correctedPrompt, session_id: state.currentSessionId });
    };
}

async function openViewPromptModal(promptName) {
    DOM.viewPromptModalOverlay.classList.remove('hidden', 'opacity-0');
    DOM.viewPromptModalContent.classList.remove('scale-95', 'opacity-0');
    DOM.viewPromptModalTitle.textContent = `Viewing Prompt: ${promptName}`;
    DOM.viewPromptModalText.textContent = 'Loading...';

    try {
        const token = localStorage.getItem('tda_auth_token');
        const res = await fetch(`/prompt/${promptName}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await res.json();
        if (res.ok) {
            DOM.viewPromptModalText.textContent = data.content;
        } else {
            if (data.error === 'dynamic_prompt_error') {
                DOM.viewPromptModalText.textContent = `Info: ${data.message}`;
            } else {
                throw new Error(data.error || 'Failed to fetch prompt content.');
            }
        }
    } catch (error) {
        DOM.viewPromptModalText.textContent = `Error: ${error.message}`;
    }
}

// --- FUNCTIONS MOVED TO handlers/configManagement.js ---
// getCurrentCoreConfig
// handleCloseConfigModalRequest
// handleConfigActionButtonClick
// finalizeConfiguration
// handleConfigFormSubmit
// loadCredentialsAndModels
// handleProviderChange
// handleModelChange
// handleRefreshModelsClick
// openPromptEditor
// forceClosePromptEditor
// closePromptEditor
// saveSystemPromptChanges
// resetSystemPrompt
// handleIntensityChange
// ---

function openChatModal() {
    DOM.chatModalOverlay.classList.remove('hidden', 'opacity-0');
    DOM.chatModalContent.classList.remove('scale-95', 'opacity-0');
    DOM.chatModalInput.focus();
}

async function handleChatModalSubmit(e) {
    e.preventDefault();
    const message = DOM.chatModalInput.value.trim();
    if (!message) return;

    UI.addMessageToModal('user', message);
    state.simpleChatHistory.push({ role: 'user', content: message });
    DOM.chatModalInput.value = '';
    DOM.chatModalInput.disabled = true;

    try {
        const res = await fetch('/simple_chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                history: state.simpleChatHistory
            })
        });

        const data = await res.json();

        if (res.ok) {
            UI.addMessageToModal('assistant', data.response);
            state.simpleChatHistory.push({ role: 'assistant', content: data.response });
        } else {
            throw new Error(data.error || 'An unknown error occurred.');
        }

    } catch (error) {
        UI.addMessageToModal('assistant', `Error: ${error.message}`);
    } finally {
        DOM.chatModalInput.disabled = false;
        DOM.chatModalInput.focus();
    }
}

function handleKeyDown(e) {
    if (e.key === 'Control' && !e.repeat) {
        if (e.shiftKey) {
            state.isVoiceModeLocked = !state.isVoiceModeLocked;
            if (state.isVoiceModeLocked) {
                startRecognition();
            } else {
                stopRecognition();
            }
        } else {
            state.isTempVoiceMode = true;
            startRecognition();
        }
        UI.updateVoiceModeUI();
        e.preventDefault();
        return;
    }

    if (e.key === 'Alt' && !e.repeat) {
        if (e.shiftKey) {
            state.isLastTurnModeLocked = !state.isLastTurnModeLocked;
        } else {
            state.isTempLastTurnMode = true;
        }
        UI.updateHintAndIndicatorState();
        e.preventDefault();
    }
}

function handleKeyUp(e) {
    if (e.key === 'Control') {
        if (state.isTempVoiceMode) {
            state.isTempVoiceMode = false;
            stopRecognition();
            UI.updateVoiceModeUI();
        }
        e.preventDefault();
    }

    if (e.key === 'Alt') {
        if (state.isTempLastTurnMode) {
            state.isTempLastTurnMode = false;
            UI.updateHintAndIndicatorState();
        }
        e.preventDefault();
    }
}

function handleKeyObservationsToggleClick() {
    switch (state.keyObservationsMode) {
        case 'autoplay-off':
            state.keyObservationsMode = 'autoplay-on';
            break;
        case 'autoplay-on':
            state.keyObservationsMode = 'off';
            break;
        case 'off':
        default:
            state.keyObservationsMode = 'autoplay-off';
            break;
    }
    localStorage.setItem('keyObservationsMode', state.keyObservationsMode);
    UI.updateKeyObservationsModeUI();

    let announcementText = '';
    switch (state.keyObservationsMode) {
        case 'autoplay-off':
            announcementText = 'Key Observations Autoplay Off';
            break;
        case 'autoplay-on':
            announcementText = 'Key Observations Autoplay On';
            break;
        case 'off':
            announcementText = 'Key Observations Off';
            break;
    }

    if (announcementText) {
        (async () => {
            try {
                const audioBlob = await API.synthesizeText(announcementText);
                if (audioBlob) {
                    const audioUrl = URL.createObjectURL(audioBlob);
                    const audio = new Audio(audioUrl);
                    audio.play();
                }
            } catch (error) {
                console.error("Failed to play state change announcement:", error);
            }
        })();
    }
}

function getSystemPromptSummaryHTML() {
    let devFlagHtml = '';
//    if (state.appConfig.allow_synthesis_from_history) {
//        devFlagHtml = `
//             <div class="p-3 bg-yellow-900/50 rounded-lg mt-4">
//                <p class="font-semibold text-yellow-300">Developer Mode Enabled</p>
//                <p class="text-xs text-yellow-400 mt-1">The 'Answer from History' feature is active. The agent may answer questions by synthesizing from previous turns without re-running tools.</p>
//           </div>
//        `;
//    }

    return `
        <div class="space-y-4 text-gray-300 text-sm p-2">
            <h4 class="font-bold text-lg text-white">Agent Operating Principles</h4>
            <p>The agent's primary goal is to answer your requests by using its available capabilities:</p>
            <ul class="list-disc list-outside space-y-2 pl-5">
                <li><strong>Prompts:</strong> For pre-defined analyses, descriptions, or summaries.</li>
                <li><strong>Tools:</strong> For direct actions like "list tables" or "count users".</li>
            </ul>
            <div class="p-3 bg-gray-900/50 rounded-lg">
                <p class="font-semibold text-white">Decision-Making Process:</p>
                <p class="text-xs text-gray-400 mt-1">The agent follows a strict hierarchy. It will <strong class="text-white">always prioritize using a pre-defined prompt</strong> if it matches your request for an analysis. Otherwise, it will use the most appropriate tool to perform a direct action.</p>
            </div>
            ${devFlagHtml}
            <div class="border-t border-white/10 pt-4 mt-4">
                <h4 class="text-md font-bold text-yellow-300 mb-2">New features available</h4>
                <p class="text-xs text-gray-400 mb-3">Latest enhancements and updates to the Uderia Platform.</p>
                <div class="whats-new-container">
                    <ul class="list-disc list-inside text-xs text-gray-300 space-y-1">
                       <li><strong>06-Nov-2025:</strong> UI Real-Time Monitoring of Rest Requests</li>
                       <li><strong>31-Oct-2025:</strong> Fully configurable Context Management (Turn & Session)</li>
                       <li><strong>28-Oct-2025:</strong> Turn Replay & Turn Reload Plan</li>
                       <li><strong>24-Oct-2025:</strong> Stop Button Added - Ability to immediately Stop Workflows</li>
                       <li><strong>23-Oct-2025:</strong> Robust Multi-Tool Phase Handling</li>
                       <li><strong>11-Oct-2025:</strong> Friendly.AI Integration</li>
                       <li><strong>10-Oct-2025:</strong> Context Aware Rendering of the Collateral Report</li>
                       <li><strong>19-SEP-2025:</strong> Microsoft Azure Integration</li>
                       <li><strong>18-SEP-2025:</strong> REST Interface for Engine Configuration, Execution & Monitoring </li>
                       <li><strong>12-SEP-2025:</strong> Significant Formatting Upgrade (Canonical Baseline Model for LLM Provider Rendering)</li>
                       <li><strong>05-SEP-2025:</strong> Conversation Mode (Google Cloud Credentials required)</li>
                    </ul>
                </div>
            </div>
            <div class="border-t border-white/10 pt-4 mt-4">
                 <h4 class="text-md font-bold text-yellow-300 mb-2">Model Price/Performance Leadership Board</h4>
                 <p class="text-xs text-gray-400 mb-3">External link to the latest LLM benchmarks.</p>
                 <a href="https://gorilla.cs.berkeley.edu/leaderboard.html" target="_blank" class="text-teradata-orange hover:underline text-sm">https://gorilla.cs.berkeley.edu/leaderboard.html</a>
            </div>
            <div id="disabled-capabilities-container-splash">
                <!-- Disabled capabilities will be injected here -->
            </div>
        </div>
    `;
}

function buildDisabledCapabilitiesListHTML() {
    const disabledTools = [];
    if (state.resourceData.tools) {
        Object.values(state.resourceData.tools).flat().forEach(tool => {
            if (tool.disabled) disabledTools.push(tool.name);
        });
    }

    const disabledPrompts = [];
    if (state.resourceData.prompts) {
        Object.values(state.resourceData.prompts).flat().forEach(prompt => {
            if (prompt.disabled) disabledPrompts.push(prompt.name);
        });
    }

    if (disabledTools.length === 0 && disabledPrompts.length === 0) {
        return '';
    }

    let html = `
        <div class="border-t border-white/10 pt-4 mt-4">
            <h4 class="text-md font-bold text-yellow-300 mb-2">Reactive Capabilities</h4>
            <p class="text-xs text-gray-400 mb-3">The following capabilities are not actively participating in user queries. You can enable and/or actively execute them in the 'Capabilities' panel.</p>
            <div class="flex gap-x-8">
    `;

    if (disabledTools.length > 0) {
        html += '<div><h5 class="font-semibold text-sm text-white mb-1">Tools</h5><ul class="list-disc list-inside text-xs text-gray-300 space-y-1">';
        disabledTools.forEach(name => {
            html += `<li><code class="text-teradata-orange text-xs">${name}</code></li>`;
        });
        html += '</ul></div>';
    }

    if (disabledPrompts.length > 0) {
        html += '<div><h5 class="font-semibold text-sm text-white mb-1">Prompts</h5><ul class="list-disc list-inside text-xs text-gray-300 space-y-1">';
        disabledPrompts.forEach(name => {
            html += `<li><code class="text-teradata-orange text-xs">${name}</code></li>`;
        });
        html += '</ul></div>';
    }

    html += '</div></div>';
    return html;
}

async function handleTogglePrompt(promptName, isDisabled, buttonEl) {
    try {
        await API.togglePromptApi(promptName, isDisabled);

        for (const category in state.resourceData.prompts) {
            const prompt = state.resourceData.prompts[category].find(p => p.name === promptName);
            if (prompt) {
                prompt.disabled = isDisabled;
                break;
            }
        }

        const promptItem = document.getElementById(`resource-prompts-${promptName}`);
        const runButton = promptItem.querySelector('.run-prompt-button');

        promptItem.classList.toggle('opacity-60', isDisabled);
        promptItem.title = isDisabled ? 'This prompt is disabled and will not be used by the agent.' : '';
        runButton.disabled = isDisabled;
        runButton.title = isDisabled ? 'This prompt is disabled.' : 'Run this prompt.';

        buttonEl.innerHTML = isDisabled ?
            `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074L3.707 2.293zM10 12a2 2 0 110-4 2 2 0 010 4z" clip-rule="evenodd" /><path d="M2 10s3.939 4 8 4 8-4 8-4-3.939-4-8-4-8 4-8 4zm13.707 4.293a1 1 0 00-1.414-1.414L12.586 14.6A8.007 8.007 0 0110 16c-4.478 0-8.268-2.943-9.542-7 .946-2.317 2.83-4.224 5.166-5.447L2.293 1.293A1 1 0 00.879 2.707l14 14a1 1 0 001.414 0z" /></svg>` :
            `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z" /><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.022 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd" /></svg>`;

        UI.updatePromptsTabCounter();

    } catch (error) {
        console.error(`Failed to toggle prompt ${promptName}:`, error);
    }
}

async function handleToggleTool(toolName, isDisabled, buttonEl) {
    try {
        await API.toggleToolApi(toolName, isDisabled);

        for (const category in state.resourceData.tools) {
            const tool = state.resourceData.tools[category].find(t => t.name === toolName);
            if (tool) {
                tool.disabled = isDisabled;
                break;
            }
        }

        const toolItem = document.getElementById(`resource-tools-${toolName}`);
        toolItem.classList.toggle('opacity-60', isDisabled);
        toolItem.title = isDisabled ? 'This tool is disabled and will not be used by the agent.' : '';

        buttonEl.innerHTML = isDisabled ?
            `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074L3.707 2.293zM10 12a2 2 0 110-4 2 2 0 010 4z" clip-rule="evenodd" /><path d="M2 10s3.939 4 8 4 8-4 8-4-3.939-4-8-4-8 4-8 4zm13.707 4.293a1 1 0 00-1.414-1.414L12.586 14.6A8.007 8.007 0 0110 16c-4.478 0-8.268-2.943-9.542-7 .946-2.317 2.83-4.224 5.166-5.447L2.293 1.293A1 1 0 00.879 2.707l14 14a1 1 0 001.414 0z" /></svg>` :
            `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z" /><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.022 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd" /></svg>`;

        UI.updateToolsTabCounter();

    } catch (error) {
        console.error(`Failed to toggle tool ${toolName}:`, error);
    }
}

/**
 * Handles the save action when editing a session name (Enter or Blur).
 * @param {Event} e - The event object (blur or keydown).
 */
export async function handleSessionRenameSave(e) {
    const inputElement = e.target;
    const sessionItem = inputElement.closest('.session-item');
    if (!sessionItem) return;

    const sessionId = sessionItem.dataset.sessionId;
    const newName = inputElement.value.trim();
    const originalName = inputElement.dataset.originalName;

    if (!newName || newName === originalName) {
        UI.exitSessionEditMode(inputElement, originalName);
        return;
    }

    inputElement.disabled = true;
    inputElement.style.opacity = '0.7';

    try {
        await renameSession(sessionId, newName);
        UI.exitSessionEditMode(inputElement, newName);
        UI.moveSessionToTop(sessionId);
    } catch (error) {
        console.error(`Failed to rename session ${sessionId}:`, error);
        inputElement.style.borderColor = 'red';
        inputElement.disabled = false;
        // Revert to original name and exit edit mode on API error
        UI.exitSessionEditMode(inputElement, originalName);
    }
}

/**
 * Handles the cancel action when editing a session name (Escape).
 * @param {Event} e - The event object (keydown).
 */
export function handleSessionRenameCancel(e) {
    const inputElement = e.target;
    const originalName = inputElement.dataset.originalName;
    UI.exitSessionEditMode(inputElement, originalName);
}

async function handleToggleTurnValidity(badgeEl) {
    const turnId = badgeEl.dataset.turnId;
    const sessionId = state.currentSessionId;
    if (!turnId || !sessionId) {
        console.error("Missing turnId or sessionId for toggling validity.");
        return;
    }

    try {
        const headers = {
            'Content-Type': 'application/json'
        };
        
        // Add authentication token if available
        const authToken = localStorage.getItem('tda_auth_token');
        if (authToken) {
            headers['Authorization'] = `Bearer ${authToken}`;
        }
        
        const response = await fetch(`/api/session/${sessionId}/turn/${turnId}/toggle_validity`, {
            method: 'POST',
            headers: headers
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || 'Failed to toggle turn validity.');
        }

        // On success, toggle the UI
        const allBadgesForTurn = document.querySelectorAll(`.turn-badge[data-turn-id="${turnId}"]`);
        allBadgesForTurn.forEach(badge => {
            badge.classList.toggle('context-invalid');
        });

    } catch (error) {
        console.error(`Error toggling validity for turn ${turnId}:`, error);
        if (window.showAppBanner) {
            window.showAppBanner(`Error: Could not update turn status. ${error.message}`, 'error');
        }
    }
}

// --- Initializer ---

export function initializeEventListeners() {
    DOM.chatForm.addEventListener('submit', handleChatSubmit);
    DOM.newChatButton.addEventListener('click', handleStartNewSession);
    DOM.resourceTabs.addEventListener('click', handleResourceTabClick);
    DOM.keyObservationsToggleButton.addEventListener('click', handleKeyObservationsToggleClick);

    // Delegated event listener for copy buttons and NEW reload/replay buttons
    DOM.chatLog.addEventListener('click', (e) => {
        const copyButton = e.target.closest('.copy-button');
        const clickableAvatar = e.target.closest('.clickable-avatar[data-turn-id]');
        const clickableBadge = e.target.closest('.clickable-badge[data-turn-id]');

        if (clickableBadge) {
            e.stopPropagation();
            handleToggleTurnValidity(clickableBadge);
        } else if (copyButton) {
            const copyType = copyButton.dataset.copyType;
            if (copyType === 'code') {
                copyToClipboard(copyButton);
            } else if (copyType === 'table') {
                copyTableToClipboard(copyButton);
            }
        } else if (clickableAvatar) {
            handleReloadPlanClick(clickableAvatar);
        }
    });

    if (DOM.stopExecutionButton) {
        DOM.stopExecutionButton.addEventListener('click', handleStopExecutionClick);
    } else {
        console.error("Stop execution button not found in DOM elements.");
    }

    if (DOM.headerReplayPlannedButton) {
        DOM.headerReplayPlannedButton.addEventListener('click', (e) => {
            // --- MODIFICATION: Wire to the new handleReplayPlanClick ---
            handleReplayPlanClick(e.currentTarget);
        });
    }
    if (DOM.headerReplayOptimizedButton) {
        DOM.headerReplayOptimizedButton.addEventListener('click', (e) => {
             if (window.showAppBanner) {
                window.showAppBanner('Replay Optimized Query - Not Implemented Yet.', 'info');
            }
            // Placeholder: handleReplayOptimizedClick(e.currentTarget);
        });
    }


    DOM.mainContent.addEventListener('click', (e) => {
        const runButton = e.target.closest('.run-prompt-button');
        const viewButton = e.target.closest('.view-prompt-button');
        const promptToggleButton = e.target.closest('.prompt-toggle-button');
        const toolToggleButton = e.target.closest('.tool-toggle-button');

        if (runButton && !runButton.disabled) {
            const resourceItem = runButton.closest('.resource-item');
            const promptName = resourceItem.id.replace('resource-prompts-', '');
            let promptData = null;
            for (const category in state.resourceData.prompts) {
                const found = state.resourceData.prompts[category].find(p => p.name === promptName);
                if (found) {
                    promptData = found;
                    break;
                }
            }
            if (promptData) openPromptModal(promptData);
            return;
        }

        if (viewButton) {
            const resourceItem = viewButton.closest('.resource-item');
            const promptName = resourceItem.id.replace('resource-prompts-', '');
            openViewPromptModal(promptName);
            return;
        }

        if (promptToggleButton) {
            const resourceItem = promptToggleButton.closest('.resource-item');
            const promptName = resourceItem.id.replace('resource-prompts-', '');
            let promptData = null;
            for (const category in state.resourceData.prompts) {
                const found = state.resourceData.prompts[category].find(p => p.name === promptName);
                if (found) {
                    promptData = found;
                    break;
                }
            }
            if (promptData) handleTogglePrompt(promptName, !promptData.disabled, promptToggleButton);
            return;
        }

        if (toolToggleButton) {
            const resourceItem = toolToggleButton.closest('.resource-item');
            const toolName = resourceItem.id.replace('resource-tools-', '');
             let toolData = null;
            for (const category in state.resourceData.tools) {
                const found = state.resourceData.tools[category].find(t => t.name === toolName);
                if (found) {
                    toolData = found;
                    break;
                }
            }
            if (toolData) handleToggleTool(toolName, !toolData.disabled, toolToggleButton);
            return;
        }
    });

    DOM.sessionList.addEventListener('click', (e) => {
        const sessionItem = e.target.closest('.session-item');
        if (!sessionItem) return;

        const editButton = e.target.closest('.session-edit-button');
        const deleteButton = e.target.closest('.session-delete-button');

        if (deleteButton) {
            handleDeleteSessionClick(deleteButton);
        } else if (editButton) {
            UI.enterSessionEditMode(editButton);
        } else if (!sessionItem.querySelector('.session-edit-input')) {
            handleLoadSession(sessionItem.dataset.sessionId);
        }
    });

    // --- NEW: Active session title click to edit ---
    if (DOM.activeSessionTitle) {
        DOM.activeSessionTitle.addEventListener('click', () => {
            UI.enterActiveSessionTitleEdit();
        });
    }

    // --- NEW: Listen for custom rename event dispatched by UI.saveActiveSessionTitleEdit ---
    document.addEventListener('activeSessionTitleRenamed', (e) => {
        const { newName } = e.detail || {};
        if (newName) {
            renameActiveSession(newName);
        }
    });

    // All modal listeners
    DOM.promptModalClose.addEventListener('click', UI.closePromptModal);
    DOM.promptModalOverlay.addEventListener('click', (e) => {
        if (e.target === DOM.promptModalOverlay) UI.closePromptModal();
    });
    DOM.viewPromptModalClose.addEventListener('click', UI.closeViewPromptModal);
    DOM.viewPromptModalOverlay.addEventListener('click', (e) => {
        if (e.target === DOM.viewPromptModalOverlay) UI.closeViewPromptModal();
    });
    
    // Info Modal (now accessed from user dropdown)
    DOM.infoModalClose.addEventListener('click', () => {
        DOM.infoModalOverlay.classList.add('opacity-0');
        DOM.infoModalContent.classList.add('scale-95', 'opacity-0');
        setTimeout(() => DOM.infoModalOverlay.classList.add('hidden'), 300);
    });
    DOM.infoModalOverlay.addEventListener('click', (e) => {
        if (e.target === DOM.infoModalOverlay) {
            DOM.infoModalClose.click();
        }
    });

    // Config modal listeners
    // DOM.configMenuButton.addEventListener('click', () => {
    //     DOM.configModalOverlay.classList.remove('hidden', 'opacity-0');
    //     DOM.configModalContent.classList.remove('scale-95', 'opacity-0');
    //     // --- MODIFICATION: Use function from config handler ---
    //     // This function will need to be created/moved
    //     // For now, we'll assume getCurrentCoreConfig is still here
    //     // state.pristineConfig = getCurrentCoreConfig();
    //     // UI.updateConfigButtonState();
    //     // ---
    //     // Let's find getCurrentCoreConfig. It's not exported.
    //     // It's in the configManagement.js file but not exported.
    //     // I will assume for now that it is correctly handled by the config form's input listener.
    // });
    // DOM.configModalClose.addEventListener('click', handleCloseConfigModalRequest);
    // DOM.configActionButton.addEventListener('click', handleConfigActionButtonClick);
    
    // Old config form event listeners - wrapped in null checks since form was removed
    if (DOM.configForm) {
        DOM.configForm.addEventListener('submit', handleConfigFormSubmit);
        DOM.configForm.addEventListener('input', UI.updateConfigButtonState);
    }

    // LLM config listeners - wrapped in null checks
    if (DOM.llmProviderSelect) {
        DOM.llmProviderSelect.addEventListener('change', handleProviderChange);
    }
    // AWS credentials are now stored in encrypted database only (no localStorage)
    // API keys are now stored in encrypted database only (no localStorage)
    // Ollama host is now stored in encrypted database only (no localStorage)
    if (DOM.refreshModelsButton) {
        DOM.refreshModelsButton.addEventListener('click', handleRefreshModelsClick);
    }
    if (DOM.llmModelSelect) {
        DOM.llmModelSelect.addEventListener('change', handleModelChange);
    }


    // Prompt editor listeners
    DOM.promptEditorButton.addEventListener('click', openPromptEditor);
    DOM.promptEditorClose.addEventListener('click', closePromptEditor);
    DOM.promptEditorSave.addEventListener('click', saveSystemPromptChanges);
    DOM.promptEditorReset.addEventListener('click', () => resetSystemPrompt(false));
    DOM.promptEditorTextarea.addEventListener('input', UI.updatePromptEditorState);

    // Simple chat modal listeners
    DOM.chatModalButton.addEventListener('click', openChatModal);
    DOM.chatModalClose.addEventListener('click', UI.closeChatModal); // FIXED
    DOM.chatModalOverlay.addEventListener('click', (e) => {
        if (e.target === DOM.chatModalOverlay) UI.closeChatModal(); // FIXED
    });
    DOM.chatModalForm.addEventListener('submit', handleChatModalSubmit);

    // Global listeners
    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('keyup', handleKeyUp);
    DOM.statusWindowContent.addEventListener('mouseenter', () => { state.isMouseOverStatus = true; });
    DOM.statusWindowContent.addEventListener('mouseleave', () => { state.isMouseOverStatus = false; });
    DOM.chartingIntensitySelect.addEventListener('change', handleIntensityChange);
    
    DOM.windowMenuButton.addEventListener('click', (e) => {
        e.stopPropagation();
        DOM.windowDropdownMenu.classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
        if (!DOM.windowDropdownMenu.contains(e.target) && e.target !== DOM.windowMenuButton) {
            DOM.windowDropdownMenu.classList.remove('open');
        }
        // Settings dropdown removed - now using user dropdown for Info
    });

    DOM.contextStatusDot.addEventListener('click', handleContextPurgeClick);

    DOM.ragStatusDot.addEventListener('click', () => {
        if (state.lastRagCaseData) {
            UI.showRagCaseModal(state.lastRagCaseData);
        } else {
        }
    });

    DOM.ragCaseModalClose.addEventListener('click', UI.closeRagCaseModal);
    DOM.ragCaseModalCloseBottom.addEventListener('click', UI.closeRagCaseModal);
    DOM.ragCaseModalOverlay.addEventListener('click', (e) => {
        if (e.target === DOM.ragCaseModalOverlay) UI.closeRagCaseModal();
    });
    DOM.ragCaseModalCopy.addEventListener('click', () => {
        if (state.lastRagCaseData) {
            navigator.clipboard.writeText(JSON.stringify(state.lastRagCaseData.full_case_data, null, 2)).then(() => {
                // Provide visual feedback
                const originalText = DOM.ragCaseModalCopy.textContent;
                DOM.ragCaseModalCopy.textContent = 'Copied!';
                setTimeout(() => {
                    DOM.ragCaseModalCopy.textContent = originalText;
                }, 1500);
            }).catch(err => {
                console.error('Failed to copy RAG case data: ', err);
            });
        }
    });

    const toggleTooltipsCheckbox = document.getElementById('toggle-tooltips-checkbox');
    if (toggleTooltipsCheckbox) {
        // Set initial state from localStorage
        const savedTooltipPref = localStorage.getItem('showTooltips');
        state.showTooltips = savedTooltipPref === null ? true : savedTooltipPref === 'true';
        toggleTooltipsCheckbox.checked = state.showTooltips;

        toggleTooltipsCheckbox.addEventListener('change', (e) => {
            state.showTooltips = e.target.checked;
            localStorage.setItem('showTooltips', state.showTooltips);
        });
    }

    const welcomeScreenCheckbox = document.getElementById('toggle-welcome-screen-checkbox');
    const welcomeScreenPopupCheckbox = document.getElementById('welcome-screen-show-at-startup-checkbox');

    const handleWelcomeScreenToggle = (e) => {
        const isChecked = e.target.checked;
        state.showWelcomeScreenAtStartup = isChecked;
        // Note: localStorage is now only updated on page load/unload, not on every toggle
        // This prevents race conditions with other configuration saves
        if (welcomeScreenCheckbox) welcomeScreenCheckbox.checked = isChecked;
        if (welcomeScreenPopupCheckbox) welcomeScreenPopupCheckbox.checked = isChecked;
    };

    if (welcomeScreenCheckbox) {
        welcomeScreenCheckbox.addEventListener('change', handleWelcomeScreenToggle);
    }
    if (welcomeScreenPopupCheckbox) {
        welcomeScreenPopupCheckbox.addEventListener('change', handleWelcomeScreenToggle);
    }
    
    if (DOM.appMenuToggle) {
        DOM.appMenuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleSideNav();
        });
    }

    if (DOM.viewSwitchButtons) {
        DOM.viewSwitchButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                // Find the closest ancestor which is a link
                const link = e.target.closest('.view-switch-button');
                const viewId = link.dataset.view;
                if (viewId) {
                    handleViewSwitch(viewId);
                }
            });
        });
    }
    
    // --- MODIFICATION START: Add delegated event listener for case feedback buttons ---
    document.addEventListener('click', async (e) => {
        const caseFeedbackBtn = e.target.closest('.case-feedback-btn');
        if (caseFeedbackBtn) {
            e.preventDefault();
            const sessionId = caseFeedbackBtn.dataset.sessionId;
            const turnId = parseInt(caseFeedbackBtn.dataset.turnId);
            const caseId = caseFeedbackBtn.dataset.caseId;
            const vote = caseFeedbackBtn.dataset.vote;
            
            // Require either (sessionId + turnId) OR caseId
            if ((!sessionId || isNaN(turnId)) && !caseId) {
                console.error('Missing required data on feedback button (need either session+turn or case ID)');
                return;
            }
            
            try {
                // Import the API functions
                const { updateTurnFeedback, updateRAGCaseFeedback } = await import('./api.js');
                
                // Get current state from button classes
                const isActive = caseFeedbackBtn.classList.contains('text-[#F15F22]');
                const newVote = isActive ? null : vote;
                
                // Update backend using appropriate endpoint
                if (caseId) {
                    // Direct RAG case feedback (doesn't require session)
                    const result = await updateRAGCaseFeedback(caseId, newVote);
                    console.log('[CaseFeedback] Result:', result);
                    
                    // Calculate new feedback score for immediate UI update
                    const newScore = newVote === 'up' ? 1 : newVote === 'down' ? -1 : 0;
                    
                    // Immediately update table row feedback badge (before server refresh)
                    const { updateTableRowFeedback } = await import('./ui.js');
                    updateTableRowFeedback(caseId, newScore);
                    console.log('[CaseFeedback] Updated table row feedback immediately for', caseId);
                    
                    // Display warning if session doesn't exist
                    if (result.warning) {
                        console.log('[CaseFeedback] Warning detected, showing banner:', result.warning);
                        if (window.showAppBanner) {
                            window.showAppBanner(result.warning, 'warning');
                        } else {
                            console.warn('[CaseFeedback] showAppBanner not available');
                        }
                    } else {
                        // Show success message even without warning
                        if (window.showAppBanner) {
                            const action = newVote === 'up' ? 'marked helpful' : newVote === 'down' ? 'marked unhelpful' : 'cleared';
                            window.showAppBanner(`RAG case ${action}`, 'success');
                        }
                    }
                    
                    // Update the case details panel to show updated feedback score
                    // (Don't refresh entire table - we already updated the row immediately above)
                    console.log('[CaseFeedback] Refreshing case details panel for case', caseId);
                    const { selectCaseRow } = await import('./ui.js');
                    await selectCaseRow(caseId);
                } else if (sessionId && !isNaN(turnId)) {
                    // Session-based feedback
                    await updateTurnFeedback(sessionId, turnId, newVote);
                } else {
                    throw new Error('Invalid feedback data');
                }
                
                // Update UI: find both buttons in this container
                const container = caseFeedbackBtn.closest('.inline-flex');
                const upBtn = container.querySelector('[data-vote="up"]');
                const downBtn = container.querySelector('[data-vote="down"]');
                
                // Reset both buttons
                upBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
                upBtn.classList.add('text-gray-300');
                downBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
                downBtn.classList.add('text-gray-300');
                
                // Apply active state to clicked button if not clearing
                if (newVote) {
                    caseFeedbackBtn.classList.remove('text-gray-300');
                    caseFeedbackBtn.classList.add('text-[#F15F22]', 'bg-gray-800/60');
                }
                
            } catch (error) {
                console.error('Failed to update case feedback:', error);
                if (window.showAppBanner) {
                    window.showAppBanner(`Error updating feedback: ${error.message}`, 'error');
                }
            }
        }
    });
    // --- MODIFICATION END ---

    // Add event listener for the copy session ID button
    document.addEventListener('DOMContentLoaded', () => {
        const copyButton = document.getElementById('copy-session-id');
        if (copyButton) {
            copyButton.addEventListener('click', () => {
                const sessionId = state.activeSessionId; // Assuming activeSessionId holds the current session ID
                if (sessionId) {
                    UI.copySessionIdToClipboard(sessionId);
                } else {
                    console.error('No active session ID found.');
                }
            });
        }
    });
}
// --- Repository Tab Switching ---
export function wireRepositoryTabs() {
    if (DOM.plannerRepoTab) {
        DOM.plannerRepoTab.addEventListener('click', () => {
            // Update tab styles
            DOM.plannerRepoTab.classList.add('border-[#F15F22]', 'text-[#F15F22]');
            DOM.plannerRepoTab.classList.remove('border-transparent', 'text-gray-400');
            DOM.knowledgeRepoTab.classList.remove('border-[#F15F22]', 'text-[#F15F22]');
            DOM.knowledgeRepoTab.classList.add('border-transparent', 'text-gray-400');
            
            // Show/hide content
            DOM.plannerRepoContent.classList.remove('hidden');
            DOM.knowledgeRepoContent.classList.add('hidden');
        });
    }
    
    if (DOM.knowledgeRepoTab) {
        DOM.knowledgeRepoTab.addEventListener('click', () => {
            // Update tab styles
            DOM.knowledgeRepoTab.classList.add('border-[#F15F22]', 'text-[#F15F22]');
            DOM.knowledgeRepoTab.classList.remove('border-transparent', 'text-gray-400');
            DOM.plannerRepoTab.classList.remove('border-[#F15F22]', 'text-[#F15F22]');
            DOM.plannerRepoTab.classList.add('border-transparent', 'text-gray-400');
            
            // Show/hide content
            DOM.knowledgeRepoContent.classList.remove('hidden');
            DOM.plannerRepoContent.classList.add('hidden');
        });
    }
}

// --- Export harmonization functions for use in event reload ---
// These functions are used by ui.js during historical event rendering
// to regenerate harmonized titles from stored event payloads
window.EventHandlers = {
    getToolEnabledTitle,
    getLlmOnlyTitle,
    getRagFocusedTitle,
    getGenieTitle
};
