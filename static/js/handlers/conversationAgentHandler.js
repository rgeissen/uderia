/**
 * handlers/conversationAgentHandler.js
 *
 * Handles Conversation Agent state tracking for Live Status window updates.
 *
 * ARCHITECTURE NOTE (World-Class UX Decision):
 * Tool execution details are shown ONLY in the Live Status window, not inline in chat.
 * This keeps the conversation pane clean and focused on Q&A, while the status panel
 * shows the "how" (execution details, timing, tool calls).
 *
 * This module:
 * - Tracks conversation agent execution state
 * - Provides state for Live Status window rendering (handled by ui.js)
 * - NO inline cards in chat - all visualization in status panel
 *
 * The actual rendering is done by ui.js:_renderConversationAgentStep()
 */

import { state } from '../state.js';

// ============================================================================
// Conversation Agent State
// ============================================================================

export const conversationAgentState = {
    activeExecution: null,      // Current execution session ID
    toolProgress: {},           // {tool_name: {status, startTime, duration, result}}
    startTime: null,            // Timestamp when execution started
    availableTools: [],         // Tools available for this execution
    toolsUsed: [],              // Tools that have been invoked
    profileTag: null            // Profile tag for this execution
};

// ============================================================================
// State Management Functions
// ============================================================================

/**
 * Initialize conversation agent execution state.
 * Called when conversation_agent_start event is received.
 */
export function initConversationAgentCard(payload) {
    const { session_id, profile_tag, available_tools } = payload;

    // Only track for current session
    if (session_id && session_id !== state.currentSessionId) {
        console.log('[ConversationAgentHandler] Ignoring event for different session');
        return;
    }

    // Clear any existing execution state
    if (conversationAgentState.activeExecution) {
        console.warn('[ConversationAgentHandler] New execution started while previous still active');
        cleanupExecution();
    }

    // Initialize state
    conversationAgentState.activeExecution = session_id;
    conversationAgentState.toolProgress = {};
    conversationAgentState.startTime = Date.now();
    conversationAgentState.availableTools = available_tools || [];
    conversationAgentState.toolsUsed = [];
    conversationAgentState.profileTag = profile_tag;

    // Mark conversation agent as active in global state
    state.isConversationAgentActive = true;

    console.log('[ConversationAgentHandler] Execution started with', (available_tools || []).length, 'available tools');
}

/**
 * Track tool invocation.
 * Called when conversation_tool_invoked event is received.
 */
export function updateToolInvoked(payload) {
    if (!conversationAgentState.activeExecution) return;

    const { tool_name, arguments: toolArgs } = payload;

    // Track tool state
    conversationAgentState.toolProgress[tool_name] = {
        status: 'active',
        startTime: Date.now(),
        arguments: toolArgs
    };

    // Add to tools used list if not already there
    if (!conversationAgentState.toolsUsed.includes(tool_name)) {
        conversationAgentState.toolsUsed.push(tool_name);
    }

    console.log('[ConversationAgentHandler] Tool invoked:', tool_name);
}

/**
 * Track tool completion.
 * Called when conversation_tool_completed event is received.
 */
export function updateToolCompleted(payload) {
    if (!conversationAgentState.activeExecution) return;

    const { tool_name, result_preview, duration_ms, success, error } = payload;

    // Update tool state
    if (conversationAgentState.toolProgress[tool_name]) {
        conversationAgentState.toolProgress[tool_name].status = success ? 'completed' : 'error';
        conversationAgentState.toolProgress[tool_name].duration = duration_ms;
        conversationAgentState.toolProgress[tool_name].result = result_preview;
        conversationAgentState.toolProgress[tool_name].error = error;
    }

    console.log('[ConversationAgentHandler] Tool completed:', tool_name, success ? 'success' : 'failed');
}

/**
 * Complete execution and clean up state.
 * Called when conversation_agent_complete event is received.
 */
export function completeAgentExecution(payload) {
    const { total_duration_ms, tools_used, success, error } = payload;

    console.log('[ConversationAgentHandler] Execution completed', {
        success,
        duration: total_duration_ms,
        tools: tools_used
    });

    // Mark conversation agent as inactive
    state.isConversationAgentActive = false;

    // Clear pending knowledge retrieval event
    state.pendingKnowledgeRetrievalEvent = null;

    // Clear state
    cleanupExecution();
}

/**
 * Clean up execution state.
 */
function cleanupExecution() {
    conversationAgentState.activeExecution = null;
    conversationAgentState.toolProgress = {};
    conversationAgentState.startTime = null;
    conversationAgentState.availableTools = [];
    conversationAgentState.toolsUsed = [];
    conversationAgentState.profileTag = null;
}

// ============================================================================
// Historical Card Rendering - DISABLED
// ============================================================================

/**
 * Create a historical card for session reload.
 *
 * NOTE: This function is DEPRECATED. Tool execution details are now shown
 * only in the Live Status window, not as inline cards in the chat.
 *
 * This stub is kept for backwards compatibility but returns null.
 * Session reload will no longer render inline tool cards.
 */
export function createHistoricalAgentCard(turnData, turnId) {
    // DISABLED: No longer rendering inline cards in chat
    // Tool execution history is available in the Live Status window when clicking on a turn
    console.log('[ConversationAgentHandler] Historical card rendering disabled - use Live Status panel');
    return null;
}

// ============================================================================
// Main Event Handler
// ============================================================================

/**
 * Handle all conversation agent events.
 * Called from notifications.js when conversation agent events are received.
 *
 * NOTE: This handler now only updates internal state.
 * Visual rendering is handled by ui.js:_renderConversationAgentStep() in the Live Status window.
 */
export function handleConversationAgentEvent(eventType, payload) {
    console.log('[ConversationAgentHandler] Received event:', eventType);

    switch (eventType) {
        case 'conversation_agent_start':
            initConversationAgentCard(payload);
            break;

        case 'conversation_tool_invoked':
            updateToolInvoked(payload);
            break;

        case 'conversation_tool_completed':
            updateToolCompleted(payload);
            break;

        case 'conversation_agent_complete':
            completeAgentExecution(payload);
            break;

        case 'conversation_llm_step':
            // LLM step events are handled by ui.js for Live Status rendering
            // No additional state tracking needed here
            break;

        default:
            console.warn('[ConversationAgentHandler] Unknown event type:', eventType);
    }
}
