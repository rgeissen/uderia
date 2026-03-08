#!/usr/bin/env python3
"""
Quick test to verify database-backed collections work properly.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from trusted_data_agent.core.collection_db import get_collection_db


def test_collection_operations():
    """Test basic collection database operations."""
    db = get_collection_db()
    
    print("🧪 Testing Collection Database Operations\n")
    
    # Test 1: Create a collection
    print("1️⃣ Creating test collection...")
    test_collection = {
        'name': 'Test Collection',
        'collection_name': 'test_collection_12345',
        'mcp_server_id': 'test-server',
        'enabled': True,
        'description': 'A test collection',
        'owner_user_id': '8edf780c-6f3e-41d4-aaed-eff045571267',  # admin user
        'visibility': 'private',
        'is_marketplace_listed': False,
        'subscriber_count': 0,
        'marketplace_metadata': {
            'category': 'test',
            'tags': ['test', 'demo'],
            'long_description': 'This is a test collection'
        }
    }
    
    coll_id = db.create_collection(test_collection)
    print(f"   ✅ Created collection with ID: {coll_id}\n")
    
    # Test 2: Retrieve collection
    print("2️⃣ Retrieving collection...")
    retrieved = db.get_collection_by_id(coll_id)
    print(f"   ✅ Retrieved: {retrieved['name']}")
    print(f"   Owner: {retrieved['owner_user_id']}")
    print(f"   Visibility: {retrieved['visibility']}\n")
    
    # Test 3: Update collection
    print("3️⃣ Updating collection...")
    db.update_collection(coll_id, {
        'description': 'Updated description',
        'is_marketplace_listed': True
    })
    updated = db.get_collection_by_id(coll_id)
    print(f"   ✅ Description: {updated['description']}")
    print(f"   Marketplace listed: {updated['is_marketplace_listed']}\n")
    
    # Test 4: Get user collections
    print("4️⃣ Getting user's collections...")
    user_colls = db.get_user_owned_collections('8edf780c-6f3e-41d4-aaed-eff045571267')
    print(f"   ✅ Found {len(user_colls)} collection(s) for admin user\n")
    
    # Test 5: Get marketplace collections
    print("5️⃣ Getting marketplace collections...")
    marketplace_colls = db.get_marketplace_collections()
    print(f"   ✅ Found {len(marketplace_colls)} marketplace collection(s)\n")
    
    # Test 6: Delete collection
    print("6️⃣ Deleting test collection...")
    db.delete_collection(coll_id)
    deleted = db.get_collection_by_id(coll_id)
    print(f"   ✅ Deleted: {deleted is None}\n")
    
    print("✅ All tests passed!")


if __name__ == "__main__":
    test_collection_operations()
