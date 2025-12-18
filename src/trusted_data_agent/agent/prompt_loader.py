"""
Prompt Loader - Database-backed prompt system with license protection

This module replaces the file-based prompts.dat system with database storage
while maintaining the same license verification and tier-based access control.

Security Model:
    - License verification MUST pass before database access
    - Invalid/expired licenses prevent app startup (RuntimeError)
    - Tier-based features (Prompt Engineer/Enterprise only for overrides)
    - Same security boundary as prompts.dat system

Architecture:
    - Singleton pattern for efficient resource usage
    - Connection pooling for database access
    - In-memory caching for performance
    - Parameter resolution with override hierarchy
"""

import os
import sqlite3
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature

from trusted_data_agent.core.config import APP_STATE
from trusted_data_agent.core.utils import get_project_root

# Initialize logger
logger = logging.getLogger("quart.app")


class PromptLoader:
    """
    Database-backed prompt loader with license protection.
    
    This class provides secure access to prompts stored in tda_auth.db,
    enforcing license validation and tier-based permissions.
    """
    
    _instance = None
    
    def __new__(cls):
        """Singleton pattern - one instance per application"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """
        Initialize prompt loader with license verification.
        
        Raises:
            RuntimeError: If license is invalid, expired, or missing
        """
        if self._initialized:
            return
            
        logger.info("Initializing PromptLoader...")
        
        # Step 1: SECURITY GATE - Verify license (app dies here if invalid)
        self._verify_license()
        
        # Step 2: Store license info for tier checks
        self._license_info = APP_STATE.get('license_info', {})
        self._tier = self._license_info.get('tier', 'Standard')
        
        # Step 3: Get database path
        project_root = get_project_root()
        self.db_path = os.path.join(project_root, "tda_auth.db")
        
        if not os.path.exists(self.db_path):
            raise RuntimeError(f"Database not found: {self.db_path}")
        
        # Step 4: Initialize cache
        self._prompt_cache: Dict[str, str] = {}
        self._parameter_cache: Dict[str, Dict] = {}
        self._override_cache: Dict[str, Any] = {}
        
        logger.info(f"PromptLoader initialized successfully (Tier: {self._tier})")
        self._initialized = True
    
    def _verify_license(self):
        """
        Verify license signature, expiration, and store info.
        
        This is the SECURITY GATE - same enforcement as prompts.dat system.
        Without a valid license, the application will not start.
        
        Raises:
            RuntimeError: If license is invalid, expired, or missing
        """
        project_root = str(get_project_root())
        keys_dir = os.path.join(project_root, "tda_keys")
        public_key_path = os.path.join(keys_dir, "public_key.pem")
        license_path = os.path.join(keys_dir, "license.key")
        
        # Check public key
        if not os.path.exists(public_key_path):
            raise RuntimeError("Application is missing its public key; cannot verify license.")
        
        try:
            with open(public_key_path, "rb") as f:
                public_key = serialization.load_pem_public_key(f.read())
        except Exception as e:
            raise RuntimeError("Application public key is invalid; cannot verify license.") from e
        
        # Check license file
        if not os.path.exists(license_path):
            raise RuntimeError("A valid license.key file is required to run this application.")
        
        try:
            # Load and parse license
            with open(license_path, 'r', encoding='utf-8') as f:
                license_content = json.load(f)
            
            payload = license_content['payload']
            signature = bytes.fromhex(license_content['signature'])
            payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
            
            # Verify signature
            public_key.verify(
                signature, payload_bytes,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256()
            )
            
            # Check expiration
            expiration_date = datetime.fromisoformat(payload['expires_at'])
            if expiration_date < datetime.now(timezone.utc):
                raise RuntimeError("Your license key has expired.")
            
            # Store license info in APP_STATE
            APP_STATE['license_info'] = payload
            
            logger.info(f"License successfully validated for: {payload['holder']} (Tier: {payload.get('tier', 'N/A')})")
            
        except (InvalidSignature, json.JSONDecodeError, KeyError):
            raise RuntimeError("Invalid or corrupt license.key file.")
        except Exception as e:
            raise RuntimeError("License validation failed.") from e
    
    def _get_db_connection(self) -> sqlite3.Connection:
        """
        Get database connection.
        
        Returns:
            sqlite3.Connection: Database connection
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn
    
    def get_prompt(self, name: str, user_uuid: Optional[str] = None, 
                   profile_id: Optional[str] = None, 
                   parameters: Optional[Dict[str, Any]] = None) -> str:
        """
        Load prompt with tier-based override hierarchy and parameter resolution.
        
        Override Hierarchy (highest to lowest priority):
            1. User-level override (if Prompt Engineer/Enterprise tier)
            2. Profile-level override (if exists)
            3. Base prompt from database
        
        Args:
            name: Prompt name (e.g., 'MASTER_SYSTEM_PROMPT')
            user_uuid: User UUID for user-level overrides (optional)
            profile_id: Profile ID for profile-level overrides (optional)
            parameters: Parameter values to substitute (optional)
        
        Returns:
            str: Prompt content with parameters resolved
        
        Raises:
            ValueError: If prompt not found
        """
        # Check cache first
        cache_key = f"{name}:{user_uuid}:{profile_id}"
        if cache_key in self._prompt_cache:
            content = self._prompt_cache[cache_key]
        else:
            # Load with override hierarchy
            content = self._load_with_overrides(name, user_uuid, profile_id)
            self._prompt_cache[cache_key] = content
        
        # Resolve parameters if provided
        if parameters:
            content = self._resolve_parameters(content, parameters)
        
        return content
    
    def _load_with_overrides(self, name: str, user_uuid: Optional[str], 
                            profile_id: Optional[str]) -> str:
        """
        Load prompt with override hierarchy.
        
        Args:
            name: Prompt name
            user_uuid: User UUID (optional)
            profile_id: Profile ID (optional)
        
        Returns:
            str: Prompt content (base or overridden)
        
        Raises:
            ValueError: If prompt not found
        """
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 1. Check user-level override (tier-gated)
            if user_uuid and self._tier in ['Prompt Engineer', 'Enterprise']:
                cursor.execute("""
                    SELECT po.content
                    FROM prompt_overrides po
                    JOIN prompts p ON po.prompt_id = p.id
                    WHERE p.name = ? AND po.user_uuid = ? AND po.is_active = 1
                """, (name, user_uuid))
                
                row = cursor.fetchone()
                if row:
                    logger.debug(f"Loaded user override for {name} (user: {user_uuid})")
                    return row['content']
            
            # 2. Check profile-level override
            if profile_id:
                cursor.execute("""
                    SELECT po.content
                    FROM prompt_overrides po
                    JOIN prompts p ON po.prompt_id = p.id
                    WHERE p.name = ? AND po.profile_id = ? AND po.is_active = 1
                """, (name, profile_id))
                
                row = cursor.fetchone()
                if row:
                    logger.debug(f"Loaded profile override for {name} (profile: {profile_id})")
                    return row['content']
            
            # 3. Load base prompt
            cursor.execute("""
                SELECT content
                FROM prompts
                WHERE name = ? AND is_active = 1
            """, (name,))
            
            row = cursor.fetchone()
            if row:
                logger.debug(f"Loaded base prompt: {name}")
                return row['content']
            
            raise ValueError(f"Prompt not found: {name}")
            
        finally:
            conn.close()
    
    def _resolve_parameters(self, content: str, parameters: Dict[str, Any]) -> str:
        """
        Resolve parameters in prompt content.
        
        Parameters are specified as {parameter_name} in the content.
        
        Args:
            content: Prompt content with {parameter} placeholders
            parameters: Parameter values to substitute
        
        Returns:
            str: Content with parameters resolved
        """
        try:
            return content.format(**parameters)
        except KeyError as e:
            logger.warning(f"Missing parameter in prompt: {e}")
            return content
        except Exception as e:
            logger.error(f"Error resolving parameters: {e}")
            return content
    
    def get_prompt_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get prompt metadata (display name, description, role, etc.).
        
        Args:
            name: Prompt name
        
        Returns:
            dict: Prompt metadata or None if not found
        """
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT 
                    p.id,
                    p.name,
                    p.display_name,
                    p.description,
                    p.role,
                    p.provider,
                    p.version,
                    p.is_active,
                    pc.display_name as category
                FROM prompts p
                LEFT JOIN prompt_classes pc ON p.class_id = pc.id
                WHERE p.name = ?
            """, (name,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
            
        finally:
            conn.close()
    
    def list_prompts(self, category: Optional[str] = None, 
                    role: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List available prompts with optional filtering.
        
        Args:
            category: Filter by category (optional)
            role: Filter by role (optional)
        
        Returns:
            list: List of prompt metadata dictionaries
        """
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT 
                    p.id,
                    p.name,
                    p.display_name,
                    p.description,
                    p.role,
                    p.provider,
                    pc.display_name as category
                FROM prompts p
                LEFT JOIN prompt_classes pc ON p.class_id = pc.id
                WHERE p.is_active = 1
            """
            params = []
            
            if category:
                query += " AND pc.name = ?"
                params.append(category)
            
            if role:
                query += " AND p.role = ?"
                params.append(role)
            
            query += " ORDER BY pc.id, p.name"
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
            
        finally:
            conn.close()
    
    def clear_cache(self):
        """Clear all caches (useful for testing or after prompt updates)"""
        self._prompt_cache.clear()
        self._parameter_cache.clear()
        self._override_cache.clear()
        logger.info("Prompt cache cleared")
    
    def has_tier_access(self, required_tier: str) -> bool:
        """
        Check if current license tier has required access.
        
        Tier hierarchy: Standard < Prompt Engineer < Enterprise
        
        Args:
            required_tier: Required tier level
        
        Returns:
            bool: True if license tier meets or exceeds requirement
        """
        tier_levels = {
            'Standard': 1,
            'Prompt Engineer': 2,
            'Enterprise': 3
        }
        
        current_level = tier_levels.get(self._tier, 0)
        required_level = tier_levels.get(required_tier, 99)
        
        return current_level >= required_level


# Singleton instance (initialized on first import)
_loader_instance: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """
    Get the global PromptLoader instance.
    
    Returns:
        PromptLoader: Singleton instance
    
    Raises:
        RuntimeError: If license validation fails
    """
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = PromptLoader()
    return _loader_instance


# Convenience functions for backward compatibility
def load_prompt(name: str, **kwargs) -> str:
    """Load prompt by name (convenience wrapper)"""
    loader = get_prompt_loader()
    return loader.get_prompt(name, **kwargs)


def list_prompts(**kwargs) -> List[Dict[str, Any]]:
    """List available prompts (convenience wrapper)"""
    loader = get_prompt_loader()
    return loader.list_prompts(**kwargs)
