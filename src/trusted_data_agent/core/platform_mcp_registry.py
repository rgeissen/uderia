"""
Platform MCP Server Registry

Manages admin-governed capability MCP servers (browser, files, shell, web, google).
Strictly separate from user-configured data source servers (Configuration → MCP Servers).

Governance chain: admin enables + sets policy → user assigns to profiles →
                  profile selects tool subset → execution merges into tool context
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
# Internal helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _platform_fernet():
    """Return a Fernet instance keyed to the platform (not per-user)."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt = b'platform_mcp_registry'
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
            "SELECT id, name, url, enabled, is_builtin FROM mcp_registry_sources ORDER BY is_builtin DESC, name"
        ).fetchall()
    return [dict(r) for r in rows]


def add_registry_source(name: str, url: str) -> dict:
    """Add an enterprise private registry source."""
    import uuid
    source_id = f"registry-{uuid.uuid4().hex[:8]}"
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO mcp_registry_sources (id, name, url, enabled, is_builtin) VALUES (?, ?, ?, 1, 0)",
            (source_id, name, url)
        )
        conn.commit()
    return {"id": source_id, "name": name, "url": url, "enabled": 1, "is_builtin": 0}


def delete_registry_source(source_id: str) -> bool:
    """Delete a non-builtin registry source."""
    with _get_conn() as conn:
        row = conn.execute("SELECT is_builtin FROM mcp_registry_sources WHERE id = ?", (source_id,)).fetchone()
        if not row or row["is_builtin"]:
            return False
        conn.execute("DELETE FROM mcp_registry_sources WHERE id = ?", (source_id,))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Server listing (proxies to external registry APIs)
# ---------------------------------------------------------------------------

async def list_registry_servers(source_id: str, search: str = "", page: int = 1, cursor: str = "") -> dict:
    """
    Browse servers from a registry source.
    Built-in source returns locally registered first-party servers.
    External sources proxy GET /v0.1/servers to the registry URL.
    cursor is forwarded to external registries that use cursor-based pagination
    (e.g. registry.modelcontextprotocol.io uses metadata.nextCursor).
    """
    with _get_conn() as conn:
        source = conn.execute(
            "SELECT id, name, url, enabled FROM mcp_registry_sources WHERE id = ?", (source_id,)
        ).fetchone()

    if not source:
        return {"servers": [], "total": 0, "page": page}

    if source["url"] == "builtin://":
        return _list_builtin_servers(search, page)

    return await _proxy_registry_request(source["url"], search, page, cursor=cursor)


def _load_builtin_manifests() -> list[dict]:
    """Load first-party server manifests from mcp_servers/builtin/*/manifest.json."""
    repo_root = Path(__file__).resolve().parents[3]
    builtin_dir = repo_root / "mcp_servers" / "builtin"
    servers = []
    if not builtin_dir.exists():
        return servers
    for manifest_path in sorted(builtin_dir.glob("*/manifest.json")):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            # Build an install_spec for local stdio execution
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
    """Return the list of Uderia first-party platform servers from disk manifests."""
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
    Proxy GET /v0.1/servers to an external MCP registry.
    Supports both page-based (built-in compatible) and cursor-based pagination
    (official MCP Registry uses metadata.nextCursor).
    The raw registry response is returned as-is so the frontend can read
    metadata.nextCursor for progressive loading.
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
# Server installation / connection
# ---------------------------------------------------------------------------

def install_server(source_id: str, server_id: str, server_data: dict) -> dict:
    """
    Register a server as installed/connected.
    For package-based servers: records install intent (actual pip install is separate).
    For remote servers: records connection details.
    """
    import uuid
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM platform_mcp_servers WHERE id = ?", (server_id,)
        ).fetchone()

        now = _now()
        if existing:
            conn.execute(
                """UPDATE platform_mcp_servers SET
                    source_id=?, name=?, display_name=?, description=?, version=?,
                    registry_metadata=?, install_spec=?, install_status=?,
                    requires_user_auth=?, updated_at=?
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
                    1 if server_data.get("requires_user_auth") else 0,
                    now,
                    server_id,
                )
            )
        else:
            conn.execute(
                """INSERT INTO platform_mcp_servers
                   (id, source_id, name, display_name, description, version,
                    registry_metadata, install_spec, install_status,
                    enabled, requires_user_auth, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'installed', 0, ?, ?, ?)""",
                (
                    server_id,
                    source_id,
                    server_data.get("name", server_id),
                    server_data.get("display_name", server_id),
                    server_data.get("description", ""),
                    server_data.get("version", "0.0.0"),
                    json.dumps(server_data.get("registry_metadata", {})),
                    json.dumps(server_data.get("install_spec", {})),
                    1 if server_data.get("requires_user_auth") else 0,
                    now, now,
                )
            )
        conn.commit()

    return get_server(server_id)


def get_server(server_id: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM platform_mcp_servers WHERE id = ?", (server_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_server(row)


def list_installed_servers() -> list[dict]:
    """Return all servers registered in platform_mcp_servers (installed or connected)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM platform_mcp_servers ORDER BY name"
        ).fetchall()
    return [_row_to_server(r) for r in rows]


def update_server_governance(server_id: str, updates: dict) -> Optional[dict]:
    """Update admin governance settings for a platform server."""
    allowed = {
        "enabled", "available_tools", "auto_opt_in",
        "user_can_opt_out", "user_can_configure_tools", "config",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_server(server_id)

    # Serialize list fields
    if "available_tools" in fields and isinstance(fields["available_tools"], list):
        fields["available_tools"] = json.dumps(fields["available_tools"])

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [server_id]

    with _get_conn() as conn:
        conn.execute(f"UPDATE platform_mcp_servers SET {set_clause} WHERE id = ?", values)
        conn.commit()
    return get_server(server_id)


def update_server_credentials(server_id: str, credentials: dict) -> bool:
    """Encrypt and store sensitive credentials for a platform server."""
    encrypted = _encrypt(credentials)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE platform_mcp_servers SET credentials = ?, updated_at = ? WHERE id = ?",
            (encrypted, _now(), server_id)
        )
        conn.commit()
    return True


def get_server_credentials(server_id: str) -> dict:
    """Decrypt and return credentials for a platform server."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT credentials FROM platform_mcp_servers WHERE id = ?", (server_id,)
        ).fetchone()
    if not row or not row["credentials"]:
        return {}
    return _decrypt(row["credentials"])


def delete_server(server_id: str) -> bool:
    """Remove a platform server (cascades to profile settings via ON DELETE CASCADE)."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM platform_mcp_servers WHERE id = ?", (server_id,))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Effective tool resolution (the governance chain)
# ---------------------------------------------------------------------------

def get_effective_tool_names(profile_id: str) -> set[str]:
    """
    Return the set of platform server tool names that are active for this profile,
    after applying the full governance chain:
      admin enabled → auto_opt_in → user opt-in/out → available_tools → user_tools
    """
    return {t["name"] for t in get_effective_tools(profile_id)}


def get_effective_tools(profile_id: str) -> list[dict]:
    """
    Return structured tool definitions for all platform servers active on this profile.
    Used by load_and_categorize_mcp_resources() to merge platform tools into APP_STATE.
    """
    with _get_conn() as conn:
        servers = conn.execute(
            "SELECT * FROM platform_mcp_servers WHERE enabled = 1"
        ).fetchall()
        settings_rows = conn.execute(
            "SELECT server_id, opted_in, user_tools FROM profile_platform_mcp_settings WHERE profile_id = ?",
            (profile_id,)
        ).fetchall()

    settings = {r["server_id"]: dict(r) for r in settings_rows}
    active_tools = []

    for server_row in servers:
        server = _row_to_server(server_row)
        sid = server["id"]
        pref = settings.get(sid, {})
        opted_in = pref.get("opted_in")  # None / 1 / 0

        # Determine if this server is active for this profile
        if server["auto_opt_in"]:
            if server["user_can_opt_out"] and opted_in == 0:
                continue  # user explicitly opted out
            # else: active (auto opt-in, user hasn't opted out)
        else:
            if opted_in != 1:
                continue  # not auto opted-in, user hasn't explicitly opted in

        # Resolve permitted tool set
        admin_tools = server.get("available_tools")  # list or None
        user_tools_raw = pref.get("user_tools")
        user_tools = json.loads(user_tools_raw) if user_tools_raw else None

        if admin_tools is None:
            permitted = None  # all tools
        else:
            permitted = set(admin_tools)
            if server["user_can_configure_tools"] and user_tools:
                permitted = permitted & set(user_tools)

        # Fetch live tool schemas from the running server
        server_tools = _get_cached_tool_schemas(sid)
        for tool in server_tools:
            if permitted is None or tool["name"] in permitted:
                active_tools.append(tool)

    return active_tools


def has_effective_tools(profile_id: str) -> bool:
    """Return True if this profile has at least one active platform server tool."""
    return bool(get_effective_tool_names(profile_id))


# ---------------------------------------------------------------------------
# Per-profile user settings (opt-in/out, tool selection)
# ---------------------------------------------------------------------------

def get_profile_server_settings(profile_id: str) -> list[dict]:
    """
    Return all enabled platform servers with the user's current opt-in state for this profile.
    """
    with _get_conn() as conn:
        servers = conn.execute(
            "SELECT * FROM platform_mcp_servers WHERE enabled = 1 ORDER BY name"
        ).fetchall()
        settings_rows = conn.execute(
            "SELECT server_id, opted_in, user_tools FROM profile_platform_mcp_settings WHERE profile_id = ?",
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
            "server_id": sid,  # alias for JS consumers
            "opted_in": pref.get("opted_in"),
            "user_tools": json.loads(pref["user_tools"]) if pref.get("user_tools") else None,
        })
    return result


def update_profile_server_setting(profile_id: str, server_id: str, opted_in: Optional[int], user_tools: Optional[list]) -> bool:
    """Upsert a profile's opt-in state and tool selection for a platform server."""
    user_tools_json = json.dumps(user_tools) if user_tools is not None else None
    now = _now()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO profile_platform_mcp_settings (profile_id, server_id, opted_in, user_tools, updated_at)
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
# Tool schema cache (avoids repeated subprocess calls per request)
# ---------------------------------------------------------------------------

_tool_schema_cache: dict = {}  # server_id → {tools: list, ts: float}
_TOOL_CACHE_TTL = 300  # 5 minutes


def _get_cached_tool_schemas(server_id: str) -> list[dict]:
    """
    Return cached tool schemas for a platform server, or fetch live if stale.
    Falls back to the builtin manifest if the server process is not running.
    """
    import time
    cached = _tool_schema_cache.get(server_id)
    if cached and (time.time() - cached["ts"]) < _TOOL_CACHE_TTL:
        return cached["tools"]

    tools = _fetch_tool_schemas_from_manifest(server_id)
    _tool_schema_cache[server_id] = {"tools": tools, "ts": time.time()}
    return tools


def _fetch_tool_schemas_from_manifest(server_id: str) -> list[dict]:
    """
    Return tool schemas from the builtin server manifest.
    When a server is running, these will be superseded by live discovery.
    """
    builtin_result = _list_builtin_servers("", 1)
    for s in builtin_result["servers"]:
        if s["id"] == server_id:
            return [{"name": t, "description": f"{server_id} tool: {t}", "arguments": [], "disabled": False}
                    for t in s.get("tools", [])]
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
    return d


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Platform tool invocation (per-call stdio subprocess)
# ---------------------------------------------------------------------------

_INVOKE_TIMEOUT = 30  # seconds per tool call


async def invoke_platform_tool(
    server_id: str,
    tool_name: str,
    args: dict,
    user_uuid: Optional[str] = None,
) -> dict:
    """
    Invoke a tool on a builtin platform MCP server.

    Spawns the server process once per call (stateless, no persistent session),
    sends initialize + tools/call over stdio, and returns the parsed result dict.

    For servers with requires_user_auth (e.g. uderia-google), injects user OAuth
    tokens from messaging_identities alongside the admin credentials.
    """
    import asyncio
    import sys

    server = get_server(server_id)
    if not server:
        return {"status": "error", "error": f"Platform server '{server_id}' not found."}

    # Resolve the server entry point
    repo_root = Path(__file__).resolve().parents[3]
    install_spec = server.get("install_spec") or {}
    if isinstance(install_spec, str):
        try:
            install_spec = json.loads(install_spec)
        except Exception:
            install_spec = {}

    cmd_args = install_spec.get("args", [])
    if not cmd_args:
        # Fall back: derive from manifest entry_point
        builtin_dir = repo_root / "mcp_servers" / "builtin" / server_id
        entry = builtin_dir / "server.py"
        if not entry.exists():
            return {"status": "error", "error": f"Server entry point not found for '{server_id}'."}
        cmd_args = [str(entry)]

    # Build environment: inherit current env + admin credentials + user tokens
    env = dict(os.environ)
    creds = get_server_credentials(server_id)
    for k, v in creds.items():
        if v:
            env[k] = str(v)

    # Inject user OAuth tokens for servers that require per-user auth
    if server.get("requires_user_auth") and user_uuid:
        _inject_user_tokens(server_id, user_uuid, env)

    # Spawn the MCP server process
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, *cmd_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except Exception as exc:
        logger.error(f"Failed to spawn platform server '{server_id}': {exc}")
        return {"status": "error", "error": f"Could not start '{server_id}': {exc}"}

    try:
        return await asyncio.wait_for(
            _call_via_stdio(proc, tool_name, args),
            timeout=_INVOKE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return {"status": "error", "error": f"Tool '{tool_name}' timed out after {_INVOKE_TIMEOUT}s."}
    except Exception as exc:
        logger.error(f"Platform tool '{tool_name}' invocation error: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}
    finally:
        try:
            proc.kill()
        except Exception:
            pass


def _inject_user_tokens(server_id: str, user_uuid: str, env: dict):
    """Inject per-user OAuth tokens into the subprocess environment.

    Delegates to the connector module registered for this server_id, if any.
    The connector module must expose an `inject_env_tokens(user_uuid, env)` function.
    Falls back to a direct DB lookup for connectors that don't implement that function.
    """
    try:
        from trusted_data_agent.connectors.registry import server_id_to_platform, get as get_connector
        platform = server_id_to_platform(server_id)
        if not platform:
            return  # Not a user-auth connector
        mod = get_connector(platform)
        if mod is None:
            return
        if hasattr(mod, "inject_env_tokens"):
            mod.inject_env_tokens(user_uuid, env)
        else:
            # Generic fallback: read encrypted tokens from messaging_identities and
            # set PLATFORM_ACCESS_TOKEN / PLATFORM_REFRESH_TOKEN env vars.
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT access_token, refresh_token FROM messaging_identities "
                    "WHERE user_uuid = ? AND platform = ?",
                    (user_uuid, platform),
                ).fetchone()
            if not row:
                return
            f = _platform_fernet()
            prefix = platform.upper()
            if row["access_token"]:
                env[f"{prefix}_ACCESS_TOKEN"] = f.decrypt(row["access_token"].encode()).decode()
            if row["refresh_token"]:
                env[f"{prefix}_REFRESH_TOKEN"] = f.decrypt(row["refresh_token"].encode()).decode()
    except Exception as exc:
        logger.warning(f"Could not inject user tokens for server '{server_id}' / user {user_uuid}: {exc}")


async def _call_via_stdio(proc: asyncio.subprocess.Process, tool_name: str, args: dict) -> dict:
    """
    Run MCP initialize + tools/call over the process stdin/stdout and return parsed result.
    """
    import json

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

    # Write all requests at once
    stdin_data = _send(init_req) + _send(init_done) + _send(call_req)
    proc.stdin.write(stdin_data)
    await proc.stdin.drain()
    proc.stdin.close()

    # Read responses
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
            break  # Got what we need

    if call_resp is None:
        # Read stderr for diagnostics
        try:
            stderr_raw = await proc.stderr.read(2000)
            stderr_txt = stderr_raw.decode("utf-8", errors="replace").strip()
        except Exception:
            stderr_txt = ""
        err_msg = stderr_txt or "No response from server."
        return {"status": "error", "error": err_msg}

    if "error" in call_resp:
        return {"status": "error", "error": call_resp["error"].get("message", str(call_resp["error"]))}

    # Extract text content from MCP result
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


def get_server_for_tool(tool_name: str) -> Optional[str]:
    """
    Return the server_id that owns the given tool name across all enabled platform servers.
    Used by invoke_mcp_tool to route platform tool calls.
    """
    builtin_result = _list_builtin_servers("", 1)
    builtin_map = {s["id"]: s.get("tools", []) for s in builtin_result["servers"]}

    with _get_conn() as conn:
        servers = conn.execute(
            "SELECT id FROM platform_mcp_servers WHERE enabled = 1"
        ).fetchall()

    for row in servers:
        sid = row["id"]
        tools = builtin_map.get(sid, [])
        if tool_name in tools:
            return sid

    # Also check against cached tool schemas
    for sid in list(_tool_schema_cache.keys()):
        cached = _tool_schema_cache[sid]
        for t in cached.get("tools", []):
            if (isinstance(t, dict) and t.get("name") == tool_name) or t == tool_name:
                return sid

    return None
