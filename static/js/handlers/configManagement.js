/**
 * handlers/configManagement.js
 * * This module handles all logic related to the Configuration modal
 * and the System Prompt Editor.
 * NOTE: Many functions reference old config form DOM elements that may not exist.
 * Null checks are added to prevent errors with the new configuration system.
 */

import * as DOM from '../domElements.js';
import * as API from '../api.js';
import * as UI from '../ui.js';
import { state } from '../state.js';
import { safeSetItem, safeGetItem } from '../storageUtils.js';
import * as Utils from '../utils.js';
import { handleLoadSession, handleStartNewSession } from './sessionManagement.js?v=3.2';
// We need to import from eventHandlers for functions not yet moved
import { handleLoadResources } from '../eventHandlers.js?v=3.2';
// Note: openSystemPromptPopup is deprecated - welcome screen is now the unified interface
import { handleViewSwitch, updateGenieMasterBadges, sortSessionsHierarchically } from '../ui.js';

/**
 * Helper to safely set config status message (old form element may not exist)
 */
function setConfigStatus(message, className = 'text-sm text-gray-400 text-center') {
    if (DOM.configStatus) {
        DOM.configStatus.textContent = message;
        DOM.configStatus.className = className;
    }
}

/**
 * Gets the current core configuration from the form.
 * @returns {object} The configuration object.
 */
function getCurrentCoreConfig() {
    // Old config form no longer exists - return empty object
    if (!DOM.configForm) {
        return {};
    }
    const formData = new FormData(DOM.configForm);
    return Object.fromEntries(formData.entries());
}

/**
 * Finalizes the application configuration after a successful connection.
 * Loads resources, sessions, and sets UI state.
 * @param {object} config - The configuration object from the form.
 */
export async function finalizeConfiguration(config, switchToConversationView = true) {
    // Update old config form status elements if they exist
    setConfigStatus('Success! MCP & LLM services connected.', 'text-sm text-green-400 text-center');
    DOM.mcpStatusDot.classList.remove('disconnected');
    DOM.mcpStatusDot.classList.add('connected');
    DOM.llmStatusDot.classList.remove('disconnected', 'busy');
    DOM.llmStatusDot.classList.add('idle'); // Start as idle
    DOM.contextStatusDot.classList.remove('disconnected');
    DOM.contextStatusDot.classList.add('idle');
    
    // Update CCR (Champion Case Retrieval) indicator - check if active after configuration
    if (DOM.ccrStatusDot) {
        // Fetch fresh status after configuration to check if planner collections are loaded
        const status = await API.checkServerStatus();
        if (status.rag_active) {
            DOM.ccrStatusDot.classList.remove('disconnected');
            DOM.ccrStatusDot.classList.add('connected');
        } else {
            DOM.ccrStatusDot.classList.remove('connected');
            DOM.ccrStatusDot.classList.add('disconnected');
        }
    }
    
    // Show conversation header after successful configuration
    const conversationHeader = document.getElementById('conversation-header');
    if (conversationHeader) {
        conversationHeader.classList.remove('hidden');
    } else {
        console.error('Conversation header element not found!');
    }
    
    // Show panel toggle buttons container after configuration
    const topButtonsContainer = document.getElementById('top-buttons-container');
    if (topButtonsContainer) {
        topButtonsContainer.classList.remove('hidden');
    }

    safeSetItem('lastSelectedProvider', config.provider);

    state.currentProvider = config.provider;
    state.currentModel = config.model;

    UI.updateStatusPromptName(config.provider, config.model);

    // Panel initialization is now handled by initializePanels() in main.js
    // which uses admin window_defaults settings. No need for manual setup here.

    if (Utils.isPrivilegedUser()) {
        const activePrompt = Utils.getSystemPromptForModel(state.currentProvider, state.currentModel);
        // Only reset if we have a valid provider and model
        if (!activePrompt && state.currentProvider && state.currentModel) {
            await resetSystemPrompt(true);
        }
    }

    const promptEditorMenuItem = DOM.promptEditorButton.parentElement;
    if (Utils.isPrivilegedUser()) {
        promptEditorMenuItem.style.display = 'block';
        DOM.promptEditorButton.disabled = false;
    } else {
        promptEditorMenuItem.style.display = 'none';
        DOM.promptEditorButton.disabled = true;
    }

    // Load resources based on default profile type
    // For Genie and RAG profiles, use profile-specific resource panel
    // For other profiles, load generic MCP resources
    const defaultProfileId = window.configState?.defaultProfileId;
    if (defaultProfileId) {
        const defaultProfile = window.configState?.profiles?.find(p => p.id === defaultProfileId);
        const profileType = defaultProfile?.profile_type;

        if (profileType === 'genie' || profileType === 'rag_focused') {
            // Load profile-specific resources for special profile types
            if (typeof window.updateResourcePanelForProfile === 'function') {
                await window.updateResourcePanelForProfile(defaultProfileId);
                console.log('[FinalizeConfig] Loaded profile-specific resources for', profileType, 'profile:', defaultProfileId);
            }
        } else {
            // Load generic MCP resources for standard profiles
            await Promise.all([
                handleLoadResources('tools'),
                handleLoadResources('prompts'),
                handleLoadResources('resources')
            ]);
            console.log('[FinalizeConfig] Loaded generic MCP resources for', profileType || 'unknown', 'profile');
        }
    } else {
        // Fallback: load generic resources if no default profile
        await Promise.all([
            handleLoadResources('tools'),
            handleLoadResources('prompts'),
            handleLoadResources('resources')
        ]);
        console.log('[FinalizeConfig] Loaded generic MCP resources (no default profile)');
    }

    const currentSessionId = state.currentSessionId;

    try {
        const sessions = await API.loadAllSessions();

        // Filter out archived sessions from the conversation view selector
        const activeSessions = sessions ? sessions.filter(s => !s.archived) : [];

        // Sort sessions hierarchically so slave sessions appear under their parents
        const sortedSessions = sortSessionsHierarchically(activeSessions);

        DOM.sessionList.innerHTML = '';
        if (sortedSessions && Array.isArray(sortedSessions) && sortedSessions.length > 0) {
            sortedSessions.forEach((session) => {
                const isActive = session.id === currentSessionId;
                const sessionItem = UI.addSessionToList(session, isActive);
                DOM.sessionList.appendChild(sessionItem);
            });

            // Update utility sessions filter visibility
            if (window.updateUtilitySessionsFilter) {
                window.updateUtilitySessionsFilter();
            }

            // Update genie master badges (adds collapse toggles to sessions with slaves)
            updateGenieMasterBadges();

            // If the previously active session still exists and is not archived, ensure it is loaded.
            // Otherwise, load the most recent active session.
            const sessionToLoad = sortedSessions.find(s => s.id === currentSessionId) ? currentSessionId : sortedSessions[0].id;
            await handleLoadSession(sessionToLoad);
        } else {
            // No active sessions exist, create a new one
            await handleStartNewSession();
        }
    } catch (sessionError) {
        console.error("Error loading previous sessions:", sessionError);
        DOM.sessionList.innerHTML = '<li class="text-red-400 p-2">Error loading sessions</li>';
        // Fallback to creating a new session if loading fails
        await handleStartNewSession();
    }

    DOM.chatModalButton.disabled = false;
    DOM.userInput.placeholder = "Ask about databases, tables, users...";
    UI.setExecutionState(false);

    state.pristineConfig = getCurrentCoreConfig();
    UI.updateConfigButtonState();
    
    // No longer showing the old popup - the welcome screen is now the unified interface
    // setTimeout(UI.closeConfigModal, 1000); // REMOVED
    // DOM.unconfiguredWrapper.classList.add('hidden'); // REMOVED
    // DOM.configuredWrapper.classList.remove('hidden'); // REMOVED
    
    // Always hide welcome screen after successful configuration
    // The welcome screen is only for unconfigured state
    if (window.hideWelcomeScreen) {
        window.hideWelcomeScreen();
    }
    
    console.log('[finalizeConfiguration] switchToConversationView:', switchToConversationView);
    if (switchToConversationView) {
        console.log('[finalizeConfiguration] About to call handleViewSwitch(conversation-view)');
        handleViewSwitch('conversation-view'); // Set the default view
        console.log('[finalizeConfiguration] Called handleViewSwitch(conversation-view)');
    }
    
    // Mark conversation mode as initialized for deploy button validation
    // This ensures that after normal startup (page refresh), the system is marked as initialized
    if (window.__conversationInitState) {
        window.__conversationInitState.initialized = true;
        window.__conversationInitState.lastInitTimestamp = Date.now();
        window.__conversationInitState.inProgress = false;
        console.log('[finalizeConfiguration] Marked conversation as initialized');
    }
}

/**
 * Handles the submission of the main configuration form.
 * @param {Event} e - The submit event.
 */
export async function handleConfigFormSubmit(e) {
    e.preventDefault();
    await API.checkAndUpdateDefaultPrompts();

    const selectedModel = DOM.llmModelSelect.value;
    if (!selectedModel) {
        setConfigStatus('Please select your LLM Model.', 'text-sm text-red-400 text-center');
        return;
    }

    if (DOM.configLoadingSpinner) DOM.configLoadingSpinner.classList.remove('hidden');
    if (DOM.configActionButton) DOM.configActionButton.disabled = true;
    setConfigStatus('Connecting to MCP & LLM...', 'text-sm text-yellow-400 text-center');

    const formData = new FormData(e.target);
    const config = Object.fromEntries(formData.entries());

    const mcpConfig = { server_name: config.server_name, host: config.host, port: config.port, path: config.path };
    safeSetItem('mcpConfig', JSON.stringify(mcpConfig));

    if (config.provider === 'Amazon') {
        const awsCreds = { aws_access_key_id: config.aws_access_key_id, aws_secret_access_key: config.aws_secret_access_key, aws_region: config.aws_region };
        safeSetItem('amazonApiKey', JSON.stringify(awsCreds));
    } else if (config.provider === 'Ollama') {
        safeSetItem('ollamaHost', config.ollama_host);
    } else if (config.provider === 'Azure') {
        const azureCreds = {
            azure_api_key: config.azure_api_key,
            azure_endpoint: config.azure_endpoint,
            azure_deployment_name: config.azure_deployment_name,
            azure_api_version: config.azure_api_version
        };
        safeSetItem('azureApiKey', JSON.stringify(azureCreds));
    } else if (config.provider === 'Friendli') {
        const friendliCreds = {
            friendli_token: config.friendli_token,
            friendli_endpoint_url: config.friendli_endpoint_url
        };
        safeSetItem('friendliApiKey', JSON.stringify(friendliCreds));
    } else {
        safeSetItem(`${config.provider.toLowerCase()}ApiKey`, config.apiKey);
    }

    if (config.tts_credentials_json) {
        safeSetItem('ttsCredentialsJson', config.tts_credentials_json);
    }

    try {
        const res = await fetch('/configure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const result = await res.json();

        if (res.ok) {
            // Switch to Conversation view immediately after successful configuration.
            // Previously passed 'false' to keep Credentials view; requirement changed.
            await finalizeConfiguration(config, true);
        } else {
            throw new Error(result.message || 'An unknown configuration error occurred.');
        }
    } catch (error) {
        setConfigStatus(`Error: ${error.message}`, 'text-sm text-red-400 text-center');
        DOM.promptEditorButton.disabled = true;
        DOM.chatModalButton.disabled = true;
        DOM.mcpStatusDot.classList.add('disconnected');
        DOM.mcpStatusDot.classList.remove('connected');
        DOM.llmStatusDot.classList.add('disconnected');
        DOM.llmStatusDot.classList.remove('connected', 'idle');
        DOM.contextStatusDot.classList.add('disconnected');
        DOM.contextStatusDot.classList.remove('idle', 'context-active');
    } finally {
        if (DOM.configLoadingSpinner) DOM.configLoadingSpinner.classList.add('hidden');
        if (DOM.configActionButton) DOM.configActionButton.disabled = false;
        UI.updateConfigButtonState();
    }
}

/**
 * Loads saved credentials and fetches models for the selected provider.
 */
export async function loadCredentialsAndModels() {
    const newProvider = DOM.llmProviderSelect.value;

    DOM.apiKeyContainer.classList.add('hidden');
    DOM.awsCredentialsContainer.classList.add('hidden');
    DOM.awsListingMethodContainer.classList.add('hidden');
    DOM.ollamaHostContainer.classList.add('hidden');
    DOM.azureCredentialsContainer.classList.add('hidden');
    DOM.friendliCredentialsContainer.classList.add('hidden');

    if (newProvider === 'Amazon') {
        DOM.awsCredentialsContainer.classList.remove('hidden');
        DOM.awsListingMethodContainer.classList.remove('hidden');
        const envCreds = await API.getApiKey('amazon');
        DOM.awsAccessKeyIdInput.value = envCreds.aws_access_key_id || '';
        DOM.awsSecretAccessKeyInput.value = envCreds.aws_secret_access_key || '';
        DOM.awsRegionInput.value = envCreds.aws_region || '';
    } else if (newProvider === 'Ollama') {
        DOM.ollamaHostContainer.classList.remove('hidden');
        const data = await API.getApiKey('ollama');
        DOM.ollamaHostInput.value = data.host || 'http://localhost:11434';
    } else if (newProvider === 'Azure') {
        DOM.azureCredentialsContainer.classList.remove('hidden');
        const envCreds = await API.getApiKey('azure');
        DOM.azureApiKeyInput.value = envCreds.azure_api_key || '';
        DOM.azureEndpointInput.value = envCreds.azure_endpoint || '';
        DOM.azureDeploymentNameInput.value = envCreds.azure_deployment_name || '';
        DOM.azureApiVersionInput.value = envCreds.azure_api_version || '2024-02-01';
    } else if (newProvider === 'Friendli') {
        DOM.friendliCredentialsContainer.classList.remove('hidden');
        const envCreds = await API.getApiKey('friendli');
        DOM.friendliTokenInput.value = envCreds.friendli_token || '';
        DOM.friendliEndpointInput.value = envCreds.friendli_endpoint_url || '';
    } else {
        DOM.apiKeyContainer.classList.remove('hidden');
        const data = await API.getApiKey(newProvider);
        DOM.llmApiKeyInput.value = data.apiKey || '';
    }

    await handleRefreshModelsClick();
}

/**
 * Handles the change event for the LLM provider dropdown.
 */
export async function handleProviderChange() {
    DOM.llmModelSelect.innerHTML = '<option value="">-- Select Provider & Enter Credentials --</option>';
    setConfigStatus('');

    await loadCredentialsAndModels();
}

/**
 * Handles the change event for the LLM model dropdown.
 */
export async function handleModelChange() {
    state.currentModel = DOM.llmModelSelect.value;
    state.currentProvider = DOM.llmProviderSelect.value;
    if (!state.currentModel || !state.currentProvider) return;

    if (Utils.isPrivilegedUser()) {
        const activePrompt = Utils.getSystemPromptForModel(state.currentProvider, state.currentModel);
        if (!activePrompt) {
            setConfigStatus(`Fetching default prompt for ${Utils.getNormalizedModelId(state.currentModel)}...`);
            await resetSystemPrompt(true);
            setConfigStatus(`Default prompt for ${Utils.getNormalizedModelId(state.currentModel)} loaded.`);
            setTimeout(() => { setConfigStatus(''); }, 2000);
        }
    }
}

/**
 * Handles the click event for the "Refresh Models" button.
 */
export async function handleRefreshModelsClick() {
    DOM.refreshIcon.classList.add('hidden');
    DOM.refreshSpinner.classList.remove('hidden');
    DOM.refreshModelsButton.disabled = true;
    setConfigStatus('Fetching models...');
    try {
        const result = await API.fetchModels();
        DOM.llmModelSelect.innerHTML = '';
        result.models.forEach(model => {
            const option = document.createElement('option');
            option.value = model.name;
            option.textContent = model.name + (model.certified ? '' : ' (support evaluated)');
            option.disabled = !model.certified;
            DOM.llmModelSelect.appendChild(option);
        });
        setConfigStatus(`Successfully fetched ${result.models.length} models.`, 'text-sm text-green-400 text-center');
        if (DOM.llmModelSelect.value) {
            await handleModelChange();
        }
    } catch (error) {
        setConfigStatus(`Error: ${error.message}`, 'text-sm text-red-400 text-center');
        DOM.llmModelSelect.innerHTML = '<option value="">-- Could not fetch models --</option>';
    } finally {
        DOM.refreshIcon.classList.remove('hidden');
        DOM.refreshSpinner.classList.add('hidden');
        DOM.refreshModelsButton.disabled = false;
    }
}

/**
 * Opens the System Prompt Editor modal.
 */
export function openPromptEditor() {
    DOM.promptEditorTitle.innerHTML = `System Prompt Editor for: <code class="text-teradata-orange font-normal">${state.currentProvider} / ${Utils.getNormalizedModelId(state.currentModel)}</code>`;
    const promptText = Utils.getSystemPromptForModel(state.currentProvider, state.currentModel);
    DOM.promptEditorTextarea.value = promptText;
    DOM.promptEditorTextarea.dataset.initialValue = promptText;

    DOM.promptEditorOverlay.classList.remove('hidden', 'opacity-0');
    DOM.promptEditorContent.classList.remove('scale-95', 'opacity-0');
    UI.updatePromptEditorState();
}

/**
 * Force-closes the System Prompt Editor modal without checking for changes.
 */
export function forceClosePromptEditor() {
    DOM.promptEditorOverlay.classList.add('opacity-0');
    DOM.promptEditorContent.classList.add('scale-95', 'opacity-0');
    setTimeout(() => {
        DOM.promptEditorOverlay.classList.add('hidden');
        DOM.promptEditorStatus.textContent = '';
    }, 300);
}

/**
 * Handles request to close the System Prompt Editor, checking for unsaved changes.
 */
export function closePromptEditor() {
    const hasChanged = DOM.promptEditorTextarea.value.trim() !== DOM.promptEditorTextarea.dataset.initialValue.trim();
    if (hasChanged) {
        UI.showConfirmation(
            'Discard Changes?',
            'You have unsaved changes that will be lost. Are you sure you want to close the editor?',
            forceClosePromptEditor
        );
    } else {
        forceClosePromptEditor();
    }
}

/**
 * Saves changes made in the System Prompt Editor.
 */
export async function saveSystemPromptChanges() {
    const newPromptText = DOM.promptEditorTextarea.value;
    const defaultPromptText = await Utils.getDefaultSystemPrompt(state.currentProvider, state.currentModel);

    if (defaultPromptText === null) {
        return;
    }

    const isCustom = newPromptText.trim() !== defaultPromptText.trim();

    Utils.saveSystemPromptForModel(state.currentProvider, state.currentModel, newPromptText, isCustom);
    UI.updateStatusPromptName();

    DOM.promptEditorTextarea.dataset.initialValue = newPromptText;

    DOM.promptEditorStatus.textContent = 'Saved!';
    DOM.promptEditorStatus.className = 'text-sm text-green-400';
    setTimeout(() => {
        UI.updatePromptEditorState();
    }, 2000);
}

/**
 * Resets the System Prompt to its default value.
 * @param {boolean} [force=false] - If true, saves the reset without confirmation.
 */
export async function resetSystemPrompt(force = false) {
    const defaultPrompt = await Utils.getDefaultSystemPrompt(state.currentProvider, state.currentModel);
    if (defaultPrompt) {
        if (!force) {
            DOM.promptEditorTextarea.value = defaultPrompt;
            UI.updatePromptEditorState();
        } else {
            Utils.saveSystemPromptForModel(state.currentProvider, state.currentModel, defaultPrompt, false);
            DOM.promptEditorTextarea.value = defaultPrompt;
            UI.updateStatusPromptName();
        }
    }
}

/**
 * Handles changes to the charting intensity dropdown.
 */
export async function handleIntensityChange() {
    if (Utils.isPromptCustomForModel(state.currentProvider, state.currentModel)) {
        UI.showConfirmation(
            'Reset System Prompt?',
            'Changing the charting intensity requires resetting the system prompt to a new default to include updated instructions. Your custom changes will be lost. Do you want to continue?',
            () => {
                resetSystemPrompt(true);
                DOM.configStatus.textContent = 'Charting intensity updated and system prompt was reset to default.';
                DOM.configStatus.className = 'text-sm text-yellow-400 text-center';
            }
        );
    } else {
        await resetSystemPrompt(true);
        DOM.configStatus.textContent = 'Charting intensity updated.';
        DOM.configStatus.className = 'text-sm text-green-400 text-center';
    }
}