/**
 * knowledgeGraphPanelHandler.js
 *
 * Manages Knowledge Graph views in two locations:
 *   1. Resource Panel sidebar — compact cards with active indicator
 *   2. Intelligence Performance page — full glass-panel cards with Import/Export/Delete
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

// ── Card creation ───────────────────────────────────────────────────────────

function createKnowledgeGraphCard(kg, isActive) {
    const ifoc = IFOC_CONFIG[kg.profile_type] || { label: kg.profile_type || 'Unknown', color: '#6b7280' };

    const card = document.createElement('div');
    card.className = 'kg-panel-card rounded-lg border p-4 transition-all';
    card.dataset.profileId = kg.profile_id;
    card.style.background = 'var(--card-bg, rgba(31, 41, 55, 0.5))';
    card.style.borderColor = 'var(--border-primary, rgba(75, 85, 99, 0.6))';

    if (isActive) {
        card.style.borderLeftWidth = '4px';
        card.style.borderLeftColor = '#F15F22';
    }

    // Entity type pills
    const typePills = Object.entries(kg.entity_types || {})
        .map(([type, count]) =>
            `<span class="text-xs px-2 py-0.5 rounded" style="background: var(--hover-bg, rgba(75,85,99,0.4)); color: var(--text-muted, #9ca3af);">${type} (${count})</span>`
        ).join(' ');

    // Active badge
    const activeBadge = isActive
        ? '<span class="text-xs font-semibold px-2 py-0.5 rounded" style="color: #F15F22; background: rgba(241,95,34,0.15); border: 1px solid rgba(241,95,34,0.3);">ACTIVE</span>'
        : '';

    // IFOC badge
    const ifocBadge = `<span class="text-xs font-semibold px-2 py-0.5 rounded-full" style="color: ${ifoc.color}; background: ${ifoc.color}20; border: 1px solid ${ifoc.color}40;">${ifoc.label}</span>`;

    // Profile tag
    const tagLabel = kg.profile_tag
        ? `<span class="text-xs font-mono" style="color: var(--text-muted, #9ca3af);">@${kg.profile_tag}</span>`
        : '';

    card.innerHTML = `
        <div class="flex justify-between items-center mb-2">
            <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold" style="color: var(--text-primary, #e5e7eb);">${kg.profile_name || kg.profile_id}</span>
                ${tagLabel}
                ${ifocBadge}
                ${activeBadge}
            </div>
        </div>
        <div class="flex gap-4 text-sm mb-2" style="color: var(--text-muted, #d1d5db);">
            <span>Entities: <strong style="color: var(--text-primary, #fff);">${kg.total_entities}</strong></span>
            <span>Relationships: <strong style="color: var(--text-primary, #fff);">${kg.total_relationships}</strong></span>
        </div>
        <div class="flex flex-wrap gap-1 mb-3">${typePills || '<span class="text-xs" style="color: var(--text-muted, #6b7280);">No entities</span>'}</div>
        <div class="text-xs mb-3" style="color: var(--text-muted, #6b7280);">Last updated: ${formatTimeAgo(kg.last_updated)}</div>
        <div class="flex items-center gap-2 pt-2" style="border-top: 1px solid var(--border-primary, rgba(75,85,99,0.6));">
            <button class="kg-export-btn px-3 py-1 bg-blue-600 text-white text-xs font-semibold rounded-md hover:bg-blue-500 transition-colors"
                    data-profile-id="${kg.profile_id}" title="Export as JSON">Export</button>
            <button class="kg-promote-btn px-3 py-1 text-xs font-semibold rounded-md cursor-not-allowed opacity-50"
                    style="background: var(--hover-bg, #4b5563); color: var(--text-muted, #9ca3af);"
                    disabled title="Coming soon">Promote</button>
            <button class="kg-delete-btn px-3 py-1 bg-red-600/80 text-white text-xs font-semibold rounded-md hover:bg-red-500 transition-colors"
                    data-profile-id="${kg.profile_id}" data-profile-name="${kg.profile_name || kg.profile_id}" title="Delete this knowledge graph">Delete</button>
        </div>
    `;

    return card;
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

// ── Main load function ──────────────────────────────────────────────────────

export async function loadKnowledgeGraphsPanel() {
    const container = document.getElementById('knowledge-graphs-content');
    if (!container) return;

    renderLoadingState(container);

    try {
        const response = await API.loadKnowledgeGraphList();
        const graphs = response.knowledge_graphs || [];
        state.resourceData.knowledgeGraphs = graphs;

        // Update tab counter
        const tabBtn = document.querySelector('.resource-tab[data-type="knowledge-graphs"]');
        if (tabBtn) {
            tabBtn.textContent = `Knowledge Graphs (${graphs.length})`;
        }

        if (graphs.length === 0) {
            renderEmptyState(container);
            return;
        }

        const activeProfileId = state.currentResourcePanelProfileId;
        container.innerHTML = '';

        for (const kg of graphs) {
            const isActive = kg.profile_id === activeProfileId;
            const card = createKnowledgeGraphCard(kg, isActive);
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

// ── Refresh (re-fetch + re-render) ──────────────────────────────────────────

export async function refreshKnowledgeGraphsPanel() {
    await loadKnowledgeGraphsPanel();
}

// ── Active indicator update (DOM-only, no re-fetch) ─────────────────────────

export function updateKnowledgeGraphActiveIndicator() {
    const container = document.getElementById('knowledge-graphs-content');
    if (!container) return;

    const activeProfileId = state.currentResourcePanelProfileId;
    const cards = container.querySelectorAll('.kg-panel-card');

    cards.forEach(card => {
        const profileId = card.dataset.profileId;
        const isActive = profileId === activeProfileId;

        // Update border
        card.style.borderLeftWidth = isActive ? '4px' : '';
        card.style.borderLeftColor = isActive ? '#F15F22' : '';

        // Update ACTIVE badge visibility
        const existingBadge = card.querySelector('[data-active-badge]');
        if (existingBadge) existingBadge.remove();

        if (isActive) {
            const nameRow = card.querySelector('.flex.items-center.gap-2');
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

// ── Action handlers ─────────────────────────────────────────────────────────

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

// ── Delegated click handler (call from eventHandlers.js) ────────────────────

export function handleKnowledgeGraphPanelClick(e) {
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

function createIntelligenceKGCard(kg) {
    const ifoc = IFOC_CONFIG[kg.profile_type] || { label: kg.profile_type || 'Unknown', color: '#6b7280' };

    const tagLabel = kg.profile_tag ? `@${kg.profile_tag}` : '';

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
                    </div>
                    <p class="text-xs text-gray-500">Profile ID: ${kg.profile_id}</p>
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
    container.addEventListener('click', (e) => {
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

                const profileId = data.profile_id;
                const entities = data.entities || [];
                const relationships = data.relationships || [];

                if (!profileId) {
                    showAppBanner('Import file is missing profile_id', 'error');
                    return;
                }
                if (!entities.length && !relationships.length) {
                    showAppBanner('Import file contains no entities or relationships', 'error');
                    return;
                }

                importBtn.disabled = true;
                importBtn.textContent = 'Importing...';

                const result = await API.importKnowledgeGraph(profileId, entities, relationships);
                showAppBanner(
                    `Imported ${result.entities_added || 0} entities and ${result.relationships_added || 0} relationships`,
                    'success'
                );
                await loadKnowledgeGraphsIntelligenceTab();
                // Also refresh resource panel if it was loaded
                if (state.resourceData.knowledgeGraphs !== null) {
                    await loadKnowledgeGraphsPanel();
                }
            } catch (err) {
                console.error('[KG Import] Failed:', err);
                showAppBanner(`Import failed: ${err.message}`, 'error');
            } finally {
                importBtn.disabled = false;
                importBtn.innerHTML = `
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path>
                    </svg>
                    Import
                `;
            }
        });

        input.click();
    });
}
