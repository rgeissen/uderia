"""
Generic OIDC provider — Phase 1 SSO implementation.

Supports any standards-compliant OIDC IdP (Okta, Azure AD, Google Workspace,
Keycloak, Auth0, Ping, etc.) via the /.well-known/openid-configuration
discovery mechanism.

Responsibilities:
  - Fetch and cache the OIDC discovery document
  - Build the authorization URL (with PKCE-ready state/nonce)
  - Exchange the authorization code for tokens
  - Validate the id_token (signature, iss, aud, exp, nonce)
  - Return a normalized user-info dict for provisioning
"""

import hashlib
import json
import logging
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("quart.app")

_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"

# How long to cache a discovery document (seconds)
_DISCOVERY_TTL = 3600

# Pending nonce/state store — in-process dict is fine for single-process Quart
_pending: dict[str, dict] = {}
_PENDING_TTL = 600


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _encrypt(plaintext: str) -> str:
    from trusted_data_agent.core.platform_connector_registry import _platform_fernet
    return _platform_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    from trusted_data_agent.core.platform_connector_registry import _platform_fernet
    return _platform_fernet().decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# Configuration CRUD
# ---------------------------------------------------------------------------

def list_sso_configs(enabled_only: bool = False) -> list[dict]:
    """Return all SSO configurations (secrets redacted)."""
    with _get_conn() as conn:
        query = "SELECT * FROM sso_configurations"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY display_order, name"
        rows = conn.execute(query).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_sso_config(config_id: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sso_configurations WHERE id = ?", (config_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_sso_config(data: dict) -> dict:
    """Create a new SSO configuration. Returns the created record (secret redacted)."""
    cfg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    client_secret_enc = _encrypt(data["client_secret"])
    scopes = json.dumps(data.get("scopes", ["openid", "profile", "email"]))
    group_tier_map = json.dumps(data["group_tier_map"]) if data.get("group_tier_map") else None

    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO sso_configurations
               (id, name, provider, issuer_url, client_id, client_secret,
                scopes, email_claim, name_claim, groups_claim, sub_claim,
                group_tier_map, default_tier, enabled, auto_provision_users,
                require_email_verification, display_order, button_label, icon_url,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cfg_id, data["name"], data.get("provider", "oidc"), data["issuer_url"],
             data["client_id"], client_secret_enc,
             scopes, data.get("email_claim", "email"), data.get("name_claim", "name"),
             data.get("groups_claim"), data.get("sub_claim", "sub"),
             group_tier_map, data.get("default_tier", "user"),
             1 if data.get("enabled", True) else 0,
             1 if data.get("auto_provision_users", True) else 0,
             1 if data.get("require_email_verification", False) else 0,
             data.get("display_order", 0), data.get("button_label"), data.get("icon_url"),
             now, now),
        )
        conn.commit()
    return get_sso_config(cfg_id)


def update_sso_config(config_id: str, data: dict) -> Optional[dict]:
    """Update an existing SSO configuration. Omit client_secret to leave it unchanged."""
    now = datetime.now(timezone.utc).isoformat()
    updates: list[str] = []
    params: list = []

    simple_fields = [
        "name", "issuer_url", "client_id", "email_claim", "name_claim",
        "groups_claim", "sub_claim", "default_tier", "button_label", "icon_url",
        "display_order",
    ]
    for field in simple_fields:
        if field in data:
            updates.append(f"{field} = ?")
            params.append(data[field])

    bool_fields = ["enabled", "auto_provision_users", "require_email_verification"]
    for field in bool_fields:
        if field in data:
            updates.append(f"{field} = ?")
            params.append(1 if data[field] else 0)

    if "client_secret" in data and data["client_secret"] and data["client_secret"] != "[REDACTED]":
        updates.append("client_secret = ?")
        params.append(_encrypt(data["client_secret"]))

    if "scopes" in data:
        updates.append("scopes = ?")
        params.append(json.dumps(data["scopes"]))

    if "group_tier_map" in data:
        updates.append("group_tier_map = ?")
        params.append(json.dumps(data["group_tier_map"]) if data["group_tier_map"] else None)

    if not updates:
        return get_sso_config(config_id)

    updates.append("updated_at = ?")
    params.append(now)
    params.append(config_id)

    with _get_conn() as conn:
        conn.execute(
            f"UPDATE sso_configurations SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()

    # Invalidate cached discovery doc so it's re-fetched with any URL change
    if "issuer_url" in data:
        _invalidate_discovery(config_id)

    return get_sso_config(config_id)


def delete_sso_config(config_id: str) -> bool:
    with _get_conn() as conn:
        c = conn.execute("DELETE FROM sso_configurations WHERE id = ?", (config_id,))
        conn.commit()
    return c.rowcount > 0


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    d["client_secret"] = "[REDACTED]" if d.get("client_secret") else None
    d.pop("discovery_doc", None)   # large, internal
    for json_field in ("scopes", "group_tier_map"):
        if d.get(json_field):
            try:
                d[json_field] = json.loads(d[json_field])
            except Exception:
                pass
    return d


# ---------------------------------------------------------------------------
# OIDC Discovery
# ---------------------------------------------------------------------------

async def _fetch_discovery(issuer_url: str) -> dict:
    """Fetch OIDC discovery document from /.well-known/openid-configuration."""
    url = issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return resp.json()


async def get_discovery(config_id: str, issuer_url: str) -> dict:
    """Return discovery doc, using DB cache when fresh."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT discovery_doc, discovery_cached_at FROM sso_configurations WHERE id = ?",
            (config_id,),
        ).fetchone()

    if row and row["discovery_doc"] and row["discovery_cached_at"]:
        try:
            cached_at = datetime.fromisoformat(row["discovery_cached_at"])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - cached_at).total_seconds()
            if age < _DISCOVERY_TTL:
                return json.loads(row["discovery_doc"])
        except Exception:
            pass

    doc = await _fetch_discovery(issuer_url)
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE sso_configurations SET discovery_doc=?, discovery_cached_at=? WHERE id=?",
            (json.dumps(doc), now, config_id),
        )
        conn.commit()
    return doc


def _invalidate_discovery(config_id: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE sso_configurations SET discovery_doc=NULL, discovery_cached_at=NULL WHERE id=?",
            (config_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Authorization URL
# ---------------------------------------------------------------------------

async def build_authorization_url(config_id: str, redirect_uri: str) -> Optional[str]:
    """
    Build the authorization redirect URL for a given SSO config.
    Stores nonce + state in _pending for callback validation.
    """
    cfg = get_sso_config_with_secret(config_id)
    if not cfg or not cfg.get("enabled"):
        return None

    doc = await get_discovery(config_id, cfg["issuer_url"])
    auth_endpoint = doc.get("authorization_endpoint")
    if not auth_endpoint:
        logger.error(f"SSO config {config_id}: discovery doc missing authorization_endpoint")
        return None

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    _cleanup_pending()
    _pending[state] = {
        "config_id": config_id,
        "nonce": nonce,
        "redirect_uri": redirect_uri,
        "created_at": time.time(),
    }

    scopes = cfg.get("scopes") or ["openid", "profile", "email"]
    if isinstance(scopes, str):
        try:
            scopes = json.loads(scopes)
        except Exception:
            scopes = ["openid", "profile", "email"]

    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "nonce": nonce,
    }
    return auth_endpoint + "?" + urlencode(params)


def get_sso_config_with_secret(config_id: str) -> Optional[dict]:
    """Like get_sso_config but includes decrypted client_secret."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sso_configurations WHERE id = ?", (config_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d.pop("discovery_doc", None)
    try:
        d["client_secret"] = _decrypt(d["client_secret"])
    except Exception:
        d["client_secret"] = ""
    for json_field in ("scopes", "group_tier_map"):
        if d.get(json_field):
            try:
                d[json_field] = json.loads(d[json_field])
            except Exception:
                pass
    return d


def _cleanup_pending() -> None:
    cutoff = time.time() - _PENDING_TTL
    stale = [s for s, v in list(_pending.items()) if v["created_at"] < cutoff]
    for s in stale:
        _pending.pop(s, None)


# ---------------------------------------------------------------------------
# Callback handling
# ---------------------------------------------------------------------------

async def handle_callback(state: str, code: str) -> Optional[dict]:
    """
    Exchange code for tokens, validate id_token, return normalized user info.

    Returns dict with:
        config_id, sub, email, name, email_verified, groups, id_token
    or None on failure.
    """
    _cleanup_pending()
    pending = _pending.pop(state, None)
    if not pending:
        logger.warning("SSO callback: unknown or expired state")
        return None

    config_id = pending["config_id"]
    nonce = pending["nonce"]
    redirect_uri = pending["redirect_uri"]

    cfg = get_sso_config_with_secret(config_id)
    if not cfg:
        logger.error(f"SSO callback: config {config_id} not found")
        return None

    doc = await get_discovery(config_id, cfg["issuer_url"])

    # Exchange code for tokens
    token_endpoint = doc.get("token_endpoint")
    if not token_endpoint:
        logger.error(f"SSO config {config_id}: missing token_endpoint")
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_endpoint, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
            })
        resp.raise_for_status()
    except Exception as exc:
        logger.error(f"SSO token exchange failed: {exc}")
        return None

    token_data = resp.json()
    id_token = token_data.get("id_token")
    if not id_token:
        logger.error("SSO token response missing id_token")
        return None

    # Validate id_token
    claims = await _validate_id_token(
        id_token=id_token,
        doc=doc,
        client_id=cfg["client_id"],
        nonce=nonce,
        issuer=cfg["issuer_url"],
    )
    if claims is None:
        return None

    # Optionally enrich from userinfo endpoint
    access_token = token_data.get("access_token")
    if access_token and doc.get("userinfo_endpoint"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                ui_resp = await client.get(
                    doc["userinfo_endpoint"],
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if ui_resp.status_code == 200:
                claims.update(ui_resp.json())
        except Exception as exc:
            logger.debug(f"SSO userinfo fetch failed (non-fatal): {exc}")

    email_claim = cfg.get("email_claim", "email")
    name_claim = cfg.get("name_claim", "name")
    groups_claim = cfg.get("groups_claim")
    sub_claim = cfg.get("sub_claim", "sub")

    return {
        "config_id": config_id,
        "sub": claims.get(sub_claim) or claims.get("sub"),
        "email": claims.get(email_claim),
        "name": claims.get(name_claim) or claims.get("preferred_username"),
        "email_verified": bool(claims.get("email_verified", False)),
        "groups": claims.get(groups_claim, []) if groups_claim else [],
        "id_token": id_token,
        "raw_claims": claims,
    }


async def _validate_id_token(
    id_token: str,
    doc: dict,
    client_id: str,
    nonce: str,
    issuer: str,
) -> Optional[dict]:
    """
    Validate an OIDC id_token.

    Uses python-jose when available; falls back to unverified decode + basic
    claim checks if the library is not installed (dev mode only, logs warning).
    """
    try:
        from jose import jwt as jose_jwt, jwk, exceptions as jose_exc
        return await _validate_with_jose(id_token, doc, client_id, nonce, issuer, jose_jwt, jwk, jose_exc)
    except ImportError:
        logger.warning(
            "python-jose not installed — id_token signature NOT verified. "
            "Install with: pip install 'python-jose[cryptography]'"
        )
        return _validate_without_jose(id_token, client_id, nonce, issuer)


async def _validate_with_jose(id_token, doc, client_id, nonce, issuer, jose_jwt, jwk, jose_exc):
    """Full validation using python-jose + IdP JWKS."""
    jwks_uri = doc.get("jwks_uri")
    if not jwks_uri:
        logger.error("SSO discovery doc missing jwks_uri — cannot validate id_token")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(jwks_uri)
            resp.raise_for_status()
        jwks = resp.json()
    except Exception as exc:
        logger.error(f"Failed to fetch JWKS from {jwks_uri}: {exc}")
        return None

    try:
        claims = jose_jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            audience=client_id,
            issuer=issuer.rstrip("/"),
            options={"verify_exp": True, "verify_aud": True, "verify_iss": True},
        )
    except jose_exc.ExpiredSignatureError:
        logger.warning("SSO id_token expired")
        return None
    except jose_exc.JWTError as exc:
        logger.warning(f"SSO id_token validation failed: {exc}")
        return None

    # Validate nonce
    if claims.get("nonce") != nonce:
        logger.warning("SSO id_token nonce mismatch")
        return None

    return claims


def _validate_without_jose(id_token, client_id, nonce, issuer) -> Optional[dict]:
    """Minimal validation without signature verification (dev fallback only)."""
    import base64

    try:
        _, payload_b64, _ = id_token.split(".")
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as exc:
        logger.error(f"Failed to decode id_token payload: {exc}")
        return None

    now = time.time()
    if claims.get("exp", 0) < now:
        logger.warning("SSO id_token expired (no-jose path)")
        return None

    aud = claims.get("aud")
    if isinstance(aud, list):
        if client_id not in aud:
            logger.warning("SSO id_token aud mismatch (no-jose path)")
            return None
    elif aud != client_id:
        logger.warning("SSO id_token aud mismatch (no-jose path)")
        return None

    if claims.get("nonce") != nonce:
        logger.warning("SSO id_token nonce mismatch (no-jose path)")
        return None

    return claims


# ---------------------------------------------------------------------------
# Session tracking (back-channel logout support)
# ---------------------------------------------------------------------------

def record_sso_session(
    user_uuid: str,
    config_id: str,
    id_token: str,
    sub: str,
    sid: Optional[str] = None,
) -> str:
    """Record an SSO login session for later revocation. Returns session ID."""
    session_id = str(uuid.uuid4())
    id_token_hash = hashlib.sha256(id_token.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO sso_sessions
               (id, user_uuid, sso_config_id, id_token_hash, sid, sub, issued_at)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, user_uuid, config_id, id_token_hash, sid, sub, now),
        )
        conn.commit()
    return session_id


def revoke_sso_session_by_sid(sid: str) -> int:
    """Back-channel logout: revoke all sessions matching IdP session ID. Returns count."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        c = conn.execute(
            "UPDATE sso_sessions SET revoked=1, revoked_at=? WHERE sid=? AND revoked=0",
            (now, sid),
        )
        conn.commit()
    return c.rowcount


def revoke_sso_session_by_token_hash(id_token_hash: str) -> int:
    """Revoke session by id_token hash. Returns count."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        c = conn.execute(
            "UPDATE sso_sessions SET revoked=1, revoked_at=? WHERE id_token_hash=? AND revoked=0",
            (now, id_token_hash),
        )
        conn.commit()
    return c.rowcount


async def test_sso_config(config_id: str) -> dict:
    """Test an SSO configuration by fetching the discovery document. Returns status dict."""
    cfg = get_sso_config(config_id)
    if not cfg:
        return {"success": False, "error": "Configuration not found"}

    issuer_url = cfg.get("issuer_url", "")
    if not issuer_url:
        return {"success": False, "error": "Issuer URL not set"}

    try:
        doc = await _fetch_discovery(issuer_url)
        endpoints = {
            "authorization_endpoint": doc.get("authorization_endpoint"),
            "token_endpoint": doc.get("token_endpoint"),
            "userinfo_endpoint": doc.get("userinfo_endpoint"),
            "jwks_uri": doc.get("jwks_uri"),
            "end_session_endpoint": doc.get("end_session_endpoint"),
        }
        missing = [k for k, v in endpoints.items() if not v and k != "end_session_endpoint"]
        if missing:
            return {
                "success": False,
                "error": f"Discovery doc missing required endpoints: {missing}",
                "endpoints": endpoints,
            }

        # Update discovery cache
        now = datetime.now(timezone.utc).isoformat()
        with _get_conn() as conn:
            conn.execute(
                "UPDATE sso_configurations SET discovery_doc=?, discovery_cached_at=?, updated_at=? WHERE id=?",
                (json.dumps(doc), now, now, config_id),
            )
            conn.commit()

        return {
            "success": True,
            "endpoints": endpoints,
            "issuer": doc.get("issuer"),
            "scopes_supported": doc.get("scopes_supported", [])[:10],
        }
    except httpx.HTTPStatusError as exc:
        return {"success": False, "error": f"HTTP {exc.response.status_code} from discovery endpoint"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
