#!/usr/bin/env python3
"""
Check user's consumption profile assignment
"""

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, ConsumptionProfile

def check_user_profile(username: str):
    """Check which profile is assigned to a user."""
    with get_db_session() as session:
        user = session.query(User).filter_by(username=username).first()
        
        if not user:
            print(f"❌ User '{username}' not found")
            return
        
        print(f"\n=== User: {username} ===")
        print(f"User ID: {user.id}")
        print(f"Is Admin: {user.is_admin}")
        print(f"Consumption Profile ID: {user.consumption_profile_id}")
        
        if user.consumption_profile_id:
            profile = session.query(ConsumptionProfile).filter_by(
                id=user.consumption_profile_id
            ).first()
            
            if profile:
                print(f"\n=== Assigned Profile ===")
                print(f"Profile Name: {profile.name}")
                print(f"Is Active: {profile.is_active}")
                print(f"Is Default: {profile.is_default}")
                print(f"Prompts/Hour: {profile.prompts_per_hour}")
                print(f"Prompts/Day: {profile.prompts_per_day}")
                print(f"Config Changes/Hour: {profile.config_changes_per_hour}")
                print(f"Input Tokens/Month: {profile.input_tokens_per_month}")
                print(f"Output Tokens/Month: {profile.output_tokens_per_month}")
            else:
                print(f"❌ Profile ID {user.consumption_profile_id} not found!")
        else:
            print("\n⚠️  No profile assigned - will use default profile")
            
            # Show default profile
            default_profile = session.query(ConsumptionProfile).filter_by(
                is_default=True
            ).first()
            
            if default_profile:
                print(f"\n=== Default Profile ===")
                print(f"Profile Name: {default_profile.name}")
                print(f"Is Active: {default_profile.is_active}")
                print(f"Prompts/Hour: {default_profile.prompts_per_hour}")
                print(f"Prompts/Day: {default_profile.prompts_per_day}")
        
        print("\n=== All Available Profiles ===")
        all_profiles = session.query(ConsumptionProfile).all()
        for p in all_profiles:
            print(f"\nID: {p.id}")
            print(f"  Name: {p.name}")
            print(f"  Active: {p.is_active}")
            print(f"  Default: {p.is_default}")
            print(f"  Prompts/Hour: {p.prompts_per_hour}")
            print(f"  Prompts/Day: {p.prompts_per_day}")

if __name__ == "__main__":
    check_user_profile("test")
    print("\n" + "="*50 + "\n")
    check_user_profile("admin")
