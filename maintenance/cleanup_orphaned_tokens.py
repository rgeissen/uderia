#!/usr/bin/env python3
"""
Clean up orphaned authentication tokens from the database.

This script removes:
1. Tokens for users that no longer exist
2. Expired tokens (older than expiration date)

Run this after database migrations that change user IDs.
"""

import sys
import os
from datetime import datetime, timezone

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, AuthToken


def cleanup_orphaned_tokens():
    """Remove tokens for non-existent users and expired tokens."""
    
    with get_db_session() as session:
        # Get all tokens
        all_tokens = session.query(AuthToken).all()
        print(f"Found {len(all_tokens)} total tokens")
        
        orphaned_count = 0
        expired_count = 0
        valid_count = 0
        
        now = datetime.now(timezone.utc)
        
        for token in all_tokens:
            # Check if user exists
            user = session.query(User).filter_by(id=token.user_id).first()
            
            if not user:
                print(f"  Removing orphaned token for non-existent user {token.user_id}")
                session.delete(token)
                orphaned_count += 1
            elif token.expires_at < now:
                print(f"  Removing expired token for user {user.username} (expired: {token.expires_at})")
                session.delete(token)
                expired_count += 1
            else:
                valid_count += 1
        
        session.commit()
        
        print(f"\nCleanup complete:")
        print(f"  - Orphaned tokens removed: {orphaned_count}")
        print(f"  - Expired tokens removed: {expired_count}")
        print(f"  - Valid tokens remaining: {valid_count}")
        
        if orphaned_count > 0:
            print(f"\nNote: Users with orphaned tokens will need to log in again.")


if __name__ == "__main__":
    print("Starting authentication token cleanup...")
    print("=" * 60)
    
    try:
        cleanup_orphaned_tokens()
        print("\n✓ Token cleanup completed successfully")
    except Exception as e:
        print(f"\n✗ Error during cleanup: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
