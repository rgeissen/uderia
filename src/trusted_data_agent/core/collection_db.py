"""
Database operations for RAG collections.
Replaces JSON file storage with SQLite database storage.
"""

import sqlite3
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

DB_PATH = "tda_auth.db"


class CollectionDatabase:
    """Handles all database operations for RAG collections."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        return conn
    
    def get_all_collections(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all collections for a user (owned + subscribed).
        If user_id is None, returns all collections (admin use).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if user_id is None:
            # Admin view - all collections
            cursor.execute("""
                SELECT c.*, u.username as owner_username 
                FROM collections c
                LEFT JOIN users u ON c.owner_user_id = u.id
                ORDER BY c.id
            """)
        else:
            # User view - owned + subscribed collections
            cursor.execute("""
                SELECT DISTINCT c.*, u.username as owner_username 
                FROM collections c
                LEFT JOIN users u ON c.owner_user_id = u.id
                LEFT JOIN collection_subscriptions cs ON c.id = cs.source_collection_id
                WHERE c.owner_user_id = ? OR cs.user_id = ?
                ORDER BY c.id
            """, (user_id, user_id))
        
        rows = cursor.fetchall()
        conn.close()
        
        collections = []
        for row in rows:
            coll = dict(row)
            # Parse JSON fields
            if coll['marketplace_tags']:
                coll['marketplace_tags'] = json.loads(coll['marketplace_tags'])
            else:
                coll['marketplace_tags'] = []
            
            # Build marketplace_metadata from separate columns
            coll['marketplace_metadata'] = {
                'category': coll.pop('marketplace_category', ''),
                'tags': coll.pop('marketplace_tags', []),
                'long_description': coll.pop('marketplace_long_description', '')
            }
            
            collections.append(coll)
        
        return collections
    
    def get_collection_by_id(self, collection_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific collection by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT c.*, u.username as owner_username 
            FROM collections c
            LEFT JOIN users u ON c.owner_user_id = u.id
            WHERE c.id = ?
        """, (collection_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        coll = dict(row)
        # Parse JSON fields
        if coll['marketplace_tags']:
            coll['marketplace_tags'] = json.loads(coll['marketplace_tags'])
        else:
            coll['marketplace_tags'] = []
        
        # Build marketplace_metadata
        coll['marketplace_metadata'] = {
            'category': coll.pop('marketplace_category', ''),
            'tags': coll.pop('marketplace_tags', []),
            'long_description': coll.pop('marketplace_long_description', '')
        }
        
        return coll
    
    def get_user_owned_collections(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all collections owned by a user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM collections
            WHERE owner_user_id = ?
            ORDER BY id
        """, (user_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        collections = []
        for row in rows:
            coll = dict(row)
            if coll['marketplace_tags']:
                coll['marketplace_tags'] = json.loads(coll['marketplace_tags'])
            else:
                coll['marketplace_tags'] = []
            
            coll['marketplace_metadata'] = {
                'category': coll.pop('marketplace_category', ''),
                'tags': coll.pop('marketplace_tags', []),
                'long_description': coll.pop('marketplace_long_description', '')
            }
            
            collections.append(coll)
        
        return collections
    
    def create_collection(self, collection_data: Dict[str, Any]) -> int:
        """
        Create a new collection.
        Returns the new collection ID.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Extract marketplace metadata
        marketplace_metadata = collection_data.get('marketplace_metadata', {})
        marketplace_tags = marketplace_metadata.get('tags', [])
        
        cursor.execute("""
            INSERT INTO collections (
                name, collection_name, mcp_server_id, enabled, created_at,
                description, owner_user_id, visibility, is_marketplace_listed,
                subscriber_count, marketplace_category, marketplace_tags,
                marketplace_long_description, repository_type, chunking_strategy,
                chunk_size, chunk_overlap
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            collection_data['name'],
            collection_data['collection_name'],
            collection_data.get('mcp_server_id', ''),
            collection_data.get('enabled', True),
            collection_data.get('created_at', datetime.now(timezone.utc).isoformat()),
            collection_data.get('description', ''),
            collection_data['owner_user_id'],
            collection_data.get('visibility', 'private'),
            collection_data.get('is_marketplace_listed', False),
            collection_data.get('subscriber_count', 0),
            marketplace_metadata.get('category', ''),
            json.dumps(marketplace_tags) if marketplace_tags else '',
            marketplace_metadata.get('long_description', ''),
            collection_data.get('repository_type', 'planner'),
            collection_data.get('chunking_strategy', 'none'),
            collection_data.get('chunk_size', 1000),
            collection_data.get('chunk_overlap', 200)
        ))
        
        collection_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Created collection ID {collection_id}: {collection_data['name']}")
        return collection_id
    
    def update_collection(self, collection_id: int, updates: Dict[str, Any]) -> bool:
        """Update a collection's metadata."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Handle marketplace_metadata updates
        if 'marketplace_metadata' in updates:
            metadata = updates.pop('marketplace_metadata')
            if 'category' in metadata:
                updates['marketplace_category'] = metadata['category']
            if 'tags' in metadata:
                updates['marketplace_tags'] = json.dumps(metadata['tags'])
            if 'long_description' in metadata:
                updates['marketplace_long_description'] = metadata['long_description']
        
        # Build UPDATE query dynamically
        set_clauses = [f"{key} = ?" for key in updates.keys()]
        values = list(updates.values())
        values.append(collection_id)
        
        query = f"UPDATE collections SET {', '.join(set_clauses)} WHERE id = ?"
        
        cursor.execute(query, values)
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_affected > 0:
            logger.info(f"Updated collection ID {collection_id}")
            return True
        else:
            logger.warning(f"Collection ID {collection_id} not found for update")
            return False
    
    def delete_collection(self, collection_id: int) -> bool:
        """Delete a collection."""
        if collection_id == 0:
            logger.warning("Cannot delete default collection (ID 0)")
            return False
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_affected > 0:
            logger.info(f"Deleted collection ID {collection_id}")
            return True
        else:
            logger.warning(f"Collection ID {collection_id} not found for deletion")
            return False
    
    def get_marketplace_collections(self, exclude_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all marketplace-listed collections.
        Optionally exclude collections owned by a specific user.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if exclude_user_id:
            cursor.execute("""
                SELECT c.*, u.username as owner_username 
                FROM collections c
                LEFT JOIN users u ON c.owner_user_id = u.id
                WHERE c.is_marketplace_listed = 1
                  AND c.visibility = 'public'
                  AND c.owner_user_id IS NOT NULL
                  AND c.owner_user_id != ?
                ORDER BY c.subscriber_count DESC, c.created_at DESC
            """, (exclude_user_id,))
        else:
            cursor.execute("""
                SELECT c.*, u.username as owner_username 
                FROM collections c
                LEFT JOIN users u ON c.owner_user_id = u.id
                WHERE c.is_marketplace_listed = 1
                  AND c.visibility = 'public'
                  AND c.owner_user_id IS NOT NULL
                ORDER BY c.subscriber_count DESC, c.created_at DESC
            """)
        
        rows = cursor.fetchall()
        conn.close()
        
        collections = []
        for row in rows:
            coll = dict(row)
            if coll['marketplace_tags']:
                coll['marketplace_tags'] = json.loads(coll['marketplace_tags'])
            else:
                coll['marketplace_tags'] = []
            
            coll['marketplace_metadata'] = {
                'category': coll.pop('marketplace_category', ''),
                'tags': coll.pop('marketplace_tags', []),
                'long_description': coll.pop('marketplace_long_description', '')
            }
            
            collections.append(coll)
        
        return collections
    
    def create_default_collection(self, user_id: str, mcp_server_id: str = "") -> int:
        """
        Create a default collection for a new user.
        Returns the collection ID.
        """
        from trusted_data_agent.core.config import APP_CONFIG
        
        collection_data = {
            'name': 'Default Collection',
            'collection_name': f'default_collection_{user_id[:8]}',
            'mcp_server_id': mcp_server_id,
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'description': 'Your default collection for RAG cases',
            'owner_user_id': user_id,
            'visibility': 'private',
            'is_marketplace_listed': False,
            'subscriber_count': 0,
            'marketplace_metadata': {},
            'repository_type': 'planner'
        }
        
        return self.create_collection(collection_data)
    
    def get_collection_ratings(self, collection_id: int) -> Dict[str, Any]:
        """
        Get rating statistics for a collection.
        
        Returns:
            Dict with 'average_rating' (float), 'rating_count' (int), and 'ratings_breakdown' (dict)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Get average rating and count
        cursor.execute("""
            SELECT 
                COALESCE(AVG(rating), 0) as average_rating,
                COUNT(*) as rating_count
            FROM collection_ratings
            WHERE collection_id = ?
        """, (collection_id,))
        
        result = cursor.fetchone()
        average_rating = float(result['average_rating']) if result else 0.0
        rating_count = int(result['rating_count']) if result else 0
        
        # Get ratings breakdown (count per star level)
        cursor.execute("""
            SELECT rating, COUNT(*) as count
            FROM collection_ratings
            WHERE collection_id = ?
            GROUP BY rating
            ORDER BY rating DESC
        """, (collection_id,))
        
        breakdown = {str(i): 0 for i in range(1, 6)}  # Initialize 1-5 stars
        for row in cursor.fetchall():
            breakdown[str(row['rating'])] = row['count']
        
        conn.close()
        
        return {
            'average_rating': round(average_rating, 1),
            'rating_count': rating_count,
            'ratings_breakdown': breakdown
        }
    
    def get_bulk_collection_ratings(self, collection_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Get rating statistics for multiple collections in a single query.
        
        Args:
            collection_ids: List of collection IDs
        
        Returns:
            Dict mapping collection_id to rating stats
        """
        if not collection_ids:
            return {}
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        placeholders = ','.join('?' * len(collection_ids))
        cursor.execute(f"""
            SELECT 
                collection_id,
                COALESCE(AVG(rating), 0) as average_rating,
                COUNT(*) as rating_count
            FROM collection_ratings
            WHERE collection_id IN ({placeholders})
            GROUP BY collection_id
        """, collection_ids)
        
        ratings_map = {}
        for row in cursor.fetchall():
            coll_id = row['collection_id']
            ratings_map[coll_id] = {
                'average_rating': round(float(row['average_rating']), 1),
                'rating_count': int(row['rating_count'])
            }
        
        # Fill in collections with no ratings
        for coll_id in collection_ids:
            if coll_id not in ratings_map:
                ratings_map[coll_id] = {
                    'average_rating': 0.0,
                    'rating_count': 0
                }
        
        conn.close()
        return ratings_map


# Global instance
_collection_db = None


def get_collection_db() -> CollectionDatabase:
    """Get the global CollectionDatabase instance."""
    global _collection_db
    if _collection_db is None:
        _collection_db = CollectionDatabase()
    return _collection_db
