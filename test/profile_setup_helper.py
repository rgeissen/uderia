#!/usr/bin/env python3
"""
Profile Setup Helper for Test Scripts

Provides utilities to check, create, and configure profiles for testing.
Handles LLM and MCP server configuration for test users.
"""

import requests
import json
from typing import Dict, Any, Optional, Tuple


class ProfileSetupHelper:
    """Helper class for profile setup in tests."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:5050"):
        self.base_url = base_url
        self.api_v1_base = f"{base_url}/api/v1"
        self.auth_base = f"{base_url}/api/v1/auth"
    
    def get_or_create_llm_config(self, jwt_token: str, user_uuid: str) -> Tuple[bool, str, Optional[str]]:
        """
        Get existing LLM config or create a test one.
        
        Returns:
            (success, config_id, error_message)
        """
        try:
            headers = {"Authorization": f"Bearer {jwt_token}"}
            
            # Get existing LLM configs
            response = requests.get(
                f"{self.api_v1_base}/llm-configurations",
                headers=headers
            )
            
            if response.status_code == 200:
                configs = response.json().get('llm_configurations', [])
                if configs:
                    # Return first available config
                    return True, configs[0].get('id'), None
            
            # No configs exist, try to create one
            # This would require valid credentials - for testing, we assume at least one exists
            return False, None, "No LLM configuration found. Please configure one via the UI first."
            
        except Exception as e:
            return False, None, str(e)
    
    def get_or_create_mcp_server(self, jwt_token: str, user_uuid: str) -> Tuple[bool, str, Optional[str]]:
        """
        Get existing MCP server or create a test one.
        
        Returns:
            (success, server_id, error_message)
        """
        try:
            headers = {"Authorization": f"Bearer {jwt_token}"}
            
            # Get existing MCP servers
            response = requests.get(
                f"{self.api_v1_base}/mcp-servers",
                headers=headers
            )
            
            if response.status_code == 200:
                servers = response.json().get('mcp_servers', [])
                if servers:
                    # Return first available server
                    return True, servers[0].get('id'), None
            
            # No servers exist
            return False, None, "No MCP Server configuration found. Please configure one via the UI first."
            
        except Exception as e:
            return False, None, str(e)
    
    def check_profiles(self, jwt_token: str) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Check if user has profiles and get profile info.
        
        Returns:
            (has_profiles, profile_info, error_message)
            profile_info contains: profiles, default_profile_id, active_for_consumption_profile_ids
        """
        try:
            headers = {"Authorization": f"Bearer {jwt_token}"}
            
            response = requests.get(
                f"{self.api_v1_base}/profiles",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                profiles = data.get('profiles', [])
                default_profile_id = data.get('default_profile_id')
                active_for_consumption = data.get('active_for_consumption_profile_ids', [])
                
                has_profiles = len(profiles) > 0
                has_default = default_profile_id is not None
                
                return has_profiles, {
                    'profiles': profiles,
                    'default_profile_id': default_profile_id,
                    'active_for_consumption_profile_ids': active_for_consumption,
                    'count': len(profiles),
                    'has_default': has_default
                }, None
            
            return False, {}, f"Failed to check profiles: {response.status_code}"
            
        except Exception as e:
            return False, {}, str(e)
    
    def create_profile(
        self, 
        jwt_token: str, 
        llm_config_id: str, 
        mcp_server_id: str,
        profile_name: str = "Test Profile"
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Create a new profile with LLM and MCP server.
        
        Returns:
            (success, profile_id, error_message)
        """
        try:
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "name": profile_name,
                "llmConfigurationId": llm_config_id,
                "mcpServerId": mcp_server_id
            }
            
            response = requests.post(
                f"{self.api_v1_base}/profiles",
                headers=headers,
                json=payload
            )
            
            if response.status_code == 201:
                data = response.json()
                profile_id = data.get('profile', {}).get('id')
                return True, profile_id, None
            
            error_msg = response.json().get('error', response.text) if response.text else response.reason
            return False, None, f"Failed to create profile: {error_msg}"
            
        except Exception as e:
            return False, None, str(e)
    
    def set_default_profile(self, jwt_token: str, profile_id: str) -> Tuple[bool, Optional[str]]:
        """
        Set a profile as default.
        
        Returns:
            (success, error_message)
        """
        try:
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{self.api_v1_base}/profiles/{profile_id}/set_default",
                headers=headers
            )
            
            if response.status_code == 200:
                return True, None
            
            error_msg = response.json().get('error', response.text) if response.text else response.reason
            return False, f"Failed to set default profile: {error_msg}"
            
        except Exception as e:
            return False, str(e)
    
    def ensure_profile_configured(self, jwt_token: str, user_uuid: str) -> Tuple[bool, Optional[str]]:
        """
        Ensure user has a default profile configured.
        If not, tries to create one from existing LLM + MCP configs.
        
        Returns:
            (success, error_message)
        """
        # Check if profile exists
        has_profiles, profile_info, error = self.check_profiles(jwt_token)
        
        if error:
            return False, error
        
        # If user has a default profile, we're good
        if profile_info.get('has_default'):
            return True, None
        
        # Try to create a profile from existing configs
        success, llm_id, llm_error = self.get_or_create_llm_config(jwt_token, user_uuid)
        if not success:
            return False, f"LLM setup: {llm_error}"
        
        success, mcp_id, mcp_error = self.get_or_create_mcp_server(jwt_token, user_uuid)
        if not success:
            return False, f"MCP setup: {mcp_error}"
        
        # Create profile
        success, profile_id, create_error = self.create_profile(jwt_token, llm_id, mcp_id)
        if not success:
            return False, create_error
        
        # Set as default
        success, set_error = self.set_default_profile(jwt_token, profile_id)
        if not success:
            return False, set_error
        
        return True, None


def print_profile_setup_requirement():
    """Print requirement message about profiles."""
    print("\n" + "=" * 70)
    print("PROFILE SETUP REQUIRED")
    print("=" * 70)
    print("""
The Uderia Platform now uses profiles for REST API session creation.

A profile consists of:
  • LLM Provider (e.g., Google, OpenAI, AWS Bedrock)
  • MCP Server (for data access)

To configure a profile:
print("  1. Open the web UI at http://localhost:5050")
  2. Click "Configuration" panel
  3. Add an LLM Provider (if not already added)
  4. Add an MCP Server (if not already added)
  5. Create a profile combining LLM + MCP
  6. Mark it as default

Alternatively, if you already have LLM and MCP configured,
this test script will try to create and set a default profile automatically.
    """)
    print("=" * 70 + "\n")
