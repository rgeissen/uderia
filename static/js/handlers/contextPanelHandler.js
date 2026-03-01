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

// Cached snapshot from last query
let lastSnapshot = null;

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
        renderContextPanelContent(container, cwt, activeProfile);

    } catch (err) {
        console.error('Failed to load context panel:', err);
        container.innerHTML = `<div class="text-center text-red-400 py-8">${escapeHtml(err.message)}</div>`;
    }
}

/**
 * Render the context window type composition in the resource panel.
 */
function renderContextPanelContent(container, cwt, profile) {
    const modules = cwt.modules || {};
    const activeModules = Object.entries(modules)
        .filter(([, m]) => m.active)
        .sort((a, b) => (b[1].priority || 0) - (a[1].priority || 0));
    const inactiveModules = Object.entries(modules).filter(([, m]) => !m.active);

    const outputReserve = cwt.output_reserve_pct || 12;
    const totalTargetPct = activeModules.reduce((sum, [, m]) => sum + (m.target_pct || 0), 0);

    // Build stacked bar
    const barSegments = activeModules.map(([id, m]) => {
        const pct = m.target_pct || 0;
        const color = getModuleColor(id);
        return `<div class="h-full rounded-sm transition-all" style="width:${pct}%;background:${color}"
                     title="${formatModuleName(id)}: ${pct}%"></div>`;
    }).join('');

    // Build module cards
    const moduleCards = activeModules.map(([id, m]) => {
        const color = getModuleColor(id);
        const pct = m.target_pct || 0;
        const isRequired = (id === 'system_prompt' || id === 'conversation_history');

        return `
            <div class="flex items-center gap-3 px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                <div class="w-3 h-3 rounded-sm flex-shrink-0" style="background:${color}"></div>
                <span class="text-sm text-white flex-1 truncate">${formatModuleName(id)}</span>
                ${isRequired ? '<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300">Required</span>' : ''}
                <span class="text-xs text-gray-400 tabular-nums">${pct}%</span>
                <span class="text-[10px] text-gray-500">P${m.priority || 50}</span>
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

    // Last snapshot section
    const snapshotSection = lastSnapshot ? renderSnapshotSummary(lastSnapshot) : '';

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

            <div class="flex gap-0.5 w-full h-3 rounded overflow-hidden bg-white/5">
                ${barSegments}
                <div class="h-full rounded-sm" style="width:${outputReserve}%;background:rgba(255,255,255,0.1)"
                     title="Output Reserve: ${outputReserve}%"></div>
            </div>
            <div class="flex justify-between text-[10px] text-gray-500">
                <span>Input Budget: ${100 - outputReserve}%</span>
                <span>Output Reserve: ${outputReserve}%</span>
            </div>

            <div class="space-y-1.5">
                ${moduleCards}
            </div>
            ${inactiveCards}
            <div id="context-panel-snapshot">${snapshotSection}</div>
        </div>`;
}

/**
 * Render a snapshot summary for the Context panel (after a query completes).
 */
function renderSnapshotSummary(snapshot) {
    const used = snapshot.total_used || 0;
    const budget = snapshot.available_budget || 1;
    const pct = ((used / budget) * 100).toFixed(1);

    const contribs = (snapshot.contributions || []).map(c => {
        const color = getModuleColor(c.module_id);
        const usedK = (c.tokens_used / 1000).toFixed(1);
        return `<span class="inline-flex items-center gap-1 text-[10px]">
            <span class="w-2 h-2 rounded-sm" style="background:${color}"></span>
            ${formatModuleName(c.module_id)}: ${usedK}K
        </span>`;
    }).join(' ');

    // Distillation events
    const distillations = snapshot.distillation_events || [];
    const distillationLine = distillations.length > 0
        ? `<div class="text-[10px] text-cyan-400/70 mt-1">Distilled: ${distillations.length} result set${distillations.length > 1 ? 's' : ''} (${distillations.map(d => `${(d.row_count || 0).toLocaleString()} rows`).join(', ')})</div>`
        : '';

    return `
        <div class="mt-3 pt-3 border-t border-white/10">
            <div class="flex items-center justify-between mb-2">
                <span class="text-xs font-semibold text-gray-300">Last Query</span>
                <span class="text-xs text-gray-400 tabular-nums">${(used / 1000).toFixed(1)}K / ${(budget / 1000).toFixed(1)}K tokens (${pct}%)</span>
            </div>
            <div class="flex flex-wrap gap-2">${contribs}</div>
            ${distillationLine}
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

    const used = snapshot.total_used || 0;
    const budget = snapshot.available_budget || 1;
    const pct = ((used / budget) * 100).toFixed(1);
    const typeName = snapshot.context_window_type_name || 'Unknown';

    // Build compact bar segments
    const contribs = snapshot.contributions || [];
    const barSegments = contribs.map(c => {
        const color = getModuleColor(c.module_id);
        const widthPct = budget > 0 ? ((c.tokens_used / budget) * 100).toFixed(1) : 0;
        const label = formatModuleName(c.module_id);
        const tokensK = (c.tokens_used / 1000).toFixed(1);
        return `<div class="h-2 rounded-sm" style="width:${widthPct}%;background:${color};min-width:2px"
                     title="${label}: ${tokensK}K tokens"></div>`;
    }).join('');

    // Condensation events
    const condensations = snapshot.condensations || [];
    const condensedText = condensations.length > 0
        ? condensations.map(c =>
            `${formatModuleName(c.module_id)} (${c.strategy}, saved ${((c.tokens_before - c.tokens_after) / 1000).toFixed(1)}K)`
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

    // Build labels row
    const labels = contribs.map(c => {
        const color = getModuleColor(c.module_id);
        const shortName = c.label || formatModuleName(c.module_id);
        const tokensK = (c.tokens_used / 1000).toFixed(1);
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
        </div>`;
}

/**
 * Refresh the "Last Query" snapshot section in the Resource Panel context tab.
 * Called after a new context_window_snapshot SSE event arrives.
 */
function _refreshSnapshotInPanel() {
    if (!lastSnapshot) return;
    const el = document.getElementById('context-panel-snapshot');
    if (!el) return;
    el.innerHTML = renderSnapshotSummary(lastSnapshot);
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
