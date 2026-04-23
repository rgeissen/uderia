"""
Per-session ephemeral vector store for RAG-based context window condensation.

Each SessionVectorStore manages one vector store collection per module per session.
Collections are named {session_id}__{module_id}.

Backend choices:
  - Internal (default): in-memory chromadb.Client() — zero config, zero cleanup,
    auto-destroyed when the process exits or destroy() is called.
  - External: user-configured Qdrant / Teradata backend — user pays, platform
    explicitly deletes collections on session archive.

Lifecycle:
  get_session_store()       — get or create per-session store (call from executor)
  store.ingest()            — add chunks (idempotent, dedup by chunk ID)
  store.retrieve()          — semantic search within a module's collection
  store.has_data()          — check whether a module has indexed content
  destroy_session_store()   — called from session_manager on session archive
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from trusted_data_agent.vectorstore.types import VectorDocument

logger = logging.getLogger("quart.app")

# ---------------------------------------------------------------------------
# Process-level registry
# ---------------------------------------------------------------------------

_SESSION_STORES: Dict[str, "SessionVectorStore"] = {}


def get_session_store(
    session_id: str,
    user_uuid: str,
    backend_config: Optional[Dict[str, Any]] = None,
) -> "SessionVectorStore":
    """
    Get or create the SessionVectorStore for a session.

    Args:
        session_id:     Session UUID.
        user_uuid:      Owner user UUID.
        backend_config: If None, uses internal in-memory ChromaDB.
                        If set, must contain "backend_type" and "backend_config"
                        keys matching a resolved vector_store_configuration.
    """
    if session_id not in _SESSION_STORES:
        _SESSION_STORES[session_id] = SessionVectorStore(
            session_id=session_id,
            user_uuid=user_uuid,
            backend_config=backend_config,
        )
    return _SESSION_STORES[session_id]


async def destroy_session_store(session_id: str) -> None:
    """
    Destroy the SessionVectorStore for a session.

    For in-memory backend: removes from registry (GC handles the rest).
    For external backend: explicitly deletes all module collections.
    """
    store = _SESSION_STORES.pop(session_id, None)
    if store:
        await store.destroy()


# ---------------------------------------------------------------------------
# SessionVectorStore
# ---------------------------------------------------------------------------

class SessionVectorStore:
    """
    Per-session ephemeral vector store for RAG condensation.

    One sub-collection per module: {session_id}__{module_id}
    """

    # Approximate chars per MB for size estimation
    _CHARS_PER_MB: int = 1_000_000

    def __init__(
        self,
        session_id: str,
        user_uuid: str,
        backend_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._session_id = session_id
        self._user_uuid = user_uuid
        self._backend_config = backend_config
        self._is_external = backend_config is not None

        self._backend: Any = None       # Initialized lazily
        self._init_lock = asyncio.Lock()

        # Per-module tracking
        self._initialized_collections: Set[str] = set()
        self._ingested: Set[str] = set()                    # module_ids with data
        self._ingested_ids: Dict[str, Set[str]] = {}        # module_id -> chunk_id set
        self._ingested_chars: Dict[str, int] = {}           # module_id -> char count

    # ── Collection naming ─────────────────────────────────────────────────────

    def collection_name(self, module_id: str) -> str:
        """Return the ChromaDB/backend collection name for a module."""
        return f"{self._session_id}__{module_id}"

    # ── State queries ─────────────────────────────────────────────────────────

    def has_data(self, module_id: str) -> bool:
        """True if the module has at least one chunk indexed."""
        return module_id in self._ingested

    @property
    def is_external(self) -> bool:
        """True if using a user-configured external backend."""
        return self._is_external

    @property
    def ingested_modules(self) -> Set[str]:
        """Set of module_ids that have indexed content."""
        return set(self._ingested)

    def get_store_size_mb(self, module_id: str) -> float:
        """Approximate store size in MB for the given module (character-based estimate)."""
        return self._ingested_chars.get(module_id, 0) / self._CHARS_PER_MB

    # ── Backend lifecycle ─────────────────────────────────────────────────────

    async def _get_backend(self) -> Any:
        """Lazily initialize and return the vector store backend."""
        if self._backend is not None:
            return self._backend

        async with self._init_lock:
            if self._backend is not None:
                return self._backend

            if self._is_external:
                # Resolve user-configured external backend via the platform factory
                from trusted_data_agent.vectorstore.factory import get_backend
                backend_type = self._backend_config.get("backend_type", "chromadb")
                config = self._backend_config.get("backend_config", {})
                self._backend = await get_backend(backend_type, config)
                logger.debug(
                    f"SessionVectorStore using external backend '{backend_type}' "
                    f"for session {self._session_id}"
                )
            else:
                # Internal: own in-memory ChromaDB instance (not the shared singleton)
                from trusted_data_agent.vectorstore.chromadb_backend import ChromaDBBackend
                self._backend = ChromaDBBackend(persist_directory=None)
                await self._backend.initialize()
                logger.debug(
                    f"SessionVectorStore initialized in-memory ChromaDB "
                    f"for session {self._session_id}"
                )

        return self._backend

    async def _ensure_collection(self, module_id: str) -> None:
        """Create the module sub-collection if it does not exist yet."""
        if module_id in self._initialized_collections:
            return

        from trusted_data_agent.vectorstore.types import CollectionConfig
        backend = await self._get_backend()
        await backend.get_or_create_collection(
            CollectionConfig(name=self.collection_name(module_id))
        )
        self._initialized_collections.add(module_id)

    # ── Write path ────────────────────────────────────────────────────────────

    async def ingest(
        self,
        module_id: str,
        chunks: List["VectorDocument"],
        max_store_mb: float = 10.0,
    ) -> int:
        """
        Ingest chunks into the module's sub-collection.

        Idempotent — skips chunks whose IDs are already indexed.
        Stops ingestion if the module's store size would exceed max_store_mb.

        Returns the number of new chunks added.
        """
        if not chunks:
            return 0

        # Cap check
        if self.get_store_size_mb(module_id) >= max_store_mb:
            logger.debug(
                f"SessionVectorStore cap reached for {module_id} "
                f"({self.get_store_size_mb(module_id):.1f}MB >= {max_store_mb}MB), "
                f"skipping ingestion"
            )
            return 0

        from trusted_data_agent.vectorstore.embedding_providers import (
            SentenceTransformerProvider,
        )

        # Dedup by chunk ID
        if module_id not in self._ingested_ids:
            self._ingested_ids[module_id] = set()
        known_ids = self._ingested_ids[module_id]
        new_chunks = [c for c in chunks if c.id not in known_ids]

        if not new_chunks:
            return 0

        await self._ensure_collection(module_id)
        backend = await self._get_backend()
        embedding_provider = SentenceTransformerProvider.get_cached()

        try:
            added = await backend.upsert(
                collection_name=self.collection_name(module_id),
                documents=new_chunks,
                embedding_provider=embedding_provider,
            )
        except (NotImplementedError, Exception):
            # Fallback to add() for backends without UPSERT capability
            try:
                added = await backend.add(
                    collection_name=self.collection_name(module_id),
                    documents=new_chunks,
                    embedding_provider=embedding_provider,
                )
            except Exception as e:
                logger.warning(
                    f"SessionVectorStore ingest failed for {module_id} "
                    f"(session={self._session_id}): {e}"
                )
                return 0

        # Update tracking state
        for chunk in new_chunks:
            known_ids.add(chunk.id)
            self._ingested_chars[module_id] = (
                self._ingested_chars.get(module_id, 0) + len(chunk.content)
            )
        self._ingested.add(module_id)

        logger.debug(
            f"SessionVectorStore ingested {added} chunks for {module_id} "
            f"(session={self._session_id}, "
            f"size={self.get_store_size_mb(module_id):.2f}MB)"
        )
        return added

    # ── Read path ─────────────────────────────────────────────────────────────

    async def retrieve(
        self,
        module_id: str,
        query_text: str,
        n_results: int = 5,
    ) -> List["VectorDocument"]:
        """
        Retrieve semantically relevant chunks for the given query.

        Returns an empty list if the module has no data or retrieval fails —
        callers must fall back to existing condense() in that case.
        """
        if not self.has_data(module_id):
            return []

        from trusted_data_agent.vectorstore.embedding_providers import (
            SentenceTransformerProvider,
        )

        backend = await self._get_backend()
        embedding_provider = SentenceTransformerProvider.get_cached()

        try:
            result = await backend.query(
                collection_name=self.collection_name(module_id),
                query_text=query_text,
                n_results=n_results,
                embedding_provider=embedding_provider,
            )
            return result.documents
        except Exception as e:
            logger.warning(
                f"SessionVectorStore retrieval failed for {module_id} "
                f"(session={self._session_id}): {e}"
            )
            return []

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def destroy(self) -> None:
        """
        Clean up all collections for this session.

        In-memory backend: no-op (collections are garbage-collected with the object).
        External backend: explicitly deletes each module's collection.
        """
        if not self._is_external or self._backend is None:
            return

        for module_id in list(self._initialized_collections):
            coll_name = self.collection_name(module_id)
            try:
                await self._backend.delete_collection(coll_name)
                logger.debug(
                    f"SessionVectorStore deleted external collection '{coll_name}' "
                    f"(session={self._session_id})"
                )
            except Exception as e:
                logger.warning(
                    f"SessionVectorStore failed to delete '{coll_name}': {e}"
                )
