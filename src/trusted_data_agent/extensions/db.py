"""
Database operations for per-user extension activation.

Supports multiple activations of the same extension with different
default parameters. Each activation has a unique `activation_name`
(what the user types as #name) mapped to an `extension_id` (which
Python extension to execute).

Auto-naming: json → json2 → json3 → ...
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
    """Parse a user_extensions row into a dict."""
    config = None
    if row["config_json"]:
        try:
            config = json.loads(row["config_json"])
        except json.JSONDecodeError:
            config = None

    return {
        "id": row["id"],
        "extension_id": row["extension_id"],
        "activation_name": row["activation_name"],
        "is_active": bool(row["is_active"]),
        "default_param": row["default_param"],
        "config": config,
        "activated_at": row["activated_at"],
        "updated_at": row["updated_at"],
    }


def _generate_activation_name(cursor: sqlite3.Cursor, user_uuid: str, extension_id: str) -> str:
    """
    Generate a unique activation_name for a new activation.

    First activation of 'json' → 'json'
    Second → 'json2', Third → 'json3', etc.
    """
    cursor.execute(
        """
        SELECT activation_name FROM user_extensions
        WHERE user_uuid = ? AND extension_id = ?
        ORDER BY activated_at
        """,
        (user_uuid, extension_id),
    )
    existing_names = {row[0] for row in cursor.fetchall()}

    # First activation: use bare extension_id
    if extension_id not in existing_names:
        return extension_id

    # Find next available number
    n = 2
    while f"{extension_id}{n}" in existing_names:
        n += 1
    return f"{extension_id}{n}"


def get_user_activated_extensions(user_uuid: str) -> List[Dict[str, Any]]:
    """
    Get all activated extensions for a user.

    Returns list of dicts with activation_name as the user-facing key.
    """
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, extension_id, activation_name, is_active, default_param,
                   config_json, activated_at, updated_at
            FROM user_extensions
            WHERE user_uuid = ? AND is_active = 1
            ORDER BY activated_at
            """,
            (user_uuid,),
        )

        results = [_parse_row(row) for row in cursor.fetchall()]
        conn.close()
        return results

    except Exception as e:
        logger.error(f"Failed to get activated extensions for user {user_uuid}: {e}")
        return []


def get_all_user_extensions(user_uuid: str) -> List[Dict[str, Any]]:
    """
    Get all extension records for a user (active and inactive).
    Used by the Extensions UI tab to show activation status.
    """
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, extension_id, activation_name, is_active, default_param,
                   config_json, activated_at, updated_at
            FROM user_extensions
            WHERE user_uuid = ?
            ORDER BY activated_at
            """,
            (user_uuid,),
        )

        results = [_parse_row(row) for row in cursor.fetchall()]
        conn.close()
        return results

    except Exception as e:
        logger.error(f"Failed to get user extensions for {user_uuid}: {e}")
        return []


def activate_extension(
    user_uuid: str,
    extension_id: str,
    default_param: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    activation_name: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Activate a new instance of an extension for a user.

    If activation_name is not provided, auto-generates one
    (json → json2 → json3 → ...).

    Returns (success, activation_name).
    """
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(config) if config else None

        # Auto-generate name if not specified
        if not activation_name:
            activation_name = _generate_activation_name(cursor, user_uuid, extension_id)

        cursor.execute(
            """
            INSERT INTO user_extensions
                (user_uuid, extension_id, activation_name, is_active, default_param, config_json, activated_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (user_uuid, extension_id, activation_name, default_param, config_json, now, now),
        )

        conn.commit()
        conn.close()
        logger.info(f"Extension '{extension_id}' activated as '{activation_name}' for user {user_uuid}")
        return True, activation_name

    except sqlite3.IntegrityError:
        logger.warning(f"Activation name '{activation_name}' already exists for user {user_uuid}")
        return False, None
    except Exception as e:
        logger.error(f"Failed to activate extension '{extension_id}' for user {user_uuid}: {e}")
        return False, None


def deactivate_extension(user_uuid: str, activation_name: str) -> bool:
    """Deactivate an extension activation by its activation_name (soft delete)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            UPDATE user_extensions
            SET is_active = 0, updated_at = ?
            WHERE user_uuid = ? AND activation_name = ?
            """,
            (now, user_uuid, activation_name),
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()

        if affected > 0:
            logger.info(f"Extension '{activation_name}' deactivated for user {user_uuid}")
            return True
        else:
            logger.warning(f"Extension '{activation_name}' was not found for user {user_uuid}")
            return False

    except Exception as e:
        logger.error(f"Failed to deactivate extension '{activation_name}' for user {user_uuid}: {e}")
        return False


def delete_extension_activation(user_uuid: str, activation_name: str) -> bool:
    """Hard-delete an extension activation (removes the row entirely)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM user_extensions
            WHERE user_uuid = ? AND activation_name = ?
            """,
            (user_uuid, activation_name),
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()

        if affected > 0:
            logger.info(f"Extension activation '{activation_name}' deleted for user {user_uuid}")
            return True
        else:
            logger.warning(f"Extension '{activation_name}' not found for user {user_uuid}")
            return False

    except Exception as e:
        logger.error(f"Failed to delete extension '{activation_name}' for user {user_uuid}: {e}")
        return False


def update_extension_config(
    user_uuid: str,
    activation_name: str,
    default_param: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Update the configuration for an activation by its activation_name."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(config) if config else None

        cursor.execute(
            """
            UPDATE user_extensions
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
        logger.error(f"Failed to update extension config for '{activation_name}': {e}")
        return False


def rename_extension_activation(
    user_uuid: str,
    old_name: str,
    new_name: str,
) -> bool:
    """Rename an activation (change activation_name)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            UPDATE user_extensions
            SET activation_name = ?, updated_at = ?
            WHERE user_uuid = ? AND activation_name = ?
            """,
            (new_name, now, user_uuid, old_name),
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()

        if affected > 0:
            logger.info(f"Extension renamed '{old_name}' → '{new_name}' for user {user_uuid}")
            return True
        else:
            return False

    except sqlite3.IntegrityError:
        logger.warning(f"Cannot rename to '{new_name}' — already exists for user {user_uuid}")
        return False
    except Exception as e:
        logger.error(f"Failed to rename extension '{old_name}': {e}")
        return False


def get_extension_activation(user_uuid: str, activation_name: str) -> Optional[Dict[str, Any]]:
    """Get activation details for a specific activation by name."""
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, extension_id, activation_name, is_active, default_param,
                   config_json, activated_at, updated_at
            FROM user_extensions
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


def has_active_activations(extension_id: str) -> bool:
    """Check if any user has active activations for this extension."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_extensions WHERE extension_id = ? AND is_active = 1",
            (extension_id,),
        )
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"Failed to check active activations for '{extension_id}': {e}")
        return True  # Safe default: assume active to prevent accidental deletion


def delete_inactive_activations_for_extension(extension_id: str) -> int:
    """Delete all inactive (is_active=0) activation rows for an extension. Returns count deleted."""
    try:
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM user_extensions WHERE extension_id = ? AND is_active = 0",
            (extension_id,),
        )
        conn.commit()
        deleted = cursor.rowcount
        conn.close()
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} inactive activation(s) for extension '{extension_id}'")
        return deleted
    except Exception as e:
        logger.error(f"Failed to delete inactive activations for '{extension_id}': {e}")
        return 0
