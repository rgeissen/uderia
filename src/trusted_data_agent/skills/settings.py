"""
Skill governance settings helper.

Loads / saves admin-controlled settings from the skill_settings table.
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

def get_skill_settings() -> dict:
    """
    Load all skill_settings rows into a dict.

    Returns e.g.:
        {
            "skills_mode": "all",
            "disabled_skills": [],
            "user_skills_enabled": True,
            "auto_skills_enabled": False
        }
    """
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_key, setting_value FROM skill_settings")
        rows = cursor.fetchall()
        conn.close()

        settings = {}
        for key, value in rows:
            settings[key] = _parse_value(key, value)
        return settings
    except Exception as e:
        logger.error(f"Failed to load skill settings: {e}", exc_info=True)
        # Safe defaults — everything available
        return {
            "skills_mode": "all",
            "disabled_skills": [],
            "user_skills_enabled": True,
            "auto_skills_enabled": False,
            "user_skills_marketplace_enabled": True,
        }


def _parse_value(key: str, raw: str):
    """Convert stored string value to typed Python value."""
    if key == "disabled_skills":
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

def save_skill_settings(settings: dict, admin_uuid: str) -> None:
    """
    Upsert changed keys into the skill_settings table.
    Only updates keys that are present in *settings*.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        for key, value in settings.items():
            str_value = _to_string(key, value)
            cursor.execute(
                "INSERT INTO skill_settings (setting_key, setting_value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET "
                "setting_value = excluded.setting_value, "
                "updated_at = excluded.updated_at",
                (key, str_value, now),
            )
        conn.commit()
        conn.close()
        logger.info(f"Skill settings updated by admin {admin_uuid}: {list(settings.keys())}")
    except Exception as e:
        logger.error(f"Failed to save skill settings: {e}", exc_info=True)
        raise


def _to_string(key: str, value) -> str:
    """Convert typed Python value to string for DB storage."""
    if key == "disabled_skills":
        return json.dumps(value if isinstance(value, list) else [])
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------

def is_skill_available(skill_id: str) -> bool:
    """
    Check whether a specific skill is available under current settings.
    mode=all → always True.  mode=selective → True unless in disabled list.
    """
    settings = get_skill_settings()
    if settings.get("skills_mode", "all") == "all":
        return True
    disabled = settings.get("disabled_skills", [])
    return skill_id not in disabled


def are_user_skills_enabled() -> bool:
    """Check whether custom skill creation is allowed."""
    return get_skill_settings().get("user_skills_enabled", True)


def are_auto_skills_enabled() -> bool:
    """Check whether automatic skill selection is enabled (Phase 2)."""
    return get_skill_settings().get("auto_skills_enabled", False)


def is_skill_marketplace_enabled() -> bool:
    """Check whether the skill marketplace is enabled."""
    return get_skill_settings().get("user_skills_marketplace_enabled", True)
