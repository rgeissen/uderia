/**
 * handlers/capabilitiesManagement.js
 * * This module handles all logic related to the "Capabilities" panel
 * (Tools, Prompts, Resources) and the modals launched from it.
 */

import * as DOM from '../domElements.js';
import { state } from '../state.js';
import * as API from '../api.js';
import * as UI from '../ui.js?v=1.3';
// We need to import from eventHandlers for functions not yet moved
// This creates a temporary, manageable circular dependency
import { handleStreamRequest } from '../eventHandlers.js?v=3.4';

/**
 * Loads resources (tools, prompts, etc.) for a given type and populates the UI.
 * @param {string} type - The type of resource to load (e.g., 'tools', 'prompts').
 */
export async function handleLoadResources(type) {
    const tabButton = document.querySelector(`.resource-tab[data-type="${type}"]`);
    const categoriesContainer = document.getElementById(`${type}-categories`);
    const panelsContainer = document.getElementById(`${type}-panels-container`);
    const typeCapitalized = type.charAt(0).toUpperCase() + type.slice(1);

    try {
        let data = await API.loadResources(type);

        // Handle new response format with profile metadata for special profiles
        // Backend returns { tools: {}, profile_type: 'rag_focused', ... } for rag_focused/genie profiles
        if (data && data.profile_type) {
            const profileType = data.profile_type;

            if (profileType === 'rag_focused') {
                state.activeRagProfile = {
                    tag: data.profile_tag,
                    knowledgeCollections: data.knowledge_collections || []
                };
                state.activeGenieProfile = null;
                console.log(`📚 Default profile is RAG-focused: @${data.profile_tag}`);
            } else if (profileType === 'genie') {
                state.activeGenieProfile = {
                    tag: data.profile_tag,
                    slaveProfiles: data.slave_profiles || []
                };
                state.activeRagProfile = null;
                console.log(`🧞 Default profile is Genie coordinator: @${data.profile_tag}`);
            }

            // Extract the actual tools/prompts from the wrapper
            data = data[type] || {};
        }

        if (!data || Object.keys(data).length === 0) {
            if(tabButton) {
                tabButton.style.display = 'none';
            }
            // Still render the panel for special profiles to show the message
            if (state.activeRagProfile || state.activeGenieProfile) {
                renderResourcePanel(type);
            }
            return;
        }

        tabButton.style.display = 'inline-block';
        state.resourceData[type] = data;

        if (type === 'prompts') {
            UI.updatePromptsTabCounter();
        } else if (type === 'tools') {
            UI.updateToolsTabCounter();
        } else {
            const totalCount = Object.values(data).reduce((acc, items) => acc + items.length, 0);
            tabButton.textContent = `${typeCapitalized} (${totalCount})`;
        }

        categoriesContainer.innerHTML = '';
        panelsContainer.innerHTML = '';

        Object.keys(data).forEach(category => {
            const categoryTab = document.createElement('button');
            categoryTab.className = 'category-tab px-4 py-2 rounded-md font-semibold text-sm transition-colors hover:bg-[#D9501A]';
            categoryTab.textContent = category;
            categoryTab.dataset.category = category;
            categoryTab.dataset.type = type;
            categoriesContainer.appendChild(categoryTab);

            const panel = document.createElement('div');
            panel.id = `panel-${type}-${category}`;
            panel.className = 'category-panel px-4 space-y-2';
            panel.dataset.category = category;

            data[category].forEach(resource => {
                const itemEl = UI.createResourceItem(resource, type);
                panel.appendChild(itemEl);
            });
            panelsContainer.appendChild(panel);
        });

        document.querySelectorAll(`#${type}-categories .category-tab`).forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll(`#${type}-categories .category-tab`).forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                document.querySelectorAll(`#${type}-panels-container .category-panel`).forEach(p => {
                    p.classList.toggle('open', p.dataset.category === tab.dataset.category);
                });
            });
        });

        if (categoriesContainer.querySelector('.category-tab')) {
            categoriesContainer.querySelector('.category-tab').click();
        }

    } catch (error) {
        console.error(`Failed to load ${type}: ${error.message}`);
        if(tabButton) {
            tabButton.textContent = `${typeCapitalized} (Error)`;
            tabButton.style.display = 'inline-block';
        }
        categoriesContainer.innerHTML = '';
        panelsContainer.innerHTML = `<div class="p-4 text-center text-red-400">Failed to load ${type}.</div>`;
    }
}

/**
 * Renders the resource panel using data already in state (no API fetch).
 * Used when switching profiles to avoid overwriting profile-specific data.
 * @param {string} type - The type of resource to render (e.g., 'tools', 'prompts').
 */
export function renderResourcePanel(type) {
    const tabButton = document.querySelector(`.resource-tab[data-type="${type}"]`);
    const categoriesContainer = document.getElementById(`${type}-categories`);
    const panelsContainer = document.getElementById(`${type}-panels-container`);
    const typeCapitalized = type.charAt(0).toUpperCase() + type.slice(1);

    try {
        // Use data from state instead of fetching
        const data = state.resourceData[type] || {};

        // Special handling for LLM-only/Conversation-focused profiles WITHOUT tools
        // Note: LLM-only profiles CAN have MCP tools/prompts and knowledge collections
        // Show exception message when they have no MCP tools (with or without knowledge)
        const hasNoData = !data || Object.keys(data).length === 0;
        if (state.activeLlmOnlyProfile && type === 'tools' && hasNoData) {
            const knowledgeCollections = state.activeLlmOnlyProfile.knowledgeCollections || [];
            const hasKnowledge = knowledgeCollections.length > 0;

            if (tabButton) {
                tabButton.style.display = 'inline-block';
                tabButton.textContent = hasKnowledge ? `Tools (Knowledge)` : `Tools (Conversation)`;
            }

            // Hide Resources tab for LLM-only profiles without MCP tools
            const resourcesTab = document.querySelector('.resource-tab[data-type="resources"]');
            if (resourcesTab) {
                resourcesTab.style.display = 'none';
            }

            // Hide categories container to avoid double border
            categoriesContainer.innerHTML = '';
            categoriesContainer.style.display = 'none';

            if (hasKnowledge) {
                // Show knowledge-focused message for LLM-only profiles with knowledge collections
                // Clean book/document icon representing knowledge
                panelsContainer.innerHTML = `
                    <div class="p-6 text-center space-y-3">
                        <svg class="w-12 h-12 mx-auto text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <!-- Open book -->
                            <path d="M4 19.5 C4 18.1 5.1 17 6.5 17 L12 17 L12 6.5 C12 5.7 11.3 5 10.5 5 L6.5 5 C5.1 5 4 6.1 4 7.5 Z" stroke-width="2" stroke-linejoin="round"/>
                            <path d="M20 19.5 C20 18.1 18.9 17 17.5 17 L12 17 L12 6.5 C12 5.7 12.7 5 13.5 5 L17.5 5 C18.9 5 20 6.1 20 7.5 Z" stroke-width="2" stroke-linejoin="round"/>
                            <!-- Page lines -->
                            <line x1="7" y1="9" x2="10" y2="9" stroke-width="1.5" stroke-linecap="round"/>
                            <line x1="7" y1="12" x2="10" y2="12" stroke-width="1.5" stroke-linecap="round"/>
                            <line x1="14" y1="9" x2="17" y2="9" stroke-width="1.5" stroke-linecap="round"/>
                            <line x1="14" y1="12" x2="17" y2="12" stroke-width="1.5" stroke-linecap="round"/>
                        </svg>
                        <div class="text-lg font-semibold text-gray-200">Knowledge-Enhanced Conversation</div>
                        <div class="text-sm text-gray-400 max-w-md mx-auto">
                            This profile uses LLM conversation enhanced with knowledge retrieval from document repositories.
                            It doesn't use MCP tools - instead, it searches configured knowledge collections.
                        </div>
                        ${knowledgeCollections.length > 0 ? `
                            <div class="mt-4 text-sm text-gray-300">
                                <div class="font-semibold mb-2">Knowledge Collections:</div>
                                <div class="flex flex-wrap gap-2 justify-center">
                                    ${knowledgeCollections.map(collection => {
                                        const name = collection.name || collection.collection_name || 'Unknown';
                                        return `<span class="px-3 py-1 bg-gray-700 rounded-md">${name}</span>`;
                                    }).join('')}
                                </div>
                            </div>
                        ` : ''}
                    </div>
                `;
            } else {
                // Show pure conversation message for LLM-only profiles without any external resources
                panelsContainer.innerHTML = `
                    <div class="p-6 text-center space-y-3">
                        <svg class="w-12 h-12 mx-auto text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <!-- Message square with dialogue waves -->
                            <rect x="4" y="6" width="16" height="12" rx="2" stroke-width="2"/>
                            <!-- Dialogue wave lines -->
                            <path d="M8 10 Q9 9 10 10 T12 10" stroke-width="1.5" stroke-linecap="round" fill="none"/>
                            <path d="M8 13 Q10 12 12 13 T16 13" stroke-width="1.5" stroke-linecap="round" fill="none"/>
                            <path d="M8 16 Q9 15 10 16 T12 16" stroke-width="1.5" stroke-linecap="round" fill="none"/>
                        </svg>
                        <div class="text-lg font-semibold text-gray-200">Conversation-Focused Profile</div>
                        <div class="text-sm text-gray-400 max-w-md mx-auto">
                            This profile uses direct LLM conversation without external tools or data sources.
                            It focuses on natural language understanding and generation for general-purpose dialogue.
                        </div>
                    </div>
                `;
            }
            return;
        }

        // Special handling for Genie coordinator profiles
        if (state.activeGenieProfile && type === 'tools') {
            // Show Genie coordinator info instead of hiding the tab
            if (tabButton) {
                tabButton.style.display = 'inline-block';
                tabButton.textContent = `Tools (Coordinator)`;
            }

            // Hide Resources tab for Genie profiles
            const resourcesTab = document.querySelector('.resource-tab[data-type="resources"]');
            if (resourcesTab) {
                resourcesTab.style.display = 'none';
            }

            // Hide categories container to avoid double border
            categoriesContainer.innerHTML = '';
            categoriesContainer.style.display = 'none';
            panelsContainer.innerHTML = `
                <div class="p-6 text-center space-y-3">
                    <svg class="w-12 h-12 mx-auto text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <circle cx="12" cy="12" r="3" stroke-width="2"/>
                        <circle cx="6" cy="6" r="2" stroke-width="2"/>
                        <circle cx="18" cy="6" r="2" stroke-width="2"/>
                        <circle cx="6" cy="18" r="2" stroke-width="2"/>
                        <circle cx="18" cy="18" r="2" stroke-width="2"/>
                        <line x1="9.5" y1="10.5" x2="6.8" y2="7.8" stroke-width="2"/>
                        <line x1="14.5" y1="10.5" x2="17.2" y2="7.8" stroke-width="2"/>
                        <line x1="9.5" y1="13.5" x2="6.8" y2="16.2" stroke-width="2"/>
                        <line x1="14.5" y1="13.5" x2="17.2" y2="16.2" stroke-width="2"/>
                    </svg>
                    <div class="text-lg font-semibold text-gray-200">Genie Coordinator Profile</div>
                    <div class="text-sm text-gray-400 max-w-md mx-auto">
                        This profile coordinates multiple specialized profiles to answer complex questions.
                        It doesn't use tools directly - instead, it intelligently routes queries to slave profiles.
                    </div>
                    ${state.activeGenieProfile.slaveProfiles && state.activeGenieProfile.slaveProfiles.length > 0 ? `
                        <div class="mt-4 text-sm text-gray-300">
                            <div class="font-semibold mb-2">Coordinating Profiles:</div>
                            <div class="flex flex-wrap gap-2 justify-center">
                                ${state.activeGenieProfile.slaveProfiles.map(entry => {
                                    if (typeof entry === 'object' && entry.tag) {
                                        return UI.renderProfileTag(entry.tag);
                                    }
                                    const profile = window.configState?.profiles?.find(p => p.id === entry);
                                    return profile ? UI.renderProfileTag(profile.tag, profile.profile_type) : '';
                                }).join('')}
                            </div>
                        </div>
                    ` : ''}
                </div>
            `;
            return;
        }

        // Special handling for RAG-focused profiles
        if (state.activeRagProfile && type === 'tools') {
            // Show RAG-focused info instead of tools
            if (tabButton) {
                tabButton.style.display = 'inline-block';
                tabButton.textContent = `Tools (Knowledge)`;
            }

            // Hide Resources tab for RAG profiles
            const resourcesTab = document.querySelector('.resource-tab[data-type="resources"]');
            if (resourcesTab) {
                resourcesTab.style.display = 'none';
            }

            // Hide categories container to avoid double border
            categoriesContainer.innerHTML = '';
            categoriesContainer.style.display = 'none';
            panelsContainer.innerHTML = `
                <div class="p-6 text-center space-y-3">
                    <svg class="w-12 h-12 mx-auto text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <!-- Filing cabinet / archive -->
                        <rect x="5" y="4" width="14" height="5" rx="1" stroke-width="2"/>
                        <rect x="5" y="10" width="14" height="5" rx="1" stroke-width="2"/>
                        <rect x="5" y="16" width="14" height="4" rx="1" stroke-width="2"/>
                        <!-- Drawer handles -->
                        <line x1="10" y1="6.5" x2="14" y2="6.5" stroke-width="2" stroke-linecap="round"/>
                        <line x1="10" y1="12.5" x2="14" y2="12.5" stroke-width="2" stroke-linecap="round"/>
                        <line x1="10" y1="18" x2="14" y2="18" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    <div class="text-lg font-semibold text-gray-200">Knowledge-Focused Profile</div>
                    <div class="text-sm text-gray-400 max-w-md mx-auto">
                        This profile retrieves knowledge from document repositories to answer questions.
                        It doesn't use tools directly - instead, it searches configured knowledge collections.
                    </div>
                    ${state.activeRagProfile.knowledgeCollections && state.activeRagProfile.knowledgeCollections.length > 0 ? `
                        <div class="mt-4 text-sm text-gray-300">
                            <div class="font-semibold mb-2">Knowledge Collections:</div>
                            <div class="flex flex-wrap gap-2 justify-center">
                                ${state.activeRagProfile.knowledgeCollections.map(collection => {
                                    const name = collection.name || collection.collection_name || 'Unknown';
                                    return `<span class="px-3 py-1 bg-gray-700 rounded-md">${name}</span>`;
                                }).join('')}
                            </div>
                        </div>
                    ` : ''}
                </div>
            `;
            return;
        }

        if (!data || Object.keys(data).length === 0) {
            if(tabButton) {
                tabButton.style.display = 'none';
            }
            return;
        }

        tabButton.style.display = 'inline-block';

        // Restore categories container for normal profiles (not special types)
        // Note: Resources tab visibility is controlled by handleLoadResources('resources') based on actual data
        if (!state.activeGenieProfile && !state.activeRagProfile && !state.activeLlmOnlyProfile) {
            // Restore categories container display
            categoriesContainer.style.display = 'flex';
        }

        if (type === 'prompts') {
            UI.updatePromptsTabCounter();
        } else if (type === 'tools') {
            UI.updateToolsTabCounter();
        } else {
            const totalCount = Object.values(data).reduce((acc, items) => acc + items.length, 0);
            tabButton.textContent = `${typeCapitalized} (${totalCount})`;
        }

        categoriesContainer.innerHTML = '';
        panelsContainer.innerHTML = '';

        Object.keys(data).forEach(category => {
            const categoryTab = document.createElement('button');
            categoryTab.className = 'category-tab px-4 py-2 rounded-md font-semibold text-sm transition-colors hover:bg-[#D9501A]';
            categoryTab.textContent = category;
            categoryTab.dataset.category = category;
            categoryTab.dataset.type = type;
            categoriesContainer.appendChild(categoryTab);

            const panel = document.createElement('div');
            panel.id = `panel-${type}-${category}`;
            panel.className = 'category-panel px-4 space-y-2';
            panel.dataset.category = category;

            data[category].forEach(resource => {
                const itemEl = UI.createResourceItem(resource, type);
                panel.appendChild(itemEl);
            });
            panelsContainer.appendChild(panel);
        });

        document.querySelectorAll(`#${type}-categories .category-tab`).forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll(`#${type}-categories .category-tab`).forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                document.querySelectorAll(`#${type}-panels-container .category-panel`).forEach(p => {
                    p.classList.toggle('open', p.dataset.category === tab.dataset.category);
                });
            });
        });

        if (categoriesContainer.querySelector('.category-tab')) {
            categoriesContainer.querySelector('.category-tab').click();
        }

    } catch (error) {
        console.error(`Failed to render ${type}: ${error.message}`);
        if(tabButton) {
            tabButton.textContent = `${typeCapitalized} (Error)`;
            tabButton.style.display = 'inline-block';
        }
        categoriesContainer.innerHTML = '';
        panelsContainer.innerHTML = `<div class="p-4 text-center text-red-400">Failed to render ${type}.</div>`;
    }
}

/**
 * Handles clicks on the main resource tabs (Tools, Prompts, etc.).
 * @param {Event} e - The click event.
 */
export function handleResourceTabClick(e) {
    if (e.target.classList.contains('resource-tab')) {
        const type = e.target.dataset.type;
        document.querySelectorAll('.resource-tab').forEach(tab => tab.classList.remove('active'));
        e.target.classList.add('active');

        document.querySelectorAll('.resource-panel').forEach(panel => {
            panel.style.display = panel.id === `${type}-panel` ? 'flex' : 'none';
        });
    }
}

/**
 * Opens the modal to run a prompt with arguments.
 * @param {object} prompt - The prompt resource object.
 */
export function openPromptModal(prompt) {
    DOM.promptModalOverlay.classList.remove('hidden', 'opacity-0');
    DOM.promptModalContent.classList.remove('scale-95', 'opacity-0');
    DOM.promptModalTitle.textContent = prompt.name;
    DOM.promptModalForm.dataset.promptName = prompt.name;
    DOM.promptModalInputs.innerHTML = '';
    DOM.promptModalForm.querySelector('button[type="submit"]').textContent = 'Run Prompt';

    if (prompt.arguments && prompt.arguments.length > 0) {
        prompt.arguments.forEach(arg => {
            const inputGroup = document.createElement('div');
            const label = document.createElement('label');
            label.htmlFor = `prompt-arg-${arg.name}`;
            label.className = 'block text-sm font-medium text-gray-300 mb-1';
            label.textContent = arg.name + (arg.required ? ' *' : '');

            const input = document.createElement('input');
            input.type = 'text';
            input.id = `prompt-arg-${arg.name}`;
            input.name = arg.name;
            input.className = 'w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none';
            input.placeholder = arg.description || `Enter value for ${arg.name}`;
            if (arg.required) input.required = true;

            inputGroup.appendChild(label);
            inputGroup.appendChild(input);
            DOM.promptModalInputs.appendChild(inputGroup);
        });
    } else {
        DOM.promptModalInputs.innerHTML = '<p class="text-gray-400">This prompt requires no arguments.</p>';
    }

    DOM.promptModalForm.onsubmit = (e) => {
        e.preventDefault();
        const promptName = e.target.dataset.promptName;
        const formData = new FormData(e.target);
        const arugments = Object.fromEntries(formData.entries());

        UI.closePromptModal();
        // Priority: typed @TAG > resource panel profile > undefined
        const profileId = window.activeProfileOverrideId || state.currentResourcePanelProfileId || undefined;
        console.log(`🎯 [Prompt Invocation] Using profile_override_id: ${profileId}`);
        handleStreamRequest('/invoke_prompt_stream', {
            session_id: state.currentSessionId,
            prompt_name: promptName,
            arguments: arugments,
            profile_override_id: profileId
        });
    };
}

/**
 * Opens the modal for user correction of tool arguments.
 * @param {object} data - The correction data from the server.
 */
export function openCorrectionModal(data) {
    DOM.promptModalOverlay.classList.remove('hidden', 'opacity-0');
    DOM.promptModalContent.classList.remove('scale-95', 'opacity-0');

    const spec = data.specification;
    DOM.promptModalTitle.textContent = `Correction for: ${spec.name}`;
    DOM.promptModalForm.dataset.toolName = spec.name;
    DOM.promptModalInputs.innerHTML = '';
    DOM.promptModalForm.querySelector('button[type="submit"]').textContent = 'Run Correction';

    const messageEl = document.createElement('p');
    messageEl.className = 'text-yellow-300 text-sm mb-4 p-3 bg-yellow-500/10 rounded-lg';
    messageEl.textContent = data.message;
    DOM.promptModalInputs.appendChild(messageEl);

    spec.arguments.forEach(arg => {
        const inputGroup = document.createElement('div');
        const label = document.createElement('label');
        label.htmlFor = `correction-arg-${arg.name}`;
        label.className = 'block text-sm font-medium text-gray-300 mb-1';
        label.textContent = arg.name + (arg.required ? ' *' : '');

        const input = document.createElement('input');
        input.type = 'text';
        input.id = `correction-arg-${arg.name}`;
        input.name = arg.name;
        input.className = 'w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none';
        input.placeholder = arg.description || `Enter value for ${arg.name}`;
        if (arg.required) input.required = true;

        inputGroup.appendChild(label);
        inputGroup.appendChild(input);
        DOM.promptModalInputs.appendChild(inputGroup);
    });

    DOM.promptModalForm.onsubmit = (e) => {
        e.preventDefault();
        const toolName = e.target.dataset.toolName;
        const formData = new FormData(e.target);
        const userArgs = Object.fromEntries(formData.entries());

        const correctedPrompt = `Please run the tool '${toolName}' with the following corrected parameters: ${JSON.stringify(userArgs)}`;

        UI.closePromptModal();

        handleStreamRequest('/ask_stream', { message: correctedPrompt, session_id: state.currentSessionId });
    };
}

/**
 * Opens the modal to view the content of a prompt.
 * @param {string} promptName - The name of the prompt to view.
 */
export async function openViewPromptModal(promptName) {
    DOM.viewPromptModalOverlay.classList.remove('hidden', 'opacity-0');
    DOM.viewPromptModalContent.classList.remove('scale-95', 'opacity-0');
    DOM.viewPromptModalTitle.textContent = `Viewing Prompt: ${promptName}`;
    DOM.viewPromptModalText.textContent = 'Loading...';

    try {
        const token = localStorage.getItem('tda_auth_token');
        const res = await fetch(`/prompt/${promptName}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await res.json();
        if (res.ok) {
            DOM.viewPromptModalText.textContent = data.content;
        } else {
            if (data.error === 'dynamic_prompt_error') {
                DOM.viewPromptModalText.textContent = `Info: ${data.message}`;
            } else {
                throw new Error(data.error || 'Failed to fetch prompt content.');
            }
        }
    } catch (error) {
        DOM.viewPromptModalText.textContent = `Error: ${error.message}`;
    }
}

/**
 * Handles toggling a prompt's enabled/disabled state.
 * @param {string} promptName - The name of the prompt.
 * @param {boolean} isDisabled - The new disabled state.
 * @param {HTMLButtonElement} buttonEl - The button that was clicked.
 */
export async function handleTogglePrompt(promptName, isDisabled, buttonEl) {
    try {
        await API.togglePromptApi(promptName, isDisabled);

        for (const category in state.resourceData.prompts) {
            const prompt = state.resourceData.prompts[category].find(p => p.name === promptName);
            if (prompt) {
                prompt.disabled = isDisabled;
                break;
            }
        }

        const promptItem = document.getElementById(`resource-prompts-${promptName}`);
        const runButton = promptItem.querySelector('.run-prompt-button');

        promptItem.classList.toggle('opacity-60', isDisabled);
        promptItem.title = isDisabled ? 'This prompt is disabled and will not be used by the agent.' : '';
        runButton.disabled = isDisabled;
        runButton.title = isDisabled ? 'This prompt is disabled.' : 'Run this prompt.';

        buttonEl.innerHTML = isDisabled ?
            `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074L3.707 2.293zM10 12a2 2 0 110-4 2 2 0 010 4z" clip-rule="evenodd" /><path d="M2 10s3.939 4 8 4 8-4 8-4-3.939-4-8-4-8 4-8 4zm13.707 4.293a1 1 0 00-1.414-1.414L12.586 14.6A8.007 8.007 0 0110 16c-4.478 0-8.268-2.943-9.542-7 .946-2.317 2.83-4.224 5.166-5.447L2.293 1.293A1 1 0 00.879 2.707l14 14a1 1 0 001.414 0z" /></svg>` :
            `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z" /><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.022 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd" /></svg>`;

        UI.updatePromptsTabCounter();

    } catch (error) {
        console.error(`Failed to toggle prompt ${promptName}:`, error);
    }
}

/**
 * Handles toggling a tool's enabled/disabled state.
 * @param {string} toolName - The name of the tool.
 * @param {boolean} isDisabled - The new disabled state.
 * @param {HTMLButtonElement} buttonEl - The button that was clicked.
 */
export async function handleToggleTool(toolName, isDisabled, buttonEl) {
    try {
        await API.toggleToolApi(toolName, isDisabled);

        for (const category in state.resourceData.tools) {
            const tool = state.resourceData.tools[category].find(t => t.name === toolName);
            if (tool) {
                tool.disabled = isDisabled;
                break;
            }
        }

        const toolItem = document.getElementById(`resource-tools-${toolName}`);
        toolItem.classList.toggle('opacity-60', isDisabled);
        toolItem.title = isDisabled ? 'This tool is disabled and will not be used by the agent.' : '';

        buttonEl.innerHTML = isDisabled ?
            `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074L3.707 2.293zM10 12a2 2 0 110-4 2 2 0 010 4z" clip-rule="evenodd" /><path d="M2 10s3.939 4 8 4 8-4 8-4-3.939-4-8-4-8 4-8 4zm13.707 4.293a1 1 0 00-1.414-1.414L12.586 14.6A8.007 8.007 0 0110 16c-4.478 0-8.268-2.943-9.542-7 .946-2.317 2.83-4.224 5.166-5.447L2.293 1.293A1 1 0 00.879 2.707l14 14a1 1 0 001.414 0z" /></svg>` :
            `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z" /><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.022 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd" /></svg>`;

        UI.updateToolsTabCounter();

    } catch (error) {
        console.error(`Failed to toggle tool ${toolName}:`, error);
    }
}