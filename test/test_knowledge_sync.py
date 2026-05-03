"""
Unit tests for Knowledge Repository CDC Sync engine.

All database and RAG-stack calls are mocked — no real SQLite, ChromaDB, or
embedding model is required.

Run with:
  PYTHONPATH=src python test/test_knowledge_sync.py -v

Patching notes
--------------
get_collection_db, get_rag_retriever, DocumentUploadHandler, and
create_repository_constructor are all imported *inside* the functions they
are used by (local imports).  We therefore patch at the *definition* site:
    trusted_data_agent.core.collection_db.get_collection_db
    trusted_data_agent.agent.rag_retriever.get_rag_retriever
    trusted_data_agent.llm.document_upload.DocumentUploadHandler
    trusted_data_agent.agent.repository_constructor.create_repository_constructor

fetch_source, _sync_upsert_document, and _fetch_local_file are module-level
in knowledge_sync, so they can be patched there directly.

_fetch_http / _fetch_google_drive are referenced by the SOURCE_RESOLVERS dict
at module load time, so we patch the dict with patch.dict.
"""

import asyncio
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trusted_data_agent.core.knowledge_sync import (
    _fetch_local_file,
    fetch_source,
    sync_knowledge_collection,
    reindex_knowledge_collection,
    SOURCE_RESOLVERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_collection(collection_id=1, source_root=None, sync_interval="daily"):
    return {
        "id": collection_id,
        "name": "Test Knowledge Repo",
        "collection_name": f"test_collection_{collection_id}",
        "repository_type": "knowledge",
        "backend_type": "chromadb",
        "backend_config": "{}",
        "chunking_strategy": "paragraph",
        "embedding_model": "all-MiniLM-L6-v2",
        "chunk_size": 1000,
        "chunk_overlap": 200,
        "source_root": source_root,
        "sync_interval": sync_interval,
        "embedding_model_locked": 0,
    }


def _make_doc(doc_id="doc-001", filename="guide.md", source_uri=None,
              content_hash=None, sync_enabled=1):
    return {
        "document_id": doc_id,
        "collection_id": 1,
        "filename": filename,
        "title": filename,
        "author": "",
        "source": "upload",
        "category": "",
        "tags": "",
        "file_size": 1024,
        "document_type": "markdown",
        "source_uri": source_uri,
        "sync_enabled": sync_enabled,
        "content_hash": content_hash,
        "last_checked_at": None,
        "ingest_epoch": 1000000,
    }


# ---------------------------------------------------------------------------
# _fetch_local_file
# ---------------------------------------------------------------------------

class TestFetchLocalFile(unittest.TestCase):
    """Tests for _fetch_local_file() — all four resolution paths."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="wb")
        self.content = b"# Hello World\nThis is a test document."
        self.tmp.write(self.content)
        self.tmp.close()
        self.tmp_path = self.tmp.name

    def tearDown(self):
        try:
            os.unlink(self.tmp_path)
        except OSError:
            pass

    def test_absolute_path_read_directly(self):
        """Absolute path (starts with /) is used without any resolution."""
        uri = f"file://{self.tmp_path}"
        result = _run(_fetch_local_file(uri, "user-1"))
        self.assertEqual(result, self.content)

    def test_relative_path_resolved_via_source_root(self):
        """Relative path resolved against source_root argument (priority 1)."""
        parent = str(Path(self.tmp_path).parent)
        rel_name = Path(self.tmp_path).name
        uri = f"file://{rel_name}"
        result = _run(_fetch_local_file(uri, "user-1", source_root=parent))
        self.assertEqual(result, self.content)

    def test_relative_path_resolved_via_env_var(self):
        """Relative path resolved against UDERIA_DOCS_ROOT env var (priority 2)."""
        parent = str(Path(self.tmp_path).parent)
        rel_name = Path(self.tmp_path).name
        uri = f"file://{rel_name}"
        with patch.dict(os.environ, {"UDERIA_DOCS_ROOT": parent}):
            result = _run(_fetch_local_file(uri, "user-1", source_root=None))
        self.assertEqual(result, self.content)

    def test_source_root_takes_priority_over_env_var(self):
        """source_root wins over UDERIA_DOCS_ROOT when both are set."""
        parent = str(Path(self.tmp_path).parent)
        rel_name = Path(self.tmp_path).name
        uri = f"file://{rel_name}"
        # env var points at a non-existent dir; if used, the call would fail
        with patch.dict(os.environ, {"UDERIA_DOCS_ROOT": "/tmp/nonexistent_uderia_xyz"}):
            result = _run(_fetch_local_file(uri, "user-1", source_root=parent))
        self.assertEqual(result, self.content)

    def test_relative_path_auto_detect_fallback(self):
        """Relative path resolved against auto-detected install root (priority 3)."""
        import trusted_data_agent.core.knowledge_sync as _ks_mod
        auto_root = Path(_ks_mod.__file__).resolve().parents[3]

        with tempfile.NamedTemporaryFile(
            dir=str(auto_root), delete=False, suffix=".md", mode="wb"
        ) as f:
            f.write(self.content)
            auto_file = f.name

        try:
            rel_name = Path(auto_file).name
            uri = f"file://{rel_name}"
            env = {k: v for k, v in os.environ.items() if k != "UDERIA_DOCS_ROOT"}
            with patch.dict(os.environ, env, clear=True):
                result = _run(_fetch_local_file(uri, "user-1", source_root=None))
            self.assertEqual(result, self.content)
        finally:
            try:
                os.unlink(auto_file)
            except OSError:
                pass

    def test_file_not_found_raises(self):
        """Missing file raises FileNotFoundError / OSError."""
        uri = "file:///tmp/uderia_test_nonexistent_xyz_12345.md"
        with self.assertRaises((FileNotFoundError, OSError)):
            _run(_fetch_local_file(uri, "user-1"))


# ---------------------------------------------------------------------------
# fetch_source — scheme dispatch
# ---------------------------------------------------------------------------

class TestFetchSourceSchemeDispatch(unittest.TestCase):
    """fetch_source() dispatches to the correct resolver by URI scheme."""

    def test_file_scheme_calls_fetch_local_file(self):
        """file:// URIs are dispatched directly to _fetch_local_file."""
        content = b"local content"
        with patch(
            "trusted_data_agent.core.knowledge_sync._fetch_local_file",
            new=AsyncMock(return_value=content),
        ) as mock_local:
            result = _run(fetch_source("file://some/path.md", "user-1"))
        self.assertEqual(result, content)
        mock_local.assert_called_once_with("file://some/path.md", "user-1", None)

    def test_file_scheme_passes_source_root(self):
        """source_root is forwarded to _fetch_local_file."""
        content = b"local content"
        with patch(
            "trusted_data_agent.core.knowledge_sync._fetch_local_file",
            new=AsyncMock(return_value=content),
        ) as mock_local:
            result = _run(fetch_source("file://some/path.md", "user-1", source_root="/opt/uderia"))
        self.assertEqual(result, content)
        mock_local.assert_called_once_with("file://some/path.md", "user-1", "/opt/uderia")

    def test_https_scheme_calls_http_resolver(self):
        """https:// URIs go to _fetch_http via SOURCE_RESOLVERS."""
        content = b"remote content"
        mock_http = AsyncMock(return_value=content)
        with patch.dict(
            "trusted_data_agent.core.knowledge_sync.SOURCE_RESOLVERS",
            {"https": mock_http},
        ):
            result = _run(fetch_source("https://example.com/doc.pdf", "user-1"))
        self.assertEqual(result, content)
        mock_http.assert_called_once_with("https://example.com/doc.pdf", "user-1")

    def test_http_scheme_calls_http_resolver(self):
        """http:// URIs go to _fetch_http via SOURCE_RESOLVERS."""
        content = b"intranet content"
        mock_http = AsyncMock(return_value=content)
        with patch.dict(
            "trusted_data_agent.core.knowledge_sync.SOURCE_RESOLVERS",
            {"http": mock_http},
        ):
            result = _run(fetch_source("http://intranet.local/guide.md", "user-1"))
        self.assertEqual(result, content)
        mock_http.assert_called_once_with("http://intranet.local/guide.md", "user-1")

    def test_gdrive_scheme_calls_google_resolver(self):
        """gdrive:// URIs go to _fetch_google_drive via SOURCE_RESOLVERS."""
        content = b"gdrive content"
        mock_gdrive = AsyncMock(return_value=content)
        with patch.dict(
            "trusted_data_agent.core.knowledge_sync.SOURCE_RESOLVERS",
            {"gdrive": mock_gdrive},
        ):
            result = _run(fetch_source("gdrive://abc123fileId", "user-1"))
        self.assertEqual(result, content)
        mock_gdrive.assert_called_once_with("gdrive://abc123fileId", "user-1")

    def test_unsupported_scheme_raises_value_error(self):
        """Unknown URI scheme raises ValueError with a helpful message."""
        with self.assertRaises(ValueError) as ctx:
            _run(fetch_source("ftp://example.com/doc.txt", "user-1"))
        self.assertIn("ftp", str(ctx.exception))
        self.assertIn("Supported", str(ctx.exception))

    def test_empty_source_uri_raises_value_error(self):
        """Empty source_uri raises ValueError."""
        with self.assertRaises(ValueError):
            _run(fetch_source("", "user-1"))

    def test_none_source_uri_raises(self):
        """None source_uri raises (AttributeError or ValueError)."""
        with self.assertRaises((ValueError, AttributeError)):
            _run(fetch_source(None, "user-1"))


# ---------------------------------------------------------------------------
# sync_knowledge_collection
# ---------------------------------------------------------------------------

# Patch target for get_collection_db (local import inside the function)
_PATCH_DB = "trusted_data_agent.core.collection_db.get_collection_db"


class TestSyncKnowledgeCollection(unittest.TestCase):
    """Tests for the full hash-check CDC sync loop."""

    def _make_mock_db(self, collection=None, candidates=None):
        db = MagicMock()
        db.get_collection_by_id.return_value = collection
        db.get_sync_candidates.return_value = candidates or []
        db.mark_document_checked.return_value = None
        db.upsert_document_metadata.return_value = "doc-001"
        db.sync_collection_counts.return_value = (1, 5)
        return db

    def test_collection_not_found_raises(self):
        """Raises ValueError when collection_id does not exist."""
        mock_db = self._make_mock_db(collection=None)
        with patch(_PATCH_DB, return_value=mock_db):
            with self.assertRaises(ValueError) as ctx:
                _run(sync_knowledge_collection(999, "user-1"))
        self.assertIn("999", str(ctx.exception))

    def test_no_candidates_returns_zero_counts(self):
        """Empty candidate list returns all-zero stats without errors."""
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=[])
        with patch(_PATCH_DB, return_value=mock_db):
            result = _run(sync_knowledge_collection(1, "user-1"))
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["unchanged"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertIn("duration_seconds", result)

    def test_older_than_seconds_zero_bypasses_throttle(self):
        """older_than_seconds=0 is forwarded to get_sync_candidates (force-check all)."""
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=[])
        with patch(_PATCH_DB, return_value=mock_db):
            _run(sync_knowledge_collection(1, "user-1", older_than_seconds=0))
        mock_db.get_sync_candidates.assert_called_once_with(1, older_than_seconds=0)

    def test_default_throttle_is_3600(self):
        """Default older_than_seconds is 3600 (1 hour)."""
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=[])
        with patch(_PATCH_DB, return_value=mock_db):
            _run(sync_knowledge_collection(1, "user-1"))
        mock_db.get_sync_candidates.assert_called_once_with(1, older_than_seconds=3600)

    def test_document_without_source_uri_is_marked_checked(self):
        """Doc with no source_uri: counted as unchanged and mark_document_checked called."""
        doc = _make_doc(source_uri=None)
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=[doc])
        with patch(_PATCH_DB, return_value=mock_db):
            result = _run(sync_knowledge_collection(1, "user-1"))
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["updated"], 0)
        mock_db.mark_document_checked.assert_called_once_with("doc-001")

    def test_unchanged_content_hash_marks_checked(self):
        """Doc whose content hash matches stored hash: skipped, marked checked."""
        content = b"unchanged document content"
        doc = _make_doc(source_uri="file://docs/guide.md", content_hash=_sha256(content))
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=[doc])
        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(return_value=content)):
            result = _run(sync_knowledge_collection(1, "user-1"))
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["updated"], 0)
        mock_db.mark_document_checked.assert_called_once_with("doc-001")

    def test_changed_content_triggers_upsert(self):
        """Doc whose hash differs triggers _sync_upsert_document with new hash."""
        old_content = b"old document content"
        new_content = b"new document content - it changed"
        doc = _make_doc(source_uri="file://docs/guide.md",
                        content_hash=_sha256(old_content))
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=[doc])
        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(return_value=new_content)), \
             patch("trusted_data_agent.core.knowledge_sync._sync_upsert_document",
                   new=AsyncMock()) as mock_upsert:
            result = _run(sync_knowledge_collection(1, "user-1"))
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["unchanged"], 0)
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args[1]
        self.assertEqual(call_kwargs["content_hash"], _sha256(new_content))

    def test_fetch_error_increments_errors_continues_loop(self):
        """Fetch failure for one doc increments errors but does not stop the loop."""
        doc1 = _make_doc("doc-001", "a.md", source_uri="file://a.md")
        doc2_content = b"document B content"
        doc2 = _make_doc("doc-002", "b.md", source_uri="file://b.md",
                         content_hash=_sha256(doc2_content))
        mock_db = self._make_mock_db(
            collection=_make_collection(), candidates=[doc1, doc2]
        )

        async def _selective_fetch(uri, user_uuid, source_root=None):
            if "a.md" in uri:
                raise OSError("File not found")
            return doc2_content

        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(side_effect=_selective_fetch)):
            result = _run(sync_knowledge_collection(1, "user-1"))
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["unchanged"], 1)

    def test_upsert_error_increments_errors_continues_loop(self):
        """Re-ingest failure increments errors but does not abort the loop."""
        content = b"changed content"
        doc = _make_doc(source_uri="file://docs/guide.md", content_hash="stale_hash")
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=[doc])
        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(return_value=content)), \
             patch("trusted_data_agent.core.knowledge_sync._sync_upsert_document",
                   new=AsyncMock(side_effect=RuntimeError("Embedding failed"))):
            result = _run(sync_knowledge_collection(1, "user-1"))
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["updated"], 0)

    def test_source_root_from_collection_forwarded_to_fetch(self):
        """source_root on collection is passed through to fetch_source."""
        content = b"content"
        doc = _make_doc(source_uri="file://docs/guide.md",
                        content_hash=_sha256(content))
        mock_db = self._make_mock_db(
            collection=_make_collection(source_root="/opt/uderia"),
            candidates=[doc],
        )
        mock_fetch = AsyncMock(return_value=content)
        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=mock_fetch):
            _run(sync_knowledge_collection(1, "user-1"))
        mock_fetch.assert_called_once_with(
            "file://docs/guide.md", "user-1", source_root="/opt/uderia"
        )

    def test_null_source_root_collection_passes_none_to_fetch(self):
        """source_root=None on collection propagates None to fetch_source."""
        content = b"content"
        doc = _make_doc(source_uri="file://docs/guide.md",
                        content_hash=_sha256(content))
        mock_db = self._make_mock_db(
            collection=_make_collection(source_root=None), candidates=[doc]
        )
        mock_fetch = AsyncMock(return_value=content)
        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=mock_fetch):
            _run(sync_knowledge_collection(1, "user-1"))
        mock_fetch.assert_called_once_with(
            "file://docs/guide.md", "user-1", source_root=None
        )

    def test_result_always_contains_duration_seconds(self):
        """Return value contains duration_seconds as a float."""
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=[])
        with patch(_PATCH_DB, return_value=mock_db):
            result = _run(sync_knowledge_collection(1, "user-1"))
        self.assertIsInstance(result["duration_seconds"], float)

    def test_mixed_outcomes_correct_tallies(self):
        """Correctly tallies checked/updated/unchanged/errors across mixed docs."""
        old_content = b"old"
        new_content = b"new"
        same_content = b"same"
        docs = [
            _make_doc("d1", "a.md", source_uri="file://a.md",
                      content_hash=_sha256(old_content)),   # -> updated
            _make_doc("d2", "b.md", source_uri="file://b.md",
                      content_hash=_sha256(same_content)),  # -> unchanged
            _make_doc("d3", "c.md", source_uri=None),       # -> unchanged (no URI)
            _make_doc("d4", "d.md", source_uri="file://d.md",
                      content_hash="stale"),                 # -> error (fetch fails)
        ]
        mock_db = self._make_mock_db(collection=_make_collection(), candidates=docs)

        async def _fetch(uri, user_uuid, source_root=None):
            if "a.md" in uri:
                return new_content
            if "b.md" in uri:
                return same_content
            raise OSError("fetch fail")

        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(side_effect=_fetch)), \
             patch("trusted_data_agent.core.knowledge_sync._sync_upsert_document",
                   new=AsyncMock()):
            result = _run(sync_knowledge_collection(1, "user-1"))

        self.assertEqual(result["checked"], 4)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["unchanged"], 2)
        self.assertEqual(result["errors"], 1)


# ---------------------------------------------------------------------------
# reindex_knowledge_collection
# ---------------------------------------------------------------------------

class TestReindexKnowledgeCollection(unittest.TestCase):
    """Tests for force re-embed / embedding model change path."""

    def _make_mock_db(self, collection=None, documents=None):
        db = MagicMock()
        db.get_collection_by_id.return_value = collection
        db.get_all_documents_in_collection.return_value = documents or []
        db.update_collection.return_value = True
        db.upsert_document_metadata.return_value = "doc-001"
        db.sync_collection_counts.return_value = (1, 5)
        return db

    def test_collection_not_found_raises(self):
        """Raises ValueError when collection_id does not exist."""
        mock_db = self._make_mock_db(collection=None)
        with patch(_PATCH_DB, return_value=mock_db):
            with self.assertRaises(ValueError):
                _run(reindex_knowledge_collection(999, "user-1"))

    def test_document_without_source_uri_is_skipped(self):
        """Doc without source_uri contributes to skipped, not reindexed."""
        mock_db = self._make_mock_db(
            collection=_make_collection(), documents=[_make_doc(source_uri=None)]
        )
        with patch(_PATCH_DB, return_value=mock_db):
            result = _run(reindex_knowledge_collection(1, "user-1"))
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["reindexed"], 0)
        self.assertEqual(result["errors"], 0)

    def test_document_with_source_uri_is_reindexed_regardless_of_hash(self):
        """Even if content hash matches, reindex always re-embeds the doc."""
        content = b"document content unchanged"
        doc = _make_doc(source_uri="file://docs/guide.md",
                        content_hash=_sha256(content))
        mock_db = self._make_mock_db(
            collection=_make_collection(), documents=[doc]
        )
        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(return_value=content)), \
             patch("trusted_data_agent.core.knowledge_sync._sync_upsert_document",
                   new=AsyncMock()) as mock_upsert:
            result = _run(reindex_knowledge_collection(1, "user-1"))
        self.assertEqual(result["reindexed"], 1)
        self.assertEqual(result["skipped"], 0)
        mock_upsert.assert_called_once()

    def test_embedding_model_locked_after_completion(self):
        """embedding_model_locked=1 is set on the collection after all docs processed."""
        mock_db = self._make_mock_db(
            collection=_make_collection(), documents=[_make_doc(source_uri=None)]
        )
        with patch(_PATCH_DB, return_value=mock_db):
            _run(reindex_knowledge_collection(1, "user-1"))
        mock_db.update_collection.assert_called_once_with(1, {"embedding_model_locked": 1})

    def test_embedding_model_locked_even_when_all_errors(self):
        """embedding_model_locked is set even if every doc failed re-indexing."""
        doc = _make_doc(source_uri="file://docs/guide.md")
        mock_db = self._make_mock_db(
            collection=_make_collection(), documents=[doc]
        )
        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(side_effect=OSError("Not found"))):
            result = _run(reindex_knowledge_collection(1, "user-1"))
        self.assertEqual(result["errors"], 1)
        mock_db.update_collection.assert_called_once_with(1, {"embedding_model_locked": 1})

    def test_fetch_error_increments_errors_continues_loop(self):
        """Fetch failure for one doc does not abort remaining docs."""
        content_b = b"document B content"
        doc1 = _make_doc("d1", "a.md", source_uri="file://a.md")
        doc2 = _make_doc("d2", "b.md", source_uri="file://b.md")
        mock_db = self._make_mock_db(
            collection=_make_collection(), documents=[doc1, doc2]
        )

        async def _selective_fetch(uri, user_uuid, source_root=None):
            if "a.md" in uri:
                raise OSError("missing")
            return content_b

        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(side_effect=_selective_fetch)), \
             patch("trusted_data_agent.core.knowledge_sync._sync_upsert_document",
                   new=AsyncMock()):
            result = _run(reindex_knowledge_collection(1, "user-1"))
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["reindexed"], 1)

    def test_strategy_field_in_result(self):
        """Result dict includes strategy field matching the requested strategy."""
        mock_db = self._make_mock_db(collection=_make_collection(), documents=[])
        with patch(_PATCH_DB, return_value=mock_db):
            result = _run(reindex_knowledge_collection(1, "user-1", strategy="in_place"))
        self.assertEqual(result["strategy"], "in_place")

    def test_result_contains_duration_seconds(self):
        """Return value always contains duration_seconds as a float."""
        mock_db = self._make_mock_db(collection=_make_collection(), documents=[])
        with patch(_PATCH_DB, return_value=mock_db):
            result = _run(reindex_knowledge_collection(1, "user-1"))
        self.assertIsInstance(result["duration_seconds"], float)

    def test_mixed_docs_correct_tallies(self):
        """Correctly tallies skipped/reindexed/errors for a mixed document set."""
        content = b"doc content"
        docs = [
            _make_doc("d1", "a.md", source_uri=None),
            _make_doc("d2", "b.md", source_uri="file://b.md"),
            _make_doc("d3", "c.md", source_uri="file://c.md"),
        ]
        mock_db = self._make_mock_db(collection=_make_collection(), documents=docs)

        async def _fetch(uri, user_uuid, source_root=None):
            if "c.md" in uri:
                raise OSError("missing")
            return content

        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.core.knowledge_sync.fetch_source",
                   new=AsyncMock(side_effect=_fetch)), \
             patch("trusted_data_agent.core.knowledge_sync._sync_upsert_document",
                   new=AsyncMock()):
            result = _run(reindex_knowledge_collection(1, "user-1"))
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["reindexed"], 1)
        self.assertEqual(result["errors"], 1)


# ---------------------------------------------------------------------------
# Stale chunk cleanup (ingest_epoch-based)
# ---------------------------------------------------------------------------

class TestStaleChunkCleanup(unittest.TestCase):
    """
    Verify that _sync_upsert_document issues a delete call for vector-store
    chunks whose ingest_epoch is older than the current ingest pass.
    """

    def _make_mock_retriever_and_backend(self, stale_ids=None):
        from trusted_data_agent.vectorstore.types import GetResult, VectorDocument

        stale_docs = [
            VectorDocument(id=sid, content="", metadata={})
            for sid in (stale_ids or [])
        ]
        mock_get_result = GetResult(documents=stale_docs, total_count=len(stale_docs))

        mock_backend = AsyncMock()
        mock_backend.has_capability.return_value = False   # force client-side path
        mock_backend.get.return_value = mock_get_result
        mock_backend.delete.return_value = None

        mock_retriever = MagicMock()
        mock_retriever.client = MagicMock()
        mock_retriever.rag_cases_dir = Path(tempfile.mkdtemp())
        mock_retriever._get_knowledge_backend = AsyncMock(return_value=mock_backend)

        return mock_retriever, mock_backend

    def _run_upsert(self, mock_retriever, mock_db, doc, content_bytes, mock_constructor):
        """Helper: run _sync_upsert_document with standard mocks."""
        from trusted_data_agent.core.knowledge_sync import _sync_upsert_document

        mock_handler = MagicMock()
        mock_handler.prepare_document_for_llm.return_value = {
            "content": content_bytes.decode("utf-8", errors="replace")
        }

        with patch(_PATCH_DB, return_value=mock_db), \
             patch("trusted_data_agent.agent.rag_retriever.get_rag_retriever",
                   return_value=mock_retriever), \
             patch("trusted_data_agent.llm.document_upload.DocumentUploadHandler",
                   return_value=mock_handler), \
             patch("trusted_data_agent.agent.repository_constructor"
                   ".create_repository_constructor",
                   return_value=mock_constructor):
            _run(_sync_upsert_document(
                collection_id=1,
                collection=_make_collection(),
                content_bytes=content_bytes,
                content_hash=_sha256(content_bytes),
                existing_doc=doc,
                user_uuid="user-1",
            ))

    def test_stale_chunks_deleted_after_upsert(self):
        """backend.delete is called with the IDs of chunks from old ingest epochs."""
        stale_ids = ["chunk_old_1", "chunk_old_2"]
        mock_retriever, mock_backend = self._make_mock_retriever_and_backend(
            stale_ids=stale_ids
        )
        doc = _make_doc(source_uri="file://docs/guide.md",
                        content_hash="oldhash", sync_enabled=1)
        doc["ingest_epoch"] = 1000000

        mock_db = MagicMock()
        mock_db.upsert_document_metadata.return_value = doc["document_id"]
        mock_db.sync_collection_counts.return_value = (1, 5)

        mock_constructor = MagicMock()
        mock_constructor.construct_async = AsyncMock(return_value={"chunks_stored": 3})

        content_bytes = b"updated content for stale chunk test"
        self._run_upsert(mock_retriever, mock_db, doc, content_bytes, mock_constructor)

        mock_backend.delete.assert_called_once()
        call_args = mock_backend.delete.call_args
        deleted_ids = call_args[1].get("ids") or call_args[0][1]
        self.assertEqual(sorted(deleted_ids), sorted(stale_ids))

    def test_no_stale_chunks_means_no_delete_call(self):
        """When backend.get returns empty ids, backend.delete is never called."""
        mock_retriever, mock_backend = self._make_mock_retriever_and_backend(
            stale_ids=[]
        )
        doc = _make_doc(source_uri="file://docs/guide.md",
                        content_hash="oldhash", sync_enabled=1)
        doc["ingest_epoch"] = 1000000

        mock_db = MagicMock()
        mock_db.upsert_document_metadata.return_value = doc["document_id"]
        mock_db.sync_collection_counts.return_value = (1, 5)

        mock_constructor = MagicMock()
        mock_constructor.construct_async = AsyncMock(return_value={"chunks_stored": 2})

        self._run_upsert(
            mock_retriever, mock_db, doc, b"updated content", mock_constructor
        )

        mock_backend.delete.assert_not_called()

    def test_metadata_row_updated_with_new_hash_and_epoch(self):
        """upsert_document_metadata is called with the new content_hash."""
        mock_retriever, _ = self._make_mock_retriever_and_backend(stale_ids=[])
        doc = _make_doc(source_uri="file://docs/guide.md",
                        content_hash="oldhash", sync_enabled=1)
        doc["ingest_epoch"] = 1000000

        mock_db = MagicMock()
        mock_db.upsert_document_metadata.return_value = doc["document_id"]
        mock_db.sync_collection_counts.return_value = (1, 5)

        mock_constructor = MagicMock()
        mock_constructor.construct_async = AsyncMock(return_value={"chunks_stored": 2})

        content_bytes = b"new content to hash"
        self._run_upsert(mock_retriever, mock_db, doc, content_bytes, mock_constructor)

        mock_db.upsert_document_metadata.assert_called_once()
        call_kwargs = mock_db.upsert_document_metadata.call_args[1]
        self.assertEqual(call_kwargs["content_hash"], _sha256(content_bytes))
        # ingest_epoch must be a recent Unix timestamp (greater than old epoch)
        self.assertGreater(call_kwargs["ingest_epoch"], doc["ingest_epoch"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
