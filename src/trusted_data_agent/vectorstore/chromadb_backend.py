"""
ChromaDB implementation of VectorStoreBackend.

This class extracts all ChromaDB-specific logic that previously lived directly
in rag_retriever.py, repository_constructor.py, knowledge_routes.py, and
collection_utils.py.  The rest of the codebase now interacts only with the
VectorStoreBackend interface.

All synchronous ChromaDB calls are wrapped in asyncio.to_thread() so they
never block the Quart event loop.
"""

from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .base import VectorStoreBackend
from .capabilities import VectorStoreCapability
from .embedding_providers import EmbeddingProvider, SentenceTransformerProvider
from .filters import MetadataFilter, to_chromadb_where
from .types import (
    CollectionConfig,
    CollectionInfo,
    DistanceMetric,
    GetResult,
    QueryResult,
    SearchMode,
    VectorDocument,
)

logger = logging.getLogger("vectorstore.chromadb")

_METRIC_TO_HNSW: Dict[DistanceMetric, str] = {
    DistanceMetric.COSINE: "cosine",
    DistanceMetric.EUCLIDEAN: "l2",
    DistanceMetric.DOT_PRODUCT: "ip",
}


class ChromaDBBackend(VectorStoreBackend):
    """ChromaDB vector store backend.

    A single instance may be shared across many collections — it holds one
    PersistentClient (or in-memory Client) and caches the raw ChromaDB
    collection objects keyed by collection name.

    ``raw_client`` is exposed for the migration period: code in rag_retriever.py
    that still uses the planner-repo ChromaDB paths can access the same client
    without creating a second database connection.
    """

    def __init__(self, persist_directory: Optional[Path] = None):
        self._persist_directory = persist_directory
        self._client: Any = None          # chromadb.Client or PersistentClient
        # Cache: collection_name -> chromadb collection object
        self._coll_cache: Dict[str, Any] = {}

    # ── Identity & capabilities ───────────────────────────────────────────────

    @property
    def backend_type(self) -> str:
        return "chromadb"

    def capabilities(self) -> Set[VectorStoreCapability]:
        return {
            VectorStoreCapability.CREATE_COLLECTION,
            VectorStoreCapability.DELETE_COLLECTION,
            VectorStoreCapability.ADD_DOCUMENTS,
            VectorStoreCapability.DELETE_DOCUMENTS,
            VectorStoreCapability.SIMILARITY_SEARCH,
            VectorStoreCapability.GET_BY_ID,
            VectorStoreCapability.COUNT,
            VectorStoreCapability.UPSERT,
            VectorStoreCapability.GET_BY_METADATA_FILTER,
            VectorStoreCapability.UPDATE_METADATA,
            VectorStoreCapability.EMBEDDING_PASSTHROUGH,
            VectorStoreCapability.GET_ALL,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        import chromadb
        if self._persist_directory:
            self._persist_directory.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._persist_directory))
        else:
            self._client = chromadb.Client()
        logger.info(
            f"ChromaDBBackend initialized "
            f"(persist={self._persist_directory or 'in-memory'})"
        )

    async def shutdown(self) -> None:
        self._coll_cache.clear()

    @property
    def raw_client(self) -> Any:
        """Expose the raw ChromaDB client for the migration bridge in rag_retriever.py."""
        return self._client

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ef_from_provider(self, provider: Optional[EmbeddingProvider]) -> Any:
        """Return a ChromaDB EmbeddingFunction from a provider, or None."""
        if provider is None:
            return None
        if isinstance(provider, SentenceTransformerProvider):
            return provider.chromadb_embedding_function
        return None  # server-side provider — ChromaDB won't need it

    def _hnsw_space(self, metric: DistanceMetric) -> str:
        return _METRIC_TO_HNSW.get(metric, "cosine")

    def _get_chroma_collection(self, name: str) -> Any:
        """Return cached ChromaDB collection, raising if not found."""
        coll = self._coll_cache.get(name)
        if coll is None:
            raise KeyError(f"ChromaDB collection '{name}' not loaded in backend cache. "
                           "Call get_or_create_collection() first.")
        return coll

    @staticmethod
    def _sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """ChromaDB requires flat, non-None metadata values.

        Removes None values (ChromaDB rejects them) and converts lists/dicts
        to strings so the constraint is always satisfied — callers no longer
        need to know about this limitation.
        """
        sanitized: Dict[str, Any] = {}
        for k, v in metadata.items():
            if v is None:
                continue
            if isinstance(v, (list, dict)):
                import json
                sanitized[k] = json.dumps(v)
            elif isinstance(v, (str, int, float, bool)):
                sanitized[k] = v
            else:
                sanitized[k] = str(v)
        return sanitized

    @staticmethod
    def _normalize_query_result(raw: Dict[str, Any]) -> QueryResult:
        """Convert ChromaDB's nested-list result into a flat QueryResult."""
        ids = raw.get("ids", [[]])[0]
        documents_text = raw.get("documents") or [[]]
        documents_text = documents_text[0] if documents_text else []
        metadatas = raw.get("metadatas") or [[]]
        metadatas = metadatas[0] if metadatas else []
        distances = raw.get("distances") or [[]]
        distances = distances[0] if distances else []

        docs: List[VectorDocument] = []
        for i, doc_id in enumerate(ids):
            docs.append(VectorDocument(
                id=doc_id,
                content=documents_text[i] if i < len(documents_text) else "",
                metadata=metadatas[i] if i < len(metadatas) else {},
            ))

        return QueryResult(
            documents=docs,
            distances=list(distances),
            total_results=len(docs),
        )

    @staticmethod
    def _normalize_get_result(
        raw: Dict[str, Any],
        include_embeddings: bool = False,
    ) -> GetResult:
        """Convert a ChromaDB get() result into a flat GetResult."""
        ids = raw.get("ids") if raw.get("ids") is not None else []
        documents_text = raw.get("documents") if raw.get("documents") is not None else []
        metadatas = raw.get("metadatas") if raw.get("metadatas") is not None else []
        embeddings = raw.get("embeddings") if raw.get("embeddings") is not None else []

        docs: List[VectorDocument] = []
        for i, doc_id in enumerate(ids):
            emb = embeddings[i] if (include_embeddings and i < len(embeddings)) else None
            docs.append(VectorDocument(
                id=doc_id,
                content=documents_text[i] if i < len(documents_text) else "",
                metadata=metadatas[i] if i < len(metadatas) else {},
                embedding=emb,
            ))

        return GetResult(documents=docs, total_count=len(docs))

    # ── Collection management ─────────────────────────────────────────────────

    async def create_collection(self, config: CollectionConfig) -> CollectionInfo:
        ef = self._ef_from_provider(
            SentenceTransformerProvider.get_cached(config.embedding_model)
        )
        hnsw = self._hnsw_space(config.distance_metric)

        def _sync():
            coll = self._client.create_collection(
                name=config.name,
                embedding_function=ef,
                metadata={**config.metadata, "hnsw:space": hnsw},
            )
            self._coll_cache[config.name] = coll
            return coll

        coll = await asyncio.to_thread(_sync)
        return CollectionInfo(
            name=coll.name,
            document_count=0,
            distance_metric=config.distance_metric,
            metadata=config.metadata,
        )

    async def get_or_create_collection(self, config: CollectionConfig) -> CollectionInfo:
        ef = self._ef_from_provider(
            SentenceTransformerProvider.get_cached(config.embedding_model)
        )
        hnsw = self._hnsw_space(config.distance_metric)

        def _sync():
            coll = self._client.get_or_create_collection(
                name=config.name,
                embedding_function=ef,
                metadata={**config.metadata, "hnsw:space": hnsw},
            )
            self._coll_cache[config.name] = coll
            return coll

        coll = await asyncio.to_thread(_sync)
        count = await asyncio.to_thread(coll.count)
        return CollectionInfo(
            name=coll.name,
            document_count=count,
            distance_metric=config.distance_metric,
            metadata=config.metadata,
        )

    async def get_collection_info(self, name: str) -> Optional[CollectionInfo]:
        def _sync():
            try:
                coll = self._client.get_collection(name=name)
                self._coll_cache[name] = coll
                return coll
            except Exception:
                return None

        coll = await asyncio.to_thread(_sync)
        if coll is None:
            return None
        count = await asyncio.to_thread(coll.count)
        return CollectionInfo(name=name, document_count=count)

    async def delete_collection(self, name: str) -> bool:
        def _sync():
            try:
                self._client.delete_collection(name=name)
                self._coll_cache.pop(name, None)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_sync)

    async def count(self, collection_name: str) -> int:
        coll = self._get_chroma_collection(collection_name)
        return await asyncio.to_thread(coll.count)

    # ── Document writes ───────────────────────────────────────────────────────

    async def add(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        if not documents:
            return 0
        coll = self._get_chroma_collection(collection_name)

        ids = [d.id for d in documents]
        texts = [d.content for d in documents]
        metadatas = [self._sanitize_metadata(d.metadata) for d in documents]
        # Use pre-computed embeddings if available (fork / import path)
        embeddings = [d.embedding for d in documents] if documents[0].embedding is not None else None

        def _sync():
            coll.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
                embeddings=embeddings,
            )

        await asyncio.to_thread(_sync)
        return len(ids)

    async def upsert(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        if not documents:
            return 0
        coll = self._get_chroma_collection(collection_name)

        ids = [d.id for d in documents]
        texts = [d.content for d in documents]
        metadatas = [self._sanitize_metadata(d.metadata) for d in documents]

        def _sync():
            coll.upsert(ids=ids, documents=texts, metadatas=metadatas)

        await asyncio.to_thread(_sync)
        return len(ids)

    async def delete(self, collection_name: str, ids: List[str]) -> int:
        if not ids:
            return 0
        coll = self._get_chroma_collection(collection_name)

        def _sync():
            coll.delete(ids=ids)

        await asyncio.to_thread(_sync)
        return len(ids)

    async def update_metadata(
        self,
        collection_name: str,
        ids: List[str],
        metadatas: List[dict],
    ) -> int:
        if not ids:
            return 0
        coll = self._get_chroma_collection(collection_name)
        sanitized = [self._sanitize_metadata(m) for m in metadatas]

        def _sync():
            coll.update(ids=ids, metadatas=sanitized)

        await asyncio.to_thread(_sync)
        return len(ids)

    # ── Document reads ────────────────────────────────────────────────────────

    async def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 10,
        where: Optional[MetadataFilter] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        include_documents: bool = True,
        include_metadata: bool = True,
        search_mode: SearchMode = SearchMode.SEMANTIC,
        keyword_weight: float = 0.3,
    ) -> QueryResult:
        # ChromaDB does not declare HYBRID_SEARCH — always resolves to SEMANTIC.
        search_mode = self._resolve_search_mode(search_mode)

        coll = self._get_chroma_collection(collection_name)
        chroma_where = to_chromadb_where(where)

        include: List[str] = ["distances"]
        if include_documents:
            include.append("documents")
        if include_metadata:
            include.append("metadatas")

        def _sync():
            return coll.query(
                query_texts=[query_text],
                n_results=n_results,
                where=chroma_where,
                include=include,
            )

        raw = await asyncio.to_thread(_sync)
        return self._normalize_query_result(raw)

    async def get(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        where: Optional[MetadataFilter] = None,
        include_documents: bool = True,
        include_metadata: bool = True,
        include_embeddings: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> GetResult:
        coll = self._get_chroma_collection(collection_name)
        chroma_where = to_chromadb_where(where)

        include: List[str] = []
        if include_documents:
            include.append("documents")
        if include_metadata:
            include.append("metadatas")
        if include_embeddings:
            include.append("embeddings")

        def _sync():
            kwargs: Dict[str, Any] = {"include": include}
            if ids is not None:
                kwargs["ids"] = ids
            if chroma_where is not None:
                kwargs["where"] = chroma_where
            if limit is not None:
                kwargs["limit"] = limit
            if offset:
                kwargs["offset"] = offset
            return coll.get(**kwargs)

        raw = await asyncio.to_thread(_sync)
        return self._normalize_get_result(raw, include_embeddings=include_embeddings)

    # ── Collection cache management (called by rag_retriever bridge) ──────────

    def register_collection(self, name: str, chroma_collection: Any) -> None:
        """Register a pre-loaded ChromaDB collection object in the cache.

        Used during the migration: rag_retriever._load_active_collections()
        loads collections via the raw client then registers them here so
        subsequent backend method calls can find them.
        """
        self._coll_cache[name] = chroma_collection

    def evict_collection(self, name: str) -> None:
        """Remove a collection from the cache (e.g. after deletion or disable)."""
        self._coll_cache.pop(name, None)

    def is_collection_loaded(self, name: str) -> bool:
        return name in self._coll_cache
