"""
Unit tests for TeradataVectorBackend.

All Teradata SDK calls are mocked — no real Teradata connection is required.
Run with: PYTHONPATH=src python test/test_teradata_backend.py -v
"""

import asyncio
import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

# ---------------------------------------------------------------------------
# Minimal stubs so the module can be imported without the real SDKs.
# We create proper module objects (not MagicMock) to avoid Python 3.11
# InvalidSpecError when asyncio.to_thread receives a MagicMock callable.
# ---------------------------------------------------------------------------
_fake_teradatagenai = types.ModuleType("teradatagenai")
_fake_teradatagenai.VectorStore = MagicMock()
_fake_teradatagenai.set_auth_token = MagicMock()
_fake_teradatagenai.VSManager = MagicMock()
_fake_teradatagenai.VSPattern = MagicMock()
_fake_teradatagenai.VSApi = MagicMock()

_fake_teradataml = types.ModuleType("teradataml")
_fake_teradataml.create_context = MagicMock()
_fake_teradataml.execute_sql = MagicMock()
_fake_teradataml.copy_to_sql = MagicMock()

# Also stub pandas (used inside add/query) with a minimal fake
_fake_pandas = types.ModuleType("pandas")


class _FakeDataFrame:
    """Minimal DataFrame stub for tests that need row iteration."""

    def __init__(self, data=None):
        if data is None:
            data = {}
        # Accept list-of-dicts (like real pd.DataFrame([{...}, {...}]))
        if isinstance(data, list):
            if data:
                keys = list(data[0].keys())
                data = {k: [row.get(k) for row in data] for k in keys}
            else:
                data = {}
        self._data = data
        self._keys = list(data.keys())
        self._len = len(next(iter(data.values()))) if data else 0
        self.columns = list(data.keys())

    def __len__(self):
        return self._len

    @property
    def empty(self):
        return self._len == 0

    def head(self, n=5):
        trimmed = {k: v[:n] for k, v in self._data.items()}
        return _FakeDataFrame(trimmed)

    def rename(self, columns=None, **_):
        if columns and callable(columns):
            new_data = {columns(k): v for k, v in self._data.items()}
            return _FakeDataFrame(new_data)
        return self

    def iterrows(self):
        for i in range(self._len):
            row = {k: self._data[k][i] for k in self._keys}
            yield i, _FakeRow(row)

    @property
    def iloc(self):
        return _FakeIloc(self._data, self._len)


class _FakeRow(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _FakeIloc:
    def __init__(self, data, length):
        self._data = data
        self._len = length

    def __getitem__(self, item):
        if isinstance(item, tuple):
            row, col = item
            key = list(self._data.keys())[col]
            return self._data[key][row]
        raise IndexError(item)


_fake_pandas.DataFrame = _FakeDataFrame

sys.modules["teradatagenai"] = _fake_teradatagenai
sys.modules["teradataml"] = _fake_teradataml
sys.modules["pandas"] = _fake_pandas

from trusted_data_agent.vectorstore.capabilities import (
    VectorStoreCapability,
    REQUIRED_CAPABILITIES,
)
from trusted_data_agent.vectorstore.teradata_backend import TeradataVectorBackend
from trusted_data_agent.vectorstore.types import (
    CollectionConfig,
    VectorDocument,
    QueryResult,
    GetResult,
)


def _run(coro):
    """Shorthand to run a coroutine."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_backend(**overrides) -> TeradataVectorBackend:
    """Create a backend instance with sensible defaults."""
    config = {
        "host": "td-host.example.com",
        "base_url": "https://td-api.example.com",
        "username": "td_user",
        "password": "td_pass",
        "database": "TEST_DB",
        "embedding_model": "amazon.titan-embed-text-v1",
        "search_algorithm": "VECTORDISTANCE",
        "top_k": 5,
    }
    config.update(overrides)
    return TeradataVectorBackend(config)


# Helper: create an async side_effect that returns values in order
def _async_side_effects(values):
    """Return an async function that yields values in order."""
    it = iter(values)

    async def _side_effect(*args, **kwargs):
        try:
            val = next(it)
            if isinstance(val, Exception):
                raise val
            return val
        except StopIteration:
            return None

    return _side_effect


async def _async_return(val=None):
    return val


class TestIdentity(unittest.TestCase):
    """backend_type and capabilities."""

    def test_backend_type(self):
        backend = _make_backend()
        self.assertEqual(backend.backend_type, "teradata")

    def test_capabilities_required_present(self):
        """All 7 REQUIRED_CAPABILITIES must be declared."""
        caps = _make_backend().capabilities()
        missing = REQUIRED_CAPABILITIES - caps
        self.assertEqual(missing, set(), f"Missing required capabilities: {missing}")

    def test_capabilities_no_false_metadata_filter(self):
        """GET_BY_METADATA_FILTER must NOT be declared (not implemented)."""
        caps = _make_backend().capabilities()
        self.assertNotIn(VectorStoreCapability.GET_BY_METADATA_FILTER, caps)

    def test_capabilities_includes_upsert(self):
        """UPSERT must be declared (works via Teradata UPI semantics)."""
        caps = _make_backend().capabilities()
        self.assertIn(VectorStoreCapability.UPSERT, caps)

    def test_capabilities_includes_server_side_embedding(self):
        caps = _make_backend().capabilities()
        self.assertIn(VectorStoreCapability.SERVER_SIDE_EMBEDDING, caps)


class TestInitialize(unittest.TestCase):
    """Lifecycle: initialize(), shutdown()."""

    def test_initialize_no_credentials_raises(self):
        """Should raise RuntimeError if neither user/pass nor pat_token provided."""
        backend = _make_backend(username="", password="", pat_token="")
        with self.assertRaises(RuntimeError) as ctx:
            _run(backend.initialize())
        self.assertIn("pat_token", str(ctx.exception))

    def test_initialize_success(self):
        """initialize() should set _initialized = True on success."""
        backend = _make_backend()

        async def _fake_to_thread(fn, *args, **kwargs):
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            _run(backend.initialize())

        self.assertTrue(backend._initialized)

    def test_initialize_pat_token_auth(self):
        """PAT token path should call set_auth_token with pat_token kwarg."""
        backend = _make_backend(pat_token="eyJ_test_token", pem_file="/path/cert.pem")
        calls = []

        async def _fake_to_thread(fn, *args, **kwargs):
            calls.append((fn, args, kwargs))
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            _run(backend.initialize())

        self.assertTrue(backend._initialized)
        # First call is create_context (SQL), second is set_auth_token (PAT)
        self.assertEqual(len(calls), 2)
        _, _, second_kwargs = calls[1]
        self.assertIn("pat_token", second_kwargs)
        self.assertEqual(second_kwargs["pat_token"], "eyJ_test_token")
        # valid_from should NOT be passed (matches Getting Started pattern)
        self.assertNotIn("valid_from", second_kwargs)

    def test_initialize_strips_open_analytics(self):
        """base_url ending with /open-analytics should be stripped (Getting Started pattern)."""
        backend = _make_backend(
            base_url="https://example.com/api/accounts/abc123/open-analytics",
            pat_token="tok",
            pem_file="/path/cert.pem",
        )
        calls = []

        async def _fake_to_thread(fn, *args, **kwargs):
            calls.append((fn, args, kwargs))
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            _run(backend.initialize())

        _, _, second_kwargs = calls[1]
        self.assertEqual(
            second_kwargs["base_url"],
            "https://example.com/api/accounts/abc123",
        )

    def test_initialize_missing_teradatagenai(self):
        """Should raise RuntimeError with install hint if teradatagenai is absent."""
        backend = _make_backend()

        with patch.dict(sys.modules, {"teradatagenai": None}):
            # Force reimport to trigger ImportError
            with self.assertRaises((RuntimeError, ImportError)):
                _run(backend.initialize())


class TestCollections(unittest.TestCase):
    """Collection management: create, delete, count."""

    def _backend_with_mock_aio(self):
        backend = _make_backend()
        backend._initialized = True
        return backend

    def test_create_collection(self):
        """create_collection should call staging table DDL and register the collection."""
        backend = self._backend_with_mock_aio()

        async def _fake_to_thread(fn, *args, **kwargs):
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            config = CollectionConfig(name="test_collection")
            info = _run(backend.create_collection(config))

        self.assertEqual(info.name, "test_collection")
        self.assertEqual(info.document_count, 0)
        self.assertIn("test_collection", backend._collections)

    def test_create_collection_already_exists(self):
        """Should tolerate Teradata error 3803 (table already exists)."""
        backend = self._backend_with_mock_aio()

        async def _fake_to_thread(fn, *args, **kwargs):
            raise Exception("[Error 3803] Table already exists")

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            config = CollectionConfig(name="existing_collection")
            info = _run(backend.create_collection(config))

        self.assertEqual(info.name, "existing_collection")
        self.assertIn("existing_collection", backend._collections)

    def test_delete_collection(self):
        """delete_collection should remove from stores and collections."""
        backend = self._backend_with_mock_aio()

        mock_vs = MagicMock()
        backend._stores["my_vs"] = mock_vs
        backend._collections.add("my_vs")

        call_count = [0]

        async def _fake_to_thread(fn, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:  # vs.status poll
                return "COMPLETED"
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            deleted = _run(backend.delete_collection("my_vs"))

        self.assertTrue(deleted)
        self.assertNotIn("my_vs", backend._stores)
        self.assertNotIn("my_vs", backend._collections)

    def test_count(self):
        """count() should execute SELECT COUNT(*) and return integer."""
        backend = self._backend_with_mock_aio()

        mock_result = MagicMock()
        mock_result.to_pandas.return_value = _FakeDataFrame({"CNT": [42]})

        async def _fake_to_thread(fn, *args, **kwargs):
            return mock_result

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            count = _run(backend.count("my_collection"))

        self.assertEqual(count, 42)


class TestDocumentOps(unittest.TestCase):
    """Document add, query, get_by_ids."""

    def test_add_documents(self):
        """add() should write to staging + delta tables, then create VS."""
        backend = _make_backend()
        backend._initialized = True
        backend._collections.add("test_vs")

        mock_vs = MagicMock()
        _fake_teradatagenai.VectorStore.return_value = mock_vs

        call_count = [0]

        async def _fake_to_thread(fn, *args, **kwargs):
            call_count[0] += 1
            # Call 4 = vs.status poll
            if call_count[0] == 4:
                return "COMPLETED"
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            docs = [
                VectorDocument(id="doc1", content="Hello world", metadata={"key": "val"}),
                VectorDocument(id="doc2", content="Foo bar"),
            ]
            added = _run(backend.add("test_vs", docs))

        self.assertEqual(added, 2)
        self.assertIn("test_vs", backend._stores)

    def test_query(self):
        """query() should call similarity_search and return QueryResult."""
        backend = _make_backend()
        backend._initialized = True
        backend._collections.add("search_vs")

        mock_vs = MagicMock()
        backend._stores["search_vs"] = mock_vs

        result_df = _FakeDataFrame({
            "CHUNK_ID": ["id1", "id2"],
            "CONTENT": ["result one", "result two"],
            "SCORE": [0.95, 0.80],
        })

        meta_result_1 = MagicMock()
        meta_result_1.to_pandas.return_value = _FakeDataFrame(
            {"METADATA_JSON": [json.dumps({"source": "test"})]}
        )
        meta_result_2 = MagicMock()
        meta_result_2.to_pandas.return_value = _FakeDataFrame(
            {"METADATA_JSON": [json.dumps({"source": "test2"})]}
        )

        call_count = [0]
        side_effects = [result_df, meta_result_1, meta_result_2]

        async def _fake_to_thread(fn, *args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(side_effects):
                return side_effects[idx]
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            qr = _run(backend.query("search_vs", "test query", n_results=2))

        self.assertIsInstance(qr, QueryResult)
        self.assertEqual(len(qr.documents), 2)
        self.assertEqual(qr.documents[0].id, "id1")
        self.assertEqual(qr.documents[0].content, "result one")
        # Score 0.95 -> distance 0.05
        self.assertAlmostEqual(qr.distances[0], 0.05, places=2)

    def test_get_by_ids(self):
        """get() with ids should return matching documents from staging table."""
        backend = _make_backend()
        backend._initialized = True

        mock_result = MagicMock()
        mock_result.to_pandas.return_value = _FakeDataFrame({
            "CHUNK_ID": ["chunk_a"],
            "CONTENT": ["The content"],
            "METADATA_JSON": [json.dumps({"doc_id": "d1"})],
        })

        async def _fake_to_thread(fn, *args, **kwargs):
            return mock_result

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            gr = _run(backend.get("my_coll", ids=["chunk_a"]))

        self.assertIsInstance(gr, GetResult)
        self.assertEqual(len(gr.documents), 1)
        self.assertEqual(gr.documents[0].id, "chunk_a")
        self.assertEqual(gr.documents[0].content, "The content")
        self.assertEqual(gr.documents[0].metadata["doc_id"], "d1")


class TestQueryAfterRestart(unittest.TestCase):
    """Simulate server restart: _collections and _stores are empty."""

    def test_query_works_with_empty_collections(self):
        """query() should auto-attach to an existing VectorStore even if _collections is empty."""
        backend = _make_backend()
        backend._initialized = True
        # Simulate restart: _collections and _stores are empty
        backend._collections = set()
        backend._stores = {}

        # VectorStore constructor returns a mock
        mock_vs = MagicMock()
        _fake_teradatagenai.VectorStore.return_value = mock_vs

        result_df = _FakeDataFrame({
            "CHUNK_ID": ["id1"],
            "CONTENT": ["result one"],
            "SCORE": [0.90],
        })

        meta_result = MagicMock()
        meta_result.to_pandas.return_value = _FakeDataFrame(
            {"METADATA_JSON": [json.dumps({"source": "test"})]}
        )

        call_count = [0]
        side_effects = [result_df, meta_result]

        async def _fake_to_thread(fn, *args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(side_effects):
                return side_effects[idx]
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            qr = _run(backend.query("my_vs", "test query", n_results=1))

        self.assertIsInstance(qr, QueryResult)
        self.assertEqual(len(qr.documents), 1)
        self.assertEqual(qr.documents[0].id, "id1")
        # _collections should now contain the auto-registered collection
        self.assertIn("my_vs", backend._collections)
        self.assertIn("my_vs", backend._stores)


class TestServerSideChunking(unittest.TestCase):
    """Server-side chunking: add_document_files() passes files to VectorStore.create()."""

    def test_capabilities_includes_server_side_chunking(self):
        """SERVER_SIDE_CHUNKING must be declared."""
        caps = _make_backend().capabilities()
        self.assertIn(VectorStoreCapability.SERVER_SIDE_CHUNKING, caps)

    def test_add_document_files(self):
        """document_files passed to VectorStore.create() with chunking config."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True

        mock_vs = MagicMock()
        _fake_teradatagenai.VectorStore.return_value = mock_vs

        call_count = [0]

        async def _fake_to_thread(fn, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:  # vs.status poll
                return "COMPLETED"
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            result = _run(
                backend.add_document_files(
                    "my_collection",
                    ["/tmp/test.pdf"],
                    chunking_config={"chunk_size": 500},
                )
            )

        # Verify VectorStore was instantiated with collection name
        _fake_teradatagenai.VectorStore.assert_called_with("my_collection")

        # Verify create() was called (via to_thread) — check the first call's fn
        self.assertGreater(call_count[0], 0)

        # Verify result
        self.assertEqual(result, 1)

        # Verify collection registered
        self.assertIn("my_collection", backend._collections)
        self.assertIn("my_collection", backend._stores)

    def test_add_document_files_default_config(self):
        """When chunking_config is None, defaults (chunk_size=500, optimized=True) are used."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True

        mock_vs = MagicMock()
        _fake_teradatagenai.VectorStore.return_value = mock_vs

        call_count = [0]

        async def _fake_to_thread(fn, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:  # vs.status poll
                return "COMPLETED"
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            result = _run(
                backend.add_document_files(
                    "default_config_vs",
                    ["/tmp/a.pdf", "/tmp/b.pdf"],
                )
            )

        # Two files → result should be 2
        self.assertEqual(result, 2)
        self.assertIn("default_config_vs", backend._collections)

    def test_add_document_files_multiple_files(self):
        """Multiple files should all be passed in document_files list."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True

        mock_vs = MagicMock()
        _fake_teradatagenai.VectorStore.return_value = mock_vs

        create_call_kwargs = {}

        async def _fake_to_thread(fn, *args, **kwargs):
            # Capture the create() call kwargs
            if fn == mock_vs.create:
                create_call_kwargs.update(kwargs)
                return None
            # vs.status poll
            return "COMPLETED"

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            result = _run(
                backend.add_document_files(
                    "multi_file_vs",
                    ["/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"],
                    chunking_config={"chunk_size": 1000, "optimized_chunking": False},
                )
            )

        self.assertEqual(result, 3)
        # Verify create() received all files
        self.assertEqual(
            create_call_kwargs.get("document_files"),
            ["/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"],
        )
        self.assertEqual(create_call_kwargs.get("chunk_size"), 1000)
        self.assertFalse(create_call_kwargs.get("optimized_chunking"))
        # Should NOT have object_names (that's the client-side path)
        self.assertNotIn("object_names", create_call_kwargs)


class TestServerSideBrowse(unittest.TestCase):
    """count() and get() fallback to chunks_table for server-side collections."""

    def _make_result(self, data):
        """Create a mock execute_sql result with to_pandas()."""
        result = MagicMock()
        result.to_pandas.return_value = _FakeDataFrame(data)
        return result

    def test_count_falls_back_to_chunks_table(self):
        """When staging count is 0, count() resolves chunks_table via index and counts it."""
        backend = _make_backend()
        backend._initialized = True

        call_log = []

        async def _fake_to_thread(fn, *args, **kwargs):
            sql = args[0] if args else ""
            call_log.append(sql)
            if "UDERIA_VS_" in sql:
                # Staging count → 0
                return self._make_result({"CNT": [0]})
            if "vectorstore_" in sql and "_index" in sql:
                # Index table → resolve chunks table name
                return self._make_result({"TN": ["chunks_table_abc123"]})
            if "chunks_table_" in sql:
                # Chunks table count → 42
                return self._make_result({"CNT": [42]})
            return self._make_result({})

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            count = _run(backend.count("my_coll"))

        self.assertEqual(count, 42)

    def test_count_staging_takes_priority(self):
        """When staging table has rows, count() returns staging count (no fallback)."""
        backend = _make_backend()
        backend._initialized = True

        async def _fake_to_thread(fn, *args, **kwargs):
            return self._make_result({"CNT": [15]})

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            count = _run(backend.count("my_coll"))

        self.assertEqual(count, 15)

    def test_get_falls_back_to_chunks_table(self):
        """When staging table doesn't exist, get() resolves and queries chunks_table."""
        backend = _make_backend()
        backend._initialized = True

        call_log = []

        async def _fake_to_thread(fn, *args, **kwargs):
            sql = args[0] if args else ""
            call_log.append(sql)

            if "UDERIA_VS_" in sql:
                raise Exception("[Error 3807] Object 'UDERIA_VS_my_coll' does not exist.")
            if "vectorstore_" in sql and "_index" in sql:
                return self._make_result({"TN": ["chunks_table_abc123"]})
            if "chunks_table_" in sql:
                return self._make_result({
                    "TD_ID": ["1", "2", "3"],
                    "file_splits": ["chunk one text", "chunk two text", "chunk three text"],
                    "TD_FILENAME": ["report.pdf", "report.pdf", "report.pdf"],
                    "RN": [1, 2, 3],
                })
            return self._make_result({})

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            result = _run(backend.get("my_coll", limit=10, offset=0))

        self.assertEqual(result.total_count, 3)
        self.assertEqual(len(result.documents), 3)
        self.assertEqual(result.documents[0].id, "1")
        self.assertEqual(result.documents[0].content, "chunk one text")
        self.assertEqual(result.documents[0].metadata, {"filename": "report.pdf"})

    def test_get_staging_takes_priority(self):
        """When staging table has data, get() returns staging rows (no fallback)."""
        backend = _make_backend()
        backend._initialized = True

        async def _fake_to_thread(fn, *args, **kwargs):
            return self._make_result({
                "CHUNK_ID": ["c1", "c2"],
                "CONTENT": ["hello", "world"],
                "METADATA_JSON": ['{"source": "test.pdf"}', '{}'],
                "RN": [1, 2],
            })

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            result = _run(backend.get("my_coll", limit=10, offset=0))

        self.assertEqual(result.total_count, 2)
        self.assertEqual(result.documents[0].id, "c1")
        self.assertEqual(result.documents[0].content, "hello")
        self.assertEqual(result.documents[0].metadata, {"source": "test.pdf"})

    def test_get_no_index_table(self):
        """When neither staging nor index table exists, get() returns empty."""
        backend = _make_backend()
        backend._initialized = True

        async def _fake_to_thread(fn, *args, **kwargs):
            raise Exception("[Error 3807] Object does not exist.")

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            result = _run(backend.get("nonexistent_coll", limit=10, offset=0))

        self.assertEqual(result.total_count, 0)
        self.assertEqual(len(result.documents), 0)

    def test_get_by_ids_chunks_table(self):
        """get() by IDs falls back to chunks_table when staging missing."""
        backend = _make_backend()
        backend._initialized = True

        call_log = []

        async def _fake_to_thread(fn, *args, **kwargs):
            sql = args[0] if args else ""
            call_log.append(sql)
            if "UDERIA_VS_" in sql:
                raise Exception("[Error 3807] does not exist")
            if "vectorstore_" in sql and "_index" in sql:
                return self._make_result({"TN": ["chunks_table_xyz"]})
            if "chunks_table_" in sql:
                return self._make_result({
                    "TD_ID": ["5"],
                    "file_splits": ["found chunk"],
                    "TD_FILENAME": ["doc.pdf"],
                })
            return self._make_result({})

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            result = _run(backend.get("my_coll", ids=["5"]))

        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.documents[0].id, "5")
        self.assertEqual(result.documents[0].content, "found chunk")


class TestShutdown(unittest.TestCase):
    """shutdown() should clear state and call VSManager.disconnect()."""

    def test_shutdown_clears_state(self):
        backend = _make_backend()
        backend._stores["a"] = MagicMock()
        backend._collections.add("a")
        backend._initialized = True

        async def _fake_to_thread(fn, *args, **kwargs):
            return None

        with patch("trusted_data_agent.vectorstore.teradata_backend.asyncio") as mock_aio:
            mock_aio.to_thread = _fake_to_thread
            mock_aio.sleep = asyncio.sleep
            _run(backend.shutdown())

        self.assertEqual(len(backend._stores), 0)
        self.assertEqual(len(backend._collections), 0)
        self.assertFalse(backend._initialized)


if __name__ == "__main__":
    unittest.main()
