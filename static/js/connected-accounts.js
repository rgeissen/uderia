/**
 * Connected Accounts Component
 * 
 * Manages display and interaction with linked OAuth accounts
 */

class ConnectedAccountsComponent {
    constructor(containerId = 'connected-accounts-container') {
        this.containerId = containerId;
        this.oauth = new OAuthClient();
        this.accounts = [];
        this.providers = [];
    }

    /**
     * Initialize the component
     */
    async initialize() {
        await this.loadData();
        this.render();
        this.attachEventListeners();
    }

    /**
     * Load accounts and providers data
     */
    async loadData() {
        this.accounts = await this.oauth.getLinkedAccounts();
        this.providers = await this.oauth.getAvailableProviders();
    }

    /**
     * Render the component HTML
     */
    render() {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        const html = `
            <div class="connected-accounts-section space-y-6">
                <!-- Header -->
                <div>
                    <h3 class="text-xl font-semibold text-white mb-2">Connected Accounts</h3>
                    <p class="text-slate-400 text-sm">Manage your OAuth account connections for seamless login and account linking</p>
                </div>

                <!-- Linked Accounts -->
                <div class="space-y-3">
                    <h4 class="text-sm font-semibold text-slate-300">Linked Accounts</h4>
                    <div id="linked-accounts-list" class="space-y-3">
                        ${this.renderLinkedAccounts()}
                    </div>
                </div>

                <!-- Available Providers -->
                <div class="space-y-3 pt-4 border-t border-slate-700">
                    <h4 class="text-sm font-semibold text-slate-300">Link Additional Accounts</h4>
                    <div id="available-providers-list" class="grid grid-cols-2 md:grid-cols-3 gap-3">
                        ${this.renderAvailableProviders()}
                    </div>
                </div>

                <!-- Info -->
                <div class="p-4 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-300 text-sm">
                    <p class="flex items-start gap-2">
                        <span class="text-lg leading-none">ℹ️</span>
                        <span>You can link multiple OAuth accounts to your profile for flexible login options.</span>
                    </p>
                </div>
            </div>
        `;

        container.innerHTML = html;
    }

    /**
     * Render linked accounts section
     */
    renderLinkedAccounts() {
        if (!this.accounts || this.accounts.length === 0) {
            return '<p class="text-slate-500 text-sm italic">No connected accounts yet</p>';
        }

        return this.accounts.map(account => {
            const formatted = this.oauth.formatLinkedAccount(account);
            return `
                <div class="flex items-center justify-between p-4 rounded-lg bg-slate-800/50 border border-slate-700 hover:border-slate-600 transition-colors">
                    <div class="flex items-center gap-3 flex-1">
                        <span class="text-2xl">${formatted.icon}</span>
                        <div>
                            <p class="font-semibold text-white text-sm">${formatted.displayName}</p>
                            <p class="text-xs text-slate-500">
                                ${formatted.provider_email ? `Connected as: ${formatted.provider_email}` : 'Connected'}
                                ${formatted.linkedDate ? ` • Linked ${formatted.linkedDate}` : ''}
                            </p>
                        </div>
                    </div>
                    <button
                        class="disconnect-btn px-3 py-2 text-sm font-medium text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors"
                        data-provider="${account.provider}"
                        title="Disconnect this OAuth account"
                    >
                        Disconnect
                    </button>
                </div>
            `;
        }).join('');
    }

    /**
     * Render available providers to link
     */
    renderAvailableProviders() {
        const linkedProviders = this.accounts.map(a => a.provider.toLowerCase());

        return this.providers
            .filter(provider => !linkedProviders.includes(provider.name.toLowerCase()))
            .map(provider => {
                const providerInfo = this.oauth.getProviderInfo()[provider.name.toLowerCase()] || {
                    name: provider.name,
                    icon: '◉'
                };

                return `
                    <button
                        class="link-provider-btn flex flex-col items-center gap-2 p-4 rounded-lg bg-slate-800/50 border border-slate-700 hover:border-slate-600 hover:bg-slate-700/50 transition-all text-white text-sm font-medium"
                        data-provider="${provider.name}"
                        title="Connect ${providerInfo.name} account"
                    >
                        <span class="text-2xl">${providerInfo.icon}</span>
                        <span class="text-xs">${providerInfo.name}</span>
                    </button>
                `;
            })
            .join('');
    }

    /**
     * Attach event listeners to buttons
     */
    attachEventListeners() {
        // Disconnect buttons
        document.querySelectorAll('.disconnect-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.handleDisconnect(e));
        });

        // Link provider buttons
        document.querySelectorAll('.link-provider-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.handleLinkProvider(e));
        });
    }

    /**
     * Handle disconnect button click
     */
    async handleDisconnect(event) {
        const provider = event.target.dataset.provider;
        
        if (!confirm(`Are you sure you want to disconnect your ${provider} account?`)) {
            return;
        }

        event.target.disabled = true;
        const originalText = event.target.textContent;
        event.target.textContent = 'Disconnecting...';

        try {
            const result = await this.oauth.disconnectOAuthAccount(provider);
            
            if (result.success) {
                this.showMessage(`${provider} account disconnected successfully`, 'success');
                // Reload component after a short delay
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            } else {
                this.showMessage(result.message || 'Failed to disconnect account', 'error');
                event.target.disabled = false;
                event.target.textContent = originalText;
            }
        } catch (error) {
            console.error('Error disconnecting account:', error);
            this.showMessage('An error occurred while disconnecting', 'error');
            event.target.disabled = false;
            event.target.textContent = originalText;
        }
    }

    /**
     * Handle link provider button click
     */
    handleLinkProvider(event) {
        const provider = event.target.dataset.provider;
        this.oauth.initiateOAuthLink(provider);
    }

    /**
     * Show message to user
     */
    showMessage(message, type = 'info') {
        // Try to use existing alert system if available
        if (window.showAlert) {
            window.showAlert(message, type);
        } else {
            // Fallback: simple alert
            alert(message);
        }
    }

    /**
     * Refresh the component
     */
    async refresh() {
        await this.loadData();
        this.render();
        this.attachEventListeners();
    }
}

/**
 * Initialize connected accounts component when DOM is ready
 */
document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('connected-accounts-container');
    if (container) {
        const component = new ConnectedAccountsComponent('connected-accounts-container');
        component.initialize();
    }
});
