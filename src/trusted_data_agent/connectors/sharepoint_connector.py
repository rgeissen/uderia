"""
Microsoft SharePoint OAuth connector.

Handles per-user Microsoft OAuth2 flow (Azure AD), token storage in
messaging_identities, automatic token refresh, and revocation.

Admin configures AZURE_CLIENT_ID + AZURE_CLIENT_SECRET (+ optional AZURE_TENANT_ID)
via Admin Panel → Components → Connectors → uderia-sharepoint (credentials section).

Users connect their own Microsoft account via:
  Platform Components → Connectors → uderia-sharepoint → "Connect Microsoft account"

Graph API scopes:
  Files.Read.All  Files.ReadWrite.All  Sites.Read.All  Sites.ReadWrite.All
  User.Read  offline_access
"""

import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("quart.app")

SERVER_ID = "uderia-sharepoint"
_PLATFORM = "sharepoint"

_MS_AUTHORITY_TMPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
_MS_GRAPH_ME = "https://graph.microsoft.com/v1.0/me"

_DEFAULT_SCOPES = " ".join([
    "Files.Read.All",
    "Files.ReadWrite.All",
    "Sites.Read.All",
    "Sites.ReadWrite.All",
    "User.Read",
    "offline_access",
])

_pending_states: dict[str, dict] = {}
_STATE_TTL = 600


# ── DB / encryption helpers ───────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    from trusted_data_agent.core.platform_connector_registry import _DB_PATH
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encrypt(plaintext: str) -> str:
    from trusted_data_agent.core.platform_connector_registry import _platform_fernet
    return _platform_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(token: str) -> str:
    from trusted_data_agent.core.platform_connector_registry import _platform_fernet
    return _platform_fernet().decrypt(token.encode()).decode()


def _cleanup_states():
    now = time.time()
    expired = [s for s, v in list(_pending_states.items()) if now - v["created_at"] > _STATE_TTL]
    for s in expired:
        _pending_states.pop(s, None)


# ── Admin credentials ─────────────────────────────────────────────────────────

def _get_admin_creds() -> Tuple[Optional[str], Optional[str], str]:
    """Return (client_id, client_secret, tenant_id)."""
    from trusted_data_agent.core.platform_connector_registry import get_server_credentials, get_server
    creds = get_server_credentials(SERVER_ID)
    client_id = creds.get("AZURE_CLIENT_ID")
    client_secret = creds.get("AZURE_CLIENT_SECRET")
    tenant = "common"
    server = get_server(SERVER_ID)
    if server:
        cfg = server.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        tenant = cfg.get("AZURE_TENANT_ID", "common") or "common"
    return client_id, client_secret, tenant


def is_configured() -> bool:
    client_id, client_secret, _ = _get_admin_creds()
    return bool(client_id and client_secret)


def _auth_url(tenant: str) -> str:
    return f"{_MS_AUTHORITY_TMPL.format(tenant=tenant)}/authorize"


def _token_url(tenant: str) -> str:
    return f"{_MS_AUTHORITY_TMPL.format(tenant=tenant)}/token"


# ── OAuth flow ────────────────────────────────────────────────────────────────

def initiate_oauth(user_uuid: str, redirect_uri: str) -> Optional[str]:
    client_id, _, tenant = _get_admin_creds()
    if not client_id:
        logger.warning("SharePoint connector: AZURE_CLIENT_ID not configured.")
        return None

    state = str(uuid.uuid4())
    _cleanup_states()
    _pending_states[state] = {"user_uuid": user_uuid, "created_at": time.time()}

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _DEFAULT_SCOPES,
        "response_mode": "query",
        "state": state,
        "prompt": "select_account",
    }
    return _auth_url(tenant) + "?" + urlencode(params)


async def handle_callback(code: str, state: str, redirect_uri: str) -> Optional[dict]:
    _cleanup_states()
    state_data = _pending_states.pop(state, None)
    if not state_data:
        logger.warning("SharePoint connector: Invalid or expired OAuth state token.")
        return None

    user_uuid = state_data["user_uuid"]
    client_id, client_secret, tenant = _get_admin_creds()
    if not client_id:
        return None

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(_token_url(tenant), data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "scope": _DEFAULT_SCOPES,
        })

    if token_resp.status_code != 200:
        logger.error(f"SharePoint token exchange failed ({token_resp.status_code}): {token_resp.text}")
        return None

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        logger.error("SharePoint token exchange returned no access_token.")
        return None

    display_name = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            me_resp = await client.get(
                _MS_GRAPH_ME,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if me_resp.status_code == 200:
            data = me_resp.json()
            display_name = data.get("userPrincipalName") or data.get("mail") or data.get("displayName")
    except Exception as exc:
        logger.warning(f"Could not fetch SharePoint user info: {exc}")

    expiry = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc).isoformat()
    _store_tokens(user_uuid, display_name or "", access_token, refresh_token, expiry)
    logger.info(f"SharePoint account connected for user {user_uuid}: {display_name}")
    return {"email": display_name, "user_uuid": user_uuid}


# ── Token storage ─────────────────────────────────────────────────────────────

def _store_tokens(user_uuid, identity, access_token, refresh_token, expiry):
    enc_access = _encrypt(access_token) if access_token else None
    enc_refresh = _encrypt(refresh_token) if refresh_token else None
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO messaging_identities
               (user_uuid, platform, platform_user_id, access_token, refresh_token, token_expiry, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_uuid, platform) DO UPDATE SET
                   platform_user_id = excluded.platform_user_id,
                   access_token     = excluded.access_token,
                   refresh_token    = excluded.refresh_token,
                   token_expiry     = excluded.token_expiry,
                   updated_at       = excluded.updated_at""",
            (user_uuid, _PLATFORM, identity, enc_access, enc_refresh, expiry, _now()),
        )
        conn.commit()


async def get_tokens(user_uuid: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM messaging_identities WHERE user_uuid = ? AND platform = ?",
            (user_uuid, _PLATFORM),
        ).fetchone()

    if not row:
        return None

    row = dict(row)
    expiry_str = row.get("token_expiry")
    if expiry_str:
        try:
            expiry_dt = datetime.fromisoformat(expiry_str)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            if expiry_dt <= datetime.now(timezone.utc):
                enc_refresh = row.get("refresh_token")
                if enc_refresh:
                    ok = await _do_refresh(user_uuid, _decrypt(enc_refresh))
                    if ok:
                        return await get_tokens(user_uuid)
                return None
        except Exception:
            pass

    return {
        "access_token": _decrypt(row["access_token"]) if row.get("access_token") else None,
        "refresh_token": _decrypt(row["refresh_token"]) if row.get("refresh_token") else None,
        "token_expiry": row.get("token_expiry"),
        "email": row.get("platform_user_id"),
    }


async def _do_refresh(user_uuid: str, refresh_token: str) -> bool:
    client_id, client_secret, tenant = _get_admin_creds()
    if not client_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(_token_url(tenant), data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "scope": _DEFAULT_SCOPES,
            })
    except Exception as exc:
        logger.warning(f"SharePoint token refresh HTTP error: {exc}")
        return False

    if resp.status_code != 200:
        logger.warning(f"SharePoint token refresh failed ({resp.status_code}): {resp.text}")
        return False

    data = resp.json()
    new_access = data.get("access_token")
    if not new_access:
        return False

    expires_in = data.get("expires_in", 3600)
    expiry = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc).isoformat()
    new_refresh = data.get("refresh_token", refresh_token)

    with _get_conn() as conn:
        conn.execute(
            """UPDATE messaging_identities
               SET access_token=?, refresh_token=?, token_expiry=?, updated_at=?
               WHERE user_uuid=? AND platform=?""",
            (_encrypt(new_access), _encrypt(new_refresh), expiry, _now(), user_uuid, _PLATFORM),
        )
        conn.commit()

    return True


# ── Connection status ─────────────────────────────────────────────────────────

def get_connection_status(user_uuid: str) -> dict:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT platform_user_id, token_expiry FROM messaging_identities WHERE user_uuid = ? AND platform = ?",
            (user_uuid, _PLATFORM),
        ).fetchone()

    if not row:
        return {"connected": False, "configured": is_configured()}

    return {
        "connected": True,
        "email": row["platform_user_id"],
        "token_expiry": row["token_expiry"],
        "configured": is_configured(),
    }


# ── Disconnect ────────────────────────────────────────────────────────────────

async def disconnect(user_uuid: str):
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM messaging_identities WHERE user_uuid = ? AND platform = ?",
            (user_uuid, _PLATFORM),
        )
        conn.commit()
    logger.info(f"SharePoint account disconnected for user {user_uuid}")


# ── Token injection ───────────────────────────────────────────────────────────

def inject_env_tokens(user_uuid: str, env: dict):
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT access_token, refresh_token FROM messaging_identities "
                "WHERE user_uuid = ? AND platform = ?",
                (user_uuid, _PLATFORM),
            ).fetchone()
        if not row:
            return
        if row["access_token"]:
            env["MS_SHAREPOINT_ACCESS_TOKEN"] = _decrypt(row["access_token"])
        if row["refresh_token"]:
            env["MS_SHAREPOINT_REFRESH_TOKEN"] = _decrypt(row["refresh_token"])
    except Exception as exc:
        logger.warning(f"Could not inject SharePoint tokens for user {user_uuid}: {exc}")
