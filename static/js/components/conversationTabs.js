/**
 * ConversationTabs - World-Class Tabbed Conversation Interface
 *
 * Manages profile-based conversation tabs with:
 * - Dynamic tab creation when profiles are used
 * - Message filtering by profile
 * - Smooth animations and micro-interactions
 * - Profile color integration
 * - Session persistence
 *
 * @author Claude Code
 * @version 1.0.0
 */

class ConversationTabs {
    constructor() {
        this.activeTab = null;  // null = Combined, or profile_tag string
        this.tabs = new Map();  // profile_tag -> {count, profileId, color}
        this.tabsContainer = null;
        this.tabsBar = null;
    }

    /**
     * Initialize tab system
     */
    init() {
        this.tabsContainer = document.getElementById('profile-tabs-container');
        this.tabsBar = document.getElementById('profile-tabs-bar');

        if (!this.tabsContainer || !this.tabsBar) {
            console.error('ConversationTabs: Required DOM elements not found');
            return;
        }

        // Create Combined tab (always present)
        this.createCombinedTab();

        // Restore tab state from session if exists
        this.restoreTabState();

        // Set up event listeners
        this.setupEventListeners();

        // Check if there are already messages in chat-log (show tab bar if so)
        const chatLog = document.getElementById('chat-log');
        if (chatLog && chatLog.querySelectorAll('.message-container').length > 0) {
            this.showTabBar();
            this.updateCombinedCount();
        }

        console.log('ConversationTabs: Initialized successfully');
    }

    /**
     * Show the tab bar (when conversation starts)
     */
    showTabBar() {
        if (this.tabsContainer) {
            this.tabsContainer.classList.remove('hidden');
        }
    }

    /**
     * Create Combined tab
     */
    createCombinedTab() {
        const tab = this.createTabElement(null, 'Combined', 0);
        this.tabsBar.appendChild(tab);
        this.activeTab = null;  // Combined is active by default
        this.updateTabActiveState();
    }

    /**
     * Create or update profile tab
     * @param {string} profileTag - Profile tag (e.g., "SQL")
     * @param {string} profileId - Profile UUID
     * @param {string} color - Profile color hex
     */
    ensureProfileTab(profileTag, profileId, color) {
        // Show tab bar when first tab is created
        this.showTabBar();

        if (!this.tabs.has(profileTag)) {
            // Create new tab
            this.tabs.set(profileTag, {
                count: 0,
                profileId: profileId,
                color: color
            });

            const tab = this.createTabElement(profileTag, `@${profileTag}`, 0, color);
            this.tabsBar.appendChild(tab);
        }

        // Increment count
        const tabData = this.tabs.get(profileTag);
        tabData.count++;
        this.updateTabCount(profileTag, tabData.count);

        // Update Combined count
        this.updateCombinedCount();
    }

    /**
     * Create tab DOM element
     */
    createTabElement(profileTag, label, count, color = null) {
        const button = document.createElement('button');
        button.className = 'profile-tab';
        button.setAttribute('data-profile-tag', profileTag || '');

        if (profileTag === null) {
            button.classList.add('active');
        }

        // Tab label
        const labelSpan = document.createElement('span');
        labelSpan.className = 'tab-label';
        labelSpan.textContent = label;
        button.appendChild(labelSpan);

        // Tab count badge
        const countSpan = document.createElement('span');
        countSpan.className = 'tab-count';
        countSpan.textContent = count;
        button.appendChild(countSpan);

        // Close button (only for profile tabs)
        if (profileTag !== null) {
            const closeBtn = document.createElement('button');
            closeBtn.className = 'tab-close';
            closeBtn.textContent = '×';
            closeBtn.onclick = (e) => {
                e.stopPropagation();
                this.closeTab(profileTag);
            };
            button.appendChild(closeBtn);
        }

        // Apply profile color if provided (with computed lighter variants)
        if (color) {
            button.style.setProperty('--profile-color', color);

            // Compute lighter variants for gradients
            const colorWithAlpha = (hex, alpha) => {
                const r = parseInt(hex.slice(1, 3), 16);
                const g = parseInt(hex.slice(3, 5), 16);
                const b = parseInt(hex.slice(5, 7), 16);
                return `rgba(${r}, ${g}, ${b}, ${alpha})`;
            };

            button.style.setProperty('--profile-color-light', colorWithAlpha(color, 0.12));
            button.style.setProperty('--profile-color-lighter', colorWithAlpha(color, 0.06));
        }

        // Click handler with ripple effect
        button.onclick = (e) => {
            // Add ripple effect on click
            const ripple = document.createElement('span');
            ripple.style.cssText = `
                position: absolute;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.3);
                width: 100px;
                height: 100px;
                margin-top: -50px;
                margin-left: -50px;
                left: ${e.offsetX}px;
                top: ${e.offsetY}px;
                animation: ripple 0.6s cubic-bezier(0.16, 1, 0.3, 1);
                pointer-events: none;
            `;
            button.appendChild(ripple);
            setTimeout(() => ripple.remove(), 600);

            this.switchTab(profileTag);
        };

        return button;
    }

    /**
     * Switch active tab
     * @param {string|null} profileTag - null for Combined, or profile tag
     */
    switchTab(profileTag) {
        if (this.activeTab === profileTag) return;

        this.activeTab = profileTag;
        this.updateTabActiveState();
        this.filterMessages();
        this.updateHeaderIndicator();
        this.updateProfileContext();
        this.saveTabState();

        // Emit event for other components
        window.dispatchEvent(new CustomEvent('tabSwitched', {
            detail: { profileTag: profileTag }
        }));

        console.log(`ConversationTabs: Switched to ${profileTag || 'Combined'} tab`);
    }

    /**
     * Update visual active state
     */
    updateTabActiveState() {
        const tabs = this.tabsBar.querySelectorAll('.profile-tab');
        tabs.forEach(tab => {
            const tag = tab.getAttribute('data-profile-tag') || null;
            if (tag === this.activeTab) {
                tab.classList.add('active');
            } else {
                tab.classList.remove('active');
            }
        });
    }

    /**
     * Filter chat messages based on active tab
     */
    filterMessages() {
        const chatLog = document.getElementById('chat-log');
        if (!chatLog) return;

        const messages = chatLog.querySelectorAll('.message-bubble');

        messages.forEach(messageWrapper => {
            const messageContainer = messageWrapper.querySelector('.message-container');
            if (!messageContainer) return;

            const messageRole = messageContainer.getAttribute('data-role');
            const messageProfileTag = messageContainer.getAttribute('data-profile-tag');

            if (this.activeTab === null) {
                // Combined tab: show all messages
                messageWrapper.style.display = '';
            } else {
                // Profile tab: show only messages for this profile
                // Show user messages with matching profile tag
                // AND show assistant responses that follow those user messages
                if (messageRole === 'user') {
                    if (messageProfileTag === this.activeTab) {
                        messageWrapper.style.display = '';
                    } else {
                        messageWrapper.style.display = 'none';
                    }
                } else if (messageRole === 'assistant') {
                    // Show assistant message if previous user message had matching profile
                    const prevUserMessage = this.findPreviousUserMessage(messageWrapper);
                    if (prevUserMessage) {
                        const prevProfileTag = prevUserMessage.getAttribute('data-profile-tag');
                        if (prevProfileTag === this.activeTab) {
                            messageWrapper.style.display = '';
                        } else {
                            messageWrapper.style.display = 'none';
                        }
                    }
                }
            }
        });
    }

    /**
     * Find previous user message for an assistant message
     */
    findPreviousUserMessage(assistantMessageWrapper) {
        let current = assistantMessageWrapper.previousElementSibling;
        while (current) {
            const container = current.querySelector('.message-container');
            if (container && container.getAttribute('data-role') === 'user') {
                return container;
            }
            current = current.previousElementSibling;
        }
        return null;
    }

    /**
     * Update header profile indicator
     */
    updateHeaderIndicator() {
        const overrideBadge = document.getElementById('header-override-profile');
        const overrideTag = document.getElementById('header-override-profile-tag');

        if (!overrideBadge || !overrideTag) return;

        if (this.activeTab === null) {
            // Combined tab: hide override indicator
            overrideBadge.classList.add('hidden');
        } else {
            // Profile tab: Check if this is the default profile
            const tabData = this.tabs.get(this.activeTab);
            const defaultProfileId = window.configState?.defaultProfileId;
            const isDefaultProfile = tabData && tabData.profileId === defaultProfileId;

            if (isDefaultProfile) {
                // Default profile: hide override indicator (no override needed)
                overrideBadge.classList.add('hidden');
            } else {
                // Non-default profile: show override indicator
                overrideTag.textContent = `@${this.activeTab}`;
                overrideBadge.classList.remove('hidden');

                // Apply profile color
                if (tabData && tabData.color) {
                    overrideBadge.style.borderColor = tabData.color;
                    overrideBadge.style.background = `${tabData.color}22`;
                }
            }
        }
    }

    /**
     * Update profile context for autocomplete and resource panel
     */
    updateProfileContext() {
        if (this.activeTab === null) {
            // Combined tab: restore default profile
            window.activeProfileOverrideId = null;
            window.activeTagPrefix = '';

            // Restore default profile resources (if function exists)
            const defaultProfileId = window.configState?.defaultProfileId;
            if (defaultProfileId && typeof updateResourcePanelForProfile === 'function') {
                updateResourcePanelForProfile(defaultProfileId);
            }
        } else {
            // Profile tab: set active profile override
            const tabData = this.tabs.get(this.activeTab);
            if (tabData) {
                window.activeProfileOverrideId = tabData.profileId;
                window.activeTagPrefix = ''; // No prefix needed, implicit

                // Update resource panel (if function exists)
                if (typeof updateResourcePanelForProfile === 'function') {
                    updateResourcePanelForProfile(tabData.profileId);
                }
            }
        }
    }

    /**
     * Update tab message count with animation
     */
    updateTabCount(profileTag, count) {
        const tab = this.tabsBar.querySelector(`[data-profile-tag="${profileTag}"]`);
        if (tab) {
            const countSpan = tab.querySelector('.tab-count');
            if (countSpan) {
                const oldCount = parseInt(countSpan.textContent) || 0;
                if (count !== oldCount) {
                    // Animate badge on count change
                    countSpan.style.animation = 'none';
                    setTimeout(() => {
                        countSpan.textContent = count;
                        countSpan.style.animation = 'badgeUpdate 0.5s cubic-bezier(0.16, 1, 0.3, 1)';
                    }, 10);
                }
            }
        }
    }

    /**
     * Update Combined tab count (total messages)
     */
    updateCombinedCount() {
        const combinedTab = this.tabsBar.querySelector('[data-profile-tag=""]');
        if (combinedTab) {
            const chatLog = document.getElementById('chat-log');
            if (!chatLog) return;

            const totalMessages = chatLog.querySelectorAll('.message-container[data-role="user"]').length;
            const countSpan = combinedTab.querySelector('.tab-count');
            if (countSpan) {
                countSpan.textContent = totalMessages;
            }
        }
    }

    /**
     * Close profile tab with smooth animation
     */
    async closeTab(profileTag) {
        const tab = this.tabsBar.querySelector(`[data-profile-tag="${profileTag}"]`);
        if (!tab) return;

        // Add removing class for animation
        tab.classList.add('removing');

        // Wait for animation to complete
        await new Promise(resolve => setTimeout(resolve, 300));

        // Remove from tabs map
        this.tabs.delete(profileTag);

        // Remove DOM element
        tab.remove();

        // If this was the active tab, switch to Combined
        if (this.activeTab === profileTag) {
            this.switchTab(null);
        }

        this.saveTabState();

        console.log(`ConversationTabs: Closed tab ${profileTag}`);
    }

    /**
     * Save tab state to session storage
     */
    saveTabState() {
        const state = {
            activeTab: this.activeTab,
            tabs: Array.from(this.tabs.entries()).map(([tag, data]) => ({
                profileTag: tag,
                profileId: data.profileId,
                color: data.color,
                count: data.count
            }))
        };

        sessionStorage.setItem('conversationTabState', JSON.stringify(state));
    }

    /**
     * Restore tab state from session storage
     */
    restoreTabState() {
        const stateJson = sessionStorage.getItem('conversationTabState');
        if (!stateJson) return;

        try {
            const state = JSON.parse(stateJson);

            // Show tab bar if restoring tabs
            if (state.tabs && state.tabs.length > 0) {
                this.showTabBar();
            }

            // Restore profile tabs
            state.tabs.forEach(tabInfo => {
                this.tabs.set(tabInfo.profileTag, {
                    count: tabInfo.count,
                    profileId: tabInfo.profileId,
                    color: tabInfo.color
                });

                const tab = this.createTabElement(
                    tabInfo.profileTag,
                    `@${tabInfo.profileTag}`,
                    tabInfo.count,
                    tabInfo.color
                );
                this.tabsBar.appendChild(tab);
            });

            // Restore active tab
            if (state.activeTab !== null) {
                this.switchTab(state.activeTab);
            }

            console.log('ConversationTabs: Restored tab state from session storage');
        } catch (e) {
            console.error('ConversationTabs: Failed to restore tab state:', e);
        }
    }

    /**
     * Set up event listeners
     */
    setupEventListeners() {
        // Listen for new messages to update counts
        window.addEventListener('messageAdded', (e) => {
            const { role, profileTag } = e.detail;

            // Show tab bar on first message
            if (role === 'user') {
                this.showTabBar();
                this.updateCombinedCount(); // Update Combined tab count
            }

            if (role === 'user' && profileTag) {
                // Get profile info from configState
                const profile = window.configState?.profiles?.find(p => p.tag === profileTag);
                if (profile) {
                    this.ensureProfileTab(profileTag, profile.id, profile.color);
                }
            }
        });

        // Listen for session load to rebuild tabs
        window.addEventListener('sessionLoaded', (e) => {
            const { profile_tags_used } = e.detail;
            this.rebuildTabsFromSession(profile_tags_used);
        });
    }

    /**
     * Rebuild tabs when loading a session
     */
    rebuildTabsFromSession(profileTagsUsed) {
        // Show tab bar when loading session
        this.showTabBar();

        // Clear existing profile tabs (keep Combined)
        const profileTabs = this.tabsBar.querySelectorAll('.profile-tab:not([data-profile-tag=""])');
        profileTabs.forEach(tab => tab.remove());
        this.tabs.clear();

        // Create tabs for each profile used in session
        if (profileTagsUsed && Array.isArray(profileTagsUsed)) {
            profileTagsUsed.forEach(tag => {
                const profile = window.configState?.profiles?.find(p => p.tag === tag);
                if (profile) {
                    // Count messages for this profile
                    const chatLog = document.getElementById('chat-log');
                    if (!chatLog) return;

                    const count = chatLog.querySelectorAll(
                        `.message-container[data-role="user"][data-profile-tag="${tag}"]`
                    ).length;

                    this.tabs.set(tag, {
                        count: count,
                        profileId: profile.id,
                        color: profile.color
                    });

                    const tab = this.createTabElement(tag, `@${tag}`, count, profile.color);
                    this.tabsBar.appendChild(tab);
                }
            });
        }

        // Update Combined count
        this.updateCombinedCount();

        // Reset to Combined tab
        this.switchTab(null);

        console.log('ConversationTabs: Rebuilt tabs from session data');
    }
}

// Export singleton instance
export const conversationTabs = new ConversationTabs();
