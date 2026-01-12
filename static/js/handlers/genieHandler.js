/**
 * handlers/genieHandler.js
 *
 * Handles Genie coordination UI updates and inline progress cards.
 * Provides world-class real-time feedback for Genie profile execution.
 *
 * This module:
 * - Creates inline progress cards in the conversation panel
 * - Updates card state as coordination events are received
 * - Triggers split view when slave sessions are clicked
 */

import * as DOM from '../domElements.js';
import { state } from '../state.js';

// ============================================================================
// Genie Coordination State
// ============================================================================

export const genieState = {
    activeCoordination: null,  // Current coordination session ID
    cardElement: null,         // Reference to inline card DOM element
    slaveProgress: {},         // {profile_tag: {status, name, id, sessionId}}
    startTime: null,           // Timestamp when coordination started
    timerAnimationFrame: null  // Animation frame ID for timer
};

// ============================================================================
// Coordination Lifecycle Functions
// ============================================================================

/**
 * Initialize Genie coordination display.
 * Called when genie_coordination_start event is received.
 */
export function initGenieCoordination(payload) {
    const { genie_session_id, query, slave_profiles } = payload;

    // Only show card for current session
    if (payload.session_id && payload.session_id !== state.currentSessionId) {
        console.log('[GenieHandler] Ignoring coordination event for different session');
        return;
    }

    // Clear any existing coordination
    if (genieState.activeCoordination) {
        console.warn('[GenieHandler] New coordination started while previous still active');
        cleanupCoordination();
    }

    genieState.activeCoordination = genie_session_id || payload.session_id;
    genieState.slaveProgress = {};
    genieState.startTime = Date.now();

    // Initialize progress tracking for each slave profile
    (slave_profiles || []).forEach(p => {
        genieState.slaveProgress[p.tag] = {
            status: 'pending',
            name: p.name || '',
            id: p.id
        };
    });

    // Create and append inline card
    genieState.cardElement = createGenieProgressCard(slave_profiles || []);

    // Find chat log and append
    const chatLog = DOM.chatLog || document.getElementById('chat-log');
    if (chatLog) {
        chatLog.appendChild(genieState.cardElement);
        genieState.cardElement.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }

    console.log('[GenieHandler] Coordination started with', (slave_profiles || []).length, 'slave profiles');
}

/**
 * Create the inline progress card DOM element.
 * NOTE: We no longer pre-populate with all available profiles.
 * Instead, profile cards are dynamically added when genie_slave_invoked events arrive.
 * This ensures only actually-used profiles appear in the card.
 */
function createGenieProgressCard(slaveProfiles) {
    const card = document.createElement('div');
    card.className = 'genie-coordination-card message-bubble glass-panel';
    card.id = `genie-card-${Date.now()}`;

    // Store available profiles for reference (used to get name when invoked)
    card.dataset.availableProfiles = JSON.stringify(slaveProfiles.reduce((acc, p) => {
        acc[p.tag] = { name: p.name || '', id: p.id };
        return acc;
    }, {}));

    // Start with empty slaves grid - cards are added dynamically when invoked
    card.innerHTML = `
        <div class="genie-card-header">
            <div class="genie-icon-wrapper">
                <div class="genie-icon pulsing">G</div>
            </div>
            <div class="genie-header-content">
                <h4 class="genie-title">Coordinating Response</h4>
                <p class="genie-subtitle">Analyzing your question and routing to experts...</p>
            </div>
            <div class="genie-timer">
                <span class="timer-value">0.0s</span>
            </div>
        </div>

        <div class="genie-routing-decision" style="display: none;">
            <p class="routing-text"></p>
        </div>

        <div class="genie-slaves-grid">
            <!-- Slave cards added dynamically when invoked -->
        </div>

        <div class="genie-synthesis" style="display: none;">
            <div class="synthesis-spinner"></div>
            <span>Synthesizing response from consulted experts...</span>
        </div>
    `;

    // Start timer animation
    startCardTimer(card);

    return card;
}

/**
 * Start the elapsed time timer on the card.
 */
function startCardTimer(card) {
    const timerEl = card.querySelector('.timer-value');
    if (!timerEl) return;

    const startTime = Date.now();

    const updateTimer = () => {
        if (!genieState.activeCoordination) return;

        const elapsed = (Date.now() - startTime) / 1000;
        timerEl.textContent = `${elapsed.toFixed(1)}s`;
        genieState.timerAnimationFrame = requestAnimationFrame(updateTimer);
    };

    genieState.timerAnimationFrame = requestAnimationFrame(updateTimer);
}

// ============================================================================
// Event Update Functions
// ============================================================================

/**
 * Show routing decision in the card.
 * Called when genie_routing_decision event is received.
 */
export function showRoutingDecision(payload) {
    if (!genieState.cardElement) return;

    const { decision_text, selected_profiles } = payload;
    const decisionEl = genieState.cardElement.querySelector('.genie-routing-decision');
    const textEl = decisionEl?.querySelector('.routing-text');

    if (decisionEl && textEl) {
        textEl.textContent = decision_text || '';
        decisionEl.style.display = 'block';
        decisionEl.classList.add('fade-in');
    }

    // Update subtitle
    const subtitle = genieState.cardElement.querySelector('.genie-subtitle');
    if (subtitle && selected_profiles) {
        const count = selected_profiles.length;
        subtitle.textContent = `Consulting ${count} expert${count > 1 ? 's' : ''}...`;
    }
}

/**
 * Update slave card when invoked.
 * Called when genie_slave_invoked event is received.
 * If the slave card doesn't exist yet, it will be dynamically created.
 */
export function updateSlaveInvoked(payload) {
    if (!genieState.cardElement) return;

    const { profile_tag, slave_session_id, profile_id } = payload;
    let slaveCard = genieState.cardElement.querySelector(`[data-tag="${profile_tag}"]`);

    // If slave card doesn't exist, create it dynamically
    if (!slaveCard) {
        const slavesGrid = genieState.cardElement.querySelector('.genie-slaves-grid');
        if (slavesGrid) {
            // Get profile info from stored available profiles
            let profileName = '';
            let profileIdToUse = profile_id || '';
            try {
                const availableProfiles = JSON.parse(genieState.cardElement.dataset.availableProfiles || '{}');
                if (availableProfiles[profile_tag]) {
                    profileName = availableProfiles[profile_tag].name || '';
                    profileIdToUse = availableProfiles[profile_tag].id || profile_id || '';
                }
            } catch (e) {
                console.warn('[GenieHandler] Could not parse available profiles:', e);
            }

            // Create the slave card
            slaveCard = document.createElement('div');
            slaveCard.className = 'genie-slave-card';
            slaveCard.dataset.tag = profile_tag;
            slaveCard.dataset.id = profileIdToUse;
            slaveCard.innerHTML = `
                <div class="slave-status-indicator active"></div>
                <div class="slave-info">
                    <span class="slave-tag">@${profile_tag}</span>
                    <span class="slave-name">${profileName}</span>
                </div>
                <div class="slave-progress-bar">
                    <div class="progress-fill" style="width: 15%"></div>
                </div>
                <div class="slave-status-text">Processing...</div>
            `;
            slaveCard.classList.add('active');
            slavesGrid.appendChild(slaveCard);

            // Update subtitle to show count
            const currentCount = slavesGrid.querySelectorAll('.genie-slave-card').length;
            const subtitle = genieState.cardElement.querySelector('.genie-subtitle');
            if (subtitle) {
                subtitle.textContent = `Consulting ${currentCount} expert${currentCount > 1 ? 's' : ''}...`;
            }
        }
    } else {
        // Card exists, update it
        const indicator = slaveCard.querySelector('.slave-status-indicator');
        if (indicator) {
            indicator.className = 'slave-status-indicator active';
        }

        const statusText = slaveCard.querySelector('.slave-status-text');
        if (statusText) {
            statusText.textContent = 'Processing...';
        }

        const progressFill = slaveCard.querySelector('.progress-fill');
        if (progressFill) {
            progressFill.style.width = '15%';
        }

        slaveCard.classList.add('active');
    }

    // Store session ID and make clickable
    if (slaveCard && slave_session_id) {
        slaveCard.dataset.sessionId = slave_session_id;
        slaveCard.style.cursor = 'pointer';
        slaveCard.title = 'Click to view slave session in split view';
        slaveCard.onclick = () => openSplitView(slave_session_id, profile_tag);
    }

    // Update internal state
    if (!genieState.slaveProgress[profile_tag]) {
        genieState.slaveProgress[profile_tag] = { status: 'active', sessionId: slave_session_id };
    } else {
        genieState.slaveProgress[profile_tag].status = 'active';
        genieState.slaveProgress[profile_tag].sessionId = slave_session_id;
    }
}

/**
 * Update slave progress.
 * Called when genie_slave_progress event is received.
 */
export function updateSlaveProgress(payload) {
    if (!genieState.cardElement) return;

    const { profile_tag, status, message, progress_pct } = payload;
    const slaveCard = genieState.cardElement.querySelector(`[data-tag="${profile_tag}"]`);

    if (slaveCard) {
        // Update status text if provided
        if (message) {
            const statusText = slaveCard.querySelector('.slave-status-text');
            if (statusText) {
                statusText.textContent = message;
            }
        }

        // Update progress bar if percentage provided
        if (progress_pct !== undefined) {
            const progressFill = slaveCard.querySelector('.progress-fill');
            if (progressFill) {
                progressFill.style.width = `${progress_pct}%`;
            }
        }
    }
}

/**
 * Update slave card when completed.
 * Called when genie_slave_completed event is received.
 */
export function updateSlaveCompleted(payload) {
    if (!genieState.cardElement) return;

    const { profile_tag, result_preview, duration_ms, success } = payload;
    const slaveCard = genieState.cardElement.querySelector(`[data-tag="${profile_tag}"]`);

    if (slaveCard) {
        // Update status indicator
        const indicator = slaveCard.querySelector('.slave-status-indicator');
        if (indicator) {
            indicator.className = `slave-status-indicator ${success ? 'completed' : 'error'}`;
        }

        // Update status text
        const statusText = slaveCard.querySelector('.slave-status-text');
        if (statusText) {
            if (success) {
                const duration = duration_ms ? `${(duration_ms / 1000).toFixed(1)}s` : '';
                statusText.textContent = duration ? `Done ${duration}` : 'Done';
            } else {
                statusText.textContent = 'Failed';
            }
        }

        // Complete progress bar
        const progressFill = slaveCard.querySelector('.progress-fill');
        if (progressFill) {
            progressFill.style.width = success ? '100%' : '100%';
        }

        // Update classes
        slaveCard.classList.remove('active');
        slaveCard.classList.add(success ? 'completed' : 'error');
    }

    // Update internal state
    if (genieState.slaveProgress[profile_tag]) {
        genieState.slaveProgress[profile_tag].status = success ? 'completed' : 'error';
    }
}

/**
 * Show synthesis phase.
 * Called when genie_synthesis_start event is received.
 */
export function showSynthesis(payload) {
    if (!genieState.cardElement) return;

    const synthesisEl = genieState.cardElement.querySelector('.genie-synthesis');
    if (synthesisEl) {
        synthesisEl.style.display = 'flex';
        synthesisEl.classList.add('fade-in');
    }

    // Update subtitle
    const subtitle = genieState.cardElement.querySelector('.genie-subtitle');
    if (subtitle) {
        const profileCount = payload.profiles_consulted?.length || 0;
        subtitle.textContent = `Combining insights from ${profileCount} expert${profileCount > 1 ? 's' : ''}...`;
    }
}

/**
 * Complete coordination and finalize card.
 * Called when genie_coordination_complete event is received.
 */
export function completeCoordination(payload) {
    if (!genieState.cardElement) return;

    const { total_duration_ms, profiles_used, success } = payload;

    // Stop timer animation
    if (genieState.timerAnimationFrame) {
        cancelAnimationFrame(genieState.timerAnimationFrame);
        genieState.timerAnimationFrame = null;
    }

    // Update icon
    const icon = genieState.cardElement.querySelector('.genie-icon');
    if (icon) {
        icon.classList.remove('pulsing');
        icon.classList.add(success ? 'completed' : 'error');
    }

    // Update title
    const title = genieState.cardElement.querySelector('.genie-title');
    if (title) {
        title.textContent = success ? 'Coordination Complete' : 'Coordination Failed';
    }

    // Update subtitle with summary
    const subtitle = genieState.cardElement.querySelector('.genie-subtitle');
    if (subtitle) {
        const duration = total_duration_ms ? `${(total_duration_ms / 1000).toFixed(1)}s` : '';
        const profileCount = profiles_used?.length || 0;

        if (success) {
            subtitle.textContent = `Consulted ${profileCount} expert${profileCount > 1 ? 's' : ''} in ${duration}`;
        } else {
            subtitle.textContent = 'An error occurred during coordination';
        }
    }

    // Hide synthesis spinner
    const synthesisEl = genieState.cardElement.querySelector('.genie-synthesis');
    if (synthesisEl) {
        synthesisEl.style.display = 'none';
    }

    // Add completion class to card
    genieState.cardElement.classList.add(success ? 'completed' : 'error');

    // Clear active coordination state (but keep card reference for now)
    genieState.activeCoordination = null;

    // IMPORTANT: Clear cardElement so next turn creates a fresh card
    // Without this, follow-up questions would try to update the old completed card
    genieState.cardElement = null;
    genieState.slaveProgress = {};

    console.log('[GenieHandler] Coordination completed', { success, duration: total_duration_ms, profiles: profiles_used });
}

// ============================================================================
// Split View Integration
// ============================================================================

/**
 * Open split view with slave session.
 * Dispatches event for splitViewHandler to handle.
 */
function openSplitView(sessionId, profileTag) {
    console.log('[GenieHandler] Opening split view for', profileTag, sessionId);

    window.dispatchEvent(new CustomEvent('openGenieSplitView', {
        detail: { sessionId, profileTag }
    }));
}

// ============================================================================
// Cleanup
// ============================================================================

/**
 * Clean up coordination state.
 */
function cleanupCoordination() {
    if (genieState.timerAnimationFrame) {
        cancelAnimationFrame(genieState.timerAnimationFrame);
        genieState.timerAnimationFrame = null;
    }

    genieState.activeCoordination = null;
    genieState.cardElement = null;
    genieState.slaveProgress = {};
    genieState.startTime = null;
}

// ============================================================================
// Main Event Handler
// ============================================================================

/**
 * Handle all genie coordination events.
 * Called from notifications.js when genie events are received.
 */
export function handleGenieEvent(eventType, payload) {
    console.log('[GenieHandler] Received event:', eventType, payload);

    switch (eventType) {
        // genie_start comes from execution_service before genie_coordination_start
        // It has slave_profiles info we need for card initialization
        case 'genie_start':
            // Pre-initialize if we have slave_profiles, otherwise just log
            if (payload.slave_profiles && !genieState.activeCoordination) {
                initGenieCoordination({
                    ...payload,
                    genie_session_id: payload.session_id
                });
            }
            break;

        // genie_routing comes from execution_service with slave profile details
        case 'genie_routing':
            // If card not yet created, initialize with routing info
            if (!genieState.cardElement && payload.slave_profiles) {
                initGenieCoordination({
                    ...payload,
                    genie_session_id: payload.session_id
                });
            }
            break;

        case 'genie_coordination_start':
            // Only init if not already initialized by genie_start/genie_routing
            if (!genieState.cardElement) {
                initGenieCoordination(payload);
            }
            break;

        case 'genie_routing_decision':
            showRoutingDecision(payload);
            break;

        case 'genie_slave_invoked':
            updateSlaveInvoked(payload);
            break;

        case 'genie_slave_progress':
            updateSlaveProgress(payload);
            break;

        case 'genie_slave_completed':
            updateSlaveCompleted(payload);
            break;

        case 'genie_synthesis_start':
            showSynthesis(payload);
            break;

        case 'genie_coordination_complete':
            completeCoordination(payload);
            break;

        default:
            console.warn('[GenieHandler] Unknown event type:', eventType);
    }
}

/**
 * Check if there's an active Genie coordination.
 */
export function hasActiveCoordination() {
    return genieState.activeCoordination !== null;
}

/**
 * Get current coordination state (for debugging/status display).
 */
export function getCoordinationState() {
    return {
        active: genieState.activeCoordination !== null,
        sessionId: genieState.activeCoordination,
        slaveProgress: { ...genieState.slaveProgress },
        elapsedMs: genieState.startTime ? Date.now() - genieState.startTime : 0
    };
}

// ============================================================================
// Historical Card Rendering (for session load)
// ============================================================================

/**
 * Create a completed genie coordination card for historical display.
 * Used when loading a session to show past coordination results.
 *
 * NOTE: This card is NOT included in session context to avoid bloat.
 * It's purely a UI element rendered on the fly.
 *
 * @param {Object} turnData - Turn data from workflow_history
 * @param {number} turnId - Turn number
 * @returns {HTMLElement} - The completed card element
 */
export function createHistoricalGenieCard(turnData, turnId) {
    const card = document.createElement('div');
    card.className = 'genie-coordination-card message-bubble glass-panel completed';
    card.id = `genie-card-historical-${turnId}`;
    card.dataset.turnId = turnId;

    const success = turnData.success !== false;
    const toolsUsed = turnData.tools_used || [];
    const profileTag = turnData.profile_tag || 'GENIE';

    // Build slave cards from tools_used (format: invoke_TAG)
    const slaveProfiles = toolsUsed.map(tool => {
        const tag = tool.replace('invoke_', '');
        return { tag, name: '' };
    });

    const slaveCardsHtml = slaveProfiles.length > 0
        ? slaveProfiles.map(p => `
            <div class="genie-slave-card completed" data-tag="${p.tag}">
                <div class="slave-status-indicator completed"></div>
                <div class="slave-info">
                    <span class="slave-tag">@${p.tag}</span>
                </div>
                <div class="slave-progress-bar">
                    <div class="progress-fill" style="width: 100%"></div>
                </div>
                <div class="slave-status-text">Done</div>
            </div>
        `).join('')
        : '<div class="text-xs text-gray-400 italic">Direct response (no profiles invoked)</div>';

    card.innerHTML = `
        <div class="genie-card-header">
            <div class="genie-icon-wrapper">
                <div class="genie-icon ${success ? 'completed' : 'error'}">G</div>
            </div>
            <div class="genie-header-content">
                <h4 class="genie-title">${success ? 'Coordination Complete' : 'Coordination Failed'}</h4>
                <p class="genie-subtitle">@${profileTag} - Turn ${turnId}</p>
            </div>
        </div>
        <div class="genie-slaves-grid">
            ${slaveCardsHtml}
        </div>
    `;

    // Add click handler to show turn details in status panel
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => {
        // Dispatch event to trigger plan reload for this turn
        const event = new CustomEvent('genieCardClick', {
            detail: { turnId, turnData }
        });
        window.dispatchEvent(event);
    });

    return card;
}
