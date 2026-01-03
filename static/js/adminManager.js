/**
 * Administration Module
 * Handles user management and feature configuration UI
 */

const AdminManager = {
    currentUsers: [],
    currentFeatures: [],
    currentProfiles: [],
    currentConsumptionData: [],
    consumptionSortColumn: 'username',
    consumptionSortDirection: 'asc',
    featureChanges: {},

    /**
     * Initialize the administration module
     */
    init() {
        console.log('[AdminManager] Initializing...');
        this.setupEventListeners();
    },

    /**
     * Setup event listeners for admin UI
     */
    setupEventListeners() {
        // Tab switching
        document.querySelectorAll('.admin-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const tabName = e.currentTarget.dataset.tab;
                this.switchTab(tabName);
            });
        });

        // User management
        const createUserBtn = document.getElementById('create-user-btn');
        if (createUserBtn) {
            createUserBtn.addEventListener('click', () => this.showCreateUserModal());
        }
        
        const refreshBtn = document.getElementById('refresh-users-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadUsers());
        }
        
        // User modal handlers
        const userModalClose = document.getElementById('user-modal-close');
        if (userModalClose) {
            userModalClose.addEventListener('click', () => this.hideUserModal());
        }
        
        const userFormCancel = document.getElementById('user-form-cancel');
        if (userFormCancel) {
            userFormCancel.addEventListener('click', () => this.hideUserModal());
        }

        // User Management Sub-tabs
        document.querySelectorAll('.user-management-subtab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const subtabName = e.currentTarget.dataset.subtab;
                this.switchUserManagementSubtab(subtabName);
            });
        });

        // User status filter buttons
        document.querySelectorAll('.user-status-filter-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const status = e.currentTarget.dataset.status;
                this.filterUsersByStatus(status);
            });
        });

        // Refresh consumption button
        const refreshConsumptionBtn = document.getElementById('refresh-consumption-btn');
        if (refreshConsumptionBtn) {
            refreshConsumptionBtn.addEventListener('click', () => this.loadUserConsumption());
        }

        // Consumption table sorting
        document.addEventListener('click', (e) => {
            const th = e.target.closest('th[data-sort]');
            if (th && th.closest('#user-consumption-subtab')) {
                const sortBy = th.dataset.sort;
                this.sortConsumptionTable(sortBy);
            }
        });

        // Consumption Profiles
        const createProfileBtn = document.getElementById('create-profile-btn');
        if (createProfileBtn) {
            createProfileBtn.addEventListener('click', () => this.showCreateProfileModal());
        }

        // Consumption Profile modal handlers
        const profileModalClose = document.getElementById('close-consumption-profile-modal');
        if (profileModalClose) {
            profileModalClose.addEventListener('click', () => this.hideProfileModal());
        }
        
        const profileFormCancel = document.getElementById('cancel-consumption-profile');
        if (profileFormCancel) {
            profileFormCancel.addEventListener('click', () => this.hideProfileModal());
        }
        
        const profileForm = document.getElementById('consumption-profile-form');
        if (profileForm) {
            profileForm.addEventListener('submit', (e) => this.handleProfileFormSubmit(e));
        }
        
        const userForm = document.getElementById('user-form');
        if (userForm) {
            userForm.addEventListener('submit', (e) => {
                e.preventDefault();
                const formData = {
                    id: document.getElementById('user-form-id').value,
                    username: document.getElementById('user-form-username').value,
                    email: document.getElementById('user-form-email').value,
                    displayName: document.getElementById('user-form-display-name').value,
                    password: document.getElementById('user-form-password').value,
                    tier: document.getElementById('user-form-tier').value
                };
                this.saveUser(formData);
            });
        }

        // Feature configuration
        const saveBtn = document.getElementById('save-features-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveFeatureChanges());
        }

        const resetBtn = document.getElementById('reset-features-btn');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => this.resetFeatures());
        }

        // Feature search and filter
        const searchInput = document.getElementById('feature-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => this.filterFeatures(e.target.value));
        }

        const filterSelect = document.getElementById('feature-filter-tier');
        if (filterSelect) {
            filterSelect.addEventListener('change', (e) => this.filterFeaturesByTier(e.target.value));
        }

        // Pane configuration
        const refreshPanesBtn = document.getElementById('refresh-panes-btn');
        if (refreshPanesBtn) {
            refreshPanesBtn.addEventListener('click', () => this.loadPanes());
        }

        const resetPanesBtn = document.getElementById('reset-panes-btn');
        if (resetPanesBtn) {
            resetPanesBtn.addEventListener('click', () => this.resetPanes());
        }

        // Application configuration
        const runMcpClassificationBtn = document.getElementById('run-mcp-classification-btn');
        if (runMcpClassificationBtn) {
            runMcpClassificationBtn.addEventListener('click', () => this.runMcpClassification());
        }

        // MCP Classification toggle is handled by configurationHandler.js

        // Expert Settings
        const saveExpertSettingsBtn = document.getElementById('save-expert-settings-btn');
        if (saveExpertSettingsBtn) {
            saveExpertSettingsBtn.addEventListener('click', () => this.saveExpertSettings());
        }

        const clearCacheBtn = document.getElementById('clear-cache-btn');
        if (clearCacheBtn) {
            clearCacheBtn.addEventListener('click', () => this.clearCache());
        }

        const resetStateBtn = document.getElementById('reset-state-btn');
        if (resetStateBtn) {
            resetStateBtn.addEventListener('click', () => this.resetState());
        }

        // System Prompts
        const systemPromptsTierSelector = document.getElementById('system-prompts-tier-selector');
        if (systemPromptsTierSelector) {
            systemPromptsTierSelector.addEventListener('change', (e) => {
                const promptName = e.target.value;
                this.loadSystemPromptForTier(promptName);
                // Always reload parameters when prompt changes
                this.loadPromptParameters(promptName);
            });
        }

        const loadSystemPromptBtn = document.getElementById('load-system-prompt-btn');
        if (loadSystemPromptBtn) {
            loadSystemPromptBtn.addEventListener('click', () => {
                const tier = document.getElementById('system-prompts-tier-selector').value;
                this.loadSystemPromptForTier(tier);
            });
        }

        const saveSystemPromptBtn = document.getElementById('save-system-prompt-btn');
        if (saveSystemPromptBtn) {
            saveSystemPromptBtn.addEventListener('click', () => this.saveSystemPrompt());
        }

        const resetSystemPromptBtn = document.getElementById('reset-system-prompt-btn');
        if (resetSystemPromptBtn) {
            resetSystemPromptBtn.addEventListener('click', () => this.resetSystemPromptToDefault());
        }

        // Phase 4: Enhanced Features Event Handlers
        const duplicatePromptBtn = document.getElementById('duplicate-prompt-btn');
        if (duplicatePromptBtn) {
            duplicatePromptBtn.addEventListener('click', () => this.duplicatePrompt());
        }

        const deletePromptBtn = document.getElementById('delete-prompt-btn');
        if (deletePromptBtn) {
            deletePromptBtn.addEventListener('click', () => this.deletePrompt());
        }

        const toggleParametersBtn = document.getElementById('toggle-parameters-btn');
        if (toggleParametersBtn) {
            toggleParametersBtn.addEventListener('click', () => this.toggleSection('parameters'));
        }

        const toggleVersionsBtn = document.getElementById('toggle-versions-btn');
        if (toggleVersionsBtn) {
            toggleVersionsBtn.addEventListener('click', () => this.toggleSection('versions'));
        }

        const toggleDiffBtn = document.getElementById('toggle-diff-btn');
        if (toggleDiffBtn) {
            toggleDiffBtn.addEventListener('click', () => this.toggleSection('diff'));
        }

        const systemPromptTextarea = document.getElementById('system-prompt-editor-textarea');
        if (systemPromptTextarea) {
            systemPromptTextarea.addEventListener('input', () => {
                this.updateCharCount();
                this.updateSaveButtonState(); // Check if content changed
                
                // Auto-reload parameters if the section is expanded
                const parametersContent = document.getElementById('parameters-content');
                if (parametersContent && !parametersContent.classList.contains('hidden')) {
                    const promptName = document.getElementById('system-prompts-tier-selector').value;
                    if (promptName) {
                        // Debounce to avoid too many API calls while typing
                        clearTimeout(this._parameterReloadTimeout);
                        this._parameterReloadTimeout = setTimeout(() => {
                            this.loadPromptParameters(promptName);
                        }, 500); // Wait 500ms after user stops typing
                    }
                }
            });
        }

        // Application Configuration
        const saveAppConfigBtn = document.getElementById('save-app-config-btn');
        if (saveAppConfigBtn) {
            saveAppConfigBtn.addEventListener('click', () => this.saveAppConfig());
        }

        // Window defaults button
        const saveWindowDefaultsBtn = document.getElementById('save-window-defaults-btn');
        if (saveWindowDefaultsBtn) {
            saveWindowDefaultsBtn.addEventListener('click', () => this.saveWindowDefaults());
        }

        // Rate Limiting
        const rateLimitEnabledCheckbox = document.getElementById('rate-limit-enabled');
        if (rateLimitEnabledCheckbox) {
            rateLimitEnabledCheckbox.addEventListener('change', (e) => this.toggleGlobalOverrideAvailability(e.target.checked));
        }

        const globalOverrideCheckbox = document.getElementById('rate-limit-global-override');
        if (globalOverrideCheckbox) {
            globalOverrideCheckbox.addEventListener('change', (e) => this.toggleRateLimitSettings(e.target.checked));
        }

        const saveRateLimitBtn = document.getElementById('save-rate-limit-btn');
        if (saveRateLimitBtn) {
            saveRateLimitBtn.addEventListener('click', () => this.saveRateLimitSettings());
        }

        // Knowledge Repository Configuration
        const saveKnowledgeConfigBtn = document.getElementById('save-knowledge-config-btn');
        if (saveKnowledgeConfigBtn) {
            saveKnowledgeConfigBtn.addEventListener('click', () => this.saveKnowledgeConfig());
        }
    },

    /**
     * Switch between admin tabs
     */
    switchTab(tabName) {
        // Update tab buttons
        document.querySelectorAll('.admin-tab').forEach(tab => {
            if (tab.dataset.tab === tabName) {
                tab.classList.add('active', 'border-[#F15F22]', 'text-white');
                tab.classList.remove('text-gray-400', 'border-transparent');
            } else {
                tab.classList.remove('active', 'border-[#F15F22]', 'text-white');
                tab.classList.add('text-gray-400', 'border-transparent');
            }
        });

        // Update tab content
        document.querySelectorAll('.admin-tab-content').forEach(content => {
            if (content.id === tabName) {
                content.classList.remove('hidden');
                content.classList.add('active');
            } else {
                content.classList.add('hidden');
                content.classList.remove('active');
            }
        });

        // Load data for the active tab
        if (tabName === 'user-management-tab') {
            this.loadUsers();
            // Load the active sub-tab
            const activeSubtab = document.querySelector('.user-management-subtab.active');
            if (activeSubtab && activeSubtab.dataset.subtab === 'user-consumption-subtab') {
                this.loadUserConsumption();
            }
        } else if (tabName === 'consumption-profiles-tab') {
            this.loadProfiles();
        } else if (tabName === 'feature-config-tab') {
            this.loadFeatures();
        } else if (tabName === 'pane-config-tab') {
            this.loadPanes();
        } else if (tabName === 'app-config-tab') {
            this.loadAppConfig();
            this.loadRateLimitSettings();
            // Load document upload configurations
            if (typeof DocumentUploadConfigManager !== 'undefined' && DocumentUploadConfigManager.loadConfigurations) {
                DocumentUploadConfigManager.loadConfigurations();
            }
        } else if (tabName === 'expert-settings-tab') {
            this.loadExpertSettings();
        } else if (tabName === 'system-prompts-tab') {
            // Load all prompts first to populate the dropdown
            this.loadAllPrompts().then(() => {
                const tier = document.getElementById('system-prompts-tier-selector').value;
                if (tier) {
                    this.loadSystemPromptForTier(tier);
                }
            });
        }
    },

    /**
     * Switch User Management sub-tabs
     */
    switchUserManagementSubtab(subtabName) {
        // Update sub-tab buttons (filled rounded button style)
        document.querySelectorAll('.user-management-subtab').forEach(tab => {
            if (tab.dataset.subtab === subtabName) {
                tab.classList.add('active', 'bg-[#F15F22]', 'text-white');
                tab.classList.remove('bg-gray-700/50', 'text-gray-400', 'hover:bg-gray-700');
            } else {
                tab.classList.remove('active', 'bg-[#F15F22]', 'text-white');
                tab.classList.add('bg-gray-700/50', 'text-gray-400', 'hover:bg-gray-700');
            }
        });

        // Update sub-tab content
        document.querySelectorAll('.user-management-subtab-content').forEach(content => {
            if (content.id === subtabName) {
                content.classList.remove('hidden');
                content.classList.add('active');
            } else {
                content.classList.add('hidden');
                content.classList.remove('active');
            }
        });

        // Load data for the active sub-tab
        if (subtabName === 'user-consumption-subtab') {
            this.loadUserConsumption();
        }
    },

    currentUserStatusFilter: 'all',

    /**
     * Filter users by status and reload the list
     */
    filterUsersByStatus(status) {
        this.currentUserStatusFilter = status;
        
        // Update button styles
        document.querySelectorAll('.user-status-filter-btn').forEach(btn => {
            if (btn.dataset.status === status) {
                btn.classList.add('bg-gray-600', 'text-white');
                btn.classList.remove('bg-gray-800', 'text-gray-400', 'hover:bg-gray-700');
            } else {
                btn.classList.remove('bg-gray-600', 'text-white');
                btn.classList.add('bg-gray-800', 'text-gray-400', 'hover:bg-gray-700');
            }
        });
        
        this.loadUsers();
    },

    /**
     * Load all users from API
     */
    async loadUsers() {
        try {
            // Load profiles first if not loaded yet
            if (this.currentProfiles.length === 0) {
                await this.loadProfilesForDropdown();
            }

            const token = localStorage.getItem('tda_auth_token');
            const apiUrl = `/api/v1/admin/users?status=${this.currentUserStatusFilter}`;
            
            const response = await fetch(apiUrl, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                this.currentUsers = data.users;
                this.renderUsers();
                this.updateUserStats();
            } else {
                window.showNotification('error', data.message || 'Failed to load users');
                // Clear loading state even on error
                this.currentUsers = [];
                this.renderUsers();
                this.updateUserStats();
            }
        } catch (error) {
            console.error('[AdminManager] Error loading users:', error);
            window.showNotification('error', 'Failed to load users');
            // Clear loading state even on error
            this.currentUsers = [];
            this.renderUsers();
            this.updateUserStats();
        }
    },

    /**
     * Render users table
     */
    renderUsers() {
        const tbody = document.getElementById('users-table-body');
        if (!tbody) return;

        // Update table headers to include Status
        const thead = tbody.parentElement.querySelector('thead');
        if (thead) {
            thead.innerHTML = `
                <tr>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">User</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Email</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Tier</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Profile</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Status</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Change Tier</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Assign Profile</th>
                    <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Actions</th>
                </tr>
            `;
        }


        if (this.currentUsers.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="px-6 py-8 text-center text-gray-400">
                        No users found for this filter.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.currentUsers
            .map(user => {
                const defaultProfile = this.currentProfiles.find(p => p.is_default);
                const userProfileId = user.consumption_profile_id || (defaultProfile ? defaultProfile.id : null);
                const userProfileName = user.consumption_profile_name || (defaultProfile ? defaultProfile.name : 'None');
                
                const profileOptions = this.currentProfiles.map(profile => 
                    `<option value="${profile.id}" ${userProfileId === profile.id ? 'selected' : ''}>${this.escapeHtml(profile.name)}</option>`
                ).join('');

                const actionButton = user.is_active
                    ? `<button class="deactivate-user-btn p-2 text-yellow-400 hover:text-yellow-300 transition-colors" data-user-id="${user.id}" title="Deactivate User" ${user.is_current_user ? 'disabled' : ''}>
                          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM7 9a1 1 0 000 2h6a1 1 0 100-2H7z" clip-rule="evenodd" /></svg>
                       </button>`
                    : `<button class="activate-user-btn p-2 text-green-400 hover:text-green-300 transition-colors" data-user-id="${user.id}" title="Activate User" ${user.is_current_user ? 'disabled' : ''}>
                          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z" clip-rule="evenodd" /></svg>
                       </button>`;
                
                return `
            <tr class="bg-gray-800/50 hover:bg-gray-700/50 transition-colors">
                <td class="px-6 py-4 font-medium text-white">${this.escapeHtml(user.username)}</td>
                <td class="px-6 py-4 text-gray-300">${this.escapeHtml(user.email || '')}</td>
                <td class="px-6 py-4">
                    <span class="px-3 py-1 rounded-full text-xs font-semibold ${this.getTierBadgeClass(user.profile_tier)}">
                        ${user.profile_tier.toUpperCase()}
                    </span>
                </td>
                <td class="px-6 py-4">
                    <span class="px-3 py-1 rounded-full text-xs font-semibold ${this.getProfileBadgeClass(userProfileName)}">${this.escapeHtml(userProfileName)}</span>
                </td>
                <td class="px-6 py-4">
                     <span class="px-3 py-1 rounded-full text-xs font-semibold ${user.is_active ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}">
                        ${user.is_active ? 'Active' : 'Inactive'}
                    </span>
                </td>
                <td class="px-6 py-4">
                    <select
                        class="tier-select p-2 bg-gray-700 border border-gray-600 rounded-md text-sm text-white focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none"
                        data-user-id="${user.id}"
                        ${user.is_current_user ? 'disabled' : ''}
                    >
                        <option value="user" ${user.profile_tier === 'user' ? 'selected' : ''}>User</option>
                        <option value="developer" ${user.profile_tier === 'developer' ? 'selected' : ''}>Developer</option>
                        <option value="admin" ${user.profile_tier === 'admin' ? 'selected' : ''}>Admin</option>
                    </select>
                </td>
                <td class="px-6 py-4">
                    <select
                        class="profile-select p-2 bg-gray-700 border border-gray-600 rounded-md text-sm text-white focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none"
                        data-user-id="${user.id}"
                        title="Assign Consumption Profile"
                    >
                        ${profileOptions}
                    </select>
                </td>
                <td class="px-6 py-4">
                    <div class="flex gap-2">
                        <button class="edit-user-btn p-2 text-blue-400 hover:text-blue-300 transition-colors" data-user-id="${user.id}" title="Edit User">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                            </svg>
                        </button>
                        ${actionButton}
                    </div>
                </td>
            </tr>
        `;
            }).join('');

        // Attach change listeners for tier
        tbody.querySelectorAll('.tier-select').forEach(select => {
            select.addEventListener('change', async (e) => {
                const userId = e.target.dataset.userId;
                const newTier = e.target.value;
                await this.changeUserTier(userId, newTier);
            });
        });
        
        // Attach change listeners for profile
        tbody.querySelectorAll('.profile-select').forEach(select => {
            select.addEventListener('change', async (e) => {
                const userId = e.target.dataset.userId;
                const profileId = e.target.value ? parseInt(e.target.value) : null;
                await this.assignUserProfile(userId, profileId);
            });
        });
        
        // Attach edit listeners
        tbody.querySelectorAll('.edit-user-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const userId = e.currentTarget.dataset.userId;
                this.showEditUserModal(userId);
            });
        });
        
        // Attach activate/deactivate listeners
        tbody.querySelectorAll('.deactivate-user-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const userId = e.currentTarget.dataset.userId;
                this.deactivateUser(userId);
            });
        });

        tbody.querySelectorAll('.activate-user-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const userId = e.currentTarget.dataset.userId;
                this.activateUser(userId);
            });
        });
    },

    /**
     * Get badge class for tier
     */
    getTierBadgeClass(tier) {
        const classes = {
            'user': 'bg-blue-500/20 text-blue-400 border border-blue-400/30',
            'developer': 'bg-purple-500/20 text-purple-400 border border-purple-400/30',
            'admin': 'bg-red-500/20 text-red-400 border border-red-400/30'
        };
        return classes[tier] || classes['user'];
    },

    /**
     * Get badge class for consumption profile
     */
    getProfileBadgeClass(profileName) {
        const classes = {
            'Free': 'bg-blue-500/20 text-blue-400 border border-blue-400/30',
            'Pro': 'bg-purple-500/20 text-purple-400 border border-purple-400/30',
            'Enterprise': 'bg-orange-500/20 text-orange-400 border border-orange-400/30',
            'Unlimited': 'bg-green-500/20 text-green-400 border border-green-400/30'
        };
        return classes[profileName] || 'bg-gray-500/20 text-gray-400 border border-gray-400/30';
    },

    /**
     * Update user statistics
     */
    updateUserStats() {
        const tierCounts = {
            user: 0,
            developer: 0,
            admin: 0
        };

        this.currentUsers.forEach(user => {
            tierCounts[user.profile_tier] = (tierCounts[user.profile_tier] || 0) + 1;
        });

        document.getElementById('user-tier-count').textContent = tierCounts.user;
        document.getElementById('developer-tier-count').textContent = tierCounts.developer;
        document.getElementById('admin-tier-count').textContent = tierCounts.admin;
    },

    /**
     * Change user tier
     */
    async changeUserTier(userId, newTier) {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch(`/api/v1/admin/users/${userId}/tier`, {
                method: 'PATCH',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ profile_tier: newTier })
            });
            const data = await response.json();

            if (data.status === 'success') {
                window.showNotification('success', `User tier updated to ${newTier}`);
                await this.loadUsers(); // Reload to get updated feature counts
            } else {
                window.showNotification('error', data.message || 'Failed to update user tier');
                await this.loadUsers(); // Reload to reset select
            }
        } catch (error) {
            console.error('[AdminManager] Error changing user tier:', error);
            window.showNotification('error', 'Failed to update user tier');
            await this.loadUsers();
        }
    },

    /**
     * Assign consumption profile to user
     */
    async assignUserProfile(userId, profileId) {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch(`/api/v1/auth/admin/users/${userId}/consumption-profile`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ profile_id: profileId })
            });
            const data = await response.json();

            if (data.status === 'success') {
                const profileName = profileId ? this.currentProfiles.find(p => p.id === profileId)?.name : 'Default';
                window.showNotification('success', `User profile updated to ${profileName}`);
                await this.loadUsers();
                await this.updateProfileStats();
            } else {
                window.showNotification('error', data.message || 'Failed to assign profile');
                await this.loadUsers();
            }
        } catch (error) {
            console.error('[AdminManager] Error assigning profile:', error);
            window.showNotification('error', 'Failed to assign profile');
            await this.loadUsers();
        }
    },

    /**
     * Load profiles for dropdown (silent, no rendering)
     */
    async loadProfilesForDropdown() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch('/api/v1/auth/admin/consumption-profiles', {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                this.currentProfiles = data.profiles;
            }
        } catch (error) {
            console.error('[AdminManager] Error loading profiles:', error);
        }
    },

    /**
     * Load all consumption profiles from API
     */
    async loadProfiles() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch('/api/v1/auth/admin/consumption-profiles', {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                this.currentProfiles = data.profiles;
                this.renderProfiles();
                this.updateProfileStats();
            } else {
                window.showNotification('error', data.message || 'Failed to load profiles');
            }
        } catch (error) {
            console.error('[AdminManager] Error loading profiles:', error);
            window.showNotification('error', 'Failed to load profiles');
        }
    },

    /**
     * Render profiles table
     */
    renderProfiles() {
        const tbody = document.getElementById('profiles-table-body');
        if (!tbody) return;

        if (this.currentProfiles.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="px-6 py-8 text-center text-gray-400">
                        No profiles found
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.currentProfiles.map(profile => `
            <tr class="bg-gray-800/50 hover:bg-gray-700/50 transition-colors">
                <td class="px-6 py-4 font-medium text-white">
                    ${this.escapeHtml(profile.name)}
                    ${profile.is_default ? '<span class="ml-2 px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded">DEFAULT</span>' : ''}
                </td>
                <td class="px-6 py-4 text-gray-300 text-sm">${this.escapeHtml(profile.description || '')}</td>
                <td class="px-6 py-4 text-center text-gray-300">${profile.prompts_per_hour || '∞'}</td>
                <td class="px-6 py-4 text-center text-gray-300">${profile.prompts_per_day || '∞'}</td>
                <td class="px-6 py-4 text-center text-gray-300">${this.formatTokens(profile.input_tokens_per_month)}</td>
                <td class="px-6 py-4 text-center text-gray-300">${this.formatTokens(profile.output_tokens_per_month)}</td>
                <td class="px-6 py-4 text-center">
                    <span class="px-3 py-1 rounded-full text-xs font-semibold ${this.getProfileBadgeClass(profile.name)}">${profile.user_count || 0}</span>
                </td>
                <td class="px-6 py-4 text-center">
                    <span class="px-2 py-1 rounded text-xs ${profile.is_active ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'}">
                        ${profile.is_active ? 'Active' : 'Inactive'}
                    </span>
                </td>
                <td class="px-6 py-4">
                    <div class="flex gap-2 justify-center">
                        <button class="edit-profile-btn p-2 text-blue-400 hover:text-blue-300 transition-colors" data-profile-id="${profile.id}" title="Edit Profile">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                            </svg>
                        </button>
                        <button class="delete-profile-btn p-2 text-red-400 hover:text-red-300 transition-colors ${profile.user_count > 0 ? 'opacity-50 cursor-not-allowed' : ''}" 
                                data-profile-id="${profile.id}" 
                                title="${profile.user_count > 0 ? 'Cannot delete profile with assigned users' : 'Delete Profile'}"
                                ${profile.user_count > 0 ? 'disabled' : ''}>
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');

        // Attach event listeners
        tbody.querySelectorAll('.edit-profile-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const profileId = parseInt(e.currentTarget.dataset.profileId);
                this.showEditProfileModal(profileId);
            });
        });

        tbody.querySelectorAll('.delete-profile-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const profileId = parseInt(e.currentTarget.dataset.profileId);
                this.deleteProfile(profileId);
            });
        });

        // Update KPIs
        this.updateProfileKPIs();
    },

    /**
     * Update consumption profile KPIs
     */
    updateProfileKPIs() {
        const totalProfiles = this.currentProfiles.length;
        const activeProfiles = this.currentProfiles.filter(p => p.is_active).length;
        const assignedUsers = this.currentProfiles.reduce((sum, p) => sum + (p.user_count || 0), 0);

        const totalElem = document.getElementById('total-profiles-count');
        const activeElem = document.getElementById('active-profiles-count');
        const assignedElem = document.getElementById('assigned-users-count');

        if (totalElem) totalElem.textContent = totalProfiles;
        if (activeElem) activeElem.textContent = activeProfiles;
        if (assignedElem) assignedElem.textContent = assignedUsers;
    },

    /**
     * Format token values for display
     */
    formatTokens(tokens) {
        if (tokens === null || tokens === undefined) return '∞';
        if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
        if (tokens >= 1000) return `${(tokens / 1000).toFixed(0)}K`;
        return tokens.toString();
    },

    /**
     * Update profile statistics
     */
    updateProfileStats() {
        const stats = {
            'Free': 0,
            'Pro': 0,
            'Enterprise': 0,
            'Unlimited': 0
        };

        this.currentProfiles.forEach(profile => {
            if (stats.hasOwnProperty(profile.name)) {
                stats[profile.name] = profile.user_count || 0;
            }
        });

        const elements = {
            'Free': 'free-profile-count',
            'Pro': 'pro-profile-count',
            'Enterprise': 'enterprise-profile-count',
            'Unlimited': 'unlimited-profile-count'
        };

        Object.entries(elements).forEach(([name, id]) => {
            const elem = document.getElementById(id);
            if (elem) elem.textContent = stats[name];
        });
    },

    /**
     * Show create profile modal
     */
    showCreateProfileModal() {
        const modal = document.getElementById('consumption-profile-modal');
        const title = document.getElementById('consumption-profile-modal-title');
        const form = document.getElementById('consumption-profile-form');
        
        if (!modal || !title || !form) return;
        
        title.textContent = 'Create Consumption Profile';
        form.reset();
        document.getElementById('consumption-profile-id').value = '';
        document.getElementById('consumption-profile-is-active').checked = true;
        modal.classList.remove('hidden');
    },

    /**
     * Show edit profile modal
     */
    showEditProfileModal(profileId) {
        const profile = this.currentProfiles.find(p => p.id === profileId);
        if (!profile) return;
        
        const modal = document.getElementById('consumption-profile-modal');
        const title = document.getElementById('consumption-profile-modal-title');
        
        if (!modal || !title) return;
        
        title.textContent = 'Edit Consumption Profile';
        
        // Fill form with profile data
        document.getElementById('consumption-profile-id').value = profile.id;
        document.getElementById('consumption-profile-name').value = profile.name;
        document.getElementById('consumption-profile-description').value = profile.description || '';
        document.getElementById('consumption-profile-is-default').checked = profile.is_default;
        document.getElementById('consumption-profile-is-active').checked = profile.is_active;
        document.getElementById('consumption-profile-prompts-hour').value = profile.prompts_per_hour || '';
        document.getElementById('consumption-profile-prompts-day').value = profile.prompts_per_day || '';
        document.getElementById('consumption-profile-input-tokens').value = profile.input_tokens_per_month || '';
        document.getElementById('consumption-profile-output-tokens').value = profile.output_tokens_per_month || '';
        
        modal.classList.remove('hidden');
    },

    /**
     * Hide profile modal
     */
    hideProfileModal() {
        const modal = document.getElementById('consumption-profile-modal');
        if (modal) {
            modal.classList.add('hidden');
            document.getElementById('consumption-profile-form').reset();
        }
    },

    /**
     * Handle profile form submission
     */
    async handleProfileFormSubmit(e) {
        e.preventDefault();
        
        const profileId = document.getElementById('consumption-profile-id').value;
        const isEdit = !!profileId;
        
        // Get form values
        const profileData = {
            name: document.getElementById('consumption-profile-name').value,
            description: document.getElementById('consumption-profile-description').value || null,
            is_default: document.getElementById('consumption-profile-is-default').checked,
            is_active: document.getElementById('consumption-profile-is-active').checked,
            prompts_per_hour: this.parseIntOrNull('consumption-profile-prompts-hour'),
            prompts_per_day: this.parseIntOrNull('consumption-profile-prompts-day'),
            config_changes_per_hour: 10,
            input_tokens_per_month: this.parseIntOrNull('consumption-profile-input-tokens'),
            output_tokens_per_month: this.parseIntOrNull('consumption-profile-output-tokens')
        };
        
        try {
            const token = localStorage.getItem('tda_auth_token');
            const url = isEdit 
                ? `/api/v1/auth/admin/consumption-profiles/${profileId}`
                : '/api/v1/auth/admin/consumption-profiles';
            const method = isEdit ? 'PUT' : 'POST';
            
            const response = await fetch(url, {
                method: method,
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(profileData)
            });
            
            const data = await response.json();
            
            if (data.status === 'success') {
                window.showNotification('success', `Profile ${isEdit ? 'updated' : 'created'} successfully`);
                this.hideProfileModal();
                await this.loadProfiles();
                await this.loadUsers(); // Refresh users to update dropdowns
            } else {
                window.showNotification('error', data.message || `Failed to ${isEdit ? 'update' : 'create'} profile`);
            }
        } catch (error) {
            console.error('[AdminManager] Error saving profile:', error);
            window.showNotification('error', `Failed to ${isEdit ? 'update' : 'create'} profile`);
        }
    },

    /**
     * Parse integer or return null
     */
    parseIntOrNull(elementId) {
        const value = document.getElementById(elementId).value.trim();
        return value === '' ? null : parseInt(value);
    },

    /**
     * Load user consumption data
     */
    async loadUserConsumption() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            
            // Use new DB-backed endpoint for fast consumption queries
            const response = await fetch(`/api/v1/consumption/users?limit=1000`, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (!data.users) {
                throw new Error('Invalid response format');
            }

            // Transform data to match expected format
            const consumptionData = data.users.map(userData => {
                const inputPercentage = userData.input_tokens_limit 
                    ? (userData.total_input_tokens / userData.input_tokens_limit * 100)
                    : 0;
                const outputPercentage = userData.output_tokens_limit
                    ? (userData.total_output_tokens / userData.output_tokens_limit * 100)
                    : 0;
                
                return {
                    user: {
                        id: userData.user_id,
                        username: userData.username,
                        email: userData.email
                    },
                    consumption: {
                        period: userData.current_period,
                        profile_name: 'N/A',
                        profile_id: null,
                        input_tokens: {
                            used: userData.total_input_tokens,
                            limit: userData.input_tokens_limit,
                            remaining: userData.input_tokens_remaining,
                            percentage_used: Math.round(inputPercentage)
                        },
                        output_tokens: {
                            used: userData.total_output_tokens,
                            limit: userData.output_tokens_limit,
                            remaining: userData.output_tokens_remaining,
                            percentage_used: Math.round(outputPercentage)
                        },
                        has_quota: userData.input_tokens_limit !== null || userData.output_tokens_limit !== null
                    }
                };
            });

            this.currentConsumptionData = consumptionData;
            this.renderUserConsumption(consumptionData);
            this.updateConsumptionKPIs(consumptionData);
            
        } catch (error) {
            console.error('[AdminManager] Error loading consumption:', error);
            window.showNotification('error', 'Failed to load consumption data');
        }
    },

    /**
     * Sort consumption table
     */
    sortConsumptionTable(column) {
        // Toggle direction if clicking same column
        if (this.consumptionSortColumn === column) {
            this.consumptionSortDirection = this.consumptionSortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this.consumptionSortColumn = column;
            this.consumptionSortDirection = 'asc';
        }

        // Sort the data
        const sortedData = [...this.currentConsumptionData].sort((a, b) => {
            let aVal, bVal;

            switch (column) {
                case 'username':
                    aVal = a.user.username.toLowerCase();
                    bVal = b.user.username.toLowerCase();
                    break;
                case 'profile':
                    aVal = (a.user.consumption_profile_name || 'Unlimited').toLowerCase();
                    bVal = (b.user.consumption_profile_name || 'Unlimited').toLowerCase();
                    break;
                case 'input':
                    aVal = a.consumption?.input_tokens?.used || 0;
                    bVal = b.consumption?.input_tokens?.used || 0;
                    break;
                case 'output':
                    aVal = a.consumption?.output_tokens?.used || 0;
                    bVal = b.consumption?.output_tokens?.used || 0;
                    break;
                case 'total':
                    const aInput = a.consumption?.input_tokens?.used || 0;
                    const aOutput = a.consumption?.output_tokens?.used || 0;
                    aVal = aInput + aOutput;
                    const bInput = b.consumption?.input_tokens?.used || 0;
                    const bOutput = b.consumption?.output_tokens?.used || 0;
                    bVal = bInput + bOutput;
                    break;
                case 'inputPercent':
                    aVal = a.consumption?.input_tokens?.percentage_used || 0;
                    bVal = b.consumption?.input_tokens?.percentage_used || 0;
                    break;
                case 'outputPercent':
                    aVal = a.consumption?.output_tokens?.percentage_used || 0;
                    bVal = b.consumption?.output_tokens?.percentage_used || 0;
                    break;
                case 'status':
                    // Status priority: Critical > Warning > Moderate > Good > Unlimited
                    const getStatusPriority = (item) => {
                        if (!item.consumption?.input_tokens?.limit && !item.consumption?.output_tokens?.limit) return 0;
                        const inputPercent = item.consumption?.input_tokens?.percentage_used || 0;
                        const outputPercent = item.consumption?.output_tokens?.percentage_used || 0;
                        const maxPercent = Math.max(inputPercent, outputPercent);
                        if (maxPercent >= 90) return 4;
                        if (maxPercent >= 75) return 3;
                        if (maxPercent >= 50) return 2;
                        return 1;
                    };
                    aVal = getStatusPriority(a);
                    bVal = getStatusPriority(b);
                    break;
                default:
                    return 0;
            }

            // Compare
            if (typeof aVal === 'string') {
                return this.consumptionSortDirection === 'asc' ? 
                    aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
            } else {
                return this.consumptionSortDirection === 'asc' ? 
                    aVal - bVal : bVal - aVal;
            }
        });

        // Update sort indicators
        document.querySelectorAll('#user-consumption-subtab th[data-sort]').forEach(th => {
            const svg = th.querySelector('svg');
            if (th.dataset.sort === column) {
                th.classList.add('text-[#F15F22]');
                if (svg) {
                    svg.style.opacity = '1';
                    svg.style.transform = this.consumptionSortDirection === 'desc' ? 'rotate(180deg)' : 'rotate(0deg)';
                }
            } else {
                th.classList.remove('text-[#F15F22]');
                if (svg) {
                    svg.style.opacity = '0.5';
                    svg.style.transform = 'rotate(0deg)';
                }
            }
        });

        this.renderUserConsumption(sortedData);
    },

    /**
     * Render user consumption table
     */
    renderUserConsumption(consumptionData) {
        const tbody = document.getElementById('user-consumption-table-body');
        if (!tbody) return;

        if (consumptionData.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="px-6 py-8 text-center text-gray-400">
                        No consumption data available
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = consumptionData.map(({ user, consumption }) => {
            const profileName = user.consumption_profile_name || consumption?.profile_name || 'Unlimited';
            
            if (!consumption) {
                return `
                    <tr class="bg-gray-800/50 hover:bg-gray-700/50 transition-colors">
                        <td class="px-6 py-4 font-medium text-white">${this.escapeHtml(user.username)}</td>
                        <td class="px-6 py-4">
                            <span class="px-3 py-1 rounded-full text-xs font-semibold ${this.getProfileBadgeClass(profileName)}">
                                ${this.escapeHtml(profileName)}
                            </span>
                        </td>
                        <td colspan="6" class="px-6 py-4 text-center text-gray-500 text-sm">Failed to load consumption data</td>
                    </tr>
                `;
            }

            const inputTokens = consumption.input_tokens?.used || 0;
            const outputTokens = consumption.output_tokens?.used || 0;
            const totalTokens = inputTokens + outputTokens;
            const inputLimit = consumption.input_tokens?.limit;
            const outputLimit = consumption.output_tokens?.limit;
            const inputPercent = consumption.input_tokens?.percentage_used || 0;
            const outputPercent = consumption.output_tokens?.percentage_used || 0;
            
            const getStatusBadge = () => {
                if (!inputLimit && !outputLimit) {
                    return '<span class="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">Unlimited</span>';
                }
                const maxPercent = Math.max(inputPercent, outputPercent);
                if (maxPercent >= 90) return '<span class="px-2 py-1 rounded text-xs bg-red-500/20 text-red-400">Critical</span>';
                if (maxPercent >= 75) return '<span class="px-2 py-1 rounded text-xs bg-orange-500/20 text-orange-400">Warning</span>';
                if (maxPercent >= 50) return '<span class="px-2 py-1 rounded text-xs bg-yellow-500/20 text-yellow-400">Moderate</span>';
                return '<span class="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">Good</span>';
            };

            // Calculate max usage percentage
            const maxPercent = Math.max(inputPercent, outputPercent);
            const limitDisplay = (inputLimit && outputLimit) ? 
                `${this.formatTokens(Math.max(inputLimit, outputLimit))}` : 
                '<span class="text-gray-500">∞</span>';

            return `
                <tr class="bg-gray-800/50 hover:bg-gray-700/50 transition-colors">
                    <td class="px-6 py-4 font-medium text-white">${this.escapeHtml(user.username)}</td>
                    <td class="px-6 py-4">
                        <span class="px-3 py-1 rounded-full text-xs font-semibold ${this.getProfileBadgeClass(profileName)}">
                            ${this.escapeHtml(profileName)}
                        </span>
                    </td>
                    <td class="px-6 py-4 text-center text-gray-300 font-semibold">${this.formatTokens(totalTokens)}</td>
                    <td class="px-6 py-4 text-center text-gray-300">${limitDisplay}</td>
                    <td class="px-6 py-4 text-center">
                        ${(inputLimit || outputLimit) ? 
                            `<div class="flex flex-col items-center">
                                <span class="text-sm ${maxPercent >= 90 ? 'text-red-400' : maxPercent >= 75 ? 'text-orange-400' : 'text-gray-300'}">${Math.round(maxPercent)}%</span>
                                <div class="w-full bg-gray-700 rounded-full h-1.5 mt-1">
                                    <div class="h-1.5 rounded-full ${maxPercent >= 90 ? 'bg-red-500' : maxPercent >= 75 ? 'bg-orange-500' : 'bg-blue-500'}" style="width: ${Math.min(maxPercent, 100)}%"></div>
                                </div>
                            </div>` 
                            : '<span class="text-gray-500">∞</span>'}
                    </td>
                    <td class="px-6 py-4 text-center">${getStatusBadge()}</td>
                    <td class="px-6 py-4 text-center">
                        <button class="text-blue-400 hover:text-blue-300 text-sm" onclick="AdminManager.viewUserDetails('${user.id}')">View</button>
                    </td>
                </tr>
            `;
        }).join('');
    },

    /**
     * Update consumption KPIs
     */
    updateConsumptionKPIs(consumptionData) {
        let totalInput = 0;
        let totalOutput = 0;
        let activeUsers = 0;

        consumptionData.forEach(({ consumption }) => {
            if (consumption) {
                const inputUsed = consumption.input_tokens?.used || 0;
                const outputUsed = consumption.output_tokens?.used || 0;
                totalInput += inputUsed;
                totalOutput += outputUsed;
                if (inputUsed > 0 || outputUsed > 0) {
                    activeUsers++;
                }
            }
        });

        const avgTokens = activeUsers > 0 ? Math.round((totalInput + totalOutput) / activeUsers) : 0;

        const totalInputElem = document.getElementById('consumption-total-input-tokens');
        const totalOutputElem = document.getElementById('consumption-total-output-tokens');
        const activeUsersElem = document.getElementById('consumption-active-users-count');
        const avgTokensElem = document.getElementById('consumption-avg-tokens-per-user');

        if (totalInputElem) totalInputElem.textContent = this.formatTokens(totalInput);
        if (totalOutputElem) totalOutputElem.textContent = this.formatTokens(totalOutput);
        if (activeUsersElem) activeUsersElem.textContent = activeUsers;
        if (avgTokensElem) avgTokensElem.textContent = this.formatTokens(avgTokens);

        // Update period labels based on actual data
        const period = consumptionData.length > 0 && consumptionData[0].consumption?.period 
            ? consumptionData[0].consumption.period 
            : null;
        
        if (period) {
            const periodLabel = this.formatPeriodLabel(period);
            const periodLabel1 = document.getElementById('consumption-period-label-1');
            const periodLabel2 = document.getElementById('consumption-period-label-2');
            const periodLabel4 = document.getElementById('consumption-period-label-4');
            
            if (periodLabel1) periodLabel1.textContent = periodLabel;
            if (periodLabel2) periodLabel2.textContent = periodLabel;
            if (periodLabel4) periodLabel4.textContent = periodLabel;
        }
    },

    /**
     * Format period string (YYYY-MM) to readable format
     */
    formatPeriodLabel(period) {
        const [year, month] = period.split('-');
        const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
                           'July', 'August', 'September', 'October', 'November', 'December'];
        const monthIndex = parseInt(month, 10) - 1;
        return `${monthNames[monthIndex]} ${year}`;
    },

    /**
     * Delete profile
     */
    async deleteProfile(profileId) {
        const profile = this.currentProfiles.find(p => p.id === profileId);
        if (!profile) return;

        if (profile.user_count > 0) {
            window.showNotification('error', 'Cannot delete profile with assigned users');
            return;
        }

        if (!confirm(`Delete profile "${profile.name}"?`)) return;

        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch(`/api/v1/auth/admin/consumption-profiles/${profileId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();

            if (data.status === 'success') {
                window.showNotification('success', 'Profile deleted successfully');
                await this.loadProfiles();
            } else {
                window.showNotification('error', data.message || 'Failed to delete profile');
            }
        } catch (error) {
            console.error('[AdminManager] Error deleting profile:', error);
            window.showNotification('error', 'Failed to delete profile');
        }
    },

    /**
     * Load all features from API
     */
    async loadFeatures() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch('/api/v1/admin/features', {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            
            if (data.status === 'success') {
                this.currentFeatures = data.features;
                this.featureChanges = {}; // Reset changes
                this.renderFeatures();
                this.updateFeatureStats(data.feature_count_by_tier);
            } else {
                window.showNotification('error', data.message || 'Failed to load features');
            }
        } catch (error) {
            console.error('[AdminManager] Error loading features:', error);
            window.showNotification('error', 'Failed to load features');
        }
    },

    /**
     * Render features table
     */
    renderFeatures() {
        const tbody = document.getElementById('features-table-body');
        if (!tbody) return;

        if (this.currentFeatures.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="px-6 py-8 text-center text-gray-400">
                        No features found
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.currentFeatures.map(feature => `
            <tr class="bg-gray-800/50 hover:bg-gray-700/50 transition-colors feature-row" data-feature="${feature.name}" data-tier="${feature.required_tier}" data-category="${feature.category}">
                <td class="px-6 py-4 font-medium text-white">${this.escapeHtml(feature.display_name)}</td>
                <td class="px-6 py-4 text-gray-400 text-sm">${this.escapeHtml(feature.description)}</td>
                <td class="px-6 py-4">
                    <select 
                        class="feature-tier-select p-2 bg-gray-700 border border-gray-600 rounded-md text-sm text-white focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none"
                        data-feature-name="${feature.name}"
                    >
                        <option value="user" ${feature.required_tier === 'user' ? 'selected' : ''}>User</option>
                        <option value="developer" ${feature.required_tier === 'developer' ? 'selected' : ''}>Developer</option>
                        <option value="admin" ${feature.required_tier === 'admin' ? 'selected' : ''}>Admin</option>
                    </select>
                </td>
                <td class="px-6 py-4 text-gray-400 text-sm">${this.escapeHtml(feature.category)}</td>
            </tr>
        `).join('');

        // Attach change listeners
        tbody.querySelectorAll('.feature-tier-select').forEach(select => {
            select.addEventListener('change', (e) => {
                const featureName = e.target.dataset.featureName;
                const newTier = e.target.value;
                this.featureChanges[featureName] = newTier;
                this.updateSaveButtonState();
            });
        });
    },

    /**
     * Update save button state
     */
    updateSaveButtonState() {
        const saveBtn = document.getElementById('save-features-btn');
        if (saveBtn) {
            const hasChanges = Object.keys(this.featureChanges).length > 0;
            if (hasChanges) {
                saveBtn.classList.add('ring-2', 'ring-yellow-400');
                saveBtn.textContent = `Save Changes (${Object.keys(this.featureChanges).length})`;
            } else {
                saveBtn.classList.remove('ring-2', 'ring-yellow-400');
                saveBtn.textContent = 'Save Changes';
            }
        }
    },

    /**
     * Filter features by search term
     */
    filterFeatures(searchTerm) {
        const term = searchTerm.toLowerCase();
        document.querySelectorAll('.feature-row').forEach(row => {
            const featureName = row.dataset.feature.toLowerCase();
            const description = row.querySelector('td:nth-child(2)').textContent.toLowerCase();
            const matches = featureName.includes(term) || description.includes(term);
            row.style.display = matches ? '' : 'none';
        });
    },

    /**
     * Filter features by tier
     */
    filterFeaturesByTier(tier) {
        document.querySelectorAll('.feature-row').forEach(row => {
            if (!tier || row.dataset.tier === tier) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    },

    /**
     * Update feature statistics
     */
    updateFeatureStats(tierCounts) {
        if (tierCounts) {
            document.getElementById('user-features-count').textContent = tierCounts.user || 0;
            document.getElementById('developer-features-count').textContent = tierCounts.developer || 0;
            document.getElementById('admin-features-count').textContent = tierCounts.admin || 0;
        }
    },

    /**
     * Save feature changes
     */
    async saveFeatureChanges() {
        if (Object.keys(this.featureChanges).length === 0) {
            window.showNotification('info', 'No changes to save');
            return;
        }

        try {
            const changes = Object.entries(this.featureChanges);
            let successCount = 0;
            let errorCount = 0;

            for (const [featureName, newTier] of changes) {
                try {
                    const token = localStorage.getItem('tda_auth_token');
                    const response = await fetch(`/api/v1/admin/features/${featureName}/tier`, {
                        method: 'PATCH',
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ required_tier: newTier })
                    });
                    const data = await response.json();
                    
                    if (data.status === 'success') {
                        successCount++;
                    } else {
                        errorCount++;
                    }
                } catch (error) {
                    errorCount++;
                }
            }

            if (successCount > 0) {
                window.showNotification('success', `Updated ${successCount} feature(s)`);
            }
            if (errorCount > 0) {
                window.showNotification('error', `Failed to update ${errorCount} feature(s)`);
            }

            // Reload features to get fresh data
            await this.loadFeatures();

        } catch (error) {
            console.error('[AdminManager] Error saving feature changes:', error);
            window.showNotification('error', 'Failed to save changes');
        }
    },

    /**
     * Reset features to defaults
     */
    async resetFeatures() {
        if (!window.showConfirmation) {
            console.error('Confirmation system not available');
            return;
        }
        
        window.showConfirmation(
            'Reset Feature Tiers',
            'Are you sure you want to reset all feature tiers to their default values?',
            async () => {
                try {
                    const token = localStorage.getItem('tda_auth_token');
                    const response = await fetch('/api/v1/admin/features/reset', {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json'
                        }
                    });
                    const data = await response.json();
                    
                    if (data.status === 'success') {
                        window.showNotification('success', data.message || 'Features reset to defaults');
                        await this.loadFeatures();
                    } else {
                        window.showNotification('error', data.message || 'Failed to reset features');
                    }
                } catch (error) {
                    console.error('[AdminManager] Error resetting features:', error);
                    window.showNotification('error', 'Failed to reset features');
                }
            }
        );
    },

    /**
     * Show create user modal
     */
    showCreateUserModal() {
        const modal = document.getElementById('user-modal-overlay');
        const form = document.getElementById('user-form');
        const title = document.getElementById('user-modal-title');
        const passwordContainer = document.getElementById('user-form-password-container');
        
        title.textContent = 'Create User';
        form.reset();
        document.getElementById('user-form-id').value = '';
        document.getElementById('user-form-password').required = true;
        document.getElementById('password-optional-text').style.display = 'none';
        passwordContainer.style.display = 'block';
        
        modal.classList.remove('hidden');
    },
    
    /**
     * Show edit user modal
     */
    showEditUserModal(userId) {
        const user = this.currentUsers.find(u => u.id === userId);
        if (!user) return;
        
        const modal = document.getElementById('user-modal-overlay');
        const form = document.getElementById('user-form');
        const title = document.getElementById('user-modal-title');
        const passwordContainer = document.getElementById('user-form-password-container');
        
        title.textContent = 'Edit User';
        document.getElementById('user-form-id').value = user.id;
        document.getElementById('user-form-username').value = user.username;
        document.getElementById('user-form-email').value = user.email || '';
        document.getElementById('user-form-display-name').value = user.display_name || '';
        document.getElementById('user-form-tier').value = user.profile_tier;
        document.getElementById('user-form-password').required = false;
        document.getElementById('user-form-password').value = '';
        document.getElementById('password-optional-text').style.display = 'inline';
        passwordContainer.style.display = 'block'; // Show password field for optional reset
        
        modal.classList.remove('hidden');
    },
    
    /**
     * Hide user modal
     */
    hideUserModal() {
        const modal = document.getElementById('user-modal-overlay');
        modal.classList.add('hidden');
    },
    
    /**
     * Save user (create or update)
     */
    async saveUser(formData) {
        // Prevent double submission
        if (this._savingUser) {
            console.log('[AdminManager] Save already in progress, ignoring duplicate request');
            return;
        }
        
        this._savingUser = true;
        
        try {
            const userId = formData.id;
            const token = localStorage.getItem('tda_auth_token');
            const isEdit = !!userId;
            
            // Validate required fields for new user
            if (!isEdit) {
                if (!formData.username || !formData.email || !formData.password) {
                    window.showNotification('error', 'Please fill in all required fields (username, email, password)');
                    this._savingUser = false;
                    return;
                }
            }
            
            const url = isEdit ? `/api/v1/admin/users/${userId}` : '/api/v1/admin/users';
            const method = isEdit ? 'PATCH' : 'POST';
            
            const payload = {
                username: formData.username,
                email: formData.email,
                display_name: formData.displayName,
                profile_tier: formData.tier
            };
            
            if (!isEdit || formData.password) {
                payload.password = formData.password;
            }
            
            console.log('[AdminManager] Saving user:', { method, url, payload: { ...payload, password: '***' } });
            
            const response = await fetch(url, {
                method,
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            
            const data = await response.json();
            console.log('[AdminManager] Save user response:', { status: response.status, data });
            
            // Check both HTTP status code and response data status
            if (response.ok && data.status === 'success') {
                window.showNotification('success', isEdit ? 'User updated successfully' : 'User created successfully');
                this.hideUserModal();
                await this.loadUsers();
            } else {
                window.showNotification('error', data.message || 'Failed to save user');
            }
        } catch (error) {
            console.error('[AdminManager] Error saving user:', error);
            window.showNotification('error', 'Failed to save user');
        } finally {
            this._savingUser = false;
        }
    },
    
    /**
     * Deactivate a user
     */
    async deactivateUser(userId) {
        const user = this.currentUsers.find(u => u.id === userId);
        if (!user) return;

        if (!window.showConfirmation) {
            console.error('Confirmation system not available');
            return;
        }

        window.showConfirmation(
            'Deactivate User',
            `Deactivate user "${user.username}"? They will not be able to log in.`,
            async () => {
                await this.setUserStatus(userId, false);
            }
        );
    },

    /**
     * Activate a user
     */
    async activateUser(userId) {
        const user = this.currentUsers.find(u => u.id === userId);
        if (!user) return;
        
        await this.setUserStatus(userId, true);
    },

    /**
     * Helper to set user's active status
     */
    async setUserStatus(userId, isActive) {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const response = await fetch(`/api/v1/admin/users/${userId}`, {
                method: 'PATCH',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ is_active: isActive })
            });

            const data = await response.json();

            if (data.status === 'success') {
                window.showNotification('success', `User successfully ${isActive ? 'activated' : 'deactivated'}`);
                await this.loadUsers();
            } else {
                window.showNotification('error', data.message || 'Failed to update user status');
            }
        } catch (error) {
            console.error('[AdminManager] Error updating user status:', error);
            window.showNotification('error', 'Failed to update user status');
        }
    },

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text ? String(text).replace(/[&<>"']/g, m => map[m]) : '';
    },

    // ==============================================================================
    // PANE VISIBILITY MANAGEMENT
    // ==============================================================================

    currentPanes: [],

    /**
     * Load pane visibility configuration
     */
    async loadPanes() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) {
                window.showNotification('error', 'Not authenticated');
                return;
            }

            const response = await fetch('/api/v1/admin/panes', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            
            if (data.status === 'success') {
                this.currentPanes = data.panes || [];
                this.renderPanes();
            } else {
                window.showNotification('error', data.message || 'Failed to load panes');
            }
        } catch (error) {
            console.error('[AdminManager] Error loading panes:', error);
            window.showNotification('error', 'Failed to load panes');
        }
    },

    /**
     * Render panes table
     */
    renderPanes() {
        const tbody = document.getElementById('panes-table-body');
        if (!tbody) return;

        if (this.currentPanes.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="px-6 py-8 text-center text-gray-400">
                        No panes configured
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.currentPanes.map(pane => {
            const isAdminPane = pane.pane_id === 'admin';
            
            return `
                <tr class="hover:bg-white/5 transition-colors">
                    <td class="px-6 py-4">
                        <div class="flex items-center gap-2">
                            <span class="font-medium text-white">${this.escapeHtml(pane.pane_name)}</span>
                            ${isAdminPane ? '<span class="text-xs px-2 py-0.5 bg-red-500/20 text-red-400 rounded-full">Protected</span>' : ''}
                        </div>
                    </td>
                    <td class="px-6 py-4">
                        <span class="text-sm text-gray-400">${this.escapeHtml(pane.description || '')}</span>
                    </td>
                    <td class="px-6 py-4 text-center">
                        <label class="inline-flex items-center cursor-pointer">
                            <input type="checkbox" 
                                class="pane-visibility-checkbox sr-only peer" 
                                style="position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border-width: 0 !important;"
                                data-pane-id="${pane.pane_id}" 
                                data-tier="user"
                                ${pane.visible_to_user ? 'checked' : ''}>
                            <div class="relative w-11 h-6 bg-gray-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-800 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                        </label>
                    </td>
                    <td class="px-6 py-4 text-center">
                        <label class="inline-flex items-center cursor-pointer">
                            <input type="checkbox" 
                                class="pane-visibility-checkbox sr-only peer" 
                                style="position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border-width: 0 !important;"
                                data-pane-id="${pane.pane_id}" 
                                data-tier="developer"
                                ${pane.visible_to_developer ? 'checked' : ''}>
                            <div class="relative w-11 h-6 bg-gray-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-purple-800 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-purple-600"></div>
                        </label>
                    </td>
                    <td class="px-6 py-4 text-center">
                        <label class="inline-flex items-center cursor-pointer">
                            <input type="checkbox" 
                                class="pane-visibility-checkbox sr-only peer" 
                                style="position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border-width: 0 !important;"
                                data-pane-id="${pane.pane_id}" 
                                data-tier="admin"
                                ${pane.visible_to_admin ? 'checked' : ''}
                                ${isAdminPane ? 'disabled' : ''}>
                            <div class="relative w-11 h-6 bg-gray-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-red-800 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-red-600 ${isAdminPane ? 'opacity-50 cursor-not-allowed' : ''}"></div>
                        </label>
                    </td>
                </tr>
            `;
        }).join('');

        // Add event listeners to checkboxes
        const checkboxes = tbody.querySelectorAll('.pane-visibility-checkbox');
        console.log(`[AdminManager] Found ${checkboxes.length} pane visibility checkboxes`);
        
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const paneId = e.target.dataset.paneId;
                const tier = e.target.dataset.tier;
                const visible = e.target.checked;
                console.log(`[AdminManager] Checkbox changed: paneId=${paneId}, tier=${tier}, visible=${visible}`);
                this.updatePaneVisibility(paneId, tier, visible);
            });
        });
    },

    /**
     * Update pane visibility for a specific tier
     */
    async updatePaneVisibility(paneId, tier, visible) {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) {
                window.showNotification('error', 'Not authenticated');
                return;
            }

            const updateData = {};
            updateData[`visible_to_${tier}`] = visible;

            const response = await fetch(`/api/v1/admin/panes/${paneId}/visibility`, {
                method: 'PATCH',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(updateData)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            
            if (data.status === 'success') {
                window.showNotification('success', `Pane visibility updated for ${tier} tier`);
                
                // Update local state
                const paneIndex = this.currentPanes.findIndex(p => p.pane_id === paneId);
                if (paneIndex !== -1) {
                    this.currentPanes[paneIndex] = data.pane;
                }
                
                // Trigger pane visibility refresh for current user if needed
                if (typeof window.updatePaneVisibility === 'function') {
                    window.updatePaneVisibility();
                }
            } else {
                window.showNotification('error', data.message || 'Failed to update pane visibility');
                // Reload to reset UI
                await this.loadPanes();
            }
        } catch (error) {
            console.error('[AdminManager] Error updating pane visibility:', error);
            window.showNotification('error', 'Failed to update pane visibility');
            // Reload to reset UI
            await this.loadPanes();
        }
    },

    /**
     * Reset all pane visibility to defaults
     */
    async resetPanes() {
        if (!window.showConfirmation) {
            console.error('Confirmation system not available');
            return;
        }
        
        window.showConfirmation(
            'Reset Pane Visibility',
            'Reset all pane visibility to default configuration? This will override all custom settings.',
            async () => {
                try {
                    const token = localStorage.getItem('tda_auth_token');
                    if (!token) {
                        window.showNotification('error', 'Not authenticated');
                        return;
                    }

                    const response = await fetch('/api/v1/admin/panes/reset', {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`
                        }
                    });

                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }

                    const data = await response.json();
            
            if (data.status === 'success') {
                window.showNotification('success', 'Pane visibility reset to defaults');
                this.currentPanes = data.panes || [];
                this.renderPanes();
                
                // Trigger pane visibility refresh for current user
                if (typeof window.updatePaneVisibility === 'function') {
                    window.updatePaneVisibility();
                }
            } else {
                window.showNotification('error', data.message || 'Failed to reset panes');
            }
        } catch (error) {
            console.error('[AdminManager] Error resetting panes:', error);
            window.showNotification('error', 'Failed to reset panes');
        }
            }
        );
    },

    /**
     * Run MCP Resource Classification
     */
    async runMcpClassification() {
        const statusEl = document.getElementById('mcp-classification-status');
        const detailsEl = document.getElementById('mcp-classification-details');
        const progressEl = document.getElementById('mcp-classification-progress');
        const button = document.getElementById('run-mcp-classification-btn');

        try {
            // Show progress
            if (progressEl) progressEl.classList.remove('hidden');
            if (button) button.disabled = true;
            if (statusEl) statusEl.textContent = 'Initializing services...';
            if (detailsEl) detailsEl.textContent = '';

            const token = localStorage.getItem('tda_auth_token');
            if (!token) {
                window.showNotification('error', 'Not authenticated');
                return;
            }

            const response = await fetch('/api/v1/admin/mcp-classification', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }

            const data = await response.json();
            
            if (data.status === 'success') {
                window.showNotification('success', 'MCP classification completed successfully');
                if (statusEl) statusEl.textContent = 'Classification completed successfully';
                if (detailsEl) {
                    const details = [];
                    if (data.categories_count) details.push(`${data.categories_count} categories created`);
                    if (data.tools_count) details.push(`${data.tools_count} tools classified`);
                    if (data.prompts_count) details.push(`${data.prompts_count} prompts classified`);
                    if (data.resources_count) details.push(`${data.resources_count} resources classified`);
                    detailsEl.textContent = details.join(' • ');
                }
            } else {
                throw new Error(data.message || 'Classification failed');
            }
        } catch (error) {
            console.error('[AdminManager] Error running MCP classification:', error);
            
            // Show error in header banner
            const headerBanner = document.getElementById('header-status-message');
            if (headerBanner) {
                headerBanner.textContent = error.message;
                headerBanner.className = 'text-sm px-3 py-1 rounded-md bg-red-500/20 border border-red-400/40 text-red-200';
                headerBanner.style.opacity = '1';
                
                // Auto-hide after 10 seconds
                setTimeout(() => {
                    headerBanner.style.opacity = '0';
                    setTimeout(() => {
                        headerBanner.textContent = '';
                        headerBanner.className = 'text-sm px-3 py-1 rounded-md transition-all duration-300 opacity-0';
                    }, 300);
                }, 10000);
            }
            
            if (statusEl) statusEl.textContent = 'Ready to classify';
            if (detailsEl) detailsEl.textContent = '';
        } finally {
            // Hide progress
            if (progressEl) progressEl.classList.add('hidden');
            if (button) button.disabled = false;
        }
    },

    /**
     * Load application configuration settings
     */
    async loadAppConfig() {
        try {
            // Load MCP classification setting
            const response = await fetch('/api/v1/config/classification', {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (response.ok) {
                const result = await response.json();
                const checkbox = document.getElementById('enable-mcp-classification');
                if (checkbox) {
                    checkbox.checked = result.enable_mcp_classification;
                }
            }
        } catch (error) {
            console.error('[AdminManager] Failed to load app configuration:', error);
        }
    },

    /**
     * Save the MCP classification setting
     */
    async saveClassificationSetting(enabled) {
        try {
            const response = await fetch('/api/v1/config/classification', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enable_mcp_classification: enabled })
            });
            
            if (response.ok) {
                const result = await response.json();
                window.showNotification('success', result.message || 'Classification setting updated');
            } else {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.message || 'Failed to update setting');
            }
        } catch (error) {
            console.error('[AdminManager] Failed to save classification setting:', error);
            window.showNotification('error', `Failed to save setting: ${error.message}`);
            
            // Revert checkbox on error
            const checkbox = document.getElementById('enable-mcp-classification');
            if (checkbox) {
                checkbox.checked = !enabled;
            }
        }
    },

    /**
     * Load expert settings from backend
     */
    async loadExpertSettings() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) return;

            const response = await fetch('/api/v1/admin/expert-settings', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (response.ok) {
                const data = await response.json();
                if (data.status === 'success' && data.settings) {
                    const s = data.settings;
                    
                    // LLM Behavior
                    if (s.llm_behavior) {
                        this.setFieldValue('llm-max-retries', s.llm_behavior.max_retries);
                        this.setFieldValue('llm-base-delay', s.llm_behavior.base_delay);
                    }
                    
                    // Agent Configuration
                    if (s.agent_config) {
                        this.setFieldValue('max-execution-steps', s.agent_config.max_execution_steps);
                        this.setFieldValue('tool-call-timeout', s.agent_config.tool_call_timeout);
                    }
                    
                    // Performance & Context
                    if (s.performance) {
                        this.setFieldValue('context-max-rows', s.performance.context_max_rows);
                        this.setFieldValue('context-max-chars', s.performance.context_max_chars);
                        this.setFieldValue('description-threshold', s.performance.description_threshold);
                    }
                    
                    // Agent Behavior
                    if (s.agent_behavior) {
                        const allowSynthesis = document.getElementById('allow-synthesis');
                        const forceSubSummary = document.getElementById('force-sub-summary');
                        const condensePrompts = document.getElementById('condense-prompts');
                        if (allowSynthesis) allowSynthesis.checked = s.agent_behavior.allow_synthesis;
                        if (forceSubSummary) forceSubSummary.checked = s.agent_behavior.force_sub_summary;
                        if (condensePrompts) condensePrompts.checked = s.agent_behavior.condense_prompts;
                    }
                    
                    // Query Optimization
                    if (s.query_optimization) {
                        const sqlConsolidation = document.getElementById('enable-sql-consolidation');
                        if (sqlConsolidation) sqlConsolidation.checked = s.query_optimization.enable_sql_consolidation;
                    }
                    
                    // Security
                    if (s.security) {
                        this.setFieldValue('session-timeout', s.security.session_timeout);
                        this.setFieldValue('token-expiry', s.security.token_expiry);
                    }
                }
            }
        } catch (error) {
            console.error('[AdminManager] Error loading expert settings:', error);
        }
    },

    /**
     * Save expert settings to backend
     */
    async saveExpertSettings() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) {
                window.showNotification('error', 'Not authenticated');
                return;
            }

            const settings = {
                llm_behavior: {
                    max_retries: parseInt(this.getFieldValue('llm-max-retries')),
                    base_delay: parseFloat(this.getFieldValue('llm-base-delay'))
                },
                agent_config: {
                    max_execution_steps: parseInt(this.getFieldValue('max-execution-steps')),
                    tool_call_timeout: parseInt(this.getFieldValue('tool-call-timeout'))
                },
                performance: {
                    context_max_rows: parseInt(this.getFieldValue('context-max-rows')),
                    context_max_chars: parseInt(this.getFieldValue('context-max-chars')),
                    description_threshold: parseInt(this.getFieldValue('description-threshold'))
                },
                agent_behavior: {
                    allow_synthesis: document.getElementById('allow-synthesis')?.checked || false,
                    force_sub_summary: document.getElementById('force-sub-summary')?.checked || false,
                    condense_prompts: document.getElementById('condense-prompts')?.checked || false
                },
                query_optimization: {
                    enable_sql_consolidation: document.getElementById('enable-sql-consolidation')?.checked || false
                },
                security: {
                    session_timeout: parseInt(this.getFieldValue('session-timeout')),
                    token_expiry: parseInt(this.getFieldValue('token-expiry'))
                }
            };

            const response = await fetch('/api/v1/admin/expert-settings', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(settings)
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                // Use configurationHandler's notification system (positioned in header)
                if (window.showNotification) {
                    window.showNotification('success', 'Expert settings saved successfully');
                }
            } else {
                if (window.showNotification) {
                    window.showNotification('error', data.message || 'Failed to save settings');
                }
            }
        } catch (error) {
            console.error('[AdminManager] Error saving expert settings:', error);
            if (window.showNotification) {
                window.showNotification('error', error.message);
            }
        }
    },

    /**
     * Clear application cache
     */
    async clearCache() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) return;

            const response = await fetch('/api/v1/admin/clear-cache', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                window.showNotification('success', 'Cache cleared successfully');
            } else {
                throw new Error(data.message || 'Failed to clear cache');
            }
        } catch (error) {
            console.error('[AdminManager] Error clearing cache:', error);
            window.showNotification('error', error.message);
        }
    },

    /**
     * Reset application state
     */
    async resetState() {
        if (!window.showConfirmation) {
            console.error('Confirmation system not available');
            return;
        }
        
        window.showConfirmation(
            'Reset Application State',
            'This will reset all application state and require reconnection. Continue?',
            async () => {
                try {
                    const token = localStorage.getItem('tda_auth_token');
                    if (!token) return;

                    const response = await fetch('/api/v1/admin/reset-state', {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`
                        }
                    });

                    const data = await response.json();
                    
                    if (response.ok && data.status === 'success') {
                        window.showNotification('success', data.message);
                    } else {
                        throw new Error(data.message || 'Failed to reset state');
                    }
                } catch (error) {
                    console.error('[AdminManager] Error resetting state:', error);
                    window.showNotification('error', error.message);
                }
            }
        );
    },

    /**
     * Load application configuration (feature toggles)
     */
    async loadAppConfig() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) return;

            const response = await fetch('/api/v1/admin/app-config', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                // Set checkbox values
                const ragCheckbox = document.getElementById('enable-rag-system');
                const voiceCheckbox = document.getElementById('enable-voice-system');
                const chartingCheckbox = document.getElementById('enable-charting-system');
                
                if (ragCheckbox) ragCheckbox.checked = data.config.rag_enabled || false;
                if (voiceCheckbox) voiceCheckbox.checked = data.config.voice_conversation_enabled || false;
                if (chartingCheckbox) chartingCheckbox.checked = data.config.charting_enabled || false;
                
                // Set RAG configuration values
                if (data.config.rag_config) {
                    const ragRefreshCheckbox = document.getElementById('rag-refresh-startup');
                    if (ragRefreshCheckbox) ragRefreshCheckbox.checked = data.config.rag_config.refresh_on_startup;
                    
                    this.setFieldValue('rag-num-examples', data.config.rag_config.num_examples);
                    this.setFieldValue('rag-embedding-model', data.config.rag_config.embedding_model);
                }
                
                // Load Knowledge Repository configuration from dedicated endpoint
                try {
                    const knowledgeResp = await fetch('/api/v1/admin/knowledge-config', {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('tda_auth_token')}` }
                    });
                    if (knowledgeResp.ok) {
                        const knowledgeData = await knowledgeResp.json();
                        if (knowledgeData.config) {
                            const kc = knowledgeData.config;
                            const knowledgeEnabledCheckbox = document.getElementById('knowledge-rag-enabled');
                            const knowledgeRerankingCheckbox = document.getElementById('knowledge-reranking-enabled');
                            
                            if (knowledgeEnabledCheckbox) knowledgeEnabledCheckbox.checked = kc.enabled || false;
                            this.setFieldValue('knowledge-num-docs', kc.num_docs);
                            this.setFieldValue('knowledge-min-relevance', kc.min_relevance_score);
                            this.setFieldValue('knowledge-max-tokens', kc.max_tokens);
                            if (knowledgeRerankingCheckbox) knowledgeRerankingCheckbox.checked = kc.reranking_enabled || false;
                        }
                    }
                } catch (knowledgeError) {
                    console.error('[AdminManager] Error loading knowledge config:', knowledgeError);
                }
            }

            // Load window defaults
            await this.loadWindowDefaults();
        } catch (error) {
            console.error('[AdminManager] Error loading app config:', error);
        }
    },

    /**
     * Load window defaults from backend
     */
    async loadWindowDefaults() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) return;

            const response = await fetch('/api/v1/admin/window-defaults', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                const wd = data.window_defaults;
                
                // Session History Panel
                const sessionVisible = document.getElementById('session-history-visible');
                const sessionMode = document.getElementById('session-history-default-mode');
                const sessionToggle = document.getElementById('session-history-user-can-toggle');
                if (sessionVisible) sessionVisible.checked = wd.session_history_visible !== false;
                if (sessionMode) sessionMode.value = wd.session_history_default_mode || 'collapsed';
                if (sessionToggle) sessionToggle.checked = wd.session_history_user_can_toggle !== false;
                
                // Resources Panel
                const resourcesVisible = document.getElementById('resources-visible');
                const resourcesMode = document.getElementById('resources-default-mode');
                const resourcesToggle = document.getElementById('resources-user-can-toggle');
                if (resourcesVisible) resourcesVisible.checked = wd.resources_visible !== false;
                if (resourcesMode) resourcesMode.value = wd.resources_default_mode || 'collapsed';
                if (resourcesToggle) resourcesToggle.checked = wd.resources_user_can_toggle !== false;
                
                // Status Window
                const statusVisible = document.getElementById('status-visible');
                const statusMode = document.getElementById('status-default-mode');
                const statusToggle = document.getElementById('status-user-can-toggle');
                if (statusVisible) statusVisible.checked = wd.status_visible !== false;
                if (statusMode) statusMode.value = wd.status_default_mode || 'collapsed';
                if (statusToggle) statusToggle.checked = wd.status_user_can_toggle !== false;
                
                // Other settings
                const alwaysShowWelcomeCheckbox = document.getElementById('always-show-welcome-screen');
                const defaultThemeSelector = document.getElementById('default-theme-selector');
                if (alwaysShowWelcomeCheckbox) alwaysShowWelcomeCheckbox.checked = wd.always_show_welcome_screen || false;
                if (defaultThemeSelector) defaultThemeSelector.value = wd.default_theme || 'legacy';
            }
        } catch (error) {
            console.error('[AdminManager] Error loading window defaults:', error);
        }
    },

    /**
     * Save window defaults to backend
     */
    async saveWindowDefaults() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) return;

            // Session History Panel
            const sessionVisible = document.getElementById('session-history-visible');
            const sessionMode = document.getElementById('session-history-default-mode');
            const sessionToggle = document.getElementById('session-history-user-can-toggle');
            
            // Resources Panel
            const resourcesVisible = document.getElementById('resources-visible');
            const resourcesMode = document.getElementById('resources-default-mode');
            const resourcesToggle = document.getElementById('resources-user-can-toggle');
            
            // Status Window
            const statusVisible = document.getElementById('status-visible');
            const statusMode = document.getElementById('status-default-mode');
            const statusToggle = document.getElementById('status-user-can-toggle');
            
            // Other settings
            const alwaysShowWelcomeCheckbox = document.getElementById('always-show-welcome-screen');
            const defaultThemeSelector = document.getElementById('default-theme-selector');

            const windowDefaults = {
                // Session History Panel
                session_history_visible: sessionVisible ? sessionVisible.checked : true,
                session_history_default_mode: sessionMode ? sessionMode.value : 'collapsed',
                session_history_user_can_toggle: sessionToggle ? sessionToggle.checked : true,
                
                // Resources Panel
                resources_visible: resourcesVisible ? resourcesVisible.checked : true,
                resources_default_mode: resourcesMode ? resourcesMode.value : 'collapsed',
                resources_user_can_toggle: resourcesToggle ? resourcesToggle.checked : true,
                
                // Status Window
                status_visible: statusVisible ? statusVisible.checked : true,
                status_default_mode: statusMode ? statusMode.value : 'collapsed',
                status_user_can_toggle: statusToggle ? statusToggle.checked : true,
                
                // Other settings
                always_show_welcome_screen: alwaysShowWelcomeCheckbox ? alwaysShowWelcomeCheckbox.checked : false,
                default_theme: defaultThemeSelector ? defaultThemeSelector.value : 'legacy'
            };

            const response = await fetch('/api/v1/admin/window-defaults', {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(windowDefaults)
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                if (window.showNotification) {
                    window.showNotification('success', 'Startup settings saved successfully. Users will see these defaults on next load.');
                }
            } else {
                if (window.showNotification) {
                    window.showNotification('error', data.message || 'Failed to save window defaults');
                }
            }
        } catch (error) {
            console.error('[AdminManager] Error saving window defaults:', error);
            if (window.showNotification) {
                window.showNotification('error', 'Failed to save window defaults');
            }
        }
    },

    /**
     * Save application configuration (feature toggles)
     */
    async saveAppConfig() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) return;

            const ragCheckbox = document.getElementById('enable-rag-system');
            const voiceCheckbox = document.getElementById('enable-voice-system');
            const chartingCheckbox = document.getElementById('enable-charting-system');
            const ragRefreshCheckbox = document.getElementById('rag-refresh-startup');

            const config = {
                rag_enabled: ragCheckbox ? ragCheckbox.checked : false,
                voice_conversation_enabled: voiceCheckbox ? voiceCheckbox.checked : false,
                charting_enabled: chartingCheckbox ? chartingCheckbox.checked : false,
                rag_config: {
                    refresh_on_startup: ragRefreshCheckbox ? ragRefreshCheckbox.checked : true,
                    num_examples: parseInt(this.getFieldValue('rag-num-examples')) || 3,
                    embedding_model: this.getFieldValue('rag-embedding-model') || 'all-MiniLM-L6-v2'
                }
            };

            const response = await fetch('/api/v1/admin/app-config', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(config)
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                // Use configurationHandler's notification system (positioned in header)
                if (window.showNotification) {
                    window.showNotification('success', 'Feature settings saved successfully');
                }
            } else {
                if (window.showNotification) {
                    window.showNotification('error', data.message || 'Failed to save settings');
                }
            }
        } catch (error) {
            console.error('[AdminManager] Error saving app config:', error);
            if (window.showNotification) {
                window.showNotification('error', error.message);
            }
        }
    },

    /**
     * Save knowledge repository configuration
     */
    async saveKnowledgeConfig() {
        try {
            const token = localStorage.getItem('tda_auth_token');
            if (!token) return;

            const knowledgeEnabledCheckbox = document.getElementById('knowledge-rag-enabled');
            const knowledgeRerankingCheckbox = document.getElementById('knowledge-reranking-enabled');

            const config = {
                enabled: knowledgeEnabledCheckbox ? knowledgeEnabledCheckbox.checked : true,
                num_docs: parseInt(this.getFieldValue('knowledge-num-docs')) || 3,
                min_relevance_score: parseFloat(this.getFieldValue('knowledge-min-relevance')) || 0.70,
                max_tokens: parseInt(this.getFieldValue('knowledge-max-tokens')) || 2000,
                reranking_enabled: knowledgeRerankingCheckbox ? knowledgeRerankingCheckbox.checked : false
            };

            const response = await fetch('/api/v1/admin/knowledge-config', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(config)
            });

            const data = await response.json();
            
            if (response.ok && data.status === 'success') {
                if (window.showNotification) {
                    window.showNotification('success', 'Knowledge repository settings saved successfully');
                }
            } else {
                if (window.showNotification) {
                    window.showNotification('error', data.message || 'Failed to save settings');
                }
            }
        } catch (error) {
            console.error('[AdminManager] Error saving knowledge config:', error);
            if (window.showNotification) {
                window.showNotification('error', error.message);
            }
        }
    },

    /**
     * Helper to set field value
     */
    setFieldValue(id, value) {
        const field = document.getElementById(id);
        if (field) field.value = value;
    },

    /**
     * Helper to get field value
     */
    getFieldValue(id) {
        const field = document.getElementById(id);
        return field ? field.value : null;
    },

    // ========================================================================
    // SYSTEM PROMPTS MANAGEMENT
    // ========================================================================

    /**
     * Load system prompt for a specific prompt name
     */
    async loadSystemPromptForTier(promptName) {
        try {
            // Check license tier access (only "Prompt Engineer" and "Enterprise" license tiers can edit)
            const token = authClient ? authClient.getToken() : null;
            let canEdit = false;
            let licenseTier = 'Unknown';
            
            if (token) {
                try {
                    const response = await fetch('/api/v1/auth/me', {
                        headers: { 'Authorization': `Bearer ${token}` }
                    });
                    if (response.ok) {
                        const userData = await response.json();
                        // Check license_info from APP_STATE (stored during license validation)
                        licenseTier = userData.user?.license_tier || 'Unknown';
                        canEdit = licenseTier === 'Prompt Engineer' || licenseTier === 'Enterprise';
                    }
                } catch (error) {
                    console.error('[AdminManager] Error checking license tier:', error);
                }
            }
            
            const notice = document.getElementById('system-prompts-tier-notice');
            const noticeText = notice?.querySelector('p.text-xs');
            const textarea = document.getElementById('system-prompt-editor-textarea');
            const saveBtn = document.getElementById('save-system-prompt-btn');
            const resetBtn = document.getElementById('reset-system-prompt-btn');
            const deleteBtn = document.getElementById('delete-prompt-btn');
            
            // Show/hide notice and disable controls if not authorized
            if (notice) {
                notice.classList.toggle('hidden', canEdit);
                if (noticeText && !canEdit) {
                    noticeText.textContent = `System Prompt Editor requires "Prompt Engineer" or "Enterprise" license tier. Current tier: ${licenseTier}`;
                }
            }
            if (textarea) {
                textarea.disabled = !canEdit;
            }
            if (saveBtn) {
                saveBtn.disabled = !canEdit;
                saveBtn.classList.toggle('opacity-50', !canEdit);
                saveBtn.classList.toggle('cursor-not-allowed', !canEdit);
            }
            if (resetBtn) {
                resetBtn.disabled = !canEdit;
                resetBtn.classList.toggle('opacity-50', !canEdit);
                resetBtn.classList.toggle('cursor-not-allowed', !canEdit);
            }

            // Load the system prompt from the backend
            const overrideBadge = document.getElementById('system-prompt-override-badge');
            
            if (canEdit && token) {
                try {
                    const response = await fetch(`/api/v1/system-prompts/${promptName}`, {
                        headers: { 'Authorization': `Bearer ${token}` }
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        if (textarea) {
                            textarea.value = data.content || '';
                            // Store original content for change detection
                            textarea.dataset.originalContent = data.content || '';
                            this.updateCharCount();
                            this.updateSaveButtonState(); // Initial state check
                        }
                        // Show/hide override badge
                        // Override badge should only show if:
                        // 1. There is an override (data.is_override)
                        // 2. AND we're viewing a version > 1 (v1 is the base prompt, not an override)
                        if (overrideBadge) {
                            const isViewingOverride = data.is_override && data.metadata?.version > 1;
                            overrideBadge.classList.toggle('hidden', !isViewingOverride);
                        }
                        
                        // Show current version number
                        const versionBadge = document.getElementById('system-prompt-version-badge');
                        const versionNumber = document.getElementById('current-version-number');
                        const activeBadge = document.getElementById('system-prompt-active-badge');
                        console.log('[AdminManager] Full prompt data:', data);
                        console.log('[AdminManager] is_version_active:', data.is_version_active);
                        if (versionBadge && versionNumber && data.metadata?.version) {
                            versionNumber.textContent = `v${data.metadata.version}`;
                            versionBadge.classList.remove('hidden');
                            
                            // Store currently loaded version for button state management
                            this.currentLoadedVersion = data.metadata.version;
                            
                            // Show active badge if this version is pinned as active
                            if (activeBadge) {
                                if (data.is_version_active) {
                                    console.log('[AdminManager] Showing active badge');
                                    activeBadge.classList.remove('hidden');
                                } else {
                                    console.log('[AdminManager] Hiding active badge');
                                    activeBadge.classList.add('hidden');
                                }
                            }
                        } else if (versionBadge) {
                            versionBadge.classList.add('hidden');
                            if (activeBadge) {
                                activeBadge.classList.add('hidden');
                            }
                        }
                        
                        // Check if this is a system default prompt (cannot be deleted)
                        // System prompts have created_by as null, undefined, 'SYSTEM', 'system', or empty string
                        const createdBy = data.metadata?.created_by;
                        const isSystemPrompt = !createdBy || createdBy === 'SYSTEM' || createdBy === 'system';
                        
                        // Disable delete button for system prompts or when no edit permission
                        if (deleteBtn) {
                            deleteBtn.disabled = isSystemPrompt || !canEdit;
                            deleteBtn.classList.toggle('opacity-50', isSystemPrompt || !canEdit);
                            deleteBtn.classList.toggle('cursor-not-allowed', isSystemPrompt || !canEdit);
                            deleteBtn.title = !canEdit 
                                ? 'Requires Prompt Engineer or Enterprise license'
                                : isSystemPrompt 
                                    ? 'System default prompts cannot be deleted' 
                                    : 'Delete this custom prompt';
                        }
                        
                        // Auto-reload parameters if section is expanded
                        const parametersContent = document.getElementById('section-parameters-content');
                        if (parametersContent && !parametersContent.classList.contains('hidden')) {
                            this.loadPromptParameters(promptName);
                        }
                    } else {
                        throw new Error('Failed to load system prompt');
                    }
                } catch (error) {
                    console.error('[AdminManager] Error loading system prompt:', error);
                    // Disable delete button on error
                    if (deleteBtn) {
                        deleteBtn.disabled = true;
                        deleteBtn.classList.add('opacity-50', 'cursor-not-allowed');
                        deleteBtn.title = 'Failed to load prompt metadata';
                    }
                    if (window.showNotification) {
                        window.showNotification('error', `Failed to load system prompt: ${error.message}`);
                    }
                }
            } else {
                // No edit permission - disable delete button
                if (deleteBtn) {
                    deleteBtn.disabled = true;
                    deleteBtn.classList.add('opacity-50', 'cursor-not-allowed');
                    deleteBtn.title = 'Requires Prompt Engineer or Enterprise license';
                }
                if (textarea) {
                    textarea.value = '';
                    textarea.dataset.originalContent = '';
                    this.updateCharCount();
                    this.updateSaveButtonState();
                }
                if (overrideBadge) {
                    overrideBadge.classList.add('hidden');
                }
            }

        } catch (error) {
            console.error('[AdminManager] Error loading system prompt:', error);
            if (window.showNotification) {
                window.showNotification('error', 'Failed to load system prompt');
            }
        }
    },

    /**
     * Save system prompt for current prompt name
     */
    async saveSystemPrompt() {
        try {
            const promptName = document.getElementById('system-prompts-tier-selector').value;
            const textarea = document.getElementById('system-prompt-editor-textarea');
            const content = textarea ? textarea.value : '';

            // Check license tier access
            const token = authClient ? authClient.getToken() : null;
            if (!token) {
                if (window.showNotification) {
                    window.showNotification('error', 'Authentication required');
                }
                return;
            }

            const response = await fetch('/api/v1/auth/me', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            
            if (!response.ok) {
                if (window.showNotification) {
                    window.showNotification('error', 'Failed to verify license tier');
                }
                return;
            }

            const userData = await response.json();
            const licenseTier = userData.user?.license_tier || 'Unknown';
            
            if (licenseTier !== 'Prompt Engineer' && licenseTier !== 'Enterprise') {
                if (window.showNotification) {
                    window.showNotification('error', `System Prompt Editor requires "Prompt Engineer" or "Enterprise" license tier. Current tier: ${licenseTier}`);
                }
                return;
            }

            // Save the system prompt via backend API
            const saveResponse = await fetch(`/api/v1/system-prompts/${promptName}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ content })
            });

            if (saveResponse.ok) {
                // Show override badge after saving
                const overrideBadge = document.getElementById('system-prompt-override-badge');
                if (overrideBadge) {
                    overrideBadge.classList.remove('hidden');
                }
                
                // Update original content after successful save
                if (textarea) {
                    textarea.dataset.originalContent = content;
                    this.updateSaveButtonState(); // Disable save button after save
                }
                
                // Get the newly created version number from save response
                const saveData = await saveResponse.json();
                const newVersion = saveData.version || saveData.metadata?.version;
                
                // Auto-activate the newly saved version
                if (newVersion) {
                    try {
                        const activateResponse = await fetch(`/api/v1/system-prompts/${promptName}/versions/${newVersion}/activate`, {
                            method: 'POST',
                            headers: { 
                                'Authorization': `Bearer ${token}`,
                                'Content-Type': 'application/json'
                            }
                        });
                        if (activateResponse.ok) {
                            console.log(`[AdminManager] Auto-activated version ${newVersion}`);
                        }
                    } catch (error) {
                        console.error('[AdminManager] Failed to auto-activate version:', error);
                    }
                }
                
                // Reload prompt metadata to get updated version (AFTER activation)
                const metadataResponse = await fetch(`/api/v1/system-prompts/${promptName}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (metadataResponse.ok) {
                    const data = await metadataResponse.json();
                    const currentVersion = data.metadata?.version;
                    const versionBadge = document.getElementById('system-prompt-version-badge');
                    const versionNumber = document.getElementById('current-version-number');
                    const activeBadge = document.getElementById('system-prompt-active-badge');
                    if (versionBadge && versionNumber && currentVersion) {
                        versionNumber.textContent = `v${currentVersion}`;
                        versionBadge.classList.remove('hidden');
                        
                        // Update the currently loaded version tracker
                        this.currentLoadedVersion = currentVersion;
                        
                        // Show active badge (GET endpoint always returns active version)
                        if (activeBadge && data.is_version_active) {
                            activeBadge.classList.remove('hidden');
                        }
                    }
                }
                
                // Auto-refresh version history if it's expanded
                const versionsContent = document.getElementById('versions-content');
                if (versionsContent && !versionsContent.classList.contains('hidden')) {
                    await this.loadPromptVersions(promptName);
                }
                
                if (window.showNotification) {
                    window.showNotification('success', `System prompt "${promptName}" saved successfully`);
                }
            } else {
                const errorData = await saveResponse.json().catch(() => ({}));
                throw new Error(errorData.message || 'Failed to save system prompt');
            }

        } catch (error) {
            console.error('[AdminManager] Error saving system prompt:', error);
            if (window.showNotification) {
                window.showNotification('error', `Failed to save system prompt: ${error.message}`);
            }
        }
    },

    /**
     * Reset system prompt to default for current prompt name
     */
    async resetSystemPromptToDefault() {
        const promptName = document.getElementById('system-prompts-tier-selector').value;
        const promptLabel = document.getElementById('system-prompts-tier-selector').selectedOptions[0]?.text || promptName;
        
        if (!window.showConfirmation) {
            console.error('Confirmation system not available');
            return;
        }
        
        window.showConfirmation(
            'Reset System Prompt',
            `Reset "${promptLabel}" to default?\n\nThis will remove any custom override and restore the encrypted default prompt.`,
            async () => {
                const token = authClient ? authClient.getToken() : null;
                if (!token) {
                    if (window.showNotification) {
                        window.showNotification('error', 'Authentication required');
                    }
                    return;
                }

                try {
                    const response = await fetch(`/api/v1/system-prompts/${promptName}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': `Bearer ${token}` }
                    });

                    if (response.ok) {
                        await this.loadSystemPromptForTier(promptName);
                        if (window.showNotification) {
                            window.showNotification('success', `System prompt "${promptLabel}" reset to default`);
                        }
                    } else {
                        throw new Error('Failed to reset system prompt');
                    }
                } catch (error) {
                    console.error('[AdminManager] Error resetting system prompt:', error);
                    if (window.showNotification) {
                        window.showNotification('error', `Failed to reset system prompt: ${error.message}`);
                    }
                }
            }
        );
    },

    /**
     * Update character count for system prompt
     */
    updateCharCount() {
        const textarea = document.getElementById('system-prompt-editor-textarea');
        const countElement = document.getElementById('system-prompt-char-count');
        
        if (textarea && countElement) {
            countElement.textContent = textarea.value.length.toLocaleString();
        }
    },

    /**
     * Update save button state based on whether content has changed
     */
    updateSaveButtonState() {
        const textarea = document.getElementById('system-prompt-editor-textarea');
        const saveBtn = document.getElementById('save-system-prompt-btn');
        
        if (!textarea || !saveBtn) return;
        
        const originalContent = textarea.dataset.originalContent || '';
        const currentContent = textarea.value || '';
        const hasChanged = originalContent !== currentContent;
        const isDisabled = textarea.disabled; // Respect license tier restrictions
        
        if (isDisabled) {
            // Keep disabled if license tier doesn't allow editing
            saveBtn.disabled = true;
            saveBtn.classList.add('opacity-50', 'cursor-not-allowed');
        } else if (hasChanged) {
            // Enable if content changed and has permission
            saveBtn.disabled = false;
            saveBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        } else {
            // Disable if no changes
            saveBtn.disabled = true;
            saveBtn.classList.add('opacity-50', 'cursor-not-allowed');
        }
    },

    // ========================================================================
    // PHASE 4: ENHANCED SYSTEM PROMPTS FEATURES
    // ========================================================================

    /**
     * Toggle collapsible sections (parameters, versions, diff)
     */
    toggleSection(sectionName) {
        const content = document.getElementById(`${sectionName}-content`);
        const button = document.getElementById(`toggle-${sectionName}-btn`);
        
        if (!content || !button) return;

        const isHidden = content.classList.contains('hidden');
        
        if (isHidden) {
            content.classList.remove('hidden');
            button.querySelector('.expand-text').textContent = 'Hide';
            
            // Load data when opening
            const promptName = document.getElementById('system-prompts-tier-selector').value;
            if (promptName) {
                if (sectionName === 'parameters') {
                    this.loadPromptParameters(promptName);
                } else if (sectionName === 'versions') {
                    this.loadPromptVersions(promptName);
                } else if (sectionName === 'diff') {
                    this.loadPromptDiff(promptName);
                }
            }
        } else {
            content.classList.add('hidden');
            button.querySelector('.expand-text').textContent = 'Show';
        }
    },

    /**
     * Load parameters for the selected prompt
     */
    async loadPromptParameters(promptName) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            return;
        }

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/parameters`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!response.ok) {
                throw new Error(`Failed to load parameters: ${response.statusText}`);
            }

            const data = await response.json();
            const tbody = document.getElementById('parameters-table-body');
            
            if (!tbody) return;

            // Clear existing rows
            tbody.innerHTML = '';

            const allParameters = [
                ...data.global_parameters.map(p => ({ ...p, scope: 'Global' })),
                ...data.prompt_parameters.map(p => ({ ...p, scope: 'Prompt' })),
                ...(data.undefined_parameters || []).map(p => ({ ...p, scope: 'Undefined' }))
            ];

            if (allParameters.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center py-4 text-gray-500">
                            No parameters referenced in this prompt
                        </td>
                    </tr>
                `;
                return;
            }

            // Render parameter rows
            allParameters.forEach(param => {
                const isUndefined = param.scope === 'Undefined';
                const isGlobal = param.scope === 'Global';
                const isPrompt = param.scope === 'Prompt';
                const isEditable = (isGlobal || isPrompt) && !isUndefined;
                const hasOverride = param.has_override || false;
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="py-2 px-3 ${isUndefined ? 'text-yellow-400' : 'text-gray-300'}">
                        ${isUndefined ? '⚠️ ' : ''}${param.display_name || param.parameter_name}
                    </td>
                    <td class="py-2 px-3 text-gray-400">${param.parameter_type}</td>
                    <td class="py-2 px-3">
                        ${isUndefined 
                            ? '<span class="text-xs text-yellow-400">Not defined</span>'
                            : `<code class="text-xs bg-gray-700 px-2 py-1 rounded text-gray-300">${param.default_value || 'N/A'}</code>`
                        }
                    </td>
                    <td class="py-2 px-3">
                        ${isEditable 
                            ? `<input type="text" 
                                      id="override-${param.parameter_name}" 
                                      value="${param.override_value || ''}"
                                      placeholder="Enter override..."
                                      class="w-full px-2 py-1 text-xs bg-gray-700 border ${hasOverride ? 'border-orange-500' : 'border-gray-600'} rounded text-gray-300 focus:outline-none focus:border-[#F15F22]">`
                            : '<span class="text-xs text-gray-500">—</span>'
                        }
                    </td>
                    <td class="py-2 px-3">
                        <span class="text-xs px-2 py-0.5 rounded ${
                            param.scope === 'Global' 
                                ? 'bg-blue-500/20 text-blue-300' 
                                : param.scope === 'Prompt'
                                ? 'bg-purple-500/20 text-purple-300'
                                : 'bg-yellow-500/20 text-yellow-300'
                        }">
                            ${param.scope}
                        </span>
                        ${hasOverride ? '<span class="ml-1 text-xs px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-300">✓</span>' : ''}
                    </td>
                    <td class="py-2 px-3">
                        ${isEditable 
                            ? `<div class="flex gap-1">
                                <button onclick="adminManager.saveParameterOverride('${promptName}', '${param.parameter_name}')" 
                                        class="px-2 py-1 text-xs bg-blue-600 hover:bg-blue-700 rounded text-white transition-colors">
                                    Save
                                </button>
                                ${hasOverride 
                                    ? `<button onclick="adminManager.deleteParameterOverride('${promptName}', '${param.parameter_name}')" 
                                              class="px-2 py-1 text-xs bg-red-600 hover:bg-red-700 rounded text-white transition-colors">
                                        Delete
                                      </button>`
                                    : ''
                                }
                               </div>`
                            : '<span class="text-xs text-gray-500">—</span>'
                        }
                    </td>
                `;
                tbody.appendChild(row);
            });

        } catch (error) {
            console.error('[AdminManager] Error loading parameters:', error);
            const tbody = document.getElementById('parameters-table-body');
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="4" class="text-center py-4 text-red-400">
                            Error loading parameters: ${error.message}
                        </td>
                    </tr>
                `;
            }
        }
    },

    /**
     * Load version history for the selected prompt
     */
    async loadPromptVersions(promptName) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            return;
        }

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/versions`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!response.ok) {
                throw new Error(`Failed to load versions: ${response.statusText}`);
            }

            const data = await response.json();
            const tbody = document.getElementById('versions-table-body');
            
            if (!tbody) return;

            // Clear existing rows
            tbody.innerHTML = '';

            if (!data.versions || data.versions.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="5" class="text-center py-4 text-gray-500">
                            No version history available
                        </td>
                    </tr>
                `;
                return;
            }
            
            console.log('[AdminManager] Active version ID from API:', data.active_version_id);
            console.log('[AdminManager] All versions:', data.versions);

            // Render version rows
            data.versions.forEach((version, index) => {
                const row = document.createElement('tr');
                row.classList.add('hover:bg-gray-700/50', 'transition-colors');
                
                // Check if this version is the active one
                const isActive = version.is_active === true || version.is_active === 1;
                const activeBadge = isActive ? '<span class="ml-2 px-2 py-0.5 text-xs bg-green-600 text-white rounded">Active</span>' : '';
                
                // Check if this version is currently loaded in the editor
                const isCurrentlyLoaded = this.currentLoadedVersion === version.version;
                
                console.log(`[AdminManager] Version ${version.version}: is_active=${version.is_active}, isActive=${isActive}, isCurrentlyLoaded=${isCurrentlyLoaded}`);
                
                row.innerHTML = `
                    <td class="py-2 px-3">
                        <span class="flex items-center gap-2">
                            <span class="text-gray-300">v${version.version}${activeBadge}</span>
                        </span>
                    </td>
                    <td class="py-2 px-3 text-gray-400">${new Date(version.created_at).toLocaleString()}</td>
                    <td class="py-2 px-3 text-gray-400">${version.author_display || version.changed_by || 'System'}</td>
                    <td class="py-2 px-3 text-gray-300">${version.change_reason || 'Initial version'}</td>
                    <td class="py-2 px-3">
                        <div class="flex gap-2">
                            <button class="px-3 py-1 text-xs ${isCurrentlyLoaded ? 'bg-gray-600 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'} text-white rounded transition-colors"
                                    data-action="load" data-version="${version.version}" ${isCurrentlyLoaded ? 'disabled' : ''}>
                                ${isCurrentlyLoaded ? 'Loaded' : 'Load'}
                            </button>
                            <button class="px-3 py-1 text-xs ${isActive ? 'bg-gray-600 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700'} text-white rounded transition-colors"
                                    data-action="activate" data-version="${version.version}" ${isActive ? 'disabled' : ''}>
                                ${isActive ? 'Active' : 'Activate'}
                            </button>
                        </div>
                    </td>
                `;
                
                // Add click handlers for buttons
                const loadBtn = row.querySelector('[data-action="load"]');
                const activateBtn = row.querySelector('[data-action="activate"]');
                
                if (loadBtn && !isCurrentlyLoaded) {
                    loadBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.loadVersionToEditor(promptName, version.version);
                    });
                }
                
                if (activateBtn && !isActive) {
                    activateBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.activateVersion(promptName, version.version);
                    });
                }
                
                tbody.appendChild(row);
            });

        } catch (error) {
            console.error('[AdminManager] Error loading versions:', error);
            const tbody = document.getElementById('versions-table-body');
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="5" class="text-center py-4 text-red-400">
                            Error loading versions: ${error.message}
                        </td>
                    </tr>
                `;
            }
        }
    },

    /**
     * Load a specific version into the editor for viewing/editing
     */
    async loadVersionToEditor(promptName, versionNumber) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            return;
        }

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/versions/${versionNumber}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!response.ok) {
                throw new Error(`Failed to load version ${versionNumber}`);
            }

            const data = await response.json();
            const textarea = document.getElementById('system-prompt-editor-textarea');
            
            if (textarea && data.content) {
                textarea.value = data.content;
                // Update original content to mark as unchanged initially
                textarea.dataset.originalContent = data.content;
                this.updateCharCount();
                this.updateSaveButtonState();
                
                // Update the currently loaded version tracker
                this.currentLoadedVersion = versionNumber;
                
                // Update version badge in header to show loaded version
                const versionNumber_el = document.getElementById('current-version-number');
                if (versionNumber_el) {
                    versionNumber_el.textContent = `v${versionNumber}`;
                }
                
                // Hide "Custom Override" badge if loading v1 (base prompt)
                const overrideBadge = document.getElementById('system-prompt-override-badge');
                if (overrideBadge) {
                    // v1 is the base prompt, not an override
                    overrideBadge.classList.toggle('hidden', versionNumber === 1);
                }
                
                // Update "Active" badge - need to check if this version is actually active
                // Fetch the current prompt info to get is_version_active status
                const currentPromptResponse = await fetch(`/api/v1/system-prompts/${promptName}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (currentPromptResponse.ok) {
                    const currentData = await currentPromptResponse.json();
                    const activeBadge = document.getElementById('system-prompt-active-badge');
                    if (activeBadge) {
                        // Show active badge only if loaded version matches current version AND is active
                        const isLoadedVersionActive = (currentData.metadata?.version === versionNumber && currentData.is_version_active);
                        activeBadge.classList.toggle('hidden', !isLoadedVersionActive);
                    }
                }
                
                // Refresh version history to update button states
                await this.loadPromptVersions(promptName);
                
                if (window.showNotification) {
                    window.showNotification('success', `Loaded version ${versionNumber} into editor`);
                }
            }
        } catch (error) {
            console.error('[AdminManager] Error loading version to editor:', error);
            if (window.showNotification) {
                window.showNotification('error', `Failed to load version: ${error.message}`);
            }
        }
    },

    /**
     * Activate a specific version (make it the current active version)
     */
    async activateVersion(promptName, versionNumber) {
        console.log(`[AdminManager] Activating version ${versionNumber} for ${promptName}`);
        
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            return;
        }

        // Confirm with user (wrap callback-based showConfirmation in a Promise)
        console.log('[AdminManager] Showing confirmation dialog...');
        const confirmed = await new Promise((resolve) => {
            if (window.showConfirmation) {
                window.showConfirmation(
                    `Activate Version ${versionNumber}`,
                    `This will make version ${versionNumber} the active version used by the application. Continue?`,
                    () => resolve(true)  // onConfirm callback
                );
                // Note: If user clicks Cancel, the modal closes but doesn't call anything
                // We need to handle cancel too
                const cancelBtn = document.getElementById('confirm-modal-cancel');
                if (cancelBtn) {
                    const cancelHandler = () => {
                        resolve(false);
                        cancelBtn.removeEventListener('click', cancelHandler);
                    };
                    cancelBtn.addEventListener('click', cancelHandler, { once: true });
                }
            } else {
                resolve(confirm(`Activate version ${versionNumber}?`));
            }
        });
        
        console.log('[AdminManager] Confirmation result:', confirmed);
        
        if (!confirmed) {
            console.log('[AdminManager] Activation cancelled by user');
            return;
        }

        try {
            console.log('[AdminManager] Making API call to activate version...');
            const response = await fetch(`/api/v1/system-prompts/${promptName}/versions/${versionNumber}/activate`, {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            console.log('[AdminManager] API response status:', response.status);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `Failed to activate version ${versionNumber}`);
            }

            const data = await response.json();
            console.log('[AdminManager] Activation successful:', data);
            
            // Reload the prompt content to show the newly activated version
            // This will load the activated version into the editor with all metadata/badges
            await this.loadSystemPromptForTier(promptName);
            
            // Refresh version history to update active badges and button states
            await this.loadPromptVersions(promptName);
            
            if (window.showNotification) {
                window.showNotification('success', `Version ${versionNumber} is now active (pinned)`);
            }
        } catch (error) {
            console.error('[AdminManager] Error activating version:', error);
            if (window.showNotification) {
                window.showNotification('error', `Failed to activate version: ${error.message}`);
            }
        }
    },

    /**
     * Load diff comparison for the selected prompt
     */
    async loadPromptDiff(promptName) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            return;
        }

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/diff`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!response.ok) {
                throw new Error(`Failed to load diff: ${response.statusText}`);
            }

            const data = await response.json();
            
            // Update base content
            const baseContent = document.getElementById('diff-base-content');
            if (baseContent) {
                baseContent.textContent = data.base_content || 'No base content';
            }

            // Update override content
            const overrideContent = document.getElementById('diff-override-content');
            if (overrideContent) {
                if (data.has_override) {
                    overrideContent.textContent = data.override_content;
                } else {
                    overrideContent.textContent = 'No override found';
                }
            }

            // Update statistics
            const baseLength = document.getElementById('diff-base-length');
            const overrideLength = document.getElementById('diff-override-length');
            const delta = document.getElementById('diff-delta');
            
            if (baseLength) baseLength.textContent = data.base_length.toLocaleString();
            if (overrideLength) overrideLength.textContent = data.override_length.toLocaleString();
            if (delta) {
                const diff = data.override_length - data.base_length;
                delta.textContent = `${diff >= 0 ? '+' : ''}${diff.toLocaleString()}`;
                delta.className = diff > 0 ? 'text-green-400' : (diff < 0 ? 'text-red-400' : '');
            }

        } catch (error) {
            console.error('[AdminManager] Error loading diff:', error);
            const baseContent = document.getElementById('diff-base-content');
            const overrideContent = document.getElementById('diff-override-content');
            
            if (baseContent) baseContent.textContent = 'Error loading base content';
            if (overrideContent) overrideContent.textContent = 'Error loading override content';
        }
    },

    /**
     * View a specific version of a prompt (preview in modal/dialog)
     */
    async viewPromptVersion(promptName, versionNumber, encryptedContent) {
        try {
            // Decrypt the version content by fetching from API
            const token = authClient ? authClient.getToken() : null;
            if (!token) {
                if (window.showNotification) {
                    window.showNotification('error', 'Authentication required');
                }
                return;
            }

            const response = await fetch(`/api/v1/system-prompts/${promptName}/versions/${versionNumber}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!response.ok) {
                throw new Error('Failed to load version content');
            }

            const data = await response.json();
            
            // Show version in a modal or update textarea temporarily
            if (window.showConfirmation) {
                const contentPreview = data.content.substring(0, 500) + (data.content.length > 500 ? '...' : '');
                window.showConfirmation(
                    `View Version ${versionNumber}`,
                    `Prompt: ${promptName}\nVersion: ${versionNumber}\nDate: ${data.created_at}\nAuthor: ${data.changed_by || 'System'}\n\nContent preview:\n${contentPreview}`,
                    () => {
                        // Optional: Load this version into the editor
                        const textarea = document.getElementById('system-prompt-editor-textarea');
                        if (textarea) {
                            textarea.value = data.content;
                            textarea.dataset.originalContent = textarea.value; // Update baseline
                            this.updateCharCount();
                            this.updateSaveButtonState();
                            if (window.showNotification) {
                                window.showNotification('info', `Loaded version ${versionNumber} into editor`);
                            }
                        }
                    },
                    'Load into Editor',
                    'Close'
                );
            } else {
                // Fallback: just load into editor
                const textarea = document.getElementById('system-prompt-editor-textarea');
                if (textarea && confirm(`Load version ${versionNumber} into the editor?`)) {
                    textarea.value = data.content;
                    textarea.dataset.originalContent = textarea.value;
                    this.updateCharCount();
                    this.updateSaveButtonState();
                    if (window.showNotification) {
                        window.showNotification('info', `Loaded version ${versionNumber} into editor`);
                    }
                }
            }

        } catch (error) {
            console.error('[AdminManager] Error viewing version:', error);
            if (window.showNotification) {
                window.showNotification('error', `Failed to load version: ${error.message}`);
            }
        }
    },

    /**
     * Save parameter override
     */
    async saveParameterOverride(promptName, parameterName) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            showNotification('Authentication required', 'error');
            return;
        }

        const inputField = document.getElementById(`override-${parameterName}`);
        if (!inputField) {
            console.error('[AdminManager] Input field not found');
            return;
        }

        const overrideValue = inputField.value.trim();
        if (!overrideValue) {
            showNotification('Please enter an override value', 'error');
            return;
        }

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/parameters/${parameterName}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ override_value: overrideValue })
            });

            if (!response.ok) {
                throw new Error(`Failed to save override: ${response.statusText}`);
            }

            const data = await response.json();
            showNotification(`Parameter override saved for '${parameterName}'`, 'success');
            
            // Reload parameters to show updated state
            this.loadPromptParameters(promptName);

        } catch (error) {
            console.error('[AdminManager] Error saving parameter override:', error);
            showNotification(`Error saving override: ${error.message}`, 'error');
        }
    },

    /**
     * Delete parameter override
     */
    async deleteParameterOverride(promptName, parameterName) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            showNotification('Authentication required', 'error');
            return;
        }

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/parameters/${parameterName}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error(`Failed to delete override: ${response.statusText}`);
            }

            const data = await response.json();
            showNotification(`Override deleted for '${parameterName}'`, 'success');
            
            // Reload parameters to show updated state
            this.loadPromptParameters(promptName);

        } catch (error) {
            console.error('[AdminManager] Error deleting parameter override:', error);
            window.showAppBanner(`Error deleting override: ${error.message}`, 'error', 5000);
        }
    },

    /**
     * Show prompt input modal and return user input
     * @param {string} title - Modal title
     * @param {string} label - Input label
     * @param {string} defaultValue - Default input value
     * @returns {Promise<string|null>} - User input or null if cancelled
     */
    showPromptInputModal(title, label, defaultValue = '') {
        return new Promise((resolve) => {
            const overlay = document.getElementById('prompt-input-modal-overlay');
            const titleEl = document.getElementById('prompt-input-modal-title');
            const labelEl = document.getElementById('prompt-input-modal-label');
            const input = document.getElementById('prompt-input-modal-input');
            const form = document.getElementById('prompt-input-modal-form');
            const closeBtn = document.getElementById('prompt-input-modal-close');
            const cancelBtn = document.getElementById('prompt-input-modal-cancel');

            if (!overlay || !titleEl || !labelEl || !input || !form) {
                console.error('[AdminManager] Prompt input modal elements not found');
                resolve(null);
                return;
            }

            // Set modal content
            titleEl.textContent = title;
            labelEl.textContent = label;
            input.value = defaultValue;

            // Show modal
            overlay.classList.remove('hidden');
            setTimeout(() => input.focus(), 100);

            // Remove any existing listeners first (in case modal was opened before)
            const oldSubmit = form._submitHandler;
            const oldCancel = form._cancelHandler;
            if (oldSubmit) form.removeEventListener('submit', oldSubmit);
            if (oldCancel) {
                closeBtn.removeEventListener('click', oldCancel);
                cancelBtn.removeEventListener('click', oldCancel);
            }

            // Handle form submit
            const handleSubmit = (e) => {
                e.preventDefault();
                e.stopPropagation();
                const value = input.value.trim();
                cleanup();
                resolve(value || null);
            };

            // Handle cancel/close
            const handleCancel = (e) => {
                if (e) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                cleanup();
                resolve(null);
            };

            // Cleanup function
            const cleanup = () => {
                overlay.classList.add('hidden');
                form.removeEventListener('submit', handleSubmit);
                closeBtn.removeEventListener('click', handleCancel);
                cancelBtn.removeEventListener('click', handleCancel);
                delete form._submitHandler;
                delete form._cancelHandler;
                input.value = '';
            };

            // Store handlers for cleanup on next open
            form._submitHandler = handleSubmit;
            form._cancelHandler = handleCancel;

            // Attach event listeners
            form.addEventListener('submit', handleSubmit);
            closeBtn.addEventListener('click', handleCancel);
            cancelBtn.addEventListener('click', handleCancel);
        });
    },

    /**
     * Duplicate the selected prompt
     */
    async duplicatePrompt() {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            window.showAppBanner('Authentication required', 'error', 5000);
            return;
        }

        const promptName = document.getElementById('system-prompts-tier-selector').value;
        if (!promptName) {
            window.showAppBanner('Please select a prompt to duplicate', 'error', 5000);
            return;
        }

        try {
            // Get current display name for default
            const currentDisplayName = promptName.replace(/_/g, ' ');
            
            // Ask user for new display name
            const newDisplayName = await this.showPromptInputModal(
                'Enter a name for the duplicated prompt',
                'Prompt Name',
                `${currentDisplayName} Copy`
            );
            
            if (!newDisplayName || !newDisplayName.trim()) {
                return; // User cancelled
            }

            // Auto-generate internal name from display name
            const newName = newDisplayName.trim().toUpperCase().replace(/\s+/g, '_');

            const response = await fetch(`/api/v1/system-prompts/${promptName}/duplicate`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    new_name: newName,
                    new_display_name: newDisplayName.trim(),
                    copy_parameters: true
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Failed to duplicate prompt');
            }

            const data = await response.json();
            window.showAppBanner(`Prompt duplicated successfully: ${newDisplayName}`, 'success', 5000);
            
            // Reload prompt list to include new prompt
            await this.loadAllPrompts();
            
            // Select the new prompt
            document.getElementById('system-prompts-tier-selector').value = newName;
            await this.loadSystemPromptForTier(newName);

        } catch (error) {
            console.error('[AdminManager] Error duplicating prompt:', error);
            window.showAppBanner(error.message || 'Failed to duplicate prompt', 'error', 5000);
        }
    },

    /**
     * Delete the selected prompt
     */
    async deletePrompt() {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            console.error('[AdminManager] No auth token found');
            window.showAppBanner('Authentication required', 'error', 5000);
            return;
        }

        const promptName = document.getElementById('system-prompts-tier-selector').value;
        if (!promptName) {
            window.showAppBanner('Please select a prompt to delete', 'error', 5000);
            return;
        }

        console.log('[AdminManager] Deleting prompt:', promptName);

        try {
            console.log('[AdminManager] About to send DELETE request to:', `/api/v1/system-prompts/${promptName}/delete`);
            const response = await fetch(`/api/v1/system-prompts/${promptName}/delete`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            console.log('[AdminManager] DELETE response received:', response.status, response.statusText);

            if (!response.ok) {
                const error = await response.json();
                console.log('[AdminManager] DELETE failed with error:', error);
                throw new Error(error.message || 'Failed to delete prompt');
            }

            const data = await response.json();
            console.log('[AdminManager] DELETE successful:', data);
            window.showAppBanner(`Prompt deleted successfully: ${promptName}`, 'success', 5000);
            
            // Reload prompt list and load the first prompt to update button states
            await this.loadAllPrompts();
            
            // Explicitly load the now-selected prompt to ensure button states are updated
            const selector = document.getElementById('system-prompts-tier-selector');
            if (selector && selector.value) {
                await this.loadSystemPromptForTier(selector.value);
            }

        } catch (error) {
            console.error('[AdminManager] Error deleting prompt:', error);
            window.showAppBanner(error.message || 'Failed to delete prompt', 'error', 5000);
        }
    },

    /**
     * Load all prompts from the database
     */
    async loadAllPrompts() {
        const token = authClient ? authClient.getToken() : null;
        if (!token) return;

        try {
            // Add cache buster to ensure fresh data
            const response = await fetch(`/api/v1/system-prompts/list?_=${Date.now()}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error('Failed to load prompts');
            }

            const data = await response.json();
            const selector = document.getElementById('system-prompts-tier-selector');
            
            if (!selector) return;

            // Clear current options
            selector.innerHTML = '';

            // Group prompts by category
            const groups = {};
            const categoryOrder = {}; // Track original order from database
            data.prompts.forEach(prompt => {
                const category = prompt.category || 'Other';
                if (!groups[category]) {
                    groups[category] = [];
                    categoryOrder[category] = prompt.category_id || 999;
                }
                groups[category].push(prompt);
            });

            // Add optgroups in database order (not alphabetical)
            Object.keys(groups).sort((a, b) => categoryOrder[a] - categoryOrder[b]).forEach(category => {
                const optgroup = document.createElement('optgroup');
                optgroup.label = category;
                
                groups[category].forEach(prompt => {
                    const option = document.createElement('option');
                    option.value = prompt.name;
                    option.textContent = prompt.display_name || prompt.name;
                    if (!prompt.is_active) {
                        option.textContent += ' (Inactive)';
                        option.style.color = '#999';
                    }
                    optgroup.appendChild(option);
                });
                
                selector.appendChild(optgroup);
            });

            // Select the first prompt by default if none is selected
            if (selector.options.length > 0 && !selector.value) {
                selector.selectedIndex = 0;
                // Trigger change event to load the first prompt
                selector.dispatchEvent(new Event('change'));
            }

        } catch (error) {
            console.error('[AdminManager] Error loading prompts:', error);
        }
    },

    /**
     * Load version history for current prompt
     */
    async loadVersionHistory(promptName) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) return;

        if (!promptName) {
            promptName = document.getElementById('system-prompts-tier-selector').value;
        }

        if (!promptName) {
            console.log('[AdminManager] No prompt selected for version history');
            return;
        }

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/versions`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error('Failed to load version history');
            }

            const data = await response.json();
            const tbody = document.getElementById('versions-table-body');
            
            if (!tbody) return;

            if (data.versions && data.versions.length > 0) {
                tbody.innerHTML = data.versions.map(v => `
                    <tr class="hover:bg-gray-700/50 cursor-pointer" onclick="adminManager.viewVersionContent('${promptName}', ${v.version})">
                        <td class="py-2 px-3 text-white">v${v.version}</td>
                        <td class="py-2 px-3 text-gray-400">${new Date(v.created_at).toLocaleString()}</td>
                        <td class="py-2 px-3 text-gray-400">${v.changed_by || 'System'}</td>
                        <td class="py-2 px-3 text-gray-400 text-sm">${v.change_reason || 'N/A'}</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="4" class="text-center py-4 text-gray-500">
                            No version history available
                        </td>
                    </tr>
                `;
            }

        } catch (error) {
            console.error('[AdminManager] Error loading version history:', error);
            showNotification(`Error loading version history: ${error.message}`, 'error');
        }
    },

    /**
     * View content of a specific version
     */
    async viewVersionContent(promptName, version) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) return;

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/versions/${version}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error('Failed to load version content');
            }

            const data = await response.json();
            
            // Show in a modal or replace current content
            if (confirm(`View version ${version} content in editor?\n\nNote: This will replace the current editor content.`)) {
                const textarea = document.getElementById('system-prompt-editor-textarea');
                if (textarea) {
                    textarea.value = data.content;
                    this.updateCharCount();
                    showNotification(`Loaded version ${version} (read-only)`, 'info');
                }
            }

        } catch (error) {
            console.error('[AdminManager] Error loading version content:', error);
            showNotification(`Error loading version: ${error.message}`, 'error');
        }
    },

    /**
     * Show diff between two versions
     */
    async showDiff(promptName, version1, version2) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) return;

        if (!promptName) {
            promptName = document.getElementById('system-prompts-tier-selector').value;
        }

        if (!promptName) {
            showNotification('Please select a prompt first', 'error');
            return;
        }

        // Default: compare current with previous version
        if (!version1) version1 = 'current';
        if (!version2) version2 = 1;

        try {
            const response = await fetch(`/api/v1/system-prompts/${promptName}/diff`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    version1: version1,
                    version2: version2
                })
            });

            if (!response.ok) {
                throw new Error('Failed to generate diff');
            }

            const data = await response.json();
            
            // Display diff in the diff-content div
            const diffContent = document.getElementById('diff-content');
            if (diffContent && data.diff_html) {
                diffContent.innerHTML = data.diff_html;
                
                // Auto-expand the diff section if it's collapsed
                if (diffContent.classList.contains('hidden')) {
                    document.getElementById('toggle-diff-btn').click();
                }
            }

            if (!data.has_changes) {
                window.showAppBanner('No differences found between versions', 'info', 5000);
            }

        } catch (error) {
            console.error('[AdminManager] Error generating diff:', error);
            window.showAppBanner(`Error generating diff: ${error.message}`, 'error', 5000);
        }
    },

    /**
     * Perform bulk operations on prompts
     */
    async bulkUpdatePrompts(operations) {
        const token = authClient ? authClient.getToken() : null;
        if (!token) {
            window.showAppBanner('Authentication required', 'error', 5000);
            return;
        }

        try {
            const response = await fetch('/api/v1/system-prompts/bulk/update', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ operations })
            });

            if (!response.ok) {
                throw new Error('Bulk update failed');
            }

            const data = await response.json();
            
            // Show results
            const successCount = data.results.filter(r => r.status === 'success').length;
            const errorCount = data.results.filter(r => r.status === 'error').length;
            
            if (errorCount > 0) {
                const errors = data.results.filter(r => r.status === 'error');
                console.error('[AdminManager] Bulk operation errors:', errors);
                window.showAppBanner(`Completed ${successCount} operations, ${errorCount} errors`, 'warning', 5000);
            } else {
                window.showAppBanner(`Successfully completed ${successCount} operations`, 'success', 5000);
            }

            // Reload prompts
            await this.loadAllPrompts();

        } catch (error) {
            console.error('[AdminManager] Error in bulk update:', error);
            window.showAppBanner(`Bulk update failed: ${error.message}`, 'error', 5000);
        }
    },

    /**
     * Load rate limiting settings from server
     */
    async loadRateLimitSettings() {
        const token = localStorage.getItem('tda_auth_token');
        if (!token) return;

        try {
            const response = await fetch('/api/v1/auth/admin/rate-limit-settings', {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!response.ok) {
                throw new Error('Failed to load rate limit settings');
            }

            const data = await response.json();
            const settings = data.settings || {};

            // Update checkboxes
            const enabled = settings.rate_limit_enabled?.value === 'true';
            const checkbox = document.getElementById('rate-limit-enabled');
            if (checkbox) {
                checkbox.checked = enabled;
                this.toggleGlobalOverrideAvailability(enabled);
            }
            
            const globalOverride = settings.rate_limit_global_override?.value === 'true';
            const overrideCheckbox = document.getElementById('rate-limit-global-override');
            if (overrideCheckbox) {
                overrideCheckbox.checked = globalOverride;
                this.toggleRateLimitSettings(globalOverride);
            }

            // Update input fields
            if (settings.rate_limit_user_prompts_per_hour) {
                const input = document.getElementById('rate-limit-user-prompts-per-hour');
                if (input) input.value = settings.rate_limit_user_prompts_per_hour.value;
            }
            if (settings.rate_limit_user_prompts_per_day) {
                const input = document.getElementById('rate-limit-user-prompts-per-day');
                if (input) input.value = settings.rate_limit_user_prompts_per_day.value;
            }
            if (settings.rate_limit_user_configs_per_hour) {
                const input = document.getElementById('rate-limit-user-configs-per-hour');
                if (input) input.value = settings.rate_limit_user_configs_per_hour.value;
            }
            if (settings.rate_limit_ip_login_per_minute) {
                const input = document.getElementById('rate-limit-ip-login-per-minute');
                if (input) input.value = settings.rate_limit_ip_login_per_minute.value;
            }
            if (settings.rate_limit_ip_register_per_hour) {
                const input = document.getElementById('rate-limit-ip-register-per-hour');
                if (input) input.value = settings.rate_limit_ip_register_per_hour.value;
            }
            if (settings.rate_limit_ip_api_per_minute) {
                const input = document.getElementById('rate-limit-ip-api-per-minute');
                if (input) input.value = settings.rate_limit_ip_api_per_minute.value;
            }

        } catch (error) {
            console.error('[AdminManager] Error loading rate limit settings:', error);
            window.showAppBanner('Failed to load rate limit settings', 'error', 5000);
        }
    },

    /**
     * Toggle rate limit settings visibility
     */
    toggleGlobalOverrideAvailability(rateLimitEnabled) {
        const globalOverrideCheckbox = document.getElementById('rate-limit-global-override');
        
        // Enable/disable Global Override checkbox based on rate limiting state
        if (globalOverrideCheckbox) {
            globalOverrideCheckbox.disabled = !rateLimitEnabled;
            if (!rateLimitEnabled) {
                globalOverrideCheckbox.checked = false;
                // Also hide settings when rate limiting is disabled
                this.toggleRateLimitSettings(false);
            }
        }
    },

    toggleRateLimitSettings(globalOverrideEnabled) {
        const settingsDiv = document.getElementById('rate-limit-settings');
        
        if (settingsDiv) {
            if (globalOverrideEnabled) {
                settingsDiv.classList.remove('hidden');
            } else {
                settingsDiv.classList.add('hidden');
            }
        }
    },

    /**
     * Save rate limiting settings
     */
    async saveRateLimitSettings() {
        const token = localStorage.getItem('tda_auth_token');
        if (!token) {
            window.showAppBanner('Authentication required', 'error', 5000);
            return;
        }

        try {
            // Collect settings
            const settings = {
                rate_limit_enabled: document.getElementById('rate-limit-enabled')?.checked ? 'true' : 'false',
                rate_limit_global_override: document.getElementById('rate-limit-global-override')?.checked ? 'true' : 'false',
                rate_limit_user_prompts_per_hour: document.getElementById('rate-limit-user-prompts-per-hour')?.value || '100',
                rate_limit_user_prompts_per_day: document.getElementById('rate-limit-user-prompts-per-day')?.value || '1000',
                rate_limit_user_configs_per_hour: document.getElementById('rate-limit-user-configs-per-hour')?.value || '10',
                rate_limit_ip_login_per_minute: document.getElementById('rate-limit-ip-login-per-minute')?.value || '5',
                rate_limit_ip_register_per_hour: document.getElementById('rate-limit-ip-register-per-hour')?.value || '3',
                rate_limit_ip_api_per_minute: document.getElementById('rate-limit-ip-api-per-minute')?.value || '60'
            };

            const response = await fetch('/api/v1/auth/admin/rate-limit-settings', {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(settings)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Failed to save rate limit settings');
            }

            const data = await response.json();
            window.showAppBanner('Rate limit settings saved successfully', 'success', 5000);
            console.log('[AdminManager] Rate limit settings saved:', data);

        } catch (error) {
            console.error('[AdminManager] Error saving rate limit settings:', error);
            window.showAppBanner(`Failed to save rate limit settings: ${error.message}`, 'error', 5000);
        }
    }
};

// Expose AdminManager globally for inline onclick handlers
window.adminManager = AdminManager;
window.AdminManager = AdminManager;

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => AdminManager.init());
} else {
    AdminManager.init();
}
