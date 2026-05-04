/**
 * extensionsPanelHandler.js
 *
 * Manages the Extensions tab in the Resource Panel.
 * Shows the user's activated extensions as read-only expandable cards.
 * Accent color: amber/yellow (#fbbf24) — matches extensionHandler.js.
 */

import { state } from '../state.js';

// ── Badge configs ────────────────────────────────────────────────────────────

const TIER_CONFIG = {
    convention: { label: 'Convention', color: '#9ca3af', bg: 'rgba(156,163,175,0.12)', border: 'rgba(156,163,175,0.25)' },
    simple:     { label: 'Simple',     color: '#60a5fa', bg: 'rgba(96,165,250,0.12)',  border: 'rgba(96,165,250,0.25)' },
    standard:   { label: 'Standard',   color: '#a78bfa', bg: 'rgba(167,139,250,0.12)', border: 'rgba(167,139,250,0.25)' },
    llm:        { label: 'LLM',        color: '#f472b6', bg: 'rgba(244,114,182,0.12)', border: 'rgba(244,114,182,0.25)' },
};

const OUTPUT_TARGET_CONFIG = {
    silent:       { label: 'Silent',       color: '#6b7280', bg: 'rgba(107,114,128,0.12)', border: 'rgba(107,114,128,0.25)' },
    chat_append:  { label: 'Chat',         color: '#34d399', bg: 'rgba(52,211,153,0.12)',  border: 'rgba(52,211,153,0.25)' },
    status_panel: { label: 'Status Panel', color: '#60a5fa', bg: 'rgba(96,165,250,0.12)',  border: 'rgba(96,165,250,0.25)' },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function _getHeaders() {
    const token = localStorage.getItem('tda_auth_token');
    return {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    };
}

// ── Card creation ────────────────────────────────────────────────────────────

function createExtensionCard(ext) {
    const detailsEl = document.createElement('details');
    detailsEl.className = 'resource-item';
    detailsEl.dataset.extName = ext.activation_name;

    // Amber left border for activated extensions
    detailsEl.style.borderLeftWidth = '4px';
    detailsEl.style.borderLeftColor = '#fbbf24';

    const tierCfg = TIER_CONFIG[ext.extension_tier] || TIER_CONFIG.standard;
    const outputCfg = OUTPUT_TARGET_CONFIG[ext.output_target] || OUTPUT_TARGET_CONFIG.silent;

    const summaryHTML = `
        <summary class="flex justify-between items-center px-3 py-2.5">
            <div class="flex items-center gap-2 flex-wrap min-w-0">
                <span class="text-xs font-mono font-semibold px-1.5 py-0.5 rounded" style="background: rgba(251,191,36,0.15); color: #fbbf24; border: 1px solid rgba(251,191,36,0.3);">!${ext.activation_name}</span>
                <span class="text-sm font-medium truncate">${ext.display_name}</span>
                <span class="text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap" style="background: ${tierCfg.bg}; color: ${tierCfg.color}; border: 1px solid ${tierCfg.border};">${tierCfg.label}</span>
                <span class="text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap" style="background: ${outputCfg.bg}; color: ${outputCfg.color}; border: 1px solid ${outputCfg.border};">${outputCfg.label}</span>
            </div>
            <svg class="chevron w-5 h-5 flex-shrink-0" style="color: var(--text-muted, #9ca3af);" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
            </svg>
        </summary>
    `;

    let detailItems = '';
    if (ext.description) {
        detailItems += `<p class="text-xs" style="color: var(--text-muted, #9ca3af);">${ext.description}</p>`;
    }
    if (ext.default_param) {
        detailItems += `
            <div class="flex items-center gap-2">
                <span class="text-[10px]" style="color: var(--text-muted, #6b7280);">Default param:</span>
                <span class="text-xs font-mono px-1.5 py-0.5 rounded" style="background: rgba(251,191,36,0.08); color: #fbbf24; border: 1px solid rgba(251,191,36,0.2);">${ext.default_param}</span>
            </div>`;
    }
    if (ext.requires_llm) {
        detailItems += `
            <span class="text-[10px] font-medium px-1.5 py-0.5 rounded" style="background: rgba(244,114,182,0.12); color: #f472b6; border: 1px solid rgba(244,114,182,0.25);">Requires LLM</span>`;
    }

    const contentHTML = `
        <div class="px-3 pb-3 pt-2 space-y-2 text-xs" style="color:var(--text-muted,#9ca3af);">
            ${detailItems}
            <div class="text-[10px] pt-1" style="color: var(--text-muted, #6b7280); border-top: 1px solid var(--border-primary, rgba(148,163,184,0.18));">
                Manage in Setup &rarr; Extensions
            </div>
        </div>
    `;

    detailsEl.innerHTML = summaryHTML + contentHTML;
    return detailsEl;
}

// ── State renderers ──────────────────────────────────────────────────────────

function renderEmptyState(container) {
    container.innerHTML = `
        <div class="flex flex-col items-center justify-center py-12 text-center">
            <svg class="w-12 h-12 mb-4" style="color: var(--text-muted, #6b7280);" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875s-2.25.84-2.25 1.875c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 01-.657.643 48.39 48.39 0 01-4.163-.3c.186 1.613.293 3.25.315 4.907a.656.656 0 01-.658.663v0c-.355 0-.676-.186-.959-.401a1.647 1.647 0 00-1.003-.349c-1.036 0-1.875 1.007-1.875 2.25s.84 2.25 1.875 2.25c.369 0 .713-.128 1.003-.349.283-.215.604-.401.959-.401v0c.31 0 .555.26.532.57a48.039 48.039 0 01-.642 5.056c1.518.19 3.058.309 4.616.354a.64.64 0 00.657-.643v0c0-.355-.186-.676-.401-.959a1.647 1.647 0 01-.349-1.003c0-1.035 1.008-1.875 2.25-1.875 1.243 0 2.25.84 2.25 1.875 0 .369-.128.713-.349 1.003-.215.283-.401.604-.401.959v0c0 .333.277.599.61.58a48.1 48.1 0 005.427-.63 48.05 48.05 0 00.582-4.717.532.532 0 00-.533-.57v0c-.355 0-.676.186-.959.401-.29.221-.634.349-1.003.349-1.035 0-1.875-1.007-1.875-2.25s.84-2.25 1.875-2.25c.37 0 .713.128 1.003.349.283.215.604.401.959.401v0a.656.656 0 00.658-.663 48.422 48.422 0 00-.37-5.36c-1.886.342-3.81.574-5.766.689a.578.578 0 01-.61-.58v0z" />
            </svg>
            <p class="text-sm font-semibold mb-1" style="color: var(--text-primary, #e5e7eb);">No Active Extensions</p>
            <p class="text-xs max-w-xs" style="color: var(--text-muted, #6b7280);">
                Activate extensions in Setup &rarr; Extensions to use them with <span class="font-mono" style="color: #fbbf24;">!</span> shortcuts in your queries.
            </p>
        </div>
    `;
}

function renderLoadingState(container) {
    container.innerHTML = `
        <div class="flex items-center justify-center py-12">
            <div class="animate-spin rounded-full h-6 w-6 border-2" style="border-color: var(--border-primary); border-top-color: #fbbf24;"></div>
            <span class="ml-3 text-sm" style="color: var(--text-muted, #9ca3af);">Loading extensions...</span>
        </div>
    `;
}

// ── Main load function ───────────────────────────────────────────────────────

export async function loadExtensionsPanel() {
    const container = document.getElementById('extensions-panel-content');
    if (!container) return;

    renderLoadingState(container);

    try {
        const res = await fetch('/api/v1/extensions/activated', {
            headers: _getHeaders(),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const extensions = data.extensions || [];

        // Update tab counter and visibility
        const tabBtn = document.querySelector('.resource-tab[data-type="extensions"]');
        if (tabBtn) {
            if (extensions.length === 0) {
                tabBtn.style.display = 'none';
            } else {
                tabBtn.style.display = 'inline-block';
                tabBtn.textContent = `Extensions (${extensions.length})`;
            }
        }

        if (extensions.length === 0) {
            renderEmptyState(container);
            return;
        }

        container.innerHTML = '';
        for (const ext of extensions) {
            container.appendChild(createExtensionCard(ext));
        }
    } catch (err) {
        console.error('Failed to load extensions panel:', err);
        container.innerHTML = `
            <div class="flex items-center justify-center py-12 text-center">
                <p class="text-sm" style="color: #ef4444;">Failed to load extensions: ${err.message}</p>
            </div>
        `;
    }
}

// ── Dynamic focus (called from eventHandlers.js on extension_start/complete) ──

export function highlightExtension(extName) {
    // Switch tab directly — avoids tabBtn.click() which would trigger loadExtensionsPanel()
    // and wipe the card DOM before it can be highlighted.
    document.querySelectorAll('.resource-tab').forEach(t => t.classList.remove('active'));
    const tabBtn = document.querySelector('.resource-tab[data-type="extensions"]');
    if (tabBtn) tabBtn.classList.add('active');
    document.querySelectorAll('.resource-panel').forEach(p => {
        p.style.display = p.id === 'extensions-panel' ? 'flex' : 'none';
    });

    const card = document.querySelector(`[data-ext-name="${CSS.escape(extName)}"]`);
    if (!card) {
        loadExtensionsPanel();
        return;
    }
    if (state.currentlySelectedResource) state.currentlySelectedResource.classList.remove('resource-selected');
    card.open = true;
    card.classList.add('resource-selected');
    state.currentlySelectedResource = card;
    setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'start' }), 350);
}

// ── Reset (called on session switch) ─────────────────────────────────────────

export function resetExtensionsPanelState() {
    const container = document.getElementById('extensions-panel-content');
    if (container) container.innerHTML = '';

    const tabBtn = document.querySelector('.resource-tab[data-type="extensions"]');
    if (tabBtn) {
        tabBtn.textContent = 'Extensions';
        tabBtn.style.display = 'inline-block';
    }
}
