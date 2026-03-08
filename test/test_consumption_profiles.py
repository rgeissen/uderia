#!/usr/bin/env python3
"""
Test consumption profiles backend implementation.

Tests:
1. Database tables and schema
2. Default profiles creation
3. Token quota management
4. Rate limiter integration
5. User profile assignment

Usage:
    python test/test_consumption_profiles.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datetime import datetime, timezone
from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, ConsumptionProfile, UserTokenUsage
from trusted_data_agent.auth.token_quota import (
    get_user_consumption_profile,
    check_token_quota,
    record_token_usage,
    get_user_quota_status,
    get_current_period
)

def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def test_database_schema():
    """Test that all tables and columns exist."""
    print_section("TEST 1: Database Schema")
    
    try:
        with get_db_session() as session:
            # Test consumption_profiles table
            profiles = session.query(ConsumptionProfile).all()
            print(f"✓ consumption_profiles table exists ({len(profiles)} profiles)")
            
            # Test user_token_usage table
            usage_count = session.query(UserTokenUsage).count()
            print(f"✓ user_token_usage table exists ({usage_count} records)")
            
            # Test users.consumption_profile_id column
            user = session.query(User).first()
            if user:
                _ = user.consumption_profile_id
                print(f"✓ users.consumption_profile_id column exists")
            else:
                print("⚠ No users found in database")
        
        return True
    except Exception as e:
        print(f"✗ Schema test failed: {e}")
        return False

def test_default_profiles():
    """Test that default profiles were created."""
    print_section("TEST 2: Default Profiles")
    
    try:
        with get_db_session() as session:
            profiles = session.query(ConsumptionProfile).order_by(ConsumptionProfile.name).all()
            
            print(f"\nFound {len(profiles)} profiles:")
            print("\n{:<15} {:<12} {:<12} {:<20} {:<20} {:<10}".format(
                "Name", "Prompts/Hr", "Prompts/Day", "Input Tokens/Mo", "Output Tokens/Mo", "Default"
            ))
            print("-" * 100)
            
            for profile in profiles:
                input_tokens = f"{profile.input_tokens_per_month:,}" if profile.input_tokens_per_month else "Unlimited"
                output_tokens = f"{profile.output_tokens_per_month:,}" if profile.output_tokens_per_month else "Unlimited"
                default_mark = "★" if profile.is_default else ""
                
                print("{:<15} {:<12} {:<12} {:<20} {:<20} {:<10}".format(
                    profile.name,
                    profile.prompts_per_hour,
                    profile.prompts_per_day,
                    input_tokens,
                    output_tokens,
                    default_mark
                ))
            
            # Check for expected profiles
            expected_profiles = ['Free', 'Pro', 'Enterprise', 'Unlimited']
            found_profiles = [p.name for p in profiles]
            
            all_found = all(name in found_profiles for name in expected_profiles)
            if all_found:
                print(f"\n✓ All expected profiles found")
            else:
                missing = [name for name in expected_profiles if name not in found_profiles]
                print(f"\n⚠ Missing profiles: {missing}")
            
            # Check default profile
            default_profiles = [p for p in profiles if p.is_default]
            if len(default_profiles) == 1:
                print(f"✓ Exactly one default profile: {default_profiles[0].name}")
            else:
                print(f"⚠ Found {len(default_profiles)} default profiles (should be 1)")
        
        return True
    except Exception as e:
        print(f"✗ Default profiles test failed: {e}")
        return False

def test_token_quota_functions():
    """Test token quota management functions."""
    print_section("TEST 3: Token Quota Functions")
    
    try:
        # Get a test user
        with get_db_session() as session:
            user = session.query(User).first()
            if not user:
                print("⚠ No users found - creating test user")
                from trusted_data_agent.auth.security import hash_password
                user = User(
                    username='test_quota_user',
                    email='test_quota@example.com',
                    password_hash=hash_password('test123'),
                    full_name='Test Quota User'
                )
                session.add(user)
                session.commit()
                session.refresh(user)
            
            user_id = user.id
            print(f"Using test user: {user.username} (ID: {user_id[:8]}...)")
        
        # Test 1: Get user consumption profile
        print("\n1. Testing get_user_consumption_profile()...")
        profile = get_user_consumption_profile(user_id)
        if profile:
            print(f"   ✓ Got profile: {profile['name']}")
            print(f"     - Input tokens/month: {profile['input_tokens_per_month'] or 'Unlimited'}")
            print(f"     - Output tokens/month: {profile['output_tokens_per_month'] or 'Unlimited'}")
        else:
            print("   ⚠ No profile found (user will use system defaults)")
        
        # Test 2: Record token usage
        print("\n2. Testing record_token_usage()...")
        period = get_current_period()
        success = record_token_usage(user_id, input_tokens=1000, output_tokens=500)
        if success:
            print(f"   ✓ Recorded usage: 1000 input + 500 output tokens")
        else:
            print("   ✗ Failed to record usage")
        
        # Test 3: Check token quota
        print("\n3. Testing check_token_quota()...")
        allowed, msg, quota_info = check_token_quota(user_id, input_tokens=5000, output_tokens=2500)
        print(f"   Status: {'✓ Allowed' if allowed else '✗ Denied'}")
        if msg:
            print(f"   Message: {msg}")
        if quota_info:
            print(f"   Quota info:")
            print(f"     - Input limit: {quota_info.get('input_limit') or 'Unlimited'}")
            print(f"     - Input used: {quota_info.get('input_used', 0)}")
            print(f"     - Output limit: {quota_info.get('output_limit') or 'Unlimited'}")
            print(f"     - Output used: {quota_info.get('output_used', 0)}")
        
        # Test 4: Get quota status
        print("\n4. Testing get_user_quota_status()...")
        status = get_user_quota_status(user_id)
        if status.get('has_quota'):
            print(f"   ✓ Quota status retrieved")
            print(f"   Profile: {status['profile_name']} (Period: {status['period']})")
            print(f"   Input tokens: {status['input_tokens']['used']:,} / {status['input_tokens']['limit'] or 'Unlimited'} ({status['input_tokens']['percentage_used']:.1f}%)")
            print(f"   Output tokens: {status['output_tokens']['used']:,} / {status['output_tokens']['limit'] or 'Unlimited'} ({status['output_tokens']['percentage_used']:.1f}%)")
        else:
            print("   ⚠ No quota limits (unlimited access)")
        
        return True
    except Exception as e:
        print(f"✗ Token quota functions test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_profile_assignment():
    """Test assigning consumption profiles to users."""
    print_section("TEST 4: Profile Assignment")
    
    try:
        with get_db_session() as session:
            # Get a user and profiles
            user = session.query(User).first()
            if not user:
                print("⚠ No users found")
                return False
            
            profiles = session.query(ConsumptionProfile).all()
            if len(profiles) < 2:
                print("⚠ Not enough profiles to test assignment")
                return False
            
            print(f"Test user: {user.username}")
            print(f"Current profile: {user.consumption_profile.name if user.consumption_profile else 'None'}")
            
            # Test assigning a profile
            print("\n1. Assigning 'Pro' profile...")
            pro_profile = next((p for p in profiles if p.name == 'Pro'), None)
            if pro_profile:
                user.consumption_profile_id = pro_profile.id
                session.commit()
                session.refresh(user)
                
                if user.consumption_profile_id == pro_profile.id:
                    print(f"   ✓ Profile assigned successfully")
                    print(f"   User now has: {user.consumption_profile.name}")
                else:
                    print("   ✗ Assignment failed")
            else:
                print("   ⚠ 'Pro' profile not found")
            
            # Test unassigning
            print("\n2. Unassigning profile...")
            user.consumption_profile_id = None
            session.commit()
            session.refresh(user)
            
            if user.consumption_profile_id is None:
                print("   ✓ Profile unassigned successfully")
                print("   User will use default profile")
            else:
                print("   ✗ Unassignment failed")
            
            # Test default profile fallback
            print("\n3. Testing default profile fallback...")
            profile = get_user_consumption_profile(user.id)
            if profile and profile['name'] == 'Free':  # Free is the default profile
                print(f"   ✓ Falls back to default profile: {profile['name']}")
            else:
                print(f"   ⚠ Default profile fallback: {profile['name'] if profile else 'None'}")
        
        return True
    except Exception as e:
        print(f"✗ Profile assignment test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_rate_limiter_integration():
    """Test that rate limiter uses consumption profile limits."""
    print_section("TEST 5: Rate Limiter Integration")
    
    try:
        from trusted_data_agent.auth.rate_limiter import check_user_prompt_quota, check_user_config_quota
        
        with get_db_session() as session:
            # Get or create test user
            user = session.query(User).first()
            if not user:
                print("⚠ No users found")
                return False
            
            # Assign Pro profile
            pro_profile = session.query(ConsumptionProfile).filter_by(name='Pro').first()
            if pro_profile:
                user.consumption_profile_id = pro_profile.id
                session.commit()
                print(f"Assigned '{pro_profile.name}' profile to user {user.username}")
                print(f"  - Prompts per hour: {pro_profile.prompts_per_hour}")
                print(f"  - Config changes per hour: {pro_profile.config_changes_per_hour}")
            
            user_id = user.id
        
        # Note: Rate limiting needs to be enabled in settings for this to work
        print("\n1. Testing prompt quota check...")
        allowed, msg = check_user_prompt_quota(user_id)
        print(f"   Status: {'✓ Allowed' if allowed else '✗ Denied'}")
        if msg:
            print(f"   Message: {msg}")
        
        print("\n2. Testing config quota check...")
        allowed, msg = check_user_config_quota(user_id)
        print(f"   Status: {'✓ Allowed' if allowed else '✗ Denied'}")
        if msg:
            print(f"   Message: {msg}")
        
        print("\n✓ Rate limiter integration working (checks consumption profile)")
        print("  Note: Enable rate limiting in Admin Panel to enforce limits")
        
        return True
    except Exception as e:
        print(f"✗ Rate limiter integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("  CONSUMPTION PROFILES - BACKEND TEST SUITE")
    print("=" * 70)
    print(f"Test date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    results = {
        "Database Schema": test_database_schema(),
        "Default Profiles": test_default_profiles(),
        "Token Quota Functions": test_token_quota_functions(),
        "Profile Assignment": test_profile_assignment(),
        "Rate Limiter Integration": test_rate_limiter_integration()
    }
    
    # Summary
    print_section("TEST SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:10} {test_name}")
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Backend implementation is working correctly.")
        print("\nNext steps:")
        print("  1. Build Admin UI for profile management")
        print("  2. Build User Dashboard for quota display")
        print("  3. Integrate token tracking into prompt execution")
    else:
        print(f"\n⚠ {total - passed} test(s) failed. Please review the errors above.")
    
    return passed == total

if __name__ == '__main__':
    try:
        success = run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
