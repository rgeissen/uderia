import os
import json
import glob
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
# --- MODIFICATION START: Import uuid, copy, and datetime ---
import uuid
import copy
from datetime import datetime, timezone
# --- MODIFICATION END ---
# --- MARKETPLACE PHASE 2: Import database models for subscriptions ---
from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import CollectionSubscription
# --- MARKETPLACE PHASE 2 END ---

# Disable tqdm progress bars from ChromaDB
os.environ['TQDM_DISABLE'] = '1'

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.utils import embedding_functions

from trusted_data_agent.core.config import APP_CONFIG, APP_STATE
from trusted_data_agent.core.config_manager import get_config_manager

# Configure a dedicated logger for the RAG retriever
logger = logging.getLogger("rag_retriever")

class RAGRetriever:
    def __init__(self, rag_cases_dir: str | Path, embedding_model_name: str = "all-MiniLM-L6-v2", persist_directory: Optional[str | Path] = None):
        self.rag_cases_dir = Path(rag_cases_dir).resolve()
        self.embedding_model_name = embedding_model_name
        self.persist_directory = Path(persist_directory).resolve() if persist_directory else None

        # Create RAG cases directory if it doesn't exist
        if not self.rag_cases_dir.exists():
            logger.info(f"Creating RAG cases directory at: {self.rag_cases_dir}")
            self.rag_cases_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client
        if self.persist_directory:
            self.persist_directory.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        else:
            self.client = chromadb.Client()

        # Initialize default embedding function (for backward compatibility)
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self.embedding_model_name
        )

        # --- MODIFICATION START: Support multiple collections ---
        # Store collections as a dict: {collection_id: chromadb_collection_object}
        self.collections = {}

        # Store embedding functions per collection: {embedding_model_name: embedding_function}
        self.embedding_functions_cache = {
            self.embedding_model_name: self.embedding_function
        }

        # Initialize feedback cache: maps case_id -> feedback_score
        self.feedback_cache = {}
        
        # Initialize default collection if not already in APP_STATE
        self._ensure_default_collection()
        
        # Migrate flat structure to nested collection directories
        self._migrate_to_nested_structure()
        
        # Load all active collections from APP_STATE
        self._load_active_collections()
        
        # Auto-rebuild ChromaDB from JSON files if collections are empty
        self._auto_rebuild_if_needed()
        
        # Load feedback cache from case files
        self._load_feedback_cache()
        # --- MODIFICATION END ---

    def _get_embedding_function(self, embedding_model: str):
        """
        Get or create an embedding function for a specific model.
        Uses caching to avoid creating duplicate embedding functions.

        Args:
            embedding_model: Name of the embedding model (e.g., 'all-MiniLM-L6-v2', 'all-mpnet-base-v2')

        Returns:
            ChromaDB embedding function for the specified model
        """
        if embedding_model not in self.embedding_functions_cache:
            logger.info(f"Creating new embedding function for model: {embedding_model}")
            self.embedding_functions_cache[embedding_model] = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=embedding_model
            )
        return self.embedding_functions_cache[embedding_model]

    def _ensure_default_collection(self):
        """
        DEPRECATED: Default collections are now created per-user in the database.
        This method is kept for backward compatibility but does nothing.
        Default collections are created automatically when users log in or register.
        """
        # Load ONLY planner collections from database into APP_STATE
        # Knowledge collections are loaded separately in _load_active_collections()
        config_manager = get_config_manager()
        all_collections = config_manager.get_rag_collections()
        planner_collections = [c for c in all_collections if c.get('repository_type') == 'planner']
        APP_STATE["rag_collections"] = planner_collections
        logger.debug(f"Loaded {len(planner_collections)} planner collections from database into APP_STATE")
    
    def get_collection_metadata(self, collection_id: int) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific collection by ID."""
        collections_list = APP_STATE.get("rag_collections", [])
        return next((c for c in collections_list if c["id"] == collection_id), None)
    
    def _get_user_accessible_collections(self, user_id: Optional[str] = None) -> List[int]:
        """
        Get collection IDs accessible to a specific user.
        
        Args:
            user_id: User UUID. If None, returns only public collections.
            
        Returns:
            List of collection IDs the user can access (owned + subscribed)
            
        Access rules:
        - Admin users (owner_user_id is None): Accessible to everyone
        - Owner: User owns the collection (owner_user_id matches)
        - Subscribed: User has an active subscription
        - Public: Collection visibility is 'public' or 'unlisted'
        """
        accessible_ids = []
        collections_list = APP_STATE.get("rag_collections", [])
        
        for coll in collections_list:
            coll_id = coll["id"]
            owner_id = coll.get("owner_user_id")
            visibility = coll.get("visibility", "private")
            
            # Rule 1: Admin-owned collections (owner_user_id is None) are accessible to all
            if owner_id is None:
                accessible_ids.append(coll_id)
                continue
            
            # Rule 2: User owns the collection
            if user_id and owner_id == user_id:
                accessible_ids.append(coll_id)
                continue
            
            # Rule 3: Public or unlisted collections
            if visibility in ["public", "unlisted"]:
                accessible_ids.append(coll_id)
                continue
            
            # Rule 4: User has active subscription
            if user_id:
                try:
                    with get_db_session() as session:
                        subscription = session.query(CollectionSubscription).filter_by(
                            user_id=user_id,
                            source_collection_id=coll_id,
                            enabled=True
                        ).first()
                        if subscription:
                            accessible_ids.append(coll_id)
                except Exception as e:
                    logger.warning(f"Error checking subscription for collection {coll_id}: {e}")
        
        return accessible_ids
    
    def is_user_collection_owner(self, collection_id: int, user_id: Optional[str]) -> bool:
        """
        Check if a user owns a specific collection.
        
        Args:
            collection_id: Collection ID
            user_id: User UUID
            
        Returns:
            True if user is the owner or collection is admin-owned (owner_user_id is None)
        """
        coll_meta = self.get_collection_metadata(collection_id)
        if not coll_meta:
            return False
        
        owner_id = coll_meta.get("owner_user_id")
        
        # Admin-owned collections (owner_user_id is None) are considered owned by admins
        if owner_id is None:
            # Check if user is admin
            if user_id:
                try:
                    from trusted_data_agent.auth.database import get_db_session
                    from trusted_data_agent.auth.models import User
                    with get_db_session() as session:
                        user = session.query(User).filter_by(id=user_id).first()
                        return user and user.is_admin
                except Exception as e:
                    logger.warning(f"Error checking admin status: {e}")
                    return False
            return False
        
        # User owns the collection
        return owner_id == user_id
    
    def _get_user_default_collection_id(self, user_id: str) -> Optional[int]:
        """
        Get the user's default collection ID.
        
        Args:
            user_id: User UUID
            
        Returns:
            Collection ID of user's default collection, or None if not found
        """
        if not user_id:
            return None
            
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            
            # Get all collections
            collections = APP_STATE.get("rag_collections", [])
            
            # Find user's owned collections
            user_collections = [c for c in collections if c.get("owner_user_id") == user_id]
            
            if not user_collections:
                logger.warning(f"No collections found for user {user_id}")
                return None
            
            # Return the first collection (typically the default one created at registration)
            # Collections are sorted by ID, so the first one is usually the default
            default_collection = user_collections[0]
            logger.debug(f"Found default collection {default_collection['id']} for user {user_id}")
            return default_collection["id"]
            
        except Exception as e:
            logger.error(f"Error getting default collection for user {user_id}: {e}", exc_info=True)
            return None
    
    def is_subscribed_collection(self, collection_id: int, user_id: Optional[str]) -> bool:
        """
        Check if a collection is accessed via subscription (not owned).
        
        Args:
            collection_id: Collection ID
            user_id: User UUID
            
        Returns:
            True if user has active subscription but doesn't own the collection
        """
        if not user_id:
            return False
        
        # Check if user is owner
        if self.is_user_collection_owner(collection_id, user_id):
            return False
        
        # Check if user has active subscription
        try:
            with get_db_session() as session:
                subscription = session.query(CollectionSubscription).filter_by(
                    user_id=user_id,
                    source_collection_id=collection_id,
                    enabled=True
                ).first()
                return subscription is not None
        except Exception as e:
            logger.warning(f"Error checking subscription status: {e}")
            return False
    
    def _get_collection_dir(self, collection_id: int) -> Path:
        """Returns the directory path for a specific collection."""
        return self.rag_cases_dir / f"collection_{collection_id}"
    
    def _ensure_collection_dir(self, collection_id: int) -> Path:
        """Ensures the collection directory exists and validates collection_id."""
        # Validate collection exists in APP_STATE
        if self.get_collection_metadata(collection_id) is None:
            raise ValueError(f"Collection ID {collection_id} does not exist in APP_STATE")
        
        collection_dir = self._get_collection_dir(collection_id)
        collection_dir.mkdir(parents=True, exist_ok=True)
        return collection_dir
    
    def _migrate_to_nested_structure(self):
        """One-time migration: moves flat cases into collection subdirectories based on their metadata."""
        # Find all flat case files in root directory (not in subdirectories)
        flat_cases = [f for f in self.rag_cases_dir.glob("case_*.json") if f.parent == self.rag_cases_dir]
        
        if not flat_cases:
            logger.debug("No flat case files found to migrate.")
            return
        
        logger.info(f"Migrating {len(flat_cases)} cases to nested collection structure...")
        
        migrated_count = 0
        for case_file in flat_cases:
            try:
                # Read case to get collection_id from metadata
                with open(case_file, 'r', encoding='utf-8') as f:
                    case_data = json.load(f)
                
                # Default to collection 0 for old cases without collection_id
                collection_id = case_data.get("metadata", {}).get("collection_id", 0)
                
                # Update metadata to include collection_id if missing
                if "collection_id" not in case_data.get("metadata", {}):
                    case_data.setdefault("metadata", {})["collection_id"] = collection_id
                    logger.debug(f"Added collection_id={collection_id} to case {case_file.name}")
                
                # Create collection directory
                collection_dir = self._get_collection_dir(collection_id)
                collection_dir.mkdir(parents=True, exist_ok=True)
                
                # Move file to collection directory
                target = collection_dir / case_file.name
                
                # Write updated metadata and move
                with open(target, 'w', encoding='utf-8') as f:
                    json.dump(case_data, f, indent=2)
                
                # Remove old file
                case_file.unlink()
                migrated_count += 1
                
            except Exception as e:
                logger.error(f"Failed to migrate case {case_file.name}: {e}", exc_info=True)
        
        logger.info(f"Migration complete: {migrated_count} cases migrated to nested structure.")
    
    def _load_active_collections(self):
        """
        Loads and initializes enabled collections.
        Loads both planner repositories (from APP_STATE) and knowledge repositories (from database).
        """
        # Load planner repositories from APP_STATE
        planner_collections = APP_STATE.get("rag_collections", [])
        
        # Load knowledge repositories from database
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        all_collections_from_db = collection_db.get_all_collections()
        knowledge_collections = [c for c in all_collections_from_db if c.get('repository_type') == 'knowledge' and c.get('enabled')]
        
        # Combine both lists
        collections_list = planner_collections + knowledge_collections
        
        current_mcp_server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID
        
        # Planner collections are filtered by MCP server
        # Knowledge collections are always loaded (not tied to MCP servers)
        # If no MCP server configured, load all enabled collections for viewing
        if not current_mcp_server_id:
            filter_by_mcp = False
        else:
            filter_by_mcp = True
        
        for coll_meta in collections_list:
            if not coll_meta.get("enabled", False):
                continue
            
            coll_id = coll_meta["id"]
            coll_name = coll_meta["collection_name"]
            coll_mcp_server_id = coll_meta.get("mcp_server_id")
            repo_type = coll_meta.get("repository_type", "planner")
            coll_embedding_model = coll_meta.get("embedding_model", self.embedding_model_name)

            # Knowledge repositories are always loaded (not tied to MCP servers)
            # Planner repositories are filtered by MCP server
            if repo_type == "knowledge":
                # Always load knowledge repositories
                pass
            elif filter_by_mcp and coll_mcp_server_id != current_mcp_server_id:
                logger.debug(f"Skipping collection '{coll_id}': associated with server ID '{coll_mcp_server_id}', current server ID is '{current_mcp_server_id}'")
                continue

            try:
                # Get collection-specific embedding function
                embedding_func = self._get_embedding_function(coll_embedding_model)
                logger.debug(f"Loading collection '{coll_id}' ({coll_name}) with embedding model: {coll_embedding_model}")

                # Try to get existing collection first (for imported collections)
                # Don't pass embedding_function to get_collection - it will use the stored one
                try:
                    collection = self.client.get_collection(name=coll_name)
                    doc_count = collection.count()
                    logger.info(f"Loaded existing collection '{coll_name}' with {doc_count} documents")
                except Exception as get_error:
                    # Collection doesn't exist, create it
                    logger.info(f"Collection '{coll_name}' not found ({get_error}), creating new empty collection")
                    collection = self.client.create_collection(
                        name=coll_name,
                        embedding_function=embedding_func,
                        metadata={"hnsw:space": "cosine"}
                    )
                    logger.info(f"Created new empty collection '{coll_name}'")

                self.collections[coll_id] = collection
            except KeyError as e:
                if "'_type'" in str(e):
                    logger.error(f"Collection '{coll_id}' has corrupted metadata (missing _type field). Attempting to delete and recreate...")
                    try:
                        # Try to delete the corrupted collection
                        self.client.delete_collection(name=coll_name)
                        logger.info(f"Deleted corrupted collection '{coll_name}'")
                        # Recreate it with collection-specific embedding model
                        embedding_func = self._get_embedding_function(coll_embedding_model)
                        collection = self.client.create_collection(
                            name=coll_name,
                            embedding_function=embedding_func,
                            metadata={"hnsw:space": "cosine"}
                        )
                        self.collections[coll_id] = collection
                    except Exception as delete_error:
                        logger.error(f"Failed to recover collection '{coll_id}': {delete_error}. Run maintenance/reset_chromadb.py to fix.", exc_info=True)
                else:
                    logger.error(f"Failed to load collection '{coll_id}': {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Failed to load collection '{coll_id}': {e}", exc_info=True)
        
        if not self.collections and filter_by_mcp:
            logger.warning(f"No active RAG collections loaded for MCP server ID '{current_mcp_server_id}'!")
        
        # Refresh vector stores for all collections if configured
        if APP_CONFIG.RAG_REFRESH_ON_STARTUP:
            for coll_id in self.collections:
                self._maintain_vector_store(coll_id)
    
    def _auto_rebuild_if_needed(self):
        """
        Automatically rebuilds ChromaDB from JSON files if collections are empty
        but JSON case files exist. This ensures a fresh git clone can automatically
        populate ChromaDB without manual intervention.
        """
        for coll_id, collection in self.collections.items():
            try:
                # Check if collection is empty in ChromaDB
                count = collection.count()
                
                # Check if JSON files exist on disk
                collection_dir = self._get_collection_dir(coll_id)
                json_files = list(collection_dir.glob("case_*.json"))
                
                # If ChromaDB is empty but JSON files exist, rebuild
                if count == 0 and len(json_files) > 0:
                    logger.info(f"Collection '{coll_id}' is empty but {len(json_files)} JSON case files found. Auto-rebuilding...")
                    self._maintain_vector_store(coll_id)
                    logger.info(f"Auto-rebuild complete for collection '{coll_id}'")
                elif count == 0 and len(json_files) == 0:
                    logger.debug(f"Collection '{coll_id}' is empty and no JSON files found (new collection)")
                else:
                    logger.debug(f"Collection '{coll_id}' has {count} documents in ChromaDB")
                    
            except Exception as e:
                logger.error(f"Failed to auto-rebuild collection '{coll_id}': {e}", exc_info=True)
    
    def fork_collection(self, source_collection_id: int, new_name: str, new_description: str = "", owner_user_id: Optional[str] = None, mcp_server_id: Optional[str] = None) -> Optional[int]:
        """
        Fork (copy) an existing collection to create an independent copy.
        
        Args:
            source_collection_id: ID of the collection to fork
            new_name: Name for the new forked collection
            new_description: Description for the new collection
            owner_user_id: Owner of the new collection
            mcp_server_id: MCP server ID for the new collection (required)
            
        Returns:
            New collection ID if successful, None otherwise
            
        Note:
            This creates a complete copy including:
            - All ChromaDB embeddings and metadata
            - All JSON case files
            - Independent collection that can be modified without affecting the source
        """
        if mcp_server_id is None:
            logger.error("Cannot fork collection: mcp_server_id is required")
            return None
        
        # Verify source collection exists
        source_meta = self.get_collection_metadata(source_collection_id)
        if not source_meta:
            logger.error(f"Cannot fork: Source collection {source_collection_id} does not exist")
            return None
        
        # Create new collection
        new_collection_id = self.add_collection(new_name, new_description, mcp_server_id, owner_user_id=owner_user_id)
        if new_collection_id is None:
            logger.error("Failed to create new collection during fork")
            return None
        
        try:
            # Copy ChromaDB data if source collection is loaded
            if source_collection_id in self.collections:
                source_collection = self.collections[source_collection_id]
                
                # Ensure target collection is loaded (may not be if MCP server differs)
                if new_collection_id not in self.collections:
                    new_meta = self.get_collection_metadata(new_collection_id)
                    if new_meta:
                        target_collection = self.client.get_or_create_collection(
                            name=new_meta["collection_name"],
                            embedding_function=self.embedding_function,
                            metadata={"hnsw:space": "cosine"}
                        )
                        self.collections[new_collection_id] = target_collection
                        logger.info(f"Loaded forked collection {new_collection_id} into retriever for copying")
                else:
                    target_collection = self.collections[new_collection_id]
                
                # Get all documents from source
                results = source_collection.get(include=["documents", "metadatas", "embeddings"])
                
                if results["ids"]:
                    # Copy to target collection
                    target_collection.add(
                        ids=results["ids"],
                        documents=results["documents"],
                        metadatas=results["metadatas"],
                        embeddings=results["embeddings"]
                    )
                    logger.info(f"Copied {len(results['ids'])} documents from collection {source_collection_id} to {new_collection_id}")
            
            # Copy JSON files (cases for planner, documents for knowledge)
            source_dir = self._get_collection_dir(source_collection_id)
            target_dir = self._ensure_collection_dir(new_collection_id)
            
            # Determine file pattern based on repository type
            repo_type = source_meta.get("repository_type", "planner")
            if repo_type == "knowledge":
                file_pattern = "doc_*.json"
            else:
                file_pattern = "case_*.json"
            
            data_files = list(source_dir.glob(file_pattern))
            copied_files = 0
            
            for data_file in data_files:
                try:
                    # Read source file
                    with open(data_file, 'r', encoding='utf-8') as f:
                        file_data = json.load(f)
                    
                    # Update metadata with new collection_id and fork info
                    if "metadata" in file_data:
                        file_data["metadata"]["collection_id"] = new_collection_id
                        file_data["metadata"]["forked_from"] = source_collection_id
                        file_data["metadata"]["forked_at"] = datetime.now(timezone.utc).isoformat()
                    else:
                        file_data.setdefault("metadata", {})["collection_id"] = new_collection_id
                        file_data.setdefault("metadata", {})["forked_from"] = source_collection_id
                        file_data.setdefault("metadata", {})["forked_at"] = datetime.now(timezone.utc).isoformat()
                    
                    # Write to target directory
                    target_file = target_dir / data_file.name
                    with open(target_file, 'w', encoding='utf-8') as f:
                        json.dump(file_data, f, indent=2)
                    
                    copied_files += 1
                except Exception as e:
                    logger.error(f"Failed to copy file {data_file.name}: {e}")
            
            # Copy knowledge_documents database entries if this is a knowledge repository
            if repo_type == "knowledge":
                try:
                    from trusted_data_agent.core.collection_db import CollectionDatabase
                    db = CollectionDatabase()
                    conn = db._get_connection()
                    cursor = conn.cursor()
                    
                    # Get all documents from source collection
                    cursor.execute("""
                        SELECT document_id, filename, document_type, title, author, source, 
                               category, tags, file_size, content_hash, created_at
                        FROM knowledge_documents 
                        WHERE collection_id = ?
                    """, (source_collection_id,))
                    
                    docs = cursor.fetchall()
                    
                    # Insert into target collection
                    for doc in docs:
                        cursor.execute("""
                            INSERT INTO knowledge_documents
                            (collection_id, document_id, filename, document_type, title, author, 
                             source, category, tags, file_size, content_hash, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            new_collection_id,
                            doc['document_id'],
                            doc['filename'],
                            doc['document_type'],
                            doc['title'],
                            doc['author'],
                            'forked',  # Mark as forked
                            doc['category'],
                            doc['tags'],
                            doc['file_size'],
                            doc['content_hash'],
                            doc['created_at']
                        ))
                    
                    conn.commit()
                    conn.close()
                    logger.info(f"Copied {len(docs)} document metadata entries for Knowledge repository fork")
                except Exception as e:
                    logger.error(f"Failed to copy knowledge_documents entries: {e}")
            
            logger.info(f"Successfully forked {repo_type} collection {source_collection_id} to {new_collection_id}. Copied {copied_files} files.")
            return new_collection_id
            
        except Exception as e:
            logger.error(f"Failed to fork collection {source_collection_id}: {e}", exc_info=True)
            # Clean up failed fork
            try:
                self.delete_collection(new_collection_id)
            except:
                pass
            return None
    
    def add_collection(self, name: str, description: str = "", mcp_server_id: Optional[str] = None, owner_user_id: Optional[str] = None, 
                      repository_type: str = "planner", chunking_strategy: str = "none", chunk_size: int = 1000, chunk_overlap: int = 200,
                      embedding_model: str = "all-MiniLM-L6-v2") -> Optional[int]:
        """
        Adds a new RAG collection and enables it.
        
        Args:
            name: Display name for the collection
            description: Collection description
            mcp_server_id: Associated MCP server ID (REQUIRED for planner repositories, optional for knowledge)
            owner_user_id: User ID of the collection owner
            repository_type: Type of repository - "planner" or "knowledge" (default: "planner")
            chunking_strategy: Chunking strategy for knowledge repositories (default: "none")
            chunk_size: Size of chunks in characters (default: 1000)
            chunk_overlap: Overlap between chunks (default: 200)
            embedding_model: Embedding model to use (default: "all-MiniLM-L6-v2")
            
        Returns:
            The numeric collection ID if successful, None otherwise
        """
        config_manager = get_config_manager()
        
        # Enforcement: mcp_server_id is required for planner collections only
        if repository_type == "planner" and mcp_server_id is None:
            logger.error("Cannot add planner collection: mcp_server_id is required")
            return None
        
        # Generate unique numeric ID
        collections_list = APP_STATE.get("rag_collections", [])
        existing_ids = [c["id"] for c in collections_list if isinstance(c["id"], int)]
        collection_id = max(existing_ids) + 1 if existing_ids else 1
        
        # Generate unique ChromaDB collection name
        collection_name = f"tda_rag_coll_{collection_id}_{uuid.uuid4().hex[:6]}"
        
        new_collection = {
            "name": name,
            "collection_name": collection_name,
            "mcp_server_id": mcp_server_id,
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "description": description,
            "owner_user_id": owner_user_id,
            "visibility": "private",
            "is_marketplace_listed": False,
            "subscriber_count": 0,
            "marketplace_metadata": {},
            "repository_type": repository_type,
            "chunking_strategy": chunking_strategy,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "embedding_model": embedding_model
        }
        
        # Save to database
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        try:
            collection_id = collection_db.create_collection(new_collection)
        except Exception as e:
            logger.error(f"Failed to save collection to database: {e}", exc_info=True)
            return None
        
        # Reload collections into APP_STATE
        APP_STATE["rag_collections"] = config_manager.get_rag_collections()
        
        # Create ChromaDB collection and load into retriever
        # - For planner repositories: only if it matches the current MCP server ID
        # - For knowledge repositories: always load (no MCP server requirement)
        current_mcp_server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID
        should_load = (
            repository_type == "knowledge" or  # Always load knowledge repos
            mcp_server_id == current_mcp_server_id  # Load planner repos if MCP server matches
        )
        
        if should_load:
            try:
                collection = self.client.get_or_create_collection(
                    name=collection_name,
                    embedding_function=self.embedding_function,
                    metadata={"hnsw:space": "cosine", "repository_type": repository_type}
                )
                self.collections[collection_id] = collection
                logger.info(f"Added and loaded new {repository_type} collection '{collection_id}' (ChromaDB: '{collection_name}', MCP Server ID: '{mcp_server_id or 'N/A'}')")
            except Exception as e:
                logger.error(f"Failed to create collection '{collection_id}': {e}", exc_info=True)
                # Remove from APP_STATE if creation failed
                APP_STATE["rag_collections"] = [c for c in collections_list if c["id"] != collection_id]
                config_manager.save_rag_collections(APP_STATE["rag_collections"])
                return None
        else:
            logger.info(f"Added planner collection '{collection_id}' for MCP server ID '{mcp_server_id}' (not loaded - current server ID is '{current_mcp_server_id}')")
        
        return collection_id
    
    def remove_collection(self, collection_id: int, user_id: Optional[str] = None):
        """
        Removes a RAG collection (except default).
        
        Args:
            collection_id: ID of the collection to remove
            user_id: Optional user ID to check if this is their default collection
        
        Returns:
            True if successful, False otherwise
        """
        if collection_id == 0:  # Legacy: Default collection is always ID 0
            logger.warning("Cannot remove default collection")
            return False
        
        # If user_id provided, check if this is their default collection
        if user_id:
            default_collection_id = self._get_user_default_collection_id(user_id)
            if default_collection_id and collection_id == default_collection_id:
                logger.warning(f"Cannot remove default collection {collection_id} for user {user_id}")
                return False
        
        config_manager = get_config_manager()
        collections_list = APP_STATE.get("rag_collections", [])
        coll_meta = next((c for c in collections_list if c["id"] == collection_id), None)
        
        if not coll_meta:
            logger.warning(f"Collection '{collection_id}' not found")
            return False
        
        try:
            # Delete from ChromaDB
            self.client.delete_collection(name=coll_meta["collection_name"])
            
            # Remove from runtime
            if collection_id in self.collections:
                del self.collections[collection_id]
            
            # Delete from database
            from trusted_data_agent.core.collection_db import get_collection_db
            collection_db = get_collection_db()
            collection_db.delete_collection(collection_id)
            
            # Reload APP_STATE
            APP_STATE["rag_collections"] = config_manager.get_rag_collections()
            
            logger.info(f"Removed collection '{collection_id}'")
            return True
        except Exception as e:
            logger.error(f"Failed to remove collection '{collection_id}': {e}", exc_info=True)
            return False
    
    def toggle_collection(self, collection_id: int, enabled: bool):
        """
        Enables or disables a RAG collection.
        Collections are only loaded into memory if they match the current MCP server.
        Collections cannot be enabled without an MCP server assignment.
        """
        config_manager = get_config_manager()
        collections_list = APP_STATE.get("rag_collections", [])
        coll_meta = next((c for c in collections_list if c["id"] == collection_id), None)
        
        if not coll_meta:
            logger.warning(f"Collection '{collection_id}' not found")
            return False
        
        # Validate: Cannot enable a PLANNER collection without an MCP server assignment
        # Knowledge repositories don't require MCP servers
        coll_mcp_server = coll_meta.get("mcp_server_id")
        repo_type = coll_meta.get("repository_type", "planner")
        if enabled and repo_type == "planner" and not coll_mcp_server:
            logger.warning(f"Cannot enable planner collection '{collection_id}': no MCP server assigned")
            return False
        
        # Update in database
        config_manager.update_rag_collection(collection_id, {"enabled": enabled})
        
        # Reload collections into APP_STATE
        APP_STATE["rag_collections"] = config_manager.get_rag_collections()
        collections_list = APP_STATE["rag_collections"]
        coll_meta = next((c for c in collections_list if c["id"] == collection_id), None)
        
        # Check if collection matches current MCP server ID
        current_mcp_server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID
        
        mcp_server_matches = (coll_mcp_server == current_mcp_server_id)
        
        if enabled and collection_id not in self.collections:
            if not mcp_server_matches:
                logger.info(f"Collection '{collection_id}' enabled but not loaded: associated with server ID '{coll_mcp_server}', current server ID is '{current_mcp_server_id}'")
                return True  # Config updated, but not loaded
            
            # Load the collection
            try:
                collection = self.client.get_or_create_collection(
                    name=coll_meta["collection_name"],
                    embedding_function=self.embedding_function,
                    metadata={"hnsw:space": "cosine"}
                )
                self.collections[collection_id] = collection
                logger.info(f"Enabled and loaded collection '{collection_id}'")
            except Exception as e:
                logger.error(f"Failed to enable collection '{collection_id}': {e}", exc_info=True)
                return False
        elif not enabled and collection_id in self.collections:
            # Unload the collection
            del self.collections[collection_id]
            logger.info(f"Disabled collection '{collection_id}'")
        
        return True

    def reload_collections_for_mcp_server(self):
        """
        Reloads collections to match the current MCP server.
        Unloads collections from previous MCP server and loads collections for current server.
        Should be called when the MCP server changes.
        """
        current_mcp_server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID
        logger.info(f"Reloading RAG collections for MCP server ID: '{current_mcp_server_id}'")
        
        # Clear currently loaded collections
        self.collections.clear()
        
        # Ensure default collection exists (will create if MCP server is now set)
        self._ensure_default_collection()
        
        # Reload collections using the standard method
        self._load_active_collections()

        logger.info(f"Reload complete. {len(self.collections)} collection(s) now loaded for MCP server ID '{current_mcp_server_id}'")

    def refresh_vector_store(self, collection_id: Optional[int] = None):
        """
        Manually triggers the maintenance of the vector store.
        If collection_id is None, refreshes all collections.
        """
        if collection_id is not None:
            # Ensure collection_id is an integer
            if isinstance(collection_id, str):
                collection_id = int(collection_id)
            logger.info(f"Manual refresh of vector store triggered for collection: {collection_id}")
            self._maintain_vector_store(collection_id)
        else:
            logger.info("Manual refresh of all vector stores triggered.")
            for coll_id in self.collections:
                self._maintain_vector_store(coll_id)

    def _load_feedback_cache(self):
        """
        Load all feedback scores from case files into memory cache.
        Called at startup to build initial cache.
        """
        try:
            self.feedback_cache = {}
            
            for collection_id in self.collections.keys():
                collection_dir = self._get_collection_dir(collection_id)
                if not collection_dir.exists():
                    continue
                
                for case_file in collection_dir.glob('case_*.json'):
                    try:
                        with open(case_file, 'r', encoding='utf-8') as f:
                            case_data = json.load(f)
                        case_id = case_data.get('case_id', case_file.stem.replace('case_', ''))
                        feedback = case_data.get('metadata', {}).get('user_feedback_score', 0)
                        
                        # Store both formats in cache for compatibility
                        # ChromaDB returns case_id with "case_" prefix, filesystem ID without
                        self.feedback_cache[case_id] = feedback
                        self.feedback_cache[f'case_{case_id}'] = feedback
                    except Exception as e:
                        logger.debug(f"Error loading cache for {case_file}: {e}")
            
            pass  # Feedback cache loaded
        except Exception as e:
            logger.error(f"Error loading feedback cache: {e}")

    def get_feedback_score(self, case_id: str) -> int:
        """
        Get feedback score from cache.
        
        Args:
            case_id: The case ID to lookup
            
        Returns:
            Feedback score (1, 0, or -1), defaults to 0 if not found
        """
        return self.feedback_cache.get(case_id, 0)

    async def update_case_feedback(self, case_id: str, feedback_score: int) -> bool:
        """
        Update user feedback for a RAG case.
        Updates cache atomically with filesystem, then ChromaDB.
        
        Args:
            case_id: The case ID to update
            feedback_score: -1 (downvote), 0 (neutral), 1 (upvote)
            
        Returns:
            True if successful, False if case not found
        """
        import json
        
        # Find case file by searching all collection directories
        # Note: case_id may already have "case_" prefix, so normalize it
        normalized_case_id = case_id.replace("case_", "") if case_id.startswith("case_") else case_id

        case_file = None
        for collection_id in self.collections.keys():
            potential_file = self._get_collection_dir(collection_id) / f"case_{normalized_case_id}.json"
            if potential_file.exists():
                case_file = potential_file
                break
        
        if not case_file:
            logger.warning(f"Case file not found for case_id: {case_id}")
            return False
        
        try:
            # Update case study JSON
            with open(case_file, 'r', encoding='utf-8') as f:
                case_study = json.load(f)
            
            old_feedback = case_study["metadata"].get("user_feedback_score", 0)
            case_study["metadata"]["user_feedback_score"] = feedback_score
            
            # Save updated case study to filesystem (reliable source of truth)
            with open(case_file, 'w', encoding='utf-8') as f:
                json.dump(case_study, f, indent=2)
            
            logger.info(f"Updated case {case_id} feedback: {old_feedback} -> {feedback_score}")
            
            # Update cache immediately (used by get_collection_rows for instant consistency)
            # Store both formats since ChromaDB returns "case_" prefixed IDs
            self.feedback_cache[case_id] = feedback_score
            self.feedback_cache[f'case_{normalized_case_id}'] = feedback_score
            if not case_id.startswith("case_"):
                self.feedback_cache[f'case_{case_id}'] = feedback_score  # Also cache with prefix if original didn't have it
            logger.debug(f"Updated feedback cache for case {case_id}: {feedback_score}")

            # Update ChromaDB metadata in all collections that contain this case
            # ChromaDB stores IDs WITH the "case_" prefix
            chroma_case_id = f'case_{normalized_case_id}'
            for collection_id, collection in self.collections.items():
                try:
                    # Check if this case exists in this collection
                    existing = collection.get(ids=[chroma_case_id], include=["metadatas"])
                    
                    if existing and existing["ids"]:
                        # Update the metadata
                        metadata = existing["metadatas"][0]
                        metadata["user_feedback_score"] = feedback_score
                        
                        # If downvoted, demote from champion status
                        if feedback_score < 0:
                            metadata["is_most_efficient"] = False
                            logger.info(f"Case {case_id} downvoted - demoted from champion in collection {collection_id}")
                            
                            # Trigger re-evaluation to find new champion
                            await self._reevaluate_champion_for_query(
                                collection_id, 
                                metadata["user_query"]
                            )
                        
                        # Update full_case_data with new feedback
                        metadata["full_case_data"] = json.dumps(case_study)

                        collection.update(
                            ids=[chroma_case_id],  # Use normalized ID with "case_" prefix
                            metadatas=[metadata]
                        )
                        logger.debug(f"Updated ChromaDB metadata for case {case_id} in collection {collection_id}")
                        
                except Exception as e:
                    logger.error(f"Error updating case {case_id} in collection {collection_id}: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating case feedback: {e}", exc_info=True)
            return False

    async def _reevaluate_champion_for_query(self, collection_id: int, user_query: str):
        """
        Re-evaluates which case should be champion for a given query.
        Called when the current champion is downvoted.
        """
        if collection_id not in self.collections:
            return
        
        collection = self.collections[collection_id]
        
        try:
            # Get all cases for this query (excluding downvoted)
            all_cases = collection.get(
                where={"$and": [
                    {"user_query": {"$eq": user_query}},
                    {"user_feedback_score": {"$gte": 0}}  # Exclude downvoted
                ]},
                include=["metadatas"]
            )
            
            if not all_cases or not all_cases["ids"]:
                logger.info(f"No eligible cases remain for query '{user_query}' in collection {collection_id}")
                return
            
            # Find the best case using our priority logic
            best_case_id = None
            best_feedback = -999
            best_tokens = float('inf')
            
            for i, case_id in enumerate(all_cases["ids"]):
                meta = all_cases["metadatas"][i]
                feedback = meta.get("user_feedback_score", 0)
                tokens = meta.get("output_tokens", float('inf'))
                
                # Priority: feedback first, then tokens
                if feedback > best_feedback or (feedback == best_feedback and tokens < best_tokens):
                    best_case_id = case_id
                    best_feedback = feedback
                    best_tokens = tokens
            
            if best_case_id:
                # Demote all others, promote the best
                for i, case_id in enumerate(all_cases["ids"]):
                    meta = all_cases["metadatas"][i]
                    meta["is_most_efficient"] = (case_id == best_case_id)
                    collection.update(ids=[case_id], metadatas=[meta])
                
                logger.info(f"New champion for query '{user_query[:50]}...' in collection {collection_id}: {best_case_id} (feedback={best_feedback}, tokens={best_tokens})")
                
        except Exception as e:
            logger.error(f"Error re-evaluating champion: {e}", exc_info=True)

    def _maintain_vector_store(self, collection_id: int, user_id: Optional[str] = None):
        """
        Maintains the ChromaDB vector store for a specific collection by synchronizing it with the
        JSON case files on disk. It adds new cases, removes deleted ones,
        and updates existing ones if their metadata has changed.
        
        Args:
            collection_id: Collection ID to maintain
            user_id: User UUID (used to check ownership for subscribed collections)
            
        Note:
            Subscribed collections cannot be maintained by subscribers - only owners can
            modify the source collection. This preserves the reference-based model.
            
            Knowledge repositories are NOT maintained by this method - they use direct
            document upload to ChromaDB without JSON case files.
        """
        # Ensure collection_id is an integer
        if isinstance(collection_id, str):
            collection_id = int(collection_id)
            
        if collection_id not in self.collections:
            logger.warning(f"Cannot maintain vector store: collection '{collection_id}' not loaded")
            return
        
        # --- KNOWLEDGE REPOSITORIES: Skip maintenance (no JSON files, direct ChromaDB storage) ---
        coll_meta = self.get_collection_metadata(collection_id)
        if coll_meta and coll_meta.get("repository_type") == "knowledge":
            logger.info(f"Skipping maintenance for collection '{collection_id}': Knowledge repository (no file-based cases)")
            return
        # --- KNOWLEDGE REPOSITORIES END ---
        
        # --- MARKETPLACE PHASE 2: Skip maintenance for subscribed collections ---
        if user_id and self.is_subscribed_collection(collection_id, user_id):
            logger.info(f"Skipping maintenance for collection '{collection_id}': User '{user_id}' is a subscriber (not owner). Only owners can maintain collections.")
            return
        # --- MARKETPLACE PHASE 2 END ---
        
        collection = self.collections[collection_id]
        collection_dir = self._get_collection_dir(collection_id)

        # Skip maintenance if collection directory doesn't exist or has no JSON files
        # This handles imported collections that only exist in ChromaDB
        if not collection_dir.exists():
            logger.info(f"Skipping maintenance for collection '{collection_id}': Directory does not exist (likely imported)")
            return

        disk_case_files = list(collection_dir.glob("case_*.json"))
        if not disk_case_files:
            logger.info(f"Skipping maintenance for collection '{collection_id}': No JSON files found (likely imported or empty)")
            return

        # 1. Get current state from disk and DB
        disk_case_ids = {p.stem for p in disk_case_files}
        db_results = collection.get(include=["metadatas"])
        db_case_ids = set(db_results["ids"])
        db_metadatas = {db_results["ids"][i]: meta for i, meta in enumerate(db_results["metadatas"])}

        # 2. Identify cases to delete from DB
        ids_to_delete = list(db_case_ids - disk_case_ids)
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)

        # 3. Iterate through disk cases to add or update
        added_count = 0
        updated_count = 0
        for case_id_stem in disk_case_ids:
            case_file = collection_dir / f"{case_id_stem}.json"
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    case_data = json.load(f)
                
                # Prepare document and metadata for ChromaDB
                user_query = case_data.get("intent", {}).get("user_query", "")
                strategy_summary = self._summarize_strategy(case_data)
                
                if not user_query or not strategy_summary:
                    logger.warning(f"Skipping case {case_id_stem}: Missing user_query or strategy_summary.")
                    continue

                document_content = user_query
                
                # --- MODIFICATION START: Use new metadata helper ---
                metadata = self._prepare_chroma_metadata(case_data)
                # --- MODIFICATION END ---

                # Decide whether to add or update
                if case_id_stem not in db_case_ids:
                    # Add new case
                    collection.add(documents=[document_content], metadatas=[metadata], ids=[case_id_stem])
                    added_count += 1
                    logger.debug(f"Added new case {case_id_stem} to collection '{collection_id}'.")
                else:
                    # Check if update is needed by comparing the full content
                    existing_meta = db_metadatas.get(case_id_stem, {})
                    try:
                        existing_case_data = json.loads(existing_meta.get("full_case_data", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        existing_case_data = {}

                    # If the file on disk is different from what's in the DB, update.
                    if case_data != existing_case_data:
                        collection.update(
                            ids=[case_id_stem],
                            metadatas=[metadata],
                            documents=[document_content] # Ensure embedding is updated too
                        )
                        updated_count += 1

            except Exception as e:
                logger.error(f"Failed to process RAG case file {case_file.name}: {e}", exc_info=True)
        
        logger.debug(f"Vector store maintenance for '{collection_id}': +{added_count} ={updated_count} -{len(ids_to_delete)}")

    def _summarize_strategy(self, case_data: Dict[str, Any]) -> str:
        """
        Creates a concise string summary of a strategy from the case data.
        """
        if "successful_strategy" in case_data:
            strategy = case_data["successful_strategy"]
            phase_summaries = []
            for phase in strategy.get("phases", []):
                goal = phase.get("goal", "No goal specified.")
                # --- MODIFICATION START: Handle relevant_tools list ---
                tool = (phase.get("relevant_tools") or ["No tool specified."])[0]
                # --- MODIFICATION END ---
                phase_summaries.append(f"Phase {phase.get('phase', 'N/A')}: Goal '{goal}', Tool '{tool}'")
            return " -> ".join(phase_summaries)
        elif "failed_strategy" in case_data:
            return f"Failed with error: {case_data['failed_strategy'].get('error_summary', 'details unavailable.')}"
        elif "conversational_response" in case_data:
            return case_data["conversational_response"].get("summary", "Conversational response.")
        return "Strategy details unavailable."

    def retrieve_examples(self, query: str, k: int = 1, min_score: float = 0.7, allowed_collection_ids: set = None, 
                         rag_context: Optional['RAGAccessContext'] = None, repository_type: str = "planner") -> List[Dict[str, Any]]:
        """
        Retrieves the top-k most relevant and efficient RAG cases based on the query.
        Queries all active collections and aggregates results by similarity score.
        
        Args:
            query: Search query text
            k: Number of examples to retrieve
            min_score: Minimum similarity score threshold
            allowed_collection_ids: Optional set of collection IDs to filter by (for profile-based filtering)
            rag_context: Optional RAGAccessContext for user-aware filtering. If provided, only retrieves from accessible collections.
            repository_type: Type of repository to retrieve from - "planner" or "knowledge" (default: "planner")
                           --- MODIFICATION: Added repository_type parameter for knowledge repository support ---
        """
        logger.info(f"Retrieving top {k} RAG examples for query: '{query}' (repository_type: {repository_type}, min_score: {min_score}, allowed_collections: {allowed_collection_ids})")
        
        if not self.collections:
            logger.warning("No active collections to retrieve examples from")
            return []
        
        # --- MODIFICATION START: Apply rag_context to filter accessible collections ---
        # If rag_context is provided, only query user-accessible collections
        if rag_context:
            accessible = rag_context.accessible_collections
            if allowed_collection_ids:
                # Intersect context-accessible with profile-allowed
                effective_allowed = accessible & allowed_collection_ids
            else:
                effective_allowed = accessible
            logger.debug(f"RAG context applied: user {rag_context.user_id} can access {len(effective_allowed)} collections")
        else:
            effective_allowed = allowed_collection_ids
        # --- MODIFICATION END ---
        
        # --- MODIFICATION START: Query all active collections with optional filtering ---
        all_candidate_cases = []
        
        logger.info(f"RAG retriever has {len(self.collections)} loaded collections: {list(self.collections.keys())}")
        logger.info(f"Effective allowed collections: {effective_allowed}")
        
        for collection_id, collection in self.collections.items():
            # Skip collections not in the allowed set (if filtering is active)
            if effective_allowed is not None and collection_id not in effective_allowed:
                logger.info(f"Skipping collection '{collection_id}' - not accessible to user or not in profile filter")
                continue
            
            # --- MODIFICATION START: Filter by repository_type ---
            coll_meta = self.get_collection_metadata(collection_id)
            if coll_meta:
                coll_repo_type = coll_meta.get("repository_type", "planner")  # Default to planner for backward compatibility
                if coll_repo_type != repository_type:
                    logger.debug(f"Skipping collection '{collection_id}' - repository_type '{coll_repo_type}' does not match requested '{repository_type}'")
                    continue
            # --- MODIFICATION END ---
            
            try:
                # --- MODIFICATION: Use context-aware query builder ---
                # Knowledge repositories have different metadata schema than planner repositories
                if repository_type == "knowledge":
                    # Knowledge documents don't have strategy_type, is_most_efficient, etc.
                    # They should have document_id, collection_id, chunk metadata
                    where_filter = None  # No filtering needed for knowledge documents
                elif rag_context:
                    # Allow cases that are EITHER efficient OR explicitly upvoted
                    # This ensures "better suited" plans (which users liked) aren't hidden by "lazier" plans (fewer tokens)
                    efficiency_filter = {
                        "$or": [
                            {"is_most_efficient": {"$eq": True}},
                            {"user_feedback_score": {"$gt": 0}}
                        ]
                    }
                    
                    where_filter = rag_context.build_query_filter(
                        collection_id=collection_id,
                        extra_filter=efficiency_filter,
                        strategy_type={"$eq": "successful"},
                        user_feedback_score={"$gte": 0}
                    )
                else:
                    # Fallback logic without context
                    where_filter = {"$and": [
                        {"strategy_type": {"$eq": "successful"}},
                        {"user_feedback_score": {"$gte": 0}},
                        {"$or": [
                            {"is_most_efficient": {"$eq": True}},
                            {"user_feedback_score": {"$gt": 0}}
                        ]}
                    ]}
                
                # Log collection state before query
                try:
                    coll_count = collection.count()
                    logger.info(f"Collection '{collection_id}' has {coll_count} documents before query")
                except Exception as e:
                    logger.warning(f"Could not get count for collection '{collection_id}': {e}")
                
                logger.info(f"Querying collection '{collection_id}' with where_filter={where_filter}, n_results={k * 10}")
                
                query_results = collection.query(
                    query_texts=[query],
                    n_results=k * 10,  # Retrieve more candidates to filter
                    where=where_filter,
                    include=["metadatas", "distances", "documents"]
                )
                # --- MODIFICATION END ---
                
                logger.info(f"Collection '{collection_id}' returned {len(query_results['ids'][0])} raw results")
                
                for i in range(len(query_results["ids"][0])):
                    case_id = query_results["ids"][0][i]
                    metadata = query_results["metadatas"][0][i]
                    distance = query_results["distances"][0][i]
                    
                    similarity_score = 1 - distance 

                    if similarity_score < min_score:
                        logger.info(f"Skipping case {case_id} from collection '{collection_id}' due to low similarity score: {similarity_score:.3f} < {min_score}")
                        continue
                    
                    # Handle different metadata structures for knowledge vs planner repositories
                    if repository_type == "knowledge":
                        # Knowledge documents have chunk text directly, not full_case_data
                        chunk_text = query_results["documents"][0][i] if "documents" in query_results else ""
                        full_case_data = {
                            "content": chunk_text,
                            "metadata": metadata
                        }
                    else:
                        # Planner repositories have full_case_data as JSON
                        full_case_data = json.loads(metadata["full_case_data"])
                    
                    # --- MODIFICATION START: Add enhanced metadata for knowledge repositories ---
                    if repository_type == "knowledge":
                        # Knowledge documents have different structure
                        candidate = {
                            "case_id": case_id,
                            "collection_id": collection_id,
                            "user_query": query,  # The search query
                            "content": full_case_data.get("content", ""),
                            "full_case_data": full_case_data,
                            "similarity_score": similarity_score,
                            "document_id": metadata.get("document_id", case_id),
                            "chunk_index": metadata.get("chunk_index", 0),
                            "strategy_type": "knowledge",  # Mark as knowledge document
                            "is_most_efficient": True,  # Not applicable for knowledge
                            "had_plan_improvements": False,
                            "had_tactical_improvements": False
                        }
                    else:
                        # Planner repositories have standard structure
                        candidate = {
                            "case_id": case_id,
                            "collection_id": collection_id,
                            "user_query": metadata["user_query"],
                            "strategy_type": metadata.get("strategy_type", "unknown"),
                            "full_case_data": full_case_data,
                            "similarity_score": similarity_score,
                            "is_most_efficient": metadata.get("is_most_efficient"),
                            "had_plan_improvements": full_case_data.get("metadata", {}).get("had_plan_improvements", False),
                            "had_tactical_improvements": full_case_data.get("metadata", {}).get("had_tactical_improvements", False),
                            "document_id": case_id
                        }
                    
                    # Add collection metadata for knowledge repositories
                    if coll_meta:
                        candidate["collection_name"] = coll_meta.get("name")
                        candidate["repository_type"] = coll_meta.get("repository_type", "planner")
                    
                    all_candidate_cases.append(candidate)
                    # --- MODIFICATION END ---
            except Exception as e:
                logger.error(f"Error querying collection '{collection_id}': {e}", exc_info=True)
        
        if not all_candidate_cases:
            logger.info("No candidate cases found across all collections")
            return []
        # --- MODIFICATION END ---
        
        # Calculate Adjusted Score to balance Relevance vs. Cleanliness
        # Instead of hard buckets (which hide highly relevant cases if they have corrections),
        # we apply a small penalty to the similarity score for corrections.
        # This ensures a 95% match with corrections still beats a 70% clean match,
        # but a 90% clean match beats a 92% match with corrections.
        
        PENALTY_TACTICAL = 0.05  # 5% penalty for tactical corrections
        PENALTY_PLAN = 0.05      # 5% penalty for plan corrections
        
        for case in all_candidate_cases:
            penalty = 0.0
            if case["had_tactical_improvements"]:
                penalty += PENALTY_TACTICAL
            if case["had_plan_improvements"]:
                penalty += PENALTY_PLAN
            
            case["adjusted_score"] = case["similarity_score"] - penalty

        # Sort by Adjusted Score descending
        all_candidate_cases.sort(key=lambda x: x["adjusted_score"], reverse=True)
        
        final_candidates = all_candidate_cases
        logger.debug(f"Returning top {k} candidates sorted by adjusted score (Relevance - Cleanliness Penalty).")

        # Enrich with collection metadata
        for case in final_candidates[:k]:
            coll_id = case.get("collection_id")
            if coll_id:
                coll_meta = self.get_collection_metadata(coll_id)
                if coll_meta:
                    case["collection_name"] = coll_meta.get("name")
                    case["collection_mcp_server_id"] = coll_meta.get("mcp_server_id")

        return final_candidates[:k]

    def _format_few_shot_example(self, case: Dict[str, Any]) -> str:
        """
        Formats a retrieved RAG case into a string suitable for the prompt.
        """
        user_query = case["user_query"]
        case_id = case["case_id"]
        
        strategy_type = case.get("strategy_type", "unknown")
        plan_content = ""
        thought_process_summary = ""

        if strategy_type == "successful":
            plan_json = "[]"
            if case["full_case_data"].get("successful_strategy", {}).get("phases"):
                plan_json = json.dumps(case["full_case_data"]["successful_strategy"]["phases"], indent=2)
            plan_content = f"- **Correct Plan**:\n```json\n{plan_json}\n```"
            thought_process_summary = f"RAG case `{case_id}` shows a proven strategy pattern for this query type."
        elif strategy_type == "failed":
            error_summary = case["full_case_data"].get("failed_strategy", {}).get("error_summary", "an unspecified error.")
            plan_content = f"- **Failed Action**: {json.dumps(case['full_case_data'].get('failed_strategy', {}).get('failed_action', {}), indent=2)}"
            thought_process_summary = f"Retrieved RAG case `{case_id}` shows a past failure with error: {error_summary}. This helps in avoiding similar pitfalls."
        elif strategy_type == "conversational":
            conversation_summary = case["full_case_data"].get("conversational_response", {}).get("summary", "a conversational response.")
            plan_content = f"- **Conversational Response**: {conversation_summary}"
            thought_process_summary = f"Retrieved RAG case `{case_id}` indicates a conversational interaction: {conversation_summary}."
        else:
            thought_process_summary = f"Retrieved RAG case `{case_id}` with unknown strategy type."

        formatted_example = f"""### RAG Example (Case ID: {case_id})
- **User Goal**: "{user_query}"
- **Thought Process**:
  1. The user's request is similar to a past interaction.
  2. {thought_process_summary}
{plan_content}"""
        return formatted_example

    # --- MODIFICATION START: Add real-time processing methods ---
    
    def _extract_case_from_turn_summary(self, turn_summary: dict, collection_id: Optional[int] = None) -> dict | None:
        """
        Core logic to transform a raw turn_summary log into a clean Case Study.
        Adapted from rag_miner.py's _extract_case_study.
        
        Args:
            turn_summary: The turn data to process
            collection_id: The collection this case will belong to (defaults to 0)
        """
        try:
            turn = turn_summary
            # Note: We rely on PlanExecutor to add session_id to the turn_summary
            session_id = turn.get("session_id")
            turn_id = turn.get("turn")

            if not session_id:
                logger.error(f"  -> Skipping turn {turn_id}: 'session_id' is missing from turn_summary.")
                return None
            if not turn_id:
                logger.error(f"  -> Skipping turn: 'turn' number is missing from turn_summary.")
                return None

            case_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{session_id}_{turn_id}"))
            trace = turn.get("execution_trace", [])

            for entry in trace:
                if not isinstance(entry, dict):
                    continue
                action = entry.get("action", {})
                if isinstance(action, dict) and action.get("tool_name") == "TDA_ContextReport":
                    logger.info(f"  -> Skipping turn {turn.get('turn')} due to TDA_ContextReport usage.")
                    return None
            
            # --- MODIFICATION START: Stricter success checking ---
            original_plan = turn.get("original_plan")
            if not original_plan or not isinstance(original_plan, list):
                logger.info(f"  -> Skipping turn {turn.get('turn')}: 'original_plan' is missing or not a list.")
                return None

            required_phases = {p.get("phase") for p in original_plan if isinstance(p, dict) and p.get("phase") is not None}
            if not required_phases:
                logger.info(f"  -> Skipping turn {turn.get('turn')}: 'original_plan' has no valid phases.")
                return None
            
            completed_phases = set()
            has_critical_error = False
            first_error_action = None
            successful_actions_map = {}
            had_plan_improvements = False
            had_tactical_improvements = False
            has_orchestration = False  # Track if System Orchestration occurred
            # --- MODIFICATION END ---

            for entry in trace:
                if not isinstance(entry, dict): continue
                action = entry.get("action", {})
                result = entry.get("result", {})
                action_is_dict = isinstance(action, dict)
                result_is_dict = isinstance(result, dict)

                if action_is_dict:
                    action_args = action.get("arguments", {})
                    action_meta = action.get("metadata", {})
                    tool_name = action.get("tool_name", "")
                    # --- MODIFICATION START: Check for unrecoverable errors ---
                    if (tool_name == "TDA_SystemLog" and 
                        isinstance(action_args, dict) and 
                        action_args.get("message") == "Unrecoverable Error"):
                        has_critical_error = True
                    # --- MODIFICATION END ---
                    if isinstance(action_meta, dict) and action_meta.get("type") == "workaround": had_tactical_improvements = True
                    if tool_name == "TDA_SystemLog" and isinstance(action_args, dict) and action_args.get("message") == "System Correction":
                        if "Planner" in action_args.get("details", {}).get("summary", ""): had_plan_improvements = True
                
                # --- MODIFICATION START: Stricter error tracking ---
                if result_is_dict and result.get("status") == "error":
                    has_critical_error = True
                    if not first_error_action:
                        first_error_action = action
                # --- MODIFICATION END ---
                
                # --- MODIFICATION START: Accept results without explicit "success" status ---
                # Some tools (like TDA_Charting) return data directly without a status field
                # Consider them successful if they're not explicitly marked as errors
                is_successful_result = (
                    result_is_dict and 
                    (result.get("status") == "success" or 
                     (result.get("status") is None and "error" not in str(result).lower()))
                )
                
                if is_successful_result and action_is_dict:
                    tool_name = action.get("tool_name")
                    
                    # --- MODIFICATION START: Detect System Orchestration ---
                    if tool_name == "TDA_SystemOrchestration":
                        has_orchestration = True
                        phase_num = action.get("metadata", {}).get("phase_number")
                        if phase_num is not None:
                            completed_phases.add(phase_num)
                    # --- MODIFICATION END ---
                    
                    if tool_name and tool_name != "TDA_SystemLog":
                        # --- MODIFICATION START: Use phase_number (can be None) ---
                        phase_num = action.get("metadata", {}).get("phase_number")
                        if phase_num is not None:
                            completed_phases.add(phase_num)
                        # --- MODIFICATION END ---
                            
                            original_phase = None
                            # --- MODIFICATION START: Use original_plan variable ---
                            if original_plan:
                                for p in original_plan:
                            # --- MODIFICATION END ---
                                    if isinstance(p, dict) and p.get("phase") == phase_num:
                                        original_phase = p
                                        break
                            
                            if original_phase:
                                compliant_phase = {
                                    "phase": phase_num,
                                    "goal": original_phase.get("goal", "Execute tool."),
                                    "relevant_tools": [tool_name]
                                }
                                if "type" in original_phase:
                                    compliant_phase["type"] = original_phase["type"]
                                if "loop_over" in original_phase:
                                    compliant_phase["loop_over"] = original_phase["loop_over"]
                                
                                # --- MODIFICATION START: Get arguments from the original plan, not the resolved action ---
                                # This saves the strategic placeholders (e.g., {"source": "result_of_phase_1"})
                                # instead of the raw data.
                                compliant_phase["arguments"] = original_phase.get("arguments", {})
                                # --- MODIFICATION END ---
                                
                                successful_actions_map[phase_num] = compliant_phase
                            else:
                                successful_actions_map[phase_num] = {
                                    "phase": phase_num, 
                                    "goal": "Goal not found in original plan.",
                                    "relevant_tools": [tool_name], 
                                    "arguments": action.get("arguments", {})
                                }
            
            # --- MODIFICATION START: Apply success criteria with orchestration awareness ---
            # Normal execution: required_phases == completed_phases
            # Orchestrated execution: Allow subset match if orchestration occurred and has successful actions
            #   System Orchestration can intelligently optimize/merge phases at runtime
            if has_orchestration:
                phase_match = (len(completed_phases) > 0 and 
                              completed_phases.issubset(required_phases) and 
                              len(successful_actions_map) > 0)
            else:
                phase_match = (required_phases == completed_phases)
            
            is_success = (not has_critical_error) and phase_match
            if not is_success:
                logger.info(f"  -> Skipping turn {turn.get('turn')} - NOT successful. "
                             f"HasError: {has_critical_error}, "
                             f"HasOrchestration: {has_orchestration}, "
                             f"Required phases: {required_phases}, "
                             f"Completed phases: {completed_phases}, "
                             f"Successful actions: {len(successful_actions_map)}")
                return None
            # --- MODIFICATION END ---

            # --- MODIFICATION START: Convert feedback string to score ---
            feedback_str = turn.get("feedback")
            if feedback_str == "up":
                user_feedback_score = 1
            elif feedback_str == "down":
                user_feedback_score = -1
            else:
                user_feedback_score = 0  # Default: no feedback yet
            # --- MODIFICATION END ---

            case_study = {
                "case_id": case_id,
                "metadata": {
                    "session_id": session_id, "turn_id": turn.get("turn"), "is_success": is_success,
                    # --- MODIFICATION START: Add task_id, collection_id, and orchestration flag ---
                    "task_id": turn.get("task_id"),
                    "collection_id": collection_id if collection_id is not None else 0,
                    "has_orchestration": has_orchestration,  # Flag for System Orchestration usage
                    # --- MODIFICATION END ---
                    "had_plan_improvements": had_plan_improvements, "had_tactical_improvements": had_tactical_improvements,
                    "timestamp": turn.get("timestamp"),
                    "user_feedback_score": user_feedback_score,  # Derived from turn.feedback (-1=downvote, 0=neutral, 1=upvote)
                    "llm_config": {
                        "provider": turn.get("provider"), "model": turn.get("model"),
                        "profile_tag": turn.get("profile_tag"),  # Add profile tag
                        "input_tokens": turn.get("turn_input_tokens", 0), "output_tokens": turn.get("turn_output_tokens", 0)
                    },
                },
                "intent": {"user_query": turn.get("user_query")}
            }

            if not case_study["intent"]["user_query"]:
                logger.warning(f"  -> Skipping turn {turn.get('turn')}: 'user_query' is missing or empty.")
                return None

            # --- MODIFICATION START: Use is_success flag to build strategy ---
            if is_success:
                case_study["metadata"]["is_most_efficient"] = False # Default
                case_study["successful_strategy"] = {"phases": []}
                for phase_num in sorted(successful_actions_map.keys()):
                    action_info = successful_actions_map[phase_num]
                    case_study["successful_strategy"]["phases"].append(action_info)
                
                steps_per_phase = {}
                total_steps = 0
                for entry in trace:
                    if not isinstance(entry, dict): continue
                    action = entry.get("action", {})
                    if not isinstance(action, dict): continue
                    if action.get("tool_name") and action.get("tool_name") != "TDA_SystemLog":
                        phase_num = str(action.get("metadata", {}).get("phase_number", "N/A"))
                        steps_per_phase[phase_num] = steps_per_phase.get(phase_num, 0) + 1
                        total_steps += 1
                case_study["metadata"]["strategy_metrics"] = {"phase_count": len(turn.get("original_plan", [])), "steps_per_phase": steps_per_phase, "total_steps": total_steps}
                return case_study  # Return successful strategy
            elif first_error_action:
                case_study["failed_strategy"] = {"original_plan": turn.get("original_plan"), "error_summary": turn.get("final_summary", ""), "failed_action": first_error_action}
                return case_study  # Return failed strategy for analysis
            else:
                # Conversational response - skip RAG processing
                logger.debug(f"  -> Skipping turn {turn.get('turn')}: Conversational response (no strategic value for RAG).")
                return None
            # --- MODIFICATION END ---
        except Exception as e:
            logger.error(f"  -> CRITICAL: An unexpected error occurred during case extraction for turn {turn.get('turn')}: {e}", exc_info=True)
            return None

    def _prepare_chroma_metadata(self, case_study: dict) -> dict:
        """Prepares the metadata dictionary for upserting into ChromaDB."""
        # Metadata for ChromaDB *must* be flat (str, int, float, bool).
        # ChromaDB does NOT accept None values - filter them out or convert to valid types.
        
        strategy_type = "unknown"
        if "successful_strategy" in case_study:
            strategy_type = "successful"
        elif "failed_strategy" in case_study:
            strategy_type = "failed"
        elif "conversational_response" in case_study:
            strategy_type = "conversational"

        metadata = {
            "case_id": case_study["case_id"],
            "user_uuid": case_study["metadata"].get("user_uuid") or "",  # --- MODIFICATION: Add user_uuid for multi-user support ---
            "user_query": case_study["intent"]["user_query"],
            "strategy_type": strategy_type,
            "timestamp": case_study["metadata"]["timestamp"],
            "task_id": case_study["metadata"].get("task_id") or "",  # Convert None to empty string
            "collection_id": case_study["metadata"].get("collection_id", 0),
            "is_success": case_study["metadata"].get("is_success", False),  # --- MODIFICATION: Add success flag ---
            "is_most_efficient": case_study["metadata"].get("is_most_efficient", False),
            "had_plan_improvements": case_study["metadata"].get("had_plan_improvements", False),
            "had_tactical_improvements": case_study["metadata"].get("had_tactical_improvements", False),
            "has_orchestration": case_study["metadata"].get("has_orchestration", False),  # --- MODIFICATION: Add orchestration flag ---
            "output_tokens": case_study["metadata"].get("llm_config", {}).get("output_tokens", 0),
            "user_feedback_score": case_study["metadata"].get("user_feedback_score", 0),
            # Store the full case data as a JSON string
            "full_case_data": json.dumps(case_study)
        }
        
        # Safety check: Remove any remaining None values (shouldn't happen, but just in case)
        metadata = {k: v for k, v in metadata.items() if v is not None}
        
        return metadata

    async def process_turn_for_rag(self, turn_summary: dict, collection_id: Optional[int] = None,
                                  rag_context: Optional['RAGAccessContext'] = None):
        """
        The main "consumer" method. It processes a single turn summary,
        determines its efficiency, and transactionally updates the vector store.
        If collection_id is not specified, uses the default collection (ID 0).
        
        Args:
            turn_summary: The turn data to process.
            collection_id: The collection this case belongs to.
            rag_context: Optional RAGAccessContext for access control. If provided, validates access.
        
        --- MODIFICATION: Added rag_context parameter for multi-user support ---
        """
        try:
            # --- MODIFICATION START: Extract user_uuid first ---
            # Extract user_uuid from turn_summary or rag_context
            user_uuid = turn_summary.get("user_uuid")
            
            if rag_context:
                user_uuid = rag_context.user_id  # Use context's user_id as authoritative
            
            if not user_uuid:
                logger.warning("Skipping RAG processing: user_uuid not found in turn_summary or rag_context.")
                return
            
            # 1. Determine which collection to use BEFORE validating access
            if collection_id is None:
                # Get user's default collection instead of hardcoding 0
                collection_id = self._get_user_default_collection_id(user_uuid)
                if collection_id is None:
                    logger.warning(f"No default collection found for user {user_uuid}. Skipping RAG processing.")
                    return
                logger.info(f"Using user's default collection {collection_id} for RAG case storage")
            
            # 2. NOW validate user has write access to the determined collection
            if rag_context:
                if not rag_context.validate_collection_access(collection_id, write=True):
                    logger.error(f"User {user_uuid} cannot write to collection {collection_id}. Skipping RAG processing.")
                    return
            
            # 3. Extract & Filter (pass collection_id so it's stored in case metadata)
            case_study = self._extract_case_from_turn_summary(turn_summary, collection_id)
            
            if not case_study or "successful_strategy" not in case_study:
                logger.debug("Skipping RAG processing: Turn was not a successful strategy.")
                return
            
            # --- MODIFICATION: Store user_uuid in case metadata ---
            case_study["metadata"]["user_uuid"] = user_uuid
            # --- MODIFICATION END ---

            # 4. Verify collection is active

            if collection_id not in self.collections:
                logger.warning(f"Collection '{collection_id}' not found or not active. Skipping RAG processing.")
                return
            
            collection = self.collections[collection_id]

            # 5. Get new case data
            new_case_id = case_study["case_id"]
            new_query = case_study["intent"]["user_query"]
            new_tokens = case_study["metadata"].get("llm_config", {}).get("output_tokens", 0)
            new_document = new_query # The document we embed is the user query
            
            logger.info(f"Processing RAG case {new_case_id} for collection '{collection_id}', query: '{new_query[:50]}...' (Tokens: {new_tokens})")

            # 4. Query ChromaDB for existing "most efficient" in this collection
            # --- MODIFICATION: Use rag_context to build query filter with user isolation ---
            if rag_context:
                where_filter = rag_context.build_query_filter(
                    collection_id=collection_id,
                    user_query={"$eq": new_query},
                    is_most_efficient={"$eq": True}
                )
            else:
                # Fallback: use user_uuid for filtering if no context provided
                where_filter = {"$and": [
                    {"user_query": {"$eq": new_query}},
                    {"user_uuid": {"$eq": user_uuid}},
                    {"is_most_efficient": {"$eq": True}}
                ]}
            
            existing_cases = collection.get(
                where=where_filter,
                include=["metadatas"]
            )
            # --- MODIFICATION END ---

            old_best_case_id = None
            old_best_case_tokens = float('inf')
            old_best_case_feedback = 0
            new_feedback = case_study["metadata"].get("user_feedback_score", 0)

            if existing_cases and existing_cases["ids"]:
                old_best_case_id = existing_cases["ids"][0]
                old_best_case_tokens = existing_cases["metadatas"][0].get("output_tokens", float('inf'))
                old_best_case_feedback = existing_cases["metadatas"][0].get("user_feedback_score", 0)

            # 5. Compare & Decide (Feedback score takes priority over token efficiency)
            id_to_demote = None
            
            # Downvoted cases never become champion
            if new_feedback < 0:
                logger.info(f"New case {new_case_id} is downvoted (feedback={new_feedback}). Not eligible for champion.")
                case_study["metadata"]["is_most_efficient"] = False
            # Old champion is downvoted, new case wins by default (if not also downvoted)
            elif old_best_case_feedback < 0:
                logger.info(f"Old case {old_best_case_id} is downvoted. New case {new_case_id} becomes champion.")
                case_study["metadata"]["is_most_efficient"] = True
                id_to_demote = old_best_case_id
            # Compare feedback scores first
            elif new_feedback != old_best_case_feedback:
                if new_feedback > old_best_case_feedback:
                    logger.info(f"New case {new_case_id} has better feedback ({new_feedback}) than old case {old_best_case_id} ({old_best_case_feedback}). New case wins.")
                    case_study["metadata"]["is_most_efficient"] = True
                    id_to_demote = old_best_case_id
                else:
                    logger.info(f"Old case {old_best_case_id} has better feedback ({old_best_case_feedback}) than new case {new_case_id} ({new_feedback}). Old case wins.")
                    case_study["metadata"]["is_most_efficient"] = False
            # Same feedback level - use token efficiency as tiebreaker
            else:
                if new_tokens < old_best_case_tokens:
                    logger.info(f"New case {new_case_id} is MORE efficient ({new_tokens} tokens) than old case {old_best_case_id} ({old_best_case_tokens} tokens). Same feedback level ({new_feedback}).")
                    case_study["metadata"]["is_most_efficient"] = True
                    id_to_demote = old_best_case_id
                else:
                    logger.info(f"New case {new_case_id} ({new_tokens} tokens) is NOT more efficient than old case {old_best_case_id} ({old_best_case_tokens} tokens). Same feedback level ({new_feedback}).")
                    case_study["metadata"]["is_most_efficient"] = False
            
            new_metadata = self._prepare_chroma_metadata(case_study)

            # 6. Transact with ChromaDB
            # Step 6a: Upsert the new case
            # Ensure ChromaDB ID has "case_" prefix for consistency with filesystem
            chroma_id = f"case_{new_case_id}" if not new_case_id.startswith("case_") else new_case_id
            collection.upsert(
                ids=[chroma_id],
                documents=[new_document],
                metadatas=[new_metadata]
            )
            logger.debug(f"Upserted new case {chroma_id} to collection '{collection_id}' with is_most_efficient={new_metadata['is_most_efficient']}.")

            # Step 6b: Demote the old case if necessary
            if id_to_demote:
                logger.info(f"Demoting old best case: {id_to_demote}")
                # We must fetch the *full metadata* for the old case to update it
                old_case_meta_result = collection.get(ids=[id_to_demote], include=["metadatas"])
                if old_case_meta_result["metadatas"]:
                    meta_to_update = old_case_meta_result["metadatas"][0]
                    meta_to_update["is_most_efficient"] = False
                    collection.update(
                        ids=[id_to_demote],
                        metadatas=[meta_to_update]
                    )
                    logger.info(f"Successfully demoted old case {id_to_demote} in ChromaDB.")

                    # Also update the JSON file on disk
                    # Normalize ID: remove "case_" prefix if present, then add it back for filename
                    normalized_id = id_to_demote.replace("case_", "") if id_to_demote.startswith("case_") else id_to_demote
                    old_case_file = self._get_collection_dir(collection_id) / f"case_{normalized_id}.json"
                    if old_case_file.exists():
                        try:
                            with open(old_case_file, 'r', encoding='utf-8') as f:
                                old_case_data = json.load(f)
                            old_case_data["metadata"]["is_most_efficient"] = False
                            with open(old_case_file, 'w', encoding='utf-8') as f:
                                json.dump(old_case_data, f, indent=2)
                            logger.debug(f"Updated JSON file for demoted case {id_to_demote}")
                        except Exception as e:
                            logger.warning(f"Failed to update JSON file for demoted case {id_to_demote}: {e}")
                    else:
                        logger.debug(f"JSON file not found for old case {id_to_demote} (might not be persisted yet)")
                else:
                    logger.warning(f"Could not find old case {id_to_demote} to demote it.")
            
            # 7. Save the case study JSON to disk in collection directory
            # Ensure the collection directory exists before writing
            collection_dir = self._ensure_collection_dir(collection_id)
            output_path = collection_dir / f"case_{new_case_id}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(case_study, f, indent=2)
            logger.debug(f"Saved case study JSON to disk: {output_path}")
            
            # Return the case_id so it can be stored in the session
            return new_case_id

        except Exception as e:
            logger.error(f"Error during real-time RAG processing: {e}", exc_info=True)
            return None


# Example Usage (for testing purposes)
if __name__ == "__main__":
    # Assuming tda_rag_cases is in the parent directory of this script
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent.parent # uderia
    rag_cases_dir = project_root / "rag" / "tda_rag_cases"
    persist_dir = project_root / ".chromadb_rag_cache" # Persistent storage for ChromaDB

    # Configure logging for main execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.setLevel(logging.DEBUG) # Set RAG retriever logger to DEBUG for detailed output

    try:
        retriever = RAGRetriever(rag_cases_dir=rag_cases_dir, persist_directory=persist_dir)
        
        test_query = "educate yourself on the ddls of the fitness_db database"
        few_shot_examples = retriever.retrieve_examples(test_query, k=1)

        if few_shot_examples:
            print(f"\n--- Retrieved Few-Shot Examples for '{test_query}' ---\n")
            for example in few_shot_examples:
                print(retriever._format_few_shot_example(example))
        else:
            print(f"\nNo RAG examples found for '{test_query}'.")

        test_query_2 = "what is the quality of table 'online' in database 'DEMO_Customer360_db'?"
        few_shot_examples_2 = retriever.retrieve_examples(test_query_2, k=1)

        if few_shot_examples_2:
            print(f"\n--- Retrieved Few-Shot Examples for '{test_query_2}' ---\n")
            for example in few_shot_examples_2:
                print(retriever._format_few_shot_example(example))
        else:
            print(f"\nNo RAG examples found for '{test_query_2}'.")

    except Exception as e:
        logger.error(f"An error occurred during RAGRetriever example usage: {e}", exc_info=True)