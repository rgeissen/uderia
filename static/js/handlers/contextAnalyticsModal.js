/**
 * Context Window Analytics Modal.
 *
 * Shared full-screen modal for viewing context window utilization analytics
 * for any session. Two entry points:
 *   - Session gallery card button (sidebar)
 *   - Live Status panel header button
 *
 * Reuses renderContextAnalytics() from contextWindowHandler.js.
 */

import { renderContextAnalytics } from './contextWindowHandler.js';
import { escapeHtml } from '../ui.js';

let modalElement = null;

const BAR_CHART_SVG = `<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
    <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
</svg>`;

/**
 * Open the context analytics modal for a given session.
 * @param {string} sessionId - The session ID to fetch analytics for
 * @param {string} sessionName - Display name for the modal title
 */
export async function openContextAnalyticsModal(sessionId, sessionName) {
    if (!modalElement) {
        modalElement = _createModalDOM();
        document.body.appendChild(modalElement);
    }

    // Set title
    const titleEl = modalElement.querySelector('#cw-analytics-modal-title');
    titleEl.textContent = `Context Window Analytics: ${sessionName || 'Session'}`;

    // Show modal with animation
    const overlay = modalElement;
    const content = modalElement.querySelector('#cw-analytics-modal-content');
    overlay.classList.remove('hidden');
    requestAnimationFrame(() => {
        overlay.classList.remove('opacity-0');
        content.classList.remove('scale-95', 'opacity-0');
    });

    // Loading state
    const body = modalElement.querySelector('#cw-analytics-modal-body');
    body.innerHTML = '<p class="text-sm text-gray-400 py-8 text-center">Loading analytics...</p>';

    // Fetch analytics data
    const token = localStorage.getItem('tda_auth_token');
    try {
        const res = await fetch(`/api/v1/sessions/${sessionId}/context-analytics`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) {
            body.innerHTML = '<p class="text-sm text-red-400 py-8 text-center">Failed to load analytics. This session may not have context window data.</p>';
            return;
        }
        const data = await res.json();
        renderContextAnalytics(body, data);
    } catch (err) {
        body.innerHTML = `<p class="text-sm text-red-400 py-8 text-center">Error: ${escapeHtml(err.message)}</p>`;
    }
}

function _closeModal() {
    if (!modalElement) return;
    const content = modalElement.querySelector('#cw-analytics-modal-content');
    modalElement.classList.add('opacity-0');
    content.classList.add('scale-95', 'opacity-0');
    setTimeout(() => modalElement.classList.add('hidden'), 300);
}

function _createModalDOM() {
    const overlay = document.createElement('div');
    overlay.id = 'cw-analytics-modal-overlay';
    overlay.className = 'fixed inset-0 z-50 flex items-start justify-center overflow-y-auto hidden opacity-0';
    overlay.style.cssText = 'background-color: rgba(0, 0, 0, 0.7); backdrop-filter: blur(4px); transition: opacity 0.3s ease;';

    overlay.innerHTML = `
        <div id="cw-analytics-modal-content" class="rounded-2xl border max-w-4xl w-full my-8 mx-4 shadow-2xl transform scale-95 opacity-0"
             style="background: linear-gradient(to bottom right, var(--bg-secondary), var(--bg-primary)); border-color: var(--border-primary); transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);">
            <!-- Header -->
            <div class="border-b p-5 flex items-center justify-between" style="border-color: var(--border-primary);">
                <div class="flex items-center gap-3">
                    <div class="p-2 rounded-lg" style="background: rgba(99, 102, 241, 0.15);">
                        ${BAR_CHART_SVG}
                    </div>
                    <h3 id="cw-analytics-modal-title" class="text-lg font-bold" style="color: var(--text-primary);">Context Window Analytics</h3>
                </div>
                <button id="cw-analytics-modal-close" class="p-2 rounded-lg transition-colors" style="color: var(--text-muted);"
                        onmouseover="this.style.backgroundColor='var(--hover-bg)'; this.style.color='var(--text-primary)';"
                        onmouseout="this.style.backgroundColor='transparent'; this.style.color='var(--text-muted)';">
                    <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
            <!-- Body -->
            <div id="cw-analytics-modal-body" class="p-5 max-h-[75vh] overflow-y-auto">
                <p class="text-sm text-gray-400 py-8 text-center">Loading analytics...</p>
            </div>
        </div>`;

    // Close handlers
    const closeBtn = overlay.querySelector('#cw-analytics-modal-close');
    closeBtn.addEventListener('click', _closeModal);
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) _closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !overlay.classList.contains('hidden')) {
            _closeModal();
        }
    });

    return overlay;
}
