"""
Database operations for per-user skill activation.

Mirrors extensions/db.py pattern exactly. Each user can activate skills
with custom activation names and default parameters.

Auto-naming: sql-expert → sql-expert2 → sql-expert3 → ...
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("quart.app")

# Resolve default DB path (same pattern as auth/database.py)
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"


def _get_db_path() -> str:
    """Get the database file path string."""
    return str(_DEFAULT_DB_PATH)


def _parse_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Parse a user_skills row into a dict."""
    config = None
    if row["config_json"]:
        try:
            config = json.loads(row["config_json"])
        except json.JSONDecodeError:
            config = None

    return {
        "id": row["id"],
        "skill_id": row["skill_id"],
        "activation_name": row["activation_name"],
        "is_active": bool(row["is_active"]),
        "default_param": row["default_param"],
        "config": config,
        "activated_at": row["activated_at"],
        "updated_at": row["updated_at"],
    }


def _generate_activation_name(cursor: sqlite3.Cursor, user_uuid: str, skill_id: str) -> str:
    """
    Generate a unique activation_name for a new activation.

    First activation of 'sql-expert' → 'sql-expert'
    Second → 'sql-expert2', Third → 'sql-expert3', etc.
    """
    cursor.execute(
        """
        SELECT activation_name FROM user_skills
        WHERE user_uuid = ? AND skill_id = ?
        ORDER BY activated_at
        """,
        (user_uuid, skill_id),
    )
    existing_names = {row[0] for row in cursor.fetchall()}

    if skill_id not in existing_names:
        return skill_id

    n = 2
    while f"{skill_id}{n}" in existing_names:
        n += 1
    return f"{skill_id}{n}"


def get_user_activated_skills(user_uuid: str) -> List[Dict[str, Any]]:
    """
    Get all activated skills for a user.
    Returns list of dicts with activation_name as the user-facing key.
    """
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, skill_id, activation_name, is_active, default_param,
                   config_json, activated_at, updated_at
            FROM user_skills
            WHERE user_uuid = ? AND is_active = 1
            ORDER BY activated_at
            """,
            (user_uuid,),
        )

        results = [_parse_row(row) for row in cursor.fetchall()]
        conn.close()
        return results

    except Exception as e:
        logger.error(f"Failed to get activated skills for user {user_uuid}: {e}")
        return []


def get_all_user_skills(user_uuid: str) -> List[Dict[str, Any]]:
    """
    Get all skill records for a user (active and inactive).
    Used by the Skills UI tab to show activation status.
    """
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, skill_id, activation_name, is_active, default_param,
                   config_json, activated_at, updated_at
            FROM user_skills
            WHERE user_uuid = ?
            ORDER BY activated_at
            """,
            (user_uuid,),
        )

        results = [_parse_row(row) for row in cursor.fetchall()]
        conn.close()
        return results

    except Exception as e:
        logger.error(f"Failed to get user skills for {user_uuid}: {e}")
        return []


def activate_skill(
    user_uuid: str,
    skill_id: str,
    default_param: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    activation_name: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Activate a skill for a user.

    If activation_name is not provided, auto-generates one.
    Returns (success, activation_name).
    """
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(config) if config else None

        if not activation_name:
            activation_name = _generate_activation_name(cursor, user_uuid, skill_id)

        cursor.execute(
            """
            INSERT INTO user_skills
                (user_uuid, skill_id, activation_name, is_active, default_param, config_json, activated_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (user_uuid, skill_id, activation_name, default_param, config_json, now, now),
        )

        conn.commit()
        conn.close()
        logger.info(f"Skill '{skill_id}' activated as '{activation_name}' for user {user_uuid}")
        return True, activation_name

    except sqlite3.IntegrityError:
        logger.warning(f"Activation name '{activation_name}' already exists for user {user_uuid}")
        return False, None
    except Exception as e:
        logger.error(f"Failed to activate skill '{skill_id}' for user {user_uuid}: {e}")
        return False, None


def deactivate_skill(user_uuid: str, activation_name: str) -> bool:
    """Deactivate a skill activation by its activation_name (soft delete)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            UPDATE user_skills
            SET is_active = 0, updated_at = ?
            WHERE user_uuid = ? AND activation_name = ?
            """,
            (now, user_uuid, activation_name),
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()

        if affected > 0:
            logger.info(f"Skill '{activation_name}' deactivated for user {user_uuid}")
            return True
        else:
            logger.warning(f"Skill '{activation_name}' was not found for user {user_uuid}")
            return False

    except Exception as e:
        logger.error(f"Failed to deactivate skill '{activation_name}' for user {user_uuid}: {e}")
        return False


def delete_skill_activation(user_uuid: str, activation_name: str) -> bool:
    """Hard-delete a skill activation (removes the row entirely)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM user_skills
            WHERE user_uuid = ? AND activation_name = ?
            """,
            (user_uuid, activation_name),
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()

        if affected > 0:
            logger.info(f"Skill activation '{activation_name}' deleted for user {user_uuid}")
            return True
        else:
            logger.warning(f"Skill '{activation_name}' not found for user {user_uuid}")
            return False

    except Exception as e:
        logger.error(f"Failed to delete skill '{activation_name}' for user {user_uuid}: {e}")
        return False


def update_skill_config(
    user_uuid: str,
    activation_name: str,
    default_param: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Update the configuration for a skill activation."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(config) if config else None

        cursor.execute(
            """
            UPDATE user_skills
            SET default_param = ?, config_json = ?, updated_at = ?
            WHERE user_uuid = ? AND activation_name = ? AND is_active = 1
            """,
            (default_param, config_json, now, user_uuid, activation_name),
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    except Exception as e:
        logger.error(f"Failed to update skill config for '{activation_name}': {e}")
        return False


def rename_skill_activation(
    user_uuid: str,
    old_name: str,
    new_name: str,
) -> bool:
    """Rename a skill activation (change activation_name)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            UPDATE user_skills
            SET activation_name = ?, updated_at = ?
            WHERE user_uuid = ? AND activation_name = ?
            """,
            (new_name, now, user_uuid, old_name),
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()

        if affected > 0:
            logger.info(f"Skill renamed '{old_name}' → '{new_name}' for user {user_uuid}")
            return True
        else:
            return False

    except sqlite3.IntegrityError:
        logger.warning(f"Cannot rename to '{new_name}' — already exists for user {user_uuid}")
        return False
    except Exception as e:
        logger.error(f"Failed to rename skill '{old_name}': {e}")
        return False


def get_skill_activation(user_uuid: str, activation_name: str) -> Optional[Dict[str, Any]]:
    """Get activation details for a specific skill activation by name."""
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, skill_id, activation_name, is_active, default_param,
                   config_json, activated_at, updated_at
            FROM user_skills
            WHERE user_uuid = ? AND activation_name = ?
            """,
            (user_uuid, activation_name),
        )

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return _parse_row(row)

    except Exception as e:
        logger.error(f"Failed to get activation for '{activation_name}': {e}")
        return None
