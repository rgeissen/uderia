"""
Knowledge Graph marketplace governance settings helper.

Loads / saves admin-controlled settings from the kg_marketplace_settings table.
Mirrors skills/settings.py pattern exactly.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("quart.app")

_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"


def _get_conn():
    return sqlite3.connect(str(_DB_PATH))


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_kg_marketplace_settings() -> dict:
    """Load all kg_marketplace_settings rows into a dict."""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_key, setting_value FROM kg_marketplace_settings")
        rows = cursor.fetchall()
        conn.close()

        settings = {}
        for key, value in rows:
            settings[key] = _parse_value(value)
        return settings
    except Exception as e:
        logger.error(f"Failed to load KG marketplace settings: {e}", exc_info=True)
        return {"kg_marketplace_enabled": True}


def _parse_value(raw: str):
    if raw in ("true", "True", "1"):
        return True
    if raw in ("false", "False", "0"):
        return False
    return raw


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_kg_marketplace_settings(settings: dict, admin_uuid: str) -> None:
    """Upsert changed keys into the kg_marketplace_settings table."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        for key, value in settings.items():
            str_value = "true" if value is True else "false" if value is False else str(value)
            cursor.execute(
                "INSERT INTO kg_marketplace_settings (setting_key, setting_value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET "
                "setting_value = excluded.setting_value, "
                "updated_at = excluded.updated_at",
                (key, str_value, now),
            )
        conn.commit()
        conn.close()
        logger.info(f"KG marketplace settings updated by admin {admin_uuid}: {list(settings.keys())}")
    except Exception as e:
        logger.error(f"Failed to save KG marketplace settings: {e}", exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------

def is_kg_marketplace_enabled() -> bool:
    """Check whether the KG marketplace is enabled."""
    return get_kg_marketplace_settings().get("kg_marketplace_enabled", True)
