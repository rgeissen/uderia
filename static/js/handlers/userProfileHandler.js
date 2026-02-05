/**
 * User Profile Handler
 *
 * Manages the User Profile modal: loads data from multiple endpoints,
 * renders 6 sections (Identity, Personal Info, Account, Security,
 * Connected Accounts, Usage Statistics), handles inline editing,
 * and marketplace visibility toggle.
 */

class UserProfileManager {
    constructor() {
        this.userData = null;
        this.quotaData = null;
        this.tokensData = null;
        this.oauthAccounts = [];
        this.oauthProviders = [];
        this.isEditing = false;
    }

    // =========================================================================
    // API Helpers
    // =========================================================================

    _getToken() {
        return window.authClient ? window.authClient.getToken() : localStorage.getItem('tda_auth_token');
    }

    async _fetch(url, options = {}) {
        const token = this._getToken();
        const headers = {
            'Content-Type': 'application/json',
            ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            ...(options.headers || {})
        };
        const res = await fetch(url, { ...options, headers });
        return res.json();
    }

    // =========================================================================
    // Modal Open / Close
    // =========================================================================

    async openProfile() {
        const overlay = document.getElementById('user-profile-modal-overlay');
        const content = document.getElementById('user-profile-modal-content');
        if (!overlay || !content) return;

        // Close user dropdown
        const dropdown = document.getElementById('user-dropdown-menu');
        if (dropdown) dropdown.classList.remove('open');

        // Show overlay with animation
        overlay.classList.remove('hidden');
        requestAnimationFrame(() => {
            overlay.style.opacity = '1';
            content.style.transform = 'scale(1)';
            content.style.opacity = '1';
        });

        // Load data and render
        await this._loadAllData();
        this._renderSections();
    }

    closeProfile() {
        const overlay = document.getElementById('user-profile-modal-overlay');
        const content = document.getElementById('user-profile-modal-content');
        if (!overlay) return;

        // Animate out
        overlay.style.opacity = '0';
        if (content) {
            content.style.transform = 'scale(0.95)';
            content.style.opacity = '0';
        }

        setTimeout(() => {
            overlay.classList.add('hidden');
        }, 300);
    }

    // =========================================================================
    // Data Loading
    // =========================================================================

    async _loadAllData() {
        const results = await Promise.allSettled([
            this._fetch('/api/v1/auth/me'),
            this._fetch('/api/v1/auth/user/quota-status'),
            this._fetch('/api/v1/auth/tokens'),
            this._fetch('/api/v1/auth/oauth/accounts'),
            this._fetch('/api/v1/auth/oauth/providers'),
        ]);

        if (results[0].status === 'fulfilled' && results[0].value.status === 'success') {
            this.userData = results[0].value.user;
        }
        if (results[1].status === 'fulfilled' && results[1].value.status === 'success') {
            this.quotaData = results[1].value.quota;
        }
        if (results[2].status === 'fulfilled' && results[2].value.status === 'success') {
            this.tokensData = results[2].value.tokens || [];
        }
        if (results[3].status === 'fulfilled') {
            const d = results[3].value;
            this.oauthAccounts = d.accounts || d.linked_accounts || [];
        }
        if (results[4].status === 'fulfilled') {
            const d = results[4].value;
            this.oauthProviders = d.providers || [];
        }
    }

    // =========================================================================
    // Section Rendering
    // =========================================================================

    _renderSections() {
        const body = document.getElementById('profile-modal-body');
        if (!body || !this.userData) return;

        body.innerHTML = [
            this._renderIdentityHeader(),
            this._renderPersonalInfo(),
            `<div class="profile-two-col">
                ${this._renderAccountDetails()}
                ${this._renderSecurity()}
            </div>`,
            `<div class="profile-two-col">
                ${this._renderConnectedAccounts()}
                ${this._renderUsageStatistics()}
            </div>`,
            this._renderMarketplace(),
        ].join('');

        this._attachEventListeners();
    }

    // -------------------------------------------------------------------------
    // 1. Identity Header
    // -------------------------------------------------------------------------

    _renderIdentityHeader() {
        const u = this.userData;
        const initials = this._getInitials(u.display_name || u.username);
        const tierBadge = this._renderTierBadge(u.profile_tier);
        const memberSince = this._formatDate(u.created_at);

        return `
        <div class="profile-section profile-identity-card">
            <div class="flex items-center gap-4">
                <div class="profile-avatar-large">
                    <span>${initials}</span>
                </div>
                <div class="flex-1 min-w-0">
                    <h3 class="text-lg font-bold truncate" style="color: var(--text-primary);">${this._esc(u.display_name || u.username)}</h3>
                    <p class="text-sm" style="color: var(--text-muted);">@${this._esc(u.username)}</p>
                    <div class="flex items-center gap-2 mt-1 flex-wrap">
                        ${tierBadge}
                        <span class="text-xs" style="color: var(--text-muted);">Member since ${memberSince}</span>
                    </div>
                </div>
            </div>
        </div>`;
    }

    // -------------------------------------------------------------------------
    // 2. Personal Information (editable)
    // -------------------------------------------------------------------------

    _renderPersonalInfo() {
        const u = this.userData;
        return `
        <div class="profile-section">
            <div class="flex justify-between items-center mb-4">
                <h4 class="profile-section-title">Personal Information</h4>
                <button id="profile-edit-btn" class="profile-action-btn" title="Edit personal information">Edit</button>
            </div>
            <div id="profile-personal-view" class="profile-kv-grid">
                <div class="profile-kv-key">Display Name</div>
                <div class="profile-kv-value">${this._esc(u.display_name || '—')}</div>
                <div class="profile-kv-key">Full Name</div>
                <div class="profile-kv-value">${this._esc(u.full_name || '—')}</div>
            </div>
            <div id="profile-personal-edit" class="hidden space-y-3">
                <div>
                    <label class="block text-xs font-medium mb-1" style="color: var(--text-muted);">Display Name</label>
                    <input id="profile-edit-display-name" type="text" value="${this._esc(u.display_name || '')}" maxlength="100"
                        class="profile-field-input w-full px-3 py-2 rounded-lg text-sm">
                </div>
                <div>
                    <label class="block text-xs font-medium mb-1" style="color: var(--text-muted);">Full Name</label>
                    <input id="profile-edit-full-name" type="text" value="${this._esc(u.full_name || '')}" maxlength="255"
                        class="profile-field-input w-full px-3 py-2 rounded-lg text-sm">
                </div>
                <div class="flex gap-2 pt-1">
                    <button id="profile-save-btn" class="px-4 py-1.5 rounded-lg text-sm font-medium text-white" style="background: var(--teradata-orange);">Save</button>
                    <button id="profile-cancel-btn" class="px-4 py-1.5 rounded-lg text-sm font-medium" style="color: var(--text-muted); background: var(--bg-tertiary);">Cancel</button>
                </div>
            </div>
        </div>`;
    }

    // -------------------------------------------------------------------------
    // 3. Account Details (read-only)
    // -------------------------------------------------------------------------

    _renderAccountDetails() {
        const u = this.userData;
        const verifiedBadge = u.email_verified
            ? '<span class="ml-2 text-xs font-medium px-1.5 py-0.5 rounded" style="background: rgba(16,185,129,0.15); color: #10b981;">Verified</span>'
            : '<span class="ml-2 text-xs font-medium px-1.5 py-0.5 rounded" style="background: rgba(239,68,68,0.15); color: #ef4444;">Unverified</span>';
        const lastLogin = u.last_login_at ? this._formatDateTime(u.last_login_at) : 'Never';

        return `
        <div class="profile-section">
            <h4 class="profile-section-title mb-4">Account Details</h4>
            <div class="profile-kv-grid">
                <div class="profile-kv-key">Email</div>
                <div class="profile-kv-value">${this._esc(u.email)}${verifiedBadge}</div>
                <div class="profile-kv-key">Username</div>
                <div class="profile-kv-value">@${this._esc(u.username)}</div>
                <div class="profile-kv-key">Profile Tier</div>
                <div class="profile-kv-value">${this._renderTierBadge(u.profile_tier)}</div>
                <div class="profile-kv-key">Last Login</div>
                <div class="profile-kv-value">${lastLogin}</div>
            </div>
        </div>`;
    }

    // -------------------------------------------------------------------------
    // 4. Security
    // -------------------------------------------------------------------------

    _renderSecurity() {
        const activeTokens = Array.isArray(this.tokensData)
            ? this.tokensData.filter(t => !t.revoked).length
            : 0;

        return `
        <div class="profile-section">
            <h4 class="profile-section-title mb-4">Security</h4>
            <div class="profile-kv-grid">
                <div class="profile-kv-key">Password</div>
                <div class="profile-kv-value flex items-center gap-2">
                    <span style="letter-spacing: 2px;">••••••••</span>
                    <button id="profile-change-pw-btn" class="profile-action-btn text-xs">Change Password</button>
                </div>
                <div class="profile-kv-key">Access Tokens</div>
                <div class="profile-kv-value">${activeTokens} active</div>
            </div>
        </div>`;
    }

    // -------------------------------------------------------------------------
    // 5. Connected Accounts
    // -------------------------------------------------------------------------

    _renderConnectedAccounts() {
        const linkedHtml = this.oauthAccounts.length > 0
            ? this.oauthAccounts.map(acc => {
                const icon = this._getProviderIcon(acc.provider);
                const email = acc.provider_email || acc.provider_name || '';
                return `
                <div class="flex items-center justify-between py-2 px-3 rounded-lg" style="background: var(--bg-tertiary); border: 1px solid var(--border-primary);">
                    <div class="flex items-center gap-2">
                        <span class="text-lg">${icon}</span>
                        <div>
                            <span class="text-sm font-medium" style="color: var(--text-primary);">${this._esc(acc.provider)}</span>
                            ${email ? `<span class="text-xs ml-2" style="color: var(--text-muted);">${this._esc(email)}</span>` : ''}
                        </div>
                    </div>
                    <button class="profile-disconnect-btn text-xs px-2 py-1 rounded" data-provider="${this._esc(acc.provider)}"
                        style="color: #ef4444; background: rgba(239,68,68,0.1);">Disconnect</button>
                </div>`;
            }).join('')
            : '<p class="text-sm italic" style="color: var(--text-muted);">No connected accounts</p>';

        // Available providers to link (not already linked)
        const linkedNames = this.oauthAccounts.map(a => a.provider.toLowerCase());
        const availableHtml = this.oauthProviders
            .filter(p => !linkedNames.includes(p.name.toLowerCase()))
            .map(p => {
                const icon = this._getProviderIcon(p.name);
                return `
                <button class="profile-link-provider-btn flex items-center gap-2 px-3 py-2 rounded-lg text-sm" data-provider="${this._esc(p.name)}"
                    style="background: var(--bg-tertiary); border: 1px solid var(--border-primary); color: var(--text-primary);"
                    onmouseover="this.style.borderColor='var(--border-secondary)'" onmouseout="this.style.borderColor='var(--border-primary)'">
                    <span>${icon}</span> ${this._esc(p.name)}
                </button>`;
            }).join('');

        return `
        <div class="profile-section">
            <h4 class="profile-section-title mb-4">Connected Accounts</h4>
            <div class="space-y-2">
                ${linkedHtml}
            </div>
            ${availableHtml ? `
            <div class="mt-3 pt-3" style="border-top: 1px solid var(--border-primary);">
                <p class="text-xs font-medium mb-2" style="color: var(--text-muted);">Link Additional Account</p>
                <div class="flex flex-wrap gap-2">${availableHtml}</div>
            </div>` : ''}
        </div>`;
    }

    // -------------------------------------------------------------------------
    // 6. Usage Statistics
    // -------------------------------------------------------------------------

    _renderUsageStatistics() {
        if (!this.quotaData) {
            return `
            <div class="profile-section">
                <h4 class="profile-section-title mb-4">Usage Statistics</h4>
                <p class="text-sm italic" style="color: var(--text-muted);">No usage data available</p>
            </div>`;
        }

        const q = this.quotaData;
        // quota-status returns nested: { period, input_tokens: { used, limit, ... }, output_tokens: { used, limit, ... } }
        const inputUsed = q.input_tokens?.used ?? 0;
        const outputUsed = q.output_tokens?.used ?? 0;
        const inputLimit = q.input_tokens?.limit;
        const outputLimit = q.output_tokens?.limit;
        const period = q.period || this._getCurrentPeriod();

        // Calculate usage percentage
        let usagePercent = null;
        if (inputLimit || outputLimit) {
            const totalUsed = inputUsed + outputUsed;
            const totalLimit = (inputLimit || 0) + (outputLimit || 0);
            if (totalLimit > 0) usagePercent = Math.min(100, Math.round((totalUsed / totalLimit) * 100));
        }

        const barColor = usagePercent === null ? '' :
            usagePercent < 50 ? '#10b981' :
            usagePercent < 80 ? '#f59e0b' : '#ef4444';

        return `
        <div class="profile-section">
            <h4 class="profile-section-title mb-4">Usage Statistics</h4>
            <div class="profile-kv-grid">
                <div class="profile-kv-key">Current Period</div>
                <div class="profile-kv-value">${this._formatPeriod(period)}</div>
                <div class="profile-kv-key">Input Tokens</div>
                <div class="profile-kv-value">${this._formatNumber(inputUsed)}${inputLimit ? ` / ${this._formatNumber(inputLimit)}` : ''}</div>
                <div class="profile-kv-key">Output Tokens</div>
                <div class="profile-kv-value">${this._formatNumber(outputUsed)}${outputLimit ? ` / ${this._formatNumber(outputLimit)}` : ''}</div>
                ${usagePercent !== null ? `
                <div class="profile-kv-key">Quota Status</div>
                <div class="profile-kv-value">
                    <div class="flex items-center gap-2 w-full">
                        <div class="profile-quota-bar flex-1">
                            <div class="profile-quota-fill" style="width: ${usagePercent}%; background: ${barColor};"></div>
                        </div>
                        <span class="text-xs font-medium" style="color: ${barColor};">${usagePercent}%</span>
                    </div>
                </div>` : `
                <div class="profile-kv-key">Quota</div>
                <div class="profile-kv-value">No quotas configured</div>`}
            </div>
        </div>`;
    }

    // -------------------------------------------------------------------------
    // 7. Marketplace Visibility
    // -------------------------------------------------------------------------

    _renderMarketplace() {
        const u = this.userData;
        const isVisible = u.marketplace_visible || false;

        return `
        <div class="profile-section">
            <h4 class="profile-section-title mb-3">Marketplace</h4>
            <div class="flex items-center justify-between">
                <div>
                    <p class="text-sm" style="color: var(--text-primary);">Listed in Marketplace</p>
                    <p class="text-xs mt-0.5" style="color: var(--text-muted);">When enabled, your username and email will be visible to other marketplace users</p>
                </div>
                <label class="profile-toggle">
                    <input type="checkbox" id="profile-marketplace-toggle" ${isVisible ? 'checked' : ''}>
                    <span class="profile-toggle-slider"></span>
                </label>
            </div>
        </div>`;
    }

    // =========================================================================
    // Event Listeners
    // =========================================================================

    _attachEventListeners() {
        // Close button
        const closeBtn = document.getElementById('profile-modal-close');
        if (closeBtn) closeBtn.addEventListener('click', () => this.closeProfile());

        // Overlay click
        const overlay = document.getElementById('user-profile-modal-overlay');
        if (overlay) {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) this.closeProfile();
            });
        }

        // Edit / Save / Cancel for Personal Info
        const editBtn = document.getElementById('profile-edit-btn');
        const saveBtn = document.getElementById('profile-save-btn');
        const cancelBtn = document.getElementById('profile-cancel-btn');

        if (editBtn) editBtn.addEventListener('click', () => this._enterEditMode());
        if (saveBtn) saveBtn.addEventListener('click', () => this._saveProfile());
        if (cancelBtn) cancelBtn.addEventListener('click', () => this._exitEditMode());

        // Change password button
        const changePwBtn = document.getElementById('profile-change-pw-btn');
        if (changePwBtn) {
            changePwBtn.addEventListener('click', () => {
                this.closeProfile();
                setTimeout(() => {
                    document.getElementById('change-password-modal-overlay')?.classList.remove('hidden');
                }, 350);
            });
        }

        // Marketplace toggle
        const marketplaceToggle = document.getElementById('profile-marketplace-toggle');
        if (marketplaceToggle) {
            marketplaceToggle.addEventListener('change', (e) => this._toggleMarketplace(e.target.checked));
        }

        // OAuth disconnect buttons
        document.querySelectorAll('.profile-disconnect-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this._handleDisconnect(e));
        });

        // OAuth link buttons
        document.querySelectorAll('.profile-link-provider-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this._handleLinkProvider(e));
        });

        // Keyboard: ESC to close
        this._escHandler = (e) => {
            if (e.key === 'Escape') this.closeProfile();
        };
        document.addEventListener('keydown', this._escHandler);
    }

    // =========================================================================
    // Edit Mode
    // =========================================================================

    _enterEditMode() {
        document.getElementById('profile-personal-view')?.classList.add('hidden');
        document.getElementById('profile-personal-edit')?.classList.remove('hidden');
        document.getElementById('profile-edit-btn')?.classList.add('hidden');
        this.isEditing = true;
    }

    _exitEditMode() {
        document.getElementById('profile-personal-view')?.classList.remove('hidden');
        document.getElementById('profile-personal-edit')?.classList.add('hidden');
        document.getElementById('profile-edit-btn')?.classList.remove('hidden');
        this.isEditing = false;
    }

    async _saveProfile() {
        const displayName = document.getElementById('profile-edit-display-name')?.value || '';
        const fullName = document.getElementById('profile-edit-full-name')?.value || '';

        const saveBtn = document.getElementById('profile-save-btn');
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';
        }

        try {
            const result = await this._fetch('/api/v1/auth/me', {
                method: 'PUT',
                body: JSON.stringify({
                    display_name: displayName,
                    full_name: fullName,
                }),
            });

            if (result.status === 'success') {
                this.userData.display_name = displayName;
                this.userData.full_name = fullName;
                this._exitEditMode();
                this._renderSections();

                // Update header display name
                const headerName = document.getElementById('user-display-name');
                if (headerName) headerName.textContent = displayName || this.userData.username;
                const menuName = document.getElementById('user-menu-name');
                if (menuName) menuName.textContent = displayName || this.userData.username;

                window.showAppBanner?.('Profile updated successfully', 'success', 3000);
            } else {
                window.showAppBanner?.(result.message || 'Failed to update profile', 'error', 4000);
            }
        } catch (err) {
            console.error('[Profile] Save error:', err);
            window.showAppBanner?.('An error occurred while saving', 'error', 4000);
        } finally {
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save';
            }
        }
    }

    // =========================================================================
    // Marketplace Toggle
    // =========================================================================

    async _toggleMarketplace(visible) {
        try {
            const result = await this._fetch('/api/v1/auth/me', {
                method: 'PUT',
                body: JSON.stringify({ marketplace_visible: visible }),
            });

            if (result.status === 'success') {
                this.userData.marketplace_visible = visible;
                window.showAppBanner?.(
                    visible ? 'You are now listed in the marketplace' : 'You have been removed from the marketplace',
                    'success', 3000
                );
            } else {
                // Revert toggle
                const toggle = document.getElementById('profile-marketplace-toggle');
                if (toggle) toggle.checked = !visible;
                window.showAppBanner?.(result.message || 'Failed to update marketplace visibility', 'error', 4000);
            }
        } catch (err) {
            console.error('[Profile] Marketplace toggle error:', err);
            const toggle = document.getElementById('profile-marketplace-toggle');
            if (toggle) toggle.checked = !visible;
            window.showAppBanner?.('An error occurred', 'error', 4000);
        }
    }

    // =========================================================================
    // OAuth Actions
    // =========================================================================

    async _handleDisconnect(event) {
        const provider = event.target.dataset.provider;
        if (!confirm(`Disconnect your ${provider} account?`)) return;

        event.target.disabled = true;
        event.target.textContent = 'Disconnecting...';

        try {
            const oauth = window.oauthClient || (typeof OAuthClient !== 'undefined' ? new OAuthClient() : null);
            if (oauth) {
                const result = await oauth.disconnectOAuthAccount(provider);
                if (result.success) {
                    window.showAppBanner?.(`${provider} account disconnected`, 'success', 3000);
                    await this._loadAllData();
                    this._renderSections();
                } else {
                    window.showAppBanner?.(result.message || 'Failed to disconnect', 'error', 4000);
                    event.target.disabled = false;
                    event.target.textContent = 'Disconnect';
                }
            }
        } catch (err) {
            console.error('[Profile] Disconnect error:', err);
            event.target.disabled = false;
            event.target.textContent = 'Disconnect';
        }
    }

    _handleLinkProvider(event) {
        const provider = event.target.closest('[data-provider]')?.dataset.provider;
        if (!provider) return;
        const oauth = window.oauthClient || (typeof OAuthClient !== 'undefined' ? new OAuthClient() : null);
        if (oauth) oauth.initiateOAuthLink(provider);
    }

    // =========================================================================
    // Utilities
    // =========================================================================

    _getInitials(name) {
        if (!name) return '?';
        const parts = name.trim().split(/\s+/);
        if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        return parts[0].substring(0, 2).toUpperCase();
    }

    _renderTierBadge(tier) {
        const colors = {
            admin: { bg: 'rgba(239, 68, 68, 0.15)', text: '#ef4444', label: 'Admin' },
            developer: { bg: 'rgba(99, 102, 241, 0.15)', text: '#818cf8', label: 'Developer' },
            user: { bg: 'rgba(16, 185, 129, 0.15)', text: '#10b981', label: 'User' },
        };
        const c = colors[tier] || colors.user;
        return `<span class="text-xs font-semibold px-2 py-0.5 rounded" style="background: ${c.bg}; color: ${c.text};">${c.label}</span>`;
    }

    _getProviderIcon(provider) {
        const icons = {
            google: '<svg class="inline w-4 h-4" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>',
            github: '<svg class="inline w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>',
            microsoft: '<svg class="inline w-4 h-4" viewBox="0 0 24 24"><rect fill="#F25022" x="1" y="1" width="10" height="10"/><rect fill="#7FBA00" x="13" y="1" width="10" height="10"/><rect fill="#00A4EF" x="1" y="13" width="10" height="10"/><rect fill="#FFB900" x="13" y="13" width="10" height="10"/></svg>',
        };
        return icons[provider.toLowerCase()] || '<span class="inline-block w-4 h-4 rounded-full" style="background: var(--text-muted);"></span>';
    }

    _formatDate(isoStr) {
        if (!isoStr) return '—';
        try {
            return new Date(isoStr).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
        } catch { return isoStr; }
    }

    _formatDateTime(isoStr) {
        if (!isoStr) return '—';
        try {
            return new Date(isoStr).toLocaleString('en-US', {
                month: 'short', day: 'numeric', year: 'numeric',
                hour: 'numeric', minute: '2-digit'
            });
        } catch { return isoStr; }
    }

    _formatNumber(n) {
        if (n == null) return '0';
        return Number(n).toLocaleString();
    }

    _formatPeriod(period) {
        if (!period) return '—';
        const [year, month] = period.split('-');
        const months = ['January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'];
        return `${months[parseInt(month, 10) - 1] || month} ${year}`;
    }

    _getCurrentPeriod() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    }

    _esc(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
}

// =========================================================================
// Initialize
// =========================================================================

(function () {
    const manager = new UserProfileManager();
    window.UserProfileManager = manager;
})();
