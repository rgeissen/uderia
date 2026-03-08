#!/usr/bin/env python3
"""
Cleanup orphaned RAG collections that belong to deleted users.

This script:
1. Finds all collections in the database
2. Checks if their owner still exists
3. Removes collections whose owners have been deleted
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User
from trusted_data_agent.core.collection_db import get_collection_db
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def cleanup_orphaned_collections():
    """Remove collections whose owner users no longer exist."""
    
    collection_db = get_collection_db()
    
    with get_db_session() as session:
        # Get all collections
        all_collections = collection_db.get_all_collections()
        logger.info(f"Found {len(all_collections)} total collections")
        
        orphaned_collections = []
        
        for collection in all_collections:
            collection_id = collection.get('id')
            owner_user_id = collection.get('owner_user_id')
            name = collection.get('name', 'Unnamed')
            
            # Check if owner still exists
            user = session.query(User).filter_by(id=owner_user_id).first()
            
            if not user:
                logger.warning(f"Collection {collection_id} '{name}' is orphaned (owner {owner_user_id} not found)")
                orphaned_collections.append((collection_id, name, owner_user_id))
            else:
                logger.info(f"Collection {collection_id} '{name}' has valid owner: {user.username}")
        
        if not orphaned_collections:
            logger.info("✅ No orphaned collections found!")
            return
        
        logger.info(f"\n⚠️  Found {len(orphaned_collections)} orphaned collection(s):")
        for coll_id, coll_name, owner_id in orphaned_collections:
            logger.info(f"  - ID {coll_id}: '{coll_name}' (owner: {owner_id})")
        
        # Ask for confirmation
        response = input("\nDelete these orphaned collections? (yes/no): ").strip().lower()
        
        if response == 'yes':
            for coll_id, coll_name, owner_id in orphaned_collections:
                try:
                    collection_db.delete_collection(coll_id)
                    logger.info(f"✅ Deleted orphaned collection {coll_id} '{coll_name}'")
                except Exception as e:
                    logger.error(f"❌ Failed to delete collection {coll_id}: {e}")
            
            logger.info(f"\n✅ Cleanup complete! Removed {len(orphaned_collections)} orphaned collection(s)")
        else:
            logger.info("Cleanup cancelled by user")


if __name__ == "__main__":
    try:
        cleanup_orphaned_collections()
    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        sys.exit(1)
