#!/usr/bin/env python3
"""
Automated REST API Test for Phase 2: Backend Lifecycle Events
Tests execution_start, execution_complete, execution_error, execution_cancelled
events across all 4 profile types.

Usage:
    python test_lifecycle_events.py

Credentials: admin/admin (as specified by user)
"""

import asyncio
import httpx
import json
import sys
from datetime import datetime


BASE_URL = "http://localhost:5050"
USERNAME = "admin"
PASSWORD = "admin"


class LifecycleEventTester:
    def __init__(self):
        self.token = None
        self.user_uuid = None
        self.test_results = {
            "tool_enabled": {"passed": False, "events": [], "errors": []},
            "llm_only": {"passed": False, "events": [], "errors": []},
            "rag_focused": {"passed": False, "events": [], "errors": []},
            "genie": {"passed": False, "events": [], "errors": []}
        }

    async def login(self):
        """Authenticate with admin credentials"""
        print(f"\n{'='*60}")
        print("PHASE 2: Lifecycle Events Test - Login")
        print(f"{'='*60}")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/api/v1/auth/login",
                json={"username": USERNAME, "password": PASSWORD}
            )
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("token")  # Changed from "access_token"
                user_data = data.get("user", {})
                self.user_uuid = user_data.get("user_uuid")  # Get from nested user object
                print(f"✅ Login successful")
                print(f"   User UUID: {self.user_uuid}")
                return True
            else:
                print(f"❌ Login failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False

    async def get_profiles(self):
        """Fetch user profiles to get profile IDs"""
        print(f"\n{'='*60}")
        print("Fetching User Profiles")
        print(f"{'='*60}")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/api/v1/profiles",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            if response.status_code == 200:
                profiles_data = response.json()
                profiles = profiles_data.get("profiles", [])
                print(f"✅ Found {len(profiles)} profiles")

                profile_map = {}
                for profile in profiles:
                    profile_type = profile.get("profile_type")
                    profile_id = profile.get("id")
                    profile_tag = profile.get("tag", "N/A")
                    profile_name = profile.get("name", "N/A")

                    if profile_type in ["tool_enabled", "llm_only", "rag_focused", "genie"]:
                        # Only use the first profile of each type (avoid overwriting)
                        if profile_type not in profile_map:
                            profile_map[profile_type] = {
                                "id": profile_id,
                                "tag": profile_tag,
                                "name": profile_name
                            }
                            print(f"   - {profile_type}: @{profile_tag} ({profile_name})")

                return profile_map
            else:
                print(f"❌ Failed to fetch profiles: {response.status_code}")
                return {}

    async def test_profile(self, profile_type, profile_info, query):
        """Test lifecycle events for a specific profile"""
        print(f"\n{'='*60}")
        print(f"Testing Profile: {profile_type}")
        print(f"{'='*60}")
        print(f"Query: {query}")
        print(f"Profile: @{profile_info.get('tag')} ({profile_info.get('name')})")

        events_received = []
        lifecycle_events = []

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Create a new session first
                session_response = await client.post(
                    f"{BASE_URL}/api/v1/sessions",
                    headers={"Authorization": f"Bearer {self.token}"}
                )
                if session_response.status_code not in [200, 201]:  # Accept both 200 and 201
                    error_msg = f"Failed to create session: {session_response.status_code}"
                    print(f"❌ {error_msg}")
                    self.test_results[profile_type]["errors"].append(error_msg)
                    return False

                session_data = session_response.json()
                session_id = session_data.get("session_id")
                print(f"✅ Created session: {session_id}")

                # Execute query via REST API with profile override
                payload = {
                    "prompt": query,  # Changed from "query" to "prompt"
                    "profile_id": profile_info.get("id")  # Changed from "profile_override_id" to "profile_id"
                }

                print(f"Sending query request...")

                # Submit query (REST API returns 202 with task_id)
                response = await client.post(
                    f"{BASE_URL}/api/v1/sessions/{session_id}/query",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.token}"
                    }
                )
                if response.status_code != 202:
                    error_msg = f"Request failed: {response.status_code}"
                    print(f"❌ {error_msg}")
                    self.test_results[profile_type]["errors"].append(error_msg)
                    return False

                task_data = response.json()
                task_id = task_data.get("task_id")
                print(f"✅ Task created: {task_id}")
                print(f"\nPolling for task completion...")

                # Poll task status until complete
                max_polls = 60  # 60 seconds max
                poll_interval = 1  # 1 second
                for poll_count in range(max_polls):
                    await asyncio.sleep(poll_interval)

                    status_response = await client.get(
                        f"{BASE_URL}/api/v1/tasks/{task_id}",
                        headers={"Authorization": f"Bearer {self.token}"}
                    )

                    if status_response.status_code != 200:
                        continue

                    task_status = status_response.json()
                    status = task_status.get("status")
                    task_events = task_status.get("events", [])

                    print(f"   Poll {poll_count + 1}: {status} ({len(task_events)} events)")

                    # Check for lifecycle events in task events
                    for event in task_events:
                        # Handle both dict and string event_data
                        event_data = event.get("event_data", {})
                        if isinstance(event_data, str):
                            # Some events have string event_data, skip them
                            event_type = event.get("event_type")
                        else:
                            event_type = event_data.get("type") or event.get("event_type")

                        # Track all events
                        events_received.append(event_type)

                        # Check for lifecycle events (only process dict event_data)
                        if isinstance(event_data, dict) and event_type in ["execution_start", "execution_complete", "execution_error", "execution_cancelled"]:
                            # For genie, payload is directly in event_data. For other profiles, it's nested under "payload"
                            payload_data = event_data.get("payload", event_data)
                            profile_type_from_event = payload_data.get("profile_type")

                            # Avoid duplicates
                            if not any(e["type"] == event_type and e.get("timestamp") == payload_data.get("timestamp") for e in lifecycle_events):
                                lifecycle_events.append({
                                    "type": event_type,
                                    "profile_type": profile_type_from_event,
                                    "timestamp": payload_data.get("timestamp"),
                                    "payload": payload_data
                                })

                                print(f"   📍 {event_type}: profile_type={profile_type_from_event}")

                    # Stop when task is complete
                    if status in ["complete", "error", "cancelled"]:
                        print(f"   ⏹️  Task finished: {status}")
                        break
                else:
                    # Timeout
                    error_msg = "Task polling timeout (60s)"
                    print(f"❌ {error_msg}")
                    self.test_results[profile_type]["errors"].append(error_msg)
                    return False

                # Verify lifecycle events
                print(f"\n{'='*60}")
                print(f"Verification Results")
                print(f"{'='*60}")
                print(f"Total events received: {len(events_received)}")
                # Filter to only string event types for the set
                print(f"Event types seen: {set([e for e in events_received if e and isinstance(e, str)])}")
                print(f"Lifecycle events: {len(lifecycle_events)}")

                # Check for execution_start
                has_start = any(e["type"] == "execution_start" for e in lifecycle_events)
                # Check for execution_complete (or error/cancelled)
                has_end = any(e["type"] in ["execution_complete", "execution_error", "execution_cancelled"] for e in lifecycle_events)

                # Verify profile_type matches
                correct_profile_type = all(
                    e.get("profile_type") == profile_type
                    for e in lifecycle_events
                )

                print(f"✅ execution_start: {'Yes' if has_start else 'No'}")
                print(f"✅ execution_complete/error/cancelled: {'Yes' if has_end else 'No'}")
                print(f"✅ Correct profile_type: {'Yes' if correct_profile_type else 'No'}")

                # Store results
                self.test_results[profile_type]["events"] = lifecycle_events
                self.test_results[profile_type]["passed"] = has_start and has_end and correct_profile_type

                if self.test_results[profile_type]["passed"]:
                    print(f"\n✅ {profile_type} PASSED")
                else:
                    print(f"\n❌ {profile_type} FAILED")
                    if not has_start:
                        self.test_results[profile_type]["errors"].append("Missing execution_start event")
                    if not has_end:
                        self.test_results[profile_type]["errors"].append("Missing execution_complete/error/cancelled event")
                    if not correct_profile_type:
                        self.test_results[profile_type]["errors"].append("Incorrect profile_type in events")

                return self.test_results[profile_type]["passed"]

        except Exception as e:
            error_msg = f"Exception: {str(e)}"
            print(f"❌ {error_msg}")
            self.test_results[profile_type]["errors"].append(error_msg)
            return False

    async def run_tests(self):
        """Run tests for all profile types"""
        # Login
        if not await self.login():
            print("❌ Login failed. Exiting.")
            return False

        # Get profiles
        profiles = await self.get_profiles()
        if not profiles:
            print("❌ No profiles found. Exiting.")
            return False

        # Test each profile type
        test_queries = {
            "tool_enabled": "What is 2 + 2?",  # Simple query for efficiency focused
            "llm_only": "What is the capital of France?",  # Conversation focused
            "rag_focused": "Tell me about fitness equipment",  # Knowledge focused (if RAG enabled)
            "genie": "What is machine learning?"  # Multi-profile coordinator
        }

        for profile_type in ["tool_enabled", "llm_only", "rag_focused", "genie"]:
            if profile_type not in profiles:
                print(f"\n⚠️  Skipping {profile_type}: Profile not found")
                self.test_results[profile_type]["errors"].append("Profile not found in user profiles")
                continue

            query = test_queries.get(profile_type)
            profile_info = profiles[profile_type]

            await self.test_profile(profile_type, profile_info, query)

            # Small delay between tests
            await asyncio.sleep(2)

        # Print summary
        self.print_summary()

        # Return overall pass/fail
        all_passed = all(result["passed"] for result in self.test_results.values())
        return all_passed

    def print_summary(self):
        """Print test summary"""
        print(f"\n{'='*60}")
        print("TEST SUMMARY")
        print(f"{'='*60}")

        for profile_type, result in self.test_results.items():
            status = "✅ PASSED" if result["passed"] else "❌ FAILED"
            print(f"\n{profile_type}: {status}")

            if result["events"]:
                print(f"  Lifecycle events received:")
                for event in result["events"]:
                    print(f"    - {event['type']} (profile_type={event.get('profile_type')})")

            if result["errors"]:
                print(f"  Errors:")
                for error in result["errors"]:
                    print(f"    - {error}")

        # Overall result
        passed_count = sum(1 for r in self.test_results.values() if r["passed"])
        total_count = len(self.test_results)

        print(f"\n{'='*60}")
        print(f"Overall: {passed_count}/{total_count} profiles passed")
        print(f"{'='*60}")

        if passed_count == total_count:
            print("🎉 ALL TESTS PASSED!")
        else:
            print("⚠️  SOME TESTS FAILED")


async def main():
    """Main test entry point"""
    print(f"\n{'='*60}")
    print("PHASE 2: Backend Lifecycle Events - Automated Test")
    print(f"{'='*60}")
    print(f"Base URL: {BASE_URL}")
    print(f"Credentials: {USERNAME}/{PASSWORD}")
    print(f"Time: {datetime.now().isoformat()}")

    tester = LifecycleEventTester()
    success = await tester.run_tests()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
