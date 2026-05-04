/**
 * handlers/capabilitiesManagement.js
 * * This module handles all logic related to the "Capabilities" panel
 * (Tools, Prompts, Resources) and the modals launched from it.
 */

import * as DOM from '../domElements.js';
import { state } from '../state.js';
import * as API from '../api.js';
import * as UI from '../ui.js?v=1.5';
// We need to import from eventHandlers for functions not yet moved
// This creates a temporary, manageable circular dependency
import { handleStreamRequest } from '../eventHandlers.js?v=3.4';

// ── Badge helpers (matching componentsPanelHandler style) ────────────────────

const _IFOC = {
    tool_enabled: { label: 'Optimize',   color: '#9333ea', bg: 'rgba(147,51,234,0.10)', border: 'rgba(147,51,234,0.25)' },
    llm_only:     { label: 'Ideate',     color: '#4ade80', bg: 'rgba(74,222,128,0.10)', border: 'rgba(74,222,128,0.25)' },
    rag_focused:  { label: 'Focus',      color: '#3b82f6', bg: 'rgba(59,130,246,0.10)', border: 'rgba(59,130,246,0.25)' },
    genie:        { label: 'Coordinate', color: '#F15F22', bg: 'rgba(241,95,34,0.10)',  border: 'rgba(241,95,34,0.25)'  },
};

function _pill(text, color, bg, border, mono = false) {
    const font = mono ? 'font-mono' : 'font-medium';
    return `<span class="text-[10px] ${font} px-1.5 py-0.5 rounded whitespace-nowrap"
        style="background:${bg};color:${color};border:1px solid ${border};">${text}</span>`;
}

function createKnowledgeCard(collection) {
    const name = collection.name || collection.collection_name || collection.collection_id || 'Unknown';
    const el = document.createElement('details');
    el.className = 'resource-item rounded-lg';
    el.style.cssText = 'background:var(--card-bg,rgba(30,41,59,0.5));border:1px solid var(--border-primary,rgba(148,163,184,0.18));border-left:4px solid #3b82f6;';

    const typeBadge   = _pill('knowledge',   '#3b82f6', 'rgba(59,130,246,0.10)',  'rgba(59,130,246,0.25)');
    const storeBadge  = _pill('vector store', '#34d399', 'rgba(16,185,129,0.12)',  'rgba(16,185,129,0.25)', true);
    const activeBadge = _pill('ACTIVE',       '#4ade80', 'rgba(74,222,128,0.10)',  'rgba(74,222,128,0.2)');

    el.innerHTML = `
        <summary style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;cursor:pointer;border-radius:8px;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;">
                <span style="font-size:13px;font-weight:500;color:var(--text-primary,#e5e7eb);">${name}</span>
                ${typeBadge}${storeBadge}${activeBadge}
            </div>
            <svg class="chevron" style="width:16px;height:16px;flex-shrink:0;color:var(--text-muted,#9ca3af);" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
        </summary>
        <div style="padding:8px 12px 10px;font-size:11px;color:var(--text-muted,#9ca3af);border-top:1px solid var(--border-primary,rgba(148,163,184,0.18));">
            Semantically searched on every query using this profile.
        </div>`;
    return el;
}

function createCoordCard(entry) {
    const tag = entry.tag || 'Unknown';
    const profileType = entry.profile_type || '';
    const ifoc = _IFOC[profileType] || { label: profileType, color: '#94a3b8', bg: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.2)' };

    const el = document.createElement('details');
    el.className = 'resource-item rounded-lg';
    el.style.cssText = `background:var(--card-bg,rgba(30,41,59,0.5));border:1px solid var(--border-primary,rgba(148,163,184,0.18));border-left:4px solid ${ifoc.color};`;

    const tagPill   = UI.renderProfileTag(tag, profileType);
    const ifocBadge = _pill(ifoc.label, ifoc.color, ifoc.bg, ifoc.border);

    const descriptions = {
        tool_enabled: 'Multi-step planning with MCP tool execution.',
        llm_only:     'Direct LLM conversation, optional tool access.',
        rag_focused:  'Knowledge retrieval from document collections.',
        genie:        'Nested coordination across multiple profiles.',
    };

    el.innerHTML = `
        <summary style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;cursor:pointer;border-radius:8px;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;">
                ${tagPill}
                ${ifocBadge}
            </div>
            <svg class="chevron" style="width:16px;height:16px;flex-shrink:0;color:var(--text-muted,#9ca3af);" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
        </summary>
        <div style="padding:8px 12px 10px;font-size:11px;color:var(--text-muted,#9ca3af);border-top:1px solid var(--border-primary,rgba(148,163,184,0.18));">
            ${descriptions[profileType] || 'Child profile coordinated by this profile.'}
        </div>`;
    return el;
}

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
            categoryTab.className = 'category-tab';
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
    const panelTitle = document.querySelector(`#${type}-panel .panel-title`);
    const typeCapitalized = type.charAt(0).toUpperCase() + type.slice(1);

    // Helper: update the rail button label + hide/show the MCP chip for special profile modes
    const setRailLabel = (label, showMcpChip = false) => {
        if (type !== 'tools') return;
        const railBtn = document.querySelector('.rail-item[data-type="tools"]');
        if (!railBtn) return;
        const lbl = railBtn.querySelector('.rail-label');
        const chip = railBtn.querySelector('.rail-mcp-chip');
        if (lbl) lbl.textContent = label;
        if (chip) chip.style.display = showMcpChip ? '' : 'none';
        railBtn.title = label;
    };

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

            // Hide Resources tab for LLM-only profiles without MCP tools
            const resourcesTab = document.querySelector('.resource-tab[data-type="resources"]');
            if (resourcesTab) resourcesTab.style.display = 'none';

            if (hasKnowledge) {
                // Render KNOWLEDGE category with collection cards (same as rag_focused path)
                if (tabButton) {
                    tabButton.style.display = 'inline-block';
                    tabButton.textContent = `Tools (${knowledgeCollections.length})`;
                }
                if (panelTitle) panelTitle.textContent = 'Knowledge';
                setRailLabel('Knowledge');

                categoriesContainer.innerHTML = '';
                categoriesContainer.style.display = 'none';
                panelsContainer.innerHTML = '';

                const panel = document.createElement('div');
                panel.id = 'panel-tools-knowledge';
                panel.className = 'category-panel open px-4 space-y-2';
                panel.dataset.category = 'knowledge';

                knowledgeCollections.forEach(collection => {
                    panel.appendChild(createKnowledgeCard(collection));
                });
                panelsContainer.appendChild(panel);
            } else {
                // Pure conversation: no tab, minimal message
                if (tabButton) tabButton.style.display = 'none';
                categoriesContainer.innerHTML = '';
                categoriesContainer.style.display = 'none';
                panelsContainer.innerHTML = `
                    <div class="p-6 text-center space-y-3">
                        <svg class="w-12 h-12 mx-auto text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <rect x="4" y="6" width="16" height="12" rx="2" stroke-width="2"/>
                            <path d="M8 10 Q9 9 10 10 T12 10" stroke-width="1.5" stroke-linecap="round" fill="none"/>
                            <path d="M8 13 Q10 12 12 13 T16 13" stroke-width="1.5" stroke-linecap="round" fill="none"/>
                        </svg>
                        <div class="text-lg font-semibold" style="color:var(--text-primary)">Conversation Profile</div>
                        <div class="text-sm" style="color:var(--text-muted)">Direct LLM conversation — no external tools or knowledge collections.</div>
                    </div>
                `;
            }
            return;
        }

        // Special handling for Genie coordinator profiles — render COORD category with child profile cards
        if (state.activeGenieProfile && type === 'tools') {
            // Resolve slave profile entries to { tag, profile_type } objects
            // Entries may be plain IDs (string), { id, tag } objects, or full profile objects
            const slaveEntries = (state.activeGenieProfile.slaveProfiles || []).map(entry => {
                if (typeof entry === 'string') {
                    return window.configState?.profiles?.find(p => p.id === entry) || null;
                }
                // Object entry — look up full profile to get profile_type if missing
                if (!entry.profile_type && entry.id) {
                    const full = window.configState?.profiles?.find(p => p.id === entry.id);
                    return full || entry;
                }
                return entry;
            }).filter(Boolean);

            // Update hidden tab so rail badge picks up the count
            if (tabButton) {
                tabButton.style.display = 'inline-block';
                tabButton.textContent = `Tools (${slaveEntries.length})`;
            }
            if (panelTitle) panelTitle.textContent = 'Coordinate';
            setRailLabel('Coordinate');

            // Hide Resources tab for Genie profiles (no MCP data sources)
            const resourcesTab = document.querySelector('.resource-tab[data-type="resources"]');
            if (resourcesTab) resourcesTab.style.display = 'none';

            // Render cards directly — no category pill needed for a single category
            categoriesContainer.innerHTML = '';
            categoriesContainer.style.display = 'none';
            panelsContainer.innerHTML = '';

            const panel = document.createElement('div');
            panel.id = 'panel-tools-coord';
            panel.className = 'category-panel open px-4 space-y-2';
            panel.dataset.category = 'coord';

            if (slaveEntries.length === 0) {
                panel.innerHTML = '<p class="text-sm text-gray-400 py-4 text-center">No child profiles configured.</p>';
            } else {
                slaveEntries.forEach(entry => panel.appendChild(createCoordCard(entry)));
            }
            panelsContainer.appendChild(panel);
            return;
        }

        // Special handling for RAG-focused profiles — render KNOWLEDGE category instead of tools
        if (state.activeRagProfile && type === 'tools') {
            const collections = state.activeRagProfile.knowledgeCollections || [];

            // Update hidden tab so rail badge picks up the count
            if (tabButton) {
                tabButton.style.display = 'inline-block';
                tabButton.textContent = `Tools (${collections.length})`;
            }
            if (panelTitle) panelTitle.textContent = 'Knowledge';
            setRailLabel('Knowledge');

            // Hide Resources tab for RAG profiles (no MCP data sources)
            const resourcesTab = document.querySelector('.resource-tab[data-type="resources"]');
            if (resourcesTab) resourcesTab.style.display = 'none';

            // Render cards directly — no category pill needed for a single category
            categoriesContainer.innerHTML = '';
            categoriesContainer.style.display = 'none';
            panelsContainer.innerHTML = '';

            const panel = document.createElement('div');
            panel.id = 'panel-tools-knowledge';
            panel.className = 'category-panel open px-4 space-y-2';
            panel.dataset.category = 'knowledge';

            if (collections.length === 0) {
                panel.innerHTML = '<p class="text-sm text-gray-400 py-4 text-center">No knowledge collections configured.</p>';
            } else {
                collections.forEach(collection => panel.appendChild(createKnowledgeCard(collection)));
            }
            panelsContainer.appendChild(panel);
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
            // Restore categories container display and panel title for normal profiles
            categoriesContainer.style.display = 'flex';
            if (panelTitle && type === 'tools') panelTitle.textContent = 'Tools';
            setRailLabel('Tools', true);
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
            categoryTab.className = 'category-tab';
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
            if (data.error === 'dynamic_prompt_error' || data.error === 'prompt_not_on_server') {
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