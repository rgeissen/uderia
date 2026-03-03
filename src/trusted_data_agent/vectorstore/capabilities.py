"""
Capability negotiation for vector store backends.

Each backend declares which optional operations it supports. Callers check
capabilities before using advanced features (e.g. embedding pass-through
during fork, metadata-only updates).
"""

from enum import Enum, auto
from typing import Set


class VectorStoreCapability(Enum):
    # ── Required (every backend MUST declare these) ───────────────────────────
    CREATE_COLLECTION = auto()
    DELETE_COLLECTION = auto()
    ADD_DOCUMENTS = auto()
    DELETE_DOCUMENTS = auto()
    SIMILARITY_SEARCH = auto()
    GET_BY_ID = auto()
    COUNT = auto()

    # ── Optional ──────────────────────────────────────────────────────────────
    UPSERT = auto()
    """Atomic insert-or-update. If absent, callers must check existence first."""

    GET_BY_METADATA_FILTER = auto()
    """Filter documents by metadata predicates during get()."""

    UPDATE_METADATA = auto()
    """Update metadata for existing documents without re-embedding the content."""

    EMBEDDING_PASSTHROUGH = auto()
    """Accept pre-computed embeddings via add(). Required for fork and fast import."""

    GET_ALL = auto()
    """Retrieve all documents (with optional pagination). Required for export."""

    SERVER_SIDE_EMBEDDING = auto()
    """Backend generates embeddings internally (e.g. Teradata + Bedrock).
    When declared, the EmbeddingProvider passed to add()/query() is a
    ServerSideEmbeddingProvider marker and must NOT be called for inference."""


# Every concrete backend must declare at least these:
REQUIRED_CAPABILITIES: Set[VectorStoreCapability] = {
    VectorStoreCapability.CREATE_COLLECTION,
    VectorStoreCapability.DELETE_COLLECTION,
    VectorStoreCapability.ADD_DOCUMENTS,
    VectorStoreCapability.DELETE_DOCUMENTS,
    VectorStoreCapability.SIMILARITY_SEARCH,
    VectorStoreCapability.GET_BY_ID,
    VectorStoreCapability.COUNT,
}
