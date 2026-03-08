/**
 * Industrial Hierarchy UI Helpers
 * Path highlighting and lineage visualization for blueprint-style session tree
 *
 * Features:
 * - Traverse parent-child relationships from any node to root
 * - Highlight entire lineage path on hover
 * - Debounced hover for performance
 * - Works with unlimited nesting depth
 */

/**
 * Get all sibling sessions (same parent)
 * @param {string} sessionId - Starting session ID
 * @returns {Array<string>} Array of session IDs that are siblings (including self)
 */
export function getSiblings(sessionId) {
    const wrapper = document.querySelector(`.genie-wrapper[data-session-id="${sessionId}"]`);
    if (!wrapper) return [sessionId];

    const parentId = wrapper.dataset.parentId;
    if (!parentId || parentId === 'null' || parentId === 'undefined') {
        return [sessionId];  // No siblings if no parent
    }

    // Find all wrappers with the same parent
    const siblings = Array.from(
        document.querySelectorAll(`.genie-wrapper[data-parent-id="${parentId}"]`)
    ).map(w => w.dataset.sessionId);

    return siblings;
}

/**
 * Highlight all sibling sessions (same parent, same level)
 * @param {string} sessionId - Session ID to start highlighting from
 * @param {boolean} isEnter - True to highlight, false to remove
 */
export function highlightSiblings(sessionId, isEnter = true) {
    const siblings = getSiblings(sessionId);

    // Highlight all sibling wrappers
    siblings.forEach(id => {
        const wrapper = document.querySelector(`.genie-wrapper[data-session-id="${id}"]`);
        if (wrapper) {
            if (isEnter) {
                wrapper.classList.add('path-highlighted');
            } else {
                wrapper.classList.remove('path-highlighted');
            }
        }
    });
}

/**
 * Track currently highlighted wrapper to prevent flickering when hovering over child elements
 */
let currentlyHighlightedWrapper = null;

/**
 * Debounced hover handler to prevent performance issues
 */
let hoverTimeout;
const HOVER_DEBOUNCE_MS = 50;  // 50ms debounce for smooth interaction

/**
 * Highlight siblings with debouncing
 * @param {string} sessionId - Session ID
 * @param {boolean} isEnter - True for enter, false for leave
 */
export function highlightSiblingsDebounced(sessionId, isEnter = true) {
    clearTimeout(hoverTimeout);

    if (isEnter) {
        // Debounce entry to avoid flickering on fast mouse movement
        hoverTimeout = setTimeout(() => {
            highlightSiblings(sessionId, true);
        }, HOVER_DEBOUNCE_MS);
    } else {
        // Immediate removal for snappy feedback
        highlightSiblings(sessionId, false);
    }
}

/**
 * Initialize hover listeners for sibling highlighting
 * Attaches event listeners to the document for efficient delegation
 * Prevents flickering by tracking which wrapper is currently hovered
 */
export function initializePathHighlighting() {
    // Track mouse movement and only update highlighting when moving between different wrappers
    document.addEventListener('mouseover', (e) => {
        const wrapper = e.target.closest('.genie-wrapper');

        // Only update if we've moved to a different wrapper (or first time)
        if (wrapper && wrapper.dataset.sessionId && wrapper !== currentlyHighlightedWrapper) {
            // Clear previous highlighting if exists
            if (currentlyHighlightedWrapper) {
                const prevSessionId = currentlyHighlightedWrapper.dataset.sessionId;
                if (prevSessionId) {
                    highlightSiblings(prevSessionId, false);
                }
            }

            // Apply new highlighting
            currentlyHighlightedWrapper = wrapper;
            highlightSiblingsDebounced(wrapper.dataset.sessionId, true);
        }
    });

    document.addEventListener('mouseout', (e) => {
        const wrapper = e.target.closest('.genie-wrapper');

        // Only clear if we're actually leaving the wrapper entirely
        if (wrapper && currentlyHighlightedWrapper === wrapper) {
            // Check where the mouse is going
            const relatedTarget = e.relatedTarget;
            const newWrapper = relatedTarget ? relatedTarget.closest('.genie-wrapper') : null;

            // Only clear if we're leaving the wrapper area entirely (not moving to another wrapper)
            if (!newWrapper) {
                const sessionId = currentlyHighlightedWrapper.dataset.sessionId;
                if (sessionId) {
                    highlightSiblingsDebounced(sessionId, false);
                    currentlyHighlightedWrapper = null;
                }
            }
        }
    });

    console.log('[HierarchyHelpers] Sibling highlighting initialized (no flicker)');
}

/**
 * Sync wrapper collapsed states on page load
 * Finds all wrappers containing hidden children and applies .genie-wrapper-collapsed class
 */
export function syncWrapperStates() {
    // Find all wrappers
    const allWrappers = document.querySelectorAll('.genie-wrapper');

    allWrappers.forEach(wrapper => {
        // Check if this wrapper contains a hidden child
        const hiddenChild = wrapper.querySelector('.genie-slave-hidden');

        if (hiddenChild) {
            // Apply collapsed state to wrapper
            wrapper.classList.add('genie-wrapper-collapsed');
        } else {
            // Ensure collapsed state is removed if child is not hidden
            wrapper.classList.remove('genie-wrapper-collapsed');
        }
    });

    console.log('[HierarchyHelpers] Wrapper states synchronized on page load');
}

/**
 * Get level info for a session (for debugging/tooltips)
 * @param {string} sessionId - Session ID
 * @returns {Object} Level information
 */
export function getSessionLevelInfo(sessionId) {
    const wrapper = document.querySelector(`.genie-wrapper[data-session-id="${sessionId}"]`);
    if (!wrapper) {
        return { isChild: false, level: 0, sequence: 0 };
    }

    return {
        isChild: true,
        level: parseInt(wrapper.dataset.level) || 0,
        sequence: parseInt(wrapper.dataset.sequence) || 0,
        parentId: wrapper.dataset.parentId,
        pathToRoot: getPathToRoot(sessionId)
    };
}

/**
 * Collapse/expand cascade helper (optional - for future keyboard nav)
 * @param {string} parentId - Parent session ID
 * @param {boolean} shouldCollapse - True to collapse, false to expand
 */
export function cascadeCollapseState(parentId, shouldCollapse) {
    const children = document.querySelectorAll(`.genie-wrapper[data-parent-id="${parentId}"]`);

    children.forEach((child, index) => {
        // Apply staggered delay based on sequence
        setTimeout(() => {
            child.classList.toggle('collapsed', shouldCollapse);

            // Recursively collapse grandchildren
            const childId = child.dataset.sessionId;
            if (childId) {
                cascadeCollapseState(childId, shouldCollapse);
            }
        }, index * 40);  // 40ms stagger matches CSS transition-delay
    });
}

// Export all functions
export default {
    getSiblings,
    highlightSiblings,
    highlightSiblingsDebounced,
    initializePathHighlighting,
    syncWrapperStates,
    getSessionLevelInfo,
    cascadeCollapseState
};
