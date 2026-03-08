"""
RAG Access Context - Unified Access Control Layer

Provides a centralized, reusable context object that encapsulates user identity
and applies consistent access control rules across all RAG operations:
- Retrieval (planner few-shot examples, autocomplete suggestions)
- Storage (case processing and caching)
- Querying (ChromaDB query construction)
- Maintenance (vector store operations)

This single abstraction prevents bypassing access checks and ensures permission
rules are applied uniformly throughout the RAG system.
"""

import logging
from typing import Dict, List, Set, Optional, Any
from trusted_data_agent.agent.rag_template_generator import RAGTemplateGenerator

logger = logging.getLogger("rag_access_context")


class RAGAccessContext:
    """
    Unified context for RAG operations with built-in access control.
    
    Encapsulates:
    - User identity (who is performing the operation)
    - Collection accessibility (which collections the user can access)
    - Query builders (apply context rules to ChromaDB queries)
    - Access validators (check permissions before operations)
    
    This class is designed to be created once per operation and passed through
    the RAG retrieval, storage, and processing pipelines to ensure consistent
    access control application.
    """
    
    def __init__(self, user_id: Optional[str], retriever: 'RAGRetriever'):
        """
        Initialize RAG access context.
        
        Args:
            user_id: User UUID performing the operation. None for unauthenticated access.
            retriever: RAGRetriever instance for collection metadata and access checks.
        """
        self.user_id = user_id
        self.retriever = retriever
        self._accessible_collections_cache: Optional[Set[int]] = None
        self._access_type_cache: Dict[int, str] = {}  # collection_id -> "owned"|"subscribed"|"public"
    
    @property
    def accessible_collections(self) -> Set[int]:
        """
        Get cached set of collection IDs accessible to this user.
        
        Returns:
            Set of collection IDs the user can read from (owned + subscribed + public).
            Empty set if user is unauthenticated.
        """
        if self._accessible_collections_cache is None:
            accessible_ids = self.retriever._get_user_accessible_collections(self.user_id)
            self._accessible_collections_cache = set(accessible_ids)
            logger.debug(f"User {self.user_id} has access to collections: {self._accessible_collections_cache}")
        return self._accessible_collections_cache
    
    def validate_collection_access(self, collection_id: int, write: bool = False) -> bool:
        """
        Validate if user can access collection.
        
        Args:
            collection_id: Collection to check access for.
            write: If True, require ownership (write permission). If False, allow read-only access.
        
        Returns:
            True if user has required access level, False otherwise.
        """
        if write:
            # Write access requires ownership
            can_write = self.retriever.is_user_collection_owner(collection_id, self.user_id)
            if not can_write:
                logger.warning(f"User {self.user_id} attempted write access to collection {collection_id} (not owner)")
            return can_write
        else:
            # Read access: can access via ownership or subscription
            can_read = collection_id in self.accessible_collections
            if not can_read:
                logger.warning(f"User {self.user_id} attempted read access to collection {collection_id} (not accessible)")
            return can_read
    
    def get_access_type(self, collection_id: int) -> str:
        """
        Determine how user accesses this collection.
        
        Returns:
            "owned" - User owns the collection
            "subscribed" - User has active subscription
            "public" - Collection is public/unlisted (read-only)
            None - User cannot access collection
        """
        if collection_id in self._access_type_cache:
            return self._access_type_cache[collection_id]
        
        # Check ownership first
        if self.retriever.is_user_collection_owner(collection_id, self.user_id):
            access_type = "owned"
        # Check subscription
        elif self.retriever.is_subscribed_collection(collection_id, self.user_id):
            access_type = "subscribed"
        # Check if public/unlisted
        else:
            coll_meta = self.retriever.get_collection_metadata(collection_id)
            if coll_meta and coll_meta.get("visibility") in ["public", "unlisted"]:
                access_type = "public"
            else:
                access_type = None
        
        self._access_type_cache[collection_id] = access_type
        return access_type
    
    def build_query_filter(self, collection_id: int, extra_filter: Optional[Dict[str, Any]] = None, **conditions) -> Dict[str, Any]:
        """
        Build ChromaDB where clause with automatic context filtering.
        
        This is the key method that enforces access control uniformly across all
        ChromaDB queries. It validates access and merges context-aware conditions
        with user-provided query conditions.
        
        Args:
            collection_id: Which collection to query.
            extra_filter: Optional dictionary of complex conditions (e.g. $or logic) to add to the AND block.
            **conditions: Additional simple key-value conditions to merge.
                Example: strategy_type={"$eq": "successful"}
        
        Returns:
            Complete ChromaDB where clause as a dictionary.
            
        Raises:
            PermissionError: If user cannot read from collection.
        """
        # Validate read access
        if not self.validate_collection_access(collection_id, write=False):
            raise PermissionError(
                f"User {self.user_id} cannot read from collection {collection_id}"
            )
        
        # Build the base conditions list
        and_conditions = []
        
        # Add user context based on collection type
        access_type = self.get_access_type(collection_id)
        
        if access_type == "owned":
            # For owned collections, show this user's cases AND template-generated cases
            # (user_uuid matches current user OR template UUID)
            and_conditions.append({
                "$or": [
                    {"user_uuid": {"$eq": self.user_id}},
                    {"user_uuid": {"$eq": RAGTemplateGenerator.TEMPLATE_SESSION_ID}}
                ]
            })
            logger.debug(f"Query filter for owned collection {collection_id}: filtering by user_uuid={self.user_id} OR template UUID")
        
        elif access_type == "subscribed":
            # For subscribed collections, show all cases (different creators)
            # This allows learning from others' strategies
            logger.debug(f"Query filter for subscribed collection {collection_id}: no user_uuid filter (see all cases)")
        
        elif access_type == "public":
            # For public collections, show all cases
            logger.debug(f"Query filter for public collection {collection_id}: no user_uuid filter (see all cases)")
        
        # Add extra complex filter if provided
        if extra_filter:
            and_conditions.append(extra_filter)
        
        # Merge user-provided simple conditions
        for key, value in conditions.items():
            and_conditions.append({key: value})
        
        # Return merged where clause
        if len(and_conditions) == 1:
            # Single condition - return directly
            return and_conditions[0]
        else:
            # Multiple conditions - wrap in $and
            return {"$and": and_conditions}
    
    def is_same_user(self, other_user_id: Optional[str]) -> bool:
        """
        Check if comparing same user.
        
        Args:
            other_user_id: User UUID to compare against.
            
        Returns:
            True if same user, False otherwise.
        """
        return self.user_id == other_user_id
    
    def clear_cache(self):
        """Clear cached collections and access types (useful for testing or after permission changes)."""
        self._accessible_collections_cache = None
        self._access_type_cache.clear()
        logger.debug(f"Cleared access context cache for user {self.user_id}")
    
    def __repr__(self):
        return f"<RAGAccessContext(user_id='{self.user_id}', accessible={len(self.accessible_collections)} collections)>"
