#!/usr/bin/env python3
"""
Manually create default collection for a user.
Useful when bootstrap didn't create it automatically.
"""

import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def create_default_collection(user_id: str):
    """Create a default planner collection for the specified user."""
    
    db_path = Path(__file__).parent.parent / "tda_auth.db"
    
    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        return False
    
    print(f"📊 Database: {db_path}")
    print(f"👤 User ID: {user_id}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check if user exists
        cursor.execute("SELECT username, email FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        
        if not user_row:
            print(f"❌ User {user_id} not found in database")
            conn.close()
            return False
        
        username, email = user_row
        print(f"✓ Found user: {username} ({email})")
        
        # Check if user already has a Default Collection
        cursor.execute("""
            SELECT id, name, collection_name, repository_type
            FROM collections
            WHERE owner_user_id = ? AND name LIKE '%Default Collection%'
        """, (user_id,))
        
        existing = cursor.fetchone()
        if existing:
            coll_id, name, coll_name, repo_type = existing
            print(f"\n⚠️  User already has a default collection:")
            print(f"   ID: {coll_id}")
            print(f"   Name: {name}")
            print(f"   Collection Name: {coll_name}")
            print(f"   Repository Type: {repo_type}")
            conn.close()
            return True
        
        # Create Default Collection
        print("\n🔧 Creating Default Collection...")
        
        collection_name = f'default_collection_{user_id[:8]}'
        created_at = datetime.now(timezone.utc).isoformat()
        
        cursor.execute("""
            INSERT INTO collections (
                name, collection_name, mcp_server_id, enabled, created_at,
                description, owner_user_id, visibility, is_marketplace_listed,
                subscriber_count, marketplace_category, marketplace_tags,
                marketplace_long_description, repository_type,
                chunking_strategy, chunk_size, chunk_overlap
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'Default Collection',
            collection_name,
            '',  # No MCP server required initially
            True,  # enabled
            created_at,
            'Your default collection for RAG cases',
            user_id,
            'private',
            False,  # not marketplace listed
            0,  # subscriber count
            '',  # marketplace category
            '',  # marketplace tags
            '',  # marketplace long description
            'planner',  # repository_type
            'none',  # chunking_strategy
            1000,  # chunk_size
            200  # chunk_overlap
        ))
        
        collection_id = cursor.lastrowid
        conn.commit()
        
        print(f"✅ Created Default Collection!")
        print(f"   ID: {collection_id}")
        print(f"   Name: Default Collection")
        print(f"   Collection Name: {collection_name}")
        print(f"   Repository Type: planner")
        print(f"   Owner: {user_id}")
        
        # Show all user's collections
        cursor.execute("""
            SELECT id, name, collection_name, repository_type
            FROM collections
            WHERE owner_user_id = ?
            ORDER BY id
        """, (user_id,))
        
        all_collections = cursor.fetchall()
        print(f"\n📋 User's collections ({len(all_collections)} total):")
        for coll_id, name, coll_name, repo_type in all_collections:
            print(f"  - [{repo_type}] {name} (ID: {coll_id})")
        
        conn.close()
        return True
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python maintenance/create_default_collection.py <user_id>")
        print("\nTo find user IDs, run:")
        print("  sqlite3 tda_auth.db 'SELECT id, username FROM users'")
        sys.exit(1)
    
    user_id = sys.argv[1]
    success = create_default_collection(user_id)
    
    if success:
        print("\n✅ Done! Refresh your browser to see the collection.")
    else:
        print("\n❌ Failed to create default collection.")
        sys.exit(1)
