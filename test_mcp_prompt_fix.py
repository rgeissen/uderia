#!/usr/bin/env python3
"""
Test script to verify MCP prompt execution fixes for None value issue.

This script:
1. Executes the qlty_databaseQuality MCP prompt via @OPTIM profile
2. Analyzes execution trace for self-correction events
3. Checks for None value validation errors
4. Reports token usage and execution quality
"""

import sys
import json
import time
import requests
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:5050"
USERNAME = "admin"
PASSWORD = "admin"
PROFILE_TAG = "OPTIM"
MCP_PROMPT = "qlty_databaseQuality"

def authenticate():
    """Authenticate and get JWT token."""
    print("\n🔐 Authenticating...")
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        headers={"Content-Type": "application/json"}
    )

    if response.status_code != 200:
        print(f"❌ Authentication failed: {response.status_code}")
        print(f"Response: {response.text}")
        sys.exit(1)

    token = response.json().get('token')
    print(f"✅ Authenticated successfully")
    return token

def get_profile_id(jwt_token, profile_tag):
    """Get profile ID for a given profile tag."""
    response = requests.get(
        f"{BASE_URL}/api/v1/profiles",
        headers={"Authorization": f"Bearer {jwt_token}"}
    )

    if response.status_code != 200:
        print(f"❌ Failed to get profiles: {response.status_code}")
        sys.exit(1)

    data = response.json()
    profiles = data.get('profiles', [])

    for profile in profiles:
        if profile.get('tag') == profile_tag:
            return profile.get('id')

    print(f"❌ Profile @{profile_tag} not found")
    print("Available profiles:")
    for p in profiles:
        print(f"  - @{p.get('tag', 'N/A')}: {p.get('name', 'N/A')}")
    sys.exit(1)

def create_session(jwt_token):
    """Create a session with default profile."""
    print(f"\n📝 Creating session...")

    response = requests.post(
        f"{BASE_URL}/api/v1/sessions",
        json={},
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }
    )

    if response.status_code != 201:
        print(f"❌ Session creation failed: {response.status_code}")
        print(f"Response: {response.text}")
        sys.exit(1)

    session_id = response.json().get('session_id')
    print(f"✅ Session created: {session_id}")
    return session_id

def submit_query(jwt_token, session_id, query, profile_id=None):
    """Submit MCP prompt query to session with optional profile override."""
    print(f"\n🚀 Submitting query: '{query}'")
    if profile_id:
        print(f"   Profile override: {profile_id}")

    payload = {"prompt": query}
    if profile_id:
        payload["profile_id"] = profile_id

    response = requests.post(
        f"{BASE_URL}/api/v1/sessions/{session_id}/query",
        json=payload,
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }
    )

    # Accept both 200 and 202 status codes
    if response.status_code not in [200, 202]:
        print(f"❌ Query submission failed: {response.status_code}")
        print(f"Response: {response.text}")
        sys.exit(1)

    task_id = response.json().get('task_id')
    print(f"✅ Query submitted, task ID: {task_id}")
    return task_id

def poll_for_results(jwt_token, task_id, timeout=120):
    """Poll for task completion."""
    print(f"\n⏳ Polling for results (timeout: {timeout}s)...")

    start_time = time.time()
    poll_interval = 2

    while time.time() - start_time < timeout:
        response = requests.get(
            f"{BASE_URL}/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {jwt_token}"}
        )

        if response.status_code != 200:
            print(f"❌ Failed to get task status: {response.status_code}")
            sys.exit(1)

        task_data = response.json()
        status = task_data.get('status')

        print(f"   Status: {status}", end='\r')

        if status in ['completed', 'failed', 'error']:
            print(f"\n✅ Task {status}")
            return task_data

        time.sleep(poll_interval)

    print(f"\n❌ Task timed out after {timeout}s")
    sys.exit(1)

def analyze_execution(task_data):
    """Analyze execution trace for issues."""
    print("\n" + "="*80)
    print("📊 EXECUTION ANALYSIS")
    print("="*80)

    events = task_data.get('events', [])

    # Count self-correction events
    self_corrections = [
        e for e in events
        if e.get('event_data', {}).get('message') == 'System Self-Correction'
    ]

    # Look for None value errors
    none_value_errors = []
    for event in events:
        event_str = json.dumps(event)
        if 'None is not of type' in event_str or 'Input validation error' in event_str:
            none_value_errors.append(event)

    # Count LLM correction calls
    llm_corrections = [
        e for e in events
        if 'Calling LLM for Self-Correction' in json.dumps(e)
    ]

    # Extract token usage
    token_updates = [e for e in events if e.get('event_type') == 'token_update']
    final_tokens = token_updates[-1]['event_data'] if token_updates else {}

    # Extract execution result
    final_result = None
    for event in reversed(events):
        if event.get('event_type') == 'notification':
            msg = event.get('event_data', {}).get('message', '')
            if 'Agent Complete' in msg or 'Final Report' in msg:
                final_result = event.get('event_data')
                break

    # Print results
    print(f"\n🔍 Self-Correction Events: {len(self_corrections)}")
    if self_corrections:
        print("   ❌ FAILED: Should be 0 after fixes!")
        for i, sc in enumerate(self_corrections[:3], 1):
            print(f"   [{i}] {sc.get('event_data', {}).get('summary', 'N/A')}")
    else:
        print("   ✅ PASSED: Zero self-corrections")

    print(f"\n🔍 None Value Validation Errors: {len(none_value_errors)}")
    if none_value_errors:
        print("   ❌ FAILED: Should be 0 after fixes!")
        for i, err in enumerate(none_value_errors[:3], 1):
            print(f"   [{i}] {json.dumps(err, indent=2)[:200]}...")
    else:
        print("   ✅ PASSED: No None value errors")

    print(f"\n🔍 LLM Correction Calls: {len(llm_corrections)}")
    if llm_corrections:
        print(f"   ⚠️  WARNING: {len(llm_corrections)} correction calls (should be 0)")
    else:
        print("   ✅ PASSED: No unnecessary LLM corrections")

    print(f"\n📊 Token Usage:")
    print(f"   Input:  {final_tokens.get('total_input', 0):,}")
    print(f"   Output: {final_tokens.get('total_output', 0):,}")
    print(f"   Total:  {final_tokens.get('total_input', 0) + final_tokens.get('total_output', 0):,}")

    print(f"\n📋 Execution Result: {task_data.get('status', 'unknown')}")

    # Summary
    print("\n" + "="*80)
    print("📊 TEST SUMMARY")
    print("="*80)

    all_passed = (
        len(self_corrections) == 0 and
        len(none_value_errors) == 0 and
        len(llm_corrections) == 0 and
        task_data.get('status') == 'completed'
    )

    if all_passed:
        print("✅ ALL TESTS PASSED!")
        print("   - Zero self-corrections")
        print("   - No None value errors")
        print("   - No unnecessary LLM correction calls")
        print("   - Execution completed successfully")
    else:
        print("❌ SOME TESTS FAILED")
        if len(self_corrections) > 0:
            print(f"   - Found {len(self_corrections)} self-correction events")
        if len(none_value_errors) > 0:
            print(f"   - Found {len(none_value_errors)} None value errors")
        if len(llm_corrections) > 0:
            print(f"   - Found {len(llm_corrections)} LLM correction calls")
        if task_data.get('status') != 'completed':
            print(f"   - Task status: {task_data.get('status')}")

    print("="*80 + "\n")

    return all_passed

def main():
    """Main test execution."""
    print("\n" + "="*80)
    print("🧪 MCP PROMPT FIX VERIFICATION TEST")
    print("="*80)
    print(f"Testing fixes for None value issue in MCP prompt execution")
    print(f"Profile: @{PROFILE_TAG}")
    print(f"Prompt: Executing prompt: {MCP_PROMPT}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    try:
        # Step 1: Authenticate
        jwt_token = authenticate()

        # Step 2: Get profile ID for @OPTIM
        profile_id = get_profile_id(jwt_token, PROFILE_TAG)
        print(f"   @{PROFILE_TAG} profile ID: {profile_id}")

        # Step 3: Create session
        session_id = create_session(jwt_token)

        # Step 4: Submit query with profile_id parameter (REST API method)
        query = f"Executing prompt: {MCP_PROMPT}"
        task_id = submit_query(jwt_token, session_id, query, profile_id=profile_id)

        # Step 4: Poll for results
        task_data = poll_for_results(jwt_token, task_id)

        # Step 5: Analyze execution
        all_passed = analyze_execution(task_data)

        # Step 6: Save results
        output_file = f"/tmp/mcp_prompt_test_{task_id}.json"
        with open(output_file, 'w') as f:
            json.dump(task_data, f, indent=2)
        print(f"📄 Full results saved to: {output_file}")

        # Exit with appropriate code
        sys.exit(0 if all_passed else 1)

    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
