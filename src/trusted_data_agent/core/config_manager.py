# src/trusted_data_agent/core/config_manager.py
"""
Persistent configuration management for TDA.
Handles saving and loading application configuration to/from tda_config.json.
"""

import json
import logging
import copy
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from sqlalchemy import text

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

                    # Sync any new default profiles from bootstrap template
                    original_profile_count = len(user_config.get("profiles", []))
                    user_config = self._sync_new_default_profiles(user_config)
                    new_profile_count = len(user_config.get("profiles", []))

                    self._user_configs[user_uuid] = user_config

                    # If new profiles were added, save the updated config
                    if new_profile_count > original_profile_count:
                        self.save_config(user_config, user_uuid)

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

    def _sync_new_default_profiles(self, user_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sync any new default profiles from bootstrap template to user config.

        This handles the case where new default profiles (like Genie) are added
        to tda_config.json after a user has already bootstrapped. Without this,
        existing users would never see new default profiles.

        Only profiles with IDs starting with 'profile-default-' are synced.
        User-created profiles and modifications to existing profiles are preserved.

        Args:
            user_config: User's current configuration

        Returns:
            Updated user configuration with any new default profiles added
        """
        try:
            bootstrap_config = self._load_bootstrap_template()
            bootstrap_profiles = bootstrap_config.get("profiles", [])
            user_profiles = user_config.get("profiles", [])

            # Get set of existing profile IDs in user config
            existing_profile_ids = {p.get("id") for p in user_profiles}

            # Find default profiles in bootstrap that are missing from user config
            new_profiles_added = []
            for bootstrap_profile in bootstrap_profiles:
                profile_id = bootstrap_profile.get("id", "")

                # Only sync profiles with default prefix
                if not profile_id.startswith("profile-default-"):
                    continue

                # Skip if user already has this profile
                if profile_id in existing_profile_ids:
                    continue

                # Add the missing default profile
                user_profiles.append(copy.deepcopy(bootstrap_profile))
                new_profiles_added.append(profile_id)

            if new_profiles_added:
                user_config["profiles"] = user_profiles
                app_logger.info(f"Synced {len(new_profiles_added)} new default profile(s) to user config: {new_profiles_added}")

            return user_config

        except Exception as e:
            app_logger.warning(f"Error syncing default profiles: {e}")
            return user_config

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

    def get_default_collection_for_mcp_server(self, mcp_server_id: str, user_uuid: Optional[str] = None) -> Optional[int]:
        """
        Get the default RAG collection ID for a specific MCP server.

        Args:
            mcp_server_id: The MCP server ID
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            Collection ID of the default collection for this MCP server, or None if not found
        """
        try:
            from trusted_data_agent.core.collection_db import get_collection_db
            collection_db = get_collection_db()

            # Get all collections for this MCP server
            all_collections = collection_db.get_all_collections()

            # Filter by MCP server and repository type (planner)
            server_collections = [
                c for c in all_collections
                if c.get('mcp_server_id') == mcp_server_id
                and c.get('repository_type') == 'planner'
                and (user_uuid is None or c.get('owner_user_id') == user_uuid)
            ]

            if not server_collections:
                app_logger.warning(f"No collections found for MCP server '{mcp_server_id}'")
                return None

            # Return the first (oldest) collection for this MCP server as the default
            # Collections are typically sorted by ID (creation order)
            default_collection = sorted(server_collections, key=lambda c: c.get('id', 0))[0]
            return default_collection.get('id')

        except Exception as e:
            app_logger.error(f"Error getting default collection for MCP server '{mcp_server_id}': {e}", exc_info=True)
            return None
    
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
        Also creates a default RAG collection for this MCP server.

        Args:
            server: MCP server configuration dictionary
            user_uuid: Optional user UUID for per-user configuration isolation

        Returns:
            True if successful, False otherwise
        """
        servers = self.get_mcp_servers(user_uuid)
        servers.append(server)
        success = self.save_mcp_servers(servers, user_uuid)

        if success:
            # Create a default RAG collection for this MCP server
            try:
                from trusted_data_agent.agent.rag_retriever import RAGRetriever
                from trusted_data_agent.core.config import APP_STATE

                rag_retriever = APP_STATE.get('rag_retriever_instance')
                if rag_retriever:
                    server_name = server.get('name', 'Unknown Server')
                    server_id = server.get('id')

                    # Create default collection for this MCP server
                    collection_name = f"Default Collection - {server_name}"
                    collection_description = f"Default planner repository for MCP server: {server_name}"

                    collection_id = rag_retriever.add_collection(
                        name=collection_name,
                        description=collection_description,
                        mcp_server_id=server_id,
                        owner_user_id=user_uuid,
                        repository_type="planner",
                        embedding_model="all-MiniLM-L6-v2"
                    )

                    if collection_id:
                        app_logger.info(f"Created default RAG collection {collection_id} for MCP server '{server_name}' (ID: {server_id})")
                    else:
                        app_logger.warning(f"Failed to create default RAG collection for MCP server '{server_name}'")
                else:
                    app_logger.warning("RAG retriever not available - skipping default collection creation")
            except Exception as e:
                app_logger.error(f"Error creating default RAG collection for MCP server: {e}", exc_info=True)
                # Don't fail the MCP server addition if collection creation fails

        return success
    
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

        CASCADE DELETE: Automatically deletes all collections associated with this MCP server.

        Prevents deletion if:
        - Any profiles reference this server (mcpServerId)
        - Any profiles use the server's collections (in ragCollections or knowledgeConfig)

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

        # CASCADE DELETE: Automatically delete all collections assigned to this server
        collections = self.get_rag_collections(user_uuid)
        assigned_collections = [
            c for c in collections
            if c.get("mcp_server_id") == server_id
        ]

        # Additional safety check: Ensure no profiles (other than those already checked)
        # are using any of these collections in their ragCollections or knowledgeConfig
        if assigned_collections:
            collection_ids = {c.get("id") for c in assigned_collections}
            profiles_using_collections = []

            for p in profiles:
                # Check ragCollections array
                rag_collections = p.get("ragCollections", [])
                if isinstance(rag_collections, list):
                    if any(cid in collection_ids for cid in rag_collections if isinstance(cid, int)):
                        profiles_using_collections.append(p)
                        continue

                # Check knowledgeConfig.collections
                knowledge_config = p.get("knowledgeConfig", {})
                knowledge_collections = knowledge_config.get("collections", [])
                if isinstance(knowledge_collections, list):
                    knowledge_ids = {kc.get("id") for kc in knowledge_collections if isinstance(kc, dict)}
                    if any(cid in collection_ids for cid in knowledge_ids):
                        profiles_using_collections.append(p)

            if profiles_using_collections:
                profile_names = [
                    p.get("profileName") or p.get("name") or f"@{p.get('tag')}" or "Unknown"
                    for p in profiles_using_collections
                ]
                names_list = ", ".join(profile_names)
                error_msg = f"Cannot delete MCP server: {len(profiles_using_collections)} profile(s) use its collections: {names_list}"
                app_logger.warning(f"{error_msg} (Server ID: {server_id})")
                return False, error_msg

        if assigned_collections:
            app_logger.info(f"Cascade deleting {len(assigned_collections)} collection(s) for MCP server {server_id}")
            try:
                from trusted_data_agent.agent.rag_retriever import RAGRetriever
                from trusted_data_agent.core.config import APP_STATE

                rag_retriever = APP_STATE.get('rag_retriever_instance')
                if rag_retriever:
                    for coll in assigned_collections:
                        coll_id = coll.get("id")
                        coll_name = coll.get("name", "Unknown")
                        app_logger.info(f"  Deleting collection {coll_id} ('{coll_name}')")

                        # Note: remove_collection has default collection protection built-in
                        # But we're deleting the MCP server, so all its collections must go
                        # We'll bypass the default check by directly calling the deletion logic
                        try:
                            # Delete from ChromaDB
                            collection_name = coll.get("collection_name", f"tda_rag_collection_{coll_id}")
                            rag_retriever.client.delete_collection(name=collection_name)

                            # Remove from runtime
                            if coll_id in rag_retriever.collections:
                                del rag_retriever.collections[coll_id]

                            # Delete from database
                            from trusted_data_agent.core.collection_db import get_collection_db
                            collection_db = get_collection_db()
                            collection_db.delete_collection(coll_id)

                            app_logger.info(f"  ✓ Deleted collection {coll_id}")
                        except Exception as coll_error:
                            app_logger.error(f"  ✗ Failed to delete collection {coll_id}: {coll_error}")
                            # Continue with other collections even if one fails

                    # Reload APP_STATE after deletions
                    APP_STATE["rag_collections"] = self.get_rag_collections(user_uuid)
                else:
                    app_logger.warning("RAG retriever not available - collections may not be fully deleted")
            except Exception as e:
                app_logger.error(f"Error during cascade delete of collections: {e}", exc_info=True)
                error_msg = f"Failed to delete associated collections: {str(e)}"
                return False, error_msg

        servers = self.get_mcp_servers(user_uuid)
        original_count = len(servers)
        servers = [s for s in servers if s.get("id") != server_id]

        if len(servers) == original_count:
            error_msg = "MCP server not found"
            app_logger.warning(f"MCP server with ID {server_id} not found for removal")
            return False, error_msg

        success = self.save_mcp_servers(servers, user_uuid)

        if success and assigned_collections:
            app_logger.info(f"✅ Successfully deleted MCP server {server_id} and {len(assigned_collections)} associated collection(s)")

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

    def validate_profile(self, profile: Dict[str, Any], user_uuid: Optional[str] = None) -> tuple[bool, str]:
        """
        Validate a profile's configuration.

        Args:
            profile: Profile configuration dictionary
            user_uuid: Optional user UUID for validating references to other profiles

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

        elif profile_type == "genie":
            # Genie profiles REQUIRE genieConfig (but slaveProfiles can be empty - user will configure later)
            genie_config = profile.get("genieConfig", {})
            if not genie_config:
                return False, "Genie profiles require genieConfig"

            # Note: slaveProfiles can be empty - activation will prompt user to add children
            slave_profiles = genie_config.get("slaveProfiles", [])

            # Only validate child profiles if any are configured
            if slave_profiles and len(slave_profiles) > 0 and user_uuid:
                all_profiles = self.get_profiles(user_uuid)
                profile_map = {p.get("id"): p for p in all_profiles}
                current_profile_id = profile.get("id")

                for slave_pid in slave_profiles:
                    # Check if referencing self
                    if slave_pid == current_profile_id:
                        return False, "Genie profiles cannot reference themselves as children"

                    slave = profile_map.get(slave_pid)
                    if not slave:
                        return False, f"Child profile {slave_pid} not found"
                    # NOTE: Genie profiles CAN now have other Genie profiles as children
                    # Circular dependencies and depth limits are checked below

                # Get max nesting depth from global settings
                global_settings = self.get_genie_global_settings()
                max_depth = int(global_settings.get('maxNestingDepth', {}).get('value', 3))

                # Check for circular dependencies and depth limits
                has_error, error_msg, detected_depth = self._detect_circular_genie_dependency(
                    profile_id=current_profile_id,
                    slave_profiles=slave_profiles,
                    user_uuid=user_uuid,
                    depth=0,
                    max_depth=max_depth
                )

                if has_error:
                    return False, error_msg

        elif profile_type == "llm_only":
            # llm_only profiles have optional capabilities via flags
            llm_config_id = profile.get("llmConfigurationId")
            if not llm_config_id:
                return False, "Conversation profiles require an LLM configuration"

            # If useMcpTools is enabled, MCP server is required
            use_mcp_tools = profile.get("useMcpTools", False)
            if use_mcp_tools:
                mcp_server_id = profile.get("mcpServerId")
                if not mcp_server_id:
                    return False, "Conversation profiles with MCP Tools enabled require an MCP server configuration"

        return True, ""

    def _detect_circular_genie_dependency(
        self,
        profile_id: str,
        slave_profiles: List[str],
        user_uuid: str,
        visited_path: Optional[set] = None,
        depth: int = 0,
        max_depth: int = 3
    ) -> tuple[bool, str, int]:
        """
        Detect circular dependencies in Genie child profiles using DFS with path tracking.

        This method prevents:
        1. Circular dependencies (A → B → A)
        2. Excessive nesting depth (A → B → C → D when max is 3)

        Args:
            profile_id: Current profile being validated
            slave_profiles: List of child profile IDs for current profile (parameter name preserved for API compatibility)
            user_uuid: User UUID for profile lookup
            visited_path: Set of profile IDs in current traversal path (cycle detection)
            depth: Current nesting depth (0 = top level)
            max_depth: Maximum allowed nesting depth

        Returns:
            Tuple of (has_error: bool, error_message: str, max_depth_found: int)
            - (False, "", depth) if valid
            - (True, "error message", depth) if circular or too deep

        Algorithm:
            1. Initialize visited_path if first call
            2. Check max depth limit
            3. For each child profile:
               a. Check if it's in visited_path (circular dependency)
               b. If child is Genie type, recursively check its children
               c. Track maximum depth encountered
            4. Return result
        """
        if visited_path is None:
            visited_path = set()

        # Check depth limit
        if depth > max_depth:
            return True, f"Genie nesting exceeds maximum depth of {max_depth} levels", depth

        # Add current profile to path
        visited_path.add(profile_id)

        # Get all profiles for lookup
        all_profiles = self.get_profiles(user_uuid)
        profile_map = {p.get("id"): p for p in all_profiles}

        max_depth_encountered = depth

        # Check each child
        for slave_id in slave_profiles:
            # Check for circular reference
            if slave_id in visited_path:
                # Build path string for error message
                path_list = list(visited_path) + [slave_id]
                path_tags = []
                for pid in path_list:
                    p = profile_map.get(pid)
                    if p:
                        path_tags.append(f"@{p.get('tag', pid)}")
                cycle_path = " → ".join(path_tags)
                return True, f"Circular dependency detected: {cycle_path}", depth

            slave_profile = profile_map.get(slave_id)
            if not slave_profile:
                continue  # Skip missing profiles (caught by other validation)

            # If child is also a Genie, recursively check
            if slave_profile.get("profile_type") == "genie":
                slave_genie_config = slave_profile.get("genieConfig", {})
                nested_slaves = slave_genie_config.get("slaveProfiles", [])

                # Recursively check this Genie's children
                has_error, error_msg, nested_depth = self._detect_circular_genie_dependency(
                    profile_id=slave_id,
                    slave_profiles=nested_slaves,
                    user_uuid=user_uuid,
                    visited_path=visited_path.copy(),  # Important: copy to isolate branches
                    depth=depth + 1,
                    max_depth=max_depth
                )

                if has_error:
                    return True, error_msg, nested_depth

                max_depth_encountered = max(max_depth_encountered, nested_depth)

        return False, "", max_depth_encountered

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

    # =========================================================================
    # Genie Global Settings Management
    # =========================================================================

    def get_genie_global_settings(self) -> Dict[str, Any]:
        """
        Get all global Genie coordination settings with lock status.

        Returns:
            Dict with setting keys and their values/lock status:
            {
                'temperature': {'value': 0.7, 'is_locked': False},
                'queryTimeout': {'value': 300, 'is_locked': False},
                'maxIterations': {'value': 10, 'is_locked': True}
            }
        """
        from trusted_data_agent.auth.database import get_db_session

        settings = {}
        try:
            with get_db_session() as session:
                # Query genie_global_settings table
                result = session.execute(
                    text("SELECT setting_key, setting_value, is_locked FROM genie_global_settings")
                )
                rows = result.fetchall()

                for row in rows:
                    key, value, is_locked = row
                    # Parse value to appropriate type based on key
                    # Float values: temperature, knowledge_minRelevanceScore
                    # Integer values: everything else
                    if key in ('temperature', 'knowledge_minRelevanceScore'):
                        parsed_value = float(value)
                    else:
                        parsed_value = int(value)

                    settings[key] = {
                        'value': parsed_value,
                        'is_locked': bool(is_locked)
                    }

                # Ensure defaults if table is empty
                defaults = {
                    'temperature': {'value': 0.7, 'is_locked': False},
                    'queryTimeout': {'value': 300, 'is_locked': False},
                    'maxIterations': {'value': 10, 'is_locked': False},
                    'maxNestingDepth': {'value': 3, 'is_locked': False},
                    'knowledge_minRelevanceScore': {'value': 0.30, 'is_locked': False},
                    'knowledge_maxDocs': {'value': 3, 'is_locked': False},
                    'knowledge_maxTokens': {'value': 2000, 'is_locked': False},
                    'knowledge_rerankingEnabled': {'value': 0, 'is_locked': False}
                }
                for key, default in defaults.items():
                    if key not in settings:
                        settings[key] = default

        except Exception as e:
            app_logger.error(f"Error loading genie global settings: {e}")
            # Return defaults on error
            settings = {
                'temperature': {'value': 0.7, 'is_locked': False},
                'queryTimeout': {'value': 300, 'is_locked': False},
                'maxIterations': {'value': 10, 'is_locked': False}
            }

        return settings

    def set_genie_global_setting(
        self,
        setting_key: str,
        setting_value: Any,
        is_locked: bool,
        user_uuid: Optional[str] = None
    ) -> bool:
        """
        Update a global Genie setting.

        Args:
            setting_key: Setting identifier (temperature, queryTimeout, maxIterations)
            setting_value: New value for the setting
            is_locked: Whether to lock this setting (prevent profile overrides)
            user_uuid: Admin user who made the change (for audit)

        Returns:
            True if successful, False otherwise
        """
        from trusted_data_agent.auth.database import get_db_session

        try:
            with get_db_session() as session:
                session.execute(
                    text("""
                    INSERT OR REPLACE INTO genie_global_settings
                    (setting_key, setting_value, is_locked, updated_at, updated_by)
                    VALUES (:setting_key, :setting_value, :is_locked, datetime('now'), :updated_by)
                    """),
                    {"setting_key": setting_key, "setting_value": str(setting_value), "is_locked": int(is_locked), "updated_by": user_uuid}
                )
                session.commit()
                app_logger.info(f"Updated genie global setting: {setting_key}={setting_value}, locked={is_locked}")
                return True
        except Exception as e:
            app_logger.error(f"Error saving genie global setting: {e}")
            return False

    def save_genie_global_settings(
        self,
        settings: Dict[str, Dict[str, Any]],
        user_uuid: Optional[str] = None
    ) -> bool:
        """
        Save all global Genie settings at once.

        Args:
            settings: Dict of settings in format:
                {
                    'temperature': {'value': 0.7, 'is_locked': False},
                    'queryTimeout': {'value': 300, 'is_locked': True},
                    ...
                }
            user_uuid: Admin user who made the change (for audit)

        Returns:
            True if all settings saved successfully
        """
        success = True
        for key, config in settings.items():
            if not self.set_genie_global_setting(
                key,
                config.get('value'),
                config.get('is_locked', False),
                user_uuid
            ):
                success = False
        return success

    def get_effective_genie_config(self, profile_genie_config: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Get effective Genie configuration by merging global settings with profile overrides.

        Resolution hierarchy:
        1. If global setting is locked -> use global value
        2. If profile has a non-null value -> use profile value
        3. Otherwise -> use global default

        Args:
            profile_genie_config: Profile-level genieConfig dict (may contain temperature,
                                 queryTimeout, maxIterations)

        Returns:
            Effective configuration dict with resolved values:
            {
                'temperature': 0.7,
                'queryTimeout': 300,
                'maxIterations': 10
            }
        """
        global_settings = self.get_genie_global_settings()
        profile_genie_config = profile_genie_config or {}

        effective = {}

        for key, global_config in global_settings.items():
            global_value = global_config['value']
            is_locked = global_config['is_locked']

            if is_locked:
                # Admin-locked: always use global value
                effective[key] = global_value
            else:
                # Check for profile override
                profile_value = profile_genie_config.get(key)
                if profile_value is not None:
                    effective[key] = profile_value
                else:
                    effective[key] = global_value

        return effective

    # =========================================================================
    # Knowledge Global Settings Management
    # =========================================================================

    def get_knowledge_global_settings(self) -> Dict[str, Any]:
        """
        Get all global Knowledge repository settings with lock status.

        Returns:
            Dict with setting keys and their values/lock status:
            {
                'minRelevanceScore': {'value': 0.30, 'is_locked': False},
                'maxDocs': {'value': 3, 'is_locked': False},
                'maxTokens': {'value': 2000, 'is_locked': False},
                'rerankingEnabled': {'value': False, 'is_locked': False}
            }
        """
        from trusted_data_agent.auth.database import get_db_session

        settings = {}
        try:
            with get_db_session() as session:
                # Query genie_global_settings table for knowledge_ prefixed keys
                result = session.execute(
                    text("SELECT setting_key, setting_value, is_locked FROM genie_global_settings WHERE setting_key LIKE 'knowledge_%'")
                )
                rows = result.fetchall()

                for row in rows:
                    key, value, is_locked = row
                    # Remove 'knowledge_' prefix for API response
                    short_key = key.replace('knowledge_', '')

                    # Parse value to appropriate type
                    if short_key == 'minRelevanceScore':
                        parsed_value = float(value)
                    elif short_key == 'rerankingEnabled':
                        parsed_value = bool(int(value))
                    else:
                        parsed_value = int(value)

                    settings[short_key] = {
                        'value': parsed_value,
                        'is_locked': bool(is_locked)
                    }

                # Ensure defaults if table is empty
                defaults = {
                    'minRelevanceScore': {'value': 0.30, 'is_locked': False},
                    'maxDocs': {'value': 3, 'is_locked': False},
                    'maxTokens': {'value': 2000, 'is_locked': False},
                    'rerankingEnabled': {'value': False, 'is_locked': False}
                }
                for key, default in defaults.items():
                    if key not in settings:
                        settings[key] = default

        except Exception as e:
            app_logger.error(f"Error loading knowledge global settings: {e}")
            # Return defaults on error
            settings = {
                'minRelevanceScore': {'value': 0.30, 'is_locked': False},
                'maxDocs': {'value': 3, 'is_locked': False},
                'maxTokens': {'value': 2000, 'is_locked': False},
                'rerankingEnabled': {'value': False, 'is_locked': False}
            }

        return settings

    def set_knowledge_global_setting(
        self,
        setting_key: str,
        setting_value: Any,
        is_locked: bool,
        user_uuid: Optional[str] = None
    ) -> bool:
        """
        Update a global Knowledge setting.

        Args:
            setting_key: Setting identifier (minRelevanceScore, maxDocs, maxTokens, rerankingEnabled)
            setting_value: New value for the setting
            is_locked: Whether to lock this setting (prevent profile overrides)
            user_uuid: Admin user who made the change (for audit)

        Returns:
            True if successful, False otherwise
        """
        from trusted_data_agent.auth.database import get_db_session

        # Add 'knowledge_' prefix for database storage
        db_key = f"knowledge_{setting_key}"

        # Convert boolean to int for storage
        if setting_key == 'rerankingEnabled':
            setting_value = 1 if setting_value else 0

        try:
            with get_db_session() as session:
                session.execute(
                    text("""
                    INSERT OR REPLACE INTO genie_global_settings
                    (setting_key, setting_value, is_locked, updated_at, updated_by)
                    VALUES (:setting_key, :setting_value, :is_locked, datetime('now'), :updated_by)
                    """),
                    {"setting_key": db_key, "setting_value": str(setting_value), "is_locked": int(is_locked), "updated_by": user_uuid}
                )
                session.commit()
                app_logger.info(f"Updated knowledge global setting: {setting_key}={setting_value}, locked={is_locked}")
                return True
        except Exception as e:
            app_logger.error(f"Error saving knowledge global setting: {e}")
            return False

    def save_knowledge_global_settings(
        self,
        settings: Dict[str, Dict[str, Any]],
        user_uuid: Optional[str] = None
    ) -> bool:
        """
        Save all global Knowledge settings at once.

        Args:
            settings: Dict of settings in format:
                {
                    'minRelevanceScore': {'value': 0.30, 'is_locked': False},
                    'maxDocs': {'value': 3, 'is_locked': True},
                    ...
                }
            user_uuid: Admin user who made the change (for audit)

        Returns:
            True if all settings saved successfully
        """
        success = True
        for key, config in settings.items():
            if not self.set_knowledge_global_setting(
                key,
                config.get('value'),
                config.get('is_locked', False),
                user_uuid
            ):
                success = False
        return success

    def get_effective_knowledge_config(self, profile_knowledge_config: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Get effective Knowledge configuration by merging global settings with profile overrides.

        Resolution hierarchy:
        1. If global setting is locked -> use global value
        2. If profile has a non-null value -> use profile value
        3. Otherwise -> use global default

        Args:
            profile_knowledge_config: Profile-level knowledgeConfig dict (may contain
                                     minRelevanceScore, maxDocs, maxTokens)

        Returns:
            Effective configuration dict with resolved values:
            {
                'minRelevanceScore': 0.30,
                'maxDocs': 3,
                'maxTokens': 2000,
                'rerankingEnabled': False
            }
        """
        global_settings = self.get_knowledge_global_settings()
        profile_knowledge_config = profile_knowledge_config or {}

        effective = {}

        for key, global_config in global_settings.items():
            global_value = global_config['value']
            is_locked = global_config['is_locked']

            if is_locked:
                # Admin-locked: always use global value
                effective[key] = global_value
            else:
                # Check for profile override
                profile_value = profile_knowledge_config.get(key)
                if profile_value is not None:
                    effective[key] = profile_value
                else:
                    effective[key] = global_value

        return effective


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
