#!/usr/bin/env python3
"""
Uderia Prompt Management System - Content Migration Script

This script extracts prompt content from prompts.dat and updates the database
with the actual content, replacing [MIGRATE] placeholders.

Usage:
    python migrate_prompt_content.py --db-path /path/to/tda_auth.db
"""

import sqlite3
import argparse
import sys
import os
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trusted_data_agent.agent.prompts import _LOADED_PROMPTS

def migrate_prompt_content(db_path):
    """Migrate prompt content from prompts.dat to database"""
    
    print(f"Connecting to database: {db_path}")
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # Get all prompts that need migration
    cursor.execute("""
        SELECT id, name, display_name 
        FROM prompts 
        WHERE content = '[MIGRATE]'
        ORDER BY id
    """)
    
    prompts_to_migrate = cursor.fetchall()
    
    if not prompts_to_migrate:
        print("No prompts need migration (no [MIGRATE] placeholders found)")
        return True
    
    print(f"\nFound {len(prompts_to_migrate)} prompts to migrate:")
    for prompt_id, name, display_name in prompts_to_migrate:
        print(f"  - {name} ({display_name})")
    
    print("\nMigrating content...")
    
    migrated = 0
    skipped = 0
    errors = 0
    
    for prompt_id, name, display_name in prompts_to_migrate:
        # Check if content exists in _LOADED_PROMPTS
        if name not in _LOADED_PROMPTS:
            print(f"  ⚠ SKIPPED: {name} - not found in prompts.dat")
            skipped += 1
            continue
        
        content = _LOADED_PROMPTS[name]
        
        # Skip if content is not a string (e.g., CHARTING_INSTRUCTIONS is a dict)
        if not isinstance(content, str):
            print(f"  ⚠ SKIPPED: {name} - content is {type(content).__name__}, not string")
            skipped += 1
            continue
        
        try:
            # Update the prompt content
            cursor.execute("""
                UPDATE prompts 
                SET content = ?, updated_at = CURRENT_TIMESTAMP, updated_by = 'migration_script'
                WHERE id = ?
            """, (content, prompt_id))
            
            # Note: Version history is auto-created by the update trigger
            
            print(f"  ✓ MIGRATED: {name} ({len(content)} characters)")
            migrated += 1
            
        except sqlite3.Error as e:
            print(f"  ✗ ERROR: {name} - {str(e)}")
            errors += 1
    
    # Commit changes
    if migrated > 0:
        conn.commit()
        print(f"\n✓ Successfully migrated {migrated} prompts")
    
    if skipped > 0:
        print(f"⚠ Skipped {skipped} prompts")
    
    if errors > 0:
        print(f"✗ Encountered {errors} errors")
        conn.rollback()
        return False
    
    # Verify migration
    cursor.execute("""
        SELECT COUNT(*) FROM prompts WHERE content = '[MIGRATE]'
    """)
    remaining = cursor.fetchone()[0]
    
    if remaining > 0:
        print(f"\n⚠ WARNING: {remaining} prompts still have [MIGRATE] placeholder")
    else:
        print(f"\n✓ All prompts successfully migrated!")
    
    # Display summary
    print("\n" + "="*70)
    print("Migration Summary")
    print("="*70)
    
    cursor.execute("""
        SELECT 
            pc.display_name as category,
            COUNT(p.id) as prompt_count,
            SUM(CASE WHEN p.content != '[MIGRATE]' THEN 1 ELSE 0 END) as migrated_count
        FROM prompt_classes pc
        LEFT JOIN prompts p ON pc.id = p.class_id
        GROUP BY pc.id, pc.display_name
        ORDER BY pc.id
    """)
    
    print("\nPrompts by Category:")
    for category, total, migrated_count in cursor.fetchall():
        print(f"  {category}: {migrated_count}/{total} migrated")
    
    cursor.execute("SELECT COUNT(*) FROM global_parameters")
    global_params = cursor.fetchone()[0]
    print(f"\nGlobal Parameters: {global_params}")
    
    cursor.execute("SELECT COUNT(*) FROM prompt_parameters")
    prompt_params = cursor.fetchone()[0]
    print(f"Prompt Parameters: {prompt_params}")
    
    conn.close()
    return True

def main():
    parser = argparse.ArgumentParser(
        description='Migrate prompt content from prompts.dat to database'
    )
    parser.add_argument(
        '--db-path',
        type=str,
        required=True,
        help='Path to tda_auth.db database'
    )
    
    args = parser.parse_args()
    
    print("="*70)
    print("Uderia Prompt Content Migration")
    print("="*70)
    print(f"Database: {args.db_path}")
    print(f"Source: prompts.dat (via _LOADED_PROMPTS)")
    print("="*70 + "\n")
    
    try:
        success = migrate_prompt_content(args.db_path)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠ Migration cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
