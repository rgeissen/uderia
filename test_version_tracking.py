#!/usr/bin/env python3
"""
Test script to verify version tracking for prompt overrides
"""

import sqlite3
import os
from pathlib import Path

# Get database path
project_root = Path(__file__).parent
db_path = project_root / "tda_auth.db"

if not db_path.exists():
    print(f"❌ Database not found at {db_path}")
    exit(1)

print(f"✅ Connected to database: {db_path}\n")

# Connect to database
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get a sample prompt
cursor.execute("""
    SELECT id, name, version, display_name 
    FROM prompts 
    WHERE name = 'GOOGLE_MASTER_SYSTEM_PROMPT'
    LIMIT 1
""")

prompt = cursor.fetchone()
if not prompt:
    print("❌ No prompt found")
    conn.close()
    exit(1)

prompt_id = prompt['id']
prompt_name = prompt['name']
current_version = prompt['version']

print(f"📝 Prompt: {prompt['display_name']}")
print(f"   Name: {prompt_name}")
print(f"   ID: {prompt_id}")
print(f"   Current Version: {current_version}")
print()

# Check existing overrides
cursor.execute("""
    SELECT COUNT(*) as count
    FROM prompt_overrides
    WHERE prompt_id = ? AND is_active = 1
""", (prompt_id,))

override_count = cursor.fetchone()['count']
print(f"📋 Active Overrides: {override_count}")
print()

# Check version history
cursor.execute("""
    SELECT 
        version,
        changed_by,
        change_reason,
        created_at,
        LENGTH(content) as content_length
    FROM prompt_versions
    WHERE prompt_id = ?
    ORDER BY version DESC
    LIMIT 10
""", (prompt_id,))

versions = cursor.fetchall()
print(f"📚 Version History ({len(versions)} versions):")
print("-" * 80)
if versions:
    for v in versions:
        print(f"  v{v['version']:>3} | {v['created_at'][:19]} | {v['changed_by'] or 'System':20s} | {v['change_reason'] or 'N/A'}")
else:
    print("  (No version history found)")

print("-" * 80)
print()

# Test: Simulate creating an override (read-only test)
print("🧪 Testing Version Tracking Logic:")
print("   When you save a prompt override, the system should:")
print("   1. ✅ Check if an override already exists")
print("   2. ✅ Compare old content with new content")
print("   3. ✅ If changed, create version entry in prompt_versions")
print("   4. ✅ Insert/update prompt_overrides table")
print()

# Check if prompt_versions has the right structure
cursor.execute("PRAGMA table_info(prompt_versions)")
columns = [col['name'] for col in cursor.fetchall()]
print(f"✅ prompt_versions table columns: {', '.join(columns)}")
print()

conn.close()

print("✨ Test completed!")
print()
print("To verify the fix works:")
print("1. Start the application")
print("2. Go to Admin > System Prompts")
print("3. Select 'Google Master System Prompt'")
print("4. Expand 'Version History' section")
print("5. Make a change and click 'Save System Prompt'")
print("6. Version history should automatically refresh with new version")
