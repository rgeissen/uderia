#!/usr/bin/env python3
"""
Fix Wildcard Collection Assignments in Existing Profiles

This script removes wildcard ["*"] from ragCollections and autocompleteCollections
in existing user profiles, replacing them with empty arrays [].

This prevents imported collections from automatically appearing as enabled in profiles.

Usage:
    python maintenance/fix_wildcard_collections.py
"""

import sqlite3
import json
import os
from datetime import datetime

def update_profile_collections():
    """
    Remove wildcard collection assignments from existing profiles.

    Replaces:
    - ragCollections: ["*"] → []
    - autocompleteCollections: ["*"] → []

    Returns:
        True if successful, False otherwise
    """
    db_path = "tda_auth.db"

    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        print("   Make sure you're running this from the project root directory.")
        return False

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("="*70)
        print("FIX WILDCARD COLLECTION ASSIGNMENTS")
        print("="*70)
        print("\nThis script will remove wildcard ['*'] collection assignments")
        print("from existing profiles to prevent imported collections from")
        print("automatically appearing as enabled.\n")
        print("="*70 + "\n")

        # Get all users with preferences
        cursor.execute("SELECT user_id, preferences_json FROM user_preferences")
        users = cursor.fetchall()

        if not users:
            print("ℹ️  No users found in database.")
            return True

        total_profiles_updated = 0
        total_users_updated = 0

        for user_id, preferences_json_str in users:
            try:
                preferences = json.loads(preferences_json_str)
                profiles = preferences.get("profiles", [])

                if not profiles:
                    continue

                profiles_updated_count = 0
                updated_profiles = []

                for profile in profiles:
                    profile_updated = False
                    profile_tag = profile.get("tag", "UNKNOWN")

                    # Check and fix ragCollections
                    rag_collections = profile.get("ragCollections", [])
                    if rag_collections == ["*"]:
                        profile["ragCollections"] = []
                        profile_updated = True
                        print(f"  • @{profile_tag}: ragCollections ['*'] → []")

                    # Check and fix autocompleteCollections
                    autocomplete_collections = profile.get("autocompleteCollections", [])
                    if autocomplete_collections == ["*"]:
                        profile["autocompleteCollections"] = []
                        profile_updated = True
                        print(f"  • @{profile_tag}: autocompleteCollections ['*'] → []")

                    if profile_updated:
                        profiles_updated_count += 1
                        updated_profiles.append(profile_tag)

                # If any profiles were updated, save back to database
                if profiles_updated_count > 0:
                    preferences["last_modified"] = datetime.utcnow().isoformat() + "+00:00"
                    updated_json = json.dumps(preferences, indent=2)

                    cursor.execute("""
                        UPDATE user_preferences
                        SET preferences_json = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = ?
                    """, (updated_json, user_id))

                    total_profiles_updated += profiles_updated_count
                    total_users_updated += 1

                    print(f"\n✅ Updated {profiles_updated_count} profile(s) for user {user_id[:8]}...")
                    print(f"   Profiles: {', '.join('@' + tag for tag in updated_profiles)}")
                    print()

            except json.JSONDecodeError as e:
                print(f"⚠️  Warning: Could not parse preferences for user {user_id}: {e}")
                continue
            except Exception as e:
                print(f"⚠️  Warning: Error processing user {user_id}: {e}")
                continue

        # Commit all changes
        conn.commit()

        print("="*70)
        if total_profiles_updated > 0:
            print(f"✅ SUCCESS: Updated {total_profiles_updated} profile(s) across {total_users_updated} user(s)")
            print("\nNext steps:")
            print("  1. Restart the Uderia application")
            print("  2. Open profile editor and verify collections are no longer auto-enabled")
            print("  3. Manually select desired collections for each profile")
            print("\nImported collections will no longer auto-appear in existing profiles!")
        else:
            print("ℹ️  No profiles with wildcard ['*'] collection assignments found.")
            print("   All profiles are already using explicit collection lists.")
        print("="*70)

        return True

    except sqlite3.Error as e:
        print(f"\n❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def main():
    print("\n" + "="*70)
    print("WILDCARD COLLECTION FIX")
    print("="*70)
    print("\nThis script will fix existing profiles that have wildcard ['*']")
    print("collection assignments, preventing imported collections from")
    print("automatically appearing as enabled.")
    print("\nChanges:")
    print("  • ragCollections: ['*'] → []")
    print("  • autocompleteCollections: ['*'] → []")
    print("\n" + "="*70 + "\n")

    response = input("Proceed with database update? (yes/no): ").strip().lower()

    if response not in ['yes', 'y']:
        print("\n❌ Update cancelled by user.")
        return

    print()
    success = update_profile_collections()

    if not success:
        print("\n❌ Update failed. Please check error messages above.")
        exit(1)
    else:
        print("\n✅ Update completed successfully!")
        exit(0)

if __name__ == "__main__":
    main()
