-- Rename platform connector tables and add connector_type discriminator.
-- "mcp" was the first (and currently only) connector type; the abstraction is
-- now generic so the table names no longer encode a specific protocol.
--
-- connector_type values:
--   mcp_stdio   MCP protocol via subprocess stdin/stdout (default — all existing rows)
--   mcp_http    MCP protocol via HTTP/SSE transport endpoint
--   rest        Direct REST API calls (no MCP protocol)
--   oauth_only  Authentication only — no tool execution
--
-- SQLite automatically updates FK constraint text when a table is renamed
-- (version 3.26+, which ships with macOS 12+ and Python 3.9+).

ALTER TABLE mcp_registry_sources          RENAME TO connector_registry_sources;
ALTER TABLE platform_mcp_servers          RENAME TO platform_connectors;
ALTER TABLE profile_platform_mcp_settings RENAME TO profile_connector_settings;

-- Add connector_type to platform_connectors; default 'mcp_stdio' for all
-- existing rows so nothing breaks without a data-migration step.
ALTER TABLE platform_connectors ADD COLUMN connector_type TEXT NOT NULL DEFAULT 'mcp_stdio';
