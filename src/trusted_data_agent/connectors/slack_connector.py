"""
Slack OAuth connector.

Handles per-user Slack OAuth2 flow, token storage in messaging_identities,
and revocation.

Slack bot tokens do not expire and have no refresh_token. The connector stores
the bot token as access_token with no expiry. For per-user (user) tokens,
expiry is also not applicable.

Admin configures SLACK_CLIENT_ID + SLACK_CLIENT_SECRET via:
  Admin Panel → Components → Connectors → uderia-slack (credentials section).

Users connect their own Slack workspace via:
  Platform Components → Connectors → uderia-slack → "Connect Slack"

Scopes (user token + bot token combined):
  channels:read  channels:history  chat:write  users:read
  search:read  files:read
"""

import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("quart.app")

SERVER_ID = "uderia-slack"
_PLATFORM = "slack"

_SLACK_AUTH_URL = "https://slack.com/oauth/v2/authorize"
_SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
_SLACK_REVOKE_URL = "https://slack.com/api/auth.revoke"
_SLACK_USER_INFO_URL = "https://slack.com/api/users.identity"

_DEFAULT_SCOPES = "channels:read channels:history chat:write users:read search:read files:read"
_DEFAULT_USER_SCOPES = "identity.basic identity.email"

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

def _get_admin_creds():
    """Return (client_id, client_secret)."""
    from trusted_data_agent.core.platform_connector_registry import get_server_credentials
    creds = get_server_credentials(SERVER_ID)
    return creds.get("SLACK_CLIENT_ID"), creds.get("SLACK_CLIENT_SECRET")


def is_configured() -> bool:
    client_id, client_secret = _get_admin_creds()
    return bool(client_id and client_secret)


# ── OAuth flow ────────────────────────────────────────────────────────────────

def initiate_oauth(user_uuid: str, redirect_uri: str) -> Optional[str]:
    client_id, _ = _get_admin_creds()
    if not client_id:
        logger.warning("Slack connector: SLACK_CLIENT_ID not configured.")
        return None

    state = str(uuid.uuid4())
    _cleanup_states()
    _pending_states[state] = {"user_uuid": user_uuid, "created_at": time.time()}

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": _DEFAULT_SCOPES,
        "user_scope": _DEFAULT_USER_SCOPES,
        "state": state,
    }
    return _SLACK_AUTH_URL + "?" + urlencode(params)


async def handle_callback(code: str, state: str, redirect_uri: str) -> Optional[dict]:
    _cleanup_states()
    state_data = _pending_states.pop(state, None)
    if not state_data:
        logger.warning("Slack connector: Invalid or expired OAuth state token.")
        return None

    user_uuid = state_data["user_uuid"]
    client_id, client_secret = _get_admin_creds()
    if not client_id:
        return None

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(_SLACK_TOKEN_URL, data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        })

    if token_resp.status_code != 200:
        logger.error(f"Slack token exchange HTTP failed ({token_resp.status_code}): {token_resp.text}")
        return None

    token_data = token_resp.json()
    if not token_data.get("ok"):
        logger.error(f"Slack token exchange error: {token_data.get('error')}")
        return None

    # Prefer user token (for identity), fall back to bot token
    authed_user = token_data.get("authed_user", {})
    user_token = authed_user.get("access_token")
    bot_token = token_data.get("access_token")

    # Use bot token as the primary stored token (doesn't expire)
    access_token = bot_token or user_token
    if not access_token:
        logger.error("Slack token exchange returned no access_token.")
        return None

    # Fetch display name using user token if available
    display_name = None
    team_name = token_data.get("team", {}).get("name", "")
    if user_token:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                id_resp = await client.get(
                    _SLACK_USER_INFO_URL,
                    headers={"Authorization": f"Bearer {user_token}"},
                )
            if id_resp.status_code == 200:
                id_data = id_resp.json()
                if id_data.get("ok"):
                    user_info = id_data.get("user", {})
                    email = id_data.get("user", {}).get("email", "")
                    name = user_info.get("name", "")
                    display_name = email or name
        except Exception as exc:
            logger.warning(f"Could not fetch Slack user info: {exc}")

    if not display_name and team_name:
        display_name = team_name

    # Slack bot tokens don't expire — store with far-future token_expiry = None
    _store_tokens(user_uuid, display_name or "", access_token, user_token, None)
    logger.info(f"Slack account connected for user {user_uuid}: {display_name}")
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
    # Slack tokens don't expire — skip expiry check
    return {
        "access_token": _decrypt(row["access_token"]) if row.get("access_token") else None,
        "refresh_token": _decrypt(row["refresh_token"]) if row.get("refresh_token") else None,
        "token_expiry": row.get("token_expiry"),
        "email": row.get("platform_user_id"),
    }


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
    # Revoke the token before deleting
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT access_token FROM messaging_identities WHERE user_uuid = ? AND platform = ?",
                (user_uuid, _PLATFORM),
            ).fetchone()
        if row and row["access_token"]:
            token = _decrypt(row["access_token"])
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(_SLACK_REVOKE_URL, data={"token": token})
    except Exception as exc:
        logger.warning(f"Could not revoke Slack token for user {user_uuid}: {exc}")

    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM messaging_identities WHERE user_uuid = ? AND platform = ?",
            (user_uuid, _PLATFORM),
        )
        conn.commit()
    logger.info(f"Slack account disconnected for user {user_uuid}")


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
            env["SLACK_BOT_TOKEN"] = _decrypt(row["access_token"])
        if row["refresh_token"]:
            env["SLACK_USER_TOKEN"] = _decrypt(row["refresh_token"])
    except Exception as exc:
        logger.warning(f"Could not inject Slack tokens for user {user_uuid}: {exc}")
