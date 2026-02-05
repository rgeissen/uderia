/**
 * Configuration Dirty State Tracker
 * Prevents navigation away from Configuration pane when there are unsaved changes
 * 
 * Tracks changes to:
 * - MCP Server selection
 * - LLM Provider selection
 * - Profile configuration
 * - Advanced Settings
 * 
 * Only allows navigation via "Save & Connect" button or explicit discard
 */

import { showAppBanner } from './bannerSystem.js';

// State tracking
const dirtyState = {
    isDirty: false,
    originalState: null,
    trackedFields: new Map(),
    isInitialized: false,
    pendingNavigation: null,
    isSaving: false  // Flag to indicate save operation in progress
};

/**
 * Initialize dirty state tracking for configuration pane
 * Call this when configuration view is shown
 */
export function initializeConfigDirtyTracking() {
    if (dirtyState.isInitialized) {
        console.log('[ConfigDirty] Already initialized');
        return;
    }
    
    console.log('[ConfigDirty] Initializing dirty state tracking');
    
    // Capture initial state
    captureCurrentState();
    
    // Attach change listeners to all configuration inputs
    attachChangeListeners();
    
    dirtyState.isInitialized = true;
    dirtyState.isDirty = false;
    
    console.log('[ConfigDirty] ✅ Dirty state tracking initialized');
}

/**
 * Capture the current state of all configuration fields
 */
function captureCurrentState() {
    const state = {
        // MCP Server
        activeMcpServer: getSelectedValue('mcp-server-select'),
        
        // LLM Provider
        activeLlmProvider: getSelectedValue('llm-config-select'),
        
        // Default Profile
        defaultProfile: getDefaultProfileId(),
        
        // Profile configurations (all profiles)
        profiles: captureAllProfileStates(),
        
        // Advanced Settings (if visible)
        advancedSettings: captureAdvancedSettings()
    };
    
    dirtyState.originalState = state;
    dirtyState.trackedFields.clear();
    
    console.log('[ConfigDirty] Captured initial state:', state);
}

/**
 * Get selected value from a select element
 */
function getSelectedValue(elementId) {
    const element = document.getElementById(elementId);
    return element ? element.value : null;
}

/**
 * Get the default profile ID from configuration state
 */
function getDefaultProfileId() {
    // Access configState from configurationHandler
    if (window.configState) {
        return window.configState.defaultProfileId;
    }
    return null;
}

/**
 * Capture all profile configurations
 */
function captureAllProfileStates() {
    if (!window.configState || !window.configState.profiles) {
        return [];
    }
    
    // Deep clone profiles to capture current state
    return JSON.parse(JSON.stringify(window.configState.profiles));
}

/**
 * Capture advanced settings state
 */
function captureAdvancedSettings() {
    return {
        chartingIntensity: document.getElementById('charting-intensity')?.value || 'none'
    };
}

/**
 * Attach change listeners to all configuration inputs
 */
function attachChangeListeners() {
    // MCP Server select
    const mcpSelect = document.getElementById('mcp-server-select');
    if (mcpSelect) {
        mcpSelect.addEventListener('change', () => markDirty('mcp-server'));
    }
    
    // LLM Provider select
    const llmSelect = document.getElementById('llm-config-select');
    if (llmSelect) {
        llmSelect.addEventListener('change', () => markDirty('llm-provider'));
    }
    
    // Advanced Settings (TTS credentials now managed via dedicated save button)
    const chartingSelect = document.getElementById('charting-intensity');
    if (chartingSelect) {
        chartingSelect.addEventListener('change', () => markDirty('charting-intensity'));
    }
    
    // Profile changes are tracked via custom events from configurationHandler
    document.addEventListener('profile-modified', (e) => {
        console.log('[ConfigDirty] Profile modified event:', e.detail);
        markDirty('profile-' + e.detail.profileId);
    });
    
    document.addEventListener('default-profile-changed', (e) => {
        console.log('[ConfigDirty] Default profile changed event:', e.detail);
        markDirty('default-profile');
    });
    
    console.log('[ConfigDirty] Change listeners attached');
}

/**
 * Mark configuration as dirty
 */
function markDirty(field) {
    const wasDirty = dirtyState.isDirty;
    dirtyState.isDirty = true;
    dirtyState.trackedFields.set(field, Date.now());
    
    if (!wasDirty) {
        console.log('[ConfigDirty] ⚠️ Configuration is now DIRTY - changes detected in:', field);
        updateUIIndicators(true);
    } else {
        console.log('[ConfigDirty] Additional changes detected in:', field);
    }
}

/**
 * Mark that a save operation is starting
 * This allows navigation during the save process
 * Can be called even if dirty tracking isn't fully initialized
 */
export function markSaving() {
    console.log('[ConfigDirty] 💾 markSaving() called - BEFORE state:', { isDirty: dirtyState.isDirty, isSaving: dirtyState.isSaving });
    dirtyState.isSaving = true;
    dirtyState.isDirty = false;  // Also clear dirty flag immediately
    console.log('[ConfigDirty] 💾 markSaving() called - AFTER state:', { isDirty: dirtyState.isDirty, isSaving: dirtyState.isSaving });
    console.log('[ConfigDirty] 💾 Save operation started - navigation allowed');
    
    // Update UI immediately to reflect clean state
    updateUIIndicators(false);
}

/**
 * Mark configuration as clean (after successful save)
 */
export function markConfigClean() {
    const wasDirty = dirtyState.isDirty;
    dirtyState.isDirty = false;
    dirtyState.isSaving = false;  // Clear saving flag
    dirtyState.trackedFields.clear();
    
    // Recapture current state as the new baseline
    captureCurrentState();
    
    if (wasDirty) {
        console.log('[ConfigDirty] ✅ Configuration marked as CLEAN');
        updateUIIndicators(false);
    }
    
    // If there was a pending navigation, execute it now
    if (dirtyState.pendingNavigation) {
        console.log('[ConfigDirty] Executing pending navigation to:', dirtyState.pendingNavigation);
        const targetView = dirtyState.pendingNavigation;
        dirtyState.pendingNavigation = null;
        
        // Execute navigation after a brief delay to ensure state is clean
        setTimeout(async () => {
            const { handleViewSwitch } = await import('./ui.js');
            handleViewSwitch(targetView);
        }, 100);
    }
}

/**
 * Check if navigation is allowed
 * @param {string} targetView - The view user wants to navigate to
 * @returns {boolean} True if navigation is allowed
 */
export function canNavigateAway(targetView) {
    console.log('[ConfigDirty] 🔍 canNavigateAway() called:', { 
        targetView, 
        isDirty: dirtyState.isDirty, 
        isSaving: dirtyState.isSaving,
        isInitialized: dirtyState.isInitialized 
    });
    
    // Always allow navigation if:
    // 1. Configuration is not dirty
    // 2. Navigating within configuration view
    // 3. Save operation is in progress (Save & Connect clicked)
    if (!dirtyState.isDirty || targetView === 'credentials-view' || dirtyState.isSaving) {
        console.log('[ConfigDirty] ✅ Navigation ALLOWED');
        return true;
    }
    
    console.log('[ConfigDirty] ❌ Navigation blocked - unsaved changes detected');
    
    // Store the intended navigation target
    dirtyState.pendingNavigation = targetView;
    
    // Show warning banner
    showAppBanner(
        'You have unsaved changes in Configuration. Please click "Save & Connect" to save your changes, or discard them to navigate away.',
        'warning'
    );
    
    // Show discard button if not already visible
    showDiscardButton();
    
    return false;
}

/**
 * Update UI indicators to show dirty state
 */
function updateUIIndicators(isDirty) {
    // Add/remove visual indicator on Configuration menu item
    const configMenuItem = document.getElementById('view-switch-credentials');
    if (configMenuItem) {
        if (isDirty) {
            // Add dirty indicator (orange dot)
            if (!configMenuItem.querySelector('.dirty-indicator')) {
                const indicator = document.createElement('span');
                indicator.className = 'dirty-indicator inline-block w-2 h-2 bg-orange-500 rounded-full ml-2 animate-pulse';
                indicator.title = 'Unsaved changes';
                configMenuItem.appendChild(indicator);
            }
        } else {
            // Remove dirty indicator
            const indicator = configMenuItem.querySelector('.dirty-indicator');
            if (indicator) {
                indicator.remove();
            }
        }
    }
    
    // Update Save & Connect button appearance
    const saveButton = document.getElementById('reconnect-and-load-btn');
    const saveButtonText = document.getElementById('reconnect-button-text');
    if (saveButton && saveButtonText) {
        if (isDirty) {
            // Dirty: same industrial outline style, dirty state signaled by Discard button appearing
            saveButton.className = 'card-btn card-btn--lg card-btn--primary flex-1 flex items-center justify-center';
            saveButtonText.textContent = 'Save & Connect';
        } else {
            // Clean: primary outline, no extra emphasis
            saveButton.className = 'card-btn card-btn--lg card-btn--primary flex-1 flex items-center justify-center';
            saveButtonText.textContent = 'Save & Connect';
        }
    }
}

/**
 * Show discard changes button
 */
function showDiscardButton() {
    // Check if discard button already exists
    let discardBtn = document.getElementById('discard-config-changes-btn');
    
    if (!discardBtn) {
        // Create discard button in the action buttons container
        const buttonContainer = document.getElementById('config-action-buttons');
        const saveButton = document.getElementById('reconnect-and-load-btn');
        
        if (buttonContainer && saveButton) {
            discardBtn = document.createElement('button');
            discardBtn.id = 'discard-config-changes-btn';
            discardBtn.type = 'button';
            discardBtn.className = 'card-btn card-btn--lg card-btn--neutral';
            discardBtn.textContent = 'Discard Changes';
            
            discardBtn.addEventListener('click', handleDiscardChanges);
            
            // Insert before Save & Connect button (left position)
            buttonContainer.insertBefore(discardBtn, saveButton);
            console.log('[ConfigDirty] Discard button added');
        }
    }
    
    if (discardBtn) {
        discardBtn.classList.remove('hidden');
    }
}

/**
 * Hide discard changes button
 */
function hideDiscardButton() {
    const discardBtn = document.getElementById('discard-config-changes-btn');
    if (discardBtn) {
        discardBtn.classList.add('hidden');
    }
}

/**
 * Handle discard changes action
 */
function handleDiscardChanges() {
    console.log('[ConfigDirty] User chose to discard changes');
    
    // Show confirmation banner with action buttons
    showDiscardConfirmation();
}

/**
 * Show discard confirmation UI
 */
function showDiscardConfirmation() {
    // Use the existing delete confirmation banner system
    const banner = document.getElementById('delete-confirmation-banner');
    const messageEl = document.getElementById('delete-confirmation-message');
    const cancelBtn = document.getElementById('delete-confirmation-cancel');
    const okBtn = document.getElementById('delete-confirmation-ok');
    
    if (!banner || !messageEl || !cancelBtn || !okBtn) {
        console.error('[ConfigDirty] Confirmation banner elements not found, falling back to banner notification');
        // Fallback: just show a warning banner
        showAppBanner('Click "Discard Changes" again to confirm discarding all unsaved changes.', 'warning', 8000);
        
        // On second click, proceed with discard
        const discardBtn = document.getElementById('discard-config-changes-btn');
        if (discardBtn && !discardBtn.dataset.confirmRequested) {
            discardBtn.dataset.confirmRequested = 'true';
            discardBtn.textContent = 'Confirm Discard';
            discardBtn.classList.remove('bg-gray-600', 'hover:bg-gray-700');
            discardBtn.classList.add('bg-red-600', 'hover:bg-red-700');
            
            // Reset after 8 seconds
            setTimeout(() => {
                if (discardBtn.dataset.confirmRequested) {
                    delete discardBtn.dataset.confirmRequested;
                    discardBtn.textContent = 'Discard Changes';
                    discardBtn.classList.remove('bg-red-600', 'hover:bg-red-700');
                    discardBtn.classList.add('bg-gray-600', 'hover:bg-gray-700');
                }
            }, 8000);
        } else if (discardBtn && discardBtn.dataset.confirmRequested) {
            // Second click confirmed - proceed
            delete discardBtn.dataset.confirmRequested;
            executeDiscardChanges();
        }
        return;
    }
    
    // Set the confirmation message
    messageEl.textContent = 'Are you sure you want to discard all unsaved configuration changes? This cannot be undone.';
    
    // Show the banner
    banner.classList.remove('hidden');
    
    // Remove existing event listeners by cloning
    const newCancelBtn = cancelBtn.cloneNode(true);
    const newOkBtn = okBtn.cloneNode(true);
    cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
    okBtn.parentNode.replaceChild(newOkBtn, okBtn);
    
    // Hide banner function
    const hideBanner = () => {
        banner.classList.add('hidden');
    };
    
    // Cancel button - just hide the confirmation
    newCancelBtn.addEventListener('click', () => {
        hideBanner();
        showAppBanner('Discard cancelled. Your changes are still pending.', 'info');
    });
    
    // OK button - proceed with discard
    newOkBtn.addEventListener('click', () => {
        hideBanner();
        executeDiscardChanges();
    });
}

/**
 * Execute the discard changes action (after confirmation)
 */
function executeDiscardChanges() {
    console.log('[ConfigDirty] Executing discard changes');
    
    // Reload configuration from saved state
    reloadConfiguration();
    
    // Mark as clean
    markConfigClean();
    
    // Hide discard button
    hideDiscardButton();
    
    // Reset any confirm state
    const discardBtn = document.getElementById('discard-config-changes-btn');
    if (discardBtn) {
        delete discardBtn.dataset.confirmRequested;
        discardBtn.textContent = 'Discard Changes';
        discardBtn.classList.remove('bg-red-600', 'hover:bg-red-700');
        discardBtn.classList.add('bg-gray-600', 'hover:bg-gray-700');
    }
    
    showAppBanner('Changes discarded. Configuration restored to last saved state.', 'info');
    
    // If there was a pending navigation, execute it
    if (dirtyState.pendingNavigation) {
        const targetView = dirtyState.pendingNavigation;
        dirtyState.pendingNavigation = null;
        
        setTimeout(async () => {
            const { handleViewSwitch } = await import('./ui.js');
            handleViewSwitch(targetView);
        }, 100);
    }
}

/**
 * Reload configuration from last saved state
 */
function reloadConfiguration() {
    console.log('[ConfigDirty] Reloading configuration from saved state');
    
    // Trigger configuration reload via configurationHandler
    if (window.configState && window.configState.loadProfiles) {
        window.configState.loadProfiles();
    }
    
    // Reload MCP servers
    if (window.configState && window.configState.loadMCPServers) {
        window.configState.loadMCPServers();
    }
    
    // Reload LLM configurations
    if (window.configState && window.configState.loadLLMConfigurations) {
        window.configState.loadLLMConfigurations();
    }
    
    // Re-render UI
    if (window.renderProfiles) {
        window.renderProfiles();
    }
}

/**
 * Check if configuration is dirty
 */
export function isConfigDirty() {
    return dirtyState.isDirty;
}

/**
 * Reset dirty state tracking (when leaving configuration view after save)
 */
export function resetConfigDirtyTracking() {
    console.log('[ConfigDirty] Resetting dirty state tracking');
    dirtyState.isDirty = false;
    dirtyState.trackedFields.clear();
    dirtyState.pendingNavigation = null;
    dirtyState.isInitialized = false;
    updateUIIndicators(false);
    hideDiscardButton();
}

/**
 * Get detailed dirty state information (for debugging)
 */
export function getConfigDirtyState() {
    return {
        isDirty: dirtyState.isDirty,
        changedFields: Array.from(dirtyState.trackedFields.keys()),
        pendingNavigation: dirtyState.pendingNavigation,
        isInitialized: dirtyState.isInitialized
    };
}
