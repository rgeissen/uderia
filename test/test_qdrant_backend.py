"""
Unit tests for QdrantBackend.

All Qdrant SDK calls are mocked — no real Qdrant connection is required.
Run with: PYTHONPATH=src python test/test_qdrant_backend.py -v
"""

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Minimal stubs so the module can be imported without the real qdrant-client.
# ---------------------------------------------------------------------------
_fake_qdrant = types.ModuleType("qdrant_client")
_fake_qdrant_models = types.ModuleType("qdrant_client.models")


class _FakeDistance:
    COSINE = "Cosine"
    EUCLID = "Euclid"
    DOT = "Dot"


class _FakeVectorParams:
    def __init__(self, size=None, distance=None):
        self.size = size
        self.distance = distance


class _FakePointStruct:
    def __init__(self, id=None, vector=None, payload=None):
        self.id = id
        self.vector = vector
        self.payload = payload


class _FakePointIdsList:
    def __init__(self, points=None):
        self.points = points


class _FakeMatchValue:
    def __init__(self, value=None):
        self.value = value


class _FakeMatchAny:
    def __init__(self, any=None):
        self.any = any


class _FakeMatchExcept:
    def __init__(self, **kwargs):
        self.except_values = kwargs.get("except", [])


class _FakeRange:
    def __init__(self, gt=None, gte=None, lt=None, lte=None):
        self.gt = gt
        self.gte = gte
        self.lt = lt
        self.lte = lte


class _FakeFieldCondition:
    def __init__(self, key=None, match=None, range=None):
        self.key = key
        self.match = match
        self.range = range


class _FakeFilter:
    def __init__(self, must=None, must_not=None, should=None):
        self.must = must
        self.must_not = must_not
        self.should = should


_fake_qdrant_models.Distance = _FakeDistance
_fake_qdrant_models.VectorParams = _FakeVectorParams
_fake_qdrant_models.PointStruct = _FakePointStruct
_fake_qdrant_models.PointIdsList = _FakePointIdsList
_fake_qdrant_models.MatchValue = _FakeMatchValue
_fake_qdrant_models.MatchAny = _FakeMatchAny
_fake_qdrant_models.MatchExcept = _FakeMatchExcept
_fake_qdrant_models.Range = _FakeRange
_fake_qdrant_models.FieldCondition = _FakeFieldCondition
_fake_qdrant_models.Filter = _FakeFilter

_fake_qdrant.AsyncQdrantClient = MagicMock()
_fake_qdrant.models = _fake_qdrant_models

sys.modules["qdrant_client"] = _fake_qdrant
sys.modules["qdrant_client.models"] = _fake_qdrant_models

from trusted_data_agent.vectorstore.capabilities import (
    VectorStoreCapability,
    REQUIRED_CAPABILITIES,
)
from trusted_data_agent.vectorstore.qdrant_backend import QdrantBackend
from trusted_data_agent.vectorstore.types import (
    CollectionConfig,
    CollectionInfo,
    DistanceMetric,
    GetResult,
    QueryResult,
    VectorDocument,
)
from trusted_data_agent.vectorstore.filters import (
    FieldFilter,
    AndFilter,
    OrFilter,
    FilterOp,
    to_qdrant_filter,
    eq,
    ne,
    and_,
    or_,
)


def _run(coro):
    """Shorthand to run a coroutine."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_backend(**overrides) -> QdrantBackend:
    """Create a backend instance with sensible defaults."""
    config = {
        "url": "https://test.cloud.qdrant.io:6333",
        "api_key": "test-api-key",
        "prefer_grpc": False,
        "timeout": 30,
    }
    config.update(overrides)
    return QdrantBackend(config)


def _mock_client() -> AsyncMock:
    """Create an AsyncMock mimicking AsyncQdrantClient."""
    client = AsyncMock()
    client.close = AsyncMock()
    return client


class TestIdentity(unittest.TestCase):
    """backend_type and capabilities."""

    def test_backend_type(self):
        backend = _make_backend()
        self.assertEqual(backend.backend_type, "qdrant")

    def test_capabilities_required_present(self):
        """All 7 REQUIRED_CAPABILITIES must be declared."""
        caps = _make_backend().capabilities()
        missing = REQUIRED_CAPABILITIES - caps
        self.assertEqual(missing, set(), f"Missing required capabilities: {missing}")

    def test_capabilities_includes_optional(self):
        """UPSERT, GET_BY_METADATA_FILTER, UPDATE_METADATA, EMBEDDING_PASSTHROUGH, GET_ALL."""
        caps = _make_backend().capabilities()
        for cap in [
            VectorStoreCapability.UPSERT,
            VectorStoreCapability.GET_BY_METADATA_FILTER,
            VectorStoreCapability.UPDATE_METADATA,
            VectorStoreCapability.EMBEDDING_PASSTHROUGH,
            VectorStoreCapability.GET_ALL,
        ]:
            self.assertIn(cap, caps, f"Missing optional capability: {cap}")

    def test_capabilities_excludes_server_side(self):
        """SERVER_SIDE_EMBEDDING and SERVER_SIDE_CHUNKING must NOT be declared."""
        caps = _make_backend().capabilities()
        self.assertNotIn(VectorStoreCapability.SERVER_SIDE_EMBEDDING, caps)
        self.assertNotIn(VectorStoreCapability.SERVER_SIDE_CHUNKING, caps)


class TestLifecycle(unittest.TestCase):
    """initialize() and shutdown()."""

    def test_initialize_success(self):
        backend = _make_backend()
        mock_client = _mock_client()
        _fake_qdrant.AsyncQdrantClient.return_value = mock_client

        _run(backend.initialize())

        self.assertTrue(backend._initialized)
        self.assertIs(backend._client, mock_client)

    def test_initialize_missing_url(self):
        backend = _make_backend(url="")
        with self.assertRaises(RuntimeError) as ctx:
            _run(backend.initialize())
        self.assertIn("URL", str(ctx.exception))

    def test_initialize_missing_api_key(self):
        backend = _make_backend(api_key="")
        with self.assertRaises(RuntimeError) as ctx:
            _run(backend.initialize())
        self.assertIn("API key", str(ctx.exception))

    def test_shutdown(self):
        backend = _make_backend()
        mock_client = _mock_client()
        backend._client = mock_client
        backend._initialized = True

        _run(backend.shutdown())

        mock_client.close.assert_awaited_once()
        self.assertFalse(backend._initialized)
        self.assertIsNone(backend._client)

    def test_shutdown_idempotent(self):
        """Calling shutdown() when not initialized should not raise."""
        backend = _make_backend()
        _run(backend.shutdown())  # Should not raise


class TestCollections(unittest.TestCase):
    """Collection management."""

    def _initialized_backend(self):
        backend = _make_backend()
        backend._client = _mock_client()
        backend._initialized = True
        return backend

    def test_create_collection(self):
        backend = self._initialized_backend()

        with patch(
            "trusted_data_agent.vectorstore.qdrant_backend.SentenceTransformerProvider"
        ) as mock_stp:
            mock_provider = MagicMock()
            mock_provider.dimensions = 384
            mock_stp.get_cached.return_value = mock_provider

            config = CollectionConfig(name="test_coll")
            info = _run(backend.create_collection(config))

        self.assertIsInstance(info, CollectionInfo)
        self.assertEqual(info.name, "test_coll")
        self.assertEqual(info.document_count, 0)
        backend._client.create_collection.assert_awaited_once()

    def test_get_or_create_collection_exists(self):
        backend = self._initialized_backend()
        backend._client.collection_exists = AsyncMock(return_value=True)

        mock_info = MagicMock()
        mock_info.points_count = 42
        backend._client.get_collection = AsyncMock(return_value=mock_info)

        config = CollectionConfig(name="existing")
        info = _run(backend.get_or_create_collection(config))

        self.assertEqual(info.name, "existing")
        self.assertEqual(info.document_count, 42)
        backend._client.create_collection.assert_not_awaited()

    def test_get_or_create_collection_creates(self):
        backend = self._initialized_backend()
        backend._client.collection_exists = AsyncMock(return_value=False)

        with patch(
            "trusted_data_agent.vectorstore.qdrant_backend.SentenceTransformerProvider"
        ) as mock_stp:
            mock_provider = MagicMock()
            mock_provider.dimensions = 384
            mock_stp.get_cached.return_value = mock_provider

            config = CollectionConfig(name="new_coll")
            info = _run(backend.get_or_create_collection(config))

        self.assertEqual(info.name, "new_coll")
        self.assertEqual(info.document_count, 0)
        backend._client.create_collection.assert_awaited_once()

    def test_delete_collection(self):
        backend = self._initialized_backend()
        backend._client.collection_exists = AsyncMock(return_value=True)

        result = _run(backend.delete_collection("to_delete"))

        self.assertTrue(result)
        backend._client.delete_collection.assert_awaited_once_with("to_delete")

    def test_delete_collection_not_found(self):
        backend = self._initialized_backend()
        backend._client.collection_exists = AsyncMock(return_value=False)

        result = _run(backend.delete_collection("missing"))

        self.assertFalse(result)
        backend._client.delete_collection.assert_not_awaited()

    def test_count(self):
        backend = self._initialized_backend()
        mock_count = MagicMock()
        mock_count.count = 99
        backend._client.count = AsyncMock(return_value=mock_count)

        result = _run(backend.count("my_coll"))

        self.assertEqual(result, 99)

    def test_get_collection_info(self):
        backend = self._initialized_backend()
        backend._client.collection_exists = AsyncMock(return_value=True)
        mock_info = MagicMock()
        mock_info.points_count = 55
        backend._client.get_collection = AsyncMock(return_value=mock_info)

        info = _run(backend.get_collection_info("info_coll"))

        self.assertIsInstance(info, CollectionInfo)
        self.assertEqual(info.name, "info_coll")
        self.assertEqual(info.document_count, 55)

    def test_get_collection_info_not_found(self):
        backend = self._initialized_backend()
        backend._client.collection_exists = AsyncMock(return_value=False)

        info = _run(backend.get_collection_info("missing"))

        self.assertIsNone(info)


class TestDocumentWrites(unittest.TestCase):
    """add, upsert, delete, update_metadata."""

    def _initialized_backend(self):
        backend = _make_backend()
        backend._client = _mock_client()
        backend._initialized = True
        return backend

    def test_add_with_embedding_provider(self):
        backend = self._initialized_backend()
        mock_provider = MagicMock()
        mock_provider.embed_texts.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

        docs = [
            VectorDocument(id="d1", content="hello", metadata={"key": "val"}),
            VectorDocument(id="d2", content="world", metadata={}),
        ]
        count = _run(backend.add("coll", docs, embedding_provider=mock_provider))

        self.assertEqual(count, 2)
        mock_provider.embed_texts.assert_called_once_with(["hello", "world"])
        backend._client.upsert.assert_awaited_once()

    def test_add_with_precomputed_embeddings(self):
        backend = self._initialized_backend()

        docs = [
            VectorDocument(
                id="d1",
                content="hello",
                metadata={"key": "val"},
                embedding=[0.1, 0.2, 0.3],
            ),
        ]
        count = _run(backend.add("coll", docs))

        self.assertEqual(count, 1)
        backend._client.upsert.assert_awaited_once()
        # Verify the point was built correctly
        call_args = backend._client.upsert.call_args
        points = call_args.kwargs.get("points", call_args[1].get("points", []))
        self.assertEqual(len(points), 1)
        # "d1" is not a valid UUID so it gets hashed to a deterministic UUID5
        from trusted_data_agent.vectorstore.qdrant_backend import _QDRANT_NS
        import uuid as _uuid
        expected_id = str(_uuid.uuid5(_QDRANT_NS, "d1"))
        self.assertEqual(points[0].id, expected_id)
        self.assertEqual(points[0].vector, [0.1, 0.2, 0.3])
        self.assertEqual(points[0].payload["_content"], "hello")
        self.assertEqual(points[0].payload["key"], "val")
        # Original ID stored in payload for round-trip
        self.assertEqual(points[0].payload["_uderia_id"], "d1")

    def test_add_empty_list(self):
        backend = self._initialized_backend()
        count = _run(backend.add("coll", []))
        self.assertEqual(count, 0)
        backend._client.upsert.assert_not_awaited()

    def test_add_without_provider_or_embedding_raises(self):
        backend = self._initialized_backend()
        docs = [VectorDocument(id="d1", content="hello", metadata={})]
        with self.assertRaises(ValueError):
            _run(backend.add("coll", docs))

    def test_upsert_delegates_to_add(self):
        backend = self._initialized_backend()
        mock_provider = MagicMock()
        mock_provider.embed_texts.return_value = [[0.1, 0.2]]

        docs = [VectorDocument(id="d1", content="hello", metadata={})]
        count = _run(backend.upsert("coll", docs, embedding_provider=mock_provider))

        self.assertEqual(count, 1)
        backend._client.upsert.assert_awaited_once()

    def test_delete(self):
        backend = self._initialized_backend()
        count = _run(backend.delete("coll", ["id1", "id2"]))

        self.assertEqual(count, 2)
        backend._client.delete.assert_awaited_once()

    def test_delete_empty_list(self):
        backend = self._initialized_backend()
        count = _run(backend.delete("coll", []))
        self.assertEqual(count, 0)
        backend._client.delete.assert_not_awaited()

    def test_update_metadata(self):
        backend = self._initialized_backend()
        count = _run(
            backend.update_metadata(
                "coll",
                ids=["id1", "id2"],
                metadatas=[{"new_key": "v1"}, {"new_key": "v2"}],
            )
        )

        self.assertEqual(count, 2)
        self.assertEqual(backend._client.set_payload.await_count, 2)

    def test_sanitize_payload_removes_none(self):
        """None values in metadata should be stripped from the payload."""
        backend = self._initialized_backend()
        mock_provider = MagicMock()
        mock_provider.embed_texts.return_value = [[0.1, 0.2]]

        docs = [
            VectorDocument(
                id="d1",
                content="hello",
                metadata={"keep": "yes", "drop": None},
            ),
        ]
        _run(backend.add("coll", docs, embedding_provider=mock_provider))

        call_args = backend._client.upsert.call_args
        points = call_args.kwargs.get("points", call_args[1].get("points", []))
        payload = points[0].payload
        self.assertEqual(payload["keep"], "yes")
        self.assertNotIn("drop", payload)
        self.assertEqual(payload["_content"], "hello")


class TestDocumentReads(unittest.TestCase):
    """query and get."""

    def _initialized_backend(self):
        backend = _make_backend()
        backend._client = _mock_client()
        backend._initialized = True
        return backend

    def test_query(self):
        backend = self._initialized_backend()
        mock_provider = MagicMock()
        mock_provider.embed_query.return_value = [0.1, 0.2, 0.3]

        # Mock query_points response
        point1 = MagicMock()
        point1.id = "p1"
        point1.payload = {"_content": "result one", "source": "test.pdf"}
        point1.score = 0.95

        point2 = MagicMock()
        point2.id = "p2"
        point2.payload = {"_content": "result two"}
        point2.score = 0.80

        mock_result = MagicMock()
        mock_result.points = [point1, point2]
        backend._client.query_points = AsyncMock(return_value=mock_result)

        qr = _run(
            backend.query("coll", "test query", n_results=2, embedding_provider=mock_provider)
        )

        self.assertIsInstance(qr, QueryResult)
        self.assertEqual(len(qr.documents), 2)
        self.assertEqual(qr.documents[0].id, "p1")
        self.assertEqual(qr.documents[0].content, "result one")
        self.assertEqual(qr.documents[0].metadata, {"source": "test.pdf"})
        # Score 0.95 → distance 0.05
        self.assertAlmostEqual(qr.distances[0], 0.05, places=2)
        # Score 0.80 → distance 0.20
        self.assertAlmostEqual(qr.distances[1], 0.20, places=2)

    def test_query_without_provider_raises(self):
        backend = self._initialized_backend()
        with self.assertRaises(ValueError):
            _run(backend.query("coll", "test"))

    def test_get_by_ids(self):
        backend = self._initialized_backend()

        point = MagicMock()
        point.id = "abc"
        point.payload = {"_content": "doc content", "source": "file.pdf"}
        point.vector = None

        backend._client.retrieve = AsyncMock(return_value=[point])

        gr = _run(backend.get("coll", ids=["abc"]))

        self.assertIsInstance(gr, GetResult)
        self.assertEqual(len(gr.documents), 1)
        self.assertEqual(gr.documents[0].id, "abc")
        self.assertEqual(gr.documents[0].content, "doc content")
        self.assertEqual(gr.documents[0].metadata, {"source": "file.pdf"})
        backend._client.retrieve.assert_awaited_once()

    def test_get_all_scroll(self):
        backend = self._initialized_backend()

        point1 = MagicMock()
        point1.id = "s1"
        point1.payload = {"_content": "first"}
        point1.vector = None

        point2 = MagicMock()
        point2.id = "s2"
        point2.payload = {"_content": "second"}
        point2.vector = None

        # scroll returns (points, next_page_offset)
        backend._client.scroll = AsyncMock(return_value=([point1, point2], None))

        gr = _run(backend.get("coll", limit=10, offset=0))

        self.assertIsInstance(gr, GetResult)
        self.assertEqual(len(gr.documents), 2)
        self.assertEqual(gr.documents[0].id, "s1")
        self.assertEqual(gr.documents[1].id, "s2")

    def test_get_scroll_with_offset(self):
        """Integer offset emulated via fetch-and-slice."""
        backend = self._initialized_backend()

        points = []
        for i in range(5):
            p = MagicMock()
            p.id = f"p{i}"
            p.payload = {"_content": f"content {i}"}
            p.vector = None
            points.append(p)

        backend._client.scroll = AsyncMock(return_value=(points, None))

        # Offset=2, limit=2 → should skip first 2, return next 2
        gr = _run(backend.get("coll", limit=2, offset=2))

        self.assertEqual(len(gr.documents), 2)
        self.assertEqual(gr.documents[0].id, "p2")
        self.assertEqual(gr.documents[1].id, "p3")


class TestFilterTranslation(unittest.TestCase):
    """to_qdrant_filter() translates MetadataFilter AST to Qdrant models."""

    def test_none_filter(self):
        self.assertIsNone(to_qdrant_filter(None))

    def test_eq_filter(self):
        f = to_qdrant_filter(eq("status", "active"))
        self.assertIsNotNone(f.must)
        self.assertEqual(len(f.must), 1)
        self.assertEqual(f.must[0].key, "status")
        self.assertEqual(f.must[0].match.value, "active")

    def test_ne_filter(self):
        f = to_qdrant_filter(ne("status", "deleted"))
        self.assertIsNotNone(f.must_not)
        self.assertEqual(len(f.must_not), 1)
        self.assertEqual(f.must_not[0].key, "status")
        self.assertEqual(f.must_not[0].match.value, "deleted")

    def test_range_filters(self):
        for op, attr in [
            (FilterOp.GT, "gt"),
            (FilterOp.GTE, "gte"),
            (FilterOp.LT, "lt"),
            (FilterOp.LTE, "lte"),
        ]:
            with self.subTest(op=op):
                f = to_qdrant_filter(FieldFilter("score", op, 0.5))
                self.assertEqual(len(f.must), 1)
                range_obj = f.must[0].range
                self.assertEqual(getattr(range_obj, attr), 0.5)

    def test_and_filter(self):
        f = to_qdrant_filter(and_(eq("a", 1), eq("b", 2)))
        self.assertIsNotNone(f.must)
        self.assertEqual(len(f.must), 2)

    def test_or_filter(self):
        f = to_qdrant_filter(or_(eq("a", 1), eq("b", 2)))
        self.assertIsNotNone(f.should)
        self.assertEqual(len(f.should), 2)

    def test_and_with_ne(self):
        """AND with a NE child should produce must_not list."""
        f = to_qdrant_filter(and_(eq("status", "active"), ne("type", "draft")))
        self.assertIsNotNone(f.must)
        self.assertIsNotNone(f.must_not)
        self.assertEqual(len(f.must), 1)
        self.assertEqual(len(f.must_not), 1)


class TestNotInitialized(unittest.TestCase):
    """Operations on an uninitialized backend should raise."""

    def test_create_collection_not_initialized(self):
        backend = _make_backend()
        with self.assertRaises(RuntimeError):
            _run(backend.create_collection(CollectionConfig(name="test")))

    def test_query_not_initialized(self):
        backend = _make_backend()
        with self.assertRaises(RuntimeError):
            _run(backend.query("coll", "query"))

    def test_get_not_initialized(self):
        backend = _make_backend()
        with self.assertRaises(RuntimeError):
            _run(backend.get("coll", ids=["id1"]))


if __name__ == "__main__":
    unittest.main()
