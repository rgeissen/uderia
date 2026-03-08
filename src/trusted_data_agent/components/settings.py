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

def is_component_available(component_id: str) -> bool:
    """
    Check whether a specific component is available under current settings.
    mode=all -> always True.  mode=selective -> True unless in disabled list.
    """
    settings = get_component_settings()
    if settings.get("components_mode", "all") == "all":
        return True
    disabled = settings.get("disabled_components", [])
    return component_id not in disabled


def are_user_components_enabled() -> bool:
    """Check whether custom component import is allowed."""
    return get_component_settings().get("user_components_enabled", True)


def is_component_marketplace_enabled() -> bool:
    """Check whether the component marketplace is enabled."""
    return get_component_settings().get("user_components_marketplace_enabled", True)
