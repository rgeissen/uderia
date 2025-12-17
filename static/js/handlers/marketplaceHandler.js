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
let currentRepositoryType = 'planner'; // 'planner' or 'knowledge'

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
            loadMarketplaceCollections();
        });
    }
    
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                currentPage = 1;
                currentSearch = searchInput.value;
                currentVisibility = visibilityFilter?.value || 'public';
                currentSortBy = sortFilter?.value || 'subscribers';
                loadMarketplaceCollections();
            }
        });
    }
    
    // Auto-reload when sort filter changes
    if (sortFilter) {
        sortFilter.addEventListener('change', () => {
            currentPage = 1;
            currentSortBy = sortFilter.value;
            loadMarketplaceCollections();
        });
    }
    
    // Pagination handlers
    const prevBtn = document.getElementById('marketplace-prev-btn');
    const nextBtn = document.getElementById('marketplace-next-btn');
    
    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                loadMarketplaceCollections();
            }
        });
    }
    
    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            if (currentPage < totalPages) {
                currentPage++;
                loadMarketplaceCollections();
            }
        });
    }
    
    // Initialize modals
    initializeForkModal();
    initializePublishModal();
    initializeRateModal();
    
    // Load initial collections
    loadMarketplaceCollections();
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
    
    loadMarketplaceCollections();
}

/**
 * Switch between repository types (planner / knowledge)
 */
function switchRepositoryType(type) {
    currentRepositoryType = type;
    currentPage = 1;
    
    // Update tab styling
    const plannerTab = document.getElementById('marketplace-repo-type-planner');
    const knowledgeTab = document.getElementById('marketplace-repo-type-knowledge');
    const plannerDesc = document.getElementById('planner-description');
    const knowledgeDesc = document.getElementById('knowledge-description');
    
    if (type === 'planner') {
        if (plannerTab) {
            plannerTab.classList.add('bg-[#F15F22]', 'text-white');
            plannerTab.classList.remove('text-gray-400', 'hover:bg-white/10');
        }
        if (knowledgeTab) {
            knowledgeTab.classList.remove('bg-[#F15F22]', 'text-white');
            knowledgeTab.classList.add('text-gray-400', 'hover:bg-white/10');
        }
        if (plannerDesc) plannerDesc.classList.remove('hidden');
        if (knowledgeDesc) knowledgeDesc.classList.add('hidden');
    } else {
        if (knowledgeTab) {
            knowledgeTab.classList.add('bg-[#F15F22]', 'text-white');
            knowledgeTab.classList.remove('text-gray-400', 'hover:bg-white/10');
        }
        if (plannerTab) {
            plannerTab.classList.remove('bg-[#F15F22]', 'text-white');
            plannerTab.classList.add('text-gray-400', 'hover:bg-white/10');
        }
        if (knowledgeDesc) knowledgeDesc.classList.remove('hidden');
        if (plannerDesc) plannerDesc.classList.add('hidden');
    }
    
    loadMarketplaceCollections();
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
            // Filter out Default Collection (ID 0), filter by repository type, and mark all as owned
            collections = collections
                .filter(c => c.id !== 0 && c.repository_type === currentRepositoryType)
                .map(c => ({ ...c, is_owner: true }));
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
        showNotification('Failed to load marketplace collections: ' + error.message, 'error');
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
    
    // Repository type badge configuration
    const repoTypeBadge = repositoryType === 'knowledge' 
        ? '<span class="px-2 py-1 text-xs rounded-full bg-purple-500/20 text-purple-400 flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>Knowledge</span>'
        : '<span class="px-2 py-1 text-xs rounded-full bg-blue-500/20 text-blue-400 flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>Planner</span>';
    
    card.innerHTML = `
        <!-- Header with title and status badge -->
        <div class="flex items-start justify-between gap-2">
            <div class="flex-1">
                <h2 class="text-lg font-semibold text-white">${escapeHtml(collection.name)}</h2>
                <p class="text-xs text-gray-500">Collection ID: ${collection.id}</p>
            </div>
            <div class="flex flex-col items-end gap-1">
                ${repoTypeBadge}
                ${isOwner && collection.is_marketplace_listed ? `
                    <span class="px-2 py-1 text-xs rounded-full bg-green-500/20 text-green-400">Published</span>
                ` : ''}
                ${isOwner && !collection.is_marketplace_listed && collection.visibility === 'private' ? `
                    <span class="px-2 py-1 text-xs rounded-full bg-gray-500/20 text-gray-400">Private</span>
                ` : ''}
                ${collection.visibility === 'unlisted' && collection.is_marketplace_listed ? `
                    <span class="px-2 py-1 text-xs rounded-full bg-yellow-500/20 text-yellow-400">Unlisted</span>
                ` : ''}
            </div>
        </div>
        
        <!-- Description -->
        ${collection.description ? `
            <p class="text-xs text-gray-400">${escapeHtml(collection.description)}</p>
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
                <button class="rate-btn px-3 py-1 rounded-md bg-purple-600 hover:bg-purple-500 text-sm text-white"
                        data-collection-id="${collection.id}"
                        data-collection-name="${escapeHtml(collection.name)}">
                    Rate
                </button>
            ` : ''}
            ${isOwner && collection.id !== 0 ? `
                <button class="publish-btn px-3 py-1 rounded-md bg-green-600 hover:bg-green-500 text-sm text-white"
                        data-collection-id="${collection.id}"
                        data-collection-name="${escapeHtml(collection.name)}"
                        data-collection-description="${escapeHtml(collection.description || '')}">
                    ${collection.is_marketplace_listed ? 'Update' : 'Publish'}
                </button>
            ` : ''}
            ${isOwner && collection.id === 0 ? `
                <button class="px-3 py-1 rounded-md bg-gray-800 text-sm text-gray-600 cursor-not-allowed" 
                        disabled
                        title="The Default Collection cannot be shared">
                    Cannot Share
                </button>
            ` : ''}
        </div>
    `;
    
    // Attach event listeners
    const subscribeBtn = card.querySelector('.subscribe-btn');
    const unsubscribeBtn = card.querySelector('.unsubscribe-btn');
    const forkBtn = card.querySelector('.fork-btn');
    const publishBtn = card.querySelector('.publish-btn');
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
            showNotification('Authentication required. Please log in.', 'error');
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
        
        showNotification('Successfully subscribed to collection', 'success');
        loadMarketplaceCollections(); // Reload marketplace to update UI
        
        // Also reload RAG collections if the function is available
        if (window.loadRagCollections) {
            await window.loadRagCollections();
        }
        
    } catch (error) {
        console.error('Subscribe failed:', error);
        showNotification('Failed to subscribe: ' + error.message, 'error');
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
            showNotification('Authentication required. Please log in.', 'error');
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
        
        showNotification('Successfully unsubscribed from collection', 'success');
        loadMarketplaceCollections(); // Reload marketplace to update UI
        
        // Also reload RAG collections if the function is available
        if (window.loadRagCollections) {
            await window.loadRagCollections();
        }
        
    } catch (error) {
        console.error('Unsubscribe failed:', error);
        showNotification('Failed to unsubscribe: ' + error.message, 'error');
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
        showNotification('Invalid subscription ID', 'error');
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
                        showNotification('Authentication required. Please log in.', 'error');
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
                    
                    showNotification(`Successfully unsubscribed from "${collectionName}"`, 'success');
                    
                    // Reload both marketplace and RAG collections
                    loadMarketplaceCollections();
                    if (window.loadRagCollections) {
                        await window.loadRagCollections();
                    }
                    
                } catch (error) {
                    console.error('Unsubscribe failed:', error);
                    showNotification('Failed to unsubscribe: ' + error.message, 'error');
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
                showNotification('Authentication required. Please log in.', 'error');
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
            
            showNotification(`Successfully unsubscribed from "${collectionName}"`, 'success');
            
            // Reload both marketplace and RAG collections
            loadMarketplaceCollections();
            if (window.loadRagCollections) {
                await window.loadRagCollections();
            }
            
        } catch (error) {
            console.error('Unsubscribe failed:', error);
            showNotification('Failed to unsubscribe: ' + error.message, 'error');
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
        showNotification('Please provide a name for the forked collection', 'error');
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
            showNotification('Authentication required. Please log in.', 'error');
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
        showNotification(`Successfully forked collection as "${newName}"`, 'success');
        closeForkModal();
        
        // Reload collections to show the new fork
        if (window.loadRagCollections) {
            await window.loadRagCollections();
        }
        
    } catch (error) {
        console.error('Fork failed:', error);
        showNotification('Failed to fork collection: ' + error.message, 'error');
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
}

/**
 * Open publish modal
 */
function openPublishModal(collection) {
    const modal = document.getElementById('publish-collection-modal-overlay');
    const modalContent = document.getElementById('publish-collection-modal-content');
    const collectionIdInput = document.getElementById('publish-collection-id');
    const collectionName = document.getElementById('publish-collection-name');
    const collectionDescription = document.getElementById('publish-collection-description');
    const visibilitySelect = document.getElementById('publish-visibility');
    
    if (!modal || !modalContent) return;
    
    // Set collection info
    if (collectionIdInput) collectionIdInput.value = collection.id;
    if (collectionName) collectionName.textContent = collection.name;
    if (collectionDescription) collectionDescription.textContent = collection.description || 'No description';
    if (visibilitySelect && collection.visibility !== 'private') {
        visibilitySelect.value = collection.visibility;
    }
    
    // Show modal with animation
    modal.classList.remove('hidden');
    setTimeout(() => {
        modal.classList.add('opacity-100');
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);
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
    }, 300);
}

/**
 * Handle publish submission
 */
async function handlePublish() {
    const collectionId = document.getElementById('publish-collection-id')?.value;
    const visibility = document.getElementById('publish-visibility')?.value;
    const submitBtn = document.getElementById('publish-collection-submit');
    
    if (!collectionId || !visibility) {
        showNotification('Please select a visibility option', 'error');
        return;
    }
    
    const originalText = submitBtn?.textContent || 'Publish Collection';
    if (submitBtn) {
        submitBtn.textContent = 'Publishing...';
        submitBtn.disabled = true;
    }
    
    try {
        // Get authentication token
        const token = window.authClient?.getToken();
        if (!token) {
            showNotification('Authentication required. Please log in.', 'error');
            return;
        }
        
        const response = await fetch(`/api/v1/rag/collections/${collectionId}/publish`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ visibility })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Publish failed');
        }
        
        showNotification('Successfully published collection to marketplace', 'success');
        closePublishModal();
        loadMarketplaceCollections(); // Reload to update UI
        
    } catch (error) {
        console.error('Publish failed:', error);
        showNotification('Failed to publish collection: ' + error.message, 'error');
    } finally {
        if (submitBtn) {
            submitBtn.textContent = originalText;
            submitBtn.disabled = false;
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
        showNotification('Please select a rating', 'error');
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
            showNotification('Authentication required. Please log in.', 'error');
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
        
        showNotification('Successfully submitted rating', 'success');
        closeRateModal();
        loadMarketplaceCollections(); // Reload to update ratings
        
    } catch (error) {
        console.error('Rate failed:', error);
        showNotification('Failed to submit rating: ' + error.message, 'error');
    } finally {
        if (submitBtn) {
            submitBtn.textContent = originalText;
            submitBtn.disabled = false;
        }
    }
}

// Export refresh function for external use
export function refreshMarketplace() {
    currentPage = 1;
    loadMarketplaceCollections();
}

// Make refreshMarketplace globally accessible
window.refreshMarketplace = refreshMarketplace;
