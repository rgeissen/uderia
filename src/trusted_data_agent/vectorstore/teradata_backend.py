"""
Teradata Enterprise Vector Store backend (skeleton).

This backend integrates with Teradata's ``teradatagenai.TDVectorStore`` to provide
enterprise-grade vector storage with server-side embedding via AWS Bedrock or Azure
OpenAI.

Registration at import time:

    from trusted_data_agent.vectorstore.teradata_backend import TeradataVectorBackend
    # TeradataVectorBackend is auto-registered when this module is imported.

Connection config (stored as JSON in collections.backend_config):

    {
        "host":     "teradata-host.company.com",
        "username": "td_user",
        "password": "td_pass",       # stored encrypted by caller
        "database": "VECTORS_DB",
        "embedding_model": "amazon.titan-embed-text-v1"   # or Azure model name
    }
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Set

from .base import VectorStoreBackend
from .capabilities import VectorStoreCapability
from .embedding_providers import EmbeddingProvider, ServerSideEmbeddingProvider
from .filters import MetadataFilter
from .types import (
    CollectionConfig,
    CollectionInfo,
    DistanceMetric,
    GetResult,
    QueryResult,
    VectorDocument,
)

logger = logging.getLogger("vectorstore.teradata")

# ── Auto-register this backend when module is imported ────────────────────────

def _register() -> None:
    from .factory import register_backend
    register_backend("teradata", TeradataVectorBackend)

_register()


class TeradataVectorBackend(VectorStoreBackend):
    """Teradata Enterprise Vector Store backend.

    Uses ``teradatagenai.TDVectorStore`` for CUD operations (async) and
    similarity search (async).  Embedding is handled server-side by Bedrock or
    Azure OpenAI — callers must pass a ``ServerSideEmbeddingProvider``.

    All methods are async-first.  Teradata's own library provides native async
    coroutines so no ``asyncio.to_thread()`` wrapping is needed.

    NOTE: This is a skeleton implementation.  The Teradata ``teradatagenai``
    package is not yet a hard dependency — ``initialize()`` raises
    ``RuntimeError`` with an installation hint if it is not found.
    """

    def __init__(self, connection_config: Dict[str, Any]):
        self._config = connection_config
        self._host: str = connection_config.get("host", "")
        self._username: str = connection_config.get("username", "")
        self._password: str = connection_config.get("password", "")
        self._database: str = connection_config.get("database", "")
        self._embedding_model: str = connection_config.get(
            "embedding_model", "amazon.titan-embed-text-v1"
        )
        # teradatagenai connection object — set in initialize()
        self._connection: Any = None
        # Cache: collection_name -> TDVectorStore instance
        self._stores: Dict[str, Any] = {}

    # ── Identity & capabilities ───────────────────────────────────────────────

    @property
    def backend_type(self) -> str:
        return "teradata"

    def capabilities(self) -> Set[VectorStoreCapability]:
        return {
            VectorStoreCapability.CREATE_COLLECTION,
            VectorStoreCapability.DELETE_COLLECTION,
            VectorStoreCapability.ADD_DOCUMENTS,
            VectorStoreCapability.DELETE_DOCUMENTS,
            VectorStoreCapability.SIMILARITY_SEARCH,
            VectorStoreCapability.GET_BY_ID,
            VectorStoreCapability.COUNT,
            VectorStoreCapability.GET_BY_METADATA_FILTER,
            VectorStoreCapability.SERVER_SIDE_EMBEDDING,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Open Teradata connection.  Raises RuntimeError if teradatagenai not installed."""
        try:
            import teradatagenai  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "The 'teradatagenai' package is required for the Teradata vector backend. "
                "Install it with: pip install teradatagenai"
            ) from exc

        try:
            self._connection = teradatagenai.connect(
                host=self._host,
                username=self._username,
                password=self._password,
                database=self._database,
            )
            logger.info(
                f"TeradataVectorBackend initialized "
                f"(host={self._host}, database={self._database})"
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to connect to Teradata at '{self._host}': {exc}"
            ) from exc

    async def shutdown(self) -> None:
        self._stores.clear()
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_store(self, name: str) -> Any:
        store = self._stores.get(name)
        if store is None:
            raise KeyError(
                f"Teradata vector store '{name}' not loaded in backend cache. "
                "Call get_or_create_collection() first."
            )
        return store

    # ── Collection management ─────────────────────────────────────────────────

    async def create_collection(self, config: CollectionConfig) -> CollectionInfo:
        import teradatagenai  # type: ignore[import]
        store = teradatagenai.TDVectorStore.create(
            connection=self._connection,
            table_name=config.name,
            embedding_model=self._embedding_model,
            metadata=config.metadata,
        )
        self._stores[config.name] = store
        return CollectionInfo(
            name=config.name,
            document_count=0,
            distance_metric=config.distance_metric,
            metadata=config.metadata,
        )

    async def get_or_create_collection(self, config: CollectionConfig) -> CollectionInfo:
        import teradatagenai  # type: ignore[import]
        store = teradatagenai.TDVectorStore.get_or_create(
            connection=self._connection,
            table_name=config.name,
            embedding_model=self._embedding_model,
            metadata=config.metadata,
        )
        self._stores[config.name] = store
        count = await store.count()
        return CollectionInfo(
            name=config.name,
            document_count=count,
            distance_metric=config.distance_metric,
            metadata=config.metadata,
        )

    async def get_collection_info(self, name: str) -> Optional[CollectionInfo]:
        import teradatagenai  # type: ignore[import]
        try:
            store = teradatagenai.TDVectorStore.get(
                connection=self._connection,
                table_name=name,
            )
            self._stores[name] = store
            count = await store.count()
            return CollectionInfo(name=name, document_count=count)
        except Exception:
            return None

    async def delete_collection(self, name: str) -> bool:
        store = self._stores.get(name)
        if store is None:
            return False
        try:
            await store.delete_all()
            self._stores.pop(name, None)
            return True
        except Exception as exc:
            logger.error(f"Failed to delete Teradata collection '{name}': {exc}")
            return False

    async def count(self, collection_name: str) -> int:
        store = self._get_store(collection_name)
        return await store.count()

    # ── Document writes ───────────────────────────────────────────────────────

    async def add(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        if not documents:
            return 0
        store = self._get_store(collection_name)

        # Teradata handles embedding server-side — pass text and metadata only
        records = [
            {
                "id": d.id,
                "text": d.content,
                "metadata": d.metadata,
            }
            for d in documents
        ]
        await store.update(records)
        return len(documents)

    async def upsert(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        # Teradata's update() is upsert semantics
        return await self.add(collection_name, documents, embedding_provider)

    async def delete(self, collection_name: str, ids: List[str]) -> int:
        if not ids:
            return 0
        store = self._get_store(collection_name)
        await store.delete(ids=ids)
        return len(ids)

    async def update_metadata(
        self,
        collection_name: str,
        ids: List[str],
        metadatas: List[dict],
    ) -> int:
        # Teradata does not support metadata-only updates without re-embedding.
        # Fall back to full re-add (requires original content — not available here).
        raise NotImplementedError(
            "TeradataVectorBackend does not support metadata-only updates. "
            "Use add() or upsert() to replace documents with updated metadata."
        )

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
    ) -> QueryResult:
        store = self._get_store(collection_name)

        # TODO: translate MetadataFilter to Teradata SQL WHERE clause
        # For now, ignore metadata filters
        if where is not None:
            logger.warning(
                "TeradataVectorBackend: metadata filters are not yet implemented. "
                "Query will return unfiltered results."
            )

        raw_results = await store.similarity_search(
            query=query_text,
            k=n_results,
        )

        docs: List[VectorDocument] = []
        distances: List[float] = []
        for item in raw_results:
            docs.append(VectorDocument(
                id=item.get("id", ""),
                content=item.get("text", "") if include_documents else "",
                metadata=item.get("metadata", {}) if include_metadata else {},
            ))
            # Teradata returns similarity score (higher = closer) — convert to distance
            similarity = item.get("score", 0.0)
            distances.append(1.0 - similarity)

        return QueryResult(
            documents=docs,
            distances=distances,
            total_results=len(docs),
        )

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
        store = self._get_store(collection_name)

        if ids is not None:
            raw_results = await store.get_by_ids(ids=ids)
        else:
            # TODO: translate MetadataFilter to WHERE clause
            raw_results = await store.get_all(limit=limit, offset=offset)

        docs: List[VectorDocument] = []
        for item in raw_results:
            docs.append(VectorDocument(
                id=item.get("id", ""),
                content=item.get("text", "") if include_documents else "",
                metadata=item.get("metadata", {}) if include_metadata else {},
                # Embeddings not returned from Teradata to client
                embedding=None,
            ))

        return GetResult(documents=docs, total_count=len(docs))
