"""
Extension governance settings helper.

Loads / saves admin-controlled settings from the extension_settings table.
Provides convenience predicates used by enforcement points in rest_routes.py.
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

def get_extension_settings() -> dict:
    """
    Load all extension_settings rows into a dict.

    Returns e.g.:
        {
            "extensions_mode": "all",
            "disabled_extensions": [],
            "user_extensions_enabled": True,
            "user_extensions_marketplace_enabled": True
        }
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_key, setting_value FROM extension_settings")
        rows = cursor.fetchall()
        conn.close()

        settings = {}
        for key, value in rows:
            settings[key] = _parse_value(key, value)
        return settings
    except Exception as e:
        logger.error(f"Failed to load extension settings: {e}", exc_info=True)
        # Safe defaults — everything available
        return {
            "extensions_mode": "all",
            "disabled_extensions": [],
            "user_extensions_enabled": True,
            "user_extensions_marketplace_enabled": True,
        }


def _parse_value(key: str, raw: str):
    """Convert stored string value to typed Python value."""
    if key == "disabled_extensions":
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

def save_extension_settings(settings: dict, admin_uuid: str) -> None:
    """
    Upsert changed keys into the extension_settings table.
    Only updates keys that are present in *settings*.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        for key, value in settings.items():
            str_value = _to_string(key, value)
            cursor.execute(
                "INSERT INTO extension_settings (setting_key, setting_value, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET "
                "setting_value = excluded.setting_value, "
                "updated_at = excluded.updated_at, "
                "updated_by = excluded.updated_by",
                (key, str_value, now, admin_uuid),
            )
        conn.commit()
        conn.close()
        logger.info(f"Extension settings updated by admin {admin_uuid}: {list(settings.keys())}")
    except Exception as e:
        logger.error(f"Failed to save extension settings: {e}", exc_info=True)
        raise


def _to_string(key: str, value) -> str:
    """Convert typed Python value to string for DB storage."""
    if key == "disabled_extensions":
        return json.dumps(value if isinstance(value, list) else [])
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------

def is_extension_available(ext_id: str) -> bool:
    """
    Check whether a specific extension is available under current settings.
    mode=all → always True.  mode=selective → True unless in disabled list.
    """
    settings = get_extension_settings()
    if settings.get("extensions_mode", "all") == "all":
        return True
    disabled = settings.get("disabled_extensions", [])
    return ext_id not in disabled


def are_user_extensions_enabled() -> bool:
    """Check whether custom extension creation is allowed."""
    return get_extension_settings().get("user_extensions_enabled", True)


def is_marketplace_enabled() -> bool:
    """Check whether the extension marketplace is enabled."""
    return get_extension_settings().get("user_extensions_marketplace_enabled", True)
