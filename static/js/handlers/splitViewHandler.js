/**
 * handlers/splitViewHandler.js
 *
 * Handles split view for accessing slave sessions during Genie coordination.
 * Provides a world-class side-by-side view without losing context.
 *
 * Features:
 * - CSS Grid-based split layout
 * - Draggable divider (30-70% range)
 * - Keyboard shortcut (Escape) to close
 * - Smooth animations
 */

import * as DOM from '../domElements.js';
import { state } from '../state.js';

// ============================================================================
// Split View State
// ============================================================================

export const splitViewState = {
    isActive: false,
    mainSessionId: null,
    slaveSessionId: null,
    slaveProfileTag: null,
    dividerPosition: 50,  // Percentage
    isDragging: false
};

// ============================================================================
// Initialization
// ============================================================================

/**
 * Initialize split view event listeners.
 * Should be called on page load.
 */
export function initSplitView() {
    // Listen for split view requests from genieHandler
    window.addEventListener('openGenieSplitView', handleOpenSplitView);

    // Keyboard shortcut to close (Escape)
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && splitViewState.isActive) {
            closeSplitView();
        }
    });

    console.log('[SplitView] Initialized');
}

// ============================================================================
// Split View Lifecycle
// ============================================================================

/**
 * Handle request to open split view.
 */
async function handleOpenSplitView(event) {
    const { sessionId, profileTag } = event.detail;

    if (!sessionId) {
        console.warn('[SplitView] No session ID provided');
        return;
    }

    console.log('[SplitView] Opening for session:', sessionId, 'profile:', profileTag);

    // Store current main session
    splitViewState.mainSessionId = state.currentSessionId;
    splitViewState.slaveSessionId = sessionId;
    splitViewState.slaveProfileTag = profileTag;

    // Create split view container if not exists
    let splitContainer = document.getElementById('split-view-container');
    if (!splitContainer) {
        splitContainer = createSplitViewContainer();
        const mainContentArea = document.getElementById('main-content-area') ||
                               document.getElementById('chat-area')?.parentElement;
        if (mainContentArea) {
            mainContentArea.appendChild(splitContainer);
        } else {
            document.body.appendChild(splitContainer);
        }
    }

    // Activate split view
    activateSplitView(profileTag);

    // Load slave session content
    await loadSlaveSessionContent(sessionId);
}

/**
 * Create the split view container structure.
 */
function createSplitViewContainer() {
    const container = document.createElement('div');
    container.id = 'split-view-container';
    container.className = 'split-view-container';

    container.innerHTML = `
        <div class="split-view-pane split-view-main" id="split-main-pane">
            <!-- Main session chat will be moved here -->
        </div>
        <div class="split-view-divider" id="split-divider">
            <div class="divider-handle"></div>
        </div>
        <div class="split-view-pane split-view-slave" id="split-slave-pane">
            <header class="split-slave-header">
                <div class="slave-session-info">
                    <span class="slave-badge">G</span>
                    <span class="slave-session-tag" id="split-slave-tag">@TAG</span>
                    <span class="slave-session-label">Slave Session</span>
                </div>
                <button class="split-close-btn" id="split-close-btn" title="Close split view (Esc)">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </header>
            <div class="split-slave-content" id="split-slave-content">
                <!-- Slave session conversation will be loaded here -->
            </div>
        </div>
    `;

    // Set up divider drag
    setupDividerDrag(container.querySelector('#split-divider'));

    // Set up close button
    container.querySelector('#split-close-btn').addEventListener('click', closeSplitView);

    return container;
}

/**
 * Set up draggable divider.
 */
function setupDividerDrag(divider) {
    if (!divider) return;

    const handleMouseDown = (e) => {
        splitViewState.isDragging = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    };

    const handleMouseMove = (e) => {
        if (!splitViewState.isDragging) return;

        const container = document.getElementById('split-view-container');
        if (!container) return;

        const rect = container.getBoundingClientRect();
        const percentage = ((e.clientX - rect.left) / rect.width) * 100;

        // Clamp between 30% and 70%
        const clamped = Math.max(30, Math.min(70, percentage));

        splitViewState.dividerPosition = clamped;
        updateDividerPosition(clamped);
    };

    const handleMouseUp = () => {
        if (splitViewState.isDragging) {
            splitViewState.isDragging = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    };

    divider.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    // Touch support
    divider.addEventListener('touchstart', (e) => {
        splitViewState.isDragging = true;
        e.preventDefault();
    }, { passive: false });

    document.addEventListener('touchmove', (e) => {
        if (!splitViewState.isDragging) return;

        const touch = e.touches[0];
        const container = document.getElementById('split-view-container');
        if (!container) return;

        const rect = container.getBoundingClientRect();
        const percentage = ((touch.clientX - rect.left) / rect.width) * 100;
        const clamped = Math.max(30, Math.min(70, percentage));

        splitViewState.dividerPosition = clamped;
        updateDividerPosition(clamped);
    }, { passive: true });

    document.addEventListener('touchend', () => {
        splitViewState.isDragging = false;
    });
}

/**
 * Update divider position via CSS custom property.
 */
function updateDividerPosition(percentage) {
    const container = document.getElementById('split-view-container');
    if (!container) return;

    container.style.setProperty('--split-position', `${percentage}%`);
}

/**
 * Activate split view layout.
 */
function activateSplitView(profileTag) {
    splitViewState.isActive = true;

    // Move chat container to main pane
    const mainPane = document.getElementById('split-main-pane');
    const chatContainer = document.getElementById('chat-container');

    if (mainPane && chatContainer) {
        mainPane.appendChild(chatContainer);
    }

    // Update slave tag
    const tagEl = document.getElementById('split-slave-tag');
    if (tagEl) {
        tagEl.textContent = `@${profileTag || 'SLAVE'}`;
    }

    // Show split container
    const splitContainer = document.getElementById('split-view-container');
    if (splitContainer) {
        splitContainer.classList.add('active');
    }

    // Add class to original chat area
    const chatArea = document.getElementById('chat-area');
    if (chatArea) {
        chatArea.classList.add('split-active');
    }

    // Set initial position
    updateDividerPosition(splitViewState.dividerPosition);

    console.log('[SplitView] Activated with position:', splitViewState.dividerPosition + '%');
}

/**
 * Load slave session content into right pane.
 */
async function loadSlaveSessionContent(sessionId) {
    const slaveContent = document.getElementById('split-slave-content');
    if (!slaveContent) return;

    // Show loading state
    slaveContent.innerHTML = `
        <div class="split-loading">
            <div class="loading-spinner"></div>
            <p>Loading slave session...</p>
        </div>
    `;

    try {
        // Fetch session conversation
        const authToken = state.authToken || localStorage.getItem('auth_token');
        const response = await fetch(`/api/v1/sessions/${sessionId}/conversation`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (!response.ok) {
            throw new Error(`Failed to load session: ${response.status}`);
        }

        const data = await response.json();
        const messages = data.messages || data.conversation || [];

        // Render conversation
        slaveContent.innerHTML = '';
        renderSlaveConversation(slaveContent, messages);

    } catch (error) {
        console.error('[SplitView] Error loading slave session:', error);
        slaveContent.innerHTML = `
            <div class="split-error">
                <p>Failed to load slave session</p>
                <p class="error-details">${error.message}</p>
                <button class="retry-btn" onclick="window.dispatchEvent(new CustomEvent('openGenieSplitView', {detail: {sessionId: '${sessionId}', profileTag: '${splitViewState.slaveProfileTag}'}}))">
                    Retry
                </button>
            </div>
        `;
    }
}

/**
 * Render slave conversation messages.
 */
function renderSlaveConversation(container, messages) {
    if (!messages || messages.length === 0) {
        container.innerHTML = `
            <div class="split-empty">
                <p>No messages in this session yet.</p>
            </div>
        `;
        return;
    }

    messages.forEach(msg => {
        const role = msg.role || 'assistant';
        const content = msg.content || msg.message || '';

        const msgEl = document.createElement('div');
        msgEl.className = `split-message ${role}`;

        // Sanitize content for display
        const displayContent = escapeHtml(content);

        msgEl.innerHTML = `
            <div class="split-msg-avatar">${role === 'user' ? 'U' : 'A'}</div>
            <div class="split-msg-content">${displayContent}</div>
        `;
        container.appendChild(msgEl);
    });

    // Scroll to bottom
    container.scrollTop = container.scrollHeight;
}

/**
 * Simple HTML escape function.
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Close split view and restore normal layout.
 */
export function closeSplitView() {
    if (!splitViewState.isActive) return;

    console.log('[SplitView] Closing');

    splitViewState.isActive = false;

    // Move chat container back to original location
    const chatArea = document.getElementById('chat-area');
    const chatContainer = document.getElementById('chat-container');

    if (chatArea && chatContainer) {
        chatArea.classList.remove('split-active');
        chatArea.appendChild(chatContainer);
    }

    // Hide split container
    const splitContainer = document.getElementById('split-view-container');
    if (splitContainer) {
        splitContainer.classList.remove('active');
    }

    // Clear state
    splitViewState.mainSessionId = null;
    splitViewState.slaveSessionId = null;
    splitViewState.slaveProfileTag = null;
}

/**
 * Check if split view is currently active.
 */
export function isSplitViewActive() {
    return splitViewState.isActive;
}

/**
 * Get split view state (for debugging/status).
 */
export function getSplitViewState() {
    return { ...splitViewState };
}

// Auto-initialize when DOM is ready
if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSplitView);
    } else {
        // DOM already loaded
        initSplitView();
    }
}
