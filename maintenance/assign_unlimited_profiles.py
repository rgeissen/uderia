#!/usr/bin/env python3
"""
Assign all existing users to the Unlimited consumption profile.

This ensures existing users continue to have unrestricted access while
the consumption profile system is being rolled out.

Usage:
    python maintenance/assign_unlimited_profiles.py
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, ConsumptionProfile

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def assign_unlimited_to_all_users():
    """Assign Unlimited profile to all existing users."""
    try:
        with get_db_session() as session:
            # Get the Unlimited profile
            unlimited_profile = session.query(ConsumptionProfile).filter_by(
                name='Unlimited'
            ).first()
            
            if not unlimited_profile:
                logger.error("Unlimited profile not found! Run migrate_consumption_profiles.py first.")
                return False
            
            logger.info(f"Found Unlimited profile (ID: {unlimited_profile.id})")
            
            # Get all users without a profile
            users_without_profile = session.query(User).filter(
                User.consumption_profile_id.is_(None)
            ).all()
            
            logger.info(f"Found {len(users_without_profile)} users without a consumption profile")
            
            if len(users_without_profile) == 0:
                logger.info("All users already have profiles assigned")
                return True
            
            # Assign Unlimited profile to all users without a profile
            for user in users_without_profile:
                user.consumption_profile_id = unlimited_profile.id
                logger.info(f"  Assigned Unlimited profile to user: {user.username}")
            
            session.commit()
            
            logger.info("✓ All users now have Unlimited profile")
            return True
            
    except Exception as e:
        logger.error(f"Error assigning profiles: {e}", exc_info=True)
        return False


def set_unlimited_as_default():
    """Set Unlimited profile as the default for new users."""
    try:
        with get_db_session() as session:
            # Unset all defaults
            session.query(ConsumptionProfile).update({'is_default': False})
            
            # Set Unlimited as default
            unlimited_profile = session.query(ConsumptionProfile).filter_by(
                name='Unlimited'
            ).first()
            
            if unlimited_profile:
                unlimited_profile.is_default = True
                session.commit()
                logger.info("✓ Set Unlimited profile as default for new users")
                return True
            else:
                logger.error("Unlimited profile not found")
                return False
                
    except Exception as e:
        logger.error(f"Error setting default: {e}", exc_info=True)
        return False


def show_summary():
    """Show summary of profile assignments."""
    try:
        with get_db_session() as session:
            profiles = session.query(ConsumptionProfile).all()
            
            print("\n" + "=" * 70)
            print("  CONSUMPTION PROFILE SUMMARY")
            print("=" * 70)
            
            for profile in profiles:
                user_count = len(profile.users) if profile.users else 0
                default_mark = " (DEFAULT)" if profile.is_default else ""
                print(f"\n{profile.name}{default_mark}:")
                print(f"  - Users assigned: {user_count}")
                print(f"  - Prompts/hour: {profile.prompts_per_hour}")
                print(f"  - Prompts/day: {profile.prompts_per_day}")
                
                if profile.input_tokens_per_month:
                    print(f"  - Input tokens/month: {profile.input_tokens_per_month:,}")
                else:
                    print(f"  - Input tokens/month: Unlimited")
                    
                if profile.output_tokens_per_month:
                    print(f"  - Output tokens/month: {profile.output_tokens_per_month:,}")
                else:
                    print(f"  - Output tokens/month: Unlimited")
            
            print("\n" + "=" * 70)
            
    except Exception as e:
        logger.error(f"Error showing summary: {e}", exc_info=True)


def main():
    """Main execution."""
    print("=" * 70)
    print("  ASSIGN UNLIMITED PROFILES TO EXISTING USERS")
    print("=" * 70)
    print("\nThis script will:")
    print("  1. Assign Unlimited profile to all existing users")
    print("  2. Set Unlimited as the default profile for new users")
    print("\nThis ensures no disruption while you set up the UI.\n")
    
    # Assign unlimited to existing users
    if not assign_unlimited_to_all_users():
        logger.error("Failed to assign profiles to users")
        return False
    
    # Set unlimited as default
    if not set_unlimited_as_default():
        logger.error("Failed to set default profile")
        return False
    
    # Show summary
    show_summary()
    
    print("\n✓ Migration complete!")
    print("\nNext steps:")
    print("  1. Build Admin UI for profile management")
    print("  2. Assign specific profiles to users as needed")
    print("  3. Eventually change default from Unlimited to Free for new users")
    
    return True


if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
