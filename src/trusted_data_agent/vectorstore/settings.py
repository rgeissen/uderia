"""
Vector store governance settings helper.

Loads / saves admin-controlled settings from the vectorstore_settings table.
Provides convenience predicates used by enforcement points in rest_routes.py.
Mirrors components/settings.py pattern exactly.

Tier model (cumulative):
- admin:     always all backends (bypass — not stored in DB)
- developer: from allowed_backends_developer
- user:      from allowed_backends_user (subset of developer)
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("quart.app")

# Resolve DB path once (same pattern as database.py)
_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"

ALL_BACKENDS = ["chromadb", "teradata", "qdrant"]


def _get_conn():
    return sqlite3.connect(str(_DB_PATH))


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_vectorstore_settings() -> dict:
    """
    Load all vectorstore_settings rows into a dict.

    Returns e.g.:
        {
            "allowed_backends_user": ["chromadb", "teradata", "qdrant"],
            "allowed_backends_developer": ["chromadb", "teradata", "qdrant"]
        }
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_key, setting_value FROM vectorstore_settings")
        rows = cursor.fetchall()
        conn.close()

        settings = {}
        for key, value in rows:
            settings[key] = _parse_value(key, value)
        return settings
    except Exception as e:
        logger.error(f"Failed to load vectorstore settings: {e}", exc_info=True)
        # Safe defaults — everything available
        return {
            "allowed_backends_user": list(ALL_BACKENDS),
            "allowed_backends_developer": list(ALL_BACKENDS),
        }


def _parse_value(key: str, raw: str):
    """Convert stored string value to typed Python value."""
    if key.startswith("allowed_backends_"):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return list(ALL_BACKENDS)
    return raw


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_vectorstore_settings(settings: dict, admin_uuid: str) -> None:
    """
    Upsert changed keys into the vectorstore_settings table.
    Only updates keys that are present in *settings*.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        for key, value in settings.items():
            str_value = _to_string(key, value)
            cursor.execute(
                "INSERT INTO vectorstore_settings (setting_key, setting_value, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET "
                "setting_value = excluded.setting_value, "
                "updated_at = excluded.updated_at, "
                "updated_by = excluded.updated_by",
                (key, str_value, now, admin_uuid),
            )
        conn.commit()
        conn.close()
        logger.info(f"Vector store settings updated by admin {admin_uuid}: {list(settings.keys())}")
    except Exception as e:
        logger.error(f"Failed to save vectorstore settings: {e}", exc_info=True)
        raise


def _to_string(key: str, value) -> str:
    """Convert typed Python value to string for DB storage."""
    if key.startswith("allowed_backends_"):
        return json.dumps(value if isinstance(value, list) else [])
    return str(value)


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------

def get_allowed_backends(user_tier: str) -> list:
    """
    Get list of allowed backend types for the given user tier.

    Admin always gets all backends (bypass).
    Developer gets allowed_backends_developer.
    User gets allowed_backends_user.
    """
    if user_tier == "admin":
        return list(ALL_BACKENDS)

    settings = get_vectorstore_settings()

    if user_tier == "developer":
        return settings.get("allowed_backends_developer", list(ALL_BACKENDS))

    # user tier (default)
    return settings.get("allowed_backends_user", list(ALL_BACKENDS))


def is_backend_allowed(backend_type: str, user_tier: str) -> bool:
    """
    Check whether a specific backend is available for the given user tier.
    """
    return backend_type in get_allowed_backends(user_tier)
