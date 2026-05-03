-- Platform Connector Registry
-- Separates admin-governed capability servers (browser, files, shell, web, google)
-- from user-configured data source servers (Configuration → MCP Servers).
-- These two namespaces are strictly separate and never share a UI surface.

-- Registry sources: Uderia built-in, official MCP Registry, enterprise private
CREATE TABLE IF NOT EXISTS connector_registry_sources (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    url        TEXT NOT NULL,        -- registry API base URL (GET /v0.1/servers)
    enabled    INTEGER DEFAULT 1,
    is_builtin INTEGER DEFAULT 0,    -- built-in sources cannot be deleted
    created_at TEXT DEFAULT (datetime('now'))
);

-- Platform connectors installed or connected by admin + governance settings
CREATE TABLE IF NOT EXISTS platform_connectors (
    id                       TEXT PRIMARY KEY,
    source_id                TEXT NOT NULL REFERENCES connector_registry_sources(id),
    name                     TEXT NOT NULL,
    display_name             TEXT,
    description              TEXT,
    version                  TEXT NOT NULL DEFAULT '0.0.0',
    registry_metadata        TEXT,              -- full JSON from registry API
    install_spec             TEXT,              -- JSON: transport, command, args, env
    install_status           TEXT DEFAULT 'not_installed',  -- not_installed | installing | installed | unavailable | error
    connector_type           TEXT NOT NULL DEFAULT 'mcp_stdio',  -- mcp_stdio | mcp_http | rest | oauth_only
    enabled                  INTEGER DEFAULT 0, -- admin master switch
    config                   TEXT,              -- JSON: non-sensitive config values
    credentials              TEXT,              -- Fernet-encrypted JSON, sensitive values
    available_tools          TEXT,              -- JSON array of permitted tool names; NULL = all tools
    auto_opt_in              INTEGER DEFAULT 0, -- 1 = active on all profiles by default
    user_can_opt_out         INTEGER DEFAULT 1, -- 1 = user may disable on their profiles
    user_can_configure_tools INTEGER DEFAULT 0, -- 1 = user may select individual tools per profile
    requires_user_auth       INTEGER DEFAULT 0, -- 1 = needs per-user OAuth (e.g. uderia-google)
    created_at               TEXT DEFAULT (datetime('now')),
    updated_at               TEXT DEFAULT (datetime('now'))
);

-- Per-profile user preferences, within admin-permitted bounds
CREATE TABLE IF NOT EXISTS profile_connector_settings (
    profile_id  TEXT NOT NULL,
    server_id   TEXT NOT NULL REFERENCES platform_connectors(id) ON DELETE CASCADE,
    opted_in    INTEGER,   -- NULL = follow auto_opt_in; 1 = explicit opt-in; 0 = explicit opt-out
    user_tools  TEXT,      -- JSON array of tool names; NULL = use all available_tools
    updated_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (profile_id, server_id)
);

-- Seed: built-in registry source (always present, cannot be deleted)
INSERT OR IGNORE INTO connector_registry_sources (id, name, url, enabled, is_builtin)
VALUES ('builtin', 'Uderia Built-in', 'builtin://', 1, 1);
