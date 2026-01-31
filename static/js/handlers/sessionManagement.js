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

        // Check if session has a primer configured - execute it automatically
        if (data.session_primer) {
            console.log('[Session Primer] Executing session primer:', data.session_primer.substring(0, 50) + '...');
            // Import and use handleStreamRequest to execute the primer
            const { handleStreamRequest } = await import('../eventHandlers.js?v=3.4');
            const primerRequest = {
                message: data.session_primer,
                session_id: data.id,
                is_session_primer: true
            };
            // Pass profile_override_id if present (ensures executor uses correct profile)
            if (data.profile_override_id) {
                primerRequest.profile_override_id = data.profile_override_id;
                console.log('[Session Primer] Using profile override:', data.profile_override_id);
            }
            handleStreamRequest('/ask_stream', primerRequest);
        }
    } catch (error) {
        UI.addMessage('assistant', `Failed to start a new session: ${error.message}`);
    } finally {
        DOM.userInput.focus();
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
                    UI.addMessage(msg.role, displayContent, null, isValid, msg.source, profileTag, isSessionPrimer);
                }
            }
            // --- MODIFICATION END ---
        } else {
             UI.addMessage('assistant', "I'm ready to help. How can I assist you with your Teradata system today?");
        }
        UI.updateTokenDisplay({ total_input: data.input_tokens, total_output: data.output_tokens });
        
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
        // This will reset the status display to the globally configured model
        UI.updateStatusPromptName(data.provider, data.model);
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

    UI.showConfirmation(
        'Delete Session?',
        `Are you sure you want to permanently delete '${sessionName}'? This action cannot be undone.`,
        async () => {
            try {
                await deleteSession(sessionId);
                UI.removeSessionFromList(sessionId);

                if (state.currentSessionId === sessionId) {
                    try {
                        const remainingSessions = await API.loadAllSessions();
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