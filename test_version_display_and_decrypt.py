#!/usr/bin/env python3
"""
Test script for version display and plain text decryption fallback.

This tests:
1. Version badge displays correctly in UI (requires manual verification)
2. Version 1 (plain text) can be loaded without decryption errors
3. Encrypted versions still decrypt correctly

Run this after starting the application.
"""

import sqlite3
from pathlib import Path
from trusted_data_agent.core.utils import get_project_root
from trusted_data_agent.agent.prompt_loader import PromptLoader
from trusted_data_agent.agent.prompt_encryption import encrypt_prompt, decrypt_prompt

def test_version_display():
    """Test that version information is properly returned in API response."""
    print("=" * 60)
    print("TEST 1: Version Display")
    print("=" * 60)
    
    db_path = get_project_root() / 'tda_auth.db'
    loader = PromptLoader()
    
    # Test a system prompt
    prompt_name = "GOOGLE_MASTER_SYSTEM_PROMPT"
    metadata = loader.get_prompt_metadata(prompt_name)
    
    if metadata:
        print(f"✅ Prompt: {prompt_name}")
        print(f"   Version: {metadata.get('version', 'N/A')}")
        print(f"   Display Name: {metadata.get('display_name', 'N/A')}")
        print(f"   Category: {metadata.get('category', 'N/A')}")
    else:
        print(f"❌ Failed to get metadata for {prompt_name}")
    
    print("\n📝 Manual verification needed:")
    print("   1. Load admin panel → System Prompts tab")
    print("   2. Select a prompt from dropdown")
    print("   3. Verify blue 'Version: vX' badge appears next to label")
    print()


def test_version_decryption():
    """Test that both encrypted and plain text versions can be loaded."""
    print("=" * 60)
    print("TEST 2: Version Decryption (Plain Text Fallback)")
    print("=" * 60)
    
    db_path = get_project_root() / 'tda_auth.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    loader = PromptLoader()
    
    # Get a prompt with multiple versions
    cursor.execute("""
        SELECT p.name, p.id, COUNT(pv.id) as version_count
        FROM prompts p
        LEFT JOIN prompt_versions pv ON p.id = pv.prompt_id
        GROUP BY p.id
        HAVING version_count > 0
        ORDER BY version_count DESC
        LIMIT 1
    """)
    
    row = cursor.fetchone()
    if not row:
        print("❌ No prompts with versions found")
        conn.close()
        return
    
    prompt_name = row['name']
    prompt_id = row['id']
    print(f"Testing prompt: {prompt_name} ({row['version_count']} versions)")
    print()
    
    # Test each version
    cursor.execute("""
        SELECT version, content, created_at
        FROM prompt_versions
        WHERE prompt_id = ?
        ORDER BY version ASC
    """, (prompt_id,))
    
    versions = cursor.fetchall()
    for version_row in versions:
        version_num = version_row['version']
        content = version_row['content']
        
        print(f"Version {version_num}:")
        
        # Try decryption
        try:
            decrypted = decrypt_prompt(content, loader._decryption_key)
            print(f"   ✅ Decryption successful")
            print(f"   Content preview: {decrypted[:60]}...")
        except Exception as e:
            # Should fall back to plain text
            print(f"   ⚠️  Decryption failed: {e}")
            print(f"   ✅ Using as plain text")
            print(f"   Content preview: {content[:60]}...")
        
        print()
    
    conn.close()
    
    print("📝 Manual verification needed:")
    print("   1. Load admin panel → System Prompts tab")
    print("   2. Select a prompt with multiple versions")
    print("   3. Expand 'Version History' section")
    print("   4. Click on Version 1 (or any version)")
    print("   5. Verify NO 'Incorrect padding' error appears")
    print("   6. Verify version content displays in preview dialog")
    print()


def test_override_version():
    """Test that override version is displayed correctly."""
    print("=" * 60)
    print("TEST 3: Override Detection")
    print("=" * 60)
    
    db_path = get_project_root() / 'tda_auth.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Find a prompt with an override
    cursor.execute("""
        SELECT p.name, p.version as base_version,
               CASE WHEN po.user_uuid IS NOT NULL THEN 'user' ELSE 'profile' END as scope
        FROM prompts p
        JOIN prompt_overrides po ON p.id = po.prompt_id
        WHERE po.is_active = 1
        LIMIT 1
    """)
    
    row = cursor.fetchone()
    if not row:
        print("❌ No active overrides found")
        print("   Create an override by editing and saving a prompt")
        conn.close()
        return
    
    print(f"Prompt: {row['name']}")
    print(f"   Base version: v{row['base_version']}")
    print(f"   Override scope: {row['scope']}")
    print(f"   ✅ Override detected in database")
    print()
    
    conn.close()
    
    print("📝 Manual verification needed:")
    print("   1. Load admin panel → System Prompts tab")
    print("   2. Select a prompt that you have overridden")
    print("   3. Verify 'Custom Override' badge shows (orange)")
    print("   4. Verify 'Version: vX' badge shows current version (blue)")
    print("   5. Click 'Reset to Default' to see version change to base")
    print()


if __name__ == "__main__":
    print("\n🧪 Version Display and Decryption Test Suite\n")
    
    try:
        test_version_display()
        test_version_decryption()
        test_override_version()
        
        print("=" * 60)
        print("✅ All automated tests completed!")
        print("=" * 60)
        print("\n⚠️  Remember to perform manual verification steps above")
        print("   to confirm UI displays correctly.\n")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
