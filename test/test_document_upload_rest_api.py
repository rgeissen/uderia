#!/usr/bin/env python3
"""
REST API and Admin UI Integration Test

Tests the document upload configuration REST API endpoints and admin UI integration.
Uses the provided test token for authentication.
"""

import requests
import json
import sys
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:5050"
API_BASE = f"{BASE_URL}/api/v1"
TEST_TOKEN = "tda_t_h3YrfIaVqdugXYNBCaaCGHpYL-ONRK"

# Headers with authentication
HEADERS = {
    "Authorization": f"Bearer {TEST_TOKEN}",
    "Content-Type": "application/json"
}


def print_header(title):
    """Print a formatted header."""
    print(f"\n{'='*70}")
    print(f"{title}")
    print(f"{'='*70}")


def print_test(test_name):
    """Print a test name."""
    print(f"\n[Test] {test_name}")
    print("-" * 70)


def test_connection():
    """Test basic connection to server."""
    print_test("Server Connection")
    try:
        # Try the actual API endpoint instead of health check
        response = requests.get(
            f"{API_BASE}/admin/config/document-upload",
            headers=HEADERS,
            timeout=5
        )
        if response.status_code in [200, 401, 403]:
            print(f"✓ Server is running (status: {response.status_code})")
            return True
        else:
            print(f"✗ Unexpected response: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ Cannot connect to server")
        print("  Please ensure the server is running: python -m trusted_data_agent.main --host 0.0.0.0 --port 5050")
        return False
    except Exception as e:
        print(f"✗ Connection error: {e}")
        return False


def test_get_all_configs():
    """Test GET /api/v1/admin/config/document-upload - List all configurations."""
    print_test("GET All Document Upload Configurations")
    
    try:
        response = requests.get(
            f"{API_BASE}/admin/config/document-upload",
            headers=HEADERS,
            timeout=5
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('status') == 'success':
                configs = data.get('configs', [])
                print(f"✓ Retrieved {len(configs)} provider configurations")
                
                print(f"\n{'Provider':<12} {'Enabled':<10} {'Native':<10} {'Capability':<20} {'Status'}")
                print("-" * 70)
                
                for config in configs:
                    print(f"{config['provider']:<12} "
                          f"{str(config['enabled']):<10} "
                          f"{str(config['use_native_upload']):<10} "
                          f"{config['capability']:<20} "
                          f"{'Modified' if config['has_overrides'] else 'Default'}")
                
                return True
            else:
                print(f"✗ API returned error: {data.get('message')}")
                return False
        else:
            print(f"✗ HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_get_single_config(provider="Google"):
    """Test GET /api/v1/admin/config/document-upload/<provider> - Get specific config."""
    print_test(f"GET Configuration for {provider}")
    
    try:
        response = requests.get(
            f"{API_BASE}/admin/config/document-upload/{provider}",
            headers=HEADERS,
            timeout=5
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('status') == 'success':
                config = data.get('config', {})
                print(f"✓ Retrieved configuration for {provider}")
                print(f"  Provider: {config['provider']}")
                print(f"  Enabled: {config['enabled']}")
                print(f"  Use Native Upload: {config['use_native_upload']}")
                print(f"  Capability: {config['capability']}")
                print(f"  Max File Size: {config['max_file_size_mb']} MB")
                print(f"  Supported Formats: {len(config['supported_formats'])} formats")
                print(f"  Has Overrides: {config['has_overrides']}")
                if config.get('notes'):
                    print(f"  Notes: {config['notes']}")
                
                return True
            else:
                print(f"✗ API returned error: {data.get('message')}")
                return False
        else:
            print(f"✗ HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_update_config(provider="Ollama"):
    """Test PUT /api/v1/admin/config/document-upload/<provider> - Update config."""
    print_test(f"PUT Update Configuration for {provider}")
    
    # Get current config first
    try:
        response = requests.get(
            f"{API_BASE}/admin/config/document-upload/{provider}",
            headers=HEADERS,
            timeout=5
        )
        
        if response.status_code != 200:
            print(f"✗ Could not get current config")
            return False
        
        current_config = response.json().get('config', {})
        print(f"Current state:")
        print(f"  Enabled: {current_config['enabled']}")
        print(f"  Native Upload: {current_config['use_native_upload']}")
        
    except Exception as e:
        print(f"✗ Failed to get current config: {e}")
        return False
    
    # Update config
    update_data = {
        "enabled": True,
        "use_native_upload": False,  # Force text extraction
        "notes": f"Test update via REST API - forcing text extraction for {provider}"
    }
    
    try:
        response = requests.put(
            f"{API_BASE}/admin/config/document-upload/{provider}",
            headers=HEADERS,
            json=update_data,
            timeout=5
        )
        
        print(f"\nUpdate Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('status') == 'success':
                updated_config = data.get('config', {})
                print(f"✓ Configuration updated successfully")
                print(f"  New state:")
                print(f"    Enabled: {updated_config['enabled']}")
                print(f"    Native Upload: {updated_config['use_native_upload']}")
                print(f"    Has Overrides: {updated_config['has_overrides']}")
                if updated_config.get('notes'):
                    print(f"    Notes: {updated_config['notes']}")
                
                return True
            else:
                print(f"✗ API returned error: {data.get('message')}")
                return False
        else:
            print(f"✗ HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_reset_config(provider="Ollama"):
    """Test POST /api/v1/admin/config/document-upload/<provider>/reset - Reset to defaults."""
    print_test(f"POST Reset Configuration for {provider}")
    
    try:
        response = requests.post(
            f"{API_BASE}/admin/config/document-upload/{provider}/reset",
            headers=HEADERS,
            timeout=5
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('status') == 'success':
                reset_config = data.get('config', {})
                print(f"✓ Configuration reset to defaults")
                print(f"  Provider: {reset_config['provider']}")
                print(f"  Enabled: {reset_config['enabled']}")
                print(f"  Native Upload: {reset_config['use_native_upload']}")
                print(f"  Has Overrides: {reset_config['has_overrides']}")
                
                return True
            else:
                print(f"✗ API returned error: {data.get('message')}")
                return False
        else:
            print(f"✗ HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_invalid_provider():
    """Test error handling for invalid provider."""
    print_test("Error Handling - Invalid Provider")
    
    try:
        response = requests.get(
            f"{API_BASE}/admin/config/document-upload/InvalidProvider",
            headers=HEADERS,
            timeout=5
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 400:
            data = response.json()
            print(f"✓ Invalid provider rejected correctly")
            print(f"  Message: {data.get('message')}")
            return True
        else:
            print(f"✗ Expected 400 Bad Request, got {response.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_unauthorized_access():
    """Test that endpoints require authentication."""
    print_test("Authorization - Unauthenticated Request")
    
    try:
        # Request without token
        response = requests.get(
            f"{API_BASE}/admin/config/document-upload",
            headers={"Content-Type": "application/json"},  # No auth token
            timeout=5
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 401:
            print(f"✓ Unauthenticated request rejected correctly")
            return True
        else:
            print(f"✗ Expected 401 Unauthorized, got {response.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def run_all_tests():
    """Run all REST API tests."""
    print_header("Document Upload REST API Integration Tests")
    print(f"Base URL: {BASE_URL}")
    print(f"API Base: {API_BASE}")
    print(f"Test Token: {TEST_TOKEN[:20]}...")
    
    results = []
    
    # Test 1: Server connection
    if not test_connection():
        print("\n✗ Cannot proceed without server connection")
        return False
    results.append(True)
    
    # Test 2: Get all configs
    results.append(test_get_all_configs())
    
    # Test 3: Get single config
    results.append(test_get_single_config("Google"))
    
    # Test 4: Update config
    results.append(test_update_config("Ollama"))
    
    # Test 5: Get updated config
    results.append(test_get_single_config("Ollama"))
    
    # Test 6: Reset config
    results.append(test_reset_config("Ollama"))
    
    # Test 7: Verify reset
    results.append(test_get_single_config("Ollama"))
    
    # Test 8: Invalid provider
    results.append(test_invalid_provider())
    
    # Test 9: Unauthorized access
    results.append(test_unauthorized_access())
    
    # Summary
    print_header("Test Summary")
    total = len(results)
    passed = sum(results)
    failed = total - passed
    
    print(f"Total tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    if failed == 0:
        print("\n✓ All REST API tests passed!")
        return True
    else:
        print(f"\n✗ {failed} test(s) failed")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
