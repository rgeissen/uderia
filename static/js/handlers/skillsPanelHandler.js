/**
 * skillsPanelHandler.js
 *
 * Manages the Skills tab in the Resource Panel.
 * Shows skills assigned to the current profile as expandable cards.
 * - Enabled: skill available for manual #hashtag invocation
 * - Active: skill auto-applies on every query (implies enabled)
 * Changes persist to profile config via PUT /api/v1/profiles/<id>.
 */

import { state } from '../state.js';
import * as API from '../api.js';

// ── Helpers ─────────────────────────────────────────────────────────────────

// Match skillHandler.js badge styles exactly
const INJECTION_TARGET_CONFIG = {
    system_prompt: { color: '#a78bfa', bg: 'rgba(167,139,250,0.12)', border: 'rgba(167,139,250,0.25)', label: 'System Prompt' },
    user_context:  { color: '#60a5fa', bg: 'rgba(96,165,250,0.12)',  border: 'rgba(96,165,250,0.25)',  label: 'User Context' },
};
const TAG_COLOR = { color: '#94a3b8', bg: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.18)' };

function _getHeaders() {
    const token = localStorage.getItem('tda_auth_token');
    return {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    };
}

// ── Card creation ───────────────────────────────────────────────────────────

function createSkillCard(skill) {
    const detailsEl = document.createElement('details');
    detailsEl.className = 'resource-item bg-gray-800/50 rounded-lg border border-gray-700/60';
    detailsEl.dataset.skillId = skill.id;

    // Left border accent: green if active, blue if enabled-only
    if (skill.active) {
        detailsEl.style.borderLeftWidth = '4px';
        detailsEl.style.borderLeftColor = '#10b981';
    } else if (skill.enabled) {
        detailsEl.style.borderLeftWidth = '4px';
        detailsEl.style.borderLeftColor = '#3b82f6';
    }

    const targetCfg = INJECTION_TARGET_CONFIG[skill.injection_target] || INJECTION_TARGET_CONFIG.system_prompt;

    // Status badge
    let statusBadge = '';
    if (skill.active) {
        statusBadge = '<span class="text-xs font-semibold px-2 py-0.5 rounded" style="color: #10b981; background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.3);">AUTO</span>';
    } else if (skill.enabled) {
        statusBadge = '<span class="text-xs font-semibold px-2 py-0.5 rounded" style="color: #3b82f6; background: rgba(59,130,246,0.15); border: 1px solid rgba(59,130,246,0.3);">ENABLED</span>';
    } else {
        statusBadge = '<span class="text-xs font-semibold px-2 py-0.5 rounded" style="color: #6b7280; background: rgba(107,114,128,0.15); border: 1px solid rgba(107,114,128,0.3);">OFF</span>';
    }

    const availabilityNote = !skill.available
        ? '<span class="text-xs text-red-400 ml-1">(disabled by admin)</span>'
        : '';

    // Summary row (always visible) — badges match skillHandler.js
    const summaryHTML = `
        <summary class="flex justify-between items-center p-3 text-white hover:bg-gray-700/50 rounded-lg transition-colors cursor-pointer">
            <div class="flex items-center gap-2 flex-wrap min-w-0">
                <span class="text-xs font-mono font-semibold px-1.5 py-0.5 rounded" style="background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">#${skill.id}</span>
                <span class="text-sm font-medium truncate">${skill.name}</span>
                <span class="text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap" style="background: ${targetCfg.bg}; color: ${targetCfg.color}; border: 1px solid ${targetCfg.border};">${targetCfg.label}</span>
                ${statusBadge}
                ${availabilityNote}
            </div>
            <svg class="chevron w-5 h-5 flex-shrink-0" style="color: var(--text-muted, #9ca3af);" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
            </svg>
        </summary>
    `;

    // Expanded content
    const tagPills = (skill.tags || [])
        .map(t => `<span class="text-xs px-1.5 py-0.5 rounded" style="background: ${TAG_COLOR.bg}; color: ${TAG_COLOR.color}; border: 1px solid ${TAG_COLOR.border};">${t}</span>`)
        .join(' ');

    // Toggle buttons (only if skill is available at admin level)
    let toggles = '';
    if (skill.available) {
        const enabledStyle = skill.enabled
            ? 'background: rgba(59,130,246,0.15); color: #3b82f6; border: 1px solid rgba(59,130,246,0.3);'
            : 'background: var(--hover-bg, #4b5563); color: var(--text-muted, #9ca3af);';
        const enabledLabel = skill.enabled ? 'Enabled' : 'Enable';
        const enabledTitle = skill.enabled ? 'Disable #hashtag invocation' : 'Enable #hashtag invocation';

        const activeStyle = skill.active
            ? 'background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid rgba(16,185,129,0.3);'
            : 'background: var(--hover-bg, #4b5563); color: var(--text-muted, #9ca3af);';
        const activeLabel = skill.active ? 'Auto-Active' : 'Activate';
        const activeTitle = skill.active ? 'Stop auto-applying on every query' : 'Auto-apply on every query';

        toggles = `
            <button class="skill-toggle-btn px-3 py-1 text-xs font-semibold rounded-md transition-colors"
                    style="${enabledStyle}"
                    data-skill-id="${skill.id}" data-field="enabled" data-current="${skill.enabled ? '1' : '0'}"
                    title="${enabledTitle}">${enabledLabel}</button>
            <button class="skill-toggle-btn px-3 py-1 text-xs font-semibold rounded-md transition-colors"
                    style="${activeStyle}"
                    data-skill-id="${skill.id}" data-field="active" data-current="${skill.active ? '1' : '0'}"
                    title="${activeTitle}">${activeLabel}</button>
        `;
    }

    const contentHTML = `
        <div class="p-3 pt-2 text-sm space-y-3" style="color: var(--text-muted, #d1d5db);">
            ${skill.description ? `<p class="text-xs" style="color: var(--text-muted, #9ca3af);">${skill.description}</p>` : ''}
            ${tagPills ? `<div class="flex flex-wrap gap-1">${tagPills}</div>` : ''}
            <div class="flex items-center gap-2 pt-2" style="border-top: 1px solid var(--border-primary, rgba(75,85,99,0.6));">
                ${toggles}
            </div>
        </div>
    `;

    detailsEl.innerHTML = summaryHTML + contentHTML;
    return detailsEl;
}

function renderEmptyState(container) {
    container.innerHTML = `
        <div class="flex flex-col items-center justify-center py-12 text-center">
            <svg class="w-12 h-12 mb-4" style="color: var(--text-muted, #6b7280);" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            <p class="text-sm font-semibold mb-1" style="color: var(--text-primary, #e5e7eb);">No Skills Assigned</p>
            <p class="text-xs max-w-xs" style="color: var(--text-muted, #6b7280);">
                Assign skills to this profile in Setup &rarr; Profiles &rarr; Edit to have them auto-applied on every query.
            </p>
        </div>
    `;
}

function renderLoadingState(container) {
    container.innerHTML = `
        <div class="flex items-center justify-center py-12">
            <div class="animate-spin rounded-full h-6 w-6 border-2 border-gray-500 border-t-emerald-500"></div>
            <span class="ml-3 text-sm" style="color: var(--text-muted, #9ca3af);">Loading skills...</span>
        </div>
    `;
}

// ── Main load function ──────────────────────────────────────────────────────

export async function loadSkillsPanel() {
    const container = document.getElementById('skills-panel-content');
    if (!container) return;

    const profileId = state.currentResourcePanelProfileId;
    if (!profileId) {
        renderEmptyState(container);
        return;
    }

    renderLoadingState(container);

    try {
        const res = await fetch(`/api/v1/profiles/${encodeURIComponent(profileId)}/skills`, {
            headers: _getHeaders(),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const skills = data.skills || [];

        // Update tab counter
        const tabBtn = document.querySelector('.resource-tab[data-type="skills"]');
        if (tabBtn) {
            const activeCount = skills.filter(s => s.active).length;
            const enabledCount = skills.filter(s => s.enabled && !s.active).length;
            let label = 'Skills';
            if (activeCount > 0 || enabledCount > 0) {
                const parts = [];
                if (activeCount > 0) parts.push(`${activeCount} auto`);
                if (enabledCount > 0) parts.push(`${enabledCount} on`);
                label = `Skills (${parts.join(', ')})`;
            }
            tabBtn.textContent = label;
        }

        if (skills.length === 0) {
            renderEmptyState(container);
            return;
        }

        container.innerHTML = '';
        for (const skill of skills) {
            container.appendChild(createSkillCard(skill));
        }
    } catch (err) {
        console.error('Failed to load skills panel:', err);
        container.innerHTML = `
            <div class="flex items-center justify-center py-12 text-center">
                <p class="text-sm" style="color: #ef4444;">Failed to load skills: ${err.message}</p>
            </div>
        `;
    }
}

// ── Toggle handler ──────────────────────────────────────────────────────────

async function handleSkillToggle(skillId, field, currentValue) {
    const profileId = state.currentResourcePanelProfileId;
    if (!profileId) return;

    try {
        const skillsRes = await fetch(`/api/v1/profiles/${encodeURIComponent(profileId)}/skills`, {
            headers: _getHeaders(),
        });
        if (!skillsRes.ok) throw new Error('Failed to load profile skills');
        const data = await skillsRes.json();

        const skills = (data.skills || []).map(s => ({
            id: s.id,
            enabled: !!s.enabled,
            active: !!s.active,
            param: s.param || null,
        }));

        const entry = skills.find(s => s.id === skillId);
        if (!entry) return;

        const newValue = !currentValue;

        if (field === 'enabled') {
            entry.enabled = newValue;
            if (!newValue) entry.active = false;
        } else if (field === 'active') {
            entry.active = newValue;
            if (newValue) entry.enabled = true;
        }

        await API.updateProfile(profileId, { skillsConfig: { skills } });

        await loadSkillsPanel();
        if (window.loadActivatedSkills) window.loadActivatedSkills();
    } catch (err) {
        console.error(`Failed to toggle skill ${field}:`, err);
    }
}

// ── Event delegation ────────────────────────────────────────────────────────

export function initSkillsPanelEvents() {
    const container = document.getElementById('skills-panel-content');
    if (!container) return;

    container.addEventListener('click', (e) => {
        const toggleBtn = e.target.closest('.skill-toggle-btn');
        if (toggleBtn) {
            e.stopPropagation();
            const skillId = toggleBtn.dataset.skillId;
            const field = toggleBtn.dataset.field;
            const currentValue = toggleBtn.dataset.current === '1';
            handleSkillToggle(skillId, field, currentValue);
        }
    });
}

// ── Reset (called on session switch) ────────────────────────────────────────

export function resetSkillsPanelState() {
    const container = document.getElementById('skills-panel-content');
    if (container) container.innerHTML = '';

    const tabBtn = document.querySelector('.resource-tab[data-type="skills"]');
    if (tabBtn) tabBtn.textContent = 'Skills';
}
