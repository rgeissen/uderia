/**
 * Access Token Manager
 * Handles UI interactions for access token management
 */

const AccessTokenManager = {
    /**
     * Initialize the access token manager
     */
    init() {
        this.bindEvents();
        this.loadAccessTokens();
    },

    /**
     * Bind event listeners
     */
    bindEvents() {
        // Create token button
        const createBtn = document.getElementById('create-access-token-btn');
        if (createBtn) {
            createBtn.addEventListener('click', () => this.showCreateModal());
        }

        // Cancel token creation
        const cancelBtn = document.getElementById('cancel-token-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.hideCreateModal());
        }

        // Confirm token creation
        const confirmBtn = document.getElementById('confirm-create-token-btn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => this.createToken());
        }

        // Close token display modal
        const closeDisplayBtn = document.getElementById('close-token-display-btn');
        if (closeDisplayBtn) {
            closeDisplayBtn.addEventListener('click', () => this.hideTokenDisplayModal());
        }

        // Copy new token
        const copyNewTokenBtn = document.getElementById('copy-new-token-btn');
        if (copyNewTokenBtn) {
            copyNewTokenBtn.addEventListener('click', () => this.copyNewToken());
        }

        // Close modals on backdrop click
        document.getElementById('create-token-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'create-token-modal') this.hideCreateModal();
        });
        document.getElementById('token-display-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'token-display-modal') this.hideTokenDisplayModal();
        });
    },

    /**
     * Show create token modal
     */
    showCreateModal() {
        document.getElementById('create-token-modal')?.classList.remove('hidden');
        document.getElementById('token-name')?.focus();
    },

    /**
     * Hide create token modal
     */
    hideCreateModal() {
        document.getElementById('create-token-modal')?.classList.add('hidden');
        document.getElementById('token-name').value = '';
        document.getElementById('token-expiry').value = '90';
    },

    /**
     * Show token display modal with the new token
     */
    showTokenDisplayModal(token) {
        const modal = document.getElementById('token-display-modal');
        const input = document.getElementById('new-token-value');
        if (modal && input) {
            input.value = token;
            modal.classList.remove('hidden');
        }
    },

    /**
     * Hide token display modal
     */
    hideTokenDisplayModal() {
        document.getElementById('token-display-modal')?.classList.add('hidden');
        document.getElementById('new-token-value').value = '';
        this.loadAccessTokens(); // Refresh the list
    },

    /**
     * Show banner message (uses centralized application-level banner system)
     */
    showBanner(message, type = 'info') {
        // Use global function from bannerSystem.js
        if (window.showAppBanner) {
            window.showAppBanner(message, type);
        } else {
            console.error('[AccessTokenManager] showAppBanner not available. Message:', message);
        }
    },

    /**
     * Copy the newly created token to clipboard
     */
    async copyNewToken() {
        const input = document.getElementById('new-token-value');
        if (input) {
            try {
                await navigator.clipboard.writeText(input.value);
                const btn = document.getElementById('copy-new-token-btn');
                const originalHTML = btn.innerHTML;
                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg> Copied!';
                btn.classList.remove('bg-green-600', 'hover:bg-green-700');
                btn.classList.add('bg-green-700');
                setTimeout(() => {
                    btn.innerHTML = originalHTML;
                    btn.classList.add('bg-green-600', 'hover:bg-green-700');
                    btn.classList.remove('bg-green-700');
                }, 2000);
            } catch (err) {
                console.error('Failed to copy:', err);
                this.showBanner('Failed to copy token to clipboard', 'error');
            }
        }
    },

    /**
     * Create a new access token
     */
    async createToken() {
        const name = document.getElementById('token-name')?.value.trim();
        const expiryDays = parseInt(document.getElementById('token-expiry')?.value || '0');

        if (!name) {
            this.showBanner('Please enter a token name', 'warning');
            return;
        }

        try {
            // Get JWT token from authClient
            const jwtToken = window.authClient ? window.authClient.getToken() : localStorage.getItem('tda_auth_token');
            if (!jwtToken) {
                this.showBanner('Authentication required. Please log in.', 'error');
                return;
            }
            
            const response = await fetch('/api/v1/auth/tokens', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${jwtToken}`
                },
                body: JSON.stringify({
                    name: name,
                    expires_in_days: expiryDays > 0 ? expiryDays : null
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.hideCreateModal();
                this.showTokenDisplayModal(data.token);
                this.showBanner(`Access token "${name}" created successfully`, 'success');
            } else {
                console.error('Token creation failed:', response.status, data);
                const errorMsg = data.message || data.detail || 'Failed to create token';
                this.showBanner(errorMsg, 'error');
            }
        } catch (err) {
            console.error('Error creating token:', err);
            this.showBanner('Failed to create token. Please check the console for details.', 'error');
        }
    },

    /**
     * Load and display access tokens
     */
    async loadAccessTokens() {
        const container = document.getElementById('access-tokens-list');
        if (!container) return;

        container.innerHTML = '<div class="text-center text-gray-500 text-sm py-4">Loading tokens...</div>';

        try {
            // Get JWT token from authClient
            const jwtToken = window.authClient ? window.authClient.getToken() : localStorage.getItem('tda_auth_token');
            if (!jwtToken) {
                container.innerHTML = '<div class="text-center text-gray-500 text-sm py-4">Please log in to view tokens</div>';
                return;
            }
            
            const response = await fetch('/api/v1/auth/tokens?include_revoked=true', {
                headers: {
                    'Authorization': `Bearer ${jwtToken}`
                }
            });

            if (!response.ok) {
                // Don't show error for authentication issues, just show empty state
                if (response.status === 401) {
                    container.innerHTML = '<div class="text-center text-gray-500 text-sm py-4">No access tokens yet. Create one to get started!</div>';
                    return;
                }
                throw new Error('Failed to load tokens');
            }

            const data = await response.json();
            const tokens = data.tokens || [];

            if (tokens.length === 0) {
                container.innerHTML = '<div class="text-center text-gray-500 text-sm py-4">No access tokens yet. Create one to get started!</div>';
                return;
            }

            container.innerHTML = tokens.map(token => this.renderToken(token)).join('');

            // Bind revoke buttons
            tokens.forEach(token => {
                const btn = document.getElementById(`revoke-token-${token.id}`);
                if (btn) {
                    btn.addEventListener('click', () => this.revokeToken(token.id));
                }
            });
        } catch (err) {
            console.error('Error loading tokens:', err);
            // Only show error for actual failures, not empty state
            container.innerHTML = '<div class="text-center text-gray-500 text-sm py-4">No access tokens yet. Create one to get started!</div>';
        }
    },

    /**
     * Render a single token card
     */
    renderToken(token) {
        const createdDate = new Date(token.created_at).toLocaleDateString();
        const lastUsed = token.last_used_at ? new Date(token.last_used_at).toLocaleDateString() : 'Never';
        const expiresAt = token.expires_at ? new Date(token.expires_at).toLocaleDateString() : 'Never';
        const isExpired = token.expires_at && new Date(token.expires_at) < new Date();
        const isRevoked = token.revoked;
        const revokedDate = token.revoked_at ? new Date(token.revoked_at).toLocaleDateString() : null;

        let statusBadge = '';
        let cardOpacity = '';
        if (isRevoked) {
            statusBadge = '<span class="px-2 py-1 text-xs font-medium bg-red-900/30 text-red-400 rounded">Revoked</span>';
            cardOpacity = 'opacity-60';
        } else if (isExpired) {
            statusBadge = '<span class="px-2 py-1 text-xs font-medium bg-yellow-900/30 text-yellow-400 rounded">Expired</span>';
            cardOpacity = 'opacity-75';
        } else {
            statusBadge = '<span class="px-2 py-1 text-xs font-medium bg-green-900/30 text-green-400 rounded">Active</span>';
        }

        return `
            <div class="bg-gray-700/50 rounded-md p-4 border border-gray-600 ${cardOpacity}">
                <div class="flex items-start justify-between mb-3">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-2">
                            <h5 class="text-sm font-medium text-white">${this.escapeHtml(token.name)}</h5>
                            ${statusBadge}
                        </div>
                        <p class="text-xs font-mono text-gray-400">${this.escapeHtml(token.token_prefix)}...</p>
                    </div>
                    ${!isRevoked ? `
                    <button id="revoke-token-${token.id}" class="card-btn card-btn--sm card-btn--danger">
                        Revoke
                    </button>
                    ` : ''}
                </div>
                <div class="grid grid-cols-2 gap-3 text-xs">
                    <div>
                        <span class="text-gray-500">Created:</span>
                        <span class="text-gray-300 ml-1">${createdDate}</span>
                    </div>
                    <div>
                        <span class="text-gray-500">Last Used:</span>
                        <span class="text-gray-300 ml-1">${lastUsed}</span>
                    </div>
                    ${isRevoked ? `
                    <div>
                        <span class="text-gray-500">Revoked:</span>
                        <span class="text-red-400 ml-1">${revokedDate}</span>
                    </div>
                    ` : `
                    <div>
                        <span class="text-gray-500">Expires:</span>
                        <span class="text-gray-300 ml-1">${expiresAt}</span>
                    </div>
                    `}
                    <div>
                        <span class="text-gray-500">Uses:</span>
                        <span class="text-gray-300 ml-1">${token.use_count || 0}</span>
                    </div>
                </div>
            </div>
        `;
    },

    /**
     * Revoke an access token
     */
    async revokeToken(tokenId) {
        // Use custom confirmation modal instead of browser confirm()
        if (!window.showConfirmation) {
            console.error('Confirmation system not available');
            return;
        }
        
        window.showConfirmation(
            'Revoke Access Token',
            'Are you sure you want to revoke this token? The token will become inactive but remain in the audit trail.',
            async () => {
                try {
                    // Get JWT token from authClient
                    const jwtToken = window.authClient ? window.authClient.getToken() : localStorage.getItem('tda_auth_token');
                    if (!jwtToken) {
                        this.showBanner('Authentication required', 'error');
                        return;
                    }
                    
                    const response = await fetch(`/api/v1/auth/tokens/${tokenId}`, {
                        method: 'DELETE',
                        headers: {
                            'Authorization': `Bearer ${jwtToken}`
                        }
                    });

                    if (response.ok) {
                        this.showBanner('Access token revoked successfully', 'success');
                        this.loadAccessTokens(); // Refresh the list
                    } else {
                        const data = await response.json();
                        this.showBanner(data.detail || 'Failed to revoke token', 'error');
                    }
                } catch (err) {
                    console.error('Error revoking token:', err);
                    this.showBanner('Failed to revoke token. Please try again.', 'error');
                }
            }
        );
    },

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => AccessTokenManager.init());
} else {
    AccessTokenManager.init();
}

// Export for global access
window.AccessTokenManager = AccessTokenManager;
