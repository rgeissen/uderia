#!/usr/bin/env python3
"""
Update Nested Genie Support for Existing Installations

This script applies the necessary database changes to enable nested Genie coordination
on existing Uderia installations, allowing parent Genies to coordinate child Genies.

Changes applied:
1. Adds nesting_level column to genie_session_links table
2. Adds maxNestingDepth setting to genie_global_settings table

Usage:
    python maintenance/update_nested_genie_support.py
"""

import sqlite3
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

def update_database():
    """Apply nested Genie support updates to the database."""
    db_path = project_root / "tda_auth.db"

    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        print("   This script is for existing installations only.")
        return False

    print(f"📊 Updating database at: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if updates are already applied
        print("\n🔍 Checking current database state...")

        # Check for nesting_level column
        cursor.execute("PRAGMA table_info(genie_session_links)")
        columns = [col[1] for col in cursor.fetchall()]
        has_nesting_level = 'nesting_level' in columns

        # Check for maxNestingDepth setting
        cursor.execute("""
            SELECT COUNT(*) FROM genie_global_settings
            WHERE setting_key = 'maxNestingDepth'
        """)
        has_max_depth_setting = cursor.fetchone()[0] > 0

        if has_nesting_level and has_max_depth_setting:
            print("✅ Database already has nested Genie support enabled.")
            print("   No updates needed.")
            return True

        # Apply updates
        updates_applied = []

        # 1. Add nesting_level column if missing
        if not has_nesting_level:
            print("\n📝 Adding nesting_level column to genie_session_links...")
            cursor.execute("""
                ALTER TABLE genie_session_links
                ADD COLUMN nesting_level INTEGER DEFAULT 0
            """)

            # Create index
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_genie_nesting_level
                ON genie_session_links(nesting_level)
            """)

            # Backfill existing records
            cursor.execute("""
                UPDATE genie_session_links
                SET nesting_level = 0
                WHERE nesting_level IS NULL
            """)

            updates_applied.append("✅ Added nesting_level column with index")
        else:
            print("⏭️  Skipping nesting_level column (already exists)")

        # 2. Add maxNestingDepth setting if missing
        if not has_max_depth_setting:
            print("\n📝 Adding maxNestingDepth to genie_global_settings...")
            cursor.execute("""
                INSERT OR IGNORE INTO genie_global_settings
                (setting_key, setting_value, is_locked)
                VALUES ('maxNestingDepth', '3', 0)
            """)
            updates_applied.append("✅ Added maxNestingDepth global setting (default: 3)")
        else:
            print("⏭️  Skipping maxNestingDepth setting (already exists)")

        # Commit changes
        conn.commit()

        # Summary
        print("\n" + "="*60)
        print("✅ DATABASE UPDATE SUCCESSFUL")
        print("="*60)

        if updates_applied:
            print("\nChanges applied:")
            for update in updates_applied:
                print(f"  {update}")
        else:
            print("\nNo changes needed - database already up to date.")

        print("\nNested Genie coordination is now enabled!")
        print("\nNext steps:")
        print("  1. Restart the Uderia application")
        print("  2. Navigate to Administration → Expert Settings → Genie Coordination")
        print("  3. Configure maxNestingDepth (default: 3, range: 1-10)")
        print("  4. Edit Genie profiles to add other Genies as children")
        print("\nWarning: Nested Genies significantly increase token usage.")
        print("         Circular dependencies and self-reference are blocked automatically.")

        return True

    except sqlite3.Error as e:
        print(f"\n❌ Database error: {e}")
        return False

    finally:
        if conn:
            conn.close()

def main():
    print("="*60)
    print("NESTED GENIE SUPPORT - DATABASE UPDATE")
    print("="*60)
    print("\nThis script updates existing Uderia installations to support")
    print("nested Genie coordination (parent Genies coordinating child Genies).")
    print("\nFeatures enabled:")
    print("  • Genie profiles can coordinate other Genie profiles as children")
    print("  • Circular dependency detection prevents infinite loops")
    print("  • Configurable maximum nesting depth (default: 3)")
    print("  • Self-reference protection (cannot select itself as child)")
    print("  • Runtime depth checks prevent excessive nesting")
    print("\n" + "="*60 + "\n")

    response = input("Proceed with database update? (yes/no): ").strip().lower()

    if response not in ['yes', 'y']:
        print("\n❌ Update cancelled by user.")
        return

    success = update_database()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
