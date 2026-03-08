#!/usr/bin/env python3
"""Check token usage in database"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.trusted_data_agent.auth.database import get_db_session
from src.trusted_data_agent.auth.models import User, UserTokenUsage
from datetime import datetime

def check_token_usage():
    """Check token usage records"""
    print("Checking token usage...")
    
    with get_db_session() as session:
        # Get all users
        users = session.query(User).all()
        print(f"\n=== Users ({len(users)} total) ===")
        for user in users:
            print(f"  - {user.username} (ID: {user.id}, Profile Tier: {user.profile_tier})")
        
        # Get all token usage records
        usage_records = session.query(UserTokenUsage).all()
        print(f"\n=== Token Usage Records ({len(usage_records)} total) ===")
        for record in usage_records:
            user = session.query(User).filter_by(id=record.user_id).first()
            username = user.username if user else "UNKNOWN"
            print(f"  - User: {username} ({record.user_id[:8]}...)")
            print(f"    Period: {record.period}")
            print(f"    Input: {record.input_tokens_used:,}")
            print(f"    Output: {record.output_tokens_used:,}")
            print(f"    Total: {record.total_tokens_used:,}")
            print(f"    Last usage: {record.last_usage_at}")
            print()
        
        # Check current period
        current_period = datetime.now().strftime("%Y-%m")
        print(f"\n=== Current Period: {current_period} ===")
        current_usage = session.query(UserTokenUsage).filter_by(period=current_period).all()
        print(f"Records for current period: {len(current_usage)}")

if __name__ == '__main__':
    check_token_usage()
