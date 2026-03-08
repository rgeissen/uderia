"""
Query helper for the agent_pack_resources junction table.

Centralizes all many-to-many relationship queries between agent packs
and their resources (profiles + collections). Used by rest_routes.py
(API enrichment, deletion constraints), agent_pack_manager.py (uninstall),
and frontend enrichment.
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("quart.app")

# Default DB path (same convention as database.py)
_DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[3] / "tda_auth.db")


class AgentPackDB:
    """Query helper for agent_pack_resources junction table."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or _DEFAULT_DB_PATH

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_packs_for_resource(self, resource_type: str, resource_id: str) -> list[dict]:
        """Return all packs that reference a resource.

        Returns: [{"id": 3, "name": "Virtual Account Team"}, ...]
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT api.id, api.name
                FROM agent_pack_installations api
                JOIN agent_pack_resources apr ON api.id = apr.pack_installation_id
                WHERE apr.resource_type = ? AND apr.resource_id = ?
            """, (resource_type, str(resource_id)))
            return [{"id": row["id"], "name": row["name"]} for row in cursor.fetchall()]
        finally:
            conn.close()

    def is_pack_managed(self, resource_type: str, resource_id: str) -> bool:
        """Return True if the resource is referenced by any pack."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM agent_pack_resources
                WHERE resource_type = ? AND resource_id = ?
            """, (resource_type, str(resource_id)))
            return cursor.fetchone()[0] > 0
        finally:
            conn.close()

    def get_pack_names_for_resource(self, resource_type: str, resource_id: str) -> list[str]:
        """Return list of pack names for a resource (for UI badges)."""
        packs = self.get_packs_for_resource(resource_type, resource_id)
        return [p["name"] for p in packs]

    def is_safe_to_delete(
        self, resource_type: str, resource_id: str,
        excluding_pack_id: int | None = None
    ) -> bool:
        """Return True if the resource is not referenced by any (other) pack.

        Args:
            resource_type: 'profile' or 'collection'
            resource_id: Profile ID or collection ID as string
            excluding_pack_id: If provided, exclude this pack from the check
                              (used during uninstall to check if other packs reference it)
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            if excluding_pack_id is not None:
                cursor.execute("""
                    SELECT COUNT(*) FROM agent_pack_resources
                    WHERE resource_type = ? AND resource_id = ?
                    AND pack_installation_id != ?
                """, (resource_type, str(resource_id), excluding_pack_id))
            else:
                cursor.execute("""
                    SELECT COUNT(*) FROM agent_pack_resources
                    WHERE resource_type = ? AND resource_id = ?
                """, (resource_type, str(resource_id)))
            return cursor.fetchone()[0] == 0
        finally:
            conn.close()

    def get_resources_for_pack(self, pack_installation_id: int) -> list[dict]:
        """Return all resources for a pack."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT resource_type, resource_id, resource_tag, resource_role, is_owned
                FROM agent_pack_resources WHERE pack_installation_id = ?
            """, (pack_installation_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def remove_pack_resources(self, pack_installation_id: int):
        """Remove all junction rows for a pack (during uninstall)."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM agent_pack_resources WHERE pack_installation_id = ?",
                (pack_installation_id,)
            )
            conn.commit()
            logger.info(f"Removed junction rows for pack {pack_installation_id}")
        finally:
            conn.close()
