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
    message.className = 'mb-4';
    message.style.color = 'var(--text-secondary)';
    message.textContent = data.message;

    const configDetails = document.createElement('pre');
    configDetails.className = 'p-4 rounded-md text-xs overflow-x-auto';
    configDetails.style.backgroundColor = 'var(--bg-tertiary)';
    configDetails.style.color = 'var(--text-secondary)';
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
    const banner = document.getElementById('profile-override-warning-banner');
    const message = document.getElementById('profile-override-warning-message');
    const dismissBtn = document.getElementById('dismiss-profile-warning');

    if (!banner || !message) {
        console.error('[showProfileOverrideWarning] Required elements not found!');
        return;
    }

    const displayMessage = `Unable to use profile '${overrideProfileName}' (@${overrideProfileTag}): Missing credentials. Using default profile (@${defaultProfileTag}).`;
    message.textContent = displayMessage;
    banner.classList.remove('hidden');

    // Setup dismiss button
    if (dismissBtn) {
        dismissBtn.onclick = () => {
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
            return 'LLM Synthesis Started';
        case 'genie_synthesis_complete':
            return 'LLM Synthesis Results';
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

/**
 * Routes a REST task event to the correct profile-specific renderer.
 * Different profile classes (tool_enabled, llm_only, conversation_with_tools,
 * rag_focused) produce different event types that need different renderers.
 * This dispatcher replaces the previous blanket 'rest' source rendering.
 *
 * @param {Object} event - The canonical event object (has .type and payload fields)
 * @param {string} taskId - The REST task ID
 */
function _dispatchRestEvent(event, taskId) {
    const eventType = event.type;
    if (!eventType) return;

    // --- Token updates: direct to token display, not status window ---
    if (eventType === 'token_update') {
        UI.updateTokenDisplay(event);
        return;
    }

    // --- Status indicators: transient, skip (handled separately) ---
    if (eventType === 'status_indicator_update') return;

    // --- Session model updates: handle metadata only ---
    if (eventType === 'session_model_update') {
        const payload = event.payload || event;
        UI.updateSessionModels(payload.session_id, payload.models_used, payload.profile_tags_used);
        if (payload.session_id === state.currentSessionId) {
            state.currentProvider = payload.provider;
            state.currentModel = payload.model;
            UI.updateStatusPromptName();
        }
        return;
    }

    // --- Conversation Agent events (conversation_with_tools profile) ---
    if (eventType.startsWith('conversation_agent') ||
        eventType.startsWith('conversation_llm') ||
        eventType.startsWith('conversation_tool')) {
        const payload = event.payload || event;
        const stepTitle = _getConversationAgentStepTitle(eventType, payload);
        UI.updateStatusWindow({
            step: stepTitle,
            details: payload,
            type: eventType
        }, eventType === 'conversation_agent_complete', 'conversation_agent');
        // Also update handler state for correct live event processing
        handleConversationAgentEvent(eventType, payload);
        return;
    }

    // --- Knowledge Retrieval events (rag_focused + conversation_with_tools) ---
    if (eventType.startsWith('knowledge_') ||
        eventType === 'rag_llm_step' ||
        eventType === 'knowledge_search_complete') {
        const payload = event.payload || event;
        const stepTitle = _getConversationAgentStepTitle(eventType, payload);
        UI.updateStatusWindow({
            step: stepTitle,
            details: payload,
            type: eventType
        }, false, 'knowledge_retrieval');
        return;
    }

    // --- LLM execution events (llm_only profile) ---
    if (eventType === 'llm_execution' || eventType === 'llm_execution_complete') {
        const payload = event.payload || event;
        const stepTitle = _getConversationAgentStepTitle(eventType, payload);
        UI.updateStatusWindow({
            step: stepTitle,
            details: payload,
            type: eventType
        }, eventType === 'llm_execution_complete', 'conversation_agent');
        return;
    }

    // --- Lifecycle events (all profile types) ---
    if (eventType === 'execution_start' || eventType === 'execution_complete' ||
        eventType === 'execution_error' || eventType === 'execution_cancelled') {
        const payload = event.payload || event;

        // Capture turn number from execution_start for title display
        if (eventType === 'execution_start' && payload.turn_id) {
            state.currentTurnNumber = payload.turn_id;
        }

        const isFinal = eventType !== 'execution_start';
        UI.updateStatusWindow({
            step: eventType,
            details: payload,
            type: eventType
        }, isFinal, 'lifecycle');
        return;
    }

    // --- Default: planner/executor events (tool_enabled profile) → 'rest' source ---
    const isFinal = (eventType === 'final_answer' || eventType === 'error' || eventType === 'cancelled');
    UI.updateStatusWindow(event, isFinal, 'rest', taskId);
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

        // Skip SSE session loading - sessions are loaded by configManagement.js with pagination
        // This prevents duplicate loading and ensures pagination works correctly
        console.log('[SSE] Skipping session load - handled by configManagement.js with pagination');
    };

    eventSource.addEventListener('notification', (event) => {
        const data = JSON.parse(event.data);

        // Only log non-routine notifications (skip frequent status updates)
        if (!['status_indicator_update', 'session_model_update'].includes(data.type)) {
            console.log('[notification] Received:', data.type);
        }

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

                // Check if this is a genie slave session to determine if it's the last child
                const genieMetadata = newSession.genie_metadata || {};
                const parentSessionId = genieMetadata.parent_session_id;
                let isLastChild = true;  // New session is always the last child when created

                // Add the new session to the UI list, but do not make it active
                const sessionItem = UI.addSessionToList(newSession, false, isLastChild);

                if (genieMetadata.is_genie_slave && parentSessionId) {
                    // Find the parent session element (might be wrapped)
                    const parentElement = document.getElementById(`session-${parentSessionId}`);
                    if (parentElement) {
                        // Find all existing sibling slaves (same parent) - these are wrapped elements
                        const existingSlaveWrappers = Array.from(DOM.sessionList.querySelectorAll('.genie-wrapper'))
                            .filter(wrapper => {
                                const sessionEl = wrapper.querySelector('.genie-slave-session');
                                return sessionEl && sessionEl.dataset.genieParentId === parentSessionId;
                            });

                        if (existingSlaveWrappers.length === 0) {
                            // No existing slaves, insert directly after parent (or parent's wrapper)
                            const insertAfter = parentElement.parentElement && parentElement.parentElement.classList.contains('genie-wrapper')
                                ? parentElement.parentElement
                                : parentElement;
                            insertAfter.insertAdjacentElement('afterend', sessionItem);
                        } else {
                            // Insert after the last existing slave wrapper to maintain order
                            const lastSlaveWrapper = existingSlaveWrappers[existingSlaveWrappers.length - 1];
                            lastSlaveWrapper.insertAdjacentElement('afterend', sessionItem);

                            // Update the previous last child to no longer be the last child
                            // Remove the 'genie-wrapper-last' class so it shows ├─ with vertical line
                            if (lastSlaveWrapper.classList && lastSlaveWrapper.classList.contains('genie-wrapper-last')) {
                                lastSlaveWrapper.classList.remove('genie-wrapper-last');
                            }
                        }

                        // Update genie master badges to add collapse toggle to parent if needed
                        UI.updateGenieMasterBadges();

                        // Sync wrapper collapsed states for new child sessions
                        import('../hierarchyHelpers.js').then(module => {
                            module.syncWrapperStates();
                        });
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
                // Update archived sessions filter visibility
                if (window.updateArchivedSessionsFilter) {
                    window.updateArchivedSessionsFilter();
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
                const { override_profile_name, override_profile_tag, default_profile_tag, error_message } = data.payload;
                showProfileOverrideWarning(override_profile_name, override_profile_tag, default_profile_tag, error_message);
                break;
            }
            case 'session_model_update': {
                const { session_id, models_used, profile_tags_used, last_updated, provider, model, name } = data.payload;
                UI.updateSessionModels(session_id, models_used, profile_tags_used);
                UI.updateSessionTimestamp(session_id, last_updated);
                if (name) {
                    UI.updateSessionListItemName(session_id, name);
                }
                UI.moveSessionToTop(session_id);

                if (session_id === state.currentSessionId) {
                    state.currentProvider = provider;
                    state.currentModel = model;
                    UI.updateStatusPromptName();
                }
                break;
            }
            // --- REST task events with buffering and profile-aware dispatch ---
            case 'rest_task_update': {
                const { task_id, session_id, event } = data.payload;

                // --- Always buffer REST events per session for cross-session replay ---
                // Buffer is created on first event, and session is tracked as active.
                // Completion is handled by the separate 'rest_task_complete' notification.
                if (!state.restEventBuffer[session_id]) {
                    state.restEventBuffer[session_id] = { taskId: task_id, events: [], isComplete: false };
                    state.activeRestSessions.add(session_id);
                }
                state.restEventBuffer[session_id].events.push(event);

                // --- Session guard: allow current session + child sessions during Genie ---
                if (session_id !== state.currentSessionId && !state.isGenieCoordinationActive) break;

                // --- Extract indicator events (CCR, KNW) for dot blinks ---
                if (event.type === 'rag_retrieval') {
                    state.lastRagCaseData = event;
                    UI.blinkCcrDot();
                }
                if (event.type === 'knowledge_retrieval' || event.type === 'knowledge_retrieval_complete') {
                    const collections = event.data?.collections || [];
                    const documentCount = event.data?.document_count || 0;
                    if (!state.isViewingHistoricalTurn) UI.blinkKnowledgeDot();
                    UI.updateKnowledgeIndicator(collections, documentCount);
                }

                // During Genie coordination, child REST events should only blink dots.
                // The Genie renderer handles child progress via genie_slave_* events.
                if (state.isGenieCoordinationActive && session_id !== state.currentSessionId) {
                    break;
                }

                // --- Route to profile-specific renderer ---
                _dispatchRestEvent(event, task_id);
                break;
            }
            case 'rest_task_complete': {
                const { session_id, turn_id, user_input, final_answer, profile_tag } = data.payload;

                // --- Definitive cleanup for REST session tracking ---
                state.activeRestSessions.delete(session_id);
                if (state.restEventBuffer[session_id]) {
                    state.restEventBuffer[session_id].isComplete = true;
                }

                if (session_id === state.currentSessionId) {
                    // User is viewing this session — render Q&A and clean up
                    UI.addMessage('user', user_input, turn_id, true, 'rest', profile_tag);
                    UI.addMessage('assistant', final_answer, turn_id, true);
                    UI.moveSessionToTop(session_id);
                    UI.setExecutionState(false);

                    // Explicitly mark the last active status step as completed
                    const lastStep = DOM.statusWindowContent.querySelector('.status-step.active');
                    if (lastStep) {
                        lastStep.classList.remove('active');
                        lastStep.classList.add('completed');
                    }

                    // Buffer no longer needed — UI is fully rendered
                    delete state.restEventBuffer[session_id];
                } else {
                    // User is viewing a different session
                    UI.highlightSession(session_id);
                    // Delete stale cache (next visit should use normal server load with fresh data)
                    delete state.sessionUiCache[session_id];
                    // Buffer is kept (marked complete) — cleaned on next visit to this session
                }
                break;
            }
            case 'status_indicator_update': {
                // Status indicators (MCP, LLM) are global system health indicators.
                // Always process them regardless of active streams — they reflect
                // system-wide connection state that applies to all sessions equally.
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
                // RAG retrieval is a system-wide indicator — always process.
                // Per-request stream also handles this (eventHandlers.js:756)
                // for the viewed session; double-blink is acceptable.
                state.lastRagCaseData = data.payload || data;
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
                // CRITICAL: Skip if there's an active stream for this session
                // The /ask_stream channel is the primary handler - notifications are supplementary
                if (payload.session_id && state.activeStreamSessions && state.activeStreamSessions.has(payload.session_id)) {
                    console.log('[ConversationAgent] Skipping - active stream handling this session:', payload.session_id);
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

                // Session guard: skip events for other sessions
                if (payload.session_id && payload.session_id !== state.currentSessionId) {
                    console.log(`[${data.type}] Ignoring notification for different session:`, payload.session_id);
                    break;
                }
                // When multiple streams active and no session_id, skip to avoid ambiguity
                if (!payload.session_id && state.activeStreamSessions.size > 1) {
                    break;
                }

                const stepTitle = _getConversationAgentStepTitle(data.type, payload);
                console.log(`[${data.type}] Received direct notification:`, payload);

                // Update knowledge indicator for completion events
                if (data.type === 'knowledge_retrieval_complete' || data.type === 'knowledge_retrieval') {
                    const collections = payload.collections || [];
                    const documentCount = payload.document_count || 0;
                    // Only blink during live execution, not when viewing historical turns
                    if (!state.isViewingHistoricalTurn) {
                        UI.blinkKnowledgeDot();
                    }
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