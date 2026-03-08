#!/usr/bin/env python3
"""
Create a Knowledge Repository collection for testing.
"""

import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def create_knowledge_collection(user_id: str, collection_name: str = "TerraData Migration Knowledge"):
    """Create a knowledge repository collection."""
    
    db_path = Path(__file__).parent.parent / "tda_auth.db"
    
    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        return None
    
    print(f"📊 Database: {db_path}")
    print(f"👤 User ID: {user_id}")
    print(f"📚 Collection Name: {collection_name}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check if user exists
        cursor.execute("SELECT username, email FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        
        if not user_row:
            print(f"❌ User {user_id} not found in database")
            conn.close()
            return None
        
        username, email = user_row
        print(f"✓ Found user: {username} ({email})")
        
        # Create Knowledge Repository collection
        collection_db_name = f'knowledge_{username}_{int(datetime.now().timestamp())}'
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
            collection_name,
            collection_db_name,
            '',  # No MCP server for knowledge repos
            True,  # enabled
            created_at,
            'Knowledge repository for TerraData cloud migration best practices',
            user_id,
            'private',
            False,  # not marketplace listed
            0,  # subscriber count
            '',  # marketplace category
            '',  # marketplace tags
            '',  # marketplace long description
            'knowledge',  # repository_type - THIS IS KEY!
            'recursive',  # chunking_strategy for documents
            1000,  # chunk_size
            200  # chunk_overlap
        ))
        
        collection_id = cursor.lastrowid
        conn.commit()
        
        print(f"\n✅ Created Knowledge Repository Collection!")
        print(f"   ID: {collection_id}")
        print(f"   Name: {collection_name}")
        print(f"   Collection Name: {collection_db_name}")
        print(f"   Repository Type: knowledge")
        print(f"   Chunking Strategy: recursive")
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
        return collection_id
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python maintenance/create_knowledge_collection.py <user_id> [collection_name]")
        print("\nTo find user IDs, run:")
        print("  sqlite3 tda_auth.db 'SELECT id, username FROM users'")
        sys.exit(1)
    
    user_id = sys.argv[1]
    collection_name = sys.argv[2] if len(sys.argv) > 2 else "TerraData Migration Knowledge"
    
    collection_id = create_knowledge_collection(user_id, collection_name)
    
    if collection_id:
        print("\n✅ Done!")
        print("\n📝 Next Steps:")
        print("   1. Restart the TDA application")
        print("   2. Upload test/knowledge_test_document.md to this collection")
        print("   3. Configure your profile to enable Knowledge Repository")
        print("   4. Ask: 'What parallel degree should I use for TerraData Schema Transfer Utility?'")
    else:
        print("\n❌ Failed to create knowledge collection.")
        sys.exit(1)
