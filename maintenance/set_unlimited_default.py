#!/usr/bin/env python3
"""
Set Unlimited as the default consumption profile
"""
from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import ConsumptionProfile

def set_unlimited_as_default():
    """Set Unlimited profile as default"""
    with get_db_session() as session:
        # Get all profiles
        profiles = session.query(ConsumptionProfile).all()
        
        print("Current profiles:")
        for profile in profiles:
            print(f"  {profile.name}: is_default={profile.is_default}, id={profile.id}")
        
        # Find Unlimited profile
        unlimited = session.query(ConsumptionProfile).filter_by(name='Unlimited').first()
        
        if not unlimited:
            print("\n❌ Unlimited profile not found!")
            return False
        
        # Unset all defaults first
        for profile in profiles:
            if profile.is_default:
                print(f"\nUnsetting default for: {profile.name}")
                profile.is_default = False
        
        # Set Unlimited as default
        print(f"\n✅ Setting Unlimited as default profile (ID: {unlimited.id})")
        unlimited.is_default = True
        
        session.commit()
        
        print("\n✅ Done! Unlimited is now the default profile")
        
        # Verify
        print("\nUpdated profiles:")
        session.refresh(unlimited)
        profiles = session.query(ConsumptionProfile).all()
        for profile in profiles:
            print(f"  {profile.name}: is_default={profile.is_default}")
        
        return True

if __name__ == '__main__':
    set_unlimited_as_default()
