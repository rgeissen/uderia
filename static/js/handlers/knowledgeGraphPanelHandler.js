/**
 * knowledgeGraphPanelHandler.js
 *
 * Manages Knowledge Graph views in two locations:
 *   1. Resource Panel sidebar — compact cards with active indicator + activate toggle
 *   2. Intelligence Performance page — full glass-panel cards with assignment management
 *
 * Active/Inactive model:
 *   - Multiple KGs can be ASSIGNED to a profile
 *   - Only ONE KG can be ACTIVE per profile at a time
 *   - The active KG is the one used for context enrichment
 *   - Self-assignment rows track the owner's own activation state
 */

import { state } from '../state.js';
import * as API from '../api.js';
import { showConfirmation } from '../ui.js';
import { showAppBanner } from '../bannerSystem.js';

// ── IFOC colour mapping (matches ifocTagConfig in configurationHandler.js) ──
const IFOC_CONFIG = {
    llm_only:     { label: 'Ideate',     color: '#4ade80' },
    rag_focused:  { label: 'Focus',      color: '#3b82f6' },
    tool_enabled: { label: 'Optimize',   color: '#F15F22' },
    genie:        { label: 'Coordinate', color: '#9333ea' },
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatTimeAgo(isoStr) {
    if (!isoStr) return 'Unknown';
    const now = Date.now();
    const then = new Date(isoStr).getTime();
    const diffMs = now - then;

    const mins  = Math.floor(diffMs / 60000);
    const hours = Math.floor(diffMs / 3600000);
    const days  = Math.floor(diffMs / 86400000);

    if (mins < 1)   return 'Just now';
    if (mins < 60)  return `${mins}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 30)  return `${days}d ago`;
    return new Date(isoStr).toLocaleDateString();
}

/**
 * Determine the active/available state of a KG relative to a specific profile.
 */
function _getKgStateForProfile(kg, profileId) {
    const isOwner = kg.profile_id === profileId;
    const assignedEntry = (kg.assigned_profiles || []).find(a => a.id === profileId);
    const isAssigned = !!assignedEntry;
    const isAvailable = isOwner || isAssigned;

    let isActive = false;
    if (isOwner) isActive = !!kg.is_active_for_owner;
    else if (assignedEntry) isActive = !!assignedEntry.is_active;

    return { isOwner, isAssigned, isAvailable, isActive };
}

// ── Resource Panel — Card creation ─────────────────────────────────────────

function createKnowledgeGraphCard(kg, kgState) {
    const ifoc = IFOC_CONFIG[kg.profile_type] || { label: kg.profile_type || 'Unknown', color: '#6b7280' };

    const detailsEl = document.createElement('details');
    detailsEl.className = 'resource-item kg-panel-card bg-gray-800/50 rounded-lg border border-gray-700/60';
    detailsEl.dataset.profileId = kg.profile_id;

    if (kgState.isActive) {
        detailsEl.style.borderLeftWidth = '4px';
        detailsEl.style.borderLeftColor = '#F15F22';
    }

    // Entity type pills
    const typePills = Object.entries(kg.entity_types || {})
        .map(([type, count]) =>
            `<span class="text-xs px-2 py-0.5 rounded" style="background: var(--hover-bg, rgba(75,85,99,0.4)); color: var(--text-muted, #9ca3af);">${type} (${count})</span>`
        ).join(' ');

    // Active badge (shown in summary line)
    const activeBadge = kgState.isActive
        ? '<span data-active-badge class="text-xs font-semibold px-2 py-0.5 rounded" style="color: #F15F22; background: rgba(241,95,34,0.15); border: 1px solid rgba(241,95,34,0.3);">ACTIVE</span>'
        : '';

    // IFOC badge
    const ifocBadge = `<span class="text-xs font-semibold px-1.5 py-0.5 rounded-full" style="color: ${ifoc.color}; background: ${ifoc.color}20; border: 1px solid ${ifoc.color}40;">${ifoc.label}</span>`;

    // Profile tag
    const tagLabel = kg.profile_tag
        ? `<span class="text-xs font-mono" style="color: var(--text-muted, #9ca3af);">@${kg.profile_tag}</span>`
        : '';

    // Owner label
    const ownerLabel = kgState.isOwner
        ? '<span class="text-xs text-gray-500">(own)</span>'
        : '';

    // Assigned profiles badges
    const assignedBadges = _renderAssignedProfilesBadges(kg);

    // Activate/deactivate button
    let activateBtn = '';
    if (kgState.isAvailable && !kgState.isActive) {
        activateBtn = `<button class="kg-activate-btn px-3 py-1 text-xs font-semibold rounded-md transition-colors"
                               style="background: rgba(241,95,34,0.15); color: #F15F22; border: 1px solid rgba(241,95,34,0.3);"
                               data-kg-owner-id="${kg.profile_id}" title="Activate this KG for context enrichment">Activate</button>`;
    } else if (kgState.isActive) {
        activateBtn = `<button class="kg-deactivate-btn px-3 py-1 text-xs font-semibold rounded-md transition-colors"
                               style="background: var(--hover-bg, #4b5563); color: var(--text-muted, #9ca3af);"
                               data-kg-owner-id="${kg.profile_id}" title="Deactivate this KG">Deactivate</button>`;
    }

    detailsEl.innerHTML = `
        <summary class="flex justify-between items-center p-3 font-semibold text-white hover:bg-gray-700/50 rounded-lg transition-colors cursor-pointer">
            <div class="flex items-center gap-2 flex-wrap min-w-0">
                <span class="truncate">${kg.profile_name || kg.profile_id}</span>
                ${tagLabel}
                ${ifocBadge}
                ${ownerLabel}
                ${activeBadge}
                <span class="text-xs font-normal" style="color: var(--text-muted, #6b7280);">${kg.total_entities} entities</span>
            </div>
            <svg class="chevron w-5 h-5 text-[#F15F22] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
        </summary>
        <div class="p-3 pt-2 text-sm space-y-3" style="color: var(--text-muted, #d1d5db);">
            <div class="flex gap-4 text-sm">
                <span>Entities: <strong style="color: var(--text-primary, #fff);">${kg.total_entities}</strong></span>
                <span>Relationships: <strong style="color: var(--text-primary, #fff);">${kg.total_relationships}</strong></span>
            </div>
            <div class="flex flex-wrap gap-1">${typePills || '<span class="text-xs" style="color: var(--text-muted, #6b7280);">No entities</span>'}</div>
            <div class="flex flex-wrap items-center gap-1">
                <span class="text-xs" style="color: var(--text-muted, #6b7280);">Shared with:</span>
                ${assignedBadges}
            </div>
            <div class="text-xs" style="color: var(--text-muted, #6b7280);">Last updated: ${formatTimeAgo(kg.last_updated)}</div>
            <div class="flex items-center gap-2 pt-2" style="border-top: 1px solid var(--border-primary, rgba(75,85,99,0.6));">
                ${activateBtn}
                <button class="kg-inspect-btn px-3 py-1 text-xs font-semibold rounded-md transition-colors"
                        style="background: rgba(147,51,234,0.15); color: #a78bfa; border: 1px solid rgba(147,51,234,0.3);"
                        data-profile-id="${kg.profile_id}" data-profile-name="${kg.profile_name || kg.profile_id}" title="Inspect knowledge graph">Inspect</button>
                <button class="kg-export-btn px-3 py-1 bg-blue-600 text-white text-xs font-semibold rounded-md hover:bg-blue-500 transition-colors"
                        data-profile-id="${kg.profile_id}" title="Export as JSON">Export</button>
                <button class="kg-delete-btn px-3 py-1 bg-red-600/80 text-white text-xs font-semibold rounded-md hover:bg-red-500 transition-colors"
                        data-profile-id="${kg.profile_id}" data-profile-name="${kg.profile_name || kg.profile_id}" title="Delete this knowledge graph">Delete</button>
            </div>
        </div>
    `;

    return detailsEl;
}

function renderEmptyState(container) {
    container.innerHTML = `
        <div class="flex flex-col items-center justify-center py-12 text-center">
            <svg class="w-12 h-12 mb-4" style="color: var(--text-muted, #6b7280);" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
            </svg>
            <p class="text-sm font-semibold mb-1" style="color: var(--text-primary, #e5e7eb);">No Knowledge Graphs</p>
            <p class="text-xs max-w-xs" style="color: var(--text-muted, #6b7280);">
                Knowledge graphs are built automatically when you use profiles with the KG component enabled.
                Entities and relationships are discovered during your conversations.
            </p>
        </div>
    `;
}

function renderLoadingState(container) {
    container.innerHTML = `
        <div class="flex items-center justify-center py-12">
            <div class="animate-spin rounded-full h-6 w-6 border-2 border-gray-500 border-t-[#F15F22]"></div>
            <span class="ml-3 text-sm" style="color: var(--text-muted, #9ca3af);">Loading knowledge graphs...</span>
        </div>
    `;
}

// ── Resource Panel — Main load function ────────────────────────────────────

export async function loadKnowledgeGraphsPanel() {
    const container = document.getElementById('knowledge-graphs-content');
    if (!container) return;

    renderLoadingState(container);

    try {
        const response = await API.loadKnowledgeGraphList();
        const graphs = response.knowledge_graphs || [];
        state.resourceData.knowledgeGraphs = graphs;

        const activeProfileId = state.currentResourcePanelProfileId;

        // Filter to only KGs that are owned by or assigned to the current profile
        const visibleGraphs = graphs.filter(kg => {
            const kgState = _getKgStateForProfile(kg, activeProfileId);
            return kgState.isAvailable;
        });

        // Update tab counter with visible count only
        const tabBtn = document.querySelector('.resource-tab[data-type="knowledge-graphs"]');
        if (tabBtn) {
            tabBtn.textContent = `Knowledge Graphs (${visibleGraphs.length})`;
        }

        if (visibleGraphs.length === 0) {
            renderEmptyState(container);
            return;
        }

        container.innerHTML = '';

        for (const kg of visibleGraphs) {
            const kgState = _getKgStateForProfile(kg, activeProfileId);
            const card = createKnowledgeGraphCard(kg, kgState);
            container.appendChild(card);
        }
    } catch (err) {
        console.error('Failed to load knowledge graphs:', err);
        container.innerHTML = `
            <div class="flex items-center justify-center py-12 text-center">
                <p class="text-sm" style="color: var(--text-muted, #ef4444);">Failed to load knowledge graphs: ${err.message}</p>
            </div>
        `;
    }
}

// ── Resource Panel — Refresh (re-fetch + re-render) ────────────────────────

export async function refreshKnowledgeGraphsPanel() {
    await loadKnowledgeGraphsPanel();
}

// ── Resource Panel — Active indicator update (DOM-only, no re-fetch) ───────

export function updateKnowledgeGraphActiveIndicator() {
    const container = document.getElementById('knowledge-graphs-content');
    if (!container) return;

    const activeProfileId = state.currentResourcePanelProfileId;
    const cards = container.querySelectorAll('.kg-panel-card');
    const graphs = state.resourceData?.knowledgeGraphs || [];

    cards.forEach(card => {
        const profileId = card.dataset.profileId;
        const kg = graphs.find(g => g.profile_id === profileId);
        if (!kg) return;

        const kgState = _getKgStateForProfile(kg, activeProfileId);

        // Update border
        card.style.borderLeftWidth = kgState.isActive ? '4px' : '';
        card.style.borderLeftColor = kgState.isActive ? '#F15F22' : '';

        // Update ACTIVE badge visibility
        const existingBadge = card.querySelector('[data-active-badge]');
        if (existingBadge) existingBadge.remove();

        if (kgState.isActive) {
            const nameRow = card.querySelector('summary .flex.items-center.gap-2');
            if (nameRow) {
                const badge = document.createElement('span');
                badge.setAttribute('data-active-badge', '');
                badge.className = 'text-xs font-semibold px-2 py-0.5 rounded';
                badge.style.cssText = 'color: #F15F22; background: rgba(241,95,34,0.15); border: 1px solid rgba(241,95,34,0.3);';
                badge.textContent = 'ACTIVE';
                nameRow.appendChild(badge);
            }
        }
    });
}

// ── Resource Panel — Action handlers ───────────────────────────────────────

async function handleExport(profileId) {
    try {
        await API.exportKnowledgeGraph(profileId);
        showAppBanner('Knowledge graph exported successfully', 'success');
    } catch (err) {
        console.error('Export failed:', err);
        showAppBanner(`Export failed: ${err.message}`, 'error');
    }
}

function handleDelete(profileId, profileName) {
    showConfirmation(
        'Delete Knowledge Graph',
        `<p>Are you sure you want to delete the knowledge graph for <strong>${profileName}</strong>?</p>
         <p class="mt-2 text-sm text-gray-400">This will permanently remove all entities and relationships. This action cannot be undone.</p>`,
        async () => {
            try {
                await API.deleteKnowledgeGraph(profileId);
                showAppBanner('Knowledge graph deleted', 'success');
                await refreshKnowledgeGraphsPanel();
            } catch (err) {
                console.error('Delete failed:', err);
                showAppBanner(`Delete failed: ${err.message}`, 'error');
            }
        }
    );
}

async function handleActivate(kgOwnerProfileId) {
    const activeProfileId = state.currentResourcePanelProfileId;
    if (!activeProfileId) return;

    try {
        await API.activateKgForProfile(kgOwnerProfileId, activeProfileId);
        showAppBanner('Knowledge graph activated', 'success');
        await refreshKnowledgeGraphsPanel();
        // Also refresh Intelligence tab if visible
        const intelContainer = document.getElementById('knowledge-graphs-grid-container');
        if (intelContainer) await loadKnowledgeGraphsIntelligenceTab();
    } catch (err) {
        console.error('Activate failed:', err);
        showAppBanner(`Activate failed: ${err.message}`, 'error');
    }
}

async function handleDeactivate(kgOwnerProfileId) {
    const activeProfileId = state.currentResourcePanelProfileId;
    if (!activeProfileId) return;

    try {
        // Deactivate all — pass null for kgOwnerProfileId
        await API.activateKgForProfile(null, activeProfileId);
        showAppBanner('Knowledge graph deactivated', 'success');
        await refreshKnowledgeGraphsPanel();
        const intelContainer = document.getElementById('knowledge-graphs-grid-container');
        if (intelContainer) await loadKnowledgeGraphsIntelligenceTab();
    } catch (err) {
        console.error('Deactivate failed:', err);
        showAppBanner(`Deactivate failed: ${err.message}`, 'error');
    }
}

// ── Resource Panel — Delegated click handler ───────────────────────────────

export function handleKnowledgeGraphPanelClick(e) {
    const activateBtn = e.target.closest('.kg-activate-btn');
    if (activateBtn) {
        handleActivate(activateBtn.dataset.kgOwnerId);
        return;
    }

    const deactivateBtn = e.target.closest('.kg-deactivate-btn');
    if (deactivateBtn) {
        handleDeactivate(deactivateBtn.dataset.kgOwnerId);
        return;
    }

    const inspectBtn = e.target.closest('.kg-inspect-btn');
    if (inspectBtn) {
        openKnowledgeGraphInspection(inspectBtn.dataset.profileId, inspectBtn.dataset.profileName);
        return;
    }

    const exportBtn = e.target.closest('.kg-export-btn');
    if (exportBtn) {
        const profileId = exportBtn.dataset.profileId;
        handleExport(profileId);
        return;
    }

    const deleteBtn = e.target.closest('.kg-delete-btn');
    if (deleteBtn) {
        const profileId = deleteBtn.dataset.profileId;
        const profileName = deleteBtn.dataset.profileName;
        handleDelete(profileId, profileName);
        return;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  Intelligence Performance Page — Knowledge Graphs Tab
// ═══════════════════════════════════════════════════════════════════════════════

function _renderAssignedProfilesBadges(kg) {
    const assigned = kg.assigned_profiles || [];
    if (assigned.length === 0) return '<span class="text-xs text-gray-600 italic">No additional profiles</span>';
    return assigned.map(ap => {
        const aIfoc = IFOC_CONFIG[ap.profile_type] || { label: ap.profile_type || '?', color: '#6b7280' };
        const isActive = !!ap.is_active;

        // Active: full color + green dot; Inactive: dimmed outline
        if (isActive) {
            return `<span class="kg-intel-activate-badge text-xs font-mono px-1.5 py-0.5 rounded cursor-pointer hover:opacity-80 transition-opacity"
                          style="color: ${aIfoc.color}; background: ${aIfoc.color}20; border: 1px solid ${aIfoc.color}50;"
                          data-kg-owner-id="${kg.profile_id}" data-assigned-id="${ap.id}" data-is-active="1"
                          title="Active — click to deactivate">
                        <span class="inline-block w-1.5 h-1.5 rounded-full mr-1" style="background: #22c55e;"></span>@${ap.tag || ap.name}</span>`;
        } else {
            return `<span class="kg-intel-activate-badge text-xs font-mono px-1.5 py-0.5 rounded cursor-pointer hover:opacity-80 transition-opacity"
                          style="color: ${aIfoc.color}60; background: transparent; border: 1px dashed ${aIfoc.color}30;"
                          data-kg-owner-id="${kg.profile_id}" data-assigned-id="${ap.id}" data-is-active="0"
                          title="Inactive — click to activate">@${ap.tag || ap.name}</span>`;
        }
    }).join(' ');
}

function createIntelligenceKGCard(kg) {
    const ifoc = IFOC_CONFIG[kg.profile_type] || { label: kg.profile_type || 'Unknown', color: '#6b7280' };

    const tagLabel = kg.profile_tag ? `@${kg.profile_tag}` : '';

    // Owner active state
    const ownerActive = !!kg.is_active_for_owner;
    const ownerStatusDot = ownerActive
        ? '<span class="inline-block w-1.5 h-1.5 rounded-full mr-1" style="background: #22c55e;"></span>'
        : '';
    const ownerStatusLabel = ownerActive ? 'owner, active' : 'owner, inactive';
    const ownerStatusStyle = ownerActive
        ? 'color: #9ca3af;'
        : 'color: #6b7280; opacity: 0.7;';

    // Entity type pills
    const typePills = Object.entries(kg.entity_types || {})
        .map(([type, count]) =>
            `<span class="text-xs px-2 py-0.5 rounded-full bg-white/5 text-gray-400">${type} (${count})</span>`
        ).join(' ');

    // Relationship type pills
    const relPills = Object.entries(kg.relationship_types || {})
        .map(([type, count]) =>
            `<span class="text-xs px-2 py-0.5 rounded-full bg-white/5 text-gray-400">${type} (${count})</span>`
        ).join(' ');

    // Assigned profiles section
    const assignedBadges = _renderAssignedProfilesBadges(kg);

    return `
        <div class="glass-panel p-4 rounded-lg hover:bg-white/5 transition-all" data-profile-id="${kg.profile_id}">
            <div class="flex items-start gap-3 mb-3">
                <div class="p-2 bg-purple-500/20 rounded-lg relative">
                    <svg class="w-6 h-6 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418"/>
                    </svg>
                    <div class="w-2 h-2 rounded-full absolute top-1 right-1" style="background: ${ifoc.color};"></div>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1 flex-wrap">
                        <h3 class="text-base font-semibold text-white truncate">${kg.profile_name || kg.profile_id}</h3>
                        ${tagLabel ? `<span class="text-xs font-mono text-gray-500">${tagLabel}</span>` : ''}
                        <span class="px-2 py-0.5 text-xs rounded-full font-semibold" style="color: ${ifoc.color}; background: ${ifoc.color}20; border: 1px solid ${ifoc.color}40;">${ifoc.label}</span>
                        <span class="kg-intel-owner-toggle text-xs cursor-pointer hover:opacity-80 transition-opacity" style="${ownerStatusStyle}"
                              data-kg-owner-id="${kg.profile_id}" data-is-active="${ownerActive ? '1' : '0'}"
                              title="Click to ${ownerActive ? 'deactivate' : 'activate'} for owner profile">${ownerStatusDot}(${ownerStatusLabel})</span>
                    </div>
                    <p class="text-xs text-gray-500">Profile ID: ${kg.profile_id}</p>
                </div>
            </div>

            <!-- Assigned profiles -->
            <div class="mb-3 p-2 rounded-lg bg-white/[0.02] border border-white/5">
                <div class="flex items-center justify-between mb-1.5">
                    <span class="text-xs text-gray-500 font-medium">Assigned to profiles</span>
                    <button class="kg-intel-assign-btn text-xs font-semibold px-2 py-0.5 rounded bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 transition-colors"
                            data-profile-id="${kg.profile_id}" data-profile-name="${kg.profile_name || kg.profile_id}">
                        Manage
                    </button>
                </div>
                <div class="flex flex-wrap gap-1 kg-assigned-badges" data-owner-id="${kg.profile_id}">
                    ${assignedBadges}
                </div>
            </div>

            <div class="text-xs text-gray-500 mb-2 flex items-center gap-3">
                <span><span class="text-white font-medium">${kg.total_entities}</span> entities</span>
                <span>&bull;</span>
                <span><span class="text-white font-medium">${kg.total_relationships}</span> relationships</span>
            </div>

            ${typePills ? `<div class="flex flex-wrap gap-1 mb-2">${typePills}</div>` : ''}
            ${relPills ? `<div class="flex flex-wrap gap-1 mb-2">${relPills}</div>` : ''}

            <p class="text-xs text-gray-500 mb-3">Last updated: ${formatTimeAgo(kg.last_updated)}</p>

            <div class="flex gap-2 flex-wrap">
                <button class="kg-intel-inspect-btn card-btn card-btn--primary" data-profile-id="${kg.profile_id}" data-profile-name="${kg.profile_name || kg.profile_id}">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                    </svg>
                    Inspect
                </button>
                <button class="kg-intel-export-btn card-btn card-btn--cyan" data-profile-id="${kg.profile_id}">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                    </svg>
                    Export
                </button>
                <button class="kg-intel-delete-btn card-btn card-btn--danger" data-profile-id="${kg.profile_id}" data-profile-name="${kg.profile_name || kg.profile_id}">
                    Delete
                </button>
                <button class="card-btn" disabled title="Coming soon">
                    Promote
                </button>
            </div>
        </div>
    `;
}

// ── Intelligence page — load & render ────────────────────────────────────────

export async function loadKnowledgeGraphsIntelligenceTab() {
    const container = document.getElementById('knowledge-graphs-grid-container');
    if (!container) return;

    // Loading state
    container.innerHTML = `
        <div class="col-span-full flex items-center justify-center py-12">
            <div class="animate-spin rounded-full h-6 w-6 border-2 border-gray-500 border-t-[#F15F22]"></div>
            <span class="ml-3 text-sm text-gray-400">Loading knowledge graphs...</span>
        </div>
    `;

    try {
        const response = await API.loadKnowledgeGraphList();
        const graphs = response.knowledge_graphs || [];

        // Also keep cached for Resource Panel
        state.resourceData.knowledgeGraphs = graphs;

        // Update tab counter
        const tabBtn = document.getElementById('knowledge-graphs-tab');
        if (tabBtn) {
            tabBtn.textContent = `Knowledge Graphs (${graphs.length})`;
        }

        if (graphs.length === 0) {
            container.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <svg class="w-16 h-16 mx-auto text-gray-600 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418"/>
                    </svg>
                    <p class="text-gray-400 text-sm">No Knowledge Graphs yet.</p>
                    <p class="text-gray-500 text-xs mt-1">Knowledge graphs are built automatically when you use profiles with the KG component enabled.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = graphs.map(kg => createIntelligenceKGCard(kg)).join('');
        attachIntelligenceKGHandlers(container);
    } catch (err) {
        console.error('[KG Intelligence] Failed to load:', err);
        container.innerHTML = `
            <div class="col-span-full text-center text-red-400 text-sm py-12">
                Failed to load knowledge graphs: ${err.message}
            </div>
        `;
    }
}

// ── Intelligence page — card action handlers ─────────────────────────────────

function attachIntelligenceKGHandlers(container) {
    container.addEventListener('click', async (e) => {
        const inspectBtn = e.target.closest('.kg-intel-inspect-btn');
        if (inspectBtn) {
            openKnowledgeGraphInspection(inspectBtn.dataset.profileId, inspectBtn.dataset.profileName);
            return;
        }

        const exportBtn = e.target.closest('.kg-intel-export-btn');
        if (exportBtn) {
            handleExport(exportBtn.dataset.profileId);
            return;
        }

        const deleteBtn = e.target.closest('.kg-intel-delete-btn');
        if (deleteBtn) {
            handleIntelligenceDelete(deleteBtn.dataset.profileId, deleteBtn.dataset.profileName);
            return;
        }

        const assignBtn = e.target.closest('.kg-intel-assign-btn');
        if (assignBtn) {
            const ownerProfileId = assignBtn.dataset.profileId;
            const ownerName = assignBtn.dataset.profileName;
            _openAssignmentPanel(ownerProfileId, ownerName, container);
            return;
        }

        // Toggle activation from assigned profile badges
        const activateBadge = e.target.closest('.kg-intel-activate-badge');
        if (activateBadge) {
            const kgOwnerId = activateBadge.dataset.kgOwnerId;
            const assignedId = activateBadge.dataset.assignedId;
            const isCurrentlyActive = activateBadge.dataset.isActive === '1';

            try {
                if (isCurrentlyActive) {
                    // Deactivate: pass null for kgOwnerProfileId
                    await API.activateKgForProfile(null, assignedId);
                    showAppBanner('Knowledge graph deactivated for profile', 'success');
                } else {
                    await API.activateKgForProfile(kgOwnerId, assignedId);
                    showAppBanner('Knowledge graph activated for profile', 'success');
                }
                await loadKnowledgeGraphsIntelligenceTab();
                if (state.resourceData.knowledgeGraphs !== null) {
                    await loadKnowledgeGraphsPanel();
                }
            } catch (err) {
                console.error('[KG] Toggle activation failed:', err);
                showAppBanner(`Activation failed: ${err.message}`, 'error');
            }
            return;
        }

        // Toggle owner's own activation
        const ownerToggle = e.target.closest('.kg-intel-owner-toggle');
        if (ownerToggle) {
            const kgOwnerId = ownerToggle.dataset.kgOwnerId;
            const isCurrentlyActive = ownerToggle.dataset.isActive === '1';

            try {
                if (isCurrentlyActive) {
                    await API.activateKgForProfile(null, kgOwnerId);
                    showAppBanner('Knowledge graph deactivated for owner', 'success');
                } else {
                    await API.activateKgForProfile(kgOwnerId, kgOwnerId);
                    showAppBanner('Knowledge graph activated for owner', 'success');
                }
                await loadKnowledgeGraphsIntelligenceTab();
                if (state.resourceData.knowledgeGraphs !== null) {
                    await loadKnowledgeGraphsPanel();
                }
            } catch (err) {
                console.error('[KG] Toggle owner activation failed:', err);
                showAppBanner(`Activation failed: ${err.message}`, 'error');
            }
            return;
        }
    });
}

function handleIntelligenceDelete(profileId, profileName) {
    showConfirmation(
        'Delete Knowledge Graph',
        `<p>Are you sure you want to delete the knowledge graph for <strong>${profileName}</strong>?</p>
         <p class="mt-2 text-sm text-gray-400">This will permanently remove all entities and relationships. This action cannot be undone.</p>`,
        async () => {
            try {
                await API.deleteKnowledgeGraph(profileId);
                showAppBanner('Knowledge graph deleted', 'success');
                await loadKnowledgeGraphsIntelligenceTab();
                // Also refresh resource panel if it was loaded
                if (state.resourceData.knowledgeGraphs !== null) {
                    await loadKnowledgeGraphsPanel();
                }
            } catch (err) {
                console.error('Delete failed:', err);
                showAppBanner(`Delete failed: ${err.message}`, 'error');
            }
        }
    );
}

// ── Assignment panel ─────────────────────────────────────────────────────────

let _assignOverlay = null;

function _openAssignmentPanel(ownerProfileId, ownerName, parentContainer) {
    // Close any existing overlay
    if (_assignOverlay) {
        _assignOverlay.remove();
        _assignOverlay = null;
    }

    const allProfiles = window.configState?.profiles || [];
    // All profiles are candidates except the owner itself
    const candidates = allProfiles.filter(p => p.id !== ownerProfileId);

    if (candidates.length === 0) {
        showAppBanner('No other profiles available for assignment.', 'info');
        return;
    }

    // Find currently assigned profiles from the cached data
    const graphs = state.resourceData?.knowledgeGraphs || [];
    const thisKg = graphs.find(g => g.profile_id === ownerProfileId);
    const currentlyAssigned = new Set((thisKg?.assigned_profiles || []).map(a => a.id));

    _assignOverlay = document.createElement('div');
    _assignOverlay.className = 'fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm';
    _assignOverlay.style.opacity = '0';
    _assignOverlay.style.transition = 'opacity 200ms';

    const checkboxes = candidates.map(p => {
        const ifoc = IFOC_CONFIG[p.profile_type] || { label: p.profile_type || '?', color: '#6b7280' };
        const checked = currentlyAssigned.has(p.id) ? 'checked' : '';
        return `
            <label class="flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 cursor-pointer transition-colors">
                <input type="checkbox" class="kg-assign-check w-4 h-4 rounded border-gray-600 bg-gray-800 text-purple-500 focus:ring-purple-500 focus:ring-offset-0"
                       data-profile-id="${p.id}" ${checked} />
                <span class="text-xs font-mono" style="color: ${ifoc.color};">@${p.tag || p.name}</span>
                <span class="text-xs text-gray-500">${p.name || p.id}</span>
                <span class="text-xs px-1.5 py-0.5 rounded-full ml-auto" style="color: ${ifoc.color}; background: ${ifoc.color}15; border: 1px solid ${ifoc.color}30;">${ifoc.label}</span>
            </label>
        `;
    }).join('');

    _assignOverlay.innerHTML = `
        <div class="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-md max-h-[70vh] overflow-hidden flex flex-col transform scale-95 transition-transform duration-200"
             id="kg-assign-modal-content">
            <div class="p-5 border-b border-white/10">
                <div class="flex items-center justify-between">
                    <div>
                        <h3 class="text-base font-bold text-white">Assign Profiles</h3>
                        <p class="text-xs text-gray-400 mt-1">Select which profiles can use the KG from <span class="text-purple-400 font-mono">@${thisKg?.profile_tag || ownerName}</span></p>
                    </div>
                    <button id="kg-assign-close" class="text-gray-400 hover:text-white transition-colors p-1">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="flex-1 overflow-y-auto p-4 space-y-1">
                ${checkboxes}
            </div>
            <div class="p-4 border-t border-white/10 flex items-center justify-end gap-3">
                <button id="kg-assign-cancel" class="card-btn card-btn--neutral px-4">Cancel</button>
                <button id="kg-assign-save" class="card-btn card-btn--primary px-4">Save Assignments</button>
            </div>
        </div>
    `;

    document.body.appendChild(_assignOverlay);

    // Animate in
    requestAnimationFrame(() => {
        _assignOverlay.style.opacity = '1';
        const content = _assignOverlay.querySelector('#kg-assign-modal-content');
        if (content) {
            content.style.transform = 'scale(1)';
        }
    });

    // Close handlers
    const closePanel = () => {
        if (!_assignOverlay) return;
        _assignOverlay.style.opacity = '0';
        setTimeout(() => {
            if (_assignOverlay) {
                _assignOverlay.remove();
                _assignOverlay = null;
            }
        }, 200);
    };

    _assignOverlay.querySelector('#kg-assign-close').addEventListener('click', closePanel);
    _assignOverlay.querySelector('#kg-assign-cancel').addEventListener('click', closePanel);
    _assignOverlay.addEventListener('click', (e) => {
        if (e.target === _assignOverlay) closePanel();
    });

    // Save handler
    _assignOverlay.querySelector('#kg-assign-save').addEventListener('click', async () => {
        const checked = _assignOverlay.querySelectorAll('.kg-assign-check:checked');
        const assignedIds = Array.from(checked).map(cb => cb.dataset.profileId);

        const saveBtn = _assignOverlay.querySelector('#kg-assign-save');
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';

        try {
            await API.updateKgAssignments(ownerProfileId, assignedIds);
            showAppBanner(`Assigned ${assignedIds.length} profile(s) to knowledge graph`, 'success');
            closePanel();

            // Refresh both views
            await loadKnowledgeGraphsIntelligenceTab();
            if (state.resourceData.knowledgeGraphs !== null) {
                await loadKnowledgeGraphsPanel();
            }
        } catch (err) {
            console.error('[KG Assignment] Save failed:', err);
            showAppBanner(`Failed to save assignments: ${err.message}`, 'error');
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save Assignments';
        }
    });
}

// ── Knowledge Graph Inspection (full D3 graph view) ──────────────────────────

let _kgInspectFullscreen = false;

export async function openKnowledgeGraphInspection(profileId, profileName) {
    const { handleViewSwitch } = await import('../ui.js?v=1.5');
    const { renderKnowledgeGraph } = await import('/api/v1/components/knowledge_graph/renderer');

    // Switch to inspect view
    handleViewSwitch('kg-inspect-view');

    // Update title
    const titleEl = document.getElementById('kg-inspect-title');
    if (titleEl) titleEl.textContent = `Inspect: ${profileName}`;

    // Show loading spinner
    const contentArea = document.getElementById('kg-inspect-content');
    contentArea.innerHTML = `
        <div class="flex items-center justify-center flex-1">
            <div class="animate-spin rounded-full h-8 w-8 border-2 border-gray-500 border-t-purple-500"></div>
            <span class="ml-3 text-sm text-gray-400">Loading knowledge graph...</span>
        </div>
    `;

    // Wire handlers immediately (back button should always work)
    _wireKGInspectHandlers();

    try {
        const response = await API.fetchKnowledgeGraphSpec(profileId);
        const spec = response.spec;

        if (!spec || !spec.nodes || spec.nodes.length === 0) {
            contentArea.innerHTML = `
                <div class="flex flex-col items-center justify-center flex-1 text-center">
                    <svg class="w-16 h-16 text-gray-600 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418"/>
                    </svg>
                    <p class="text-gray-400 text-sm">This knowledge graph is empty.</p>
                    <p class="text-gray-500 text-xs mt-1">Entities and relationships will appear here once the graph is populated.</p>
                </div>
            `;
            return;
        }

        // Clear and create render target with kg-split- prefix (triggers renderKGFull in renderer)
        contentArea.innerHTML = '';
        const renderTarget = document.createElement('div');
        renderTarget.id = `kg-split-inspect-${Date.now()}`;
        renderTarget.style.cssText = 'flex:1;display:flex;flex-direction:column;min-height:0;';
        contentArea.appendChild(renderTarget);

        // Render full interactive D3 graph (toolbar + force graph + legend)
        renderKnowledgeGraph(renderTarget.id, spec);
    } catch (err) {
        console.error('[KG Inspect] Failed to load graph:', err);
        contentArea.innerHTML = `
            <div class="flex flex-col items-center justify-center flex-1 text-center">
                <p class="text-red-400 text-sm">Failed to load knowledge graph: ${err.message}</p>
                <button onclick="document.getElementById('kg-inspect-back')?.click()"
                        class="card-btn card-btn--neutral mt-4">Go Back</button>
            </div>
        `;
    }
}

function _wireKGInspectHandlers() {
    const backBtn = document.getElementById('kg-inspect-back');
    if (backBtn) {
        backBtn.onclick = async () => {
            // Exit fullscreen if active
            if (_kgInspectFullscreen) {
                _kgInspectFullscreen = false;
                const mainArea = document.getElementById('main-content-area');
                if (mainArea) mainArea.classList.remove('kg-fullscreen');
                document.documentElement.style.removeProperty('--kg-fullscreen-top');
            }
            const { handleViewSwitch } = await import('../ui.js?v=1.5');
            handleViewSwitch('rag-maintenance-view');
        };
    }

    const fsBtn = document.getElementById('kg-inspect-fullscreen');
    if (fsBtn) {
        fsBtn.onclick = () => {
            _kgInspectFullscreen = !_kgInspectFullscreen;
            const mainArea = document.getElementById('main-content-area');
            if (_kgInspectFullscreen) {
                mainArea.classList.add('kg-fullscreen');
                // Offset for any top nav bar
                const nav = document.querySelector('nav, .top-nav');
                if (nav) {
                    document.documentElement.style.setProperty('--kg-fullscreen-top', nav.offsetHeight + 'px');
                }
            } else {
                mainArea.classList.remove('kg-fullscreen');
                document.documentElement.style.removeProperty('--kg-fullscreen-top');
            }
            // Update icon to reflect state
            fsBtn.title = _kgInspectFullscreen ? 'Exit fullscreen' : 'Toggle fullscreen';
        };
    }
}

// ── Import handler ───────────────────────────────────────────────────────────

export function initializeImportHandler() {
    const importBtn = document.getElementById('import-knowledge-graph-btn');
    if (!importBtn) return;

    importBtn.addEventListener('click', () => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';

        // iPadOS file picker workaround
        if (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) {
            input.removeAttribute('accept');
        }

        input.addEventListener('change', async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;

            try {
                const text = await file.text();
                const data = JSON.parse(text);

                const entities = data.entities || [];
                const relationships = data.relationships || [];

                if (!entities.length && !relationships.length) {
                    showAppBanner('Import file contains no entities or relationships', 'error');
                    return;
                }

                // Build profile dropdown options
                const profiles = window.configState?.profiles || [];
                const fileProfileId = data.profile_id || '';
                const ifocLabels = {
                    llm_only: 'Ideate', rag_focused: 'Focus',
                    tool_enabled: 'Optimize', genie: 'Coordinate'
                };

                const optionsHtml = profiles.map(p => {
                    const label = `@${p.tag || p.name} (${ifocLabels[p.profile_type] || p.profile_type})`;
                    const selected = p.id === fileProfileId ? ' selected' : '';
                    return `<option value="${p.id}"${selected}>${label}</option>`;
                }).join('');

                const summary = `<span class="text-gray-400">${entities.length} entities, ${relationships.length} relationships</span>`;

                showConfirmation(
                    'Import Knowledge Graph',
                    `<div class="space-y-3">
                        <p class="text-sm text-gray-300">File: <span class="text-white font-medium">${file.name}</span> — ${summary}</p>
                        <div>
                            <label class="block text-xs text-gray-400 mb-1">Target Profile</label>
                            <select id="kg-import-profile-select"
                                    class="w-full p-2 text-sm text-white rounded-lg outline-none cursor-pointer appearance-none"
                                    style="background: rgba(30, 30, 40, 0.8); border: 1px solid rgba(147, 51, 234, 0.3); background-image: url('data:image/svg+xml;charset=UTF-8,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 12 12%22%3E%3Cpath fill=%22%239ca3af%22 d=%22M2 4l4 4 4-4%22/%3E%3C/svg%3E'); background-repeat: no-repeat; background-position: right 0.75rem center;">
                                ${optionsHtml}
                            </select>
                        </div>
                    </div>`,
                    async () => {
                        const selectedProfileId = document.getElementById('kg-import-profile-select')?.value;
                        if (!selectedProfileId) {
                            showAppBanner('Please select a target profile', 'error');
                            return;
                        }

                        importBtn.disabled = true;
                        importBtn.textContent = 'Importing...';

                        try {
                            const result = await API.importKnowledgeGraph(selectedProfileId, entities, relationships);
                            showAppBanner(
                                `Imported ${result.entities_added || 0} entities and ${result.relationships_added || 0} relationships`,
                                'success'
                            );
                            await loadKnowledgeGraphsIntelligenceTab();
                            if (state.resourceData.knowledgeGraphs !== null) {
                                await loadKnowledgeGraphsPanel();
                            }
                        } catch (importErr) {
                            console.error('[KG Import] Failed:', importErr);
                            showAppBanner(`Import failed: ${importErr.message}`, 'error');
                        } finally {
                            importBtn.disabled = false;
                            importBtn.innerHTML = `
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path>
                                </svg>
                                Import
                            `;
                        }
                    }
                );
            } catch (err) {
                console.error('[KG Import] Parse failed:', err);
                showAppBanner(`Import failed: ${err.message}`, 'error');
            }
        });

        input.click();
    });
}
