"""
Backend factory with singleton caching.

Usage:
    from trusted_data_agent.vectorstore.factory import get_backend, get_default_chromadb_backend

    # Default ChromaDB backend (shared singleton — same client as rag_retriever)
    backend = await get_default_chromadb_backend()

    # Per-collection backend resolved from collection metadata
    backend = await get_backend_for_collection(coll_meta)

New backends are registered at import time via ``register_backend()``.
"""

from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Type

from .base import VectorStoreBackend
from .capabilities import REQUIRED_CAPABILITIES
from .chromadb_backend import ChromaDBBackend

logger = logging.getLogger("vectorstore.factory")

# Registry: backend_type string -> backend class
_REGISTRY: Dict[str, Type[VectorStoreBackend]] = {
    "chromadb": ChromaDBBackend,
}

# Singleton cache: config fingerprint -> initialized backend instance
_INSTANCES: Dict[str, VectorStoreBackend] = {}

# Shared default ChromaDB backend (used by rag_retriever bridge)
_DEFAULT_CHROMADB: Optional[ChromaDBBackend] = None


def register_backend(backend_type: str, cls: Type[VectorStoreBackend]) -> None:
    """Register a new backend implementation.

    Call this at module import time from the backend's own module, e.g.:
        from trusted_data_agent.vectorstore.factory import register_backend
        register_backend("teradata", TeradataVectorBackend)
    """
    _REGISTRY[backend_type] = cls
    logger.info(f"Registered vector store backend: {backend_type}")


def _config_fingerprint(backend_type: str, config: Dict[str, Any]) -> str:
    """Stable cache key for a (backend_type, config) pair."""
    payload = json.dumps({"t": backend_type, "c": config}, sort_keys=True)
    return hashlib.md5(payload.encode()).hexdigest()[:12]


async def get_backend(
    backend_type: str = "chromadb",
    config: Optional[Dict[str, Any]] = None,
) -> VectorStoreBackend:
    """Get or create a backend instance for the given type and config.

    Instances are cached by (backend_type, config) so the same backend is
    returned for identical configurations — important for ChromaDB where a
    single PersistentClient must be shared across all collections.

    Args:
        backend_type: Registered backend identifier (``"chromadb"`` | ``"teradata"``).
        config:       Backend-specific kwargs dict.
                      ChromaDB: ``{"persist_directory": "/path/to/.chromadb_rag_cache"}``
                      Teradata: ``{"host": "...", "username": "...", "database": "..."}``
    """
    config = config or {}
    key = _config_fingerprint(backend_type, config)

    if key in _INSTANCES:
        return _INSTANCES[key]

    if backend_type not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown vector store backend: '{backend_type}'. "
            f"Available backends: {available}"
        )

    cls = _REGISTRY[backend_type]

    if backend_type == "chromadb":
        persist = config.get("persist_directory")
        instance = cls(persist_directory=Path(persist) if persist else None)
    else:
        instance = cls(connection_config=config)  # type: ignore[call-arg]

    await instance.initialize()

    # Validate required capabilities
    missing = REQUIRED_CAPABILITIES - instance.capabilities()
    if missing:
        names = ", ".join(c.name for c in missing)
        raise RuntimeError(
            f"Backend '{backend_type}' is missing required capabilities: {names}"
        )

    _INSTANCES[key] = instance
    logger.info(f"Created vector store backend: {backend_type} (key={key})")
    return instance


async def get_default_chromadb_backend(persist_directory: Optional[Path] = None) -> ChromaDBBackend:
    """Return the shared default ChromaDB backend.

    Called once during RAGRetriever initialization.  All subsequent calls
    return the same singleton.  The ``persist_directory`` argument is only
    used on first call; later calls ignore it and return the cached instance.
    """
    global _DEFAULT_CHROMADB
    if _DEFAULT_CHROMADB is not None:
        return _DEFAULT_CHROMADB

    config: Dict[str, Any] = {}
    if persist_directory:
        config["persist_directory"] = str(persist_directory)

    backend = await get_backend("chromadb", config)
    _DEFAULT_CHROMADB = backend  # type: ignore[assignment]
    return _DEFAULT_CHROMADB


async def get_backend_for_collection(coll_meta: Dict[str, Any]) -> VectorStoreBackend:
    """Resolve and return the correct backend for a collection metadata dict.

    ``coll_meta`` is the dict returned by ``CollectionDatabase.get_collection_by_id()``.
    It must contain ``backend_type`` (defaults to ``"chromadb"``) and optionally
    ``backend_config`` (JSON string with backend-specific connection parameters).
    """
    backend_type = coll_meta.get("backend_type") or "chromadb"
    backend_config_raw = coll_meta.get("backend_config") or "{}"

    if isinstance(backend_config_raw, str):
        try:
            backend_config: Dict[str, Any] = json.loads(backend_config_raw)
        except (json.JSONDecodeError, ValueError):
            backend_config = {}
    else:
        backend_config = backend_config_raw

    # ChromaDB always returns the shared singleton regardless of per-collection config
    if backend_type == "chromadb":
        return await get_default_chromadb_backend()

    return await get_backend(backend_type, backend_config)


def reset_instances() -> None:
    """Clear all cached backend instances.  Used in tests only."""
    global _DEFAULT_CHROMADB
    _INSTANCES.clear()
    _DEFAULT_CHROMADB = None
