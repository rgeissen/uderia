/**
 * main.js
 * * This is the entry point for the application.
 * It initializes the application by setting up event listeners and loading initial data.
 */

import { initializeEventListeners } from './eventHandlers.js?v=3.4';
import { finalizeConfiguration } from './handlers/configManagement.js';
import { initializeConfigurationUI } from './handlers/configurationHandler.js';
import * as API from './api.js';
import * as DOM from './domElements.js';
import { state } from './state.js';
import { setupPanelToggle } from './utils.js';
import * as UI from './ui.js';
import { handleViewSwitch } from './ui.js';
import { initializeVoiceRecognition } from './voice.js';
import { subscribeToNotifications } from './notifications.js?v=3.4';
import { initializeMarketplace, unsubscribeFromCollection } from './handlers/marketplaceHandler.js';
import * as capabilitiesModule from './handlers/capabilitiesManagement.js';
// Import conversationInitializer early to ensure window.__conversationInitState is available
import './conversationInitializer.js';
// Import splitViewHandler for Genie slave session split view (auto-initializes on import)
import './handlers/splitViewHandler.js';

// Expose capabilities module globally for resource panel updates
window.capabilitiesModule = capabilitiesModule;

// Session header profile display - uses unified profile tag system
function updateSessionHeaderProfile(defaultProfile, overrideProfile) {
    const headerDefaultProfile = document.getElementById('header-default-profile');
    const headerDefaultProfileTag = document.getElementById('header-default-profile-tag');
    const headerOverrideProfile = document.getElementById('header-override-profile');
    const headerOverrideProfileTag = document.getElementById('header-override-profile-tag');

    // Helper to convert hex to rgba
    const hexToRgba = (hex, alpha) => {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    };

    // Update knowledge indicator based on active profile
    const profile = overrideProfile || defaultProfile;
    updateKnowledgeIndicatorStatus(profile);

    // Update default profile - use CSS custom properties for theme compliance
    if (defaultProfile && defaultProfile.tag) {
        headerDefaultProfileTag.textContent = `@${defaultProfile.tag}`;
        if (defaultProfile.color) {
            const color1 = hexToRgba(defaultProfile.color, 0.25);
            const color2 = hexToRgba(defaultProfile.color, 0.12);
            const borderColor = hexToRgba(defaultProfile.color, 0.4);
            headerDefaultProfile.style.setProperty('--profile-tag-bg', `linear-gradient(135deg, ${color1}, ${color2})`);
            headerDefaultProfile.style.setProperty('--profile-tag-border', borderColor);
        }
        headerDefaultProfile.classList.remove('hidden');
    } else {
        headerDefaultProfile.classList.add('hidden');
        headerDefaultProfile.style.removeProperty('--profile-tag-bg');
        headerDefaultProfile.style.removeProperty('--profile-tag-border');
    }

    // Update override profile - use CSS custom properties for theme compliance
    if (overrideProfile && overrideProfile.tag) {
        headerOverrideProfileTag.textContent = `@${overrideProfile.tag}`;
        if (overrideProfile.color) {
            const color1 = hexToRgba(overrideProfile.color, 0.25);
            const color2 = hexToRgba(overrideProfile.color, 0.12);
            const borderColor = hexToRgba(overrideProfile.color, 0.4);
            headerOverrideProfile.style.setProperty('--profile-tag-bg', `linear-gradient(135deg, ${color1}, ${color2})`);
            headerOverrideProfile.style.setProperty('--profile-tag-border', borderColor);
        }
        headerOverrideProfile.classList.remove('hidden');
    } else {
        headerOverrideProfile.classList.add('hidden');
        headerOverrideProfile.style.removeProperty('--profile-tag-bg');
        headerOverrideProfile.style.removeProperty('--profile-tag-border');
    }
}

// Update knowledge indicator based on all active profiles' knowledge collections
function updateKnowledgeIndicatorStatus(profile) {
    const knowledgeDot = document.getElementById('knowledge-status-dot');
    if (!knowledgeDot) return;
    
    // Check if ANY active-for-consumption profile has knowledge collections
    let hasActiveKnowledgeCollections = false;
    
    if (window.configState && window.configState.profiles) {
        const activeProfiles = window.configState.profiles.filter(p => 
            window.configState.activeForConsumptionProfileIds.includes(p.id)
        );
        
        hasActiveKnowledgeCollections = activeProfiles.some(p => 
            p.knowledgeConfig?.collections?.length > 0
        );
    }
    
    if (hasActiveKnowledgeCollections) {
        knowledgeDot.classList.remove('knowledge-idle', 'knowledge-active');
        knowledgeDot.classList.add('knowledge-configured');
    } else {
        knowledgeDot.classList.remove('knowledge-configured', 'knowledge-active');
        knowledgeDot.classList.add('knowledge-idle');
    }
}

// Make it globally accessible
window.updateSessionHeaderProfile = updateSessionHeaderProfile;
window.updateKnowledgeIndicatorStatus = updateKnowledgeIndicatorStatus;

async function initializeRAGAutoCompletion() {
    const suggestionsContainer = document.getElementById('rag-suggestions-container');
    const profileTagSelector = document.getElementById('profile-tag-selector');
    const activeProfileTag = document.getElementById('active-profile-tag');
    const userInput = document.getElementById('user-input');
    let debounceTimer = null;
    let currentSuggestions = [];
    let selectedIndex = -1;
    let currentProfiles = [];
    let profileSelectedIndex = -1;
    let isShowingProfileSelector = false;

    // Prevent scroll events from propagating to parent when scrolling inside dropdown
    profileTagSelector.addEventListener('wheel', (e) => {
        const { scrollTop, scrollHeight, clientHeight } = profileTagSelector;
        const atTop = scrollTop === 0;
        const atBottom = scrollTop + clientHeight >= scrollHeight;

        // Only prevent default if we're at the boundary and trying to scroll further
        if ((atTop && e.deltaY < 0) || (atBottom && e.deltaY > 0)) {
            e.preventDefault();
        }
        e.stopPropagation();
    }, { passive: false });

    function highlightSuggestion(index) {
        const items = suggestionsContainer.querySelectorAll('.rag-suggestion-item');
        items.forEach((item, idx) => {
            if (idx === index) {
                item.classList.add('rag-suggestion-highlighted');
            } else {
                item.classList.remove('rag-suggestion-highlighted');
            }
        });
    }

    function highlightProfile(index) {
        const items = profileTagSelector.querySelectorAll('.profile-tag-item');
        items.forEach((item, idx) => {
            if (idx === index) {
                item.classList.add('profile-tag-highlighted');
                // Auto-scroll highlighted item into view within the dropdown only
                // Use scrollTop manipulation to avoid scrolling the whole page
                const container = profileTagSelector;
                const itemTop = item.offsetTop;
                const itemBottom = itemTop + item.offsetHeight;
                const containerTop = container.scrollTop;
                const containerBottom = containerTop + container.clientHeight;

                if (itemTop < containerTop) {
                    container.scrollTop = itemTop;
                } else if (itemBottom > containerBottom) {
                    container.scrollTop = itemBottom - container.clientHeight;
                }
            } else {
                item.classList.remove('profile-tag-highlighted');
            }
        });
    }

    function selectSuggestion(index) {
        if (index >= 0 && index < currentSuggestions.length) {
            const currentValue = userInput.value;
            const tagMatch = currentValue.match(/^@(\w+)\s/);
            
            if (tagMatch) {
                // Preserve the @TAG prefix
                userInput.value = tagMatch[0] + currentSuggestions[index];
            } else {
                userInput.value = currentSuggestions[index];
            }
            
            suggestionsContainer.innerHTML = '';
            suggestionsContainer.classList.add('hidden');
            currentSuggestions = [];
            selectedIndex = -1;
        }
    }

    let activeTagPrefix = '';
    let isUpdatingInput = false;
    
    // Expose activeTagPrefix to window for access by other modules
    Object.defineProperty(window, 'activeTagPrefix', {
        get: () => activeTagPrefix,
        set: (value) => { activeTagPrefix = value; }
    });

    function showActiveTagBadge(profile) {
        // Add unified profile tag classes
        activeProfileTag.className = 'profile-tag profile-tag--lg profile-tag--removable';
        activeProfileTag.innerHTML = `
            <span>@${profile.tag}</span>
            <span class="profile-tag__remove" title="Remove profile override">×</span>
        `;

        // Apply provider color via CSS custom properties
        if (profile.color && profile.colorSecondary) {
            const hexToRgba = (hex, alpha) => {
                const r = parseInt(hex.slice(1, 3), 16);
                const g = parseInt(hex.slice(3, 5), 16);
                const b = parseInt(hex.slice(5, 7), 16);
                return `rgba(${r}, ${g}, ${b}, ${alpha})`;
            };
            const color1 = hexToRgba(profile.color, 0.25);
            const color2 = hexToRgba(profile.colorSecondary, 0.12);
            const borderColor = hexToRgba(profile.color, 0.4);
            activeProfileTag.style.setProperty('--profile-tag-bg', `linear-gradient(135deg, ${color1}, ${color2})`);
            activeProfileTag.style.setProperty('--profile-tag-border', borderColor);
            activeProfileTag.style.setProperty('--profile-tag-shadow', `0 2px 8px ${hexToRgba(profile.color, 0.15)}`);
        }

        activeProfileTag.classList.remove('hidden');
        userInput.classList.add('has-tag');
        
        // Store the tag prefix and remove it from visible input
        const currentValue = userInput.value;
        const tagMatch = currentValue.match(/^@\w+\s/);
        if (tagMatch) {
            activeTagPrefix = tagMatch[0];
            isUpdatingInput = true;
            userInput.value = currentValue.substring(tagMatch[0].length);
            isUpdatingInput = false;
        }
        
        // Add click handler for remove button
        const removeBtn = activeProfileTag.querySelector('.profile-tag__remove');
        removeBtn.addEventListener('click', () => {
            activeTagPrefix = '';
            hideActiveTagBadge();
            userInput.focus();
        });
        
        // Update session header to show override (keep default profile visible)
        const defaultProfileId = window.configState?.defaultProfileId;
        const defaultProfile = defaultProfileId && window.configState?.profiles
            ? window.configState.profiles.find(p => p.id === defaultProfileId)
            : null;
        updateSessionHeaderProfile(defaultProfile, profile);

        // Update resource panel to show profile-specific tools/prompts
        updateResourcePanelForProfile(profile.id);
    }

    function hideActiveTagBadge() {
        // Skip if badge is already hidden (prevents unnecessary API calls on each keystroke)
        if (activeProfileTag.classList.contains('hidden')) {
            return;
        }

        activeProfileTag.innerHTML = '';
        activeProfileTag.className = 'hidden';  // Reset all classes
        activeProfileTag.style.removeProperty('--profile-tag-bg');
        activeProfileTag.style.removeProperty('--profile-tag-border');
        activeProfileTag.style.removeProperty('--profile-tag-shadow');
        userInput.classList.remove('has-tag');

        // Clear session header override and restore default
        const defaultProfileId = window.configState?.defaultProfileId;
        if (defaultProfileId && window.configState?.profiles) {
            const defaultProfile = window.configState.profiles.find(p => p.id === defaultProfileId);
            updateSessionHeaderProfile(defaultProfile, null);

            // Restore default profile resources in resource panel
            updateResourcePanelForProfile(defaultProfileId);
        } else {
            // Fallback to generic resources if no default profile
            updateResourcePanelForProfile(null);
        }
    }

    async function updateResourcePanelForProfile(profileId) {
        /**
         * Update the resource panel to show tools/prompts for a specific profile.
         * If profileId is null, restores default profile resources.
         */
        try {
            const authToken = localStorage.getItem('tda_auth_token');
            if (!authToken) return;

            let tools, prompts;

            if (profileId) {
                // Fetch profile-specific resources
                const response = await fetch(`/api/v1/profiles/${profileId}/resources`, {
                    headers: { 'Authorization': `Bearer ${authToken}` }
                });

                if (!response.ok) {
                    console.error('Failed to fetch profile resources');
                    return;
                }

                const data = await response.json();
                tools = data.tools || {};
                prompts = data.prompts || {};

                // Handle Genie profiles: show coordinator info in resource panel
                if (data.profile_type === 'genie') {
                    // Store Genie profile info in state for rendering
                    state.activeGenieProfile = {
                        tag: data.profile_tag,
                        slaveProfiles: data.slave_profiles || []
                    };
                    state.activeRagProfile = null;
                    state.activeLlmOnlyProfile = null;
                    console.log(`🧞 Genie coordinator profile active: @${data.profile_tag}`);
                } else if (data.profile_type === 'rag_focused') {
                    // Store RAG-focused profile info in state for rendering
                    state.activeRagProfile = {
                        tag: data.profile_tag,
                        knowledgeCollections: data.knowledge_collections || []
                    };
                    state.activeGenieProfile = null;
                    state.activeLlmOnlyProfile = null;
                    console.log(`📚 RAG-focused profile active: @${data.profile_tag}`);
                } else if (data.profile_type === 'llm_only') {
                    // Store LLM-only profile info in state for rendering
                    state.activeLlmOnlyProfile = {
                        tag: data.profile_tag,
                        knowledgeCollections: data.knowledge_collections || []
                    };
                    state.activeGenieProfile = null;
                    state.activeRagProfile = null;
                    console.log(`💬 Conversation-focused profile active: @${data.profile_tag}`);
                } else {
                    // Clear special profile info if switching away
                    state.activeGenieProfile = null;
                    state.activeRagProfile = null;
                    state.activeLlmOnlyProfile = null;
                    console.log(`🔍 Resource panel updated for profile: @${data.profile_tag}`);
                }
            } else {
                // Restore default resources
                const [toolsResponse, promptsResponse] = await Promise.all([
                    fetch('/tools', { headers: { 'Authorization': `Bearer ${authToken}` } }),
                    fetch('/prompts', { headers: { 'Authorization': `Bearer ${authToken}` } })
                ]);

                const toolsData = toolsResponse.ok ? await toolsResponse.json() : {};
                const promptsData = promptsResponse.ok ? await promptsResponse.json() : {};

                // Check if response includes profile metadata (for rag_focused/genie/llm_only profiles)
                // The backend returns { tools: {}, profile_type: '...', ... } for special profiles
                if (toolsData.profile_type === 'rag_focused') {
                    tools = toolsData.tools || {};
                    prompts = promptsData.prompts || {};
                    state.activeRagProfile = {
                        tag: toolsData.profile_tag,
                        knowledgeCollections: toolsData.knowledge_collections || []
                    };
                    state.activeGenieProfile = null;
                    state.activeLlmOnlyProfile = null;
                    console.log(`📚 Default profile is RAG-focused: @${toolsData.profile_tag}`);
                } else if (toolsData.profile_type === 'genie') {
                    tools = toolsData.tools || {};
                    prompts = promptsData.prompts || {};
                    state.activeGenieProfile = {
                        tag: toolsData.profile_tag,
                        slaveProfiles: toolsData.slave_profiles || []
                    };
                    state.activeRagProfile = null;
                    state.activeLlmOnlyProfile = null;
                    console.log(`🧞 Default profile is Genie coordinator: @${toolsData.profile_tag}`);
                } else if (toolsData.profile_type === 'llm_only') {
                    tools = toolsData.tools || {};
                    prompts = promptsData.prompts || {};
                    state.activeLlmOnlyProfile = {
                        tag: toolsData.profile_tag,
                        knowledgeCollections: toolsData.knowledge_collections || []
                    };
                    state.activeGenieProfile = null;
                    state.activeRagProfile = null;
                    console.log(`💬 Default profile is Conversation-focused: @${toolsData.profile_tag}`);
                } else {
                    // Normal profile - response is tools/prompts directly
                    tools = toolsData;
                    prompts = promptsData;
                    state.activeGenieProfile = null;
                    state.activeRagProfile = null;
                    state.activeLlmOnlyProfile = null;
                    console.log('🔄 Resource panel restored to default profile');
                }
            }

            // Update the resource panel with new data
            state.resourceData.tools = tools;
            state.resourceData.prompts = prompts;

            // Trigger re-render of resource panels (using existing state data, not fetching)
            if (window.capabilitiesModule) {
                window.capabilitiesModule.renderResourcePanel('tools');
                window.capabilitiesModule.renderResourcePanel('prompts');
            }

        } catch (error) {
            console.error('Error updating resource panel:', error);
        }
    }

    // Expose globally for use by configurationHandler when default profile changes
    window.updateResourcePanelForProfile = updateResourcePanelForProfile;

    function updateTagBadge() {
        if (isUpdatingInput) return;
        
        // Check if we have an active tag
        if (activeTagPrefix) {
            // Tag is active, badge should be showing
            return;
        }
        
        // Check if input starts with @TAG
        const inputValue = userInput.value;
        const tagMatch = inputValue.match(/^@(\w+)\s/);
        
        if (tagMatch && window.configState?.profiles) {
            const tag = tagMatch[1].toUpperCase();
            const profile = window.configState.profiles.find(p => p.tag === tag);
            if (profile) {
                showActiveTagBadge(profile);
                return;
            }
        }
        
        // No valid tag found, hide badge
        if (!activeTagPrefix) {
            hideActiveTagBadge();
        }
    }

    function selectProfile(index) {
        if (index >= 0 && index < currentProfiles.length) {
            const profile = currentProfiles[index];
            
            // Clear the input (remove the @ or partial tag)
            isUpdatingInput = true;
            userInput.value = '';
            isUpdatingInput = false;
            
            // Set up the badge and store the tag prefix
            activeTagPrefix = `@${profile.tag} `;
            activeProfileTag.innerHTML = `
                <span style="font-size: 13px;">@${profile.tag}</span>
                <span class="tag-remove" title="Remove profile override">×</span>
            `;
            
            // Apply provider color
            if (profile.color && profile.colorSecondary) {
                const hexToRgba = (hex, alpha) => {
                    const r = parseInt(hex.slice(1, 3), 16);
                    const g = parseInt(hex.slice(3, 5), 16);
                    const b = parseInt(hex.slice(5, 7), 16);
                    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
                };
                const color1 = hexToRgba(profile.color, 0.25);
                const color2 = hexToRgba(profile.colorSecondary, 0.15);
                activeProfileTag.style.background = `linear-gradient(135deg, ${color1}, ${color2})`;
                activeProfileTag.style.boxShadow = `0 2px 10px ${hexToRgba(profile.color, 0.2)}`;
            }
            
            activeProfileTag.classList.remove('hidden');
            userInput.classList.add('has-tag');
            
            // Add click handler for remove button
            const removeBtn = activeProfileTag.querySelector('.tag-remove');
            removeBtn.addEventListener('click', () => {
                activeTagPrefix = '';
                hideActiveTagBadge();
                userInput.focus();
            });
            
            // Update session header to show override (keep default profile visible)
            const defaultProfileId = window.configState?.defaultProfileId;
            const defaultProfile = defaultProfileId && window.configState?.profiles
                ? window.configState.profiles.find(p => p.id === defaultProfileId)
                : null;
            updateSessionHeaderProfile(defaultProfile, profile);

            // Update resource panel to show profile-specific tools/prompts
            updateResourcePanelForProfile(profile.id);

            profileTagSelector.innerHTML = '';
            profileTagSelector.classList.add('hidden');
            currentProfiles = [];
            profileSelectedIndex = -1;
            isShowingProfileSelector = false;
            userInput.focus();
        }
    }

    function showSuggestions(questionsToShow) {
        currentSuggestions = questionsToShow;
        selectedIndex = questionsToShow.length > 0 ? 0 : -1;

        if (questionsToShow.length === 0) {
            suggestionsContainer.innerHTML = '';
            suggestionsContainer.classList.add('hidden');
            return;
        }

        suggestionsContainer.innerHTML = '';
        questionsToShow.forEach((q, index) => {
            const suggestionItem = document.createElement('div');
            suggestionItem.className = 'rag-suggestion-item';
            if (index === 0) {
                suggestionItem.classList.add('rag-suggestion-highlighted');
            }
            suggestionItem.textContent = q;
            suggestionItem.addEventListener('mousedown', (e) => {
                e.preventDefault();
                selectSuggestion(index);
                userInput.focus();
            });
            suggestionItem.addEventListener('mouseenter', () => {
                selectedIndex = index;
                highlightSuggestion(index);
            });
            suggestionsContainer.appendChild(suggestionItem);
        });
        suggestionsContainer.classList.remove('hidden');
    }

    function showProfileSelector(profiles) {
        currentProfiles = profiles;
        const defaultProfileId = window.configState?.defaultProfileId;
        
        // Set initial selection to first non-default profile
        if (profiles.length > 0) {
            const firstSelectableIndex = profiles.findIndex(p => p.id !== defaultProfileId);
            profileSelectedIndex = firstSelectableIndex >= 0 ? firstSelectableIndex : -1;
        } else {
            profileSelectedIndex = -1;
        }
        
        isShowingProfileSelector = true;

        if (profiles.length === 0) {
            profileTagSelector.innerHTML = '';
            profileTagSelector.classList.add('hidden');
            return;
        }

        profileTagSelector.innerHTML = '';
        
        profiles.forEach((profile, index) => {
            const isDefault = profile.id === defaultProfileId;
            const profileItem = document.createElement('div');
            profileItem.className = 'profile-tag-item';
            
            // Make default profile non-selectable
            if (isDefault) {
                profileItem.classList.add('profile-tag-disabled');
                profileItem.style.opacity = '0.6';
                profileItem.style.cursor = 'not-allowed';
            } else if (index === 1 || (index === 0 && !isDefault)) {
                // Highlight first selectable profile
                profileItem.classList.add('profile-tag-highlighted');
            }

            const header = document.createElement('div');
            header.className = 'profile-tag-header';

            const badge = document.createElement('span');
            badge.className = 'profile-tag profile-tag--md profile-tag-badge';
            badge.textContent = `@${profile.tag}`;

            // Apply provider color via CSS custom properties
            if (profile.color && profile.colorSecondary) {
                const hexToRgba = (hex, alpha) => {
                    const r = parseInt(hex.slice(1, 3), 16);
                    const g = parseInt(hex.slice(3, 5), 16);
                    const b = parseInt(hex.slice(5, 7), 16);
                    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
                };
                badge.style.setProperty('--profile-tag-bg', `linear-gradient(135deg, ${hexToRgba(profile.color, 0.25)}, ${hexToRgba(profile.color, 0.12)})`);
                badge.style.setProperty('--profile-tag-border', hexToRgba(profile.color, 0.4));
            }

            const name = document.createElement('span');
            name.className = 'profile-tag-name';
            name.textContent = profile.name;

            // Add default indicator if this is the default profile
            if (isDefault) {
                const defaultIndicator = document.createElement('span');
                defaultIndicator.className = 'profile-default-indicator';
                defaultIndicator.textContent = '★ Default';
                defaultIndicator.title = 'Default Profile (already active)';
                header.appendChild(badge);
                header.appendChild(name);
                header.appendChild(defaultIndicator);
            } else {
                header.appendChild(badge);
                header.appendChild(name);
            }
            
            profileItem.appendChild(header);

            if (profile.description) {
                const description = document.createElement('div');
                description.className = 'profile-tag-description';
                description.textContent = profile.description;
                profileItem.appendChild(description);
            }

            // Only add click handlers for non-default profiles
            if (!isDefault) {
                profileItem.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    selectProfile(index);
                });
                profileItem.addEventListener('mouseenter', () => {
                    profileSelectedIndex = index;
                    highlightProfile(index);
                });
            }

            profileTagSelector.appendChild(profileItem);
        });
        profileTagSelector.classList.remove('hidden');
    }

    function hideProfileSelector() {
        profileTagSelector.innerHTML = '';
        profileTagSelector.classList.add('hidden');
        currentProfiles = [];
        profileSelectedIndex = -1;
        isShowingProfileSelector = false;
    }

    async function fetchAndShowSuggestions(queryText) {
        if (!queryText || queryText.length < 2) {
            showSuggestions([]);
            return;
        }

        // Determine which profile to use for collection filtering
        let profileId = window.configState?.defaultProfileId || null;
        
        // Priority 1: Check if there's an active profile badge (user selected via @TAG)
        if (activeTagPrefix && window.configState?.profiles) {
            const tag = activeTagPrefix.replace('@', '').trim().toUpperCase();
            const overrideProfile = window.configState.profiles.find(p => p.tag.toUpperCase() === tag);
            if (overrideProfile) {
                profileId = overrideProfile.id;
            }
        }
        // Priority 2: Check if there's an active profile override from previous message
        else if (window.activeProfileOverrideId) {
            profileId = window.activeProfileOverrideId;
        }
        // Priority 3: Check if query text starts with @TAG (not yet selected)
        else {
            const tagMatch = queryText.match(/^@(\w+)\s/);
            if (tagMatch && window.configState?.profiles) {
                const tag = tagMatch[1].toUpperCase();
                const overrideProfile = window.configState.profiles.find(p => p.tag.toUpperCase() === tag);
                if (overrideProfile) {
                    profileId = overrideProfile.id;
                    // Remove @TAG from query for autocomplete search
                    queryText = queryText.substring(tagMatch[0].length);
                }
            }
        }
        
        // Fetch semantically ranked questions from backend
        const questions = await API.fetchRAGQuestions(queryText, profileId, 5);
        showSuggestions(questions);
    }

    if (suggestionsContainer && userInput) {
        userInput.addEventListener('focus', () => {
            const inputValue = userInput.value.trim();
            if (inputValue.length >= 2) {
                fetchAndShowSuggestions(inputValue);
            }
        });

        userInput.addEventListener('input', () => {
            const inputValue = userInput.value;

            // Don't update tag badge if we're in the middle of programmatic changes
            if (!isUpdatingInput) {
                // If we have an active tag, check if the full message (prefix + input) still has a valid tag
                if (activeTagPrefix) {
                    // Reconstruct what the full message would look like
                    const fullMessage = activeTagPrefix + inputValue;
                    const tagMatch = fullMessage.match(/^@(\w+)\s/);

                    if (!tagMatch) {
                        // Tag pattern is no longer valid - user deleted it
                        activeTagPrefix = '';
                        hideActiveTagBadge();
                    }
                } else {
                    // No active tag - check if user is adding one
                    updateTagBadge();
                }
            }
            
            // Clear previous timer
            if (debounceTimer) {
                clearTimeout(debounceTimer);
            }

            // Check if user typed @ at the start (profile tag selector)
            // But only if we don't have an active tag badge already
            if (!activeTagPrefix && inputValue.startsWith('@') && !inputValue.includes(' ')) {
                // User is typing @TAG but hasn't added space yet - show profile selector
                hideProfileSelector();
                showSuggestions([]);
                
                // Show only active profiles with tags
                const profiles = window.configState?.profiles || [];
                const activeIds = window.configState?.activeForConsumptionProfileIds || [];
                const defaultProfileId = window.configState?.defaultProfileId;
                
                const activeProfilesWithTags = profiles.filter(p => 
                    p.tag && activeIds.includes(p.id)
                );
                
                // Sort profiles: default first, then others
                const sortedProfiles = activeProfilesWithTags.sort((a, b) => {
                    if (a.id === defaultProfileId) return -1;
                    if (b.id === defaultProfileId) return 1;
                    return 0;
                });
                
                if (inputValue === '@') {
                    // Show all active profiles
                    showProfileSelector(sortedProfiles);
                } else {
                    // Filter active profiles by partial tag match
                    const partialTag = inputValue.substring(1).toUpperCase();
                    const filteredProfiles = sortedProfiles.filter(p => 
                        p.tag.toUpperCase().startsWith(partialTag)
                    );
                    showProfileSelector(filteredProfiles);
                }
                return;
            }

            // Hide profile selector if we're past the tag selection phase
            if (isShowingProfileSelector) {
                hideProfileSelector();
            }
            
            const trimmedValue = inputValue.trim();
            if (trimmedValue.length >= 2) {
                // Debounce API calls (300ms delay)
                debounceTimer = setTimeout(() => {
                    fetchAndShowSuggestions(trimmedValue);
                }, 300);
            } else {
                showSuggestions([]);
            }
        });

        userInput.addEventListener('keydown', (e) => {
            // Handle backspace to remove active profile tag
            if (e.key === 'Backspace' && activeTagPrefix && userInput.value === '') {
                e.preventDefault();
                activeTagPrefix = '';
                hideActiveTagBadge();
                return;
            }
            
            // Handle profile selector navigation
            if (isShowingProfileSelector && currentProfiles.length > 0) {
                const defaultProfileId = window.configState?.defaultProfileId;
                const selectableProfiles = currentProfiles.filter(p => p.id !== defaultProfileId);
                
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    // If no selectable profiles, don't navigate
                    if (selectableProfiles.length === 0) return;
                    
                    let nextIndex = (profileSelectedIndex + 1) % currentProfiles.length;
                    let iterations = 0;
                    const maxIterations = currentProfiles.length;
                    
                    // Skip default profile
                    while (iterations < maxIterations && currentProfiles[nextIndex].id === defaultProfileId) {
                        nextIndex = (nextIndex + 1) % currentProfiles.length;
                        iterations++;
                    }
                    
                    // Only update if we found a selectable profile
                    if (iterations < maxIterations) {
                        profileSelectedIndex = nextIndex;
                        highlightProfile(profileSelectedIndex);
                    }
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    // If no selectable profiles, don't navigate
                    if (selectableProfiles.length === 0) return;
                    
                    let prevIndex = (profileSelectedIndex - 1 + currentProfiles.length) % currentProfiles.length;
                    let iterations = 0;
                    const maxIterations = currentProfiles.length;
                    
                    // Skip default profile
                    while (iterations < maxIterations && currentProfiles[prevIndex].id === defaultProfileId) {
                        prevIndex = (prevIndex - 1 + currentProfiles.length) % currentProfiles.length;
                        iterations++;
                    }
                    
                    // Only update if we found a selectable profile
                    if (iterations < maxIterations) {
                        profileSelectedIndex = prevIndex;
                        highlightProfile(profileSelectedIndex);
                    }
                } else if ((e.key === 'Tab' || e.key === 'Enter') && profileSelectedIndex >= 0) {
                    e.preventDefault();
                    // Only select if not default profile
                    if (currentProfiles[profileSelectedIndex].id !== defaultProfileId) {
                        selectProfile(profileSelectedIndex);
                    }
                } else if (e.key === 'Escape') {
                    hideProfileSelector();
                }
                return;
            }

            // Handle autocomplete navigation
            if (currentSuggestions.length === 0) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIndex = (selectedIndex + 1) % currentSuggestions.length;
                highlightSuggestion(selectedIndex);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIndex = (selectedIndex - 1 + currentSuggestions.length) % currentSuggestions.length;
                highlightSuggestion(selectedIndex);
            } else if (e.key === 'Tab' && selectedIndex >= 0) {
                e.preventDefault();
                selectSuggestion(selectedIndex);
            } else if (e.key === 'Escape') {
                suggestionsContainer.innerHTML = '';
                suggestionsContainer.classList.add('hidden');
                currentSuggestions = [];
                selectedIndex = -1;
            }
        });

        userInput.addEventListener('blur', () => {
            setTimeout(() => {
                suggestionsContainer.innerHTML = '';
                suggestionsContainer.classList.add('hidden');
                currentSuggestions = [];
                selectedIndex = -1;
                hideProfileSelector();
            }, 150);
        });
    }
}

/**
 * Extract user ID from JWT authentication for SSE notifications.
 * User identification is now handled via JWT authentication tokens.
 */
function ensureUserUUID() {
    // Extract user ID from JWT-stored user object
    if (window.authClient) {
        const user = window.authClient.getUser();
        if (user && user.id) {
            state.userUUID = user.id;
            console.log('[Auth] User ID extracted from JWT:', user.id);
        } else {
            console.warn('[Auth] No user ID found in session');
        }
    } else {
        console.warn('[Auth] authClient not initialized');
    }
}

/**
 * Fetches the current star count for the GitHub repository and updates the UI.
 * GitHub API is enabled by default. Use --nogitcall flag to disable.
 * Hides the button completely if disabled.
 */
async function fetchGitHubStarCount() {
    const starButtonElement = document.querySelector('a[href="https://github.com/rgeissen/uderia"]');
    const starCountElement = document.getElementById('github-star-count');
    const starIconElement = starButtonElement ? starButtonElement.querySelector('svg') : null;
    
    if (!starCountElement || !starButtonElement) {
        console.error('fetchGitHubStarCount: star elements not found');
        return;
    }

    // Check if GitHub API is enabled
    try {
        const settingsResponse = await fetch('/app-settings');
        if (settingsResponse.ok) {
            const settings = await settingsResponse.json();
            console.log('GitHub API enabled status:', settings.github_api_enabled);
            if (!settings.github_api_enabled) {
                console.log('GitHub API disabled. Use default (no --nogitcall flag) to enable. Button hidden.');
                starButtonElement.style.display = 'none';
                return;
            }
            // If enabled, ensure button is visible
            starButtonElement.style.display = 'flex';
        }
    } catch (error) {
        console.error('Error checking app settings:', error);
        starButtonElement.style.display = 'none';
        return;
    }

    try {
        console.log('Fetching GitHub star count from API...');
        const response = await fetch('https://api.github.com/repos/rgeissen/uderia', {
            method: 'GET',
            headers: {
                'Accept': 'application/vnd.github.v3+json'
            },
            mode: 'cors'
        });
        
        
        if (response.ok) {
            const data = await response.json();
            const starCount = data.stargazers_count || 0;
            console.log('GitHub star count fetched:', starCount);
            // Format the number with comma separators
            starCountElement.textContent = starCount.toLocaleString('en-US');
            
            // Update star icon based on count (filled if > 0, outline if 0)
            if (starIconElement) {
                if (starCount > 0) {
                    starIconElement.setAttribute('fill', 'currentColor');
                } else {
                    starIconElement.setAttribute('fill', 'none');
                    starIconElement.setAttribute('stroke', 'currentColor');
                    starIconElement.setAttribute('stroke-width', '1.5');
                }
            }
            
        } else {
            const errorText = await response.text();
            console.error('GitHub API response not OK:', response.status, errorText);
            starCountElement.textContent = '-';
        }
    } catch (error) {
        console.error('Error fetching GitHub star count:', error);
        console.error('Error details:', error.message, error.stack);
        starCountElement.textContent = '-';
    }
}

// REMOVED: loadInitialConfig() function - obsolete with new configuration system
// The new configuration system (configState) automatically loads from localStorage
// and doesn't need manual form population

/**
 * Update Intelligence and Marketplace navigation state based on current active profile
 * Disables these views if no profile is set as default (unconfigured system)
 */
function updatePlannerRepositoryNavigation() {
    const intelligenceNavLink = document.getElementById('view-switch-rag-maintenance');
    const marketplaceNavLink = document.getElementById('view-switch-rag-marketplace');
    
    if (!intelligenceNavLink || !marketplaceNavLink) {
        console.warn('[PlannerRepository] Navigation links not found in DOM');
        return;
    }
    
    // Get the currently active (default) profile
    const defaultProfileId = window.configState?.defaultProfileId;
    
    console.log('[PlannerRepository] Checking navigation state. defaultProfileId:', defaultProfileId);
    
    // Disable navigation if no default profile is set
    if (!defaultProfileId) {
        intelligenceNavLink.classList.add('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
        marketplaceNavLink.classList.add('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
        intelligenceNavLink.setAttribute('title', 'Set a default profile to access Planner Repository');
        marketplaceNavLink.setAttribute('title', 'Set a default profile to access Planner Repository Marketplace');
        console.log('[PlannerRepository] Navigation DISABLED - no default profile set');
        return;
    }
    
    // If we reach here, a default profile is set - enable navigation
    {
        // Enable Intelligence and Marketplace views
        intelligenceNavLink.classList.remove('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
        marketplaceNavLink.classList.remove('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
        
        // Restore original titles
        intelligenceNavLink.setAttribute('title', '');
        marketplaceNavLink.setAttribute('title', '');
        
        console.log('[PlannerRepository] Navigation ENABLED - default profile is set:', defaultProfileId);
    }
}

// Export for use in other modules
window.updatePlannerRepositoryNavigation = updatePlannerRepositoryNavigation;

// Define welcome screen functions BEFORE DOMContentLoaded to ensure they're available
function hideWelcomeScreen() {
    const welcomeScreen = document.getElementById('welcome-screen');
    const chatLog = document.getElementById('chat-log');
    const chatFooter = document.getElementById('chat-footer');
    const chatContainer = document.getElementById('chat-container');
    
    if (welcomeScreen && chatLog) {
        welcomeScreen.classList.add('hidden');
        chatLog.classList.remove('hidden');
        chatLog.style.display = 'block';  // Ensure it's visible
        if (chatFooter) {
            chatFooter.classList.remove('hidden');
            chatFooter.style.display = 'block';  // Ensure it's visible
        }
        if (chatContainer) {
            chatContainer.style.display = 'flex';
            chatContainer.style.flexDirection = 'column';
        }
        
        // Show all panels (History, Live Status, Resource) when welcome screen is hidden
        document.querySelectorAll('[data-requires-config="true"]').forEach(panel => {
            panel.style.display = '';  // Reset to default (CSS will control visibility)
        });
    }
}

// Make function available globally
window.hideWelcomeScreen = hideWelcomeScreen;

document.addEventListener('DOMContentLoaded', async () => {
    const savedShowWelcomeScreen = localStorage.getItem('showWelcomeScreenAtStartup');
    state.showWelcomeScreenAtStartup = savedShowWelcomeScreen === null ? true : savedShowWelcomeScreen === 'true';
    const welcomeScreenCheckbox = document.getElementById('toggle-welcome-screen-checkbox');
    const welcomeScreenPopupCheckbox = document.getElementById('welcome-screen-show-at-startup-checkbox');
    if (welcomeScreenCheckbox) {
        welcomeScreenCheckbox.checked = state.showWelcomeScreenAtStartup;
    }
    if (welcomeScreenPopupCheckbox) {
        welcomeScreenPopupCheckbox.checked = state.showWelcomeScreenAtStartup;
    }

    ensureUserUUID(); // Get/Set the User UUID right away
    subscribeToNotifications();
    initializeRAGAutoCompletion();
    initializeMarketplace();
    
    // Make marketplace functions globally available
    window.marketplaceHandler = {
        unsubscribeFromCollection: unsubscribeFromCollection
    };
    
    // Restore current session ID from localStorage if available
    const savedSessionId = localStorage.getItem('currentSessionId');
    if (savedSessionId) {
        state.currentSessionId = savedSessionId;
        console.log('[Startup] Restored session ID from localStorage:', savedSessionId);
    }

    // Fetch GitHub star count
    fetchGitHubStarCount();

    // REMOVED: loadInitialConfig() - obsolete with new configuration system
    // The new configuration system uses configState which loads from localStorage automatically

    // Initialize all event listeners first to ensure they are ready.
    initializeEventListeners();
    initializeVoiceRecognition();
    
    // Import and wire repository tabs
    const { wireRepositoryTabs } = await import('./eventHandlers.js?v=3.4');
    wireRepositoryTabs();
    
    // Initialize utility sessions filter for sidebar
    const { initializeUtilitySessionsFilter } = await import('./handlers/sessionManagement.js?v=3.2');
    initializeUtilitySessionsFilter();
    
    // Initialize Execution Dashboard
    if (window.ExecutionDashboard) {
        window.executionDashboard = new window.ExecutionDashboard();
    } else {
    }

    // Initialize new configuration UI (async - loads MCP servers from backend)
    await initializeConfigurationUI();

    // Update resource panel with default profile after configuration loads
    if (window.configState?.defaultProfileId) {
        await updateResourcePanelForProfile(window.configState.defaultProfileId);
        console.log('[Startup] Resource panel initialized with default profile:', window.configState.defaultProfileId);
    }

    // Hide prompt editor menu item if it exists (may be removed from UI)
    if (DOM.promptEditorButton?.parentElement) {
        DOM.promptEditorButton.parentElement.style.display = 'none';
    }

    try {
        // Use the app config that was already fetched in index.html
        // Wait for it to be available if it hasn't loaded yet
        let attempts = 0;
        while (!window.appConfigData && attempts < 50) {
            await new Promise(resolve => setTimeout(resolve, 100));
            attempts++;
        }
        
        if (window.appConfigData) {
            state.appConfig = window.appConfigData;
        } else {
            // Fallback: fetch directly if window.appConfigData isn't available
            const token = localStorage.getItem('tda_auth_token');
            const res = await fetch('/app-config', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            state.appConfig = await res.json();
        }

        await API.checkAndUpdateDefaultPrompts();

        const chartingIntensityContainer = document.getElementById('charting-intensity-container');
        if (!state.appConfig.charting_enabled) {
            chartingIntensityContainer.style.display = 'none';
        } else {
            DOM.chartingIntensitySelect.value = state.appConfig.default_charting_intensity || 'medium';
        }

        if (state.appConfig.voice_conversation_enabled) {
            DOM.voiceInputButton.classList.remove('hidden');
            DOM.keyObservationsToggleButton.classList.remove('hidden');
        }

        if (DOM.ccrStatusDot) {
            if (!state.appConfig.rag_enabled) {
                DOM.ccrStatusDot.parentElement.style.display = 'none';
            } else {
                DOM.ccrStatusDot.parentElement.style.display = 'flex';
            }
        }

    } catch (e) {
        console.error("Could not fetch app config", e);
    }

    // Initialize panels as hidden and disabled until conversation pane is entered
    // Panels will be configured based on admin settings when entering conversation view
    DOM.sessionHistoryPanel.style.display = 'none';
    DOM.statusWindow.style.display = 'none';
    DOM.toolHeader.style.display = 'none';
    DOM.toggleHistoryButton.style.display = 'none';
    DOM.toggleStatusButton.style.display = 'none';
    DOM.toggleHeaderButton.style.display = 'none';

    try {
        const status = await API.checkServerStatus();
        
        // Note: Credentials are ALWAYS stored in localStorage
        
        // Update CCR (Champion Case Retrieval) indicator based on status
        if (DOM.ccrStatusDot && state.appConfig.rag_enabled) {
            if (status.rag_active) {
                DOM.ccrStatusDot.classList.remove('disconnected');
                DOM.ccrStatusDot.classList.add('connected');
            } else {
                DOM.ccrStatusDot.classList.remove('connected');
                DOM.ccrStatusDot.classList.add('disconnected');
            }
        }

        if (status.isConfigured) {

            // Check authentication status - show welcome screen for unauthenticated users
            const isAuthenticated = window.authClient && window.authClient.isAuthenticated();
            
            // Check if admin has enabled "always show welcome screen"
            const alwaysShowWelcome = state.appConfig?.window_defaults?.always_show_welcome_screen || false;
            
            if (!isAuthenticated || alwaysShowWelcome) {
                // Show welcome screen for unauthenticated users or if admin setting enabled
                await showWelcomeScreen();
            } else {
                // Normal flow - finalize configuration and show chat interface
                // NOTE: With new config UI, we don't need to pre-fill old form fields
                // The configurationHandler manages its own state via localStorage
                
                // Old code removed:
                // DOM.llmProviderSelect.value = status.provider;
                // DOM.mcpServerNameInput.value = status.mcp_server.name;
                // await loadCredentialsAndModels();

                const currentConfig = { provider: status.provider, model: status.model };
                // Pass the mcp_server details from status to ensure they are used if re-finalizing
                currentConfig.mcp_server = status.mcp_server;
                await finalizeConfiguration(currentConfig, true);

                // handleViewSwitch is now called inside finalizeConfiguration
            }

        } else {
            // The new configuration UI handles its own state
            // No need to pre-fill old form fields
            const savedTtsCreds = localStorage.getItem('ttsCredentialsJson');
            if (savedTtsCreds && DOM.ttsCredentialsJsonTextarea) {
                DOM.ttsCredentialsJsonTextarea.value = savedTtsCreds;
            }
            
            // Show welcome screen in conversation view
            await showWelcomeScreen();
        }
    } catch (startupError) {
        console.error("DEBUG: Error during startup configuration/session loading. Showing config modal.", startupError);
        // Fallback to showing credentials view
        try {
             const savedTtsCreds = localStorage.getItem('ttsCredentialsJson');
             if (savedTtsCreds && DOM.ttsCredentialsJsonTextarea) { 
                 DOM.ttsCredentialsJsonTextarea.value = savedTtsCreds; 
             }
             // NOTE: Old loadCredentialsAndModels() removed - new config UI handles this
        } catch (prefillError) {
            console.error("DEBUG: Error during fallback pre-fill:", prefillError);
        }
        
        handleViewSwitch('credentials-view');
    }

    // Panel setup will be done when entering conversation pane
    // (panels remain hidden during welcome screen)

    const savedKeyObservationsMode = localStorage.getItem('keyObservationsMode');
    if (['autoplay-off', 'autoplay-on', 'off'].includes(savedKeyObservationsMode)) {
        state.keyObservationsMode = savedKeyObservationsMode;
    }

    UI.updateHintAndIndicatorState();
    UI.updateVoiceModeUI();
    UI.updateKeyObservationsModeUI();
    
    // Update Planner Repository navigation based on profile state
    // Need to wait a bit for configState to be initialized
    setTimeout(() => {
        if (typeof updatePlannerRepositoryNavigation === 'function') {
            updatePlannerRepositoryNavigation();
        }
    }, 500);

    // Save user preferences before page unloads
    window.addEventListener('beforeunload', () => {
        localStorage.setItem('showWelcomeScreenAtStartup', state.showWelcomeScreenAtStartup);
    });
});

// ============================================================================
// PANEL MANAGEMENT
// ============================================================================

/**
 * Initialize panels based on admin window defaults
 * Called when entering conversation pane (not during welcome screen)
 */
function initializePanels() {
    const windowDefaults = state.appConfig?.window_defaults || {};
    
    console.log('[Panel Init] Initializing panels with defaults:', windowDefaults);
    
    // Setup each panel with admin settings
    DOM.toggleHistoryCheckbox.checked = windowDefaults.session_history_default_mode === 'expanded';
    setupPanelToggle(DOM.toggleHistoryButton, DOM.sessionHistoryPanel, DOM.toggleHistoryCheckbox, DOM.historyCollapseIcon, DOM.historyExpandIcon, windowDefaults);

    DOM.toggleHeaderCheckbox.checked = windowDefaults.resources_default_mode === 'expanded';
    setupPanelToggle(DOM.toggleHeaderButton, DOM.toolHeader, DOM.toggleHeaderCheckbox, DOM.headerCollapseIcon, DOM.headerExpandIcon, windowDefaults);

    DOM.toggleStatusCheckbox.checked = windowDefaults.status_default_mode === 'expanded';
    setupPanelToggle(DOM.toggleStatusButton, DOM.statusWindow, DOM.toggleStatusCheckbox, DOM.statusCollapseIcon, DOM.statusExpandIcon, windowDefaults);
    
    console.log('[Panel Init] Panels initialized');
}

// Make initializePanels globally accessible
window.initializePanels = initializePanels;
console.log('[main.js] window.initializePanels is now available:', typeof window.initializePanels);

// ============================================================================
// WELCOME SCREEN MANAGEMENT
// ============================================================================

/**
 * Show the welcome screen for unconfigured applications
 */
async function showWelcomeScreen() {
    const welcomeScreen = document.getElementById('welcome-screen');
    const chatLog = document.getElementById('chat-log');
    const chatFooter = document.getElementById('chat-footer');
    const welcomeBtn = document.getElementById('welcome-configure-btn');
    const welcomeBtnText = document.getElementById('welcome-button-text');
    const welcomeCogwheel = document.getElementById('welcome-cogwheel-icon');
    const welcomeSubtext = document.querySelector('.welcome-subtext');
    const reconfigureLink = document.getElementById('welcome-reconfigure-link');
    const welcomeCheckbox = document.getElementById('welcome-screen-show-at-startup-checkbox');
    
    // Populate disabled capabilities section
    populateWelcomeDisabledCapabilities();
    
    // Sync checkbox state with user preference
    if (welcomeCheckbox) {
        welcomeCheckbox.checked = state.showWelcomeScreenAtStartup;
    }
    
    if (welcomeScreen && chatLog) {
        welcomeScreen.classList.remove('hidden');
        chatLog.classList.add('hidden');
        // Hide chat input footer when showing welcome screen
        if (chatFooter) {
            chatFooter.classList.add('hidden');
        }
        
        // Hide all panels (History, Live Status, Resource) when welcome screen is shown
        document.querySelectorAll('[data-requires-config="true"]').forEach(panel => {
            panel.style.display = 'none';
        });
    }
    
    // Check if user has previously saved configurations
    // For tool_enabled: MCP server + LLM required
    // For llm_only/rag_focused: LLM only required
    let hasSavedConfig = false;
    let configDetails = '';

    try {
        const token = localStorage.getItem('tda_auth_token');

        // Get default profile to determine requirements
        const defaultProfile = window.configState?.defaultProfileId
            ? window.configState.profiles?.find(p => p.id === window.configState.defaultProfileId)
            : null;

        const profileType = defaultProfile?.profile_type || 'tool_enabled';
        const activeLLM = configState.getActiveLLMConfiguration();

        if (profileType === 'tool_enabled') {
            // Tool Focused: Requires MCP server + LLM
            const response = await fetch('/api/v1/mcp/servers', {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const data = await response.json();
                const hasMCPServer = data && data.servers && data.servers.length > 0;

                if (hasMCPServer && data.active_server_id) {
                    const activeServer = data.servers.find(s => s.id === data.active_server_id);
                    if (activeServer) {
                        const mcpName = activeServer.name || 'Unknown Server';

                        if (activeLLM) {
                            const llmProvider = activeLLM.provider || 'Unknown Provider';
                            const llmModel = activeLLM.model || 'Unknown Model';
                            configDetails = `${mcpName} • ${llmProvider} / ${llmModel}`;
                            hasSavedConfig = true;
                        } else {
                            configDetails = `${mcpName} • LLM not configured`;
                            hasSavedConfig = false;
                        }
                    }
                }
            }
        } else {
            // Conversation Focused or RAG Focused: Only LLM required
            if (activeLLM) {
                const llmProvider = activeLLM.provider || 'Unknown Provider';
                const llmModel = activeLLM.model || 'Unknown Model';
                const profileName = defaultProfile?.name || 'Conversation';
                configDetails = `${profileName} • ${llmProvider} / ${llmModel}`;
                hasSavedConfig = true;
            } else {
                configDetails = 'LLM not configured';
                hasSavedConfig = false;
            }
        }
    } catch (error) {
        console.error("Error checking for saved configurations:", error);
    }

    // Check if default profile exists and is valid
    let isDefaultProfileValid = false;
    if (window.configState?.defaultProfileId) {
        try {
            console.log('[Welcome Screen] Testing default profile:', window.configState.defaultProfileId);
            const { testProfile } = await import('./api.js');
            const result = await testProfile(window.configState.defaultProfileId);
            
            // Check if all tests passed (accept both 'success' and 'info' as valid)
            // 'info' status is used for optional features (e.g., RAG collections in conversation profiles)
            isDefaultProfileValid = Object.values(result.results).every(r =>
                r.status === 'success' || r.status === 'info'
            );
            console.log('[Welcome Screen] Default profile validation result:', isDefaultProfileValid);
            
            if (!isDefaultProfileValid) {
                console.warn('[Welcome Screen] Default profile validation failed:', result.results);
            }
        } catch (error) {
            console.error('[Welcome Screen] Error testing default profile:', error);
            isDefaultProfileValid = false;
        }
    }
    
    // Update button text based on whether user has a valid default profile
    if (welcomeBtnText) {
        const buttonText = (hasSavedConfig && isDefaultProfileValid) ? 'Start Conversation' : 'Configure Application';
        welcomeBtnText.textContent = buttonText;
    }
    
    // Update subtext with configuration details or default message
    if (welcomeSubtext) {
        if (hasSavedConfig && isDefaultProfileValid && configDetails) {
            welcomeSubtext.textContent = configDetails;
        } else if (hasSavedConfig && !isDefaultProfileValid) {
            welcomeSubtext.textContent = "Default profile needs validation. Please check your credentials.";
        } else {
            welcomeSubtext.textContent = "Please activate a Profile";
        }
    }
    
    // Show/hide reconfigure link based on saved config
    if (reconfigureLink) {
        if (hasSavedConfig) {
            reconfigureLink.classList.remove('hidden');
        } else {
            reconfigureLink.classList.add('hidden');
        }
        
        // Wire up the reconfigure link
        if (!reconfigureLink.dataset._wired) {
            reconfigureLink.addEventListener('click', (e) => {
                e.preventDefault();
                handleViewSwitch('credentials-view');
            });
            reconfigureLink.dataset._wired = 'true';
        }
    }
    
    // Wire up the configure button
    if (welcomeBtn && !welcomeBtn.dataset._wired) {
        welcomeBtn.addEventListener('click', async () => {
            if (hasSavedConfig && isDefaultProfileValid) {
                // User has valid default profile - start conversation
                
                // Show spinning cogwheel and update button text
                if (welcomeCogwheel) {
                    welcomeCogwheel.classList.add('animate-spin');
                }
                if (welcomeBtnText) {
                    welcomeBtnText.textContent = 'Connecting...';
                }
                welcomeBtn.disabled = true;
                
                try {
                    // Use centralized initialization - ensures all services are ready
                    const { initializeConversationMode } = await import('./conversationInitializer.js');
                    await initializeConversationMode();
                    
                } catch (error) {
                    console.error('[WelcomeScreen] Error during conversation initialization:', error);
                    // Error notifications handled by initializeConversationMode
                } finally {
                    // Stop spinning and restore button
                    if (welcomeCogwheel) {
                        welcomeCogwheel.classList.remove('animate-spin');
                    }
                    if (welcomeBtnText) {
                        welcomeBtnText.textContent = (hasSavedConfig && isDefaultProfileValid) ? 'Start Conversation' : 'Configure Application';
                    }
                    welcomeBtn.disabled = false;    
                }
            } else {
                // No valid profile - go to credentials view to configure
                handleViewSwitch('credentials-view');
            }
        });
        welcomeBtn.dataset._wired = 'true';
    }
    
    // After setting up welcome screen, check auth state and override button if needed
    if (window.updateAuthUI) {
        window.updateAuthUI();
    }
    
    // Fetch and display consumption warnings
    await fetchConsumptionWarnings();
}

/**
 * Fetch consumption warnings from the API
 */
async function fetchConsumptionWarnings() {
    try {
        const token = localStorage.getItem('tda_auth_token');
        const userUUID = localStorage.getItem('user_uuid');
        
        if (!token || !userUUID) {
            // Hide warning banner if not authenticated
            document.getElementById('consumption-warning-banner')?.classList.add('hidden');
            return;
        }
        
        const response = await fetch('/api/v1/consumption_warnings', {
            headers: {
                'Authorization': `Bearer ${token}`,
                'X-User-UUID': userUUID
            }
        });
        
        if (!response.ok) {
            // Hide warning banner if error
            document.getElementById('consumption-warning-banner')?.classList.add('hidden');
            return;
        }
        
        const data = await response.json();
        displayConsumptionWarning(data);
    } catch (error) {
        console.error('Error fetching consumption warnings:', error);
        document.getElementById('consumption-warning-banner')?.classList.add('hidden');
    }
}

/**
 * Display consumption warning banner based on usage data
 */
function displayConsumptionWarning(data) {
    const banner = document.getElementById('consumption-warning-banner');
    const warning80 = document.getElementById('consumption-warning-80');
    const warning95 = document.getElementById('consumption-warning-95');
    const warning100 = document.getElementById('consumption-warning-100');
    
    if (!banner || !warning80 || !warning95 || !warning100) return;
    
    // Hide all warnings first
    warning80.classList.add('hidden');
    warning95.classList.add('hidden');
    warning100.classList.add('hidden');
    banner.classList.add('hidden');
    
    // If no warning level, don't show anything
    if (!data.warning_level) return;
    
    // Show appropriate warning based on level
    let activeWarning;
    if (data.warning_level === 'critical' || data.percentage >= 100) {
        activeWarning = warning100;
        document.getElementById('consumption-warning-100-message').textContent = data.message;
        document.getElementById('consumption-percentage-100').textContent = `${Math.round(data.percentage)}%`;
        document.getElementById('consumption-progress-100').style.width = `${Math.min(data.percentage, 100)}%`;
    } else if (data.warning_level === 'urgent' || data.percentage >= 95) {
        activeWarning = warning95;
        document.getElementById('consumption-warning-95-message').textContent = data.message;
        document.getElementById('consumption-percentage-95').textContent = `${Math.round(data.percentage)}%`;
        document.getElementById('consumption-progress-95').style.width = `${Math.min(data.percentage, 100)}%`;
    } else if (data.warning_level === 'warning' || data.percentage >= 80) {
        activeWarning = warning80;
        document.getElementById('consumption-warning-80-message').textContent = data.message;
        document.getElementById('consumption-percentage-80').textContent = `${Math.round(data.percentage)}%`;
        document.getElementById('consumption-progress-80').style.width = `${Math.min(data.percentage, 100)}%`;
    }
    
    // Show the banner and active warning with smooth animation
    if (activeWarning) {
        banner.classList.remove('hidden');
        setTimeout(() => {
            activeWarning.classList.remove('hidden');
        }, 100);
    }
}

/**
 * Populate the disabled capabilities section on the welcome screen
 */
function populateWelcomeDisabledCapabilities() {
    const container = document.getElementById('welcome-disabled-capabilities');
    if (!container) return;

    const disabledTools = [];
    if (state.resourceData.tools) {
        Object.values(state.resourceData.tools).flat().forEach(tool => {
            if (tool.disabled) disabledTools.push(tool.name);
        });
    }

    const disabledPrompts = [];
    if (state.resourceData.prompts) {
        Object.values(state.resourceData.prompts).flat().forEach(prompt => {
            if (prompt.disabled) disabledPrompts.push(prompt.name);
        });
    }

    if (disabledTools.length === 0 && disabledPrompts.length === 0) {
        container.classList.add('hidden');
        return;
    }

    container.classList.remove('hidden');
    
    let html = `
        <div class="pt-6 border-t border-white/10 max-w-3xl mx-auto text-left">
            <h4 class="text-lg font-bold text-yellow-300 mb-2">Reactive Capabilities</h4>
            <p class="text-sm text-gray-400 mb-4">The following capabilities are not actively participating in queries. You can enable them in the Capabilities panel.</p>
            <div class="grid md:grid-cols-2 gap-6">
    `;

    if (disabledTools.length > 0) {
        html += '<div><h5 class="font-semibold text-sm text-white mb-2">Tools</h5><ul class="space-y-1">';
        disabledTools.forEach(name => {
            html += `<li class="text-xs text-gray-300"><code class="text-teradata-orange">${name}</code></li>`;
        });
        html += '</ul></div>';
    }

    if (disabledPrompts.length > 0) {
        html += '<div><h5 class="font-semibold text-sm text-white mb-2">Prompts</h5><ul class="space-y-1">';
        disabledPrompts.forEach(name => {
            html += `<li class="text-xs text-gray-300"><code class="text-teradata-orange">${name}</code></li>`;
        });
        html += '</ul></div>';
    }

    html += '</div></div>';
    container.innerHTML = html;
}

// Make showWelcomeScreen available globally
window.showWelcomeScreen = showWelcomeScreen;

// Make showConfirmation available globally for custom confirmation modals
window.showConfirmation = UI.showConfirmation;