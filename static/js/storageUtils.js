/**
 * storageUtils.js
 * Safe wrapper for localStorage with error handling
 */

/**
 * Safe localStorage.setItem with error handling
 * @param {string} key - The localStorage key
 * @param {string} value - The value to store
 */
export function safeSetItem(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (error) {
        console.error(`[Storage] Error setting localStorage key '${key}':`, error);
    }
}

/**
 * Safe localStorage.getItem with error handling
 * @param {string} key - The localStorage key
 * @returns {string|null} - The stored value or null
 */
export function safeGetItem(key) {
    try {
        return localStorage.getItem(key);
    } catch (error) {
        console.error(`[Storage] Error getting localStorage key '${key}':`, error);
        return null;
    }
}

/**
 * Safe localStorage.removeItem with error handling
 * @param {string} key - The localStorage key
 */
export function safeRemoveItem(key) {
    try {
        localStorage.removeItem(key);
    } catch (error) {
        console.error(`[Storage] Error removing localStorage key '${key}':`, error);
    }
}

/**
 * Clear all stored credentials from localStorage
 * This is useful when transitioning to non-persistent mode or for security
 */
export function clearAllCredentials() {
    const credentialKeys = [
        'mcpConfig',
        'amazonApiKey',
        'ollamaHost',
        'azureApiKey',
        'friendliApiKey',
        'googleApiKey',
        'openaiApiKey',
        'anthropicApiKey',
        'ttsCredentialsJson',
        'lastSelectedProvider'
    ];
    
    credentialKeys.forEach(key => {
        try {
            localStorage.removeItem(key);
        } catch (error) {
            console.error(`[Storage] Error clearing credential '${key}':`, error);
        }
    });
}
