"""
VectorStoreBackend abstract base class.

All methods are async-first. Synchronous backends (ChromaDB) wrap their calls
in ``asyncio.to_thread()`` internally so callers are never blocked on the Quart
event loop. Asynchronous backends (Teradata) use native coroutines.

Callers interact only with this interface — never with ChromaDB or Teradata
types directly.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Set
import logging

from .types import (
    CollectionConfig,
    CollectionInfo,
    GetResult,
    IngestionProgressCallback,
    QueryResult,
    SearchMode,
    ServerSideChunkingConfig,
    VectorDocument,
)
from .capabilities import VectorStoreCapability
from .embedding_providers import EmbeddingProvider
from .filters import MetadataFilter

logger = logging.getLogger("vectorstore")


class VectorStoreBackend(ABC):
    """Abstract interface every vector store backend must implement."""

    # ── Identity & capability negotiation ─────────────────────────────────────

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Short identifier string, e.g. ``"chromadb"`` or ``"teradata"``."""
        ...

    @abstractmethod
    def capabilities(self) -> Set[VectorStoreCapability]:
        """Return the complete set of capabilities this backend supports."""
        ...

    def has_capability(self, cap: VectorStoreCapability) -> bool:
        """Convenience: check whether a specific capability is supported."""
        return cap in self.capabilities()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Called once at startup. Override to open connections, validate config, etc."""
        pass

    async def shutdown(self) -> None:
        """Called at teardown. Override to close connections, flush caches, etc."""
        pass

    # ── Collection management ─────────────────────────────────────────────────

    @abstractmethod
    async def create_collection(self, config: CollectionConfig) -> CollectionInfo:
        """Create a new collection.  Raises if a collection with that name already exists."""
        ...

    @abstractmethod
    async def get_or_create_collection(self, config: CollectionConfig) -> CollectionInfo:
        """Get an existing collection or create it if it does not exist."""
        ...

    @abstractmethod
    async def get_collection_info(self, name: str) -> Optional[CollectionInfo]:
        """Return metadata for an existing collection, or ``None`` if not found."""
        ...

    @abstractmethod
    async def delete_collection(self, name: str) -> bool:
        """Delete a collection.  Returns ``True`` if deleted, ``False`` if not found."""
        ...

    @abstractmethod
    async def count(self, collection_name: str) -> int:
        """Return the number of documents currently in the collection."""
        ...

    # ── Document write operations ─────────────────────────────────────────────

    @abstractmethod
    async def add(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        """Add documents to a collection.  Returns the number of documents added.

        If ``VectorDocument.embedding`` is set and the backend declares
        ``EMBEDDING_PASSTHROUGH``, the pre-computed embedding is used directly.
        Otherwise the backend generates embeddings via ``embedding_provider``
        (client-side) or its own internal service (server-side).
        """
        ...

    @abstractmethod
    async def upsert(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        """Insert or update documents atomically.  Returns the number of documents upserted.

        Requires ``UPSERT`` capability.  Callers should check
        ``has_capability(UPSERT)`` and fall back to ``add()`` if absent.
        """
        ...

    @abstractmethod
    async def delete(
        self,
        collection_name: str,
        ids: List[str],
    ) -> int:
        """Delete documents by their IDs.  Returns the number of documents deleted."""
        ...

    @abstractmethod
    async def update_metadata(
        self,
        collection_name: str,
        ids: List[str],
        metadatas: List[dict],
    ) -> int:
        """Update metadata for existing documents without re-generating embeddings.

        Requires ``UPDATE_METADATA`` capability.  ``ids`` and ``metadatas`` must
        be the same length.  Returns the number of documents updated.
        """
        ...

    # ── File-based ingestion (optional) ──────────────────────────────────────

    async def add_document_files(
        self,
        collection_name: str,
        file_paths: List[str],
        chunking_config: Optional[ServerSideChunkingConfig] = None,
        progress_callback: Optional[IngestionProgressCallback] = None,
    ) -> int:
        """Ingest raw files (PDF, etc.) with server-side chunking and embedding.

        Requires ``SERVER_SIDE_CHUNKING`` capability.  Backends that do not
        support this raise ``NotImplementedError``.

        ``progress_callback``, when provided, is invoked with an
        ``IngestionProgress`` on each status change during long-running
        server-side operations (chunking, embedding, indexing).

        ``chunking_config`` controls chunking behavior (optimized vs fixed-size,
        header/footer trimming).  When ``None``, backend defaults apply
        (equivalent to ``ServerSideChunkingConfig()``).
        """
        raise NotImplementedError(
            f"{self.backend_type} does not support server-side file ingestion. "
            "Use add() with pre-chunked documents instead."
        )

    # ── Search-mode helpers ──────────────────────────────────────────────────

    def _resolve_search_mode(self, search_mode: SearchMode) -> SearchMode:
        """Downgrade *search_mode* when the backend lacks ``HYBRID_SEARCH``.

        Backends call this at the top of ``query()`` so that unsupported modes
        fall back to ``SEMANTIC`` with a logged warning instead of raising.
        """
        if search_mode in (SearchMode.HYBRID, SearchMode.KEYWORD) and \
           not self.has_capability(VectorStoreCapability.HYBRID_SEARCH):
            logger.warning(
                "%s backend does not support %s search; falling back to SEMANTIC",
                self.backend_type, search_mode.value,
            )
            return SearchMode.SEMANTIC
        return search_mode

    # ── Document read operations ──────────────────────────────────────────────

    @abstractmethod
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
        """Search a collection using the specified *search_mode*.

        Returns a ``QueryResult`` with flat parallel lists of documents and
        distances.  Distances are in the backend's native scale
        (e.g. cosine distance 0–2 for ChromaDB).  Callers convert to
        similarity as needed: ``similarity = 1 - distance`` for cosine.

        ``where`` is translated to backend-native filter syntax internally.
        Pass ``None`` for knowledge repositories (no filter required).

        ``search_mode`` controls the retrieval strategy:

        * ``SEMANTIC`` (default) — dense vector similarity search.  Supported
          by all backends.
        * ``HYBRID`` — combines dense + sparse (keyword) search with fusion
          (e.g. Reciprocal Rank Fusion).  Requires ``HYBRID_SEARCH``
          capability; falls back to ``SEMANTIC`` if absent.
        * ``KEYWORD`` — sparse / keyword-only search.  Requires
          ``HYBRID_SEARCH`` capability.

        ``keyword_weight`` (0.0–1.0) hints at the relative importance of the
        keyword component in hybrid mode.  Not all backends honour this
        (e.g. Qdrant RRF is rank-based and ignores explicit weights).
        """
        ...

    @abstractmethod
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
        """Fetch documents by ID list or metadata filter (non-similarity).

        If both ``ids`` and ``where`` are None, all documents are returned
        (requires ``GET_ALL`` capability).  ``include_embeddings=True`` requires
        ``EMBEDDING_PASSTHROUGH`` or ``BATCH_EXPORT`` capability.
        """
        ...
