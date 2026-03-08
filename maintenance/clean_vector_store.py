#!/usr/bin/env python3
"""
Cleans up the ChromaDB vector store by removing entries for deleted orphan cases.
This syncs the vector store with the case files on disk.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

import chromadb
from chromadb.utils import embedding_functions
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_vector_store():
    """Clean up vector store by syncing with disk case files."""
    
    # Set up paths
    rag_cases_dir = project_root / "rag" / "tda_rag_cases"
    persist_dir = project_root / ".chromadb_rag_cache"
    
    if not persist_dir.exists():
        logger.info("No ChromaDB cache found. Nothing to clean.")
        return
    
    logger.info("=" * 80)
    logger.info("CHROMADB VECTOR STORE CLEANUP")
    logger.info("=" * 80)
    logger.info("")
    
    # Initialize ChromaDB client
    logger.info(f"Connecting to ChromaDB at: {persist_dir}")
    client = chromadb.PersistentClient(path=str(persist_dir))
    
    # Get all collections
    collections_list = client.list_collections()
    logger.info(f"Found {len(collections_list)} collections")
    logger.info("")
    
    total_deleted = 0
    
    for collection_info in collections_list:
        collection_name = collection_info.name
        
        # Extract collection ID from name (e.g., "tda_rag_coll_0" -> 0)
        if not collection_name.startswith("tda_rag_coll_"):
            logger.info(f"Skipping non-RAG collection: {collection_name}")
            continue
        
        try:
            collection_id = int(collection_name.split("_")[-1])
        except ValueError:
            logger.warning(f"Could not parse collection ID from: {collection_name}")
            continue
        
        collection_dir = rag_cases_dir / f"collection_{collection_id}"
        
        logger.info(f"Processing collection '{collection_id}' ({collection_name})...")
        logger.info(f"  Collection directory: {collection_dir}")
        
        if not collection_dir.exists():
            logger.warning(f"  Collection directory not found on disk!")
            continue
        
        # Get collection
        collection = client.get_collection(name=collection_name)
        
        # Get all IDs in ChromaDB
        db_results = collection.get(include=["metadatas"])
        db_case_ids = set(db_results["ids"])
        logger.info(f"  Cases in ChromaDB: {len(db_case_ids)}")
        
        # Get all case files on disk
        disk_case_ids = {p.stem for p in collection_dir.glob("case_*.json")}
        logger.info(f"  Cases on disk: {len(disk_case_ids)}")
        
        # Identify stale cases (in DB but not on disk)
        ids_to_delete = list(db_case_ids - disk_case_ids)
        
        if ids_to_delete:
            logger.info(f"  Found {len(ids_to_delete)} orphan entries to remove")
            logger.info(f"  Deleting orphan entries...")
            collection.delete(ids=ids_to_delete)
            total_deleted += len(ids_to_delete)
            logger.info(f"  ✓ Deleted {len(ids_to_delete)} entries")
        else:
            logger.info(f"  ✓ No orphan entries found - collection is clean")
        
        logger.info("")
    
    logger.info("=" * 80)
    logger.info("CLEANUP SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total orphan entries deleted: {total_deleted}")
    logger.info("")
    
    if total_deleted > 0:
        logger.info("✓ Vector store has been cleaned successfully!")
    else:
        logger.info("✓ Vector store was already clean!")
    
    logger.info("")

if __name__ == "__main__":
    try:
        clean_vector_store()
    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        sys.exit(1)
