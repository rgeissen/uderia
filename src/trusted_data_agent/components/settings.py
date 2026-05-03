"""
Component governance settings helper.

Loads / saves admin-controlled settings from the component_settings table.
Provides convenience predicates used by enforcement points in rest_routes.py.
Mirrors extensions/settings.py pattern exactly.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("quart.app")

# Resolve DB path once (same pattern as database.py)
_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"


def _get_conn():
    return sqlite3.connect(str(_DB_PATH))


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_component_settings() -> dict:
    """
    Load all component_settings rows into a dict.

    Returns e.g.:
        {
            "components_mode": "all",
            "disabled_components": [],
            "user_components_enabled": True,
            "user_components_marketplace_enabled": True
        }
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_key, setting_value FROM component_settings")
        rows = cursor.fetchall()
        conn.close()

        settings = {}
        for key, value in rows:
            settings[key] = _parse_value(key, value)
        return settings
    except Exception as e:
        logger.error(f"Failed to load component settings: {e}", exc_info=True)
        # Safe defaults — everything available
        return {
            "components_mode": "all",
            "disabled_components": [],
            "user_components_enabled": True,
            "user_components_marketplace_enabled": True,
        }


def _parse_value(key: str, raw: str):
    """Convert stored string value to typed Python value."""
    if key == "disabled_components":
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if raw in ("true", "True", "1"):
        return True
    if raw in ("false", "False", "0"):
        return False
    return raw


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_component_settings(settings: dict, admin_uuid: str) -> None:
    """
    Upsert changed keys into the component_settings table.
    Only updates keys that are present in *settings*.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        for key, value in settings.items():
            str_value = _to_string(key, value)
            cursor.execute(
                "INSERT INTO component_settings (setting_key, setting_value, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET "
                "setting_value = excluded.setting_value, "
                "updated_at = excluded.updated_at, "
                "updated_by = excluded.updated_by",
                (key, str_value, now, admin_uuid),
            )
        conn.commit()
        conn.close()
        logger.info(f"Component settings updated by admin {admin_uuid}: {list(settings.keys())}")
    except Exception as e:
        logger.error(f"Failed to save component settings: {e}", exc_info=True)
        raise


def _to_string(key: str, value) -> str:
    """Convert typed Python value to string for DB storage."""
    if key == "disabled_components":
        return json.dumps(value if isinstance(value, list) else [])
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------

def is_component_available(component_id: str, user_uuid: str | None = None) -> bool:
    """
    Check whether a specific component is available.

    Governance chain:
      1. Global: components_mode + disabled_components list
      2. Per-user override: user_component_settings table (admin-set)
      3. Per-profile: componentConfig checked separately in manager.py

    If *user_uuid* is provided the per-user override is also checked.
    """
    settings = get_component_settings()
    # Global gate — disabled_components is always authoritative regardless of mode
    disabled = settings.get("disabled_components", [])
    if component_id in disabled:
        return False

    # Per-user override
    if user_uuid:
        override = get_user_component_override(user_uuid, component_id)
        if override is not None:
            return override

    return True


def are_user_components_enabled() -> bool:
    """Check whether custom component import is allowed."""
    return get_component_settings().get("user_components_enabled", True)


def is_component_marketplace_enabled() -> bool:
    """Check whether the component marketplace is enabled."""
    return get_component_settings().get("user_components_marketplace_enabled", True)


def is_profile_scheduler_enabled() -> bool:
    """Return True if user-created profile jobs are globally enabled."""
    return _get_bool_setting("profile_scheduler_enabled", default=True)


def is_platform_scheduler_enabled() -> bool:
    """Return True if platform maintenance jobs are globally enabled."""
    return _get_bool_setting("platform_scheduler_enabled", default=True)


def _get_bool_setting(key: str, default: bool = True) -> bool:
    """Read a single boolean key from component_settings."""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM component_settings WHERE setting_key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            val = _parse_value(key, row[0])
            return bool(val) if not isinstance(val, str) else default
        return default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Per-user component overrides
# ---------------------------------------------------------------------------

def get_user_component_override(user_uuid: str, component_id: str) -> bool | None:
    """
    Return the admin-set override for (user_uuid, component_id).
    Returns True (granted), False (blocked), or None (no override — inherit global).
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_enabled FROM user_component_settings WHERE user_uuid = ? AND component_id = ?",
            (user_uuid, component_id),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return bool(row[0])
    except Exception as e:
        logger.error(f"Failed to get user component override: {e}")
        return None


def set_user_component_override(
    user_uuid: str, component_id: str, is_enabled: bool, admin_uuid: str, note: str = ""
) -> None:
    """Create or update a per-user component override."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO user_component_settings "
            "(user_uuid, component_id, is_enabled, note, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_uuid, component_id) DO UPDATE SET "
            "is_enabled = excluded.is_enabled, note = excluded.note, "
            "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (user_uuid, component_id, 1 if is_enabled else 0, note, now, admin_uuid),
        )
        conn.commit()
        conn.close()
        logger.info(f"User component override set: user={user_uuid} component={component_id} enabled={is_enabled} by={admin_uuid}")
    except Exception as e:
        logger.error(f"Failed to set user component override: {e}", exc_info=True)
        raise


def delete_user_component_override(user_uuid: str, component_id: str) -> None:
    """Remove a per-user component override (user reverts to global default)."""
    try:
        conn = _get_conn()
        conn.execute(
            "DELETE FROM user_component_settings WHERE user_uuid = ? AND component_id = ?",
            (user_uuid, component_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to delete user component override: {e}", exc_info=True)
        raise


def get_component_user_overrides(component_id: str) -> list[dict]:
    """
    Return all per-user overrides for a given component.
    Joins with users table to include display info.
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT ucs.user_uuid, ucs.is_enabled, ucs.note, ucs.updated_at, ucs.updated_by,
                      u.username, u.email, u.profile_tier
               FROM user_component_settings ucs
               LEFT JOIN users u ON u.id = ucs.user_uuid
               WHERE ucs.component_id = ?
               ORDER BY ucs.updated_at DESC""",
            (component_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        result = []
        for row in rows:
            result.append({
                "user_uuid": row[0],
                "is_enabled": bool(row[1]),
                "note": row[2] or "",
                "updated_at": row[3],
                "updated_by": row[4],
                "username": row[5] or row[0][:8],
                "email": row[6] or "",
                "tier": row[7] or "user",
            })
        return result
    except Exception as e:
        logger.error(f"Failed to get component user overrides: {e}", exc_info=True)
        return []


def get_all_users_with_component_access(component_id: str) -> list[dict]:
    """
    Return all users annotated with their effective access to a component.
    Users without an override show access='global' (inherits global setting).
    """
    global_available = is_component_available(component_id)
    overrides = {o["user_uuid"]: o for o in get_component_user_overrides(component_id)}
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, profile_tier FROM users ORDER BY username")
        users = cursor.fetchall()
        conn.close()
        result = []
        for (uuid_, username, email, tier) in users:
            if uuid_ in overrides:
                ov = overrides[uuid_]
                result.append({
                    "user_uuid": uuid_,
                    "username": username or uuid_[:8],
                    "email": email or "",
                    "tier": tier or "user",
                    "access_type": "override",
                    "is_enabled": ov["is_enabled"],
                    "note": ov["note"],
                    "updated_at": ov["updated_at"],
                    "updated_by": ov["updated_by"],
                })
            else:
                result.append({
                    "user_uuid": uuid_,
                    "username": username or uuid_[:8],
                    "email": email or "",
                    "tier": tier or "user",
                    "access_type": "global",
                    "is_enabled": global_available,
                    "note": "",
                    "updated_at": None,
                    "updated_by": None,
                })
        return result
    except Exception as e:
        logger.error(f"Failed to get all users with component access: {e}", exc_info=True)
        return []
