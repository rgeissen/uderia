#!/usr/bin/env python3
"""
Sync autocomplete settings for existing users who don't have default collections enabled.

This maintenance script updates existing users' profiles to enable autocomplete for their
default planner collections. Run this after deploying the autocomplete bootstrap feature.

Usage:
    python maintenance/sync_default_collection_autocomplete.py

The script will:
1. Find all active users
2. For each user, identify their default planner collections
3. Update profiles to include these collections in autocompleteCollections
4. Save the updated profiles

This is safe to run multiple times (idempotent).
"""

import sys
import logging
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User
from trusted_data_agent.core.collection_db import get_collection_db
from trusted_data_agent.api.auth_routes import _update_profiles_with_default_collections

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sync_all_users():
    """
    Sync autocomplete settings for all active users.

    This function finds all default planner collections for each user
    and updates their profiles to enable autocomplete for these collections.
    """
    collection_db = get_collection_db()

    try:
        with get_db_session() as session:
            users = session.query(User).filter_by(is_active=True).all()
            logger.info(f"Found {len(users)} active users to sync")

            synced_count = 0
            skipped_count = 0
            error_count = 0

            for user in users:
                user_id = user.id
                username = user.username

                try:
                    # Get all collections owned by this user
                    user_collections = collection_db.get_user_owned_collections(user_id)

                    # Find default planner collections
                    default_collections = [
                        c for c in user_collections
                        if 'Default Collection' in c.get('name', '')
                        and c.get('repository_type') == 'planner'
                    ]

                    if default_collections:
                        # Build mapping of mcp_server_id -> collection_id
                        collection_ids_by_server = {
                            c['mcp_server_id']: c['id']
                            for c in default_collections
                            if c.get('mcp_server_id')
                        }

                        if collection_ids_by_server:
                            logger.info(f"Syncing user '{username}' ({user_id}): {len(collection_ids_by_server)} default collection(s)")
                            success = _update_profiles_with_default_collections(user_id, collection_ids_by_server)

                            if success:
                                synced_count += 1
                                logger.info(f"✅ Successfully synced user '{username}'")
                            else:
                                error_count += 1
                                logger.error(f"❌ Failed to sync user '{username}'")
                        else:
                            logger.debug(f"User '{username}' has default collections but no MCP server mapping")
                            skipped_count += 1
                    else:
                        logger.debug(f"User '{username}' has no default collections to sync")
                        skipped_count += 1

                except Exception as user_err:
                    error_count += 1
                    logger.error(f"Error processing user '{username}': {user_err}", exc_info=True)

            # Summary
            logger.info("=" * 60)
            logger.info("Sync Complete!")
            logger.info(f"  Successfully synced: {synced_count} users")
            logger.info(f"  Skipped (no collections): {skipped_count} users")
            logger.info(f"  Errors: {error_count} users")
            logger.info("=" * 60)

            return synced_count, skipped_count, error_count

    except Exception as e:
        logger.error(f"Fatal error during sync: {e}", exc_info=True)
        raise


def main():
    """Main entry point for the script."""
    logger.info("=" * 60)
    logger.info("Starting autocomplete sync for existing users...")
    logger.info("=" * 60)

    try:
        synced, skipped, errors = sync_all_users()

        if errors > 0:
            logger.warning(f"⚠️  Sync completed with {errors} error(s). Check logs above.")
            sys.exit(1)
        else:
            logger.info("✅ Sync completed successfully!")
            sys.exit(0)

    except Exception as e:
        logger.error(f"💥 Sync failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
