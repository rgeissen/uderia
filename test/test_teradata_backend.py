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

# ── Collection V2 class stubs ───────────────────────────────────────────────
# A real class so isinstance(instance, Collection) works in backend code.

class _FakeCollection:
    """Stub for teradatagenai.Collection (V2 API)."""

    def __init__(self, name=None, **kwargs):
        self.name = name

    def create(self, **kwargs):
        return None

    def update(self, **kwargs):
        return None

    def similarity_search(self, **kwargs):
        return _FakeDataFrame({
            "CHUNK_ID": [], "CONTENT": [], "SCORE": [],
        })

    def status(self):
        return None

    def destroy(self):
        return None


_fake_teradatagenai.Collection = _FakeCollection
_fake_teradatagenai.Collection.from_documents = MagicMock(
    return_value=_FakeCollection()
)
_fake_teradatagenai.ContentBasedIndex = MagicMock()
_fake_teradatagenai.TeradataAI = MagicMock()
_fake_teradatagenai.HNSW = MagicMock()
_fake_teradatagenai.SearchParams = MagicMock()
_fake_teradatagenai.LocalConfig = MagicMock()
_fake_teradatagenai.BasicIngestor = MagicMock()
_fake_teradatagenai.NVIngestor = MagicMock()
_fake_teradatagenai.CollectionManager = MagicMock()

# Stub teradatagenai.common.constants (imported as CollectionType)
_fake_tg_common = types.ModuleType("teradatagenai.common")
_fake_tg_common_constants = types.ModuleType("teradatagenai.common.constants")


class _FakeCollectionType:
    CONTENT_BASED = "CONTENT_BASED"
    FILE_CONTENT_BASED = "FILE_CONTENT_BASED"


_fake_tg_common_constants.CollectionType = _FakeCollectionType
sys.modules["teradatagenai.common"] = _fake_tg_common
sys.modules["teradatagenai.common.constants"] = _fake_tg_common_constants

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
    ServerSideChunkingConfig,
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

    def test_capabilities_includes_metadata_filter(self):
        """GET_BY_METADATA_FILTER must be declared (implemented via staging SQL)."""
        caps = _make_backend().capabilities()
        self.assertIn(VectorStoreCapability.GET_BY_METADATA_FILTER, caps)

    def test_capabilities_includes_hybrid_search(self):
        """HYBRID_SEARCH must be declared (Python-side RRF fusion)."""
        caps = _make_backend().capabilities()
        self.assertIn(VectorStoreCapability.HYBRID_SEARCH, caps)

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

        async def _fake(fn, *args, **kwargs):
            return None

        backend._run_in_td_thread = _fake
        _run(backend.initialize())

        self.assertTrue(backend._initialized)

    def test_initialize_pat_token_auth(self):
        """PAT token path should call set_auth_token with pat_token kwarg."""
        backend = _make_backend(pat_token="eyJ_test_token", pem_file="/path/cert.pem")
        calls = []

        async def _fake(fn, *args, **kwargs):
            calls.append((fn, args, kwargs))
            return None

        backend._run_in_td_thread = _fake
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

        async def _fake(fn, *args, **kwargs):
            calls.append((fn, args, kwargs))
            return None

        backend._run_in_td_thread = _fake
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

        async def _fake(fn, *args, **kwargs):
            return None

        backend._run_in_td_thread = _fake
        config = CollectionConfig(name="test_collection")
        info = _run(backend.create_collection(config))

        self.assertEqual(info.name, "test_collection")
        self.assertEqual(info.document_count, 0)
        self.assertIn("test_collection", backend._collections)

    def test_create_collection_already_exists(self):
        """Should tolerate Teradata error 3803 (table already exists)."""
        backend = self._backend_with_mock_aio()

        async def _fake(fn, *args, **kwargs):
            raise Exception("[Error 3803] Table already exists")

        backend._run_in_td_thread = _fake
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

        async def _fake(fn, *args, **kwargs):
            return None

        backend._run_in_td_thread = _fake
        deleted = _run(backend.delete_collection("my_vs"))

        self.assertTrue(deleted)
        self.assertNotIn("my_vs", backend._stores)
        self.assertNotIn("my_vs", backend._collections)

    def test_count(self):
        """count() should execute SELECT COUNT(*) and return integer."""
        backend = self._backend_with_mock_aio()

        mock_result = MagicMock()
        mock_result.to_pandas.return_value = _FakeDataFrame({"CNT": [42]})

        async def _fake(fn, *args, **kwargs):
            return mock_result

        backend._run_in_td_thread = _fake
        count = _run(backend.count("my_collection"))

        self.assertEqual(count, 42)


class TestDocumentOps(unittest.TestCase):
    """Document add, query, get_by_ids."""

    def test_add_documents(self):
        """add() should write to staging + delta tables, then create VS (V2 Collection API)."""
        backend = _make_backend()
        backend._initialized = True
        backend._collections.add("test_vs")

        # Short-circuit _poll_status so create/update returns immediately
        async def _noop_poll(vs, operation, **kwargs):
            return vs

        backend._poll_status = _noop_poll

        # Return a mock Collection so col.create is recorded
        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.create.return_value = None

        async def _fake_create_col(name):
            return mock_col

        backend._create_collection = _fake_create_col

        import functools as _f

        async def _fake(fn, *args, **kwargs):
            if kwargs:
                fn = _f.partial(fn, **kwargs)
            return fn(*args)

        backend._run_in_td_thread = _fake
        backend._execute_sql = AsyncMock(return_value=MagicMock())

        docs = [
            VectorDocument(id="doc1", content="Hello world", metadata={"key": "val"}),
            VectorDocument(id="doc2", content="Foo bar"),
        ]
        added = _run(backend.add("test_vs", docs))

        self.assertEqual(added, 2)
        self.assertIn("test_vs", backend._stores)

    def test_query(self):
        """query() should call similarity_search and return QueryResult (V2 SearchParams)."""
        backend = _make_backend()
        backend._initialized = True
        backend._collections.add("search_vs")

        result_df = _FakeDataFrame({
            "CHUNK_ID": ["id1", "id2"],
            "CONTENT": ["result one", "result two"],
            "SCORE": [0.95, 0.80],
        })
        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.similarity_search.return_value = result_df
        backend._stores["search_vs"] = mock_col
        backend._get_store = AsyncMock(return_value=mock_col)

        import functools as _f

        async def _fake(fn, *args, **kwargs):
            if kwargs:
                fn = _f.partial(fn, **kwargs)
            return fn(*args)

        backend._run_in_td_thread = _fake

        # Batch metadata fetch returns both docs in one call
        batch_result = MagicMock()
        batch_result.to_pandas.return_value = _FakeDataFrame({
            "CHUNK_ID": ["id1", "id2"],
            "CONTENT": ["result one", "result two"],
            "METADATA_JSON": [json.dumps({"source": "test"}), json.dumps({"source": "test2"})],
        })
        backend._execute_sql = AsyncMock(return_value=batch_result)

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

        async def _fake(fn, *args, **kwargs):
            return mock_result

        backend._run_in_td_thread = _fake
        gr = _run(backend.get("my_coll", ids=["chunk_a"]))

        self.assertIsInstance(gr, GetResult)
        self.assertEqual(len(gr.documents), 1)
        self.assertEqual(gr.documents[0].id, "chunk_a")
        self.assertEqual(gr.documents[0].content, "The content")
        self.assertEqual(gr.documents[0].metadata["doc_id"], "d1")


class TestQueryAfterRestart(unittest.TestCase):
    """Simulate server restart: _collections and _stores are empty."""

    def test_query_works_with_empty_collections(self):
        """query() should auto-attach to an existing Collection even if _collections is empty."""
        backend = _make_backend()
        backend._initialized = True
        # Simulate restart: _collections and _stores are empty
        backend._collections = set()
        backend._stores = {}

        # V2: _get_store calls _create_collection; mock it to return a usable Collection
        result_df = _FakeDataFrame({
            "CHUNK_ID": ["id1"],
            "CONTENT": ["result one"],
            "SCORE": [0.90],
        })
        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.similarity_search.return_value = result_df

        async def _fake_create_col(name):
            return mock_col

        backend._create_collection = _fake_create_col

        import functools as _f

        async def _fake(fn, *args, **kwargs):
            if kwargs:
                fn = _f.partial(fn, **kwargs)
            return fn(*args)

        backend._run_in_td_thread = _fake

        batch_result = MagicMock()
        batch_result.to_pandas.return_value = _FakeDataFrame({
            "CHUNK_ID": ["id1"],
            "CONTENT": ["result one"],
            "METADATA_JSON": [json.dumps({"source": "test"})],
        })
        backend._execute_sql = AsyncMock(return_value=batch_result)

        qr = _run(backend.query("my_vs", "test query", n_results=1))

        self.assertIsInstance(qr, QueryResult)
        self.assertEqual(len(qr.documents), 1)
        self.assertEqual(qr.documents[0].id, "id1")
        # _collections should now contain the auto-registered collection
        self.assertIn("my_vs", backend._collections)
        self.assertIn("my_vs", backend._stores)


class TestServerSideChunking(unittest.TestCase):
    """Server-side chunking: add_document_files() uses Collection.from_documents() (V2)."""

    def setUp(self):
        """Reset V2 class mocks before each test."""
        _fake_teradatagenai.Collection.from_documents.reset_mock()
        _fake_teradatagenai.Collection.from_documents.return_value = _FakeCollection()
        _fake_teradatagenai.BasicIngestor.reset_mock()
        _fake_teradatagenai.NVIngestor.reset_mock()
        _fake_teradatagenai.LocalConfig.reset_mock()

    def _make_run_in_td_thread(self):
        """Return a fake _run_in_td_thread that actually calls fn(**kwargs)."""
        import functools as _f

        async def _impl(fn, *args, **kwargs):
            if kwargs:
                fn = _f.partial(fn, **kwargs)
            return fn(*args)

        return _impl

    def test_capabilities_includes_server_side_chunking(self):
        """SERVER_SIDE_CHUNKING must be declared."""
        caps = _make_backend().capabilities()
        self.assertIn(VectorStoreCapability.SERVER_SIDE_CHUNKING, caps)

    def test_add_document_files(self):
        """add_document_files() calls Collection.from_documents() (V2), not VectorStore."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True
        backend._run_in_td_thread = self._make_run_in_td_thread()

        result = _run(
            backend.add_document_files(
                "my_collection",
                ["/tmp/test.pdf"],
                chunking_config=ServerSideChunkingConfig(chunk_size=500),
            )
        )

        # V2: Collection.from_documents() was called (not VectorStore)
        _fake_teradatagenai.Collection.from_documents.assert_called_once()

        self.assertEqual(result, 1)
        self.assertIn("my_collection", backend._collections)
        self.assertIn("my_collection", backend._stores)

    def test_add_document_files_default_config(self):
        """When chunking_config is None, defaults (chunk_size=2000, optimized=True) are used."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True
        backend._run_in_td_thread = self._make_run_in_td_thread()

        result = _run(
            backend.add_document_files(
                "default_config_vs",
                ["/tmp/a.pdf", "/tmp/b.pdf"],
            )
        )

        self.assertEqual(result, 2)
        self.assertIn("default_config_vs", backend._collections)
        # Default is optimized_chunking=True → NVIngestor, not BasicIngestor
        _fake_teradatagenai.NVIngestor.assert_called_once()

    def test_add_document_files_multiple_files(self):
        """Multiple files passed to LocalConfig; BasicIngestor gets chunk_size."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True
        backend._run_in_td_thread = self._make_run_in_td_thread()

        result = _run(
            backend.add_document_files(
                "multi_file_vs",
                ["/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"],
                chunking_config=ServerSideChunkingConfig(
                    chunk_size=1000, optimized_chunking=False,
                ),
            )
        )

        self.assertEqual(result, 3)
        # V2: LocalConfig was called with all files
        _fake_teradatagenai.LocalConfig.assert_called_once_with(
            files=["/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"]
        )
        # V2: BasicIngestor was called with chunk_size (not VectorStore.create kwargs)
        basic_call_kwargs = _fake_teradatagenai.BasicIngestor.call_args[1]
        self.assertEqual(basic_call_kwargs.get("chunk_size"), 1000)
        # header/footer absent (both 0)
        self.assertNotIn("header_height", basic_call_kwargs)
        self.assertNotIn("footer_height", basic_call_kwargs)

    def test_add_document_files_header_footer(self):
        """header_height and footer_height forwarded to BasicIngestor (V2)."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True
        backend._run_in_td_thread = self._make_run_in_td_thread()

        result = _run(
            backend.add_document_files(
                "trim_test",
                ["/tmp/doc.pdf"],
                chunking_config=ServerSideChunkingConfig(
                    optimized_chunking=False,
                    chunk_size=500,
                    header_height=50,
                    footer_height=55,
                ),
            )
        )

        self.assertEqual(result, 1)
        basic_call_kwargs = _fake_teradatagenai.BasicIngestor.call_args[1]
        self.assertEqual(basic_call_kwargs.get("header_height"), 50)
        self.assertEqual(basic_call_kwargs.get("footer_height"), 55)

    def test_add_document_files_zero_trim_not_passed(self):
        """When header/footer are 0, they should NOT be in BasicIngestor kwargs."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True
        backend._run_in_td_thread = self._make_run_in_td_thread()

        _run(
            backend.add_document_files(
                "no_trim_test",
                ["/tmp/doc.pdf"],
                chunking_config=ServerSideChunkingConfig(
                    optimized_chunking=False,
                    chunk_size=500,
                ),  # header_height=0, footer_height=0
            )
        )

        basic_call_kwargs = _fake_teradatagenai.BasicIngestor.call_args[1]
        self.assertNotIn("header_height", basic_call_kwargs)
        self.assertNotIn("footer_height", basic_call_kwargs)

    def test_add_document_files_none_config_uses_defaults(self):
        """Passing None → default optimized_chunking=True → NVIngestor, not BasicIngestor."""
        backend = _make_backend(pat_token="tok", pem_file="/p.pem")
        backend._initialized = True
        backend._run_in_td_thread = self._make_run_in_td_thread()

        _run(
            backend.add_document_files(
                "default_vs",
                ["/tmp/a.pdf"],
                chunking_config=None,
            )
        )

        # Default: optimized_chunking=True → NVIngestor
        _fake_teradatagenai.NVIngestor.assert_called_once()
        # BasicIngestor must NOT be called
        _fake_teradatagenai.BasicIngestor.assert_not_called()


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

        async def _fake(fn, *args, **kwargs):
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

        backend._run_in_td_thread = _fake
        count = _run(backend.count("my_coll"))

        self.assertEqual(count, 42)

    def test_count_staging_takes_priority(self):
        """When staging table has rows, count() returns staging count (no fallback)."""
        backend = _make_backend()
        backend._initialized = True

        async def _fake(fn, *args, **kwargs):
            return self._make_result({"CNT": [15]})

        backend._run_in_td_thread = _fake
        count = _run(backend.count("my_coll"))

        self.assertEqual(count, 15)

    def test_get_falls_back_to_chunks_table(self):
        """When staging table doesn't exist, get() resolves and queries chunks_table."""
        backend = _make_backend()
        backend._initialized = True

        call_log = []

        async def _fake(fn, *args, **kwargs):
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

        backend._run_in_td_thread = _fake
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

        async def _fake(fn, *args, **kwargs):
            return self._make_result({
                "CHUNK_ID": ["c1", "c2"],
                "CONTENT": ["hello", "world"],
                "METADATA_JSON": ['{"source": "test.pdf"}', '{}'],
                "RN": [1, 2],
            })

        backend._run_in_td_thread = _fake
        result = _run(backend.get("my_coll", limit=10, offset=0))

        self.assertEqual(result.total_count, 2)
        self.assertEqual(result.documents[0].id, "c1")
        self.assertEqual(result.documents[0].content, "hello")
        self.assertEqual(result.documents[0].metadata, {"source": "test.pdf"})

    def test_get_no_index_table(self):
        """When neither staging nor index table exists, get() returns empty."""
        backend = _make_backend()
        backend._initialized = True

        async def _fake(fn, *args, **kwargs):
            raise Exception("[Error 3807] Object does not exist.")

        backend._run_in_td_thread = _fake
        result = _run(backend.get("nonexistent_coll", limit=10, offset=0))

        self.assertEqual(result.total_count, 0)
        self.assertEqual(len(result.documents), 0)

    def test_get_by_ids_chunks_table(self):
        """get() by IDs falls back to chunks_table when staging missing."""
        backend = _make_backend()
        backend._initialized = True

        call_log = []

        async def _fake(fn, *args, **kwargs):
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

        backend._run_in_td_thread = _fake
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

        async def _fake(fn, *args, **kwargs):
            return None

        backend._run_in_td_thread = _fake
        _run(backend.shutdown())

        self.assertEqual(len(backend._stores), 0)
        self.assertEqual(len(backend._collections), 0)
        self.assertFalse(backend._initialized)


class TestMetadataFilterTranslator(unittest.TestCase):
    """Unit tests for to_teradata_sql_where() in filters.py."""

    def setUp(self):
        from trusted_data_agent.vectorstore.filters import (
            to_teradata_sql_where, eq, ne, gt, gte, lt, lte, and_, or_,
            FieldFilter, FilterOp,
        )
        self.fn = to_teradata_sql_where
        self.eq = eq
        self.ne = ne
        self.gt = gt
        self.gte = gte
        self.lt = lt
        self.lte = lte
        self.and_ = and_
        self.or_ = or_
        self.FieldFilter = FieldFilter
        self.FilterOp = FilterOp

    def test_none_returns_none(self):
        self.assertIsNone(self.fn(None))

    def test_eq_string(self):
        sql = self.fn(self.eq("category", "manual"))
        self.assertIn("JSON_VALUE(METADATA_JSON, '$.category')", sql)
        self.assertIn("= 'manual'", sql)

    def test_eq_number(self):
        sql = self.fn(self.eq("score", 42))
        self.assertIn("CAST(JSON_VALUE(METADATA_JSON, '$.score') AS FLOAT)", sql)
        self.assertIn("= 42", sql)

    def test_ne_string(self):
        sql = self.fn(self.ne("status", "archived"))
        self.assertIn("<>", sql)
        self.assertIn("'archived'", sql)

    def test_gt(self):
        sql = self.fn(self.gt("priority", 3))
        self.assertIn("> 3", sql)
        self.assertIn("CAST(", sql)

    def test_gte(self):
        sql = self.fn(self.gte("priority", 3))
        self.assertIn(">= 3", sql)

    def test_lt(self):
        sql = self.fn(self.lt("age", 30))
        self.assertIn("< 30", sql)

    def test_lte(self):
        sql = self.fn(self.lte("age", 30))
        self.assertIn("<= 30", sql)

    def test_in_strings(self):
        sql = self.fn(self.FieldFilter("tag", self.FilterOp.IN, ["a", "b", "c"]))
        self.assertIn("IN (", sql)
        self.assertIn("'a'", sql)
        self.assertIn("'b'", sql)

    def test_not_in_strings(self):
        sql = self.fn(self.FieldFilter("tag", self.FilterOp.NOT_IN, ["x", "y"]))
        self.assertIn("NOT IN (", sql)

    def test_and_filter(self):
        sql = self.fn(self.and_(self.eq("a", "1"), self.eq("b", "2")))
        self.assertIn(" AND ", sql)
        self.assertIn("'$.a'", sql)
        self.assertIn("'$.b'", sql)

    def test_or_filter(self):
        sql = self.fn(self.or_(self.eq("x", "foo"), self.eq("x", "bar")))
        self.assertIn(" OR ", sql)

    def test_single_quote_escaping(self):
        sql = self.fn(self.eq("name", "O'Brien"))
        self.assertIn("O''Brien", sql)

    def test_nested_and_or(self):
        """AND of two OR clauses → parenthesised correctly."""
        f = self.and_(
            self.or_(self.eq("a", "1"), self.eq("a", "2")),
            self.eq("b", "3"),
        )
        sql = self.fn(f)
        self.assertIn(" AND ", sql)
        self.assertIn(" OR ", sql)


class TestQueryMetadataFilter(unittest.TestCase):
    """query() with a where= filter pre-fetches CHUNK_IDs and post-filters results."""

    def _make_initialized_backend(self):
        backend = _make_backend()
        backend._initialized = True
        backend._collections.add("coll")
        return backend

    def _sql_result(self, rows_dict):
        """Helper: build a MagicMock that looks like a teradataml execute_sql result."""
        mock_res = MagicMock()
        mock_res.to_pandas.return_value = _FakeDataFrame(rows_dict)
        return mock_res

    def test_query_with_metadata_filter_prunes_results(self):
        """Only IDs returned by the staging pre-filter should appear in results."""
        backend = self._make_initialized_backend()

        # SDK returns 3 results; staging pre-filter only allows "id1" and "id3"
        sdk_df = _FakeDataFrame({
            "CHUNK_ID": ["id1", "id2", "id3"],
            "CONTENT": ["doc one", "doc two", "doc three"],
            "SCORE": [0.9, 0.85, 0.8],
        })
        mock_vs = MagicMock()
        mock_vs.similarity_search.return_value = sdk_df
        backend._stores["coll"] = mock_vs

        # Two SQL calls: (1) pre-filter fetch, (2) batch content fetch
        sql_results = [
            self._sql_result({"CHUNK_ID": ["id1", "id3"]}),
            self._sql_result({
                "CHUNK_ID": ["id1", "id3"],
                "CONTENT": ["doc one", "doc three"],
                "METADATA_JSON": [
                    json.dumps({"category": "A"}),
                    json.dumps({"category": "B"}),
                ],
            }),
        ]
        sql_idx = [0]

        async def _fake_execute_sql(sql):
            idx = sql_idx[0]; sql_idx[0] += 1
            return sql_results[idx] if idx < len(sql_results) else sql_results[-1]

        async def _fake_run_in_td_thread(fn, *args, **kwargs):
            if kwargs:
                import functools as _f
                fn = _f.partial(fn, **kwargs)
            return fn(*args)

        backend._execute_sql = _fake_execute_sql
        backend._run_in_td_thread = _fake_run_in_td_thread
        backend._get_store = AsyncMock(return_value=mock_vs)

        from trusted_data_agent.vectorstore.filters import eq

        qr = _run(backend.query("coll", "test query", n_results=5, where=eq("category", "A")))

        ids = [d.id for d in qr.documents]
        self.assertIn("id1", ids)
        self.assertNotIn("id2", ids)

    def test_query_empty_filter_returns_empty(self):
        """If the metadata pre-filter matches nothing, return empty QueryResult immediately."""
        backend = self._make_initialized_backend()

        sdk_called = [False]

        async def _fake_execute_sql(sql):
            mock_res = MagicMock()
            mock_res.to_pandas.return_value = _FakeDataFrame({"CHUNK_ID": []})
            return mock_res

        async def _fake_run_in_td_thread(fn, *args, **kwargs):
            sdk_called[0] = True
            return _FakeDataFrame({"CHUNK_ID": [], "CONTENT": [], "SCORE": []})

        backend._execute_sql = _fake_execute_sql
        backend._run_in_td_thread = _fake_run_in_td_thread
        backend._get_store = AsyncMock(return_value=MagicMock())

        from trusted_data_agent.vectorstore.filters import eq

        qr = _run(backend.query("coll", "test query", n_results=5, where=eq("missing", "val")))

        self.assertEqual(len(qr.documents), 0)
        self.assertFalse(sdk_called[0], "SDK should not be called when pre-filter returns nothing")


class TestHybridSearch(unittest.TestCase):
    """HYBRID and KEYWORD search modes via Python RRF fusion."""

    def _make_initialized_backend(self):
        backend = _make_backend()
        backend._initialized = True
        backend._collections.add("coll")
        return backend

    def test_rrf_fuse_basic(self):
        """RRF fusion combines two ranked lists and returns merged top-N IDs."""
        semantic = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.7}]
        lexical = [{"id": "b", "score": 0.8}, {"id": "c", "score": 0.6}]
        result = TeradataVectorBackend._rrf_fuse(semantic, lexical, n_results=3)
        # "b" appears in both lists → should rank highest (or very high)
        self.assertIn("b", result)
        self.assertIn("a", result)
        self.assertIn("c", result)

    def test_rrf_fuse_prefers_both_lists(self):
        """A document in both lists should outrank one in only one list."""
        semantic = [{"id": "x", "score": 0.5}, {"id": "shared", "score": 0.4}]
        lexical = [{"id": "shared", "score": 0.8}, {"id": "y", "score": 0.3}]
        result = TeradataVectorBackend._rrf_fuse(semantic, lexical, n_results=3)
        self.assertEqual(result[0], "shared")

    def _make_initialized_backend(self):
        backend = _make_backend()
        backend._initialized = True
        backend._collections.add("coll")
        return backend

    def _sql_result(self, rows_dict):
        mock_res = MagicMock()
        mock_res.to_pandas.return_value = _FakeDataFrame(rows_dict)
        return mock_res

    def test_keyword_mode_uses_only_lexical_leg(self):
        """KEYWORD mode should not call vs.similarity_search at all."""
        backend = self._make_initialized_backend()

        sdk_called = [False]
        mock_vs = MagicMock()
        mock_vs.similarity_search.side_effect = lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("SDK must not be called in KEYWORD mode")
        )
        backend._stores["coll"] = mock_vs

        sql_results = [
            self._sql_result({"CHUNK_ID": ["id1"], "CONTENT": ["hello world keyword"]}),
            self._sql_result({
                "CHUNK_ID": ["id1"],
                "CONTENT": ["hello world keyword"],
                "METADATA_JSON": [json.dumps({})],
            }),
        ]
        sql_idx = [0]

        async def _fake_execute_sql(sql):
            idx = sql_idx[0]; sql_idx[0] += 1
            return sql_results[idx] if idx < len(sql_results) else sql_results[-1]

        async def _fake_run_in_td_thread(fn, *args, **kwargs):
            sdk_called[0] = True
            raise AssertionError("SDK must not be called in KEYWORD mode")

        backend._execute_sql = _fake_execute_sql
        backend._run_in_td_thread = _fake_run_in_td_thread
        backend._get_store = AsyncMock(return_value=mock_vs)

        from trusted_data_agent.vectorstore.types import SearchMode

        qr = _run(backend.query("coll", "hello keyword", n_results=5, search_mode=SearchMode.KEYWORD))

        self.assertFalse(sdk_called[0], "SDK must not be called in KEYWORD mode")
        self.assertIsInstance(qr, QueryResult)

    def test_hybrid_mode_calls_both_legs(self):
        """HYBRID mode calls SDK (dense) AND lexical SQL, then fuses via RRF."""
        backend = self._make_initialized_backend()

        sdk_df = _FakeDataFrame({
            "CHUNK_ID": ["id1", "id2"],
            "CONTENT": ["semantic doc", "another"],
            "SCORE": [0.9, 0.75],
        })
        mock_vs = MagicMock()
        mock_vs.similarity_search.return_value = sdk_df
        backend._stores["coll"] = mock_vs
        backend._get_store = AsyncMock(return_value=mock_vs)

        sql_results = [
            # lexical search
            self._sql_result({"CHUNK_ID": ["id2", "id3"], "CONTENT": ["another", "lexical only"]}),
            # batch content fetch for fused IDs
            self._sql_result({
                "CHUNK_ID": ["id1", "id2"],
                "CONTENT": ["semantic doc", "another"],
                "METADATA_JSON": [json.dumps({}), json.dumps({})],
            }),
        ]
        sql_idx = [0]

        async def _fake_execute_sql(sql):
            idx = sql_idx[0]; sql_idx[0] += 1
            return sql_results[idx] if idx < len(sql_results) else sql_results[-1]

        async def _fake_run_in_td_thread(fn, *args, **kwargs):
            import functools as _f
            if kwargs:
                fn = _f.partial(fn, **kwargs)
            return fn(*args)

        backend._execute_sql = _fake_execute_sql
        backend._run_in_td_thread = _fake_run_in_td_thread

        from trusted_data_agent.vectorstore.types import SearchMode

        qr = _run(backend.query("coll", "test query", n_results=3, search_mode=SearchMode.HYBRID))

        self.assertIsInstance(qr, QueryResult)
        self.assertGreater(len(qr.documents), 0)


class TestGetWithMetadataFilter(unittest.TestCase):
    """get() with where= appends AND clause to staging SQL."""

    def test_get_with_where_filter(self):
        """where= filter should be appended to the staging SQL WHERE clause."""
        backend = _make_backend()
        backend._initialized = True

        sql_issued = []

        mock_result = MagicMock()
        mock_result.to_pandas.return_value = _FakeDataFrame({
            "CHUNK_ID": ["id1"],
            "CONTENT": ["filtered content"],
            "METADATA_JSON": [json.dumps({"status": "active"})],
        })

        async def _fake_execute_sql(sql):
            sql_issued.append(sql)
            return mock_result

        backend._execute_sql = _fake_execute_sql

        from trusted_data_agent.vectorstore.filters import eq

        gr = _run(backend.get("coll", where=eq("status", "active")))

        self.assertTrue(len(sql_issued) > 0)
        combined_sql = " ".join(sql_issued)
        self.assertIn("JSON_VALUE", combined_sql)
        self.assertIn("status", combined_sql)
        self.assertIn("active", combined_sql)


class TestCollectionAPIMigration(unittest.TestCase):
    """Verify all SDK calls use Collection V2 API — no VectorStore V1 calls."""

    # ── helpers ──────────────────────────────────────────────────────────────

    def setUp(self):
        """Reset V2 class mocks before each test."""
        _fake_teradatagenai.Collection.from_documents.reset_mock()
        _fake_teradatagenai.Collection.from_documents.return_value = _FakeCollection()
        _fake_teradatagenai.ContentBasedIndex.reset_mock()
        _fake_teradatagenai.TeradataAI.reset_mock()
        _fake_teradatagenai.HNSW.reset_mock()
        _fake_teradatagenai.SearchParams.reset_mock()
        _fake_teradatagenai.LocalConfig.reset_mock()
        _fake_teradatagenai.BasicIngestor.reset_mock()
        _fake_teradatagenai.NVIngestor.reset_mock()

    def _make_v2_backend(self, **config_overrides):
        """Backend with _initialized=True and _poll_status short-circuited."""
        b = _make_backend(**config_overrides)
        b._initialized = True

        async def _noop_poll(vs, operation, **kwargs):
            return vs

        b._poll_status = _noop_poll
        return b

    def _make_run_in_td_thread(self, call_log=None):
        """Fake _run_in_td_thread that calls fn(**kwargs) synchronously."""
        import functools as _f
        _log = call_log if call_log is not None else []

        async def _impl(fn, *args, **kwargs):
            _log.append({"fn": fn, "args": args, "kwargs": kwargs})
            if kwargs:
                fn = _f.partial(fn, **kwargs)
            return fn(*args)

        return _impl, _log

    def _make_execute_sql(self, rows_by_keyword=None):
        """Fake _execute_sql that returns empty results by default."""
        rows_by_keyword = rows_by_keyword or {}

        async def _impl(sql):
            for keyword, fake_result in rows_by_keyword.items():
                if keyword in sql:
                    return fake_result
            result = MagicMock()
            result.to_pandas.return_value = _FakeDataFrame({})
            return result

        return _impl

    # ── Phase A tests ─────────────────────────────────────────────────────────

    def test_create_uses_collection_api(self):
        """add() first-add path calls Collection.create() with ContentBasedIndex."""
        backend = self._make_v2_backend()
        backend._collections.add("test_coll")

        mock_col = _FakeCollection()
        create_calls = []

        async def _fake_create_collection(name):
            return mock_col

        backend._create_collection = _fake_create_collection

        run_in_td, call_log = self._make_run_in_td_thread()

        # Wrap to capture col.create() call but skip executing it
        async def _capturing_run_in_td(fn, *args, **kwargs):
            call_log.append({"fn": fn, "args": args, "kwargs": kwargs})
            if fn is mock_col.create if callable(getattr(mock_col, "create", None)) else False:
                create_calls.append(kwargs)
            return None  # return None for all SDK calls

        backend._run_in_td_thread = _capturing_run_in_td
        backend._execute_sql = self._make_execute_sql()

        docs = [VectorDocument(id="doc1", content="Hello world")]
        _run(backend.add("test_coll", docs))

        # Verify ContentBasedIndex was instantiated (not document_files like V1)
        _fake_teradatagenai.ContentBasedIndex.assert_called()
        cbi_kwargs = _fake_teradatagenai.ContentBasedIndex.call_args[1]
        self.assertIn("key_columns", cbi_kwargs)
        self.assertEqual(cbi_kwargs.get("key_columns"), ["CHUNK_ID"])
        self.assertNotIn("document_files", cbi_kwargs)  # V1-specific kwarg absent

        # Verify collection registered
        self.assertIn("test_coll", backend._stores)
        self.assertIn("test_coll", backend._collections)

    def test_add_uses_collection_update(self):
        """add() subsequent-add path calls col.update(alter_operation='ADD')."""
        backend = self._make_v2_backend()
        backend._collections.add("test_coll")

        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.update.return_value = None
        backend._stores["test_coll"] = mock_col

        # Return mock_col so col.update is mock_col.update (not a fresh _FakeCollection)
        async def _fake_create_col(name):
            return mock_col

        backend._create_collection = _fake_create_col

        run_in_td, call_log = self._make_run_in_td_thread()
        backend._run_in_td_thread = run_in_td
        backend._execute_sql = self._make_execute_sql()

        docs = [VectorDocument(id="doc1", content="Hello")]
        _run(backend.add("test_coll", docs))

        # Find the col.update call in call_log
        update_calls = [
            c for c in call_log
            if c.get("fn") is mock_col.update
        ]
        self.assertEqual(len(update_calls), 1)
        self.assertEqual(update_calls[0]["kwargs"].get("alter_operation"), "ADD")
        self.assertEqual(update_calls[0]["kwargs"].get("update_style"), "MINOR")

    def test_delete_uses_collection_update(self):
        """delete() calls col.update(alter_operation='DELETE')."""
        backend = self._make_v2_backend()
        backend._collections.add("test_coll")

        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.update.return_value = None
        backend._stores["test_coll"] = mock_col

        # Mock staging table to return rows for deletion
        staging_result = MagicMock()
        staging_result.to_pandas.return_value = _FakeDataFrame({
            "CHUNK_ID": ["doc1"],
            "CONTENT": ["Some content"],
        })

        run_in_td, call_log = self._make_run_in_td_thread()
        backend._run_in_td_thread = run_in_td

        sql_calls = []

        async def _fake_execute_sql(sql):
            sql_calls.append(sql)
            return staging_result

        backend._execute_sql = _fake_execute_sql

        _run(backend.delete("test_coll", ["doc1"]))

        # Find the col.update(alter_operation=DELETE) call
        update_calls = [
            c for c in call_log
            if c.get("fn") is mock_col.update
        ]
        self.assertEqual(len(update_calls), 1)
        self.assertEqual(update_calls[0]["kwargs"].get("alter_operation"), "DELETE")

    def test_query_semantic_uses_collection_search_params(self):
        """SEMANTIC query passes SearchParams(search_type='semantic_search') to SDK."""
        backend = self._make_v2_backend()
        backend._collections.add("coll")

        sdk_df = _FakeDataFrame({
            "CHUNK_ID": ["id1"],
            "CONTENT": ["result"],
            "SCORE": [0.9],
        })
        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.similarity_search.return_value = sdk_df
        backend._stores["coll"] = mock_col
        backend._get_store = AsyncMock(return_value=mock_col)

        meta_result = MagicMock()
        meta_result.to_pandas.return_value = _FakeDataFrame(
            {"METADATA_JSON": ["{}"]}
        )

        run_in_td, call_log = self._make_run_in_td_thread()
        backend._run_in_td_thread = run_in_td
        backend._execute_sql = self._make_execute_sql()

        _run(backend.query("coll", "test", n_results=1))

        # SearchParams must have been instantiated with search_type='semantic_search'
        _fake_teradatagenai.SearchParams.assert_called()
        sp_kwargs = _fake_teradatagenai.SearchParams.call_args[1]
        self.assertEqual(sp_kwargs.get("search_type"), "semantic_search")

    def test_query_hybrid_native_bm25(self):
        """When td_bm25_enabled=True, SearchParams uses search_type='hybrid_search'."""
        backend = self._make_v2_backend(td_bm25_enabled=True, td_scoring_method="rrf")
        backend._config["td_bm25_enabled"] = True
        backend._config["td_scoring_method"] = "rrf"
        backend._config["td_sparse_weight"] = 0.3
        backend._collections.add("coll")

        sdk_df = _FakeDataFrame({
            "CHUNK_ID": ["id1"],
            "CONTENT": ["result"],
            "SCORE": [0.9],
        })
        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.similarity_search.return_value = sdk_df
        backend._stores["coll"] = mock_col
        backend._get_store = AsyncMock(return_value=mock_col)

        run_in_td, _ = self._make_run_in_td_thread()
        backend._run_in_td_thread = run_in_td
        backend._execute_sql = self._make_execute_sql()

        from trusted_data_agent.vectorstore.types import SearchMode
        _run(backend.query("coll", "test", n_results=1, search_mode=SearchMode.HYBRID))

        sp_kwargs = _fake_teradatagenai.SearchParams.call_args[1]
        self.assertEqual(sp_kwargs.get("search_type"), "hybrid_search")
        self.assertEqual(sp_kwargs.get("scoring_method"), "rrf")
        self.assertIn("sparse_weight", sp_kwargs)

    def test_query_hybrid_fallback_to_rrf(self):
        """When td_bm25_enabled=False, HYBRID falls back to Python-side RRF."""
        backend = self._make_v2_backend()
        backend._config["td_bm25_enabled"] = False
        backend._collections.add("coll")

        sdk_df = _FakeDataFrame({
            "CHUNK_ID": ["id1", "id2"],
            "CONTENT": ["semantic doc", "another"],
            "SCORE": [0.9, 0.75],
        })
        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.similarity_search.return_value = sdk_df
        backend._stores["coll"] = mock_col
        backend._get_store = AsyncMock(return_value=mock_col)

        lexical_result = MagicMock()
        lexical_result.to_pandas.return_value = _FakeDataFrame({
            "CHUNK_ID": ["id2"],
            "CONTENT": ["another"],
        })
        content_result = MagicMock()
        content_result.to_pandas.return_value = _FakeDataFrame({
            "CHUNK_ID": ["id1", "id2"],
            "CONTENT": ["semantic doc", "another"],
            "METADATA_JSON": ["{}", "{}"],
        })
        sql_idx = [0]
        sql_results = [lexical_result, content_result]

        async def _fake_execute_sql(sql):
            idx = sql_idx[0]; sql_idx[0] += 1
            return sql_results[idx] if idx < len(sql_results) else content_result

        run_in_td, _ = self._make_run_in_td_thread()
        backend._run_in_td_thread = run_in_td
        backend._execute_sql = _fake_execute_sql

        from trusted_data_agent.vectorstore.types import SearchMode
        qr = _run(backend.query("coll", "test", n_results=2, search_mode=SearchMode.HYBRID))

        # SDK was called with semantic_search (not hybrid_search — BM25 not built)
        sp_kwargs = _fake_teradatagenai.SearchParams.call_args[1]
        self.assertEqual(sp_kwargs.get("search_type"), "semantic_search")
        # Python-side RRF produced results
        self.assertGreater(len(qr.documents), 0)

    def test_enable_bm25_calls_collection_update(self):
        """enable_bm25() calls col.update(search_params=SearchParams(search_type='hybrid_search'))."""
        backend = self._make_v2_backend()
        backend._collections.add("coll")

        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.update.return_value = None
        backend._get_store = AsyncMock(return_value=mock_col)
        backend._stores["coll"] = mock_col

        run_in_td, call_log = self._make_run_in_td_thread()
        backend._run_in_td_thread = run_in_td

        _run(backend.enable_bm25("coll", scoring_method="rrf", sparse_weight=0.3))

        # SearchParams instantiated with hybrid_search
        _fake_teradatagenai.SearchParams.assert_called()
        sp_kwargs = _fake_teradatagenai.SearchParams.call_args[1]
        self.assertEqual(sp_kwargs.get("search_type"), "hybrid_search")

        # col.update() called with search_params
        update_calls = [c for c in call_log if c.get("fn") is mock_col.update]
        self.assertEqual(len(update_calls), 1)
        self.assertIn("search_params", update_calls[0]["kwargs"])

    def test_query_keyword_falls_back_to_semantic(self):
        """KEYWORD mode with empty lexical results falls back to SEMANTIC search."""
        backend = self._make_v2_backend()
        backend._collections.add("coll")

        sdk_df = _FakeDataFrame({
            "CHUNK_ID": ["id1"],
            "CONTENT": ["content"],
            "SCORE": [0.8],
        })
        mock_col = MagicMock(spec=_FakeCollection)
        mock_col.similarity_search.return_value = sdk_df
        backend._stores["coll"] = mock_col
        backend._get_store = AsyncMock(return_value=mock_col)

        # Staging table raises error (server-side collection → no staging table)
        async def _raise_3807(sql):
            raise Exception("[Error 3807] Object does not exist.")

        run_in_td, _ = self._make_run_in_td_thread()
        backend._run_in_td_thread = run_in_td
        backend._execute_sql = _raise_3807

        from trusted_data_agent.vectorstore.types import SearchMode
        # Should NOT raise; should fall back to SEMANTIC
        qr = _run(backend.query("coll", "test keyword", n_results=5,
                                search_mode=SearchMode.KEYWORD))

        # SearchParams was eventually called (fallback to SEMANTIC happened)
        _fake_teradatagenai.SearchParams.assert_called()
        sp_kwargs = _fake_teradatagenai.SearchParams.call_args[1]
        self.assertEqual(sp_kwargs.get("search_type"), "semantic_search")


if __name__ == "__main__":
    unittest.main()
