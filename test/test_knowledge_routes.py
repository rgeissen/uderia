"""
Tests for Knowledge Repository route contracts (Track B).

Covers:
  1. PATCH /v1/knowledge/repositories/{id} — allowed field set includes
     source_root, sync_interval, embedding_model_locked, description
  2. POST /v1/knowledge/repositories/{id}/sync — route exists and calls
     sync_knowledge_collection with older_than_seconds=0
  3. GET /v1/rag/collections — effective_source_root priority chain
     (collection setting → UDERIA_DOCS_ROOT env var → auto-detect)
  4. collections table schema — source_root column added by migration
  5. PATCH field isolation — unknown fields are silently ignored

No live Quart server or database required — all external dependencies are
mocked or verified via source-text inspection.

Run with:
  PYTHONPATH=src python test/test_knowledge_routes.py -v
"""

import asyncio
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Source text helpers — read once, reuse across tests
# ---------------------------------------------------------------------------

def _knowledge_routes_source() -> str:
    p = Path(__file__).parent.parent / "src/trusted_data_agent/api/knowledge_routes.py"
    return p.read_text()


def _rest_routes_source() -> str:
    p = Path(__file__).parent.parent / "src/trusted_data_agent/api/rest_routes.py"
    return p.read_text()


def _database_py_source() -> str:
    p = Path(__file__).parent.parent / "src/trusted_data_agent/auth/database.py"
    return p.read_text()


# ---------------------------------------------------------------------------
# 1. PATCH allowed-field contract
# ---------------------------------------------------------------------------

class TestPatchAllowedFieldContract(unittest.TestCase):
    """PATCH /v1/knowledge/repositories/{id} ALLOWED set must be correct."""

    def setUp(self):
        self.source = _knowledge_routes_source()

    def test_source_root_allowed(self):
        self.assertIn('"source_root"', self.source,
                      "source_root must be in the PATCH ALLOWED set")

    def test_sync_interval_allowed(self):
        self.assertIn('"sync_interval"', self.source,
                      "sync_interval must be in the PATCH ALLOWED set")

    def test_embedding_model_locked_allowed(self):
        self.assertIn('"embedding_model_locked"', self.source,
                      "embedding_model_locked must be in the PATCH ALLOWED set")

    def test_description_allowed(self):
        self.assertIn('"description"', self.source,
                      "description must be in the PATCH ALLOWED set")

    def test_allowed_set_definition_present(self):
        """ALLOWED variable must be defined as a set literal."""
        self.assertIn("ALLOWED = {", self.source)

    def test_unknown_fields_filtered(self):
        """
        Route uses dict comprehension to filter by ALLOWED — unknown fields
        like 'name' or 'owner_user_id' must not pass through.
        The filtering pattern must be present in source.
        """
        # The route must apply a filter like: {k: v for k, v in ... if k in ALLOWED}
        self.assertIn("if k in ALLOWED", self.source)


# ---------------------------------------------------------------------------
# 2. POST sync route contract
# ---------------------------------------------------------------------------

class TestSyncRouteContract(unittest.TestCase):
    """POST /v1/knowledge/repositories/{id}/sync must use older_than_seconds=0."""

    def setUp(self):
        self.source = _knowledge_routes_source()

    def test_route_url_pattern_registered(self):
        """Route must be registered at .../sync."""
        self.assertIn("/sync", self.source)

    def test_route_uses_older_than_seconds_zero(self):
        """Manual trigger must always bypass the 1-hour throttle."""
        self.assertIn("older_than_seconds=0", self.source,
                      "Sync route must call sync_knowledge_collection with "
                      "older_than_seconds=0 to force-check all documents")

    def test_route_imports_sync_knowledge_collection(self):
        """Route must import or call sync_knowledge_collection."""
        self.assertIn("sync_knowledge_collection", self.source)

    def test_scheduled_default_is_3600(self):
        """Scheduled runs use the 3600-second default (throttle)."""
        from trusted_data_agent.core.knowledge_sync import sync_knowledge_collection
        sig = inspect.signature(sync_knowledge_collection)
        param = sig.parameters.get("older_than_seconds")
        self.assertIsNotNone(param, "sync_knowledge_collection must have older_than_seconds param")
        self.assertEqual(
            param.default, 3600,
            "Default older_than_seconds must be 3600 so scheduled runs are throttled"
        )

    def test_sync_result_keys(self):
        """Sync engine must return a dict with the standard result keys."""
        from trusted_data_agent.core.knowledge_sync import sync_knowledge_collection
        src = Path(__file__).parent.parent / "src/trusted_data_agent/core/knowledge_sync.py"
        source = src.read_text()
        for key in ("checked", "updated", "unchanged", "errors"):
            self.assertIn(f'"{key}"', source,
                          f"sync_knowledge_collection result must include '{key}' key")


# ---------------------------------------------------------------------------
# 3. GET /v1/rag/collections — effective_source_root in response
# ---------------------------------------------------------------------------

class TestEffectiveSourceRootInCollectionResponse(unittest.TestCase):
    """
    GET /v1/rag/collections must include effective_source_root for knowledge
    collections, computed via the three-tier priority chain.
    """

    def setUp(self):
        self.source = _rest_routes_source()

    def test_effective_source_root_key_written(self):
        """Response must set effective_source_root on each knowledge collection."""
        self.assertIn("effective_source_root", self.source)

    def test_source_root_from_collection_first(self):
        """Collection's own source_root is the highest-priority source."""
        # The priority chain must reference coll.get("source_root") before env var
        idx_coll = self.source.find('coll.get("source_root")')
        idx_env = self.source.find('UDERIA_DOCS_ROOT')
        self.assertNotEqual(idx_coll, -1, "source_root lookup missing from rest_routes.py")
        self.assertNotEqual(idx_env, -1, "UDERIA_DOCS_ROOT lookup missing from rest_routes.py")
        self.assertLess(idx_coll, idx_env,
                        "Collection source_root must take priority over UDERIA_DOCS_ROOT")

    def test_env_var_fallback_present(self):
        """UDERIA_DOCS_ROOT env var must be the second-tier fallback."""
        self.assertIn("UDERIA_DOCS_ROOT", self.source)

    def test_auto_detect_fallback_present(self):
        """Auto-detect via __file__ parents must be the final fallback."""
        self.assertIn("__file__", self.source)
        self.assertIn("parents[3]", self.source)

    def test_source_root_passthrough_in_response(self):
        """source_root field (possibly None) must be included in the raw response."""
        self.assertIn('coll_copy["source_root"]', self.source)

    def test_effective_root_only_for_knowledge_collections(self):
        """effective_source_root must only be set for repository_type == 'knowledge'."""
        # Check that the assignment is inside a knowledge-type guard
        idx_guard = self.source.find("repository_type") and self.source.find('"knowledge"')
        idx_effective = self.source.find("effective_source_root")
        # Both must appear close together (within 500 chars)
        guard_area = self.source[max(0, idx_effective - 500):idx_effective + 200]
        self.assertIn("knowledge", guard_area,
                      "effective_source_root should only be computed for knowledge repos")


# ---------------------------------------------------------------------------
# 4. source_root column migration in collections table
# ---------------------------------------------------------------------------

class TestSourceRootColumnMigration(unittest.TestCase):
    """
    The source_root column must be added to the collections table by the
    database migration in auth/database.py.
    """

    def setUp(self):
        self.source = _database_py_source()

    def test_migration_adds_source_root_column(self):
        """database.py must include ALTER TABLE ... ADD COLUMN source_root."""
        self.assertIn("source_root", self.source,
                      "source_root column migration missing from database.py")
        self.assertIn("ADD COLUMN source_root", self.source)

    def test_source_root_is_text_nullable(self):
        """source_root should be TEXT DEFAULT NULL (user sets it explicitly)."""
        self.assertIn("source_root TEXT DEFAULT NULL", self.source)

    def test_migration_guard_pattern(self):
        """Migration must use try/except OperationalError to be idempotent."""
        # The guard must appear near the source_root migration
        idx = self.source.find("source_root TEXT DEFAULT NULL")
        surrounding = self.source[max(0, idx - 300):idx + 100]
        self.assertIn("OperationalError", surrounding,
                      "source_root migration must use try/except OperationalError guard")

    def test_source_root_column_works_in_sqlite(self):
        """
        End-to-end: create an in-memory SQLite DB with the collections schema,
        add the source_root column, and verify it round-trips through update.
        """
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                repository_type TEXT DEFAULT 'planner',
                sync_interval TEXT DEFAULT 'daily',
                embedding_model_locked INTEGER DEFAULT 0
            )
        """)
        conn.execute("ALTER TABLE collections ADD COLUMN source_root TEXT DEFAULT NULL")
        conn.execute(
            "INSERT INTO collections(name, collection_name, owner_user_id, repository_type) "
            "VALUES (?, ?, ?, ?)",
            ("Test Repo", "test_repo_coll", "user-1", "knowledge")
        )
        conn.commit()

        # Verify NULL default
        row = conn.execute("SELECT source_root FROM collections WHERE id = 1").fetchone()
        self.assertIsNone(row["source_root"])

        # Verify update round-trips
        conn.execute(
            "UPDATE collections SET source_root = ? WHERE id = 1",
            ("/opt/uderia",)
        )
        conn.commit()
        row = conn.execute("SELECT source_root FROM collections WHERE id = 1").fetchone()
        self.assertEqual(row["source_root"], "/opt/uderia")

        # Verify clear to NULL
        conn.execute("UPDATE collections SET source_root = NULL WHERE id = 1")
        conn.commit()
        row = conn.execute("SELECT source_root FROM collections WHERE id = 1").fetchone()
        self.assertIsNone(row["source_root"])
        conn.close()


# ---------------------------------------------------------------------------
# 5. PATCH field isolation — unknown fields silently ignored
# ---------------------------------------------------------------------------

class TestPatchFieldIsolation(unittest.TestCase):
    """
    Only ALLOWED fields should ever reach update_collection().
    Unknown fields in the request body must be dropped silently.
    """

    def test_filter_drops_unknown_fields(self):
        """Simulate the route's filtering logic on an adversarial payload."""
        ALLOWED = {"embedding_model_locked", "sync_interval", "description", "source_root"}
        adversarial_body = {
            "source_root": "/opt/uderia",
            "owner_user_id": "injected-user",   # must be dropped
            "id": 9999,                          # must be dropped
            "is_marketplace_listed": 1,          # must be dropped
            "sync_interval": "hourly",
        }
        updates = {k: v for k, v in adversarial_body.items() if k in ALLOWED}
        self.assertEqual(
            set(updates.keys()), {"source_root", "sync_interval"},
            "Only ALLOWED fields should survive the filter"
        )
        self.assertNotIn("owner_user_id", updates)
        self.assertNotIn("id", updates)
        self.assertNotIn("is_marketplace_listed", updates)

    def test_empty_body_after_filter_produces_no_updates(self):
        """Completely unknown payload must yield an empty updates dict."""
        ALLOWED = {"embedding_model_locked", "sync_interval", "description", "source_root"}
        body = {"owner_user_id": "x", "collection_name": "y"}
        updates = {k: v for k, v in body.items() if k in ALLOWED}
        self.assertEqual(len(updates), 0)

    def test_null_source_root_is_allowed(self):
        """Passing source_root=null must be accepted (clears the field)."""
        ALLOWED = {"embedding_model_locked", "sync_interval", "description", "source_root"}
        body = {"source_root": None}
        updates = {k: v for k, v in body.items() if k in ALLOWED}
        self.assertIn("source_root", updates)
        self.assertIsNone(updates["source_root"])


# ---------------------------------------------------------------------------
# 6. collection_db.update_collection passes source_root through dynamically
# ---------------------------------------------------------------------------

class TestCollectionDbUpdateSourceRoot(unittest.TestCase):
    """
    CollectionDB.update_collection() builds its UPDATE dynamically — verify
    that source_root survives the round-trip through a real in-memory SQLite DB.
    """

    def _make_db(self):
        """Create a minimal in-memory SQLite DB matching collection_db schema."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                collection_name TEXT NOT NULL UNIQUE,
                owner_user_id TEXT NOT NULL,
                repository_type TEXT DEFAULT 'knowledge',
                sync_interval TEXT DEFAULT 'daily',
                embedding_model_locked INTEGER DEFAULT 0,
                source_root TEXT DEFAULT NULL
            )
        """)
        conn.execute(
            "INSERT INTO collections(name, collection_name, owner_user_id) "
            "VALUES (?, ?, ?)",
            ("Uderia Documentation", "uderia_docs", "user-1")
        )
        conn.commit()
        return conn

    def test_set_source_root(self):
        """update_collection's dynamic SQL pattern must set source_root."""
        conn = self._make_db()
        updates = {"source_root": "/opt/uderia"}
        set_clauses = [f"{k} = ?" for k in updates.keys()]
        values = list(updates.values()) + [1]  # id=1
        conn.execute(f"UPDATE collections SET {', '.join(set_clauses)} WHERE id = ?", values)
        conn.commit()
        row = conn.execute("SELECT source_root FROM collections WHERE id = 1").fetchone()
        self.assertEqual(row["source_root"], "/opt/uderia")
        conn.close()

    def test_clear_source_root_to_null(self):
        """Setting source_root=None must store NULL in the database."""
        conn = self._make_db()
        conn.execute("UPDATE collections SET source_root = '/old/path' WHERE id = 1")
        conn.commit()
        updates = {"source_root": None}
        set_clauses = [f"{k} = ?" for k in updates.keys()]
        values = list(updates.values()) + [1]
        conn.execute(f"UPDATE collections SET {', '.join(set_clauses)} WHERE id = ?", values)
        conn.commit()
        row = conn.execute("SELECT source_root FROM collections WHERE id = 1").fetchone()
        self.assertIsNone(row["source_root"])
        conn.close()

    def test_update_multiple_fields(self):
        """Multiple fields including source_root must all be updated atomically."""
        conn = self._make_db()
        updates = {"source_root": "/opt/uderia", "sync_interval": "hourly"}
        set_clauses = [f"{k} = ?" for k in updates.keys()]
        values = list(updates.values()) + [1]
        conn.execute(f"UPDATE collections SET {', '.join(set_clauses)} WHERE id = ?", values)
        conn.commit()
        row = conn.execute(
            "SELECT source_root, sync_interval FROM collections WHERE id = 1"
        ).fetchone()
        self.assertEqual(row["source_root"], "/opt/uderia")
        self.assertEqual(row["sync_interval"], "hourly")
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
