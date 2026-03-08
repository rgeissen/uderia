/**
 * Conversation Initializer
 * Central gate for ensuring conversation mode is properly initialized
 * 
 * This module wraps the existing reconnectAndLoad() function and ensures
 * consistent initialization regardless of entry point ("Start Conversation" or "Save & Connect").
 */

import { showAppBanner } from './bannerSystem.js';

// Initialization state tracking - make globally accessible for easy checking
const initState = {
    initialized: false,
    inProgress: false,
    lastInitTimestamp: null,
    errors: []
};

// Expose state globally for synchronous access (no dynamic imports needed)
window.__conversationInitState = initState;

/**
 * Main initialization function - Central entry point for conversation mode
 * Called from both "Start Conversation" (welcome screen) and "Save & Connect" (config screen)
 * 
 * This wraps the existing reconnectAndLoad() with consistent state management
 * 
 * @returns {Promise<boolean>} True if initialization succeeded
 */
export async function initializeConversationMode() {
    // If already initialized recently (within last 2 seconds), skip re-initialization
    if (initState.initialized && 
        initState.lastInitTimestamp && 
        (Date.now() - initState.lastInitTimestamp < 2000)) {
        console.log('[ConversationInit] Already initialized recently, skipping');
        return true;
    }
    
    // If initialization is in progress, wait for it
    if (initState.inProgress) {
        console.log('[ConversationInit] Initialization already in progress, waiting...');
        return await waitForInitialization();
    }
    
    // Start initialization
    initState.inProgress = true;
    initState.errors = [];
    console.log('[ConversationInit] Starting conversation initialization...');
    
    // Note: markSaving() is called by the button handler BEFORE this function is called
    // This ensures the dirty state is cleared synchronously
    
    try {
        // Import the existing reconnectAndLoad function which handles:
        // 1. Profile validation (default profile with MCP + LLM)
        // 2. MCP/LLM configuration validation
        // 3. Backend /configure request (which loads planner repositories)
        // 4. Resource loading (tools, prompts, resources)
        // 5. Session loading/creation
        // 6. View switching to conversation
        const { reconnectAndLoad } = await import('./handlers/configurationHandler.js');
        
        // Call the main initialization sequence
        await reconnectAndLoad();
        
        // Additional step: Verify knowledge repositories are loaded
        await verifyRepositoriesLoaded();
        
        // Mark as successfully initialized
        initState.initialized = true;
        initState.lastInitTimestamp = Date.now();
        initState.inProgress = false;
        
        console.log('[ConversationInit] ✅ Initialization complete');
        return true;
        
    } catch (error) {
        console.error('[ConversationInit] ❌ Initialization failed:', error);
        initState.initialized = false;
        initState.inProgress = false;
        initState.errors.push(error.message);
        
        // Show error banner
        showAppBanner(
            `Failed to initialize conversation: ${error.message}`,
            'error'
        );
        
        return false;
    }
}

/**
 * Verify that repositories (planner and knowledge) are properly loaded
 * This is a post-initialization check to ensure the RAG retriever has all collections
 */
async function verifyRepositoriesLoaded() {
    console.log('[ConversationInit] Verifying repository initialization...');
    
    try {
        // Get the default profile to check which repositories should be loaded
        const token = localStorage.getItem('tda_auth_token');
        const profileResponse = await fetch('/api/v1/profiles', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (!profileResponse.ok) {
            console.warn('[ConversationInit] Could not verify profiles');
            return; // Non-critical, continue
        }
        
        const profileData = await profileResponse.json();
        const defaultProfile = profileData.profiles?.find(p => p.id === profileData.default_profile_id);
        
        if (!defaultProfile) {
            console.warn('[ConversationInit] No default profile found');
            return; // Non-critical
        }
        
        // Check if knowledge collections are configured in profile
        const knowledgeCollections = defaultProfile.knowledgeConfig?.collections || [];
        const knowledgeEnabled = defaultProfile.knowledgeConfig?.enabled;
        
        if (knowledgeEnabled && knowledgeCollections.length > 0) {
            console.log(`[ConversationInit] Profile has ${knowledgeCollections.length} knowledge collection(s) configured`);
            
            // Trigger backend to ensure knowledge collections are loaded into RAG retriever
            // This endpoint should load the collections into memory if not already loaded
            const reloadResponse = await fetch('/api/v1/rag/reload-collections', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('tda_auth_token')}`
                }
            });
            
            if (reloadResponse.ok) {
                const result = await reloadResponse.json();
                console.log(`[ConversationInit] ✅ Repository reload complete: ${result.message || 'success'}`);
            } else {
                console.warn('[ConversationInit] ⚠️ Could not reload collections, but continuing...');
            }
        } else {
            console.log('[ConversationInit] No knowledge collections configured in profile');
        }
        
        // Check planner collections
        const plannerCollections = defaultProfile.ragCollections || [];
        if (plannerCollections.length > 0 || plannerCollections.includes('*')) {
            console.log('[ConversationInit] ✅ Planner repositories configured');
        }
        
    } catch (error) {
        // Non-critical error - log but don't fail initialization
        console.warn('[ConversationInit] ⚠️ Repository verification warning:', error.message);
    }
}

/**
 * Wait for ongoing initialization to complete
 */
function waitForInitialization() {
    return new Promise((resolve) => {
        const checkInterval = setInterval(() => {
            if (!initState.inProgress) {
                clearInterval(checkInterval);
                resolve(initState.initialized);
            }
        }, 100);
        
        // Timeout after 30 seconds
        setTimeout(() => {
            clearInterval(checkInterval);
            console.warn('[ConversationInit] Initialization timeout after 30 seconds');
            resolve(false);
        }, 30000);
    });
}

/**
 * Get current initialization state (for debugging)
 */
export function getInitializationState() {
    return { ...initState };
}

/**
 * Mark conversation as initialized (called after successful startup or reconnect)
 * Used when conversation mode is loaded through normal startup flow (page refresh)
 */
export function setInitialized() {
    initState.initialized = true;
    initState.lastInitTimestamp = Date.now();
    initState.inProgress = false;
    console.log('[ConversationInit] Marked as initialized');
}

/**
 * Force re-initialization (useful after config changes)
 * Call this after profile changes, server reconnections, etc.
 */
export function resetInitialization() {
    initState.initialized = false;
    initState.lastInitTimestamp = null;
    initState.errors = [];
    console.log('[ConversationInit] Initialization state reset - will re-initialize on next conversation start');
}
