/**
 * Marketplace Handler
 * Manages UI interactions for the intelligence marketplace
 */

// Import utility functions
import { showNotification } from './rag/utils.js';
import { escapeHtml } from '../ui.js';

// Marketplace state
let currentPage = 1;
let currentVisibility = 'public';
let currentSearch = '';
let currentSortBy = 'subscribers';
let totalPages = 1;
let currentTab = 'browse'; // 'browse' or 'my-collections'
let currentRepositoryType = 'planner'; // 'planner', 'knowledge', or 'agent-packs'

/**
 * Initialize marketplace functionality
 */
export function initializeMarketplace() {
    console.log('Initializing marketplace...');
    
    // Main tab handlers (Browse / My Collections)
    const browseTab = document.getElementById('marketplace-tab-browse');
    const myCollectionsTab = document.getElementById('marketplace-tab-my-collections');
    
    if (browseTab) {
        browseTab.addEventListener('click', () => {
            switchTab('browse');
        });
    }
    
    if (myCollectionsTab) {
        myCollectionsTab.addEventListener('click', () => {
            switchTab('my-collections');
        });
    }
    
    // Repository type tab handlers (Planner / Knowledge)
    const plannerTypeTab = document.getElementById('marketplace-repo-type-planner');
    const knowledgeTypeTab = document.getElementById('marketplace-repo-type-knowledge');
    
    if (plannerTypeTab) {
        plannerTypeTab.addEventListener('click', () => {
            switchRepositoryType('planner');
        });
    }
    
    if (knowledgeTypeTab) {
        knowledgeTypeTab.addEventListener('click', () => {
            switchRepositoryType('knowledge');
        });
    }

    // Agent Packs type tab
    const agentPacksTypeTab = document.getElementById('marketplace-repo-type-agent-packs');
    if (agentPacksTypeTab) {
        agentPacksTypeTab.addEventListener('click', () => {
            switchRepositoryType('agent-packs');
        });
    }
    
    // Search and filter handlers
    const searchBtn = document.getElementById('marketplace-search-btn');
    const searchInput = document.getElementById('marketplace-search-input');
    const visibilityFilter = document.getElementById('marketplace-visibility-filter');
    const sortFilter = document.getElementById('marketplace-sort-filter');
    
    if (searchBtn) {
        searchBtn.addEventListener('click', () => {
            currentPage = 1;
            currentSearch = searchInput?.value || '';
            currentVisibility = visibilityFilter?.value || 'public';
            currentSortBy = sortFilter?.value || 'subscribers';
            loadMarketplaceContent();
        });
    }

    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                currentPage = 1;
                currentSearch = searchInput.value;
                currentVisibility = visibilityFilter?.value || 'public';
                currentSortBy = sortFilter?.value || 'subscribers';
                loadMarketplaceContent();
            }
        });
    }

    // Auto-reload when sort filter changes
    if (sortFilter) {
        sortFilter.addEventListener('change', () => {
            currentPage = 1;
            currentSortBy = sortFilter.value;
            loadMarketplaceContent();
        });
    }

    // Pagination handlers
    const prevBtn = document.getElementById('marketplace-prev-btn');
    const nextBtn = document.getElementById('marketplace-next-btn');

    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                loadMarketplaceContent();
            }
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            if (currentPage < totalPages) {
                currentPage++;
                loadMarketplaceContent();
            }
        });
    }

    // Initialize modals
    initializeForkModal();
    initializePublishModal();
    initializeRateModal();
    initializeAgentPackRateModal();

    // Load initial collections
    loadMarketplaceContent();
}

/**
 * Switch between marketplace tabs
 */
function switchTab(tab) {
    currentTab = tab;
    currentPage = 1;
    
    // Update tab UI
    const browseTab = document.getElementById('marketplace-tab-browse');
    const myCollectionsTab = document.getElementById('marketplace-tab-my-collections');
    
    if (browseTab && myCollectionsTab) {
        if (tab === 'browse') {
            browseTab.classList.add('border-[#F15F22]', 'text-white');
            browseTab.classList.remove('border-transparent', 'text-gray-400');
            myCollectionsTab.classList.remove('border-[#F15F22]', 'text-white');
            myCollectionsTab.classList.add('border-transparent', 'text-gray-400');
        } else {
            myCollectionsTab.classList.add('border-[#F15F22]', 'text-white');
            myCollectionsTab.classList.remove('border-transparent', 'text-gray-400');
            browseTab.classList.remove('border-[#F15F22]', 'text-white');
            browseTab.classList.add('border-transparent', 'text-gray-400');
        }
    }
    
    // Update search/filter UI visibility
    const searchBar = document.querySelector('#marketplace-search-input')?.closest('.glass-panel');
    if (searchBar) {
        if (tab === 'my-collections') {
            searchBar.classList.add('hidden');
        } else {
            searchBar.classList.remove('hidden');
        }
    }

    loadMarketplaceContent();
}

/**
 * Switch between repository types (planner / knowledge)
 */
function switchRepositoryType(type) {
    currentRepositoryType = type;
    currentPage = 1;

    // Update tab styling — deactivate all, then activate selected
    const tabs = {
        planner: document.getElementById('marketplace-repo-type-planner'),
        knowledge: document.getElementById('marketplace-repo-type-knowledge'),
        'agent-packs': document.getElementById('marketplace-repo-type-agent-packs'),
    };
    const descs = {
        planner: document.getElementById('planner-description'),
        knowledge: document.getElementById('knowledge-description'),
        'agent-packs': document.getElementById('agent-packs-description'),
    };

    for (const [key, tab] of Object.entries(tabs)) {
        if (!tab) continue;
        if (key === type) {
            tab.classList.add('bg-[#F15F22]', 'text-white');
            tab.classList.remove('text-gray-400', 'hover:bg-white/10');
        } else {
            tab.classList.remove('bg-[#F15F22]', 'text-white');
            tab.classList.add('text-gray-400', 'hover:bg-white/10');
        }
    }
    for (const [key, desc] of Object.entries(descs)) {
        if (!desc) continue;
        desc.classList.toggle('hidden', key !== type);
    }

    loadMarketplaceContent();
}

/**
 * Route to correct loader based on current repository type
 */
function loadMarketplaceContent() {
    if (currentRepositoryType === 'agent-packs') {
        loadMarketplaceAgentPacks();
    } else {
        loadMarketplaceCollections();
    }
}

/**
 * Load marketplace agent packs from API
 *
 * Handles both tabs:
 *   - "Browse Marketplace" → fetches from /api/v1/marketplace/agent-packs
 *   - "My Collections"     → fetches from /api/v1/agent-packs (installed packs)
 */
async function loadMarketplaceAgentPacks() {
    const container = document.getElementById('marketplace-collections-list');
    const loading = document.getElementById('marketplace-loading');
    const empty = document.getElementById('marketplace-empty');
    const pagination = document.getElementById('marketplace-pagination');

    if (!container) return;

    if (loading) loading.classList.remove('hidden');
    if (empty) empty.classList.add('hidden');
    container.innerHTML = '';
    if (pagination) pagination.classList.add('hidden');

    try {
        const token = await window.authClient.getToken();
        const headers = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;

        let packs = [];

        if (currentTab === 'my-collections') {
            // Load user's installed agent packs
            const response = await fetch('/api/v1/agent-packs', { headers });
            if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            const data = await response.json();
            packs = data.packs || [];
        } else {
            // Load marketplace agent packs (browse)
            const params = new URLSearchParams({
                page: currentPage,
                per_page: 12,
                sort_by: currentSortBy === 'subscribers' ? 'recent' : currentSortBy,
                visibility: 'public',
            });
            if (currentSearch) params.append('search', currentSearch);

            const response = await fetch(`/api/v1/marketplace/agent-packs?${params}`, { headers });
            if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

            const data = await response.json();
            packs = data.packs || [];
            totalPages = data.total_pages || 1;
            updatePaginationUI(data);
        }

        if (loading) loading.classList.add('hidden');

        if (packs.length === 0) {
            if (empty) {
                empty.classList.remove('hidden');
                const emptyTitle = empty.querySelector('h3');
                const emptyDesc = empty.querySelector('p');
                if (currentTab === 'my-collections') {
                    if (emptyTitle) emptyTitle.textContent = 'No Agent Packs';
                    if (emptyDesc) emptyDesc.textContent = 'Subscribe to an agent pack from the Browse tab or upload an .agentpack file from Setup';
                } else {
                    if (emptyTitle) emptyTitle.textContent = 'No Agent Packs Found';
                    if (emptyDesc) emptyDesc.textContent = currentSearch
                        ? 'Try adjusting your search'
                        : 'No agent packs have been published to the marketplace yet';
                }
            }
            return;
        }

        packs.forEach(pack => {
            if (currentTab === 'my-collections') {
                container.appendChild(createMyAgentPackCard(pack));
            } else {
                container.appendChild(createAgentPackMarketplaceCard(pack));
            }
        });

    } catch (error) {
        console.error('Failed to load agent packs:', error);
        if (loading) loading.classList.add('hidden');
        showNotification('error', 'Failed to load agent packs: ' + error.message);
    }
}

/**
 * Create an agent pack marketplace card
 */
function createAgentPackMarketplaceCard(pack) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-xl p-4 flex flex-col gap-3 border border-white/10 hover:border-teradata-orange transition-colors';

    const isPublisher = pack.is_publisher || false;
    const rating = pack.average_rating || 0;
    const packType = pack.pack_type || 'genie';

    // Pack type badge
    const packTypeBadges = {
        genie:  { bg: 'bg-orange-100 dark:bg-orange-500/20', text: 'text-orange-600 dark:text-orange-400', label: 'Coordinator' },
        bundle: { bg: 'bg-purple-100 dark:bg-purple-500/20', text: 'text-purple-600 dark:text-purple-400', label: 'Bundle' },
        single: { bg: 'bg-blue-100 dark:bg-blue-500/20',     text: 'text-blue-600 dark:text-blue-400',     label: 'Single' },
    };
    const badge = packTypeBadges[packType] || packTypeBadges.genie;

    // Profile tags chips
    const profileTags = (pack.profile_tags || []).slice(0, 8);
    const tagsHtml = profileTags.map(t =>
        `<span class="px-1.5 py-0.5 text-xs rounded bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300 font-mono">@${escapeHtml(t)}</span>`
    ).join('');
    const moreTagsCount = (pack.profile_tags || []).length - 8;

    // Publisher info
    let publisherHtml = '';
    if (pack.publisher_username) {
        publisherHtml = `<span class="text-gray-600 dark:text-gray-400">${escapeHtml(pack.publisher_username)}</span>`;
        if (pack.publisher_email) {
            publisherHtml += ` <span class="text-gray-500 dark:text-gray-600">(${escapeHtml(pack.publisher_email)})</span>`;
        }
    }

    card.innerHTML = `
        <!-- Header -->
        <div class="flex items-start justify-between gap-2">
            <div class="flex-1">
                <div class="flex items-center gap-2 flex-wrap">
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">${escapeHtml(pack.name)}</h2>
                    ${pack.version ? `<span class="px-2 py-0.5 text-xs rounded-full bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300">v${escapeHtml(pack.version)}</span>` : ''}
                    <span class="px-2 py-0.5 text-xs rounded-full ${badge.bg} ${badge.text}">${badge.label}</span>
                    ${pack.shared_with_me ? `<span class="px-2 py-0.5 text-xs rounded-full bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-400">Shared with you</span>` : ''}
                </div>
                ${pack.author ? `<p class="text-xs text-gray-500 mt-0.5">by ${escapeHtml(pack.author)}</p>` : ''}
            </div>
        </div>

        <!-- Description -->
        ${pack.description ? `<p class="text-xs text-gray-600 dark:text-gray-400">${escapeHtml(pack.description)}</p>` : ''}

        <!-- Shared by info -->
        ${pack.shared_with_me && pack.shared_by_username ? `
            <p class="text-xs text-indigo-600 dark:text-indigo-400">Shared by ${escapeHtml(pack.shared_by_username)}</p>
        ` : ''}

        <!-- Profile tags -->
        ${profileTags.length > 0 ? `
            <div class="flex flex-wrap gap-1">
                ${tagsHtml}
                ${moreTagsCount > 0 ? `<span class="px-1.5 py-0.5 text-xs text-gray-500">+${moreTagsCount} more</span>` : ''}
            </div>
        ` : ''}

        <!-- Metadata row -->
        <div class="flex items-center gap-4 text-xs text-gray-500">
            ${publisherHtml ? `
                <div class="flex items-center gap-1">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                    </svg>
                    ${publisherHtml}
                </div>
            ` : ''}
            <div class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                <span>${pack.profile_count || 0} profiles</span>
            </div>
            <div class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
                </svg>
                <span>${pack.collection_count || 0} collections</span>
            </div>
            <div class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <span>${pack.install_count || 0} subscribers</span>
            </div>
            ${rating > 0 ? `
                <div class="flex items-center gap-1 text-yellow-500 dark:text-yellow-400">
                    <svg class="w-3.5 h-3.5 fill-current" viewBox="0 0 20 20">
                        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/>
                    </svg>
                    <span>${rating.toFixed(1)}</span>
                    ${pack.rating_count > 0 ? `<span class="text-xs text-gray-500">(${pack.rating_count})</span>` : ''}
                </div>
            ` : `
                <div class="text-xs text-gray-500">No ratings yet</div>
            `}
        </div>

        <!-- Actions -->
        <div class="mt-2 flex gap-2 flex-wrap">
            ${pack.shared_with_me ? `
                <button class="agent-pack-subscribe-btn px-3 py-1 rounded-md bg-[#F15F22] hover:bg-[#D9501A] text-sm text-white"
                        data-pack-id="${pack.id}">
                    Subscribe
                </button>
            ` : !isPublisher ? `
                <button class="agent-pack-subscribe-btn px-3 py-1 rounded-md bg-[#F15F22] hover:bg-[#D9501A] text-sm text-white"
                        data-pack-id="${pack.id}">
                    Subscribe
                </button>
                <button class="agent-pack-rate-btn px-3 py-1 rounded-md bg-amber-600 hover:bg-amber-500 text-sm text-white"
                        data-pack-id="${pack.id}"
                        data-pack-name="${escapeHtml(pack.name)}">
                    Rate
                </button>
            ` : `
                <button class="agent-pack-unpublish-btn px-3 py-1 rounded-md bg-orange-600 hover:bg-orange-500 text-sm text-white"
                        data-pack-id="${pack.id}"
                        data-pack-name="${escapeHtml(pack.name)}">
                    Unpublish
                </button>
            `}
        </div>
    `;

    // Attach event listeners
    const subscribeBtn = card.querySelector('.agent-pack-subscribe-btn');
    const rateBtn = card.querySelector('.agent-pack-rate-btn');
    const unpublishBtn = card.querySelector('.agent-pack-unpublish-btn');

    if (subscribeBtn) {
        subscribeBtn.addEventListener('click', () => handleAgentPackInstall(pack, subscribeBtn));
    }
    if (rateBtn) {
        rateBtn.addEventListener('click', () => openAgentPackRateModal(pack));
    }
    if (unpublishBtn) {
        unpublishBtn.addEventListener('click', () => handleAgentPackUnpublish(pack.id, pack.name, unpublishBtn));
    }

    return card;
}

/**
 * Create a card for an installed agent pack (My Collections tab)
 *
 * Uses the /api/v1/agent-packs response shape which differs from the
 * marketplace browse shape:
 *   - installation_id (not id)
 *   - profiles_count / collections_count / experts_count
 *   - marketplace_pack_id (non-null when published)
 *   - sharing_count
 */
function createMyAgentPackCard(pack) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-xl p-4 flex flex-col gap-3 border border-white/10 hover:border-teradata-orange transition-colors';

    const packType = pack.pack_type || 'genie';
    const packTypeBadges = {
        genie:  { bg: 'bg-orange-500/20', text: 'text-orange-400', label: 'Coordinator' },
        bundle: { bg: 'bg-purple-500/20', text: 'text-purple-400', label: 'Bundle' },
        single: { bg: 'bg-blue-500/20',   text: 'text-blue-400',   label: 'Single' },
    };
    const badge = packTypeBadges[packType] || packTypeBadges.genie;

    const installed = pack.installed_at
        ? new Date(pack.installed_at).toLocaleDateString()
        : '';

    const isShared = pack.shared_with_me || false;

    card.innerHTML = `
        <!-- Header -->
        <div class="flex items-start justify-between gap-2">
            <div class="flex-1">
                <div class="flex items-center gap-2 flex-wrap">
                    <h2 class="text-lg font-semibold text-white">${escapeHtml(pack.name)}</h2>
                    ${pack.version ? `<span class="px-2 py-0.5 text-xs rounded-full bg-white/10 text-gray-300">v${escapeHtml(pack.version)}</span>` : ''}
                    <span class="px-2 py-0.5 text-xs rounded-full ${badge.bg} ${badge.text}">${badge.label}</span>
                </div>
                ${pack.author ? `<p class="text-xs text-gray-500 mt-0.5">by ${escapeHtml(pack.author)}</p>` : ''}
            </div>
            <div class="flex flex-col items-end gap-1">
                ${isShared
                    ? '<span class="px-2 py-1 text-xs rounded-full bg-indigo-500/20 text-indigo-400">Shared with you</span>'
                    : pack.marketplace_pack_id
                        ? '<span class="px-2 py-1 text-xs rounded-full bg-green-500/20 text-green-400">Published</span>'
                        : '<span class="px-2 py-1 text-xs rounded-full bg-gray-500/20 text-gray-400">Private</span>'
                }
            </div>
        </div>

        <!-- Description -->
        ${pack.description ? `<p class="text-xs text-gray-400">${escapeHtml(pack.description)}</p>` : ''}

        <!-- Shared by info -->
        ${isShared && pack.shared_by_username ? `
            <p class="text-xs text-indigo-400">Shared by ${escapeHtml(pack.shared_by_username)}</p>
        ` : ''}

        <!-- Metadata row -->
        <div class="flex items-center gap-4 text-xs text-gray-500">
            ${pack.coordinator_tag ? `
                <div class="flex items-center gap-1">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    <span class="text-gray-300 font-mono">@${escapeHtml(pack.coordinator_tag)}</span>
                </div>
            ` : ''}
            <div class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                <span>${pack.profile_count || pack.profiles_count || 0} profiles</span>
            </div>
            <div class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
                </svg>
                <span>${pack.collection_count || pack.collections_count || 0} collections</span>
            </div>
            ${installed ? `
                <div class="flex items-center gap-1">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <span>${installed}</span>
                </div>
            ` : ''}
        </div>

        <!-- Actions -->
        <div class="mt-2 flex gap-2 flex-wrap">
            ${isShared ? `
                <span class="px-3 py-1 text-xs rounded-md bg-white/5 text-gray-500">Read-only</span>
            ` : `
                ${!pack.marketplace_pack_id ? `
                    <button class="my-pack-publish-btn px-3 py-1 rounded-md bg-green-600 hover:bg-green-500 text-sm text-white"
                            data-installation-id="${pack.installation_id}"
                            data-pack-name="${escapeHtml(pack.name)}">
                        Publish${pack.sharing_count > 0 ? ` (${pack.sharing_count} shared)` : ''}
                    </button>
                ` : `
                    <button class="my-pack-unpublish-btn px-3 py-1 rounded-md bg-orange-600 hover:bg-orange-500 text-sm text-white"
                            data-marketplace-id="${pack.marketplace_pack_id}"
                            data-pack-name="${escapeHtml(pack.name)}">
                        Unpublish
                    </button>
                `}
            `}
        </div>
    `;

    // Attach event listeners (only for owned packs)
    if (!isShared) {
        const publishBtn = card.querySelector('.my-pack-publish-btn');
        const unpublishBtn = card.querySelector('.my-pack-unpublish-btn');

        if (publishBtn) {
            publishBtn.addEventListener('click', () => {
                if (window.agentPackHandler?.openPublishPackModal) {
                    window.agentPackHandler.openPublishPackModal(
                        parseInt(publishBtn.dataset.installationId),
                        publishBtn.dataset.packName
                    );
                }
            });
        }
        if (unpublishBtn) {
            unpublishBtn.addEventListener('click', () => {
                handleAgentPackUnpublish(unpublishBtn.dataset.marketplaceId, unpublishBtn.dataset.packName, unpublishBtn);
            });
        }
    }

    return card;
}

/**
 * Handle agent pack subscribe from marketplace (logical sharing grant).
 * @param {object|string} packOrId - Full pack object (preferred) or pack ID string
 * @param {HTMLElement} button - The subscribe button element
 */
async function handleAgentPackInstall(packOrId, button) {
    const pack = typeof packOrId === 'object' ? packOrId : { id: packOrId };
    const packId = pack.id;
    const isShared = pack.shared_with_me === true;
    const originalText = button.textContent;

    if (isShared) {
        showNotification('info', 'This pack is already shared with you.');
        return;
    }

    button.textContent = 'Subscribing...';
    button.disabled = true;

    try {
        const token = await window.authClient.getToken();
        if (!token) {
            showNotification('error', 'Authentication required. Please log in.');
            button.textContent = originalText;
            button.disabled = false;
            return;
        }

        const installRes = await fetch(`/api/v1/marketplace/agent-packs/${packId}/install`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({})
        });

        const result = await installRes.json();
        if (!installRes.ok || result.status === 'error') {
            throw new Error(result.message || 'Subscribe failed');
        }

        showNotification('success', `Subscribed to ${result.name || 'agent pack'}`);

        // Reload marketplace and agent packs list
        loadMarketplaceAgentPacks();
        if (window.agentPackHandler?.loadAgentPacks) {
            window.agentPackHandler.loadAgentPacks();
        }

    } catch (error) {
        console.error('Agent pack subscribe failed:', error);
        showNotification('error', 'Subscribe failed: ' + error.message);
    } finally {
        button.textContent = originalText;
        button.disabled = false;
    }
}

/**
 * Handle agent pack unpublish from marketplace
 */
async function handleAgentPackUnpublish(packId, packName, button) {
    const confirmed = window.showConfirmation ? await new Promise(resolve => {
        window.showConfirmation(
            'Unpublish Agent Pack',
            `Are you sure you want to remove "${packName}" from the marketplace?`,
            () => resolve(true),
            () => resolve(false)
        );
    }) : confirm(`Remove "${packName}" from the marketplace?`);

    if (!confirmed) return;

    const originalText = button?.textContent || 'Unpublish';
    if (button) {
        button.textContent = 'Unpublishing...';
        button.disabled = true;
    }

    try {
        const token = await window.authClient.getToken();
        if (!token) {
            showNotification('error', 'Authentication required.');
            return;
        }

        const response = await fetch(`/api/v1/marketplace/agent-packs/${packId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || 'Unpublish failed');
        }

        showNotification('success', 'Agent pack unpublished from marketplace');
        loadMarketplaceAgentPacks();

        // Refresh installed packs to update publish state
        if (window.agentPackHandler?.loadAgentPacks) {
            window.agentPackHandler.loadAgentPacks();
        }

    } catch (error) {
        console.error('Unpublish failed:', error);
        showNotification('error', 'Failed to unpublish: ' + error.message);
    } finally {
        if (button) {
            button.textContent = originalText;
            button.disabled = false;
        }
    }
}

/**
 * Initialize agent pack rate modal
 */
function initializeAgentPackRateModal() {
    // Reuses the same rate modal pattern but with agent-pack-specific IDs
    // The modal is created dynamically when opened
}

/**
 * Open agent pack rate modal
 */
function openAgentPackRateModal(pack) {
    // Create a dynamic modal for rating agent packs
    let overlay = document.getElementById('rate-agent-pack-modal-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'rate-agent-pack-modal-overlay';
    overlay.className = 'fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[10000] opacity-0 transition-opacity duration-300';
    overlay.innerHTML = `
        <div id="rate-agent-pack-modal-content" class="glass-panel rounded-xl p-6 w-full max-w-md border border-white/10 shadow-2xl transform scale-95 opacity-0 transition-all duration-300">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-lg font-bold text-white">Rate Agent Pack</h3>
                <button id="rate-agent-pack-close" class="text-gray-400 hover:text-white">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
            <p class="text-sm text-gray-400 mb-4">Rating: <span class="text-white font-medium">${escapeHtml(pack.name)}</span></p>
            <div class="flex gap-2 mb-4 justify-center" id="rate-agent-pack-stars">
                ${[1,2,3,4,5].map(i => `
                    <button class="rate-agent-pack-star cursor-pointer" data-rating="${i}">
                        <svg class="w-8 h-8 text-gray-500 hover:text-yellow-400 transition-colors" fill="currentColor" viewBox="0 0 20 20">
                            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                        </svg>
                    </button>
                `).join('')}
            </div>
            <textarea id="rate-agent-pack-comment" rows="3" placeholder="Optional review comment..."
                      class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm mb-4 focus:outline-none focus:border-blue-500 resize-none"></textarea>
            <div class="flex justify-end gap-3">
                <button id="rate-agent-pack-cancel" class="px-4 py-2 text-sm rounded-lg bg-white/5 text-gray-300 hover:bg-white/10 transition-colors">Cancel</button>
                <button id="rate-agent-pack-submit" class="px-4 py-2 text-sm rounded-lg bg-amber-600 text-white hover:bg-amber-700 transition-colors" disabled>Submit Rating</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    let selectedRating = 0;
    const stars = overlay.querySelectorAll('.rate-agent-pack-star');
    const submitBtn = overlay.querySelector('#rate-agent-pack-submit');
    const content = overlay.querySelector('#rate-agent-pack-modal-content');

    // Show with animation
    requestAnimationFrame(() => {
        overlay.classList.add('opacity-100');
        content.classList.remove('scale-95', 'opacity-0');
        content.classList.add('scale-100', 'opacity-100');
    });

    // Star click handlers
    stars.forEach(star => {
        star.addEventListener('click', () => {
            selectedRating = parseInt(star.dataset.rating);
            submitBtn.disabled = false;
            stars.forEach((s, idx) => {
                const svg = s.querySelector('svg');
                if (idx < selectedRating) {
                    svg.classList.remove('text-gray-500');
                    svg.classList.add('text-yellow-400');
                } else {
                    svg.classList.remove('text-yellow-400');
                    svg.classList.add('text-gray-500');
                }
            });
        });
    });

    const closeModal = () => {
        overlay.classList.remove('opacity-100');
        content.classList.remove('scale-100', 'opacity-100');
        content.classList.add('scale-95', 'opacity-0');
        setTimeout(() => overlay.remove(), 300);
    };

    overlay.querySelector('#rate-agent-pack-close').onclick = closeModal;
    overlay.querySelector('#rate-agent-pack-cancel').onclick = closeModal;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

    submitBtn.onclick = async () => {
        if (!selectedRating) return;
        submitBtn.textContent = 'Submitting...';
        submitBtn.disabled = true;
        try {
            const token = await window.authClient.getToken();
            const comment = overlay.querySelector('#rate-agent-pack-comment').value.trim();
            const body = { rating: selectedRating };
            if (comment) body.comment = comment;

            const res = await fetch(`/api/v1/marketplace/agent-packs/${pack.id}/rate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify(body),
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.message || 'Rating failed');
            }
            showNotification('success', 'Rating submitted successfully');
            closeModal();
            loadMarketplaceAgentPacks();
        } catch (err) {
            showNotification('error', 'Failed to submit rating: ' + err.message);
            submitBtn.textContent = 'Submit Rating';
            submitBtn.disabled = false;
        }
    };
}

/**
 * Load marketplace collections from API
 */
async function loadMarketplaceCollections() {
    const container = document.getElementById('marketplace-collections-list');
    const loading = document.getElementById('marketplace-loading');
    const empty = document.getElementById('marketplace-empty');
    const pagination = document.getElementById('marketplace-pagination');
    
    if (!container) return;
    
    // Show loading
    if (loading) loading.classList.remove('hidden');
    if (empty) empty.classList.add('hidden');
    container.innerHTML = '';
    if (pagination) pagination.classList.add('hidden');
    
    try {
        // Get authentication token
        const token = await window.authClient.getToken();
        const headers = {};
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        let response;
        
        if (currentTab === 'my-collections') {
            // Load user's own collections
            response = await fetch('/api/v1/rag/collections', { headers });
        } else {
            // Load marketplace collections
            const params = new URLSearchParams({
                page: currentPage,
                per_page: 10,
                visibility: currentVisibility,
                repository_type: currentRepositoryType,
                sort_by: currentSortBy
            });
            
            if (currentSearch) {
                params.append('search', currentSearch);
            }
            
            response = await fetch(`/api/v1/marketplace/collections?${params}`, { headers });
        }
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        // Hide loading
        if (loading) loading.classList.add('hidden');
        
        // Handle different response formats
        let collections;
        if (currentTab === 'my-collections') {
            // /api/v1/rag/collections returns array directly
            collections = Array.isArray(data) ? data : (data.collections || []);
            // Filter out Default Collection (ID 0), filter by repository type
            // Preserve actual is_owned from API (shared collections have is_owned: false)
            collections = collections
                .filter(c => c.id !== 0 && c.repository_type === currentRepositoryType)
                .map(c => ({ ...c, is_owner: c.is_owned !== undefined ? c.is_owned : true }));
        } else {
            // /api/v1/marketplace/collections returns {collections: [], total_pages: n}
            collections = data.collections || [];
            // Filter out collections owned by the current user in browse mode
            collections = collections.filter(c => !c.is_owner);
        }
        
        if (collections.length === 0) {
            if (empty) {
                empty.classList.remove('hidden');
                // Update empty state message based on tab
                const emptyTitle = empty.querySelector('h3');
                const emptyDesc = empty.querySelector('p');
                if (currentTab === 'my-collections') {
                    if (emptyTitle) emptyTitle.textContent = 'No Collections Yet';
                    if (emptyDesc) emptyDesc.textContent = 'Create a RAG collection to get started';
                } else {
                    if (emptyTitle) emptyTitle.textContent = 'No Collections Found';
                    if (emptyDesc) emptyDesc.textContent = 'Try adjusting your search or filters';
                }
            }
            return;
        }
        
        // Update pagination info (only for browse mode)
        if (currentTab === 'browse') {
            totalPages = data.total_pages || 1;
            updatePaginationUI(data);
        }
        
        // Render collections
        collections.forEach(collection => {
            container.appendChild(createCollectionCard(collection));
        });
        
    } catch (error) {
        console.error('Failed to load marketplace collections:', error);
        if (loading) loading.classList.add('hidden');
        showNotification('error', 'Failed to load marketplace collections: ' + error.message);
    }
}

/**
 * Create a collection card element
 */
function createCollectionCard(collection) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-xl p-4 flex flex-col gap-3 border border-white/10 hover:border-teradata-orange transition-colors';
    
    const isOwner = collection.is_owner || false;
    const isSubscribed = collection.is_subscribed || false;
    const rating = collection.average_rating || 0;
    const subscriberCount = collection.subscriber_count || 0;
    const repositoryType = collection.repository_type || 'planner';
    const agentPacks = collection.agent_packs || [];

    // Repository type badge configuration - Knowledge=Blue (Focus), Planner=Orange (Optimize)
    const repoTypeBadge = repositoryType === 'knowledge'
        ? '<span class="px-2 py-1 text-xs rounded-full bg-blue-500/20 text-blue-400 flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>Knowledge</span>'
        : '<span class="px-2 py-1 text-xs rounded-full bg-orange-500/20 text-orange-400 flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>Planner</span>';

    // Agent pack badge - show pack name(s) if collection belongs to an agent pack
    const agentPackBadge = agentPacks.length > 0
        ? agentPacks.map(ap =>
            `<span class="px-2 py-1 text-xs rounded-full bg-teal-500/20 text-teal-400 flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" /></svg>${escapeHtml(ap.name)}</span>`
          ).join('')
        : '';
    
    card.innerHTML = `
        <!-- Header with title and status badge -->
        <div class="flex items-start justify-between gap-2">
            <div class="flex-1">
                <h2 class="text-lg font-semibold text-white">${escapeHtml(collection.name)}</h2>
                <p class="text-xs text-gray-500">Collection ID: ${collection.id}</p>
            </div>
            <div class="flex flex-col items-end gap-1">
                ${repoTypeBadge}
                ${agentPackBadge}
                ${isOwner && collection.is_marketplace_listed ? `
                    <span class="px-2 py-1 text-xs rounded-full bg-green-500/20 text-green-400">Published</span>
                ` : ''}
                ${isOwner && !collection.is_marketplace_listed && collection.visibility === 'private' ? `
                    <span class="px-2 py-1 text-xs rounded-full bg-gray-500/20 text-gray-400">Private</span>
                ` : ''}
                ${collection.shared_with_me && collection.shared_by_username ? `
                    <span class="px-2 py-1 text-xs rounded-full bg-indigo-500/20 text-indigo-400" title="Shared by ${escapeHtml(collection.shared_by_username)}">Targeted</span>
                ` : ''}
                ${collection.shared_with_me ? `
                    <span class="px-2 py-1 text-xs rounded-full bg-indigo-500/20 text-indigo-400">Shared with you</span>
                ` : ''}
            </div>
        </div>
        
        <!-- Description -->
        ${collection.description ? `
            <p class="text-xs text-gray-400">${escapeHtml(collection.description)}</p>
        ` : ''}

        <!-- Shared by info -->
        ${collection.shared_with_me && collection.shared_by_username ? `
            <p class="text-xs text-indigo-400">Shared by ${escapeHtml(collection.shared_by_username)}</p>
        ` : ''}

        <!-- Metadata -->
        <div class="flex items-center gap-4 text-xs text-gray-500">
            <div class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                </svg>
                <span class="text-gray-400">${escapeHtml(collection.owner_username || 'Unknown')}</span>
            </div>
            <div class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path>
                </svg>
                <span>${subscriberCount} subscriber${subscriberCount !== 1 ? 's' : ''}</span>
            </div>
            <div class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
                </svg>
                <span>${collection.rag_case_count || 0} ${repositoryType === 'knowledge' ? 'document' : 'case'}${(collection.rag_case_count || 0) !== 1 ? 's' : ''}</span>
            </div>
            ${rating > 0 ? `
                <div class="flex items-center gap-1 text-yellow-400">
                    <svg class="w-3.5 h-3.5 fill-current" viewBox="0 0 20 20">
                        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/>
                    </svg>
                    <span>${rating.toFixed(1)}</span>
                    ${collection.rating_count > 0 ? `<span class="text-xs text-gray-500">(${collection.rating_count})</span>` : ''}
                </div>
            ` : `
                <div class="text-xs text-gray-500">No ratings yet</div>
            `}
        </div>
        
        <!-- Actions -->
        <div class="mt-2 flex gap-2 flex-wrap">
            ${collection.shared_with_me ? `
                <span class="px-3 py-1 text-xs rounded-md bg-white/5 text-gray-500">Read-only</span>
                <button class="fork-btn px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-sm text-white"
                        data-collection-id="${collection.id}"
                        data-collection-name="${escapeHtml(collection.name)}"
                        data-collection-description="${escapeHtml(collection.description || '')}">
                    Fork
                </button>
            ` : `
                ${!isOwner && !isSubscribed ? `
                    <button class="subscribe-btn px-3 py-1 rounded-md bg-[#F15F22] hover:bg-[#D9501A] text-sm text-white"
                            data-collection-id="${collection.id}">
                        Subscribe
                    </button>
                ` : ''}
                ${!isOwner && isSubscribed ? `
                    <button class="unsubscribe-btn px-3 py-1 rounded-md bg-yellow-600 hover:bg-yellow-500 text-sm text-white"
                            data-subscription-id="${collection.subscription_id}">
                        Unsubscribe
                    </button>
                ` : ''}
                ${!isOwner ? `
                    <button class="fork-btn px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-sm text-white"
                            data-collection-id="${collection.id}"
                            data-collection-name="${escapeHtml(collection.name)}"
                            data-collection-description="${escapeHtml(collection.description || '')}">
                        Fork
                    </button>
                ` : ''}
                ${!isOwner ? `
                    <button class="rate-btn px-3 py-1 rounded-md bg-amber-600 hover:bg-amber-500 text-sm text-white"
                            data-collection-id="${collection.id}"
                            data-collection-name="${escapeHtml(collection.name)}">
                        Rate
                    </button>
                ` : ''}
                ${isOwner && collection.id !== 0 && !collection.is_marketplace_listed ? `
                    <button class="publish-btn px-3 py-1 rounded-md bg-green-600 hover:bg-green-500 text-sm text-white"
                            data-collection-id="${collection.id}"
                            data-collection-name="${escapeHtml(collection.name)}"
                            data-collection-description="${escapeHtml(collection.description || '')}">
                        Publish${collection.sharing_count > 0 ? ` (${collection.sharing_count} shared)` : ''}
                    </button>
                ` : ''}
                ${isOwner && collection.id !== 0 && collection.is_marketplace_listed ? `
                    <button class="unpublish-btn px-3 py-1 rounded-md bg-orange-600 hover:bg-orange-500 text-sm text-white"
                            data-collection-id="${collection.id}"
                            data-collection-name="${escapeHtml(collection.name)}">
                        Unpublish
                    </button>
                ` : ''}
            `}
        </div>
    `;
    
    // Attach event listeners
    const subscribeBtn = card.querySelector('.subscribe-btn');
    const unsubscribeBtn = card.querySelector('.unsubscribe-btn');
    const forkBtn = card.querySelector('.fork-btn');
    const publishBtn = card.querySelector('.publish-btn');
    const unpublishBtn = card.querySelector('.unpublish-btn');
    const rateBtn = card.querySelector('.rate-btn');
    if (subscribeBtn) {
        subscribeBtn.addEventListener('click', () => handleSubscribe(collection.id, subscribeBtn));
    }
    
    if (unsubscribeBtn) {
        unsubscribeBtn.addEventListener('click', () => handleUnsubscribe(collection.subscription_id, unsubscribeBtn));
    }
    
    if (forkBtn) {
        forkBtn.addEventListener('click', () => openForkModal(collection));
    }
    
    if (publishBtn) {
        publishBtn.addEventListener('click', () => openPublishModal(collection));
    }
    
    if (unpublishBtn) {
        unpublishBtn.addEventListener('click', () => handleUnpublish(collection.id, collection.name, unpublishBtn));
    }
    
    if (rateBtn) {
        rateBtn.addEventListener('click', () => openRateModal(collection));
    }
    
    return card;
}

/**
 * Render star rating
 */
function renderStars(rating) {
    const fullStars = Math.floor(rating);
    const hasHalfStar = rating % 1 >= 0.5;
    let starsHtml = '';
    
    for (let i = 0; i < 5; i++) {
        if (i < fullStars) {
            starsHtml += '<svg class="w-4 h-4 text-yellow-400" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"></path></svg>';
        } else if (i === fullStars && hasHalfStar) {
            starsHtml += '<svg class="w-4 h-4 text-yellow-400" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"></path></svg>';
        } else {
            starsHtml += '<svg class="w-4 h-4 text-gray-500" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"></path></svg>';
        }
    }
    
    return `<div class="flex gap-1">${starsHtml}</div>`;
}

/**
 * Update pagination UI
 */
function updatePaginationUI(data) {
    const pagination = document.getElementById('marketplace-pagination');
    const prevBtn = document.getElementById('marketplace-prev-btn');
    const nextBtn = document.getElementById('marketplace-next-btn');
    const pageInfo = document.getElementById('marketplace-page-info');
    
    if (!pagination) return;
    
    if (data.total_pages > 1) {
        pagination.classList.remove('hidden');
        
        if (prevBtn) {
            prevBtn.disabled = currentPage <= 1;
        }
        
        if (nextBtn) {
            nextBtn.disabled = currentPage >= data.total_pages;
        }
        
        if (pageInfo) {
            pageInfo.textContent = `Page ${currentPage} of ${data.total_pages} (${data.total_count} total)`;
        }
    } else {
        pagination.classList.add('hidden');
    }
}

/**
 * Handle subscribe action
 */
async function handleSubscribe(collectionId, button) {
    const originalText = button.textContent;
    button.textContent = 'Subscribing...';
    button.disabled = true;
    
    try {
        const token = window.authClient?.getToken();
        if (!token) {
            showNotification('error', 'Authentication required. Please log in.');
            button.textContent = originalText;
            button.disabled = false;
            return;
        }

        const response = await fetch(`/api/v1/marketplace/collections/${collectionId}/subscribe`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Subscription failed');
        }
        
        showNotification('success', 'Successfully subscribed to collection');
        loadMarketplaceCollections(); // Reload marketplace to update UI
        
        // Also reload RAG collections if the function is available
        if (window.loadRagCollections) {
            await window.loadRagCollections();
        }
        
    } catch (error) {
        console.error('Subscribe failed:', error);
        showNotification('error', 'Failed to subscribe: ' + error.message);
        button.textContent = originalText;
        button.disabled = false;
    }
}

/**
 * Handle unsubscribe action
 */
async function handleUnsubscribe(subscriptionId, button) {
    const originalText = button.textContent;
    button.textContent = 'Unsubscribing...';
    button.disabled = true;
    
    try {
        const token = window.authClient?.getToken();
        if (!token) {
            showNotification('error', 'Authentication required. Please log in.');
            button.textContent = originalText;
            button.disabled = false;
            return;
        }

        const response = await fetch(`/api/v1/marketplace/subscriptions/${subscriptionId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Unsubscribe failed');
        }

        showNotification('success', 'Successfully unsubscribed from collection');
        loadMarketplaceCollections(); // Reload marketplace to update UI
        
        // Also reload RAG collections if the function is available
        if (window.loadRagCollections) {
            await window.loadRagCollections();
        }
        
    } catch (error) {
        console.error('Unsubscribe failed:', error);
        showNotification('error', 'Failed to unsubscribe: ' + error.message);
        button.textContent = originalText;
        button.disabled = false;
    }
}

/**
 * Unsubscribe from a collection (wrapper for external use)
 * @param {string} subscriptionId - The subscription ID to cancel
 * @param {string} collectionName - Name of the collection (for notifications)
 */
export async function unsubscribeFromCollection(subscriptionId, collectionName) {
    if (!subscriptionId) {
        showNotification('error', 'Invalid subscription ID');
        return;
    }
    
    // Use custom confirmation if available
    if (window.showConfirmation) {
        window.showConfirmation(
            'Unsubscribe from Collection',
            `Are you sure you want to unsubscribe from "${collectionName}"?\n\nYou will lose access to this collection's cases.`,
            async () => {
                try {
                    const token = window.authClient?.getToken();
                    if (!token) {
                        showNotification('error', 'Authentication required. Please log in.');
                        return;
                    }

                    const response = await fetch(`/api/v1/marketplace/subscriptions/${subscriptionId}`, {
                        method: 'DELETE',
                        headers: {
                            'Authorization': `Bearer ${token}`
                        }
                    });
                    
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.message || error.error || 'Unsubscribe failed');
                    }
                    
                    showNotification('success', `Successfully unsubscribed from "${collectionName}"`);

                    // Reload both marketplace and RAG collections
                    loadMarketplaceCollections();
                    if (window.loadRagCollections) {
                        await window.loadRagCollections();
                    }

                } catch (error) {
                    console.error('Unsubscribe failed:', error);
                    showNotification('error', 'Failed to unsubscribe: ' + error.message);
                }
            }
        );
    } else {
        // Fallback without confirmation
        if (!confirm(`Are you sure you want to unsubscribe from "${collectionName}"?`)) {
            return;
        }
        
        try {
            const token = window.authClient?.getToken();
            if (!token) {
                showNotification('error', 'Authentication required. Please log in.');
                return;
            }

            const response = await fetch(`/api/v1/marketplace/subscriptions/${subscriptionId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || error.error || 'Unsubscribe failed');
            }

            showNotification('success', `Successfully unsubscribed from "${collectionName}"`);
            
            // Reload both marketplace and RAG collections
            loadMarketplaceCollections();
            if (window.loadRagCollections) {
                await window.loadRagCollections();
            }
            
        } catch (error) {
            console.error('Unsubscribe failed:', error);
            showNotification('error', 'Failed to unsubscribe: ' + error.message);
        }
    }
}

/**
 * Initialize fork modal
 */
function initializeForkModal() {
    const modal = document.getElementById('fork-collection-modal-overlay');
    const closeBtn = document.getElementById('fork-collection-modal-close');
    const cancelBtn = document.getElementById('fork-collection-cancel');
    const form = document.getElementById('fork-collection-form');
    
    if (closeBtn) {
        closeBtn.addEventListener('click', () => closeForkModal());
    }
    
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => closeForkModal());
    }
    
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            await handleFork();
        });
    }
    
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeForkModal();
        });
    }
}

/**
 * Open fork modal
 */
function openForkModal(collection) {
    const modal = document.getElementById('fork-collection-modal-overlay');
    const modalContent = document.getElementById('fork-collection-modal-content');
    const collectionIdInput = document.getElementById('fork-collection-id');
    const collectionNameInput = document.getElementById('fork-collection-name');
    const sourceName = document.getElementById('fork-source-name');
    const sourceDescription = document.getElementById('fork-source-description');
    
    if (!modal || !modalContent) return;
    
    // Set collection info
    if (collectionIdInput) {
        collectionIdInput.value = collection.id;
    }
    if (collectionNameInput) collectionNameInput.value = `${collection.name} (Fork)`;
    if (sourceName) sourceName.textContent = collection.name;
    if (sourceDescription) sourceDescription.textContent = collection.description || 'No description';
    
    // Show modal with animation
    modal.classList.remove('hidden');
    setTimeout(() => {
        modal.classList.add('opacity-100');
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);
}

/**
 * Close fork modal
 */
function closeForkModal() {
    const modal = document.getElementById('fork-collection-modal-overlay');
    const modalContent = document.getElementById('fork-collection-modal-content');
    const form = document.getElementById('fork-collection-form');
    
    if (!modal || !modalContent) return;
    
    modal.classList.remove('opacity-100');
    modalContent.classList.remove('scale-100', 'opacity-100');
    modalContent.classList.add('scale-95', 'opacity-0');
    
    setTimeout(() => {
        modal.classList.add('hidden');
        if (form) form.reset();
    }, 300);
}

/**
 * Handle fork submission
 */
async function handleFork() {
    const collectionId = document.getElementById('fork-collection-id')?.value;
    const newName = document.getElementById('fork-collection-name')?.value;
    const submitBtn = document.getElementById('fork-collection-submit');
    
    if (!collectionId || !newName) {
        showNotification('error', 'Please provide a name for the forked collection');
        return;
    }
    
    const originalText = submitBtn?.textContent || 'Fork Collection';
    if (submitBtn) {
        submitBtn.textContent = 'Forking...';
        submitBtn.disabled = true;
    }
    
    try {
        const token = window.authClient?.getToken();
        if (!token) {
            showNotification('error', 'Authentication required. Please log in.');
            if (submitBtn) {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            }
            return;
        }

        const response = await fetch(`/api/v1/marketplace/collections/${collectionId}/fork`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ 
                name: newName  // Backend will use user's own MCP server
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || error.error || 'Fork failed');
        }
        
        const result = await response.json();
        showNotification('success', `Successfully forked collection as "${newName}"`);
        closeForkModal();
        
        // Reload collections to show the new fork
        if (window.loadRagCollections) {
            await window.loadRagCollections();
        }
        
    } catch (error) {
        console.error('Fork failed:', error);
        showNotification('error', 'Failed to fork collection: ' + error.message);
    } finally {
        if (submitBtn) {
            submitBtn.textContent = originalText;
            submitBtn.disabled = false;
        }
    }
}

/**
 * Initialize publish modal
 */
let _collExistingGrants = [];  // Existing grants loaded on modal open

function initializePublishModal() {
    const modal = document.getElementById('publish-collection-modal-overlay');
    const closeBtn = document.getElementById('publish-collection-modal-close');
    const cancelBtn = document.getElementById('publish-collection-cancel');
    const form = document.getElementById('publish-collection-form');

    if (closeBtn) {
        closeBtn.addEventListener('click', () => closePublishModal());
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => closePublishModal());
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            await handlePublish();
        });
    }

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closePublishModal();
        });
    }

    // Visibility change handler — show/hide user picker section + update button text
    const visibilitySelect = document.getElementById('publish-visibility');
    if (visibilitySelect) {
        visibilitySelect.addEventListener('change', () => {
            const section = document.getElementById('publish-share-users-section');
            if (!section) return;
            if (visibilitySelect.value === 'targeted') {
                section.classList.remove('hidden');
                _loadPublishShareableUsers('');
            } else {
                section.classList.add('hidden');
            }
            _updatePublishCollectionButtonText();
        });
    }

    // Search input in user picker
    const searchInput = document.getElementById('publish-share-users-search');
    if (searchInput) {
        let debounce = null;
        searchInput.addEventListener('input', () => {
            clearTimeout(debounce);
            debounce = setTimeout(() => _loadPublishShareableUsers(searchInput.value), 300);
        });
    }
}

/**
 * Load shareable users for the publish modal user picker.
 * Pre-checks users who have existing grants.
 */
async function _loadPublishShareableUsers(search) {
    const listEl = document.getElementById('publish-share-users-list');
    if (!listEl) return;

    const token = window.authClient?.getToken();
    if (!token) return;

    try {
        const url = `/api/v1/marketplace/shareable-users${search ? `?search=${encodeURIComponent(search)}` : ''}`;
        const res = await fetch(url, { headers: { 'Authorization': `Bearer ${token}` } });
        const data = await res.json();

        if (!res.ok || data.status !== 'success' || !data.users.length) {
            listEl.innerHTML = '<p class="text-sm text-gray-500 text-center py-2">No eligible users found</p>';
            return;
        }

        // Preserve manual selections OR pre-check from existing grants
        const prevSelected = new Set();
        listEl.querySelectorAll('input[type=checkbox]:checked').forEach(cb => prevSelected.add(cb.value));
        const grantedUserIds = new Set(_collExistingGrants.map(g => g.grantee_user_id));

        listEl.innerHTML = data.users.map(u => {
            const isChecked = prevSelected.has(u.id) || grantedUserIds.has(u.id);
            return `
            <label class="flex items-center gap-2 p-1.5 rounded hover:bg-white/5 cursor-pointer">
                <input type="checkbox" value="${u.id}" class="publish-share-user-cb accent-indigo-500"
                       ${isChecked ? 'checked' : ''}>
                <span class="text-sm text-white">${escapeHtml(u.display_name)}</span>
                <span class="text-xs text-gray-500">${escapeHtml(u.username)}</span>
                ${u.email ? `<span class="text-xs text-gray-600 ml-auto">${escapeHtml(u.email)}</span>` : ''}
            </label>`;
        }).join('');

        // Update count on checkbox change
        listEl.querySelectorAll('.publish-share-user-cb').forEach(cb => {
            cb.addEventListener('change', _updatePublishShareCount);
        });
        _updatePublishShareCount();
    } catch (err) {
        listEl.innerHTML = '<p class="text-sm text-red-400 text-center py-2">Failed to load users</p>';
    }
}

function _updatePublishShareCount() {
    const countEl = document.getElementById('publish-share-users-count');
    if (!countEl) return;
    const checked = document.querySelectorAll('.publish-share-user-cb:checked').length;
    countEl.textContent = `${checked} user${checked !== 1 ? 's' : ''} selected`;
}

/**
 * Update the submit button text based on visibility and existing grants.
 */
function _updatePublishCollectionButtonText() {
    const submitBtn = document.getElementById('publish-collection-submit');
    const visibility = document.getElementById('publish-visibility')?.value;
    if (!submitBtn) return;
    if (visibility === 'targeted') {
        submitBtn.textContent = _collExistingGrants.length > 0 ? 'Save Changes' : 'Share';
    } else {
        submitBtn.textContent = 'Publish Collection';
    }
}

/**
 * Open publish modal.
 * Fetches existing grants to adaptively pre-select visibility and pre-check users.
 */
async function openPublishModal(collection) {
    const modal = document.getElementById('publish-collection-modal-overlay');
    const modalContent = document.getElementById('publish-collection-modal-content');
    const collectionIdInput = document.getElementById('publish-collection-id');
    const collectionName = document.getElementById('publish-collection-name');
    const collectionDescription = document.getElementById('publish-collection-description');
    const visibilitySelect = document.getElementById('publish-visibility');
    const usersSection = document.getElementById('publish-share-users-section');

    if (!modal || !modalContent) return;

    // Reset state
    _collExistingGrants = [];
    if (collectionIdInput) collectionIdInput.value = collection.id;
    if (collectionName) collectionName.textContent = collection.name;
    if (collectionDescription) collectionDescription.textContent = collection.description || 'No description';
    if (visibilitySelect) visibilitySelect.value = '';
    if (usersSection) usersSection.classList.add('hidden');

    // Show modal with animation
    modal.classList.remove('hidden');
    setTimeout(() => {
        modal.classList.add('opacity-100');
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);

    // Fetch existing grants to determine adaptive state
    try {
        const token = window.authClient?.getToken();
        if (token) {
            const res = await fetch(`/api/v1/marketplace/share/collection/${collection.id}`, {
                headers: { 'Authorization': `Bearer ${token}` },
            });
            const data = await res.json();
            _collExistingGrants = (data.status === 'success' && data.grants) ? data.grants : [];

            if (_collExistingGrants.length > 0) {
                // Pre-select "Targeted" and show user picker with pre-checked users
                if (visibilitySelect) visibilitySelect.value = 'targeted';
                if (usersSection) usersSection.classList.remove('hidden');
                await _loadPublishShareableUsers('');
            }
        }
    } catch { /* ignore, use defaults */ }

    _updatePublishCollectionButtonText();
}

/**
 * Close publish modal
 */
function closePublishModal() {
    const modal = document.getElementById('publish-collection-modal-overlay');
    const modalContent = document.getElementById('publish-collection-modal-content');
    const form = document.getElementById('publish-collection-form');

    if (!modal || !modalContent) return;

    modal.classList.remove('opacity-100');
    modalContent.classList.remove('scale-100', 'opacity-100');
    modalContent.classList.add('scale-95', 'opacity-0');

    setTimeout(() => {
        modal.classList.add('hidden');
        if (form) form.reset();
        _collExistingGrants = [];
    }, 300);
}

/**
 * Handle publish submission with grant sync.
 */
async function handlePublish() {
    const collectionId = document.getElementById('publish-collection-id')?.value;
    const visibility = document.getElementById('publish-visibility')?.value;
    const submitBtn = document.getElementById('publish-collection-submit');

    if (!collectionId || !visibility) {
        showNotification('error', 'Please select a visibility option');
        return;
    }

    const token = window.authClient?.getToken();
    if (!token) {
        showNotification('error', 'Authentication required. Please log in.');
        return;
    }

    // For targeted: grant sync (create new, revoke removed)
    if (visibility === 'targeted') {
        const selectedUserIds = [...document.querySelectorAll('.publish-share-user-cb:checked')].map(cb => cb.value);

        // Build map of existing grants by user ID
        const existingGrantsByUserId = {};
        _collExistingGrants.forEach(g => { existingGrantsByUserId[g.grantee_user_id] = g.id; });
        const existingUserIds = new Set(Object.keys(existingGrantsByUserId));

        // Determine what to create and revoke
        const toCreate = selectedUserIds.filter(uid => !existingUserIds.has(uid));
        const toRevoke = [...existingUserIds].filter(uid => !selectedUserIds.includes(uid));

        // Allow 0 selected only when revoking existing grants
        if (selectedUserIds.length === 0 && _collExistingGrants.length === 0) {
            showNotification('error', 'Please select at least one user to share with');
            return;
        }

        // Nothing changed
        if (toCreate.length === 0 && toRevoke.length === 0) {
            showNotification('info', 'No changes to save');
            closePublishModal();
            return;
        }

        const originalText = submitBtn?.textContent || 'Save Changes';
        if (submitBtn) { submitBtn.textContent = 'Saving...'; submitBtn.disabled = true; }

        try {
            const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` };

            // Create new grants
            if (toCreate.length > 0) {
                const res = await fetch('/api/v1/marketplace/share', {
                    method: 'POST', headers,
                    body: JSON.stringify({
                        resource_type: 'collection',
                        resource_id: collectionId,
                        user_ids: toCreate,
                    }),
                });
                const data = await res.json();
                if (!res.ok || data.status === 'error') {
                    throw new Error(data.message || 'Share failed');
                }
            }

            // Revoke removed grants
            for (const uid of toRevoke) {
                const res = await fetch(`/api/v1/marketplace/share/${existingGrantsByUserId[uid]}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` },
                });
                if (!res.ok) {
                    const data = await res.json();
                    throw new Error(data.message || 'Revoke failed');
                }
            }

            const msg = toRevoke.length > 0 && toCreate.length === 0
                ? `Removed sharing for ${toRevoke.length} user(s)`
                : 'Sharing updated';
            showNotification('success', msg);

            closePublishModal();
            loadMarketplaceContent();
        } catch (error) {
            console.error('Share failed:', error);
            showNotification('error', 'Failed: ' + error.message);
        } finally {
            if (submitBtn) { submitBtn.textContent = originalText; submitBtn.disabled = false; }
        }
        return;
    }

    // Public: call the existing publish endpoint
    const originalText = submitBtn?.textContent || 'Publish Collection';
    if (submitBtn) { submitBtn.textContent = 'Publishing...'; submitBtn.disabled = true; }

    try {
        const response = await fetch(`/api/v1/rag/collections/${collectionId}/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ visibility }),
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Publish failed');
        }
        showNotification('success', 'Successfully published collection to marketplace');

        closePublishModal();
        loadMarketplaceContent();
    } catch (error) {
        console.error('Publish failed:', error);
        showNotification('error', 'Failed to publish: ' + error.message);
    } finally {
        if (submitBtn) { submitBtn.textContent = originalText; submitBtn.disabled = false; }
    }
}

/**
 * Handle unpublish action
 */
async function handleUnpublish(collectionId, collectionName, button) {
    // Confirm unpublish
    const confirmed = window.showConfirmation ? await new Promise(resolve => {
        window.showConfirmation(
            'Unpublish Collection',
            `Are you sure you want to remove "${collectionName}" from the marketplace?\n\nExisting subscribers will retain read-only access, but new users won't be able to subscribe.`,
            () => resolve(true),
            () => resolve(false)
        );
    }) : confirm(`Remove "${collectionName}" from the marketplace?\n\nExisting subscribers will keep access.`);
    
    if (!confirmed) return;
    
    const originalText = button?.textContent || 'Unpublish';
    if (button) {
        button.textContent = 'Unpublishing...';
        button.disabled = true;
    }
    
    try {
        const token = window.authClient?.getToken();
        if (!token) {
            showNotification('error', 'Authentication required. Please log in.');
            return;
        }

        const response = await fetch(`/api/v1/rag/collections/${collectionId}/unpublish`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || error.error || 'Unpublish failed');
        }
        
        showNotification('success', 'Successfully unpublished collection from marketplace');
        loadMarketplaceCollections(); // Reload to update UI
        
        // Also reload RAG collections if available
        if (window.loadRagCollections) {
            await window.loadRagCollections();
        }
        
    } catch (error) {
        console.error('Unpublish failed:', error);
        showNotification('error', 'Failed to unpublish collection: ' + error.message);
    } finally {
        if (button) {
            button.textContent = originalText;
            button.disabled = false;
        }
    }
}


/**
 * Initialize rate modal
 */
function initializeRateModal() {
    const modal = document.getElementById('rate-collection-modal-overlay');
    const closeBtn = document.getElementById('rate-collection-modal-close');
    const cancelBtn = document.getElementById('rate-collection-cancel');
    const form = document.getElementById('rate-collection-form');
    const stars = document.querySelectorAll('.rate-star');
    const ratingInput = document.getElementById('rate-collection-rating');
    
    if (closeBtn) {
        closeBtn.addEventListener('click', () => closeRateModal());
    }
    
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => closeRateModal());
    }
    
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            await handleRate();
        });
    }
    
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeRateModal();
        });
    }
    
    // Star rating interaction
    stars.forEach(star => {
        star.addEventListener('click', () => {
            const rating = star.getAttribute('data-rating');
            if (ratingInput) ratingInput.value = rating;
            
            // Update star colors
            stars.forEach((s, index) => {
                const svg = s.querySelector('svg');
                if (svg) {
                    if (index < parseInt(rating)) {
                        svg.classList.remove('text-gray-500');
                        svg.classList.add('text-yellow-400');
                    } else {
                        svg.classList.remove('text-yellow-400');
                        svg.classList.add('text-gray-500');
                    }
                }
            });
        });
    });
}

/**
 * Open rate modal
 */
function openRateModal(collection) {
    const modal = document.getElementById('rate-collection-modal-overlay');
    const modalContent = document.getElementById('rate-collection-modal-content');
    const collectionIdInput = document.getElementById('rate-collection-id');
    const collectionName = document.getElementById('rate-collection-name');
    const ratingInput = document.getElementById('rate-collection-rating');
    const stars = document.querySelectorAll('.rate-star svg');
    
    if (!modal || !modalContent) return;
    
    // Reset stars
    stars.forEach(svg => {
        svg.classList.remove('text-yellow-400');
        svg.classList.add('text-gray-500');
    });
    
    // Set collection info
    if (collectionIdInput) collectionIdInput.value = collection.id;
    if (collectionName) collectionName.textContent = collection.name;
    if (ratingInput) ratingInput.value = '';
    
    // Show modal with animation
    modal.classList.remove('hidden');
    setTimeout(() => {
        modal.classList.add('opacity-100');
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);
}

/**
 * Close rate modal
 */
function closeRateModal() {
    const modal = document.getElementById('rate-collection-modal-overlay');
    const modalContent = document.getElementById('rate-collection-modal-content');
    const form = document.getElementById('rate-collection-form');
    
    if (!modal || !modalContent) return;
    
    modal.classList.remove('opacity-100');
    modalContent.classList.remove('scale-100', 'opacity-100');
    modalContent.classList.add('scale-95', 'opacity-0');
    
    setTimeout(() => {
        modal.classList.add('hidden');
        if (form) form.reset();
    }, 300);
}

/**
 * Handle rate submission
 */
async function handleRate() {
    const collectionId = document.getElementById('rate-collection-id')?.value;
    const rating = document.getElementById('rate-collection-rating')?.value;
    const review = document.getElementById('rate-collection-review')?.value;
    const submitBtn = document.getElementById('rate-collection-submit');
    
    if (!collectionId || !rating) {
        showNotification('error', 'Please select a rating');
        return;
    }
    
    const originalText = submitBtn?.textContent || 'Submit Rating';
    if (submitBtn) {
        submitBtn.textContent = 'Submitting...';
        submitBtn.disabled = true;
    }
    
    try {
        const token = window.authClient?.getToken();
        if (!token) {
            showNotification('error', 'Authentication required. Please log in.');
            if (submitBtn) {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            }
            return;
        }

        const body = { rating: parseInt(rating) };
        if (review) body.review = review;
        
        const response = await fetch(`/api/v1/marketplace/collections/${collectionId}/rate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify(body)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Rating submission failed');
        }
        
        showNotification('success', 'Successfully submitted rating');
        closeRateModal();
        loadMarketplaceCollections(); // Reload to update ratings
        
    } catch (error) {
        console.error('Rate failed:', error);
        showNotification('error', 'Failed to submit rating: ' + error.message);
    } finally {
        if (submitBtn) {
            submitBtn.textContent = originalText;
            submitBtn.disabled = false;
        }
    }
}

// ============================================================================
// TARGETED SHARING — Share Modal + Grant Management
// ============================================================================

/**
 * Open the share modal for a resource (collection or agent pack).
 * Shows a user picker + list of existing grants with revoke buttons.
 */
async function openShareModal(resourceType, resourceId, resourceName) {
    const token = window.authClient?.getToken();
    if (!token) {
        showNotification('error', 'Authentication required');
        return;
    }

    // Build overlay
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[10000]';
    overlay.id = 'share-modal-overlay';
    overlay.innerHTML = `
        <div class="glass-panel rounded-xl p-6 w-full max-w-lg border border-white/10 shadow-2xl max-h-[90vh] overflow-y-auto">
            <h3 class="text-lg font-bold text-white mb-1">Share</h3>
            <p class="text-sm text-gray-400 mb-4">
                Share <span class="text-white font-medium">${escapeHtml(resourceName)}</span> with specific users.
                Check to grant access, uncheck to revoke.
            </p>

            <!-- User picker -->
            <div class="mb-4">
                <div class="relative mb-2">
                    <input type="text" id="share-modal-search" placeholder="Search users..."
                           class="w-full p-2 pl-8 bg-gray-700 border border-gray-600 rounded-md text-white text-sm focus:outline-none focus:border-blue-500">
                    <svg class="w-4 h-4 text-gray-400 absolute left-2 top-1/2 -translate-y-1/2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                    </svg>
                </div>
                <div id="share-modal-users-list" class="max-h-48 overflow-y-auto space-y-1 bg-white/5 rounded-lg p-2 border border-white/10">
                    <p class="text-sm text-gray-500 text-center py-2">Loading...</p>
                </div>
                <p id="share-modal-status" class="text-xs text-gray-400 mt-1"></p>
            </div>

            <hr class="border-white/10 my-4">

            <!-- Current access info -->
            <div>
                <label class="block text-sm font-medium text-gray-300 mb-2">Current Access</label>
                <div id="share-modal-access-list" class="space-y-1">
                    <p class="text-sm text-gray-500 text-center py-2">No users have access yet</p>
                </div>
            </div>

            <div class="flex justify-end gap-3 mt-4 pt-4 border-t border-white/10">
                <button id="share-modal-close" class="px-4 py-2 text-sm rounded-lg bg-white/5 text-gray-300 hover:bg-white/10 transition-colors">Close</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Close handlers
    const closeModal = () => overlay.remove();
    overlay.querySelector('#share-modal-close').onclick = closeModal;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

    // Maps: userId → grantId (for revoke), userId → grant data
    let grantsByUserId = {};
    const authHeaders = { 'Authorization': `Bearer ${token}` };

    // Grant access to a user (check handler)
    const _grantUser = async (userId, cb) => {
        cb.disabled = true;
        const statusEl = overlay.querySelector('#share-modal-status');
        statusEl.textContent = 'Sharing...';
        statusEl.className = 'text-xs text-gray-400 mt-1';
        try {
            const res = await fetch('/api/v1/marketplace/share', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders },
                body: JSON.stringify({ resource_type: resourceType, resource_id: resourceId, user_ids: [userId] }),
            });
            const data = await res.json();
            if (!res.ok || data.status === 'error') throw new Error(data.message || 'Share failed');
            statusEl.textContent = 'Access granted';
            statusEl.className = 'text-xs text-green-400 mt-1';
            // Refresh grants to get the new grant ID
            await _loadGrants();
        } catch (err) {
            cb.checked = false;
            cb.disabled = false;
            statusEl.textContent = `Failed: ${err.message}`;
            statusEl.className = 'text-xs text-red-400 mt-1';
        }
    };

    // Revoke access from a user (uncheck handler)
    const _revokeUser = async (userId, cb) => {
        const grantId = grantsByUserId[userId];
        if (!grantId) { cb.checked = false; return; }
        cb.disabled = true;
        const statusEl = overlay.querySelector('#share-modal-status');
        statusEl.textContent = 'Revoking...';
        statusEl.className = 'text-xs text-gray-400 mt-1';
        try {
            const res = await fetch(`/api/v1/marketplace/share/${grantId}`, {
                method: 'DELETE',
                headers: authHeaders,
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || 'Revoke failed');
            statusEl.textContent = 'Access revoked';
            statusEl.className = 'text-xs text-yellow-400 mt-1';
            await _loadGrants();
        } catch (err) {
            cb.checked = true;
            cb.disabled = false;
            statusEl.textContent = `Failed: ${err.message}`;
            statusEl.className = 'text-xs text-red-400 mt-1';
        }
    };

    // Render user list with current grant state
    const _renderUsers = (users) => {
        const listEl = overlay.querySelector('#share-modal-users-list');
        if (!users?.length) {
            listEl.innerHTML = '<p class="text-sm text-gray-500 text-center py-2">No eligible users found</p>';
            return;
        }
        const sharedCount = Object.keys(grantsByUserId).length;
        const statusEl = overlay.querySelector('#share-modal-status');
        statusEl.textContent = sharedCount > 0 ? `Shared with ${sharedCount} user${sharedCount !== 1 ? 's' : ''}` : '';
        statusEl.className = 'text-xs text-gray-400 mt-1';

        listEl.innerHTML = users.map(u => {
            const isGranted = !!grantsByUserId[u.id];
            return `
            <label class="flex items-center gap-2 p-1.5 rounded hover:bg-white/5 cursor-pointer">
                <input type="checkbox" value="${u.id}" class="share-modal-user-cb accent-indigo-500"
                       ${isGranted ? 'checked' : ''}>
                <span class="text-sm text-white">${escapeHtml(u.display_name)}</span>
                <span class="text-xs text-gray-500">${escapeHtml(u.username)}</span>
                ${u.email ? `<span class="text-xs text-gray-600 ml-auto">${escapeHtml(u.email)}</span>` : ''}
            </label>`;
        }).join('');

        listEl.querySelectorAll('.share-modal-user-cb').forEach(cb => {
            cb.addEventListener('change', () => {
                if (cb.checked) {
                    _grantUser(cb.value, cb);
                } else {
                    _revokeUser(cb.value, cb);
                }
            });
        });
    };

    // Cache last loaded users so we can re-render without re-fetching
    let cachedUsers = [];

    // Load shareable users from API
    const _loadUsers = async (search) => {
        const listEl = overlay.querySelector('#share-modal-users-list');
        try {
            const url = `/api/v1/marketplace/shareable-users${search ? `?search=${encodeURIComponent(search)}` : ''}`;
            const res = await fetch(url, { headers: authHeaders });
            const data = await res.json();
            cachedUsers = (res.ok && data.users) ? data.users : [];
            _renderUsers(cachedUsers);
        } catch {
            listEl.innerHTML = '<p class="text-sm text-red-400 text-center py-2">Failed to load users</p>';
        }
    };

    // Load existing grants (populates grantsByUserId, re-renders user list + access info)
    const _loadGrants = async () => {
        try {
            const res = await fetch(`/api/v1/marketplace/share/${resourceType}/${resourceId}`, {
                headers: authHeaders,
            });
            const data = await res.json();
            grantsByUserId = {};
            const accessEl = overlay.querySelector('#share-modal-access-list');

            if (res.ok && data.grants?.length) {
                data.grants.forEach(g => { grantsByUserId[g.grantee_user_id] = g.id; });
                // Render current access info
                accessEl.innerHTML = data.grants.map(g => `
                    <div class="flex items-center justify-between p-2 rounded bg-white/5 border border-white/5">
                        <div class="flex items-center gap-2">
                            <svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                            </svg>
                            <span class="text-sm text-white">${escapeHtml(g.grantee_display_name || g.grantee_username || g.grantee_user_id)}</span>
                        </div>
                        <span class="text-xs text-gray-500">${g.created_at ? new Date(g.created_at).toLocaleDateString() : ''}</span>
                    </div>
                `).join('');
            } else {
                accessEl.innerHTML = '<p class="text-sm text-gray-500 text-center py-2">No users have access yet</p>';
            }

            // Re-render user list with updated grant state
            if (cachedUsers.length) {
                _renderUsers(cachedUsers);
            }
        } catch {
            // Silent — grants just won't be pre-checked
        }
    };

    // Search input handler
    const searchInput = overlay.querySelector('#share-modal-search');
    let debounce = null;
    searchInput.addEventListener('input', () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => _loadUsers(searchInput.value), 300);
    });

    // Initial load — grants first, then users
    await _loadGrants();
    _loadUsers('');
}

// Expose openShareModal globally for agentPackHandler
window.openShareModal = openShareModal;

// Export refresh function for external use
export function refreshMarketplace() {
    currentPage = 1;
    loadMarketplaceContent();
}

// Make refreshMarketplace globally accessible
window.refreshMarketplace = refreshMarketplace;
