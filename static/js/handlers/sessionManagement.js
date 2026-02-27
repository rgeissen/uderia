/**
 * handlers/sessionManagement.js
 * * This module handles all logic related to session management.
 * (create, load, rename, delete)
 */

import * as DOM from '../domElements.js';
import { state } from '../state.js';
import * as API from '../api.js';
import * as UI from '../ui.js';
import { renameSession, deleteSession } from '../api.js';
import { updateActiveSessionTitle } from '../ui.js';
import { renderAttachmentChips, initializeUploadCapabilities } from './chatDocumentUpload.js';
import { genieState, cleanupCoordination } from './genieHandler.js?v=3.4';
import { conversationAgentState, cleanupExecution } from './conversationAgentHandler.js?v=1.0';

// 🔥 DEBUG: Module load detection (v3.3 - Feb 13, 2026)
console.log('%c🔥 SESSION MANAGEMENT LOADED - VERSION 3.3 (NEW CODE)', 'background: #ff00ff; color: #fff; font-size: 16px; font-weight: bold; padding: 5px;');

// NOTE: createHistoricalGenieCard import removed - genie coordination cards
// are no longer rendered inline. Coordination details shown in Live Status window only.
// NOTE: createHistoricalAgentCard import removed - conversation agent cards
// are no longer rendered inline. Tool details shown in Live Status window only.

/**
 * Creates a new session, adds it to the list, and loads it.
 */
export async function handleStartNewSession() {
    // Hide welcome screen when starting a new session
    if (window.hideWelcomeScreen) {
        window.hideWelcomeScreen();
    }
    
    DOM.chatLog.innerHTML = '';
    DOM.statusWindowContent.innerHTML = '<p class="text-gray-400">Waiting for a new request...</p>';

    // Reset cost accumulator for new session
    if (window.sessionCostAccumulator) {
        window.sessionCostAccumulator.turn = 0;
        window.sessionCostAccumulator.session = 0;
        window.sessionCostAccumulator.strategic = 0;
        window.sessionCostAccumulator.tactical = 0;
        window.sessionCostAccumulator.strategicTurnIn = 0;
        window.sessionCostAccumulator.strategicTurnOut = 0;
        window.sessionCostAccumulator.strategicTurnCost = 0;
        window.sessionCostAccumulator.tacticalTurnIn = 0;
        window.sessionCostAccumulator.tacticalTurnOut = 0;
        window.sessionCostAccumulator.tacticalTurnCost = 0;
        window.sessionCostAccumulator.strategicSessionIn = 0;
        window.sessionCostAccumulator.strategicSessionOut = 0;
        window.sessionCostAccumulator.tacticalSessionIn = 0;
        window.sessionCostAccumulator.tacticalSessionOut = 0;
        window.sessionCostAccumulator.lastStmtPhase = null;
    }
    // Update cost display to reflect reset
    const turnCostElNew = document.getElementById('turn-cost-value');
    const sessionCostElNew = document.getElementById('session-cost-value');
    if (turnCostElNew) turnCostElNew.textContent = '$0.000000';
    if (sessionCostElNew) sessionCostElNew.textContent = '$0.000000';
    // Clear dual-model tooltips
    ['metric-card-statement','metric-card-turn','metric-card-session',
     'metric-card-turn-cost','metric-card-session-cost'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.removeAttribute('data-tooltip-html');
    });

    UI.updateTokenDisplay({ statement_input: 0, statement_output: 0, total_input: 0, total_output: 0 });
    UI.addMessage('assistant', "Starting a new conversation... Please wait.");
    UI.setThinkingIndicator(false);

    // --- MODIFICATION START: Hide profile override warning banner on new session ---
    const profileWarningBanner = document.getElementById('profile-override-warning-banner');
    if (profileWarningBanner) {
        profileWarningBanner.classList.add('hidden');
    }
    // Capture the active profile override BEFORE clearing it - needed for session primer
    // PRIORITY: Badge (current selection) > activeProfileOverrideId (last executed) > null
    let activeProfileOverrideId = null;

    // Check badge FIRST - it represents the user's current intent (what they typed/selected)
    // This takes priority over window.activeProfileOverrideId which is the last *executed* profile
    const tagBadge = document.getElementById('active-profile-tag');
    const isTagBadgeVisible = tagBadge && !tagBadge.classList.contains('hidden');

    if (isTagBadgeVisible && window.configState?.profiles) {
        // Get tag from badge's first span (the one containing "@TAG"), fallback to activeTagPrefix
        // Badge structure: <span>@TAG</span><span class="tag-remove">×</span>
        const tagSpan = tagBadge.querySelector('span:first-child');
        const badgeText = (tagSpan?.textContent || window.activeTagPrefix || '').trim();
        const tag = badgeText.replace('@', '').trim().toUpperCase();
        if (tag) {
            const overrideProfile = window.configState.profiles.find(p => p.tag === tag);
            if (overrideProfile) {
                activeProfileOverrideId = overrideProfile.id;
                console.log(`[Session Primer] Resolved tag badge @${tag} to profile ID: ${activeProfileOverrideId}`);
            }
        }
    }

    // Fall back to last executed profile if no badge is active
    if (!activeProfileOverrideId) {
        activeProfileOverrideId = window.activeProfileOverrideId || null;
    }

    // Clear the active profile override for autocomplete when starting a new session
    if (window.activeProfileOverrideId) {
        delete window.activeProfileOverrideId;
    }
    // --- MODIFICATION END ---

    // --- MODIFICATION START: Hide header buttons and clear turnId on new session ---
    if (DOM.headerReplayPlannedButton) {
        DOM.headerReplayPlannedButton.classList.add('hidden');
        DOM.headerReplayPlannedButton.dataset.turnId = '';
    }
    if (DOM.headerReplayOptimizedButton) {
        DOM.headerReplayOptimizedButton.classList.add('hidden');
        DOM.headerReplayOptimizedButton.dataset.turnId = '';
    }
    // --- MODIFICATION END ---

    // --- MODIFICATION START: Clear task ID display on new session ---
    UI.updateTaskIdDisplay(null);
    // --- MODIFICATION END ---
    
    // Clear persisted session ID when starting new session
    localStorage.removeItem('currentSessionId');
    state.sessionLoaded = false;

    try {
        console.log('[Session Primer] Starting new session with profile override ID:', activeProfileOverrideId);
        const data = await API.startNewSession(activeProfileOverrideId);
        console.log('[Session Primer] Session created, response:', { id: data.id, has_primer: !!data.session_primer });
        const sessionItem = UI.addSessionToList(data, true);
        DOM.sessionList.prepend(sessionItem);
        await handleLoadSession(data.id, true);

        // AUTO-EXECUTE PRIMER IF CONFIGURED AND ENABLED
        if (data.session_primer) {
            // Backward compatibility: convert string to new format
            const primerConfig = typeof data.session_primer === 'string'
                ? { enabled: true, mode: 'combined', statements: [data.session_primer] }
                : data.session_primer;

            // Only execute if explicitly enabled
            if (!primerConfig.enabled) {
                console.log('[Session Primer] Primer data exists but is disabled - skipping execution');
            } else {
                console.log(`[Session Primer] Executing ${primerConfig.statements.length} statement(s) in ${primerConfig.mode} mode`);

                // Import and use handleStreamRequest to execute the primer(s)
                const { handleStreamRequest } = await import('../eventHandlers.js?v=3.4');

                if (primerConfig.mode === 'combined') {
                    // Execute all statements as one merged query with clear separators
                    let mergedQuery;
                    if (primerConfig.statements.length === 1) {
                        // Single statement - no need for numbering
                        mergedQuery = primerConfig.statements[0];
                    } else {
                        // Multiple statements - add clear numbering and separators
                        mergedQuery = primerConfig.statements
                            .map((stmt, idx) => `[Statement ${idx + 1}]\n${stmt}`)
                            .join('\n\n---\n\n');
                    }
                    console.log('[Session Primer] Combined mode - merging statements into single query with separators');
                    const primerRequest = {
                        message: mergedQuery,
                        session_id: data.id,
                        is_session_primer: true
                    };

                    if (data.profile_override_id) {
                        primerRequest.profile_override_id = data.profile_override_id;
                    }

                    handleStreamRequest('/ask_stream', primerRequest);

                } else if (primerConfig.mode === 'individual') {
                    // Execute each statement separately in sequence
                    console.log('[Session Primer] Individual mode - executing statements sequentially');

                    // Simple sequential execution with delays
                    const executeNextStatement = (index) => {
                        if (index >= primerConfig.statements.length) {
                            console.log('[Session Primer] All statements executed');
                            return;
                        }

                        const statement = primerConfig.statements[index];
                        console.log(`[Session Primer] Executing statement ${index + 1}/${primerConfig.statements.length}`);

                        const primerRequest = {
                            message: statement,
                            session_id: data.id,
                            is_session_primer: true
                        };

                        if (data.profile_override_id) {
                            primerRequest.profile_override_id = data.profile_override_id;
                        }

                        // Execute statement (uses existing combined mode logic)
                        handleStreamRequest('/ask_stream', primerRequest);

                        // Wait 10 seconds before next statement (ensures completion)
                        if (index < primerConfig.statements.length - 1) {
                            setTimeout(() => executeNextStatement(index + 1), 10000);
                        }
                    };

                    // Start with first statement
                    executeNextStatement(0);
                }
            }
        }
    } catch (error) {
        UI.addMessage('assistant', `Failed to start a new session: ${error.message}`);
    } finally {
        DOM.userInput.focus();
    }
}

// ============================================================================
// Session UI State Capture/Restore Helpers (for stream isolation)
// ============================================================================

/**
 * Captures the current status window header DOM state as a plain object.
 * Used to snapshot the header before switching away from an active session.
 */
function _captureHeaderState() {
    return {
        statusTitle: (DOM.statusTitle || document.getElementById('status-title'))?.textContent || 'Live Status',
        taskIdValue: DOM.taskIdValue?.textContent || '',
        taskIdVisible: DOM.taskIdDisplay ? !DOM.taskIdDisplay.classList.contains('hidden') : false,
        promptNameHTML: document.getElementById('prompt-name-display')?.innerHTML || '',
        thinkingActive: DOM.thinkingIndicator ? !DOM.thinkingIndicator.classList.contains('hidden') : false,
        knowledgeBannerVisible: !document.getElementById('knowledge-banner')?.classList.contains('hidden'),
        knowledgeCollectionsList: document.getElementById('knowledge-collections-list')?.textContent || '',
        tokenData: {
            statementInput: document.getElementById('statement-input-tokens')?.textContent || '0',
            statementOutput: document.getElementById('statement-output-tokens')?.textContent || '0',
            turnInput: document.getElementById('turn-input-tokens')?.textContent || '0',
            turnOutput: document.getElementById('turn-output-tokens')?.textContent || '0',
            totalInput: document.getElementById('total-input-tokens')?.textContent || '0',
            totalOutput: document.getElementById('total-output-tokens')?.textContent || '0',
            turnLabel: document.getElementById('turn-token-label')?.textContent || 'Last Turn',
            normalVisible: !document.getElementById('token-normal-display')?.classList.contains('hidden'),
            awsVisible: !document.getElementById('token-aws-message')?.classList.contains('hidden'),
        },
        // Capture cost accumulator state for session switching isolation
        costAccumulator: window.sessionCostAccumulator ? {
            turn: window.sessionCostAccumulator.turn,
            session: window.sessionCostAccumulator.session,
            strategic: window.sessionCostAccumulator.strategic,
            tactical: window.sessionCostAccumulator.tactical,
            strategicTurnIn: window.sessionCostAccumulator.strategicTurnIn,
            strategicTurnOut: window.sessionCostAccumulator.strategicTurnOut,
            strategicTurnCost: window.sessionCostAccumulator.strategicTurnCost,
            tacticalTurnIn: window.sessionCostAccumulator.tacticalTurnIn,
            tacticalTurnOut: window.sessionCostAccumulator.tacticalTurnOut,
            tacticalTurnCost: window.sessionCostAccumulator.tacticalTurnCost,
            strategicSessionIn: window.sessionCostAccumulator.strategicSessionIn,
            strategicSessionOut: window.sessionCostAccumulator.strategicSessionOut,
            tacticalSessionIn: window.sessionCostAccumulator.tacticalSessionIn,
            tacticalSessionOut: window.sessionCostAccumulator.tacticalSessionOut,
            lastStmtPhase: window.sessionCostAccumulator.lastStmtPhase,
            lastTurnNumber: window.sessionCostAccumulator.lastTurnNumber,
            sessionId: window.sessionCostAccumulator.sessionId,
        } : null,
    };
}

/**
 * Captures per-execution state variables from the global state object.
 */
function _captureExecutionState() {
    return {
        currentStatusId: state.currentStatusId,
        isRestTaskActive: state.isRestTaskActive,
        activeRestTaskId: state.activeRestTaskId,
        isConversationAgentActive: state.isConversationAgentActive,
        isGenieCoordinationActive: state.isGenieCoordinationActive,
        isInFastPath: state.isInFastPath,
        currentTaskId: state.currentTaskId,
        currentTurnNumber: state.currentTurnNumber,
        currentProvider: state.currentProvider,
        currentModel: state.currentModel,
        pendingSubtaskPlanningEvents: [...state.pendingSubtaskPlanningEvents],
        pendingKnowledgeRetrievalEvent: state.pendingKnowledgeRetrievalEvent
            ? { ...state.pendingKnowledgeRetrievalEvent } : null,
        lastRagCaseData: state.lastRagCaseData
            ? { ...state.lastRagCaseData } : null,
    };
}

/**
 * Captures module-level state from genie and conversation agent handler modules.
 */
function _captureHandlerState() {
    return {
        genie: {
            activeCoordination: genieState.activeCoordination,
            slaveProgress: JSON.parse(JSON.stringify(genieState.slaveProgress)),
            startTime: genieState.startTime,
            availableProfiles: [...(genieState.availableProfiles || [])],
            profilesInvoked: [...(genieState.profilesInvoked || [])],
            profileTag: genieState.profileTag,
            selectedProfiles: [...(genieState.selectedProfiles || [])],
            synthesisStarted: genieState.synthesisStarted || false,
            profilesConsulted: [...(genieState.profilesConsulted || [])],
        },
        conversationAgent: {
            activeExecution: conversationAgentState.activeExecution,
            toolProgress: JSON.parse(JSON.stringify(conversationAgentState.toolProgress)),
            startTime: conversationAgentState.startTime,
            availableTools: [...(conversationAgentState.availableTools || [])],
            toolsUsed: [...(conversationAgentState.toolsUsed || [])],
            profileTag: conversationAgentState.profileTag,
        },
    };
}

/**
 * Restores status window header DOM state from a snapshot.
 */
function _restoreHeaderState(h) {
    const statusTitle = DOM.statusTitle || document.getElementById('status-title');
    if (statusTitle) statusTitle.textContent = h.statusTitle;

    if (DOM.taskIdValue) DOM.taskIdValue.textContent = h.taskIdValue;
    if (DOM.taskIdDisplay) DOM.taskIdDisplay.classList.toggle('hidden', !h.taskIdVisible);

    const promptNameDisplay = document.getElementById('prompt-name-display');
    if (promptNameDisplay) promptNameDisplay.innerHTML = h.promptNameHTML;

    // Thinking indicator
    if (h.thinkingActive) {
        DOM.thinkingIndicator?.classList.remove('hidden');
        DOM.thinkingIndicator?.classList.add('flex');
        DOM.promptNameDisplay?.classList.add('hidden');
    } else {
        DOM.thinkingIndicator?.classList.add('hidden');
        DOM.thinkingIndicator?.classList.remove('flex');
        DOM.promptNameDisplay?.classList.remove('hidden');
    }

    // Knowledge banner
    const knowledgeBanner = document.getElementById('knowledge-banner');
    if (knowledgeBanner) knowledgeBanner.classList.toggle('hidden', !h.knowledgeBannerVisible);
    const collectionsList = document.getElementById('knowledge-collections-list');
    if (collectionsList) collectionsList.textContent = h.knowledgeCollectionsList;

    // Token display (restore raw textContent values)
    const t = h.tokenData;
    if (t) {
        const el = (id) => document.getElementById(id);
        if (el('statement-input-tokens')) el('statement-input-tokens').textContent = t.statementInput;
        if (el('statement-output-tokens')) el('statement-output-tokens').textContent = t.statementOutput;
        if (el('turn-input-tokens')) el('turn-input-tokens').textContent = t.turnInput;
        if (el('turn-output-tokens')) el('turn-output-tokens').textContent = t.turnOutput;
        if (el('total-input-tokens')) el('total-input-tokens').textContent = t.totalInput;
        if (el('total-output-tokens')) el('total-output-tokens').textContent = t.totalOutput;
        const turnLabel = el('turn-token-label');
        if (turnLabel) turnLabel.textContent = t.turnLabel;
        el('token-normal-display')?.classList.toggle('hidden', !t.normalVisible);
        el('token-aws-message')?.classList.toggle('hidden', !t.awsVisible);
    }

    // Restore cost accumulator (critical for session switching isolation)
    if (h.costAccumulator && window.sessionCostAccumulator) {
        Object.assign(window.sessionCostAccumulator, h.costAccumulator);
        console.log(`[Cached Restore] Restored cost accumulator: Turn=$${h.costAccumulator.turn.toFixed(6)}, Session=$${h.costAccumulator.session.toFixed(6)}`);

        // Update cost display immediately
        const turnCostEl = document.getElementById('turn-cost-value');
        const sessionCostEl = document.getElementById('session-cost-value');
        if (turnCostEl) turnCostEl.textContent = `$${h.costAccumulator.turn.toFixed(6)}`;
        if (sessionCostEl) sessionCostEl.textContent = `$${h.costAccumulator.session.toFixed(6)}`;
    }
}

/**
 * Restores per-execution state variables from a snapshot.
 * Phase container DOM refs are reset to null (stale after innerHTML restore).
 */
function _restoreExecutionState(s) {
    state.currentStatusId = s.currentStatusId;
    state.isRestTaskActive = s.isRestTaskActive;
    state.activeRestTaskId = s.activeRestTaskId;
    state.isConversationAgentActive = s.isConversationAgentActive;
    state.isGenieCoordinationActive = s.isGenieCoordinationActive;
    state.isInFastPath = s.isInFastPath;
    state.currentTaskId = s.currentTaskId;
    state.currentProvider = s.currentProvider;
    state.currentModel = s.currentModel;
    state.currentTurnNumber = s.currentTurnNumber || null;
    state.pendingSubtaskPlanningEvents = s.pendingSubtaskPlanningEvents || [];
    state.pendingKnowledgeRetrievalEvent = s.pendingKnowledgeRetrievalEvent || null;
    state.lastRagCaseData = s.lastRagCaseData || null;
    // Phase containers: stale DOM refs after innerHTML restore - reset to null.
    // New events will render at root level, which is acceptable.
    state.currentPhaseContainerEl = null;
    state.phaseContainerStack = [];
}

/**
 * Restores module-level handler state from a snapshot.
 */
function _restoreHandlerState(h) {
    if (h.genie) {
        Object.assign(genieState, {
            activeCoordination: h.genie.activeCoordination,
            slaveProgress: JSON.parse(JSON.stringify(h.genie.slaveProgress)),
            startTime: h.genie.startTime,
            availableProfiles: [...h.genie.availableProfiles],
            profilesInvoked: [...h.genie.profilesInvoked],
            profileTag: h.genie.profileTag,
            selectedProfiles: [...(h.genie.selectedProfiles || [])],
            synthesisStarted: h.genie.synthesisStarted || false,
            profilesConsulted: [...(h.genie.profilesConsulted || [])],
        });
    }
    if (h.conversationAgent) {
        Object.assign(conversationAgentState, {
            activeExecution: h.conversationAgent.activeExecution,
            toolProgress: JSON.parse(JSON.stringify(h.conversationAgent.toolProgress)),
            startTime: h.conversationAgent.startTime,
            availableTools: [...h.conversationAgent.availableTools],
            toolsUsed: [...h.conversationAgent.toolsUsed],
            profileTag: h.conversationAgent.profileTag,
        });
    }
}

/**
 * Replays buffered REST events into the Live Status window for a child session.
 * Contains its own event-type routing logic (mirrors _dispatchRestEvent from
 * notifications.js) to avoid circular dependency issues. The replay version
 * suppresses indicator blinks and manages state flags directly during replay.
 *
 * Called when switching to a session with an active REST event buffer but no cached UI.
 * @param {string} sessionId - The session ID whose buffer to replay.
 */
function _replayRestEventBuffer(sessionId) {
    const buffer = state.restEventBuffer[sessionId];
    if (!buffer || buffer.events.length === 0) return;

    // Reset status window for replay
    DOM.statusWindowContent.innerHTML = '';
    const statusTitle = DOM.statusTitle || document.getElementById('status-title');
    if (statusTitle) statusTitle.textContent = 'Live Status';

    // Suppress indicator blinks during replay
    state.isViewingHistoricalTurn = true;

    for (const event of buffer.events) {
        const eventType = event.type;
        if (!eventType) continue;

        // Skip transient events that don't need replay
        if (eventType === 'status_indicator_update') continue;

        // Token updates → direct to token display
        if (eventType === 'token_update') {
            UI.updateTokenDisplay(event);
            continue;
        }

        // Session model updates → metadata only
        if (eventType === 'session_model_update') {
            const payload = event.payload || event;
            state.currentProvider = payload.provider || state.currentProvider;
            state.currentModel = payload.model || state.currentModel;
            UI.updateStatusPromptName(payload.provider, payload.model);
            continue;
        }

        // RAG retrieval → store data without blink
        if (eventType === 'rag_retrieval') {
            state.lastRagCaseData = event;
            continue;
        }

        // Knowledge retrieval → update indicator without blink
        if (eventType === 'knowledge_retrieval') {
            const collections = event.data?.collections || [];
            const documentCount = event.data?.document_count || 0;
            UI.updateKnowledgeIndicator(collections, documentCount);
        }

        // --- Conversation Agent events (conversation_with_tools profile) ---
        if (eventType.startsWith('conversation_agent') ||
            eventType.startsWith('conversation_llm') ||
            eventType.startsWith('conversation_tool')) {
            const payload = event.payload || event;
            // Set state flags during replay
            if (eventType === 'conversation_agent_start') state.isConversationAgentActive = true;
            if (eventType === 'conversation_agent_complete') state.isConversationAgentActive = false;
            UI.updateStatusWindow({
                step: eventType, details: payload, type: eventType
            }, eventType === 'conversation_agent_complete', 'conversation_agent');
            continue;
        }

        // --- Knowledge Retrieval events (rag_focused + conversation_with_tools) ---
        if (eventType.startsWith('knowledge_') ||
            eventType === 'rag_llm_step' ||
            eventType === 'knowledge_search_complete') {
            UI.updateStatusWindow({
                step: eventType, details: event.payload || event, type: eventType
            }, false, 'knowledge_retrieval');
            continue;
        }

        // --- LLM execution events (llm_only profile) ---
        if (eventType === 'llm_execution' || eventType === 'llm_execution_complete') {
            UI.updateStatusWindow({
                step: eventType, details: event.payload || event, type: eventType
            }, eventType === 'llm_execution_complete', 'conversation_agent');
            continue;
        }

        // --- Lifecycle events (all profile types) ---
        if (eventType === 'execution_start' || eventType === 'execution_complete' ||
            eventType === 'execution_error' || eventType === 'execution_cancelled') {
            const payload = event.payload || event;
            // Capture turn number from execution_start during replay
            if (eventType === 'execution_start' && payload.turn_id) {
                state.currentTurnNumber = payload.turn_id;
            }
            const isFinal = eventType !== 'execution_start';
            UI.updateStatusWindow({
                step: eventType, details: payload, type: eventType
            }, isFinal, 'lifecycle');
            continue;
        }

        // --- Session name events ---
        if (eventType === 'session_name' || eventType === 'session_name_generation_start' ||
            eventType === 'session_name_generation_complete') {
            UI.updateStatusWindow(event, false, 'session_name');
            continue;
        }

        // --- Default: planner/executor events (tool_enabled profile) → 'rest' source ---
        const isFinal = (eventType === 'final_answer' || eventType === 'error' || eventType === 'cancelled');
        UI.updateStatusWindow(event, isFinal, 'rest', buffer.taskId);
    }

    state.isViewingHistoricalTurn = false;

    // Set execution state based on buffer completeness
    if (!buffer.isComplete) {
        state.isRestTaskActive = true;
        state.activeRestTaskId = buffer.taskId;
        UI.setExecutionState(true);
    }
}

/**
 * Loads a specific session's history and data into the UI.
 * @param {string} sessionId - The ID of the session to load.
 * @param {boolean} [isNewSession=false] - Flag to skip redundant checks if it's a new session.
 */
export async function handleLoadSession(sessionId, isNewSession = false) {
    // Skip loading only if session ID matches AND session is already loaded in UI
    if (state.currentSessionId === sessionId && state.sessionLoaded && !isNewSession) return;

    // --- Session stream isolation: save current session's full UI state before switching ---
    // If the current session has an active stream, cache its DOM state, header state,
    // execution mode flags, and handler module state so we can restore everything
    // instantly when the user switches back (avoids server reload).
    const previousSessionId = state.currentSessionId;
    if (previousSessionId && (state.activeStreamSessions.has(previousSessionId) || state.activeRestSessions.has(previousSessionId))) {
        state.sessionUiCache[previousSessionId] = {
            chatHTML: DOM.chatLog.innerHTML,
            statusHTML: DOM.statusWindowContent.innerHTML,
            headerState: _captureHeaderState(),
            executionState: _captureExecutionState(),
            handlerState: _captureHandlerState(),
        };
        console.log(`[handleLoadSession] Cached full UI state for active session ${previousSessionId}`);
    }

    // Close canvas split panel when switching sessions (prevents cross-session contamination)
    try {
        const splitPanel = document.getElementById('canvas-split-panel');
        if (splitPanel && splitPanel.classList.contains('canvas-split--open')) {
            const { closeSplitPanel } = await import('/api/v1/components/canvas/renderer');
            closeSplitPanel();
        }
    } catch (e) { /* canvas component may not be loaded */ }

    // Close KG split panel when switching sessions
    try {
        const kgPanel = document.getElementById('kg-split-panel');
        if (kgPanel && kgPanel.classList.contains('kg-split--open')) {
            const { closeKGSplitPanel } = await import('/api/v1/components/knowledge_graph/renderer');
            closeKGSplitPanel();
        }
    } catch (e) { /* knowledge_graph component may not be loaded */ }

    // --- MODIFICATION START: Clear task ID display on session load ---
    UI.updateTaskIdDisplay(null);
    // --- MODIFICATION END ---

    // --- MODIFICATION START: Remove highlight on load ---
    UI.removeHighlight(sessionId);
    // --- MODIFICATION END ---

    // --- MODIFICATION START: Hide profile override warning banner when switching sessions ---
    const profileWarningBanner = document.getElementById('profile-override-warning-banner');
    if (profileWarningBanner) {
        profileWarningBanner.classList.add('hidden');
    }
    // --- MODIFICATION END ---

    // --- Session stream isolation: fast-path restore for sessions with active streams ---
    // If the target session has a running stream AND cached UI state, restore from
    // cache instead of reloading from the server. This avoids unnecessary API calls
    // and preserves the live execution context (status window header, content, chat progress).
    const cached = state.sessionUiCache[sessionId];
    if (cached && (state.activeStreamSessions.has(sessionId) || state.activeRestSessions.has(sessionId))) {
        console.log(`[handleLoadSession] Restoring cached UI for active session ${sessionId}`);
        state.currentSessionId = sessionId;
        state.sessionLoaded = true;
        localStorage.setItem('currentSessionId', sessionId);

        // Restore cached DOM state (chat canvas + status window content)
        DOM.chatLog.innerHTML = cached.chatHTML;
        DOM.statusWindowContent.innerHTML = cached.statusHTML;

        // Restore full status window header state (title, tokens, model, knowledge, thinking)
        if (cached.headerState) _restoreHeaderState(cached.headerState);

        // Restore execution mode state variables (status ID, mode flags, provider/model)
        if (cached.executionState) _restoreExecutionState(cached.executionState);

        // Restore handler module state (genie coordination, conversation agent progress)
        if (cached.handlerState) _restoreHandlerState(cached.handlerState);

        UI.setExecutionState(true);

        // Update sidebar highlighting and session title
        document.querySelectorAll('.session-item').forEach(item => {
            item.classList.toggle('active', item.dataset.sessionId === sessionId);
        });
        const activeItem = document.getElementById(`session-${sessionId}`);
        const nameSpan = activeItem ? activeItem.querySelector('.session-name-span') : null;
        if (nameSpan) {
            updateActiveSessionTitle(nameSpan.textContent.trim());
        }

        DOM.userInput.focus();
        return;
    }

    try {
        const data = await API.loadSession(sessionId);
        state.currentSessionId = sessionId;
        state.sessionLoaded = true; // Mark session as loaded in UI

        // Persist session ID to localStorage for browser refresh persistence
        localStorage.setItem('currentSessionId', sessionId);

        state.currentProvider = data.provider || state.currentProvider;
        state.currentModel = data.model || state.currentModel;

        // --- MODIFICATION START: Restore feedback state from session data ---
        if (data.feedback_by_turn) {
            state.feedbackByTurn = { ...data.feedback_by_turn };
        } else {
            state.feedbackByTurn = {};
        }
        // --- MODIFICATION END ---

        // Hide welcome screen when loading a session with history
        if (window.hideWelcomeScreen) {
            window.hideWelcomeScreen();
        }

        // Initialize cost accumulator and fetch last turn costs
        // This ensures costs display correctly immediately when switching between sessions
        if (window.sessionCostAccumulator) {
            window.sessionCostAccumulator.turn = 0;
            window.sessionCostAccumulator.session = 0;
            window.sessionCostAccumulator.strategic = 0;
            window.sessionCostAccumulator.tactical = 0;
            window.sessionCostAccumulator.strategicTurnIn = 0;
            window.sessionCostAccumulator.strategicTurnOut = 0;
            window.sessionCostAccumulator.strategicTurnCost = 0;
            window.sessionCostAccumulator.tacticalTurnIn = 0;
            window.sessionCostAccumulator.tacticalTurnOut = 0;
            window.sessionCostAccumulator.tacticalTurnCost = 0;
            window.sessionCostAccumulator.strategicSessionIn = 0;
            window.sessionCostAccumulator.strategicSessionOut = 0;
            window.sessionCostAccumulator.tacticalSessionIn = 0;
            window.sessionCostAccumulator.tacticalSessionOut = 0;
            window.sessionCostAccumulator.lastStmtPhase = null;
        }

        // Fetch last turn's cost data to initialize display
        // This provides immediate accurate costs when switching sessions
        const workflowHistory = data.last_turn_data?.workflow_history || [];
        const lastTurn = workflowHistory.length > 0 ? workflowHistory[workflowHistory.length - 1] : null;

        if (lastTurn) {
            // Use backend-provided costs if available (for sessions created after the fix)
            const lastTurnCost = lastTurn.turn_cost || 0;
            const sessionCost = lastTurn.session_cost_usd || 0;

            if (window.sessionCostAccumulator) {
                window.sessionCostAccumulator.turn = lastTurnCost;
                window.sessionCostAccumulator.session = sessionCost;
            }

            console.log(`[Session Load] Initialized costs from last turn: Turn=$${lastTurnCost.toFixed(6)}, Session=$${sessionCost.toFixed(6)}`);
        }

        // Update cost display immediately
        const turnCostEl = document.getElementById('turn-cost-value');
        const sessionCostEl = document.getElementById('session-cost-value');
        const displayTurnCost = window.sessionCostAccumulator?.turn || 0;
        const displaySessionCost = window.sessionCostAccumulator?.session || 0;

        if (turnCostEl) turnCostEl.textContent = `$${displayTurnCost.toFixed(6)}`;
        if (sessionCostEl) sessionCostEl.textContent = `$${displaySessionCost.toFixed(6)}`;

        // Clear dual-model tooltips
        ['metric-card-statement','metric-card-turn','metric-card-session',
         'metric-card-turn-cost','metric-card-session-cost'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.removeAttribute('data-tooltip-html');
        });

        DOM.chatLog.innerHTML = '';
        if (data.history && data.history.length > 0) {
            // --- MODIFICATION START: Pass turn_id and isValid during history load ---
            // NOTE: Genie coordination cards and conversation agent cards are NO LONGER
            // rendered inline in chat. All execution details (tool calls, slave invocations)
            // are shown in the Live Status window only. This keeps the conversation pane
            // clean and focused on Q&A. Historical execution data is available when
            // clicking on a turn to reload its plan/trace in the status panel.

            // Simulate turn IDs based on message pairs for existing sessions
            let currentTurnId = 1;
            for (let i = 0; i < data.history.length; i++) {
                const msg = data.history[i];
                // Default to true if isValid flag is missing (for older sessions)
                const isValid = msg.isValid === undefined ? true : msg.isValid;
                // Get profile_tag from message (for user messages)
                const profileTag = msg.profile_tag || null;
                // Get is_session_primer flag (defaults to false for older sessions)
                const isSessionPrimer = msg.is_session_primer || false;

                if (msg.role === 'assistant') {
                    // Pass the calculated turn ID, validity, and primer flag for assistant messages
                    UI.addMessage(msg.role, msg.content, currentTurnId, isValid, msg.source, null, isSessionPrimer);
                    currentTurnId++; // Increment turn ID after an assistant message
                } else {
                    // User messages: include attachment chips if present
                    let displayContent = msg.content;
                    if (msg.attachments && msg.attachments.length > 0) {
                        displayContent = msg.content + renderAttachmentChips(msg.attachments);
                    }
                    UI.addMessage(msg.role, displayContent, null, isValid, msg.source, profileTag, isSessionPrimer, msg.extension_specs || null, msg.skill_specs || null);
                }
            }
            // --- MODIFICATION END ---

            // --- Re-render extension download cards for chat_append results ---
            // Extension cards (e.g., #pdf download) are rendered into the DOM during
            // live execution but NOT persisted in session_history messages. The data IS
            // persisted in workflow_history[turn].extension_results. Re-render them here
            // so download cards survive page reloads and session switches.
            const wfHistory = data.workflow_history || [];
            for (const turn of wfHistory) {
                const extResults = turn.extension_results;
                if (!extResults || typeof extResults !== 'object') continue;

                const turnId = turn.turn || turn.turn_id || turn.turn_number;
                if (!turnId) continue;

                for (const [extName, result] of Object.entries(extResults)) {
                    if (!result.success || !result.content) continue;
                    const target = result.output_target || 'silent';
                    if (target !== 'chat_append') continue;

                    // Find the assistant message bubble for this turn via its badge.
                    // Note: .clickable-avatar[data-turn-id] matches the USER avatar (not assistant).
                    // The assistant badge (.assistant-badge) is appended to the assistant's wrapper.
                    const badge = DOM.chatLog.querySelector(`.assistant-badge[data-turn-id="${turnId}"]`);
                    if (!badge) continue;
                    const msgBubble = badge.closest('.message-bubble');
                    const msgContent = msgBubble?.querySelector('.message-content');
                    if (!msgContent) continue;

                    // Use the existing card builder (exposed on window by eventHandlers.js)
                    if (window._isExtensionBinaryContent && window._isExtensionBinaryContent(result)) {
                        const cardHtml = window._buildExtensionDownloadCard(extName, result);
                        msgContent.insertAdjacentHTML('beforeend', cardHtml);
                    } else {
                        // Non-binary chat_append (e.g., JSON text output)
                        const cardHtml = `
                            <div class="extension-output mt-3 p-3 rounded-lg" data-ext-name="${extName}"
                                 style="background: rgba(251, 191, 36, 0.05); border: 1px solid rgba(251, 191, 36, 0.15);">
                                <div class="flex items-center gap-2 mb-2">
                                    <span class="text-xs font-semibold px-1.5 py-0.5 rounded"
                                          style="background: rgba(251, 191, 36, 0.15); color: #fbbf24; font-family: 'JetBrains Mono', monospace;">#${extName}</span>
                                    <span class="text-xs text-gray-500">${result.content_type}</span>
                                </div>
                                <pre class="text-xs text-gray-300 whitespace-pre-wrap overflow-auto max-h-48"
                                     style="font-family: 'JetBrains Mono', monospace;">${
                                    typeof result.content === 'object' ? JSON.stringify(result.content, null, 2) : result.content
                                }</pre>
                            </div>`;
                        msgContent.insertAdjacentHTML('beforeend', cardHtml);
                    }
                }
            }

        } else {
             UI.addMessage('assistant', "I'm ready to help. How can I assist you with your Teradata system today?");
        }

        // Scroll to the beginning of the last assistant answer (not the bottom of chat).
        // Uses 'instant' to override any pending smooth scrolls from addMessage() calls above.
        const assistantMsgs = DOM.chatLog.querySelectorAll('.message-bubble:not(.justify-end)');
        const lastAssistant = assistantMsgs.length > 0 ? assistantMsgs[assistantMsgs.length - 1] : null;
        if (lastAssistant) {
            lastAssistant.scrollIntoView({ behavior: 'instant', block: 'start' });
        }

        // Explicitly pass all token fields as 0 for empty sessions to prevent stale values from previous session
        // Pass isHistorical=true to bypass terminal event detection and force normal update (reset to 0)
        console.log(`%c[Session Load] 🔍 Calling updateTokenDisplay for session ${sessionId}`, 'background: #ff00ff; color: #fff; font-weight: bold;');
        console.log(`  data.input_tokens: ${data.input_tokens}`);
        console.log(`  data.output_tokens: ${data.output_tokens}`);
        console.log(`  Passing isHistorical=true to bypass terminal event detection`);

        UI.updateTokenDisplay({
            statement_input: 0,           // Reset statement tokens (prevents stale values)
            statement_output: 0,
            turn_input: 0,                // Reset turn tokens
            turn_output: 0,
            total_input: data.input_tokens,   // Use backend data for session totals
            total_output: data.output_tokens
        }, true);  // isHistorical=true bypasses terminal event detection, forces normal update

        // --- MODIFICATION START: Refresh feedback button states after loading history ---
        UI.refreshFeedbackButtons();
        // --- MODIFICATION END ---

        document.querySelectorAll('.session-item').forEach(item => {
            item.classList.toggle('active', item.dataset.sessionId === sessionId);
        });

        // --- NEW: Update active session title (derive from list item since name not in loadSession response) ---
        const activeItem = document.getElementById(`session-${sessionId}`);
        const nameSpan = activeItem ? activeItem.querySelector('.session-name-span') : null;
        if (nameSpan) {
            updateActiveSessionTitle(nameSpan.textContent.trim());
        }

        // --- MODIFICATION START ---
        // Explicitly update the models/profile tags for the loaded session in the UI
        UI.updateSessionModels(sessionId, data.models_used, data.profile_tags_used);

        // Get dual-model info from session data OR profile configuration (for new sessions)
        let dualModelInfo = data.dual_model_info;
        console.log('[Session Load] 🔍 Checking dual-model:', {
            sessionDualModelInfo: dualModelInfo,
            profileId: data.profile_id,
            hasConfigState: !!window.configState,
            hasProfiles: !!window.configState?.profiles,
            hasLLMConfigs: !!window.configState?.llmConfigurations
        });

        // For new sessions without dual_model_info, check the profile configuration
        if (!dualModelInfo && data.profile_id && window.configState?.profiles) {
            const currentProfile = window.configState.profiles.find(p => p.id === data.profile_id);
            console.log('[Session Load] Found profile:', currentProfile?.name, {
                hasDualModelConfig: !!currentProfile?.dualModelConfig,
                strategicModelId: currentProfile?.dualModelConfig?.strategicModelId,
                tacticalModelId: currentProfile?.dualModelConfig?.tacticalModelId
            });

            if (currentProfile?.dualModelConfig && (currentProfile.dualModelConfig.strategicModelId || currentProfile.dualModelConfig.tacticalModelId)) {
                // Profile has dual-model configured - extract model info from LLM configs
                const strategicConfig = window.configState.llmConfigurations?.find(c => c.id === currentProfile.dualModelConfig.strategicModelId);
                const tacticalConfig = window.configState.llmConfigurations?.find(c => c.id === currentProfile.dualModelConfig.tacticalModelId);
                console.log('[Session Load] LLM Configs:', {
                    strategic: strategicConfig ? `${strategicConfig.provider}/${strategicConfig.model}` : 'NOT FOUND',
                    tactical: tacticalConfig ? `${tacticalConfig.provider}/${tacticalConfig.model}` : 'NOT FOUND'
                });

                if (strategicConfig && tacticalConfig) {
                    dualModelInfo = {
                        strategicProvider: strategicConfig.provider,
                        strategicModel: strategicConfig.model,
                        tacticalProvider: tacticalConfig.provider,
                        tacticalModel: tacticalConfig.model
                    };
                    console.log('[Session Load] ✅ Extracted dual-model info from profile config:', dualModelInfo);
                }
            }
        }

        // Store dual-model info in state for use throughout the session
        state.currentDualModelInfo = dualModelInfo;
        console.log('[Session Load] Stored in state.currentDualModelInfo:', state.currentDualModelInfo);
        // This will reset the status display to the globally configured model, including dual-model info
        UI.updateStatusPromptName(data.provider, data.model, false, dualModelInfo);
        // --- MODIFICATION END ---

        // Initialize upload capabilities for the loaded session's provider
        initializeUploadCapabilities(sessionId);

        // Preset profile tag badge based on session's first profile
        // Only show badge if session has actual profile usage history (not for new/unused sessions)
        const sessionProfileTag = (data.profile_tags_used && data.profile_tags_used.length > 0)
            ? data.profile_tags_used[0]
            : null;

        if (sessionProfileTag && window.configState?.profiles) {
            const tagUpper = sessionProfileTag.toUpperCase();
            const matchedProfile = window.configState.profiles.find(
                p => p.tag && p.tag.toUpperCase() === tagUpper
            );
            if (matchedProfile && typeof window.showActiveTagBadge === 'function') {
                window.activeTagPrefix = `@${matchedProfile.tag} `;
                window.showActiveTagBadge(matchedProfile);
            }
        } else if (!isNewSession) {
            // Switching to an existing session with no profile history — clear stale badge
            // When isNewSession=true, preserve any manually-selected override badge
            window.activeTagPrefix = '';
            if (typeof window.hideActiveTagBadge === 'function') window.hideActiveTagBadge();
        }

        // Reset execution state for the loaded session (clean slate)
        // If this session has an active stream, processStream will resume rendering
        // events and manage execution state from that point forward.
        UI.setExecutionState(false);
        UI.setThinkingIndicator(false);

        // --- Reset status window to idle state for loaded (non-streaming) session ---
        DOM.statusWindowContent.innerHTML = '<p class="text-gray-400">Waiting for a new request...</p>';
        const statusTitle = DOM.statusTitle || document.getElementById('status-title');
        if (statusTitle) statusTitle.textContent = 'Live Status';

        // Reset knowledge banner
        const knowledgeBanner = document.getElementById('knowledge-banner');
        if (knowledgeBanner) knowledgeBanner.classList.add('hidden');

        // Reset execution mode flags to clean slate
        state.currentStatusId = 0;
        state.isRestTaskActive = false;
        state.activeRestTaskId = null;
        state.isConversationAgentActive = false;
        state.isGenieCoordinationActive = false;
        state.isInFastPath = false;
        state.currentPhaseContainerEl = null;
        state.phaseContainerStack = [];
        state.pendingSubtaskPlanningEvents = [];
        state.pendingKnowledgeRetrievalEvent = null;
        state.currentTurnNumber = null;

        // Reset handler module state for idle session
        cleanupCoordination();
        cleanupExecution();

        // Check if this session has an active REST event buffer (e.g., Genie child during execution)
        const restBuffer = state.restEventBuffer[sessionId];
        if (restBuffer && !restBuffer.isComplete && state.activeRestSessions.has(sessionId)) {
            // Active REST execution: replay buffered events into status window
            _replayRestEventBuffer(sessionId);
        } else {
            // Auto-load last turn's execution data into the Live Status window.
            // Uses dynamic import() to avoid circular dependency with eventHandlers.js
            // (eventHandlers.js already imports from sessionManagement.js).
            const allAvatars = DOM.chatLog.querySelectorAll('.clickable-avatar[data-turn-id]');
            const lastAvatar = allAvatars.length > 0 ? allAvatars[allAvatars.length - 1] : null;
            if (lastAvatar) {
                import('../eventHandlers.js').then(({ handleReloadPlanClick }) => {
                    handleReloadPlanClick(lastAvatar);
                });
            }
            // Clean up completed buffers on visit (server has the data now)
            if (restBuffer) {
                delete state.restEventBuffer[sessionId];
            }
        }

        // Mark conversation as initialized after successful session load
        if (window.__conversationInitState) {
            window.__conversationInitState.initialized = true;
            window.__conversationInitState.lastInitTimestamp = Date.now();
            window.__conversationInitState.inProgress = false;
            console.log('[handleLoadSession] Marked conversation as initialized');
        }
    } catch (error) {
        UI.addMessage('assistant', `Error loading session: ${error.message}`);
        throw error;  // Re-throw so callers can implement fallback logic
    } finally {
        DOM.userInput.focus();
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
        if (state.currentSessionId === sessionId) {
            updateActiveSessionTitle(newName);
        }
    } catch (error) {
        console.error(`Failed to rename session ${sessionId}:`, error);
        inputElement.style.borderColor = 'red';
        inputElement.disabled = false;
        // Revert to original name and exit edit mode on API error
        UI.exitSessionEditMode(inputElement, originalName);
    }
}

// --- NEW: Rename active session directly (used by header title editing) ---
export async function renameActiveSession(newName) {
    if (!state.currentSessionId) return;
    const trimmed = (newName || '').trim();
    if (!trimmed) return;
    try {
        await renameSession(state.currentSessionId, trimmed);
        updateActiveSessionTitle(trimmed);
        UI.updateSessionListItemName(state.currentSessionId, trimmed);
        UI.moveSessionToTop(state.currentSessionId);
    } catch (error) {
        console.error('Failed to rename active session via header:', error);
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

/**
 * Handles the click event for the delete session button.
 * @param {HTMLButtonElement} deleteButton - The delete button element that was clicked.
 */
export async function handleDeleteSessionClick(deleteButton) {
    const sessionItem = deleteButton.closest('.session-item');
    if (!sessionItem) return;

    const sessionId = sessionItem.dataset.sessionId;
    const sessionName = sessionItem.querySelector('.session-name-span')?.textContent || 'this session';

    // Check if this is a Genie parent with child sessions
    const isGenieParent = sessionItem.classList.contains('genie-master-session');
    let confirmMessage = `Are you sure you want to permanently delete '${sessionName}'? This action cannot be undone.`;
    if (isGenieParent) {
        const childCount = document.querySelectorAll(`[data-genie-parent-id="${sessionId}"]`).length;
        if (childCount > 0) {
            confirmMessage = `Are you sure you want to permanently delete '${sessionName}' and its ${childCount} child session${childCount > 1 ? 's' : ''}? This action cannot be undone.`;
        }
    }

    UI.showConfirmation(
        'Delete Session?',
        confirmMessage,
        async () => {
            try {
                const result = await deleteSession(sessionId);
                const deletedChildren = result?.deleted_children || [];
                const wasActiveSession = state.currentSessionId === sessionId || deletedChildren.includes(state.currentSessionId);

                // Refresh the session list to show archived state
                // This replaces the old approach of just removing from DOM
                try {
                    const { refreshSessionsList } = await import('./configManagement.js');
                    await refreshSessionsList();
                    console.log('[Session Delete] Session list refreshed after archiving');
                } catch (refreshError) {
                    console.error('[Session Delete] Failed to refresh sessions list:', refreshError);
                    // Fallback: remove from DOM if refresh fails
                    UI.removeSessionAndDescendantsFromList(sessionId, deletedChildren);
                }

                // Check if the currently active session was deleted (parent or child)
                if (wasActiveSession) {
                    try {
                        const sessionsResult = await API.loadSessions(0, 0); // Load all sessions (limit=0)
                        const remainingSessions = sessionsResult.sessions || [];
                        // Filter out archived sessions
                        const activeSessions = remainingSessions ? remainingSessions.filter(s => !s.archived) : [];

                        if (activeSessions && activeSessions.length > 0) {
                            // The API returns sessions sorted by most recent first.
                            const nextSessionId = activeSessions[0].id;
                            await handleLoadSession(nextSessionId);
                        } else {
                            await handleStartNewSession();
                        }
                    } catch (error) {
                        console.error('Error handling session switch after deletion:', error);
                        UI.addMessage('assistant', `Could not switch to another session. Please select one manually or start a new one. ${error.message}`);
                        // As a fallback, create a new session if the session loading fails
                        await handleStartNewSession();
                    }
                }
            } catch (error) {
                console.error(`Failed to delete session ${sessionId}:`, error);
                UI.addMessage('assistant', `Error: Could not delete session '${sessionName}'. ${error.message}`);
            }
        }
    );
}

/**
 * Initialize utility sessions filter for the sidebar
 */
export function initializeUtilitySessionsFilter() {
    const toggle = document.getElementById('sidebar-show-utility-sessions-toggle');
    const container = document.getElementById('sidebar-show-utility-sessions-container');

    if (!toggle || !container) return;

    // Load saved preference
    const savedPref = localStorage.getItem('sidebarShowUtilitySessions');
    let showUtility = savedPref !== null ? savedPref === 'true' : true; // Default to showing
    toggle.checked = showUtility;

    // Function to update session visibility
    const updateSessionVisibility = () => {
        const sessions = document.querySelectorAll('.session-item');
        let hasUtilitySessions = false;

        sessions.forEach(item => {
            const isTemporary = item.dataset.isTemporary === 'true';
            if (isTemporary) {
                hasUtilitySessions = true;
                item.style.display = showUtility ? '' : 'none';
            }
        });

        // Show/hide the toggle container based on whether utility sessions exist
        container.classList.toggle('hidden', !hasUtilitySessions);
    };

    // Apply initial state
    updateSessionVisibility();

    // Handle toggle changes
    toggle.addEventListener('change', (e) => {
        showUtility = e.target.checked;
        localStorage.setItem('sidebarShowUtilitySessions', showUtility);
        updateSessionVisibility();
    });

    // Re-check visibility whenever sessions are added/removed
    // This will be called after sessions are loaded
    window.updateUtilitySessionsFilter = updateSessionVisibility;
}

/**
 * Initialize archived sessions filter for the sidebar
 */
export function initializeArchivedSessionsFilter() {
    const toggle = document.getElementById('sidebar-show-archived-sessions-toggle');
    const container = document.getElementById('sidebar-show-archived-sessions-container');

    if (!toggle || !container) return;

    // Load saved preference (default to NOT showing archived)
    const savedPref = localStorage.getItem('sidebarShowArchivedSessions');
    let showArchived = savedPref !== null ? savedPref === 'true' : false;
    toggle.checked = showArchived;

    // Function to update session visibility
    const updateSessionVisibility = () => {
        const sessions = document.querySelectorAll('.session-item');

        // Read current toggle state (not captured variable)
        const currentShowArchived = toggle.checked;

        sessions.forEach(item => {
            const isArchived = item.dataset.archived === 'true';
            if (isArchived) {
                // Hide archived sessions unless toggle is enabled
                item.style.display = currentShowArchived ? '' : 'none';

                // Add visual styling for archived sessions when shown
                if (currentShowArchived) {
                    item.classList.add('archived-session');
                } else {
                    item.classList.remove('archived-session');
                }
            }
        });
    };

    // Apply initial state
    updateSessionVisibility();

    // Handle toggle changes
    toggle.addEventListener('change', (e) => {
        showArchived = e.target.checked;
        localStorage.setItem('sidebarShowArchivedSessions', showArchived);
        updateSessionVisibility();
    });

    // Re-check visibility whenever sessions are added/removed
    // This will be called after sessions are loaded
    window.updateArchivedSessionsFilter = updateSessionVisibility;
}