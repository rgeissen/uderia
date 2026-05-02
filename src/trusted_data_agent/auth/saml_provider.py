"""
SAML 2.0 Identity Provider integration — SSO Phase 2.

Supports any standards-compliant SAML 2.0 IdP (ADFS, Okta, Azure AD,
Shibboleth, Ping, OneLogin, etc.) using HTTP-Redirect for the AuthnRequest
and HTTP-POST for the Assertion Consumer Service (ACS).

Responsibilities:
  - Admin CRUD for SAML provider configurations
  - SP metadata XML generation (for IdP registration)
  - SAML AuthnRequest generation (redirect binding)
  - SAML Response validation via signxml (signature, issuer, time window)
  - User attribute extraction and normalization
  - Group → tier mapping shared with OIDC provisioner
"""

import base64
import hashlib
import json
import logging
import secrets
import sqlite3
import uuid
import zlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urljoin

logger = logging.getLogger("quart.app")

_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"

# Per-request state store for relay_state → config_id mapping
_pending: dict[str, str] = {}
_PENDING_TTL = 600  # seconds

SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
SAMLP_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"


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


def _row_to_dict(row) -> Optional[dict]:
    if row is None:
        return None
    d = dict(row)
    # Redact private key, expose [REDACTED] sentinel so UI knows it's set
    d["sp_private_key"] = "[REDACTED]" if d.get("sp_private_key") else None
    # Parse JSON fields
    for f in ("group_tier_map",):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except Exception:
                pass
    return d


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_saml_configs(enabled_only: bool = False) -> list[dict]:
    with _get_conn() as conn:
        q = "SELECT * FROM saml_configurations"
        if enabled_only:
            q += " WHERE enabled = 1"
        q += " ORDER BY display_order, name"
        rows = conn.execute(q).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_saml_config(config_id: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM saml_configurations WHERE id = ?", (config_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def _get_saml_config_raw(config_id: str) -> Optional[dict]:
    """Return config with decrypted sp_private_key for internal use."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM saml_configurations WHERE id = ?", (config_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("sp_private_key"):
        try:
            d["sp_private_key"] = _decrypt(d["sp_private_key"])
        except Exception:
            d["sp_private_key"] = None
    for f in ("group_tier_map",):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except Exception:
                pass
    return d


def create_saml_config(data: dict) -> dict:
    cfg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    sp_key_enc = _encrypt(data["sp_private_key"]) if data.get("sp_private_key") else None
    group_tier_map = json.dumps(data["group_tier_map"]) if data.get("group_tier_map") else None

    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO saml_configurations
               (id, name, sp_entity_id, sp_acs_url, sp_private_key, sp_certificate,
                idp_entity_id, idp_sso_url, idp_slo_url, idp_certificate,
                email_attr, name_attr, groups_attr,
                default_tier, group_tier_map, auto_provision_users,
                enabled, button_label, icon_url, display_order, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cfg_id, data["name"],
             data["sp_entity_id"], data.get("sp_acs_url"),
             sp_key_enc, data.get("sp_certificate"),
             data["idp_entity_id"], data["idp_sso_url"], data.get("idp_slo_url"),
             data["idp_certificate"],
             data.get("email_attr", "email"), data.get("name_attr", "displayName"),
             data.get("groups_attr"),
             data.get("default_tier", "user"), group_tier_map,
             1 if data.get("auto_provision_users", True) else 0,
             1 if data.get("enabled", True) else 0,
             data.get("button_label"), data.get("icon_url"),
             data.get("display_order", 0), now, now),
        )
        conn.commit()
    return get_saml_config(cfg_id)


def update_saml_config(config_id: str, data: dict) -> Optional[dict]:
    now = datetime.now(timezone.utc).isoformat()
    updates, params = [], []

    simple = ["name", "sp_entity_id", "sp_acs_url", "sp_certificate",
              "idp_entity_id", "idp_sso_url", "idp_slo_url", "idp_certificate",
              "email_attr", "name_attr", "groups_attr", "default_tier",
              "button_label", "icon_url", "display_order"]
    for f in simple:
        if f in data:
            updates.append(f"{f} = ?"); params.append(data[f])

    for f in ("enabled", "auto_provision_users"):
        if f in data:
            updates.append(f"{f} = ?"); params.append(1 if data[f] else 0)

    if "sp_private_key" in data and data["sp_private_key"] and data["sp_private_key"] != "[REDACTED]":
        updates.append("sp_private_key = ?"); params.append(_encrypt(data["sp_private_key"]))

    if "group_tier_map" in data:
        updates.append("group_tier_map = ?")
        params.append(json.dumps(data["group_tier_map"]) if data["group_tier_map"] else None)

    if not updates:
        return get_saml_config(config_id)

    updates.append("updated_at = ?"); params.append(now)
    params.append(config_id)

    with _get_conn() as conn:
        conn.execute(f"UPDATE saml_configurations SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    return get_saml_config(config_id)


def delete_saml_config(config_id: str) -> bool:
    with _get_conn() as conn:
        c = conn.execute("DELETE FROM saml_configurations WHERE id = ?", (config_id,))
        conn.commit()
    return c.rowcount > 0


# ---------------------------------------------------------------------------
# SP Metadata XML
# ---------------------------------------------------------------------------

def get_sp_metadata(config_id: str, base_url: str) -> Optional[str]:
    """
    Generate SP metadata XML for this SAML configuration.
    Admins paste this URL (or the XML) into their IdP's SP registration.
    """
    cfg = _get_saml_config_raw(config_id)
    if not cfg:
        return None

    acs_url = cfg.get("sp_acs_url") or f"{base_url}/api/v1/auth/saml/{config_id}/acs"
    entity_id = cfg["sp_entity_id"]

    cert_block = ""
    if cfg.get("sp_certificate"):
        # Strip PEM headers for the XML element
        cert_lines = [l for l in cfg["sp_certificate"].splitlines()
                      if l and not l.startswith("-----")]
        cert_block = f"""
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="{DS_NS}">
        <ds:X509Data>
          <ds:X509Certificate>{"".join(cert_lines)}</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </md:KeyDescriptor>"""

    xml = f"""<?xml version="1.0"?>
<md:EntityDescriptor
    xmlns:md="{MD_NS}"
    xmlns:ds="{DS_NS}"
    entityID="{entity_id}"
    validUntil="{(datetime.now(timezone.utc) + timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ')}">
  <md:SPSSODescriptor
      AuthnRequestsSigned="false"
      WantAssertionsSigned="true"
      protocolSupportEnumeration="{SAMLP_NS}">
{cert_block}
    <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
    <md:NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:unspecified</md:NameIDFormat>
    <md:AssertionConsumerService
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        Location="{acs_url}"
        index="1" isDefault="true"/>
  </md:SPSSODescriptor>
</md:EntityDescriptor>"""
    return xml


# ---------------------------------------------------------------------------
# SAML AuthnRequest (redirect binding)
# ---------------------------------------------------------------------------

def build_saml_auth_request(config_id: str, base_url: str) -> Optional[tuple[str, str]]:
    """
    Build SAML AuthnRequest and return (redirect_url, relay_state).
    Stores relay_state → config_id in _pending for callback verification.
    """
    cfg = _get_saml_config_raw(config_id)
    if not cfg or not cfg.get("enabled"):
        return None

    acs_url = cfg.get("sp_acs_url") or f"{base_url}/api/v1/auth/saml/{config_id}/acs"
    relay_state = secrets.token_urlsafe(24)
    request_id = f"id-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    authn_request = f"""<samlp:AuthnRequest
    xmlns:samlp="{SAMLP_NS}"
    xmlns:saml="{SAML_NS}"
    ID="{request_id}"
    Version="2.0"
    IssueInstant="{now}"
    Destination="{cfg['idp_sso_url']}"
    AssertionConsumerServiceURL="{acs_url}"
    ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">
  <saml:Issuer>{cfg['sp_entity_id']}</saml:Issuer>
  <samlp:NameIDPolicy
      AllowCreate="true"
      Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"/>
</samlp:AuthnRequest>"""

    # Deflate + base64 encode per SAML redirect binding spec
    compressed = zlib.compress(authn_request.encode("utf-8"))[2:-4]  # raw deflate
    encoded = base64.b64encode(compressed).decode("ascii")

    params = urlencode({"SAMLRequest": encoded, "RelayState": relay_state})
    redirect_url = f"{cfg['idp_sso_url']}?{params}"

    # Store pending state
    _cleanup_pending()
    _pending[relay_state] = {
        "config_id": config_id,
        "request_id": request_id,
        "created_at": datetime.now(timezone.utc).timestamp(),
    }

    return redirect_url, relay_state


# ---------------------------------------------------------------------------
# ACS — process SAML Response
# ---------------------------------------------------------------------------

def process_saml_response(config_id: str, saml_response_b64: str) -> Optional[dict]:
    """
    Validate SAML Response and extract normalized user info.
    Returns dict with: sub, email, name, email_verified, groups, raw_attrs
    Returns None on validation failure.
    """
    cfg = _get_saml_config_raw(config_id)
    if not cfg:
        logger.error(f"SAML: unknown config_id={config_id}")
        return None

    try:
        response_xml = base64.b64decode(saml_response_b64)
    except Exception as e:
        logger.error(f"SAML: base64 decode failed: {e}")
        return None

    try:
        from lxml import etree
        root = etree.fromstring(response_xml)
    except Exception as e:
        logger.error(f"SAML: XML parse failed: {e}")
        return None

    # Check status
    status_code = root.find(
        f".//{{{SAMLP_NS}}}StatusCode"
    )
    if status_code is None or "Success" not in (status_code.get("Value") or ""):
        status_val = status_code.get("Value") if status_code is not None else "missing"
        logger.error(f"SAML: non-success status: {status_val}")
        return None

    # Verify signature
    idp_cert = cfg["idp_certificate"]
    if not _verify_saml_signature(root, idp_cert):
        return None

    # Extract assertion
    assertion = root.find(f"{{{SAML_NS}}}Assertion")
    if assertion is None:
        logger.error("SAML: no Assertion element found")
        return None

    # Time window validation
    conditions = assertion.find(f"{{{SAML_NS}}}Conditions")
    if conditions is not None:
        not_before = conditions.get("NotBefore")
        not_on_or_after = conditions.get("NotOnOrAfter")
        now = datetime.now(timezone.utc)
        skew = timedelta(seconds=300)
        if not_before:
            nb = datetime.fromisoformat(not_before.replace("Z", "+00:00"))
            if now < nb - skew:
                logger.error(f"SAML: assertion not yet valid (NotBefore={not_before})")
                return None
        if not_on_or_after:
            nooa = datetime.fromisoformat(not_on_or_after.replace("Z", "+00:00"))
            if now > nooa + skew:
                logger.error(f"SAML: assertion expired (NotOnOrAfter={not_on_or_after})")
                return None

    # Issuer check
    issuer_el = assertion.find(f"{{{SAML_NS}}}Issuer")
    if issuer_el is not None:
        issuer = (issuer_el.text or "").strip()
        if issuer != cfg["idp_entity_id"]:
            logger.error(f"SAML: issuer mismatch: got={issuer} expected={cfg['idp_entity_id']}")
            return None

    # Extract NameID (primary user identifier)
    name_id_el = assertion.find(
        f".//{{{SAML_NS}}}Subject/{{{SAML_NS}}}NameID"
    )
    sub = (name_id_el.text or "").strip() if name_id_el is not None else ""

    # Extract attributes
    attrs: dict[str, list[str]] = {}
    for attr_el in assertion.findall(f".//{{{SAML_NS}}}Attribute"):
        attr_name = attr_el.get("Name", "")
        values = [
            (v.text or "").strip()
            for v in attr_el.findall(f"{{{SAML_NS}}}AttributeValue")
            if v.text
        ]
        if attr_name and values:
            attrs[attr_name] = values

    email_attr = cfg.get("email_attr") or "email"
    name_attr = cfg.get("name_attr") or "displayName"
    groups_attr = cfg.get("groups_attr") or ""

    # Fallback: email may be the NameID if it looks like an email
    email_raw = (attrs.get(email_attr) or [])
    email = email_raw[0] if email_raw else (sub if "@" in sub else "")
    name = (attrs.get(name_attr) or attrs.get("cn") or attrs.get("name") or [sub])[0]
    groups = attrs.get(groups_attr, []) if groups_attr else []

    if not email:
        logger.error("SAML: no email found in assertion")
        return None

    return {
        "sub": sub or email,
        "email": email,
        "name": name,
        "email_verified": True,  # SAML assertions are inherently trusted
        "groups": groups,
        "raw_attrs": attrs,
    }


def _verify_saml_signature(root, idp_cert_pem: str) -> bool:
    """
    Verify XML digital signature on SAML Response or Assertion using signxml.
    Returns True if valid, False otherwise.
    """
    try:
        from signxml import XMLVerifier
        from lxml import etree

        # Normalise PEM cert — signxml accepts PEM string directly
        cert_pem = idp_cert_pem.strip()
        if not cert_pem.startswith("-----"):
            # Bare base64 — wrap in PEM headers
            cert_pem = f"-----BEGIN CERTIFICATE-----\n{cert_pem}\n-----END CERTIFICATE-----"

        verifier = XMLVerifier()
        verifier.verify(root, x509_cert=cert_pem)
        return True

    except Exception as e:
        logger.error(f"SAML: signature verification failed: {e}")
        return False


def _cleanup_pending():
    """Evict expired pending states."""
    cutoff = datetime.now(timezone.utc).timestamp() - _PENDING_TTL
    expired = [k for k, v in _pending.items() if v.get("created_at", 0) < cutoff]
    for k in expired:
        del _pending[k]


def consume_relay_state(relay_state: str) -> Optional[str]:
    """Return config_id for a relay_state and remove it. Returns None if unknown/expired."""
    _cleanup_pending()
    entry = _pending.pop(relay_state, None)
    return entry["config_id"] if entry else None


# ---------------------------------------------------------------------------
# Group sync logging (Phase 3)
# ---------------------------------------------------------------------------

def log_sync_event(
    user_uuid: str,
    config_id: Optional[str],
    config_type: str,
    sync_type: str,
    old_tier: Optional[str],
    new_tier: Optional[str],
    old_groups: list,
    new_groups: list,
) -> str:
    """Record a group-sync event. Returns the event id."""
    event_id = str(uuid.uuid4())
    changed = 1 if (old_tier != new_tier or sorted(old_groups) != sorted(new_groups)) else 0
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO sso_sync_events
               (id, user_uuid, config_id, config_type, sync_type,
                old_tier, new_tier, old_groups, new_groups, changed, synced_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id, user_uuid, config_id, config_type, sync_type,
             old_tier, new_tier,
             json.dumps(old_groups), json.dumps(new_groups),
             changed, now),
        )
        conn.commit()
    return event_id


def list_sso_users(user_uuid: Optional[str] = None) -> list[dict]:
    """Return SSO-provisioned users with their current groups and last sync."""
    with _get_conn() as conn:
        if user_uuid:
            rows = conn.execute(
                "SELECT id, username, email, full_name, profile_tier, is_admin, "
                "auth_method, sso_config_id, sso_groups, last_login_at "
                "FROM users WHERE id = ? AND auth_method IN ('oidc','saml')",
                (user_uuid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, username, email, full_name, profile_tier, is_admin, "
                "auth_method, sso_config_id, sso_groups, last_login_at "
                "FROM users WHERE auth_method IN ('oidc','saml') ORDER BY last_login_at DESC"
            ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        try:
            d["sso_groups"] = json.loads(d["sso_groups"]) if d.get("sso_groups") else []
        except Exception:
            d["sso_groups"] = []
        result.append(d)
    return result


def get_sync_history(user_uuid: str, limit: int = 20) -> list[dict]:
    """Return recent sync events for a user."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sso_sync_events WHERE user_uuid = ? "
            "ORDER BY synced_at DESC LIMIT ?",
            (user_uuid, limit)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for f in ("old_groups", "new_groups"):
            try:
                d[f] = json.loads(d[f]) if d.get(f) else []
            except Exception:
                d[f] = []
        result.append(d)
    return result
