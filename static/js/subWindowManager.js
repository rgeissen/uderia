/**
 * Sub-Window Manager
 *
 * Manages persistent, resizable panels on the conversation canvas.
 * Sub-windows are spawned by components with render_target: "sub_window"
 * (e.g., code editor, HTML preview).
 *
 * Key properties:
 * - Persistent: Stay open until user closes them
 * - Bidirectional: User edits feed back to LLM as context
 * - Multiple: Several sub-windows can be open simultaneously
 * - Updateable: LLM can update existing sub-windows by ID
 */

import { renderComponent, hasRenderer } from './componentRenderers.js';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** @type {Map<string, {componentId: string, title: string, state: any, element: HTMLElement}>} */
const _openWindows = new Map();

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Create and mount a sub-window on the conversation canvas.
 *
 * @param {string} windowId - Unique window identifier (e.g., 'sw-abc123')
 * @param {string} componentId - Component that owns this window (e.g., 'code_editor')
 * @param {object} options
 * @param {string} options.title - Window title bar text
 * @param {object} options.spec - Component render spec (passed to renderer)
 * @param {boolean} [options.interactive=false] - Whether bidirectional editing is enabled
 * @param {object} [options.defaultSize] - {width, height} in pixels
 * @returns {HTMLElement|null} The created sub-window element, or null if container not found
 */
export function createSubWindow(windowId, componentId, options = {}) {
    const container = document.getElementById('sub-window-container');
    if (!container) {
        console.warn('[SubWindowManager] No sub-window-container element found');
        return null;
    }

    // Close existing window with same ID
    if (_openWindows.has(windowId)) {
        closeSubWindow(windowId);
    }

    const { title = 'Sub Window', spec = {}, interactive = false, defaultSize } = options;

    // Build DOM
    const sw = document.createElement('div');
    sw.className = 'sub-window glass-panel';
    sw.id = windowId;
    sw.dataset.componentId = componentId;
    sw.style.width = defaultSize?.width ? `${defaultSize.width}px` : '500px';

    const bodyId = `${windowId}-body`;

    sw.innerHTML = `
        <div class="sub-window-header">
            <span class="sub-window-title">${_escapeHtml(title)}</span>
            <div class="sub-window-controls">
                <button class="sw-minimize" title="Minimize">&#x2500;</button>
                <button class="sw-close" title="Close">&#x2715;</button>
            </div>
        </div>
        <div class="sub-window-body" id="${bodyId}">
            <!-- Component renderer fills this -->
        </div>
    `;

    // Wire controls
    sw.querySelector('.sw-close').addEventListener('click', () => closeSubWindow(windowId));
    sw.querySelector('.sw-minimize').addEventListener('click', () => minimizeSubWindow(windowId));

    container.appendChild(sw);

    // Track state
    _openWindows.set(windowId, {
        componentId,
        title,
        state: spec,
        interactive,
        element: sw,
    });

    // Render component content
    if (hasRenderer(componentId)) {
        renderComponent(componentId, bodyId, spec);
    }

    return sw;
}

/**
 * Update content of an existing sub-window.
 *
 * @param {string} windowId
 * @param {object} payload - New spec to render
 */
export function updateSubWindow(windowId, payload) {
    const win = _openWindows.get(windowId);
    if (!win) {
        console.warn(`[SubWindowManager] Window '${windowId}' not found for update`);
        return;
    }

    win.state = payload;
    const bodyId = `${windowId}-body`;
    const body = document.getElementById(bodyId);
    if (body) {
        body.innerHTML = '';
        if (hasRenderer(win.componentId)) {
            renderComponent(win.componentId, bodyId, payload);
        }
    }
}

/**
 * Close and remove a sub-window.
 */
export function closeSubWindow(windowId) {
    const win = _openWindows.get(windowId);
    if (win && win.element) {
        win.element.remove();
    }
    _openWindows.delete(windowId);
}

/**
 * Minimize a sub-window (collapse body).
 */
export function minimizeSubWindow(windowId) {
    const win = _openWindows.get(windowId);
    if (!win || !win.element) return;

    const body = win.element.querySelector('.sub-window-body');
    if (body) {
        body.classList.toggle('hidden');
    }
}

/**
 * Restore a minimized sub-window.
 */
export function restoreSubWindow(windowId) {
    const win = _openWindows.get(windowId);
    if (!win || !win.element) return;

    const body = win.element.querySelector('.sub-window-body');
    if (body) {
        body.classList.remove('hidden');
    }
}

/**
 * Get the current state of a sub-window (for bidirectional context injection).
 *
 * @param {string} windowId
 * @returns {object|null} { componentId, title, state } or null
 */
export function getSubWindowState(windowId) {
    const win = _openWindows.get(windowId);
    if (!win) return null;
    return {
        componentId: win.componentId,
        title: win.title,
        state: win.state,
        interactive: win.interactive,
    };
}

/**
 * Get all open sub-windows and their current state.
 * Used for context injection when user sends a new message.
 *
 * @returns {Map<string, {componentId: string, title: string, state: any}>}
 */
export function getAllOpenWindows() {
    const result = new Map();
    for (const [id, win] of _openWindows) {
        result.set(id, {
            componentId: win.componentId,
            title: win.title,
            state: win.state,
            interactive: win.interactive,
        });
    }
    return result;
}

/**
 * Close all open sub-windows (e.g., on session switch).
 */
export function closeAllSubWindows() {
    for (const windowId of [..._openWindows.keys()]) {
        closeSubWindow(windowId);
    }
}

/**
 * Get the count of open sub-windows.
 */
export function getOpenWindowCount() {
    return _openWindows.size;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
