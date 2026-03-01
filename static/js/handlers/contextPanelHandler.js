/**
 * Context Panel handler for the Resource Panel "Context" tab.
 *
 * Shows the active profile's context window type composition:
 *   - Module allocation bar chart
 *   - Per-module budget cards
 *   - Last snapshot metrics (when available)
 *
 * Also provides the snapshot renderer for Live Status events.
 */

import { escapeHtml } from '../ui.js';
import { state } from '../state.js';

// Module color map (shared with contextWindowHandler.js)
const MODULE_COLORS = {
    system_prompt: '#6366f1',
    tool_definitions: '#f59e0b',
    conversation_history: '#10b981',
    rag_context: '#3b82f6',
    knowledge_context: '#8b5cf6',
    plan_hydration: '#ec4899',
    document_context: '#14b8a6',
    component_instructions: '#f97316',
    workflow_history: '#64748b',
};

function getModuleColor(moduleId) {
    return MODULE_COLORS[moduleId] || '#6b7280';
}

// Cached state for re-renders when snapshots arrive
let lastSnapshot = null;
let lastCwt = null;
let lastProfile = null;

/**
 * Clear all module-level caches on session switch.
 * Prevents stale snapshot overlay from previous session bleeding into the new one.
 * Called from sessionManagement.js alongside cleanupCoordination() / cleanupExecution().
 */
export function resetContextPanelState() {
    lastSnapshot = null;
    lastCwt = null;
    lastProfile = null;
}

/**
 * Load the Context panel content from the active profile's context window type.
 * Called when the user clicks the "Context" resource tab, or when the active
 * profile changes (default switch, @TAG override).
 *
 * Uses state.currentResourcePanelProfileId to show the correct profile's
 * context window type (same pattern as loadKnowledgeGraphsPanel).
 */
export async function loadContextPanel() {
    const container = document.getElementById('context-panel-content');
    if (!container) return;

    const token = localStorage.getItem('tda_auth_token');
    if (!token) {
        container.innerHTML = '<div class="text-center text-gray-400 py-8">Not authenticated.</div>';
        return;
    }

    try {
        const profileRes = await fetch('/api/v1/profiles', {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!profileRes.ok) {
            container.innerHTML = '<div class="text-center text-gray-400 py-8">Failed to load profiles.</div>';
            return;
        }

        const profileData = await profileRes.json();
        const profiles = profileData.profiles || [];

        // Use the active resource panel profile (from @TAG override) or fall back to default
        const activeProfileId = state.currentResourcePanelProfileId;
        let activeProfile = activeProfileId
            ? profiles.find(p => p.id === activeProfileId)
            : null;

        // Fall back to default profile if override not found
        if (!activeProfile) {
            activeProfile = profiles.find(p => p.is_default) || profiles[0];
        }

        if (!activeProfile) {
            container.innerHTML = '<div class="text-center text-gray-400 py-8">No profiles configured.</div>';
            return;
        }

        // Get the context window type
        const cwtId = activeProfile.contextWindowTypeId;
        if (!cwtId) {
            container.innerHTML = `
                <div class="text-center text-gray-400 py-8">
                    <p>No context window type bound to profile "${escapeHtml(activeProfile.name)}".</p>
                    <p class="text-xs text-gray-500 mt-1">Go to Setup > Context Window to configure.</p>
                </div>`;
            return;
        }

        const cwtRes = await fetch(`/api/v1/context-window-types/${cwtId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!cwtRes.ok) {
            container.innerHTML = '<div class="text-center text-gray-400 py-8">Failed to load context window type.</div>';
            return;
        }

        const cwtData = await cwtRes.json();
        const cwt = cwtData.context_window_type || cwtData;
        lastCwt = cwt;
        lastProfile = activeProfile;
        renderContextPanelContent(container, cwt, activeProfile);

    } catch (err) {
        console.error('Failed to load context panel:', err);
        container.innerHTML = `<div class="text-center text-red-400 py-8">${escapeHtml(err.message)}</div>`;
    }
}

/**
 * Render the context window type composition in the resource panel.
 * When lastSnapshot is available, overlays dynamic runtime metrics on each
 * module card (allocated vs target, used tokens, contributing status).
 */
function renderContextPanelContent(container, cwt, profile) {
    const modules = cwt.modules || {};
    const activeModules = Object.entries(modules)
        .filter(([, m]) => m.active)
        .sort((a, b) => (b[1].priority || 0) - (a[1].priority || 0));
    const inactiveModules = Object.entries(modules).filter(([, m]) => !m.active);

    const outputReserve = cwt.output_reserve_pct || 12;

    // --- Snapshot lookup maps ---
    const snapshot = lastSnapshot;
    const contribMap = {};
    let budgetAvailable = 0;
    const adjustmentModules = {};

    if (snapshot) {
        budgetAvailable = snapshot.budget?.available || 0;
        for (const c of (snapshot.contributions || [])) {
            contribMap[c.module_id] = c;
        }
        // Map fired adjustments to affected modules using CW type rules
        for (const rule of (cwt.dynamic_adjustments || [])) {
            const fired = (snapshot.dynamic_adjustments || []).includes(rule.condition);
            if (!fired) continue;
            const action = rule.action || {};
            const affected = action.force_full || action.reduce || action.transfer || action.condense;
            if (affected) {
                if (!adjustmentModules[affected]) adjustmentModules[affected] = [];
                adjustmentModules[affected].push(rule.condition);
            }
            if (action.to) {
                if (!adjustmentModules[action.to]) adjustmentModules[action.to] = [];
                adjustmentModules[action.to].push(rule.condition);
            }
        }
    }

    // --- Target allocation bar (static) ---
    const targetBarSegments = activeModules.map(([id, m]) => {
        const pct = m.target_pct || 0;
        const color = getModuleColor(id);
        return `<div class="h-full rounded-sm transition-all" style="width:${pct}%;background:${color}"
                     title="${formatModuleName(id)}: ${pct}%"></div>`;
    }).join('');

    // --- Actual allocation bar (dynamic, from snapshot) ---
    let actualBarHtml = '';
    if (snapshot && budgetAvailable > 0) {
        const actualSegments = activeModules.map(([id]) => {
            const c = contribMap[id];
            if (!c) return '';
            const allocPct = (c.allocated / budgetAvailable) * 100;
            const color = getModuleColor(id);
            return `<div class="h-full rounded-sm" style="width:${allocPct.toFixed(1)}%;background:${color};opacity:0.7"
                         title="${formatModuleName(id)}: ${(c.allocated / 1000).toFixed(1)}K allocated"></div>`;
        }).join('');

        actualBarHtml = `
            <div class="flex gap-0.5 w-full h-2 rounded overflow-hidden bg-white/5">
                ${actualSegments}
            </div>`;
    }

    // --- Module cards with dynamic overlay ---
    const moduleCards = activeModules.map(([id, m]) => {
        const color = getModuleColor(id);
        const targetPct = m.target_pct || 0;
        const isRequired = (id === 'system_prompt' || id === 'conversation_history');
        const c = contribMap[id];

        // Dynamic overlay (only when snapshot exists)
        let overlayHtml = '';
        if (snapshot) {
            if (c) {
                const allocatedK = (c.allocated / 1000).toFixed(1);
                const usedK = (c.used / 1000).toFixed(1);
                const utilPct = c.allocated > 0 ? ((c.used / c.allocated) * 100).toFixed(0) : 0;
                const allocPct = budgetAvailable > 0 ? ((c.allocated / budgetAvailable) * 100).toFixed(1) : 0;
                const deltaPct = (parseFloat(allocPct) - targetPct).toFixed(1);
                const deltaSign = deltaPct > 0 ? '+' : '';
                const deltaColor = deltaPct > 0 ? 'text-emerald-400' : deltaPct < 0 ? 'text-amber-400' : 'text-gray-500';

                // Contributing indicator
                const isContributing = c.used > 0;
                const statusDot = isContributing
                    ? '<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>'
                    : '<span class="w-1.5 h-1.5 rounded-full bg-gray-600 inline-block"></span>';
                const statusText = isContributing
                    ? `<span class="text-emerald-400/80">${usedK}K</span>`
                    : '<span class="text-gray-500">idle</span>';

                // Usage bar color
                const utilNum = parseFloat(utilPct);
                const barColor = utilNum > 80 ? '#ef4444' : utilNum > 50 ? '#eab308' : '#10b981';
                const usedBarWidth = c.allocated > 0 ? Math.min((c.used / c.allocated) * 100, 100).toFixed(1) : 0;

                // Condensation indicator
                const condensedBadge = c.condensed
                    ? '<span class="text-[9px] px-1 py-0.5 rounded bg-yellow-500/20 text-yellow-400">condensed</span>'
                    : '';

                // Adjustment tags
                const adjTags = (adjustmentModules[id] || []).map(cond =>
                    `<span class="text-[9px] px-1 py-0.5 rounded bg-purple-500/15 text-purple-300">${cond.replace(/_/g, ' ')}</span>`
                ).join(' ');

                // Reallocation badge
                const reallocEvents = (snapshot.reallocation_events || []).filter(e => e.module_id === id);
                let reallocBadge = '';
                for (const re of reallocEvents) {
                    if (re.type === 'recipient') {
                        const gained = ((re.tokens || 0) / 1000).toFixed(1);
                        reallocBadge += `<span class="text-[9px] px-1 py-0.5 rounded bg-cyan-500/15 text-cyan-300">+${gained}K surplus</span>`;
                    } else if (re.type === 'donor') {
                        const gave = ((re.tokens || 0) / 1000).toFixed(1);
                        reallocBadge += `<span class="text-[9px] px-1 py-0.5 rounded bg-gray-500/15 text-gray-400">-${gave}K donated</span>`;
                    }
                }

                overlayHtml = `
                    <div class="mt-1.5 space-y-1">
                        <div class="flex items-center gap-2 text-[10px]">
                            <span class="text-gray-500 w-8">Alloc</span>
                            <div class="flex-1 h-1.5 rounded bg-white/5 overflow-hidden">
                                <div class="h-full rounded" style="width:${allocPct}%;background:${color};opacity:0.6"></div>
                            </div>
                            <span class="text-gray-400 tabular-nums">${allocatedK}K</span>
                            <span class="${deltaColor} tabular-nums">${deltaSign}${deltaPct}%</span>
                        </div>
                        <div class="flex items-center gap-2 text-[10px]">
                            <span class="text-gray-500 w-8">Used</span>
                            <div class="flex-1 h-1.5 rounded bg-white/5 overflow-hidden">
                                <div class="h-full rounded" style="width:${usedBarWidth}%;background:${barColor}"></div>
                            </div>
                            <span class="inline-flex items-center gap-1">${statusDot} ${statusText}</span>
                            <span class="text-gray-500 tabular-nums">${utilPct}%</span>
                        </div>
                        ${(condensedBadge || adjTags || reallocBadge) ? `<div class="flex flex-wrap gap-1">${condensedBadge} ${adjTags} ${reallocBadge}</div>` : ''}
                    </div>`;
            } else {
                // Module active in config but not in snapshot (skipped by profile type)
                overlayHtml = `
                    <div class="mt-1 text-[10px] text-gray-600 italic">Not applicable to current profile type</div>`;
            }
        }

        return `
            <div class="px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                <div class="flex items-center gap-3">
                    <div class="w-3 h-3 rounded-sm flex-shrink-0" style="background:${color}"></div>
                    <span class="text-sm text-white flex-1 truncate">${formatModuleName(id)}</span>
                    ${isRequired ? '<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300">Required</span>' : ''}
                    <span class="text-xs text-gray-400 tabular-nums">${targetPct}%</span>
                    <span class="text-[10px] text-gray-500">P${m.priority || 50}</span>
                </div>
                ${overlayHtml}
            </div>`;
    }).join('');

    // Inactive modules
    const inactiveCards = inactiveModules.length > 0 ? `
        <div class="mt-3 pt-3 border-t border-white/5">
            <p class="text-xs text-gray-500 mb-2">Inactive modules:</p>
            ${inactiveModules.map(([id]) => `
                <span class="inline-block text-xs px-2 py-0.5 rounded bg-white/5 text-gray-500 mr-1 mb-1">${formatModuleName(id)}</span>
            `).join('')}
        </div>` : '';

    // --- Compact summary line (replaces old "Last Query" section) ---
    let summaryLine = '';
    if (snapshot) {
        const totalUsed = snapshot.budget?.used || 0;
        const totalBudget = snapshot.budget?.available || 1;
        const totalPct = ((totalUsed / totalBudget) * 100).toFixed(1);
        const adjList = (snapshot.dynamic_adjustments || []).map(a => a.replace(/_/g, ' ')).join(', ');
        const condensations = snapshot.condensations || [];
        const distillations = snapshot.distillation_events || [];

        const reallocations = snapshot.reallocation_events || [];

        const parts = [`${(totalUsed / 1000).toFixed(1)}K / ${(totalBudget / 1000).toFixed(1)}K tokens (${totalPct}%)`];
        if (adjList) parts.push(`Adjustments: ${adjList}`);
        if (condensations.length > 0) {
            parts.push(`${condensations.length} condensation${condensations.length > 1 ? 's' : ''}`);
        }
        if (distillations.length > 0) {
            parts.push(`${distillations.length} distillation${distillations.length > 1 ? 's' : ''}`);
        }
        if (reallocations.length > 0) {
            const recipients = reallocations.filter(r => r.type === 'recipient').length;
            if (recipients > 0) parts.push(`${recipients} reallocation${recipients > 1 ? 's' : ''}`);
        }

        summaryLine = `
            <div class="mt-3 pt-3 border-t border-white/10">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-semibold text-gray-300">Last Query</span>
                    <span class="text-[10px] text-gray-500">Turn ${snapshot.turn_number || '?'}</span>
                </div>
                <p class="text-[10px] text-gray-400 mt-1">${parts.join(' · ')}</p>
            </div>`;
    }

    container.innerHTML = `
        <div class="space-y-3">
            <div class="flex items-center justify-between">
                <div>
                    <h4 class="text-sm font-bold text-white">${escapeHtml(cwt.name)}</h4>
                    <p class="text-xs text-gray-400">${escapeHtml(cwt.description || '')}</p>
                </div>
                <div class="text-right">
                    <span class="text-xs text-gray-500">Profile: ${escapeHtml(profile.name)}</span>
                    <div class="text-xs text-gray-500">${activeModules.length} active / ${outputReserve}% reserve</div>
                </div>
            </div>

            <div>
                <div class="flex items-center gap-2 mb-0.5">
                    <span class="text-[10px] text-gray-500 w-10">Target</span>
                    <div class="flex-1 flex gap-0.5 h-3 rounded overflow-hidden bg-white/5">
                        ${targetBarSegments}
                        <div class="h-full rounded-sm" style="width:${outputReserve}%;background:rgba(255,255,255,0.1)"
                             title="Output Reserve: ${outputReserve}%"></div>
                    </div>
                </div>
                ${actualBarHtml ? `
                <div class="flex items-center gap-2">
                    <span class="text-[10px] text-gray-500 w-10">Actual</span>
                    <div class="flex-1">${actualBarHtml}</div>
                </div>` : ''}
                <div class="flex justify-between text-[10px] text-gray-500 mt-1">
                    <span>Input Budget: ${100 - outputReserve}%</span>
                    <span>Output Reserve: ${outputReserve}%</span>
                </div>
            </div>

            <div class="space-y-1.5">
                ${moduleCards}
            </div>
            ${inactiveCards}
            ${summaryLine}
        </div>`;
}

/**
 * Handle a context_window_snapshot SSE event.
 * Called from processStream() when the event type is context_window_snapshot.
 *
 * @param {Object} snapshot - The snapshot payload from the SSE event
 * @returns {string} HTML string for the Live Status panel
 */
export function renderContextWindowSnapshot(snapshot) {
    lastSnapshot = snapshot;

    // Also update the Resource Panel's "Last Query" section if visible
    _refreshSnapshotInPanel();

    const used = snapshot.budget?.used || 0;
    const budget = snapshot.budget?.available || 1;
    const pct = ((used / budget) * 100).toFixed(1);
    const typeName = snapshot.context_window_type?.name || 'Unknown';

    // Build compact bar segments
    const contribs = snapshot.contributions || [];
    const barSegments = contribs.map(c => {
        const color = getModuleColor(c.module_id);
        const widthPct = budget > 0 ? ((c.used / budget) * 100).toFixed(1) : 0;
        const label = formatModuleName(c.module_id);
        const tokensK = (c.used / 1000).toFixed(1);
        return `<div class="h-2 rounded-sm" style="width:${widthPct}%;background:${color};min-width:2px"
                     title="${label}: ${tokensK}K tokens"></div>`;
    }).join('');

    // Condensation events
    const condensations = snapshot.condensations || [];
    const condensedText = condensations.length > 0
        ? condensations.map(c =>
            `${formatModuleName(c.module_id)} (${c.strategy}, saved ${((c.before - c.after) / 1000).toFixed(1)}K)`
        ).join(', ')
        : '';

    // Distillation events (intra-turn tactical planning)
    const distillations = snapshot.distillation_events || [];
    const distillationHtml = distillations.length > 0
        ? `<div class="text-[10px] text-cyan-400/70 mt-1.5">
               Distilled: ${distillations.map(d =>
                   `${(d.row_count || 0).toLocaleString()} rows → metadata`
               ).join(', ')}
           </div>`
        : '';

    // Reallocation events (Pass 3b surplus redistribution)
    const reallocations = snapshot.reallocation_events || [];
    const donorModules = reallocations.filter(r => r.type === 'donor');
    const recipientModules = reallocations.filter(r => r.type === 'recipient');
    let reallocationHtml = '';
    if (recipientModules.length > 0) {
        const totalSurplus = donorModules.reduce((sum, d) => sum + (d.tokens || 0), 0);
        const recipientDesc = recipientModules.map(r =>
            `${formatModuleName(r.module_id)} (+${((r.tokens || 0) / 1000).toFixed(1)}K)`
        ).join(', ');
        reallocationHtml = `<div class="text-[10px] text-cyan-300/70 mt-1.5">
            Reallocated: ${(totalSurplus / 1000).toFixed(1)}K surplus → ${recipientDesc}
        </div>`;
    }

    // Build labels row
    const labels = contribs.map(c => {
        const color = getModuleColor(c.module_id);
        const shortName = c.label || formatModuleName(c.module_id);
        const tokensK = (c.used / 1000).toFixed(1);
        return `<span class="text-[10px] text-gray-400" style="color:${color}">${shortName}(${tokensK}K)</span>`;
    }).join(' ');

    return `
        <div class="bg-white/5 border border-white/10 rounded-lg p-3 my-2">
            <div class="flex items-center justify-between mb-2">
                <span class="text-xs font-semibold text-gray-300">Context Window (${escapeHtml(typeName)})</span>
                <span class="text-xs text-gray-400 tabular-nums">${(used / 1000).toFixed(1)}K / ${(budget / 1000).toFixed(1)}K tokens (${pct}%)</span>
            </div>
            <div class="flex gap-0.5 w-full h-2 rounded overflow-hidden bg-white/5 mb-1.5">
                ${barSegments}
            </div>
            <div class="flex flex-wrap gap-x-2 gap-y-0.5">
                ${labels}
            </div>
            ${condensedText ? `<div class="text-[10px] text-yellow-400/70 mt-1.5">Condensed: ${escapeHtml(condensedText)}</div>` : ''}
            ${distillationHtml}
            ${reallocationHtml}
        </div>`;
}

/**
 * Refresh the Resource Panel context tab with latest snapshot overlay.
 * Called after a new context_window_snapshot SSE event arrives.
 * Only updates when the Context tab is visible to avoid wasted work.
 */
function _refreshSnapshotInPanel() {
    if (!lastSnapshot) return;
    const panel = document.getElementById('context-panel');
    if (!panel || panel.style.display === 'none') return;

    const container = document.getElementById('context-panel-content');
    if (!container) return;

    if (lastCwt && lastProfile) {
        renderContextPanelContent(container, lastCwt, lastProfile);
    } else {
        loadContextPanel();
    }
}

/**
 * Format a module ID to a human-readable name.
 */
function formatModuleName(moduleId) {
    const names = {
        system_prompt: 'Sys Prompt',
        tool_definitions: 'Tools',
        conversation_history: 'History',
        rag_context: 'RAG',
        knowledge_context: 'Knowledge',
        plan_hydration: 'Hydration',
        document_context: 'Documents',
        component_instructions: 'Components',
        workflow_history: 'Workflow',
    };
    return names[moduleId] || moduleId.replace(/_/g, ' ');
}
