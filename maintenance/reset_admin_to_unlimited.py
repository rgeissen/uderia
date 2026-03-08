#!/usr/bin/env python3
"""
Reset admin user to use Unlimited profile
"""
from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, ConsumptionProfile

def reset_admin_profile():
    """Reset admin user to Unlimited profile"""
    with get_db_session() as session:
        # Get admin user
        admin = session.query(User).filter_by(username='admin').first()
        
        if not admin:
            print("❌ Admin user not found!")
            return False
        
        print(f"Current admin profile_id: {admin.consumption_profile_id}")
        
        # Get Unlimited profile
        unlimited = session.query(ConsumptionProfile).filter_by(name='Unlimited').first()
        
        if not unlimited:
            print("❌ Unlimited profile not found!")
            return False
        
        print(f"Unlimited profile ID: {unlimited.id}")
        
        # Assign Unlimited profile to admin
        admin.consumption_profile_id = unlimited.id
        
        session.commit()
        session.refresh(admin)
        
        print(f"\n✅ Admin user now assigned to Unlimited profile (ID: {admin.consumption_profile_id})")
        
        return True

if __name__ == '__main__':
    reset_admin_profile()
