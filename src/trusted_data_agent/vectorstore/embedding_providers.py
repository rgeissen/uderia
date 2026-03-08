"""
Embedding provider abstraction.

Separates embedding concerns from vector store concerns:
  - SentenceTransformerProvider  — client-side inference (current ChromaDB approach)
  - ServerSideEmbeddingProvider  — marker for backends that embed server-side (Teradata)

The class-level model cache mirrors the existing ``embedding_functions_cache``
in RAGRetriever so no model is loaded more than once per process.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("vectorstore.embedding")


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers."""

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        ...

    @abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """Generate an embedding for a single query string."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the vector dimensionality produced by this model."""
        ...


# ── Client-side (SentenceTransformers) ───────────────────────────────────────

# Known dimension map — extended as new models are used.
_ST_DIMENSIONS: Dict[str, int] = {
    "all-MiniLM-L6-v2": 384,
    "all-MiniLM-L12-v2": 384,
    "all-mpnet-base-v2": 768,
    "paraphrase-multilingual-MiniLM-L12-v2": 384,
}


class SentenceTransformerProvider(EmbeddingProvider):
    """Client-side embedding via SentenceTransformers / ChromaDB's embedding function.

    Instances are cached at the class level (keyed by model name) so the heavy
    model-loading happens at most once per process — identical to the original
    ``embedding_functions_cache`` in RAGRetriever.
    """

    # Class-level cache: model_name -> SentenceTransformerEmbeddingFunction
    _cache: Dict[str, Any] = {}

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        if model_name not in self._cache:
            from chromadb.utils import embedding_functions
            logger.debug(f"Loading SentenceTransformer embedding model: {model_name}")
            self._cache[model_name] = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model_name
            )
        self._ef = self._cache[model_name]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return list(self._ef(texts))

    def embed_query(self, query: str) -> List[float]:
        return list(self._ef([query])[0])

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return _ST_DIMENSIONS.get(self._model_name, 384)

    @property
    def chromadb_embedding_function(self) -> Any:
        """Return the raw ChromaDB EmbeddingFunction for use in collection creation."""
        return self._ef

    @classmethod
    def get_cached(cls, model_name: str = "all-MiniLM-L6-v2") -> "SentenceTransformerProvider":
        """Return a cached provider instance — avoids redundant object creation."""
        # The provider object itself is lightweight; caching the EF is what matters.
        return cls(model_name)


# ── Server-side embedding marker ──────────────────────────────────────────────

class ServerSideEmbeddingProvider(EmbeddingProvider):
    """Marker provider for backends that handle embedding internally (e.g. Teradata).

    ``embed_texts`` and ``embed_query`` raise ``NotImplementedError`` because the
    backend, not the client, generates embeddings. Backends check for this type
    via ``isinstance(provider, ServerSideEmbeddingProvider)`` and skip client-side
    inference accordingly.
    """

    def __init__(self, model_name: str = "server-side"):
        self._model_name = model_name

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError(
            f"Backend uses server-side embedding ({self._model_name}). "
            "Do not call embed_texts() on a ServerSideEmbeddingProvider."
        )

    def embed_query(self, query: str) -> List[float]:
        raise NotImplementedError(
            f"Backend uses server-side embedding ({self._model_name}). "
            "Do not call embed_query() on a ServerSideEmbeddingProvider."
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return 0  # Determined by the server


# ── Factory helper ────────────────────────────────────────────────────────────

def get_embedding_provider(
    backend_type: str,
    model_name: str = "all-MiniLM-L6-v2",
) -> EmbeddingProvider:
    """Return the appropriate EmbeddingProvider for a given backend type.

    Teradata uses server-side embedding (Bedrock/Azure).  All other backends
    (chromadb, qdrant) use client-side SentenceTransformer embedding.
    """
    if backend_type == "teradata":
        return ServerSideEmbeddingProvider(model_name)
    return SentenceTransformerProvider.get_cached(model_name)
