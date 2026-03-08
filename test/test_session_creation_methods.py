#!/usr/bin/env python3
"""
Test Session Creation with Both Authentication Methods

This script demonstrates and tests session creation using:
1. JWT Token (login-based, short-lived, 24 hours)
2. Access Token (long-lived, configurable expiration)

Usage:
    python test/test_session_creation_methods.py

Requirements:
    - Server running at http://localhost:5050
    - Test user credentials (will prompt for input)
    - User must have a configured default profile (LLM + MCP Server)
      OR script will attempt to create one from existing configs
"""

import requests
import json
import time
import sys
import os
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

# Add test directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from profile_setup_helper import ProfileSetupHelper, print_profile_setup_requirement

# Configuration
BASE_URL = "http://127.0.0.1:5050"
API_V1_BASE = f"{BASE_URL}/api/v1"
AUTH_BASE = f"{BASE_URL}/api/v1/auth"

# Colors for output
BLUE = "\033[94m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


class SessionTester:
    """Test session creation with different authentication methods."""
    
    def __init__(self):
        self.jwt_token: Optional[str] = None
        self.access_token: Optional[str] = None
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.user_uuid: Optional[str] = None
        self.profile_helper = ProfileSetupHelper(BASE_URL)
        
    def print_header(self, text: str):
        """Print a formatted header."""
        print(f"\n{BLUE}{'='*70}{RESET}")
        print(f"{BLUE}{text:^70}{RESET}")
        print(f"{BLUE}{'='*70}{RESET}\n")
    
    def print_section(self, text: str):
        """Print a section header."""
        print(f"\n{YELLOW}>>> {text}{RESET}")
        
    def print_success(self, text: str):
        """Print success message."""
        print(f"{GREEN}✓ {text}{RESET}")
    
    def print_error(self, text: str):
        """Print error message."""
        print(f"{RED}✗ {text}{RESET}")
    
    def print_info(self, text: str):
        """Print info message."""
        print(f"{BLUE}ℹ {text}{RESET}")
    
    def get_credentials(self):
        """Get user credentials from input."""
        self.print_section("Enter Credentials")
        self.username = input(f"{YELLOW}Username: {RESET}").strip()
        self.password = input(f"{YELLOW}Password: {RESET}").strip()
        
        if not self.username or not self.password:
            self.print_error("Username and password are required")
            return False
        return True
    
    def step(self, step_num: int, description: str):
        """Print step description."""
        print(f"\n{YELLOW}[Step {step_num}]{RESET} {description}")
    
    # ========================================================================
    # Profile Setup
    # ========================================================================
    
    def setup_profile_for_user(self):
        """Ensure user has a default profile configured."""
        self.step(1, "Check/setup user profile")
        
        # Check existing profiles
        has_profiles, profile_info, error = self.profile_helper.check_profiles(self.jwt_token)
        
        if error:
            self.print_error(f"Profile check failed: {error}")
            return False
        
        if profile_info.get('has_default'):
            self.print_success(f"Default profile found: {profile_info['default_profile_id']}")
            print(f"  Total profiles: {profile_info['count']}")
            return True
        
        self.print_info(f"No default profile. Attempting to create one...")
        
        # Get or create LLM config
        success, llm_id, llm_error = self.profile_helper.get_or_create_llm_config(self.jwt_token, self.user_uuid)
        if not success:
            self.print_error(f"LLM configuration: {llm_error}")
            print_profile_setup_requirement()
            return False
        
        self.print_success(f"Using LLM config: {llm_id}")
        
        # Get or create MCP server
        success, mcp_id, mcp_error = self.profile_helper.get_or_create_mcp_server(self.jwt_token, self.user_uuid)
        if not success:
            self.print_error(f"MCP server: {mcp_error}")
            print_profile_setup_requirement()
            return False
        
        self.print_success(f"Using MCP server: {mcp_id}")
        
        # Create profile
        success, profile_id, create_error = self.profile_helper.create_profile(
            self.jwt_token, 
            llm_id, 
            mcp_id,
            f"Test Profile - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        if not success:
            self.print_error(f"Profile creation: {create_error}")
            return False
        
        self.print_success(f"Profile created: {profile_id}")
        
        # Set as default
        success, set_error = self.profile_helper.set_default_profile(self.jwt_token, profile_id)
        if not success:
            self.print_error(f"Setting default profile: {set_error}")
            return False
        
        self.print_success("Profile set as default")
        return True
    
    # ========================================================================
    # METHOD 1: JWT Token Approach
    # ========================================================================
    
    def test_jwt_approach(self):
        """Test session creation using JWT token."""
        self.print_section("METHOD 1: JWT Token (Short-lived, 24 hours)")
        
        # Step 1: Login to get JWT
        self.step(1, "Login to get JWT token")
        self.print_info(f"POST {AUTH_BASE}/login")
        
        try:
            response = requests.post(
                f"{AUTH_BASE}/login",
                json={
                    "username": self.username,
                    "password": self.password
                }
            )
            
            if response.status_code != 200:
                self.print_error(f"Login failed: {response.status_code}")
                print(f"Response: {response.text}")
                return False
            
            data = response.json()
            self.jwt_token = data.get('token')
            self.user_uuid = data.get('user', {}).get('user_uuid')
            
            if not self.jwt_token:
                self.print_error("No token in response")
                return False
            
            self.print_success("Login successful")
            print(f"  Token (first 50 chars): {self.jwt_token[:50]}...")
            print(f"  User: {data['user']['username']}")
            print(f"  User ID: {data['user']['id']}")
            print(f"  User UUID: {self.user_uuid}")
            
        except Exception as e:
            self.print_error(f"Login request failed: {e}")
            return False
        
        # Step 2: Setup profile if needed
        if not self.setup_profile_for_user():
            return False
        
        # Step 3: Create session with JWT
        self.step(2, "Create session using JWT token")
        self.print_info(f"POST {API_V1_BASE}/sessions")
        
        try:
            headers = {
                "Authorization": f"Bearer {self.jwt_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{API_V1_BASE}/sessions",
                headers=headers
            )
            
            if response.status_code != 201:
                self.print_error(f"Session creation failed: {response.status_code}")
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('error', response.text)
                print(f"Response: {error_msg}")
                
                # Provide guidance for common errors
                if response.status_code == 400:
                    print(f"\n{YELLOW}⚠️  Profile Configuration Required{RESET}")
                    print("   No default profile is configured for this user.")
                    print("   Please configure a profile via the UI:")
                    print("   1. Add an LLM Provider")
                    print("   2. Add an MCP Server")
                    print("   3. Create a Profile combining them")
                    print("   4. Mark it as default")
                elif response.status_code == 503:
                    print(f"\n{YELLOW}⚠️  Incomplete Profile Configuration{RESET}")
                    print("   The profile exists but is missing components.")
                    print("   Please verify both LLM and MCP Server are configured.")
                
                return False
            
            data = response.json()
            session_id_jwt = data.get('session_id')
            
            if not session_id_jwt:
                self.print_error("No session_id in response")
                return False
            
            self.print_success("Session created successfully")
            print(f"  Session ID: {session_id_jwt}")
            
            return session_id_jwt
            
        except Exception as e:
            self.print_error(f"Session creation request failed: {e}")
            return False
    
    # ========================================================================
    # METHOD 2: Access Token Approach
    # ========================================================================
    
    def test_access_token_approach(self):
        """Test session creation using access token."""
        self.print_section("METHOD 2: Access Token (Long-lived, configurable)")
        
        # Step 1: Login to get JWT (needed to create access token)
        self.step(1, "Login to get JWT token (temporary)")
        self.print_info(f"POST {AUTH_BASE}/login")
        
        try:
            response = requests.post(
                f"{AUTH_BASE}/login",
                json={
                    "username": self.username,
                    "password": self.password
                }
            )
            
            if response.status_code != 200:
                self.print_error(f"Login failed: {response.status_code}")
                return False
            
            data = response.json()
            jwt_token = data.get('token')
            
            self.print_success("Login successful (got JWT)")
            print(f"  Token (first 50 chars): {jwt_token[:50]}...")
            
        except Exception as e:
            self.print_error(f"Login failed: {e}")
            return False
        
        # Step 2: Create access token using JWT
        self.step(2, "Create long-lived access token using JWT")
        self.print_info(f"POST {API_V1_BASE}/auth/tokens")
        
        try:
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{API_V1_BASE}/auth/tokens",
                headers=headers,
                json={
                    "name": f"Test Token - {datetime.now().isoformat()}",
                    "expires_in_days": 90
                }
            )
            
            if response.status_code != 201:
                self.print_error(f"Access token creation failed: {response.status_code}")
                print(f"Response: {response.text}")
                return False
            
            data = response.json()
            self.access_token = data.get('token')
            
            if not self.access_token:
                self.print_error("No token in response")
                return False
            
            self.print_success("Access token created successfully")
            print(f"  Token: {self.access_token}")
            print(f"  Token ID: {data.get('token_id')}")
            print(f"  Name: {data.get('name')}")
            print(f"  Expires at: {data.get('expires_at')}")
            print(f"  ⚠️  SAVE THIS TOKEN! It cannot be retrieved later!")
            
        except Exception as e:
            self.print_error(f"Access token creation failed: {e}")
            return False
        
        # Step 3: Create session with access token
        self.step(3, "Create session using access token")
        self.print_info(f"POST {API_V1_BASE}/sessions")
        
        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{API_V1_BASE}/sessions",
                headers=headers
            )
            
            if response.status_code != 201:
                self.print_error(f"Session creation failed: {response.status_code}")
                print(f"Response: {response.text}")
                return False
            
            data = response.json()
            session_id_access = data.get('session_id')
            
            if not session_id_access:
                self.print_error("No session_id in response")
                return False
            
            self.print_success("Session created successfully")
            print(f"  Session ID: {session_id_access}")
            
            return session_id_access
            
        except Exception as e:
            self.print_error(f"Session creation failed: {e}")
            return False
    
    # ========================================================================
    # Query Execution Test
    # ========================================================================
    
    def test_query_execution(self, session_id: str, token: str, token_type: str):
        """Test query execution in a session."""
        self.step(1, f"Submit query to session using {token_type}")
        self.print_info(f"POST {API_V1_BASE}/sessions/{session_id}/query")
        
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{API_V1_BASE}/sessions/{session_id}/query",
                headers=headers,
                json={
                    "prompt": "What databases are available?"
                }
            )
            
            if response.status_code not in [200, 202]:
                self.print_error(f"Query submission failed: {response.status_code}")
                print(f"Response: {response.text}")
                return None
            
            data = response.json()
            task_id = data.get('task_id')
            status_url = data.get('status_url')
            
            if not task_id:
                self.print_error("No task_id in response")
                return None
            
            self.print_success("Query submitted successfully")
            print(f"  Task ID: {task_id}")
            print(f"  Status URL: {status_url}")
            
            return task_id
            
        except Exception as e:
            self.print_error(f"Query submission failed: {e}")
            return None
    
    def test_task_status(self, task_id: str, token: str, token_type: str):
        """Check task status."""
        self.step(2, f"Check task status using {token_type}")
        self.print_info(f"GET {API_V1_BASE}/tasks/{task_id}")
        
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{API_V1_BASE}/tasks/{task_id}",
                headers=headers
            )
            
            if response.status_code != 200:
                self.print_error(f"Task status check failed: {response.status_code}")
                print(f"Response: {response.text}")
                return False
            
            data = response.json()
            status = data.get('status')
            
            self.print_success(f"Task status retrieved: {status}")
            print(f"  Status: {status}")
            print(f"  Last updated: {data.get('last_updated', 'N/A')}")
            
            # Show events if available
            events = data.get('events', [])
            if events:
                print(f"  Events: {len(events)}")
                for event in events[:3]:  # Show first 3
                    print(f"    - {event.get('event_type')}: {event.get('timestamp', 'N/A')}")
                if len(events) > 3:
                    print(f"    ... and {len(events) - 3} more")
            
            return True
            
        except Exception as e:
            self.print_error(f"Task status check failed: {e}")
            return False
    
    # ========================================================================
    # Main Test Runner
    # ========================================================================
    
    def run_all_tests(self):
        """Run all tests."""
        self.print_header("REST API Session Creation Test - Both Authentication Methods")
        
        # Get credentials
        if not self.get_credentials():
            return False
        
        # Test JWT approach
        self.print_header("APPROACH 1: JWT Token (24-hour session)")
        jwt_session_id = self.test_jwt_approach()
        
        if jwt_session_id:
            self.print_section("Testing Query Execution with JWT")
            jwt_task_id = self.test_query_execution(jwt_session_id, self.jwt_token, "JWT")
            
            if jwt_task_id:
                time.sleep(2)  # Wait a bit for task to start
                self.test_task_status(jwt_task_id, self.jwt_token, "JWT")
        
        # Test access token approach
        self.print_header("APPROACH 2: Access Token (90-day persistence)")
        access_session_id = self.test_access_token_approach()
        
        if access_session_id:
            self.print_section("Testing Query Execution with Access Token")
            access_task_id = self.test_query_execution(access_session_id, self.access_token, "Access Token")
            
            if access_task_id:
                time.sleep(2)  # Wait a bit for task to start
                self.test_task_status(access_task_id, self.access_token, "Access Token")
        
        # Summary
        self.print_header("SUMMARY")
        print(f"\n{YELLOW}JWT Token Approach:{RESET}")
        if jwt_session_id:
            self.print_success(f"Session created: {jwt_session_id}")
        else:
            self.print_error("Session creation failed")
        
        print(f"\n{YELLOW}Access Token Approach:{RESET}")
        if access_session_id:
            self.print_success(f"Session created: {access_session_id}")
        else:
            self.print_error("Session creation failed")
        
        print(f"\n{YELLOW}Key Differences:{RESET}")
        print("  JWT Token:")
        print("    - Lifetime: 24 hours")
        print("    - Use case: Web UI, interactive sessions")
        print("    - Revocation: Automatic after expiration")
        print(f"    - Created via: POST /auth/login")
        
        print("\n  Access Token:")
        print("    - Lifetime: 30/60/90/180/365 days or never")
        print("    - Use case: API automation, CI/CD, scripts")
        print("    - Revocation: Manual or automatic after expiration")
        print(f"    - Created via: POST /api/v1/auth/tokens")
        print(f"    - Stored: Secure hash in database")
        
        print(f"\n{BLUE}{'='*70}{RESET}\n")


def main():
    """Run the test."""
    try:
        tester = SessionTester()
        tester.run_all_tests()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Test interrupted by user{RESET}")
    except Exception as e:
        print(f"\n{RED}Unexpected error: {e}{RESET}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
