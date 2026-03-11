"""
Normalized data types for the vector store abstraction layer.

These types provide a backend-agnostic representation of vector store
documents, query results, and collection configuration. Each backend
translates to/from its native format at the boundary.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple


class DistanceMetric(Enum):
    COSINE = "cosine"
    EUCLIDEAN = "euclidean"
    DOT_PRODUCT = "dot_product"
    MANHATTAN = "manhattan"


class SearchMode(Enum):
    """Controls how ``query()`` searches the vector store.

    Backends that declare ``HYBRID_SEARCH`` capability support all three modes.
    Backends without that capability silently fall back to ``SEMANTIC``.
    """
    SEMANTIC = "semantic"   # Dense vector similarity (default, all backends)
    KEYWORD = "keyword"     # Sparse / keyword-only search
    HYBRID = "hybrid"       # Combined dense + sparse with fusion (e.g. RRF)


@dataclass
class VectorDocument:
    """A single document stored in (or retrieved from) a vector store.

    The ``embedding`` field is None in most operations. It is populated only
    when explicitly requested (e.g. during collection fork / export) via
    ``include_embeddings=True`` on a ``get()`` call.
    """
    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None


@dataclass
class QueryResult:
    """Normalized result from a similarity-search query.

    ChromaDB returns nested lists:  {"ids": [["id1","id2"]], "distances": [[0.1,0.2]], ...}
    This type uses flat parallel lists so all callers work uniformly regardless
    of which backend produced the result.
    """
    documents: List[VectorDocument]  # flat list, 1:1 with distances
    distances: List[float]           # raw backend distances (lower = more similar for cosine)
    total_results: int

    def __len__(self) -> int:
        return len(self.documents)

    def __iter__(self) -> Iterator[Tuple[VectorDocument, float]]:
        return iter(zip(self.documents, self.distances))

    def is_empty(self) -> bool:
        return len(self.documents) == 0


@dataclass
class GetResult:
    """Normalized result from a fetch / get operation (no similarity scoring)."""
    documents: List[VectorDocument]
    total_count: int

    def __len__(self) -> int:
        return len(self.documents)

    def is_empty(self) -> bool:
        return len(self.documents) == 0


@dataclass
class CollectionConfig:
    """Configuration required to create or connect to a vector store collection.

    ``backend_config`` carries backend-specific parameters that are opaque to
    the abstraction layer (e.g. Teradata host/database, Bedrock region).
    """
    name: str
    distance_metric: DistanceMetric = DistanceMetric.COSINE
    embedding_model: str = "all-MiniLM-L6-v2"
    metadata: Dict[str, Any] = field(default_factory=dict)
    backend_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectionInfo:
    """Metadata about an existing vector store collection."""
    name: str
    document_count: int
    distance_metric: DistanceMetric = DistanceMetric.COSINE
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ServerSideChunkingConfig:
    """Configuration for server-side document chunking (Teradata EVS).

    When ``optimized_chunking`` is True the backend uses structure-aware
    dynamic chunking and ``chunk_size`` is ignored.  When False, splits
    by fixed character count using ``chunk_size``.

    ``header_height`` / ``footer_height`` specify the number of **points**
    to trim from the top / bottom of each PDF page before chunking.
    Recommended footer value: 55 for standard page footers.
    """
    optimized_chunking: bool = True
    chunk_size: int = 2000
    header_height: int = 0
    footer_height: int = 0


@dataclass
class IngestionProgress:
    """Progress update from a long-running vector store ingestion operation.

    Emitted by backends that support ``SERVER_SIDE_CHUNKING`` during
    ``add_document_files()`` to report real operation phases back to callers
    (e.g. SSE streaming endpoints).
    """
    status: str          # Backend-specific status (e.g. "CREATING (EMBEDDING)")
    phase: str           # Human-readable phase label
    percentage: int      # Estimated 0-100 progress
    elapsed_seconds: int # Seconds since operation started


# Callback type for ingestion progress updates.
IngestionProgressCallback = Callable[[IngestionProgress], None]
