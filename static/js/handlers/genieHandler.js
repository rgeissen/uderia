/**
 * handlers/genieHandler.js
 *
 * Handles Genie coordination state tracking for Live Status window updates.
 *
 * ARCHITECTURE NOTE (World-Class UX Decision):
 * Coordination details are shown ONLY in the Live Status window, not inline in chat.
 * This keeps the conversation pane clean and focused on Q&A, while the status panel
 * shows the "how" (coordination details, timing, slave invocations).
 *
 * This module:
 * - Tracks Genie coordination execution state
 * - Provides state for Live Status window rendering (handled by ui.js)
 * - NO inline cards in chat - all visualization in status panel
 *
 * The actual rendering is done by ui.js:_renderGenieStep()
 */

import { state } from '../state.js';
import * as UI from '../ui.js';

// ============================================================================
// Genie Coordination State
// ============================================================================

export const genieState = {
    activeCoordination: null,  // Current coordination session ID
    slaveProgress: {},         // {profile_tag: {status, name, id, sessionId, startTime, duration}}
    startTime: null,           // Timestamp when coordination started
    availableProfiles: [],     // Profiles available for this coordination
    profilesInvoked: [],       // Profiles that have been invoked
    profileTag: null           // Profile tag for this coordination (GENIE)
};

// ============================================================================
// State Management Functions
// ============================================================================

/**
 * Initialize Genie coordination state.
 * Called when genie_start or genie_coordination_start event is received.
 */
export function initGenieCoordination(payload) {
    const { genie_session_id, session_id, slave_profiles } = payload;

    const effectiveSessionId = genie_session_id || session_id;

    // Only track for current session
    if (session_id && session_id !== state.currentSessionId) {
        console.log('[GenieHandler] Ignoring event for different session');
        return;
    }

    // Clear any existing coordination state
    if (genieState.activeCoordination) {
        console.warn('[GenieHandler] New coordination started while previous still active');
        cleanupCoordination();
    }

    // Initialize state
    genieState.activeCoordination = effectiveSessionId;
    genieState.slaveProgress = {};
    genieState.startTime = Date.now();
    genieState.availableProfiles = slave_profiles || [];
    genieState.profilesInvoked = [];
    genieState.profileTag = 'GENIE';

    // Initialize progress tracking for each slave profile
    (slave_profiles || []).forEach(p => {
        genieState.slaveProgress[p.tag] = {
            status: 'pending',
            name: p.name || '',
            id: p.id
        };
    });

    // Mark genie coordination as active in global state
    state.isGenieCoordinationActive = true;

    // Auto-expand slave sessions during execution for visibility
    setTimeout(() => {
        const collapseState = UI.getGenieCollapseState();
        if (collapseState[effectiveSessionId]) {
            // Sessions are currently collapsed - expand them
            UI.toggleGenieSlaveVisibility(effectiveSessionId);

            // Add visual feedback - brief highlight on parent session
            const parentItem = document.getElementById(`session-${effectiveSessionId}`);
            if (parentItem) {
                parentItem.style.transition = 'box-shadow 0.3s ease';
                parentItem.style.boxShadow = '0 0 0 3px rgba(241, 95, 34, 0.3)';
                setTimeout(() => {
                    parentItem.style.boxShadow = '';
                }, 800);
            }

            console.log('[GenieHandler] 🔓 Auto-expanded slave sessions for execution visibility');
        }
    }, 100); // Small delay to ensure DOM is ready

    console.log('[GenieHandler] Coordination started with', (slave_profiles || []).length, 'available profiles');
}

/**
 * Track routing decision.
 * Called when genie_routing_decision event is received.
 */
export function updateRoutingDecision(payload) {
    if (!genieState.activeCoordination) return;

    const { decision_text, selected_profiles } = payload;

    // Store selected profiles for reference
    genieState.selectedProfiles = selected_profiles || [];

    console.log('[GenieHandler] Routing decision:', decision_text);
}

/**
 * Track slave invocation.
 * Called when genie_slave_invoked event is received.
 */
export function updateSlaveInvoked(payload) {
    if (!genieState.activeCoordination) return;

    const { profile_tag, slave_session_id, profile_id, query } = payload;

    // Update or create progress entry
    if (!genieState.slaveProgress[profile_tag]) {
        genieState.slaveProgress[profile_tag] = {
            status: 'active',
            id: profile_id,
            sessionId: slave_session_id,
            startTime: Date.now(),
            query: query || ''  // Store the query sent to the slave
        };
    } else {
        genieState.slaveProgress[profile_tag].status = 'active';
        genieState.slaveProgress[profile_tag].sessionId = slave_session_id;
        genieState.slaveProgress[profile_tag].startTime = Date.now();
        genieState.slaveProgress[profile_tag].query = query || '';  // Store the query
    }

    // Add to invoked list if not already there
    if (!genieState.profilesInvoked.includes(profile_tag)) {
        genieState.profilesInvoked.push(profile_tag);
    }

    console.log('[GenieHandler] Slave invoked:', profile_tag, 'with query:', query?.slice(0, 50) + '...');
}

/**
 * Track slave progress.
 * Called when genie_slave_progress event is received.
 */
export function updateSlaveProgress(payload) {
    if (!genieState.activeCoordination) return;

    const { profile_tag, status, message, progress_pct } = payload;

    if (genieState.slaveProgress[profile_tag]) {
        genieState.slaveProgress[profile_tag].message = message;
        genieState.slaveProgress[profile_tag].progress_pct = progress_pct;
    }

    console.log('[GenieHandler] Slave progress:', profile_tag, message);
}

/**
 * Track slave completion.
 * Called when genie_slave_completed event is received.
 */
export function updateSlaveCompleted(payload) {
    if (!genieState.activeCoordination) return;

    const { profile_tag, result, result_preview, duration_ms, success, error } = payload;

    if (genieState.slaveProgress[profile_tag]) {
        genieState.slaveProgress[profile_tag].status = success ? 'completed' : 'error';
        genieState.slaveProgress[profile_tag].duration = duration_ms;
        // Store full result if available, otherwise use preview
        genieState.slaveProgress[profile_tag].result = result || result_preview;
        genieState.slaveProgress[profile_tag].error = error;
    }

    console.log('[GenieHandler] Slave completed:', profile_tag, success ? 'success' : 'failed');
}

/**
 * Track synthesis start.
 * Called when genie_synthesis_start event is received.
 */
export function updateSynthesisStart(payload) {
    if (!genieState.activeCoordination) return;

    genieState.synthesisStarted = true;
    genieState.profilesConsulted = payload.profiles_consulted || [];

    console.log('[GenieHandler] Synthesis started with', genieState.profilesConsulted.length, 'profiles');
}

/**
 * Complete coordination and clean up state.
 * Called when genie_coordination_complete event is received.
 */
export function completeCoordination(payload) {
    const { total_duration_ms, profiles_used, success, error } = payload;

    console.log('[GenieHandler] Coordination completed', {
        success,
        duration: total_duration_ms,
        profiles: profiles_used
    });

    // Store the session ID before cleanup
    const completedSessionId = genieState.activeCoordination;

    // IMPORTANT: Don't set state.isGenieCoordinationActive = false here!
    // The UI (ui.js:_renderGenieStep) will handle this AFTER rendering the final event.
    // Setting it to false here causes ui.js:updateStatusWindow to reset the status window
    // and clear all previous events before rendering the completion event.

    // Keep slave sessions expanded after execution - user can collapse manually if desired
    if (completedSessionId) {
        // Ensure slaves remain visible after completion by explicitly setting expanded state
        const collapseState = UI.getGenieCollapseState();
        collapseState[completedSessionId] = false; // false = expanded (visible)
        localStorage.setItem('genie_slave_collapse_state', JSON.stringify(collapseState));
        console.log('[GenieHandler] 🔓 Keeping slave sessions expanded after execution');

        // Visual feedback on completion (brief green highlight on parent session)
        const parentItem = document.getElementById(`session-${completedSessionId}`);
        if (parentItem) {
            parentItem.style.transition = 'box-shadow 0.3s ease';
            parentItem.style.boxShadow = '0 0 0 3px rgba(34, 197, 94, 0.3)'; // Green for completion
            setTimeout(() => {
                parentItem.style.boxShadow = '';
            }, 800);
        }
    }

    // Clear state
    cleanupCoordination();
}

/**
 * Clean up coordination state.
 */
function cleanupCoordination() {
    genieState.activeCoordination = null;
    genieState.slaveProgress = {};
    genieState.startTime = null;
    genieState.availableProfiles = [];
    genieState.profilesInvoked = [];
    genieState.profileTag = null;
    genieState.selectedProfiles = [];
    genieState.synthesisStarted = false;
    genieState.profilesConsulted = [];
}

// ============================================================================
// Historical Card Rendering - DISABLED
// ============================================================================

/**
 * Create a historical card for session reload.
 *
 * NOTE: This function is DEPRECATED. Genie coordination details are now shown
 * only in the Live Status window, not as inline cards in the chat.
 *
 * This stub is kept for backwards compatibility but returns null.
 * Session reload will no longer render inline genie cards.
 */
export function createHistoricalGenieCard(turnData, turnId) {
    // DISABLED: No longer rendering inline cards in chat
    // Coordination history is available in the Live Status window when clicking on a turn
    console.log('[GenieHandler] Historical card rendering disabled - use Live Status panel');
    return null;
}

// ============================================================================
// Split View Integration (Preserved for slave session viewing)
// ============================================================================

/**
 * Open split view with slave session.
 * Dispatches event for splitViewHandler to handle.
 */
export function openGenieSplitView(sessionId, profileTag) {
    console.log('[GenieHandler] Opening split view for', profileTag, sessionId);

    window.dispatchEvent(new CustomEvent('openGenieSplitView', {
        detail: { sessionId, profileTag }
    }));
}

// ============================================================================
// Main Event Handler
// ============================================================================

/**
 * Handle all genie coordination events.
 * Called from notifications.js when genie events are received.
 *
 * NOTE: This handler now only updates internal state.
 * Visual rendering is handled by ui.js:_renderGenieStep() in the Live Status window.
 */
export function handleGenieEvent(eventType, payload) {
    console.log('[GenieHandler] Received event:', eventType);

    switch (eventType) {
        // genie_start comes from execution_service before genie_coordination_start
        case 'genie_start':
            if (payload.slave_profiles && !genieState.activeCoordination) {
                initGenieCoordination({
                    ...payload,
                    genie_session_id: payload.session_id
                });
            }
            break;

        // genie_routing comes from execution_service with slave profile details
        case 'genie_routing':
            if (!genieState.activeCoordination && payload.slave_profiles) {
                initGenieCoordination({
                    ...payload,
                    genie_session_id: payload.session_id
                });
            }
            break;

        case 'genie_coordination_start':
            if (!genieState.activeCoordination) {
                initGenieCoordination(payload);
            }
            break;

        case 'genie_llm_step':
            // LLM step events are purely informational for the Live Status window
            // No state tracking needed - handled by ui.js:_renderGenieStep()
            break;

        case 'genie_routing_decision':
            updateRoutingDecision(payload);
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
            updateSynthesisStart(payload);
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
        elapsedMs: genieState.startTime ? Date.now() - genieState.startTime : 0,
        profilesInvoked: [...genieState.profilesInvoked]
    };
}
