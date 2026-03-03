"""
Vector store abstraction package.

Public API — import from here, not from submodules directly.

Example usage:
    from trusted_data_agent.vectorstore import (
        VectorStoreBackend,
        VectorDocument, QueryResult, GetResult,
        CollectionConfig, CollectionInfo, DistanceMetric,
        VectorStoreCapability,
        EmbeddingProvider, SentenceTransformerProvider,
        MetadataFilter, FieldFilter, AndFilter, OrFilter,
        eq, ne, gt, gte, lt, lte, and_, or_,
        get_backend, get_default_chromadb_backend, get_backend_for_collection,
        register_backend,
    )
"""

from .base import VectorStoreBackend
from .capabilities import VectorStoreCapability, REQUIRED_CAPABILITIES
from .embedding_providers import (
    EmbeddingProvider,
    SentenceTransformerProvider,
    ServerSideEmbeddingProvider,
    get_embedding_provider,
)
from .factory import (
    get_backend,
    get_default_chromadb_backend,
    get_backend_for_collection,
    register_backend,
    reset_instances,
)
from .filters import (
    FilterOp,
    FieldFilter,
    AndFilter,
    OrFilter,
    MetadataFilter,
    to_chromadb_where,
    from_chromadb_where,
    eq,
    ne,
    gt,
    gte,
    lt,
    lte,
    and_,
    or_,
)
from .types import (
    CollectionConfig,
    CollectionInfo,
    DistanceMetric,
    GetResult,
    QueryResult,
    VectorDocument,
)

__all__ = [
    # Base class
    "VectorStoreBackend",
    # Capabilities
    "VectorStoreCapability",
    "REQUIRED_CAPABILITIES",
    # Embedding providers
    "EmbeddingProvider",
    "SentenceTransformerProvider",
    "ServerSideEmbeddingProvider",
    "get_embedding_provider",
    # Factory
    "get_backend",
    "get_default_chromadb_backend",
    "get_backend_for_collection",
    "register_backend",
    "reset_instances",
    # Filters
    "FilterOp",
    "FieldFilter",
    "AndFilter",
    "OrFilter",
    "MetadataFilter",
    "to_chromadb_where",
    "from_chromadb_where",
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "and_",
    "or_",
    # Types
    "CollectionConfig",
    "CollectionInfo",
    "DistanceMetric",
    "GetResult",
    "QueryResult",
    "VectorDocument",
]
