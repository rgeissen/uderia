// static/js/handlers/configurationHandler.js
// Manages the new modular configuration system with MCP servers, LLM providers, and localStorage

import { handleViewSwitch, updateGenieMasterBadges, sortSessionsHierarchically } from '../ui.js';
import { handleStartNewSession, handleLoadSession } from './sessionManagement.js?v=3.2';
import { handleLoadResources } from '../eventHandlers.js?v=3.2';
import * as API from '../api.js';
import * as UI from '../ui.js';
import * as DOM from '../domElements.js';
import * as Utils from '../utils.js';
import { state } from '../state.js';
import { safeSetItem, safeGetItem } from '../storageUtils.js';
import { showAppBanner } from '../bannerSystem.js';
import { markSaving } from '../configDirtyState.js';

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Shows a toast notification in the header status area
 * @deprecated Use showAppBanner from bannerSystem.js instead
 * @param {string} type - 'success', 'error', 'warning', 'info'
 * @param {string} message - The message to display
 */
function showNotification(type, message) {
    // Redirect to the centralized banner system
    showAppBanner(message, type);
}

// Make showNotification globally available for backward compatibility
window.showNotification = showNotification;

function showDeleteConfirmation(message, onConfirm) {
    const banner = document.getElementById('delete-confirmation-banner');
    const messageEl = document.getElementById('delete-confirmation-message');
    const cancelBtn = document.getElementById('delete-confirmation-cancel');
    const okBtn = document.getElementById('delete-confirmation-ok');
    
    if (!banner || !messageEl || !cancelBtn || !okBtn) {
        console.error('Delete confirmation banner elements not found');
        return;
    }
    
    // Set the message
    messageEl.textContent = message;
    
    // Show the banner
    banner.classList.remove('hidden');
    
    // Remove any existing event listeners by cloning
    const newCancelBtn = cancelBtn.cloneNode(true);
    const newOkBtn = okBtn.cloneNode(true);
    cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
    okBtn.parentNode.replaceChild(newOkBtn, okBtn);
    
    // Hide banner function
    const hideBanner = () => {
        banner.classList.add('hidden');
    };
    
    // Cancel button
    newCancelBtn.addEventListener('click', hideBanner);
    
    // OK button
    newOkBtn.addEventListener('click', async () => {
        hideBanner();
        if (onConfirm) {
            await onConfirm();
        }
    });
}

/**
 * Generate a client-side ID for LLM configurations and profiles.
 * NOTE: MCP servers now use server-side UUID generation.
 */
function generateId() {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// loadCredentialsFromLocalStorage removed - credentials now only stored in encrypted database

// ============================================================================
// STORAGE KEYS
// ============================================================================
const STORAGE_KEYS = {
    MCP_SERVERS: 'tda_mcp_servers',
    LLM_PROVIDERS: 'tda_llm_providers',
    ACTIVE_MCP: 'tda_active_mcp',
    ACTIVE_LLM: 'tda_active_llm',
};

// ============================================================================
// LLM PROVIDER TEMPLATES
// ============================================================================
const LLM_PROVIDER_TEMPLATES = {
    Google: {
        name: 'Google',
        fields: [
            { id: 'apiKey', label: 'API Key', type: 'password', placeholder: 'Enter your Google API Key', required: true }
        ]
    },
    Anthropic: {
        name: 'Anthropic',
        fields: [
            { id: 'apiKey', label: 'API Key', type: 'password', placeholder: 'Enter your Anthropic API Key', required: true }
        ]
    },
    OpenAI: {
        name: 'OpenAI',
        fields: [
            { id: 'apiKey', label: 'API Key', type: 'password', placeholder: 'Enter your OpenAI API Key', required: true }
        ]
    },
    Azure: {
        name: 'Microsoft Azure',
        fields: [
            { id: 'azure_api_key', label: 'Azure API Key', type: 'password', placeholder: 'Enter your Azure API Key', required: true },
            { id: 'azure_endpoint', label: 'Azure Endpoint', type: 'text', placeholder: 'e.g., https://your-resource.openai.azure.com/', required: true },
            { id: 'azure_deployment_name', label: 'Deployment Name', type: 'text', placeholder: 'Your model deployment name', required: true },
            { id: 'azure_api_version', label: 'API Version', type: 'text', placeholder: 'e.g., 2024-02-01', required: true }
        ]
    },
    Friendli: {
        name: 'Friendli.ai',
        fields: [
            { id: 'friendli_token', label: 'Personal Access Token', type: 'password', placeholder: 'Enter your Friendli PAT', required: true },
            { id: 'friendli_endpoint_url', label: 'Dedicated Endpoint URL (Optional)', type: 'text', placeholder: 'e.g., https://your-endpoint.friendli.ai', required: false }
        ]
    },
    Amazon: {
        name: 'Amazon',
        fields: [
            { id: 'aws_access_key_id', label: 'AWS Access Key ID', type: 'password', placeholder: 'Enter your AWS Access Key ID', required: true },
            { id: 'aws_secret_access_key', label: 'AWS Secret Access Key', type: 'password', placeholder: 'Enter your AWS Secret Access Key', required: true },
            { id: 'aws_region', label: 'AWS Region', type: 'text', placeholder: 'e.g., us-east-1', required: true }
        ],
        extra: {
            listingMethod: [
                { id: 'foundation_models', label: 'Foundation Models', value: 'foundation_models', default: true },
                { id: 'inference_profiles', label: 'Inference Profiles', value: 'inference_profiles', default: false }
            ]
        }
    },
    Ollama: {
        name: 'Ollama (Local)',
        fields: [
            { id: 'ollama_host', label: 'Ollama Host', type: 'text', placeholder: 'e.g., http://localhost:11434', required: true }
        ]
    }
};

// ============================================================================
// MCP CLASSIFICATION SETTING
// ============================================================================

/**
 * Load the MCP classification setting from the backend
 */
async function loadClassificationSetting() {
    try {
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
        console.error('Failed to load classification setting:', error);
    }
}

/**
 * Save the MCP classification setting to the backend
 */
async function saveClassificationSetting(enabled) {
    try {
        const response = await fetch('/api/v1/config/classification', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enable_mcp_classification: enabled })
        });
        
        if (response.ok) {
            const result = await response.json();
            showNotification('success', result.message);
        } else {
            const error = await response.json();
            showNotification('error', error.message || 'Failed to save classification setting');
        }
    } catch (error) {
        console.error('Failed to save classification setting:', error);
        showNotification('error', 'Failed to save classification setting');
    }
}

// ============================================================================
// STATE MANAGEMENT
// ============================================================================
class ConfigurationState {
    constructor() {
        this.mcpServers = [];
        this.llmConfigurations = [];
        this.activeLLM = null;
        this.profiles = [];
        this.activeProfileId = null;
        this.masterClassificationProfileId = null; // DEPRECATED: Legacy single master (for backwards compatibility)
        this.masterClassificationProfileIds = {}; // NEW: Per-server masters {mcpServerId: profileId}
        this.initialized = false;
        this.profileTestStatus = {}; // Track test status: profileId -> { tested: boolean, passed: boolean, timestamp: number }
    }

    async initialize() {
        if (this.initialized) return;
        await this.loadMCPServers();
        await this.loadLLMConfigurations();
        await this.migrateLegacyLLMProviders();
        await this.loadProfiles();
        this.initialized = true;
    }

    /**
     * Migrate legacy localStorage LLM providers to backend configurations
     */
    async migrateLegacyLLMProviders() {
        try {
            // Check if there are any legacy providers in localStorage
            const legacyProvidersJSON = safeGetItem(STORAGE_KEYS.LLM_PROVIDERS);
            if (!legacyProvidersJSON) return; // Nothing to migrate

            const legacyProviders = JSON.parse(legacyProvidersJSON);
            const providerKeys = Object.keys(legacyProviders);
            
            if (providerKeys.length === 0) {
                // Clean up empty legacy data
                localStorage.removeItem(STORAGE_KEYS.LLM_PROVIDERS);
                localStorage.removeItem(STORAGE_KEYS.ACTIVE_LLM);
                return;
            }

            console.log('Migrating legacy LLM providers:', providerKeys);

            // Track migration results
            const migrationResults = [];

            // Migrate each provider to a new configuration
            for (const providerKey of providerKeys) {
                const legacyConfig = legacyProviders[providerKey];
                if (!legacyConfig || !legacyConfig.model) continue; // Skip incomplete configs

                const configData = {
                    name: `${providerKey} (Migrated)`,
                    provider: providerKey,
                    model: legacyConfig.model,
                    credentials: legacyConfig.credentials || {}
                };

                // Add listingMethod for Amazon if it exists
                if (providerKey === 'Amazon' && legacyConfig.listingMethod) {
                    configData.credentials.listingMethod = legacyConfig.listingMethod;
                }

                try {
                    const result = await this.addLLMConfiguration(configData);
                    if (result) {
                        migrationResults.push({ provider: providerKey, success: true, id: result.id });
                        console.log(`Migrated ${providerKey} configuration:`, result);
                    }
                } catch (error) {
                    console.error(`Failed to migrate ${providerKey}:`, error);
                    migrationResults.push({ provider: providerKey, success: false, error: error.message });
                }
            }

            // Note: We don't set an active LLM anymore since active state is now
            // determined by profiles. Users will need to update their profiles to
            // use the migrated configurations.

            // Clean up localStorage after successful migration
            localStorage.removeItem(STORAGE_KEYS.LLM_PROVIDERS);
            localStorage.removeItem(STORAGE_KEYS.ACTIVE_LLM);

            const successCount = migrationResults.filter(r => r.success).length;
            if (successCount > 0) {
                showNotification('success', `Migrated ${successCount} LLM configuration(s) to new system`);
            }
        } catch (error) {
            console.error('Error during LLM provider migration:', error);
            // Don't fail initialization if migration fails
        }
    }

    async loadProfiles() {
        try {
            const { profiles, default_profile_id, active_for_consumption_profile_ids } = await API.getProfiles();
            console.log('[ConfigState] Loaded profiles:', { profiles, default_profile_id, active_for_consumption_profile_ids });
            this.profiles = profiles || [];
            this.defaultProfileId = default_profile_id;
            this.activeForConsumptionProfileIds = active_for_consumption_profile_ids || [];

            // Load master classification profile ID
            try {
                const response = await API.getMasterClassificationProfile();
                // NEW: Per-server masters dict
                this.masterClassificationProfileIds = response.master_classification_profile_ids || {};
                // DEPRECATED: Legacy single master (for backwards compatibility)
                this.masterClassificationProfileId = response.master_classification_profile_id;
                console.log('[ConfigState] Loaded master classification profiles:', this.masterClassificationProfileIds);
            } catch (error) {
                console.error('Failed to load master classification profile:', error);
                this.masterClassificationProfileIds = {};
                this.masterClassificationProfileId = null;
            }

            // Set active_for_consumption flag on each profile based on the active list
            this.profiles.forEach(profile => {
                profile.active_for_consumption = this.activeForConsumptionProfileIds.includes(profile.id);
            });

            console.log('[ConfigState] State after load:', {
                profileCount: this.profiles.length,
                defaultProfileId: this.defaultProfileId,
                masterClassificationProfileId: this.masterClassificationProfileId,
                activeCount: this.activeForConsumptionProfileIds.length,
                activeIds: this.activeForConsumptionProfileIds
            });
            
            // Initialize session header with default profile
            if (this.defaultProfileId && typeof window.updateSessionHeaderProfile === 'function') {
                const defaultProfile = this.profiles.find(p => p.id === this.defaultProfileId);
                if (defaultProfile) {
                    window.updateSessionHeaderProfile(defaultProfile, null);
                }
            }
            
            // Update Planner Repository navigation state based on profile
            if (typeof window.updatePlannerRepositoryNavigation === 'function') {
                window.updatePlannerRepositoryNavigation();
            }
            
            return this.profiles;
        } catch (error) {
            console.error('Failed to load profiles:', error);
            this.profiles = [];
        }
        return this.profiles;
    }
    
    async addProfile(profile) {
        const newProfile = await API.addProfile(profile);
        this.profiles.push(newProfile.profile);
        return newProfile.profile;
    }

    async updateProfile(profileId, updates) {
        const updatedProfile = await API.updateProfile(profileId, updates);
        const index = this.profiles.findIndex(p => p.id === profileId);
        if (index !== -1) {
            this.profiles[index] = { ...this.profiles[index], ...updates };
        }
        
        // Dispatch event to mark configuration as dirty
        document.dispatchEvent(new CustomEvent('profile-modified', { 
            detail: { profileId, updates } 
        }));
        
        // Reset initialization state when profile is updated
        // This ensures the conversation will re-initialize with new settings
        import('../conversationInitializer.js').then(({ resetInitialization }) => {
            resetInitialization();
            console.log('[ConfigState] Profile updated - conversation will re-initialize on next start');
        });
        
        return updatedProfile;
    }

    async copyProfile(profileId) {
        const profile = this.profiles.find(p => p.id === profileId);
        if (!profile) return null;
        
        // Create a copy with a new ID and modified name
        const newProfile = {
            ...profile,
            id: `profile-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            name: `${profile.name} (Copy)`,
            tag: '' // Clear tag so user can generate/enter a new one
        };
        
        // Add the copied profile using the proper API function
        try {
            await API.addProfile(newProfile);
            await this.loadProfiles();
            return newProfile;
        } catch (error) {
            console.error('[copyProfile] Error:', error);
            return null;
        }
    }

    async removeProfile(profileId) {
        await API.deleteProfile(profileId);
        this.profiles = this.profiles.filter(p => p.id !== profileId);
        if (this.defaultProfileId === profileId) {
            this.defaultProfileId = null;
        }
        this.activeForConsumptionProfileIds = this.activeForConsumptionProfileIds.filter(id => id !== profileId);
    }

    async setDefaultProfile(profileId) {
        await API.setDefaultProfile(profileId);
        this.defaultProfileId = profileId;

        // Dispatch event to mark configuration as dirty
        document.dispatchEvent(new CustomEvent('default-profile-changed', {
            detail: { profileId }
        }));

        // Update Planner Repository navigation state when default profile changes
        if (typeof window.updatePlannerRepositoryNavigation === 'function') {
            window.updatePlannerRepositoryNavigation();
        }

        // Update resource panel to reflect new default profile's tools/prompts
        // BUT only if there's no active @TAG override (don't disrupt user's current selection)
        if (typeof window.updateResourcePanelForProfile === 'function') {
            const hasActiveOverride = window.activeTagPrefix && window.activeTagPrefix.trim().length > 0;
            if (!hasActiveOverride) {
                window.updateResourcePanelForProfile(profileId);
                console.log('[ConfigState] Resource panel updated to new default profile:', profileId);
            } else {
                console.log('[ConfigState] Skipping resource panel update - user has active @TAG override');
            }
        }

        // Reset initialization state when default profile changes
        import('../conversationInitializer.js').then(({ resetInitialization }) => {
            resetInitialization();
            console.log('[ConfigState] Default profile changed - conversation will re-initialize');
        });
    }

    async setActiveForConsumptionProfiles(profileIds) {
        console.log('[ConfigState] 🔄 setActiveForConsumptionProfiles called with:', profileIds);
        await API.setActiveForConsumptionProfiles(profileIds);
        this.activeForConsumptionProfileIds = profileIds;
        
        // Dispatch event to mark configuration as dirty
        console.log('[ConfigState] 📤 Dispatching profile-modified event');
        document.dispatchEvent(new CustomEvent('profile-modified', { 
            detail: { source: 'active-for-consumption-changed', profileIds } 
        }));
        
        // Update knowledge indicator when active profiles change
        if (typeof window.updateKnowledgeIndicatorStatus === 'function') {
            window.updateKnowledgeIndicatorStatus();
        }
    }

    async loadMCPServers() {
        try {
            const headers = {};
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }
            
            const response = await fetch('/api/v1/mcp/servers', { headers });
            const result = await response.json();
            
            if (result.status === 'success') {
                this.mcpServers = result.servers || [];
                this.activeMCP = result.active_server_id;
                return this.mcpServers;
            }
        } catch (error) {
            console.error('Failed to load MCP servers:', error);
            this.mcpServers = [];
        }
        return this.mcpServers;
    }

    async saveMCPServers() {
        // No-op: servers are saved individually via API
        // Kept for compatibility
    }

    async loadLLMConfigurations() {
        try {
            const headers = {};
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }
            
            const response = await fetch('/api/v1/llm/configurations', { headers });
            const result = await response.json();
            
            if (result.status === 'success') {
                this.llmConfigurations = result.configurations || [];
                this.activeLLM = result.active_configuration_id;
                return this.llmConfigurations;
            }
        } catch (error) {
            console.error('Failed to load LLM configurations:', error);
            this.llmConfigurations = [];
        }
        return this.llmConfigurations;
    }

    async setActiveMCP(serverId) {
        // Skip activation if serverId is null (for llm_only and rag_focused profiles)
        if (!serverId) {
            this.activeMCP = null;
            return;
        }

        try {
            const headers = {};
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }

            const response = await fetch(`/api/v1/mcp/servers/${serverId}/activate`, {
                method: 'POST',
                headers: headers
            });

            if (response.ok) {
                this.activeMCP = serverId;
                updateReconnectButton();
            }
        } catch (error) {
            console.error('Failed to set active MCP server:', error);
        }
    }

    async setActiveLLM(configId) {
        try {
            const headers = {};
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }
            
            const response = await fetch(`/api/v1/llm/configurations/${configId}/activate`, {
                method: 'POST',
                headers: headers
            });
            
            if (response.ok) {
                this.activeLLM = configId;
                updateReconnectButton();
            }
        } catch (error) {
            console.error('Failed to set active LLM configuration:', error);
        }
    }

    async addMCPServer(server) {
        // Server-side UUID generation - remove client-side ID generation
        // Backend will generate ID if not provided

        try {
            const headers = { 'Content-Type': 'application/json' };
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }

            const response = await fetch('/api/v1/mcp/servers', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(server)
            });

            if (response.ok) {
                const result = await response.json();
                const serverId = result.server_id; // Backend-generated ID

                // Reload servers from backend to get the updated list
                await this.loadMCPServers();
                // Dispatch event to mark config as dirty
                document.dispatchEvent(new CustomEvent('profile-modified', {
                    detail: { source: 'mcp-server-add' }
                }));
                return serverId;
            } else {
                const errorData = await response.json();
                console.error('Failed to add MCP server:', errorData);
                throw new Error(errorData.message || 'Failed to add MCP server');
            }
        } catch (error) {
            console.error('Failed to add MCP server:', error);
            throw error;
        }
    }

    async removeMCPServer(serverId) {
        try {
            const headers = {};
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }

            const response = await fetch(`/api/v1/mcp/servers/${serverId}`, {
                method: 'DELETE',
                headers: headers
            });

            if (response.ok) {
                this.mcpServers = this.mcpServers.filter(s => s.id !== serverId);
                if (this.activeMCP === serverId) {
                    this.activeMCP = null;
                }
                // Dispatch event to mark config as dirty
                document.dispatchEvent(new CustomEvent('profile-modified', {
                    detail: { source: 'mcp-server-remove' }
                }));
                return { success: true };
            } else {
                const errorData = await response.json();
                return {
                    success: false,
                    error: errorData.message || 'Failed to remove MCP server'
                };
            }
        } catch (error) {
            console.error('Failed to remove MCP server:', error);
            return {
                success: false,
                error: error.message || 'Failed to remove MCP server'
            };
        }
    }

    async updateMCPServer(serverId, updates) {
        try {
            const headers = { 'Content-Type': 'application/json' };
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }
            
            const response = await fetch(`/api/v1/mcp/servers/${serverId}`, {
                method: 'PUT',
                headers: headers,
                body: JSON.stringify(updates)
            });
            
            if (response.ok) {
                // Reload servers from backend to get the updated list
                await this.loadMCPServers();
                
                // Clear test status for all profiles using this MCP server
                this.profiles.forEach(profile => {
                    if (profile.mcpServerId === serverId) {
                        delete this.profileTestStatus[profile.id];
                    }
                });
                
                // Dispatch event to mark config as dirty
                document.dispatchEvent(new CustomEvent('profile-modified', { 
                    detail: { source: 'mcp-server-update' } 
                }));
                return true;
            } else {
                // Extract error message from response
                const errorData = await response.json().catch(() => ({}));
                const errorMessage = errorData.message || `Server returned status ${response.status}`;
                throw new Error(errorMessage);
            }
        } catch (error) {
            console.error('Failed to update MCP server:', error);
            throw error; // Re-throw to be handled by caller
        }
    }

    async addLLMConfiguration(configuration) {
        configuration.id = configuration.id || generateId();
        
        try {
            const headers = { 'Content-Type': 'application/json' };
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }
            
            const response = await fetch('/api/v1/llm/configurations', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(configuration)
            });
            
            if (response.ok) {
                const result = await response.json();
                await this.loadLLMConfigurations();
                // Dispatch event to mark config as dirty
                document.dispatchEvent(new CustomEvent('profile-modified', { 
                    detail: { source: 'llm-config-add' } 
                }));
                return result.configuration; // Return the full configuration object with ID
            } else {
                const errorData = await response.json();
                console.error('Failed to add LLM configuration:', errorData);
                throw new Error(errorData.message || 'Failed to add LLM configuration');
            }
        } catch (error) {
            console.error('Failed to add LLM configuration:', error);
            throw error;
        }
    }

    async removeLLMConfiguration(configId) {
        try {
            const response = await fetch(`/api/v1/llm/configurations/${configId}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.llmConfigurations = this.llmConfigurations.filter(c => c.id !== configId);
                if (this.activeLLM === configId) {
                    this.activeLLM = null;
                }
                // Dispatch event to mark config as dirty
                document.dispatchEvent(new CustomEvent('profile-modified', { 
                    detail: { source: 'llm-config-remove' } 
                }));
                return { success: true };
            } else {
                const errorData = await response.json();
                return { 
                    success: false, 
                    error: errorData.message || 'Failed to remove LLM configuration' 
                };
            }
        } catch (error) {
            console.error('Failed to remove LLM configuration:', error);
            return { 
                success: false, 
                error: error.message || 'Failed to remove LLM configuration' 
            };
        }
    }

    async updateLLMConfiguration(configId, updates) {
        try {
            const headers = { 'Content-Type': 'application/json' };
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }
            
            const response = await fetch(`/api/v1/llm/configurations/${configId}`, {
                method: 'PUT',
                headers: headers,
                body: JSON.stringify(updates)
            });
            
            if (response.ok) {
                await this.loadLLMConfigurations();
                
                // Clear test status for all profiles using this LLM configuration
                this.profiles.forEach(profile => {
                    if (profile.llmConfigurationId === configId) {
                        delete this.profileTestStatus[profile.id];
                    }
                });
                
                // Dispatch event to mark config as dirty
                document.dispatchEvent(new CustomEvent('profile-modified', { 
                    detail: { source: 'llm-config-update' } 
                }));
                return true;
            }
        } catch (error) {
            console.error('Failed to update LLM configuration:', error);
        }
        return false;
    }

    getActiveMCPServer() {
        return this.mcpServers.find(s => s.id === this.activeMCP);
    }

    getActiveLLMConfiguration() {
        return this.llmConfigurations.find(c => c.id === this.activeLLM);
    }

    canReconnect() {
        // First check global active MCP/LLM
        let mcpServer = this.getActiveMCPServer();
        let llmConfig = this.getActiveLLMConfiguration();
        let defaultProfile = null;

        // If no global active MCP/LLM, check the default profile's configuration
        if ((!mcpServer || !llmConfig) && this.defaultProfileId) {
            defaultProfile = this.profiles.find(p => p.id === this.defaultProfileId);
            if (defaultProfile) {
                if (!mcpServer && defaultProfile.mcpServerId) {
                    mcpServer = this.mcpServers.find(s => s.id === defaultProfile.mcpServerId);
                }
                if (!llmConfig && defaultProfile.llmConfigurationId) {
                    llmConfig = this.llmConfigurations.find(c => c.id === defaultProfile.llmConfigurationId);
                }
            }
        }

        // Get profile type to determine requirements
        if (!defaultProfile && this.defaultProfileId) {
            defaultProfile = this.profiles.find(p => p.id === this.defaultProfileId);
        }

        const profileType = defaultProfile?.profile_type || 'tool_enabled';

        // Conversation Focused (LLM) and Knowledge Focused (RAG) profiles only need LLM
        // Tool Focused (MCP) profiles need both MCP and LLM
        if (profileType === 'llm_only' || profileType === 'rag_focused') {
            return !!(llmConfig && llmConfig.model);
        } else {
            return !!(mcpServer && llmConfig && llmConfig.model);
        }
    }
}

// Global state instance
export const configState = new ConfigurationState();

// Also expose to window to avoid circular imports
window.configState = configState;

// ============================================================================
// UI RENDERING - MCP SERVERS
// ============================================================================
export function renderMCPServers() {
    const container = document.getElementById('mcp-servers-container');
    if (!container) return;

    if (configState.mcpServers.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-400 py-8">
                <p>No MCP servers configured. Click "Add Server" to get started.</p>
            </div>
        `;
        return;
    }

    // Determine which servers are used by profiles
    const defaultProfile = configState.profiles.find(p => p.id === configState.defaultProfileId);
    const activeProfiles = configState.profiles.filter(p => 
        configState.activeForConsumptionProfileIds.includes(p.id)
    );

    container.innerHTML = configState.mcpServers.map(server => {
        // Check if this server is used by default profile
        const isDefault = defaultProfile?.mcpServerId === server.id;
        
        // Check if this server is used by any active profile
        const isActive = activeProfiles.some(p => p.mcpServerId === server.id);
        
        // Build status badges
        let statusBadges = '';
        if (isDefault) {
            statusBadges += '<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-medium bg-blue-500 text-white rounded-full">Default</span>';
        }
        if (isActive) {
            statusBadges += '<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-medium bg-green-500 text-white rounded-full ml-2">Active</span>';
        }

        return `
            <div class="bg-gradient-to-br from-white/10 to-white/5 border-2 border-white/10 rounded-xl p-4 hover:border-white/20 transition-all duration-200" data-mcp-id="${server.id}">
                <div class="flex items-center justify-between gap-4">
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                            <h4 class="text-base font-bold text-white truncate">${escapeHtml(server.name)}</h4>
                            ${statusBadges}
                        </div>
                        <div class="text-sm text-gray-400">
                            <span class="font-medium text-gray-300">Host:</span> ${escapeHtml(server.host)}:${escapeHtml(server.port)} 
                            <span class="mx-2">•</span> 
                            <span class="font-medium text-gray-300">Path:</span> ${escapeHtml(server.path)}
                        </div>
                        ${server.testStatus ? `
                            <div class="mt-2 text-sm ${server.testStatus === 'success' ? 'text-green-400' : 'text-red-400'}">
                                ${escapeHtml(server.testMessage || '')}
                            </div>
                        ` : ''}
                    </div>
                    <div class="flex items-center gap-2 flex-shrink-0">
                        <button type="button" data-action="test-mcp" data-server-id="${server.id}" 
                            class="px-3 py-1.5 text-sm font-medium bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors text-white">
                            Test
                        </button>
                        <button type="button" data-action="edit-mcp" data-server-id="${server.id}" 
                            class="px-3 py-1.5 text-sm font-medium bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors text-white">
                            Edit
                        </button>
                        <button type="button" data-action="delete-mcp" data-server-id="${server.id}" 
                            class="px-3 py-1.5 text-sm font-medium bg-gray-700 hover:bg-red-600 rounded-lg transition-colors text-red-400 hover:text-white">
                            Delete
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    attachMCPEventListeners();
}

function attachMCPEventListeners() {

    // Test MCP button
    document.querySelectorAll('[data-action="test-mcp"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const serverId = e.target.dataset.serverId;
            testMCPConnection(serverId);
        });
    });

    // Edit MCP button
    document.querySelectorAll('[data-action="edit-mcp"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const serverId = e.target.dataset.serverId;
            showMCPServerModal(serverId);
        });
    });

    // Delete MCP button
    document.querySelectorAll('[data-action="delete-mcp"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const serverId = e.target.dataset.serverId;
            const server = configState.mcpServers.find(s => s.id === serverId);
            const serverName = server ? server.name : 'this server';

            // Count associated collections
            const { collections: allCollections } = await API.getRagCollections();
            const serverCollections = allCollections.filter(c => c.mcp_server_id === serverId);
            const collectionCount = serverCollections.length;

            // Build confirmation message with collection warning
            let confirmMessage = `Are you sure you want to delete MCP server "${serverName}"?`;
            if (collectionCount > 0) {
                confirmMessage += `\n\n⚠️ This will also delete ${collectionCount} associated collection(s):`;
                serverCollections.forEach(c => {
                    confirmMessage += `\n• ${c.name}`;
                });
            }

            showDeleteConfirmation(confirmMessage, async () => {
                const result = await configState.removeMCPServer(serverId);
                if (result.success) {
                    renderMCPServers();
                    showNotification('success', 'MCP server and associated collections deleted successfully');
                } else {
                    showNotification('error', result.error);
                }
            });
        });
    });
}

// ============================================================================
// UI RENDERING - LLM CONFIGURATIONS
// ============================================================================
export function renderLLMProviders() {
    const container = document.getElementById('llm-providers-container');
    if (!container) return;

    if (configState.llmConfigurations.length === 0) {
        container.innerHTML = `
            <div class="col-span-full text-center text-gray-400 py-8">
                <p>No LLM configurations found. Click "Add Configuration" to get started.</p>
            </div>
        `;
        return;
    }

    // Determine which configurations are used by profiles
    const defaultProfile = configState.profiles.find(p => p.id === configState.defaultProfileId);
    const activeProfiles = configState.profiles.filter(p => 
        configState.activeForConsumptionProfileIds.includes(p.id)
    );

    container.innerHTML = configState.llmConfigurations.map(config => {
        // Check if this configuration is used by default profile
        const isDefault = defaultProfile?.llmConfigurationId === config.id;
        
        // Check if this configuration is used by any active profile
        const isActive = activeProfiles.some(p => p.llmConfigurationId === config.id);
        
        // Build status badges
        let statusBadges = '';
        if (isDefault) {
            statusBadges += '<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-medium bg-blue-500 text-white rounded-full">Default</span>';
        }
        if (isActive) {
            statusBadges += '<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-medium bg-green-500 text-white rounded-full ml-2">Active</span>';
        }

        return `
            <div class="bg-gradient-to-br from-white/10 to-white/5 border-2 border-white/10 rounded-xl p-5 hover:border-white/20 transition-all duration-200" data-llm-config-id="${config.id}">
                <div class="flex flex-col gap-4">
                    <div class="flex items-start justify-between">
                        <div class="flex-1">
                            <div class="flex items-center gap-2 mb-3">
                                <h4 class="text-lg font-bold text-white">${escapeHtml(config.name)}</h4>
                                ${statusBadges}
                            </div>
                            <div class="space-y-2">
                                <div class="flex items-center gap-2 text-sm">
                                    <span class="font-semibold text-gray-300">Provider:</span>
                                    <span class="text-gray-400">${escapeHtml(config.provider)}</span>
                                </div>
                                <div class="flex items-center gap-2 text-sm">
                                    <span class="font-semibold text-gray-300">Model:</span>
                                    <span class="text-gray-400">${escapeHtml(config.model)}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- Test results container -->
                    <div id="llm-test-results-${config.id}" class="text-sm min-h-[20px]"></div>
                    
                    <div class="flex items-center gap-2 pt-2 border-t border-white/10">
                        <button type="button" data-action="test-llm" data-config-id="${config.id}" 
                            class="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors text-white">
                            Test
                        </button>
                        <button type="button" data-action="edit-llm" data-config-id="${config.id}" 
                            class="flex-1 px-4 py-2 text-sm font-medium bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors text-white">
                            Edit
                        </button>
                        <button type="button" data-action="delete-llm" data-config-id="${config.id}" 
                            class="flex-1 px-4 py-2 text-sm font-medium bg-gray-700 hover:bg-red-600 rounded-lg transition-colors text-red-400 hover:text-white">
                            Delete
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    attachLLMEventListeners();
}

function attachLLMEventListeners() {
    // Test LLM button
    document.querySelectorAll('[data-action="test-llm"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const configId = e.target.dataset.configId;
            const resultsContainer = document.getElementById(`llm-test-results-${configId}`);
            const testBtn = e.target;
            
            // Show testing state
            resultsContainer.innerHTML = '<span class="text-yellow-400">Testing credentials...</span>';
            testBtn.disabled = true;
            testBtn.textContent = 'Testing...';
            
            try {
                const result = await API.testLLMConfiguration(configId);
                
                if (result.status === 'success') {
                    resultsContainer.innerHTML = `<span class="text-green-400">✓ Credentials valid</span>`;
                } else {
                    // Extract just the key part of the error message
                    let errorMsg = result.message || 'Test failed';
                    // Remove file paths and stack traces
                    errorMsg = errorMsg.split('(/')[0].split('(File:')[0].trim();
                    // Limit length
                    if (errorMsg.length > 60) {
                        errorMsg = errorMsg.substring(0, 60) + '...';
                    }
                    resultsContainer.innerHTML = `<span class="text-red-400">✗ ${errorMsg}</span>`;
                }
            } catch (error) {
                // Extract just the key part of the error message
                let errorMsg = error.message || 'Test failed';
                errorMsg = errorMsg.split('(/')[0].split('(File:')[0].trim();
                if (errorMsg.length > 60) {
                    errorMsg = errorMsg.substring(0, 60) + '...';
                }
                resultsContainer.innerHTML = `<span class="text-red-400">✗ ${errorMsg}</span>`;
            } finally {
                testBtn.disabled = false;
                testBtn.textContent = 'Test';
            }
        });
    });
    
    // Edit LLM button
    document.querySelectorAll('[data-action="edit-llm"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const configId = e.target.dataset.configId;
            await showLLMConfigurationModal(configId);
        });
    });

    // Delete LLM button
    document.querySelectorAll('[data-action="delete-llm"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const configId = e.target.dataset.configId;
            const config = configState.llmConfigurations.find(c => c.id === configId);
            
            if (config) {
                showDeleteConfirmation(`Are you sure you want to delete "${config.name}"?`, async () => {
                    const result = await configState.removeLLMConfiguration(configId);
                    if (result.success) {
                        showNotification('success', 'LLM configuration deleted successfully');
                        renderLLMProviders();
                        updateReconnectButton();
                    } else {
                        showNotification('error', result.error);
                    }
                });
            }
        });
    });
}

// Placeholder for LLM configuration modal (to be implemented)
export async function showLLMConfigurationModal(configId = null) {
    let config = configId ? configState.llmConfigurations.find(c => c.id === configId) : null;
    const isEdit = !!config;
    
    // If editing, fetch the full configuration with decrypted credentials
    if (isEdit && configId) {
        try {
            const headers = {};
            const authToken = localStorage.getItem('tda_auth_token');
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }
            
            const response = await fetch(`/api/v1/llm/configurations/${configId}`, { 
                method: 'GET',
                headers 
            });
            
            if (response.ok) {
                const result = await response.json();
                if (result.status === 'success' && result.configuration) {
                    config = result.configuration;
                }
            }
        } catch (error) {
            console.error('Failed to fetch configuration with credentials:', error);
            // Continue with config from state (without credentials)
        }
    }
    
    const selectedProvider = config?.provider || 'Google';

    // Build provider options
    const providerOptions = Object.keys(LLM_PROVIDER_TEMPLATES)
        .map(key => `<option value="${key}" ${key === selectedProvider ? 'selected' : ''}>${LLM_PROVIDER_TEMPLATES[key].name}</option>`)
        .join('');

    const modalHTML = `
        <div id="llm-config-modal" class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
            <div class="glass-panel rounded-xl p-6 max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto">
                <h3 class="text-xl font-bold text-white mb-4">${isEdit ? 'Edit' : 'Add'} LLM Configuration</h3>
                <!-- Error banner container -->
                <div id="llm-modal-error" class="hidden mb-4 p-3 bg-red-500/20 border border-red-500 rounded-md">
                    <div class="flex items-start gap-2">
                        <svg class="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
                        </svg>
                        <span id="llm-modal-error-text" class="text-sm text-red-200 flex-1"></span>
                    </div>
                </div>
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">Configuration Name</label>
                        <input type="text" id="llm-modal-name" value="${config ? escapeHtml(config.name) : ''}" 
                            placeholder="e.g., Production GPT-4" 
                            class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">Provider</label>
                        <select id="llm-modal-provider" class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none" ${isEdit ? 'disabled' : ''}>
                            ${providerOptions}
                        </select>
                        ${isEdit ? '<p class="text-xs text-gray-400 mt-1">Provider cannot be changed after creation</p>' : ''}
                    </div>
                    <div id="llm-modal-credentials-container">
                        <!-- Credentials fields will be inserted here -->
                    </div>
                    <div id="llm-modal-model-container">
                        <label class="block text-sm font-medium text-gray-300 mb-1">Model</label>
                        <div class="flex items-center gap-2">
                            <select id="llm-modal-model" class="flex-1 min-w-0 p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none">
                                <option value="">-- Select a model --</option>
                                ${config?.model ? `<option value="${escapeHtml(config.model)}" selected>${escapeHtml(config.model)}</option>` : ''}
                            </select>
                            <button type="button" id="llm-modal-refresh-models" 
                                class="flex-shrink-0 p-2 bg-gray-600 hover:bg-gray-500 rounded-md transition-colors">
                                <svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0011.667 0l3.181-3.183m-4.991-2.691L7.985 5.356m0 0v4.992m0 0h4.992m0 0l3.181-3.183a8.25 8.25 0 0111.667 0l3.181 3.183" />
                                </svg>
                            </button>
                        </div>
                    </div>
                    <div class="flex gap-3 pt-4">
                        <button id="llm-modal-cancel" class="flex-1 px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded-md transition-colors text-white">
                            Cancel
                        </button>
                        <button id="llm-modal-save" class="flex-1 px-4 py-2 bg-[#F15F22] hover:bg-[#D9501A] rounded-md transition-colors text-white font-medium">
                            ${isEdit ? 'Update' : 'Add'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);

    const modal = document.getElementById('llm-config-modal');
    const providerSelect = modal.querySelector('#llm-modal-provider');
    const credentialsContainer = modal.querySelector('#llm-modal-credentials-container');
    const refreshBtn = modal.querySelector('#llm-modal-refresh-models');
    const modelSelect = modal.querySelector('#llm-modal-model');
    const errorBanner = modal.querySelector('#llm-modal-error');
    const errorText = modal.querySelector('#llm-modal-error-text');
    
    // Helper functions for error banner
    function showModalError(message) {
        errorText.textContent = message;
        errorBanner.classList.remove('hidden');
    }
    
    function hideModalError() {
        errorBanner.classList.add('hidden');
        errorText.textContent = '';
    }

    // Function to render credential fields based on selected provider
    function renderCredentialFields(provider) {
        const template = LLM_PROVIDER_TEMPLATES[provider];
        if (!template) return;

        let html = '';

        // Render regular credential fields
        template.fields.forEach(field => {
            let value = '';
            
            // Get credentials from config (backend database)
            if (config?.credentials) {
                value = config.credentials[field.id] || '';
            }
            
            html += `
                <div>
                    <label class="block text-sm font-medium text-gray-300 mb-1">${escapeHtml(field.label)}</label>
                    <input type="${field.type}" 
                        data-credential="${field.id}" 
                        value="${escapeHtml(value)}" 
                        placeholder="${escapeHtml(field.placeholder)}" 
                        ${field.required ? 'required' : ''}
                        class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none">
                </div>
            `;
        });

        // Render extra fields (like AWS listing method)
        if (template.extra?.listingMethod) {
            html += '<div><label class="block text-sm font-medium text-gray-300 mb-2">Model Listing Method</label><div class="flex items-center gap-6">';
            template.extra.listingMethod.forEach(option => {
                const checked = config?.listingMethod === option.value || (option.default && !config?.listingMethod);
                html += `
                    <div class="flex items-center">
                        <input id="listing-${option.id}" name="listing_method" type="radio" value="${option.value}" 
                            ${checked ? 'checked' : ''} 
                            data-credential="listing_method"
                            class="h-4 w-4 border-gray-300 text-[#F15F22] focus:ring-[#F15F22]">
                        <label for="listing-${option.id}" class="ml-2 text-sm text-gray-300">${escapeHtml(option.label)}</label>
                    </div>
                `;
            });
            html += '</div></div>';
        }

        credentialsContainer.innerHTML = html;
    }

    // Function to refresh models
    async function refreshModels() {
        const provider = providerSelect.value;
        
        if (!provider) {
            showNotification('error', 'Please select a provider first');
            return;
        }
        
        const credentials = {};
        
        // Collect credentials
        credentialsContainer.querySelectorAll('[data-credential]').forEach(input => {
            const field = input.dataset.credential;
            if (input.type === 'radio') {
                if (input.checked) {
                    credentials[field] = input.value;
                }
            } else {
                credentials[field] = input.value;
            }
        });
        
        // Validate required credentials
        const template = LLM_PROVIDER_TEMPLATES[provider];
        const missingFields = template.fields.filter(f => f.required && !credentials[f.id]);
        if (missingFields.length > 0) {
            showNotification('error', `Please enter: ${missingFields.map(f => f.label).join(', ')}`);
            return;
        }

        refreshBtn.disabled = true;
        refreshBtn.innerHTML = '<svg class="w-5 h-5 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';

        try {
            const response = await fetch('/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider, ...credentials })
            });

            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.message || 'Failed to fetch models');
            }

            if (data.models && data.models.length > 0) {
                const certifiedModels = data.models.filter(model => {
                    return typeof model === 'string' || model.certified !== false;
                });
                const firstCertifiedModel = certifiedModels.length > 0 
                    ? (typeof certifiedModels[0] === 'string' ? certifiedModels[0] : certifiedModels[0].name)
                    : null;
                
                // Clear and rebuild options without affecting select element styling
                modelSelect.innerHTML = '';
                
                const defaultOption = document.createElement('option');
                defaultOption.value = '';
                defaultOption.textContent = '-- Select a model --';
                modelSelect.appendChild(defaultOption);
                
                data.models.forEach(model => {
                    const modelName = typeof model === 'string' ? model : model.name;
                    const certified = typeof model === 'object' ? model.certified : true;
                    const label = certified ? modelName : `${modelName} (support evaluated)`;
                    const selected = modelName === firstCertifiedModel;
                    
                    const option = document.createElement('option');
                    option.value = modelName;
                    option.textContent = label;
                    if (!certified) option.disabled = true;
                    if (selected) option.selected = true;
                    
                    modelSelect.appendChild(option);
                });
                
                showNotification('success', `Found ${data.models.length} models${firstCertifiedModel ? ` - selected ${firstCertifiedModel}` : ''}`);
            } else {
                showNotification('warning', 'No models found');
            }
        } catch (error) {
            showNotification('error', `Failed to fetch models: ${error.message}`);
        } finally {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = '<svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0011.667 0l3.181-3.183m-4.991-2.691L7.985 5.356m0 0v4.992m0 0h4.992m0 0l3.181-3.183a8.25 8.25 0 0111.667 0l3.181 3.183" /></svg>';
        }
    }

    // Initial render of credential fields
    renderCredentialFields(selectedProvider);

    // Provider change handler (only for new configs)
    if (!isEdit) {
        providerSelect.addEventListener('change', () => {
            renderCredentialFields(providerSelect.value);
            // Clear model selection when provider changes
            modelSelect.innerHTML = '<option value="">-- Select a model --</option>';
        });
    }

    // Refresh models button
    refreshBtn.addEventListener('click', refreshModels);

    // Cancel button
    modal.querySelector('#llm-modal-cancel').addEventListener('click', () => modal.remove());

    // Save button
    modal.querySelector('#llm-modal-save').addEventListener('click', async () => {
        const saveBtn = modal.querySelector('#llm-modal-save');
        const name = modal.querySelector('#llm-modal-name').value.trim();
        const provider = providerSelect.value;
        const model = modelSelect.value;
        
        // Clear any previous errors
        hideModalError();
        
        if (!name) {
            showModalError('Configuration name is required');
            return;
        }

        if (!model) {
            showModalError('Please select a model');
            return;
        }

        // Collect credentials
        const credentials = {};
        credentialsContainer.querySelectorAll('[data-credential]').forEach(input => {
            const field = input.dataset.credential;
            if (input.type === 'radio') {
                if (input.checked) {
                    credentials[field] = input.value;
                }
            } else {
                credentials[field] = input.value;
            }
        });

        // Validate required fields
        const template = LLM_PROVIDER_TEMPLATES[provider];
        const missingFields = template.fields.filter(f => f.required && !credentials[f.id]);
        if (missingFields.length > 0) {
            showModalError(`Missing required fields: ${missingFields.map(f => f.label).join(', ')}`);
            return;
        }

        const configData = {
            name,
            provider,
            model,
            credentials
        };

        try {
            // Disable save button during validation
            saveBtn.disabled = true;
            saveBtn.textContent = 'Testing credentials...';
            
            // Save the configuration first (temporarily)
            let savedConfigId;
            let isNewConfig = !isEdit;
            
            if (isEdit) {
                await configState.updateLLMConfiguration(configId, configData);
                savedConfigId = configId;
            } else {
                savedConfigId = await configState.addLLMConfiguration(configData);
                if (!savedConfigId) {
                    throw new Error('Failed to create configuration');
                }
            }
            
            // Test the credentials
            try {
                const testResult = await API.testLLMConfiguration(savedConfigId);
                
                if (testResult.status !== 'success') {
                    // Test failed - remove the config if it was new, or revert if edited
                    if (isNewConfig) {
                        await configState.removeLLMConfiguration(savedConfigId);
                    }
                    showModalError(`Credential validation failed: ${testResult.message}`);
                    return;
                }
                
                // Credentials are now stored in encrypted database only (no localStorage)
                
                renderLLMProviders();
                showNotification('success', `LLM configuration ${isEdit ? 'updated' : 'added'} successfully with validated credentials`);
                modal.remove();
                
            } catch (testError) {
                // Test failed with exception - remove the config if it was new
                if (isNewConfig) {
                    await configState.removeLLMConfiguration(savedConfigId);
                }
                showModalError(`Credential validation failed: ${testError.message}`);
            }
        } catch (error) {
            showModalError(`Failed to ${isEdit ? 'update' : 'add'} configuration: ${error.message}`);
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = isEdit ? 'Update' : 'Add';
        }
    });
}

// Old LLM provider form functions removed - now using LLM configurations
// renderLLMProviderForm, refreshModels, saveLLMProvider are deprecated

// ============================================================================
// ACTION HANDLERS - MCP SERVERS
// ============================================================================
export function showMCPServerModal(serverId = null) {
    const server = serverId ? configState.mcpServers.find(s => s.id === serverId) : null;
    const isEdit = !!server;

    const modalHTML = `
        <div id="mcp-server-modal" class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
            <div class="glass-panel rounded-xl p-6 max-w-md w-full mx-4">
                <h3 class="text-xl font-bold text-white mb-4">${isEdit ? 'Edit' : 'Add'} MCP Server</h3>
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">Server Name</label>
                        <input type="text" id="mcp-modal-name" value="${server ? escapeHtml(server.name) : ''}" 
                            placeholder="e.g., Production DB Server" 
                            class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">Host</label>
                        <input type="text" id="mcp-modal-host" value="${server ? escapeHtml(server.host) : ''}" 
                            placeholder="e.g., localhost" 
                            class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">Port</label>
                        <input type="text" id="mcp-modal-port" value="${server ? escapeHtml(server.port) : ''}" 
                            placeholder="e.g., 8000" 
                            class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">Path</label>
                        <input type="text" id="mcp-modal-path" value="${server ? escapeHtml(server.path) : ''}" 
                            placeholder="e.g., /sse" 
                            class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none">
                    </div>
                    <div class="flex gap-3 pt-4">
                        <button id="mcp-modal-cancel" class="flex-1 px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded-md transition-colors text-white">
                            Cancel
                        </button>
                        <button id="mcp-modal-save" class="flex-1 px-4 py-2 bg-[#F15F22] hover:bg-[#D9501A] rounded-md transition-colors text-white font-medium">
                            ${isEdit ? 'Update' : 'Add'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);

    const modal = document.getElementById('mcp-server-modal');
    modal.querySelector('#mcp-modal-cancel').addEventListener('click', () => modal.remove());
    modal.querySelector('#mcp-modal-save').addEventListener('click', async () => {
        const data = {
            name: modal.querySelector('#mcp-modal-name').value.trim(),
            host: modal.querySelector('#mcp-modal-host').value.trim(),
            port: modal.querySelector('#mcp-modal-port').value.trim(),
            path: modal.querySelector('#mcp-modal-path').value.trim(),
        };

        if (!data.name || !data.host || !data.port || !data.path) {
            showNotification('error', 'All fields are required');
            return;
        }

        try {
            let success;
            if (isEdit) {
                success = await configState.updateMCPServer(serverId, data);
            } else {
                const result = await configState.addMCPServer(data);
                success = result !== null && result !== undefined;
            }

            if (success) {
                renderMCPServers();
                modal.remove();
                showNotification('success', `MCP server ${isEdit ? 'updated' : 'added'} successfully`);
            } else {
                showNotification('error', `Failed to ${isEdit ? 'update' : 'add'} MCP server`);
            }
        } catch (error) {
            showNotification('error', `Failed to ${isEdit ? 'update' : 'add'} MCP server: ${error.message}`);
        }
    });
}

export function showImportMCPServerModal() {
    const modalHTML = `
        <div id="import-mcp-server-modal" class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
            <div class="glass-panel rounded-xl p-6 max-w-2xl w-full mx-4">
                <h3 class="text-xl font-bold text-white mb-4">Import MCP Server Configuration</h3>
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-2">
                            Paste configuration or upload file
                        </label>
                        <div class="text-xs text-gray-400 mb-2">
                            Supports: <span class="font-semibold text-blue-400">MCP Registry format</span> or <span class="font-semibold text-green-400">Claude Desktop format</span>
                        </div>
                        <textarea id="import-mcp-json-input"
                            placeholder='MCP Registry format:
{
  "name": "io.example/server",
  "version": "1.0.0",
  "packages": [{"transport": {"type": "sse", "url": "http://localhost:8000/sse"}}]
}

Claude Desktop format:
{
  "mcpServers": {
    "server-name": {
      "command": "npx",
      "args": ["-y", "@package/name"],
      "env": {"API_KEY": "your-key"}
    }
  }
}'
                            rows="14"
                            class="w-full p-3 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none font-mono text-sm text-gray-200"></textarea>
                    </div>
                    <div class="flex items-center gap-3">
                        <label class="flex-1 cursor-pointer">
                            <input type="file" id="import-mcp-file-input" accept=".json,application/json" class="hidden">
                            <span class="flex items-center justify-center px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-md transition-colors text-white text-sm">
                                📁 Or Upload server.json File
                            </span>
                        </label>
                        <span id="import-mcp-filename" class="text-sm text-gray-400 flex-1"></span>
                    </div>
                    <div id="import-mcp-preview" class="hidden">
                        <h4 class="text-sm font-semibold text-white mb-2">Server Preview:</h4>
                        <div id="import-mcp-preview-content" class="bg-gray-700/50 rounded-md p-3 text-sm text-gray-300"></div>
                    </div>
                    <div id="import-mcp-error" class="hidden">
                        <div class="bg-red-500/20 border border-red-500/50 rounded-md p-3 text-sm text-red-400"></div>
                    </div>
                    <div class="flex gap-3 pt-4">
                        <button id="import-mcp-modal-cancel" class="flex-1 px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded-md transition-colors text-white">
                            Cancel
                        </button>
                        <button id="import-mcp-modal-import" class="flex-1 px-4 py-2 bg-[#F15F22] hover:bg-[#D9501A] rounded-md transition-colors text-white font-medium">
                            Import Server
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);

    const modal = document.getElementById('import-mcp-server-modal');
    const jsonInput = modal.querySelector('#import-mcp-json-input');
    const fileInput = modal.querySelector('#import-mcp-file-input');
    const filenameDisplay = modal.querySelector('#import-mcp-filename');
    const previewDiv = modal.querySelector('#import-mcp-preview');
    const previewContent = modal.querySelector('#import-mcp-preview-content');
    const errorDiv = modal.querySelector('#import-mcp-error');

    // File upload handler
    fileInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (file) {
            filenameDisplay.textContent = file.name;
            try {
                const text = await file.text();
                jsonInput.value = text;
                validateAndPreviewServer(text);
            } catch (error) {
                showError(`Failed to read file: ${error.message}`);
            }
        }
    });

    // JSON input validation
    jsonInput.addEventListener('input', () => {
        const value = jsonInput.value.trim();
        if (value) {
            validateAndPreviewServer(value);
        } else {
            previewDiv.classList.add('hidden');
            errorDiv.classList.add('hidden');
        }
    });

    function validateAndPreviewServer(jsonText) {
        try {
            const serverData = JSON.parse(jsonText);

            // Detect format
            let formatName = '';
            let previewHTML = '';

            if (serverData.mcpServers) {
                // Claude Desktop format
                formatName = 'Claude Desktop';
                const servers = serverData.mcpServers;
                const serverCount = Object.keys(servers).length;

                if (serverCount === 0) {
                    showError("mcpServers object is empty");
                    return;
                }

                previewHTML = `
                    <div class="space-y-2">
                        <div><span class="font-semibold text-green-400">Format:</span> Claude Desktop</div>
                        <div><span class="font-semibold">Servers:</span> ${serverCount}</div>
                        <div class="mt-2 text-xs">
                            ${Object.keys(servers).map(name => `<div class="py-1">• ${escapeHtml(name)}</div>`).join('')}
                        </div>
                    </div>
                `;

            } else if (serverData.name || serverData.$schema) {
                // MCP Registry format
                formatName = 'MCP Registry';

                if (!serverData.name) {
                    showError("Missing required field: 'name'");
                    return;
                }
                if (!serverData.version) {
                    showError("Missing required field: 'version'");
                    return;
                }

                const transportInfo = extractTransportInfo(serverData);
                previewHTML = `
                    <div class="space-y-1">
                        <div><span class="font-semibold text-blue-400">Format:</span> MCP Registry</div>
                        <div><span class="font-semibold">Name:</span> ${escapeHtml(serverData.title || serverData.name)}</div>
                        <div><span class="font-semibold">Version:</span> ${escapeHtml(serverData.version)}</div>
                        ${serverData.description ? `<div><span class="font-semibold">Description:</span> ${escapeHtml(serverData.description)}</div>` : ''}
                        <div><span class="font-semibold">Transport:</span> ${escapeHtml(transportInfo)}</div>
                    </div>
                `;

            } else {
                showError("Unknown format. Expected MCP Registry or Claude Desktop format.");
                return;
            }

            // Show preview
            errorDiv.classList.add('hidden');
            previewDiv.classList.remove('hidden');
            previewContent.innerHTML = previewHTML;

        } catch (error) {
            showError(`Invalid JSON: ${error.message}`);
        }
    }

    function extractTransportInfo(serverData) {
        const packages = serverData.packages || [];
        const remotes = serverData.remotes || [];

        for (const pkg of packages) {
            const transport = pkg.transport;
            if (transport) {
                return `${transport.type} (${transport.url || 'local command'})`;
            }
        }

        for (const remote of remotes) {
            const transport = remote.transport;
            if (transport) {
                return `${transport.type} (${transport.url || 'remote'})`;
            }
        }

        return 'Unknown';
    }

    function showError(message) {
        errorDiv.classList.remove('hidden');
        errorDiv.querySelector('div').textContent = message;
        previewDiv.classList.add('hidden');
    }

    // Cancel button
    modal.querySelector('#import-mcp-modal-cancel').addEventListener('click', () => modal.remove());

    // Import button
    modal.querySelector('#import-mcp-modal-import').addEventListener('click', async () => {
        const jsonText = jsonInput.value.trim();

        if (!jsonText) {
            showNotification('error', 'Please paste or upload a server.json file');
            return;
        }

        try {
            const serverData = JSON.parse(jsonText);

            // Call import API
            const authToken = localStorage.getItem('tda_auth_token');
            const headers = {
                'Content-Type': 'application/json'
            };
            if (authToken) {
                headers['Authorization'] = `Bearer ${authToken}`;
            }

            const response = await fetch('/api/v1/mcp/servers/import', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(serverData)
            });

            const result = await response.json();
            console.log('[Import] Backend response:', result);

            if (result.status === 'success') {
                const serverCount = result.servers?.length || 1;
                showNotification('success', `Successfully imported ${serverCount} server(s)`);
                await configState.loadMCPServers(); // Reload MCP servers list
                renderMCPServers();
                modal.remove();
            } else {
                // Show detailed error with skipped servers info
                let errorMsg = result.message || 'Failed to import server';
                if (result.skipped && result.skipped.length > 0) {
                    errorMsg += '\n\nSkipped servers:';
                    result.skipped.forEach(skip => {
                        errorMsg += `\n• ${skip.name}: ${skip.reason}`;
                    });
                }
                showError(errorMsg);
            }
        } catch (error) {
            showError(`Import failed: ${error.message}`);
        }
    });
}

async function testMCPConnection(serverId) {
    const server = configState.mcpServers.find(s => s.id === serverId);
    if (!server) return;

    const btn = document.querySelector(`[data-action="test-mcp"][data-server-id="${serverId}"]`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Testing...';
    }

    try {
        // Build test payload - include transport info for stdio servers
        const testPayload = {
            id: server.id,
            name: server.name,
            host: server.host,
            port: server.port,
            path: server.path
        };

        // Include transport configuration if available (for stdio servers)
        if (server.transport) {
            testPayload.transport = server.transport;
        }

        const response = await fetch('/test-mcp-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(testPayload)
        });

        const result = await response.json();

        server.testStatus = result.status;
        server.testMessage = result.message;
        configState.saveMCPServers();
        renderMCPServers();

        showNotification(result.status, result.message);
    } catch (error) {
        showNotification('error', `Test failed: ${error.message}`);
        server.testStatus = 'error';
        server.testMessage = error.message;
        configState.saveMCPServers();
        renderMCPServers();
    }
}

// ============================================================================
// UI UPDATE HELPERS
// ============================================================================
function updateProfilesTab() {
    const profilesTab = document.querySelector('.config-tab[data-tab="profiles-tab"]');
    if (!profilesTab) return;

    const mcpConfigured = configState.mcpServers.length > 0;
    const llmConfigured = configState.llmConfigurations.length > 0;

    if (mcpConfigured && llmConfigured) {
        profilesTab.disabled = false;
        profilesTab.classList.remove('opacity-50', 'cursor-not-allowed');
    } else {
        profilesTab.disabled = true;
        profilesTab.classList.add('opacity-50', 'cursor-not-allowed');
    }
}

export function updateReconnectButton() {
    const btn = document.getElementById('reconnect-and-load-btn');
    if (!btn) return;

    const canReconnect = configState.canReconnect();
    btn.disabled = !canReconnect;
    btn.classList.toggle('opacity-50', !canReconnect);
    btn.classList.toggle('cursor-not-allowed', !canReconnect);
}

export async function reconnectAndLoad() {
    const defaultProfile = configState.profiles.find(p => p.id === configState.defaultProfileId);

    if (!defaultProfile) {
        showNotification('error', 'Please set a default profile before connecting.');
        return;
    }

    // Set the active MCP and LLM based on the default profile
    await configState.setActiveMCP(defaultProfile.mcpServerId);
    await configState.setActiveLLM(defaultProfile.llmConfigurationId);

    const mcpServer = configState.getActiveMCPServer();
    const llmConfig = configState.getActiveLLMConfiguration();
    const profileType = defaultProfile.profile_type || 'tool_enabled';

    // Validate LLM configuration (required for all profile types)
    if (!llmConfig) {
        showNotification('error', 'Please configure and select an LLM Configuration first (go to LLM Providers tab)');
        return;
    }

    // Validate MCP server only for Tool Focused profiles
    if (profileType === 'tool_enabled') {
        if (!mcpServer) {
            showNotification('error', 'Please configure and select an MCP Server first (go to MCP Servers tab)');
            return;
        }

        // Additional validation for required fields
        if (!mcpServer.host || !mcpServer.port) {
            showNotification('error', 'MCP Server configuration is incomplete (missing host or port)');
            return;
        }
    }

    // Credentials are now fetched from backend database during connection
    // No need to load from localStorage anymore

    const btn = document.getElementById('reconnect-and-load-btn');
    const btnText = document.getElementById('reconnect-button-text');
    const spinner = document.getElementById('reconnect-loading-spinner');
    const statusDiv = document.getElementById('reconnect-status');

    btn.disabled = true;
    btnText.textContent = 'Connecting...';
    spinner.classList.remove('hidden');
    spinner.classList.add('animate-spin');
    statusDiv.innerHTML = '<span class="text-gray-400">Initializing connection...</span>';

    try {
        // Build base config data
        const configData = {
            provider: llmConfig.provider,
            model: llmConfig.model,
            credentials: llmConfig.credentials,
            listing_method: llmConfig.listingMethod || 'foundation_models',
            tts_credentials_json: document.getElementById('tts-credentials-json')?.value || '',
            charting_intensity: document.getElementById('charting-intensity')?.value || 'none'
        };

        // Add MCP server data only for Tool Focused profiles
        if (profileType === 'tool_enabled' && mcpServer) {
            configData.server_name = mcpServer.name;
            configData.server_id = mcpServer.id;
            configData.mcp_server = {
                id: mcpServer.id,
                name: mcpServer.name,
                host: mcpServer.host,
                port: mcpServer.port,
                path: mcpServer.path
            };
        }


        const headers = { 'Content-Type': 'application/json' };
        
        // Add authentication token if available
        const authToken = localStorage.getItem('tda_auth_token');
        if (authToken) {
            headers['Authorization'] = `Bearer ${authToken}`;
        }
        
        // Authentication is handled via JWT tokens only
        
        const response = await fetch('/configure', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(configData)
        });

        const result = await response.json();

        if (result.status === 'success') {
            statusDiv.innerHTML = '<span class="text-green-400">✓ ' + escapeHtml(result.message) + '</span>';
            showNotification('success', result.message);
            
            // Don't override active profiles - they are already loaded from backend configuration
            // The active_for_consumption_profile_ids should persist from the saved config
            
            // Update status indicators
            DOM.mcpStatusDot.classList.remove('disconnected');
            DOM.mcpStatusDot.classList.add('connected');
            DOM.llmStatusDot.classList.remove('disconnected', 'busy');
            DOM.llmStatusDot.classList.add('idle');
            DOM.contextStatusDot.classList.remove('disconnected');
            DOM.contextStatusDot.classList.add('idle');
            
            // Update RAG indicator - check if RAG is active after configuration
            if (DOM.ragStatusDot) {
                const status = await API.checkServerStatus();
                if (status.rag_active) {
                    DOM.ragStatusDot.classList.remove('disconnected');
                    DOM.ragStatusDot.classList.add('connected');
                } else {
                    DOM.ragStatusDot.classList.remove('connected');
                    DOM.ragStatusDot.classList.add('disconnected');
                }
            }
            
            // Update state with current provider/model
            state.currentProvider = configData.provider;
            state.currentModel = configData.model;
            safeSetItem('lastSelectedProvider', configData.provider);
            
            // Update status bar with provider and model info
            UI.updateStatusPromptName(configData.provider, configData.model);
            
            // Enable panel toggle buttons after configuration
            if (DOM.toggleHistoryButton) {
                DOM.toggleHistoryButton.classList.remove('btn-disabled');
                DOM.toggleHistoryButton.style.opacity = '1';
                DOM.toggleHistoryButton.style.cursor = 'pointer';
                DOM.toggleHistoryButton.style.pointerEvents = 'auto';
                if (DOM.historyExpandIcon) DOM.historyExpandIcon.classList.remove('hidden');
                if (DOM.historyCollapseIcon) DOM.historyCollapseIcon.classList.add('hidden');
            }
            if (DOM.toggleStatusButton) {
                DOM.toggleStatusButton.classList.remove('btn-disabled');
                DOM.toggleStatusButton.style.opacity = '1';
                DOM.toggleStatusButton.style.cursor = 'pointer';
                DOM.toggleStatusButton.style.pointerEvents = 'auto';
                if (DOM.statusExpandIcon) DOM.statusExpandIcon.classList.remove('hidden');
                if (DOM.statusCollapseIcon) DOM.statusCollapseIcon.classList.add('hidden');
            }
            if (DOM.toggleHeaderButton) {
                DOM.toggleHeaderButton.classList.remove('btn-disabled');
                DOM.toggleHeaderButton.style.opacity = '1';
                DOM.toggleHeaderButton.style.cursor = 'pointer';
                DOM.toggleHeaderButton.style.pointerEvents = 'auto';
                if (DOM.headerExpandIcon) DOM.headerExpandIcon.classList.remove('hidden');
                if (DOM.headerCollapseIcon) DOM.headerCollapseIcon.classList.add('hidden');
            }
            
            // Show conversation header after successful configuration
            const conversationHeader = document.getElementById('conversation-header');
            if (conversationHeader) {
                conversationHeader.classList.remove('hidden');
            }
            
            // Show panel toggle buttons after configuration
            const topButtonsContainer = document.getElementById('top-buttons-container');
            if (topButtonsContainer) {
                topButtonsContainer.classList.remove('hidden');
            }

            // Load resources based on profile type
            // For Genie and RAG profiles, use profile-specific resource panel
            // For other profiles (tool_enabled, llm_only, conversation_with_tools), load generic MCP resources
            if (profileType === 'genie' || profileType === 'rag_focused') {
                // Load profile-specific resources for special profile types
                if (typeof window.updateResourcePanelForProfile === 'function') {
                    await window.updateResourcePanelForProfile(defaultProfile.id);
                    console.log('[Initialization] Loaded profile-specific resources for', profileType, 'profile:', defaultProfile.id);
                }
            } else {
                // Load generic MCP resources for standard profiles
                await Promise.all([
                    handleLoadResources('tools'),
                    handleLoadResources('prompts'),
                    handleLoadResources('resources')
                ]);
                console.log('[Initialization] Loaded generic MCP resources for', profileType, 'profile');
            }
            
            // Enable chat input
            DOM.chatModalButton.disabled = false;
            DOM.userInput.placeholder = "Ask about databases, tables, users...";
            UI.setExecutionState(false);
            
            // Load existing session or create new one, then switch to conversation view
            setTimeout(async () => {
                try {
                    const currentSessionId = state.currentSessionId;
                    const sessions = await API.loadAllSessions();
                    
                    // Filter out archived sessions from the conversation view selector
                    const activeSessions = sessions ? sessions.filter(s => !s.archived) : [];

                    // Sort sessions hierarchically so slave sessions appear under their parents
                    const sortedSessions = sortSessionsHierarchically(activeSessions);

                    // Populate session list UI
                    DOM.sessionList.innerHTML = '';

                    if (sortedSessions && Array.isArray(sortedSessions) && sortedSessions.length > 0) {
                        // Populate session list dropdown/sidebar
                        const sessionToLoad = sortedSessions.find(s => s.id === currentSessionId) ? currentSessionId : sortedSessions[0].id;

                        sortedSessions.forEach((session) => {
                            const isActive = session.id === sessionToLoad;
                            const sessionItem = UI.addSessionToList(session, isActive);
                            DOM.sessionList.appendChild(sessionItem);
                        });

                        // Update utility sessions filter visibility
                        if (window.updateUtilitySessionsFilter) {
                            window.updateUtilitySessionsFilter();
                        }

                        // Update genie master badges (adds collapse toggles to sessions with slaves)
                        updateGenieMasterBadges();

                        // Load the selected session
                        await handleLoadSession(sessionToLoad);
                    } else {
                        // No active sessions exist, create a new one
                        await handleStartNewSession();
                    }
                    
                    // Hide welcome screen and show chat interface
                    if (window.hideWelcomeScreen) {
                        window.hideWelcomeScreen();
                    }
                    
                    handleViewSwitch('conversation-view');
                    
                    // Mark initialization as complete for the conversation initializer
                    console.log('[reconnectAndLoad] Conversation fully initialized');
                    
                    // Mark configuration as clean after successful save & connect
                    import('../configDirtyState.js').then(({ markConfigClean }) => {
                        markConfigClean();
                        console.log('[reconnectAndLoad] Configuration marked as clean after successful save');
                    });
                    
                } catch (sessionError) {
                    console.error('Failed to load/create session:', sessionError);
                    showNotification('warning', 'Configuration successful, but failed to initialize session. Please create one manually.');
                    handleViewSwitch('conversation-view');
                    
                    // Still mark as clean since configuration was saved successfully
                    import('../configDirtyState.js').then(({ markConfigClean }) => {
                        markConfigClean();
                    });
                    // Show welcome screen since no session was created
                    if (window.showWelcomeScreen) {
                        await window.showWelcomeScreen();
                    }
                }
            }, 1000); // Small delay to allow user to see success message
        } else {
            statusDiv.innerHTML = '<span class="text-red-400">✗ ' + escapeHtml(result.message) + '</span>';
            showNotification('error', result.message);
        }
    } catch (error) {
        statusDiv.innerHTML = '<span class="text-red-400">✗ Connection failed</span>';
        showNotification('error', `Connection failed: ${error.message}`);
    } finally {
        btn.disabled = false;
        btnText.textContent = 'Save & Connect';
        spinner.classList.remove('animate-spin');
        spinner.classList.add('hidden');
    }
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize configuration tabs
 */
function initializeConfigTabs() {
    const tabs = document.querySelectorAll('.config-tab');
    const tabContents = document.querySelectorAll('.config-tab-content');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTabId = tab.getAttribute('data-tab');
            
            // Update tab buttons
            tabs.forEach(t => {
                t.classList.remove('active', 'border-[#F15F22]', 'text-white');
                t.classList.add('text-gray-400', 'border-transparent');
            });
            tab.classList.add('active', 'border-[#F15F22]', 'text-white');
            tab.classList.remove('text-gray-400', 'border-transparent');
            
            // Update tab content
            tabContents.forEach(content => {
                if (content.id === targetTabId) {
                    content.classList.remove('hidden');
                    content.classList.add('active');
                } else {
                    content.classList.add('hidden');
                    content.classList.remove('active');
                }
            });
        });
    });
}

// ============================================================================
// UI RENDERING - PROFILES
// ============================================================================

export function renderProfiles() {
    const conversationContainer = document.getElementById('conversation-profiles-container');
    const toolContainer = document.getElementById('tool-profiles-container');

    if (!conversationContainer || !toolContainer) return;

    console.log('[renderProfiles] Rendering', configState.profiles.length, 'profiles');

    // Update Test All Profiles button state
    const testAllProfilesBtn = document.getElementById('test-all-profiles-btn');
    if (testAllProfilesBtn) {
        if (configState.profiles.length === 0) {
            testAllProfilesBtn.disabled = true;
            testAllProfilesBtn.classList.add('opacity-50', 'cursor-not-allowed');
            testAllProfilesBtn.classList.remove('hover:bg-blue-700');
        } else {
            testAllProfilesBtn.disabled = false;
            testAllProfilesBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            testAllProfilesBtn.classList.add('hover:bg-blue-700');
        }
    }

    // Separate profiles by type
    const conversationProfiles = configState.profiles.filter(p => p.profile_type === 'llm_only');
    const ragFocusedProfiles = configState.profiles.filter(p => p.profile_type === 'rag_focused');
    const genieProfiles = configState.profiles.filter(p => p.profile_type === 'genie');
    const toolProfiles = configState.profiles.filter(p => !p.profile_type || p.profile_type === 'tool_enabled');

    // Render conversation profiles
    if (conversationProfiles.length === 0) {
        conversationContainer.innerHTML = `
            <div class="text-center text-gray-400 py-8">
                <p>No conversation profiles configured.</p>
            </div>
        `;
    } else {
        conversationContainer.innerHTML = conversationProfiles.map(profile => renderProfileCard(profile)).join('');
    }

    // Render RAG focused profiles
    const ragContainer = document.getElementById('rag-profiles-container');
    if (ragContainer) {
        if (ragFocusedProfiles.length === 0) {
            ragContainer.innerHTML = `
                <div class="text-center text-gray-400 py-8">
                    <p>No RAG focused profiles configured.</p>
                </div>
            `;
        } else {
            ragContainer.innerHTML = ragFocusedProfiles.map(profile => renderProfileCard(profile)).join('');
        }
    }

    // Render Genie profiles
    const genieContainer = document.getElementById('genie-profiles-container');
    if (genieContainer) {
        if (genieProfiles.length === 0) {
            genieContainer.innerHTML = `
                <div class="text-center text-gray-400 py-8">
                    <p>No Genie profiles configured.</p>
                    <p class="text-xs mt-2">Genie profiles coordinate multiple other profiles to answer complex questions.</p>
                </div>
            `;
        } else {
            genieContainer.innerHTML = genieProfiles.map(profile => renderProfileCard(profile)).join('');
        }
    }

    // Render tool-enabled profiles
    if (toolProfiles.length === 0) {
        toolContainer.innerHTML = `
            <div class="text-center text-gray-400 py-8">
                <p>No tool-enabled profiles configured.</p>
            </div>
        `;
    } else {
        toolContainer.innerHTML = toolProfiles.map(profile => renderProfileCard(profile)).join('');
    }

    // Setup tab switching
    setupProfileTypeTabs();

    // Attach event listeners to profile action buttons
    attachProfileEventListeners();
}

function renderProfileCard(profile) {
        const isDefault = profile.id === configState.defaultProfileId;

        // Check if this profile is the master for its specific MCP server
        const mcpServerId = profile.mcpServerId;
        const isMasterClassification = mcpServerId && configState.masterClassificationProfileIds[mcpServerId] === profile.id;

        const isActiveForConsumption = configState.activeForConsumptionProfileIds.includes(profile.id);
        const testStatus = configState.profileTestStatus[profile.id];
        const testsPassedForDefault = testStatus?.passed === true;

        return `
        <div class="bg-white/5 border ${isDefault ? 'border-[#F15F22]' : 'border-white/10'} rounded-lg p-4" data-profile-id="${profile.id}">
            <div class="flex items-start justify-between">
                <div class="flex items-start gap-3 flex-1">
                    <div class="flex flex-col items-center gap-2">
                        <button title="${isDefault ? 'Current Default Profile' : (testsPassedForDefault ? 'Set as Default' : 'Run tests before setting as default')}" 
                                data-action="set-default-profile" 
                                data-profile-id="${profile.id}" 
                                class="p-1 rounded-full ${isDefault ? 'text-yellow-400' : (testsPassedForDefault ? 'text-gray-500 hover:text-yellow-400' : 'text-gray-700 cursor-not-allowed opacity-40')}"
                                ${!isDefault && !testsPassedForDefault ? 'disabled' : ''}>
                            <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path d="M10 15l-5.878 3.09 1.123-6.545L.489 6.91l6.572-.955L10 0l2.939 5.955 6.572.955-4.756 4.635 1.123 6.545z"/></svg>
                        </button>
                        <div class="flex items-center" title="${(() => {
                            const testStatus = configState.profileTestStatus[profile.id];
                            if (isActiveForConsumption) return 'Active for Consumption';
                            if (!testStatus?.tested || !testStatus?.passed) return 'Test profile before activating';
                            return 'Activate for Consumption';
                        })()}">
                           <label class="relative inline-flex items-center ${(() => {
                               const testStatus = configState.profileTestStatus[profile.id];
                               if (isActiveForConsumption || (testStatus?.tested && testStatus?.passed)) return 'cursor-pointer';
                               return 'cursor-not-allowed opacity-50';
                           })()}">
                                <input type="checkbox" data-action="toggle-active-consumption" data-profile-id="${profile.id}" ${isActiveForConsumption ? 'checked' : ''} ${(() => {
                                    const testStatus = configState.profileTestStatus[profile.id];
                                    if (isActiveForConsumption) return '';
                                    if (!testStatus?.tested || !testStatus?.passed) return 'disabled';
                                    return '';
                                })()} class="sr-only peer" style="position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border-width: 0 !important;">
                                <div class="w-11 h-6 bg-gray-800/50 border border-gray-500 rounded-full peer peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-800 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-600 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-teradata-orange peer-disabled:opacity-50 peer-disabled:cursor-not-allowed"></div>
                            </label>
                        </div>
                    </div>
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <h4 class="font-semibold text-white">${escapeHtml(profile.name || profile.tag)}</h4>
                            <div class="flex items-center gap-1">
                                ${profile.color ? `
                                <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-semibold border"
                                      style="background: linear-gradient(135deg, ${profile.color}30, ${profile.color}15); border-color: ${profile.color}50; color: ${profile.color};">
                                    <span class="w-2 h-2 rounded-full" style="background: ${profile.color};"></span>
                                    @${escapeHtml(profile.tag)}
                                </span>
                                ` : `
                                <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-semibold bg-[#F15F22]/20 text-[#F15F22] border border-[#F15F22]/30">
                                    @${escapeHtml(profile.tag)}
                                </span>
                                `}
                                <button type="button" data-action="copy-profile-id" data-profile-id="${profile.id}"
                                    class="inline-flex items-center justify-center p-1 ml-1 text-gray-400 hover:text-[#F15F22] transition-colors rounded hover:bg-white/5 group relative"
                                    title="Copy Profile ID">
                                    <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                    </svg>
                                    <span class="text-xs font-semibold opacity-0 group-hover:opacity-100 transition-opacity absolute left-full ml-2 bg-gray-800 px-2 py-1 rounded whitespace-nowrap pointer-events-none">Copied!</span>
                                </button>
                            </div>
                        </div>
                        ${(() => {
                            // Status badges section - non-interactive indicators
                            const badges = [];

                            // Warning for RAG focused profiles without knowledge collections
                            const profileType = profile.profile_type || 'tool_enabled';
                            if (profileType === 'rag_focused') {
                                const knowledgeCollections = profile.knowledgeConfig?.collections || [];
                                if (knowledgeCollections.length === 0) {
                                    badges.push(`
                                    <span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold bg-yellow-500/20 text-yellow-300 border border-yellow-400/30 rounded-full" title="RAG focused profiles require at least 1 knowledge collection">
                                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                                        </svg>
                                        No Knowledge Collections
                                    </span>
                                    `);
                                }
                            }

                            // Master Classification status badge
                            if (isMasterClassification) {
                                badges.push(`
                                <span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-400/30 rounded-full" title="This is the primary classification profile - other profiles inherit classification from this one">
                                    <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                                        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/>
                                    </svg>
                                    Primary Classification
                                </span>
                                `);
                            }

                            // Inheritance status badge (only for tool-enabled profiles)
                            if (profile.profile_type === 'tool_enabled' && profile.inherit_classification && !isMasterClassification) {
                                // Get the per-server master for this profile's MCP server
                                const profileMcpServerId = profile.mcpServerId;
                                const masterProfileId = profileMcpServerId ? configState.masterClassificationProfileIds[profileMcpServerId] : null;
                                const masterProfile = masterProfileId ? configState.profiles.find(p => p.id === masterProfileId) : null;
                                const masterName = masterProfile ? escapeHtml(masterProfile.name) : 'master profile';
                                badges.push(`
                                <span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold bg-orange-500/20 text-orange-300 border border-orange-400/30 rounded-full" title="Inheriting classification from ${masterName}">
                                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                    </svg>
                                    Inherits from ${masterName}
                                </span>
                                `);
                            }

                            return badges.length > 0 ? `<div class="flex items-center gap-2 mb-2">${badges.join('')}</div>` : '';
                        })()}
                        <p class="text-sm text-gray-400 mb-3">${escapeHtml(profile.description)}</p>
                        <div class="text-sm text-gray-400 space-y-1">
                            <p><span class="font-medium">LLM:</span> ${(() => {
                                const llmConfig = configState.llmConfigurations.find(c => c.id === profile.llmConfigurationId);
                                if (llmConfig) {
                                    const providerDisplay = profile.providerName || llmConfig.provider;
                                    return `<span style="color: ${profile.color || '#9ca3af'};">${escapeHtml(providerDisplay)}</span> / ${escapeHtml(llmConfig.model)}`;
                                }
                                return 'N/A';
                            })()}</p>
                            ${profile.profile_type === 'tool_enabled' ? `
                            <p><span class="font-medium">MCP:</span> ${escapeHtml(configState.mcpServers.find(s => s.id === profile.mcpServerId)?.name || 'Unknown')}</p>
                            ` : ''}
                            ${profile.classification_mode && profile.profile_type === 'tool_enabled' ? `
                            <p><span class="font-medium">Classification:</span> ${(() => {
                                const mode = profile.classification_mode;
                                const badges = {
                                    'light': '<span class="inline-flex items-center px-1.5 py-0.5 text-xs font-medium bg-blue-500/20 text-blue-400 rounded">Light</span>',
                                    'full': '<span class="inline-flex items-center px-1.5 py-0.5 text-xs font-medium bg-purple-500/20 text-purple-400 rounded">Full</span>'
                                };
                                return badges[mode] || badges['light'];
                            })()}</p>
                            ` : ''}
                            ${profile.needs_reclassification && profile.profile_type === 'tool_enabled' ? `
                            <p><span class="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-yellow-500/20 text-yellow-400 rounded border border-yellow-500/30">
                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                                </svg>
                                Reclassification Recommended
                            </span></p>
                            ` : ''}
                            ${profile.profile_type === 'genie' ? `
                            <p><span class="font-medium">Child Profiles:</span> ${(() => {
                                const slaveProfiles = profile.genieConfig?.slaveProfiles || [];
                                if (slaveProfiles.length === 0) {
                                    return '<span class="text-yellow-400">None configured</span>';
                                }
                                const slaveNames = slaveProfiles.map(slaveId => {
                                    const slaveProfile = configState.profiles.find(p => p.id === slaveId);
                                    return slaveProfile ? `@${escapeHtml(slaveProfile.tag)}` : 'Unknown';
                                });
                                return `<span class="text-amber-300">${slaveNames.join(', ')}</span>`;
                            })()}</p>
                            ` : ''}
                        </div>
                        <div class="mt-2 text-xs" id="test-results-${profile.id}">${(() => {
                            const testStatus = configState.profileTestStatus[profile.id];
                            // If test results exist, show them
                            if (testStatus?.results) {
                                return testStatus.results;
                            }
                            // Otherwise show warning if not active and not tested/passed
                            if (!isActiveForConsumption && (!testStatus?.tested || !testStatus?.passed)) {
                                return '<span class="text-yellow-400">⚠ Run test before activating profile</span>';
                            }
                            return '';
                        })()}</div>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    <!-- Test Button (always visible for all profile types) -->
                    <button type="button" data-action="test-profile" data-profile-id="${profile.id}"
                        class="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors text-white flex items-center gap-2"
                        title="Test profile configuration">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                        Test
                    </button>

                    <!-- Classification Dropdown (only for tool-enabled profiles) -->
                    ${profile.profile_type === 'tool_enabled' ? `
                    <div class="relative inline-block">
                        <button type="button" data-action="toggle-classification-menu" data-profile-id="${profile.id}"
                            class="px-4 py-2 text-sm font-medium bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors text-white flex items-center gap-2"
                            title="Classification options">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/>
                            </svg>
                            Classification
                            <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
                            </svg>
                        </button>
                        <div class="classification-menu hidden absolute right-0 mt-2 w-64 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50" data-profile-id="${profile.id}">
                            <div class="py-1">
                                <!-- Set as Master Classification -->
                                <button type="button" data-action="set-master-classification" data-profile-id="${profile.id}"
                                    class="w-full text-left px-4 py-2.5 text-sm hover:bg-gray-700 flex items-center gap-3 ${isMasterClassification ? 'text-amber-300 bg-amber-500/10' : 'text-gray-300'} ${!profile.mcpServerId ? 'opacity-50 cursor-not-allowed' : ''}"
                                    title="${(() => {
                                        if (!profile.mcpServerId) return 'Profile must have an MCP server configured';
                                        if (isMasterClassification) return 'This is the primary classification profile';
                                        return 'Set as primary classification profile (other profiles inherit from this)';
                                    })()}"
                                    ${!profile.mcpServerId ? 'disabled' : ''}>
                                    <svg class="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                                        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/>
                                    </svg>
                                    <span class="flex-1">${isMasterClassification ? '⭐ Primary Classification' : 'Set as Primary'}</span>
                                </button>

                                <!-- Inherit Classification Toggle -->
                                <button type="button" data-action="inherit-classification" data-profile-id="${profile.id}"
                                    class="w-full text-left px-4 py-2.5 text-sm hover:bg-gray-700 flex items-center gap-3 ${profile.inherit_classification ? 'text-orange-300 bg-orange-500/10' : 'text-gray-300'} ${!isActiveForConsumption || isMasterClassification ? 'opacity-50 cursor-not-allowed' : ''}"
                                    title="${isMasterClassification ? 'Primary profile cannot inherit (it is the source)' : (!isActiveForConsumption ? 'Activate profile to enable inheritance' : (profile.inherit_classification ? 'Currently inheriting - click to disable' : 'Inherit from primary classification profile'))}"
                                    ${!isActiveForConsumption || isMasterClassification ? 'disabled' : ''}>
                                    <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
                                    </svg>
                                    <span class="flex-1">${profile.inherit_classification ? '✓ Inheriting' : 'Inherit Classification'}</span>
                                </button>

                                <div class="border-t border-gray-700 my-1"></div>

                                <!-- Reclassify Profile -->
                                <button type="button" data-action="reclassify-profile" data-profile-id="${profile.id}"
                                    class="w-full text-left px-4 py-2.5 text-sm text-gray-300 hover:bg-gray-700 flex items-center gap-3 ${!isActiveForConsumption || profile.inherit_classification ? 'opacity-50 cursor-not-allowed' : ''}"
                                    title="${profile.inherit_classification ? 'Disable inherit to reclassify' : (!isActiveForConsumption ? 'Activate profile to reclassify' : 'Re-run classification for this profile')}"
                                    ${!isActiveForConsumption || profile.inherit_classification ? 'disabled' : ''}>
                                    <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                                    </svg>
                                    <span class="flex-1">Reclassify</span>
                                </button>

                                <!-- Show Classification -->
                                <button type="button" data-action="show-classification" data-profile-id="${profile.id}"
                                    class="w-full text-left px-4 py-2.5 text-sm text-gray-300 hover:bg-gray-700 flex items-center gap-3 ${!isActiveForConsumption || !profile.classification_results || profile.inherit_classification ? 'opacity-50 cursor-not-allowed' : ''}"
                                    title="${profile.inherit_classification ? 'Disable inherit to view own classification' : (!isActiveForConsumption ? 'Activate profile to view' : (profile.classification_results ? 'View classification results' : 'No classification results'))}"
                                    ${!isActiveForConsumption || !profile.classification_results || profile.inherit_classification ? 'disabled' : ''}>
                                    <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
                                    </svg>
                                    <span class="flex-1">Show Results</span>
                                </button>
                            </div>
                        </div>
                    </div>
                    ` : ''}

                    <!-- Overflow Menu (Copy/Edit/Delete - consistent across all profile types) -->
                    <div class="relative inline-block">
                        <button type="button" data-action="toggle-profile-menu" data-profile-id="${profile.id}"
                            class="px-3 py-2 text-sm font-medium bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors text-white"
                            title="More options">
                            <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                                <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z"/>
                            </svg>
                        </button>
                        <div class="profile-menu hidden absolute right-0 mt-2 w-48 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50" data-profile-id="${profile.id}">
                            <div class="py-1">
                                <button type="button" data-action="copy-profile" data-profile-id="${profile.id}"
                                    class="w-full text-left px-4 py-2.5 text-sm text-gray-300 hover:bg-gray-700 flex items-center gap-3">
                                    <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                    </svg>
                                    <span class="flex-1">Copy Profile</span>
                                </button>
                                <button type="button" data-action="edit-profile" data-profile-id="${profile.id}"
                                    class="w-full text-left px-4 py-2.5 text-sm text-gray-300 hover:bg-gray-700 flex items-center gap-3">
                                    <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                                    </svg>
                                    <span class="flex-1">Edit Profile</span>
                                </button>
                                <div class="border-t border-gray-700 my-1"></div>
                                <button type="button" data-action="delete-profile" data-profile-id="${profile.id}"
                                    class="w-full text-left px-4 py-2.5 text-sm text-red-400 hover:bg-red-500/10 hover:text-red-300 flex items-center gap-3">
                                    <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                    </svg>
                                    <span class="flex-1">Delete Profile</span>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function setupProfileTypeTabs() {
    const tabs = document.querySelectorAll('.profile-type-tab');
    const contents = document.querySelectorAll('.profile-type-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;

            // Update tab styles
            tabs.forEach(t => {
                if (t === tab) {
                    t.classList.remove('text-gray-400', 'border-transparent', 'hover:border-white/20');
                    t.classList.add('text-white', 'border-[#F15F22]');
                } else {
                    t.classList.remove('text-white', 'border-[#F15F22]');
                    t.classList.add('text-gray-400', 'border-transparent', 'hover:border-white/20');
                }
            });

            // Show/hide content
            contents.forEach(content => {
                if (content.id === targetTab + '-container') {
                    content.classList.remove('hidden');
                } else {
                    content.classList.add('hidden');
                }
            });
        });
    });
}

function attachProfileEventListeners() {
    // Set Default Profile button
    document.querySelectorAll('[data-action="set-default-profile"]').forEach(btn => {
        btn.replaceWith(btn.cloneNode(true)); // Remove old listeners
    });
    document.querySelectorAll('[data-action="set-default-profile"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const button = e.currentTarget;
            const profileId = button.dataset.profileId;
            const profile = configState.profiles.find(p => p.id === profileId);
            
            if (!profile) {
                showNotification('error', 'Profile not found');
                return;
            }
            
            // If already default, no need to do anything
            const isAlreadyDefault = profileId === configState.defaultProfileId;
            if (isAlreadyDefault) {
                return;
            }
            
            // Validation: Check if profile tests have passed (only for non-default profiles)
            const testStatus = configState.profileTestStatus[profileId];
            if (!testStatus || !testStatus.passed) {
                showNotification('error', 'Profile must pass all tests before it can be set as default. Please run tests first.');
                return;
            }
            
            try {
                // Disable button during processing
                button.disabled = true;
                const originalHTML = button.innerHTML;
                button.innerHTML = '<svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';
                
                // Step 1: If profile is also the master classification profile for its MCP server AND has inherit_classification enabled, disable it
                // (Master classification profile cannot inherit - circular dependency)
                const mcpServerId = profile.mcpServerId;
                const isMasterClassification = mcpServerId && configState.masterClassificationProfileIds[mcpServerId] === profileId;
                if (isMasterClassification && profile.inherit_classification) {
                    showNotification('info', 'Disabling classification inheritance (primary classification profile cannot inherit from itself)...');
                    await configState.updateProfile(profileId, {
                        inherit_classification: false
                    });
                    await configState.loadProfiles();
                }
                // Note: If profile is NOT the master, it can remain with inherit_classification enabled
                // and will inherit from the master classification profile
                
                // Step 2: Set as default
                await configState.setDefaultProfile(profileId);
                
                // Step 3: Auto-activate the default profile if it's not already active
                if (!configState.activeForConsumptionProfileIds.includes(profileId)) {
                    const activeIds = [...configState.activeForConsumptionProfileIds, profileId];
                    await configState.setActiveForConsumptionProfiles(activeIds);
                }
                
                // Step 4: Check if classification exists
                const updatedProfile = configState.profiles.find(p => p.id === profileId);
                const classificationResults = updatedProfile?.classification_results || {};
                const toolsDict = classificationResults.tools || {};
                const promptsDict = classificationResults.prompts || {};
                const totalTools = Object.values(toolsDict).reduce((sum, tools) => sum + tools.length, 0);
                const totalPrompts = Object.values(promptsDict).reduce((sum, prompts) => sum + prompts.length, 0);
                const hasClassification = totalTools > 0 || totalPrompts > 0;
                
                // Step 5: If no classification exists, trigger automatic reclassification
                if (!hasClassification) {
                    showNotification('info', `Running classification for default profile "${profile.name}"...`);
                    
                    const headers = { 'Content-Type': 'application/json' };
                    const authToken = localStorage.getItem('tda_auth_token');
                    if (authToken) {
                        headers['Authorization'] = `Bearer ${authToken}`;
                    }
                    
                    const response = await fetch(`/api/v1/profiles/${profileId}/reclassify`, {
                        method: 'POST',
                        headers: headers,
                        credentials: 'include'
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok && result.status === 'success') {
                        showNotification('success', `Default profile "${profile.name}" classified successfully`);
                    } else {
                        showNotification('warning', `Default profile set, but classification failed: ${result.message || 'Unknown error'}`);
                    }
                } else {
                    showNotification('success', `Default profile changed to "${profile.name}"`);
                }
                
                // Step 6: Reload and re-render
                await configState.loadProfiles();
                renderProfiles();
                renderLLMProviders(); // Re-render to update default/active badges
                renderMCPServers(); // Re-render to update default/active badges
                updateReconnectButton(); // Update Reconnect & Load button state
                
                // Restore button
                button.disabled = false;
                button.innerHTML = originalHTML;
                
            } catch (error) {
                console.error('Set default profile error:', error);
                showNotification('error', `Failed to set default profile: ${error.message}`);
                
                // Restore button
                button.disabled = false;
                const originalHTML = '★';
                button.innerHTML = originalHTML;
            }
        });
    });

    // Toggle Active for Consumption checkbox
    document.querySelectorAll('[data-action="toggle-active-consumption"]').forEach(checkbox => {
        checkbox.addEventListener('change', async (e) => {
            const profileId = e.target.dataset.profileId;
            const isChecked = e.target.checked;
            
            // Prevent deactivating the default profile
            if (!isChecked && profileId === configState.defaultProfileId) {
                e.target.checked = true; // Revert the checkbox
                showNotification('error', 'Cannot deactivate the default profile. Set a different profile as default first.');
                return;
            }
            
            let activeIds = configState.activeForConsumptionProfileIds;

            if (isChecked) {
                // Check if profile has been tested successfully
                const testStatus = configState.profileTestStatus[profileId];
                if (!testStatus?.tested || !testStatus?.passed) {
                    e.target.checked = false; // Revert the checkbox
                    showNotification('error', 'Please run and pass the test before activating this profile.');
                    return;
                }
                // Get profile to check type
                const profile = configState.profiles.find(p => p.id === profileId);
                // Check if profile doesn't need MCP classification (llm_only, rag_focused, genie)
                const skipMcpClassification = profile && ['llm_only', 'rag_focused', 'genie'].includes(profile.profile_type);

                // Test the profile first before any other checks
                const resultsContainer = document.getElementById(`test-results-${profileId}`);
                if (resultsContainer) {
                    // Show different message based on profile type
                    const testingMessage = skipMcpClassification
                        ? 'Testing profile...'
                        : 'Testing and classifying profile...';

                    resultsContainer.innerHTML = `
                        <div class="flex items-center gap-2">
                            <svg class="animate-spin h-4 w-4 text-yellow-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            <span class="text-yellow-400">${testingMessage}</span>
                        </div>
                    `;
                }
                
                try {
                    const result = await API.testProfile(profileId);
                    const allSuccessful = Object.values(result.results).every(r => r.status === 'success' || r.status === 'info');
                    
                    let testResultsHTML = '';
                    for (const [key, value] of Object.entries(result.results)) {
                        let statusClass;
                        if (value.status === 'success') {
                            statusClass = 'text-green-400';
                        } else if (value.status === 'info') {
                            statusClass = 'text-blue-400';
                        } else if (value.status === 'warning') {
                            statusClass = 'text-yellow-400';
                        } else {
                            statusClass = 'text-red-400';
                        }
                        testResultsHTML += `<p class="${statusClass}">${value.message}</p>`;
                    }
                    
                    if (!allSuccessful) {
                        // Tests failed - revert checkbox and show results
                        e.target.checked = false;
                        if (resultsContainer) {
                            resultsContainer.innerHTML = testResultsHTML;
                        }
                        showNotification('error', 'Profile tests failed. Cannot activate profile.');
                        return;
                    }
                    
                    // Tests passed - activate the profile
                    if (!activeIds.includes(profileId)) {
                        activeIds.push(profileId);
                    }
                    await configState.setActiveForConsumptionProfiles(activeIds);

                    // If no default profile exists, set this profile as default
                    const wasSetAsDefault = !configState.defaultProfileId;
                    if (wasSetAsDefault) {
                        await configState.setDefaultProfile(profileId);
                    }

                    // Get the profile to check if it's tool-enabled
                    const profile = configState.profiles.find(p => p.id === profileId);
                    const isToolEnabled = profile && profile.profile_type === 'tool_enabled';

                    // If tool-enabled and no master classification profile exists for this MCP server, set as master
                    let wasSetAsMaster = false;
                    const profileMcpServerId = profile.mcpServerId;
                    const hasServerMaster = profileMcpServerId && configState.masterClassificationProfileIds[profileMcpServerId];

                    if (isToolEnabled && profileMcpServerId && !hasServerMaster) {
                        try {
                            await API.setMasterClassificationProfile(profileId);
                            // Update per-server master
                            configState.masterClassificationProfileIds[profileMcpServerId] = profileId;
                            // Also update legacy single master for backwards compatibility
                            configState.masterClassificationProfileId = profileId;
                            wasSetAsMaster = true;
                            showNotification('info', `Profile "${profile.name}" set as primary classification profile for this MCP server.`);
                        } catch (masterError) {
                            console.error('Failed to set master classification profile:', masterError);
                        }
                    }

                    // Update the profile object's active_for_consumption property
                    const profileIndex = configState.profiles.findIndex(p => p.id === profileId);
                    if (profileIndex !== -1) {
                        configState.profiles[profileIndex].active_for_consumption = true;
                    }

                    await configState.loadProfiles(); // Reload to sync state

                    // If profile became master classification profile, trigger auto-classification
                    let classificationTriggered = false;
                    if (wasSetAsMaster) {
                        showNotification('info', `Running auto-classification for master profile "${profile.name}"...`);

                        // Disable Save & Connect button during classification
                        const reconnectBtn = document.getElementById('reconnect-and-load-btn');
                        const reconnectBtnText = document.getElementById('reconnect-button-text');
                        const originalBtnText = reconnectBtnText ? reconnectBtnText.textContent : 'Save & Connect';
                        if (reconnectBtn) {
                            reconnectBtn.disabled = true;
                            reconnectBtn.classList.add('opacity-50', 'cursor-not-allowed');
                            if (reconnectBtnText) {
                                reconnectBtnText.textContent = 'Classifying...';
                            }
                        }

                        try {
                            const headers = { 'Content-Type': 'application/json' };
                            const authToken = localStorage.getItem('tda_auth_token');
                            if (authToken) {
                                headers['Authorization'] = `Bearer ${authToken}`;
                            }

                            const classifyResponse = await fetch(`/api/v1/profiles/${profileId}/reclassify`, {
                                method: 'POST',
                                headers: headers,
                                credentials: 'include'
                            });

                            const classifyResult = await classifyResponse.json();

                            if (classifyResponse.ok && classifyResult.status === 'success') {
                                showNotification('success', `Master profile "${profile.name}" classified successfully.`);
                                classificationTriggered = true;
                            } else {
                                showNotification('warning', `Master profile set, but classification failed: ${classifyResult.message || 'Unknown error'}`);
                            }
                        } catch (classifyError) {
                            console.error('Auto-classification error:', classifyError);
                            showNotification('warning', `Master profile set, but auto-classification failed: ${classifyError.message}`);
                        } finally {
                            // Restore Save & Connect button text and update state
                            if (reconnectBtnText) {
                                reconnectBtnText.textContent = originalBtnText;
                            }
                            updateReconnectButton(); // Let the function determine proper state
                        }

                        // Reload profiles to get updated classification results
                        await configState.loadProfiles();
                    }

                    renderProfiles(); // Re-render with updated state (reclassify button will be enabled)
                    renderLLMProviders(); // Re-render to update default/active badges
                    renderMCPServers(); // Re-render to update default/active badges
                    updateReconnectButton(); // Update Save & Connect button state

                    // Update status indicators after activation
                    DOM.mcpStatusDot.classList.remove('disconnected');
                    DOM.mcpStatusDot.classList.add('connected');
                    DOM.llmStatusDot.classList.remove('disconnected', 'busy');
                    DOM.llmStatusDot.classList.add('idle');

                    // Update RAG indicator
                    if (DOM.ragStatusDot) {
                        const status = await API.checkServerStatus();
                        if (status.rag_active) {
                            DOM.ragStatusDot.classList.remove('disconnected');
                            DOM.ragStatusDot.classList.add('connected');
                        } else {
                            DOM.ragStatusDot.classList.remove('connected');
                            DOM.ragStatusDot.classList.add('disconnected');
                        }
                    }

                    // Build notification message based on what happened
                    let message;
                    if (wasSetAsDefault && wasSetAsMaster && classificationTriggered) {
                        message = `Profile "${profile ? profile.name : 'Profile'}" activated, set as default and primary classification profile, and classified successfully.`;
                    } else if (wasSetAsDefault && wasSetAsMaster) {
                        message = `Profile "${profile ? profile.name : 'Profile'}" activated and set as default and primary classification profile.`;
                    } else if (wasSetAsDefault) {
                        message = `Profile "${profile ? profile.name : 'Profile'}" activated and set as default. Click "Reclassify" to classify tools and prompts.`;
                    } else {
                        message = `Profile "${profile ? profile.name : 'Profile'}" activated successfully. Click "Reclassify" to classify tools and prompts.`;
                    }
                    showNotification('success', message);
                    
                    // Re-apply test results after render
                    const newResultsContainer = document.getElementById(`test-results-${profileId}`);
                    if (newResultsContainer) {
                        newResultsContainer.innerHTML = testResultsHTML;
                    }
                } catch (error) {
                    // Test error - revert checkbox
                    e.target.checked = false;
                    if (resultsContainer) {
                        resultsContainer.innerHTML = `<span class="text-red-400">Test failed: ${error.message}</span>`;
                    }
                    showNotification('error', `Failed to test profile: ${error.message}`);
                }
            } else {
                // Deactivating - no test needed
                activeIds = activeIds.filter(id => id !== profileId);
                await configState.setActiveForConsumptionProfiles(activeIds);
                await configState.loadProfiles(); // Reload to update active_for_consumption flags
                renderProfiles(); // Re-render with updated state (reclassify button will be disabled)
                renderLLMProviders(); // Re-render to update default/active badges
                renderMCPServers(); // Re-render to update default/active badges
                showNotification('success', 'Profile deactivated successfully');
            }
        });
    });
    
    // Test Profile button
    document.querySelectorAll('[data-action="test-profile"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const button = e.currentTarget;
            const profileId = button.dataset.profileId;
            const resultsContainer = document.getElementById(`test-results-${profileId}`);
            if (!resultsContainer) {
                console.error(`Test results container not found for profile ${profileId}`);
                return;
            }
            resultsContainer.innerHTML = `<span class="text-yellow-400">Testing...</span>`;
            try {
                const result = await API.testProfile(profileId);
                let html = '';
                const all_successful = Object.values(result.results).every(r => r.status === 'success' || r.status === 'info');

                for (const [key, value] of Object.entries(result.results)) {
                    let statusClass;
                    if (value.status === 'success') {
                        statusClass = 'text-green-400';
                    } else if (value.status === 'info') {
                        statusClass = 'text-blue-400';
                    } else if (value.status === 'warning') {
                        statusClass = 'text-yellow-400';
                    } else {
                        statusClass = 'text-red-400';
                    }
                    html += `<p class="${statusClass}">${value.message}</p>`;
                }
                resultsContainer.innerHTML = html;

                // Update test status
                configState.profileTestStatus[profileId] = {
                    tested: true,
                    passed: all_successful,
                    timestamp: Date.now(),
                    results: html  // Store the formatted results
                };
                
                // Re-render profiles to update activation toggle state and star button
                renderProfiles();
                
                // Restore test results after re-render
                const newResultsContainer = document.getElementById(`test-results-${profileId}`);
                if (newResultsContainer) {
                    newResultsContainer.innerHTML = html;
                }
                
                if (all_successful) {
                    showNotification('success', 'Profile test passed! You can now set it as default or activate it.');
                } else {
                    showNotification('error', 'Profile test failed. Please fix the issues before activating.');
                }

                // Just display results - don't auto-activate the profile
                // User can manually activate via the toggle switch if tests pass

            } catch (error) {
                resultsContainer.innerHTML = `<span class="text-red-400">${error.message}</span>`;
                // Also uncheck on API error
                let activeIds = configState.activeForConsumptionProfileIds.filter(id => id !== profileId);
                await configState.setActiveForConsumptionProfiles(activeIds);
                const checkbox = document.querySelector(`input[data-action="toggle-active-consumption"][data-profile-id="${profileId}"]`);
                if (checkbox) {
                    checkbox.checked = false;
                }
            }
        });
    });

    // Edit Profile button
    document.querySelectorAll('[data-action="edit-profile"]').forEach(btn => {
        btn.replaceWith(btn.cloneNode(true)); // Remove old listeners
    });
    document.querySelectorAll('[data-action="edit-profile"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const profileId = e.currentTarget.dataset.profileId;
            showProfileModal(profileId);
        });
    });

    // Copy Profile button
    document.querySelectorAll('[data-action="copy-profile"]').forEach(btn => {
        btn.replaceWith(btn.cloneNode(true)); // Remove old listeners
    });
    document.querySelectorAll('[data-action="copy-profile"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const profileId = e.currentTarget.dataset.profileId;
            const profile = configState.profiles.find(p => p.id === profileId);
            const profileName = profile ? profile.name : 'this profile';
            
            const copiedProfile = await configState.copyProfile(profileId);
            if (copiedProfile) {
                renderProfiles();
                renderLLMProviders(); // Re-render to update default/active badges
                renderMCPServers(); // Re-render to update default/active badges
                showNotification('success', `Profile "${profileName}" copied successfully. Please edit to set a unique tag.`);
            } else {
                showNotification('error', 'Failed to copy profile');
            }
        });
    });

    // Delete Profile button
    document.querySelectorAll('[data-action="delete-profile"]').forEach(btn => {
        btn.replaceWith(btn.cloneNode(true)); // Remove old listeners
    });
    document.querySelectorAll('[data-action="delete-profile"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const profileId = e.currentTarget.dataset.profileId;
            const profile = configState.profiles.find(p => p.id === profileId);
            const profileName = profile ? profile.name : 'this profile';
            
            // Only allow deleting the default profile if it's the last profile
            const isDefault = profileId === configState.defaultProfileId;
            const isLastProfile = configState.profiles.length === 1;
            
            if (isDefault && !isLastProfile) {
                showNotification('error', 'Cannot delete the default profile while other profiles exist. Please change the default profile first.');
                return;
            }
            
            showDeleteConfirmation(`Are you sure you want to delete profile "${profileName}"?`, async () => {
                await configState.removeProfile(profileId);
                renderProfiles();
                renderLLMProviders(); // Re-render to update default/active badges
                renderMCPServers(); // Re-render to update default/active badges
                showNotification('success', 'Profile deleted successfully');
            });
        });
    });
    
    // Reclassify Profile button
    document.querySelectorAll('[data-action="inherit-classification"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const button = e.currentTarget;
            const profileId = button.dataset.profileId;
            const profile = configState.profiles.find(p => p.id === profileId);

            if (button.disabled) {
                return;
            }

            // Prevent master classification profile from inheriting
            const mcpServerId = profile.mcpServerId;
            const isMasterForThisServer = mcpServerId && configState.masterClassificationProfileIds[mcpServerId] === profileId;

            if (isMasterForThisServer) {
                showNotification('error', 'Primary classification profile cannot inherit classification (it is the source for other profiles)');
                return;
            }

            // Toggle the inherit_classification flag
            const newInheritState = !profile.inherit_classification;

            try {
                // Update the profile with the new inherit_classification state
                await configState.updateProfile(profileId, {
                    inherit_classification: newInheritState
                });

                // Reload profiles to get updated state
                await configState.loadProfiles();
                renderProfiles();

                // Get the per-server master profile name
                const masterProfileId = mcpServerId ? configState.masterClassificationProfileIds[mcpServerId] : null;
                const masterProfile = masterProfileId ? configState.profiles.find(p => p.id === masterProfileId) : null;
                const masterProfileName = masterProfile ? masterProfile.name : 'primary classification profile';

                const message = newInheritState
                    ? `Profile "${profile.name}" will now inherit classification from ${masterProfileName}`
                    : `Profile "${profile.name}" will use its own classification`;
                showNotification('success', message);
            } catch (error) {
                console.error('Inherit classification toggle error:', error);
                showNotification('error', 'Failed to update classification inheritance');
            }
        });
    });

    // Set Master Classification Profile button
    document.querySelectorAll('[data-action="set-master-classification"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const button = e.currentTarget;
            const profileId = button.dataset.profileId;
            const profile = configState.profiles.find(p => p.id === profileId);

            if (button.disabled) {
                return;
            }

            // Check if this profile is already the master for its MCP server
            const mcpServerId = profile.mcpServerId;
            if (mcpServerId && configState.masterClassificationProfileIds[mcpServerId] === profileId) {
                showNotification('info', `Profile "${profile.name}" is already the primary classification profile for this MCP server`);
                return;
            }

            // Disable Save & Connect button during the process
            const reconnectBtn = document.getElementById('reconnect-and-load-btn');
            const reconnectBtnText = document.getElementById('reconnect-button-text');
            const originalReconnectText = reconnectBtnText ? reconnectBtnText.textContent : 'Save & Connect';
            if (reconnectBtn) {
                reconnectBtn.disabled = true;
                reconnectBtn.classList.add('opacity-50', 'cursor-not-allowed');
                if (reconnectBtnText) {
                    reconnectBtnText.textContent = 'Setting Master...';
                }
            }

            try {
                // Disable button and show loading state
                button.disabled = true;
                const originalText = button.textContent;
                button.textContent = 'Setting...';

                // Call API to set master classification profile
                await API.setMasterClassificationProfile(profileId);

                // Update per-server master in configState
                if (mcpServerId) {
                    configState.masterClassificationProfileIds[mcpServerId] = profileId;
                }
                // Also update legacy single master for backwards compatibility
                configState.masterClassificationProfileId = profileId;

                showNotification('success', `Profile "${profile.name}" is now the primary classification profile for this MCP server`);

                // Trigger auto-classification for the new master profile
                showNotification('info', `Running auto-classification for master profile "${profile.name}"...`);

                if (reconnectBtn && reconnectBtnText) {
                    reconnectBtnText.textContent = 'Classifying...';
                }

                try {
                    const headers = { 'Content-Type': 'application/json' };
                    const authToken = localStorage.getItem('tda_auth_token');
                    if (authToken) {
                        headers['Authorization'] = `Bearer ${authToken}`;
                    }

                    const classifyResponse = await fetch(`/api/v1/profiles/${profileId}/reclassify`, {
                        method: 'POST',
                        headers: headers,
                        credentials: 'include'
                    });

                    const classifyResult = await classifyResponse.json();

                    if (classifyResponse.ok && classifyResult.status === 'success') {
                        showNotification('success', `Master profile "${profile.name}" classified successfully.`);
                    } else {
                        showNotification('warning', `Master profile set, but classification failed: ${classifyResult.message || 'Unknown error'}`);
                    }
                } catch (classifyError) {
                    console.error('Auto-classification error:', classifyError);
                    showNotification('warning', `Master profile set, but auto-classification failed: ${classifyError.message}`);
                }

                // Reload profiles to get updated state
                await configState.loadProfiles();
                renderProfiles();

                // Restore button state
                button.disabled = false;
                button.textContent = originalText;
            } catch (error) {
                console.error('Set master classification profile error:', error);
                showNotification('error', `Failed to set primary classification profile: ${error.message}`);

                // Restore button state
                button.disabled = false;
                button.textContent = 'Set as Master Classification';
            } finally {
                // Restore Save & Connect button text and update state
                if (reconnectBtnText) {
                    reconnectBtnText.textContent = originalReconnectText;
                }
                updateReconnectButton(); // Let the function determine proper state
            }
        });
    });

    document.querySelectorAll('[data-action="reclassify-profile"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const button = e.currentTarget;
            const profileId = button.dataset.profileId;
            const profile = configState.profiles.find(p => p.id === profileId);
            const profileName = profile ? profile.name : 'this profile';
            
            // Button should be disabled if profile is not active (handled in rendering)
            if (button.disabled) {
                return;
            }
            
            try {
                // Disable button and show loading state
                button.disabled = true;
                button.textContent = 'Reclassifying...';
                
                // Show classification progress in the test results area
                const resultsContainer = document.getElementById(`test-results-${profileId}`);
                if (resultsContainer) {
                    resultsContainer.innerHTML = `
                        <div class="flex items-center gap-2">
                            <svg class="animate-spin h-4 w-4 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            <span class="text-purple-400">Reclassifying profile...</span>
                        </div>
                    `;
                }
                
                showNotification('info', `Reclassifying "${profileName}"... This will clear cached results and reclassify all resources.`);
                
                const headers = { 'Content-Type': 'application/json' };
                const authToken = localStorage.getItem('tda_auth_token');
                if (authToken) {
                    headers['Authorization'] = `Bearer ${authToken}`;
                }
                
                const response = await fetch(`/api/v1/profiles/${profileId}/reclassify`, {
                    method: 'POST',
                    headers: headers,
                    credentials: 'include'  // Include session cookies for authentication
                });
                
                const result = await response.json();
                
                if (response.ok && result.status === 'success') {
                    showNotification('success', result.message || 'Profile reclassified successfully');
                    
                    // Show success in test results area
                    const resultsContainer = document.getElementById(`test-results-${profileId}`);
                    if (resultsContainer) {
                        resultsContainer.innerHTML = `<p class="text-green-400">✓ Reclassification completed successfully</p>`;
                    }
                    
                    // Refresh profile list to update needs_reclassification flag
                    await configState.loadProfiles();
                    renderProfiles();
                } else {
                    showNotification('error', result.message || 'Failed to reclassify profile');
                    
                    // Show error in test results area
                    const resultsContainer = document.getElementById(`test-results-${profileId}`);
                    if (resultsContainer) {
                        resultsContainer.innerHTML = `<p class="text-red-400">✗ Reclassification failed</p>`;
                    }
                }
            } catch (error) {
                console.error('Reclassify error:', error);
                showNotification('error', 'Failed to reclassify profile');
                
                // Show error in test results area
                const resultsContainer = document.getElementById(`test-results-${profileId}`);
                if (resultsContainer) {
                    resultsContainer.innerHTML = `<p class="text-red-400">✗ Reclassification failed: ${error.message}</p>`;
                }
            } finally {
                // Re-enable button
                button.disabled = false;
                button.textContent = 'Reclassify';
            }
        });
    });

    document.querySelectorAll('[data-action="show-classification"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const profileId = e.currentTarget.dataset.profileId;
            const profile = configState.profiles.find(p => p.id === profileId);
            
            if (!profile) {
                showNotification('error', 'Profile not found');
                return;
            }
            
            try {
                // Fetch fresh classification results from API (with authentication)
                const result = await API.getProfileClassification(profileId);
                
                if (result.status === 'success') {
                    // Update profile with fresh classification results
                    const profileWithResults = {
                        ...profile,
                        classification_results: result.classification_results,
                        classification_mode: result.classification_mode
                    };
                    showClassificationModal(profileWithResults);
                } else {
                    showNotification('error', result.message || 'Failed to load classification results');
                }
            } catch (error) {
                console.error('Show classification error:', error);
                showNotification('error', 'Failed to load classification results');
            }
        });
    });

    // Copy Profile ID button
    document.querySelectorAll('[data-action="copy-profile-id"]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();

            const button = e.target.closest('[data-action="copy-profile-id"]');
            const profileId = button.dataset.profileId;
            const profile = configState.profiles.find(p => p.id === profileId);

            try {
                await navigator.clipboard.writeText(profileId);

                // Show visual feedback - find the tooltip span
                const tooltipSpan = button.querySelector('span');
                if (tooltipSpan) {
                    tooltipSpan.style.opacity = '1';
                    setTimeout(() => {
                        tooltipSpan.style.opacity = '0';
                    }, 1500);
                }

                // Show notification
                showNotification('success', `Profile ID copied: ${profileId}`);
            } catch (err) {
                console.error('Failed to copy profile ID:', err);
                showNotification('error', 'Failed to copy profile ID to clipboard');
            }
        });
    });

    // Toggle Classification Dropdown Menu
    document.querySelectorAll('[data-action="toggle-classification-menu"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const profileId = btn.dataset.profileId;
            const menu = document.querySelector(`.classification-menu[data-profile-id="${profileId}"]`);

            if (menu) {
                // Close all other menus first
                document.querySelectorAll('.classification-menu, .profile-menu').forEach(m => {
                    if (m !== menu) m.classList.add('hidden');
                });

                // Toggle this menu
                menu.classList.toggle('hidden');
            }
        });
    });

    // Toggle Profile Overflow Menu
    document.querySelectorAll('[data-action="toggle-profile-menu"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const profileId = btn.dataset.profileId;
            const menu = document.querySelector(`.profile-menu[data-profile-id="${profileId}"]`);

            if (menu) {
                // Close all other menus first
                document.querySelectorAll('.classification-menu, .profile-menu').forEach(m => {
                    if (m !== menu) m.classList.add('hidden');
                });

                // Toggle this menu
                menu.classList.toggle('hidden');
            }
        });
    });

    // Close dropdown menus when clicking menu items (they will trigger their own actions)
    document.querySelectorAll('.classification-menu button, .profile-menu button').forEach(menuItem => {
        menuItem.addEventListener('click', (e) => {
            // Find parent menu and close it
            const menu = e.target.closest('.classification-menu, .profile-menu');
            if (menu) {
                menu.classList.add('hidden');
            }
        });
    });

    // Click outside to close menus
    document.addEventListener('click', (e) => {
        // If click is not on a dropdown button or menu, close all menus
        if (!e.target.closest('[data-action="toggle-classification-menu"]') &&
            !e.target.closest('[data-action="toggle-profile-menu"]') &&
            !e.target.closest('.classification-menu') &&
            !e.target.closest('.profile-menu')) {
            document.querySelectorAll('.classification-menu, .profile-menu').forEach(menu => {
                menu.classList.add('hidden');
            });
        }
    });
}

function showClassificationModal(profile) {
    const modal = document.getElementById('classification-modal');
    if (!modal) return;

    const title = modal.querySelector('#classification-modal-title');
    const subtitle = modal.querySelector('#classification-modal-subtitle');
    const content = modal.querySelector('#classification-modal-content');
    
    // Set title and subtitle
    title.textContent = `Classification Results - ${profile.name || profile.tag}`;
    subtitle.textContent = `Mode: ${profile.classification_mode || 'light'} | Profile: @${profile.tag}`;
    
    // Get classification results
    const results = profile.classification_results;
    if (!results) {
        content.innerHTML = '<p class="text-gray-400">No classification results available.</p>';
        modal.classList.remove('hidden');
        return;
    }
    
    // Helper function to check if a tool/prompt is active in the profile
    const isActive = (name, type) => {
        const list = type === 'tool' ? profile.tools : profile.prompts;
        if (!list || list.length === 0) return false;
        if (list.includes('*')) return true;
        return list.includes(name);
    };
    
    // Build HTML for tools and prompts
    let html = '';
    
    // Tools section
    if (results.tools && Object.keys(results.tools).length > 0) {
        const totalTools = Object.values(results.tools).reduce((sum, arr) => sum + (Array.isArray(arr) ? arr.length : 0), 0);
        html += `
            <div class="space-y-4">
                <div class="flex items-center justify-between">
                    <h4 class="text-base font-semibold text-white">Tools</h4>
                    <span class="text-sm text-gray-400">${Object.keys(results.tools).length} categories • ${totalTools} total tools</span>
                </div>
                <div class="space-y-3">
        `;
        
        for (const [category, tools] of Object.entries(results.tools).sort()) {
            const toolList = Array.isArray(tools) ? tools : [];
            const categoryColor = getCategoryColor(category);
            const activeCount = toolList.filter(t => {
                const name = typeof t === 'string' ? t : (t.name || '');
                return isActive(name, 'tool');
            }).length;
            
            html += `
                <div class="bg-gray-800/30 border border-gray-700/50 rounded-lg p-4">
                    <div class="flex items-center justify-between mb-3">
                        <h5 class="text-sm font-medium" style="color: ${categoryColor};">
                            <span class="inline-block w-2 h-2 rounded-full mr-2" style="background: ${categoryColor};"></span>
                            ${escapeHtml(category)}
                        </h5>
                        <span class="text-xs text-gray-400">${activeCount}/${toolList.length} active</span>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
            `;
            
            toolList.forEach(tool => {
                const toolName = typeof tool === 'string' ? tool : (tool.name || 'Unknown');
                const active = isActive(toolName, 'tool');
                html += `
                    <div class="text-sm font-mono px-3 py-1.5 rounded border ${active ? 'text-gray-300 bg-gray-900/30 border-gray-700/30' : 'text-gray-500 bg-gray-900/10 border-gray-700/20 opacity-50 line-through'}">
                        ${escapeHtml(toolName)}
                        ${!active ? '<span class="text-xs text-red-400 ml-2">(deactivated)</span>' : ''}
                    </div>
                `;
            });
            
            html += `
                    </div>
                </div>
            `;
        }
        
        html += `
                </div>
            </div>
        `;
    }
    
    // Prompts section
    if (results.prompts && Object.keys(results.prompts).length > 0) {
        const totalPrompts = Object.values(results.prompts).reduce((sum, arr) => sum + (Array.isArray(arr) ? arr.length : 0), 0);
        html += `
            <div class="space-y-4 border-t border-gray-700/50 pt-6">
                <div class="flex items-center justify-between">
                    <h4 class="text-base font-semibold text-white">Prompts</h4>
                    <span class="text-sm text-gray-400">${Object.keys(results.prompts).length} categories • ${totalPrompts} total prompts</span>
                </div>
                <div class="space-y-3">
        `;
        
        for (const [category, prompts] of Object.entries(results.prompts).sort()) {
            const promptList = Array.isArray(prompts) ? prompts : [];
            const categoryColor = getCategoryColor(category);
            const activeCount = promptList.filter(p => {
                const name = typeof p === 'string' ? p : (p.name || '');
                return isActive(name, 'prompt');
            }).length;
            
            html += `
                <div class="bg-gray-800/30 border border-gray-700/50 rounded-lg p-4">
                    <div class="flex items-center justify-between mb-3">
                        <h5 class="text-sm font-medium" style="color: ${categoryColor};">
                            <span class="inline-block w-2 h-2 rounded-full mr-2" style="background: ${categoryColor};"></span>
                            ${escapeHtml(category)}
                        </h5>
                        <span class="text-xs text-gray-400">${activeCount}/${promptList.length} active</span>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
            `;
            
            promptList.forEach(prompt => {
                const promptName = typeof prompt === 'string' ? prompt : (prompt.name || 'Unknown');
                const active = isActive(promptName, 'prompt');
                html += `
                    <div class="text-sm font-mono px-3 py-1.5 rounded border ${active ? 'text-gray-300 bg-gray-900/30 border-gray-700/30' : 'text-gray-500 bg-gray-900/10 border-gray-700/20 opacity-50 line-through'}">
                        ${escapeHtml(promptName)}
                        ${!active ? '<span class="text-xs text-red-400 ml-2">(deactivated)</span>' : ''}
                    </div>
                `;
            });
            
            html += `
                    </div>
                </div>
            `;
        }
        
        html += `
                </div>
            </div>
        `;
    }
    
    // If no tools or prompts
    if ((!results.tools || Object.keys(results.tools).length === 0) && 
        (!results.prompts || Object.keys(results.prompts).length === 0)) {
        html = '<p class="text-gray-400">No tools or prompts have been classified yet.</p>';
    }
    
    content.innerHTML = html;
    
    // Show modal
    modal.classList.remove('hidden');
    
    // Close button handler
    const closeBtn = modal.querySelector('#classification-modal-close');
    closeBtn.onclick = () => modal.classList.add('hidden');
    
    // Click outside to close
    modal.onclick = (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
        }
    };
}

function getCategoryColor(category) {
    const colors = {
        'Performance': '#3b82f6',      // blue
        'Data Quality': '#10b981',      // green
        'Data Visualization': '#8b5cf6', // purple
        'Database Information': '#06b6d4', // cyan
        'Table Management': '#f59e0b',  // amber
        'Security': '#ef4444',          // red
        'User Management': '#ec4899',   // pink
        'Utilities': '#6b7280',         // gray
        'Reporting': '#14b8a6',         // teal
        'Archiving': '#a855f7'          // purple
    };
    return colors[category] || '#9ca3af'; // default gray
}

async function populateSystemPrompts(modal, profile) {
    const profileType = profile ? (profile.profile_type || 'tool_enabled') : 'tool_enabled';

    // Get all containers
    const masterPromptsContainer = modal.querySelector('#profile-modal-master-prompts');
    const workflowPromptsContainer = modal.querySelector('#profile-modal-workflow-prompts');
    const errorPromptsContainer = modal.querySelector('#profile-modal-error-prompts');
    const dataPromptsContainer = modal.querySelector('#profile-modal-data-prompts');
    const visualizationPromptsContainer = modal.querySelector('#profile-modal-visualization-prompts');
    const conversationPromptsContainer = modal.querySelector('#profile-modal-conversation-prompts');
    const ragPromptsContainer = modal.querySelector('#profile-modal-rag-prompts');
    const geniePromptsContainer = modal.querySelector('#profile-modal-genie-prompts');

    // Show/hide sections based on profile type
    const conversationSection = modal.querySelector('#conversation-execution-section');
    const ragSection = modal.querySelector('#rag-execution-section');
    const genieSection = modal.querySelector('#genie-coordination-section');
    const masterSystemSection = modal.querySelector('#master-system-section');
    const toolEnabledSection = modal.querySelector('#tool-enabled-prompts-section');
    const systemPromptsDescription = modal.querySelector('#system-prompts-description');

    if (profileType === 'llm_only') {
        // Conversation focused: show only conversation execution section
        if (conversationSection) conversationSection.classList.remove('hidden');
        if (ragSection) ragSection.classList.add('hidden');
        if (genieSection) genieSection.classList.add('hidden');
        if (masterSystemSection) masterSystemSection.classList.add('hidden');
        if (toolEnabledSection) toolEnabledSection.style.display = 'none';
        if (systemPromptsDescription) {
            systemPromptsDescription.textContent = 'Configure which conversation prompt version should be used for this profile.';
        }
    } else if (profileType === 'rag_focused') {
        // RAG focused: show only RAG execution section
        if (conversationSection) conversationSection.classList.add('hidden');
        if (ragSection) ragSection.classList.remove('hidden');
        if (genieSection) genieSection.classList.add('hidden');
        if (masterSystemSection) masterSystemSection.classList.add('hidden');
        if (toolEnabledSection) toolEnabledSection.style.display = 'none';
        if (systemPromptsDescription) {
            systemPromptsDescription.textContent = 'Configure which RAG synthesis prompt version should be used for this profile.';
        }
    } else if (profileType === 'genie') {
        // Genie: show only genie coordination section
        if (conversationSection) conversationSection.classList.add('hidden');
        if (ragSection) ragSection.classList.add('hidden');
        if (genieSection) genieSection.classList.remove('hidden');
        if (masterSystemSection) masterSystemSection.classList.add('hidden');
        if (toolEnabledSection) toolEnabledSection.style.display = 'none';
        if (systemPromptsDescription) {
            systemPromptsDescription.textContent = 'Configure the coordinator prompt that guides how this Genie orchestrates between child profiles.';
        }
    } else {
        // Tool enabled: show all sections
        if (conversationSection) conversationSection.classList.add('hidden');
        if (ragSection) ragSection.classList.add('hidden');
        if (genieSection) genieSection.classList.add('hidden');
        if (masterSystemSection) masterSystemSection.classList.remove('hidden');
        if (toolEnabledSection) toolEnabledSection.style.display = '';
        if (systemPromptsDescription) {
            systemPromptsDescription.textContent = 'Configure which prompt versions should be used for different functional areas. Defaults to system-wide prompt mappings.';
        }
    }

    // Get the provider from the profile's LLM configuration
    let profileProvider = null;
    if (profile && profile.llmConfigurationId) {
        const llmConfig = configState.llmConfigurations.find(c => c.id === profile.llmConfigurationId);
        if (llmConfig) {
            profileProvider = llmConfig.provider;
        }
    }

    // Define the categories and their subcategories with display names based on profile type
    let categories = {};

    if (profileType === 'llm_only') {
        // Conversation focused: check if MCP tools are enabled to determine which prompt category to show
        const useMcpToolsCheckbox = modal.querySelector('#profile-modal-use-mcp-tools');
        const useMcpTools = profile?.useMcpTools || useMcpToolsCheckbox?.checked || false;

        if (useMcpTools) {
            // MCP Tools enabled: show conversation_with_tools prompt option
            categories = {
                conversation_execution: {
                    container: conversationPromptsContainer,
                    subcategories: {
                        'conversation_with_tools': 'Conversation with Tools Prompt'
                    }
                }
            };
        } else {
            // Standard conversation: show basic conversation execution prompt
            categories = {
                conversation_execution: {
                    container: conversationPromptsContainer,
                    subcategories: {
                        'conversation': 'Conversation Execution Prompt'
                    }
                }
            };
        }
    } else if (profileType === 'rag_focused') {
        // RAG focused: only rag_focused_execution category
        categories = {
            rag_focused_execution: {
                container: ragPromptsContainer,
                subcategories: {
                    'rag_focused_execution': 'RAG Focused Execution Prompt'
                }
            }
        };
    } else if (profileType === 'genie') {
        // Genie: only genie_coordination category
        categories = {
            genie_coordination: {
                container: geniePromptsContainer,
                subcategories: {
                    'coordinator_prompt': 'Coordinator System Prompt'
                }
            }
        };
    } else {
        // Tool enabled: all categories
        categories = {
            master_system_prompts: {
                container: masterPromptsContainer,
                subcategories: profileProvider ? {
                    [profileProvider]: {
                        'Google': 'Google Gemini',
                        'Anthropic': 'Anthropic Claude',
                        'OpenAI': 'OpenAI GPT',
                        'Amazon': 'Amazon Bedrock',
                        'Azure': 'Azure OpenAI',
                        'Friendli': 'Friendli AI',
                        'Ollama': 'Ollama (Local)'
                    }[profileProvider] || `${profileProvider} Master System Prompt`
                } : {}
            },
            workflow_classification: {
                container: workflowPromptsContainer,
                subcategories: {
                    'task_classification': 'Task Classification',
                    'workflow_meta_planning': 'Workflow Meta Planning',
                    'workflow_tactical': 'Workflow Tactical'
                }
            },
            error_recovery: {
                container: errorPromptsContainer,
                subcategories: {
                    'error_recovery': 'Error Recovery',
                    'tactical_self_correction': 'Tactical Self-Correction',
                    'self_correction_column_error': 'Column Error Correction',
                    'self_correction_table_error': 'Table Error Correction'
                }
            },
            data_operations: {
                container: dataPromptsContainer,
                subcategories: {
                    'sql_consolidation': 'SQL Consolidation'
                }
            },
            visualization: {
                container: visualizationPromptsContainer,
                subcategories: {
                    'charting_instructions': 'Charting Instructions',
                    'g2plot_guidelines': 'G2Plot Guidelines'
                }
            }
        };
    }

    try {
        // Fetch available prompts from the system
        const token = localStorage.getItem('tda_auth_token');
        const availableResponse = await fetch('/api/v1/system-prompts/available', {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!availableResponse.ok) {
            throw new Error('Failed to fetch available prompts');
        }

        const availableData = await availableResponse.json();
        const availableCategories = availableData.categories || {};
        const defaults = availableData.defaults || {};
        
        // Debug logging
        console.log('[System Prompts] Available categories:', availableCategories);
        console.log('[System Prompts] Profile provider:', profileProvider);
        console.log('[System Prompts] Defaults:', defaults);

        // Fetch profile's current mappings if editing existing profile
        let profileMappings = {};
        if (profile && profile.id) {
            try {
                const mappingsResponse = await fetch(`/api/v1/system-prompts/profiles/${profile.id}/mappings`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (mappingsResponse.ok) {
                    const mappingsData = await mappingsResponse.json();
                    profileMappings = mappingsData.mappings || {};
                }
            } catch (err) {
                console.warn('Failed to load profile mappings:', err);
            }
        }

        // Render dropdowns for each category/subcategory
        for (const [category, config] of Object.entries(categories)) {
            const container = config.container;
            container.innerHTML = '';

            // Skip empty categories (e.g., master_system when no provider selected)
            if (Object.keys(config.subcategories).length === 0) {
                const emptyMessage = document.createElement('div');
                emptyMessage.className = 'text-xs text-gray-500 italic py-2';
                emptyMessage.textContent = category === 'master_system_prompts' 
                    ? 'Select an LLM Configuration first'
                    : 'No prompts in this category';
                container.appendChild(emptyMessage);
                continue;
            }

            for (const [subcategory, displayName] of Object.entries(config.subcategories)) {
                const div = document.createElement('div');
                div.className = 'flex items-center justify-between py-2';
                
                const label = document.createElement('label');
                label.className = 'text-xs font-medium text-gray-300 flex-1';
                // For master_system_prompts, don't show the provider name as label since dropdown shows prompt names
                label.textContent = category === 'master_system_prompts' ? 'Master System Prompt' : displayName;

                const selectWrapper = document.createElement('div');
                selectWrapper.className = 'flex-1';

                const select = document.createElement('select');
                select.className = 'w-full px-3 py-1.5 bg-gray-800/70 border border-gray-700/40 rounded text-xs text-white focus:outline-none focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 hover:border-gray-600/50 transition-all';
                select.dataset.category = category;
                select.dataset.subcategory = subcategory;

                // Add available prompts as options from the corresponding category
                const categoryPrompts = availableCategories[category]?.[subcategory] || [];
                console.log(`[System Prompts] ${category}/${subcategory}:`, categoryPrompts.length, 'prompts');
                
                let defaultPromptName = null;
                const optionValues = []; // Track all option values for debugging
                categoryPrompts.forEach(prompt => {
                    const option = document.createElement('option');
                    option.value = prompt.is_default ? '' : prompt.name;  // Empty value for default = use system default
                    optionValues.push({ name: prompt.name, value: option.value, is_default: prompt.is_default });
                    if (prompt.is_default) {
                        defaultPromptName = prompt.name;  // Remember the default prompt name
                        select.dataset.defaultPrompt = prompt.name;  // Store in dataset for save logic
                        option.textContent = `${prompt.display_name} (v${prompt.version}) (System Default)`;
                    } else {
                        option.textContent = `${prompt.display_name} (v${prompt.version})`;
                    }
                    select.appendChild(option);
                });

                console.log(`[System Prompts] Options for ${category}/${subcategory}:`, optionValues);

                // Set selected value if profile has custom mapping
                const currentMapping = profileMappings[category]?.[subcategory];
                console.log(`[System Prompts] Current mapping for ${category}/${subcategory}:`, currentMapping);
                if (currentMapping) {
                    // Check if the current mapping is the default prompt
                    if (currentMapping === defaultPromptName) {
                        console.log(`[System Prompts] Selecting default (empty) for ${category}/${subcategory}`);
                        select.value = '';  // Select the default option (empty value)
                    } else {
                        console.log(`[System Prompts] Selecting override "${currentMapping}" for ${category}/${subcategory}`);
                        select.value = currentMapping;  // Select the specific override
                        
                        // Verify the value was set correctly
                        if (select.value !== currentMapping) {
                            console.warn(`[System Prompts] Failed to set value for ${category}/${subcategory}. Tried: "${currentMapping}", got: "${select.value}"`);
                            console.warn(`[System Prompts] Available options:`, Array.from(select.options).map(opt => ({ text: opt.textContent, value: opt.value })));
                        }
                    }
                } else {
                    console.log(`[System Prompts] No custom mapping for ${category}/${subcategory}, using default`);
                }
                
                selectWrapper.appendChild(select);
                div.appendChild(label);
                div.appendChild(selectWrapper);
                container.appendChild(div);
            }
        }
    } catch (error) {
        console.error('Error populating system prompts:', error);
        // Show error in each container
        Object.values(categories).forEach(config => {
            config.container.innerHTML = '<span class="text-red-400 text-xs">Failed to load prompts</span>';
        });
    }
}

async function showProfileModal(profileId = null, defaultProfileType = null) {
    const profile = profileId ? configState.profiles.find(p => p.id === profileId) : null;
    const isEdit = !!profile;

    const modal = document.getElementById('profile-modal');
    if (!modal) return;

    modal.querySelector('#profile-modal-title').textContent = isEdit ? 'Edit Profile' : 'Add Profile';

    // Set profile type radio button
    // For new profiles: use defaultProfileType if provided, otherwise default to 'tool_enabled'
    // For existing profiles: use the profile's existing type
    const profileType = profile ?
        (profile.profile_type || 'tool_enabled') :
        (defaultProfileType || 'tool_enabled');
    const profileTypeRadioLLMOnly = modal.querySelector('#profile-modal-type-llm-only');
    const profileTypeRadioToolEnabled = modal.querySelector('#profile-modal-type-tool-enabled');
    const profileTypeRadioRAGFocused = modal.querySelector('#profile-modal-type-rag-focused');
    const profileTypeRadioGenie = modal.querySelector('#profile-modal-type-genie');

    // Function to show/hide tool-related sections based on profile type
    const updateSectionVisibility = (profileType) => {
        console.log('[Profile Modal] updateSectionVisibility called with profileType:', profileType);

        // Find MCP Server container - it's the column div containing label and select
        const mcpServerSelect = modal.querySelector('#profile-modal-mcp-server');
        // The parent is the <div> containing both label and select (the grid column)
        const mcpServerContainer = mcpServerSelect ? mcpServerSelect.parentElement : null;
        console.log('[Profile Modal] mcpServerContainer found:', !!mcpServerContainer);
        if (mcpServerContainer) {
            console.log('[Profile Modal] mcpServerContainer current display:', mcpServerContainer.style.display || 'default');
        }

        // Find classification section - search for the section with classification radio buttons
        const classificationRadio = modal.querySelector('input[name="classification-mode"]');
        let classificationSection = classificationRadio ? classificationRadio.closest('.rounded-xl') : null;
        console.log('[Profile Modal] classificationSection found:', !!classificationSection);
        if (classificationSection) {
            console.log('[Profile Modal] classificationSection current display:', classificationSection.style.display || 'default');
        }

        // Find Planner Repositories section within Intelligence tab
        const plannerCollectionsList = modal.querySelector('#profile-modal-planner-collections');
        const plannerSection = plannerCollectionsList ? plannerCollectionsList.closest('.mb-6') : null;
        console.log('[Profile Modal] plannerSection found:', !!plannerSection);

        // Find Knowledge Repositories section within Intelligence tab
        const knowledgeCollectionsList = modal.querySelector('#profile-modal-knowledge-collections');
        const knowledgeSection = knowledgeCollectionsList ? knowledgeCollectionsList.closest('.mb-6') : null;
        console.log('[Profile Modal] knowledgeSection found:', !!knowledgeSection);

        // Find LLM Reranking section (Per-Collection Override)
        const rerankingList = modal.querySelector('#profile-modal-knowledge-reranking-list');
        const knowledgeRerankingSection = rerankingList ? rerankingList.closest('.mb-6') : null;
        console.log('[Profile Modal] knowledgeRerankingSection found:', !!knowledgeRerankingSection);

        // Find Knowledge Advanced Settings section (Min Relevance, Max Docs, Max Tokens)
        // Note: Advanced Settings section uses <div> not <div class="mb-6"> so we need to find its parent container
        const minRelevanceInput = modal.querySelector('#profile-modal-min-relevance');
        const knowledgeAdvancedSection = minRelevanceInput ? minRelevanceInput.closest('.bg-gray-800\\/40')?.parentElement : null;
        console.log('[Profile Modal] knowledgeAdvancedSection found:', !!knowledgeAdvancedSection);

        const mcpResourcesTab = modal.querySelector('#profile-tab-mcp-resources');
        const intelligenceTab = modal.querySelector('#profile-tab-intelligence');
        const mcpResourcesContent = modal.querySelector('#profile-content-mcp-resources');
        const intelligenceContent = modal.querySelector('#profile-content-intelligence');
        console.log('[Profile Modal] Tabs found - MCP:', !!mcpResourcesTab, 'Intelligence:', !!intelligenceTab);

        // Get System Prompts tab (for enterprise users)
        const systemPromptsTab = modal.querySelector('#profile-tab-system-prompts');
        const systemPromptsContent = modal.querySelector('#profile-content-system-prompts');

        // Get Genie child profiles section reference (used in all profile types)
        const genieSlaveProfilesSection = modal.querySelector('#genie-slave-profiles-section');

        // Get Conversation Capabilities section (only for llm_only)
        const conversationCapabilitiesSection = modal.querySelector('#conversation-capabilities-section');
        const useMcpToolsCheckbox = modal.querySelector('#profile-modal-use-mcp-tools');
        const useKnowledgeCheckbox = modal.querySelector('#profile-modal-use-knowledge');

        // Get MCP Prompts section (hidden for llm_only with MCP tools since LangChain doesn't support MCP prompts)
        const mcpPromptsSection = modal.querySelector('#profile-modal-prompts-section');

        // Get Genie settings section reference
        const genieProfileSettingsSection = modal.querySelector('#genie-profile-settings-section');

        if (profileType === 'llm_only') {
            console.log('[Profile Modal] Configuring sections for Conversation profile with capability checkboxes');
            // Hide Genie sections
            if (genieSlaveProfilesSection) genieSlaveProfilesSection.style.display = 'none';
            if (genieProfileSettingsSection) genieProfileSettingsSection.style.display = 'none';

            // SHOW Conversation Capabilities section
            if (conversationCapabilitiesSection) conversationCapabilitiesSection.style.display = '';

            // Get checkbox states
            const useMcpTools = useMcpToolsCheckbox?.checked || false;
            const useKnowledge = useKnowledgeCheckbox?.checked || false;

            console.log('[Profile Modal] Conversation capabilities - MCP Tools:', useMcpTools, 'Knowledge:', useKnowledge);

            // Conditionally show MCP-related sections based on checkbox
            if (useMcpTools) {
                if (mcpServerContainer) mcpServerContainer.style.display = '';
                if (classificationSection) classificationSection.style.display = '';
                if (mcpResourcesTab) mcpResourcesTab.style.display = '';
                if (mcpResourcesContent) {
                    mcpResourcesContent.style.display = '';
                    mcpResourcesContent.classList.remove('hidden');  // CRITICAL FIX: Remove Tailwind hidden class
                }
                // Hide MCP Prompts section - LangChain approach doesn't support MCP prompts
                if (mcpPromptsSection) mcpPromptsSection.style.display = 'none';
            } else {
                if (mcpServerContainer) mcpServerContainer.style.display = 'none';
                if (classificationSection) classificationSection.style.display = 'none';
                if (mcpResourcesTab) mcpResourcesTab.style.display = 'none';
                if (mcpResourcesContent) {
                    mcpResourcesContent.style.display = 'none';
                    mcpResourcesContent.classList.add('hidden');  // Consistently use hidden class
                }
                // Show MCP Prompts section (not relevant when MCP tools disabled, but keep consistent)
                if (mcpPromptsSection) mcpPromptsSection.style.display = 'none';
            }

            // Always hide Planner section for conversation profiles
            if (plannerSection) plannerSection.style.display = 'none';

            // Conditionally show Intelligence tab based on checkbox
            if (useKnowledge) {
                if (intelligenceTab) intelligenceTab.style.display = '';
                if (intelligenceContent) {
                    intelligenceContent.style.display = '';
                    intelligenceContent.classList.remove('hidden');  // CRITICAL FIX: Remove Tailwind hidden class
                }
                if (intelligenceTab) {
                    intelligenceTab.setAttribute('title', 'Configure knowledge repositories for context injection');
                }
                // SHOW Knowledge Repository sections
                if (knowledgeSection) knowledgeSection.style.display = '';
                if (knowledgeRerankingSection) knowledgeRerankingSection.style.display = '';
                if (knowledgeAdvancedSection) knowledgeAdvancedSection.style.display = '';
            } else {
                if (intelligenceTab) intelligenceTab.style.display = 'none';
                if (intelligenceContent) {
                    intelligenceContent.style.display = 'none';
                    intelligenceContent.classList.add('hidden');  // Consistently use hidden class
                }
                if (knowledgeSection) knowledgeSection.style.display = 'none';
                if (knowledgeRerankingSection) knowledgeRerankingSection.style.display = 'none';
                if (knowledgeAdvancedSection) knowledgeAdvancedSection.style.display = 'none';
            }

            // KEEP System Prompts tab visible (for enterprise users to configure CONVERSATION_EXECUTION)
            if (systemPromptsTab && systemPromptsTab.style.display !== 'none') {
                systemPromptsTab.style.display = '';
            }
            if (systemPromptsContent) {
                systemPromptsContent.style.display = '';
            }
        } else if (profileType === 'rag_focused') {
            console.log('[Profile Modal] Configuring sections for RAG-focused profile');
            // Hide Genie sections and Conversation Capabilities section
            if (genieSlaveProfilesSection) genieSlaveProfilesSection.style.display = 'none';
            if (genieProfileSettingsSection) genieProfileSettingsSection.style.display = 'none';
            if (conversationCapabilitiesSection) conversationCapabilitiesSection.style.display = 'none';

            // Hide MCP and planner sections (RAG focused doesn't use tools/planner)
            if (mcpServerContainer) mcpServerContainer.style.display = 'none';
            if (classificationSection) classificationSection.style.display = 'none';
            if (mcpResourcesTab) mcpResourcesTab.style.display = 'none';
            if (mcpResourcesContent) mcpResourcesContent.style.display = 'none';
            if (mcpPromptsSection) mcpPromptsSection.style.display = 'none';
            if (plannerSection) plannerSection.style.display = 'none';

            // KEEP Intelligence tab visible - REQUIRED for RAG focused
            if (intelligenceTab) intelligenceTab.style.display = '';
            if (intelligenceContent) {
                intelligenceContent.style.display = '';
                intelligenceContent.classList.remove('hidden');  // CRITICAL FIX: Remove Tailwind hidden class
            }
            if (intelligenceTab) {
                intelligenceTab.setAttribute('title', 'Configure knowledge repositories (REQUIRED for RAG focused profiles)');
            }

            // SHOW Knowledge Repository sections - REQUIRED for RAG focused profiles
            if (knowledgeSection) knowledgeSection.style.display = '';
            if (knowledgeRerankingSection) knowledgeRerankingSection.style.display = '';
            if (knowledgeAdvancedSection) knowledgeAdvancedSection.style.display = '';

            // KEEP System Prompts tab visible (for enterprise users to configure RAG_FOCUSED_EXECUTION)
            if (systemPromptsTab && systemPromptsTab.style.display !== 'none') {
                systemPromptsTab.style.display = '';
            }
            if (systemPromptsContent) {
                systemPromptsContent.style.display = '';
            }
        } else if (profileType === 'genie') {
            console.log('[Profile Modal] Configuring sections for genie profile');

            // Hide Conversation Capabilities section
            if (conversationCapabilitiesSection) conversationCapabilitiesSection.style.display = 'none';

            // Hide MCP-related sections (genie doesn't use MCP directly)
            if (mcpServerContainer) mcpServerContainer.style.display = 'none';
            if (classificationSection) classificationSection.style.display = 'none';
            if (mcpResourcesTab) mcpResourcesTab.style.display = 'none';
            if (mcpResourcesContent) mcpResourcesContent.style.display = 'none';
            if (mcpPromptsSection) mcpPromptsSection.style.display = 'none';
            if (plannerSection) plannerSection.style.display = 'none';

            // Hide knowledge sections (slaves handle their own knowledge)
            if (knowledgeSection) knowledgeSection.style.display = 'none';
            if (knowledgeRerankingSection) knowledgeRerankingSection.style.display = 'none';
            if (knowledgeAdvancedSection) knowledgeAdvancedSection.style.display = 'none';

            // Hide Intelligence tab entirely for genie
            if (intelligenceTab) intelligenceTab.style.display = 'none';
            if (intelligenceContent) intelligenceContent.style.display = 'none';

            // SHOW Genie child profiles section
            if (genieSlaveProfilesSection) {
                genieSlaveProfilesSection.style.display = '';
                // Populate child profiles list
                populateGenieSlaveProfilesList(modal, profile);
            }

            // SHOW Genie settings section
            const genieProfileSettingsSection = modal.querySelector('#genie-profile-settings-section');
            if (genieProfileSettingsSection) {
                genieProfileSettingsSection.style.display = '';
                // Load global settings and populate the form
                loadGenieProfileSettings(modal, profile);
            }

            // KEEP System Prompts tab visible (for genie_coordination prompt)
            if (systemPromptsTab && systemPromptsTab.style.display !== 'none') {
                systemPromptsTab.style.display = '';
            }
            if (systemPromptsContent) {
                systemPromptsContent.style.display = '';
            }
        } else {
            console.log('[Profile Modal] Configuring sections for tool-enabled profile');
            // Hide Genie sections and Conversation Capabilities section
            if (genieSlaveProfilesSection) genieSlaveProfilesSection.style.display = 'none';
            if (genieProfileSettingsSection) genieProfileSettingsSection.style.display = 'none';
            if (conversationCapabilitiesSection) conversationCapabilitiesSection.style.display = 'none';

            // Show MCP sections and planner repos for tool-enabled profiles
            if (mcpServerContainer) mcpServerContainer.style.display = '';
            if (classificationSection) classificationSection.style.display = '';
            if (mcpResourcesTab) mcpResourcesTab.style.display = '';
            if (mcpResourcesContent) {
                mcpResourcesContent.style.display = '';
                mcpResourcesContent.classList.remove('hidden');  // CRITICAL FIX: Remove Tailwind hidden class
            }
            if (mcpPromptsSection) mcpPromptsSection.style.display = '';  // MCP prompts supported in planner/executor
            if (plannerSection) plannerSection.style.display = '';
            if (intelligenceTab) intelligenceTab.style.display = '';
            if (intelligenceContent) {
                intelligenceContent.style.display = '';
                intelligenceContent.classList.remove('hidden');  // CRITICAL FIX: Remove Tailwind hidden class
            }
            if (intelligenceTab) {
                intelligenceTab.setAttribute('title', 'Configure planner repositories for execution patterns');
            }

            // HIDE Knowledge Repository sections for tool-enabled profiles
            // Knowledge retrieval is only available for RAG-focused and LLM-only profiles
            if (knowledgeSection) knowledgeSection.style.display = 'none';
            if (knowledgeRerankingSection) knowledgeRerankingSection.style.display = 'none';
            if (knowledgeAdvancedSection) knowledgeAdvancedSection.style.display = 'none';
            console.log('[Profile Modal] Hiding knowledge sections for tool-enabled profile');

            // KEEP System Prompts tab visible (for enterprise users to configure all prompts)
            if (systemPromptsTab && systemPromptsTab.style.display !== 'none') {
                systemPromptsTab.style.display = '';
            }
            if (systemPromptsContent) {
                systemPromptsContent.style.display = '';
            }
        }

        console.log('[Profile Modal] updateSectionVisibility completed');
    };

    // Helper function to populate Genie child profiles list
    function populateGenieSlaveProfilesList(modal, currentGenieProfile) {
        const container = modal.querySelector('#genie-slave-profiles-list');
        if (!container) return;

        container.innerHTML = '';

        // Get all profiles except self (allow nested Genies)
        // Only include profiles that are active for consumption
        const availableProfiles = configState.profiles.filter(p => {
            const isNotSelf = p.id !== currentGenieProfile?.id;  // Exclude self-reference
            const isActive = configState.activeForConsumptionProfileIds.includes(p.id);  // Only active profiles
            return isNotSelf && isActive;
        });

        // Get currently selected children (if editing)
        const selectedSlaves = currentGenieProfile?.genieConfig?.slaveProfiles || [];

        if (availableProfiles.length === 0) {
            const hasInactiveProfiles = configState.profiles.some(p =>
                p.id !== currentGenieProfile?.id &&
                !configState.activeForConsumptionProfileIds.includes(p.id)
            );

            if (hasInactiveProfiles) {
                container.innerHTML = '<p class="text-gray-500 text-sm italic">No active profiles available. Activate profiles in the main list before selecting them as children.</p>';
            } else {
                container.innerHTML = '<p class="text-gray-500 text-sm italic">No profiles available. Create other profile types first.</p>';
            }
            return;
        }

        availableProfiles.forEach(profile => {
            const isSelected = selectedSlaves.includes(profile.id);
            const isGenieType = profile.profile_type === 'genie';

            const profileTypeLabel = {
                'llm_only': 'Conversation',
                'tool_enabled': 'Tool-Enabled',
                'rag_focused': 'RAG Focused',
                'genie': 'Genie'
            }[profile.profile_type] || profile.profile_type;

            const profileTypeColor = {
                'llm_only': 'text-green-400',
                'tool_enabled': 'text-orange-400',
                'rag_focused': 'text-purple-400',
                'genie': 'text-purple-600'
            }[profile.profile_type] || 'text-gray-400';

            const div = document.createElement('div');
            div.className = `flex items-center space-x-3 py-2 px-2 rounded hover:bg-gray-700/30 transition-colors ${isGenieType ? 'bg-purple-900/20 border border-purple-700/30' : ''}`;
            div.innerHTML = `
                <input type="checkbox"
                       id="slave-${profile.id}"
                       value="${profile.id}"
                       ${isSelected ? 'checked' : ''}
                       class="genie-slave-checkbox form-checkbox text-amber-500 rounded border-gray-600 bg-gray-700 focus:ring-amber-500 focus:ring-offset-gray-900">
                <label for="slave-${profile.id}" class="flex-1 cursor-pointer">
                    ${isGenieType ? '<span class="text-purple-400 mr-1" title="Nested Genie Coordination">🔮</span>' : ''}
                    <span class="font-semibold text-sm text-white">@${profile.tag || 'UNKNOWN'}</span>
                    <span class="text-gray-400 text-sm ml-2">${profile.name || ''}</span>
                    <span class="text-xs ${profileTypeColor} ml-2 ${isGenieType ? 'font-semibold' : ''}">(${profileTypeLabel})</span>
                    ${isGenieType ? '<span class="ml-2 text-xs bg-purple-600/30 text-purple-300 px-2 py-0.5 rounded-full border border-purple-500/30">Nested</span>' : ''}
                </label>
            `;
            container.appendChild(div);
        });

        // Add warning banner if any selected children are Genies
        const hasNestedGenies = selectedSlaves.some(slaveId => {
            const slaveProfile = configState.profiles.find(p => p.id === slaveId);
            return slaveProfile && slaveProfile.profile_type === 'genie';
        });

        if (hasNestedGenies) {
            const warningDiv = document.createElement('div');
            warningDiv.className = 'mt-4 p-3 bg-yellow-900/30 border border-yellow-600/50 rounded-lg';
            warningDiv.innerHTML = `
                <div class="flex items-start space-x-2">
                    <span class="text-yellow-400 text-lg">⚠️</span>
                    <div class="flex-1">
                        <p class="text-sm font-semibold text-yellow-300 mb-1">Nested Genie Coordination Active</p>
                        <p class="text-xs text-yellow-200/80">
                            This Genie will coordinate other Genie profiles, significantly increasing token usage.
                            Maximum nesting depth is controlled in <span class="font-mono text-yellow-300">Administration → Expert Settings → Genie Coordination</span>.
                        </p>
                    </div>
                </div>
            `;
            container.appendChild(warningDiv);
        }
    }

    // Helper function to load Genie profile settings (temperature, timeout, max iterations)
    async function loadGenieProfileSettings(modal, profile) {
        console.log('[Profile Modal] Loading Genie settings for profile:', profile?.id);

        // Get form elements
        const tempSlider = modal.querySelector('#profile-genie-temperature');
        const tempValue = modal.querySelector('#profile-genie-temperature-value');
        const tempLockedBadge = modal.querySelector('#profile-genie-temperature-locked-badge');
        const tempHint = modal.querySelector('#profile-genie-temperature-hint');

        const timeoutInput = modal.querySelector('#profile-genie-query-timeout');
        const timeoutLockedBadge = modal.querySelector('#profile-genie-query-timeout-locked-badge');
        const timeoutHint = modal.querySelector('#profile-genie-query-timeout-hint');

        const iterInput = modal.querySelector('#profile-genie-max-iterations');
        const iterLockedBadge = modal.querySelector('#profile-genie-max-iterations-locked-badge');
        const iterHint = modal.querySelector('#profile-genie-max-iterations-hint');

        // Get profile's genie config
        const genieConfig = profile?.genieConfig || {};

        // Load global settings to check for locks
        let globalSettings = {};
        try {
            const token = localStorage.getItem('jwt_token');
            if (token) {
                const response = await fetch('/api/v1/admin/genie-settings', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (response.ok) {
                    const data = await response.json();
                    globalSettings = data.settings || {};
                }
            }
        } catch (e) {
            console.warn('[Profile Modal] Could not load global genie settings:', e);
        }

        // Setup temperature slider with live update
        if (tempSlider) {
            tempSlider.addEventListener('input', (e) => {
                if (tempValue) tempValue.textContent = parseFloat(e.target.value).toFixed(1);
            });
        }

        // Configure temperature
        if (tempSlider && tempValue) {
            const isLocked = globalSettings.temperature?.is_locked || false;
            const globalValue = globalSettings.temperature?.value ?? 0.7;
            const profileValue = genieConfig.temperature;

            if (isLocked) {
                tempSlider.value = globalValue;
                tempSlider.disabled = true;
                tempValue.textContent = parseFloat(globalValue).toFixed(1);
                if (tempLockedBadge) tempLockedBadge.classList.remove('hidden');
                if (tempHint) tempHint.textContent = `Locked by admin to ${globalValue}`;
            } else {
                tempSlider.value = profileValue ?? globalValue;
                tempSlider.disabled = false;
                tempValue.textContent = parseFloat(profileValue ?? globalValue).toFixed(1);
                if (tempLockedBadge) tempLockedBadge.classList.add('hidden');
                if (tempHint) tempHint.textContent = `Leave at ${globalValue} to use global default`;
            }
        }

        // Configure query timeout
        if (timeoutInput) {
            const isLocked = globalSettings.queryTimeout?.is_locked || false;
            const globalValue = globalSettings.queryTimeout?.value ?? 300;
            const profileValue = genieConfig.queryTimeout;

            if (isLocked) {
                timeoutInput.value = globalValue;
                timeoutInput.disabled = true;
                if (timeoutLockedBadge) timeoutLockedBadge.classList.remove('hidden');
                if (timeoutHint) timeoutHint.textContent = `Locked by admin to ${globalValue}s`;
            } else {
                timeoutInput.value = profileValue ?? '';
                timeoutInput.placeholder = String(globalValue);
                timeoutInput.disabled = false;
                if (timeoutLockedBadge) timeoutLockedBadge.classList.add('hidden');
                if (timeoutHint) timeoutHint.textContent = `Leave empty to use global default (${globalValue}s)`;
            }
        }

        // Configure max iterations
        if (iterInput) {
            const isLocked = globalSettings.maxIterations?.is_locked || false;
            const globalValue = globalSettings.maxIterations?.value ?? 10;
            const profileValue = genieConfig.maxIterations;

            if (isLocked) {
                iterInput.value = globalValue;
                iterInput.disabled = true;
                if (iterLockedBadge) iterLockedBadge.classList.remove('hidden');
                if (iterHint) iterHint.textContent = `Locked by admin to ${globalValue}`;
            } else {
                iterInput.value = profileValue ?? '';
                iterInput.placeholder = String(globalValue);
                iterInput.disabled = false;
                if (iterLockedBadge) iterLockedBadge.classList.add('hidden');
                if (iterHint) iterHint.textContent = `Leave empty to use global default (${globalValue})`;
            }
        }

        console.log('[Profile Modal] Genie settings loaded - global:', globalSettings, 'profile:', genieConfig);
    }

    // Add event listeners to profile type radio buttons FIRST (before setting checked state)
    // Clone the radio buttons to remove any existing event listeners
    const llmOnlyClone = profileTypeRadioLLMOnly.cloneNode(true);
    const toolEnabledClone = profileTypeRadioToolEnabled.cloneNode(true);
    const ragFocusedClone = profileTypeRadioRAGFocused.cloneNode(true);
    const genieClone = profileTypeRadioGenie ? profileTypeRadioGenie.cloneNode(true) : null;
    profileTypeRadioLLMOnly.parentNode.replaceChild(llmOnlyClone, profileTypeRadioLLMOnly);
    profileTypeRadioToolEnabled.parentNode.replaceChild(toolEnabledClone, profileTypeRadioToolEnabled);
    profileTypeRadioRAGFocused.parentNode.replaceChild(ragFocusedClone, profileTypeRadioRAGFocused);
    if (profileTypeRadioGenie && genieClone) {
        profileTypeRadioGenie.parentNode.replaceChild(genieClone, profileTypeRadioGenie);
    }

    // Update references to the cloned elements
    const cleanLLMOnlyRadio = modal.querySelector('#profile-modal-type-llm-only');
    const cleanToolEnabledRadio = modal.querySelector('#profile-modal-type-tool-enabled');
    const cleanRAGFocusedRadio = modal.querySelector('#profile-modal-type-rag-focused');
    const cleanGenieRadio = modal.querySelector('#profile-modal-type-genie');

    // Add our event listeners to the clean radio buttons
    cleanLLMOnlyRadio.addEventListener('change', async () => {
        if (cleanLLMOnlyRadio.checked) {
            console.log('[Profile Modal] Radio changed to llm_only');
            updateSectionVisibility('llm_only');
            // Update System Prompts tab if user is privileged
            if (Utils.isPrivilegedUser()) {
                const tempProfile = { ...profile, profile_type: 'llm_only' };
                await populateSystemPrompts(modal, tempProfile);
            }
        }
    });

    cleanToolEnabledRadio.addEventListener('change', async () => {
        if (cleanToolEnabledRadio.checked) {
            console.log('[Profile Modal] Radio changed to tool_enabled');
            updateSectionVisibility('tool_enabled');
            // Update System Prompts tab if user is privileged
            if (Utils.isPrivilegedUser()) {
                const tempProfile = { ...profile, profile_type: 'tool_enabled' };
                await populateSystemPrompts(modal, tempProfile);
            }
        }
    });

    cleanRAGFocusedRadio.addEventListener('change', async () => {
        if (cleanRAGFocusedRadio.checked) {
            console.log('[Profile Modal] Radio changed to rag_focused');
            updateSectionVisibility('rag_focused');
            // Update System Prompts tab if user is privileged
            if (Utils.isPrivilegedUser()) {
                const tempProfile = { ...profile, profile_type: 'rag_focused' };
                await populateSystemPrompts(modal, tempProfile);
            }
        }
    });

    // Add Genie radio button event listener
    if (cleanGenieRadio) {
        cleanGenieRadio.addEventListener('change', async () => {
            if (cleanGenieRadio.checked) {
                console.log('[Profile Modal] Radio changed to genie');
                updateSectionVisibility('genie');
                // Update System Prompts tab if user is privileged
                if (Utils.isPrivilegedUser()) {
                    const tempProfile = { ...profile, profile_type: 'genie' };
                    await populateSystemPrompts(modal, tempProfile);
                }
            }
        });
    }

    // Add event listeners for Conversation Capabilities checkboxes
    const useMcpToolsCheckbox = modal.querySelector('#profile-modal-use-mcp-tools');
    const useKnowledgeCheckbox = modal.querySelector('#profile-modal-use-knowledge');

    if (useMcpToolsCheckbox) {
        useMcpToolsCheckbox.addEventListener('change', async () => {
            console.log('[Profile Modal] MCP Tools checkbox changed to:', useMcpToolsCheckbox.checked);
            // Re-run visibility update for llm_only profile type
            const currentProfileType = modal.querySelector('input[name="profile-type"]:checked')?.value;
            if (currentProfileType === 'llm_only') {
                updateSectionVisibility('llm_only');
                // Update System Prompts tab to show correct prompt option (conversation vs conversation_with_tools)
                if (Utils.isPrivilegedUser()) {
                    const tempProfile = { ...profile, profile_type: 'llm_only', useMcpTools: useMcpToolsCheckbox.checked };
                    await populateSystemPrompts(modal, tempProfile);
                }
            }
        });
    }

    if (useKnowledgeCheckbox) {
        useKnowledgeCheckbox.addEventListener('change', () => {
            console.log('[Profile Modal] Knowledge checkbox changed to:', useKnowledgeCheckbox.checked);
            // Re-run visibility update for llm_only profile type
            const currentProfileType = modal.querySelector('input[name="profile-type"]:checked')?.value;
            if (currentProfileType === 'llm_only') {
                updateSectionVisibility('llm_only');
            }
        });
    }

    // Set initial checkbox states from profile data (for llm_only profiles)
    if (profile && profileType === 'llm_only') {
        if (useMcpToolsCheckbox) {
            useMcpToolsCheckbox.checked = profile.useMcpTools || false;
        }
        if (useKnowledgeCheckbox) {
            useKnowledgeCheckbox.checked = profile.useKnowledgeCollections || false;
        }
    }

    // NOW set the checked state (won't trigger old listeners since we cloned)
    if (profileType === 'llm_only') {
        cleanLLMOnlyRadio.checked = true;
    } else if (profileType === 'rag_focused') {
        cleanRAGFocusedRadio.checked = true;
    } else if (profileType === 'genie' && cleanGenieRadio) {
        cleanGenieRadio.checked = true;
    } else {
        cleanToolEnabledRadio.checked = true;
    }

    // Initial visibility update will happen at the END after all async initialization
    // (Deferred to prevent race conditions with collection rendering)

    // Populate LLM configurations
    const llmSelect = modal.querySelector('#profile-modal-llm-provider');
    const activeLLMId = configState.activeLLM || configState.llmConfigurations[0]?.id;
    llmSelect.innerHTML = configState.llmConfigurations
        .map(config => {
            const isSelected = profile ? 
                (profile.llmConfigurationId === config.id) : 
                (config.id === activeLLMId);
            return `<option value="${config.id}" ${isSelected ? 'selected' : ''}>${escapeHtml(config.name)}</option>`;
        })
        .join('');

    // Populate MCP servers
    const mcpSelect = modal.querySelector('#profile-modal-mcp-server');
    const activeMCPId = configState.activeMCP || configState.mcpServers[0]?.id;
    mcpSelect.innerHTML = configState.mcpServers
        .map(server => {
            const isSelected = profile ? 
                (profile.mcpServerId === server.id) : 
                (server.id === activeMCPId);
            return `<option value="${server.id}" ${isSelected ? 'selected' : ''}>${escapeHtml(server.name)}</option>`;
        })
        .join('');

    // Set classification mode
    const classificationMode = profile?.classification_mode || 'light';
    const modeRadio = modal.querySelector(`input[name="classification-mode"][value="${classificationMode}"]`);
    if (modeRadio) {
        modeRadio.checked = true;
    }

    const toolsContainer = modal.querySelector('#profile-modal-tools');
    const promptsContainer = modal.querySelector('#profile-modal-prompts');
    let allTools = [];
    let allPrompts = [];

    async function populateResources(mcpServerId) {
        const server = configState.mcpServers.find(s => s.id === mcpServerId);
        if (!server) {
            toolsContainer.innerHTML = '<span class="text-gray-400">Select an MCP server.</span>';
            promptsContainer.innerHTML = '<span class="text-gray-400">Select an MCP server.</span>';
            return;
        }

        toolsContainer.innerHTML = '<span class="text-gray-400">Loading...</span>';
        promptsContainer.innerHTML = '<span class="text-gray-400">Loading...</span>';

        try {
            const resources = await API.fetchResourcesForServer(server);
            allTools = Object.values(resources.tools || {}).flat().map(t => t.name);
            allPrompts = Object.values(resources.prompts || {}).flat().map(p => p.name);

            // For new profiles (isEdit=false), default all to checked
            // For existing profiles with tools=null/undefined/[] (not yet configured), default all to checked
            // For existing profiles with populated arrays (specific tools selected), respect their saved selections
            // NOTE: Empty array [] is now treated as "not configured" (handles old bootstrap profiles)
            const toolsNotYetConfigured = profile && (profile.tools === null || profile.tools === undefined || profile.tools.length === 0);
            const promptsNotYetConfigured = profile && (profile.prompts === null || profile.prompts === undefined || profile.prompts.length === 0);

            toolsContainer.innerHTML = allTools.map(tool => `
                <label class="flex items-center gap-2 text-sm text-gray-300">
                    <input type="checkbox" value="${escapeHtml(tool)}" ${!isEdit || toolsNotYetConfigured || profile?.tools?.includes(tool) || profile?.tools?.includes('*') ? 'checked' : ''}>
                    ${escapeHtml(tool)}
                </label>
            `).join('') || '<span class="text-gray-400">No tools found.</span>';

            promptsContainer.innerHTML = allPrompts.map(prompt => `
                <label class="flex items-center gap-2 text-sm text-gray-300">
                    <input type="checkbox" value="${escapeHtml(prompt)}" ${!isEdit || promptsNotYetConfigured || profile?.prompts?.includes(prompt) || profile?.prompts?.includes('*') ? 'checked' : ''}>
                    ${escapeHtml(prompt)}
                </label>
            `).join('') || '<span class="text-gray-400">No prompts found.</span>';
        } catch (error) {
            toolsContainer.innerHTML = `<span class="text-red-400">Error: ${error.message}</span>`;
            promptsContainer.innerHTML = `<span class="text-red-400">Error: ${error.message}</span>`;
        }
    }
    
    // Note: MCP select onchange handler is set AFTER renderCollections is defined (see below)

    // Initial population - use the ACTUAL selected value from the dropdown
    // (not the first server in the array, which may differ from activeMCP)
    const initialMcpId = mcpSelect.value;
    if (initialMcpId) {
        populateResources(initialMcpId);
    } else {
        toolsContainer.innerHTML = '<span class="text-gray-400">No MCP servers configured.</span>';
        promptsContainer.innerHTML = '<span class="text-gray-400">No MCP servers configured.</span>';
    }


    // Populate Intelligence Collections (Planner and Knowledge Repositories)
    const plannerContainer = modal.querySelector('#profile-modal-planner-collections');
    const knowledgeContainer = modal.querySelector('#profile-modal-knowledge-collections');

    const { collections: ragCollections } = await API.getRagCollections();

    // Separate collections by repository type
    const plannerCollections = ragCollections.filter(coll => coll.repository_type === 'planner');
    const knowledgeCollections = ragCollections.filter(coll => coll.repository_type === 'knowledge');

    // Function to calculate default collection for a given MCP server
    const calculateDefaultCollectionId = (mcpServerId) => {
        if (!mcpServerId) return null;
        const serverPlannerCollections = plannerCollections.filter(c => c.mcp_server_id === mcpServerId);
        if (serverPlannerCollections.length === 0) return null;
        // Sort by ID (ascending) and return the first (oldest)
        const sorted = serverPlannerCollections.sort((a, b) => a.id - b.id);
        return sorted[0].id;
    };

    // Determine the profile's MCP server ID (for new profiles, use active MCP)
    let currentMcpServerId = profile ? profile.mcpServerId : (configState.activeMCP || configState.mcpServers[0]?.id);
    let defaultCollectionId = calculateDefaultCollectionId(currentMcpServerId);

    console.log('[Profile Modal] Profile MCP Server ID:', currentMcpServerId);
    console.log('[Profile Modal] Default Collection ID:', defaultCollectionId);

    // Note: Global Knowledge Repository Configuration has been moved to Administration panel
    // Per-collection reranking toggles remain in the profile modal
    const rerankingListContainer = modal.querySelector('#profile-modal-knowledge-reranking-list');

    // Update reranking list when knowledge collections change (must be defined before renderCollections)
    const updateRerankingList = () => {
        const selectedKnowledgeCheckboxes = knowledgeContainer.querySelectorAll('input[data-collection-type="query"]:checked');
        const selectedKnowledgeIds = Array.from(selectedKnowledgeCheckboxes).map(cb => parseInt(cb.dataset.collectionId));

        if (selectedKnowledgeIds.length === 0) {
            rerankingListContainer.innerHTML = '<span class="text-gray-400 text-sm">Select knowledge collections above to configure reranking</span>';
            return;
        }

        const existingReranking = profile?.knowledgeConfig?.collections || [];

        rerankingListContainer.innerHTML = selectedKnowledgeIds.map(collId => {
            const collection = knowledgeCollections.find(c => c.id === collId);
            const collectionConfig = existingReranking.find(c => c.id === collId);
            const isRerankingEnabled = collectionConfig?.reranking === true;

            return `
                <div class="flex items-center justify-between px-4 py-2.5 bg-gray-800/30 hover:bg-gray-800/50 rounded-lg border border-gray-700/30 hover:border-gray-600/50 transition-all">
                    <span class="text-sm text-gray-200">${escapeHtml(collection?.name || `Collection ${collId}`)}</span>
                    <div class="flex items-center gap-3">
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" data-collection-id="${collId}" data-reranking="true" ${isRerankingEnabled ? 'checked' : ''} class="sr-only peer" style="position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border-width: 0 !important;">
                            <div class="relative w-11 h-6 bg-gray-700 rounded-full peer peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-[#F15F22]/50 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#F15F22]"></div>
                        </label>
                        <span class="text-xs font-medium text-gray-400">Rerank</span>
                    </div>
                </div>
            `;
        }).join('');
    };

    // Helper function to create collection entry with toggles
    const createCollectionEntry = (coll, isPlanner) => {
        // Check if this is the default collection for the profile's MCP server
        const isDefaultCollection = isPlanner && coll.id === defaultCollectionId;

        // For new profiles (!isEdit), only default collection is enabled
        // For existing profiles being edited (isEdit=true), respect their saved selections
        // DEFAULT COLLECTIONS: Always enabled and cannot be disabled
        let isQueryEnabled;
        if (isPlanner) {
            if (isDefaultCollection) {
                // Default collection is ALWAYS enabled (cannot be disabled)
                isQueryEnabled = true;
            } else if (!isEdit) {
                // New profiles: only default collection is checked
                isQueryEnabled = false;
            } else {
                // Existing profiles: check if collection is in ragCollections array or wildcard
                isQueryEnabled = profile?.ragCollections?.includes(coll.id) || profile?.ragCollections?.includes('*');
            }
        } else {
            // Knowledge repository: check if it's in knowledgeConfig.collections
            const knowledgeCollectionIds = profile?.knowledgeConfig?.collections?.map(c => c.id) || [];
            if (!isEdit) {
                // New profiles: only default collection is checked
                isQueryEnabled = isDefaultCollection;
            } else {
                isQueryEnabled = knowledgeCollectionIds.includes(coll.id);
            }
        }

        // For autocomplete, also enable only default collection for new profiles
        // Note: Knowledge repositories DON'T support autocomplete (they lack user_query metadata)
        let isAutocompleteEnabled;
        if (isPlanner) {
            if (!isEdit) {
                // New profiles: only default collection has autocomplete enabled
                isAutocompleteEnabled = isDefaultCollection;
            } else {
                // Existing profiles: respect saved selections
                isAutocompleteEnabled = profile?.autocompleteCollections?.includes(coll.id) || profile?.autocompleteCollections?.includes('*');
            }
        }

        // Build autocomplete toggle HTML only for Planner repositories
        const autocompleteToggleHTML = isPlanner ? `
            <!-- Autocomplete Toggle -->
            <div class="flex items-center justify-center" style="width: 50px;">
                <label class="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox"
                           data-collection-id="${coll.id}"
                           data-collection-type="autocomplete"
                           ${isAutocompleteEnabled ? 'checked' : ''}
                           class="sr-only peer"
                           style="position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border-width: 0 !important;">
                    <div class="relative w-11 h-6 bg-gray-700 rounded-full peer peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-[#F15F22]/50 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#F15F22]"></div>
                </label>
            </div>
        ` : '';

        // Build the default badge if this is the default collection
        const defaultBadgeHTML = isDefaultCollection ? `
            <span class="inline-flex items-center px-2 py-0.5 ml-2 text-xs font-semibold bg-blue-500/20 text-blue-300 border border-blue-400/30 rounded-full" title="Default collection for new patterns">
                DEFAULT
            </span>
        ` : '';

        return `
            <div class="flex items-center justify-between py-2.5 bg-gray-800/30 hover:bg-gray-800/50 rounded-lg border border-gray-700/30 hover:border-gray-600/50 transition-all group" style="padding-left: 16px; padding-right: 16px;">
                <div class="flex items-center gap-2 flex-1 min-w-0">
                    <span class="text-sm text-gray-200 group-hover:text-white transition-colors truncate">${escapeHtml(coll.name)}</span>
                    ${defaultBadgeHTML}
                </div>
                <div class="flex items-center gap-8 flex-shrink-0">
                    <!-- Query Toggle -->
                    <div class="flex items-center justify-center" style="width: 50px;" ${isDefaultCollection ? 'title="Default collection cannot be disabled - it stores new discoveries"' : ''}>
                        <label class="relative inline-flex items-center ${isDefaultCollection ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}">
                            <input type="checkbox"
                                   data-collection-id="${coll.id}"
                                   data-collection-type="query"
                                   ${isQueryEnabled ? 'checked' : ''}
                                   ${isDefaultCollection ? 'disabled' : ''}
                                   class="sr-only peer"
                                   style="position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border-width: 0 !important;">
                            <div class="relative w-11 h-6 ${isDefaultCollection ? 'bg-gray-600' : 'bg-gray-700'} rounded-full peer peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-[#F15F22]/50 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all ${isDefaultCollection ? 'peer-checked:bg-blue-500' : 'peer-checked:bg-[#F15F22]'}"></div>
                        </label>
                    </div>
                    ${autocompleteToggleHTML}
                </div>
            </div>
        `;
    };

    // Function to render collections (called on initial load and when MCP server changes)
    const renderCollections = () => {
        // Recalculate default collection based on current MCP server
        currentMcpServerId = mcpSelect.value;
        defaultCollectionId = calculateDefaultCollectionId(currentMcpServerId);

        console.log('[Profile Modal] Rendering collections for MCP Server:', currentMcpServerId);
        console.log('[Profile Modal] Default Collection ID:', defaultCollectionId);

        // Render Planner Collections
        const plannerHTML = plannerCollections.length > 0
            ? plannerCollections.map(coll => createCollectionEntry(coll, true)).join('')
            : '<span class="text-gray-400 text-sm px-3 py-2 block">No planner repositories found.</span>';
        console.log('[Profile Modal] Planner HTML length:', plannerHTML.length);
        console.log('[Profile Modal] Planner collections count:', plannerCollections.length);
        plannerContainer.innerHTML = plannerHTML;

        // Render Knowledge Collections
        const knowledgeHTML = knowledgeCollections.length > 0
            ? knowledgeCollections.map(coll => createCollectionEntry(coll, false)).join('')
            : '<span class="text-gray-400 text-sm px-3 py-2 block">No knowledge repositories found.</span>';
        console.log('[Profile Modal] Knowledge HTML length:', knowledgeHTML.length);
        console.log('[Profile Modal] Knowledge collections count:', knowledgeCollections.length);
        knowledgeContainer.innerHTML = knowledgeHTML;

        // Update reranking list after collections change
        updateRerankingList();
    };

    // Initial render
    renderCollections();

    // NOW set the MCP select onchange handler (after renderCollections is defined)
    mcpSelect.onchange = () => {
        populateResources(mcpSelect.value);
        // Re-render collections to update default collection for new MCP server
        renderCollections();
    };

    // Update reranking list when knowledge collection checkboxes change
    knowledgeContainer.addEventListener('change', (e) => {
        if (e.target.dataset.collectionType === 'query') {
            updateRerankingList();
        }
    });

    // Set profile name, tag and description
    const profileNameInput = modal.querySelector('#profile-modal-name');
    const profileTagInput = modal.querySelector('#profile-modal-tag');
    const profileDescInput = modal.querySelector('#profile-modal-description');
    
    profileNameInput.value = profile ? (profile.name || '') : '';
    profileTagInput.value = profile ? (profile.tag || '').replace('@', '') : '';
    profileDescInput.value = profile ? profile.description : '';

    // Set session primer fields
    const sessionPrimerCheckbox = modal.querySelector('#profile-modal-enable-primer');
    const sessionPrimerContainer = modal.querySelector('#profile-modal-primer-container');
    const sessionPrimerTextarea = modal.querySelector('#profile-modal-primer');

    if (sessionPrimerCheckbox && sessionPrimerContainer && sessionPrimerTextarea) {
        const hasPrimer = profile && profile.session_primer;
        sessionPrimerCheckbox.checked = hasPrimer;
        sessionPrimerContainer.classList.toggle('hidden', !hasPrimer);
        sessionPrimerTextarea.value = hasPrimer ? profile.session_primer : '';

        // Add change handler for checkbox (remove old handler first to avoid duplicates)
        sessionPrimerCheckbox.onchange = () => {
            sessionPrimerContainer.classList.toggle('hidden', !sessionPrimerCheckbox.checked);
            if (!sessionPrimerCheckbox.checked) {
                sessionPrimerTextarea.value = '';
            }
        };
    }

    // Set advanced knowledge configuration fields
    const minRelevanceInput = modal.querySelector('#profile-modal-min-relevance');
    const maxDocsInput = modal.querySelector('#profile-modal-max-docs');
    const maxTokensInput = modal.querySelector('#profile-modal-max-tokens');
    const minRelevanceLockedBadge = modal.querySelector('#profile-knowledge-min-relevance-locked-badge');
    const maxDocsLockedBadge = modal.querySelector('#profile-knowledge-max-docs-locked-badge');
    const maxTokensLockedBadge = modal.querySelector('#profile-knowledge-max-tokens-locked-badge');

    // Fetch global settings from database to check for locks and set placeholders
    let knowledgeGlobalSettings = {};
    try {
        const token = localStorage.getItem('jwt_token');
        if (token) {
            const response = await fetch('/api/v1/admin/knowledge-global-settings', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (response.ok) {
                const data = await response.json();
                knowledgeGlobalSettings = data.settings || {};
            }
        }
    } catch (error) {
        console.warn('[Profile Modal] Failed to fetch global knowledge settings:', error);
    }

    // Configure min relevance score
    if (minRelevanceInput) {
        const isLocked = knowledgeGlobalSettings.minRelevanceScore?.is_locked || false;
        const globalValue = knowledgeGlobalSettings.minRelevanceScore?.value ?? 0.30;
        const profileValue = profile?.knowledgeConfig?.minRelevanceScore;

        if (isLocked) {
            minRelevanceInput.value = globalValue;
            minRelevanceInput.disabled = true;
            if (minRelevanceLockedBadge) minRelevanceLockedBadge.classList.remove('hidden');
        } else {
            minRelevanceInput.value = profileValue !== undefined ? profileValue : '';
            minRelevanceInput.placeholder = String(globalValue);
            minRelevanceInput.disabled = false;
            if (minRelevanceLockedBadge) minRelevanceLockedBadge.classList.add('hidden');
        }
    }

    // Configure max docs
    if (maxDocsInput) {
        const isLocked = knowledgeGlobalSettings.maxDocs?.is_locked || false;
        const globalValue = knowledgeGlobalSettings.maxDocs?.value ?? 3;
        const profileValue = profile?.knowledgeConfig?.maxDocs;

        if (isLocked) {
            maxDocsInput.value = globalValue;
            maxDocsInput.disabled = true;
            if (maxDocsLockedBadge) maxDocsLockedBadge.classList.remove('hidden');
        } else {
            maxDocsInput.value = profileValue !== undefined ? profileValue : '';
            maxDocsInput.placeholder = String(globalValue);
            maxDocsInput.disabled = false;
            if (maxDocsLockedBadge) maxDocsLockedBadge.classList.add('hidden');
        }
    }

    // Configure max tokens
    if (maxTokensInput) {
        const isLocked = knowledgeGlobalSettings.maxTokens?.is_locked || false;
        const globalValue = knowledgeGlobalSettings.maxTokens?.value ?? 2000;
        const profileValue = profile?.knowledgeConfig?.maxTokens;

        if (isLocked) {
            maxTokensInput.value = globalValue;
            maxTokensInput.disabled = true;
            if (maxTokensLockedBadge) maxTokensLockedBadge.classList.remove('hidden');
        } else {
            maxTokensInput.value = profileValue !== undefined ? profileValue : '';
            maxTokensInput.placeholder = String(globalValue);
            maxTokensInput.disabled = false;
            if (maxTokensLockedBadge) maxTokensLockedBadge.classList.add('hidden');
        }
    }

    console.log('[Profile Modal] Knowledge settings loaded - global:', knowledgeGlobalSettings, 'profile:', profile?.knowledgeConfig);

    // Tag generation function
    function generateTag() {
        const llmConfig = configState.llmConfigurations.find(c => c.id === llmSelect.value);
        const mcpServer = configState.mcpServers.find(s => s.id === mcpSelect.value);
        const profileName = profileNameInput.value.trim();
        const currentProfileType = modal.querySelector('input[name="profile-type"]:checked')?.value || 'tool_enabled';

        // For llm_only and rag_focused profiles, mcpServer is optional
        if (!llmConfig || !profileName) {
            return '';
        }

        // For tool_enabled profiles, mcpServer is required
        if (currentProfileType === 'tool_enabled' && !mcpServer) {
            return '';
        }

        // Extract characters: 2 from profile name, 1 from provider, 1 from model, 1 from server (if available)
        const namePart = profileName.substring(0, 2).toUpperCase();
        const providerPart = (llmConfig.provider || '').substring(0, 1).toUpperCase();
        const modelPart = (llmConfig.model || '').substring(0, 1).toUpperCase();
        const serverPart = mcpServer ? (mcpServer.name || '').substring(0, 1).toUpperCase() : '';

        let tag = (namePart + providerPart + modelPart + serverPart).substring(0, 5);

        // Ensure uniqueness
        let suffix = '';
        let counter = 1;
        while (configState.profiles.some(p => p.id !== profileId && p.tag === tag + suffix)) {
            suffix = counter.toString();
            counter++;
        }

        return tag + suffix;
    }

    // Auto-generate tag when LLM/MCP changes (only for new profiles)
    if (!isEdit) {
        // Auto-generate when LLM or MCP changes (only if tag is empty)
        const autoGenerate = () => {
            if (!profileTagInput.value.trim()) {
                profileTagInput.value = generateTag();
            }
        };
        llmSelect.addEventListener('change', autoGenerate);
        mcpSelect.addEventListener('change', autoGenerate);
    }

    // Manual tag generation button
    const generateTagBtn = modal.querySelector('#profile-modal-generate-tag');
    if (generateTagBtn) {
        generateTagBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            profileTagInput.value = generateTag();
        };
    }

    // Force uppercase on tag input
    profileTagInput.addEventListener('input', (e) => {
        e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').substring(0, 5);
    });

    // Check if user is privileged to see system prompts tab
    const isPrivileged = Utils.isPrivilegedUser();
    
    // Populate system prompts configuration (only for privileged users)
    if (isPrivileged) {
        await populateSystemPrompts(modal, profile);
    }

    // Show the modal
    modal.classList.remove('hidden');

    // Tab switching logic for MCP Resources, Intelligence Collections, and System Prompts
    const mcpResourcesTab = modal.querySelector('#profile-tab-mcp-resources');
    const intelligenceTab = modal.querySelector('#profile-tab-intelligence');
    const systemPromptsTab = modal.querySelector('#profile-tab-system-prompts');
    const mcpResourcesContent = modal.querySelector('#profile-content-mcp-resources');
    const intelligenceContent = modal.querySelector('#profile-content-intelligence');
    const systemPromptsContent = modal.querySelector('#profile-content-system-prompts');

    // Hide System Prompts tab for non-privileged users
    if (!isPrivileged && systemPromptsTab) {
        systemPromptsTab.style.display = 'none';
        if (systemPromptsContent) {
            systemPromptsContent.style.display = 'none';
        }
    }

    const allTabs = [mcpResourcesTab, intelligenceTab, systemPromptsTab].filter(tab => tab && tab.style.display !== 'none');
    const allContents = [mcpResourcesContent, intelligenceContent, systemPromptsContent].filter((content, index) => {
        const correspondingTab = [mcpResourcesTab, intelligenceTab, systemPromptsTab][index];
        return content && correspondingTab && correspondingTab.style.display !== 'none';
    });

    const switchToTab = (activeTab, activeContent) => {
        allTabs.forEach((tab, index) => {
            if (tab === activeTab) {
                // Update active tab styles with enhanced industrial design
                tab.classList.remove('border-transparent', 'text-gray-400', 'hover:bg-gray-800/40', 'hover:border-gray-600/50');
                tab.classList.add('border-[#F15F22]', 'text-white', 'bg-gradient-to-b', 'from-gray-800/70', 'to-gray-900/50', 'shadow-lg', 'relative');

                // Add the gradient underline if it doesn't exist
                if (!tab.querySelector('.absolute.inset-x-0.bottom-0')) {
                    const underline = document.createElement('div');
                    underline.className = 'absolute inset-x-0 bottom-0 h-0.5 bg-gradient-to-r from-[#F15F22] to-[#D9501A] shadow-lg shadow-orange-500/50';
                    tab.appendChild(underline);
                }

                // CRITICAL FIX: Show content - remove both hidden class AND inline display style
                allContents[index].classList.remove('hidden');
                allContents[index].style.display = '';
            } else {
                // Update inactive tab styles
                tab.classList.remove('border-[#F15F22]', 'text-white', 'bg-gradient-to-b', 'from-gray-800/70', 'to-gray-900/50', 'shadow-lg', 'relative');
                tab.classList.add('border-transparent', 'text-gray-400', 'hover:bg-gray-800/40', 'hover:border-gray-600/50');

                // Remove gradient underline from inactive tab
                const underline = tab.querySelector('.absolute.inset-x-0.bottom-0');
                if (underline) {
                    underline.remove();
                }

                // Hide content
                allContents[index].classList.add('hidden');
            }
        });
    };

    if (mcpResourcesTab && intelligenceTab && systemPromptsTab) {
        mcpResourcesTab.onclick = () => switchToTab(mcpResourcesTab, mcpResourcesContent);
        intelligenceTab.onclick = () => switchToTab(intelligenceTab, intelligenceContent);
        systemPromptsTab.onclick = () => switchToTab(systemPromptsTab, systemPromptsContent);
    }

    // Attach event listeners for uncheck all buttons
    const toolsUncheckBtn = modal.querySelector('#profile-modal-tools-uncheck-all');
    const promptsUncheckBtn = modal.querySelector('#profile-modal-prompts-uncheck-all');
    
    if (toolsUncheckBtn) {
        toolsUncheckBtn.onclick = () => {
            toolsContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
        };
    }
    
    if (promptsUncheckBtn) {
        promptsUncheckBtn.onclick = () => {
            promptsContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
        };
    }

    // Attach event listeners for save/cancel
    modal.querySelector('#profile-modal-cancel').onclick = () => modal.classList.add('hidden');
    modal.querySelector('#profile-modal-save').onclick = async () => {
        const name = modal.querySelector('#profile-modal-name').value.trim();
        const tag = modal.querySelector('#profile-modal-tag').value.trim().toUpperCase();
        const description = modal.querySelector('#profile-modal-description').value.trim();

        if (!name) {
            showNotification('error', 'Profile name is required');
            return;
        }

        if (!tag) {
            showNotification('error', 'Profile tag is required');
            return;
        }

        // Validate tag uniqueness
        if (configState.profiles.some(p => p.id !== profileId && p.tag === tag)) {
            showNotification('error', `Tag "${tag}" is already in use. Please choose a different tag.`);
            return;
        }
        
        const selectedTools = Array.from(toolsContainer.querySelectorAll('input:checked')).map(cb => cb.value);
        const selectedPrompts = Array.from(promptsContainer.querySelectorAll('input:checked')).map(cb => cb.value);
        
        // Collect query-enabled collections from both Planner and Knowledge repositories
        const plannerQueryCheckboxes = plannerContainer.querySelectorAll('input[data-collection-type="query"]:checked');
        const knowledgeQueryCheckboxes = knowledgeContainer.querySelectorAll('input[data-collection-type="query"]:checked');
        const selectedRag = [
            ...Array.from(plannerQueryCheckboxes).map(cb => parseInt(cb.dataset.collectionId)),
            ...Array.from(knowledgeQueryCheckboxes).map(cb => parseInt(cb.dataset.collectionId))
        ];

        // CRITICAL: Ensure the default collection is always included (defensive check)
        // The default collection checkbox should be disabled, but add this as a safety net
        if (defaultCollectionId !== null && !selectedRag.includes(defaultCollectionId)) {
            selectedRag.push(defaultCollectionId);
            console.log('[Profile Modal] Added default collection', defaultCollectionId, 'to selectedRag (defensive check)');
        }
        
        // Collect autocomplete-enabled collections from both Planner and Knowledge repositories
        const plannerAutocompleteCheckboxes = plannerContainer.querySelectorAll('input[data-collection-type="autocomplete"]:checked');
        const knowledgeAutocompleteCheckboxes = knowledgeContainer.querySelectorAll('input[data-collection-type="autocomplete"]:checked');
        const selectedAutocomplete = [
            ...Array.from(plannerAutocompleteCheckboxes).map(cb => parseInt(cb.dataset.collectionId)),
            ...Array.from(knowledgeAutocompleteCheckboxes).map(cb => parseInt(cb.dataset.collectionId))
        ];
        
        // Get selected classification mode
        const classificationModeRadio = modal.querySelector('input[name="classification-mode"]:checked');
        const classificationMode = classificationModeRadio ? classificationModeRadio.value : 'full';

        // Get selected profile type FIRST (needed for knowledgeConfig decision)
        const profileTypeRadio = modal.querySelector('input[name="profile-type"]:checked');
        const selectedProfileType = profileTypeRadio ? profileTypeRadio.value : 'tool_enabled';

        // Build knowledgeConfig object with per-collection reranking settings
        // Note: Global knowledge settings (minRelevance, maxDocs, maxTokens) are now in Administration panel
        // We still include them in the profile for backward compatibility; backend will use these or fall back to admin defaults
        const selectedKnowledgeIds = Array.from(knowledgeQueryCheckboxes).map(cb => parseInt(cb.dataset.collectionId));
        const rerankingListContainer = modal.querySelector('#profile-modal-knowledge-reranking-list');
        const rerankingCheckboxes = rerankingListContainer ? rerankingListContainer.querySelectorAll('input[data-reranking="true"]') : [];
        const collectionsWithReranking = Array.from(rerankingCheckboxes).map(cb => ({
            id: parseInt(cb.dataset.collectionId),
            reranking: cb.checked
        }));

        // Read advanced knowledge configuration fields
        const minRelevanceInput = modal.querySelector('#profile-modal-min-relevance');
        const maxDocsInput = modal.querySelector('#profile-modal-max-docs');
        const maxTokensInput = modal.querySelector('#profile-modal-max-tokens');

        // Check if knowledge is enabled based on profile type and capability checkbox
        // - rag_focused: always enabled
        // - llm_only: enabled only if useKnowledgeCollections checkbox is checked
        // - tool_enabled, genie: disabled
        const useKnowledgeCheckboxForConfig = modal.querySelector('#profile-modal-use-knowledge');
        const knowledgeEnabled = selectedProfileType === 'rag_focused' ||
            (selectedProfileType === 'llm_only' && useKnowledgeCheckboxForConfig?.checked);
        const knowledgeConfig = {
            enabled: knowledgeEnabled,
            collections: knowledgeEnabled ? collectionsWithReranking : []
        };

        // Add optional fields only if knowledge is enabled and user specified them (non-empty)
        if (knowledgeEnabled) {
            if (minRelevanceInput.value !== '') {
                const minRel = parseFloat(minRelevanceInput.value);
                if (!isNaN(minRel) && minRel >= 0 && minRel <= 1) {
                    knowledgeConfig.minRelevanceScore = minRel;
                }
            }

            if (maxDocsInput.value !== '') {
                const maxDocs = parseInt(maxDocsInput.value);
                if (!isNaN(maxDocs) && maxDocs >= 1) {
                    knowledgeConfig.maxDocs = maxDocs;
                }
            }

            if (maxTokensInput.value !== '') {
                const maxTokens = parseInt(maxTokensInput.value);
                if (!isNaN(maxTokens) && maxTokens >= 500) {
                    knowledgeConfig.maxTokens = maxTokens;
                }
            }
        }

        // Collect Genie child profiles and settings if this is a genie profile
        let genieConfig = null;
        if (selectedProfileType === 'genie') {
            const slaveCheckboxes = modal.querySelectorAll('.genie-slave-checkbox:checked');
            const selectedSlaveProfiles = Array.from(slaveCheckboxes).map(cb => cb.value);

            if (selectedSlaveProfiles.length === 0) {
                showNotification('error', 'Genie profiles require at least 1 child profile.');
                return;  // Prevent save
            }

            genieConfig = {
                slaveProfiles: selectedSlaveProfiles,
                maxConcurrentSlaves: 3  // Default value
            };

            // Collect optional Genie settings (temperature, queryTimeout, maxIterations)
            // Only include if not locked and user provided a value
            const tempSlider = modal.querySelector('#profile-genie-temperature');
            const timeoutInput = modal.querySelector('#profile-genie-query-timeout');
            const iterInput = modal.querySelector('#profile-genie-max-iterations');

            // Temperature - only save if not disabled (not locked) and different from placeholder
            if (tempSlider && !tempSlider.disabled) {
                const tempVal = parseFloat(tempSlider.value);
                if (!isNaN(tempVal)) {
                    genieConfig.temperature = tempVal;
                }
            }

            // Query timeout - only save if not disabled (not locked) and user provided a value
            if (timeoutInput && !timeoutInput.disabled && timeoutInput.value !== '') {
                const timeoutVal = parseInt(timeoutInput.value);
                if (!isNaN(timeoutVal) && timeoutVal >= 60 && timeoutVal <= 900) {
                    genieConfig.queryTimeout = timeoutVal;
                }
            }

            // Max iterations - only save if not disabled (not locked) and user provided a value
            if (iterInput && !iterInput.disabled && iterInput.value !== '') {
                const iterVal = parseInt(iterInput.value);
                if (!isNaN(iterVal) && iterVal >= 1 && iterVal <= 25) {
                    genieConfig.maxIterations = iterVal;
                }
            }
        }

        // Get capability checkbox states for llm_only profiles
        const useMcpToolsCheckbox = modal.querySelector('#profile-modal-use-mcp-tools');
        const useKnowledgeCheckbox = modal.querySelector('#profile-modal-use-knowledge');
        const useMcpTools = selectedProfileType === 'llm_only' && useMcpToolsCheckbox?.checked || false;
        const useKnowledgeCollections = selectedProfileType === 'llm_only' && useKnowledgeCheckbox?.checked || false;

        // Get session primer value (only if checkbox is checked and textarea has content)
        const sessionPrimerCheckbox = modal.querySelector('#profile-modal-enable-primer');
        const sessionPrimerTextarea = modal.querySelector('#profile-modal-primer');
        const sessionPrimerValue = (sessionPrimerCheckbox?.checked && sessionPrimerTextarea?.value.trim())
            ? sessionPrimerTextarea.value.trim()
            : null;

        const profileData = {
            id: profile ? profile.id : `profile-${generateId()}`,
            name,
            tag,
            description,
            profile_type: selectedProfileType,
            llmConfigurationId: llmSelect.value,
            mcpServerId: (selectedProfileType === 'genie' || (selectedProfileType === 'llm_only' && !useMcpTools)) ? null : mcpSelect.value,
            classification_mode: classificationMode,
            tools: selectedTools.length === allTools.length ? ['*'] : selectedTools,
            prompts: selectedPrompts.length === allPrompts.length ? ['*'] : selectedPrompts,
            ragCollections: selectedRag,  // Always save explicit IDs (no wildcard)
            autocompleteCollections: selectedAutocomplete,  // Always save explicit IDs (no wildcard)
            knowledgeConfig: knowledgeConfig,
            genieConfig: genieConfig,  // Will be null for non-genie profiles
            // Conversation capability flags (only relevant for llm_only profiles)
            useMcpTools: useMcpTools,
            useKnowledgeCollections: useKnowledgeCollections,
            // Session primer - auto-execute question when starting a new session
            session_primer: sessionPrimerValue
        };
        
        // For new profiles: if a default profile exists, enable inherit_classification by default
        if (!isEdit && configState.defaultProfileId) {
            profileData.inherit_classification = true;
        }

        // Collect system prompt mappings from the third tab
        const systemPromptMappings = [];
        const systemPromptsContent = modal.querySelector('#profile-content-system-prompts');
        console.log('[Save Profile] System prompts content element:', systemPromptsContent);
        if (systemPromptsContent) {
            const dropdowns = systemPromptsContent.querySelectorAll('select[data-category][data-subcategory]');
            console.log('[Save Profile] Found', dropdowns.length, 'prompt mapping dropdowns');
            dropdowns.forEach(select => {
                const value = select.value;
                const category = select.dataset.category;
                const subcategory = select.dataset.subcategory;
                console.log(`[Save Profile] Dropdown ${category}/${subcategory}: value="${value}"`);
                
                // Include ALL dropdowns in the payload
                // Empty value means "delete mapping" (revert to system default)
                // Non-empty value means "set mapping" (use custom prompt)
                systemPromptMappings.push({
                    category: category,
                    subcategory: subcategory,
                    prompt_name: value,  // Empty string for delete, prompt name for set
                    action: value ? 'set' : 'delete'  // Explicit action for backend
                });
                
                if (value) {
                    console.log(`[Save Profile] Will SET mapping: ${category}/${subcategory} -> ${value}`);
                } else {
                    console.log(`[Save Profile] Will DELETE mapping: ${category}/${subcategory} (revert to default)`);
                }
            });
        } else {
            console.warn('[Save Profile] System prompts content element not found');
        }
        console.log('[Save Profile] Total mappings to process:', systemPromptMappings.length, systemPromptMappings);

        // Validate RAG focused profiles REQUIRE at least 1 knowledge collection
        if (selectedProfileType === 'rag_focused') {
            const knowledgeCollections = knowledgeConfig.collections || [];
            if (knowledgeCollections.length === 0) {
                showNotification('error', 'RAG focused profiles require at least 1 knowledge collection.');
                return;  // Prevent save
            }
        }

        try {
            if (isEdit) {
                // Get the current state before update
                const profileBeforeUpdate = configState.profiles.find(p => p.id === profileId);
                const hadReclassificationFlag = profileBeforeUpdate?.needs_reclassification || false;
                
                await configState.updateProfile(profileId, profileData);
                
                // Save system prompt mappings
                if (systemPromptMappings.length > 0) {
                    try {
                        const token = localStorage.getItem('tda_auth_token');
                        const mappingsResponse = await fetch(`/api/v1/system-prompts/profiles/${profileId}/mappings`, {
                            method: 'POST',
                            headers: {
                                'Authorization': `Bearer ${token}`,
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({ mappings: systemPromptMappings })
                        });
                        
                        if (!mappingsResponse.ok) {
                            console.warn('Failed to save prompt mappings:', await mappingsResponse.text());
                        }
                    } catch (err) {
                        console.error('Error saving prompt mappings:', err);
                    }
                }
                
                // Reload profiles to get updated needs_reclassification flag from backend
                await configState.loadProfiles();
                
                // Clear test status since profile has been modified
                delete configState.profileTestStatus[profileId];
                
                // Check if reclassification flag was newly set during this update
                const updatedProfile = configState.profiles.find(p => p.id === profileId);
                const hasReclassificationFlag = updatedProfile?.needs_reclassification || false;
                const flagWasNewlySet = !hadReclassificationFlag && hasReclassificationFlag;
                
                console.log('[Profile Update] Before:', hadReclassificationFlag, 'After:', hasReclassificationFlag, 'Newly set:', flagWasNewlySet);
                
                renderProfiles();
                renderLLMProviders(); // Re-render to update default/active badges
                renderMCPServers(); // Re-render to update default/active badges
                modal.classList.add('hidden');
                
                if (flagWasNewlySet) {
                    showNotification('warning', 'Profile updated - Reclassification recommended. Please test the profile before activating.');
                } else {
                    showNotification('success', 'Profile updated successfully. Please test the profile before activating.');
                }
            } else {
                await configState.addProfile(profileData);
                
                // Get the new profile ID to save mappings
                const newProfile = configState.profiles.find(p => p.name === name && p.tag === tag);
                if (newProfile && systemPromptMappings.length > 0) {
                    try {
                        const token = localStorage.getItem('tda_auth_token');
                        const mappingsResponse = await fetch(`/api/v1/system-prompts/profiles/${newProfile.id}/mappings`, {
                            method: 'POST',
                            headers: {
                                'Authorization': `Bearer ${token}`,
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({ mappings: systemPromptMappings })
                        });
                        
                        if (!mappingsResponse.ok) {
                            console.warn('Failed to save prompt mappings:', await mappingsResponse.text());
                        }
                    } catch (err) {
                        console.error('Error saving prompt mappings:', err);
                    }
                }
                
                renderProfiles();
                renderLLMProviders(); // Re-render to update default/active badges
                renderMCPServers(); // Re-render to update default/active badges
                modal.classList.add('hidden');
                showNotification('success', 'Profile added successfully');
            }
        } catch (error) {
            showNotification('error', error.message);
        }
    };

    // FINAL VISIBILITY UPDATE - Execute after all async initialization completes
    // This ensures the correct sections are hidden/shown based on profile type,
    // even if something changed the radio button state during initialization
    setTimeout(() => {
        // Use the profileType variable which includes defaultProfileType for new profiles
        const finalProfileType = profileType;
        console.log('[Profile Modal] Final visibility update with profileType:', finalProfileType);
        updateSectionVisibility(finalProfileType);
    }, 100); // Small delay to ensure all DOM updates are complete
}


export async function initializeConfigurationUI() {
    // Initialize tabs
    initializeConfigTabs();
    
    // Load MCP servers from backend first
    await configState.initialize();
    
    renderMCPServers();
    renderLLMProviders();
    renderProfiles();
    updateReconnectButton();
    
    // Load MCP classification setting
    await loadClassificationSetting();

    // Add MCP server button
    const addMCPBtn = document.getElementById('add-mcp-server-btn');
    if (addMCPBtn) {
        addMCPBtn.addEventListener('click', () => showMCPServerModal());
    }

    // Import MCP server button
    const importMCPBtn = document.getElementById('import-mcp-server-btn');
    if (importMCPBtn) {
        importMCPBtn.addEventListener('click', () => showImportMCPServerModal());
    }

    // Add LLM configuration button
    const addLLMConfigBtn = document.getElementById('add-llm-config-btn');
    if (addLLMConfigBtn) {
        addLLMConfigBtn.addEventListener('click', async () => await showLLMConfigurationModal());
    }

    // Add Profile button
    const addProfileBtn = document.getElementById('add-profile-btn');
    if (addProfileBtn) {
        addProfileBtn.addEventListener('click', () => {
            // Detect which profile type tab is currently active by checking visible content containers
            let defaultProfileType = 'tool_enabled'; // Default fallback

            // Check which content container is visible (not hidden)
            if (!document.getElementById('tool-profiles-container')?.classList.contains('hidden')) {
                defaultProfileType = 'tool_enabled';
            } else if (!document.getElementById('conversation-profiles-container')?.classList.contains('hidden')) {
                defaultProfileType = 'llm_only';
            } else if (!document.getElementById('rag-profiles-container')?.classList.contains('hidden')) {
                defaultProfileType = 'rag_focused';
            } else if (!document.getElementById('genie-profiles-container')?.classList.contains('hidden')) {
                defaultProfileType = 'genie';
            }

            console.log('[Add Profile] Detected active profile type:', defaultProfileType);
            showProfileModal(null, defaultProfileType);
        });
    }

    // Test All Profiles button
    const testAllProfilesBtn = document.getElementById('test-all-profiles-btn');
    if (testAllProfilesBtn) {
        testAllProfilesBtn.addEventListener('click', async () => {
            let activeIds = [...configState.activeForConsumptionProfileIds];
            for (const profile of configState.profiles) {
                const profileId = profile.id;
                const resultsContainer = document.getElementById(`test-results-${profileId}`);
                if (resultsContainer) {
                    resultsContainer.innerHTML = `<span class="text-yellow-400">Testing...</span>`;
                    try {
                        const result = await API.testProfile(profileId);
                        let html = '';
                        const all_successful = Object.values(result.results).every(r => r.status === 'success' || r.status === 'info');

                        for (const [key, value] of Object.entries(result.results)) {
                            let statusClass;
                            if (value.status === 'success') {
                                statusClass = 'text-green-400';
                            } else if (value.status === 'info') {
                                statusClass = 'text-blue-400';
                            } else if (value.status === 'warning') {
                                statusClass = 'text-yellow-400';
                            } else {
                                statusClass = 'text-red-400';
                            }
                            html += `<p class="${statusClass}">${value.message}</p>`;
                        }
                        resultsContainer.innerHTML = html;

                        // Update activeIds list based on result
                        if (all_successful) {
                            if (!activeIds.includes(profileId)) {
                                activeIds.push(profileId);
                            }
                        } else {
                            activeIds = activeIds.filter(id => id !== profileId);
                        }
                        
                        // Manually update the toggle switch state
                        const checkbox = document.querySelector(`input[data-action="toggle-active-consumption"][data-profile-id="${profileId}"]`);
                        if (checkbox) {
                            checkbox.checked = all_successful;
                        }

                    } catch (error) {
                        resultsContainer.innerHTML = `<span class="text-red-400">${error.message}</span>`;
                        // Also uncheck on API error
                        activeIds = activeIds.filter(id => id !== profileId);
                        const checkbox = document.querySelector(`input[data-action="toggle-active-consumption"][data-profile-id="${profileId}"]`);
                        if (checkbox) {
                            checkbox.checked = false;
                        }
                    }
                }
            }
            // Save the final state of all active profiles once at the end
            await configState.setActiveForConsumptionProfiles(activeIds);
        });
    }

    // Reconnect button - use centralized initialization
    const reconnectBtn = document.getElementById('reconnect-and-load-btn');
    if (reconnectBtn) {
        reconnectBtn.addEventListener('click', async () => {
            console.log('[SaveConnect] Button clicked - marking as saving');
            
            // Mark as saving FIRST, before any initialization
            // This must happen synchronously to prevent navigation blocking
            if (typeof markSaving === 'function') {
                markSaving();
                console.log('[SaveConnect] ✅ markSaving() called successfully');
            } else {
                console.error('[SaveConnect] ⚠️ markSaving is not a function:', typeof markSaving);
            }
            
            // Now proceed with initialization
            // Add cache buster to force reload
            const { initializeConversationMode } = await import(`../conversationInitializer.js?v=${Date.now()}`);
            await initializeConversationMode();
        });
    }
    
    // MCP Classification toggle
    const classificationCheckbox = document.getElementById('enable-mcp-classification');
    if (classificationCheckbox) {
        classificationCheckbox.addEventListener('change', async (e) => {
            await saveClassificationSetting(e.target.checked);
        });
    }

}
