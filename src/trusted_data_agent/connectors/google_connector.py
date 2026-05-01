"""
Google OAuth connector (Track C).

Handles per-user Google OAuth flow, token storage in messaging_identities,
automatic token refresh, and revocation.

Admin configures GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET via:
  Admin Panel → MCP Servers → uderia-google (credentials section)

Users connect their own Google account via:
  Platform Components → MCP Servers → uderia-google → "Connect Google account"
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

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

_DEFAULT_SCOPES = " ".join([
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
])

SERVER_ID = "uderia-google"

# In-memory state store for CSRF protection: {state_token: {user_uuid, created_at}}
_pending_states: dict[str, dict] = {}
_STATE_TTL = 600  # 10 minutes


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


# ── Admin credentials ─────────────────────────────────────────────────────────

def get_google_client_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Return (client_id, client_secret) from admin-configured server credentials."""
    from trusted_data_agent.core.platform_connector_registry import get_server_credentials
    creds = get_server_credentials(SERVER_ID)
    return creds.get("GOOGLE_CLIENT_ID"), creds.get("GOOGLE_CLIENT_SECRET")


def get_scopes() -> str:
    """Return OAuth scopes from admin server config or use default."""
    from trusted_data_agent.core.platform_connector_registry import get_server
    server = get_server(SERVER_ID)
    if server:
        cfg = server.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        return cfg.get("SCOPES", _DEFAULT_SCOPES)
    return _DEFAULT_SCOPES


def is_configured() -> bool:
    """Return True if admin has configured Google client credentials."""
    client_id, client_secret = get_google_client_credentials()
    return bool(client_id and client_secret)


# ── OAuth flow ────────────────────────────────────────────────────────────────

def initiate_oauth(user_uuid: str, redirect_uri: str) -> Optional[str]:
    """
    Generate Google OAuth authorization URL.
    Returns the URL to redirect the user to, or None if not configured.
    """
    client_id, _ = get_google_client_credentials()
    if not client_id:
        logger.warning("Google connector: GOOGLE_CLIENT_ID not configured — cannot initiate OAuth.")
        return None

    state = str(uuid.uuid4())
    # Purge expired states before adding
    _cleanup_states()
    _pending_states[state] = {"user_uuid": user_uuid, "created_at": time.time()}

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": get_scopes(),
        "access_type": "offline",
        "prompt": "consent",  # Always request refresh_token
        "state": state,
    }
    return _GOOGLE_AUTH_URL + "?" + urlencode(params)


async def handle_callback(code: str, state: str, redirect_uri: str) -> Optional[dict]:
    """
    Exchange authorization code for tokens and store in messaging_identities.
    Returns {"email": ..., "user_uuid": ...} on success, None on failure.
    """
    _cleanup_states()
    state_data = _pending_states.pop(state, None)
    if not state_data:
        logger.warning("Google connector: Invalid or expired OAuth state token.")
        return None

    user_uuid = state_data["user_uuid"]
    client_id, client_secret = get_google_client_credentials()
    if not client_id:
        return None

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(_GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })

    if token_resp.status_code != 200:
        logger.error(f"Google token exchange failed ({token_resp.status_code}): {token_resp.text}")
        return None

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        logger.error("Google token exchange returned no access_token.")
        return None

    # Fetch user email
    email = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            info_resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if info_resp.status_code == 200:
            email = info_resp.json().get("email", "")
    except Exception as exc:
        logger.warning(f"Could not fetch Google userinfo: {exc}")

    expiry = datetime.fromtimestamp(
        time.time() + expires_in, tz=timezone.utc
    ).isoformat()

    store_tokens(user_uuid, email or "", access_token, refresh_token, expiry)
    logger.info(f"Google account connected for user {user_uuid}: {email}")
    return {"email": email, "user_uuid": user_uuid}


# ── Token storage ─────────────────────────────────────────────────────────────

def store_tokens(
    user_uuid: str,
    email: str,
    access_token: str,
    refresh_token: Optional[str],
    expiry: str,
):
    """Upsert encrypted tokens in messaging_identities."""
    enc_access = _encrypt(access_token) if access_token else None
    enc_refresh = _encrypt(refresh_token) if refresh_token else None
    now = _now()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO messaging_identities
               (user_uuid, platform, platform_user_id, access_token, refresh_token, token_expiry, updated_at)
               VALUES (?, 'google', ?, ?, ?, ?, ?)
               ON CONFLICT(user_uuid, platform) DO UPDATE SET
                   platform_user_id = excluded.platform_user_id,
                   access_token     = excluded.access_token,
                   refresh_token    = excluded.refresh_token,
                   token_expiry     = excluded.token_expiry,
                   updated_at       = excluded.updated_at""",
            (user_uuid, email, enc_access, enc_refresh, expiry, now),
        )
        conn.commit()


# ── Token retrieval with auto-refresh ────────────────────────────────────────

async def get_tokens(user_uuid: str) -> Optional[dict]:
    """
    Return decrypted tokens for a user. Refreshes automatically if expired.
    Returns None if not connected.
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM messaging_identities WHERE user_uuid = ? AND platform = 'google'",
            (user_uuid,),
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
                # Attempt refresh
                enc_refresh = row.get("refresh_token")
                if enc_refresh:
                    refresh_token = _decrypt(enc_refresh)
                    ok = await _do_refresh(user_uuid, refresh_token)
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
    """Use refresh_token to obtain a new access_token and update the DB."""
    client_id, client_secret = get_google_client_credentials()
    if not client_id:
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(_GOOGLE_TOKEN_URL, data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            })
    except Exception as exc:
        logger.warning(f"Token refresh HTTP error: {exc}")
        return False

    if resp.status_code != 200:
        logger.warning(f"Token refresh failed ({resp.status_code}): {resp.text}")
        return False

    data = resp.json()
    new_access = data.get("access_token")
    if not new_access:
        return False

    expires_in = data.get("expires_in", 3600)
    expiry = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc).isoformat()
    enc_access = _encrypt(new_access)
    now = _now()

    new_refresh = data.get("refresh_token")
    with _get_conn() as conn:
        if new_refresh:
            conn.execute(
                """UPDATE messaging_identities
                   SET access_token=?, refresh_token=?, token_expiry=?, updated_at=?
                   WHERE user_uuid=? AND platform='google'""",
                (_encrypt(new_access), _encrypt(new_refresh), expiry, now, user_uuid),
            )
        else:
            conn.execute(
                """UPDATE messaging_identities
                   SET access_token=?, token_expiry=?, updated_at=?
                   WHERE user_uuid=? AND platform='google'""",
                (enc_access, expiry, now, user_uuid),
            )
        conn.commit()

    logger.debug(f"Google access token refreshed for user {user_uuid}")
    return True


# ── Connection status ─────────────────────────────────────────────────────────

def get_connection_status(user_uuid: str) -> dict:
    """Return connection status dict for the UI."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT platform_user_id, token_expiry FROM messaging_identities WHERE user_uuid = ? AND platform = 'google'",
            (user_uuid,),
        ).fetchone()

    if not row:
        return {"connected": False, "configured": is_configured()}

    return {
        "connected": True,
        "email": row["platform_user_id"],
        "token_expiry": row["token_expiry"],
        "configured": is_configured(),
    }


# ── Disconnect / revoke ───────────────────────────────────────────────────────

async def disconnect(user_uuid: str):
    """Revoke Google tokens and remove from messaging_identities."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT access_token FROM messaging_identities WHERE user_uuid = ? AND platform = 'google'",
            (user_uuid,),
        ).fetchone()

    if row and row["access_token"]:
        try:
            access_token = _decrypt(row["access_token"])
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(_GOOGLE_REVOKE_URL, params={"token": access_token})
        except Exception as exc:
            logger.warning(f"Google token revocation failed (deleting locally anyway): {exc}")

    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM messaging_identities WHERE user_uuid = ? AND platform = 'google'",
            (user_uuid,),
        )
        conn.commit()

    logger.info(f"Google account disconnected for user {user_uuid}")


# ── Subprocess token injection ────────────────────────────────────────────────

def inject_env_tokens(user_uuid: str, env: dict):
    """
    Inject decrypted Google tokens into a subprocess env dict.
    Called by platform_connector_registry._inject_user_tokens() before spawning the server process.
    """
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT access_token, refresh_token FROM messaging_identities "
                "WHERE user_uuid = ? AND platform = 'google'",
                (user_uuid,),
            ).fetchone()
        if not row:
            return
        if row["access_token"]:
            env["GOOGLE_ACCESS_TOKEN"] = _decrypt(row["access_token"])
        if row["refresh_token"]:
            env["GOOGLE_REFRESH_TOKEN"] = _decrypt(row["refresh_token"])
    except Exception as exc:
        logger.warning(f"Could not inject Google tokens for user {user_uuid}: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cleanup_states():
    """Remove expired pending OAuth state tokens."""
    now = time.time()
    expired = [s for s, v in list(_pending_states.items()) if now - v["created_at"] > _STATE_TTL]
    for s in expired:
        _pending_states.pop(s, None)
