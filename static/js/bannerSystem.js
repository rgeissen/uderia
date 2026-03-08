/**
 * Centralized Banner System for TDA
 * 
 * Two distinct banner areas:
 * 1. Application-level banner (top navigation bar)
 * 2. Conversation-level banner (inside conversation pane)
 */

/**
 * Show application-level banner message
 * Location: Top navigation bar (next to "Uderia Platform" title)
 * 
 * Use for:
 * - Global configuration changes
 * - Authentication/authorization messages
 * - RAG operations (create/delete collections)
 * - Admin operations
 * - Credential management
 * - Access token management
 * - MCP server operations
 * 
 * @param {string} message - Message to display
 * @param {string} type - 'success', 'error', 'warning', or 'info'
 * @param {number} duration - Display duration in ms (default: 5000)
 */
// Reusable floating toast element (created once, reused)
let _toastEl = null;
let _toastTimeout = null;

export function showAppBanner(message, type = 'info', duration = 5000) {
    // Theme-aware colors using Tailwind classes that work with all themes
    const colors = {
        success: 'app-banner-success',
        error: 'app-banner-error',
        warning: 'app-banner-warning',
        info: 'app-banner-info'
    };

    // Detect if any modal overlay is currently visible
    // Matches: .tpl-modal-overlay (dynamic), *-modal-overlay (static), *-modal.fixed (e.g. profile-modal)
    const modalOpen = document.querySelector(
        '.tpl-modal-overlay, [id$="-modal-overlay"]:not(.hidden), [id$="-modal"].fixed:not(.hidden)'
    );

    if (modalOpen) {
        // ── Floating toast mode (above modals) ──
        _showToast(message, colors[type] || colors.info, duration);
    } else {
        // ── Inline navbar mode (original behavior) ──
        _dismissToast();   // clean up any lingering toast
        const statusElement = document.getElementById('header-status-message');
        if (!statusElement) {
            console.warn('[AppBanner] Element not found. Message:', message);
            return;
        }

        if (statusElement.hideTimeout) {
            clearTimeout(statusElement.hideTimeout);
        }

        statusElement.textContent = message;
        statusElement.className = `text-sm px-3 py-1 rounded-md transition-all duration-300 ${colors[type] || colors.info}`;
        statusElement.style.opacity = '1';

        statusElement.hideTimeout = setTimeout(() => {
            statusElement.style.opacity = '0';
            setTimeout(() => { statusElement.textContent = ''; }, 300);
        }, duration);
    }
}

function _showToast(message, colorClass, duration) {
    // Clear previous toast timeout
    if (_toastTimeout) { clearTimeout(_toastTimeout); _toastTimeout = null; }

    // Create or reuse toast element
    if (!_toastEl) {
        _toastEl = document.createElement('div');
        document.body.appendChild(_toastEl);
    }

    _toastEl.textContent = message;
    _toastEl.className = `app-banner-toast ${colorClass}`;

    // Trigger enter animation
    requestAnimationFrame(() => { _toastEl.classList.add('visible'); });

    // Auto-hide
    _toastTimeout = setTimeout(() => {
        _dismissToast();
    }, duration);
}

function _dismissToast() {
    if (_toastTimeout) { clearTimeout(_toastTimeout); _toastTimeout = null; }
    if (_toastEl) {
        _toastEl.classList.remove('visible');
        // Remove from DOM after fade-out
        setTimeout(() => {
            if (_toastEl) { _toastEl.remove(); _toastEl = null; }
        }, 350);
    }
}

/**
 * Show conversation-level banner message
 * Location: Inside the conversation pane (below profile selector)
 * 
 * Use for:
 * - Profile override warnings/errors
 * - Conversation-specific errors
 * - Query submission issues
 * - Context/history warnings
 * - Session-specific messages
 * 
 * @param {string} message - Message to display
 * @param {string} type - 'success', 'error', 'warning', or 'info'
 * @param {boolean} dismissible - Show close button (default: true)
 */
export function showConversationBanner(message, type = 'warning', dismissible = true) {
    const banner = document.getElementById('profile-override-warning-banner');
    const messageElement = document.getElementById('profile-override-warning-message');
    const dismissButton = document.getElementById('dismiss-profile-warning');
    
    if (!banner || !messageElement) {
        console.warn('[ConversationBanner] Elements not found. Message:', message);
        return;
    }
    
    // Style configurations
    const styles = {
        success: {
            bg: 'bg-green-500/20',
            border: 'border-green-400/50',
            icon: 'text-green-500',
            text: 'text-green-100'
        },
        error: {
            bg: 'bg-red-500/20',
            border: 'border-red-400/50',
            icon: 'text-red-500',
            text: 'text-red-100'
        },
        warning: {
            bg: 'bg-yellow-500/20',
            border: 'border-yellow-400/50',
            icon: 'text-yellow-500',
            text: 'text-yellow-100'
        },
        info: {
            bg: 'bg-blue-500/20',
            border: 'border-blue-400/50',
            icon: 'text-blue-500',
            text: 'text-blue-100'
        }
    };
    
    const style = styles[type] || styles.warning;
    
    // Update styling
    banner.className = `flex items-center gap-x-2 px-3 py-1 rounded-md ${style.bg} border ${style.border}`;
    
    // Update icon color
    const icon = banner.querySelector('svg');
    if (icon) {
        icon.className = `h-4 w-4 ${style.icon} flex-shrink-0`;
    }
    
    // Update message
    messageElement.textContent = message;
    messageElement.className = `text-xs ${style.text} font-medium`;
    
    // Show/hide dismiss button
    if (dismissButton) {
        dismissButton.style.display = dismissible ? 'block' : 'none';
    }
    
    // Show banner
    banner.classList.remove('hidden');
}

/**
 * Hide conversation-level banner
 */
export function hideConversationBanner() {
    const banner = document.getElementById('profile-override-warning-banner');
    if (banner) {
        banner.classList.add('hidden');
    }
}

/**
 * Hide application-level banner
 */
export function hideAppBanner() {
    const statusElement = document.getElementById('header-status-message');
    if (statusElement) {
        if (statusElement.hideTimeout) {
            clearTimeout(statusElement.hideTimeout);
        }
        statusElement.style.opacity = '0';
        setTimeout(() => {
            statusElement.textContent = '';
        }, 300);
    }
}

// Make functions available globally for backwards compatibility
window.showAppBanner = showAppBanner;
window.showConversationBanner = showConversationBanner;
window.hideConversationBanner = hideConversationBanner;
window.hideAppBanner = hideAppBanner;
