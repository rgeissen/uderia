"""
Qdrant Cloud implementation of VectorStoreBackend.

Uses the ``qdrant-client`` async SDK (``AsyncQdrantClient``) for all
operations.  Embedding is client-side via SentenceTransformerProvider
(identical to ChromaDB).

Registration at import time::

    from trusted_data_agent.vectorstore import qdrant_backend  # triggers _register()

Connection config (stored as JSON in collections.backend_config)::

    {
        "url":          "https://xxx.cloud.qdrant.io:6333",
        "api_key":      "xxx",
        "prefer_grpc":  false,
        "timeout":      30
    }
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Set

from .base import VectorStoreBackend
from .capabilities import VectorStoreCapability
from .embedding_providers import EmbeddingProvider, SentenceTransformerProvider
from .filters import MetadataFilter, to_qdrant_filter
from .types import (
    CollectionConfig,
    CollectionInfo,
    DistanceMetric,
    GetResult,
    QueryResult,
    VectorDocument,
)

logger = logging.getLogger("vectorstore.qdrant")

# Reserved payload key for document content (Qdrant stores vectors + payloads,
# not "documents" in the ChromaDB sense).
_CONTENT_KEY = "_content"

# Reserved payload key for the original Uderia document ID.  Qdrant requires
# point IDs to be valid UUIDs or unsigned 64-bit integers.  Uderia IDs are
# often compound strings (e.g. "uuid_chunk_0_hash") that fail UUID parsing.
# We hash them into deterministic UUID5 values for Qdrant and store the
# original for round-trip fidelity.
_ORIGINAL_ID_KEY = "_uderia_id"

# Namespace UUID for deterministic uuid5 generation (fixed, arbitrary).
_QDRANT_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


class QdrantBackend(VectorStoreBackend):
    """Qdrant Cloud vector store backend.

    Uses ``AsyncQdrantClient`` for all operations.  Client-side embedding
    via SentenceTransformerProvider — Qdrant receives pre-computed vectors.
    Each Uderia collection maps 1:1 to a Qdrant collection.

    The client handles connection pooling and retries internally.
    """

    def __init__(self, connection_config: Dict[str, Any]):
        self._config = connection_config
        self._url: str = connection_config.get("url", "")
        self._api_key: str = connection_config.get("api_key", "")
        self._prefer_grpc: bool = bool(connection_config.get("prefer_grpc", False))
        self._timeout: int = int(connection_config.get("timeout", 30))
        self._client: Any = None  # AsyncQdrantClient
        self._initialized: bool = False

    # ── Identity & capabilities ───────────────────────────────────────────────

    @property
    def backend_type(self) -> str:
        return "qdrant"

    def capabilities(self) -> Set[VectorStoreCapability]:
        return {
            # Required (7)
            VectorStoreCapability.CREATE_COLLECTION,
            VectorStoreCapability.DELETE_COLLECTION,
            VectorStoreCapability.ADD_DOCUMENTS,
            VectorStoreCapability.DELETE_DOCUMENTS,
            VectorStoreCapability.SIMILARITY_SEARCH,
            VectorStoreCapability.GET_BY_ID,
            VectorStoreCapability.COUNT,
            # Optional (5)
            VectorStoreCapability.UPSERT,
            VectorStoreCapability.GET_BY_METADATA_FILTER,
            VectorStoreCapability.UPDATE_METADATA,
            VectorStoreCapability.EMBEDDING_PASSTHROUGH,
            VectorStoreCapability.GET_ALL,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Open connection to Qdrant Cloud."""
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "The 'qdrant-client' package is required for the Qdrant backend. "
                "Install it with: pip install qdrant-client"
            ) from exc

        if not self._url:
            raise RuntimeError(
                "Qdrant URL is required. Provide 'url' in backend_config."
            )
        if not self._api_key:
            raise RuntimeError(
                "Qdrant API key is required. Provide 'api_key' in backend_config."
            )

        self._client = AsyncQdrantClient(
            url=self._url,
            api_key=self._api_key,
            prefer_grpc=self._prefer_grpc,
            timeout=self._timeout,
        )
        self._initialized = True
        logger.info(
            f"QdrantBackend initialized (url={self._url}, grpc={self._prefer_grpc})"
        )

    async def shutdown(self) -> None:
        """Close the Qdrant client connection."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:
                logger.debug(f"Qdrant client close during shutdown: {exc}")
        self._client = None
        self._initialized = False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ensure_initialized(self) -> None:
        if not self._initialized or self._client is None:
            raise RuntimeError(
                "QdrantBackend not initialized. Call initialize() first."
            )

    @staticmethod
    def _qdrant_distance(metric: DistanceMetric) -> Any:
        """Convert DistanceMetric to ``qdrant_client.models.Distance``."""
        from qdrant_client.models import Distance

        _mapping = {
            DistanceMetric.COSINE: Distance.COSINE,
            DistanceMetric.EUCLIDEAN: Distance.EUCLID,
            DistanceMetric.DOT_PRODUCT: Distance.DOT,
        }
        result = _mapping.get(metric)
        if result is None:
            logger.warning(
                f"Distance metric {metric} not supported by Qdrant, "
                "falling back to Cosine"
            )
            return Distance.COSINE
        return result

    @staticmethod
    def _sanitize_payload(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Remove None values from payload (Qdrant supports nested structures)."""
        return {k: v for k, v in metadata.items() if v is not None}

    @staticmethod
    def _to_qdrant_id(doc_id: str) -> str:
        """Convert an Uderia document ID to a valid Qdrant point ID (UUID string).

        If *doc_id* is already a valid UUID it is returned as-is.  Otherwise a
        deterministic UUID5 is generated so the mapping is stable across
        upserts.  The original ID is stored separately in the payload via
        ``_ORIGINAL_ID_KEY``.
        """
        try:
            uuid.UUID(doc_id)
            return doc_id  # Already a valid UUID
        except (ValueError, AttributeError):
            return str(uuid.uuid5(_QDRANT_NS, doc_id))

    @staticmethod
    def _from_qdrant_point(point: Any) -> str:
        """Extract the original Uderia document ID from a Qdrant point.

        Returns ``_ORIGINAL_ID_KEY`` from payload if present (hashed ID case),
        otherwise falls back to the Qdrant point ID itself.
        """
        payload = point.payload or {}
        return payload.get(_ORIGINAL_ID_KEY, str(point.id))

    # ── Collection management ─────────────────────────────────────────────────

    async def create_collection(self, config: CollectionConfig) -> CollectionInfo:
        self._ensure_initialized()
        from qdrant_client.models import VectorParams

        provider = SentenceTransformerProvider.get_cached(config.embedding_model)
        dimensions = provider.dimensions

        await self._client.create_collection(
            collection_name=config.name,
            vectors_config=VectorParams(
                size=dimensions,
                distance=self._qdrant_distance(config.distance_metric),
            ),
        )
        logger.info(f"Created Qdrant collection '{config.name}' (dim={dimensions})")
        return CollectionInfo(
            name=config.name,
            document_count=0,
            distance_metric=config.distance_metric,
            metadata=config.metadata,
        )

    async def get_or_create_collection(
        self, config: CollectionConfig
    ) -> CollectionInfo:
        self._ensure_initialized()

        exists = await self._client.collection_exists(config.name)
        if exists:
            info = await self._client.get_collection(config.name)
            return CollectionInfo(
                name=config.name,
                document_count=info.points_count or 0,
                distance_metric=config.distance_metric,
                metadata=config.metadata,
            )
        return await self.create_collection(config)

    async def get_collection_info(self, name: str) -> Optional[CollectionInfo]:
        self._ensure_initialized()
        try:
            exists = await self._client.collection_exists(name)
            if not exists:
                return None
            info = await self._client.get_collection(name)
            return CollectionInfo(name=name, document_count=info.points_count or 0)
        except Exception:
            return None

    async def delete_collection(self, name: str) -> bool:
        self._ensure_initialized()
        try:
            exists = await self._client.collection_exists(name)
            if not exists:
                return False
            await self._client.delete_collection(name)
            logger.info(f"Deleted Qdrant collection '{name}'")
            return True
        except Exception as exc:
            logger.warning(f"Failed to delete Qdrant collection '{name}': {exc}")
            return False

    async def count(self, collection_name: str) -> int:
        self._ensure_initialized()
        result = await self._client.count(collection_name)
        return result.count

    # ── Document writes ───────────────────────────────────────────────────────

    async def add(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        if not documents:
            return 0
        self._ensure_initialized()
        from qdrant_client.models import PointStruct

        # Resolve embeddings: pre-computed (EMBEDDING_PASSTHROUGH) or client-side
        if documents[0].embedding is not None:
            vectors = [d.embedding for d in documents]
        else:
            if embedding_provider is None:
                raise ValueError(
                    "embedding_provider is required when documents lack "
                    "pre-computed embeddings"
                )
            vectors = embedding_provider.embed_texts(
                [d.content for d in documents]
            )

        points = []
        for doc, vector in zip(documents, vectors):
            payload = self._sanitize_payload(doc.metadata)
            payload[_CONTENT_KEY] = doc.content
            qdrant_id = self._to_qdrant_id(doc.id)
            if qdrant_id != doc.id:
                # Store original ID for round-trip retrieval
                payload[_ORIGINAL_ID_KEY] = doc.id
            points.append(
                PointStruct(id=qdrant_id, vector=vector, payload=payload)
            )

        # Qdrant upsert is the standard write operation (idempotent)
        await self._client.upsert(
            collection_name=collection_name, points=points
        )
        return len(points)

    async def upsert(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        # Qdrant's upsert is naturally idempotent — same as add()
        return await self.add(collection_name, documents, embedding_provider)

    async def delete(self, collection_name: str, ids: List[str]) -> int:
        if not ids:
            return 0
        self._ensure_initialized()
        from qdrant_client.models import PointIdsList

        qdrant_ids = [self._to_qdrant_id(i) for i in ids]
        await self._client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=qdrant_ids),
        )
        return len(ids)

    async def update_metadata(
        self,
        collection_name: str,
        ids: List[str],
        metadatas: List[dict],
    ) -> int:
        if not ids:
            return 0
        self._ensure_initialized()

        for doc_id, meta in zip(ids, metadatas):
            sanitized = self._sanitize_payload(meta)
            qdrant_id = self._to_qdrant_id(doc_id)
            await self._client.set_payload(
                collection_name=collection_name,
                payload=sanitized,
                points=[qdrant_id],
            )
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
    ) -> QueryResult:
        self._ensure_initialized()

        if embedding_provider is None:
            raise ValueError(
                "embedding_provider is required for Qdrant similarity search"
            )

        query_vector = embedding_provider.embed_query(query_text)
        qdrant_filter = to_qdrant_filter(where)

        results = await self._client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=n_results,
            with_payload=True,
            with_vectors=False,
        )

        docs: List[VectorDocument] = []
        distances: List[float] = []

        for point in results.points:
            payload = dict(point.payload) if point.payload else {}
            content = payload.pop(_CONTENT_KEY, "")
            original_id = payload.pop(_ORIGINAL_ID_KEY, str(point.id))
            meta = payload if include_metadata else {}

            docs.append(
                VectorDocument(
                    id=original_id,
                    content=content if include_documents else "",
                    metadata=meta,
                )
            )
            # Qdrant returns similarity scores (higher = better).
            # Convert to distance (lower = better) for abstraction layer
            # consistency with ChromaDB.
            distances.append(
                1.0 - point.score if point.score is not None else 0.0
            )

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
        self._ensure_initialized()

        if ids is not None:
            # Fetch by specific IDs — convert to Qdrant UUIDs
            qdrant_ids = [self._to_qdrant_id(i) for i in ids]
            points = await self._client.retrieve(
                collection_name=collection_name,
                ids=qdrant_ids,
                with_payload=True,
                with_vectors=include_embeddings,
            )
        else:
            # Scroll through collection (with optional filter)
            qdrant_filter = to_qdrant_filter(where)

            # Qdrant scroll uses cursor-based pagination (point ID offset),
            # not integer offset.  For compatibility with the abstraction
            # layer's integer offset interface, fetch enough to skip.
            fetch_limit = (offset or 0) + (limit or 100)

            scroll_result = await self._client.scroll(
                collection_name=collection_name,
                scroll_filter=qdrant_filter,
                limit=fetch_limit,
                with_payload=True,
                with_vectors=include_embeddings,
            )
            all_points = scroll_result[0]  # (points, next_page_offset)
            points = all_points[offset:] if offset else all_points
            if limit:
                points = points[:limit]

        docs: List[VectorDocument] = []
        for point in points:
            payload = dict(point.payload) if point.payload else {}
            content = payload.pop(_CONTENT_KEY, "")
            original_id = payload.pop(_ORIGINAL_ID_KEY, str(point.id))
            meta = payload if include_metadata else {}
            embedding = (
                list(point.vector)
                if (include_embeddings and point.vector)
                else None
            )

            docs.append(
                VectorDocument(
                    id=original_id,
                    content=content if include_documents else "",
                    metadata=meta,
                    embedding=embedding,
                )
            )

        return GetResult(documents=docs, total_count=len(docs))


# ── Auto-register this backend when module is imported ────────────────────────

def _register() -> None:
    from .factory import register_backend
    register_backend("qdrant", QdrantBackend)


_register()
