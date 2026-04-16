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
    initialized: false,    // Full init: backend connected + sessions loaded (conversation ready)
    backendConnected: false, // Partial init: LLM/MCP connected (sufficient for repo constructors)
    inProgress: false,
    lastInitTimestamp: null,
    errors: [],
    testFailureDetail: null
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
export async function initializeConversationMode(silent = false) {
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
        await reconnectAndLoad(silent);
        
        // Additional step: Verify knowledge repositories are loaded
        await verifyRepositoriesLoaded();
        
        // Backend is connected (LLM + MCP) — sufficient for repository constructors
        initState.backendConnected = true;

        if (!silent) {
            // Full initialization: sessions are loaded and conversation view is ready
            initState.initialized = true;
            initState.lastInitTimestamp = Date.now();
        }
        initState.inProgress = false;

        console.log(silent
            ? '[ConversationInit] ✅ Backend connected (silent auto-init)'
            : '[ConversationInit] ✅ Full initialization complete');
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
    initState.backendConnected = false;
    initState.lastInitTimestamp = null;
    initState.errors = [];
    initState.testFailureDetail = null;
    console.log('[ConversationInit] Initialization state reset - will re-initialize on next conversation start');
}

/**
 * Auto-initialize silently if a default profile is already configured and activated.
 * Called on page load so repository constructors work without manual "Save & Connect".
 * Runs a live profile test first to catch expired credentials or unreachable servers.
 *
 * @returns {Promise<{success: boolean, reason: string|null, detail: string|null}>}
 */
export async function autoInitializeIfReady() {
    const configState = window.configState;

    if (!configState?.defaultProfileId) {
        console.log('[AutoInit] No default profile configured — skipping auto-init');
        return { success: false, reason: 'no_default_profile', detail: null };
    }

    const defaultProfile = configState.profiles?.find(p => p.id === configState.defaultProfileId);
    if (!defaultProfile) {
        console.log('[AutoInit] Default profile not found in profiles list — skipping auto-init');
        return { success: false, reason: 'no_default_profile', detail: null };
    }

    if (!defaultProfile.active_for_consumption) {
        console.log('[AutoInit] Default profile not yet activated — skipping auto-init');
        return { success: false, reason: 'profile_not_activated', detail: null };
    }

    // Live-test the profile before committing to initialization.
    // This catches expired LLM credentials, missing configs, etc.
    console.log('[AutoInit] Testing default profile before initializing...');
    try {
        const token = localStorage.getItem('tda_auth_token');
        const testResp = await fetch(`/api/v1/profiles/${defaultProfile.id}/test`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const testResult = await testResp.json();

        // Collect any error-level results from the test
        const errors = Object.entries(testResult.results || {})
            .filter(([, v]) => v.status === 'error')
            .map(([k, v]) => `${k}: ${v.message}`);

        if (errors.length > 0) {
            const detail = errors.join(' | ');
            console.warn('[AutoInit] Profile test failed:', detail);
            initState.testFailureDetail = detail;
            return { success: false, reason: 'test_failed', detail };
        }
    } catch (err) {
        // Non-fatal: network glitch shouldn't block init entirely.
        // Proceed and let /configure surface connectivity issues.
        console.warn('[AutoInit] Could not reach profile test endpoint:', err.message);
    }

    // Profile tested OK — initialize silently (no view switch, no session loading)
    console.log('[AutoInit] Default profile ready, auto-initializing silently...');
    const success = await initializeConversationMode(true);
    return { success, reason: success ? null : 'init_failed', detail: null };
}
