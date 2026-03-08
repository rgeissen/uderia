#!/usr/bin/env python3
"""
Test to demonstrate optional profile_id parameter in REST queries.
"""

import requests
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:5050"
API_V1_BASE = f"{BASE_URL}/api/v1"
AUTH_BASE = f"{BASE_URL}/api/v1/auth"

def test_profile_override():
    """Test that profile_id can be optionally specified in REST queries."""
    
    print("=" * 70)
    print("Profile Override Test")
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
        print(f"  Available profiles: {len(profiles)}")
        for p in profiles:
            marker = "✓" if p.get('id') == default_profile_id else " "
            print(f"  {marker} {p.get('id')}: {p.get('name')}")
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
        # Step 4: Execute query WITHOUT profile_id (should use default)
        print("[4] Query WITHOUT profile_id override (uses default)...")
        response = requests.post(
            f"{API_V1_BASE}/sessions/{session_id}/query",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json={"prompt": "What is your name?"}
        )
        
        if response.status_code not in [200, 202]:
            print(f"❌ Query failed: {response.status_code}")
            return
        
        task_id_default = response.json()['task_id']
        print(f"✓ Query submitted: {task_id_default}")
        
        # Check which profile was used
        session_file = Path(f"/Users/rainer.geissendoerfer/my_private_code/uderia/tda_sessions/{user_uuid}/{session_id}.json")
        with open(session_file) as f:
            session_data = json.load(f)
        
        profile_used = session_data.get('profile_id')
        print(f"  Profile used: {profile_used}")
        print(f"  Expected: {default_profile_id}")
        print(f"  Match: {'✅ YES' if profile_used == default_profile_id else '❌ NO'}")
        print()
        
    except Exception as e:
        print(f"❌ Error with default query: {e}")
        return
    
    try:
        # Step 5: Try to execute query WITH profile_id override (if multiple profiles exist)
        print("[5] Query WITH profile_id override (if available)...")
        other_profile = next((p.get('id') for p in profiles if p.get('id') != default_profile_id), None)
        
        if other_profile:
            response = requests.post(
                f"{API_V1_BASE}/sessions/{session_id}/query",
                headers={"Authorization": f"Bearer {jwt_token}"},
                json={
                    "prompt": "Tell me about yourself",
                    "profile_id": other_profile
                }
            )
            
            if response.status_code not in [200, 202]:
                print(f"⚠️  Override query failed: {response.status_code}")
                if response.status_code == 400:
                    print(f"   Error: {response.json().get('error')}")
            else:
                task_id_override = response.json()['task_id']
                print(f"✓ Query submitted with profile override: {task_id_override}")
                print(f"  Profile override: {other_profile}")
                print()
        else:
            print("⚠️  Only one profile available - cannot test override")
            print(f"   (You can test override with profile_id in request body)")
            print()
        
    except Exception as e:
        print(f"⚠️  Error with override query: {e}")
    
    # Final summary
    print("=" * 70)
    print("✅ TEST COMPLETE")
    print("=" * 70)
    print()
    print("USAGE:")
    print()
    print("1. Query with DEFAULT profile:")
    print("   POST /v1/sessions/{id}/query")
    print("   { \"prompt\": \"Your question here\" }")
    print()
    print("2. Query with SPECIFIC profile override:")
    print("   POST /v1/sessions/{id}/query")
    print("   { \"prompt\": \"Your question here\", \"profile_id\": \"profile-xxx\" }")
    print()
    print("If profile_id is not specified, defaults to user's default profile.")
    print()

if __name__ == "__main__":
    test_profile_override()
