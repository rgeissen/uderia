-- SAML 2.0 configurations (SSO Phase 2)
-- Each row represents one configured SAML Identity Provider.
CREATE TABLE IF NOT EXISTS saml_configurations (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,

    -- SP (Service Provider) identity — who we are
    sp_entity_id         TEXT NOT NULL,           -- e.g. https://uderia.example.com
    sp_acs_url           TEXT,                    -- override auto-computed ACS URL
    sp_private_key       TEXT,                    -- Fernet-encrypted PEM (for signed requests)
    sp_certificate       TEXT,                    -- PEM public cert (share with IdP)

    -- IdP (Identity Provider) settings — who they are
    idp_entity_id        TEXT NOT NULL,           -- IdP entity ID from their metadata
    idp_sso_url          TEXT NOT NULL,           -- IdP SSO redirect binding URL
    idp_slo_url          TEXT,                    -- IdP SLO URL (optional)
    idp_certificate      TEXT NOT NULL,           -- IdP X.509 signing cert PEM

    -- Attribute → field mapping
    email_attr           TEXT DEFAULT 'email',    -- SAML attribute name for email
    name_attr            TEXT DEFAULT 'displayName',
    groups_attr          TEXT,                    -- SAML attribute name for group membership

    -- User provisioning
    default_tier         TEXT DEFAULT 'user',
    group_tier_map       TEXT,                    -- JSON: {"GroupName": "admin"}
    auto_provision_users INTEGER DEFAULT 1,

    -- UI
    enabled              INTEGER DEFAULT 1,
    button_label         TEXT,
    icon_url             TEXT,
    display_order        INTEGER DEFAULT 0,
    created_at           TEXT,
    updated_at           TEXT
);

-- SSO group-sync audit log (SSO Phase 3)
-- Records every tier/group change triggered by an SSO login.
CREATE TABLE IF NOT EXISTS sso_sync_events (
    id          TEXT PRIMARY KEY,
    user_uuid   TEXT NOT NULL,
    config_id   TEXT,                -- NULL for manual admin syncs
    config_type TEXT,                -- 'oidc' | 'saml'
    sync_type   TEXT NOT NULL,       -- 'login' | 'manual'
    old_tier    TEXT,
    new_tier    TEXT,
    old_groups  TEXT,                -- JSON array
    new_groups  TEXT,                -- JSON array
    changed     INTEGER DEFAULT 0,  -- 1 if tier or groups actually changed
    synced_at   TEXT DEFAULT (datetime('now'))
);
