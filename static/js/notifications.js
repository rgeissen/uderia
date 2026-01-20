import { state } from './state.js';
import * as UI from './ui.js';
import * as DOM from './domElements.js';
import * as API from './api.js';
import { handleLoadSession } from './handlers/sessionManagement.js?v=3.2';
import { handleGenieEvent } from './handlers/genieHandler.js?v=3.4';
import { handleConversationAgentEvent } from './handlers/conversationAgentHandler.js?v=1.0';

function showRestQueryNotification(message) {
    const notificationContainer = document.createElement('div');
    notificationContainer.id = 'rest-notification';
    notificationContainer.className = 'notification-banner';

    const messageElement = document.createElement('p');
    messageElement.textContent = message;

    const buttonContainer = document.createElement('div');

    const refreshButton = document.createElement('button');
    refreshButton.textContent = 'Refresh';
    refreshButton.onclick = () => {
        window.location.reload();
    };

    const closeButton = document.createElement('button');
    closeButton.textContent = 'Close';
    closeButton.onclick = () => {
        notificationContainer.remove();
    };

    buttonContainer.appendChild(refreshButton);
    buttonContainer.appendChild(closeButton);

    notificationContainer.appendChild(messageElement);
    notificationContainer.appendChild(buttonContainer);

    document.body.appendChild(notificationContainer);
}

function showReconfigurationNotification(data) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50';

    const modal = document.createElement('div');
    modal.className = 'glass-panel rounded-xl shadow-2xl w-full max-w-lg p-6';

    const title = document.createElement('h3');
    title.className = 'text-xl font-bold mb-4 header-title';
    title.textContent = 'Application Reconfigured';

    const message = document.createElement('p');
    message.className = 'text-gray-300 mb-4';
    message.textContent = data.message;

    const configDetails = document.createElement('pre');
    configDetails.className = 'bg-gray-900/50 p-4 rounded-md text-xs text-gray-300 overflow-x-auto';
    configDetails.textContent = JSON.stringify(data.config, null, 2);

    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'flex justify-end mt-6';

    const refreshButton = document.createElement('button');
    refreshButton.className = 'px-4 py-2 rounded-md bg-teradata-orange hover:bg-teradata-orange-dark transition-colors font-semibold';
    refreshButton.textContent = 'Refresh Now';
    refreshButton.onclick = () => {
        window.location.reload();
    };

    buttonContainer.appendChild(refreshButton);

    modal.appendChild(title);
    modal.appendChild(message);
    modal.appendChild(configDetails);
    modal.appendChild(buttonContainer);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
}

function showProfileOverrideWarning(overrideProfileName, overrideProfileTag, defaultProfileTag, errorMessage) {
    console.log('[showProfileOverrideWarning] Function called');
    const banner = document.getElementById('profile-override-warning-banner');
    const message = document.getElementById('profile-override-warning-message');
    const dismissBtn = document.getElementById('dismiss-profile-warning');
    
    console.log('[showProfileOverrideWarning] Elements found:', {
        banner: banner ? 'yes' : 'no',
        message: message ? 'yes' : 'no',
        dismissBtn: dismissBtn ? 'yes' : 'no'
    });
    
    if (!banner || !message) {
        console.error('[showProfileOverrideWarning] Required elements not found!');
        return;
    }
    
    const displayMessage = `Unable to use profile '${overrideProfileName}' (@${overrideProfileTag}): Missing credentials. Using default profile (@${defaultProfileTag}).`;
    console.log('[showProfileOverrideWarning] Setting message:', displayMessage);
    message.textContent = displayMessage;
    banner.classList.remove('hidden');
    console.log('[showProfileOverrideWarning] Banner should now be visible');
    
    // Setup dismiss button
    if (dismissBtn) {
        dismissBtn.onclick = () => {
            console.log('[showProfileOverrideWarning] Dismiss button clicked');
            banner.classList.add('hidden');
        };
    }
}

/**
 * Get human-readable step title for genie coordination events.
 */
function _getGenieStepTitle(eventType, payload) {
    switch (eventType) {
        case 'genie_start':
            return '🔮 Genie Coordinator Activated';
        case 'genie_routing': {
            const slaveCount = payload.slave_profiles?.length || 0;
            return `Consulting ${slaveCount} expert${slaveCount > 1 ? 's' : ''}`;
        }
        case 'genie_coordination_start':
            return 'Coordinating Response';
        case 'genie_llm_step': {
            const stepName = payload.step_name || `Step ${payload.step_number || '?'}`;
            return `${stepName}`;
        }
        case 'genie_routing_decision': {
            const profileCount = payload.selected_profiles?.length || 0;
            return `Routing to ${profileCount} expert${profileCount > 1 ? 's' : ''}`;
        }
        case 'genie_slave_invoked':
            return `Invoking @${payload.profile_tag || 'PROFILE'}`;
        case 'genie_slave_progress':
            return `@${payload.profile_tag || 'PROFILE'}: ${payload.message || 'Processing'}`;
        case 'genie_slave_completed': {
            const status = payload.success ? 'Completed' : 'Failed';
            const duration = payload.duration_ms ? ` (${(payload.duration_ms / 1000).toFixed(1)}s)` : '';
            return `@${payload.profile_tag || 'PROFILE'}: ${status}${duration}`;
        }
        case 'genie_synthesis_start':
            return 'Synthesizing Response';
        case 'genie_coordination_complete':
            return payload.success ? 'Coordination Complete' : 'Coordination Failed';
        default:
            return eventType;
    }
}

/**
 * Get human-readable step title for conversation agent events.
 */
function _getConversationAgentStepTitle(eventType, payload) {
    switch (eventType) {
        case 'conversation_agent_start': {
            const toolCount = payload.available_tools?.length || 0;
            return `Using Tools (${toolCount} available)`;
        }
        case 'conversation_llm_step': {
            const stepName = payload.step_name || `Step ${payload.step_number || '?'}`;
            return `${stepName}`;
        }
        case 'conversation_tool_invoked':
            return `Executing ${payload.tool_name || 'tool'}`;
        case 'conversation_tool_completed': {
            const status = payload.success ? 'Completed' : 'Failed';
            const duration = payload.duration_ms ? ` (${(payload.duration_ms / 1000).toFixed(1)}s)` : '';
            return `${payload.tool_name || 'Tool'}: ${status}${duration}`;
        }
        case 'conversation_agent_complete': {
            const toolCount = payload.tools_used?.length || 0;
            const duration = payload.total_duration_ms ? ` in ${(payload.total_duration_ms / 1000).toFixed(1)}s` : '';
            return payload.success
                ? `Tools Complete (${toolCount} executed${duration})`
                : 'Execution Failed';
        }
        default:
            return eventType;
    }
}

export function subscribeToNotifications() {
    if (!state.userUUID) {
        // Set status to disconnected if we can't even start.
        console.warn('[SSE] Cannot subscribe: no user ID available');
        UI.updateSSEStatus('disconnected');
        return;
    }

    console.log('[SSE] Subscribing to notifications for user:', state.userUUID);
    const eventSource = new EventSource(`/api/notifications/subscribe?user_uuid=${state.userUUID}`);

    eventSource.onopen = async () => {
        console.log('[SSE] Connection established');
        UI.updateSSEStatus('connected');

        // Load existing sessions and populate UI on initial connection
        try {
            console.log('[SSE] Loading existing sessions...');
            const sessions = await API.loadAllSessions();
            console.log('[SSE] Received sessions from API:', sessions);

            if (sessions && sessions.length > 0) {
                console.log(`[SSE] Found ${sessions.length} existing sessions, populating UI...`);

                // Clear existing session list (in case of reconnection)
                DOM.sessionList.innerHTML = '';

                // Sessions are already in correct hierarchical order from backend
                // (parent → L1 child → L2 grandchild, etc.)
                let addedCount = 0;
                for (const session of sessions) {
                    const genieMetadata = session.genie_metadata || {};
                    const isGenieSlave = genieMetadata.is_genie_slave;
                    const parentSessionId = genieMetadata.parent_session_id;
                    const nestingLevel = genieMetadata.nesting_level;

                    console.log(`[SSE] Adding session ${session.id.substring(0, 12)}... (slave=${isGenieSlave}, level=${nestingLevel}, parent=${parentSessionId ? parentSessionId.substring(0, 12) + '...' : 'none'})`);

                    const sessionItem = UI.addSessionToList(session, false);

                    // Append in order (backend already sorted hierarchically)
                    DOM.sessionList.appendChild(sessionItem);
                    addedCount++;

                    console.log(`[SSE] Session ${session.id.substring(0, 12)}... added to DOM, classList:`, sessionItem.classList.toString());
                }

                console.log(`[SSE] Added ${addedCount} sessions to DOM`);

                // After all sessions loaded, update genie master badges
                UI.updateGenieMasterBadges();

                console.log('[SSE] Session list populated successfully');
                console.log('[SSE] Final DOM.sessionList.children.length:', DOM.sessionList.children.length);
            } else {
                console.log('[SSE] No existing sessions found');
            }
        } catch (error) {
            console.error('[SSE] Error loading existing sessions:', error);
        }
    };

    eventSource.addEventListener('notification', (event) => {
        const data = JSON.parse(event.data);
        console.log('[notification] Received:', data.type, data);

        // When a notification is received, we know the connection is good.
        UI.updateSSEStatus('connected');

        switch (data.type) {
            case 'reconfiguration':
                showReconfigurationNotification(data.payload);
                break;
            case 'info':
                showRestQueryNotification(data.message);
                break;
            case 'new_session_created': {
                const newSession = data.payload;
                // Add the new session to the UI list, but do not make it active
                const sessionItem = UI.addSessionToList(newSession, false);

                // Check if this is a genie slave session - insert after parent instead of prepending
                const genieMetadata = newSession.genie_metadata || {};
                const parentSessionId = genieMetadata.parent_session_id;

                if (genieMetadata.is_genie_slave && parentSessionId) {
                    // Find the parent session element
                    const parentElement = document.getElementById(`session-${parentSessionId}`);
                    if (parentElement) {
                        // Find all existing sibling slaves (same parent)
                        const existingSlaves = Array.from(DOM.sessionList.querySelectorAll('.genie-slave-session'))
                            .filter(el => el.dataset.genieParentId === parentSessionId);

                        if (existingSlaves.length === 0) {
                            // No existing slaves, insert directly after parent
                            parentElement.insertAdjacentElement('afterend', sessionItem);
                        } else {
                            // Insert after the last existing slave to maintain order
                            const lastSlave = existingSlaves[existingSlaves.length - 1];
                            lastSlave.insertAdjacentElement('afterend', sessionItem);
                        }

                        // Update genie master badges to add collapse toggle to parent if needed
                        UI.updateGenieMasterBadges();
                    } else {
                        // Fallback to prepend if parent not found
                        DOM.sessionList.prepend(sessionItem);
                    }
                } else {
                    // Non-slave sessions go to the top
                    DOM.sessionList.prepend(sessionItem);
                }

                // Update utility sessions filter visibility
                if (window.updateUtilitySessionsFilter) {
                    window.updateUtilitySessionsFilter();
                }
                break;
            }
            case 'session_name_update': {
                const { session_id, newName } = data.payload;
                UI.updateSessionListItemName(session_id, newName);
                UI.moveSessionToTop(session_id);
                if (session_id === state.currentSessionId) {
                    UI.updateActiveSessionTitle(newName);
                }
                break;
            }
            case 'profile_override_failed': {
                console.log('[profile_override_failed] Received notification:', data);
                const { override_profile_name, override_profile_tag, default_profile_tag, error_message } = data.payload;
                console.log('[profile_override_failed] Calling showProfileOverrideWarning with:', {
                    override_profile_name,
                    override_profile_tag,
                    default_profile_tag,
                    error_message
                });
                showProfileOverrideWarning(override_profile_name, override_profile_tag, default_profile_tag, error_message);
                break;
            }
            case 'session_model_update': {
                const { session_id, models_used, profile_tags_used, last_updated, provider, model, name } = data.payload;
                console.log('[session_model_update] Received notification:', {
                    session_id,
                    models_used,
                    profile_tags_used,
                    provider,
                    model,
                    current_session: state.currentSessionId,
                    is_current: session_id === state.currentSessionId
                });
                UI.updateSessionModels(session_id, models_used, profile_tags_used);
                UI.updateSessionTimestamp(session_id, last_updated);
                if (name) {
                    UI.updateSessionListItemName(session_id, name);
                }
                UI.moveSessionToTop(session_id);

                if (session_id === state.currentSessionId) {
                    console.log('[session_model_update] Updating Live Status with:', provider, model);
                    state.currentProvider = provider;
                    state.currentModel = model;
                    UI.updateStatusPromptName();
                } else {
                    console.log('[session_model_update] Not updating Live Status - wrong session');
                }
                break;
            }
            // --- MODIFICATION START: Add handlers for REST task events ---
            case 'rest_task_update': {
                const { task_id, session_id, event } = data.payload;
                if (session_id !== state.currentSessionId) break;

                // --- MODIFICATION START: Add CCR (Champion Case Retrieval) event handling ---
                // Check the *original* event type inside the payload
                if (event.type === 'rag_retrieval') {
                    state.lastRagCaseData = event; // Store the full case data
                    UI.blinkCcrDot();
                }
                // --- MODIFICATION END ---

                // --- PHASE 3: Add knowledge_retrieval event handling ---
                if (event.type === 'knowledge_retrieval') {
                    const collections = event.data?.collections || [];
                    const documentCount = event.data?.document_count || 0;
                    console.log('[knowledge_retrieval] Received:', { collections, documentCount });
                    UI.blinkKnowledgeDot();
                    UI.updateKnowledgeIndicator(collections, documentCount);
                }
                // --- END PHASE 3 ---

                const isFinal = (event.type === 'final_answer' || event.type === 'error' || event.type === 'cancelled');
                
                // The backend now sends a canonical event object, so we can pass it directly.
                UI.updateStatusWindow(event, isFinal, 'rest', task_id);
                break;
            }
            case 'rest_task_complete':
                {
                    const { session_id, turn_id, user_input, final_answer, profile_tag } = data.payload;
                    if (session_id === state.currentSessionId) {
                        // Add the Q&A to the main chat log with profile tag
                        UI.addMessage('user', user_input, turn_id, true, 'rest', profile_tag);
                        UI.addMessage('assistant', final_answer, turn_id, true);
                        UI.moveSessionToTop(session_id);
                        UI.setExecutionState(false); // Reset UI execution state

                        // Explicitly mark the last active status step as completed
                        const lastStep = DOM.statusWindowContent.querySelector('.status-step.active');
                        if (lastStep) {
                            lastStep.classList.remove('active');
                            lastStep.classList.add('completed');
                        }
                    } else {
                        // If not the current session, provide a visual cue
                        UI.highlightSession(session_id);
                    }
                    break;
                }
            case 'status_indicator_update': {
                const { target, state: statusState } = data.payload;
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
                break;
            }
            // --- MODIFICATION END ---
            case 'rag_retrieval':
                UI.blinkCcrDot();
                break;
            // --- Genie Coordination Events ---
            case 'genie_start':  // From execution_service.py
            case 'genie_routing':  // From execution_service.py
            case 'genie_coordination_start':
            case 'genie_llm_step':
            case 'genie_routing_decision':
            case 'genie_slave_invoked':
            case 'genie_slave_progress':
            case 'genie_slave_completed':
            case 'genie_synthesis_start':
            case 'genie_coordination_complete': {
                const payload = data.payload || {};
                // Only handle events for current session
                if (payload.session_id && payload.session_id !== state.currentSessionId) {
                    console.log('[Genie] Ignoring event for different session:', payload.session_id);
                    break;
                }
                // Delegate to genie handler for inline card updates
                handleGenieEvent(data.type, payload);
                // Also update status window if open (respects user preference)
                const genieStepTitle = _getGenieStepTitle(data.type, payload);
                UI.updateStatusWindow({
                    step: genieStepTitle,
                    details: payload,
                    type: data.type
                }, data.type === 'genie_coordination_complete', 'genie');
                break;
            }
            // --- Conversation Agent Events (conversation_with_tools profile) ---
            case 'conversation_agent_start':
            case 'conversation_llm_step':
            case 'conversation_tool_invoked':
            case 'conversation_tool_completed':
            case 'conversation_agent_complete': {
                const payload = data.payload || {};
                // Only handle events for current session
                if (payload.session_id && payload.session_id !== state.currentSessionId) {
                    console.log('[ConversationAgent] Ignoring event for different session:', payload.session_id);
                    break;
                }
                // IMPORTANT: Update status window BEFORE calling handler for completion event
                // because handler sets isConversationAgentActive=false which would trigger a reset
                const agentStepTitle = _getConversationAgentStepTitle(data.type, payload);
                UI.updateStatusWindow({
                    step: agentStepTitle,
                    details: payload,
                    type: data.type
                }, data.type === 'conversation_agent_complete', 'conversation_agent');
                // Delegate to conversation agent handler for state tracking (after UI update)
                handleConversationAgentEvent(data.type, payload);
                break;
            }
            // --- Knowledge Retrieval Events for Conversation Agent ---
            case 'knowledge_retrieval':
            case 'knowledge_retrieval_start':
            case 'knowledge_reranking_start':
            case 'knowledge_reranking_complete':
            case 'knowledge_retrieval_complete':
            case 'rag_llm_step':
            case 'knowledge_search_complete': {
                const payload = data.payload || {};
                const stepTitle = _getConversationAgentStepTitle(data.type, payload);
                console.log(`[${data.type}] Received direct notification:`, payload);

                // Update knowledge indicator for completion events
                if (data.type === 'knowledge_retrieval_complete' || data.type === 'knowledge_retrieval') {
                    const collections = payload.collections || [];
                    const documentCount = payload.document_count || 0;
                    UI.blinkKnowledgeDot();
                    UI.updateKnowledgeIndicator(collections, documentCount);
                    // Store the knowledge event for potential replay
                    state.pendingKnowledgeRetrievalEvent = payload;
                }

                // Always update status window for knowledge retrieval events
                // For conversation_with_tools, these arrive BEFORE conversation_agent_start
                // so we render them directly without checking isConversationAgentActive
                UI.updateStatusWindow({
                    step: stepTitle,
                    details: payload,
                    type: data.type
                }, false, 'knowledge_retrieval');
                break;
            }
            default:
                // console.warn("Unknown notification type:", data.type);
        }
    });

    eventSource.onerror = (error) => {
        console.error("EventSource failed:", error);
        // Don't close the connection; the browser will attempt to reconnect automatically.
        // Update the UI to show the reconnecting status.
        UI.updateSSEStatus('reconnecting');
    };
}