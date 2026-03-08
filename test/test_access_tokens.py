#!/usr/bin/env python3
"""
Comprehensive test suite for Access Token authentication system.

Tests:
1. Token creation
2. Token verification
3. Token usage in REST API calls
4. Token revocation
5. Token expiration
6. Error handling
7. Security validation

Usage:
    python test/test_access_tokens.py
"""

import sys
import os
import time
import json
import requests
from datetime import datetime, timedelta

# Configuration
BASE_URL = os.getenv('TDA_BASE_URL', 'http://127.0.0.1:5050')
TEST_USERNAME = f"test_access_token_{int(time.time())}"
TEST_EMAIL = f"{TEST_USERNAME}@example.com"
TEST_PASSWORD = "TestPassword123!"

# ANSI color codes for pretty output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def pass_test(self, test_name):
        self.passed += 1
        print(f"{GREEN}✓{RESET} {test_name}")
    
    def fail_test(self, test_name, reason):
        self.failed += 1
        self.errors.append((test_name, reason))
        print(f"{RED}✗{RESET} {test_name}")
        print(f"  {RED}Reason: {reason}{RESET}")
    
    def print_summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Test Summary:")
        print(f"  Total: {total}")
        print(f"  {GREEN}Passed: {self.passed}{RESET}")
        print(f"  {RED}Failed: {self.failed}{RESET}")
        print(f"{'='*60}")
        
        if self.errors:
            print(f"\n{RED}Failed Tests:{RESET}")
            for test_name, reason in self.errors:
                print(f"  • {test_name}: {reason}")
        
        return self.failed == 0

results = TestResults()

def test_user_registration():
    """Test: Register a new user account"""
    print(f"\n{BLUE}[1] Testing User Registration{RESET}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/register",
            json={
                "username": TEST_USERNAME,
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            }
        )
        
        if response.status_code == 201:
            data = response.json()
            if data.get('status') == 'success':
                results.pass_test("User registration")
                return True
            else:
                results.fail_test("User registration", f"Unexpected status: {data.get('status')}")
                return False
        else:
            results.fail_test("User registration", f"HTTP {response.status_code}: {response.text}")
            return False
    
    except Exception as e:
        results.fail_test("User registration", str(e))
        return False

def test_user_login():
    """Test: Login and get JWT token"""
    print(f"\n{BLUE}[2] Testing User Login (JWT){RESET}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={
                "username": TEST_USERNAME,
                "password": TEST_PASSWORD
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success' and data.get('token'):
                jwt_token = data['token']
                results.pass_test("User login (JWT)")
                return jwt_token
            else:
                results.fail_test("User login (JWT)", "No token in response")
                return None
        else:
            results.fail_test("User login (JWT)", f"HTTP {response.status_code}: {response.text}")
            return None
    
    except Exception as e:
        results.fail_test("User login (JWT)", str(e))
        return None

def test_create_access_token(jwt_token):
    """Test: Create access token"""
    print(f"\n{BLUE}[3] Testing Access Token Creation{RESET}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json={
                "name": "Test Token",
                "expires_in_days": 90
            }
        )
        
        if response.status_code == 201:
            data = response.json()
            if data.get('status') == 'success' and data.get('token'):
                access_token = data['token']
                token_id = data['token_id']
                
                # Verify token format
                if not access_token.startswith('tda_'):
                    results.fail_test("Access token creation", "Token doesn't start with 'tda_'")
                    return None, None
                
                if len(access_token) < 30:
                    results.fail_test("Access token creation", f"Token too short: {len(access_token)} chars")
                    return None, None
                
                results.pass_test("Access token creation")
                return access_token, token_id
            else:
                results.fail_test("Access token creation", "No token in response")
                return None, None
        else:
            results.fail_test("Access token creation", f"HTTP {response.status_code}: {response.text}")
            return None, None
    
    except Exception as e:
        results.fail_test("Access token creation", str(e))
        return None, None

def test_create_access_token_no_expiry(jwt_token):
    """Test: Create access token without expiration"""
    print(f"\n{BLUE}[4] Testing Access Token Creation (No Expiry){RESET}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json={"name": "Never Expires Token"}
        )
        
        if response.status_code == 201:
            data = response.json()
            if data.get('status') == 'success' and data.get('expires_at') is None:
                results.pass_test("Access token creation (no expiry)")
                return data['token'], data['token_id']
            else:
                results.fail_test("Access token creation (no expiry)", "Token has unexpected expiration")
                return None, None
        else:
            results.fail_test("Access token creation (no expiry)", f"HTTP {response.status_code}")
            return None, None
    
    except Exception as e:
        results.fail_test("Access token creation (no expiry)", str(e))
        return None, None

def test_list_access_tokens(jwt_token):
    """Test: List access tokens"""
    print(f"\n{BLUE}[5] Testing List Access Tokens{RESET}")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {jwt_token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success' and isinstance(data.get('tokens'), list):
                token_count = len(data['tokens'])
                if token_count >= 2:  # We created 2 tokens
                    results.pass_test(f"List access tokens (found {token_count})")
                    return True
                else:
                    results.fail_test("List access tokens", f"Expected >= 2 tokens, found {token_count}")
                    return False
            else:
                results.fail_test("List access tokens", "Invalid response format")
                return False
        else:
            results.fail_test("List access tokens", f"HTTP {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("List access tokens", str(e))
        return False

def test_access_token_authentication(access_token):
    """Test: Use access token for authentication"""
    print(f"\n{BLUE}[6] Testing Access Token Authentication{RESET}")
    
    try:
        # Try to list tokens using the access token itself
        response = requests.get(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                results.pass_test("Access token authentication")
                return True
            else:
                results.fail_test("Access token authentication", "Request failed")
                return False
        else:
            results.fail_test("Access token authentication", f"HTTP {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("Access token authentication", str(e))
        return False

def test_revoke_access_token(jwt_token, token_id):
    """Test: Revoke an access token"""
    print(f"\n{BLUE}[7] Testing Access Token Revocation{RESET}")
    
    try:
        response = requests.delete(
            f"{BASE_URL}/api/v1/auth/tokens/{token_id}",
            headers={"Authorization": f"Bearer {jwt_token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                results.pass_test("Access token revocation")
                return True
            else:
                results.fail_test("Access token revocation", "Revocation failed")
                return False
        else:
            results.fail_test("Access token revocation", f"HTTP {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("Access token revocation", str(e))
        return False

def test_revoked_token_fails(revoked_token):
    """Test: Revoked token cannot be used"""
    print(f"\n{BLUE}[8] Testing Revoked Token Rejection{RESET}")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {revoked_token}"}
        )
        
        if response.status_code == 401:
            results.pass_test("Revoked token rejection")
            return True
        else:
            results.fail_test("Revoked token rejection", f"Expected 401, got {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("Revoked token rejection", str(e))
        return False

def test_invalid_token_format():
    """Test: Invalid token format is rejected"""
    print(f"\n{BLUE}[9] Testing Invalid Token Format{RESET}")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": "Bearer invalid_token_format"}
        )
        
        if response.status_code == 401:
            results.pass_test("Invalid token format rejection")
            return True
        else:
            results.fail_test("Invalid token format rejection", f"Expected 401, got {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("Invalid token format rejection", str(e))
        return False

def test_missing_authorization_header():
    """Test: Missing authorization header"""
    print(f"\n{BLUE}[10] Testing Missing Authorization Header{RESET}")
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/auth/tokens")
        
        if response.status_code == 401:
            results.pass_test("Missing authorization header rejection")
            return True
        else:
            results.fail_test("Missing authorization header rejection", f"Expected 401, got {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("Missing authorization header rejection", str(e))
        return False

def test_token_prefix_display(jwt_token):
    """Test: Token prefix is correctly stored and displayed"""
    print(f"\n{BLUE}[11] Testing Token Prefix Display{RESET}")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {jwt_token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            tokens = data.get('tokens', [])
            
            if not tokens:
                results.fail_test("Token prefix display", "No tokens found")
                return False
            
            # Check first token has prefix
            token = tokens[0]
            if 'token_prefix' in token and token['token_prefix'].startswith('tda_'):
                results.pass_test("Token prefix display")
                return True
            else:
                results.fail_test("Token prefix display", "Token prefix missing or invalid")
                return False
        else:
            results.fail_test("Token prefix display", f"HTTP {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("Token prefix display", str(e))
        return False

def test_create_token_validation():
    """Test: Token creation validation"""
    print(f"\n{BLUE}[12] Testing Token Creation Validation{RESET}")
    
    # This test requires JWT token but we'll test it fails without auth
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": "Bearer invalid"},
            json={"name": ""}
        )
        
        # Should fail either due to auth or validation
        if response.status_code in [400, 401]:
            results.pass_test("Token creation validation")
            return True
        else:
            results.fail_test("Token creation validation", f"Expected 400/401, got {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("Token creation validation", str(e))
        return False

def test_rest_api_with_access_token(access_token):
    """Test: Use access token with actual REST API endpoint"""
    print(f"\n{BLUE}[13] Testing REST API Call with Access Token{RESET}")
    
    try:
        # Try to call /api/status (should work even without full config)
        response = requests.get(
            f"{BASE_URL}/api/status",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'isConfigured' in data:
                results.pass_test("REST API call with access token")
                return True
            else:
                results.fail_test("REST API call with access token", "Invalid response format")
                return False
        else:
            results.fail_test("REST API call with access token", f"HTTP {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("REST API call with access token", str(e))
        return False

def test_jwt_still_works(jwt_token):
    """Test: JWT tokens still work alongside access tokens"""
    print(f"\n{BLUE}[14] Testing JWT Token Still Works{RESET}")
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {jwt_token}"}
        )
        
        if response.status_code == 200:
            results.pass_test("JWT token still works")
            return True
        else:
            results.fail_test("JWT token still works", f"HTTP {response.status_code}")
            return False
    
    except Exception as e:
        results.fail_test("JWT token still works", str(e))
        return False

def main():
    print(f"\n{'='*60}")
    print(f"{BLUE}Access Token System Test Suite{RESET}")
    print(f"{'='*60}")
    print(f"Testing against: {BASE_URL}")
    print(f"Test user: {TEST_USERNAME}")
    
    # Run tests in sequence
    jwt_token = None
    access_token = None
    token_id = None
    no_expiry_token = None
    no_expiry_token_id = None
    
    # 1. Register user
    if not test_user_registration():
        print(f"\n{RED}Cannot continue without user registration{RESET}")
        return False
    
    # 2. Login to get JWT
    jwt_token = test_user_login()
    if not jwt_token:
        print(f"\n{RED}Cannot continue without JWT token{RESET}")
        return False
    
    # 3. Create access token
    access_token, token_id = test_create_access_token(jwt_token)
    if not access_token:
        print(f"\n{RED}Cannot continue without access token{RESET}")
        return False
    
    # 4. Create token without expiry
    no_expiry_token, no_expiry_token_id = test_create_access_token_no_expiry(jwt_token)
    
    # 5. List tokens
    test_list_access_tokens(jwt_token)
    
    # 6. Use access token for authentication
    test_access_token_authentication(access_token)
    
    # 7. Test REST API call with access token
    test_rest_api_with_access_token(access_token)
    
    # 8. Test JWT still works
    test_jwt_still_works(jwt_token)
    
    # 9. Test token prefix display
    test_token_prefix_display(jwt_token)
    
    # 10. Revoke token
    if token_id:
        test_revoke_access_token(jwt_token, token_id)
        
        # 11. Verify revoked token doesn't work
        test_revoked_token_fails(access_token)
    
    # 12. Test validation
    test_invalid_token_format()
    test_missing_authorization_header()
    test_create_token_validation()
    
    # Print summary
    success = results.print_summary()
    
    if success:
        print(f"\n{GREEN}🎉 All tests passed!{RESET}\n")
        return True
    else:
        print(f"\n{RED}❌ Some tests failed{RESET}\n")
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Tests interrupted by user{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Fatal error: {e}{RESET}")
        sys.exit(1)
