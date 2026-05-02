/**
 * Admin SSO / OIDC Configuration Handler
 *
 * Manages the Admin Panel → SSO tab:
 *   - List / create / edit / delete OIDC provider configurations
 *   - Test discovery endpoint connectivity
 *   - Claims mapping and group→tier rules
 */

(function () {
    'use strict';

    // ── State ─────────────────────────────────────────────────────────────────
    let _configs = [];
    let _editingId = null;     // null = new, string = editing existing

    // ── DOM helpers ───────────────────────────────────────────────────────────
    const $ = (id) => document.getElementById(id);

    function _authHeader() {
        const token = localStorage.getItem('tda_auth_token');
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }

    async function _api(method, path, body) {
        const opts = {
            method,
            headers: { ..._authHeader(), 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);
        const resp = await fetch(`/api/v1/auth${path}`, opts);
        return resp.json();
    }

    // ── Load & render list ────────────────────────────────────────────────────
    async function loadSsoConfigs() {
        const container = $('sso-list-container');
        if (!container) return;
        container.innerHTML = '<p style="color:var(--text-muted);font-size:0.875rem;">Loading…</p>';

        try {
            const data = await _api('GET', '/sso/configurations');
            _configs = data.configurations || [];
            _renderList(container);
        } catch (err) {
            container.innerHTML = `<p style="color:#f87171;font-size:0.875rem;">Error loading SSO configurations: ${err.message}</p>`;
        }
    }

    function _renderList(container) {
        if (_configs.length === 0) {
            container.innerHTML = `
                <div style="text-align:center;padding:2rem;color:var(--text-muted);font-size:0.875rem;">
                    No SSO providers configured.
                    Click <strong style="color:var(--text-primary)">Add Provider</strong> to set up OIDC single sign-on.
                </div>`;
            return;
        }

        container.innerHTML = _configs.map(cfg => `
            <div class="sso-config-card" style="
                background:var(--card-bg);border:1px solid var(--border-primary);
                border-radius:8px;padding:1rem 1.25rem;margin-bottom:0.75rem;
                display:flex;align-items:center;gap:1rem;
            ">
                <div style="flex:1;min-width:0;">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem;">
                        <span style="font-weight:600;color:var(--text-primary);font-size:0.9rem;">${_esc(cfg.name)}</span>
                        ${cfg.enabled
                            ? '<span style="font-size:0.7rem;padding:1px 6px;border-radius:9999px;background:rgba(74,222,128,0.15);color:#4ade80;border:1px solid rgba(74,222,128,0.3);">Enabled</span>'
                            : '<span style="font-size:0.7rem;padding:1px 6px;border-radius:9999px;background:rgba(148,163,184,0.15);color:var(--text-muted);border:1px solid var(--border-secondary);">Disabled</span>'
                        }
                    </div>
                    <div style="font-size:0.8rem;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                        ${_esc(cfg.issuer_url)}
                    </div>
                    <div style="font-size:0.75rem;color:var(--text-muted);margin-top:0.2rem;">
                        Client ID: <code style="font-family:monospace;font-size:0.75rem;">${_esc(cfg.client_id)}</code>
                        &nbsp;·&nbsp; Default tier: <strong>${_esc(cfg.default_tier)}</strong>
                    </div>
                </div>
                <div style="display:flex;gap:0.5rem;flex-shrink:0;">
                    <button onclick="window.adminSsoHandler.testConfig('${cfg.id}')"
                        style="padding:4px 10px;font-size:0.75rem;border-radius:6px;border:1px solid var(--border-primary);background:var(--card-bg);color:var(--text-muted);cursor:pointer;"
                        title="Test discovery endpoint">
                        Test
                    </button>
                    <button onclick="window.adminSsoHandler.editConfig('${cfg.id}')"
                        style="padding:4px 10px;font-size:0.75rem;border-radius:6px;border:1px solid var(--border-primary);background:var(--card-bg);color:var(--text-primary);cursor:pointer;">
                        Edit
                    </button>
                    <button onclick="window.adminSsoHandler.deleteConfig('${cfg.id}', '${_esc(cfg.name)}')"
                        style="padding:4px 10px;font-size:0.75rem;border-radius:6px;border:1px solid rgba(239,68,68,0.4);background:rgba(239,68,68,0.1);color:#f87171;cursor:pointer;">
                        Delete
                    </button>
                </div>
            </div>`
        ).join('');
    }

    // ── Add / Edit form ───────────────────────────────────────────────────────
    function openAddForm() {
        _editingId = null;
        _showForm({});
    }

    function editConfig(configId) {
        const cfg = _configs.find(c => c.id === configId);
        if (!cfg) return;
        _editingId = configId;
        _showForm(cfg);
    }

    function _showForm(cfg) {
        const modal = $('sso-form-modal');
        if (!modal) return;

        const scopes = Array.isArray(cfg.scopes) ? cfg.scopes.join(' ') : (cfg.scopes || 'openid profile email');
        const groupTierMap = cfg.group_tier_map && typeof cfg.group_tier_map === 'object'
            ? Object.entries(cfg.group_tier_map).map(([g, t]) => `${g}=${t}`).join('\n')
            : '';

        modal.innerHTML = `
            <div style="
                position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;
                display:flex;align-items:center;justify-content:center;padding:1rem;
            " onclick="if(event.target===this)window.adminSsoHandler.closeForm()">
                <div style="
                    background:var(--bg-overlay,#1e293b);border:1px solid var(--border-primary);
                    border-radius:12px;padding:1.5rem;width:100%;max-width:560px;max-height:90vh;
                    overflow-y:auto;
                ">
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.25rem;">
                        <h3 style="font-size:1rem;font-weight:700;color:var(--text-primary);margin:0;">
                            ${_editingId ? 'Edit SSO Provider' : 'Add SSO Provider'}
                        </h3>
                        <button onclick="window.adminSsoHandler.closeForm()"
                            style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:1.2rem;line-height:1;">
                            ✕
                        </button>
                    </div>

                    <form id="sso-config-form" onsubmit="window.adminSsoHandler.saveForm(event)">
                        ${_field('Name', 'sso-name', 'text', cfg.name || '', true,
                            'Friendly label shown on login button (e.g. "Okta Corp")')}
                        ${_field('Issuer URL', 'sso-issuer', 'url', cfg.issuer_url || '', true,
                            'Base URL of your IdP, e.g. https://your-tenant.okta.com')}
                        ${_field('Client ID', 'sso-client-id', 'text', cfg.client_id || '', true, '')}
                        ${_field('Client Secret', 'sso-client-secret', 'password', '', !_editingId,
                            _editingId ? 'Leave blank to keep existing secret' : '')}

                        <div style="margin-bottom:1rem;">
                            <label style="font-size:0.8rem;font-weight:600;color:var(--text-muted);display:block;margin-bottom:4px;">
                                Scopes
                            </label>
                            <input id="sso-scopes" type="text" value="${_esc(scopes)}"
                                style="${_inputStyle()}"
                                placeholder="openid profile email groups">
                            <p style="font-size:0.72rem;color:var(--text-muted);margin-top:3px;">Space-separated OIDC scopes.</p>
                        </div>

                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:1rem;">
                            ${_smallField('Email claim', 'sso-email-claim', cfg.email_claim || 'email')}
                            ${_smallField('Name claim', 'sso-name-claim', cfg.name_claim || 'name')}
                            ${_smallField('Groups claim', 'sso-groups-claim', cfg.groups_claim || '')}
                            ${_smallField('Subject claim', 'sso-sub-claim', cfg.sub_claim || 'sub')}
                        </div>

                        <div style="margin-bottom:1rem;">
                            <label style="font-size:0.8rem;font-weight:600;color:var(--text-muted);display:block;margin-bottom:4px;">
                                Group → Tier Mapping
                                <span style="font-weight:400;font-size:0.72rem;"> (one per line: GroupName=tier)</span>
                            </label>
                            <textarea id="sso-group-tier-map"
                                style="${_inputStyle()}height:80px;resize:vertical;font-family:monospace;font-size:0.8rem;"
                                placeholder="AdminGroup=admin&#10;DevGroup=developer">${_esc(groupTierMap)}</textarea>
                        </div>

                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:1rem;">
                            ${_smallField('Default tier', 'sso-default-tier', cfg.default_tier || 'user')}
                            ${_smallField('Button label (optional)', 'sso-button-label', cfg.button_label || '')}
                        </div>

                        <div style="display:flex;gap:1.5rem;margin-bottom:1rem;">
                            ${_checkbox('sso-enabled', 'Enabled', cfg.enabled !== false)}
                            ${_checkbox('sso-auto-provision', 'Auto-provision users', cfg.auto_provision_users !== false)}
                        </div>

                        <div style="display:flex;justify-content:flex-end;gap:0.75rem;margin-top:1.25rem;">
                            <button type="button" onclick="window.adminSsoHandler.closeForm()"
                                style="padding:6px 16px;border-radius:6px;border:1px solid var(--border-primary);background:var(--card-bg);color:var(--text-muted);cursor:pointer;font-size:0.85rem;">
                                Cancel
                            </button>
                            <button type="submit"
                                style="padding:6px 16px;border-radius:6px;border:none;background:var(--teradata-orange,#F15F22);color:#fff;cursor:pointer;font-size:0.85rem;font-weight:600;">
                                ${_editingId ? 'Update' : 'Create'}
                            </button>
                        </div>
                    </form>
                </div>
            </div>`;
        modal.classList.remove('hidden');
    }

    function closeForm() {
        const modal = $('sso-form-modal');
        if (modal) {
            modal.classList.add('hidden');
            modal.innerHTML = '';
        }
        _editingId = null;
    }

    async function saveForm(event) {
        event.preventDefault();

        const scopeStr = ($('sso-scopes')?.value || 'openid profile email').trim();
        const scopes = scopeStr.split(/\s+/).filter(Boolean);

        const groupTierRaw = $('sso-group-tier-map')?.value || '';
        const group_tier_map = {};
        groupTierRaw.split('\n').forEach(line => {
            const [g, t] = line.trim().split('=');
            if (g && t) group_tier_map[g.trim()] = t.trim();
        });

        const payload = {
            name: $('sso-name')?.value?.trim(),
            issuer_url: $('sso-issuer')?.value?.trim(),
            client_id: $('sso-client-id')?.value?.trim(),
            scopes,
            email_claim: $('sso-email-claim')?.value?.trim() || 'email',
            name_claim: $('sso-name-claim')?.value?.trim() || 'name',
            groups_claim: $('sso-groups-claim')?.value?.trim() || null,
            sub_claim: $('sso-sub-claim')?.value?.trim() || 'sub',
            group_tier_map: Object.keys(group_tier_map).length > 0 ? group_tier_map : null,
            default_tier: $('sso-default-tier')?.value?.trim() || 'user',
            button_label: $('sso-button-label')?.value?.trim() || null,
            enabled: $('sso-enabled')?.checked ?? true,
            auto_provision_users: $('sso-auto-provision')?.checked ?? true,
        };

        const secret = $('sso-client-secret')?.value?.trim();
        if (secret) payload.client_secret = secret;
        if (!_editingId) payload.client_secret = secret;  // required for create

        if (!payload.name || !payload.issuer_url || !payload.client_id) {
            _showError('Name, Issuer URL, and Client ID are required.');
            return;
        }
        if (!_editingId && !payload.client_secret) {
            _showError('Client Secret is required for new providers.');
            return;
        }

        const btn = document.querySelector('#sso-config-form button[type="submit"]');
        if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

        try {
            const method = _editingId ? 'PUT' : 'POST';
            const path = _editingId ? `/sso/configurations/${_editingId}` : '/sso/configurations';
            const data = await _api(method, path, payload);

            if (data.status === 'success') {
                closeForm();
                await loadSsoConfigs();
            } else {
                _showError(data.message || 'Save failed');
                if (btn) { btn.disabled = false; btn.textContent = _editingId ? 'Update' : 'Create'; }
            }
        } catch (err) {
            _showError(err.message);
            if (btn) { btn.disabled = false; btn.textContent = _editingId ? 'Update' : 'Create'; }
        }
    }

    // ── Test ──────────────────────────────────────────────────────────────────
    async function testConfig(configId) {
        const resultArea = $('sso-test-result') || _createTestResultArea();
        resultArea.style.display = 'block';
        resultArea.style.color = 'var(--text-muted)';
        resultArea.textContent = 'Testing discovery endpoint…';

        try {
            const data = await _api('POST', `/sso/configurations/${configId}/test`);
            if (data.success) {
                resultArea.style.color = '#4ade80';
                const eps = data.endpoints || {};
                resultArea.innerHTML = `
                    <strong>✓ Connected</strong><br>
                    Issuer: ${_esc(data.issuer || '')}<br>
                    Auth: ${_esc(eps.authorization_endpoint || '')}<br>
                    Token: ${_esc(eps.token_endpoint || '')}<br>
                    JWKS: ${_esc(eps.jwks_uri || '')}`;
            } else {
                resultArea.style.color = '#f87171';
                resultArea.textContent = `✗ ${data.error || 'Connection failed'}`;
            }
        } catch (err) {
            resultArea.style.color = '#f87171';
            resultArea.textContent = `✗ ${err.message}`;
        }

        setTimeout(() => { if (resultArea) resultArea.style.display = 'none'; }, 8000);
    }

    function _createTestResultArea() {
        const div = document.createElement('div');
        div.id = 'sso-test-result';
        div.style.cssText = `
            position:fixed;bottom:1.5rem;right:1.5rem;z-index:10000;
            background:var(--bg-overlay,#1e293b);border:1px solid var(--border-primary);
            border-radius:8px;padding:0.75rem 1rem;font-size:0.8rem;line-height:1.5;
            max-width:420px;box-shadow:0 4px 20px rgba(0,0,0,0.4);
        `;
        document.body.appendChild(div);
        return div;
    }

    // ── Delete ────────────────────────────────────────────────────────────────
    async function deleteConfig(configId, name) {
        if (!confirm(`Delete SSO provider "${name}"?\n\nUsers who signed in via this provider will still exist but can no longer use SSO login.`)) return;

        try {
            const data = await _api('DELETE', `/sso/configurations/${configId}`);
            if (data.status === 'success') {
                await loadSsoConfigs();
            } else {
                alert(`Delete failed: ${data.message}`);
            }
        } catch (err) {
            alert(`Error: ${err.message}`);
        }
    }

    // ── UI helpers ────────────────────────────────────────────────────────────
    function _inputStyle() {
        return `width:100%;padding:6px 10px;border-radius:6px;border:1px solid var(--border-primary);
                background:var(--card-bg);color:var(--text-primary);font-size:0.85rem;box-sizing:border-box;`;
    }

    function _field(label, id, type, value, required, hint) {
        return `
            <div style="margin-bottom:0.85rem;">
                <label for="${id}" style="font-size:0.8rem;font-weight:600;color:var(--text-muted);display:block;margin-bottom:4px;">
                    ${label}${required ? ' <span style="color:#f87171">*</span>' : ''}
                </label>
                <input id="${id}" type="${type}" value="${type === 'password' ? '' : _esc(value)}"
                    ${required ? 'required' : ''}
                    style="${_inputStyle()}">
                ${hint ? `<p style="font-size:0.72rem;color:var(--text-muted);margin-top:3px;">${hint}</p>` : ''}
            </div>`;
    }

    function _smallField(label, id, value) {
        return `
            <div>
                <label for="${id}" style="font-size:0.75rem;font-weight:600;color:var(--text-muted);display:block;margin-bottom:3px;">
                    ${label}
                </label>
                <input id="${id}" type="text" value="${_esc(value)}"
                    style="${_inputStyle()}padding:5px 8px;font-size:0.8rem;">
            </div>`;
    }

    function _checkbox(id, label, checked) {
        return `
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:0.82rem;color:var(--text-primary);">
                <input type="checkbox" id="${id}" ${checked ? 'checked' : ''}
                    style="width:14px;height:14px;accent-color:var(--teradata-orange,#F15F22);">
                ${label}
            </label>`;
    }

    function _esc(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _showError(msg) {
        alert(msg);
    }

    // ============================================================
    // SAML 2.0 — Phase 2
    // ============================================================

    let _samlConfigs = [];
    let _samlEditingId = null;

    async function loadSamlConfigs() {
        const container = $('saml-list-container');
        if (!container) return;
        container.innerHTML = '<p style="color:var(--text-muted);font-size:0.875rem;">Loading…</p>';
        try {
            const data = await _api('GET', '/saml/configurations');
            _samlConfigs = data.configurations || [];
            _renderSamlList(container);
        } catch (err) {
            container.innerHTML = `<p style="color:#f87171;font-size:0.875rem;">Error: ${err.message}</p>`;
        }
    }

    function _renderSamlList(container) {
        if (!_samlConfigs.length) {
            container.innerHTML = `
                <div style="text-align:center;padding:2rem;color:var(--text-muted);font-size:0.875rem;">
                    No SAML providers configured yet. Click <strong>Add SAML Provider</strong> to get started.
                </div>`;
            return;
        }
        container.innerHTML = _samlConfigs.map(cfg => `
            <div style="background:var(--card-bg);border:1px solid var(--border-primary);border-radius:8px;padding:1rem;margin-bottom:0.75rem;display:flex;align-items:center;gap:1rem;">
                <div style="flex:1;min-width:0;">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem;">
                        <span style="font-weight:600;color:var(--text-primary);">${_esc(cfg.name)}</span>
                        <span style="font-size:0.7rem;padding:2px 7px;border-radius:4px;background:rgba(59,130,246,0.15);color:#60a5fa;border:1px solid rgba(59,130,246,0.3);">SAML 2.0</span>
                        <span style="font-size:0.7rem;padding:2px 7px;border-radius:4px;${cfg.enabled ? 'background:rgba(74,222,128,0.1);color:#4ade80;border:1px solid rgba(74,222,128,0.3)' : 'background:rgba(239,68,68,0.1);color:#f87171;border:1px solid rgba(239,68,68,0.3)'}">${cfg.enabled ? 'Enabled' : 'Disabled'}</span>
                    </div>
                    <div style="font-size:0.78rem;color:var(--text-muted);">IdP: ${_esc(cfg.idp_entity_id)}</div>
                    <div style="font-size:0.78rem;color:var(--text-muted);">SP Entity: ${_esc(cfg.sp_entity_id)}</div>
                    <div style="font-size:0.75rem;color:var(--text-muted);margin-top:0.25rem;">
                        Button: "${_esc(cfg.button_label || cfg.name)}"
                        &nbsp;·&nbsp; Auto-provision: ${cfg.auto_provision_users ? 'Yes' : 'No'}
                    </div>
                </div>
                <div style="display:flex;gap:0.5rem;flex-shrink:0;">
                    <button onclick="window.adminSsoHandler.viewSamlMetadata('${cfg.id}')"
                        style="padding:0.35rem 0.75rem;font-size:0.78rem;border-radius:6px;border:1px solid var(--border-primary);background:transparent;color:var(--text-muted);cursor:pointer;">
                        Metadata
                    </button>
                    <button onclick="window.adminSsoHandler.editSamlConfig('${cfg.id}')"
                        style="padding:0.35rem 0.75rem;font-size:0.78rem;border-radius:6px;border:1px solid var(--border-primary);background:transparent;color:var(--text-primary);cursor:pointer;">
                        Edit
                    </button>
                    <button onclick="window.adminSsoHandler.deleteSamlConfig('${cfg.id}','${_esc(cfg.name)}')"
                        style="padding:0.35rem 0.75rem;font-size:0.78rem;border-radius:6px;border:1px solid rgba(239,68,68,0.4);background:transparent;color:#f87171;cursor:pointer;">
                        Delete
                    </button>
                </div>
            </div>`).join('');
    }

    async function openAddSamlForm() {
        _samlEditingId = null;
        _showSamlForm(null);
    }

    async function editSamlConfig(id) {
        const cfg = _samlConfigs.find(c => c.id === id);
        if (cfg) { _samlEditingId = id; _showSamlForm(cfg); }
    }

    function _showSamlForm(cfg) {
        const modal = $('saml-form-modal');
        if (!modal) return;
        const isEdit = !!cfg;
        modal.innerHTML = `
            <div style="position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:1000;display:flex;align-items:center;justify-content:center;padding:1rem;">
                <div style="background:var(--bg-overlay,#1e2028);border:1px solid var(--border-primary);border-radius:12px;padding:1.5rem;width:100%;max-width:660px;max-height:90vh;overflow-y:auto;">
                    <h3 style="margin:0 0 1.25rem;color:var(--text-primary);font-size:1.1rem;">${isEdit ? 'Edit' : 'Add'} SAML Provider</h3>
                    <form id="saml-config-form" onsubmit="window.adminSsoHandler.saveSamlForm(event)">
                        ${_samlField('name','Provider Name','text',cfg?.name||'',true,'e.g. Corporate ADFS')}
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
                            ${_samlField('sp_entity_id','SP Entity ID','text',cfg?.sp_entity_id||'',true,'https://uderia.example.com')}
                            ${_samlField('sp_acs_url','ACS URL Override','text',cfg?.sp_acs_url||'',false,'Leave empty to auto-compute')}
                        </div>
                        <div style="border-top:1px solid var(--border-secondary);margin:1rem 0;padding-top:1rem;">
                            <div style="font-size:0.8rem;font-weight:600;color:var(--text-muted);margin-bottom:0.75rem;">IDENTITY PROVIDER SETTINGS</div>
                            ${_samlField('idp_entity_id','IdP Entity ID','text',cfg?.idp_entity_id||'',true,'https://sts.windows.net/tenant-id/')}
                            ${_samlField('idp_sso_url','IdP SSO URL','text',cfg?.idp_sso_url||'',true,'https://login.microsoftonline.com/…/saml2')}
                            ${_samlField('idp_slo_url','IdP SLO URL (optional)','text',cfg?.idp_slo_url||'',false,'')}
                            <div style="margin-bottom:1rem;">
                                <label style="display:block;font-size:0.82rem;color:var(--text-muted);margin-bottom:0.35rem;">IdP Signing Certificate (PEM) <span style="color:#f87171;">*</span></label>
                                <textarea name="idp_certificate" rows="5" required
                                    placeholder="-----BEGIN CERTIFICATE-----&#10;MIIBIj…&#10;-----END CERTIFICATE-----"
                                    style="width:100%;background:var(--card-bg);border:1px solid var(--border-primary);border-radius:6px;padding:0.5rem;color:var(--text-primary);font-family:monospace;font-size:0.75rem;resize:vertical;">${_esc(cfg?.idp_certificate||'')}</textarea>
                            </div>
                        </div>
                        <div style="border-top:1px solid var(--border-secondary);margin:1rem 0;padding-top:1rem;">
                            <div style="font-size:0.8rem;font-weight:600;color:var(--text-muted);margin-bottom:0.75rem;">ATTRIBUTE MAPPING</div>
                            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.75rem;">
                                ${_samlField('email_attr','Email Attribute','text',cfg?.email_attr||'email',false,'email')}
                                ${_samlField('name_attr','Name Attribute','text',cfg?.name_attr||'displayName',false,'displayName')}
                                ${_samlField('groups_attr','Groups Attribute','text',cfg?.groups_attr||'',false,'groups')}
                            </div>
                        </div>
                        <div style="border-top:1px solid var(--border-secondary);margin:1rem 0;padding-top:1rem;">
                            <div style="font-size:0.8rem;font-weight:600;color:var(--text-muted);margin-bottom:0.75rem;">USER PROVISIONING</div>
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
                                <div>
                                    <label style="display:block;font-size:0.82rem;color:var(--text-muted);margin-bottom:0.35rem;">Default Tier</label>
                                    <select name="default_tier" style="width:100%;background:var(--card-bg);border:1px solid var(--border-primary);border-radius:6px;padding:0.45rem 0.5rem;color:var(--text-primary);">
                                        ${['user','developer','admin'].map(t => `<option value="${t}" ${(cfg?.default_tier||'user')===t?'selected':''}>${t.charAt(0).toUpperCase()+t.slice(1)}</option>`).join('')}
                                    </select>
                                </div>
                                ${_samlField('button_label','Login Button Label','text',cfg?.button_label||'',false,'Sign in with ADFS')}
                            </div>
                            <div style="margin-top:0.75rem;">
                                <label style="display:block;font-size:0.82rem;color:var(--text-muted);margin-bottom:0.35rem;">Group → Tier Mapping (one per line: GroupName=tier)</label>
                                <textarea name="group_tier_map_raw" rows="3"
                                    placeholder="Admins=admin&#10;Developers=developer"
                                    style="width:100%;background:var(--card-bg);border:1px solid var(--border-primary);border-radius:6px;padding:0.5rem;color:var(--text-primary);font-family:monospace;font-size:0.82rem;resize:vertical;">${_groupTierToText(cfg?.group_tier_map)}</textarea>
                            </div>
                            <div style="display:flex;gap:1.5rem;margin-top:0.75rem;">
                                <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;font-size:0.85rem;color:var(--text-primary);">
                                    <input type="checkbox" name="enabled" ${(cfg?.enabled!==false)?'checked':''}>
                                    Provider enabled
                                </label>
                                <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;font-size:0.85rem;color:var(--text-primary);">
                                    <input type="checkbox" name="auto_provision_users" ${(cfg?.auto_provision_users!==false)?'checked':''}>
                                    Auto-provision new users
                                </label>
                            </div>
                        </div>
                        <div style="display:flex;gap:0.75rem;justify-content:flex-end;margin-top:1.25rem;">
                            <button type="button" onclick="window.adminSsoHandler.closeSamlForm()"
                                style="padding:0.5rem 1.25rem;border-radius:6px;border:1px solid var(--border-primary);background:transparent;color:var(--text-muted);cursor:pointer;">
                                Cancel
                            </button>
                            <button type="submit"
                                style="padding:0.5rem 1.25rem;border-radius:6px;border:none;background:var(--teradata-orange,#F15F22);color:#fff;cursor:pointer;font-weight:600;">
                                ${isEdit ? 'Save Changes' : 'Add Provider'}
                            </button>
                        </div>
                    </form>
                </div>
            </div>`;
        modal.classList.remove('hidden');
    }

    function _samlField(name, label, type, value, required, placeholder) {
        return `
            <div style="margin-bottom:1rem;">
                <label style="display:block;font-size:0.82rem;color:var(--text-muted);margin-bottom:0.35rem;">${label}${required?' <span style="color:#f87171;">*</span>':''}</label>
                <input type="${type}" name="${name}" value="${_esc(value)}" ${required?'required':''} placeholder="${_esc(placeholder)}"
                    style="width:100%;background:var(--card-bg);border:1px solid var(--border-primary);border-radius:6px;padding:0.45rem 0.6rem;color:var(--text-primary);">
            </div>`;
    }

    function closeSamlForm() {
        const modal = $('saml-form-modal');
        if (modal) { modal.classList.add('hidden'); modal.innerHTML = ''; }
    }

    async function saveSamlForm(event) {
        event.preventDefault();
        const form = event.target;
        const fd = new FormData(form);
        const groupTierRaw = (fd.get('group_tier_map_raw') || '').trim();
        const groupTierMap = {};
        for (const line of groupTierRaw.split('\n')) {
            const [k, v] = line.split('=');
            if (k && v) groupTierMap[k.trim()] = v.trim();
        }
        const payload = {
            name: fd.get('name'),
            sp_entity_id: fd.get('sp_entity_id'),
            sp_acs_url: fd.get('sp_acs_url') || null,
            idp_entity_id: fd.get('idp_entity_id'),
            idp_sso_url: fd.get('idp_sso_url'),
            idp_slo_url: fd.get('idp_slo_url') || null,
            idp_certificate: fd.get('idp_certificate'),
            email_attr: fd.get('email_attr') || 'email',
            name_attr: fd.get('name_attr') || 'displayName',
            groups_attr: fd.get('groups_attr') || null,
            default_tier: fd.get('default_tier') || 'user',
            button_label: fd.get('button_label') || null,
            group_tier_map: Object.keys(groupTierMap).length ? groupTierMap : null,
            enabled: form.querySelector('[name=enabled]').checked,
            auto_provision_users: form.querySelector('[name=auto_provision_users]').checked,
        };
        try {
            const path = _samlEditingId ? `/saml/configurations/${_samlEditingId}` : '/saml/configurations';
            const method = _samlEditingId ? 'PUT' : 'POST';
            const data = await _api(method, path, payload);
            if (data.status === 'success') {
                closeSamlForm();
                loadSamlConfigs();
            } else {
                _showError(data.message || 'Save failed');
            }
        } catch (err) {
            _showError('Save failed: ' + err.message);
        }
    }

    async function deleteSamlConfig(id, name) {
        if (!confirm(`Delete SAML provider "${name}"? This cannot be undone.`)) return;
        try {
            await _api('DELETE', `/saml/configurations/${id}`);
            loadSamlConfigs();
        } catch (err) {
            _showError('Delete failed: ' + err.message);
        }
    }

    function viewSamlMetadata(id) {
        const url = `/api/v1/auth/saml/${id}/metadata`;
        window.open(url, '_blank');
    }

    // ============================================================
    // Phase 3 — SSO Users & Group Sync
    // ============================================================

    async function loadSsoUsers() {
        const container = $('sso-users-container');
        if (!container) return;
        container.innerHTML = '<p style="color:var(--text-muted);font-size:0.875rem;">Loading…</p>';
        try {
            const data = await _api('GET', '/sso/users');
            const users = data.users || [];
            if (!users.length) {
                container.innerHTML = '<p style="color:var(--text-muted);font-size:0.875rem;">No SSO-provisioned users yet.</p>';
                return;
            }
            container.innerHTML = `
                <table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
                    <thead>
                        <tr style="border-bottom:1px solid var(--border-primary);color:var(--text-muted);">
                            <th style="text-align:left;padding:0.5rem 0.75rem;">User</th>
                            <th style="text-align:left;padding:0.5rem 0.75rem;">Provider</th>
                            <th style="text-align:left;padding:0.5rem 0.75rem;">Tier</th>
                            <th style="text-align:left;padding:0.5rem 0.75rem;">Groups</th>
                            <th style="text-align:left;padding:0.5rem 0.75rem;">Last Login</th>
                            <th style="padding:0.5rem 0.75rem;"></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${users.map(u => `
                        <tr style="border-bottom:1px solid var(--border-secondary);">
                            <td style="padding:0.5rem 0.75rem;color:var(--text-primary);">
                                <div>${_esc(u.username)}</div>
                                <div style="color:var(--text-muted);font-size:0.75rem;">${_esc(u.email||'')}</div>
                            </td>
                            <td style="padding:0.5rem 0.75rem;">
                                <span style="font-size:0.7rem;padding:2px 7px;border-radius:4px;${u.auth_method==='saml'?'background:rgba(59,130,246,0.15);color:#60a5fa':'background:rgba(168,85,247,0.15);color:#c084fc'};">
                                    ${(u.auth_method||'oidc').toUpperCase()}
                                </span>
                            </td>
                            <td style="padding:0.5rem 0.75rem;color:var(--text-primary);">${_esc(u.profile_tier||'user')}</td>
                            <td style="padding:0.5rem 0.75rem;color:var(--text-muted);">${(u.sso_groups||[]).map(g=>`<span style="font-size:0.72rem;padding:1px 5px;border-radius:3px;background:rgba(255,255,255,0.06);margin-right:3px;">${_esc(g)}</span>`).join('')||'—'}</td>
                            <td style="padding:0.5rem 0.75rem;color:var(--text-muted);font-size:0.75rem;">${u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : '—'}</td>
                            <td style="padding:0.5rem 0.75rem;">
                                <button onclick="window.adminSsoHandler.syncUser('${u.id}','${_esc(u.username)}')"
                                    style="padding:0.25rem 0.6rem;font-size:0.75rem;border-radius:4px;border:1px solid var(--border-primary);background:transparent;color:var(--text-muted);cursor:pointer;">
                                    Sync
                                </button>
                            </td>
                        </tr>`).join('')}
                    </tbody>
                </table>`;
        } catch (err) {
            container.innerHTML = `<p style="color:#f87171;font-size:0.875rem;">Error: ${err.message}</p>`;
        }
    }

    async function syncUser(userId, username) {
        try {
            const data = await _api('POST', `/sso/users/${userId}/sync`);
            const msg = data.changed
                ? `Synced "${username}": tier changed ${data.old_tier} → ${data.new_tier}`
                : `Synced "${username}": no changes (tier remains ${data.new_tier})`;
            alert(msg);
            loadSsoUsers();
        } catch (err) {
            _showError('Sync failed: ' + err.message);
        }
    }

    // ── Public API ────────────────────────────────────────────────────────────
    window.adminSsoHandler = {
        // Phase 1 — OIDC
        loadSsoConfigs,
        openAddForm,
        editConfig,
        closeForm,
        saveForm,
        testConfig,
        deleteConfig,
        // Phase 2 — SAML
        loadSamlConfigs,
        openAddSamlForm,
        editSamlConfig,
        closeSamlForm,
        saveSamlForm,
        deleteSamlConfig,
        viewSamlMetadata,
        // Phase 3 — Group sync
        loadSsoUsers,
        syncUser,
    };
})();
