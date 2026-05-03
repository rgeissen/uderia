/**
 * componentsPanelHandler.js
 *
 * Manages the Components tab in the Resource Panel.
 * Shows all platform components with their effective enabled/disabled state
 * for the active profile.
 *
 * Enabled state resolution (highest wins):
 *   1. globally_disabled (admin/per-user governance) — gray, ADMIN badge, no toggle
 *   2. componentConfig[id].enabled === false (user explicitly off) — gray, OFF badge, toggleable
 *   3. componentConfig[id].enabled === true (user explicitly on) — cyan, ON badge, toggleable
 *   4. not in componentConfig → profile_defaults.enabled_for includes profile type — cyan, ON (default)
 *   5. not in componentConfig → not in enabled_for — gray, OFF (default)
 *
 * Asterisk (*) on tab label: appears when any component has user_disabled:true
 * (mirrors Tools(N)* / Prompts(N)* behaviour for user-toggled items).
 */

import { state } from '../state.js';

// ── Styling constants ────────────────────────────────────────────────────────

const ENABLED_COLOR  = '#06b6d4';  // cyan-500 — active / enabled
const ENABLED_BG     = 'rgba(6,182,212,0.15)';
const ENABLED_BORDER = 'rgba(6,182,212,0.3)';

const OFF_COLOR  = '#6b7280';
const OFF_BG     = 'rgba(107,114,128,0.12)';
const OFF_BORDER = 'rgba(107,114,128,0.25)';

const ADMIN_COLOR  = '#f87171';  // red-400
const ADMIN_BG     = 'rgba(248,113,113,0.12)';
const ADMIN_BORDER = 'rgba(248,113,113,0.25)';

const INTENSITY_COLORS = {
    none:   { color: '#94a3b8', bg: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.2)' },
    light:  { color: '#4ade80', bg: 'rgba(74,222,128,0.10)',  border: 'rgba(74,222,128,0.2)' },
    medium: { color: '#fbbf24', bg: 'rgba(251,191,36,0.10)',  border: 'rgba(251,191,36,0.2)' },
    heavy:  { color: '#f97316', bg: 'rgba(249,115,22,0.10)',  border: 'rgba(249,115,22,0.2)' },
};

const TYPE_COLORS = {
    action:     { color: '#a78bfa', bg: 'rgba(167,139,250,0.10)', border: 'rgba(167,139,250,0.2)' },
    structural: { color: '#60a5fa', bg: 'rgba(96,165,250,0.10)',  border: 'rgba(96,165,250,0.2)' },
    system:     { color: '#94a3b8', bg: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.2)' },
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

function createComponentCard(comp) {
    const detailsEl = document.createElement('details');
    detailsEl.className = 'resource-item bg-gray-800/50 rounded-lg border border-gray-700/60';
    detailsEl.dataset.componentId = comp.component_id;
    if (comp.tool_name) detailsEl.dataset.toolName = comp.tool_name;

    // Left border accent
    if (comp.profile_enabled && !comp.globally_disabled) {
        detailsEl.style.borderLeftWidth = '4px';
        detailsEl.style.borderLeftColor = ENABLED_COLOR;
    }

    // Status badge
    let statusBadge;
    if (comp.globally_disabled) {
        statusBadge = `<span class="text-xs font-semibold px-2 py-0.5 rounded" style="color:${ADMIN_COLOR};background:${ADMIN_BG};border:1px solid ${ADMIN_BORDER};">ADMIN</span>`;
    } else if (comp.profile_enabled) {
        statusBadge = `<span class="text-xs font-semibold px-2 py-0.5 rounded" style="color:${ENABLED_COLOR};background:${ENABLED_BG};border:1px solid ${ENABLED_BORDER};">ON</span>`;
    } else {
        statusBadge = `<span class="text-xs font-semibold px-2 py-0.5 rounded" style="color:${OFF_COLOR};background:${OFF_BG};border:1px solid ${OFF_BORDER};">OFF</span>`;
    }

    // Type badge
    const typeCfg = TYPE_COLORS[comp.component_type] || TYPE_COLORS.system;
    const typeBadge = `<span class="text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap" style="background:${typeCfg.bg};color:${typeCfg.color};border:1px solid ${typeCfg.border};">${comp.component_type}</span>`;

    // Intensity badge (only if component supports it)
    let intensityBadge = '';
    if (comp.intensity) {
        const ic = INTENSITY_COLORS[comp.intensity] || INTENSITY_COLORS.medium;
        intensityBadge = `<span class="text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap" style="background:${ic.bg};color:${ic.color};border:1px solid ${ic.border};">${comp.intensity}</span>`;
    }

    // Tool name badge
    const toolBadge = comp.tool_name
        ? `<span class="text-[10px] font-mono px-1.5 py-0.5 rounded whitespace-nowrap" style="background:rgba(16,185,129,0.12);color:#34d399;border:1px solid rgba(16,185,129,0.25);">${comp.tool_name}</span>`
        : '';

    const summaryHTML = `
        <summary class="flex justify-between items-center p-3 text-white hover:bg-gray-700/50 rounded-lg transition-colors cursor-pointer">
            <div class="flex items-center gap-2 flex-wrap min-w-0">
                <span class="text-sm font-medium truncate" style="color:var(--text-primary,#e5e7eb);">${comp.display_name}</span>
                ${typeBadge}
                ${toolBadge}
                ${intensityBadge}
                ${statusBadge}
            </div>
            <svg class="chevron w-5 h-5 flex-shrink-0" style="color:var(--text-muted,#9ca3af);" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
        </summary>
    `;

    // Toggle button (not available when globally disabled by admin)
    let toggleBtn = '';
    if (!comp.globally_disabled) {
        if (comp.profile_enabled) {
            toggleBtn = `<button class="component-toggle-btn px-3 py-1 text-xs font-semibold rounded-md transition-colors"
                style="background:${ENABLED_BG};color:${ENABLED_COLOR};border:1px solid ${ENABLED_BORDER};"
                data-component-id="${comp.component_id}" data-enabled="1"
                title="Disable for this profile">Enabled</button>`;
        } else {
            toggleBtn = `<button class="component-toggle-btn px-3 py-1 text-xs font-semibold rounded-md transition-colors"
                style="background:var(--hover-bg,#4b5563);color:var(--text-muted,#9ca3af);"
                data-component-id="${comp.component_id}" data-enabled="0"
                title="Enable for this profile">Enable</button>`;
        }
    }

    const adminNote = comp.globally_disabled
        ? `<span class="text-xs" style="color:${ADMIN_COLOR};">(disabled by admin)</span>`
        : '';

    const contentHTML = `
        <div class="p-3 pt-2 text-sm space-y-3" style="color:var(--text-muted,#d1d5db);">
            ${comp.description ? `<p class="text-xs" style="color:var(--text-muted,#9ca3af);">${comp.description}</p>` : ''}
            <div class="flex items-center gap-2 pt-2" style="border-top:1px solid var(--border-primary,rgba(75,85,99,0.6));">
                ${toggleBtn}
                ${adminNote}
            </div>
        </div>
    `;

    detailsEl.innerHTML = summaryHTML + contentHTML;
    return detailsEl;
}

function renderLoadingState(container) {
    container.innerHTML = `
        <div class="flex items-center justify-center py-12">
            <div class="animate-spin rounded-full h-6 w-6 border-2 border-gray-500 border-t-cyan-500"></div>
            <span class="ml-3 text-sm" style="color:var(--text-muted,#9ca3af);">Loading components...</span>
        </div>
    `;
}

function renderErrorState(container, msg) {
    container.innerHTML = `
        <div class="flex items-center justify-center py-12 text-center">
            <p class="text-sm" style="color:#ef4444;">Failed to load components: ${msg}</p>
        </div>
    `;
}

// ── Tab label ────────────────────────────────────────────────────────────────

function _updateTabLabel(components) {
    const tabBtn = document.querySelector('.resource-tab[data-type="components"]');
    if (!tabBtn) return;

    const total = components.length;
    const userDisabledCount = components.filter(c => c.user_disabled).length;
    const asterisk = userDisabledCount > 0 ? '*' : '';
    tabBtn.textContent = `Components (${total})${asterisk}`;
}

// ── Main load function ───────────────────────────────────────────────────────

export async function loadComponentsPanel() {
    const container = document.getElementById('components-panel-content');
    if (!container) return;

    const profileId = state.currentResourcePanelProfileId;
    if (!profileId) {
        container.innerHTML = '';
        return;
    }

    renderLoadingState(container);

    try {
        const res = await fetch(`/api/v1/profiles/${encodeURIComponent(profileId)}/components`, {
            headers: _getHeaders(),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const components = data.components || [];

        _updateTabLabel(components);

        container.innerHTML = '';
        // Sort: enabled first, then globally disabled last
        const sorted = [...components].sort((a, b) => {
            if (a.globally_disabled !== b.globally_disabled) return a.globally_disabled ? 1 : -1;
            if (a.profile_enabled !== b.profile_enabled) return a.profile_enabled ? -1 : 1;
            return (a.display_name || '').localeCompare(b.display_name || '');
        });
        for (const comp of sorted) {
            container.appendChild(createComponentCard(comp));
        }
    } catch (err) {
        console.error('Failed to load components panel:', err);
        renderErrorState(container, err.message);
    }
}

// ── Dynamic focus (called from eventHandlers.js on TDA_ tool events) ─────────

export function highlightComponent(toolName) {
    const card = document.querySelector(`[data-tool-name="${CSS.escape(toolName)}"]`);

    if (!card) {
        // No card for this tool (e.g. TDA_FinalReport, TDA_LLMTask — internal tools with no
        // component entry). Pre-load the panel if it's empty, but leave the current selection
        // untouched so the last highlighted card stays visible.
        const panelContent = document.getElementById('components-panel-content');
        if (!panelContent || panelContent.children.length === 0) {
            loadComponentsPanel();
        }
        return;
    }

    // Card exists — clear previous selection, switch to Components tab, and highlight.
    document.querySelector('.resource-selected')?.classList.remove('resource-selected');
    if (state) state.currentlySelectedResource = null;

    document.querySelectorAll('.resource-tab').forEach(t => t.classList.remove('active'));
    const tabBtn = document.querySelector('.resource-tab[data-type="components"]');
    if (tabBtn) tabBtn.classList.add('active');
    document.querySelectorAll('.resource-panel').forEach(p => {
        p.style.display = p.id === 'components-panel' ? 'flex' : 'none';
    });
    card.open = true;
    card.classList.add('resource-selected');
    if (state) state.currentlySelectedResource = card;
    setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'start' }), 350);
}

// ── Toggle handler ───────────────────────────────────────────────────────────

async function handleComponentToggle(componentId, currentlyEnabled) {
    const profileId = state.currentResourcePanelProfileId;
    if (!profileId) return;

    try {
        // Fetch current profile to read existing componentConfig
        const token = localStorage.getItem('tda_auth_token');
        const profRes = await fetch('/api/v1/profiles', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!profRes.ok) throw new Error('Failed to fetch profiles');
        const profData = await profRes.json();
        const profile = (profData.profiles || []).find(p => p.id === profileId);
        if (!profile) throw new Error('Profile not found');

        const componentConfig = { ...(profile.componentConfig || {}) };
        const existing = componentConfig[componentId] || {};
        componentConfig[componentId] = { ...existing, enabled: !currentlyEnabled };

        const updateRes = await fetch(`/api/v1/profiles/${encodeURIComponent(profileId)}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({ componentConfig }),
        });
        if (!updateRes.ok) throw new Error(`Update failed: HTTP ${updateRes.status}`);

        await loadComponentsPanel();
    } catch (err) {
        console.error(`Failed to toggle component ${componentId}:`, err);
    }
}

// ── Event delegation ─────────────────────────────────────────────────────────

export function initComponentsPanelEvents() {
    const container = document.getElementById('components-panel-content');
    if (!container) return;

    container.addEventListener('click', (e) => {
        const btn = e.target.closest('.component-toggle-btn');
        if (btn) {
            e.stopPropagation();
            const componentId = btn.dataset.componentId;
            const currentlyEnabled = btn.dataset.enabled === '1';
            handleComponentToggle(componentId, currentlyEnabled);
        }
    });
}

// ── Reset (called on session switch) ────────────────────────────────────────

export function resetComponentsPanelState() {
    const container = document.getElementById('components-panel-content');
    if (container) container.innerHTML = '';

    const tabBtn = document.querySelector('.resource-tab[data-type="components"]');
    if (tabBtn) tabBtn.textContent = 'Components';
}
