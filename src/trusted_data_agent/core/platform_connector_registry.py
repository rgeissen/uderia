"""
Platform Connector Registry

Manages admin-governed platform connectors (browser, files, shell, web, google, …).
Strictly separate from user-configured data source servers (Configuration → MCP Servers).

Governance chain:
  admin enables + sets policy → user assigns to profiles →
  profile selects tool subset → execution merges into tool context

Connector types (connector_type field):
  mcp_stdio   — MCP protocol via subprocess stdin/stdout  (default, all existing connectors)
  mcp_http    — MCP protocol via HTTP/SSE transport endpoint
  rest        — Direct REST API calls (no MCP protocol)
  oauth_only  — Authentication only; no tool execution

Adding a new connector type:
  1. Add a CONNECTOR_TYPE_* constant below.
  2. Implement a ConnectorInvocationStrategy subclass.
  3. Register an instance in _INVOCATION_STRATEGIES.
"""

import json
import logging
import sqlite3
import asyncio
import base64
import hashlib
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("quart.app")

# Resolve DB path the same way database.py does
_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"

# Master key for platform credential encryption (shared with encryption.py)
_MASTER_KEY = os.environ.get('TDA_ENCRYPTION_KEY', 'dev-master-key-change-in-production')


# ---------------------------------------------------------------------------
# Connector type constants
# ---------------------------------------------------------------------------

CONNECTOR_TYPE_MCP_STDIO  = "mcp_stdio"   # MCP protocol, subprocess stdin/stdout
CONNECTOR_TYPE_MCP_HTTP   = "mcp_http"    # MCP protocol, HTTP/SSE transport
CONNECTOR_TYPE_REST       = "rest"         # Direct REST API (no MCP)
CONNECTOR_TYPE_OAUTH_ONLY = "oauth_only"  # Auth only, no tool execution


# ---------------------------------------------------------------------------
# Invocation strategy abstraction
# ---------------------------------------------------------------------------

class ConnectorInvocationStrategy:
    """
    Abstract strategy for platform connector tool invocation.

    Each connector_type maps to exactly one strategy.  Adding a new connector
    type (REST, WebSocket, gRPC …) requires only implementing this class and
    registering an instance in _INVOCATION_STRATEGIES below — no other code
    changes are needed.

    The `env` dict has already been populated with admin credentials and,
    when the connector requires per-user auth, the user's OAuth tokens.
    """
    async def invoke_tool(
        self,
        server: dict,
        tool_name: str,
        args: dict,
        env: dict,
    ) -> dict:
        raise NotImplementedError


class McpStdioStrategy(ConnectorInvocationStrategy):
    """Invokes a tool by spawning the connector process over stdin/stdout (MCP wire protocol)."""

    async def invoke_tool(self, server: dict, tool_name: str, args: dict, env: dict) -> dict:
        import sys
        repo_root = Path(__file__).resolve().parents[3]
        server_id = server["id"]

        install_spec = server.get("install_spec") or {}
        if isinstance(install_spec, str):
            try:
                install_spec = json.loads(install_spec)
            except Exception:
                install_spec = {}

        cmd_args = install_spec.get("args", [])
        if not cmd_args:
            builtin_dir = repo_root / "mcp_servers" / "builtin" / server_id
            entry = builtin_dir / "server.py"
            if not entry.exists():
                return {"status": "error", "error": f"Server entry point not found for '{server_id}'."}
            cmd_args = [str(entry)]

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except Exception as exc:
            logger.error(f"Failed to spawn connector '{server_id}': {exc}")
            return {"status": "error", "error": f"Could not start '{server_id}': {exc}"}

        try:
            return await _call_via_mcp_stdio(proc, tool_name, args)
        finally:
            try:
                proc.kill()
            except Exception:
                pass


class McpHttpStrategy(ConnectorInvocationStrategy):
    """Invokes a tool via an HTTP/SSE MCP transport endpoint (connector must be running)."""

    async def invoke_tool(self, server: dict, tool_name: str, args: dict, env: dict) -> dict:
        raise NotImplementedError(
            "MCP HTTP transport is not yet implemented. "
            "Use connector_type='mcp_stdio' for subprocess-based connectors."
        )


# Strategy registry — maps connector_type → strategy instance.
# Extend here to add new connector types without touching any other code.
_INVOCATION_STRATEGIES: dict[str, ConnectorInvocationStrategy] = {
    CONNECTOR_TYPE_MCP_STDIO: McpStdioStrategy(),
    CONNECTOR_TYPE_MCP_HTTP:  McpHttpStrategy(),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _platform_fernet():
    """
    Return a Fernet instance keyed to the platform (not per-user).

    IMPORTANT: The salt b'platform_mcp_registry' is intentionally frozen.
    Changing it would render all existing encrypted admin credentials in the DB
    unreadable.  The salt encodes where the key was created, not what it encrypts.
    """
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt = b'platform_mcp_registry'  # frozen — see docstring above
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    key = kdf.derive(_MASTER_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(data: dict) -> str:
    return _platform_fernet().encrypt(json.dumps(data).encode()).decode()


def _decrypt(token: str) -> dict:
    try:
        return json.loads(_platform_fernet().decrypt(token.encode()).decode())
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Registry source management
# ---------------------------------------------------------------------------

def list_registry_sources() -> list[dict]:
    """Return all configured registry sources."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, url, enabled, is_builtin FROM connector_registry_sources ORDER BY is_builtin DESC, name"
        ).fetchall()
    return [dict(r) for r in rows]


def add_registry_source(name: str, url: str) -> dict:
    """Add an enterprise private registry source."""
    import uuid
    source_id = f"registry-{uuid.uuid4().hex[:8]}"
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO connector_registry_sources (id, name, url, enabled, is_builtin) VALUES (?, ?, ?, 1, 0)",
            (source_id, name, url)
        )
        conn.commit()
    return {"id": source_id, "name": name, "url": url, "enabled": 1, "is_builtin": 0}


def delete_registry_source(source_id: str) -> bool:
    """Delete a non-builtin registry source."""
    with _get_conn() as conn:
        row = conn.execute("SELECT is_builtin FROM connector_registry_sources WHERE id = ?", (source_id,)).fetchone()
        if not row or row["is_builtin"]:
            return False
        conn.execute("DELETE FROM connector_registry_sources WHERE id = ?", (source_id,))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Server listing (proxies to external registry APIs)
# ---------------------------------------------------------------------------

async def list_registry_servers(source_id: str, search: str = "", page: int = 1, cursor: str = "") -> dict:
    """
    Browse connectors from a registry source.
    Built-in source returns locally registered first-party connectors.
    External sources proxy GET /v0.1/servers to the registry URL.
    cursor is forwarded to external registries that use cursor-based pagination.
    """
    with _get_conn() as conn:
        source = conn.execute(
            "SELECT id, name, url, enabled FROM connector_registry_sources WHERE id = ?", (source_id,)
        ).fetchone()

    if not source:
        return {"servers": [], "total": 0, "page": page}

    if source["url"] == "builtin://":
        return _list_builtin_servers(search, page)

    return await _proxy_registry_request(source["url"], search, page, cursor=cursor)


def _load_builtin_manifests() -> list[dict]:
    """Load first-party connector manifests from mcp_servers/builtin/*/manifest.json."""
    repo_root = Path(__file__).resolve().parents[3]
    builtin_dir = repo_root / "mcp_servers" / "builtin"
    servers = []
    if not builtin_dir.exists():
        return servers
    for manifest_path in sorted(builtin_dir.glob("*/manifest.json")):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            entry_point = manifest.get("entry_point", "")
            server_entry = repo_root / entry_point if entry_point else None
            install_spec = {
                "transport": manifest.get("transport", "stdio"),
                "command": "python",
                "args": [str(server_entry)] if server_entry and server_entry.exists() else [],
                "local": True,
            }
            servers.append({
                "id": manifest.get("id", manifest_path.parent.name),
                "name": manifest.get("name", manifest_path.parent.name),
                "display_name": manifest.get("display_name", manifest_path.parent.name),
                "description": manifest.get("description", ""),
                "version": manifest.get("version", "1.0.0"),
                "connector_type": manifest.get("connector_type", CONNECTOR_TYPE_MCP_STDIO),
                "install_spec": install_spec,
                "tools": manifest.get("tools", []),
                "requires_user_auth": manifest.get("requires_user_auth", False),
                "security_acknowledgment_required": manifest.get("security_acknowledgment_required", False),
                "credential_schema": manifest.get("credential_schema", {}),
                "config_schema": manifest.get("config_schema", {}),
                "tags": manifest.get("tags", []),
                "_manifest_path": str(manifest_path),
            })
        except Exception as exc:
            logger.warning("Failed to load builtin manifest %s: %s", manifest_path, exc)
    return servers


def _list_builtin_servers(search: str, page: int) -> dict:
    """Return the list of Uderia first-party platform connectors from disk manifests."""
    builtin = _load_builtin_manifests()

    if search:
        search_lower = search.lower()
        builtin = [
            s for s in builtin
            if search_lower in s.get("display_name", "").lower()
            or search_lower in s.get("description", "").lower()
            or search_lower in " ".join(s.get("tags", [])).lower()
        ]

    page_size = 20
    start = (page - 1) * page_size
    return {"servers": builtin[start:start + page_size], "total": len(builtin), "page": page}


async def _proxy_registry_request(base_url: str, search: str, page: int, cursor: str = "") -> dict:
    """
    Proxy GET /v0.1/servers to an external connector registry.
    Supports both page-based and cursor-based pagination.
    """
    try:
        import httpx
        params: dict = {}
        if search:
            params["search"] = search
        if cursor:
            params["cursor"] = cursor
        else:
            params["page"] = page
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/v0.1/servers", params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"Failed to proxy registry request to {base_url}: {e}")
        return {"servers": [], "total": 0, "page": page, "error": str(e)}


# ---------------------------------------------------------------------------
# Connector installation / connection
# ---------------------------------------------------------------------------

def install_server(source_id: str, server_id: str, server_data: dict) -> dict:
    """
    Register a connector as installed/connected.
    For package-based connectors: records install intent (actual pip install is separate).
    For remote connectors: records connection details.
    """
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM platform_connectors WHERE id = ?", (server_id,)
        ).fetchone()

        connector_type = server_data.get("connector_type", CONNECTOR_TYPE_MCP_STDIO)
        now = _now()
        if existing:
            conn.execute(
                """UPDATE platform_connectors SET
                    source_id=?, name=?, display_name=?, description=?, version=?,
                    registry_metadata=?, install_spec=?, install_status=?,
                    connector_type=?, requires_user_auth=?, updated_at=?
                   WHERE id=?""",
                (
                    source_id,
                    server_data.get("name", server_id),
                    server_data.get("display_name", server_id),
                    server_data.get("description", ""),
                    server_data.get("version", "0.0.0"),
                    json.dumps(server_data.get("registry_metadata", {})),
                    json.dumps(server_data.get("install_spec", {})),
                    "installed",
                    connector_type,
                    1 if server_data.get("requires_user_auth") else 0,
                    now,
                    server_id,
                )
            )
        else:
            conn.execute(
                """INSERT INTO platform_connectors
                   (id, source_id, name, display_name, description, version,
                    registry_metadata, install_spec, install_status,
                    connector_type, enabled, requires_user_auth, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'installed', ?, 0, ?, ?, ?)""",
                (
                    server_id,
                    source_id,
                    server_data.get("name", server_id),
                    server_data.get("display_name", server_id),
                    server_data.get("description", ""),
                    server_data.get("version", "0.0.0"),
                    json.dumps(server_data.get("registry_metadata", {})),
                    json.dumps(server_data.get("install_spec", {})),
                    connector_type,
                    1 if server_data.get("requires_user_auth") else 0,
                    now, now,
                )
            )
        conn.commit()

    return get_server(server_id)


def get_server(server_id: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM platform_connectors WHERE id = ?", (server_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_server(row)


def list_installed_servers() -> list[dict]:
    """Return all connectors registered in platform_connectors (installed or connected)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM platform_connectors ORDER BY name"
        ).fetchall()
    return [_row_to_server(r) for r in rows]


def update_server_governance(server_id: str, updates: dict) -> Optional[dict]:
    """Update admin governance settings for a platform connector."""
    allowed = {
        "enabled", "available_tools", "auto_opt_in",
        "user_can_opt_out", "user_can_configure_tools", "config",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_server(server_id)

    if "available_tools" in fields and isinstance(fields["available_tools"], list):
        fields["available_tools"] = json.dumps(fields["available_tools"])

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [server_id]

    with _get_conn() as conn:
        conn.execute(f"UPDATE platform_connectors SET {set_clause} WHERE id = ?", values)
        conn.commit()
    return get_server(server_id)


def update_server_credentials(server_id: str, credentials: dict) -> bool:
    """Encrypt and store sensitive credentials for a platform connector."""
    encrypted = _encrypt(credentials)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE platform_connectors SET credentials = ?, updated_at = ? WHERE id = ?",
            (encrypted, _now(), server_id)
        )
        conn.commit()
    return True


def get_server_credentials(server_id: str) -> dict:
    """Decrypt and return credentials for a platform connector."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT credentials FROM platform_connectors WHERE id = ?", (server_id,)
        ).fetchone()
    if not row or not row["credentials"]:
        return {}
    return _decrypt(row["credentials"])


def delete_server(server_id: str) -> bool:
    """Remove a platform connector (cascades to profile settings via ON DELETE CASCADE)."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM platform_connectors WHERE id = ?", (server_id,))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Effective tool resolution (the governance chain)
# ---------------------------------------------------------------------------

def get_effective_tool_names(profile_id: str) -> set[str]:
    """
    Return the set of platform connector tool names active for this profile,
    after applying the full governance chain:
      admin enabled → auto_opt_in → user opt-in/out → available_tools → user_tools
    """
    return {t["name"] for t in get_effective_tools(profile_id)}


def get_effective_tools(profile_id: str) -> list[dict]:
    """
    Return structured tool definitions for all platform connectors active on this profile.
    Used by load_and_categorize_mcp_resources() to merge connector tools into APP_STATE.
    """
    with _get_conn() as conn:
        servers = conn.execute(
            "SELECT * FROM platform_connectors WHERE enabled = 1"
        ).fetchall()
        settings_rows = conn.execute(
            "SELECT server_id, opted_in, user_tools FROM profile_connector_settings WHERE profile_id = ?",
            (profile_id,)
        ).fetchall()

    settings = {r["server_id"]: dict(r) for r in settings_rows}
    active_tools = []

    for server_row in servers:
        server = _row_to_server(server_row)
        sid = server["id"]
        pref = settings.get(sid, {})
        opted_in = pref.get("opted_in")  # None / 1 / 0

        if server["auto_opt_in"]:
            if server["user_can_opt_out"] and opted_in == 0:
                continue
        else:
            if opted_in != 1:
                continue

        admin_tools = server.get("available_tools")  # list or None
        user_tools_raw = pref.get("user_tools")
        user_tools = json.loads(user_tools_raw) if user_tools_raw else None

        if admin_tools is None:
            permitted = None
        else:
            permitted = set(admin_tools)
            if server["user_can_configure_tools"] and user_tools:
                permitted = permitted & set(user_tools)

        category = f"Platform: {_connector_namespace(sid).replace('_', ' ').title()}"
        server_tools = _get_cached_tool_schemas(sid)
        for tool in server_tools:
            # tool["name"] is namespaced (e.g. google__read_emails); permitted stores
            # original names (e.g. read_emails) — compare against stripped name.
            original = _strip_namespace(tool["name"])
            if permitted is None or original in permitted:
                active_tools.append({**tool, "_category": category})

    return active_tools


def has_effective_tools(profile_id: str) -> bool:
    """Return True if this profile has at least one active platform connector tool."""
    return bool(get_effective_tool_names(profile_id))


# ---------------------------------------------------------------------------
# Per-profile user settings (opt-in/out, tool selection)
# ---------------------------------------------------------------------------

def get_profile_server_settings(profile_id: str) -> list[dict]:
    """
    Return all enabled platform connectors with the user's current opt-in state.
    """
    with _get_conn() as conn:
        servers = conn.execute(
            "SELECT * FROM platform_connectors WHERE enabled = 1 ORDER BY name"
        ).fetchall()
        settings_rows = conn.execute(
            "SELECT server_id, opted_in, user_tools FROM profile_connector_settings WHERE profile_id = ?",
            (profile_id,)
        ).fetchall()

    settings = {r["server_id"]: dict(r) for r in settings_rows}
    result = []
    for server_row in servers:
        server = _row_to_server(server_row)
        sid = server["id"]
        pref = settings.get(sid, {})
        result.append({
            **server,
            "server_id": sid,
            "opted_in": pref.get("opted_in"),
            "user_tools": json.loads(pref["user_tools"]) if pref.get("user_tools") else None,
        })
    return result


def update_profile_server_setting(profile_id: str, server_id: str, opted_in: Optional[int], user_tools: Optional[list]) -> bool:
    """Upsert a profile's opt-in state and tool selection for a platform connector."""
    user_tools_json = json.dumps(user_tools) if user_tools is not None else None
    now = _now()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO profile_connector_settings (profile_id, server_id, opted_in, user_tools, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(profile_id, server_id) DO UPDATE SET
                   opted_in = excluded.opted_in,
                   user_tools = excluded.user_tools,
                   updated_at = excluded.updated_at""",
            (profile_id, server_id, opted_in, user_tools_json, now)
        )
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Connector namespace helpers
# ---------------------------------------------------------------------------

def _connector_namespace(server_id: str) -> str:
    """Return the short namespace prefix for a connector's tool names.

    Strips the ``uderia-`` product prefix so tool names stay concise:
      uderia-google  →  google   (google__read_emails)
      uderia-files   →  files    (files__read_file)
      uderia-web     →  web      (web__web_search)
    Non-uderia IDs are used as-is with hyphens replaced by underscores.
    """
    ns = server_id
    if ns.startswith("uderia-"):
        ns = ns[len("uderia-"):]
    return ns.replace("-", "_")


def _namespace_tool(server_id: str, original_name: str) -> str:
    """Return ``{namespace}__{original_name}`` for a connector tool."""
    return f"{_connector_namespace(server_id)}__{original_name}"


def _strip_namespace(namespaced_name: str) -> str:
    """Return the original tool name without the connector namespace prefix."""
    if "__" in namespaced_name:
        return namespaced_name.split("__", 1)[1]
    return namespaced_name


# ---------------------------------------------------------------------------
# Tool schema cache (avoids repeated subprocess calls per request)
# ---------------------------------------------------------------------------

_tool_schema_cache: dict = {}  # server_id → {tools: list[namespaced], ts: float}
_TOOL_CACHE_TTL = 300  # 5 minutes

_manifest_cache: dict = {}  # server_id → manifest dict (refreshed on process restart)


def _get_builtin_manifest(server_id: str) -> dict:
    """Return the on-disk manifest for a builtin connector (cached for process lifetime)."""
    if server_id not in _manifest_cache:
        manifest_path = Path(__file__).resolve().parents[3] / "mcp_servers" / "builtin" / server_id / "manifest.json"
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                _manifest_cache[server_id] = json.load(f)
        except Exception:
            _manifest_cache[server_id] = {}
    return _manifest_cache[server_id]


def _enrich_with_manifest(server: dict) -> dict:
    """
    Hoist manifest_tools and auth_schema into a server dict from the on-disk manifest.

    manifest_tools  — full tool list from the manifest (before admin governance narrows it)
    auth_schema     — drives the dynamic auth UI in the Platform Components panel;
                      built from manifest.auth_schema or derived from legacy oauth_provider field
    """
    manifest = _get_builtin_manifest(server.get("id", ""))
    if not manifest:
        return server
    server["manifest_tools"] = manifest.get("tools", [])
    if "auth_schema" not in server or server.get("auth_schema") is None:
        auth_schema = manifest.get("auth_schema")
        if not auth_schema and manifest.get("requires_user_auth"):
            provider = manifest.get("oauth_provider", "")
            if provider:
                auth_schema = {
                    "type": "oauth2",
                    "display_name": provider.title(),
                    "description": f"Connect your {provider.title()} account to enable its tools.",
                    "icon": provider,
                }
        server["auth_schema"] = auth_schema
    return server


def _get_cached_tool_schemas(server_id: str) -> list[dict]:
    """
    Return cached tool schemas for a platform connector, or fetch live if stale.
    Falls back to the builtin manifest if the connector process is not running.
    """
    import time
    cached = _tool_schema_cache.get(server_id)
    if cached and (time.time() - cached["ts"]) < _TOOL_CACHE_TTL:
        return cached["tools"]

    tools = _fetch_tool_schemas_from_manifest(server_id)
    _tool_schema_cache[server_id] = {"tools": tools, "ts": time.time()}
    return tools


def _fetch_tool_schemas_from_manifest(server_id: str) -> list[dict]:
    """Return namespaced tool schemas from the builtin connector manifest.

    Tool names are prefixed with ``{namespace}__`` (e.g. ``google__read_emails``)
    so tools from different connectors cannot collide in the LLM planning context.
    The namespace is the connector ID with ``uderia-`` stripped and hyphens replaced.

    Uses the manifest's ``tool_schemas`` list (rich format with arguments) when
    present, otherwise falls back to the plain ``tools`` name list.
    """
    manifest = _get_builtin_manifest(server_id)
    if manifest:
        if manifest.get("tool_schemas"):
            return [
                {
                    "name": _namespace_tool(server_id, ts["name"]),
                    "description": ts.get("description", f"{server_id} tool: {ts['name']}"),
                    "arguments": ts.get("arguments", []),
                    "disabled": False,
                }
                for ts in manifest["tool_schemas"]
            ]
        # Fallback: plain name list with minimal metadata
        return [
            {
                "name": _namespace_tool(server_id, t),
                "description": f"{_connector_namespace(server_id)} tool: {t}",
                "arguments": [],
                "disabled": False,
            }
            for t in manifest.get("tools", [])
        ]
    # Last resort: scan builtin list
    builtin_result = _list_builtin_servers("", 1)
    for s in builtin_result["servers"]:
        if s["id"] == server_id:
            return [
                {
                    "name": _namespace_tool(server_id, t),
                    "description": f"{_connector_namespace(server_id)} tool: {t}",
                    "arguments": [],
                    "disabled": False,
                }
                for t in s.get("tools", [])
            ]
    return []


def invalidate_tool_cache(server_id: str):
    _tool_schema_cache.pop(server_id, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_server(row) -> dict:
    d = dict(row)
    for field in ("available_tools", "install_spec", "registry_metadata"):
        if d.get(field) and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    d.pop("credentials", None)  # never leak encrypted credentials
    # Hoist manifest_tools + auth_schema from the on-disk manifest for builtin connectors
    _enrich_with_manifest(d)
    return d


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Platform connector tool invocation
# ---------------------------------------------------------------------------

_INVOKE_TIMEOUT = 30  # seconds per tool call


async def invoke_connector_tool(
    server_id: str,
    tool_name: str,
    args: dict,
    user_uuid: Optional[str] = None,
) -> dict:
    """
    Invoke a tool on a platform connector.

    Dispatches to the appropriate ConnectorInvocationStrategy based on the
    connector's connector_type field.  Currently supported:
      - mcp_stdio  (default): spawns subprocess, sends MCP protocol over stdio
      - mcp_http:             HTTP/SSE MCP transport (not yet implemented)

    For connectors with requires_user_auth (e.g. uderia-google), injects user
    OAuth tokens from messaging_identities alongside admin credentials.
    """
    server = get_server(server_id)
    if not server:
        return {"status": "error", "error": f"Connector '{server_id}' not found."}

    connector_type = server.get("connector_type") or CONNECTOR_TYPE_MCP_STDIO
    strategy = _INVOCATION_STRATEGIES.get(connector_type)
    if strategy is None:
        return {
            "status": "error",
            "error": f"Unknown connector type '{connector_type}' for '{server_id}'. "
                     f"Supported types: {list(_INVOCATION_STRATEGIES)}",
        }

    # Strip connector namespace prefix before calling the MCP server process.
    # The LLM plans with namespaced names (e.g. google__read_emails) but the
    # MCP server only knows the original name (read_emails).
    original_tool_name = _strip_namespace(tool_name)

    # Build environment: inherit current env + admin credentials + user tokens
    env = dict(os.environ)
    creds = get_server_credentials(server_id)
    for k, v in creds.items():
        if v:
            env[k] = str(v)
    if server.get("requires_user_auth") and user_uuid:
        _inject_user_tokens(server_id, user_uuid, env)

    try:
        return await asyncio.wait_for(
            strategy.invoke_tool(server, original_tool_name, args, env),
            timeout=_INVOKE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"status": "error", "error": f"Tool '{tool_name}' timed out after {_INVOKE_TIMEOUT}s."}
    except Exception as exc:
        logger.error(f"invoke_connector_tool({server_id!r}, {tool_name!r}) failed: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}


def _inject_generic_tokens(server_id: str, platform: str, user_uuid: str, env: dict):
    """
    Generic token injection for connectors without a registered module.

    For oauth2 connectors: injects {PLATFORM}_ACCESS_TOKEN / {PLATFORM}_REFRESH_TOKEN.
    For api_key / token connectors: injects via auth_schema.env_key if specified,
    otherwise falls back to {PLATFORM}_ACCESS_TOKEN.
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT access_token, refresh_token FROM messaging_identities "
            "WHERE user_uuid = ? AND platform = ?",
            (user_uuid, platform),
        ).fetchone()
    if not row:
        return
    f = _platform_fernet()
    manifest = _get_builtin_manifest(server_id)
    auth_schema = manifest.get("auth_schema", {}) or {}
    auth_type = auth_schema.get("type", "oauth2")
    env_key = auth_schema.get("env_key")

    if auth_type in ("token", "api_key") and env_key:
        if row["access_token"]:
            env[env_key] = f.decrypt(row["access_token"].encode()).decode()
    else:
        prefix = platform.upper()
        if row["access_token"]:
            env[f"{prefix}_ACCESS_TOKEN"] = f.decrypt(row["access_token"].encode()).decode()
        if row["refresh_token"]:
            env[f"{prefix}_REFRESH_TOKEN"] = f.decrypt(row["refresh_token"].encode()).decode()


def _inject_user_tokens(server_id: str, user_uuid: str, env: dict):
    """
    Inject per-user OAuth tokens into the subprocess environment.

    Delegates to the connector module registered for this server_id (via
    connectors/registry.py).  The connector module must expose:
      inject_env_tokens(user_uuid: str, env: dict) -> None

    Falls back to a generic DB lookup that sets PLATFORM_ACCESS_TOKEN /
    PLATFORM_REFRESH_TOKEN env vars for connectors that don't implement the
    function yet.
    """
    try:
        from trusted_data_agent.connectors.registry import server_id_to_platform, get as get_connector
        platform = server_id_to_platform(server_id)
        if not platform:
            return
        mod = get_connector(platform)
        if mod is None:
            return
        if hasattr(mod, "inject_env_tokens"):
            mod.inject_env_tokens(user_uuid, env)
        else:
            _inject_generic_tokens(server_id, platform, user_uuid, env)
    except Exception as exc:
        logger.warning(f"Could not inject user tokens for connector '{server_id}' / user {user_uuid}: {exc}")


async def _call_via_mcp_stdio(proc: asyncio.subprocess.Process, tool_name: str, args: dict) -> dict:
    """Send MCP initialize + tools/call over the process stdin/stdout and return parsed result."""

    def _send(obj: dict) -> bytes:
        return (json.dumps(obj) + "\n").encode("utf-8")

    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "uderia-platform", "version": "1.0.0"},
    }}
    call_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": tool_name,
        "arguments": args,
    }}
    init_done = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    stdin_data = _send(init_req) + _send(init_done) + _send(call_req)
    proc.stdin.write(stdin_data)
    await proc.stdin.drain()
    proc.stdin.close()

    init_resp = None
    call_resp = None
    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = msg.get("id")
        if rid == 1:
            init_resp = msg
        elif rid == 2:
            call_resp = msg
            break

    if call_resp is None:
        try:
            stderr_raw = await proc.stderr.read(2000)
            stderr_txt = stderr_raw.decode("utf-8", errors="replace").strip()
        except Exception:
            stderr_txt = ""
        return {"status": "error", "error": stderr_txt or "No response from connector."}

    if "error" in call_resp:
        return {"status": "error", "error": call_resp["error"].get("message", str(call_resp["error"]))}

    result = call_resp.get("result", {})
    content_list = result.get("content", [])
    if content_list:
        text = content_list[0].get("text", "")
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "status" not in parsed:
                parsed["status"] = "success"
            return parsed if isinstance(parsed, dict) else {"status": "success", "result": parsed}
        except json.JSONDecodeError:
            return {"status": "success", "result": text}

    return {"status": "success", "result": result}


def get_connector_for_tool(tool_name: str) -> Optional[str]:
    """
    Return the connector_id that owns the given (namespaced) tool name.

    Tool names are namespaced (e.g. ``google__read_emails``) so the lookup is
    an exact match against the cached schemas, which also use namespaced names.
    Used by invoke_mcp_tool in adapter.py to route platform tool calls.
    """
    with _get_conn() as conn:
        connectors = conn.execute(
            "SELECT id FROM platform_connectors WHERE enabled = 1"
        ).fetchall()

    for row in connectors:
        cid = row["id"]
        schemas = _get_cached_tool_schemas(cid)
        if any(t["name"] == tool_name for t in schemas):
            return cid

    return None
