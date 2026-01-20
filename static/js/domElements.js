/**
 * domElements.js
 * * This module centralizes all DOM element selections for the application.
 * Consolidating DOM queries here makes it easier to manage and locate UI element references.
 */

// --- MODIFICATION START: Add top-level application wrappers ---
export const unconfiguredWrapper = document.getElementById('unconfigured-wrapper');
export const configuredWrapper = document.getElementById('configured-wrapper');
// --- MODIFICATION END ---

// --- MODIFICATION START: App View Management (v4 Structure) ---
export const appSideNav = document.getElementById('app-side-nav');
export const appMenuToggle = document.getElementById('app-menu-toggle');
export const appContentArea = document.getElementById('main-content-area');
export const appViewContainer = document.getElementById('app-view-container');
export const conversationView = document.getElementById('conversation-view');
export const ragMaintenanceView = document.getElementById('rag-maintenance-view');
// NEW: RAG Marketplace view element
export const ragMarketplaceView = document.getElementById('rag-marketplace-view');
// NEW: Intelligence collections container
export const ragMaintenanceCollectionsContainer = document.getElementById('rag-maintenance-collections-container');
export const ragMaintenanceEmptyHint = document.getElementById('rag-maintenance-empty-hint');
// Repository tabs and containers
export const plannerRepoTab = document.getElementById('planner-repo-tab');
export const knowledgeRepoTab = document.getElementById('knowledge-repo-tab');
export const plannerRepoContent = document.getElementById('planner-repo-content');
export const knowledgeRepoContent = document.getElementById('knowledge-repo-content');
export const knowledgeRepositoriesContainer = document.getElementById('knowledge-repositories-container');
// NEW: RAG Collection Inspection view elements
export const ragCollectionInspectView = document.getElementById('rag-collection-inspect-view');
export const ragCollectionInspectBack = document.getElementById('rag-collection-inspect-back');
export const ragCollectionInspectTitle = document.getElementById('rag-collection-inspect-title');
export const ragCollectionSearchInput = document.getElementById('rag-collection-search-input');
export const ragCollectionRefreshButton = document.getElementById('rag-collection-refresh');
export const ragCollectionLoading = document.getElementById('rag-collection-loading');
export const ragCollectionTableBody = document.getElementById('rag-collection-table-body');
export const ragCollectionFooter = document.getElementById('rag-collection-footer');
export const ragSelectedCaseDetails = document.getElementById('rag-selected-case-details');
export const ragSelectedCaseMetadata = document.getElementById('rag-selected-case-metadata');
export const ragSelectedCasePlan = document.getElementById('rag-selected-case-plan');
export const ragSelectedCaseTrace = document.getElementById('rag-selected-case-trace');
export const ragSelectedCaseSeparator = document.getElementById('rag-selected-case-separator');
export const conversationHeader = document.getElementById('conversation-header');
export const conversationPanels = document.getElementById('conversation-panels');
// This selects all view-switching buttons in the side nav
export const viewSwitchButtons = document.querySelectorAll('.view-switch-button');
// --- MODIFICATION END ---

// Chat interface elements
export const chatLog = document.getElementById('chat-log');
export const chatForm = document.getElementById('chat-form');
export const userInput = document.getElementById('user-input');
export const submitButton = document.getElementById('submit-button');
export const sendIcon = document.getElementById('send-icon');
export const loadingSpinner = document.getElementById('loading-spinner');
export const newChatButton = document.getElementById('new-chat-button');
export const voiceInputButton = document.getElementById('voice-input-button');
export const micIcon = document.getElementById('mic-icon');
export const keyObservationsToggleButton = document.getElementById('key-observations-toggle-button');
export const observationsAutoplayOffIcon = document.getElementById('observations-autoplay-off-icon');
export const observationsAutoplayOnIcon = document.getElementById('observations-autoplay-on-icon');
export const observationsOffIcon = document.getElementById('observations-off-icon');
export const thinkingIndicator = document.getElementById('thinking-indicator');
export const promptNameDisplay = document.getElementById('prompt-name-display');
export const inputHint = document.getElementById('input-hint');

// Resource tabs
export const resourceTabs = document.getElementById('resource-tabs');

// Prompt Modal elements
export const promptModalOverlay = document.getElementById('prompt-modal-overlay');
export const promptModalContent = document.getElementById('prompt-modal-content');
export const promptModalForm = document.getElementById('prompt-modal-form');
export const promptModalTitle = document.getElementById('prompt-modal-title');
export const promptModalInputs = document.getElementById('prompt-modal-inputs');
export const promptModalClose = document.getElementById('prompt-modal-close');

// Main content area (within Conversation view)
export const mainContent = document.getElementById('main-content');

// Status window elements
export const statusWindow = document.getElementById('status-window');
export const statusWindowContent = document.getElementById('status-window-content');
export const statusTitle = document.getElementById('status-title');
export const toggleStatusButton = document.getElementById('toggle-status-button');
export const statusCollapseIcon = document.getElementById('status-collapse-icon');
export const statusExpandIcon = document.getElementById('status-expand-icon');
export const toggleStatusCheckbox = document.getElementById('toggle-status-checkbox');
export const stopExecutionButton = document.getElementById('stop-execution-button');
export const headerReplayPlannedButton = document.getElementById('header-replay-planned-button');
export const headerReplayOptimizedButton = document.getElementById('header-replay-optimized-button');
export const headerReplayQueryButton = document.getElementById('header-replay-query-button');
export const taskIdDisplay = document.getElementById('task-id-display');
export const taskIdValue = document.getElementById('task-id-value');
export const copyTaskIdButton = document.getElementById('copy-task-id-button');

// Session history panel elements
export const sessionHistoryPanel = document.getElementById('session-history-panel');
export const sessionList = document.getElementById('session-list');
export const toggleHistoryButton = document.getElementById('toggle-history-button');
export const historyCollapseIcon = document.getElementById('history-collapse-icon');
export const historyExpandIcon = document.getElementById('history-expand-icon');
export const toggleHistoryCheckbox = document.getElementById('toggle-history-checkbox');
// Active session title elements (conversation header)
export const activeSessionTitle = document.getElementById('active-session-title');
export const activeSessionTitleEditingHint = document.getElementById('active-session-title-editing-hint');

// Header elements (within Conversation view)
export const toolHeader = document.getElementById('tool-header');
export const toggleHeaderButton = document.getElementById('toggle-header-button');
export const headerCollapseIcon = document.getElementById('header-collapse-icon');
export const headerExpandIcon = document.getElementById('header-expand-icon');
export const toggleHeaderCheckbox = document.getElementById('toggle-header-checkbox');

// Info Modal elements
export const infoModalOverlay = document.getElementById('info-modal-overlay');
export const infoModalClose = document.getElementById('info-modal-close');
export const infoModalContent = document.getElementById('info-modal-content');

// LLM Configuration elements
export const refreshModelsButton = document.getElementById('refresh-models-button');
export const refreshIcon = document.getElementById('refresh-icon');
export const refreshSpinner = document.getElementById('refresh-spinner');
export const llmProviderSelect = document.getElementById('llm-provider');
export const llmModelSelect = document.getElementById('llm-model');
export const llmApiKeyInput = document.getElementById('llm-api-key');
export const apiKeyContainer = document.getElementById('api-key-container');
export const awsCredentialsContainer = document.getElementById('aws-credentials-container');
export const awsAccessKeyIdInput = document.getElementById('aws-access-key-id');
export const awsSecretAccessKeyInput = document.getElementById('aws-secret-access-key');
export const awsRegionInput = document.getElementById('aws-region');
export const awsListingMethodContainer = document.getElementById('aws-listing-method-container');
export const ollamaHostContainer = document.getElementById('ollama-host-container');
export const ollamaHostInput = document.getElementById('ollama-host');
export const azureCredentialsContainer = document.getElementById('azure-credentials-container');
export const azureApiKeyInput = document.getElementById('azure-api-key');
export const azureEndpointInput = document.getElementById('azure-endpoint');
export const azureDeploymentNameInput = document.getElementById('azure-deployment-name');
export const azureApiVersionInput = document.getElementById('azure-api-version');
export const friendliCredentialsContainer = document.getElementById('friendli-credentials-container');
export const friendliTokenInput = document.getElementById('friendli-token');
export const friendliEndpointUrlInput = document.getElementById('friendli-endpoint-url');
export const chartingIntensitySelect = document.getElementById('charting-intensity');
export const ttsCredentialsJsonTextarea = document.getElementById('tts-credentials-json');


// Status indicators (now in conversation-header)
export const mcpStatusDot = document.getElementById('mcp-status-dot');
export const llmStatusDot = document.getElementById('llm-status-dot');
export const sseStatusDot = document.getElementById('sse-status-dot');
export const contextStatusDot = document.getElementById('context-status-dot');
export const ccrStatusDot = document.getElementById('ccr-status-dot');

// Window menu
export const windowMenuButton = document.getElementById('window-menu-button');
export const windowDropdownMenu = document.getElementById('window-dropdown-menu');

// Prompt Editor elements
export const promptEditorButton = document.getElementById('prompt-editor-button');
export const promptEditorOverlay = document.getElementById('prompt-editor-overlay');
export const promptEditorContent = document.getElementById('prompt-editor-content');
export const promptEditorTitle = document.getElementById('prompt-editor-title');
export const promptEditorTextarea = document.getElementById('prompt-editor-textarea');
export const promptEditorSave = document.getElementById('prompt-editor-save');
export const promptEditorReset = document.getElementById('prompt-editor-reset');
export const promptEditorClose = document.getElementById('prompt-editor-close');
export const promptEditorStatus = document.getElementById('prompt-editor-status');

// Confirmation Modal elements
export const confirmModalOverlay = document.getElementById('confirm-modal-overlay');
export const confirmModalContent = document.getElementById('confirm-modal-content');
export const confirmModalTitle = document.getElementById('confirm-modal-title');
export const confirmModalBody = document.getElementById('confirm-modal-body');
export const confirmModalConfirm = document.getElementById('confirm-modal-confirm');
export const confirmModalCancel = document.getElementById('confirm-modal-cancel');

// Simple Chat Modal elements
export const chatModalButton = document.getElementById('chat-modal-button');
export const chatModalOverlay = document.getElementById('chat-modal-overlay');
export const chatModalContent = document.getElementById('chat-modal-content');
export const chatModalClose = document.getElementById('chat-modal-close');
export const chatModalForm = document.getElementById('chat-modal-form');
export const chatModalInput = document.getElementById('chat-modal-input');
export const chatModalLog = document.getElementById('chat-modal-log');

// View Prompt Modal elements
export const viewPromptModalOverlay = document.getElementById('view-prompt-modal-overlay');
export const viewPromptModalContent = document.getElementById('view-prompt-modal-content');
export const viewPromptModalTitle = document.getElementById('view-prompt-modal-title');
export const viewPromptModalText = document.getElementById('view-prompt-modal-text');
export const viewPromptModalClose = document.getElementById('view-prompt-modal-close');

// RAG Case Modal elements
export const ragCaseModalOverlay = document.getElementById('rag-case-modal-overlay');
export const ragCaseModalContent = document.getElementById('rag-case-modal-content');
export const ragCaseModalTitle = document.getElementById('rag-case-modal-title');
export const ragCaseIdDisplay = document.getElementById('rag-case-id-display');
export const ragCaseModalJson = document.getElementById('rag-case-modal-json');
export const ragCaseModalCopy = document.getElementById('rag-case-modal-copy');
export const ragCaseModalClose = document.getElementById('rag-case-modal-close');
export const ragCaseModalCloseBottom = document.getElementById('rag-case-modal-close-bottom');