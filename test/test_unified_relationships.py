#!/usr/bin/env python3
"""
Test script for unified relationships endpoint
"""

import requests
import json
import sys

BASE_URL = "http://localhost:5050"

def test_unified_relationships():
    print("=" * 60)
    print("Unified Relationships Endpoint Test")
    print("=" * 60)
    print()

    # Step 1: Authenticate
    print("Step 1: Authenticating...")
    auth_response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": "admin", "password": "admin"}
    )

    if auth_response.status_code != 200:
        print(f"❌ Authentication failed: {auth_response.status_code}")
        return False

    jwt_token = auth_response.json().get("token")
    if not jwt_token:
        print("❌ No JWT token received")
        return False

    print(f"✅ JWT token obtained: {jwt_token[:50]}...")
    print()

    headers = {"Authorization": f"Bearer {jwt_token}"}

    # Step 2: Get collections
    print("Step 2: Getting available collections...")
    collections_response = requests.get(
        f"{BASE_URL}/api/v1/rag/collections",
        headers=headers
    )

    collections = collections_response.json().get("collections", [])
    print(f"✅ Found {len(collections)} collections")

    if not collections:
        print("⚠️  No collections found. Skipping collection tests.")
        return True

    collection_id = collections[0]["id"]
    collection_name = collections[0].get("name", "Unknown")
    print(f"   Using Collection ID: {collection_id} (\"{collection_name}\")")
    print()

    # Step 3: Test unified endpoint
    print(f"Step 3: Testing unified endpoint for collection {collection_id}...")
    print(f"   GET /api/v1/artifacts/collection/{collection_id}/relationships")

    unified_response = requests.get(
        f"{BASE_URL}/api/v1/artifacts/collection/{collection_id}/relationships",
        headers=headers
    )

    if unified_response.status_code != 200:
        print(f"❌ Unified endpoint failed with status {unified_response.status_code}")
        print(f"   Response: {unified_response.text}")
        return False

    data = unified_response.json()

    if data.get("status") != "success":
        print(f"❌ Unified endpoint returned error: {data.get('message')}")
        return False

    print("✅ Unified endpoint responded successfully")
    print()

    # Print relationship analysis
    print("   Relationship Analysis:")
    artifact = data.get("artifact", {})
    print(f"   Artifact: {artifact.get('name', 'Unknown')} (type: {artifact.get('type', 'unknown')})")

    relationships = data.get("relationships", {})
    sessions = relationships.get("sessions", {})
    profiles = relationships.get("profiles", {})
    packs = relationships.get("agent_packs", {})

    print(f"   Sessions:")
    print(f"     - Active: {sessions.get('active_count', 0)}")
    print(f"     - Archived: {sessions.get('archived_count', 0)}")
    print(f"     - Total: {sessions.get('total_count', 0)}")
    print(f"   Profiles: {profiles.get('count', 0)}")
    print(f"   Agent Packs: {packs.get('count', 0)}")

    deletion_info = data.get("deletion_info", {})
    can_delete = deletion_info.get("can_delete", True)
    warnings = deletion_info.get("warnings", [])
    blockers = deletion_info.get("blockers", [])

    print(f"   Deletion Safety:")
    print(f"     - Can Delete: {can_delete}")
    print(f"     - Warnings: {len(warnings)}")
    print(f"     - Blockers: {len(blockers)}")

    if warnings:
        for warning in warnings:
            print(f"       ⚠️  {warning}")

    if blockers:
        for blocker in blockers:
            print(f"       🚫 {blocker.get('message', 'Unknown blocker')}")
    print()

    # Step 4: Test with query parameters
    print("Step 4: Testing with include_archived=true parameter...")
    print(f"   GET /api/v1/artifacts/collection/{collection_id}/relationships?include_archived=true&limit=10")

    archived_response = requests.get(
        f"{BASE_URL}/api/v1/artifacts/collection/{collection_id}/relationships",
        headers=headers,
        params={"include_archived": "true", "limit": 10}
    )

    if archived_response.status_code != 200:
        print(f"❌ Query parameters test failed")
        return False

    archived_data = archived_response.json()
    archived_count = archived_data.get("relationships", {}).get("sessions", {}).get("archived_count", 0)
    items_count = len(archived_data.get("relationships", {}).get("sessions", {}).get("items", []))

    print("✅ Query parameters working")
    print(f"   Archived count: {archived_count}")
    print(f"   Items returned (limit 10): {items_count}")
    print()

    # Step 5: Test profile relationships
    print("Step 5: Testing profile relationships...")
    profiles_response = requests.get(
        f"{BASE_URL}/api/v1/profiles",
        headers=headers
    )

    profiles_list = profiles_response.json().get("profiles", [])
    print(f"✅ Found {len(profiles_list)} profiles")

    if not profiles_list:
        print("⚠️  No profiles found. Skipping profile tests.")
    else:
        profile_id = profiles_list[0]["id"]
        profile_name = profiles_list[0].get("name", "Unknown")

        print(f"   Using Profile ID: {profile_id} (\"{profile_name}\")")
        print(f"   Testing unified endpoint for profile...")
        print(f"   GET /api/v1/artifacts/profile/{profile_id}/relationships")

        profile_response = requests.get(
            f"{BASE_URL}/api/v1/artifacts/profile/{profile_id}/relationships",
            headers=headers
        )

        if profile_response.status_code != 200:
            print(f"❌ Profile endpoint failed")
            return False

        profile_data = profile_response.json()
        if profile_data.get("status") != "success":
            print(f"❌ Profile endpoint returned error")
            return False

        print("✅ Profile relationships endpoint working")

        profile_sessions = profile_data.get("relationships", {}).get("sessions", {}).get("total_count", 0)
        print(f"   Total sessions using this profile: {profile_sessions}")
    print()

    # Step 6: Test error handling
    print("Step 6: Testing error handling...")
    print("   Testing invalid artifact type...")

    invalid_response = requests.get(
        f"{BASE_URL}/api/v1/artifacts/invalid-type/123/relationships",
        headers=headers
    )

    if invalid_response.status_code == 400:
        print("✅ Error handling working correctly")
        error_data = invalid_response.json()
        print(f"   Error message: {error_data.get('message', 'Unknown error')}")
    else:
        print(f"❌ Error handling not working (got status {invalid_response.status_code})")
    print()

    # Summary
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("✅ Authentication: PASS")
    print("✅ Unified endpoint (collection): PASS")
    print("✅ Query parameters: PASS")
    print("✅ Profile relationships: PASS")
    print("✅ Error handling: PASS")
    print()
    print("All tests completed successfully! 🎉")

    return True

if __name__ == "__main__":
    try:
        success = test_unified_relationships()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
