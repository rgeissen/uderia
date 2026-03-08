#!/usr/bin/env python3
"""
Test to verify profile information is stored in REST API session files.
"""

import requests
import json
import time
from pathlib import Path

BASE_URL = "http://127.0.0.1:5050"
API_V1_BASE = f"{BASE_URL}/api/v1"
AUTH_BASE = f"{BASE_URL}/api/v1/auth"

def test_profile_storage_in_rest_sessions():
    """Verify that profile_id is stored in REST API session files."""
    
    print("=" * 70)
    print("REST API - Profile Storage in Sessions Test")
    print("=" * 70)
    print()
    
    # Step 1: Login
    print("[1] Logging in...")
    response = requests.post(
        f"{AUTH_BASE}/login",
        json={"username": "admin", "password": "admin"}
    )
    
    jwt_token = response.json()['token']
    user_uuid = response.json()['user']['user_uuid']
    print(f"✓ Logged in as user: {user_uuid}")
    print()
    
    # Step 2: Get profile info
    print("[2] Getting profile information...")
    response = requests.get(
        f"{API_V1_BASE}/profiles",
        headers={"Authorization": f"Bearer {jwt_token}"}
    )
    
    profiles = response.json()
    default_profile_id = profiles.get('default_profile_id')
    profile = next((p for p in profiles.get('profiles', []) if p.get('id') == default_profile_id), None)
    
    print(f"✓ Default Profile ID: {default_profile_id}")
    print(f"  Name: {profile.get('name')}")
    print(f"  Color: {profile.get('color')}")
    print()
    
    # Step 3: Create session via REST
    print("[3] Creating session via REST API...")
    response = requests.post(
        f"{API_V1_BASE}/sessions",
        headers={"Authorization": f"Bearer {jwt_token}"}
    )
    
    session_id = response.json()['session_id']
    print(f"✓ Session created: {session_id}")
    print()
    
    # Step 4: Submit query
    print("[4] Submitting query...")
    response = requests.post(
        f"{API_V1_BASE}/sessions/{session_id}/query",
        headers={"Authorization": f"Bearer {jwt_token}"},
        json={"prompt": "Hello"}
    )
    
    task_id = response.json()['task_id']
    print(f"✓ Query submitted: {task_id}")
    print()
    
    # Step 5: Find and inspect session JSON file
    print("[5] Inspecting session JSON file...")
    
    project_root = Path(__file__).resolve().parents[2]
    sessions_base = project_root / 'tda_sessions' / user_uuid
    session_file = sessions_base / f"{session_id}.json"
    
    if not session_file.exists():
        print(f"❌ Session file not found: {session_file}")
        return
    
    with open(session_file, 'r') as f:
        session_data = json.load(f)
    
    print(f"✓ Session file found and loaded")
    print(f"  File path: {session_file}")
    print()
    
    # Step 6: Check for profile information
    print("[6] Checking for profile information in session...")
    
    print(f"\n  Session structure:")
    print(f"    - id: {session_data.get('id')}")
    print(f"    - provider: {session_data.get('provider')}")
    print(f"    - model: {session_data.get('model')}")
    print(f"    - profile_tag: {session_data.get('profile_tag')}")
    print(f"    - profile_id: {session_data.get('profile_id')}")
    
    profile_id_stored = session_data.get('profile_id')
    
    if not profile_id_stored:
        print(f"\n  ⚠️  WARNING: profile_id not found in session!")
    else:
        print(f"\n  ✓ profile_id is stored: {profile_id_stored}")
        
        if profile_id_stored == default_profile_id:
            print(f"  ✓ profile_id matches default profile!")
        else:
            print(f"  ⚠️  profile_id mismatch!")
            print(f"      Expected: {default_profile_id}")
            print(f"      Got: {profile_id_stored}")
    
    print()
    
    # Step 7: Summary
    print("=" * 70)
    if profile_id_stored:
        print("✅ Profile information IS being stored in REST sessions!")
        print("\n   The UI can now:")
        print("   • Look up the profile by profile_id")
        print("   • Display the profile color/badge in session list")
        print("   • Show provider information with correct branding")
    else:
        print("❌ Profile information is NOT being stored in REST sessions")
    print("=" * 70)

if __name__ == "__main__":
    test_profile_storage_in_rest_sessions()
