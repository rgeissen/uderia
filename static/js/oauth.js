/**
 * OAuth Client JavaScript
 * 
 * Handles OAuth provider operations, account linking/unlinking, and provider management
 */

class OAuthClient {
    constructor() {
        this.apiBase = '/api/v1/auth';
    }

    /**
     * Get list of available OAuth providers
     * @returns {Promise<Array>} List of provider objects
     */
    async getAvailableProviders() {
        try {
            const response = await fetch(`${this.apiBase}/oauth/providers`);
            const data = await response.json();
            
            if (data.status === 'success') {
                return data.providers || [];
            }
            return [];
        } catch (error) {
            console.error('Error fetching OAuth providers:', error);
            return [];
        }
    }

    /**
     * Get user's linked OAuth accounts
     * @returns {Promise<Array>} List of linked OAuth accounts
     */
    async getLinkedAccounts() {
        try {
            const response = await fetch(`${this.apiBase}/oauth/accounts`);
            
            if (!response.ok) {
                if (response.status === 401) {
                    // Not authenticated
                    return [];
                }
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.status === 'success') {
                return data.accounts || [];
            }
            return [];
        } catch (error) {
            console.error('Error fetching linked accounts:', error);
            return [];
        }
    }

    /**
     * Initiate linking an OAuth provider to user's account
     * @param {string} provider - OAuth provider name
     */
    initiateOAuthLink(provider) {
        window.location.href = `${this.apiBase}/oauth/${provider}/link`;
    }

    /**
     * Disconnect/unlink an OAuth account
     * @param {string} provider - OAuth provider name
     * @returns {Promise<{success: boolean, message: string}>}
     */
    async disconnectOAuthAccount(provider) {
        try {
            const response = await fetch(
                `${this.apiBase}/oauth/${provider}/disconnect`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                }
            );
            
            const data = await response.json();
            
            return {
                success: data.status === 'success',
                message: data.message || 'Operation failed'
            };
        } catch (error) {
            console.error('Error disconnecting OAuth account:', error);
            return {
                success: false,
                message: 'An error occurred while disconnecting'
            };
        }
    }

    /**
     * Handle OAuth callback redirect (internal use)
     * Processes token from URL parameters
     * @returns {Promise<{success: boolean, token?: string, error?: string}>}
     */
    async handleOAuthCallback() {
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('token');
        const error = urlParams.get('error');

        if (error) {
            return {
                success: false,
                error: decodeURIComponent(error)
            };
        }

        if (token) {
            return {
                success: true,
                token: token
            };
        }

        return {
            success: false,
            error: 'No token found in callback'
        };
    }

    /**
     * Get OAuth provider display info
     * @returns {Object} Map of provider names to display info
     */
    getProviderInfo() {
        return {
            google: {
                name: 'Google',
                icon: '🔵',
                color: '#EA4335'
            },
            github: {
                name: 'GitHub',
                icon: '⚫',
                color: '#181717'
            },
            microsoft: {
                name: 'Microsoft',
                icon: '🟦',
                color: '#00A4EF'
            },
            discord: {
                name: 'Discord',
                icon: '🟪',
                color: '#5865F2'
            },
            okta: {
                name: 'Okta',
                icon: '🟦',
                color: '#007DC1'
            }
        };
    }

    /**
     * Format a linked OAuth account for display
     * @param {Object} account - OAuth account object
     * @returns {Object} Formatted account info
     */
    formatLinkedAccount(account) {
        const providerInfo = this.getProviderInfo()[account.provider] || {
            name: account.provider.charAt(0).toUpperCase() + account.provider.slice(1),
            icon: '◉'
        };

        return {
            ...account,
            displayName: providerInfo.name,
            icon: providerInfo.icon,
            linkedDate: account.created_at ? new Date(account.created_at).toLocaleDateString() : 'Unknown'
        };
    }
}
