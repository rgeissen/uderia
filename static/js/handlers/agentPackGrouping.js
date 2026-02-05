/**
 * Agent Pack Container Card Grouping
 *
 * Shared utility for collapsing multiple resources from the same agent pack
 * into a single expandable "container card". Used by knowledge repositories,
 * planner repositories, and profile class sections.
 */

// ─── SVG constants ───────────────────────────────────────────────────────────

const CUBE_SVG = `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
    <path stroke-linecap="round" stroke-linejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>
</svg>`;

const CHEVRON_SVG = `<svg class="w-5 h-5 pack-expand-chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
</svg>`;

// ─── Resource type labels ────────────────────────────────────────────────────

const RESOURCE_LABELS = {
    knowledge: { singular: 'Knowledge Repository', plural: 'Knowledge Repositories' },
    planner:   { singular: 'Planner Repository',   plural: 'Planner Repositories' },
    profile:   { singular: 'Profile',              plural: 'Profiles' },
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function escapeHtml(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function getResourceName(resource) {
    return resource.name || resource.collection_name || resource.tag || 'Unnamed';
}

function getResourceLabel(type, count) {
    const labels = RESOURCE_LABELS[type] || RESOURCE_LABELS.profile;
    return count === 1 ? labels.singular : labels.plural;
}

function buildBriefList(resources, maxShow = 3) {
    const names = resources.map(r => getResourceName(r));
    if (names.length <= maxShow) return names.join(', ');
    return names.slice(0, maxShow).join(', ') + ` ...+${names.length - maxShow} more`;
}

function buildStatusSummary(resources) {
    const active = resources.filter(r => r.enabled !== false).length;
    const inactive = resources.length - active;
    const parts = [];
    if (active > 0) parts.push(`<span class="text-green-400">${active} active</span>`);
    if (inactive > 0) parts.push(`<span class="text-gray-500">${inactive} inactive</span>`);
    return parts.join(' · ');
}

function buildProfileStatusSummary(resources) {
    const active = resources.filter(r => r.active_for_consumption).length;
    const inactive = resources.length - active;
    const parts = [];
    if (active > 0) parts.push(`<span class="text-green-400">${active} active</span>`);
    if (inactive > 0) parts.push(`<span class="text-gray-500">${inactive} inactive</span>`);
    return parts.join(' · ');
}

function buildAggregateStats(resources, resourceType) {
    const totalChunks = resources.reduce((sum, r) => sum + (r.count || r.example_count || 0), 0);

    let embeddingInfo = '';
    if (resourceType === 'knowledge') {
        const models = [...new Set(resources.map(r => r.embedding_model || 'all-MiniLM-L6-v2'))];
        embeddingInfo = models.length === 1 ? models[0] : 'Mixed';
    }

    let chunkingInfo = '';
    if (resourceType === 'knowledge') {
        const strategies = [...new Set(resources.map(r => r.chunking_strategy).filter(Boolean))];
        chunkingInfo = strategies.length === 1 ? strategies[0] : (strategies.length > 1 ? 'Mixed' : '');
    }

    return { totalChunks, embeddingInfo, chunkingInfo };
}

function buildOwnershipBadges(resources) {
    const owned = resources.filter(r => r.is_owned !== false).length;
    const subscribed = resources.filter(r => r.is_subscribed && !r.is_owned).length;
    if (owned > 0 && subscribed === 0) {
        return `<span class="px-2 py-0.5 text-xs rounded-full bg-blue-500/20 text-blue-400">Owner</span>`;
    } else if (subscribed > 0 && owned === 0) {
        return `<span class="px-2 py-0.5 text-xs rounded-full bg-indigo-500/20 text-indigo-400">Subscribed</span>`;
    } else if (owned > 0 && subscribed > 0) {
        return `<span class="px-2 py-0.5 text-xs rounded-full bg-blue-500/20 text-blue-400">${owned} owned</span>
                <span class="px-2 py-0.5 text-xs rounded-full bg-indigo-500/20 text-indigo-400">${subscribed} subscribed</span>`;
    }
    return '';
}

// ─── Grouping ────────────────────────────────────────────────────────────────

/**
 * Group resources by their primary agent pack.
 *
 * @param {Array} resources - Items with optional agent_packs: [{id,name}]
 * @returns {{ packGroups: Map<number, {pack:{id,name}, resources:Array}>, ungrouped: Array }}
 */
export function groupByAgentPack(resources) {
    const packGroups = new Map();
    const ungrouped = [];

    for (const resource of resources) {
        const packs = resource.agent_packs || [];
        if (packs.length === 0) {
            ungrouped.push(resource);
            continue;
        }
        const primary = packs[0];
        if (!packGroups.has(primary.id)) {
            packGroups.set(primary.id, { pack: primary, resources: [] });
        }
        packGroups.get(primary.id).resources.push(resource);
    }

    return { packGroups, ungrouped };
}

// ─── Container card (HTML string variant) ────────────────────────────────────

/**
 * Build an HTML string for a container card wrapping pre-rendered child HTML.
 *
 * @param {{id:number, name:string}} pack
 * @param {Array} resources - raw resource objects (for summary)
 * @param {'knowledge'|'planner'|'profile'} resourceType
 * @param {string} childCardsHtml - pre-rendered child card HTML
 * @returns {string}
 */
export function createPackContainerCard(pack, resources, resourceType, childCardsHtml) {
    if (resourceType === 'profile') {
        return createProfilePackContainerCard(pack, resources, childCardsHtml);
    }

    const count = resources.length;
    const label = getResourceLabel(resourceType, count);
    const brief = buildBriefList(resources);
    const status = buildStatusSummary(resources);
    const ownershipBadges = buildOwnershipBadges(resources);
    const { totalChunks, embeddingInfo, chunkingInfo } = buildAggregateStats(resources, resourceType);
    const childLayout = 'pack-children-grid';

    // Build aggregate metadata parts — each wrapped in <span> so flex keeps them atomic
    const aggregateParts = [];
    if (resourceType === 'knowledge') {
        aggregateParts.push(`<span class="pack-aggregate-item"><span class="text-white font-medium pack-aggregate-doc-count" data-pack-id="${pack.id}">...</span> docs</span>`);
    }
    aggregateParts.push(`<span class="pack-aggregate-item"><span class="text-white font-medium">${totalChunks}</span> ${resourceType === 'knowledge' ? 'chunks' : 'cases'}</span>`);
    if (embeddingInfo) {
        aggregateParts.push(`<span class="pack-aggregate-item">${escapeHtml(embeddingInfo)}</span>`);
    }
    if (chunkingInfo) {
        aggregateParts.push(`<span class="pack-aggregate-item">${escapeHtml(chunkingInfo)} chunking</span>`);
    }

    return `
    <div class="agent-pack-container-card" data-pack-id="${pack.id}" data-expanded="false">
        <div class="pack-container-header">
            <div class="pack-container-icon">
                ${CUBE_SVG}
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-0.5 flex-wrap">
                    <h3 class="text-base font-semibold text-white truncate">${escapeHtml(pack.name)}</h3>
                    <span class="pack-container-count">${count} ${label}</span>
                    ${ownershipBadges}
                </div>
                <p class="text-xs text-gray-500 truncate">${escapeHtml(brief)}</p>
                ${status ? `<p class="text-xs mt-0.5">${status}</p>` : ''}
                <div class="pack-aggregate-row">
                    ${aggregateParts.join('<span class="separator">·</span>')}
                </div>
            </div>
            <span class="text-gray-400 transition-transform shrink-0">
                ${CHEVRON_SVG}
            </span>
        </div>
        <div class="flex gap-2 flex-wrap mt-3">
            <button class="pack-toggle-all-btn card-btn card-btn--sm card-btn--warning"
                    data-pack-id="${pack.id}" data-resource-type="${resourceType}"
                    onclick="event.stopPropagation();" title="Toggle all active/inactive">
                Toggle All
            </button>
            <button class="pack-export-all-btn card-btn card-btn--sm card-btn--cyan"
                    data-pack-id="${pack.id}" data-resource-type="${resourceType}"
                    onclick="event.stopPropagation();" title="Export all repositories">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                </svg>
                Export All
            </button>
        </div>
        <div class="pack-children-container">
            <div class="${childLayout}">
                ${childCardsHtml}
            </div>
        </div>
    </div>`;
}

// ─── Profile-variant container card ──────────────────────────────────────────

function createProfilePackContainerCard(pack, resources, childCardsHtml) {
    const count = resources.length;
    const label = getResourceLabel('profile', count);
    const brief = buildBriefList(resources);
    const status = buildProfileStatusSummary(resources);

    const enabledCount = resources.filter(r => r.active_for_consumption).length;
    const allEnabled = enabledCount === count;
    const noneEnabled = enabledCount === 0;
    const triState = allEnabled ? 'all' : (noneEnabled ? 'none' : 'mixed');
    const checkedAttr = allEnabled ? 'checked' : '';

    const CUBE_SM = `<svg class="w-4 h-4 text-cyan-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>
    </svg>`;

    return `
    <div class="agent-pack-container-card pack-container-profile"
         data-pack-id="${pack.id}" data-expanded="false" data-tristate="${triState}">
        <div class="pack-container-header">
            <div class="flex flex-col items-center gap-2">
                <label class="relative inline-flex items-center cursor-pointer"
                       title="Toggle all profiles in this pack"
                       onclick="event.stopPropagation();">
                    <input type="checkbox"
                           class="sr-only pack-tristate-checkbox"
                           data-action="toggle-pack-consumption"
                           data-pack-id="${pack.id}"
                           ${checkedAttr}
                           style="position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border-width:0!important;">
                    <div class="pack-tristate-track">
                        <div class="pack-tristate-thumb"></div>
                    </div>
                </label>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-0.5 flex-wrap">
                    ${CUBE_SM}
                    <h4 class="font-semibold text-white truncate">${escapeHtml(pack.name)}</h4>
                    <span class="pack-profile-count">${count} ${label}</span>
                </div>
                <p class="text-xs text-gray-500 truncate">${escapeHtml(brief)}</p>
                ${status ? `<p class="text-xs mt-0.5">${status}</p>` : ''}
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <div class="pack-container-edit-slot">
                    <button class="pack-edit-all-btn pack-edit-all-btn--profile"
                            title="Bulk actions for this pack"
                            onclick="event.stopPropagation();">
                        Edit All
                        <svg class="w-3 h-3 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div class="pack-edit-dropdown pack-edit-dropdown--profile hidden">
                        <button class="pack-edit-dropdown-item pack-toggle-all-btn"
                                data-pack-id="${pack.id}" data-resource-type="profile"
                                onclick="event.stopPropagation();">
                            Toggle All Active/Inactive
                        </button>
                    </div>
                </div>
                <span class="text-gray-400 transition-transform">
                    ${CHEVRON_SVG}
                </span>
            </div>
        </div>
        <div class="pack-children-container">
            <div class="pack-children-stack pack-children-stack--profile">
                ${childCardsHtml}
            </div>
        </div>
    </div>`;
}

// ─── Container card (DOM element variant) ────────────────────────────────────

/**
 * Build a DOM element container card. The caller must append child card
 * elements into the `.pack-children-grid` or `.pack-children-stack` inside.
 *
 * @param {{id:number, name:string}} pack
 * @param {Array} resources
 * @param {'knowledge'|'planner'|'profile'} resourceType
 * @returns {HTMLElement}
 */
export function createPackContainerCardDOM(pack, resources, resourceType) {
    const html = createPackContainerCard(pack, resources, resourceType, '');
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html.trim();
    return wrapper.firstElementChild;
}

// ─── Expand / collapse handlers ──────────────────────────────────────────────

/**
 * Wire click-to-expand/collapse on all .agent-pack-container-card elements
 * within the given parent, and "Edit All" dropdown toggle.
 *
 * @param {HTMLElement} parentElement
 */
export function attachPackContainerHandlers(parentElement) {
    parentElement.querySelectorAll('.agent-pack-container-card').forEach(card => {
        const header = card.querySelector('.pack-container-header');
        if (!header) return;

        const isProfile = card.classList.contains('pack-container-profile');

        // ── Expand / Collapse ────────────────────────────────────────────
        header.addEventListener('click', (e) => {
            // Don't toggle when clicking buttons, labels, links, or dropdowns
            if (e.target.closest('button') || e.target.closest('a') ||
                e.target.closest('label') || e.target.closest('.pack-edit-dropdown')) return;

            const isExpanded = card.dataset.expanded === 'true';
            const children = card.querySelector('.pack-children-container');
            if (!children) return;

            if (isExpanded) {
                children.style.maxHeight = '0';
                children.style.opacity = '0';
                children.style.marginTop = '0';
                card.dataset.expanded = 'false';
                card.classList.remove('pack-container-expanded');
            } else {
                children.style.maxHeight = children.scrollHeight + 'px';
                children.style.opacity = '1';
                children.style.marginTop = '1rem';
                card.dataset.expanded = 'true';
                card.classList.add('pack-container-expanded');
            }
        });

        if (isProfile) {
            // ── Profile cards: Edit All dropdown toggle ──────────────────
            const editBtn = card.querySelector('.pack-edit-all-btn');
            const dropdown = card.querySelector('.pack-edit-dropdown');
            if (editBtn && dropdown) {
                editBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    dropdown.classList.toggle('hidden');
                });
            }
            const toggleAllBtn = card.querySelector('.pack-toggle-all-btn');
            if (toggleAllBtn) {
                toggleAllBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    dropdown?.classList.add('hidden');
                    await handleToggleAll(card, toggleAllBtn.dataset.resourceType);
                });
            }
        } else {
            // ── Knowledge/Planner cards: direct action buttons ───────────
            const toggleAllBtn = card.querySelector('.pack-toggle-all-btn');
            if (toggleAllBtn) {
                toggleAllBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    await handleToggleAll(card, toggleAllBtn.dataset.resourceType);
                });
            }
            const exportAllBtn = card.querySelector('.pack-export-all-btn');
            if (exportAllBtn) {
                exportAllBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    await handleExportAll(card, exportAllBtn.dataset.resourceType);
                });
            }
        }
    });

    // Close dropdowns on outside click (profile cards only)
    document.addEventListener('click', () => {
        parentElement.querySelectorAll('.pack-edit-dropdown').forEach(d => d.classList.add('hidden'));
    }, { once: false });

    // ── Initialize tri-state toggles for profile packs ──────────────────
    parentElement.querySelectorAll('.pack-container-profile[data-tristate="mixed"]').forEach(card => {
        const cb = card.querySelector('.pack-tristate-checkbox');
        if (cb) cb.indeterminate = true;
    });
}

// ─── Bulk toggle (Edit All → Toggle Active/Inactive) ─────────────────────────

async function handleToggleAll(containerCard, resourceType) {
    if (resourceType === 'profile') {
        const cb = containerCard.querySelector('.pack-tristate-checkbox');
        if (cb) cb.click();
        return;
    }
    if (resourceType !== 'knowledge' && resourceType !== 'planner') return;

    const childCards = containerCard.querySelectorAll('[data-repo-id]');
    if (!childCards.length) return;

    const token = localStorage.getItem('tda_auth_token');
    if (!token) return;

    // Determine current majority state to decide toggle direction
    const enabledBtns = containerCard.querySelectorAll('.toggle-knowledge-btn[data-enabled="true"], button[data-enabled="true"]');
    const disabledBtns = containerCard.querySelectorAll('.toggle-knowledge-btn[data-enabled="false"], button[data-enabled="false"]');
    const newEnabled = enabledBtns.length >= disabledBtns.length ? false : true;

    const repoIds = Array.from(childCards).map(c => c.dataset.repoId).filter(Boolean);

    try {
        const promises = repoIds.map(id =>
            fetch(`/api/v1/rag/collections/${id}/toggle`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ enabled: newEnabled })
            })
        );
        await Promise.all(promises);

        // Re-render by triggering the appropriate load function
        if (typeof window.loadKnowledgeRepositories === 'function') {
            window.loadKnowledgeRepositories();
        }
        if (typeof window.loadRagCollections === 'function') {
            window.loadRagCollections();
        }
        window.showAppBanner?.(`All repositories ${newEnabled ? 'enabled' : 'disabled'}`, 'success', 3000);
    } catch (err) {
        console.error('[PackGrouping] Toggle all failed:', err);
        window.showAppBanner?.('Failed to toggle repositories', 'error', 4000);
    }
}

// ─── Bulk export ────────────────────────────────────────────────────────────

async function handleExportAll(containerCard, resourceType) {
    const childCards = containerCard.querySelectorAll('[data-repo-id]');
    const repoIds = Array.from(childCards).map(c => c.dataset.repoId).filter(Boolean);
    if (!repoIds.length) return;

    const token = localStorage.getItem('tda_auth_token');
    if (!token) return;

    window.showAppBanner?.(`Exporting ${repoIds.length} repositories...`, 'info');

    let exported = 0;
    for (const id of repoIds) {
        try {
            const response = await fetch(`/api/v1/rag/collections/${id}/export`, {
                method: 'GET',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!response.ok) continue;

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `collection_${id}.zip`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            exported++;

            if (exported < repoIds.length) {
                await new Promise(r => setTimeout(r, 500));
            }
        } catch (err) {
            console.error(`[PackGrouping] Export failed for ${id}:`, err);
        }
    }

    window.showAppBanner?.(
        exported > 0 ? `Exported ${exported} repositories` : 'Export failed',
        exported > 0 ? 'success' : 'error',
        3000
    );
}

// ─── Async document count aggregation for knowledge containers ──────────────

/**
 * After knowledge repo child cards have been rendered and their async doc
 * counts fetched, aggregate the totals into the container card summary.
 *
 * @param {HTMLElement} parentElement
 */
export function updatePackContainerDocCounts(parentElement) {
    const containers = parentElement.querySelectorAll('.agent-pack-container-card:not(.pack-container-profile)');
    containers.forEach(card => {
        const aggregateEl = card.querySelector('.pack-aggregate-doc-count');
        if (!aggregateEl) return;

        const packId = card.dataset.packId;
        const childDocEls = card.querySelectorAll('[id^="knowledge-doc-count-"]');
        if (!childDocEls.length) {
            aggregateEl.textContent = '0';
            return;
        }

        // Poll until child doc counts are loaded (they're fetched async)
        let attempts = 0;
        const poll = setInterval(() => {
            attempts++;
            let total = 0;
            let allLoaded = true;
            childDocEls.forEach(el => {
                const val = el.textContent.trim();
                if (val === '...' || val === '') {
                    allLoaded = false;
                } else if (val !== '?' && val !== 'Error') {
                    total += parseInt(val, 10) || 0;
                }
            });

            if (allLoaded || attempts >= 20) {
                clearInterval(poll);
                aggregateEl.textContent = total;
            }
        }, 500);
    });
}
