/**
 * state.js
 * * This module manages the application's global state.
 * Centralizing state variables ensures a single source of truth and simplifies state management.
 */

export const state = {
    userUUID: null, // Extracted from JWT for SSE notifications
    showWelcomeScreenAtStartup: true,
    simpleChatHistory: [],
    currentProvider: 'Google',
    currentModel: '',
    currentStatusId: 0,
    currentSessionId: null,
    currentTaskId: null, // Add this line
    currentTurnNumber: null, // Turn number for current execution (from execution_start event)
    resourceData: { tools: {}, prompts: {}, resources: {}, charts: {} },
    currentlySelectedResource: null,
    activeGenieProfile: null, // Store Genie profile info when @GENIE override is active
    activeRagProfile: null, // Store RAG-focused profile info when active
    activeLlmOnlyProfile: null, // Store LLM-only profile info when active
    currentResourcePanelProfileId: null, // Profile ID whose resources are displayed in resource panel (for prompt invocations)
    eventSource: null,
    countdownValue: 5,
    mouseMoveHandler: null,
    pristineConfig: {},
    isMouseOverStatus: false,
    isInFastPath: false,
    mcpIndicatorTimeout: null,
    llmIndicatorTimeout: null,
    contextIndicatorTimeout: null,
    isTempLastTurnMode: false,
    isLastTurnModeLocked: false,
    isTempVoiceMode: false,
    isVoiceModeLocked: false,
    defaultPromptsCache: {},
    currentPhaseContainerEl: null,
    appConfig: {},
    // --- TTS conversation flow state ---
    ttsState: 'IDLE', // Can be 'IDLE', 'AWAITING_OBSERVATION_CONFIRMATION'
    ttsObservationBuffer: '', // Stores key observations while waiting for user confirmation
    currentTTSAudio: null, // Reference to currently playing Audio object (for cancellation)
    ttsCancelled: false, // Flag checked between TTS steps to abort the flow
    // --- MODIFICATION START: Add state for key observations mode ---
    keyObservationsMode: 'autoplay-off', // 'autoplay-off', 'autoplay-on', 'off'
    // --- MODIFICATION END ---
    // --- MODIFICATION START: Add state for tooltip visibility ---
    showTooltips: true,
    // --- MODIFICATION END ---
    // --- MODIFICATION START: Add state for pending sub-task planning events ---
    pendingSubtaskPlanningEvents: [],
    // --- MODIFICATION END ---
    phaseContainerStack: [],
    isRestTaskActive: false,
    // --- MODIFICATION START: Add flag to prevent indicator blinks during historical turn viewing ---
    isViewingHistoricalTurn: false,
    // --- MODIFICATION END ---
    activeRestTaskId: null,
    lastRagCaseData: null, // Stores the last retrieved RAG case for display
    // --- MODIFICATION START: RAG Collection Inspection ---
    currentInspectedCollectionId: null,
    currentInspectedCollectionName: null,
    currentSelectedCaseId: null, // Tracks the currently selected case row for highlighting
    ragCollectionRowsCache: {}, // keyed by collection ID for last fetched sample
    ragCollectionSearchTerm: '',
    ragCollectionSortKey: 'timestamp', // Default sort column
    ragCollectionSortDirection: 'desc', // 'asc' or 'desc'
    // --- MODIFICATION END ---
    // --- MODIFICATION START: Case Trace Rendering Controls ---
    showSystemLogsInCaseTrace: false, // Toggle for system log visibility in Selected Case Details
    collapseDuplicateTraceEntries: true, // Collapse consecutive identical tool entries
    currentCaseTrace: [], // Raw trace for current selected case
    // --- MODIFICATION END ---
    // --- MODIFICATION START: Feedback Voting ---
    feedbackByTurn: {}, // turnId -> 'up' | 'down' | null
    // --- MODIFICATION END ---
    // --- MODIFICATION START: Session Load Tracking ---
    sessionLoaded: false, // Tracks if session history is loaded in UI (vs just ID in state)
    // --- MODIFICATION END ---
    // --- Execution State Tracking ---
    isConversationAgentActive: false, // Tracks if conversation agent is executing
    isGenieCoordinationActive: false, // Tracks if genie coordination is executing
    pendingKnowledgeRetrievalEvent: null, // Stores knowledge retrieval event for conversation_with_tools
    // --- Session stream isolation ---
    activeStreamSessions: new Set(), // Session IDs with running /ask_stream processStream loops
    sessionUiCache: {},              // sessionId -> { chatHTML, statusHTML, tokenData } saved on switch-away
    restEventBuffer: {},             // session_id -> { taskId, events: [], isComplete: false } for REST task replay
    activeRestSessions: new Set(),   // Session IDs with active REST execution (e.g., Genie child sessions)
};

// Functions to modify state can be added here if needed, e.g.:
export function setCurrentSessionId(id) {
    state.currentSessionId = id;
}

export function setResourceData(type, data) {
    state.resourceData[type] = data;
}

export function resetCurrentStatusId() {
    state.currentStatusId = 0;
}

export function incrementCurrentStatusId() {
    state.currentStatusId++;
}

