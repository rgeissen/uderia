-- ============================================================================
-- SSO / OIDC Configuration Tables (Phase 1 — Generic OIDC)
-- ============================================================================
-- Stores admin-configured Identity Provider settings.
-- Per-user token data uses the existing messaging_identities table.
-- ============================================================================

-- Admin-configured OIDC providers
CREATE TABLE IF NOT EXISTS sso_configurations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,               -- display name, e.g. "Okta (Corp)"
    provider    TEXT NOT NULL DEFAULT 'oidc',-- 'oidc', 'saml' (future)
    issuer_url  TEXT NOT NULL,               -- https://accounts.google.com
    client_id   TEXT NOT NULL,
    client_secret TEXT NOT NULL,             -- Fernet-encrypted
    -- Discovery document cache
    discovery_doc       TEXT,                -- JSON cached from /.well-known/openid-configuration
    discovery_cached_at TEXT,                -- ISO timestamp
    -- Scopes + claims
    scopes          TEXT NOT NULL DEFAULT '["openid","profile","email"]',  -- JSON array
    -- Claims mapping: which JWT claim holds email/name/groups/sub
    email_claim     TEXT NOT NULL DEFAULT 'email',
    name_claim      TEXT NOT NULL DEFAULT 'name',
    groups_claim    TEXT,                    -- e.g. "groups" — maps to tier via group_tier_map
    sub_claim       TEXT NOT NULL DEFAULT 'sub',
    -- Group → tier mapping: JSON object {"AdminGroup": "admin", "DevGroup": "developer"}
    group_tier_map  TEXT,
    default_tier    TEXT NOT NULL DEFAULT 'user',   -- tier when no group matches
    -- Governance
    enabled                     INTEGER NOT NULL DEFAULT 1,
    auto_provision_users        INTEGER NOT NULL DEFAULT 1,  -- create user on first login
    require_email_verification  INTEGER NOT NULL DEFAULT 0,  -- skip if IdP verifies
    display_order               INTEGER NOT NULL DEFAULT 0,
    -- UI
    button_label    TEXT,                    -- "Sign in with Okta" — overrides default
    icon_url        TEXT,                    -- URL for IdP logo (optional)
    -- Timestamps
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sso_configurations_enabled ON sso_configurations(enabled);

-- Per-session logout tokens (for back-channel logout / token revocation)
CREATE TABLE IF NOT EXISTS sso_sessions (
    id              TEXT PRIMARY KEY,
    user_uuid       TEXT NOT NULL,
    sso_config_id   TEXT NOT NULL REFERENCES sso_configurations(id) ON DELETE CASCADE,
    id_token_hash   TEXT NOT NULL,   -- SHA-256 of id_token for revocation lookup
    sid             TEXT,            -- IdP session ID (from id_token claims)
    sub             TEXT NOT NULL,   -- IdP subject identifier
    issued_at       TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at      TEXT,
    revoked         INTEGER NOT NULL DEFAULT 0,
    revoked_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_sso_sessions_user ON sso_sessions(user_uuid);
CREATE INDEX IF NOT EXISTS idx_sso_sessions_id_token ON sso_sessions(id_token_hash);
CREATE INDEX IF NOT EXISTS idx_sso_sessions_sid ON sso_sessions(sid);
