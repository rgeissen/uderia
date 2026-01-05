#!/usr/bin/env python3
"""
Initialize the database with fresh state using the application's built-in initialization.
Creates admin user, test user, and their default collections.
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from trusted_data_agent.auth.database import init_database
from trusted_data_agent.auth.security import hash_password
from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User
from trusted_data_agent.core.collection_db import get_collection_db

# Use absolute path to project root database
DB_PATH = Path(__file__).parent.parent / "tda_auth.db"


def clear_database():
    """Clear all users, collections, and related data."""
    print("🗑️  Clearing existing data...")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Clear in order to respect foreign keys
    cursor.execute("DELETE FROM audit_logs")
    cursor.execute("DELETE FROM auth_tokens")
    cursor.execute("DELETE FROM access_tokens")
    cursor.execute("DELETE FROM password_reset_tokens")
    cursor.execute("DELETE FROM collection_ratings")
    cursor.execute("DELETE FROM collection_subscriptions")
    cursor.execute("DELETE FROM collections")
    cursor.execute("DELETE FROM user_credentials")  # Clear LLM credentials
    cursor.execute("DELETE FROM user_preferences")
    cursor.execute("DELETE FROM users")
    
    conn.commit()
    conn.close()
    
    print("   ✅ Database cleared (including credentials)\n")





def create_default_profiles(admin_id, test_id):
    """Create default profiles for both users, bootstrapped from tda_config.json."""
    print("\n👤 Creating default profiles...")
    
    from trusted_data_agent.core.config_manager import get_config_manager
    
    config_manager = get_config_manager()
    
    # Get first available MCP server and LLM config from tda_config.json
    mcp_servers = config_manager.get_mcp_servers()
    llm_configs = config_manager.get_llm_configurations()
    
    if not mcp_servers:
        print("   ⚠️  No MCP servers configured in tda_config.json - skipping profile creation")
        return
    
    if not llm_configs:
        print("   ⚠️  No LLM configurations in tda_config.json - skipping profile creation")
        return
    
    # Use first MCP server and LLM config as defaults
    default_mcp = mcp_servers[0]
    default_llm = llm_configs[0]
    
    mcp_server_id = default_mcp.get('id')
    llm_config_id = default_llm.get('id')
    
    print(f"   Using MCP Server: {default_mcp.get('name')} (ID: {mcp_server_id})")
    print(f"   Using LLM Config: {default_llm.get('provider')}/{default_llm.get('model')} (ID: {llm_config_id})")
    
    # Create profile for admin
    import time
    admin_profile_id = f"{int(time.time() * 1000)}-admin-default"
    admin_profile_data = {
        'id': admin_profile_id,
        'name': 'Default Profile',
        'tag': 'default',
        'llmConfigurationId': llm_config_id,
        'mcpServerId': mcp_server_id,
        'isDefault': True
    }
    config_manager.add_profile(admin_profile_data, admin_id)
    print(f"   ✅ Created admin's Default Profile (ID: {admin_profile_id})")
    
    # Create profile for test user
    test_profile_id = f"{int(time.time() * 1000) + 1}-test-default"
    test_profile_data = {
        'id': test_profile_id,
        'name': 'Default Profile',
        'tag': 'default',
        'llmConfigurationId': llm_config_id,
        'mcpServerId': mcp_server_id,
        'isDefault': True
    }
    config_manager.add_profile(test_profile_data, test_id)
    print(f"   ✅ Created test user's Default Profile (ID: {test_profile_id})")


def create_default_collections(admin_id, test_id):
    """Create default collections for both users."""
    print("\n📚 Creating default collections...")
    
    # Get active MCP server ID from config
    from trusted_data_agent.core.config_manager import get_config_manager
    config_manager = get_config_manager()
    mcp_server_id = config_manager.get_active_mcp_server_id()
    
    if mcp_server_id:
        print(f"   Using MCP Server ID: {mcp_server_id}")
    else:
        print("   ⚠️  No active MCP server found in config")
    
    collection_db = get_collection_db()
    
    # Admin's default collection
    admin_coll_id = collection_db.create_default_collection(admin_id, mcp_server_id or "")
    print(f"   ✅ Created admin's Default Collection (ID: {admin_coll_id})")
    
    # Test user's default collection
    test_coll_id = collection_db.create_default_collection(test_id, mcp_server_id or "")
    print(f"   ✅ Created test user's Default Collection (ID: {test_coll_id})")
    
    return admin_coll_id, test_coll_id


def verify_setup():
    """Verify the setup."""
    print("\n🔍 Verifying setup...")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Count users
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    print(f"   ✅ Users: {user_count}")
    
    # Count collections
    cursor.execute("SELECT COUNT(*) FROM collections")
    coll_count = cursor.fetchone()[0]
    print(f"   ✅ Collections: {coll_count}")
    
    # Show collections with owners
    cursor.execute("""
        SELECT c.id, c.name, u.username 
        FROM collections c
        JOIN users u ON c.owner_user_id = u.id
        ORDER BY c.id
    """)
    
    print("\n📋 Collections:")
    for row in cursor.fetchall():
        coll_id, coll_name, owner = row
        print(f"   • Collection {coll_id}: {coll_name} (owner: {owner})")
    
    conn.close()


def main():
    print("=" * 60)
    print("TDA Database Initialization")
    print("=" * 60 + "\n")
    
    # Step 1: Clear existing data
    clear_database()
    
    # Step 2: Run application's built-in initialization (creates admin user)
    print("🔧 Running application initialization...")
    init_database()
    print("   ✅ Application initialized\n")
    
    # Step 3: Create test user manually
    print("👥 Creating test user...")
    test_id = "e0b2798c-4665-4f31-ac4f-181013ab7b64"
    test_password_hash = hash_password("test")
    
    with get_db_session() as session:
        test_user = User(
            id=test_id,
            username="test",
            email="test@tda.local",
            password_hash=test_password_hash,
            display_name="Test User",
            full_name="Test User Account",
            is_active=True,
            is_admin=False,
            profile_tier="developer"
        )
        session.add(test_user)
        session.commit()
    
    print(f"   ✅ Created test user (ID: {test_id})\n")
    
    # Step 4: Get admin user ID
    with get_db_session() as session:
        admin_user = session.query(User).filter_by(username="admin").first()
        admin_id = admin_user.id
    
    # Step 5: Create default collections
    # Note: Profiles are now bootstrapped automatically on first login from tda_config.json
    admin_coll_id, test_coll_id = create_default_collections(admin_id, test_id)
    
    # Step 6: Verify
    verify_setup()
    
    print("\n" + "=" * 60)
    print("✅ Database initialization complete!")
    print("=" * 60)
    print("\n📝 Login credentials:")
    print("   Admin: username='admin', password='admin'")
    print("   Test:  username='test', password='test'")
    print("\n🚀 Ready to start the server!\n")


if __name__ == "__main__":
    main()
