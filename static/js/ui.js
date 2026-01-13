/**
 * ui.js
 * * This module handles all direct DOM manipulations and UI updates.
 * Functions here are responsible for rendering messages, modals, status updates, and other visual changes.
 */

import * as DOM from './domElements.js';
import { state } from './state.js';
import { renderChart, isPrivilegedUser, isPromptCustomForModel, getNormalizedModelId } from './utils.js';
// We need access to the functions that will handle save/cancel from the input
import { handleSessionRenameSave, handleSessionRenameCancel } from './handlers/sessionManagement.js?v=3.2';
import { handleReplayQueryClick } from './eventHandlers.js?v=3.2';
import { checkServerStatus, loadAllSessions } from './api.js';
import { exportKnowledgeRepository, importKnowledgeRepository } from './handlers/knowledgeRepositoryHandler.js';


// NOTE: This module no longer imports from eventHandlers.js, breaking a circular dependency.
// Instead, eventHandlers.js will import these UI functions.

// ============================================================================
// Genie Slave Session Collapse State Management
// ============================================================================

const GENIE_COLLAPSE_STATE_KEY = 'genie_slave_collapse_state';

/**
 * Get the collapse state for genie slave sessions from localStorage.
 * Returns an object mapping parent session IDs to boolean (true = collapsed).
 */
export function getGenieCollapseState() {
    try {
        const stored = localStorage.getItem(GENIE_COLLAPSE_STATE_KEY);
        return stored ? JSON.parse(stored) : {};
    } catch (e) {
        console.warn('[UI] Failed to read genie collapse state:', e);
        return {};
    }
}

/**
 * Save the collapse state for genie slave sessions to localStorage.
 */
function saveGenieCollapseState(state) {
    try {
        localStorage.setItem(GENIE_COLLAPSE_STATE_KEY, JSON.stringify(state));
    } catch (e) {
        console.warn('[UI] Failed to save genie collapse state:', e);
    }
}

/**
 * Toggle visibility of slave sessions for a genie master session.
 * @param {string} parentSessionId - The session ID of the genie master
 */
export function toggleGenieSlaveVisibility(parentSessionId) {
    const collapseState = getGenieCollapseState();
    const isCurrentlyCollapsed = collapseState[parentSessionId] || false;
    const newState = !isCurrentlyCollapsed;

    // Update state
    collapseState[parentSessionId] = newState;
    saveGenieCollapseState(collapseState);

    // Find all slave sessions for this parent and toggle visibility
    const slaveItems = document.querySelectorAll(`[data-genie-parent-id="${parentSessionId}"]`);
    slaveItems.forEach(item => {
        if (newState) {
            item.classList.add('genie-slave-hidden');
        } else {
            item.classList.remove('genie-slave-hidden');
        }
    });

    // Update the toggle icon in the parent
    const parentItem = document.getElementById(`session-${parentSessionId}`);
    if (parentItem) {
        const toggleIcon = parentItem.querySelector('.genie-collapse-toggle');
        if (toggleIcon) {
            toggleIcon.textContent = newState ? '▶' : '▼';
        }
    }

    console.log(`[UI] Toggled genie slave visibility for ${parentSessionId}: ${newState ? 'collapsed' : 'expanded'}`);
}

/**
 * Mark sessions that are genie masters (have slave sessions).
 * Call this after loading all sessions to identify which sessions have slaves.
 * @param {Array} sessions - Array of session objects
 * @returns {Array} - Sessions with _isGenieMaster flag added
 */
export function markGenieMasterSessions(sessions) {
    // Build a set of parent session IDs that have slaves
    const parentIds = new Set();
    sessions.forEach(session => {
        const genieMetadata = session.genie_metadata || {};
        if (genieMetadata.is_genie_slave && genieMetadata.parent_session_id) {
            parentIds.add(genieMetadata.parent_session_id);
        }
    });

    // Mark sessions that have slaves as genie masters
    sessions.forEach(session => {
        session._isGenieMaster = parentIds.has(session.id);
    });

    console.log(`[UI] Marked ${parentIds.size} sessions as genie masters`);
    return sessions;
}

/**
 * Sort sessions hierarchically so slave sessions always appear directly under their parent.
 * This ensures proper visual ordering even during Genie execution when slaves are created/updated.
 *
 * @param {Array} sessions - Array of session objects
 * @returns {Array} - Sessions sorted with slaves directly under their parents
 */
export function sortSessionsHierarchically(sessions) {
    // Build maps for quick lookups
    const parentToSlaves = new Map(); // parentId -> [slave sessions]
    const slaveIds = new Set(); // All slave session IDs

    sessions.forEach(session => {
        const genieMetadata = session.genie_metadata || {};
        if (genieMetadata.is_genie_slave && genieMetadata.parent_session_id) {
            const parentId = genieMetadata.parent_session_id;
            if (!parentToSlaves.has(parentId)) {
                parentToSlaves.set(parentId, []);
            }
            parentToSlaves.get(parentId).push(session);
            slaveIds.add(session.id);
        }
    });

    // Separate parents (including non-genie sessions) from slaves
    const parentSessions = sessions.filter(s => !slaveIds.has(s.id));

    // Build the final sorted list
    const sorted = [];
    parentSessions.forEach(parent => {
        // Add the parent session
        sorted.push(parent);

        // Add its slave sessions immediately after (if any)
        const slaves = parentToSlaves.get(parent.id);
        if (slaves && slaves.length > 0) {
            // Sort slaves by created_at (oldest first) to maintain consistent order
            slaves.sort((a, b) => {
                const timeA = new Date(a.created_at || 0).getTime();
                const timeB = new Date(b.created_at || 0).getTime();
                return timeA - timeB;
            });
            sorted.push(...slaves);
        }
    });

    console.log(`[UI] Sorted ${sorted.length} sessions hierarchically (${slaveIds.size} slaves under parents)`);
    return sorted;
}

/**
 * Update the genie master badge visibility after sessions are rendered.
 * Call this after the session list is populated to add master badges to sessions
 * that weren't initially marked but have slave sessions in the DOM.
 */
export function updateGenieMasterBadges() {
    // Find all slave sessions and their parent IDs
    const slaveElements = document.querySelectorAll('.genie-slave-session');
    const parentIds = new Set();

    slaveElements.forEach(el => {
        const parentId = el.dataset.genieParentId;
        if (parentId) {
            parentIds.add(parentId);
        }
    });

    // For each parent that doesn't have a master badge, add one
    parentIds.forEach(parentId => {
        const parentItem = document.getElementById(`session-${parentId}`);
        if (parentItem && !parentItem.querySelector('.genie-master-badge')) {
            parentItem.classList.add('genie-master-session');
            parentItem.dataset.isGenieMaster = 'true';

            // Find the name container and add the badge
            const nameContainer = parentItem.querySelector('.flex-1.min-w-0');
            if (nameContainer) {
                const collapseState = getGenieCollapseState();
                const isCollapsed = collapseState[parentId] || false;

                const genieMasterBadge = document.createElement('span');
                genieMasterBadge.className = 'genie-master-badge inline-flex items-center gap-1 mt-0.5 text-xs cursor-pointer';
                genieMasterBadge.innerHTML = `
                    <span class="genie-badge-icon">G</span>
                    <span class="text-[#F15F22]">Genie Master</span>
                    <span class="genie-collapse-toggle ml-1 text-[#F15F22] hover:text-[#FF8C00] transition-colors">${isCollapsed ? '▶' : '▼'}</span>
                `;
                genieMasterBadge.title = 'Click to collapse/expand slave sessions';

                genieMasterBadge.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggleGenieSlaveVisibility(parentId);
                });

                nameContainer.appendChild(genieMasterBadge);
            }
        }
    });

    // Apply collapse state to slave sessions
    const collapseState = getGenieCollapseState();
    slaveElements.forEach(el => {
        const parentId = el.dataset.genieParentId;
        if (parentId && collapseState[parentId]) {
            el.classList.add('genie-slave-hidden');
        }
    });
}

/**
 * Renders the historical plan and execution trace in the status window.
 * @param {Array<object>} originalPlan - The original plan array generated for the turn.
 * @param {Array<object>} executionTrace - The execution trace array (action/result pairs).
 * @param {string|number} turnId - The ID of the turn being displayed.
 * @param {string} userQuery - The original user query for this turn.
 */
export function renderHistoricalTrace(originalPlan = [], executionTrace = [], turnId, userQuery = 'N/A', knowledgeRetrievalEvent = null) {
    DOM.statusWindowContent.innerHTML = ''; // Clear previous content
    state.currentStatusId = 0; // Reset status ID counter for this rendering
    state.isInFastPath = false; // Reset fast path flag
    state.currentPhaseContainerEl = null; // Reset phase container reference
    state.pendingSubtaskPlanningEvents = []; // Clear any pending events

    // 1. Add a title
    const titleEl = document.createElement('h3');
    titleEl.className = 'text-lg font-bold text-white mb-4 p-3 bg-gray-900/50 rounded-md';
    titleEl.textContent = `Reloaded Details for Turn ${turnId}`;
    DOM.statusWindowContent.appendChild(titleEl);

    // --- PHASE 2: Render knowledge retrieval event FIRST if present ---
    if (knowledgeRetrievalEvent) {
        updateStatusWindow({
            step: 'Knowledge Retrieved',
            details: knowledgeRetrievalEvent,
            type: 'knowledge_retrieval'
        }, false, 'knowledge_retrieval');
    }
    // --- PHASE 2 END ---

    // 2. Iterate through the new, rich execution trace
    executionTrace.forEach(traceEntry => {
        let eventData = {};
        let eventName = null;

        if (traceEntry.action && traceEntry.action.tool_name === 'TDA_SystemLog') {
            // This is a system event
            const metadata = traceEntry.action.metadata || {};
            eventData = {
                step: traceEntry.action.arguments.message,
                details: traceEntry.action.arguments.details,
                type: metadata.type,
                metadata: {
                    execution_depth: metadata.execution_depth
                }
            };
        } else if (traceEntry.action && traceEntry.result) {
            // This is a regular tool call, render as two steps
            const metadata = traceEntry.action.metadata || {};

            // Render intent
            const intentEventData = {
                step: `Tool Execution Intent`,
                details: traceEntry.action,
                type: 'tool_intent',
                metadata: {
                    execution_depth: metadata.execution_depth
                }
            };
            updateStatusWindow(intentEventData, false);

            // Render result
            const resultEventData = {
                step: `Tool Execution Result`,
                details: traceEntry.result,
                type: traceEntry.result.status === 'error' ? 'tool_error' : 'tool_result',
                metadata: {
                    execution_depth: metadata.execution_depth
                }
            };
            // For tool results, the event name is important
            eventName = resultEventData.type === 'tool_error' ? 'tool_error' : 'tool_result';
            updateStatusWindow(resultEventData, false, eventName);
            return; // We've handled this entry completely
        } else {
            // Skip unknown trace entry formats
            return;
        }

        updateStatusWindow(eventData, false);
    });

    // Finalize the last step
    const finalStepElement = document.getElementById(`status-step-${state.currentStatusId}`);
    if (finalStepElement && finalStepElement.classList.contains('active')) {
        finalStepElement.classList.remove('active');
        if (!finalStepElement.classList.contains('error') && !finalStepElement.classList.contains('cancelled')) {
            finalStepElement.classList.add('completed');
        }
    }

    // Auto-scroll logic
    if (!state.isMouseOverStatus) {
        DOM.statusWindowContent.scrollTop = 0; // Scroll to top for reloaded view
    }
}


export function addMessage(role, content, turnId = null, isValid = true, source = null, profileTag = null) { // eslint-disable-line no-unused-vars
    // Hide welcome screen when adding a message
    if (window.hideWelcomeScreen) {
        window.hideWelcomeScreen();
    }
    
    const wrapper = document.createElement('div');
    wrapper.className = `message-bubble group flex items-start gap-4 ${role === 'user' ? 'justify-end' : ''}`;
    const icon = document.createElement('div');
    icon.className = 'flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-white font-bold shadow-lg';
    icon.textContent = role === 'user' ? 'U' : 'A';
    icon.classList.add(role === 'user' ? 'bg-gray-700' : 'bg-[#F15F22]');

    if (role === 'assistant' && turnId) {
        icon.classList.add('assistant-avatar');
        icon.classList.add('clickable-avatar');
        if (state.showTooltips) {
            icon.title = 'Long-press to replay original query';
        }
        let pressTimer;

        const startPress = (e) => {
            e.preventDefault();
            icon.classList.add('long-press');
            pressTimer = setTimeout(() => {
                icon.classList.remove('long-press');
                handleReplayQueryClick({ dataset: { turnId } });
            }, 1500);
        };

        const cancelPress = () => {
            clearTimeout(pressTimer);
            icon.classList.remove('long-press');
        };

        icon.addEventListener('mousedown', startPress);
        icon.addEventListener('mouseup', cancelPress);
        icon.addEventListener('mouseleave', cancelPress);
        icon.addEventListener('touchstart', startPress, { passive: true });
        icon.addEventListener('touchend', cancelPress, { passive: true });
    }

    // This logic is now handled by the badge.

    const messageContainer = document.createElement('div');
    messageContainer.className = 'p-4 rounded-xl shadow-lg max-w-3xl glass-panel relative';
    // Use theme-aware gradients for message backgrounds
    messageContainer.style.background = role === 'user' 
        ? 'linear-gradient(135deg, rgba(30, 41, 59, 0.95) 0%, rgba(15, 23, 42, 0.98) 100%)' 
        : 'var(--message-assistant-bg, rgba(30, 41, 59, 0.9))';

    // Add profile badge for user messages if profileTag is provided
    let profileBadge = null;
    if (role === 'user' && profileTag) {
        profileBadge = document.createElement('div');
        profileBadge.className = 'flex items-center gap-x-2 px-3 py-1 rounded-lg backdrop-blur-md border border-white/20 shadow-lg flex-shrink-0';
        profileBadge.textContent = `@${profileTag}`;
        profileBadge.title = `Executed with profile: ${profileTag}`;
        
        // Apply profile-specific colors if available
        if (window.configState?.profiles) {
            const profile = window.configState.profiles.find(p => p.tag === profileTag);
            if (profile && profile.color) {
                const hexToRgba = (hex, alpha) => {
                    const r = parseInt(hex.slice(1, 3), 16);
                    const g = parseInt(hex.slice(3, 5), 16);
                    const b = parseInt(hex.slice(5, 7), 16);
                    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
                };
                const color1 = hexToRgba(profile.color, 0.3);
                const color2 = hexToRgba(profile.color, 0.15);
                const borderColor = hexToRgba(profile.color, 0.5);
                profileBadge.style.background = `linear-gradient(135deg, ${color1}, ${color2})`;
                profileBadge.style.borderColor = borderColor;
            }
        }
        profileBadge.style.fontSize = '0.875rem';
        profileBadge.style.fontWeight = '600';
        profileBadge.style.color = 'white';
        profileBadge.style.alignSelf = 'flex-start';
        profileBadge.style.marginRight = '12px';
    }

    const author = document.createElement('p');
    author.className = 'font-bold mb-2 text-sm';
    author.textContent = role === 'user' ? 'You' : 'Assistant';
    author.classList.add(role === 'user' ? 'text-gray-300' : 'text-[#F15F22]');
    messageContainer.appendChild(author);

    if (role === 'user' && source === 'rest') {
        const restTag = document.createElement('span');
        restTag.className = 'rest-call-tag';
        restTag.textContent = 'Rest Call';
        author.appendChild(restTag);
    }

    const messageContent = document.createElement('div');
    messageContent.innerHTML = content;
    messageContainer.appendChild(messageContent);

    if (role === 'user') {
        if (profileBadge) {
            wrapper.appendChild(profileBadge);
        }
        wrapper.appendChild(messageContainer);
    } else {
        wrapper.appendChild(icon);
    }
    wrapper.appendChild(role === 'user' ? icon : messageContainer);

    // --- MODIFICATION START: Add vertical feedback stack for assistant answers ---
    if (role === 'assistant' && turnId) {
        const feedbackWrapper = document.createElement('div');
        feedbackWrapper.className = 'mt-2 flex justify-end';
        feedbackWrapper.dataset.turnId = turnId;

        const pill = document.createElement('div');
        pill.className = 'flex items-stretch rounded-md bg-gray-900/50 border border-white/10 overflow-hidden backdrop-blur-sm';

        const makeBtn = (dir) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            // Removed 'group' so hover only affects this button, not sibling
            btn.className = 'feedback-btn px-2 py-1 flex items-center justify-center gap-1 text-gray-300 hover:text-white hover:bg-gray-800/60 transition text-xs';
            btn.setAttribute('aria-label', dir === 'up' ? 'Mark answer as helpful' : 'Mark answer as unhelpful');
            btn.setAttribute('aria-pressed', 'false');
            btn.dataset.vote = dir;
            const svg = dir === 'up'
                ? `<svg class='w-4 h-4' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>
                     <path d='M14 9V5a3 3 0 00-3-3l-4 9v11h11a3 3 0 003-3v-5a3 3 0 00-3-3h-7'/>
                   </svg>`
                : `<svg class='w-4 h-4' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>
                     <path d='M10 15v4a3 3 0 003 3l4-9V2H6a3 3 0 00-3 3v5a3 3 0 003 3h7'/>
                   </svg>`;
            const labelText = dir === 'up' ? 'Helpful' : 'Unhelpful';
            const labelSpan = document.createElement('span');
            labelSpan.className = 'vote-label opacity-70 transition text-[10px] tracking-wide text-gray-400';
            labelSpan.textContent = labelText;
            btn.innerHTML = svg; // set icon first
            btn.appendChild(labelSpan);
            // Isolated hover: only brighten hovered button's label
            btn.addEventListener('mouseenter', () => {
                labelSpan.classList.remove('opacity-70', 'text-gray-400');
                labelSpan.classList.add('opacity-100', 'text-white');
            });
            btn.addEventListener('mouseleave', () => {
                labelSpan.classList.add('opacity-70', 'text-gray-400');
                labelSpan.classList.remove('opacity-100', 'text-white');
            });
            return btn;
        };

        const upBtn = makeBtn('up');
        const divider = document.createElement('div');
        divider.className = 'w-px bg-white/10';
        const downBtn = makeBtn('down');

        const applyState = () => {
            const current = state.feedbackByTurn[turnId] || 'none';
            upBtn.classList.toggle('active', current === 'up');
            downBtn.classList.toggle('active', current === 'down');
            upBtn.setAttribute('aria-pressed', current === 'up' ? 'true' : 'false');
            downBtn.setAttribute('aria-pressed', current === 'down' ? 'true' : 'false');
            if (current === 'up') {
                upBtn.classList.remove('text-gray-300');
                upBtn.classList.add('text-[#F15F22]', 'bg-gray-800/60');
                downBtn.classList.add('text-gray-300');
                downBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
            } else if (current === 'down') {
                downBtn.classList.remove('text-gray-300');
                downBtn.classList.add('text-[#F15F22]', 'bg-gray-800/60');
                upBtn.classList.add('text-gray-300');
                upBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
            } else {
                upBtn.classList.add('text-gray-300');
                upBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
                downBtn.classList.add('text-gray-300');
                downBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
            }
        };

        const toggleVote = (dir) => {
            const current = state.feedbackByTurn[turnId] || 'none';
            state.feedbackByTurn[turnId] = current === dir ? null : dir;
            applyState();
            
            // --- MODIFICATION START: Save feedback to backend ---
            const vote = state.feedbackByTurn[turnId];
            if (state.currentSessionId) {
                import('./api.js').then(({ updateTurnFeedback }) => {
                    updateTurnFeedback(state.currentSessionId, turnId, vote)
                        .catch(err => {
                            console.error(`Failed to save feedback for turn ${turnId}:`, err);
                        });
                });
            }
            // --- MODIFICATION END ---
        };

        upBtn.addEventListener('click', () => toggleVote('up'));
        downBtn.addEventListener('click', () => toggleVote('down'));

        pill.appendChild(upBtn);
        pill.appendChild(divider);
        pill.appendChild(downBtn);
        feedbackWrapper.appendChild(pill);
        messageContainer.appendChild(feedbackWrapper);
        applyState();
    }
    // --- MODIFICATION END ---

    DOM.chatLog.appendChild(wrapper);

    // Logic for avatar click, header buttons, and turn badges
    if (role === 'assistant' && turnId) {
        // --- Add Turn Badge to Assistant Avatar ---
        const assistantBadge = document.createElement('span');
        assistantBadge.className = 'turn-badge clickable-badge';
        assistantBadge.dataset.turnId = turnId;
        if (state.showTooltips) {
            assistantBadge.title = 'Click to toggle context validity';
        }
        assistantBadge.addEventListener('mousedown', (e) => e.stopPropagation());
        assistantBadge.textContent = turnId;
        assistantBadge.classList.add('assistant-badge');
        wrapper.appendChild(assistantBadge); // Append badge to wrapper, not icon

        if (isValid === false) {
            assistantBadge.classList.add('context-invalid');
        }


        // --- Find previous User message and add badge/click handler ---
        const userBubbles = DOM.chatLog.querySelectorAll('.message-bubble:has(.bg-gray-700)');
        const lastUserBubble = userBubbles.length > 0 ? userBubbles[userBubbles.length - 1] : null;

        if (lastUserBubble) {
            const userAvatarIcon = lastUserBubble.querySelector('.bg-gray-700');
            if (userAvatarIcon) {
                // 1. Make the User Avatar clickable (REGARDLESS of context)
                userAvatarIcon.classList.add('clickable-avatar');
                userAvatarIcon.dataset.turnId = turnId;

                // --- Add Turn Badge to User Avatar ---
                const userBadge = document.createElement('span');
                userBadge.className = 'turn-badge clickable-badge';
                userBadge.dataset.turnId = turnId;
                if (state.showTooltips) {
                    userBadge.title = 'Click to toggle context validity';
                }
                userBadge.addEventListener('mousedown', (e) => e.stopPropagation());
                userBadge.textContent = turnId;
                userBadge.classList.add('user-badge');
                lastUserBubble.appendChild(userBadge); // Append badge to wrapper, not icon

                if (isValid === false) {
                    userBadge.classList.add('context-invalid');
                }
                if (state.showTooltips) {
                    if (isValid === false) {
                        userAvatarIcon.title = `Reload Details for Turn ${turnId} (Archived Context)`;
                    } else {
                        userAvatarIcon.title = `Reload Plan & Details for Turn ${turnId}`;
                    }
                }
            }
        }

        // --- Show and update the header replay buttons ---
        if (DOM.headerReplayPlannedButton) {
            DOM.headerReplayPlannedButton.classList.remove('hidden');
            DOM.headerReplayPlannedButton.dataset.turnId = turnId;
        }
        if (DOM.headerReplayOptimizedButton) {
            DOM.headerReplayOptimizedButton.classList.remove('hidden');
            DOM.headerReplayOptimizedButton.dataset.turnId = turnId;
        }
    }

    const chartContainers = messageContent.querySelectorAll('.chart-render-target');
    chartContainers.forEach(container => {
        if (container.dataset.spec) {
            renderChart(container.id, container.dataset.spec);
        }
    });

    wrapper.scrollIntoView({ behavior: 'smooth', block: 'end' });
}


/**
 * Sets the UI state for active execution (disables input, shows stop button, etc.).
 * @param {boolean} isActive - True if execution is starting, false if ending.
 */
export function setExecutionState(isActive) {
    DOM.userInput.disabled = isActive;
    DOM.submitButton.disabled = isActive;
    DOM.newChatButton.disabled = isActive;
    DOM.sendIcon.classList.toggle('hidden', isActive);
    DOM.loadingSpinner.classList.toggle('hidden', !isActive);

    if (DOM.stopExecutionButton) {
        DOM.stopExecutionButton.classList.toggle('hidden', !isActive);
        DOM.stopExecutionButton.disabled = !isActive;
    }

    if (isActive) {
        // Hide and disable buttons when execution starts
        if (DOM.headerReplayPlannedButton) {
            DOM.headerReplayPlannedButton.classList.add('hidden');
            DOM.headerReplayPlannedButton.disabled = true;
        }
        if (DOM.headerReplayOptimizedButton) {
            DOM.headerReplayOptimizedButton.classList.add('hidden');
            DOM.headerReplayOptimizedButton.disabled = true;
        }
    } else {
        // Enable buttons when execution ends (they will be shown by addMessage if applicable)
        if (DOM.headerReplayPlannedButton) {
            DOM.headerReplayPlannedButton.disabled = false;
        }
        if (DOM.headerReplayOptimizedButton) {
            DOM.headerReplayOptimizedButton.disabled = false;
        }
        // Don't explicitly show them here, addMessage handles showing them when a turn completes
    }

    if (!isActive) {
        setThinkingIndicator(false);
        DOM.mcpStatusDot.classList.remove('pulsing', 'busy');
        DOM.llmStatusDot.classList.remove('pulsing', 'busy');

        if (!DOM.mcpStatusDot.classList.contains('disconnected')) {
            DOM.mcpStatusDot.classList.add('connected');
        }
        if (!DOM.llmStatusDot.classList.contains('disconnected')) {
            DOM.llmStatusDot.classList.add('idle');
        }
    }
}


/**
 * Updates the visual status of the Server-Sent Events (SSE) connection indicator.
 * @param {('connected'|'reconnecting'|'disconnected')} status - The current status of the connection.
 */
export function updateSSEStatus(status) {
    if (!DOM.sseStatusDot) return;

    DOM.sseStatusDot.classList.remove('connected', 'reconnecting', 'disconnected');
    DOM.sseStatusDot.classList.add(status);

    switch (status) {
        case 'connected':
            DOM.sseStatusDot.title = 'Real-time connection active.';
            break;
        case 'reconnecting':
            DOM.sseStatusDot.title = 'Connection lost. Attempting to reconnect...';
            break;
        case 'disconnected':
            DOM.sseStatusDot.title = 'Real-time connection failed. Please refresh the page.';
            break;
    }
}


function _renderKnowledgeRetrievalDetails(details) {
    if (!details.collections || !details.chunks) return null;

    const collections = details.collections || [];
    const chunks = details.chunks || [];
    const documentCount = details.document_count || chunks.length;

    let html = `
        <div class="status-kv-grid">
            <div class="status-kv-key">Collections</div>
            <div class="status-kv-value">${collections.join(', ')}</div>
            <div class="status-kv-key">Documents</div>
            <div class="status-kv-value">${documentCount} chunks retrieved</div>
        </div>
    `;

    if (chunks.length > 0) {
        html += `
            <details class="text-xs mt-2">
                <summary class="cursor-pointer text-gray-400 hover:text-white">View Retrieved Chunks (${chunks.length})</summary>
                <div class="space-y-2 mt-2">
        `;

        chunks.forEach((chunk, idx) => {
            const similarity = (chunk.similarity_score * 100).toFixed(1);
            const content = chunk.content || '';
            const previewLength = 150;
            const preview = content.length > previewLength ? content.substring(0, previewLength) + '...' : content;
            
            html += `
                <div class="p-2 bg-gray-900/50 rounded border border-purple-500/30">
                    <div class="flex justify-between items-start mb-1">
                        <span class="text-purple-400 font-semibold text-xs">Chunk ${idx + 1}</span>
                        <span class="text-gray-500 text-xs">Relevance: ${similarity}%</span>
                    </div>
                    <div class="text-gray-400 text-xs mb-1">
                        <span class="text-gray-500">Collection:</span> ${chunk.collection_name || 'Unknown'}
                    </div>
            `;

            if (content.length > previewLength) {
                html += `
                    <details class="text-xs">
                        <summary class="cursor-pointer text-gray-400 hover:text-white">${preview}</summary>
                        <div class="mt-2 p-2 status-text-block whitespace-pre-wrap text-gray-300">${content}</div>
                    </details>
                `;
            } else {
                html += `<div class="text-gray-300 text-xs whitespace-pre-wrap">${content}</div>`;
            }

            html += `</div>`;
        });

        html += `
                </div>
            </details>
        `;
    }

    return html;
}

function _renderPlanningDetails(details) {
    if (!details.summary || !details.full_text) return null;

    let fullTextHtml = '';
    const text = details.full_text;
    const characterThreshold = 150;

    if (text.length > characterThreshold) {
        fullTextHtml = `
            <details class="text-xs">
                <summary class="cursor-pointer text-gray-400 hover:text-white">Full Text (${text.length} chars)</summary>
                <div class="mt-2 p-2 status-text-block whitespace-pre-wrap">${text}</div>
            </details>
        `;
    } else {
        fullTextHtml = `<div class="status-text-block whitespace-pre-wrap">${text}</div>`;
    }

    return `
        <div class="status-kv-grid">
            <div class="status-kv-key">Summary</div>
            <div class="status-kv-value">${details.summary}</div>
            <div class="status-kv-key">Full Text</div>
            <div class="status-kv-value">${fullTextHtml}</div>
        </div>
    `;
}

function _renderMetaPlanDetails(details) {
    if (!Array.isArray(details)) return null;

    let html = `<details class="text-xs" open>
                    <summary class="cursor-pointer text-gray-400 hover:text-white">Generated Plan (${details.length} steps)</summary>
                    <div class="space-y-3 mt-2">`;

    details.forEach(phase => {
        let argsHtml = '';
        if (phase.arguments) {
            const argsString = JSON.stringify(phase.arguments, null, 2);
            argsHtml = `
                <div class="status-kv-item">
                    <div class="status-kv-key">Args</div>
                    <div class="status-kv-value">
                        <details class="text-xs">
                            <summary class="cursor-pointer text-gray-400 hover:text-white">View Arguments</summary>
                            <div class="mt-2 p-2 status-text-block whitespace-pre-wrap">${argsString}</div>
                        </details>
                    </div>
                </div>
            `;
        }

        let structuralKeysHtml = '';
        if (phase.type) {
            structuralKeysHtml += `<div class="status-kv-item"><div class="status-kv-key">Type</div><div class="status-kv-value"><code class="status-code font-bold text-yellow-300">${phase.type}</code></div></div>`;
        }
        if (phase.loop_over) {
            structuralKeysHtml += `<div class="status-kv-item"><div class="status-kv-key">Loop Over</div><div class="status-kv-value"><code class="status-code">${phase.loop_over}</code></div></div>`;
        }

        html += `<div class="status-phase-card">
                    <div class="font-bold text-gray-300 mb-2">Step ${phase.phase}</div>
                    <div class="status-kv-item"><div class="status-kv-key">Goal</div><div class="status-kv-value">${phase.goal}</div></div>`;

        html += structuralKeysHtml;

        if (phase.relevant_tools) {
            html += `<div class="status-kv-item"><div class="status-kv-key">Tools</div><div class="status-kv-value"><code class="status-code">${phase.relevant_tools.join(', ')}</code></div></div>`;
        }
        if (phase.executable_prompt) {
            html += `<div class="status-kv-item"><div class="status-kv-key">Prompt</div><div class="status-kv-value"><code class="status-code">${phase.executable_prompt}</code></div></div>`;
        }
        html += `${argsHtml}</div>`;
    });
    html += '</div></details>';
    return html;
}

function _renderToolIntentDetails(details) {
    if (!details || (!details.tool_name && !details.prompt_name)) return null;

    const name = details.tool_name || details.prompt_name;
    const type = details.tool_name ? 'Tool' : 'Prompt';

    let argsHtml = '';
    if (details.arguments) {
        try {
             const argsString = JSON.stringify(details.arguments, null, 2);
             argsHtml = `
                <div class="status-kv-item">
                    <div class="status-kv-key">Args</div>
                    <div class="status-kv-value">
                        <details class="text-xs">
                            <summary class="cursor-pointer text-gray-400 hover:text-white">View Arguments</summary>
                            <div class="mt-2 p-2 status-text-block whitespace-pre-wrap">${argsString}</div>
                        </details>
                    </div>
                </div>
            `;
        } catch (e) {
            argsHtml = `<div class="status-kv-item"><div class="status-kv-key">Args</div><div class="status-kv-value text-red-400">[Error displaying arguments]</div></div>`;
        }
    }

    return `
        <div class="status-kv-item"><div class="status-kv-key">${type}</div><div class="status-kv-value"><code class="status-code">${name}</code></div></div>
        ${argsHtml}
    `;
}

/**
 * Render Genie coordination events in the status window.
 * Uses purple-themed styling for world-class visual feedback.
 *
 * ARCHITECTURE: All coordination visualization is in Live Status window only.
 * The chat pane stays clean with just Q&A - this panel shows the "how".
 */
function _renderGenieStep(eventData, parentContainer, isFinal = false) {
    const { step, details, type } = eventData;

    // Mark previous active step as completed
    const lastStep = parentContainer.querySelector('.status-step.active');
    if (lastStep) {
        lastStep.classList.remove('active');
        lastStep.classList.add('completed');
    }

    const stepEl = document.createElement('div');
    stepEl.className = 'status-step p-3 rounded-md mb-2 genie-status-step';
    if (isFinal) {
        stepEl.classList.add('completed');
    } else {
        stepEl.classList.add('active');
    }

    // Color-code based on event type
    if (type === 'genie_coordination_complete') {
        stepEl.classList.add(details?.success ? 'genie-success' : 'genie-error');
    } else if (type === 'genie_slave_completed') {
        stepEl.classList.add(details?.success ? 'genie-slave-success' : 'genie-slave-error');
    }

    // Step header with icon
    const stepHeader = document.createElement('div');
    stepHeader.className = 'flex items-center gap-2 mb-2';

    // Add appropriate icon based on event type
    let iconSvg = '';
    switch (type) {
        case 'genie_start':
        case 'genie_routing':
        case 'genie_coordination_start':
            iconSvg = '<svg class="w-4 h-4 text-purple-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>';
            break;
        case 'genie_llm_step':
            iconSvg = '<svg class="w-4 h-4 text-cyan-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>';
            break;
        case 'genie_routing_decision':
            iconSvg = '<svg class="w-4 h-4 text-purple-400" viewBox="0 0 24 24" fill="currentColor"><path d="M13.5.67s.74 2.65.74 4.8c0 2.06-1.35 3.73-3.41 3.73-2.07 0-3.63-1.67-3.63-3.73l.03-.36C5.21 7.51 4 10.62 4 14c0 4.42 3.58 8 8 8s8-3.58 8-8C20 8.61 17.41 3.8 13.5.67zM11.71 19c-1.78 0-3.22-1.4-3.22-3.14 0-1.62 1.05-2.76 2.81-3.12 1.77-.36 3.6-1.21 4.62-2.58.39 1.29.59 2.65.59 4.04 0 2.65-2.15 4.8-4.8 4.8z"/></svg>';
            break;
        case 'genie_slave_invoked':
            iconSvg = '<svg class="w-4 h-4 text-orange-400 animate-pulse" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>';
            break;
        case 'genie_slave_progress':
            iconSvg = '<svg class="w-4 h-4 text-yellow-400 animate-pulse" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-4h2v2h-2zm1-10c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z"/></svg>';
            break;
        case 'genie_slave_completed':
            iconSvg = details?.success
                ? '<svg class="w-4 h-4 text-green-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>'
                : '<svg class="w-4 h-4 text-red-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>';
            break;
        case 'genie_synthesis_start':
            iconSvg = '<svg class="w-4 h-4 text-blue-400 animate-pulse" viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14l-5-5 1.41-1.41L12 14.17l4.59-4.58L18 11l-6 6z"/></svg>';
            break;
        case 'genie_coordination_complete':
            iconSvg = details?.success
                ? '<svg class="w-4 h-4 text-green-400" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>'
                : '<svg class="w-4 h-4 text-red-400" viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41z"/></svg>';
            break;
        default:
            iconSvg = '<svg class="w-4 h-4 text-gray-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>';
    }

    stepHeader.innerHTML = `
        ${iconSvg}
        <h4 class="font-bold text-sm text-white">${step || 'Genie Coordination'}</h4>
    `;
    stepEl.appendChild(stepHeader);

    // Render details based on event type
    if (details && typeof details === 'object') {
        const detailsEl = document.createElement('div');
        detailsEl.className = 'text-xs';

        switch (type) {
            case 'genie_start':
            case 'genie_routing':
            case 'genie_coordination_start': {
                const profileCount = details.slave_profiles?.length || 0;
                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Profile</div>
                        <div class="status-kv-value"><code class="status-code text-purple-300">@GENIE</code></div>
                        <div class="status-kv-key">Experts</div>
                        <div class="status-kv-value">${profileCount} available</div>
                    </div>
                    ${details.slave_profiles && details.slave_profiles.length > 0 ? `
                        <details class="mt-2">
                            <summary class="cursor-pointer text-gray-400 hover:text-white">View Available Profiles</summary>
                            <div class="genie-profile-tags mt-2 flex flex-wrap gap-1">
                                ${details.slave_profiles.map(p => `<span class="genie-tag">@${p.tag}</span>`).join('')}
                            </div>
                        </details>
                    ` : ''}
                `;
                break;
            }

            case 'genie_llm_step': {
                const stepNumber = details.step_number || '?';
                const stepName = details.step_name || `Step ${stepNumber}`;
                const inputTokens = details.input_tokens || 0;
                const outputTokens = details.output_tokens || 0;

                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Step</div>
                        <div class="status-kv-value"><code class="status-code text-cyan-300">#${stepNumber}: ${stepName}</code></div>
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value text-green-400">✓ Complete</div>
                        <div class="status-kv-key">Tokens</div>
                        <div class="status-kv-value">${inputTokens.toLocaleString()} in / ${outputTokens.toLocaleString()} out</div>
                    </div>
                `;
                break;
            }

            case 'genie_routing_decision': {
                const selectedCount = details.selected_profiles?.length || 0;
                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Decision</div>
                        <div class="status-kv-value">${selectedCount} profile${selectedCount > 1 ? 's' : ''} selected</div>
                    </div>
                    ${details.decision_text ? `
                        <div class="mt-2 p-2 bg-purple-900/30 rounded border border-purple-500/30 text-gray-300 text-xs">
                            ${details.decision_text}
                        </div>
                    ` : ''}
                    ${details.selected_profiles && details.selected_profiles.length > 0 ? `
                        <div class="mt-2 flex flex-wrap gap-1">
                            ${details.selected_profiles.map(tag => `<span class="genie-tag selected">@${tag}</span>`).join('')}
                        </div>
                    ` : ''}
                `;
                break;
            }

            case 'genie_slave_invoked': {
                const profileTag = details.profile_tag || 'UNKNOWN';
                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Profile</div>
                        <div class="status-kv-value"><code class="status-code text-orange-300">@${profileTag}</code></div>
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value text-orange-400">⟳ Processing...</div>
                    </div>
                    ${details.slave_session_id ? `
                        <div class="mt-1 text-gray-500 text-xs">Session: ${details.slave_session_id.slice(0, 8)}...</div>
                    ` : ''}
                `;
                break;
            }

            case 'genie_slave_progress': {
                const profileTag = details.profile_tag || 'UNKNOWN';
                const message = details.message || 'Working...';
                const progress = details.progress_pct !== undefined ? details.progress_pct : null;
                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Profile</div>
                        <div class="status-kv-value"><code class="status-code text-yellow-300">@${profileTag}</code></div>
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value text-yellow-400">${message}</div>
                        ${progress !== null ? `
                            <div class="status-kv-key">Progress</div>
                            <div class="status-kv-value">${progress}%</div>
                        ` : ''}
                    </div>
                `;
                break;
            }

            case 'genie_slave_completed': {
                const profileTag = details.profile_tag || 'UNKNOWN';
                const duration = details.duration_ms ? `${(details.duration_ms / 1000).toFixed(2)}s` : 'N/A';
                const statusText = details.success ? '✓ Success' : '✗ Failed';
                const statusClass = details.success ? 'text-green-400' : 'text-red-400';

                let resultHtml = '';
                if (details.result_preview) {
                    resultHtml = `
                        <details class="mt-2">
                            <summary class="cursor-pointer text-gray-400 hover:text-white">View Result Preview</summary>
                            <div class="mt-1 p-2 bg-gray-900/50 rounded text-gray-300 whitespace-pre-wrap">${details.result_preview}</div>
                        </details>
                    `;
                }

                let errorHtml = '';
                if (details.error) {
                    errorHtml = `<div class="mt-2 p-2 bg-red-900/30 rounded border border-red-500/30 text-red-300">${details.error}</div>`;
                }

                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Profile</div>
                        <div class="status-kv-value"><code class="status-code ${details.success ? 'text-green-300' : 'text-red-300'}">@${profileTag}</code></div>
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value ${statusClass}">${statusText}</div>
                        <div class="status-kv-key">Duration</div>
                        <div class="status-kv-value">${duration}</div>
                    </div>
                    ${resultHtml}
                    ${errorHtml}
                `;
                break;
            }

            case 'genie_synthesis_start': {
                const consulted = details.profiles_consulted?.length || 0;
                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value text-blue-400">Synthesizing response...</div>
                        <div class="status-kv-key">Profiles</div>
                        <div class="status-kv-value">${consulted} consulted</div>
                    </div>
                    ${details.profiles_consulted && details.profiles_consulted.length > 0 ? `
                        <div class="mt-2 flex flex-wrap gap-1">
                            ${details.profiles_consulted.map(tag => `<span class="genie-tag completed">@${tag}</span>`).join('')}
                        </div>
                    ` : ''}
                `;
                break;
            }

            case 'genie_coordination_complete': {
                const totalDuration = details.total_duration_ms ? `${(details.total_duration_ms / 1000).toFixed(2)}s` : 'N/A';
                const usedCount = details.profiles_used?.length || 0;
                const statusText = details.success ? '✓ Complete' : '✗ Failed';
                const statusClass = details.success ? 'text-green-400' : 'text-red-400';

                // Token counts (if available)
                const inputTokens = details.input_tokens;
                const outputTokens = details.output_tokens;
                let tokensHtml = '';
                if (inputTokens !== undefined && outputTokens !== undefined && (inputTokens > 0 || outputTokens > 0)) {
                    tokensHtml = `
                        <div class="status-kv-key">Tokens</div>
                        <div class="status-kv-value">${inputTokens.toLocaleString()} in / ${outputTokens.toLocaleString()} out</div>
                    `;
                }

                let profilesHtml = '';
                if (details.profiles_used && details.profiles_used.length > 0) {
                    profilesHtml = `
                        <div class="mt-2">
                            <div class="text-gray-500 text-xs mb-1">Profiles Consulted:</div>
                            <div class="genie-profile-tags flex flex-wrap gap-1">
                                ${details.profiles_used.map(tag => `<span class="genie-tag completed">@${tag}</span>`).join('')}
                            </div>
                        </div>
                    `;
                }

                let errorHtml = '';
                if (details.error) {
                    errorHtml = `<div class="mt-2 p-2 bg-red-900/30 rounded border border-red-500/30 text-red-300">${details.error}</div>`;
                }

                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value ${statusClass} font-semibold">${statusText}</div>
                        <div class="status-kv-key">Profiles Used</div>
                        <div class="status-kv-value">${usedCount}</div>
                        <div class="status-kv-key">Total Time</div>
                        <div class="status-kv-value">${totalDuration}</div>
                        ${tokensHtml}
                    </div>
                    ${profilesHtml}
                    ${errorHtml}
                `;
                break;
            }

            default:
                // Generic fallback with JSON display
                try {
                    const jsonStr = JSON.stringify(details, null, 2);
                    detailsEl.innerHTML = `
                        <details>
                            <summary class="cursor-pointer text-gray-400 hover:text-white">View Details</summary>
                            <pre class="mt-1 p-2 bg-gray-900/50 rounded text-gray-400 overflow-x-auto">${jsonStr}</pre>
                        </details>
                    `;
                } catch (e) {
                    detailsEl.innerHTML = `<span class="text-gray-500">[Unable to display details]</span>`;
                }
        }

        stepEl.appendChild(detailsEl);
    }

    parentContainer.appendChild(stepEl);

    // Auto-scroll to latest step
    stepEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Reset genie coordination state on completion
    if (type === 'genie_coordination_complete') {
        state.isGenieCoordinationActive = false;
    }
}

/**
 * Exported wrapper for rendering genie events during plan reload.
 * Uses the same rendering logic as live execution for consistent UX.
 */
export function renderGenieStepForReload(eventData, parentContainer, isFinal = false) {
    _renderGenieStep(eventData, parentContainer, isFinal);
}

/**
 * Render Conversation Agent tool execution events in the status window.
 * Uses blue/cyan-themed styling to differentiate from genie (purple) events.
 */
/**
 * Render conversation agent events in the Live Status window.
 * Uses consistent styling with tool_enabled profiles for a world-class UX.
 *
 * ARCHITECTURE: All tool execution visualization is in Live Status window only.
 * The chat pane stays clean with just Q&A - this panel shows the "how".
 */
function _renderConversationAgentStep(eventData, parentContainer, isFinal = false) {
    const { step, details, type } = eventData;

    // Mark previous active step as completed
    const lastStep = parentContainer.querySelector('.status-step.active');
    if (lastStep) {
        lastStep.classList.remove('active');
        lastStep.classList.add('completed');
    }

    const stepEl = document.createElement('div');
    stepEl.className = 'status-step p-3 rounded-md mb-2 conversation-agent-status-step';
    if (isFinal) {
        stepEl.classList.add('completed');
    } else {
        stepEl.classList.add('active');
    }

    // Color-code based on event type
    if (type === 'conversation_agent_complete') {
        stepEl.classList.add(details?.success ? 'conv-agent-success' : 'conv-agent-error');
    } else if (type === 'conversation_tool_completed') {
        stepEl.classList.add(details?.success ? 'conv-tool-success' : 'conv-tool-error');
    }

    // Step header with icon
    const stepHeader = document.createElement('div');
    stepHeader.className = 'flex items-center gap-2 mb-2';

    // Add appropriate icon based on event type
    let iconSvg = '';
    switch (type) {
        case 'conversation_agent_start':
            iconSvg = '<svg class="w-4 h-4 text-blue-400" viewBox="0 0 24 24" fill="currentColor"><path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z"/></svg>';
            break;
        case 'conversation_llm_step':
            iconSvg = '<svg class="w-4 h-4 text-cyan-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>';
            break;
        case 'conversation_tool_invoked':
            iconSvg = '<svg class="w-4 h-4 text-orange-400 animate-pulse" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>';
            break;
        case 'conversation_tool_completed':
            iconSvg = details?.success
                ? '<svg class="w-4 h-4 text-green-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>'
                : '<svg class="w-4 h-4 text-red-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>';
            break;
        case 'conversation_agent_complete':
            iconSvg = details?.success
                ? '<svg class="w-4 h-4 text-green-400" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>'
                : '<svg class="w-4 h-4 text-red-400" viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41z"/></svg>';
            break;
        case 'knowledge_retrieval':
            iconSvg = '<svg class="w-4 h-4 text-purple-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l-5.5 9h11L12 2zm0 3.84L13.93 9h-3.87L12 5.84zM17.5 13c-2.49 0-4.5 2.01-4.5 4.5s2.01 4.5 4.5 4.5 4.5-2.01 4.5-4.5-2.01-4.5-4.5-4.5zm0 7c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5zM3 21.5h8v-2H3v2zm0-3.5h8v-2H3v2z"/></svg>';
            break;
        default:
            iconSvg = '<svg class="w-4 h-4 text-gray-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>';
    }

    stepHeader.innerHTML = `
        ${iconSvg}
        <h4 class="font-bold text-sm text-white">${step || 'Tool Execution'}</h4>
    `;
    stepEl.appendChild(stepHeader);

    // Render details based on event type
    if (details && typeof details === 'object') {
        const detailsEl = document.createElement('div');
        detailsEl.className = 'text-xs';

        switch (type) {
            case 'conversation_agent_start': {
                const toolCount = details.available_tools?.length || 0;
                const profileTag = details.profile_tag || 'CONV';
                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Profile</div>
                        <div class="status-kv-value"><code class="status-code text-blue-300">@${profileTag}</code></div>
                        <div class="status-kv-key">Tools</div>
                        <div class="status-kv-value">${toolCount} available</div>
                    </div>
                    ${details.available_tools && details.available_tools.length > 0 ? `
                        <details class="mt-2">
                            <summary class="cursor-pointer text-gray-400 hover:text-white">View Available Tools</summary>
                            <div class="conv-agent-tool-tags mt-2 flex flex-wrap gap-1">
                                ${details.available_tools.map(t => `<span class="conv-agent-tag">${t}</span>`).join('')}
                            </div>
                        </details>
                    ` : ''}
                `;
                break;
            }

            case 'conversation_llm_step': {
                const stepNumber = details.step_number || '?';
                const stepName = details.step_name || `Step ${stepNumber}`;
                const inputTokens = details.input_tokens || 0;
                const outputTokens = details.output_tokens || 0;

                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Step</div>
                        <div class="status-kv-value"><code class="status-code text-cyan-300">#${stepNumber}: ${stepName}</code></div>
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value text-green-400">✓ Complete</div>
                        <div class="status-kv-key">Tokens</div>
                        <div class="status-kv-value">${inputTokens.toLocaleString()} in / ${outputTokens.toLocaleString()} out</div>
                    </div>
                `;
                break;
            }

            case 'conversation_tool_invoked': {
                const toolName = details.tool_name || 'Unknown';
                let argsHtml = '';
                if (details.arguments) {
                    try {
                        // Clean up runtime noise from arguments if present
                        let cleanArgs = details.arguments;
                        if (typeof cleanArgs === 'object' && cleanArgs.runtime) {
                            // Extract just the meaningful parts, not the runtime internals
                            cleanArgs = { ...cleanArgs };
                            delete cleanArgs.runtime;
                        }
                        const argsStr = typeof cleanArgs === 'string' ? cleanArgs : JSON.stringify(cleanArgs, null, 2);
                        if (argsStr && argsStr !== '{}') {
                            argsHtml = `
                                <details class="mt-2">
                                    <summary class="cursor-pointer text-gray-400 hover:text-white">View Arguments</summary>
                                    <div class="mt-1 p-2 bg-gray-900/50 rounded status-text-block whitespace-pre-wrap text-gray-300">${argsStr}</div>
                                </details>
                            `;
                        }
                    } catch (e) {
                        argsHtml = '';
                    }
                }
                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Tool</div>
                        <div class="status-kv-value"><code class="status-code text-orange-300">${toolName}</code></div>
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value text-orange-400">⟳ Executing...</div>
                    </div>
                    ${argsHtml}
                `;
                break;
            }

            case 'conversation_tool_completed': {
                const toolName = details.tool_name || 'Unknown';
                const duration = details.duration_ms ? `${(details.duration_ms / 1000).toFixed(2)}s` : 'N/A';
                const statusText = details.success ? '✓ Success' : '✗ Failed';
                const statusClass = details.success ? 'text-green-400' : 'text-red-400';

                let resultHtml = '';
                if (details.result_preview) {
                    resultHtml = `
                        <details class="mt-2">
                            <summary class="cursor-pointer text-gray-400 hover:text-white">View Result Preview</summary>
                            <div class="mt-1 p-2 bg-gray-900/50 rounded text-gray-300 whitespace-pre-wrap">${details.result_preview}</div>
                        </details>
                    `;
                }

                let errorHtml = '';
                if (details.error) {
                    errorHtml = `<div class="mt-2 p-2 bg-red-900/30 rounded border border-red-500/30 text-red-300">${details.error}</div>`;
                }

                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Tool</div>
                        <div class="status-kv-value"><code class="status-code ${details.success ? 'text-green-300' : 'text-red-300'}">${toolName}</code></div>
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value ${statusClass}">${statusText}</div>
                        <div class="status-kv-key">Duration</div>
                        <div class="status-kv-value">${duration}</div>
                    </div>
                    ${resultHtml}
                    ${errorHtml}
                `;
                break;
            }

            case 'conversation_agent_complete': {
                const totalDuration = details.total_duration_ms ? `${(details.total_duration_ms / 1000).toFixed(2)}s` : 'N/A';
                const toolCount = details.tools_used?.length || 0;
                const statusText = details.success ? '✓ Complete' : '✗ Failed';
                const statusClass = details.success ? 'text-green-400' : 'text-red-400';

                // Token counts (if available)
                const inputTokens = details.input_tokens;
                const outputTokens = details.output_tokens;
                let tokensHtml = '';
                if (inputTokens !== undefined && outputTokens !== undefined && (inputTokens > 0 || outputTokens > 0)) {
                    tokensHtml = `
                        <div class="status-kv-key">Tokens</div>
                        <div class="status-kv-value">${inputTokens.toLocaleString()} in / ${outputTokens.toLocaleString()} out</div>
                    `;
                }

                let toolsHtml = '';
                if (details.tools_used && details.tools_used.length > 0) {
                    toolsHtml = `
                        <div class="mt-2">
                            <div class="text-gray-500 text-xs mb-1">Tools Executed:</div>
                            <div class="conv-agent-tool-tags flex flex-wrap gap-1">
                                ${details.tools_used.map(t => `<span class="conv-agent-tag completed">${t}</span>`).join('')}
                            </div>
                        </div>
                    `;
                }

                let errorHtml = '';
                if (details.error) {
                    errorHtml = `<div class="mt-2 p-2 bg-red-900/30 rounded border border-red-500/30 text-red-300">${details.error}</div>`;
                }

                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Status</div>
                        <div class="status-kv-value ${statusClass} font-semibold">${statusText}</div>
                        <div class="status-kv-key">Tools Used</div>
                        <div class="status-kv-value">${toolCount}</div>
                        <div class="status-kv-key">Total Time</div>
                        <div class="status-kv-value">${totalDuration}</div>
                        ${tokensHtml}
                    </div>
                    ${toolsHtml}
                    ${errorHtml}
                `;
                break;
            }

            case 'knowledge_retrieval': {
                // Knowledge retrieval event - use purple/violet theme for consistency
                stepEl.classList.remove('conversation-agent-status-step');
                stepEl.classList.add('knowledge-retrieval-status-step');

                const collections = details.collections || [];
                const chunks = details.chunks || [];
                const documentCount = details.document_count || chunks.length;

                let chunksHtml = '';
                if (chunks.length > 0) {
                    const chunkPreviews = chunks.slice(0, 3).map((chunk, idx) => {
                        const similarity = chunk.similarity_score ? (chunk.similarity_score * 100).toFixed(1) : 'N/A';
                        const content = chunk.content || '';
                        const preview = content.length > 150 ? content.substring(0, 147) + '...' : content;
                        const source = chunk.source || 'Unknown';
                        return `
                            <div class="p-2 bg-gray-900/50 rounded border border-purple-500/30">
                                <div class="flex justify-between items-start mb-1">
                                    <span class="text-purple-400 font-semibold">Chunk ${idx + 1}</span>
                                    <span class="text-gray-500">Relevance: ${similarity}%</span>
                                </div>
                                <div class="text-gray-500 text-xs mb-1">Source: ${source}</div>
                                <div class="text-gray-300 whitespace-pre-wrap">${preview}</div>
                            </div>
                        `;
                    }).join('');

                    chunksHtml = `
                        <details class="mt-2">
                            <summary class="cursor-pointer text-gray-400 hover:text-white">
                                View Retrieved Chunks (${chunks.length})
                            </summary>
                            <div class="space-y-2 mt-2">${chunkPreviews}</div>
                            ${chunks.length > 3 ? `<div class="text-gray-500 mt-1">+${chunks.length - 3} more chunks</div>` : ''}
                        </details>
                    `;
                }

                detailsEl.innerHTML = `
                    <div class="status-kv-grid">
                        <div class="status-kv-key">Collections</div>
                        <div class="status-kv-value">${collections.length > 0 ? collections.join(', ') : 'N/A'}</div>
                        <div class="status-kv-key">Documents</div>
                        <div class="status-kv-value">${documentCount} chunks retrieved</div>
                    </div>
                    ${chunksHtml}
                `;

                // Trigger the knowledge indicator
                if (collections.length > 0) {
                    blinkKnowledgeDot();
                    updateKnowledgeIndicator(collections, documentCount);
                }
                break;
            }

            default:
                // Generic fallback with JSON display
                try {
                    const jsonStr = JSON.stringify(details, null, 2);
                    detailsEl.innerHTML = `
                        <details>
                            <summary class="cursor-pointer text-gray-400 hover:text-white">View Details</summary>
                            <pre class="mt-1 p-2 bg-gray-900/50 rounded text-gray-400 overflow-x-auto">${jsonStr}</pre>
                        </details>
                    `;
                } catch (e) {
                    detailsEl.innerHTML = `<span class="text-gray-500">[Unable to display details]</span>`;
                }
        }

        stepEl.appendChild(detailsEl);
    }

    parentContainer.appendChild(stepEl);

    // Auto-scroll to latest step
    stepEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Reset conversation agent state on completion
    if (type === 'conversation_agent_complete') {
        state.isConversationAgentActive = false;
    }
}

/**
 * Exported wrapper for rendering conversation agent events during session reload.
 * Uses the same rendering logic as live execution for consistent UX.
 */
export function renderConversationAgentStepForReload(eventData, parentContainer, isFinal = false) {
    _renderConversationAgentStep(eventData, parentContainer, isFinal);
}

function _renderStandardStep(eventData, parentContainer, isFinal = false) {
    const { step, details, type } = eventData;

    // --- UX ENHANCEMENT ---
    // The "Calling LLM" step is transient; it shouldn't stay active.
    // We mark it as 'final' so it renders as completed immediately.
    // The subsequent "Plan Generated" step will become the active one.
    if (step?.startsWith("Calling LLM for")) {
        isFinal = true;
    }
    // --- END ENHANCEMENT ---

    const lastStep = document.getElementById(`status-step-${state.currentStatusId}`);
    if (lastStep && lastStep.classList.contains('active') && parentContainer && parentContainer.contains(lastStep)) {
        lastStep.classList.remove('active');
        lastStep.classList.add('completed');
        if (state.isInFastPath && !lastStep.classList.contains('plan-optimization')) {
            lastStep.classList.add('plan-optimization');
        }
    }

    if (type !== 'plan_optimization') {
        state.isInFastPath = false;
    } else {
        state.isInFastPath = true;
    }

    state.currentStatusId++;
    const stepEl = document.createElement('div');
    stepEl.id = `status-step-${state.currentStatusId}`;
    stepEl.className = 'status-step p-3 rounded-md mb-2'; // Added mb-2 for spacing

    const stepTitle = document.createElement('h4');
    stepTitle.className = 'font-bold text-sm text-white mb-2';
    stepTitle.textContent = step || (type === 'tool_result' ? 'Result' : (type === 'error' ? 'Error' : 'Details'));
    stepEl.appendChild(stepTitle);

    const metricsEl = document.createElement('div');
    metricsEl.className = 'per-call-metrics text-xs text-gray-400 mb-2 hidden';

    if (typeof details === 'object' && details !== null && details.call_id) {
        metricsEl.dataset.callId = details.call_id;
    }
    
    if (typeof details === 'object' && details !== null) {
        // Check for planner tokens (at the root of 'details')
        const planner_input = details.input_tokens;
        const planner_output = details.output_tokens;
        
        // Check for tool tokens (inside 'details.metadata')
        const tool_input = details.metadata?.input_tokens;
        const tool_output = details.metadata?.output_tokens;

        if (planner_input !== undefined && planner_output !== undefined) {
            metricsEl.innerHTML = `(LLM Call: ${planner_input.toLocaleString()} in / ${planner_output.toLocaleString()} out)`;
            metricsEl.classList.remove('hidden');
        } else if (tool_input !== undefined && tool_output !== undefined) {
            metricsEl.innerHTML = `(LLM Call: ${tool_input.toLocaleString()} in / ${tool_output.toLocaleString()} out)`;
            metricsEl.classList.remove('hidden');
        }
    }

    stepEl.appendChild(metricsEl);

    if (details) {
        let customRenderedHtml = null;
        let detailsString = '';

        if (typeof details === 'object' && details !== null) {
            if (step?.startsWith("Calling LLM for")) {
                customRenderedHtml = _renderPlanningDetails(details);
            } else if (type === "plan_generated") {
                customRenderedHtml = _renderMetaPlanDetails(details);
            } else if (type === "tool_intent") {
                customRenderedHtml = _renderToolIntentDetails(details);
            } else if (type === "knowledge_retrieval") {
                customRenderedHtml = _renderKnowledgeRetrievalDetails(details);
                // Trigger the indicator blink when rendering knowledge retrieval event
                if (details.collections && details.collections.length > 0) {
                    blinkKnowledgeDot();
                    updateKnowledgeIndicator(details.collections, details.document_count || 0);
                }
            } else {
                try {
                    const cache = new Set();
                    detailsString = JSON.stringify(details, (key, value) => {
                        if (typeof value === 'object' && value !== null) {
                            if (cache.has(value)) {
                                return '[Circular Reference]';
                            }
                            cache.add(value);
                        }
                        return value;
                    }, 2);
                } catch (e) {
                    detailsString = "[Could not stringify details]";
                    console.error("Error stringifying details:", e, details);
                }
            }
        } else {
            detailsString = String(details);
        }

        if (customRenderedHtml) {
            const detailsContainer = document.createElement('div');
            detailsContainer.innerHTML = customRenderedHtml;
            stepEl.appendChild(detailsContainer);
        } else if (detailsString) {
            const characterThreshold = 300;
            if (detailsString.length > characterThreshold) {
                const detailsEl = document.createElement('details');
                detailsEl.className = 'text-xs';

                const summaryEl = document.createElement('summary');
                summaryEl.className = 'cursor-pointer text-gray-400 hover:text-white';

                let summaryText = `Details (${detailsString.length} chars)`;
                if ((step?.includes('Tool Execution Result') || step?.includes('Tool Execution Error')) && typeof details === 'object' && details !== null) {
                    if (details.results) {
                        const itemCount = Array.isArray(details.results) ? details.results.length : (details.results ? 1 : 0);
                        const status = details.status || 'unknown';
                        summaryText = `Tool Result (${status}, ${itemCount} items)`;
                    } else if (details.type === 'chart') {
                        summaryText = 'Chart Specification';
                    }
                } else if (step?.includes('Final Answer')) {
                    summaryText = `Final Answer Summary`;
                } else if (type === 'cancelled') {
                    summaryText = 'Cancellation Details';
                } else if (type === 'error') {
                    summaryText = 'Error Details';
                }

                summaryEl.textContent = `${summaryText} - Click to expand`;
                detailsEl.appendChild(summaryEl);

                const pre = document.createElement('pre');
                pre.className = 'mt-2 p-2 bg-gray-900/70 rounded-md text-gray-300 overflow-x-auto whitespace-pre-wrap';
                pre.textContent = detailsString;
                detailsEl.appendChild(pre);
                stepEl.appendChild(detailsEl);
            } else {
                const pre = document.createElement('pre');
                pre.className = 'p-2 bg-gray-900/70 rounded-md text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap';
                pre.textContent = detailsString;
                stepEl.appendChild(pre);
            }
        }
    }

    parentContainer.appendChild(stepEl);

    if (type === 'workaround') {
        stepEl.classList.add('workaround');
    } else if (type === 'error') {
        stepEl.classList.add('error');
    } else if (type === 'cancelled') {
        stepEl.classList.add('cancelled');
    } else if (state.isInFastPath) {
        stepEl.classList.add('plan-optimization');
    }

    if (!isFinal) {
        stepEl.classList.add('active');
    } else {
        stepEl.classList.remove('active');
        if (!stepEl.classList.contains('error') && !stepEl.classList.contains('cancelled')) {
            stepEl.classList.add('completed');
        }
    }
}

/**
 * Resets the status window and its related state variables for a new execution.
 */
export function resetStatusWindowForNewTask() {
    DOM.statusWindowContent.innerHTML = '';
    // Remove any existing scroll spacer
    const existingSpacer = document.getElementById('status-scroll-spacer');
    if (existingSpacer) existingSpacer.remove();
    state.currentStatusId = 0;
    state.isRestTaskActive = false;
    state.activeRestTaskId = null;
    state.currentPhaseContainerEl = null;
    state.phaseContainerStack = [];
    state.pendingSubtaskPlanningEvents = [];
    state.isInFastPath = false;
    setThinkingIndicator(false);
    // Reset title to default
    const statusTitle = DOM.statusTitle || document.getElementById('status-title');
    if (statusTitle) {
        statusTitle.textContent = 'Live Status';
    }
}

export function updateStatusWindow(eventData, isFinal = false, source = 'interactive', taskId = null) {
    const { step, details, type, metadata } = eventData;

    const statusTitle = DOM.statusTitle || document.getElementById('status-title');

    if (source === 'rest' && taskId) {
        // Check if this is the first event for a new or different REST task
        if (!state.isRestTaskActive || taskId !== state.activeRestTaskId) {
            resetStatusWindowForNewTask(); // Use the centralized reset function
            state.isRestTaskActive = true; // Set REST-specific state after reset
            state.activeRestTaskId = taskId;
            updateTaskIdDisplay(taskId); // Display the task ID
        }
        statusTitle.textContent = 'Live Status - REST'; // Removed redundant Task ID from title
    } else if (source === 'genie') {
        // Genie coordination events
        if (!state.isGenieCoordinationActive) {
            resetStatusWindowForNewTask();
            state.isGenieCoordinationActive = true;
            state.isRestTaskActive = false;
            updateTaskIdDisplay(null);
        }
        statusTitle.textContent = 'Live Status - Genie Coordination';
        // Render genie events using custom renderer
        _renderGenieStep(eventData, DOM.statusWindowContent, isFinal);
        if (!state.isMouseOverStatus) {
            DOM.statusWindowContent.scrollTop = DOM.statusWindowContent.scrollHeight;
        }
        return;
    } else if (source === 'conversation_agent') {
        // Conversation agent tool execution events
        if (!state.isConversationAgentActive) {
            // Only reset if there's no pending knowledge retrieval event
            // (knowledge_retrieval arrives before conversation_agent_start for conversation_with_tools)
            if (!state.pendingKnowledgeRetrievalEvent) {
                resetStatusWindowForNewTask();
            }
            state.isConversationAgentActive = true;
            state.isRestTaskActive = false;
            state.isGenieCoordinationActive = false;
            updateTaskIdDisplay(null);
        }
        statusTitle.textContent = 'Live Status - Tool Execution';
        // Render conversation agent events using custom renderer
        _renderConversationAgentStep(eventData, DOM.statusWindowContent, isFinal);
        if (!state.isMouseOverStatus) {
            DOM.statusWindowContent.scrollTop = DOM.statusWindowContent.scrollHeight;
        }
        return;
    } else if (source === 'knowledge_retrieval') {
        // Knowledge retrieval events (arrives before conversation_agent_start for conversation_with_tools)
        // Reset the status window if no agent execution is active yet
        if (!state.isConversationAgentActive && !state.isGenieCoordinationActive && !state.isRestTaskActive) {
            resetStatusWindowForNewTask();
            updateTaskIdDisplay(null);
        }
        statusTitle.textContent = 'Live Status - Knowledge Retrieval';
        // Render knowledge retrieval using the conversation agent renderer (same styling)
        _renderConversationAgentStep(eventData, DOM.statusWindowContent, false);
        if (!state.isMouseOverStatus) {
            DOM.statusWindowContent.scrollTop = DOM.statusWindowContent.scrollHeight;
        }
        return;
    } else if (source === 'interactive') {
        // If the last active view was a REST task or agent execution, reset the view
        if (state.isRestTaskActive || state.isGenieCoordinationActive || state.isConversationAgentActive) {
            resetStatusWindowForNewTask();
            updateTaskIdDisplay(null); // Hide the task ID
        }
        statusTitle.textContent = 'Live Status';
    }

    const execution_depth_from_details = details?.execution_depth ?? 0;
    const execution_depth_from_metadata = metadata?.execution_depth ?? 0;
    const execution_depth = Math.max(execution_depth_from_details, execution_depth_from_metadata);

    const isPlanningEvent = step?.startsWith("Calling LLM for") || type === "plan_generated";

    if (isPlanningEvent && execution_depth > 0 && type !== 'phase_start') {
        state.pendingSubtaskPlanningEvents.push(eventData);
        return;
    }

    if (!step && type !== 'phase_start' && type !== 'phase_end') {
        if (type !== 'tool_result' && type !== 'tool_error') {
            return;
        }
    }

    if (type === 'phase_start') {
        const { phase_num, total_phases, goal } = details;

        while (state.phaseContainerStack.length > execution_depth) {
            const oldContainer = state.phaseContainerStack.pop();
            if (oldContainer) {
                oldContainer.classList.add('completed');
            }
        }

        const parentContainer = state.phaseContainerStack.length > 0 ? state.phaseContainerStack[state.phaseContainerStack.length - 1].querySelector('.status-phase-content') : DOM.statusWindowContent;

        const lastStep = Array.from(parentContainer.querySelectorAll(':scope > .status-step')).pop();
        if (lastStep && lastStep.classList.contains('active')) {
            lastStep.classList.remove('active');
            if (!lastStep.classList.contains('plan-optimization')) {
                 lastStep.classList.add('completed');
            }
        }

        const phaseContainer = document.createElement('details');
        phaseContainer.className = 'status-phase-container';
        phaseContainer.open = false; 

        const phaseHeader = document.createElement('summary');
        phaseHeader.className = 'status-phase-header phase-start';

        let depthIndicator = '';
        if (execution_depth > 0) {
            depthIndicator = '↳ '.repeat(execution_depth);
        }

        phaseHeader.innerHTML = `
            <span class="font-bold flex-shrink-0">${depthIndicator}Plan Step ${phase_num}/${total_phases}</span>
            <span class="text-gray-400 text-xs truncate ml-2">${goal}</span>
        `;

        phaseContainer.appendChild(phaseHeader);

        const phaseContent = document.createElement('div');
        phaseContent.className = 'status-phase-content';
        phaseContainer.appendChild(phaseContent);

        if (execution_depth > 0 && state.pendingSubtaskPlanningEvents.length > 0) {
            state.pendingSubtaskPlanningEvents.forEach(event => {
                _renderStandardStep(event, phaseContent, false);
            });
            state.pendingSubtaskPlanningEvents = [];
        }

        parentContainer.appendChild(phaseContainer);
        state.phaseContainerStack.push(phaseContainer);
        state.currentPhaseContainerEl = phaseContainer;

        if (!state.isMouseOverStatus) {
            DOM.statusWindowContent.scrollTop = DOM.statusWindowContent.scrollHeight;
        }
        return;
    }

    if (type === 'phase_end') {
        const containerToEnd = state.phaseContainerStack.pop();
        if (containerToEnd) {
            const phaseContent = containerToEnd.querySelector('.status-phase-content');
            if (phaseContent) {
                const lastStepInPhase = Array.from(phaseContent.childNodes).filter(node => node.classList && node.classList.contains('status-step')).pop();
                if (lastStepInPhase && lastStepInPhase.classList.contains('active')) {
                    lastStepInPhase.classList.remove('active');
                    lastStepInPhase.classList.add('completed');
                }
            }

            const { phase_num, total_phases, status } = details;
            const phaseFooter = document.createElement('div');
            phaseFooter.className = 'status-phase-header phase-end';
            phaseFooter.innerHTML = `<span class="font-bold">Plan Step ${phase_num}/${total_phases} Completed</span>`;

            if (status === 'skipped') {
                phaseFooter.classList.add('skipped');
                phaseFooter.innerHTML = `<span class="font-bold">Plan Step ${phase_num}/${total_phases} Skipped</span>`;
            } else {
                containerToEnd.classList.add('completed');
            }

            containerToEnd.appendChild(phaseFooter);
        }
        state.currentPhaseContainerEl = state.phaseContainerStack.length > 0 ? state.phaseContainerStack[state.phaseContainerStack.length - 1] : null;
        state.isInFastPath = false;
        if (!state.isMouseOverStatus) {
            DOM.statusWindowContent.scrollTop = DOM.statusWindowContent.scrollHeight;
        }
        return;
    }

    const parentEl = state.currentPhaseContainerEl ? state.currentPhaseContainerEl.querySelector('.status-phase-content') : DOM.statusWindowContent;
    _renderStandardStep(eventData, parentEl, isFinal);

    // Breathing space handled via CSS padding-bottom; avoid DOM spacers to prevent layout jumps.

    // Simplified and user-friendly auto-scroll:
    // - Attach a scroll listener once to detect manual scroll-up and pause auto-stick.
    // - Only stick to bottom when auto-scroll is enabled (user near bottom).
    const container = DOM.statusWindowContent;
    if (!state._statusScrollInitialized) {
        state._statusAutoScrollEnabled = true; // assume start near bottom
        container.addEventListener('scroll', () => {
            const dist = container.scrollHeight - container.scrollTop - container.clientHeight;
            // If user moves away from bottom beyond threshold, disable auto-scroll
            if (dist > 40) {
                state._statusAutoScrollEnabled = false;
            } else {
                // Near bottom again -> re-enable
                state._statusAutoScrollEnabled = true;
            }
        }, { passive: true });
        state._statusScrollInitialized = true;
    }

    // If the container is at the very top (e.g., after plan reload), do not auto-stick.
    if (container.scrollTop === 0) {
        state._statusAutoScrollEnabled = false;
    }

    if (state._statusAutoScrollEnabled) {
        // Use rAF to ensure layout finalized before scrolling
        requestAnimationFrame(() => {
            const lastStep = parentEl.querySelector(':scope > .status-step:last-of-type')
                || container.querySelector('.status-step:last-of-type');
            if (lastStep && typeof lastStep.scrollIntoView === 'function') {
                lastStep.scrollIntoView({ behavior: 'auto', block: 'end' });
            } else {
                container.scrollTop = container.scrollHeight;
            }
        });
    }
}

/**
 * Updates the display of the current task ID in the status window header.
 * Includes functionality to copy the task ID to the clipboard.
 * @param {string|null} taskId - The task ID to display, or null to hide the display.
 */
export function updateTaskIdDisplay(taskId) {
    if (DOM.taskIdDisplay && DOM.taskIdValue && DOM.copyTaskIdButton) {
        if (taskId) {
            DOM.taskIdValue.textContent = `Task ID: ${taskId.substring(0, 8)}...`;
            DOM.taskIdDisplay.classList.remove('hidden');

            // Remove any existing event listener to prevent duplicates
            DOM.copyTaskIdButton.onclick = null; 
            DOM.copyTaskIdButton.onclick = () => {
                navigator.clipboard.writeText(taskId).then(() => {
                    // Provide visual feedback
                    const originalIcon = DOM.copyTaskIdButton.innerHTML;
                    DOM.copyTaskIdButton.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-green-500" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg>`;
                    setTimeout(() => {
                        DOM.copyTaskIdButton.innerHTML = originalIcon;
                    }, 2000);
                }).catch(err => {
                    console.error('Failed to copy task ID: ', err);
                });
            };
        } else {
            DOM.taskIdDisplay.classList.add('hidden');
            DOM.taskIdValue.textContent = '';
            DOM.copyTaskIdButton.onclick = null; // Clear event listener
        }
    }
}

/**
 * Provides a visual cue on a session in the list to show it has new, unseen activity.
 * @param {string} sessionId The ID of the session to highlight.
 */
export function highlightSession(sessionId) {
    const sessionItem = document.getElementById(`session-${sessionId}`);
    if (sessionItem && !sessionItem.classList.contains('active')) {
        const nameSpan = sessionItem.querySelector('.session-name-span');
        if (nameSpan) {
            nameSpan.classList.add('font-bold', 'text-teradata-orange');
        }
        // Add a blinking dot or similar indicator
        let indicator = sessionItem.querySelector('.new-activity-indicator');
        if (!indicator) {
            indicator = document.createElement('span');
            indicator.className = 'new-activity-indicator';
            sessionItem.querySelector('.flex').prepend(indicator);
        }
    }
}

/**
 * Moves a session item to the top of the session list.
 * For Genie slave sessions, maintains hierarchical order by moving after the last sibling slave.
 * @param {string} sessionId - The ID of the session to move.
 */
export function moveSessionToTop(sessionId) {
    const sessionItem = document.getElementById(`session-${sessionId}`);
    if (!sessionItem || !DOM.sessionList) return;

    // Check if this is a Genie slave session
    const isGenieSlave = sessionItem.dataset.genieParentId;
    const parentSessionId = sessionItem.dataset.genieParentId;

    if (isGenieSlave && parentSessionId) {
        // For slave sessions, maintain hierarchical order
        // Find the parent and all its existing slaves
        const parentElement = document.getElementById(`session-${parentSessionId}`);
        if (!parentElement) {
            // Parent not found, fallback to top
            sessionItem.remove();
            DOM.sessionList.prepend(sessionItem);
            return;
        }

        // Find all sibling slaves (same parent)
        const allSlaves = Array.from(DOM.sessionList.querySelectorAll('.genie-slave-session'))
            .filter(el => el.dataset.genieParentId === parentSessionId && el.id !== sessionItem.id);

        // Remove the session from its current position
        sessionItem.remove();

        if (allSlaves.length === 0) {
            // No other slaves, insert directly after parent
            parentElement.insertAdjacentElement('afterend', sessionItem);
        } else {
            // Insert after the last sibling slave
            const lastSlave = allSlaves[allSlaves.length - 1];
            lastSlave.insertAdjacentElement('afterend', sessionItem);
        }
    } else {
        // Regular session (not a slave) - move to top
        sessionItem.remove();
        DOM.sessionList.prepend(sessionItem);
    }
}


export function updateTokenDisplay(data) {
    const normalDisplay = document.getElementById('token-normal-display');
    const awsMessage = document.getElementById('token-aws-message');

    // Check if we have token data (for any provider including Amazon)
    const hasTokenData = (data.statement_input > 0 || data.statement_output > 0 || 
                         data.total_input > 0 || data.total_output > 0);

    // Check if this is an AWS model that doesn't support token counting
    // Only Cohere, Mistral, and AI21 don't provide token counts
    const isUnsupportedAwsModel = state.currentProvider === 'Amazon' && 
        state.currentModel && (
            state.currentModel.toLowerCase().includes('cohere') ||
            state.currentModel.toLowerCase().includes('mistral') ||
            state.currentModel.toLowerCase().includes('ai21')
        );

    if (isUnsupportedAwsModel && !hasTokenData) {
        // Only show warning message for Cohere/Mistral/AI21 without token data
        normalDisplay.classList.add('hidden');
        awsMessage.classList.remove('hidden');
        return;
    }

    // Show normal display for all other cases (including Nova, Titan, Llama, Claude)
    normalDisplay.classList.remove('hidden');
    awsMessage.classList.add('hidden');

    document.getElementById('statement-input-tokens').textContent = (data.statement_input || 0).toLocaleString();
    document.getElementById('statement-output-tokens').textContent = (data.statement_output || 0).toLocaleString();
    document.getElementById('total-input-tokens').textContent = (data.total_input || 0).toLocaleString();
    document.getElementById('total-output-tokens').textContent = (data.total_output || 0).toLocaleString();
}

// --- MODIFICATION START: Add function to refresh all feedback button states ---
/**
 * Refreshes all feedback button states based on current state.feedbackByTurn.
 * Should be called after loading a session to restore visual feedback state.
 */
export function refreshFeedbackButtons() {
    // Find all feedback wrappers in the chat
    const feedbackWrappers = document.querySelectorAll('[data-turn-id]');
    
    feedbackWrappers.forEach(wrapper => {
        const turnId = parseInt(wrapper.dataset.turnId);
        if (isNaN(turnId)) return;
        
        const upBtn = wrapper.querySelector('[data-vote="up"]');
        const downBtn = wrapper.querySelector('[data-vote="down"]');
        
        if (!upBtn || !downBtn) return;
        
        const current = state.feedbackByTurn[turnId] || 'none';
        
        // Update active states
        upBtn.classList.toggle('active', current === 'up');
        downBtn.classList.toggle('active', current === 'down');
        
        // Update aria attributes
        upBtn.setAttribute('aria-pressed', current === 'up' ? 'true' : 'false');
        downBtn.setAttribute('aria-pressed', current === 'down' ? 'true' : 'false');
        
        // Update visual styling
        if (current === 'up') {
            upBtn.classList.remove('text-gray-300');
            upBtn.classList.add('text-[#F15F22]', 'bg-gray-800/60');
            downBtn.classList.add('text-gray-300');
            downBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
        } else if (current === 'down') {
            downBtn.classList.remove('text-gray-300');
            downBtn.classList.add('text-[#F15F22]', 'bg-gray-800/60');
            upBtn.classList.add('text-gray-300');
            upBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
        } else {
            upBtn.classList.add('text-gray-300');
            upBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
            downBtn.classList.add('text-gray-300');
            downBtn.classList.remove('text-[#F15F22]', 'bg-gray-800/60');
        }
    });
}
// --- MODIFICATION END ---

export function setThinkingIndicator(isThinking) {
    if (isThinking) {
        DOM.promptNameDisplay.classList.add('hidden');
        DOM.thinkingIndicator.classList.remove('hidden');
        DOM.thinkingIndicator.classList.add('flex');
    } else {
        DOM.thinkingIndicator.classList.add('hidden');
        DOM.thinkingIndicator.classList.remove('flex');
        DOM.promptNameDisplay.classList.remove('hidden');
    }
}

export function updateStatusPromptName(provider = null, model = null, isHistorical = false) {
    const promptNameDiv = document.getElementById('prompt-name-display');

    // Use the provided args, or fall back to the global state
    const providerToShow = provider || state.currentProvider;
    const modelToShow = model || state.currentModel;

    if (providerToShow && modelToShow) {
        const isCustom = isPromptCustomForModel(providerToShow, modelToShow);
        const promptType = isPrivilegedUser() ? (isCustom ? 'Custom' : 'Default') : 'Default (Server-Side)';
        
        // Add a visual indicator if we are showing a *historical* turn's model
        const historicalIndicator = isHistorical ? ' (History)' : '';

        promptNameDiv.innerHTML = `
            <span class="font-semibold text-gray-300">${promptType} Prompt${historicalIndicator}</span>
            <span class="text-gray-500">/</span>
            <span class="font-mono text-teradata-orange text-xs">${providerToShow}/${getNormalizedModelId(modelToShow)}</span>
        `;
    } else {
        promptNameDiv.innerHTML = '<span>No Model/Prompt Loaded</span>';
    }
}


export function createResourceItem(resource, type) {
    const detailsEl = document.createElement('details');
    detailsEl.id = `resource-${type}-${resource.name}`;
    detailsEl.className = 'resource-item bg-gray-800/50 rounded-lg border border-gray-700/60';

    if (resource.disabled) {
        detailsEl.classList.add('opacity-60');
        detailsEl.title = `This ${type.slice(0, -1)} is disabled and will not be used by the agent.`;
    }

    const toggleIcon = resource.disabled ?
        `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074L3.707 2.293zM10 12a2 2 0 110-4 2 2 0 010 4z" clip-rule="evenodd" /><path d="M2 10s3.939 4 8 4 8-4 8-4-3.939-4-8-4-8 4-8 4zm13.707 4.293a1 1 0 00-1.414-1.414L12.586 14.6A8.007 8.007 0 0110 16c-4.478 0-8.268-2.943-9.542-7 .946-2.317 2.83-4.224 5.166-5.447L2.293 1.293A1 1 0 00.879 2.707l14 14a1 1 0 001.414 0z" /></svg>` :
        `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z" /><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.022 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd" /></svg>`;

    let argsHTML = '';
    if (resource.arguments && resource.arguments.length > 0) {
        argsHTML += `<div class="mt-4 pt-3 border-t border-gray-700/60">
                                <h5 class="font-semibold text-sm text-white mb-2">Parameters</h5>
                                <ul class="space-y-2 text-xs">`;
        resource.arguments.forEach(arg => {
            const requiredText = arg.required ? '<span class="text-red-400 font-bold">Required</span>' : '<span class="text-gray-400">Optional</span>';
            const typeText = arg.type && arg.type !== 'unknown' ? `<span class="font-mono text-xs text-cyan-400 bg-cyan-400/10 px-1.5 py-0.5 rounded-md">${arg.type}</span>` : '';

            argsHTML += `<li class="p-2 bg-black/20 rounded-md">
                                    <div class="flex justify-between items-center">
                                        <div class="flex items-center gap-x-2">
                                            <code class="font-semibold text-teradata-orange">${arg.name}</code>
                                            ${typeText}
                                        </div>
                                        ${requiredText}
                                    </div>
                                    <p class="text-gray-400 mt-1">${arg.description}</p>
                                 </li>`;
        });
        argsHTML += `</ul></div>`;
    }

    let contentHTML = '';
    if (type === 'prompts') {
        const runButtonDisabledAttr = ''; // Always enabled
        const runButtonTitle = 'Run this prompt.'; // Always use this title

        contentHTML = `
            <div class="p-3 pt-2 text-sm text-gray-300 space-y-3">
                <p>${resource.description}</p>
                ${argsHTML}
                <div class="flex justify-end items-center gap-x-2 pt-3 border-t border-gray-700/60">
                    <button class="prompt-toggle-button p-1.5 text-gray-300 hover:text-white hover:bg-white/10 rounded-md transition-colors">${toggleIcon}</button>
                    <button class="view-prompt-button px-3 py-1 bg-gray-600 text-white text-xs font-semibold rounded-md hover:bg-gray-500 transition-colors">Prompt</button>
                    <button class="run-prompt-button px-3 py-1 bg-teradata-orange text-white text-xs font-semibold rounded-md hover:bg-teradata-orange-dark transition-colors" ${runButtonDisabledAttr} title="${runButtonTitle}">Run</button>
                </div>
            </div>`;
    } else if (type === 'tools') {
        contentHTML = `
            <div class="p-3 pt-2 text-sm text-gray-300 space-y-3">
                <p>${resource.description}</p>
                ${argsHTML}
                <div class="flex justify-end items-center pt-3 border-t border-gray-700/60">
                    <button class="tool-toggle-button p-1.5 text-gray-300 hover:text-white hover:bg-white/10 rounded-md transition-colors">${toggleIcon}</button>
                </div>
            </div>`;
    } else { // For resources
        contentHTML = `
            <div class="p-3 pt-2 text-sm text-gray-300 border-t border-gray-700/60 flex justify-between items-center">
                <p>${resource.description}</p>
            </div>`;
    }

    detailsEl.innerHTML = `
        <summary class="flex justify-between items-center p-3 font-semibold text-white hover:bg-gray-700/50 rounded-lg transition-colors cursor-pointer">
            <span>${resource.name}</span>
            <svg class="chevron w-5 h-5 text-[#F15F22] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
        </summary>
        ${contentHTML}
    `;

    return detailsEl;
}

export function updatePromptsTabCounter() {
    const tabButton = document.querySelector('.resource-tab[data-type="prompts"]');
    if (!tabButton || !state.resourceData.prompts) return;
    let totalCount = 0;
    let disabledCount = 0;
    Object.values(state.resourceData.prompts).forEach(items => {
        totalCount += items.length;
        disabledCount += items.filter(item => item.disabled).length;
    });
    const disabledIndicator = disabledCount > 0 ? '*' : '';
    tabButton.textContent = `Prompts (${totalCount})${disabledIndicator}`;
}

export function updateToolsTabCounter() {
    const tabButton = document.querySelector('.resource-tab[data-type="tools"]');
    if (!tabButton || !state.resourceData.tools) return;
    let totalCount = 0;
    let disabledCount = 0;
    Object.values(state.resourceData.tools).forEach(items => {
        totalCount += items.length;
        disabledCount += items.filter(item => item.disabled).length;
    });
    const disabledIndicator = disabledCount > 0 ? '*' : '';
    tabButton.textContent = `Tools (${totalCount})${disabledIndicator}`;
}

export function highlightResource(resourceName, type) {
    if (state.currentlySelectedResource) {
        state.currentlySelectedResource.classList.remove('resource-selected');
    }

    let resourceCategory = null;
    if (state.resourceData[type]) {
        for (const category in state.resourceData[type]) {
            if (state.resourceData[type][category].some(r => r.name === resourceName)) {
                resourceCategory = category;
                break;
            }
        }
    }


    if (resourceCategory) {
        const resourceTab = document.querySelector(`.resource-tab[data-type="${type}"]`);
        if (resourceTab) resourceTab.click();

        const categoryTab = document.querySelector(`.category-tab[data-type="${type}"][data-category="${resourceCategory}"]`);
        if(categoryTab) categoryTab.click();

        const resourceElement = document.getElementById(`resource-${type}-${resourceName}`);
        if (resourceElement) {
            resourceElement.open = true;
            resourceElement.classList.add('resource-selected');
            state.currentlySelectedResource = resourceElement;

            setTimeout(() => {
                resourceElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 350);
        }
    } else {
    }
}

export function addSessionToList(session, isActive = false) {
    const sessionItem = document.createElement('div');
    sessionItem.id = `session-${session.id}`;
    sessionItem.dataset.sessionId = session.id;
    sessionItem.dataset.isTemporary = session.is_temporary ? 'true' : 'false';
    sessionItem.className = 'session-item w-full text-left p-3 rounded-lg hover:bg-white/10 transition-colors cursor-pointer';
    
    // Add purple left border for utility sessions
    if (session.is_temporary) {
        sessionItem.style.borderLeft = '3px solid rgba(139, 92, 246, 0.6)';
        sessionItem.style.paddingLeft = '0.625rem'; // Adjust padding to compensate for border
    }

    // Check for Genie slave session metadata
    const genieMetadata = session.genie_metadata || {};
    const isGenieSlave = genieMetadata.is_genie_slave || false;
    const genieParentSessionId = genieMetadata.parent_session_id;

    // Check if this session is a genie master (has slave sessions pointing to it)
    // This is set by markGenieMasterSessions() after all sessions are loaded
    const isGenieMaster = session._isGenieMaster || false;

    // Add orange left border and indentation for Genie slave sessions
    if (isGenieSlave) {
        sessionItem.classList.add('genie-slave-session');
        sessionItem.style.borderLeft = '3px solid #F15F22';
        sessionItem.style.marginLeft = '1rem';
        sessionItem.style.paddingLeft = '0.625rem';
        sessionItem.dataset.genieParentId = genieParentSessionId || '';

        // Check if slaves should be hidden (parent is collapsed)
        const collapseState = getGenieCollapseState();
        if (collapseState[genieParentSessionId]) {
            sessionItem.classList.add('genie-slave-hidden');
        }
    }

    // Mark genie master sessions for later identification
    if (isGenieMaster) {
        sessionItem.classList.add('genie-master-session');
        sessionItem.dataset.isGenieMaster = 'true';
    }

    if (isActive) {
        document.querySelectorAll('.session-item').forEach(item => item.classList.remove('active'));
        sessionItem.classList.add('active');
    }

    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'w-full flex flex-col';

    const topRow = document.createElement('div');
    topRow.className = 'flex justify-between items-center';

    const nameContainer = document.createElement('div');
    nameContainer.className = 'flex-1 min-w-0';
    
    const nameSpan = document.createElement('span');
    nameSpan.className = 'session-name-span font-semibold text-sm text-white truncate block';
    nameSpan.textContent = session.name;
    nameContainer.appendChild(nameSpan);
    
    // Add utility indicator badge for temporary sessions
    if (session.is_temporary) {
        const utilityBadge = document.createElement('span');
        utilityBadge.className = 'inline-flex items-center gap-1 mt-0.5 text-xs text-purple-400';
        utilityBadge.innerHTML = `
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span class="truncate">${session.temporary_purpose || 'utility'}</span>
        `;
        utilityBadge.title = session.temporary_purpose || 'Utility session';
        nameContainer.appendChild(utilityBadge);
    }

    // Add Genie slave indicator badge
    if (isGenieSlave) {
        const genieBadge = document.createElement('span');
        genieBadge.className = 'genie-slave-badge inline-flex items-center gap-1 mt-0.5 text-xs';
        genieBadge.innerHTML = `
            <span class="genie-badge-icon">G</span>
            <span class="text-[#F15F22]">Genie Slave</span>
        `;
        genieBadge.title = 'Spawned by Genie coordinator';

        // Add click handler to navigate to parent session
        if (genieParentSessionId) {
            const parentLink = document.createElement('button');
            parentLink.className = 'genie-parent-link ml-1 text-[#F15F22] hover:text-[#FF8C00] transition-colors';
            parentLink.innerHTML = '↑';
            parentLink.title = 'Go to parent Genie session';
            parentLink.addEventListener('click', (e) => {
                e.stopPropagation();
                const parentItem = document.getElementById(`session-${genieParentSessionId}`);
                if (parentItem) {
                    parentItem.click();
                    parentItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            });
            genieBadge.appendChild(parentLink);
        }
        nameContainer.appendChild(genieBadge);
    }

    // Add Genie master indicator badge with collapse toggle
    if (isGenieMaster) {
        const genieMasterBadge = document.createElement('span');
        genieMasterBadge.className = 'genie-master-badge inline-flex items-center gap-1 mt-0.5 text-xs cursor-pointer';

        // Check current collapse state
        const collapseState = getGenieCollapseState();
        const isCollapsed = collapseState[session.id] || false;

        genieMasterBadge.innerHTML = `
            <span class="genie-badge-icon">G</span>
            <span class="text-[#F15F22]">Genie Master</span>
            <span class="genie-collapse-toggle ml-1 text-[#F15F22] hover:text-[#FF8C00] transition-colors">${isCollapsed ? '▶' : '▼'}</span>
        `;
        genieMasterBadge.title = 'Click to collapse/expand slave sessions';

        // Add click handler to toggle slave sessions visibility
        genieMasterBadge.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleGenieSlaveVisibility(session.id);
        });

        nameContainer.appendChild(genieMasterBadge);
    }

    topRow.appendChild(nameContainer);

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'session-actions flex-shrink-0 flex items-center';

    const editButton = document.createElement('button');
    editButton.type = 'button';
    editButton.className = 'session-action-button session-edit-button';
    editButton.title = 'Rename session';
    editButton.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-11.202 11.202a.5.5 0 01-.293.146H3.5a.5.5 0 01-.5-.5v-1.414a.5.5 0 01.146-.293l11.202-11.202zM15.707 2.293a1 1 0 010 1.414L5.414 14H4v-1.414L14.293 2.293a1 1 0 011.414 0z" /></svg>`;
    actionsDiv.appendChild(editButton);

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'session-action-button session-delete-button';
    deleteButton.title = 'Delete session';
    deleteButton.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M6 2a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V4a2 2 0 00-2-2H6zm2 3a1 1 0 11-2 0 1 1 0 012 0zm4 0a1 1 0 11-2 0 1 1 0 012 0z" clip-rule="evenodd" /></svg>`;
    actionsDiv.appendChild(deleteButton);

    const copyButton = document.createElement('button');
    copyButton.type = 'button';
    copyButton.className = 'session-action-button session-copy-button';
    copyButton.title = 'Copy session ID';
    copyButton.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
    copyButton.addEventListener('click', (e) => {
        e.stopPropagation();
        const sessionId = sessionItem.dataset.sessionId;
        navigator.clipboard.writeText(sessionId).then(() => {
            copyButton.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
            setTimeout(() => {
                copyButton.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
            }, 2000);
        }).catch(err => {
            console.error('Failed to copy session ID: ', err);
        });
    });
    actionsDiv.appendChild(copyButton);

    topRow.appendChild(actionsDiv);
    contentWrapper.appendChild(topRow);

    const lastUpdatedSpan = document.createElement('span');
    lastUpdatedSpan.className = 'session-last-updated text-xs text-gray-300 mt-1';
    if (session.last_updated && session.last_updated !== "Unknown") {
        lastUpdatedSpan.textContent = `Updated: ${new Date(session.last_updated).toLocaleString()}`;
    } else {
        lastUpdatedSpan.textContent = 'Updated: Unknown';
    }
    contentWrapper.appendChild(lastUpdatedSpan);

    // Display profile tags (preferred) or fall back to models_used
    const tagsDiv = document.createElement('div');
    tagsDiv.className = 'session-models text-xs text-gray-400 mt-1 flex flex-wrap gap-1';
    
    // Debug logging with expanded arrays
    console.log('[DEBUG] Session data:', {
        id: session.id,
        profile_tags_used: session.profile_tags_used,
        models_used: session.models_used,
        provider: session.provider,
        model: session.model,
        has_profile_tags: session.profile_tags_used && Array.isArray(session.profile_tags_used) && session.profile_tags_used.length > 0
    });
    console.log('[DEBUG] models_used expanded:', session.models_used);
    console.log('[DEBUG] profile_tags_used expanded:', session.profile_tags_used);
    
    // Prefer profile_tags_used over models_used
    if (session.profile_tags_used && Array.isArray(session.profile_tags_used) && session.profile_tags_used.length > 0) {
        console.log('[DEBUG] Using profile tags:', session.profile_tags_used);
        session.profile_tags_used.forEach(tag => {
            const tagSpan = document.createElement('span');
            tagSpan.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-semibold';
            
            // Find profile by tag to get color
            const profile = window.configState?.profiles?.find(p => p.tag === tag);
            if (profile && profile.color) {
                // Helper to convert hex to rgba
                const hexToRgba = (hex, alpha) => {
                    const r = parseInt(hex.slice(1, 3), 16);
                    const g = parseInt(hex.slice(3, 5), 16);
                    const b = parseInt(hex.slice(5, 7), 16);
                    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
                };
                const color1 = hexToRgba(profile.color, 0.3);
                const color2 = hexToRgba(profile.color, 0.15);
                const borderColor = hexToRgba(profile.color, 0.5);
                tagSpan.style.background = `linear-gradient(135deg, ${color1}, ${color2})`;
                tagSpan.style.borderColor = borderColor;
                tagSpan.style.color = profile.color;
                tagSpan.style.border = '1px solid';
                // Add color dot
                const dot = document.createElement('span');
                dot.className = 'w-1.5 h-1.5 rounded-full';
                dot.style.background = profile.color;
                tagSpan.appendChild(dot);
            } else {
                // Fallback to orange if no color
                tagSpan.className += ' bg-[#F15F22]/20 text-[#F15F22] border border-[#F15F22]/30';
            }
            
            const text = document.createElement('span');
            text.textContent = `@${tag}`;
            tagSpan.appendChild(text);
            tagsDiv.appendChild(tagSpan);
        });
    } else if (session.models_used && Array.isArray(session.models_used) && session.models_used.length > 0) {
        console.log('[DEBUG] Falling back to models_used:', session.models_used);
        // Fallback to models_used for backwards compatibility
        session.models_used.forEach(modelString => {
            const modelSpan = document.createElement('span');
            modelSpan.className = 'inline-block bg-gray-700 rounded-full px-2 py-0.5 text-xs font-medium text-gray-300';
            modelSpan.textContent = modelString;
            tagsDiv.appendChild(modelSpan);
        });
    }
    contentWrapper.appendChild(tagsDiv);

    sessionItem.appendChild(contentWrapper);

    return sessionItem;
}

/**
 * Updates the displayed name of a session item in the history list.
 * @param {string} sessionId - The ID of the session to update.
 * @param {string} newName - The new name for the session.
 */
export function updateSessionListItemName(sessionId, newName) {
    const sessionItem = document.getElementById(`session-${sessionId}`);
    if (sessionItem) {
        const nameSpan = sessionItem.querySelector('.session-name-span');
        if (nameSpan) {
            nameSpan.textContent = newName;
        } else {
        }
    } else {
    }
}

export function updateSessionModels(sessionId, models_used, profile_tags_used = null) {
    const sessionItem = document.getElementById(`session-${sessionId}`);
    if (sessionItem) {
        let tagsDiv = sessionItem.querySelector('.session-models');
        if (!tagsDiv) {
            tagsDiv = document.createElement('div');
            tagsDiv.className = 'session-models text-xs text-gray-400 mt-1 flex flex-wrap gap-1';
            const contentWrapper = sessionItem.querySelector('.w-full');
            if(contentWrapper) {
                contentWrapper.appendChild(tagsDiv);
            }
        }
        tagsDiv.innerHTML = ''; // Clear existing tags/models
        
        // Prefer profile_tags_used over models_used
        if (profile_tags_used && Array.isArray(profile_tags_used) && profile_tags_used.length > 0) {
            profile_tags_used.forEach(tag => {
                const tagSpan = document.createElement('span');
                tagSpan.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-semibold';
                
                // Find profile by tag to get color
                const profile = window.configState?.profiles?.find(p => p.tag === tag);
                if (profile && profile.color) {
                    // Helper to convert hex to rgba
                    const hexToRgba = (hex, alpha) => {
                        const r = parseInt(hex.slice(1, 3), 16);
                        const g = parseInt(hex.slice(3, 5), 16);
                        const b = parseInt(hex.slice(5, 7), 16);
                        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
                    };
                    const color1 = hexToRgba(profile.color, 0.3);
                    const color2 = hexToRgba(profile.color, 0.15);
                    const borderColor = hexToRgba(profile.color, 0.5);
                    tagSpan.style.background = `linear-gradient(135deg, ${color1}, ${color2})`;
                    tagSpan.style.borderColor = borderColor;
                    tagSpan.style.color = profile.color;
                    tagSpan.style.border = '1px solid';
                    // Add color dot
                    const dot = document.createElement('span');
                    dot.className = 'w-1.5 h-1.5 rounded-full';
                    dot.style.background = profile.color;
                    tagSpan.appendChild(dot);
                } else {
                    // Fallback to orange if no color
                    tagSpan.className += ' bg-[#F15F22]/20 text-[#F15F22] border border-[#F15F22]/30';
                }
                
                const text = document.createElement('span');
                text.textContent = `@${tag}`;
                tagSpan.appendChild(text);
                tagsDiv.appendChild(tagSpan);
            });
        } else if (models_used && Array.isArray(models_used) && models_used.length > 0) {
            // Fallback to models_used for backwards compatibility
            models_used.forEach(modelString => {
                const modelSpan = document.createElement('span');
                modelSpan.className = 'inline-block bg-gray-700 rounded-full px-2 py-0.5 text-xs font-medium text-gray-300';
                modelSpan.textContent = modelString;
                tagsDiv.appendChild(modelSpan);
            });
        }

        if (state.currentSessionId === sessionId) {
            document.querySelectorAll('.session-item').forEach(item => item.classList.remove('active'));
            sessionItem.classList.add('active');
        }
    }
}

// --- NEW: Update the active session title in the header ---
export function updateActiveSessionTitle(newName) {
    const titleEl = document.getElementById('active-session-title');
    const wrapperEl = document.getElementById('active-session-title-wrapper');
    
    if (titleEl) {
        titleEl.textContent = newName || 'Unnamed Session';
    }
    
    // Show the wrapper when we have a session loaded (after configuration)
    if (wrapperEl) {
        if (newName) {
            wrapperEl.classList.remove('hidden');
        } else {
            wrapperEl.classList.add('hidden');
        }
    }
}

// --- NEW: Enter edit mode for active session title ---
export function enterActiveSessionTitleEdit() {
    const titleEl = document.getElementById('active-session-title');
    if (!titleEl) return;
    // Prevent multiple edit inputs
    if (document.getElementById('active-session-title-input')) return;

    const currentName = titleEl.textContent.trim();
    const input = document.createElement('input');
    input.type = 'text';
    input.id = 'active-session-title-input';
    input.className = 'bg-gray-700 text-white px-2 py-1 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-teradata-orange w-64';
    input.value = currentName;
    input.dataset.originalName = currentName;

    // Replace span with input
    titleEl.replaceWith(input);
    if (DOM.activeSessionTitleEditingHint) {
        DOM.activeSessionTitleEditingHint.classList.remove('hidden');
    }
    input.focus();

    // Only allow one handler to run (blur or keydown)
    let finished = false;
    function finishEdit(action, value) {
        if (finished) return;
        finished = true;
        if (action === 'save') {
            saveActiveSessionTitleEdit(value);
        } else {
            cancelActiveSessionTitleEdit();
        }
    }

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const newName = input.value.trim();
            if (!newName) {
                finishEdit('cancel');
                return;
            }
            finishEdit('save', newName);
        } else if (e.key === 'Escape') {
            finishEdit('cancel');
        }
    });

    input.addEventListener('blur', () => {
        const newName = input.value.trim();
        if (newName && newName !== input.dataset.originalName) {
            finishEdit('save', newName);
        } else {
            finishEdit('cancel');
        }
    });
}

// --- NEW: Cancel editing of active session title ---
export function cancelActiveSessionTitleEdit() {
    const input = document.getElementById('active-session-title-input');
    if (!input || !input.parentNode) return;
    const originalName = input.dataset.originalName || 'Unnamed Session';
    const span = document.createElement('span');
    span.id = 'active-session-title';
    span.className = 'text-lg font-semibold text-white cursor-pointer';
    span.textContent = originalName;
    input.replaceWith(span);
    if (DOM.activeSessionTitleEditingHint) {
        DOM.activeSessionTitleEditingHint.classList.add('hidden');
    }
}

// --- NEW: Save editing of active session title ---
export function saveActiveSessionTitleEdit(newName) {
    const input = document.getElementById('active-session-title-input');
    if (!input || !input.parentNode) return;
    const span = document.createElement('span');
    span.id = 'active-session-title';
    span.className = 'text-lg font-semibold text-white cursor-pointer';
    span.textContent = newName;
    input.replaceWith(span);
    if (DOM.activeSessionTitleEditingHint) {
        DOM.activeSessionTitleEditingHint.classList.add('hidden');
    }
    // Fire custom event to trigger rename logic elsewhere (decouple UI and logic)
    const renameEvent = new CustomEvent('activeSessionTitleRenamed', { detail: { newName } });
    document.dispatchEvent(renameEvent);
}

export function updateSessionTimestamp(sessionId, last_updated) {
    const sessionItem = document.getElementById(`session-${sessionId}`);
    if (sessionItem) {
        let lastUpdatedSpan = sessionItem.querySelector('.session-last-updated');
        if (!lastUpdatedSpan) {
            lastUpdatedSpan = document.createElement('span');
            lastUpdatedSpan.className = 'session-last-updated text-xs text-gray-300';
            const infoDiv = sessionItem.querySelector('.flex-col');
            if (infoDiv) {
                const nameSpan = infoDiv.querySelector('.session-name-span');
                if (nameSpan) {
                    nameSpan.after(lastUpdatedSpan);
                } else {
                    infoDiv.prepend(lastUpdatedSpan);
                }
            }
        }
        lastUpdatedSpan.textContent = `Updated: ${new Date(last_updated).toLocaleString()}`;
    }
}

/**
 * Removes a session item from the history list in the DOM.
 * @param {string} sessionId - The ID of the session to remove.
 */
export function removeSessionFromList(sessionId) {
    const sessionItem = document.getElementById(`session-${sessionId}`);
    if (sessionItem) {
        sessionItem.remove();
    } else {
    }
}


/**
 * Switches a session list item's name span to an input field for editing.
 * @param {HTMLButtonElement} editButton - The edit button element that was clicked.
 */
export function enterSessionEditMode(editButton) {
    const sessionItem = editButton.closest('.session-item');
    if (!sessionItem || sessionItem.querySelector('.session-edit-input')) {
        return;
    }

    const spanElement = sessionItem.querySelector('.session-name-span');
    const actionsDiv = sessionItem.querySelector('.session-actions');
    if (!spanElement || !actionsDiv) return;

    const currentName = spanElement.textContent;
    const inputElement = document.createElement('input');
    inputElement.type = 'text';
    inputElement.value = currentName;
    inputElement.dataset.originalName = currentName;
    inputElement.className = 'session-edit-input flex-grow min-w-0 w-full p-1 bg-gray-800 border border-gray-600 rounded-md text-sm text-white'; // Added flex-grow and adjusted colors

    spanElement.style.display = 'none';
    actionsDiv.style.display = 'none';

    const topRow = sessionItem.querySelector('.flex.justify-between.items-center');
    if (!topRow) return; // Should not happen if addSessionToList creates it correctly

    // Ensure the topRow is a flex container that allows the input to grow
    topRow.classList.add('flex', 'items-center'); // Ensure flex properties are present
    spanElement.replaceWith(inputElement);

    inputElement.focus();
    inputElement.select();

    inputElement.addEventListener('blur', handleSessionRenameSave);
    inputElement.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleSessionRenameSave(e);
        } else if (e.key === 'Escape') {
            handleSessionRenameCancel(e);
        }
    });
}

/**
 * Switches a session list item back from input mode to display mode.
 * @param {HTMLInputElement} inputElement - The input element currently being edited.
 * @param {string} finalName - The name to display in the span (either original or new).
 */
export function exitSessionEditMode(inputElement, finalName) {
    const sessionItem = inputElement.closest('.session-item');
    if (!sessionItem) return;

    // Create a new span element to replace the input field
    const newSpanElement = document.createElement('span');
    newSpanElement.className = 'session-name-span text-white text-sm font-semibold truncate'; // Ensure original classes are applied
    newSpanElement.textContent = finalName;

    // Replace the input element with the new span element
    inputElement.replaceWith(newSpanElement);

    const actionsDiv = sessionItem.querySelector('.session-actions');
    if (actionsDiv) {
        actionsDiv.style.display = ''; // Show actions div again
    }

    inputElement.removeEventListener('blur', handleSessionRenameSave);
}


export function updateConfigButtonState() {
    // This function is obsolete with the new configuration UI
    // The old config modal elements (configActionButton, configActionButtonText, configForm) no longer exist
    // Keeping the function for backwards compatibility but making it a no-op
    return;
}

export function showConfirmation(title, body, onConfirm) {
    DOM.confirmModalTitle.textContent = title;
    DOM.confirmModalBody.textContent = body;

    DOM.confirmModalOverlay.classList.remove('hidden', 'opacity-0');
    DOM.confirmModalContent.classList.remove('scale-95', 'opacity-0');

    const confirmHandler = () => {
        onConfirm();
        closeConfirmation();
    };

    const cancelHandler = () => {
        closeConfirmation();
    };

    const closeConfirmation = () => {
        DOM.confirmModalOverlay.classList.add('opacity-0');
        DOM.confirmModalContent.classList.add('scale-95', 'opacity-0');
        setTimeout(() => DOM.confirmModalOverlay.classList.add('hidden'), 300);
        DOM.confirmModalConfirm.removeEventListener('click', confirmHandler);
        DOM.confirmModalCancel.removeEventListener('click', cancelHandler);
    };

    DOM.confirmModalConfirm.addEventListener('click', confirmHandler, { once: true });
    DOM.confirmModalCancel.addEventListener('click', cancelHandler, { once: true });
}

export function updatePromptEditorState() {
    const hasChanged = DOM.promptEditorTextarea.value.trim() !== DOM.promptEditorTextarea.dataset.initialValue.trim();
    DOM.promptEditorSave.disabled = !hasChanged;

    let statusText = isPromptCustomForModel(state.currentProvider, state.currentModel) ? 'Custom' : 'Default';
    let statusClass = 'text-sm text-gray-400';

    if (hasChanged) {
        statusText = 'Unsaved Changes';
        statusClass = 'text-sm text-yellow-400';
    }

    DOM.promptEditorStatus.textContent = statusText;
    DOM.promptEditorStatus.className = statusClass;
}

export function addMessageToModal(role, content) {
    const messageEl = document.createElement('div');
    messageEl.className = `p-3 rounded-lg max-w-xs ${role === 'user' ? 'bg-blue-600 self-end' : 'bg-gray-600 self-start'}`;
    messageEl.textContent = content;
    DOM.chatModalLog.appendChild(messageEl);
    DOM.chatModalLog.scrollTop = DOM.chatModalLog.scrollHeight;
}

export function updateHintAndIndicatorState() {
    const hintTextSpan = DOM.inputHint.querySelector('span:first-child');
    const hintTooltipSpan = DOM.inputHint.querySelector('.tooltip');

    if (state.isLastTurnModeLocked) {
        hintTextSpan.innerHTML = `<strong>Turn Summaries Context:</strong> <span class="text-orange-400 font-semibold">Locked</span>`;
        hintTooltipSpan.innerHTML = `'Turn Summaries' context is locked on. Press <kbd>Shift</kbd> + <kbd>Alt</kbd> to switch back to the default 'Full Session Context'.`;
        DOM.contextStatusDot.className = 'connection-dot context-last-turn-locked';
        DOM.sendIcon.classList.remove('flipped');
    } else if (state.isTempLastTurnMode) {
        hintTextSpan.innerHTML = `<strong>Context:</strong> <span class="text-yellow-400 font-semibold">Turn Summaries</span>`;
        hintTooltipSpan.innerHTML = `Temporarily using 'Turn Summaries' context for this query.`;
        DOM.contextStatusDot.className = 'connection-dot context-last-turn-temp';
        DOM.sendIcon.classList.remove('flipped');
    } else {
        hintTextSpan.innerHTML = `<strong>Full Session Context:</strong> <span class="text-green-400 font-semibold">On</span>`;
        hintTooltipSpan.innerHTML = `Full session context is the default. Hold <kbd>Alt</kbd> to temporarily use 'Turn Summaries' context. Press <kbd>Shift</kbd> + <kbd>Alt</kbd> to lock 'Turn Summaries' context on.`;
        DOM.contextStatusDot.className = 'connection-dot idle';
        DOM.sendIcon.classList.add('flipped');
    }
}

export function updateVoiceModeUI() {
    const isActive = state.isVoiceModeLocked || state.isTempVoiceMode || state.ttsState === 'AWAITING_OBSERVATION_CONFIRMATION';

    if (isActive) {
        DOM.voiceInputButton.classList.remove('bg-gray-600');
        DOM.voiceInputButton.classList.add('bg-[#F15F22]');
    } else {
        DOM.voiceInputButton.classList.add('bg-gray-600');
        DOM.voiceInputButton.classList.remove('bg-[#F115F22]'); // Typo fixed from original
    }

    let tooltipText = "Voice Conversation";
    if (state.ttsState === 'AWAITING_OBSERVATION_CONFIRMATION') {
        tooltipText += " (Listening for confirmation)";
    } else if (state.isVoiceModeLocked) {
        tooltipText += " (Locked On)";
    } else if (state.isTempVoiceMode) {
        tooltipText += " (Active)";
    } else {
        tooltipText += " (Hold Ctrl)";
    }
    DOM.voiceInputButton.title = tooltipText;

    if (isActive) {
    } else {
    }
}

export function updateKeyObservationsModeUI() {
    DOM.observationsAutoplayOffIcon.classList.add('hidden');
    DOM.observationsAutoplayOnIcon.classList.add('hidden');
    DOM.observationsOffIcon.classList.add('hidden');
    DOM.keyObservationsToggleButton.classList.remove('autoplay-on', 'off');

    switch (state.keyObservationsMode) {
        case 'autoplay-on':
            DOM.observationsAutoplayOnIcon.classList.remove('hidden');
            DOM.keyObservationsToggleButton.title = 'Key Observations - Autoplay On';
            DOM.keyObservationsToggleButton.classList.add('autoplay-on');
            break;
        case 'off':
            DOM.observationsOffIcon.classList.remove('hidden');
            DOM.keyObservationsToggleButton.title = 'Key Observations - Off';
            DOM.keyObservationsToggleButton.classList.add('off');
            break;
        case 'autoplay-off':
        default:
            DOM.observationsAutoplayOffIcon.classList.remove('hidden');
            DOM.keyObservationsToggleButton.title = 'Key Observations - Autoplay Off';
            break;
    }
}

// export function closeConfigModal() {
//     DOM.configModalOverlay.classList.add('opacity-0');
//     DOM.configModalContent.classList.add('scale-95', 'opacity-0');
//     setTimeout(() => DOM.configModalOverlay.classList.add('hidden'), 300);
// }

export function closePromptModal() {
    DOM.promptModalOverlay.classList.add('opacity-0');
    DOM.promptModalContent.classList.add('scale-95', 'opacity-0');
    setTimeout(() => DOM.promptModalOverlay.classList.add('hidden'), 300);
}

export function closeViewPromptModal() {
    DOM.viewPromptModalOverlay.classList.add('opacity-0');
    DOM.viewPromptModalContent.classList.add('scale-95', 'opacity-0');
    setTimeout(() => DOM.viewPromptModalOverlay.classList.add('hidden'), 300);
}

/**
 * Displays the RAG Case modal with the provided case data.
 * @param {object} caseData - The full RAG case data to display.
 */
export function showRagCaseModal(caseData) {
    if (!DOM.ragCaseModalOverlay || !DOM.ragCaseModalContent || !DOM.ragCaseIdDisplay || !DOM.ragCaseModalJson) {
        console.error("RAG Case modal DOM elements not found.");
        return;
    }

    DOM.ragCaseIdDisplay.textContent = caseData.case_id || 'N/A';
    DOM.ragCaseModalJson.textContent = JSON.stringify(caseData.full_case_data, null, 2);

    DOM.ragCaseModalOverlay.classList.remove('hidden');
    // Trigger reflow to ensure transition plays
    void DOM.ragCaseModalOverlay.offsetWidth;
    DOM.ragCaseModalOverlay.classList.remove('opacity-0');
    DOM.ragCaseModalContent.classList.remove('scale-95', 'opacity-0');
}

/**
 * Hides the RAG Case modal.
 */
export function closeRagCaseModal() {
    if (!DOM.ragCaseModalOverlay || !DOM.ragCaseModalContent) {
        console.error("RAG Case modal DOM elements not found.");
        return;
    }

    DOM.ragCaseModalOverlay.classList.add('opacity-0');
    DOM.ragCaseModalContent.classList.add('scale-95', 'opacity-0');
    setTimeout(() => DOM.ragCaseModalOverlay.classList.add('hidden'), 300);
}

/**
 * Provides brief visual feedback on the context status dot by making it blink.
 */
export function blinkContextDot() {
    if (!DOM.contextStatusDot) return;

    DOM.contextStatusDot.classList.add('blinking-white');

    setTimeout(() => {
        DOM.contextStatusDot.classList.remove('blinking-white');
    }, 1500); // 0.5s animation * 3 iterations
}

/**
 * Provides brief visual feedback on the RAG status dot by making it blink yellow.
 */
export function blinkRagDot() {
    if (!DOM.ragStatusDot) return;

    // Ensure it's in the 'connected' state before blinking
    if (!DOM.ragStatusDot.classList.contains('connected')) {
        DOM.ragStatusDot.classList.add('connected');
    }

    DOM.ragStatusDot.classList.add('blinking-yellow');

    // The animation runs for 1.5s (0.5s * 3 iterations)
    setTimeout(() => {
        DOM.ragStatusDot.classList.remove('blinking-yellow');
    }, 1500);
}

/**
 * Provides brief visual feedback on the Knowledge status dot by making it blink purple.
 */
export function blinkKnowledgeDot() {
    const knowledgeDot = document.getElementById('knowledge-status-dot');
    if (!knowledgeDot) return;

    // Switch to 'knowledge-active' (purple) state during active use
    if (!knowledgeDot.classList.contains('knowledge-active')) {
        knowledgeDot.classList.remove('knowledge-idle', 'knowledge-configured');
        knowledgeDot.classList.add('knowledge-active');
    }

    knowledgeDot.classList.add('blinking-purple');

    // The animation runs for 1.5s (0.5s * 3 iterations)
    setTimeout(() => {
        knowledgeDot.classList.remove('blinking-purple');
        // After blinking, return to configured state if appropriate
        // (The profile update will handle setting it back to configured/idle)
    }, 1500);
}

/**
 * Updates knowledge indicator and banner when knowledge repositories are accessed.
 * @param {Array<string>} collections - List of collection names accessed
 * @param {number} documentCount - Number of documents retrieved
 */
export function updateKnowledgeIndicator(collections, documentCount) {
    const knowledgeDot = document.getElementById('knowledge-status-dot');
    const knowledgeBanner = document.getElementById('knowledge-banner');
    const collectionsList = document.getElementById('knowledge-collections-list');

    if (!knowledgeDot || !knowledgeBanner || !collectionsList) {
        console.warn('[Knowledge] UI elements not found');
        return;
    }

    console.log('[Knowledge] Updating indicator with:', { collections, documentCount });

    // Show banner with collection names
    if (collections && collections.length > 0) {
        collectionsList.textContent = collections.join(', ') + ` (${documentCount} docs)`;
        knowledgeBanner.classList.remove('hidden');
    }

    // Reset indicator to configured state (green) after successful retrieval
    knowledgeDot.classList.remove('knowledge-idle', 'knowledge-active');
    knowledgeDot.classList.add('knowledge-configured');

    // Hide banner after 8 seconds
    setTimeout(() => {
        knowledgeBanner.classList.add('hidden');
    }, 8000);
}

export function closeChatModal() {
    DOM.chatModalOverlay.classList.add('opacity-0');
    DOM.chatModalContent.classList.add('scale-95', 'opacity-0');
    setTimeout(() => DOM.chatModalOverlay.classList.add('hidden'), 300);
}

/**
 * Removes the visual highlight from a session item.
 * @param {string} sessionId The ID of the session to un-highlight.
 */
export function removeHighlight(sessionId) {
    const sessionItem = document.getElementById(`session-${sessionId}`);
    if (sessionItem) {
        const nameSpan = sessionItem.querySelector('.session-name-span');
        if (nameSpan) {
            nameSpan.classList.remove('font-bold', 'text-teradata-orange');
        }
        const indicator = sessionItem.querySelector('.new-activity-indicator');
        if (indicator) {
            indicator.remove();
        }
    }
}

/**
 * Toggles the collapsed state of the main side navigation bar.
 */
export function toggleSideNav() {
    // Simply toggle the 'collapsed' class - CSS handles everything
    DOM.appSideNav.classList.toggle('collapsed');
}

/**
 * Handles switching the main application view.
 * @param {string} viewId - The ID of the view to switch to (e.g., 'conversation-view').
 */
export function handleViewSwitch(viewId) {
    console.log('[handleViewSwitch] Switching to view:', viewId);
    
    // CRITICAL: Check if user is navigating away from configuration with unsaved changes
    const currentView = document.querySelector('.app-view.active');
    const isLeavingConfiguration = currentView?.id === 'credentials-view' && viewId !== 'credentials-view';
    
    if (isLeavingConfiguration) {
        // Import dirty state tracker dynamically to avoid circular dependencies
        import('./configDirtyState.js').then(({ canNavigateAway }) => {
            if (!canNavigateAway(viewId)) {
                console.log('[handleViewSwitch] ❌ Navigation blocked - unsaved configuration changes');
                return; // Block navigation
            }
            
            // Navigation allowed, proceed
            performViewSwitch(viewId);
        });
        return; // Exit early, will be called again if navigation is allowed
    }
    
    // Not leaving configuration or no unsaved changes - proceed normally
    performViewSwitch(viewId);
}

/**
 * Internal function to perform the actual view switch
 * Separated to allow dirty state checking to interrupt the flow
 */
function performViewSwitch(viewId) {
    // 1. Log all app views found
    const appViews = document.querySelectorAll('.app-view');

    // 2. Hide all views
    appViews.forEach(view => {
        view.classList.remove('active');
    });

    // 3. Show the selected view
    const viewToShow = document.getElementById(viewId);
    if (viewToShow) {
        viewToShow.classList.add('active');
    } else {
        console.error(`[UI DEBUG] View with ID '${viewId}' not found!`);
    }
    
    // 4. Initialize dirty tracking when entering configuration view
    if (viewId === 'credentials-view') {
        import('./configDirtyState.js').then(({ initializeConfigDirtyTracking }) => {
            initializeConfigDirtyTracking();
        });
    }
    
    // 5. Reset dirty tracking when leaving configuration view (after successful save)
    const previousView = document.querySelector('.app-view.active');
    if (previousView?.id === 'credentials-view' && viewId !== 'credentials-view') {
        import('./configDirtyState.js').then(({ resetConfigDirtyTracking }) => {
            resetConfigDirtyTracking();
        });
    }

    // 4. Update the active state of the menu buttons
    if (DOM.viewSwitchButtons) {
        DOM.viewSwitchButtons.forEach(button => {
            const isActive = button.dataset.view === viewId;
            button.classList.toggle('active', isActive);
        });
    } else {
    }
    
    // 4b. Ensure Planner Repository navigation state is maintained
    if (typeof window.updatePlannerRepositoryNavigation === 'function') {
        console.log('[handleViewSwitch] Calling updatePlannerRepositoryNavigation after view switch to:', viewId);
        window.updatePlannerRepositoryNavigation();
    } else {
        console.warn('[handleViewSwitch] updatePlannerRepositoryNavigation function not available');
    }

    // 5. Final check
    setTimeout(() => {
        const activeViews = document.querySelectorAll('.app-view.active');
        if (activeViews.length > 1) {
        } else if (activeViews.length === 0) {
        } else if (activeViews[0].id !== viewId) {
            console.error(`[UI DEBUG] WRONG VIEW IS ACTIVE! Expected ${viewId}, but found ${activeViews[0].id}`);
        }
    }, 100); // Use a small delay to catch any subsequent changes

    // 6. If switching to Intelligence, load collections and calculate KPIs
    if (viewId === 'rag-maintenance-view') {
        loadRagCollections();
        // Calculate and display RAG impact KPIs
        if (window.ragCollectionManagement && window.ragCollectionManagement.calculateRagImpactKPIs) {
            window.ragCollectionManagement.calculateRagImpactKPIs();
            
            // Start auto-refresh for Intelligence KPIs
            if (window.ragCollectionManagement.startAutoRefresh) {
                window.ragCollectionManagement.startAutoRefresh();
            }
        }
    } else {
        // Stop Intelligence auto-refresh when leaving the view
        if (window.ragCollectionManagement && window.ragCollectionManagement.stopAutoRefresh) {
            window.ragCollectionManagement.stopAutoRefresh();
        }
    }
    
    // 6b. If switching to Marketplace, refresh marketplace collections
    if (viewId === 'rag-marketplace-view') {
        if (window.refreshMarketplace) {
            window.refreshMarketplace();
        }
    }
    
    // 7. If switching to Executions view, initialize dashboard
    if (viewId === 'executions-view') {
        if (window.executionDashboard) {
            // Initialize once, then always refresh when entering the view
            if (!window.executionDashboard._isInitialized) {
                window.executionDashboard.initialize();
                window.executionDashboard._isInitialized = true;
            } else {
                // Refresh data and restart auto-refresh when re-entering the view
                window.executionDashboard.refreshDashboard();
                window.executionDashboard.startAutoRefresh();
            }
        } else {
            console.error('[UI DEBUG] ExecutionDashboard not initialized');
        }
    } else {
        // Stop Executions auto-refresh when leaving the view
        if (window.executionDashboard && window.executionDashboard.stopAutoRefresh) {
            window.executionDashboard.stopAutoRefresh();
        }
    }
    
    // 8. If switching to Admin view, load users and features
    if (viewId === 'admin-view') {
        if (window.AdminManager) {
            window.AdminManager.loadUsers();
            window.AdminManager.loadFeatures();
        } else {
            console.error('[UI DEBUG] AdminManager not initialized');
        }
    }
    
    // 9. If switching to Conversation view, initialize panels based on admin settings
    if (viewId === 'conversation-view') {
        console.log('[handleViewSwitch] Conversation view detected, checking for initializePanels:', typeof window.initializePanels);
        if (window.initializePanels) {
            console.log('[handleViewSwitch] Calling initializePanels()');
            window.initializePanels();
        } else {
            console.error('[UI DEBUG] initializePanels not available yet - will retry');
            // Retry after a short delay to allow main.js to finish loading
            setTimeout(() => {
                if (window.initializePanels) {
                    console.log('[handleViewSwitch] Calling initializePanels() after delay');
                    window.initializePanels();
                } else {
                    console.error('[UI DEBUG] initializePanels still not available after delay');
                }
            }, 500);
        }
        
        // Check if application is initialized before loading sessions
        // SKIP this check if we're already in the middle of initialization (reconnectAndLoad handles it)
        if (state.sessionLoaded) {
            console.log('[handleViewSwitch] Session already loaded, skipping initialization check');
            return;
        }
        
        checkServerStatus().then(async (status) => {
            if (!status.isConfigured) {
                // Application not configured - show welcome screen
                console.log('[handleViewSwitch] Application not configured, showing welcome screen');
                if (window.showWelcomeScreen) {
                    window.showWelcomeScreen();
                }
                return;
            }
            
            // Application is configured - but check if conversation mode has been initialized
            // Import conversationInitializer to check initialization state
            const { getInitializationState } = await import('./conversationInitializer.js');
            const initState = getInitializationState();
            
            if (!initState.initialized) {
                // Not yet initialized - show welcome screen with "Start Conversation" button
                console.log('[handleViewSwitch] Application configured but conversation not initialized, showing welcome screen');
                if (window.showWelcomeScreen) {
                    window.showWelcomeScreen();
                }
                return;
            }
            
            // Application is configured AND initialized - proceed with session loading if needed
            console.log('[handleViewSwitch] Application configured and initialized, no session loaded, checking for session to load');
            
            // Dynamically import sessionManagement to load session
            const { handleLoadSession } = await import('./handlers/sessionManagement.js?v=3.2');
            try {
                // If we have a session ID in state (restored from localStorage), load it
                if (state.currentSessionId) {
                    console.log('[handleViewSwitch] Session ID exists in state, loading session:', state.currentSessionId);
                    await handleLoadSession(state.currentSessionId);
                } else {
                    // No session ID in state - fetch sessions and load most recent
                    console.log('[handleViewSwitch] No session ID in state, fetching sessions');
                    const sessions = await loadAllSessions();
                    const activeSessions = sessions ? sessions.filter(s => !s.archived) : [];
                    
                    if (activeSessions && activeSessions.length > 0) {
                        // Sessions exist - load the most recent one (first in array)
                        console.log('[handleViewSwitch] Found', activeSessions.length, 'existing sessions, loading most recent');
                        await handleLoadSession(activeSessions[0].id);
                    } else {
                        // No sessions exist - show welcome screen
                        console.log('[handleViewSwitch] No existing sessions, showing welcome screen');
                        if (window.showWelcomeScreen) {
                            window.showWelcomeScreen();
                        }
                    }
                }
            } catch (error) {
                console.error('[handleViewSwitch] Error loading sessions:', error);
                // Fallback to welcome screen on error
                if (window.showWelcomeScreen) {
                    window.showWelcomeScreen();
                }
            }
        }).catch(error => {
            console.error('[handleViewSwitch] Error checking server status:', error);
            // On error, show welcome screen as fallback
            if (window.showWelcomeScreen) {
                window.showWelcomeScreen();
            }
        });
    }
}

/**
 * Fetches ChromaDB collections from the backend and renders them as cards.
 */
export async function loadRagCollections() {
    if (!DOM.ragMaintenanceCollectionsContainer) return;
    try {
        if (DOM.ragMaintenanceEmptyHint) {
            DOM.ragMaintenanceEmptyHint.textContent = 'Loading collections...';
        }
        // Get authentication token
        const token = localStorage.getItem('tda_auth_token');
        const res = await fetch('/api/v1/rag/collections', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await res.json();
        let collections = (data && data.collections) ? data.collections : [];
        
        // Separate collections by repository type
        const plannerCollections = collections.filter(c => c.repository_type === 'planner');
        const knowledgeCollections = collections.filter(c => c.repository_type === 'knowledge');
        
        // Sort collections: Default Collection first, then by ID
        const sortCollections = (arr) => {
            return arr.sort((a, b) => {
                const aIsDefault = a.name.includes('Default Collection');
                const bIsDefault = b.name.includes('Default Collection');
                if (aIsDefault && !bIsDefault) return -1;
                if (!aIsDefault && bIsDefault) return 1;
                return a.id - b.id;
            });
        };
        
        sortCollections(plannerCollections);
        sortCollections(knowledgeCollections);
        
        // Render Planner repositories
        DOM.ragMaintenanceCollectionsContainer.innerHTML = '';
        if (!plannerCollections.length) {
            const emptyMsg = document.createElement('div');
            emptyMsg.className = 'col-span-full text-gray-400 text-sm';
            emptyMsg.textContent = 'No planner repositories found.';
            DOM.ragMaintenanceCollectionsContainer.appendChild(emptyMsg);
        } else {
            plannerCollections.forEach(col => {
                const card = createCollectionCard(col);
                DOM.ragMaintenanceCollectionsContainer.appendChild(card);
            });
        }
        
        // Render Knowledge repositories
        if (DOM.knowledgeRepositoriesContainer) {
            DOM.knowledgeRepositoriesContainer.innerHTML = '';
            if (!knowledgeCollections.length) {
                const emptyMsg = document.createElement('div');
                emptyMsg.className = 'col-span-full text-gray-400 text-sm';
                emptyMsg.textContent = 'No knowledge repositories found.';
                DOM.knowledgeRepositoriesContainer.appendChild(emptyMsg);
            } else {
                knowledgeCollections.forEach(col => {
                    const card = createKnowledgeRepositoryCard(col);
                    DOM.knowledgeRepositoriesContainer.appendChild(card);
                });
            }
        }
    } catch (err) {
        console.error('Failed to load RAG collections:', err);
        DOM.ragMaintenanceCollectionsContainer.innerHTML = '';
        const errMsg = document.createElement('div');
        errMsg.className = 'col-span-full text-red-400 text-sm';
        errMsg.textContent = `Error loading collections: ${err.message}`;
        DOM.ragMaintenanceCollectionsContainer.appendChild(errMsg);
    }
}

// Make loadRagCollections globally available for marketplace handler
window.loadRagCollections = loadRagCollections;

function createKnowledgeRepositoryCard(col) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-xl p-4 flex flex-col gap-3 border border-white/10 hover:border-teradata-orange transition-colors';
    
    // Header with title and status badge
    const header = document.createElement('div');
    header.className = 'flex items-start justify-between gap-2';
    
    const titleSection = document.createElement('div');
    titleSection.className = 'flex-1';
    
    const title = document.createElement('h2');
    title.className = 'text-lg font-semibold text-white';
    title.textContent = col.name || col.collection_name;
    
    const collectionId = document.createElement('p');
    collectionId.className = 'text-xs text-gray-500';
    collectionId.textContent = `Collection ID: ${col.id}`;
    
    titleSection.appendChild(title);
    titleSection.appendChild(collectionId);
    
    // Status and indicator badges container
    const badgesContainer = document.createElement('div');
    badgesContainer.className = 'flex flex-col gap-1 items-end';
    
    // Active/Disabled badge
    const statusBadge = document.createElement('span');
    statusBadge.className = col.enabled 
        ? 'px-2 py-1 text-xs rounded-full bg-green-500/20 text-green-400' 
        : 'px-2 py-1 text-xs rounded-full bg-gray-500/20 text-gray-400';
    statusBadge.textContent = col.enabled ? 'Active' : 'Disabled';
    badgesContainer.appendChild(statusBadge);
    
    // Ownership/Subscription indicators
    const indicatorsRow = document.createElement('div');
    indicatorsRow.className = 'flex gap-1';
    
    // Owner indicator (if user owns this collection)
    if (col.is_owned) {
        const ownerBadge = document.createElement('span');
        ownerBadge.className = 'px-2 py-1 text-xs rounded-full bg-blue-500/20 text-blue-400';
        ownerBadge.textContent = '👤 Owner';
        ownerBadge.title = 'You own this collection';
        indicatorsRow.appendChild(ownerBadge);
    }
    
    // Subscribed indicator (if user is subscribed but doesn't own it)
    if (col.is_subscribed && !col.is_owned) {
        const subscribedBadge = document.createElement('span');
        subscribedBadge.className = 'px-2 py-1 text-xs rounded-full bg-purple-500/20 text-purple-400';
        subscribedBadge.textContent = '📌 Subscribed';
        subscribedBadge.title = 'You are subscribed to this collection';
        indicatorsRow.appendChild(subscribedBadge);
    }
    
    // Published to marketplace indicator
    if (col.is_marketplace_listed) {
        const publishedBadge = document.createElement('span');
        publishedBadge.className = 'px-2 py-1 text-xs rounded-full bg-orange-500/20 text-orange-400';
        const visibilityIcon = col.visibility === 'public' ? '🌐' : '🔗';
        publishedBadge.textContent = `${visibilityIcon} ${col.visibility === 'public' ? 'Public' : 'Unlisted'}`;
        publishedBadge.title = `Published to marketplace (${col.visibility})`;
        indicatorsRow.appendChild(publishedBadge);
    }
    
    if (indicatorsRow.children.length > 0) {
        badgesContainer.appendChild(indicatorsRow);
    }
    
    header.appendChild(titleSection);
    header.appendChild(badgesContainer);
    
    // MCP Server info
    const mcpInfo = document.createElement('p');
    mcpInfo.className = 'text-sm text-gray-300';
    let mcpServerDisplay = 'None';
    if (col.mcp_server_id && window.configState && window.configState.mcpServers) {
        const mcpServer = window.configState.mcpServers.find(s => s.id === col.mcp_server_id);
        mcpServerDisplay = mcpServer ? mcpServer.name : 'Unknown';
    }
    mcpInfo.innerHTML = `<span class="text-gray-500">MCP Server:</span> ${mcpServerDisplay}`;
    
    // Description (if exists)
    const desc = col.description ? (() => {
        const d = document.createElement('p');
        d.className = 'text-xs text-gray-400';
        d.textContent = col.description;
        return d;
    })() : null;
    
    // Metadata (ChromaDB name and chunking info)
    const meta = document.createElement('p');
    meta.className = 'text-xs text-gray-500';
    const chunkInfo = col.chunking_strategy ? ` | ${col.chunking_strategy} chunking` : '';
    meta.textContent = `ChromaDB: ${col.collection_name}${chunkInfo}`;

    // Embedding model info
    const embeddingInfo = document.createElement('p');
    embeddingInfo.className = 'text-xs text-gray-400';
    const embeddingModel = col.embedding_model || 'all-MiniLM-L6-v2';
    embeddingInfo.innerHTML = `<span class="text-gray-500">Embedding Model:</span> ${embeddingModel}`;

    // Document and chunk counts for Knowledge repositories
    const countsInfo = document.createElement('p');
    countsInfo.className = 'text-xs text-gray-400';
    const docCount = col.document_count || '?';
    const chunkCount = col.count || col.example_count || 0;
    countsInfo.textContent = `${docCount} documents • ${chunkCount} chunks`;

    card.appendChild(header);
    if (desc) card.appendChild(desc);
    card.appendChild(mcpInfo);
    card.appendChild(meta);
    card.appendChild(embeddingInfo);
    card.appendChild(countsInfo);
    
    // Actions
    const actions = document.createElement('div');
    actions.className = 'mt-2 flex gap-2 flex-wrap';
    
    // Toggle enable/disable button
    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = col.enabled
        ? 'px-3 py-1 rounded-md bg-yellow-600 hover:bg-yellow-500 text-sm text-white'
        : 'px-3 py-1 rounded-md bg-green-600 hover:bg-green-500 text-sm text-white';
    toggleBtn.textContent = col.enabled ? 'Disable' : 'Enable';
    toggleBtn.addEventListener('click', () => {
        if (window.ragCollectionManagement) {
            window.ragCollectionManagement.toggleRagCollection(col.id, col.enabled);
        }
    });
    
    // Inspect button
    const inspectBtn = document.createElement('button');
    inspectBtn.type = 'button';
    inspectBtn.className = 'px-3 py-1 rounded-md bg-[#F15F22] hover:bg-[#D9501A] text-sm text-white';
    inspectBtn.textContent = 'Inspect';
    inspectBtn.addEventListener('click', () => {
        // Use the shared collection inspection view
        openCollectionInspection(col.id, col.name, 'knowledge', col);
    });
    
    // Edit button
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-sm text-white';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => {
        if (window.ragCollectionManagement) {
            window.ragCollectionManagement.openEditCollectionModal(col);
        }
    });
    
    // Upload button (Knowledge repositories only)
    const uploadBtn = document.createElement('button');
    uploadBtn.type = 'button';
    uploadBtn.className = 'px-3 py-1 rounded-md bg-purple-600 hover:bg-purple-500 text-sm text-white';
    uploadBtn.innerHTML = '<span style="font-size: 14px;">+</span> Upload';
    uploadBtn.addEventListener('click', () => {
        if (window.knowledgeRepositoryHandler && window.knowledgeRepositoryHandler.openUploadDocumentsModal) {
            window.knowledgeRepositoryHandler.openUploadDocumentsModal(col.id, col.name, col);
        }
    });

    // Export button (Knowledge repositories only)
    const exportBtn = document.createElement('button');
    exportBtn.type = 'button';
    exportBtn.className = 'px-3 py-1 rounded-md bg-cyan-600 hover:bg-cyan-500 text-sm text-white flex items-center gap-1';
    exportBtn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
    </svg>Export`;
    exportBtn.addEventListener('click', () => {
        if (exportKnowledgeRepository) {
            exportKnowledgeRepository(col.id, col.name || col.collection_name);
        }
    });

    // Delete/Unsubscribe button for Knowledge repositories
    if (col.is_subscribed && !col.is_owned) {
        // Subscribed collection - show Unsubscribe button
        const unsubscribeBtn = document.createElement('button');
        unsubscribeBtn.type = 'button';
        unsubscribeBtn.className = 'px-3 py-1 rounded-md bg-purple-600 hover:bg-purple-500 text-sm text-white';
        unsubscribeBtn.textContent = 'Unsubscribe';
        unsubscribeBtn.addEventListener('click', async () => {
            if (window.marketplaceHandler && window.marketplaceHandler.unsubscribeFromCollection) {
                await window.marketplaceHandler.unsubscribeFromCollection(col.subscription_id, col.name);
            } else {
                console.error('Marketplace handler not available for unsubscribe');
            }
        });
        actions.appendChild(unsubscribeBtn);
    } else {
        // Owned collection - show Delete button
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'px-3 py-1 rounded-md bg-red-600 hover:bg-red-500 text-sm text-white';
        deleteBtn.textContent = 'Delete';
        deleteBtn.addEventListener('click', () => {
            if (window.knowledgeRepositoryHandler) {
                window.knowledgeRepositoryHandler.deleteKnowledgeRepository(col.id, col.name);
            }
        });
        actions.appendChild(deleteBtn);
    }
    
    actions.appendChild(toggleBtn);
    actions.appendChild(inspectBtn);
    actions.appendChild(editBtn);
    actions.appendChild(uploadBtn);
    actions.appendChild(exportBtn);
    // Delete/Unsubscribe button already appended above
    
    card.appendChild(actions);
    
    // Load document count asynchronously
    loadKnowledgeRepositoryDocCount(col.id);
    
    return card;
}

function createCollectionCard(col) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-xl p-4 flex flex-col gap-3 border border-white/10 hover:border-teradata-orange transition-colors';
            
            // Header with title and status badge
            const header = document.createElement('div');
            header.className = 'flex items-start justify-between gap-2';
            
            const titleSection = document.createElement('div');
            titleSection.className = 'flex-1';
            
            const title = document.createElement('h2');
            title.className = 'text-lg font-semibold text-white';
            title.textContent = col.name;
            
            const collectionId = document.createElement('p');
            collectionId.className = 'text-xs text-gray-500';
            collectionId.textContent = `Collection ID: ${col.id}`;
            
            titleSection.appendChild(title);
            titleSection.appendChild(collectionId);
            
            // Status and indicator badges container
            const badgesContainer = document.createElement('div');
            badgesContainer.className = 'flex flex-col gap-1 items-end';
            
            // Active/Disabled badge
            const statusBadge = document.createElement('span');
            statusBadge.className = col.enabled 
                ? 'px-2 py-1 text-xs rounded-full bg-green-500/20 text-green-400' 
                : 'px-2 py-1 text-xs rounded-full bg-gray-500/20 text-gray-400';
            statusBadge.textContent = col.enabled ? 'Active' : 'Disabled';
            badgesContainer.appendChild(statusBadge);
            
            // Ownership/Subscription indicators
            const indicatorsRow = document.createElement('div');
            indicatorsRow.className = 'flex gap-1';
            
            // Owner indicator (if user owns this collection)
            if (col.is_owned) {
                const ownerBadge = document.createElement('span');
                ownerBadge.className = 'px-2 py-1 text-xs rounded-full bg-blue-500/20 text-blue-400';
                ownerBadge.textContent = '👤 Owner';
                ownerBadge.title = 'You own this collection';
                indicatorsRow.appendChild(ownerBadge);
            }
            
            // Subscribed indicator (if user is subscribed but doesn't own it)
            if (col.is_subscribed && !col.is_owned) {
                const subscribedBadge = document.createElement('span');
                subscribedBadge.className = 'px-2 py-1 text-xs rounded-full bg-purple-500/20 text-purple-400';
                subscribedBadge.textContent = '📌 Subscribed';
                subscribedBadge.title = 'You are subscribed to this collection';
                indicatorsRow.appendChild(subscribedBadge);
            }
            
            // Published to marketplace indicator
            if (col.is_marketplace_listed) {
                const publishedBadge = document.createElement('span');
                publishedBadge.className = 'px-2 py-1 text-xs rounded-full bg-orange-500/20 text-orange-400';
                const visibilityIcon = col.visibility === 'public' ? '🌐' : '🔗';
                publishedBadge.textContent = `${visibilityIcon} ${col.visibility === 'public' ? 'Public' : 'Unlisted'}`;
                publishedBadge.title = `Published to marketplace (${col.visibility})`;
                indicatorsRow.appendChild(publishedBadge);
            }
            
            if (indicatorsRow.children.length > 0) {
                badgesContainer.appendChild(indicatorsRow);
            }
            
            header.appendChild(titleSection);
            header.appendChild(badgesContainer);
            
            // MCP Server info - look up name from ID using window.configState
            const mcpInfo = document.createElement('p');
            mcpInfo.className = 'text-sm text-gray-300';
            let mcpServerDisplay = 'None';
            if (col.mcp_server_id && window.configState && window.configState.mcpServers) {
                const mcpServer = window.configState.mcpServers.find(s => s.id === col.mcp_server_id);
                mcpServerDisplay = mcpServer ? mcpServer.name : 'Unknown';
            }
            mcpInfo.innerHTML = `<span class="text-gray-500">MCP Server:</span> ${mcpServerDisplay}`;
            
            // Description (if exists)
            const desc = col.description ? (() => {
                const d = document.createElement('p');
                d.className = 'text-xs text-gray-400';
                d.textContent = col.description;
                return d;
            })() : null;
            
            // Metadata (collection_name from ChromaDB)
            const meta = document.createElement('p');
            meta.className = 'text-xs text-gray-500';
            meta.textContent = `ChromaDB: ${col.collection_name}`;

            // Embedding model info
            const embeddingInfo = document.createElement('p');
            embeddingInfo.className = 'text-xs text-gray-400';
            const embeddingModel = col.embedding_model || 'all-MiniLM-L6-v2';
            embeddingInfo.innerHTML = `<span class="text-gray-500">Embedding Model:</span> ${embeddingModel}`;

            // Actions
            const actions = document.createElement('div');
            actions.className = 'mt-2 flex gap-2 flex-wrap';
            
            // Toggle enable/disable button
            const toggleBtn = document.createElement('button');
            toggleBtn.type = 'button';
            toggleBtn.className = col.enabled
                ? 'px-3 py-1 rounded-md bg-yellow-600 hover:bg-yellow-500 text-sm text-white'
                : 'px-3 py-1 rounded-md bg-green-600 hover:bg-green-500 text-sm text-white';
            toggleBtn.textContent = col.enabled ? 'Disable' : 'Enable';
            toggleBtn.addEventListener('click', () => {
                if (window.ragCollectionManagement) {
                    window.ragCollectionManagement.toggleRagCollection(col.id, col.enabled);
                }
            });
            
            // Inspect button
            const inspectBtn = document.createElement('button');
            inspectBtn.type = 'button';
            inspectBtn.className = 'px-3 py-1 rounded-md bg-[#F15F22] hover:bg-[#D9501A] text-sm text-white';
            inspectBtn.textContent = 'Inspect';
            inspectBtn.addEventListener('click', () => {
                openCollectionInspection(col.id, col.name, col.repository_type);
            });
            
            // Edit button
            const editBtn = document.createElement('button');
            editBtn.type = 'button';
            editBtn.className = 'px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-sm text-white';
            editBtn.textContent = 'Edit';
            editBtn.addEventListener('click', () => {
                if (window.ragCollectionManagement) {
                    window.ragCollectionManagement.openEditCollectionModal(col);
                }
            });
            
            // Export button (only for owned collections)
            if (col.is_owned) {
                const exportBtn = document.createElement('button');
                exportBtn.type = 'button';
                exportBtn.className = 'px-3 py-1 rounded-md bg-cyan-600 hover:bg-cyan-500 text-sm text-white flex items-center gap-1';
                exportBtn.innerHTML = `
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                    </svg>
                    Export
                `;
                exportBtn.addEventListener('click', async () => {
                    try {
                        await exportKnowledgeRepository(col.id, col.name);
                    } catch (error) {
                        console.error('Export failed:', error);
                    }
                });
                actions.appendChild(exportBtn);
            }

            // Delete/Unsubscribe button
            if (col.is_subscribed && !col.is_owned) {
                // Subscribed collection - show Unsubscribe button
                const unsubscribeBtn = document.createElement('button');
                unsubscribeBtn.type = 'button';
                unsubscribeBtn.className = 'px-3 py-1 rounded-md bg-purple-600 hover:bg-purple-500 text-sm text-white';
                unsubscribeBtn.textContent = 'Unsubscribe';
                unsubscribeBtn.addEventListener('click', async () => {
                    if (window.marketplaceHandler && window.marketplaceHandler.unsubscribeFromCollection) {
                        await window.marketplaceHandler.unsubscribeFromCollection(col.subscription_id, col.name);
                    } else {
                        console.error('Marketplace handler not available for unsubscribe');
                    }
                });
                actions.appendChild(unsubscribeBtn);
            } else {
                // Owned collection - show Delete button (disabled for ID 0)
                const deleteBtn = document.createElement('button');
                deleteBtn.type = 'button';
                deleteBtn.className = col.id === 0
                    ? 'px-3 py-1 rounded-md bg-gray-800 text-sm text-gray-600 cursor-not-allowed'
                    : 'px-3 py-1 rounded-md bg-red-600 hover:bg-red-500 text-sm text-white';
                deleteBtn.textContent = 'Delete';
                deleteBtn.disabled = col.id === 0;
                if (col.id !== 0) {
                    deleteBtn.addEventListener('click', () => {
                        if (window.ragCollectionManagement) {
                            window.ragCollectionManagement.deleteRagCollection(col.id, col.name);
                        }
                    });
                }
                actions.appendChild(deleteBtn);
            }
            
            actions.appendChild(toggleBtn);
            actions.appendChild(inspectBtn);
            actions.appendChild(editBtn);
            // Delete/Unsubscribe button already appended above

    card.appendChild(header);
    if (desc) card.appendChild(desc);
    card.appendChild(mcpInfo);
    card.appendChild(meta);
    card.appendChild(embeddingInfo);
    card.appendChild(actions);
    
    return card;
}

// --- RAG Collection Inspection Logic ---
export async function openCollectionInspection(collectionId, collectionName, repositoryType = 'planner', repositoryMeta = null) {
    if (collectionId === undefined) return;
    state.currentInspectedCollectionId = collectionId;
    state.currentInspectedCollectionName = collectionName;
    state.currentInspectedRepositoryType = repositoryType;
    state.currentInspectedRepositoryMeta = repositoryMeta;
    
    if (DOM.ragCollectionInspectTitle) {
        DOM.ragCollectionInspectTitle.textContent = `Inspect: ${collectionName}`;
    }
    
    // Show repository metadata for knowledge repositories
    if (repositoryType === 'knowledge' && repositoryMeta) {
        displayKnowledgeRepositoryMetadata(repositoryMeta);
    } else {
        // Hide metadata section for planner repositories
        hideKnowledgeRepositoryMetadata();
    }
    
    handleViewSwitch('rag-collection-inspect-view');
    await fetchAndRenderCollectionRows({ collectionId: collectionId, refresh: true });
    wireCollectionInspectionEvents();
}

function wireCollectionInspectionEvents() {
    if (DOM.ragCollectionInspectBack) {
        DOM.ragCollectionInspectBack.onclick = () => {
            state.currentInspectedCollectionId = null;
            state.currentInspectedCollectionName = null;
            handleViewSwitch('rag-maintenance-view');
        };
    }
    if (DOM.ragCollectionRefreshButton) {
        DOM.ragCollectionRefreshButton.onclick = () => {
            if (state.currentInspectedCollectionId !== null && state.currentInspectedCollectionId !== undefined) {
                fetchAndRenderCollectionRows({ collectionId: state.currentInspectedCollectionId, refresh: true });
            }
        };
    }
    if (DOM.ragCollectionSearchInput && !DOM.ragCollectionSearchInput.dataset._wired) {
        let debounceTimer = null;
        DOM.ragCollectionSearchInput.addEventListener('input', () => {
            const term = DOM.ragCollectionSearchInput.value.trim();
            state.ragCollectionSearchTerm = term;
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                if (state.currentInspectedCollectionId !== null && state.currentInspectedCollectionId !== undefined) {
                    fetchAndRenderCollectionRows({ collectionId: state.currentInspectedCollectionId, query: term });
                }
            }, 300);
        });
        DOM.ragCollectionSearchInput.dataset._wired = 'true';
    }
    
    // Wire infinite scroll pagination on table
    const tableContainer = document.querySelector('#rag-collection-table-body')?.closest('.overflow-auto');
    if (tableContainer && !tableContainer.dataset._scrollWired) {
        let isLoading = false;
        tableContainer.addEventListener('scroll', () => {
            // Check if scrolled near bottom (within 200px)
            if (tableContainer.scrollHeight - tableContainer.scrollTop - tableContainer.clientHeight < 200) {
                // Only load more if we haven't already and there are more rows
                if (!isLoading && state.ragCollectionHasMore && state.currentInspectedCollectionId !== null) {
                    isLoading = true;
                    console.log('[InfiniteScroll] Loading next segment...');
                    fetchAndRenderCollectionRows({ 
                        collectionId: state.currentInspectedCollectionId, 
                        query: state.ragCollectionSearchTerm || ''
                    }).finally(() => {
                        isLoading = false;
                    });
                }
            }
        });
        tableContainer.dataset._scrollWired = 'true';
    }
    
    // Wire table header sorting
    const thead = document.querySelector('#rag-collection-table-body')?.closest('table')?.querySelector('thead');
    if (thead && !thead.dataset._sortingWired) {
        thead.querySelectorAll('th[data-sort-key]').forEach(th => {
            th.addEventListener('click', () => {
                const sortKey = th.dataset.sortKey;
                // Toggle sort direction if clicking same column
                if (state.ragCollectionSortKey === sortKey) {
                    state.ragCollectionSortDirection = state.ragCollectionSortDirection === 'asc' ? 'desc' : 'asc';
                } else {
                    state.ragCollectionSortKey = sortKey;
                    state.ragCollectionSortDirection = 'asc';
                }
                // Fetch sorted data from server (server-side sorting) - reset pagination
                if (state.currentInspectedCollectionId !== null && state.currentInspectedCollectionId !== undefined) {
                    fetchAndRenderCollectionRows({ 
                        collectionId: state.currentInspectedCollectionId, 
                        query: state.ragCollectionSearchTerm || '',
                        refresh: true
                    });
                }
                updateSortIndicators();
            });
        });
        thead.dataset._sortingWired = 'true';
    }
}

async function fetchAndRenderCollectionRows({ collectionId, query = '', refresh = false }) {
    if (collectionId === undefined || collectionId === null) return;
    
    // Reset pagination on refresh or new search
    if (refresh || query !== state.ragCollectionSearchTerm) {
        state.ragCollectionOffset = 0;
        state.ragCollectionHasMore = true;
    }
    
    // Store the search term for next comparison
    state.ragCollectionSearchTerm = query;
    
    if (DOM.ragCollectionLoading) {
        if (state.ragCollectionOffset === 0) {
            // Initial load
            DOM.ragCollectionLoading.textContent = query && query.length >= 3 ? 'Searching...' : 'Loading rows...';
        } else {
            // Pagination load
            DOM.ragCollectionLoading.textContent = 'Loading next segment...';
        }
        DOM.ragCollectionLoading.style.display = 'block';
    }
    try {
        const params = new URLSearchParams();
        const pageSize = 50;  // Reduced from 100 to enable proper pagination batching
        params.set('limit', pageSize.toString());
        params.set('offset', state.ragCollectionOffset.toString());
        params.set('light', 'true');
        if (query && query.length >= 3) {
            params.set('q', query);
        }
        // Add sorting parameters
        if (state.ragCollectionSortKey) {
            params.set('sort_by', state.ragCollectionSortKey);
            params.set('sort_order', state.ragCollectionSortDirection || 'asc');
        }
        // Get authentication token
        const token = localStorage.getItem('tda_auth_token');
        
        // Determine API endpoint based on repository type
        const repositoryType = state.currentInspectedRepositoryType || 'planner';
        let apiUrl;
        if (repositoryType === 'knowledge') {
            apiUrl = `/api/v1/knowledge/collections/${collectionId}/chunks?${params.toString()}`;
        } else {
            apiUrl = `/api/v1/rag/collections/${collectionId}/rows?${params.toString()}`;
        }
        
        const res = await fetch(apiUrl, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (!res.ok) {
            throw new Error(`HTTP error! status: ${res.status}`);
        }
        
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        
        // Handle different response structures: rows (planner) vs chunks (knowledge)
        const newRows = repositoryType === 'knowledge' ? (data.chunks || []) : (data.rows || []);
        const totalAvailable = data.total || 0;
        
        // On first load/refresh, replace rows. On pagination, append rows.
        if (state.ragCollectionOffset === 0) {
            state.currentCollectionRows = newRows;
        } else {
            state.currentCollectionRows = (state.currentCollectionRows || []).concat(newRows);
        }
        
        state.currentCollectionTotal = totalAvailable;
        state.currentCollectionName = data.collection_name || `Collection ${collectionId}`;
        
        // Update offset for next fetch
        state.ragCollectionOffset += newRows.length;
        state.ragCollectionHasMore = state.ragCollectionOffset < totalAvailable;
        
        // Re-render the table based on repository type
        if (state.ragCollectionOffset === newRows.length) {
            // First load - full render
            if (repositoryType === 'knowledge') {
                renderKnowledgeChunks(state.currentCollectionRows, state.currentCollectionTotal, query, state.currentCollectionName);
            } else {
                renderCollectionRows(state.currentCollectionRows, state.currentCollectionTotal, query, state.currentCollectionName);
            }
        } else {
            // Append new rows - append to table
            if (repositoryType === 'knowledge') {
                appendKnowledgeChunks(newRows);
            } else {
                appendCollectionRows(newRows);
            }
        }
        
        updateSortIndicators();
    } catch (e) {
        console.error('Failed to fetch collection rows', e);
        if (DOM.ragCollectionTableBody) {
            // Check if it's actually an error or just an empty collection
            const isEmptyCollection = e.message && e.message.includes('not found');
            const message = isEmptyCollection 
                ? 'No rows available.' 
                : `Error loading rows: ${e.message}`;
            const colorClass = isEmptyCollection ? 'text-gray-400' : 'text-red-400';
            DOM.ragCollectionTableBody.innerHTML = `<tr><td colspan="7" class="px-2 py-2 ${colorClass}">${message}</td></tr>`;
        }
    } finally {
        if (DOM.ragCollectionLoading) {
            DOM.ragCollectionLoading.style.display = 'none';
        }
    }
}

// Export fetchAndRenderCollectionRows so it can be called from other modules (e.g., eventHandlers.js)
export { fetchAndRenderCollectionRows };

/**
 * Append new rows to the table (for infinite scroll pagination)
 */
function appendCollectionRows(newRows) {
    if (!DOM.ragCollectionTableBody || !newRows || newRows.length === 0) return;
    
    newRows.forEach(r => {
        const tr = document.createElement('tr');
        const isSelected = state.currentSelectedCaseId === r.id;
        const selectedClass = isSelected ? 'bg-orange-500/30 ring-1 ring-orange-400/50' : 'border-b border-gray-700';
        tr.className = `${selectedClass} hover:bg-gray-800/40 cursor-pointer transition-colors`;
        
        const efficientBadge = r.is_most_efficient ? '<span class="px-2 py-0.5 rounded bg-green-600 text-white text-xs">Yes</span>' : '<span class="px-2 py-0.5 rounded bg-gray-600 text-white text-xs">No</span>';

        // Convert to number to handle both string and number types from API/ChromaDB
        const feedbackScore = Number(r.user_feedback_score) || 0;
        let feedbackBadge = '<span class="px-2 py-0.5 rounded bg-gray-600 text-white text-xs">—</span>';
        if (feedbackScore === 1) {
            feedbackBadge = '<span class="px-2 py-0.5 rounded bg-green-600 text-white text-xs">👍</span>';
        } else if (feedbackScore === -1) {
            feedbackBadge = '<span class="px-2 py-0.5 rounded bg-red-600 text-white text-xs">👎</span>';
        }
        
        tr.innerHTML = `
            <td class="px-2 py-2 font-mono text-xs text-gray-300 whitespace-nowrap overflow-hidden text-ellipsis">${r.id}</td>
            <td class="px-2 py-2 text-gray-200 whitespace-nowrap overflow-hidden text-ellipsis">${escapeHtml(r.user_query || '')}</td>
            <td class="px-2 py-2 text-gray-300 whitespace-nowrap">${r.strategy_type || ''}</td>
            <td class="px-2 py-2 whitespace-nowrap">${efficientBadge}</td>
            <td class="px-2 py-2 whitespace-nowrap">${feedbackBadge}</td>
            <td class="px-2 py-2 text-gray-300 whitespace-nowrap text-right">${r.output_tokens ?? ''}</td>
            <td class="px-2 py-2 text-gray-400 whitespace-nowrap">${r.timestamp || ''}</td>
        `;
        tr.dataset.caseId = r.id;
        tr.addEventListener('click', () => selectCaseRow(r.id));
        DOM.ragCollectionTableBody.appendChild(tr);
    });
}

function renderCollectionRows(rows, total, query, collectionName) {
    if (!DOM.ragCollectionTableBody) return;
    
    // Restore planner table header
    updateTableHeaderForPlanner();
    
    DOM.ragCollectionTableBody.innerHTML = '';
    
    // Apply sorting to rows
    const sortedRows = [...rows].sort((a, b) => {
        const key = state.ragCollectionSortKey;
        let aVal = a[key];
        let bVal = b[key];
        
        // Handle null/undefined values
        if (aVal == null && bVal == null) return 0;
        if (aVal == null) return state.ragCollectionSortDirection === 'asc' ? 1 : -1;
        if (bVal == null) return state.ragCollectionSortDirection === 'asc' ? -1 : 1;
        
        // Sort logic
        let comparison = 0;
        if (typeof aVal === 'string' && typeof bVal === 'string') {
            comparison = aVal.localeCompare(bVal);
        } else if (typeof aVal === 'number' && typeof bVal === 'number') {
            comparison = aVal - bVal;
        } else if (typeof aVal === 'boolean' && typeof bVal === 'boolean') {
            comparison = aVal === bVal ? 0 : aVal ? 1 : -1;
        } else {
            comparison = String(aVal).localeCompare(String(bVal));
        }
        
        return state.ragCollectionSortDirection === 'asc' ? comparison : -comparison;
    });
    
    if (!sortedRows.length) {
        const message = query && query.length >= 3 ? 'No matches found.' : 'No rows available.';
        DOM.ragCollectionTableBody.innerHTML = `<tr><td colspan="7" class="px-2 py-2 text-gray-400">${message}</td></tr>`;
    } else {
        sortedRows.forEach(r => {
            const tr = document.createElement('tr');
            // Check if this row is currently selected and apply highlight
            const isSelected = state.currentSelectedCaseId === r.id;
            const selectedClass = isSelected ? 'bg-orange-500/30 ring-1 ring-orange-400/50' : 'border-b border-gray-700';
            tr.className = `${selectedClass} hover:bg-gray-800/40 cursor-pointer transition-colors`;
            
            const efficientBadge = r.is_most_efficient ? '<span class="px-2 py-0.5 rounded bg-green-600 text-white text-xs">Yes</span>' : '<span class="px-2 py-0.5 rounded bg-gray-600 text-white text-xs">No</span>';

            // Render feedback badge - convert to number to handle both string and number types from API/ChromaDB
            const feedbackScore = Number(r.user_feedback_score) || 0;
            let feedbackBadge = '<span class="px-2 py-0.5 rounded bg-gray-600 text-white text-xs">—</span>';
            if (feedbackScore === 1) {
                feedbackBadge = '<span class="px-2 py-0.5 rounded bg-green-600 text-white text-xs">👍</span>';
            } else if (feedbackScore === -1) {
                feedbackBadge = '<span class="px-2 py-0.5 rounded bg-red-600 text-white text-xs">👎</span>';
            }
            
            tr.innerHTML = `
                <td class="px-2 py-2 font-mono text-xs text-gray-300 whitespace-nowrap overflow-hidden text-ellipsis">${r.id}</td>
                <td class="px-2 py-2 text-gray-200 whitespace-nowrap overflow-hidden text-ellipsis">${escapeHtml(r.user_query || '')}</td>
                <td class="px-2 py-2 text-gray-300 whitespace-nowrap">${r.strategy_type || ''}</td>
                <td class="px-2 py-2 whitespace-nowrap">${efficientBadge}</td>
                <td class="px-2 py-2 whitespace-nowrap">${feedbackBadge}</td>
                <td class="px-2 py-2 text-gray-300 whitespace-nowrap text-right">${r.output_tokens ?? ''}</td>
                <td class="px-2 py-2 text-gray-400 whitespace-nowrap">${r.timestamp || ''}</td>
            `;
            // Set data attribute AFTER innerHTML so it doesn't get overwritten
            tr.dataset.caseId = r.id;
            tr.addEventListener('click', () => selectCaseRow(r.id));
            DOM.ragCollectionTableBody.appendChild(tr);
        });
    }
    if (DOM.ragCollectionFooter) {
        const mode = query && query.length >= 3 ? 'search results' : 'sample';
        DOM.ragCollectionFooter.textContent = `Showing ${rows.length} ${mode} (collection has ${total} total entries).`;
    }
    
    // Auto-select first row if available
    if (sortedRows.length > 0) {
        selectCaseRow(sortedRows[0].id);
    }
}

export function escapeHtml(str) {
    return str.replace(/[&<>"]+/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ==================== KNOWLEDGE REPOSITORY RENDERING ====================

/**
 * Display knowledge repository metadata in the inspection view
 */
function displayKnowledgeRepositoryMetadata(repo) {
    const metadataSection = document.getElementById('knowledge-repo-metadata');
    if (!metadataSection) return;
    
    // Populate metadata fields
    const descriptionEl = document.getElementById('knowledge-meta-description');
    const docCountEl = document.getElementById('knowledge-meta-doc-count');
    const chunkingEl = document.getElementById('knowledge-meta-chunking');
    const embeddingEl = document.getElementById('knowledge-meta-embedding');
    const chunkSizeEl = document.getElementById('knowledge-meta-chunk-size');
    const overlapEl = document.getElementById('knowledge-meta-overlap');
    const createdEl = document.getElementById('knowledge-meta-created');
    const idEl = document.getElementById('knowledge-meta-id');
    
    if (descriptionEl) {
        descriptionEl.textContent = repo.description || 'Knowledge repository for document storage and retrieval';
    }
    if (chunkingEl) chunkingEl.textContent = repo.chunking_strategy || 'semantic';
    if (embeddingEl) embeddingEl.textContent = repo.embedding_model || 'default';
    if (chunkSizeEl) chunkSizeEl.textContent = repo.chunk_size || 'N/A';
    if (overlapEl) overlapEl.textContent = repo.chunk_overlap || 'N/A';
    if (createdEl) {
        const createdDate = repo.created_at ? new Date(repo.created_at).toLocaleDateString() : 'N/A';
        createdEl.textContent = createdDate;
    }
    if (idEl) {
        idEl.textContent = repo.id || repo.collection_id || 'N/A';
    }
    
    // Fetch document count asynchronously
    if (docCountEl) {
        fetchKnowledgeDocumentCount(repo.id || repo.collection_id, docCountEl);
    }
    
    // Show the metadata section
    metadataSection.classList.remove('hidden');
}

/**
 * Fetch and display document count for knowledge repository
 */
async function fetchKnowledgeDocumentCount(collectionId, targetElement) {
    try {
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/knowledge/repositories/${collectionId}/documents`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            const count = data.documents ? data.documents.length : 0;
            targetElement.textContent = count;
        } else {
            targetElement.textContent = 'N/A';
        }
    } catch (error) {
        console.error('[Knowledge] Failed to fetch document count:', error);
        targetElement.textContent = 'N/A';
    }
}

/**
 * Hide knowledge repository metadata section
 */
function hideKnowledgeRepositoryMetadata() {
    const metadataSection = document.getElementById('knowledge-repo-metadata');
    if (metadataSection) {
        metadataSection.classList.add('hidden');
    }
}

/**
 * Update table header for knowledge repository view
 */
function updateTableHeaderForKnowledge() {
    const thead = document.querySelector('#rag-collection-inspect-view thead tr');
    if (!thead) return;
    
    thead.innerHTML = `
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="id">Chunk ID <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="content">Content Preview <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="document_id">Source Document <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="chunk_index">Chunk Index <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="token_count">Tokens <span class="text-xs text-gray-500">↕</span></th>
    `;
}

/**
 * Restore table header for planner repository view
 */
function updateTableHeaderForPlanner() {
    const thead = document.querySelector('#rag-collection-inspect-view thead tr');
    if (!thead) return;
    
    thead.innerHTML = `
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="id">ID <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="user_query">User Query <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="strategy_type">Strategy <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="is_most_efficient">Efficient <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="user_feedback_score">Feedback <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="output_tokens">Output Tokens <span class="text-xs text-gray-500">↕</span></th>
        <th class="px-2 py-2 text-left text-gray-300 font-semibold cursor-pointer hover:text-white hover:bg-gray-700/50 transition-colors" data-sort-key="timestamp">Timestamp <span class="text-xs text-gray-500">↕</span></th>
    `;
}

/**
 * Append new knowledge chunks to the table (for infinite scroll pagination)
 */
function appendKnowledgeChunks(newChunks) {
    if (!DOM.ragCollectionTableBody || !newChunks || newChunks.length === 0) return;
    
    newChunks.forEach(chunk => {
        const tr = document.createElement('tr');
        const isSelected = state.currentSelectedCaseId === chunk.id;
        const selectedClass = isSelected ? 'bg-orange-500/30 ring-1 ring-orange-400/50' : 'border-b border-gray-700';
        tr.className = `${selectedClass} hover:bg-gray-800/40 cursor-pointer transition-colors`;
        
        // Truncate content for preview
        const contentPreview = chunk.content.length > 100 
            ? chunk.content.substring(0, 100) + '...' 
            : chunk.content;
        
        // Get source filename from metadata
        const sourceDoc = chunk.metadata?.source_filename || chunk.document_id || 'Unknown';
        
        tr.innerHTML = `
            <td class="px-2 py-2 font-mono text-xs text-gray-300 whitespace-nowrap overflow-hidden text-ellipsis" style="max-width: 150px;">${escapeHtml(chunk.id)}</td>
            <td class="px-2 py-2 text-gray-200 overflow-hidden text-ellipsis" style="max-width: 400px;">${escapeHtml(contentPreview)}</td>
            <td class="px-2 py-2 text-gray-300 whitespace-nowrap overflow-hidden text-ellipsis" style="max-width: 200px;">${escapeHtml(sourceDoc)}</td>
            <td class="px-2 py-2 text-gray-300 whitespace-nowrap text-center">${chunk.chunk_index ?? '-'}</td>
            <td class="px-2 py-2 text-gray-300 whitespace-nowrap text-right">${chunk.token_count ?? '-'}</td>
        `;
        tr.dataset.chunkId = chunk.id;
        tr.addEventListener('click', () => selectKnowledgeChunk(chunk.id));
        DOM.ragCollectionTableBody.appendChild(tr);
    });
}

/**
 * Render knowledge chunks in table (full render, not append)
 */
function renderKnowledgeChunks(chunks, total, query, collectionName) {
    if (!DOM.ragCollectionTableBody) return;
    
    // Update table header for knowledge view
    updateTableHeaderForKnowledge();
    
    DOM.ragCollectionTableBody.innerHTML = '';
    
    if (!chunks.length) {
        const message = query && query.length >= 3 ? 'No matches found.' : 'No chunks available.';
        DOM.ragCollectionTableBody.innerHTML = `<tr><td colspan="5" class="px-2 py-2 text-gray-400">${message}</td></tr>`;
    } else {
        chunks.forEach(chunk => {
            const tr = document.createElement('tr');
            const isSelected = state.currentSelectedCaseId === chunk.id;
            const selectedClass = isSelected ? 'bg-orange-500/30 ring-1 ring-orange-400/50' : 'border-b border-gray-700';
            tr.className = `${selectedClass} hover:bg-gray-800/40 cursor-pointer transition-colors`;
            
            // Truncate content for preview
            const contentPreview = chunk.content.length > 100 
                ? chunk.content.substring(0, 100) + '...' 
                : chunk.content;
            
            // Get source filename from metadata
            const sourceDoc = chunk.metadata?.source_filename || chunk.document_id || 'Unknown';
            
            tr.innerHTML = `
                <td class="px-2 py-2 font-mono text-xs text-gray-300 whitespace-nowrap overflow-hidden text-ellipsis" style="max-width: 150px;">${escapeHtml(chunk.id)}</td>
                <td class="px-2 py-2 text-gray-200 overflow-hidden text-ellipsis" style="max-width: 400px;">${escapeHtml(contentPreview)}</td>
                <td class="px-2 py-2 text-gray-300 whitespace-nowrap overflow-hidden text-ellipsis" style="max-width: 200px;">${escapeHtml(sourceDoc)}</td>
                <td class="px-2 py-2 text-gray-300 whitespace-nowrap text-center">${chunk.chunk_index ?? '-'}</td>
                <td class="px-2 py-2 text-gray-300 whitespace-nowrap text-right">${chunk.token_count ?? '-'}</td>
            `;
            tr.dataset.chunkId = chunk.id;
            tr.addEventListener('click', () => selectKnowledgeChunk(chunk.id));
            DOM.ragCollectionTableBody.appendChild(tr);
        });
    }
    
    if (DOM.ragCollectionFooter) {
        const mode = query && query.length >= 3 ? 'search results' : 'chunks';
        DOM.ragCollectionFooter.textContent = `Showing ${chunks.length} ${mode} (collection has ${total} total chunks).`;
    }
    
    // Auto-select first chunk if available
    if (chunks.length > 0) {
        selectKnowledgeChunk(chunks[0].id);
    }
}

/**
 * Handle selection of a knowledge chunk row
 */
async function selectKnowledgeChunk(chunkId) {
    if (!chunkId) return;
    
    // Update selected chunk ID (reuse case ID state)
    state.currentSelectedCaseId = chunkId;
    
    // Highlight the selected row
    const allRows = document.querySelectorAll('#rag-collection-table-body tr[data-chunk-id]');
    allRows.forEach(row => {
        if (row.dataset.chunkId === chunkId) {
            row.classList.remove('border-b', 'border-gray-700');
            row.classList.add('bg-orange-500/30', 'ring-1', 'ring-orange-400/50');
        } else {
            row.classList.remove('bg-orange-500/30', 'ring-1', 'ring-orange-400/50');
            row.classList.add('border-b', 'border-gray-700');
        }
    });
    
    // Show the details panel
    if (DOM.ragSelectedCaseDetails) {
        DOM.ragSelectedCaseDetails.classList.remove('hidden');
        if (DOM.ragSelectedCaseSeparator) {
            DOM.ragSelectedCaseSeparator.classList.remove('hidden');
        }
    }
    
    // Show loading state
    if (DOM.ragSelectedCaseMetadata) {
        DOM.ragSelectedCaseMetadata.innerHTML = '<span class="text-gray-400">Loading chunk details...</span>';
    }
    if (DOM.ragSelectedCasePlan) {
        DOM.ragSelectedCasePlan.innerHTML = '<div class="text-gray-400">Loading full content...</div>';
    }
    
    try {
        // Fetch FULL chunk data from dedicated endpoint
        const token = localStorage.getItem('tda_auth_token');
        const collectionId = state.currentInspectedCollectionId;
        const apiUrl = `/api/v1/knowledge/collections/${collectionId}/chunks/${encodeURIComponent(chunkId)}`;
        
        console.log('Fetching full chunk from:', apiUrl);
        
        const res = await fetch(apiUrl, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (!res.ok) {
            throw new Error(`HTTP error! status: ${res.status}`);
        }
        
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        
        const chunk = data.chunk;
        console.log('Received chunk with content length:', chunk?.content?.length);
        
        if (!chunk) {
            if (DOM.ragSelectedCaseMetadata) {
                DOM.ragSelectedCaseMetadata.innerHTML = '<span class="text-red-400">Chunk not found</span>';
            }
            return;
        }
        
        // Display chunk details
        if (DOM.ragSelectedCaseMetadata) {
            const metadata = chunk.metadata || {};
            const metadataEntries = Object.entries(metadata)
                .filter(([key, value]) => value != null && value !== '')
                .map(([key, value]) => `<strong>${escapeHtml(key)}:</strong> ${escapeHtml(String(value))}`)
                .join(' | ');
            
            DOM.ragSelectedCaseMetadata.innerHTML = `
                <div class="space-y-2">
                    <div><strong>Chunk ID:</strong> <span class="font-mono text-xs">${escapeHtml(chunkId)}</span></div>
                    <div><strong>Document ID:</strong> <span class="font-mono text-xs">${escapeHtml(chunk.document_id || 'N/A')}</span></div>
                    <div><strong>Chunk Index:</strong> ${chunk.chunk_index ?? 'N/A'}</div>
                    <div><strong>Token Count:</strong> ${chunk.token_count ?? 'N/A'}</div>
                    ${metadataEntries ? `<div class="text-xs text-gray-500">${metadataEntries}</div>` : ''}
                </div>
            `;
        }
        
        // Display full chunk content
        if (DOM.ragSelectedCasePlan) {
            const contentLength = chunk.content ? chunk.content.length : 0;
            DOM.ragSelectedCasePlan.innerHTML = `
                <h3 class="text-sm font-semibold text-gray-300 mb-2">Full Content (${contentLength} characters)</h3>
                <div class="bg-gray-900/50 rounded-lg p-4 border border-white/10" style="height: 300px; overflow-y: scroll; overflow-x: hidden;">
                    <pre class="text-sm text-gray-200" style="white-space: pre-wrap; word-wrap: break-word; margin: 0; font-family: inherit;">${escapeHtml(chunk.content)}</pre>
                </div>
            `;
        }
        
        // Clear trace section (not applicable for knowledge chunks)
        if (DOM.ragSelectedCaseTrace) {
            DOM.ragSelectedCaseTrace.innerHTML = '';
        }
        
    } catch (error) {
        console.error('Error fetching full chunk:', error);
        if (DOM.ragSelectedCaseMetadata) {
            DOM.ragSelectedCaseMetadata.innerHTML = `<span class="text-red-400">Error loading chunk: ${escapeHtml(error.message)}</span>`;
        }
    }
}

// ==================== END KNOWLEDGE REPOSITORY RENDERING ====================

async function selectCaseRow(caseId) {
    if (!caseId) return;
    // Update the selected case ID and highlight the row
    updateSelectedCaseId(caseId);
    if (DOM.ragSelectedCaseDetails) {
        DOM.ragSelectedCaseDetails.classList.remove('hidden');
        DOM.ragSelectedCaseMetadata.textContent = 'Loading case details...';
        DOM.ragSelectedCasePlan.innerHTML = '';
        DOM.ragSelectedCaseTrace.innerHTML = '';
        if (DOM.ragSelectedCaseSeparator) {
            DOM.ragSelectedCaseSeparator.classList.remove('hidden');
        }
    }
    try {
        // Get authentication token
        const token = localStorage.getItem('tda_auth_token');
        const res = await fetch(`/rag/cases/${encodeURIComponent(caseId)}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        const caseData = data.case || {};
        const turnSummary = data.session_turn_summary || null;
        if (DOM.ragSelectedCaseMetadata) {
            const meta = caseData.metadata || {};
            
            // --- MODIFICATION START: Create interactive feedback selector ---
            // Use RAG case feedback score (not session turn feedback)
            const ragFeedbackScore = meta.user_feedback_score ?? 0;
            const sessionId = meta.session_id;
            const turnId = meta.turn_id;
            
            let feedbackHtml = '<span class="text-gray-400">N/A (no session data)</span>';
            if (sessionId && turnId !== undefined && turnId !== null) {
                const upActive = ragFeedbackScore === 1 ? 'text-[#F15F22] bg-gray-800/60' : 'text-gray-300';
                const downActive = ragFeedbackScore === -1 ? 'text-[#F15F22] bg-gray-800/60' : 'text-gray-300';
                feedbackHtml = `
                    <div class="inline-flex items-stretch rounded-md bg-gray-900/50 border border-white/10 overflow-hidden backdrop-blur-sm">
                        <button type="button" 
                                class="case-feedback-btn px-2 py-0.5 flex items-center gap-1 ${upActive} hover:text-white hover:bg-gray-800/60 transition text-xs"
                                data-case-id="${escapeHtml(caseData.case_id || caseId)}"
                                data-session-id="${escapeHtml(sessionId)}" 
                                data-turn-id="${turnId}" 
                                data-vote="up"
                                title="Mark as helpful">
                            <svg class='w-3 h-3' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'>
                                <path d='M14 9V5a3 3 0 00-3-3l-4 9v11h11a3 3 0 003-3v-5a3 3 0 00-3-3h-7'/>
                            </svg>
                            <span class="text-[10px]">Helpful</span>
                        </button>
                        <div class="w-px bg-white/10"></div>
                        <button type="button" 
                                class="case-feedback-btn px-2 py-0.5 flex items-center gap-1 ${downActive} hover:text-white hover:bg-gray-800/60 transition text-xs"
                                data-case-id="${escapeHtml(caseData.case_id || caseId)}"
                                data-session-id="${escapeHtml(sessionId)}" 
                                data-turn-id="${turnId}" 
                                data-vote="down"
                                title="Mark as unhelpful">
                            <svg class='w-3 h-3' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'>
                                <path d='M10 15v4a3 3 0 003 3l4-9V2H6a3 3 0 00-3 3v5a3 3 0 003 3h7'/>
                            </svg>
                            <span class="text-[10px]">Unhelpful</span>
                        </button>
                    </div>`;
            } else if (ragFeedbackScore === 1) {
                feedbackHtml = '<span class="text-[#F15F22]">👍 Helpful</span>';
            } else if (ragFeedbackScore === -1) {
                feedbackHtml = '<span class="text-[#F15F22]">👎 Unhelpful</span>';
            } else {
                feedbackHtml = '<span class="text-gray-400">None</span>';
            }
            // --- MODIFICATION END ---
            
            // Compute total execution time from trace timestamps (first to last)
            let totalExecutionTime = 'N/A';
            if (turnSummary && Array.isArray(turnSummary.execution_trace) && turnSummary.execution_trace.length > 0) {
                const parseTs = (entry) => {
                    try {
                        const ts = entry?.action?.metadata?.timestamp || entry?.result?.metadata?.timestamp;
                        return ts ? Date.parse(ts) : null;
                    } catch { return null; }
                };
                // Find first and last valid timestamps
                const firstEntry = turnSummary.execution_trace.find(e => parseTs(e) !== null);
                const lastEntry = [...turnSummary.execution_trace].reverse().find(e => parseTs(e) !== null);
                const firstTs = parseTs(firstEntry);
                const lastTs = parseTs(lastEntry);
                if (firstTs !== null && lastTs !== null && lastTs >= firstTs) {
                    totalExecutionTime = ((lastTs - firstTs) / 1000).toFixed(2) + 's';
                }
            }
            DOM.ragSelectedCaseMetadata.innerHTML = `
                <div class='grid grid-cols-2 md:grid-cols-4 gap-2'>
                    <div><span class='text-gray-500'>Case ID:</span> <code>${escapeHtml(caseData.case_id || caseId)}</code></div>
                    <div><span class='text-gray-500'>Task ID:</span> <code>${escapeHtml(meta.task_id || '')}</code></div>
                    <div><span class='text-gray-500'>Session:</span> <code>${escapeHtml(meta.session_id || '')}</code></div>
                    <div><span class='text-gray-500'>Turn:</span> <code>${escapeHtml(String(meta.turn_id ?? ''))}</code></div>
                    <div><span class='text-gray-500'>Provider:</span> ${escapeHtml(meta.llm_config?.provider || '')}</div>
                    <div><span class='text-gray-500'>Model:</span> ${escapeHtml(meta.llm_config?.model || '')}</div>
                    <div><span class='text-gray-500'>Output Tokens:</span> ${escapeHtml(String(meta.llm_config?.output_tokens ?? ''))}</div>
                    <div><span class='text-gray-500'>Efficient:</span> ${meta.is_most_efficient ? '<span class="text-green-400">Yes</span>' : '<span class="text-gray-400">No</span>'}</div>
                    <div><span class='text-gray-500'>User Feedback:</span> ${feedbackHtml}</div>
                </div>
                <div class='mt-2 text-xs text-gray-400'>Total Execution Time: <span class='font-mono text-gray-200'>${totalExecutionTime}</span></div>`;
        }
        if (DOM.ragSelectedCasePlan) {
            const phases = caseData.successful_strategy?.phases || [];
            if (phases.length) {
                const phaseHtml = phases.map(p => `
                    <div class='p-2 rounded-md bg-gray-800/40 border border-white/10'>
                        <div class='text-xs font-semibold text-teradata-orange mb-1'>Phase ${p.phase}</div>
                        <div class='text-sm text-gray-200 mb-1'>Goal: ${escapeHtml(p.goal || '')}</div>
                        <div class='text-xs text-gray-400'>Tools: ${(p.relevant_tools || []).map(t => `<code>${escapeHtml(t)}</code>`).join(', ')}</div>
                    </div>`).join('');
                DOM.ragSelectedCasePlan.innerHTML = `<h3 class='text-white font-semibold mb-2'>Successful Strategy</h3><div class='grid md:grid-cols-2 gap-2'>${phaseHtml}</div>`;
            } else {
                DOM.ragSelectedCasePlan.innerHTML = '<div class="text-gray-400 text-sm">No successful strategy phases.</div>';
            }
        }
        if (DOM.ragSelectedCaseTrace) {
            if (turnSummary && Array.isArray(turnSummary.execution_trace)) {
                // Store raw trace and render via helper for toggling & collapsing
                state.currentCaseTrace = turnSummary.execution_trace.slice();
                renderCaseTrace();
            } else {
                DOM.ragSelectedCaseTrace.innerHTML = '<div class="text-gray-400 text-sm">No execution trace available.</div>';
            }
        }
    } catch (e) {
        console.error('Failed to load case details', e);
        if (DOM.ragSelectedCaseMetadata) {
            DOM.ragSelectedCaseMetadata.textContent = 'Error loading case details.';
        }
    }
}

// Export selectCaseRow so it can be called from other modules (e.g., eventHandlers.js)
export { selectCaseRow };

/**
 * Updates the selected case ID in state and refreshes row highlighting.
 * Called when a case row is clicked or when feedback is updated.
 * @param {string} caseId - The ID of the selected case
 */
function updateSelectedCaseId(caseId) {
    state.currentSelectedCaseId = caseId;
    // Highlight all rows - remove highlighting from all, add to selected
    const allRows = document.querySelectorAll('#rag-collection-table-body tr[data-case-id]');
    allRows.forEach(row => {
        if (row.dataset.caseId === caseId) {
            row.classList.remove('border-b', 'border-gray-700');
            row.classList.add('bg-orange-500/30', 'ring-1', 'ring-orange-400/50');
        } else {
            row.classList.remove('bg-orange-500/30', 'ring-1', 'ring-orange-400/50');
            row.classList.add('border-b', 'border-gray-700');
        }
    });
}

// Export updateSelectedCaseId so it can be called from event handlers
export { updateSelectedCaseId };

/**
 * Updates the feedback badge for a specific row in the table without refreshing the entire table
 * @param {string} caseId - The case ID to update
 * @param {number} feedbackScore - The new feedback score (-1, 0, or 1)
 */
function updateTableRowFeedback(caseId, feedbackScore) {
    const allRows = document.querySelectorAll('#rag-collection-table-body tr');
    let row = null;
    
    // Try exact match first
    for (const r of allRows) {
        if (r.dataset.caseId === caseId) {
            row = r;
            break;
        }
    }
    
    // If not found, try with/without "case_" prefix
    if (!row) {
        const altCaseId = caseId.startsWith('case_') ? caseId.substring(5) : `case_${caseId}`;
        for (const r of allRows) {
            if (r.dataset.caseId === altCaseId) {
                row = r;
                break;
            }
        }
    }
    
    if (!row) {
        console.warn('[updateTableRowFeedback] Row not found for caseId:', caseId);
        return;
    }
    
    console.log('[updateTableRowFeedback] Row found, updating feedback badge');

    // Find the feedback badge cell (5th column, index 4)
    const feedbackCell = row.cells[4];
    if (!feedbackCell) {
        console.warn('[updateTableRowFeedback] Feedback cell not found');
        return;
    }

    // Generate new feedback badge - convert to number to handle both string and number types
    const score = Number(feedbackScore) || 0;
    let feedbackBadge = '<span class="px-2 py-0.5 rounded bg-gray-600 text-white text-xs">—</span>';
    if (score === 1) {
        feedbackBadge = '<span class="px-2 py-0.5 rounded bg-green-600 text-white text-xs">👍</span>';
    } else if (score === -1) {
        feedbackBadge = '<span class="px-2 py-0.5 rounded bg-red-600 text-white text-xs">👎</span>';
    }
    
    // Update the cell
    feedbackCell.innerHTML = feedbackBadge;
    console.log('[updateTableRowFeedback] Feedback badge updated successfully');
}

// Export updateTableRowFeedback so it can be called from event handlers
export { updateTableRowFeedback };

/**
 * Updates visual indicators on table headers to show current sort state
 */
function updateSortIndicators() {
    const thead = document.querySelector('#rag-collection-table-body')?.closest('table')?.querySelector('thead');
    if (!thead) return;
    
    thead.querySelectorAll('th[data-sort-key]').forEach(th => {
        const sortKey = th.dataset.sortKey;
        const span = th.querySelector('span');
        if (!span) return;
        
        if (sortKey === state.ragCollectionSortKey) {
            // Show active sort indicator
            const arrow = state.ragCollectionSortDirection === 'asc' ? '↑' : '↓';
            span.textContent = arrow;
            span.className = 'text-xs text-orange-400 font-bold';
            th.classList.add('bg-orange-500/20');
        } else {
            // Show default indicator
            span.textContent = '↕';
            span.className = 'text-xs text-gray-500';
            th.classList.remove('bg-orange-500/20');
        }
    });
}

function renderCaseTrace() {
    if (!DOM.ragSelectedCaseTrace) return;
    const rawTrace = Array.isArray(state.currentCaseTrace) ? state.currentCaseTrace : [];
    let workingTrace = rawTrace;
    if (!state.showSystemLogsInCaseTrace) {
        workingTrace = workingTrace.filter(entry => !(entry.action && entry.action.tool_name === 'TDA_SystemLog'));
    }
    // Collapse duplicates if enabled
    let collapsed = [];
    if (state.collapseDuplicateTraceEntries) {
        for (let i = 0; i < workingTrace.length; i++) {
            const entry = workingTrace[i];
            const prev = collapsed.length ? collapsed[collapsed.length - 1] : null;
            const toolName = entry.action && entry.action.tool_name;
            const message = entry.action && entry.action.arguments && entry.action.arguments.message;
            const status = entry.result && entry.result.status;
            if (prev && prev.__toolName === toolName && prev.__message === message && prev.__status === status) {
                prev.__count += 1;
                prev.entries.push(entry);
            } else {
                const wrapper = { ...entry, __toolName: toolName, __message: message, __status: status, __count: 1, entries: [entry] };
                collapsed.push(wrapper);
            }
        }
    } else {
        collapsed = workingTrace.map(e => ({ ...e, __toolName: e.action && e.action.tool_name, __message: e.action && e.action.arguments && e.action.arguments.message, __status: e.result && e.result.status, __count: 1, entries: [e] }));
    }

    // Timing calculations
    const parseTs = ts => {
        try { return ts ? Date.parse(ts) : null; } catch { return null; }
    };
    const firstTs = collapsed.length ? parseTs(collapsed[0].action && collapsed[0].action.metadata && collapsed[0].action.metadata.timestamp) : null;

    const html = collapsed.map(block => {
        const action = block.action || {}; const result = block.result || {};
        const tool = block.__toolName || 'unknown';
        const status = block.__status || 'info';
        const msg = block.__message || '';
        const tsRaw = action.metadata && action.metadata.timestamp;
        const currentTs = parseTs(tsRaw);
        let elapsed = '-';
        let delta = '-';
        if (currentTs && firstTs) {
            elapsed = ((currentTs - firstTs) / 1000).toFixed(2) + 's';
        }
        // Find previous distinct block timestamp for delta
        const idx = collapsed.indexOf(block);
        if (idx > 0) {
            const prevTsRaw = collapsed[idx - 1].action && collapsed[idx - 1].action.metadata && collapsed[idx - 1].action.metadata.timestamp;
            const prevTs = parseTs(prevTsRaw);
            if (currentTs && prevTs) {
                delta = ((currentTs - prevTs) / 1000).toFixed(2) + 's';
            }
        }
        const repeatBadge = block.__count > 1 ? `<span class='ml-2 px-1 py-0.5 rounded bg-blue-600/60 text-[10px]'>x${block.__count}</span>` : '';
        const timingBadge = `<span class='text-[10px] text-gray-500'>t=${elapsed} Δ=${delta}</span>`;
        return `<div class='text-xs p-2 rounded bg-gray-900/40 border border-gray-700/40'>
            <div class='flex justify-between items-center'><span class='font-mono text-gray-300'>${escapeHtml(tool)}</span><span class='text-[10px] ${status === 'error' ? 'text-red-400' : 'text-green-400'}'>${escapeHtml(status)}</span></div>
            <div class='text-gray-400 mt-1'>${escapeHtml(msg)}</div>
            <div class='flex justify-between mt-1'>${timingBadge}${repeatBadge}</div>
        </div>`;
    }).join('');

    DOM.ragSelectedCaseTrace.innerHTML = `<h3 class='text-white font-semibold mb-2 flex items-center gap-4'>Execution Trace
        <label class='flex items-center gap-1 text-[11px] font-normal'><input type='checkbox' id='toggle-system-logs' ${state.showSystemLogsInCaseTrace ? 'checked' : ''}>System Logs</label>
        <label class='flex items-center gap-1 text-[11px] font-normal'><input type='checkbox' id='toggle-collapse-dupes' ${state.collapseDuplicateTraceEntries ? 'checked' : ''}>Collapse Duplicates</label>
    </h3>
    <div class='space-y-1 max-h-64 overflow-y-auto pr-1'>${html}</div>`;

    const sysToggle = document.getElementById('toggle-system-logs');
    const dupesToggle = document.getElementById('toggle-collapse-dupes');
    if (sysToggle) {
        sysToggle.onchange = () => { state.showSystemLogsInCaseTrace = sysToggle.checked; renderCaseTrace(); };
    }
    if (dupesToggle) {
        dupesToggle.onchange = () => { state.collapseDuplicateTraceEntries = dupesToggle.checked; renderCaseTrace(); };
    }
}

/**
 * Copies the session ID to the clipboard.
 * @param {string} sessionId - The session ID to copy.
 */
export function copySessionIdToClipboard(sessionId) {
    navigator.clipboard.writeText(sessionId).then(() => {
    }).catch(err => {
        console.error('Failed to copy session ID:', err);
    });
}

/**
 * Load document count for a Knowledge repository
 */
async function loadKnowledgeRepositoryDocCount(collectionId) {
    try {
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/knowledge/repositories/${collectionId}/documents`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            const count = data.documents ? data.documents.length : 0;
            const countEl = document.getElementById(`doc-count-${collectionId}`);
            if (countEl) {
                countEl.textContent = `${count} document${count !== 1 ? 's' : ''}`;
            }
        }
    } catch (error) {
        console.error(`Failed to load document count for collection ${collectionId}:`, error);
    }
}

/**
 * Open Knowledge repository view to show documents and details
 */
function openKnowledgeRepositoryView(collection) {
    console.log('[Knowledge] Opening repository view:', collection);
    
    // Store current repository in state
    state.currentKnowledgeRepository = collection;
    
    // For now, show an alert with details - we'll create a proper view modal later
    const msg = `Knowledge Repository: ${collection.name}\n\n` +
                `Description: ${collection.description || 'N/A'}\n` +
                `Chunking: ${collection.chunking_strategy || 'semantic'}\n` +
                `Collection ID: ${collection.id}\n` +
                `ChromaDB: ${collection.collection_name}\n\n` +
                `View modal coming soon...`;
    
    // Using info banner as temporary solution until proper modal is implemented
    showAppBanner('Repository details view coming soon', 'info');
    console.log(msg);
    
    // TODO: Create a proper modal to show:
    // - Repository details
    // - Document list with upload dates
    // - Document preview/chunking preview
    // - Add more documents button
}

/**
 * Delete a Knowledge repository
 */
export async function deleteKnowledgeRepository(collectionId, collectionName) {
    // Use custom confirmation modal (same as planner repositories)
    if (!window.showConfirmation) {
        console.error('Confirmation system not available');
        return;
    }

    showConfirmation(
        'Delete Knowledge Repository',
        `Are you sure you want to delete the repository "${collectionName}"?\n\nThis will remove all documents and cannot be undone.`,
        async () => {
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
                    showAppBanner(`Repository "${collectionName}" deleted successfully`, 'success');
                    // Reload the collections list
                    await loadRagCollections();
                } else {
                    showAppBanner(`Failed to delete repository: ${data.message || data.error || 'Unknown error'}`, 'error');
                }
            } catch (error) {
                console.error('[Knowledge] Error deleting repository:', error);
                showAppBanner(`Error deleting repository: ${error.message}`, 'error');
            }
        }
    );
}