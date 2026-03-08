#!/usr/bin/env python3
"""
Reconcile session counts in user_consumption table with actual distinct sessions.

This script fixes discrepancies where the total_sessions counter doesn't match
the actual count of unique session_ids in the consumption_turns table.

Usage:
    python maintenance/reconcile_session_counts.py [--user-id USER_ID]
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.consumption_manager import ConsumptionManager
from trusted_data_agent.auth.models import UserConsumption

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def reconcile_all_users():
    """Reconcile session counts for all users."""
    try:
        with get_db_session() as session:
            manager = ConsumptionManager(session)
            
            # Get all users with consumption records
            users = session.query(UserConsumption.user_id).all()
            
            if not users:
                print("No users found with consumption records.")
                return
            
            print(f"\n{'='*80}")
            print(f"Reconciling session counts for {len(users)} users")
            print(f"{'='*80}\n")
            
            total_fixed = 0
            
            for (user_id,) in users:
                result = manager.reconcile_session_count(user_id)
                
                if result['difference'] != 0:
                    print(f"User {user_id[:8]}... : {result['old_count']} → {result['new_count']} "
                          f"(diff: {result['difference']:+d})")
                    total_fixed += 1
                else:
                    print(f"User {user_id[:8]}... : {result['old_count']} ✓")
            
            print(f"\n{'='*80}")
            print(f"Reconciliation complete: {total_fixed} users corrected")
            print(f"{'='*80}\n")
            
    except Exception as e:
        logger.error(f"Error during reconciliation: {e}", exc_info=True)
        return False
    
    return True


def reconcile_single_user(user_id: str):
    """Reconcile session count for a single user."""
    try:
        with get_db_session() as session:
            manager = ConsumptionManager(session)
            result = manager.reconcile_session_count(user_id)
            
            print(f"\n{'='*80}")
            print(f"Reconciliation for user: {user_id}")
            print(f"{'='*80}")
            print(f"Old count: {result['old_count']}")
            print(f"New count: {result['new_count']}")
            print(f"Difference: {result['difference']:+d}")
            print(f"{'='*80}\n")
            
            if result['difference'] == 0:
                print("✓ No correction needed")
            else:
                print(f"✓ Corrected session count")
            
    except Exception as e:
        logger.error(f"Error reconciling user {user_id}: {e}", exc_info=True)
        return False
    
    return True


def main():
    """Main execution."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Reconcile session counts in consumption database'
    )
    parser.add_argument(
        '--user-id',
        help='Reconcile specific user (default: all users)'
    )
    
    args = parser.parse_args()
    
    try:
        if args.user_id:
            success = reconcile_single_user(args.user_id)
        else:
            success = reconcile_all_users()
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
