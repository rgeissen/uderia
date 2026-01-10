# src/trusted_data_agent/core/config_manager.py
"""
Persistent configuration management for TDA.
Handles saving and loading application configuration to/from tda_config.json.
"""

import json
import logging
import copy
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

app_logger = logging.getLogger("quart.app")


class ConfigManager:
    """
    Manages persistent configuration stored in tda_config.json.
    
    The configuration file stores application objects that need to persist
    across application restarts, such as:
    - RAG collection metadata
    - User preferences (future)
    - Custom settings (future)
    """
    
    DEFAULT_CONFIG_FILENAME = "tda_config.json"
    
    # Schema version for future migration support
    CURRENT_SCHEMA_VERSION = "1.0"
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the configuration manager.
        
        Args:
            config_path: Path to the config file. If None, uses project root.
        """
        if config_path is None:
            # Use the get_project_root utility to find the correct project root
            from trusted_data_agent.core.utils import get_project_root
            project_root = get_project_root()
            config_path = project_root / self.DEFAULT_CONFIG_FILENAME
        
        self.config_path = Path(config_path)
        self._user_configs = {}  # Memory cache for loaded user configs from database
        pass  # ConfigManager initialized
    
    def _get_default_config(self) -> Dict[str, Any]:
        """
        Returns the default configuration structure.

        The default collection is NOT created here, but rather by RAGRetriever
        when it initializes, so it can use the current MCP server name.

        Returns:
            Default configuration dictionary
        """
        return {
            "schema_version": self.CURRENT_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_modified": datetime.now(timezone.utc).isoformat(),
            "rag_collections": [],  # Empty - default collection created by RAGRetriever
            "mcp_servers": [],  # MCP server configurations
            "active_mcp_server_id": None,  # ID of currently active MCP server
            "llm_configurations": [],  # LLM configuration settings
            "active_llm_configuration_id": None,  # ID of currently active LLM configuration
            "profiles": [],  # Profile configurations
            "default_profile_id": None,  # ID of the default profile (for consumption)
            "master_classification_profile_id": None,  # DEPRECATED: Legacy single master (backward compatibility only)
            "master_classification_profile_ids": {},  # NEW: Per-server masters {mcp_server_id: profile_id}
            "active_for_consumption_profile_ids": []  # IDs of profiles active for consumption
        }
    
    def _strip_credentials(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove all credentials from configuration for security before database storage.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Configuration dictionary with credentials removed
        """
        config = copy.deepcopy(config)
        
        # Strip credentials from LLM configurations
        if "llm_configurations" in config:
            for llm_config in config["llm_configurations"]:
                if "credentials" in llm_config:
                    llm_config["credentials"] = {}
        
        app_logger.debug("Stripped credentials from configuration before database storage")
        return config
    
    def load_config(self, user_uuid: Optional[str] = None) -> Dict[str, Any]:
        """
        Load per-user configuration from database (user_preferences).
        If user has no configuration yet, bootstrap from tda_config.json template.
        tda_config.json is read-only and never modified.
        
        Args:
            user_uuid: User UUID for per-user configuration (required for per-user config)
        
        Returns:
            Configuration dictionary
        """
        # If no user_uuid, return read-only bootstrap template from tda_config.json
        if not user_uuid:
            return self._load_bootstrap_template()
        
        # Check memory cache first
        if user_uuid in self._user_configs:
            return self._user_configs[user_uuid]
        
        # Load from database
        try:
            from trusted_data_agent.auth.database import get_db_session
            from trusted_data_agent.auth.models import UserPreference
            
            with get_db_session() as session:
                prefs = session.query(UserPreference).filter_by(user_id=user_uuid).first()
                
                if prefs and prefs.preferences_json:
                    # Load existing per-user configuration from database
                    user_config = json.loads(prefs.preferences_json)
                    self._user_configs[user_uuid] = user_config
                    app_logger.info(f"Loaded configuration from database for user {user_uuid}")
                    return user_config
        except Exception as e:
            app_logger.error(f"Error loading config from database for user {user_uuid}: {e}", exc_info=True)
        
        # No configuration in database - bootstrap from tda_config.json template
        app_logger.info(f"No configuration found for user {user_uuid} - bootstrapping from tda_config.json")
        bootstrap_config = self._load_bootstrap_template()
        
        # Create deep copy for this user
        user_config = copy.deepcopy(bootstrap_config)

        # Assign first LLM to @CHAT profile during bootstrap
        llm_configs = user_config.get("llm_configurations", [])
        first_llm_id = llm_configs[0]["id"] if llm_configs else None

        if first_llm_id:
            profiles = user_config.get("profiles", [])
            for profile in profiles:
                if profile.get("tag") == "CHAT" and profile.get("profile_type") == "llm_only":
                    if not profile.get("llmConfigurationId"):
                        profile["llmConfigurationId"] = first_llm_id
                        app_logger.info(f"✅ Assigned LLM {first_llm_id} to @CHAT profile during bootstrap")

        # Bootstrap configuration - do NOT auto-set profile defaults
        # The first profile activated by the user will become the default
        # This allows a clean bootstrap state where no profiles are pre-selected
        # Values are inherited from tda_config.json template (which has null/empty defaults)

        app_logger.info(f"Bootstrap complete for user {user_uuid} - no default/master/active profiles auto-set (user must activate a profile first)")

        self._user_configs[user_uuid] = user_config

        # Save to database for future loads
        self.save_config(user_config, user_uuid)
        
        return user_config
    
    def _load_bootstrap_template(self) -> Dict[str, Any]:
        """Load read-only bootstrap template from tda_config.json."""
        try:
            if not self.config_path.exists():
                app_logger.warning(f"Config file not found at {self.config_path}. Using default config.")
                return self._get_default_config()
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Validate schema version
            schema_version = config.get("schema_version", "unknown")
            if schema_version != self.CURRENT_SCHEMA_VERSION:
                app_logger.warning(
                    f"Config schema version mismatch. Expected {self.CURRENT_SCHEMA_VERSION}, "
                    f"got {schema_version}. Using existing config as-is."
                )
            
            return config
            
        except json.JSONDecodeError as e:
            app_logger.error(f"Invalid JSON in config file: {e}. Using default config.")
            return self._get_default_config()
            
        except Exception as e:
            app_logger.error(f"Error loading config file: {e}. Using default config.", exc_info=True)
            return self._get_default_config()
    
    def save_config(self, config: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Save per-user configuration to database (user_preferences).
        tda_config.json is never modified - it serves only as bootstrap template.
        
        Args:
            config: Configuration dictionary to save
            user_uuid: User UUID for per-user configuration storage (required)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not user_uuid:
                app_logger.warning("save_config called without user_uuid - configuration not saved (tda_config.json is read-only)")
                return False
            
            # Update last_modified timestamp
            config["last_modified"] = datetime.now(timezone.utc).isoformat()
            
            # Store in per-user memory cache
            self._user_configs[user_uuid] = config
            
            # Persist to database (user_preferences.preferences_json)
            from trusted_data_agent.auth.database import get_db_session
            from trusted_data_agent.auth.models import UserPreference
            
            with get_db_session() as session:
                prefs = session.query(UserPreference).filter_by(user_id=user_uuid).first()
                if not prefs:
                    prefs = UserPreference(user_id=user_uuid)
                    session.add(prefs)
                
                # Store config in preferences_json (excluding credentials for security)
                safe_config = self._strip_credentials(config)
                prefs.preferences_json = json.dumps(safe_config)
                prefs.updated_at = datetime.utcnow()
                session.commit()
            
            app_logger.info(f"Configuration saved to database for user {user_uuid}")
            return True
            
        except Exception as e:
            app_logger.error(f"Error saving config for user {user_uuid}: {e}", exc_info=True)
            return False
    
    def get_rag_collections(self, user_uuid: Optional[str] = None) -> list:
        """
        Get RAG collections from the database.
        
        Args:
            user_uuid: Optional user UUID to filter collections (owned + subscribed)
        
        Returns:
            List of RAG collection metadata dictionaries
        """
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        return collection_db.get_all_collections(user_uuid)
    
    def save_rag_collections(self, collections: list, user_uuid: Optional[str] = None) -> bool:
        """
        Save RAG collections - DEPRECATED, collections now stored in database.
        This method is kept for backward compatibility but does nothing.
        
        Args:
            collections: List of RAG collection metadata dictionaries (ignored)
            user_uuid: Optional user UUID (ignored)
            
        Returns:
            Always returns True
        """
        app_logger.warning("save_rag_collections called but collections are now in database")
        return True
    
    def add_rag_collection(self, collection_metadata: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Add a new RAG collection to the database.
        
        Args:
            collection_metadata: Collection metadata dictionary
            user_uuid: Optional user UUID (unused, owner is in collection_metadata)
            
        Returns:
            True if successful, False otherwise
        """
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        try:
            collection_db.create_collection(collection_metadata)
            return True
        except Exception as e:
            app_logger.error(f"Failed to add collection: {e}", exc_info=True)
            return False
    
    def update_rag_collection(self, collection_id: int, updates: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Update an existing RAG collection in the database.
        
        Args:
            collection_id: ID of the collection to update
            updates: Dictionary of fields to update
            user_uuid: Optional user UUID (unused)
            
        Returns:
            True if successful, False otherwise
        """
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        return collection_db.update_collection(collection_id, updates)
    
    def remove_rag_collection(self, collection_id: int, user_uuid: Optional[str] = None) -> bool:
        """
        Remove a RAG collection from the database.
        
        Args:
            collection_id: ID of the collection to remove
            user_uuid: Optional user UUID (unused)
            
        Returns:
            True if successful, False otherwise
        """
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        return collection_db.delete_collection(collection_id)
    
    # ========================================================================
    # MCP SERVER CONFIGURATION METHODS
    # ========================================================================
    
    def get_mcp_servers(self, user_uuid: Optional[str] = None) -> list:
        """
        Get all MCP server configurations.
        
        Args:
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            List of MCP server configuration dictionaries
        """
        config = self.load_config(user_uuid)
        return config.get("mcp_servers", [])
    
    def save_mcp_servers(self, servers: list, user_uuid: Optional[str] = None) -> bool:
        """
        Save MCP server configurations.
        
        Args:
            servers: List of MCP server configuration dictionaries
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        config = self.load_config(user_uuid)
        config["mcp_servers"] = servers
        return self.save_config(config, user_uuid)
    
    def add_mcp_server(self, server: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Add a new MCP server configuration.
        
        Args:
            server: MCP server configuration dictionary
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        servers = self.get_mcp_servers(user_uuid)
        servers.append(server)
        return self.save_mcp_servers(servers, user_uuid)
    
    def update_mcp_server(self, server_id: str, updates: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Update an existing MCP server configuration.
        
        Args:
            server_id: Unique ID of the server to update
            updates: Dictionary of fields to update
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        servers = self.get_mcp_servers(user_uuid)
        app_logger.info(f"Looking for MCP server {server_id} in {len(servers)} servers for user {user_uuid}")
        app_logger.debug(f"Available server IDs: {[s.get('id') for s in servers]}")
        
        server = next((s for s in servers if s.get("id") == server_id), None)
        
        if not server:
            app_logger.warning(f"MCP server with ID {server_id} not found for update")
            return False
        
        server.update(updates)
        return self.save_mcp_servers(servers, user_uuid)
    
    def remove_mcp_server(self, server_id: str, user_uuid: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        Remove an MCP server configuration.
        Prevents deletion if any RAG collections or profiles are assigned to this server.

        Args:
            server_id: Unique ID of the server to remove
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
            If successful, error_message is None
            If failed, error_message contains the reason
        """
        # Check if any profiles reference this server
        profiles = self.get_profiles(user_uuid)
        dependent_profiles = [
            p for p in profiles
            if p.get("profile_type") == "tool_enabled" and p.get("mcpServerId") == server_id
        ]

        if dependent_profiles:
            profile_names = [
                p.get("profileName") or p.get("name") or f"@{p.get('tag')}" or "Unknown"
                for p in dependent_profiles
            ]
            names_list = ", ".join(profile_names)
            error_msg = f"Cannot delete MCP server: {len(dependent_profiles)} profile(s) depend on it: {names_list}"
            app_logger.warning(f"{error_msg} (Server ID: {server_id})")
            return False, error_msg

        # Check if any collections are assigned to this server
        collections = self.get_rag_collections(user_uuid)
        assigned_collections = [
            c for c in collections
            if c.get("mcp_server_id") == server_id
        ]

        if assigned_collections:
            collection_names = [c.get("name", "Unknown") for c in assigned_collections]
            names_list = ", ".join(collection_names)
            error_msg = f"Cannot delete MCP server: {len(assigned_collections)} collection(s) assigned: {names_list}"
            app_logger.warning(f"{error_msg} (Server ID: {server_id})")
            return False, error_msg

        servers = self.get_mcp_servers(user_uuid)
        original_count = len(servers)
        servers = [s for s in servers if s.get("id") != server_id]

        if len(servers) == original_count:
            error_msg = "MCP server not found"
            app_logger.warning(f"MCP server with ID {server_id} not found for removal")
            return False, error_msg

        success = self.save_mcp_servers(servers, user_uuid)
        return success, None if success else "Failed to save configuration"
    
    def get_active_mcp_server_id(self, user_uuid: Optional[str] = None) -> Optional[str]:
        """
        Get the ID of the currently active MCP server.
        
        Args:
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            Active MCP server ID or None
        """
        config = self.load_config(user_uuid)
        return config.get("active_mcp_server_id")
    
    def set_active_mcp_server_id(self, server_id: Optional[str], user_uuid: Optional[str] = None) -> bool:
        """
        Set the active MCP server ID.
        
        Args:
            server_id: ID of the server to set as active, or None to clear
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        config = self.load_config(user_uuid)
        config["active_mcp_server_id"] = server_id
        return self.save_config(config, user_uuid)
    
    def get_all_mcp_tools(self, mcp_server_id: Optional[str] = None, user_uuid: Optional[str] = None) -> list:
        """
        Get the list of all available tools for a specific MCP server.
        If no server_id provided, uses the active MCP server.
        
        Args:
            mcp_server_id: Optional MCP server ID
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            List of all available tool names from the MCP server
        """
        if not mcp_server_id:
            mcp_server_id = self.get_active_mcp_server_id(user_uuid)
        
        if not mcp_server_id:
            return []
        
        config = self.load_config(user_uuid)
        mcp_servers = config.get("mcp_servers", [])
        
        for server in mcp_servers:
            if server.get("id") == mcp_server_id:
                return server.get("all_tools", [])
        
        return []
    
    def get_all_mcp_prompts(self, mcp_server_id: Optional[str] = None, user_uuid: Optional[str] = None) -> list:
        """
        Get the list of all available prompts for a specific MCP server.
        If no server_id provided, uses the active MCP server.
        
        Args:
            mcp_server_id: Optional MCP server ID
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            List of all available prompt names from the MCP server
        """
        if not mcp_server_id:
            mcp_server_id = self.get_active_mcp_server_id(user_uuid)
        
        if not mcp_server_id:
            return []
        
        config = self.load_config(user_uuid)
        mcp_servers = config.get("mcp_servers", [])
        
        for server in mcp_servers:
            if server.get("id") == mcp_server_id:
                return server.get("all_prompts", [])
        
        return []
    
    def get_profile_enabled_tools(self, profile_id: str, user_uuid: Optional[str] = None) -> list:
        """
        Get the list of enabled tools for a specific profile.

        If the profile has inherit_classification=true, returns the master classification profile's enabled tools instead.

        Args:
            profile_id: Profile ID
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            List of enabled tool names for this profile (or master classification profile if inheriting)
        """
        profiles = self.get_profiles(user_uuid)
        target_profile = None

        for profile in profiles:
            if profile.get("id") == profile_id:
                target_profile = profile
                break

        if not target_profile:
            return []

        # Check if profile inherits classification from master classification profile
        if target_profile.get("inherit_classification", False):
            # === STRICT ENFORCEMENT: Profile MUST inherit from per-server master ===
            current_mcp_server_id = target_profile.get('mcpServerId')

            # Use strict=True to ONLY get explicitly set per-server master (no fallbacks)
            master_profile_id = self.get_master_classification_profile_id(
                user_uuid,
                current_mcp_server_id,
                strict=True
            )

            if not master_profile_id:
                app_logger.error(
                    f"Profile {profile_id} has inherit_classification enabled but "
                    f"no master classification profile is set for MCP server '{current_mcp_server_id}'. "
                    f"Returning empty tools list."
                )
                return []

            if master_profile_id == profile_id:
                app_logger.error(
                    f"Profile {profile_id} cannot inherit classification from itself. "
                    f"Returning profile's own tools."
                )
                return target_profile.get("tools", target_profile.get("enabled_tools", []))

            # Find master profile
            master_profile = None
            for profile in profiles:
                if profile.get("id") == master_profile_id:
                    master_profile = profile
                    break

            if not master_profile:
                app_logger.error(
                    f"Master classification profile {master_profile_id} not found for profile {profile_id}. "
                    f"Returning empty tools list."
                )
                return []

            # === VALIDATION: Verify MCP server compatibility (should always match with strict mode) ===
            master_mcp_server_id = master_profile.get('mcpServerId')
            if current_mcp_server_id != master_mcp_server_id:
                app_logger.error(
                    f"DATA INTEGRITY ERROR: Profile {profile_id} uses MCP server '{current_mcp_server_id}' "
                    f"but master profile {master_profile_id} uses '{master_mcp_server_id}'. "
                    f"This should not happen with strict mode. Returning empty tools list."
                )
                return []

            app_logger.info(
                f"✓ Profile {profile_id} inherits tools from per-server master {master_profile_id} "
                f"(MCP server: {current_mcp_server_id})"
            )
            return master_profile.get("tools", master_profile.get("enabled_tools", []))

        # Frontend stores as 'tools', legacy field was 'enabled_tools'
        return target_profile.get("tools", target_profile.get("enabled_tools", []))
    
    def get_profile_enabled_prompts(self, profile_id: str, user_uuid: Optional[str] = None) -> list:
        """
        Get the list of enabled prompts for a specific profile.

        If the profile has inherit_classification=true, returns the master classification profile's enabled prompts instead.

        Args:
            profile_id: Profile ID
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            List of enabled prompt names for this profile (or master classification profile if inheriting)
        """
        profiles = self.get_profiles(user_uuid)
        target_profile = None

        for profile in profiles:
            if profile.get("id") == profile_id:
                target_profile = profile
                break

        if not target_profile:
            return []

        # Check if profile inherits classification from master classification profile
        if target_profile.get("inherit_classification", False):
            # === STRICT ENFORCEMENT: Profile MUST inherit from per-server master ===
            current_mcp_server_id = target_profile.get('mcpServerId')

            # Use strict=True to ONLY get explicitly set per-server master (no fallbacks)
            master_profile_id = self.get_master_classification_profile_id(
                user_uuid,
                current_mcp_server_id,
                strict=True
            )

            if not master_profile_id:
                app_logger.error(
                    f"Profile {profile_id} has inherit_classification enabled but "
                    f"no master classification profile is set for MCP server '{current_mcp_server_id}'. "
                    f"Returning empty prompts list."
                )
                return []

            if master_profile_id == profile_id:
                app_logger.error(
                    f"Profile {profile_id} cannot inherit classification from itself. "
                    f"Returning profile's own prompts."
                )
                return target_profile.get("prompts", target_profile.get("enabled_prompts", []))

            # Find master profile
            master_profile = None
            for profile in profiles:
                if profile.get("id") == master_profile_id:
                    master_profile = profile
                    break

            if not master_profile:
                app_logger.error(
                    f"Master classification profile {master_profile_id} not found for profile {profile_id}. "
                    f"Returning empty prompts list."
                )
                return []

            # === VALIDATION: Verify MCP server compatibility (should always match with strict mode) ===
            master_mcp_server_id = master_profile.get('mcpServerId')
            if current_mcp_server_id != master_mcp_server_id:
                app_logger.error(
                    f"DATA INTEGRITY ERROR: Profile {profile_id} uses MCP server '{current_mcp_server_id}' "
                    f"but master profile {master_profile_id} uses '{master_mcp_server_id}'. "
                    f"This should not happen with strict mode. Returning empty prompts list."
                )
                return []

            app_logger.info(
                f"✓ Profile {profile_id} inherits prompts from per-server master {master_profile_id} "
                f"(MCP server: {current_mcp_server_id})"
            )
            return master_profile.get("prompts", master_profile.get("enabled_prompts", []))

        # Frontend stores as 'prompts', legacy field was 'enabled_prompts'
        return target_profile.get("prompts", target_profile.get("enabled_prompts", []))
    
    def get_profile_disabled_tools(self, profile_id: str, user_uuid: Optional[str] = None) -> list:
        """
        Dynamically calculate disabled tools for a profile.
        This is the set difference: all_tools - enabled_tools
        TDA_ tools are NEVER disabled (mandatory core capabilities).

        Args:
            profile_id: Profile ID
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            List of disabled tool names for this profile (excluding TDA_ tools)
        """
        profile = next((p for p in self.get_profiles(user_uuid) if p.get("id") == profile_id), None)
        if not profile:
            return []

        # Get enabled tools for this profile
        enabled_tools_list = self.get_profile_enabled_tools(profile_id, user_uuid)

        # Handle wildcard: if enabled_tools is ['*'], all tools are enabled (nothing disabled)
        if enabled_tools_list == ['*']:
            return []

        # Get all tools from APP_STATE (populated from live MCP server during classification)
        # Fallback to config file if APP_STATE not available
        from trusted_data_agent.core.config import APP_STATE
        all_tools = set(APP_STATE.get('mcp_tools', {}).keys()) if APP_STATE.get('mcp_tools') else set()

        # If APP_STATE has no tools yet, fallback to config file (for backwards compatibility)
        if not all_tools:
            mcp_server_id = profile.get("mcpServerId")
            all_tools = set(self.get_all_mcp_tools(mcp_server_id, user_uuid))

        enabled_tools = set(enabled_tools_list)

        # Calculate disabled tools, but exclude TDA_ tools (they are ALWAYS enabled)
        disabled_tools = {tool for tool in all_tools if tool not in enabled_tools and not tool.startswith('TDA_')}

        return list(disabled_tools)
    
    def get_profile_disabled_prompts(self, profile_id: str, user_uuid: Optional[str] = None) -> list:
        """
        Dynamically calculate disabled prompts for a profile.
        This is the set difference: all_prompts - enabled_prompts
        TDA_ prompts are NEVER disabled (mandatory core capabilities).

        Args:
            profile_id: Profile ID
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            List of disabled prompt names for this profile (excluding TDA_ prompts)
        """
        profile = next((p for p in self.get_profiles(user_uuid) if p.get("id") == profile_id), None)
        if not profile:
            return []

        # Get enabled prompts for this profile
        enabled_prompts_list = self.get_profile_enabled_prompts(profile_id, user_uuid)

        # Handle wildcard: if enabled_prompts is ['*'], all prompts are enabled (nothing disabled)
        if enabled_prompts_list == ['*']:
            return []

        # Get all prompts from APP_STATE (populated from live MCP server during classification)
        # Fallback to config file if APP_STATE not available
        from trusted_data_agent.core.config import APP_STATE
        all_prompts = set(APP_STATE.get('mcp_prompts', {}).keys()) if APP_STATE.get('mcp_prompts') else set()

        # If APP_STATE has no prompts yet, fallback to config file (for backwards compatibility)
        if not all_prompts:
            mcp_server_id = profile.get("mcpServerId")
            all_prompts = set(self.get_all_mcp_prompts(mcp_server_id, user_uuid))

        enabled_prompts = set(enabled_prompts_list)

        # Calculate disabled prompts, but exclude TDA_ prompts (they are ALWAYS enabled)
        disabled_prompts = {prompt for prompt in all_prompts if prompt not in enabled_prompts and not prompt.startswith('TDA_')}

        return list(disabled_prompts)

    # ========================================================================
    # PROFILE CONFIGURATION METHODS
    # ========================================================================

    def get_profiles(self, user_uuid: Optional[str] = None) -> list:
        """
        Get all profile configurations.
        
        Args:
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            List of profile configuration dictionaries
        """
        config = self.load_config(user_uuid)
        return config.get("profiles", [])

    def get_profile(self, profile_id: str, user_uuid: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a single profile by ID.
        
        Args:
            profile_id: Profile ID to retrieve
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            Profile configuration dictionary or None if not found
        """
        profiles = self.get_profiles(user_uuid)
        return next((p for p in profiles if p.get("id") == profile_id), None)

    def save_profiles(self, profiles: list, user_uuid: Optional[str] = None) -> bool:
        """
        Save profile configurations.
        
        Args:
            profiles: List of profile configuration dictionaries
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        config = self.load_config(user_uuid)
        config["profiles"] = profiles
        return self.save_config(config, user_uuid)

    def add_profile(self, profile: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Add a new profile configuration.
        
        Args:
            profile: Profile configuration dictionary
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        profiles = self.get_profiles(user_uuid)
        profiles.append(profile)
        return self.save_profiles(profiles, user_uuid)

    def update_profile(self, profile_id: str, updates: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Update an existing profile configuration.
        
        Args:
            profile_id: Unique ID of the profile to update
            updates: Dictionary of fields to update
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        profiles = self.get_profiles(user_uuid)
        profile = next((p for p in profiles if p.get("id") == profile_id), None)
        
        if not profile:
            app_logger.warning(f"Profile with ID {profile_id} not found for update")
            return False
        
        profile.update(updates)
        return self.save_profiles(profiles, user_uuid)

    def remove_profile(self, profile_id: str, user_uuid: Optional[str] = None) -> bool:
        """
        Remove a profile configuration.
        
        Args:
            profile_id: Unique ID of the profile to remove
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        profiles = self.get_profiles(user_uuid)
        original_count = len(profiles)
        profiles = [p for p in profiles if p.get("id") != profile_id]
        
        if len(profiles) == original_count:
            app_logger.warning(f"Profile with ID {profile_id} not found for removal")
            return False
        
        return self.save_profiles(profiles, user_uuid)

    def validate_profile(self, profile: Dict[str, Any]) -> tuple[bool, str]:
        """
        Validate a profile's configuration.

        Args:
            profile: Profile configuration dictionary

        Returns:
            Tuple of (is_valid: bool, error_message: str)
            If valid, returns (True, "")
            If invalid, returns (False, "error message")
        """
        profile_type = profile.get("profile_type", "tool_enabled")

        if profile_type == "rag_focused":
            # RAG focused REQUIRES knowledge collections
            knowledge_config = profile.get("knowledgeConfig", {})
            knowledge_collections = knowledge_config.get("collections", [])

            if not knowledge_collections or len(knowledge_collections) == 0:
                return False, "RAG focused profiles require at least 1 knowledge collection"

        return True, ""

    def get_default_profile_id(self, user_uuid: Optional[str] = None) -> Optional[str]:
        """
        Get the ID of the currently default profile.
        
        Args:
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            Default profile ID or None
        """
        config = self.load_config(user_uuid)
        return config.get("default_profile_id")

    def set_default_profile_id(self, profile_id: Optional[str], user_uuid: Optional[str] = None) -> bool:
        """
        Set the default profile ID.
        
        Args:
            profile_id: ID of the profile to set as default, or None to clear
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        config = self.load_config(user_uuid)
        config["default_profile_id"] = profile_id
        return self.save_config(config, user_uuid)

    def get_active_for_consumption_profile_ids(self, user_uuid: Optional[str] = None) -> list:
        """
        Get the IDs of the profiles active for consumption.
        
        Args:
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            List of active profile IDs
        """
        config = self.load_config(user_uuid)
        return config.get("active_for_consumption_profile_ids", [])

    def set_active_for_consumption_profile_ids(self, profile_ids: list, user_uuid: Optional[str] = None) -> bool:
        """
        Set the IDs of the profiles active for consumption.

        Args:
            profile_ids: List of profile IDs to set as active
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            True if successful, False otherwise
        """
        config = self.load_config(user_uuid)
        config["active_for_consumption_profile_ids"] = profile_ids
        return self.save_config(config, user_uuid)

    def get_master_classification_profile_id(
        self,
        user_uuid: Optional[str] = None,
        mcp_server_id: Optional[str] = None,
        strict: bool = False
    ) -> Optional[str]:
        """
        Get master classification profile ID for a specific MCP server.

        The master profile is the reference for classification inheritance.
        Always returns a tool_enabled profile ID (not llm_only).

        IMPORTANT: With per-server masters, you should pass mcp_server_id.
        If mcp_server_id is not provided, falls back to legacy single-master behavior.

        Args:
            user_uuid: Optional user UUID for per-user configuration isolation
            mcp_server_id: MCP server ID to get master for (NEW - supports multiple masters)
            strict: If True, ONLY return explicitly set per-server master (no fallbacks).
                   Use strict=True for inheritance validation to ensure data integrity.

        Returns:
            Master classification profile ID or None if:
            - (strict=True) No per-server master explicitly set for this MCP server
            - (strict=False) No tool_enabled profiles exist for this server
        """
        config = self.load_config(user_uuid)

        # === STRICT MODE: Only return explicitly set per-server master ===
        if strict and mcp_server_id:
            master_ids = config.get('master_classification_profile_ids', {})
            if isinstance(master_ids, dict) and mcp_server_id in master_ids:
                master_id = master_ids[mcp_server_id]
                app_logger.debug(f"[STRICT] Found master classification profile for MCP server {mcp_server_id}: {master_id}")
                return master_id
            else:
                app_logger.debug(f"[STRICT] No master classification profile set for MCP server {mcp_server_id}")
                return None

        # === NON-STRICT MODE: Check per-server master with fallbacks ===
        if mcp_server_id:
            master_ids = config.get('master_classification_profile_ids', {})
            if isinstance(master_ids, dict) and mcp_server_id in master_ids:
                master_id = master_ids[mcp_server_id]
                app_logger.debug(f"Found master classification profile for MCP server {mcp_server_id}: {master_id}")
                return master_id

        # === BACKWARD COMPATIBILITY: Legacy single master ===
        legacy_master_id = config.get('master_classification_profile_id')
        if legacy_master_id:
            app_logger.debug(f"Using legacy single master classification profile: {legacy_master_id}")
            return legacy_master_id

        # === FALLBACK: Find first tool_enabled profile for this server ===
        if mcp_server_id:
            profiles = self.get_profiles(user_uuid)
            for profile in profiles:
                if (profile.get('profile_type') != 'llm_only' and
                    profile.get('mcpServerId') == mcp_server_id):
                    app_logger.debug(
                        f"No master classification profile set for MCP server {mcp_server_id}, "
                        f"using first tool_enabled profile: {profile['id']}"
                    )
                    return profile['id']

        # === LEGACY FALLBACK: Any tool_enabled profile ===
        profiles = self.get_profiles(user_uuid)
        for profile in profiles:
            if profile.get('profile_type') != 'llm_only':
                app_logger.debug(f"No master classification profile set, using first tool_enabled profile: {profile['id']}")
                return profile['id']

        app_logger.warning(f"No tool_enabled profiles found for user {user_uuid} - cannot determine master classification profile")
        return None

    def set_master_classification_profile_id(
        self,
        profile_id: str,
        user_uuid: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Set master classification profile for user.

        Validates that profile is tool_enabled before setting.
        Master classification profile must have an MCP server configured.
        If the profile has inherit_classification enabled, it will be disabled automatically.

        Args:
            profile_id: ID of the profile to set as master
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            Dictionary with "status" key:
            - {"status": "success"} if successful
            - {"status": "error", "message": "..."} if validation fails
        """
        # Validate profile exists
        profile = self.get_profile(profile_id, user_uuid)
        if not profile:
            return {"status": "error", "message": f"Profile {profile_id} not found"}

        # Validate profile is tool_enabled (not llm_only or rag_focused)
        profile_type = profile.get('profile_type')
        if profile_type == 'llm_only':
            return {
                "status": "error",
                "message": "Master classification profile must be tool-enabled (llm_only profiles have no tools/prompts to inherit)"
            }
        if profile_type == 'rag_focused':
            return {
                "status": "error",
                "message": "Master classification profile must be tool-enabled (rag_focused profiles don't use planner/tools)"
            }

        # Validate profile has MCP server
        if not profile.get('mcpServerId'):
            return {
                "status": "error",
                "message": "Master classification profile must have an MCP server configured"
            }

        # If profile has inherit_classification enabled, disable it (prevent circular dependency)
        if profile.get('inherit_classification', False):
            app_logger.info(f"Disabling inherit_classification for profile {profile_id} as it's being set as master")
            self.update_profile(profile_id, {'inherit_classification': False}, user_uuid)

        # === NEW: Store master per MCP server ===
        mcp_server_id = profile.get('mcpServerId')
        config = self.load_config(user_uuid)

        # Initialize master_classification_profile_ids if it doesn't exist
        if 'master_classification_profile_ids' not in config or not isinstance(config['master_classification_profile_ids'], dict):
            config['master_classification_profile_ids'] = {}

        # Set master for this MCP server
        config['master_classification_profile_ids'][mcp_server_id] = profile_id

        # === BACKWARD COMPATIBILITY: Also update legacy single master (deprecated) ===
        config['master_classification_profile_id'] = profile_id

        success = self.save_config(config, user_uuid)

        if not success:
            return {"status": "error", "message": "Failed to save configuration"}

        app_logger.info(f"Set master classification profile for MCP server {mcp_server_id} to {profile_id} (user: {user_uuid})")
        return {"status": "success", "mcp_server_id": mcp_server_id}

    # ========================================================================
    # PROFILE CLASSIFICATION METHODS
    # ========================================================================
    
    def get_profile_classification(self, profile_id: str, user_uuid: Optional[str] = None) -> Dict[str, Any]:
        """
        Get classification results for a specific profile.
        
        Args:
            profile_id: Profile ID
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            Classification results dictionary or empty dict if not found
        """
        profiles = self.get_profiles(user_uuid)
        profile = next((p for p in profiles if p.get("id") == profile_id), None)
        if profile:
            return profile.get("classification_results", {})
        return {}
    
    def save_profile_classification(self, profile_id: str, classification_results: Dict[str, Any], 
                                   user_uuid: Optional[str] = None) -> bool:
        """
        Save classification results for a specific profile.
        
        Args:
            profile_id: Profile ID
            classification_results: Classification data including tools, prompts, resources
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            True if successful, False otherwise
        """
        from datetime import datetime, timezone
        
        profiles = self.get_profiles(user_uuid)
        profile = next((p for p in profiles if p.get("id") == profile_id), None)
        
        if not profile:
            app_logger.warning(f"Profile {profile_id} not found for classification save")
            return False
        
        # Update classification results with timestamp
        classification_results["last_classified"] = datetime.now(timezone.utc).isoformat()
        classification_results["classified_with_mode"] = profile.get("classification_mode", "full")
        
        profile["classification_results"] = classification_results
        return self.save_profiles(profiles, user_uuid)
    
    def clear_profile_classification(self, profile_id: str, user_uuid: Optional[str] = None) -> bool:
        """
        Clear classification cache for a profile to force reclassification.
        
        Args:
            profile_id: Profile ID
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            True if successful, False otherwise
        """
        empty_results = {
            "tools": {},
            "prompts": {},
            "resources": {},
            "last_classified": None,
            "classified_with_mode": None
        }
        return self.save_profile_classification(profile_id, empty_results, user_uuid)

    # ========================================================================
    # LLM CONFIGURATION METHODS
    # ========================================================================

    def get_llm_configurations(self, user_uuid: Optional[str] = None) -> list:
        """
        Get all LLM configurations.
        
        Args:
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            List of LLM configuration dictionaries
        """
        config = self.load_config(user_uuid)
        return config.get("llm_configurations", [])

    def save_llm_configurations(self, configurations: list, user_uuid: Optional[str] = None) -> bool:
        """
        Save LLM configurations.
        
        Args:
            configurations: List of LLM configuration dictionaries
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        config = self.load_config(user_uuid)
        config["llm_configurations"] = configurations
        return self.save_config(config, user_uuid)

    def add_llm_configuration(self, configuration: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Add a new LLM configuration.
        
        Args:
            configuration: LLM configuration dictionary
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        configurations = self.get_llm_configurations(user_uuid)
        configurations.append(configuration)
        return self.save_llm_configurations(configurations, user_uuid)

    def update_llm_configuration(self, config_id: str, updates: Dict[str, Any], user_uuid: Optional[str] = None) -> bool:
        """
        Update an existing LLM configuration.
        
        Args:
            config_id: Unique ID of the configuration to update
            updates: Dictionary of fields to update
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        configurations = self.get_llm_configurations(user_uuid)
        configuration = next((c for c in configurations if c.get("id") == config_id), None)
        
        if not configuration:
            app_logger.warning(f"LLM configuration with ID {config_id} not found for update")
            return False
        
        configuration.update(updates)
        return self.save_llm_configurations(configurations, user_uuid)

    def remove_llm_configuration(self, config_id: str, user_uuid: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        Remove an LLM configuration.
        Prevents deletion if any profiles are assigned to this configuration.
        
        Args:
            config_id: Unique ID of the configuration to remove
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
            If successful, error_message is None
            If failed, error_message contains the reason
        """
        # Check if any profiles are assigned to this configuration
        profiles = self.get_profiles(user_uuid)
        assigned_profiles = [
            p for p in profiles 
            if p.get("llmConfigurationId") == config_id
        ]
        
        if assigned_profiles:
            profile_tags = [p.get("tag", "Unknown") for p in assigned_profiles]
            tags_list = ", ".join(profile_tags)
            error_msg = f"Cannot delete LLM configuration: {len(assigned_profiles)} profile(s) assigned: {tags_list}"
            app_logger.warning(f"{error_msg} (Config ID: {config_id})")
            return False, error_msg
        
        configurations = self.get_llm_configurations(user_uuid)
        original_count = len(configurations)
        configurations = [c for c in configurations if c.get("id") != config_id]
        
        if len(configurations) == original_count:
            error_msg = "LLM configuration not found"
            app_logger.warning(f"LLM configuration with ID {config_id} not found for removal")
            return False, error_msg
        
        success = self.save_llm_configurations(configurations, user_uuid)
        return success, None if success else "Failed to save configuration"

    def get_active_llm_configuration_id(self, user_uuid: Optional[str] = None) -> Optional[str]:
        """
        Get the ID of the currently active LLM configuration.
        
        Args:
            user_uuid: Optional user UUID for per-user configuration isolation
        
        Returns:
            Active LLM configuration ID or None
        """
        config = self.load_config(user_uuid)
        return config.get("active_llm_configuration_id")

    def set_active_llm_configuration_id(self, config_id: Optional[str], user_uuid: Optional[str] = None) -> bool:
        """
        Set the active LLM configuration ID.
        
        Args:
            config_id: ID of the configuration to set as active, or None to clear
            user_uuid: Optional user UUID for per-user configuration isolation
            
        Returns:
            True if successful, False otherwise
        """
        config = self.load_config(user_uuid)
        config["active_llm_configuration_id"] = config_id
        return self.save_config(config, user_uuid)


# Singleton instance
_config_manager_instance: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """
    Get the singleton ConfigManager instance.
    
    Returns:
        ConfigManager instance
    """
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = ConfigManager()
    return _config_manager_instance
