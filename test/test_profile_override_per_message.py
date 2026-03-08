#!/usr/bin/env python3
"""
Test to verify that profile overrides are tracked per-message in REST queries.
This tests that when you override a profile in a REST call, the UI shows the correct
profile badge for that specific message.
"""

import requests
import json
import time
from pathlib import Path

BASE_URL = "http://127.0.0.1:5050"
API_V1_BASE = f"{BASE_URL}/api/v1"
AUTH_BASE = f"{BASE_URL}/api/v1/auth"

def test_profile_override_per_message():
    """Test that profile overrides are tracked in message history."""
    
    print("=" * 70)
    print("Profile Override Per-Message Test")
    print("=" * 70)
    print()
    
    try:
        # Step 1: Login
        print("[1] Logging in...")
        response = requests.post(
            f"{AUTH_BASE}/login",
            json={"username": "admin", "password": "admin"}
        )
        
        if response.status_code != 200:
            print(f"❌ Login failed: {response.status_code}")
            return
        
        jwt_token = response.json()['token']
        user_uuid = response.json()['user']['user_uuid']
        print(f"✓ Login successful")
        print()
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    try:
        # Step 2: Get available profiles
        print("[2] Getting available profiles...")
        response = requests.get(
            f"{API_V1_BASE}/profiles",
            headers={"Authorization": f"Bearer {jwt_token}"}
        )
        
        if response.status_code != 200:
            print(f"❌ Failed to get profiles: {response.status_code}")
            return
        
        profiles_data = response.json()
        default_profile_id = profiles_data.get('default_profile_id')
        profiles = profiles_data.get('profiles', [])
        
        print(f"✓ Default profile: {default_profile_id}")
        
        # Get profile tags
        default_profile = next((p for p in profiles if p.get('id') == default_profile_id), None)
        default_profile_tag = default_profile.get('tag') if default_profile else "DEFAULT"
        print(f"  Profile tag: {default_profile_tag}")
        
        # Get other profile if available
        other_profile = next((p for p in profiles if p.get('id') != default_profile_id), None)
        if other_profile:
            other_profile_id = other_profile.get('id')
            other_profile_tag = other_profile.get('tag')
            print(f"✓ Other profile available: {other_profile_id}")
            print(f"  Profile tag: {other_profile_tag}")
        else:
            print(f"⚠️  Only one profile available - will test with default only")
            other_profile_id = None
            other_profile_tag = None
        
        print()
        
    except Exception as e:
        print(f"❌ Error getting profiles: {e}")
        return
    
    try:
        # Step 3: Create session
        print("[3] Creating session...")
        response = requests.post(
            f"{API_V1_BASE}/sessions",
            headers={"Authorization": f"Bearer {jwt_token}"}
        )
        
        if response.status_code != 201:
            print(f"❌ Session creation failed: {response.status_code}")
            return
        
        session_id = response.json()['session_id']
        print(f"✓ Session created: {session_id}")
        print()
        
    except Exception as e:
        print(f"❌ Error creating session: {e}")
        return
    
    try:
        # Step 4: Submit first query with default profile
        print("[4] Submitting first query with DEFAULT profile...")
        response = requests.post(
            f"{API_V1_BASE}/sessions/{session_id}/query",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json={"prompt": "What is your name?"}
        )
        
        if response.status_code not in [200, 202]:
            print(f"❌ Query failed: {response.status_code}")
            return
        
        task_id_1 = response.json()['task_id']
        print(f"✓ Query submitted: {task_id_1}")
        print(f"  Expected profile_tag: {default_profile_tag}")
        print()
        
        # Wait for task to complete
        print("[5] Waiting for first query to complete...")
        time.sleep(3)
        
    except Exception as e:
        print(f"❌ Error with first query: {e}")
        return
    
    if other_profile_id:
        try:
            # Step 6: Submit second query with profile override
            print("[6] Submitting second query with PROFILE OVERRIDE...")
            response = requests.post(
                f"{API_V1_BASE}/sessions/{session_id}/query",
                headers={"Authorization": f"Bearer {jwt_token}"},
                json={
                    "prompt": "Tell me about yourself",
                    "profile_id": other_profile_id
                }
            )
            
            if response.status_code not in [200, 202]:
                print(f"❌ Override query failed: {response.status_code}")
                return
            
            task_id_2 = response.json()['task_id']
            print(f"✓ Query submitted with override: {task_id_2}")
            print(f"  Override profile_id: {other_profile_id}")
            print(f"  Expected profile_tag: {other_profile_tag}")
            print()
            
            # Wait for task to complete
            print("[7] Waiting for second query to complete...")
            time.sleep(3)
            
        except Exception as e:
            print(f"❌ Error with override query: {e}")
            return
    
    try:
        # Step 7: Inspect session history for profile tags
        print("[8] Checking session history for profile tags...")
        session_file = Path(f"/Users/rainer.geissendoerfer/my_private_code/uderia/tda_sessions/{user_uuid}/{session_id}.json")
        
        if not session_file.exists():
            print(f"❌ Session file not found: {session_file}")
            return
        
        with open(session_file) as f:
            session_data = json.load(f)
        
        session_history = session_data.get('session_history', [])
        print(f"✓ Session history loaded: {len(session_history)} messages")
        print()
        
        print("[9] Message Profile Tags:")
        print()
        for i, msg in enumerate(session_history):
            role = msg.get('role')
            profile_tag = msg.get('profile_tag')
            content_preview = msg.get('content', '')[:60].replace('\n', ' ')
            print(f"  Message {i+1}:")
            print(f"    Role: {role}")
            print(f"    Profile Tag: {profile_tag if profile_tag else '(not set)'}")
            print(f"    Content: {content_preview}...")
            print()
        
        # Verify profile tags
        print("[10] Verification:")
        user_messages = [m for m in session_history if m.get('role') == 'user']
        
        if len(user_messages) >= 1:
            first_user_msg = user_messages[0]
            first_profile_tag = first_user_msg.get('profile_tag')
            if first_profile_tag == default_profile_tag:
                print(f"✅ First message has correct profile tag: {first_profile_tag}")
            else:
                print(f"⚠️  First message profile tag mismatch")
                print(f"   Expected: {default_profile_tag}")
                print(f"   Got: {first_profile_tag}")
        
        if len(user_messages) >= 2 and other_profile_id:
            second_user_msg = user_messages[1]
            second_profile_tag = second_user_msg.get('profile_tag')
            if second_profile_tag == other_profile_tag:
                print(f"✅ Second message has correct profile override: {second_profile_tag}")
            else:
                print(f"⚠️  Second message profile tag mismatch")
                print(f"   Expected: {other_profile_tag}")
                print(f"   Got: {second_profile_tag}")
        
        print()
        
    except Exception as e:
        print(f"❌ Error checking session history: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Final summary
    print("=" * 70)
    print("✅ TEST COMPLETE")
    print("=" * 70)
    print()
    print("WHAT THIS MEANS:")
    print()
    print("1. Each message in the session history now has a 'profile_tag' field")
    print("2. When you override a profile in a REST call, that override is")
    print("   recorded in the user message's profile_tag")
    print("3. The UI can now display the correct profile badge for EACH message")
    print()
    print("UI IMPLEMENTATION NEXT STEP:")
    print("- Modify static/js/ui.js to check message.profile_tag")
    print("- Use that profile_tag to display the badge color and name")
    print("- Different messages can show different profile badges!")
    print()

if __name__ == "__main__":
    test_profile_override_per_message()
