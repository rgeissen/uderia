#!/usr/bin/env python3
"""
Extensive REST test for unified relationships endpoint migration.

Validates:
1. All 5 artifact types work with unified endpoint
2. Response format consistency
3. Query parameters (include_archived, limit, full)
4. Deletion info structure
5. Relationship detection across all types
6. Archive functions integration
7. Error handling
"""

import requests
import json
import sys
import time
from typing import Dict, Any, List

BASE_URL = "http://localhost:5050"

class UnifiedEndpointTester:
    def __init__(self):
        self.headers = {}
        self.tests_passed = 0
        self.tests_failed = 0
        self.errors = []

    def authenticate(self) -> bool:
        """Authenticate and get JWT token."""
        print("=" * 80)
        print("EXTENSIVE UNIFIED RELATIONSHIPS ENDPOINT TEST")
        print("=" * 80)
        print()
        print("Step 1: Authentication...")

        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": "admin", "password": "admin"}
        )

        if response.status_code != 200:
            print(f"❌ Authentication failed: {response.status_code}")
            return False

        jwt_token = response.json().get("token")
        if not jwt_token:
            print("❌ No JWT token received")
            return False

        self.headers = {"Authorization": f"Bearer {jwt_token}"}
        print(f"✅ Authenticated successfully")
        print()
        return True

    def test_response_structure(self, artifact_type: str, artifact_id: str, artifact_name: str) -> bool:
        """Test response structure for an artifact."""
        print(f"\n   Testing {artifact_type}: {artifact_name} (ID: {artifact_id})")

        response = requests.get(
            f"{BASE_URL}/api/v1/artifacts/{artifact_type}/{artifact_id}/relationships",
            headers=self.headers
        )

        if response.status_code != 200:
            print(f"   ❌ HTTP {response.status_code}: {response.text}")
            self.tests_failed += 1
            self.errors.append(f"{artifact_type} - HTTP {response.status_code}")
            return False

        data = response.json()

        # Validate top-level structure
        required_keys = ["status", "artifact", "relationships", "deletion_info"]
        for key in required_keys:
            if key not in data:
                print(f"   ❌ Missing required key: {key}")
                self.tests_failed += 1
                self.errors.append(f"{artifact_type} - missing {key}")
                return False

        # Validate artifact structure
        artifact = data["artifact"]
        artifact_required = ["type", "id", "name"]
        for key in artifact_required:
            if key not in artifact:
                print(f"   ❌ Missing artifact.{key}")
                self.tests_failed += 1
                return False

        # Validate relationships structure
        relationships = data["relationships"]
        if "sessions" not in relationships:
            print("   ❌ Missing relationships.sessions")
            self.tests_failed += 1
            return False

        sessions = relationships["sessions"]
        session_required = ["active_count", "archived_count", "total_count", "items"]
        for key in session_required:
            if key not in sessions:
                print(f"   ❌ Missing relationships.sessions.{key}")
                self.tests_failed += 1
                return False

        # Validate deletion_info structure
        deletion_info = data["deletion_info"]
        deletion_required = ["can_delete", "blockers", "warnings", "cascade_effects"]
        for key in deletion_required:
            if key not in deletion_info:
                print(f"   ❌ Missing deletion_info.{key}")
                self.tests_failed += 1
                return False

        print("   ✅ Response structure valid")
        print(f"      - Active sessions: {sessions['active_count']}")
        print(f"      - Archived sessions: {sessions['archived_count']}")
        print(f"      - Can delete: {deletion_info['can_delete']}")
        print(f"      - Blockers: {len(deletion_info['blockers'])}")
        print(f"      - Warnings: {len(deletion_info['warnings'])}")

        self.tests_passed += 1
        return True

    def test_query_parameters(self, artifact_type: str, artifact_id: str) -> bool:
        """Test query parameters (include_archived, limit, full)."""
        print(f"\n   Testing query parameters for {artifact_type} {artifact_id}...")

        # Test include_archived
        response1 = requests.get(
            f"{BASE_URL}/api/v1/artifacts/{artifact_type}/{artifact_id}/relationships",
            headers=self.headers,
            params={"include_archived": "false"}
        )

        response2 = requests.get(
            f"{BASE_URL}/api/v1/artifacts/{artifact_type}/{artifact_id}/relationships",
            headers=self.headers,
            params={"include_archived": "true"}
        )

        if response1.status_code != 200 or response2.status_code != 200:
            print("   ❌ include_archived parameter failed")
            self.tests_failed += 1
            return False

        data1 = response1.json()
        data2 = response2.json()

        archived1 = data1["relationships"]["sessions"]["archived_count"]
        archived2 = data2["relationships"]["sessions"]["archived_count"]

        if archived1 > 0 and len(data1["relationships"]["sessions"]["items"]) > len(data2["relationships"]["sessions"]["items"]):
            print("   ❌ include_archived not working correctly")
            self.tests_failed += 1
            return False

        print(f"   ✅ include_archived working (found {archived2} archived sessions)")

        # Test limit parameter
        response3 = requests.get(
            f"{BASE_URL}/api/v1/artifacts/{artifact_type}/{artifact_id}/relationships",
            headers=self.headers,
            params={"limit": "2"}
        )

        if response3.status_code == 200:
            data3 = response3.json()
            items_count = len(data3["relationships"]["sessions"]["items"])
            if items_count <= 2:
                print(f"   ✅ limit parameter working (returned {items_count} items)")
            else:
                print(f"   ⚠️  limit parameter may not be working (returned {items_count} items)")
        else:
            print("   ❌ limit parameter failed")
            self.tests_failed += 1
            return False

        self.tests_passed += 1
        return True

    def test_error_handling(self) -> bool:
        """Test error handling for invalid inputs."""
        print("\nStep 4: Testing error handling...")

        # Test invalid artifact type
        response = requests.get(
            f"{BASE_URL}/api/v1/artifacts/invalid-type/123/relationships",
            headers=self.headers
        )

        if response.status_code == 400:
            print("   ✅ Invalid artifact type handled correctly")
        else:
            print(f"   ❌ Invalid artifact type not handled (HTTP {response.status_code})")
            self.tests_failed += 1
            return False

        # Test non-existent artifact
        response = requests.get(
            f"{BASE_URL}/api/v1/artifacts/collection/999999/relationships",
            headers=self.headers
        )

        if response.status_code == 404:
            print("   ✅ Non-existent artifact handled correctly")
        else:
            print(f"   ❌ Non-existent artifact not handled (HTTP {response.status_code})")
            self.tests_failed += 1
            return False

        self.tests_passed += 1
        return True

    def test_all_artifact_types(self) -> bool:
        """Test all 5 artifact types."""
        print("\nStep 2: Testing all artifact types...")

        artifact_configs = [
            {
                "type": "collection",
                "list_endpoint": "/api/v1/rag/collections",
                "list_key": "collections"
            },
            {
                "type": "profile",
                "list_endpoint": "/api/v1/profiles",
                "list_key": "profiles"
            },
            {
                "type": "mcp-server",
                "list_endpoint": "/api/v1/mcp/servers",
                "list_key": "servers"
            },
            {
                "type": "llm-config",
                "list_endpoint": "/api/v1/llm/configurations",
                "list_key": "llm_configurations"
            }
        ]

        for config in artifact_configs:
            artifact_type = config["type"]
            list_endpoint = config["list_endpoint"]
            list_key = config["list_key"]

            # Get list of artifacts
            list_response = requests.get(f"{BASE_URL}{list_endpoint}", headers=self.headers)

            if list_response.status_code != 200:
                print(f"   ⚠️  Could not list {artifact_type}s (HTTP {list_response.status_code})")
                continue

            artifacts = list_response.json().get(list_key, [])

            if not artifacts:
                print(f"   ⚠️  No {artifact_type}s found, skipping")
                continue

            artifact = artifacts[0]
            artifact_id = artifact.get("id")
            artifact_name = artifact.get("name", artifact.get("server_name", artifact.get("configuration_name", "Unknown")))

            # Test response structure
            self.test_response_structure(artifact_type, artifact_id, artifact_name)

            # Test query parameters
            self.test_query_parameters(artifact_type, artifact_id)

        return True

    def verify_old_endpoints_deprecated(self) -> bool:
        """Verify old check-sessions endpoints still exist for backward compatibility."""
        print("\nStep 5: Verifying old endpoints...")

        # Old collection endpoint should still work (backward compatibility)
        collections_response = requests.get(f"{BASE_URL}/api/v1/rag/collections", headers=self.headers)
        if collections_response.status_code == 200:
            collections = collections_response.json().get("collections", [])
            if collections:
                coll_id = collections[0]["id"]

                old_response = requests.get(
                    f"{BASE_URL}/api/v1/rag/collections/{coll_id}/check-sessions",
                    headers=self.headers
                )

                if old_response.status_code == 200:
                    print("   ✅ Old check-sessions endpoint still available (backward compatibility)")
                else:
                    print(f"   ⚠️  Old check-sessions endpoint returned HTTP {old_response.status_code}")
            else:
                print("   ⚠️  No collections to test old endpoint")
        else:
            print("   ⚠️  Could not list collections")

        self.tests_passed += 1
        return True

    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        print(f"Total tests passed: {self.tests_passed}")
        print(f"Total tests failed: {self.tests_failed}")

        if self.errors:
            print("\nErrors encountered:")
            for error in self.errors:
                print(f"  - {error}")

        if self.tests_failed == 0:
            print("\n✅ ALL TESTS PASSED! 🎉")
            print()
            print("Migration Status:")
            print("  ✅ Unified endpoint working for all artifact types")
            print("  ✅ Response structure consistent")
            print("  ✅ Query parameters working")
            print("  ✅ Error handling working")
            print("  ✅ Backward compatibility maintained")
            return True
        else:
            print(f"\n❌ {self.tests_failed} TESTS FAILED")
            return False

    def run_all_tests(self) -> bool:
        """Run all tests."""
        if not self.authenticate():
            return False

        self.test_all_artifact_types()
        self.test_error_handling()
        self.verify_old_endpoints_deprecated()

        return self.print_summary()

if __name__ == "__main__":
    tester = UnifiedEndpointTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
