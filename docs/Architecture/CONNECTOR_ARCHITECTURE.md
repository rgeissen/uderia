# Connector Architecture

## Table of Contents

1. [Overview and Purpose](#1-overview-and-purpose)
2. [Namespace Separation: Connectors vs User MCP Data Sources](#2-namespace-separation-connectors-vs-user-mcp-data-sources)
3. [Connector Categories: Platform vs User Connectors](#3-connector-categories-platform-vs-user-connectors)
4. [Connector Type System and Invocation Strategy Pattern](#4-connector-type-system-and-invocation-strategy-pattern)
5. [Three-Layer Governance Model](#5-three-layer-governance-model)
6. [Database Schema](#6-database-schema)
7. [Tool Injection Pipeline](#7-tool-injection-pipeline)
8. [Tool Invocation Pipeline](#8-tool-invocation-pipeline)
9. [OAuth Connector Module Interface](#9-oauth-connector-module-interface)
10. [REST API Reference](#10-rest-api-reference)
11. [UI Surfaces](#11-ui-surfaces)
12. [How to Add a New Connector Type](#12-how-to-add-a-new-connector-type)
13. [How to Add a New Connector Instance](#13-how-to-add-a-new-connector-instance)
14. [Security Model](#14-security-model)
15. [File Reference Map](#15-file-reference-map)

---

## 1. Overview and Purpose

The Connector subsystem provides **admin-governed, platform-managed capability tools** that augment the LLM agent with autonomous execution capabilities: web search, file access, browser automation, shell execution, and third-party SaaS integrations (Google Workspace, etc.).

Connectors are the mechanism by which Uderia closes the autonomous execution gap relative to open-source agent frameworks like OpenClaw. They differ fundamentally from the existing user MCP data source servers in purpose, ownership, governance model, and UI surface — these two namespaces must never be conflated (see §2).

### What connectors provide

| Connector | Capabilities |
|---|---|
| `uderia-web` | Web search, fetch, content extraction |
| `uderia-files` | Read/write filesystem within an admin-configured allowlist |
| `uderia-browser` | Playwright-based browser automation, screenshots, form fill |
| `uderia-google` | Gmail read/send, Calendar list/create, per-user OAuth |
| `uderia-shell` | Command execution inside Docker-isolated containers (requires Docker) |

### System-level positioning

```
Admin Layer          governs platform connectors (install, enable, policy, credentials)
      ↓
Connector Registry   resolves which tools are active for each profile
      ↓
Adapter Layer        merges connector tools into APP_STATE at load time
      ↓
Invocation Layer     routes tool calls to the correct connector process/endpoint
      ↓
Connector Process    executes tool (subprocess, HTTP, or custom transport)
```

---

## 2. Namespace Separation: Connectors vs User MCP Data Sources

This separation is **architectural, permanent, and non-negotiable**.

| Dimension | User MCP Data Sources | Platform Connectors |
|---|---|---|
| Examples | Teradata, Postgres, custom databases | Browser, files, shell, web, Google |
| Purpose | Connect the agent to the user's **data** | Give the agent **autonomous action** capability |
| Who configures | User (freely, per their own data connection) | Admin (installs once, governs for all users) |
| Who assigns | User (one server per profile, data-source slot) | User (N connectors per profile, capability slot) |
| UI surface | Configuration panel → MCP Servers tab | Platform Components panel → Connectors tab |
| Governance | User-controlled | Admin-governed (tools, opt-in policy, credentials) |
| Profile binding | One per profile (data source slot) | Many per profile (additive capability slot) |
| Appear in each other's UI? | **No** | **No** |
| RAG collection auto-created on add? | Yes | No |
| Cascade-archived sessions on delete? | Yes | No |
| DB table | `user_mcp_servers` (in `user_preferences` JSON) | `platform_connectors` |
| Code module | `mcp_adapter/adapter.py` | `core/platform_connector_registry.py` |

Connectors **never appear** in the Configuration panel's MCP Servers tab. User MCP servers **never appear** in the Platform Components panel's Connectors tab.

---

## 3. Connector Categories: Platform vs User Connectors

Within the connector subsystem, there are two sub-categories controlled by the `requires_user_auth` field on each connector record:

### 3.1 Platform Connectors (`requires_user_auth = 0`)

Admin configures credentials once; the connector serves all authorised users with those shared credentials.

**Examples:** `uderia-web` (Brave API key), `uderia-files` (path allowlist), `uderia-browser` (no credentials), `uderia-shell` (Docker config).

Credential flow:
```
Admin stores credentials → encrypted in platform_connectors.credentials
                        → decrypted at invocation time → injected into subprocess env
```

### 3.2 User Connectors (`requires_user_auth = 1`)

Admin configures the **application credentials** (OAuth `client_id`/`client_secret`); each user independently connects their own account via OAuth.

**Example:** `uderia-google` (Gmail + Calendar).

Credential flow:
```
Admin sets client_id + client_secret → stored in platform_connectors.credentials (encrypted)
User clicks "Connect {Platform} account" → OAuth popup flow
Provider redirects to /api/v1/connectors/{platform}/callback
Code exchanged for access_token + refresh_token → stored in messaging_identities (encrypted)
At invocation time: admin creds + user tokens both injected into subprocess env
```

The two flows are composed in `invoke_connector_tool()`:
1. Admin credentials always loaded from `platform_connectors.credentials`
2. User tokens additionally injected when `requires_user_auth = 1` via `_inject_user_tokens()`

---

## 4. Connector Type System and Invocation Strategy Pattern

Each connector record carries a `connector_type` discriminator field that determines how tool calls are executed. The implementation uses the **Strategy pattern** so adding a new transport type requires zero changes to caller code.

### 4.1 Defined Types

| `connector_type` | Transport | Status |
|---|---|---|
| `mcp_stdio` | MCP wire protocol over subprocess stdin/stdout | Implemented |
| `mcp_http` | MCP protocol via HTTP/SSE endpoint | Stub (raises `NotImplementedError`) |
| `rest` | Direct HTTP calls to a REST API (no MCP) | Future |
| `oauth_only` | Auth only — no tool execution | Future |

All existing connectors default to `mcp_stdio`. The migration script (`29_rename_platform_connectors.sql`) sets `DEFAULT 'mcp_stdio'` so all pre-existing rows retain full functionality.

### 4.2 Strategy Pattern

```python
# core/platform_connector_registry.py

class ConnectorInvocationStrategy:
    async def invoke_tool(self, server: dict, tool_name: str,
                          args: dict, env: dict) -> dict:
        raise NotImplementedError

class McpStdioStrategy(ConnectorInvocationStrategy):
    async def invoke_tool(self, server, tool_name, args, env) -> dict:
        # spawns subprocess → sends MCP initialize + tools/call over stdio
        # → parses JSON-RPC response → returns result dict

class McpHttpStrategy(ConnectorInvocationStrategy):
    async def invoke_tool(self, server, tool_name, args, env) -> dict:
        raise NotImplementedError("MCP HTTP transport not yet implemented.")

_INVOCATION_STRATEGIES: dict[str, ConnectorInvocationStrategy] = {
    CONNECTOR_TYPE_MCP_STDIO: McpStdioStrategy(),
    CONNECTOR_TYPE_MCP_HTTP:  McpHttpStrategy(),
}
```

Dispatch in `invoke_connector_tool()`:
```python
connector_type = server.get("connector_type") or CONNECTOR_TYPE_MCP_STDIO
strategy = _INVOCATION_STRATEGIES.get(connector_type)
if strategy is None:
    return {"status": "error", "error": f"Unknown connector type '{connector_type}'"}
return await asyncio.wait_for(
    strategy.invoke_tool(server, tool_name, args, env),
    timeout=_INVOKE_TIMEOUT,  # 30 seconds
)
```

### 4.3 MCP stdio Wire Protocol

The `McpStdioStrategy` sends three JSON-RPC messages to the subprocess stdin and reads the response from stdout:

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize",...}
→ {"jsonrpc":"2.0","method":"notifications/initialized"}
→ {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"...","arguments":{...}}}

← (skips id:1 initialize response)
← {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"..."}]}}
```

The subprocess is killed immediately after the response is received — connectors are stateless and spawned fresh per tool call.

---

## 5. Three-Layer Governance Model

Platform connectors are governed by a strict three-layer hierarchy. Each layer operates only within bounds set by the layer above.

```
Layer 1: Admin
  ├── Installs connector (from registry or remote URL)
  ├── Master enable/disable toggle
  ├── available_tools: permitted tool names (subset or NULL = all)
  ├── auto_opt_in: active on all profiles by default
  ├── user_can_opt_out: whether users may disable an auto-opted-in connector
  ├── user_can_configure_tools: whether users may select individual tools
  └── Credentials: encrypted per-connector (admin sets, never exposed)

Layer 2: User Assignment (Platform Components → Connectors tab)
  ├── Coarse on/off toggle per profile for each admin-enabled connector
  ├── Respects auto_opt_in + user_can_opt_out (lock icon if opt-out not allowed)
  └── No tool-level configuration at this layer

Layer 3: Profile Configuration (Profile Edit → Connectors section)
  ├── Fine-grained tool checklist per connector
  ├── Only shown when user_can_configure_tools = true
  └── Tool choices intersected with admin available_tools (user cannot exceed admin set)
```

### 5.1 Effective Tool Resolution

`get_effective_tools(profile_id)` applies the full governance chain at execution time:

```python
for each enabled platform connector:
    if auto_opt_in:
        active = True
        if user_can_opt_out and profile_setting.opted_in == 0:
            active = False
    else:
        active = (profile_setting.opted_in == 1)

    if not active: skip

    permitted = available_tools  # admin set (None = all)
    if user_can_configure_tools and profile_setting.user_tools:
        permitted = intersection(permitted, profile_setting.user_tools)

    yield tools filtered to permitted set
```

Platform connector tools bypass the `profile.tools[]` filter (the same exception mechanism used for `TDA_*` internal tools), because they have their own governance chain independent of the primary MCP server's tool list.

---

## 6. Database Schema

Four tables form the connector subsystem. See `schema/27_platform_mcp_servers.sql` (creation) and `schema/29_rename_platform_connectors.sql` (rename + `connector_type` addition).

### 6.1 `connector_registry_sources`

Registry endpoints from which connectors can be discovered and installed.

```sql
CREATE TABLE connector_registry_sources (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,        -- "Uderia Built-in", "Official MCP Registry", etc.
    url        TEXT NOT NULL,        -- registry API base URL (GET /v0.1/servers)
    enabled    INTEGER DEFAULT 1,
    is_builtin INTEGER DEFAULT 0,    -- built-in sources cannot be deleted
    created_at TEXT DEFAULT (datetime('now'))
);

-- Seed: always present
INSERT OR IGNORE INTO connector_registry_sources (id, name, url, enabled, is_builtin)
VALUES ('builtin', 'Uderia Built-in', 'builtin://', 1, 1);
```

Three source types are supported:

| Source | URL | Managed by |
|---|---|---|
| Uderia built-in | `builtin://` (local) | Platform (first-party connectors) |
| Official MCP Registry | `registry.modelcontextprotocol.io` | Anthropic / community |
| Enterprise private | `mcp.yourcompany.com` (admin-added) | Customer IT |

All three expose the same `GET /v0.1/servers` endpoint (MCP Registry v0.1 API).

### 6.2 `platform_connectors`

The central table — one row per installed or connected connector.

```sql
CREATE TABLE platform_connectors (
    id                       TEXT PRIMARY KEY,    -- e.g. "uderia-web", "uderia-google"
    source_id                TEXT NOT NULL REFERENCES connector_registry_sources(id),
    name                     TEXT NOT NULL,
    display_name             TEXT,
    description              TEXT,
    version                  TEXT NOT NULL DEFAULT '0.0.0',
    registry_metadata        TEXT,               -- full JSON from registry API response
    install_spec             TEXT,               -- JSON: {transport, command, args, env}
    install_status           TEXT DEFAULT 'not_installed',
    connector_type           TEXT NOT NULL DEFAULT 'mcp_stdio',
    enabled                  INTEGER DEFAULT 0,  -- admin master switch
    config                   TEXT,               -- JSON: non-sensitive config values
    credentials              TEXT,               -- Fernet-encrypted JSON (never exposed in API)
    available_tools          TEXT,               -- JSON array; NULL = all tools permitted
    auto_opt_in              INTEGER DEFAULT 0,
    user_can_opt_out         INTEGER DEFAULT 1,
    user_can_configure_tools INTEGER DEFAULT 0,
    requires_user_auth       INTEGER DEFAULT 0,  -- 1 = per-user OAuth required
    created_at               TEXT DEFAULT (datetime('now')),
    updated_at               TEXT DEFAULT (datetime('now'))
);
```

`install_status` values: `not_installed | installing | installed | unavailable | error`

`credentials` field: Fernet-encrypted JSON blob using the platform Fernet key. Never returned by any API endpoint — only decrypted at invocation time inside `invoke_connector_tool()`.

**Encryption salt note:** The Fernet key is derived using PBKDF2 with salt `b'platform_mcp_registry'`. This salt is intentionally frozen even though the module was renamed to `platform_connector_registry`. Changing the salt would corrupt all existing encrypted credentials in production databases.

### 6.3 `profile_connector_settings`

Per-profile user preferences — always within admin-permitted bounds.

```sql
CREATE TABLE profile_connector_settings (
    profile_id  TEXT NOT NULL,
    server_id   TEXT NOT NULL REFERENCES platform_connectors(id) ON DELETE CASCADE,
    opted_in    INTEGER,    -- NULL = follow auto_opt_in; 1 = explicit opt-in; 0 = explicit opt-out
    user_tools  TEXT,       -- JSON array of tool names; NULL = use all permitted tools
    updated_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (profile_id, server_id)
);
```

`opted_in` semantics:
- `NULL` — inherit `auto_opt_in` from admin setting (most common)
- `1` — user explicitly enabled this connector for the profile
- `0` — user explicitly disabled (only honoured when `user_can_opt_out = 1`)

### 6.4 `messaging_identities`

Stores per-user OAuth tokens for user connectors (`requires_user_auth = 1`).

```sql
CREATE TABLE messaging_identities (
    user_uuid        TEXT NOT NULL,
    platform         TEXT NOT NULL,     -- 'google' (matches connectors/registry.py key)
    platform_user_id TEXT NOT NULL,     -- e.g. "user@gmail.com"
    access_token     TEXT,              -- Fernet-encrypted
    refresh_token    TEXT,              -- Fernet-encrypted
    token_expiry     TEXT,
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_uuid, platform)
);
```

Tokens are stored as Fernet-encrypted strings using the same platform Fernet key as connector credentials. Automatic token refresh happens in `google_connector.get_tokens()` when the stored token is within expiry — the new token is written back to this table transparently.

---

## 7. Tool Injection Pipeline

Connector tools are merged into `APP_STATE['structured_tools']` by `load_and_categorize_mcp_resources()` in `mcp_adapter/adapter.py` at profile load time. This is an additive merge — existing primary server tools are unaffected.

```
load_and_categorize_mcp_resources(profile_id)
    ↓ (existing) loads primary MCP server tools into structured_tools
    ↓
    ↓ (new) if profile_id:
    ↓     platform_tools = platform_connector_registry.get_effective_tools(profile_id)
    ↓     for each tool:
    ↓         structured_tools["Platform Tools"].append(tool)
    ↓         mcp_tools[tool.name] = SimpleTool(...)   ← required for tool execution lookup
    ↓
    _regenerate_contexts()
    ↓
APP_STATE['tools_context']
    ↓
ToolDefinitionsModule.contribute()
    ↓
{available_tools} in WORKFLOW_META_PLANNING_PROMPT   ← platform tools appear automatically
```

Platform tools appear in the LLM context under the `"Platform Tools"` category, alongside the primary server's tools. No system prompt changes are needed — tool content is injected dynamically at load time.

### 7.1 Capabilities-Only Profiles

A profile with no primary MCP server (`mcpServerId = null`) is valid when at least one platform connector is active for it. The adapter's `load_and_categorize_mcp_resources()` handles `server_id = None` gracefully — it skips primary server loading and returns only platform connector tools.

`configuration_service.py` relaxes the hard gate:
- Old: tool_enabled profiles must have `mcpServerId`
- New: null `mcpServerId` is allowed if `platform_connector_registry.has_effective_tools(profile_id)` returns `True`

---

## 8. Tool Invocation Pipeline

When the agent calls a tool during execution, `adapter.py` checks whether it is a platform connector tool before falling through to the primary MCP server session:

```
invoke_mcp_tool(tool_name, args, user_uuid)
    ↓
    get_connector_for_tool(tool_name)
    │   ── searches builtin manifest → returns server_id, or None
    ↓
    if server_id found:
        invoke_connector_tool(server_id, tool_name, args, user_uuid)
            ↓
            get_server(server_id)               → server row from DB
            connector_type = server["connector_type"]
            strategy = _INVOCATION_STRATEGIES[connector_type]
                ↓
                build env = os.environ.copy()
                + admin credentials (decrypted from platform_connectors.credentials)
                + user tokens (if requires_user_auth and user_uuid provided)
                  via _inject_user_tokens(server_id, user_uuid, env)
                    → connectors/registry.server_id_to_platform(server_id)
                    → connector module.inject_env_tokens(user_uuid, env)
                    → (fallback) generic PLATFORM_ACCESS_TOKEN / PLATFORM_REFRESH_TOKEN
                ↓
                strategy.invoke_tool(server, tool_name, args, env)
            ↓
            asyncio.wait_for(..., timeout=30s)
            ↓
            return result dict
    ↓
    (else) fall through to primary MCP server session
```

The platform connector routing is transparent to the rest of the agent pipeline — the result dict returned is identical in structure to a primary MCP tool call result.

---

## 9. OAuth Connector Module Interface

Every connector that supports per-user OAuth must implement this interface as a Python module in `src/trusted_data_agent/connectors/`. The module is registered in `connectors/registry.py`.

### Required attributes and functions

```python
# Module-level constant — must match platform_connectors.id for this connector
SERVER_ID: str = "uderia-{platform}"

# Returns True if admin has configured the required credentials
def is_configured() -> bool: ...

# Returns the OAuth authorization URL for the user to redirect to
# Returns None if is_configured() is False
def initiate_oauth(user_uuid: str, redirect_uri: str) -> Optional[str]: ...

# Called after the provider redirects back with ?code=&state=
# Exchanges code for tokens, stores in messaging_identities
# Returns {"email": ..., "user_uuid": ...} on success, None on failure
async def handle_callback(code: str, state: str, redirect_uri: str) -> Optional[dict]: ...

# Returns connection status for the UI card
# {"connected": bool, "configured": bool, "email": str?, "token_expiry": str?}
def get_connection_status(user_uuid: str) -> dict: ...

# Revokes tokens at provider and deletes from messaging_identities
async def disconnect(user_uuid: str) -> None: ...

# Returns decrypted tokens with auto-refresh; None if not connected
async def get_tokens(user_uuid: str) -> Optional[dict]: ...

# Injects decrypted tokens into subprocess env dict
# Called by _inject_user_tokens() in platform_connector_registry.py
def inject_env_tokens(user_uuid: str, env: dict) -> None: ...
```

`inject_env_tokens` is **optional** — if not implemented, `_inject_user_tokens()` falls back to a generic pattern that sets `{PLATFORM}_ACCESS_TOKEN` and `{PLATFORM}_REFRESH_TOKEN` env vars by querying `messaging_identities` directly.

### CSRF protection

`initiate_oauth()` generates a UUID `state` token stored in an in-memory dict (`_pending_states`) with a 10-minute TTL. `handle_callback()` validates and pops the token. This prevents cross-site request forgery in the OAuth flow.

### Token auto-refresh

`get_tokens()` checks `token_expiry` on every call. If expired, it calls `_do_refresh()` which exchanges the stored `refresh_token` for a new `access_token` using the provider's token endpoint and writes the new value back to `messaging_identities`. Refresh failures return `None` (not an exception), causing the UI to show "reconnect" state.

---

## 10. REST API Reference

### 10.1 Registry Management (Admin only)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/connector-registry/sources` | List configured registry sources |
| `POST` | `/api/v1/connector-registry/sources` | Add enterprise registry URL |
| `DELETE` | `/api/v1/connector-registry/sources/<source_id>` | Remove a registry source |
| `GET` | `/api/v1/connector-registry/servers?source=&search=&page=` | Browse servers from a source |
| `POST` | `/api/v1/connector-registry/servers/install` | Install a connector from a registry |

### 10.2 Platform Connector Management (Admin only)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/platform-connectors` | List all installed connectors with governance settings |
| `GET` | `/api/v1/platform-connectors/<id>` | Get a single connector |
| `PUT` | `/api/v1/platform-connectors/<id>` | Update governance settings (enable, available_tools, opt-in policy, credentials) |
| `DELETE` | `/api/v1/platform-connectors/<id>` | Remove connector + all profile settings |
| `GET` | `/api/v1/platform-connectors/<id>/tools` | Get tool schemas (from manifest; live discovery planned) |

### 10.3 Profile Connector Settings (User)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/profiles/<profile_id>/connector-settings` | Get user's opt-in state for all connectors on this profile |
| `PUT` | `/api/v1/profiles/<profile_id>/connector-settings/<server_id>` | Update opt-in state and tool selection |

Governance enforcement is applied server-side: opt-out requests are rejected (403) when `user_can_opt_out = 0`; tool selection is ignored when `user_can_configure_tools = 0`.

### 10.4 OAuth Connector Routes (User)

Generic routes in `api/connector_routes.py` — `<platform>` resolves via `connectors/registry.py`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/connectors/<platform>/auth` | Return OAuth authorization URL for popup flow |
| `GET` | `/api/v1/connectors/<platform>/callback` | Handle OAuth callback (provider redirect) |
| `GET` | `/api/v1/connectors/<platform>/status` | Return connection status for current user |
| `DELETE` | `/api/v1/connectors/<platform>/connection` | Revoke and disconnect account |

The callback endpoint returns a minimal HTML page that posts `window.postMessage({type: "{platform}_oauth_success", email: "..."})` to the opener window and closes itself after 1.5 seconds. This allows the Platform Components panel to refresh the connector card without a full page reload.

---

## 11. UI Surfaces

Three distinct UI surfaces handle different aspects of the connector lifecycle.

### 11.1 Admin Panel → Connectors Tab

**Responsibility:** Admin installs, configures, and governs platform connectors.

**Handler:** `static/js/handlers/platformConnectorAdminHandler.js`

**Features:**
- Browse registry sources (Uderia built-in, official MCP Registry, enterprise private)
- Search and install connectors
- Per-connector governance controls:
  - Master enable/disable toggle
  - Available tools multi-select (permits subset of discovered tools)
  - Auto opt-in toggle
  - "User can opt out" toggle (visible only when auto opt-in is on)
  - "User can configure tools" toggle
- Credentials dialog — stores sensitive values encrypted in `platform_connectors.credentials`
- Test connection — calls `GET /v1/platform-connectors/<id>/tools`

Connectors are the only things managed here. User MCP data source servers never appear in this tab.

### 11.2 Platform Components Panel → Connectors Tab

**Responsibility:** User assigns connectors to profiles (coarse on/off per connector per profile).

**Handler:** `static/js/handlers/platformConnectorHandler.js`

**Features:**
- Server-centric view: one card per admin-enabled connector
- Each card shows connector name, description, and tools
- Per-profile toggle for each connector (user's profiles only)
- Lock icon on profiles where the user cannot opt out
- For `requires_user_auth` connectors (e.g. `uderia-google`): inline "Connect account" / "Connected as email" OAuth section via `_loadConnectorOAuthSection()`

**OAuth popup flow:**
1. User clicks "Connect {Platform} account"
2. Frontend calls `GET /api/v1/connectors/{platform}/auth`
3. Opens returned `auth_url` in a popup window
4. Popup redirects to provider → back to `/api/v1/connectors/{platform}/callback`
5. Callback page posts `{platform}_oauth_success` to `window.opener`
6. Panel refreshes connector card to show "Connected as user@email.com"

No tool-level configuration happens in this panel — that is delegated to Profile Edit.

### 11.3 Profile Edit Dialog → Connectors Section

**Responsibility:** User fine-tunes tool selection per connector per profile.

**Features:**
- Shows only connectors the user has enabled for this profile (via Platform Components panel)
- Auto opt-in + user cannot opt out: shown as always active (lock icon)
- For connectors where `user_can_configure_tools = true`: expandable tool checklist showing admin-permitted tools
- For connectors without `user_can_configure_tools`: shown as active (all permitted tools enabled), no checklist

This mirrors the existing component configuration pattern — enable in Platform Components, configure detail in Profile Edit.

---

## 12. How to Add a New Connector Type

A new connector type (e.g. `rest`, `websocket`, `grpc`) requires three steps, all in `core/platform_connector_registry.py`:

**Step 1: Add a constant**
```python
CONNECTOR_TYPE_REST = "rest"
```

**Step 2: Implement the strategy**
```python
class RestStrategy(ConnectorInvocationStrategy):
    async def invoke_tool(self, server: dict, tool_name: str,
                          args: dict, env: dict) -> dict:
        import httpx
        install_spec = server.get("install_spec") or {}
        base_url = install_spec.get("url")
        if not base_url:
            return {"status": "error", "error": "REST connector missing 'url' in install_spec."}
        
        api_key = env.get("API_KEY", "")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/tools/{tool_name}",
                json=args,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code != 200:
            return {"status": "error", "error": f"HTTP {resp.status_code}: {resp.text}"}
        return {"status": "success", **resp.json()}
```

**Step 3: Register the instance**
```python
_INVOCATION_STRATEGIES: dict[str, ConnectorInvocationStrategy] = {
    CONNECTOR_TYPE_MCP_STDIO: McpStdioStrategy(),
    CONNECTOR_TYPE_MCP_HTTP:  McpHttpStrategy(),
    CONNECTOR_TYPE_REST:      RestStrategy(),   # ← add this line
}
```

No changes are needed in `adapter.py`, `connector_routes.py`, or any other file. Existing connectors are unaffected.

To activate a REST-type connector via the admin UI, set `connector_type: "rest"` in the `PUT /v1/platform-connectors/<id>` governance update call.

---

## 13. How to Add a New Connector Instance

A new connector instance (e.g. `uderia-slack`, `uderia-github`) requires two steps:

**Step 1: Create the connector module**

Create `src/trusted_data_agent/connectors/slack_connector.py`:

```python
SERVER_ID = "uderia-slack"

def is_configured() -> bool:
    """Return True if admin has set SLACK_BOT_TOKEN in credentials."""
    from trusted_data_agent.core.platform_connector_registry import get_server_credentials
    creds = get_server_credentials(SERVER_ID)
    return bool(creds.get("SLACK_BOT_TOKEN"))

def inject_env_tokens(user_uuid: str, env: dict):
    """Platform connector — no per-user auth; admin token already in env from credentials."""
    pass  # Admin SLACK_BOT_TOKEN already injected by invoke_connector_tool()
```

For a user OAuth connector (like Google), implement all 7 required functions (§9). For a platform connector (shared admin credentials only), `inject_env_tokens` may be a no-op or omitted entirely.

**Step 2: Register in the connector registry**

Add to the bottom of `src/trusted_data_agent/connectors/registry.py`:

```python
from trusted_data_agent.connectors import slack_connector as _slack
register("slack", _slack)
```

The platform name (`"slack"`) becomes the `<platform>` path parameter in all OAuth routes and the key in `messaging_identities.platform` if per-user auth is added later.

**Step 3 (if installing from admin UI): Create the connector record**

The connector appears in the Admin Panel after `POST /v1/connector-registry/servers/install` is called with the appropriate registry entry, or it can be inserted directly into `platform_connectors` during development.

---

## 14. Security Model

### 14.1 Admin Credential Encryption

All admin credentials (API keys, client secrets) are stored Fernet-encrypted in `platform_connectors.credentials`. The Fernet key is derived from the platform master key (`TDA_ENCRYPTION_KEY` env var, defaulting to a development placeholder) using PBKDF2HMAC with SHA-256, 100,000 iterations, and a fixed salt (`b'platform_mcp_registry'`).

Credentials are **never exposed by any API endpoint** — `_row_to_server()` strips the `credentials` field before returning server data to callers. Decryption only happens inside `invoke_connector_tool()` immediately before environment variable injection.

### 14.2 User Token Encryption

Per-user OAuth tokens in `messaging_identities` are encrypted with the **same** platform Fernet key as admin credentials. This ensures all sensitive data at rest uses a single, consistently-managed key.

### 14.3 Tool Governance Enforcement

Governance rules are enforced at two independent points:

1. **At tool injection time** (`get_effective_tools`): Only tools that pass the full governance chain (admin enabled → opted-in → permitted set) are loaded into `APP_STATE['structured_tools']`. The LLM never sees tools that are not permitted for the current profile.

2. **At invocation time** (`update_profile_connector_setting` route): The API enforces `user_can_opt_out` and `user_can_configure_tools` constraints server-side — malformed requests that try to exceed admin-permitted bounds are rejected with HTTP 403.

### 14.4 uderia-shell Security

`uderia-shell` requires **two mandatory and complementary security layers**:

| Layer | Mechanism | What it prevents |
|---|---|---|
| Admin governance | `available_tools`, opt-in policy, per-profile opt-in | Unauthorised profiles/users accessing shell tools |
| Docker isolation | Throwaway container per invocation | LLM commands reaching host filesystem, `tda_keys/`, `tda_auth.db`, or host network |

Container constraints (non-negotiable defaults):
- No host filesystem access (only explicitly admin-configured mount paths)
- No outbound network by default (admin can allowlist specific domains)
- Resource limits: 1 CPU, 512MB RAM, 30s execution timeout, 100MB disk
- Non-root user inside container
- Container destroyed immediately after invocation

All invocations are written to the `shell_audit_log` table (command, exit code, truncated output). The admin enable toggle for `uderia-shell` is gated behind an explicit security acknowledgment modal.

### 14.5 CSRF Protection in OAuth Flows

`initiate_oauth()` generates a UUID state token stored in `_pending_states` with a 10-minute TTL. `handle_callback()` validates the state parameter against this store before proceeding. This prevents cross-site request forgery — a third party cannot initiate a token exchange on behalf of a Uderia user.

### 14.6 Subprocess Environment Isolation

Each tool invocation spawns a fresh subprocess. The environment is built as `os.environ.copy()` (inheriting the Uderia process environment) plus the connector's credentials and user tokens. The subprocess cannot read `tda_auth.db` or `tda_keys/` unless those paths are explicitly exposed — they are not, by default.

---

## 15. File Reference Map

### Core Backend

| File | Purpose |
|---|---|
| `src/trusted_data_agent/core/platform_connector_registry.py` | Central registry module: governance, tool resolution, invocation dispatch, strategy pattern |
| `src/trusted_data_agent/connectors/registry.py` | Maps platform names (`"google"`) to connector modules; `server_id_to_platform()` lookup |
| `src/trusted_data_agent/connectors/google_connector.py` | Google OAuth connector: initiate, callback, token storage, refresh, disconnect, inject |
| `src/trusted_data_agent/api/connector_routes.py` | Generic OAuth REST routes: `auth`, `callback`, `status`, `connection` |
| `src/trusted_data_agent/api/rest_routes.py` | Connector registry + platform connector management REST routes |
| `src/trusted_data_agent/mcp_adapter/adapter.py` | Tool injection (line ~915) and tool invocation routing (line ~1950) |
| `src/trusted_data_agent/core/config_manager.py` | Governance bypass: platform connector tools exempt from `profile.tools[]` filter |
| `src/trusted_data_agent/core/configuration_service.py` | Capabilities-only profile validation via `has_effective_tools()` |

### Database Schema

| File | Purpose |
|---|---|
| `schema/27_platform_mcp_servers.sql` | Original table creation (`mcp_registry_sources`, `platform_mcp_servers`, `profile_platform_mcp_settings`) |
| `schema/29_rename_platform_connectors.sql` | Rename migration + `connector_type` column addition |
| `schema/28_scheduled_tasks.sql` | `messaging_identities` table (per-user OAuth tokens) |

### Frontend

| File | Purpose |
|---|---|
| `static/js/handlers/platformConnectorAdminHandler.js` | Admin Panel → Connectors tab (install, govern, credentials) |
| `static/js/handlers/platformConnectorHandler.js` | Platform Components → Connectors tab (user assignment, OAuth flow) |
| `templates/index.html` | DOM elements: `platform-connector-container`, `platform-connector-tab`, `platform-connector-admin-container`, `profile-section-platform-connector`, `profile-connector-content`, `profile-nav-platform-connector` |
| `static/js/adminManager.js` | Tab routing: `platform-connector-tab` → `loadPlatformConnectorAdminPanel()` |
| `static/js/ui.js` | Panel init: `platform-connector-actions` → `loadPlatformConnectorPanel()` |

### First-Party Connector Servers

| Directory | Connector |
|---|---|
| `mcp_servers/builtin/uderia-web/` | Web search + fetch (Brave/Serper API key) |
| `mcp_servers/builtin/uderia-files/` | Filesystem read/write (path allowlist) |
| `mcp_servers/builtin/uderia-browser/` | Playwright browser automation |
| `mcp_servers/builtin/uderia-google/` | Gmail + Calendar (per-user OAuth via `google_connector.py`) |
| `mcp_servers/builtin/uderia-shell/` | Docker-isolated command execution |
