"""
Profile Prompt Mapping System
==============================

Provides functionality to map profiles to specific prompts for each functional category.
Falls back to system defaults from tda_config.json when no profile-specific mapping exists.

Usage:
    from trusted_data_agent.agent.prompt_mapping import get_prompt_for_category
    
    # Get master system prompt for Google provider
    prompt_name = get_prompt_for_category(
        profile_id="profile-123",
        category="master_system",
        subcategory="Google"
    )
    # Returns: "GOOGLE_MASTER_SYSTEM_PROMPT"
"""

import sqlite3
import json
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Cache for default mappings from tda_config.json
_DEFAULT_MAPPINGS_CACHE = None


def _load_default_mappings() -> dict:
    """Load default prompt mappings from tda_config.json."""
    global _DEFAULT_MAPPINGS_CACHE
    
    if _DEFAULT_MAPPINGS_CACHE is not None:
        return _DEFAULT_MAPPINGS_CACHE
    
    try:
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        _DEFAULT_MAPPINGS_CACHE = config.get('default_prompt_mappings', {})
        return _DEFAULT_MAPPINGS_CACHE
    except Exception as e:
        logger.error(f"Failed to load default prompt mappings: {e}")
        return {}


def get_prompt_for_category(
    profile_id: str,
    category: str,
    subcategory: Optional[str] = None,
    db_path: Optional[str] = None
) -> Optional[str]:
    """
    Get the prompt name for a given profile, category, and optional subcategory.
    
    Resolution order:
    1. Profile-specific mapping (from database)
    2. System default mapping (from database with profile_id='__system_default__')
    3. Hardcoded default from tda_config.json
    
    Args:
        profile_id: Profile ID (e.g., "profile-123")
        category: Functional category (e.g., "master_system", "workflow_classification")
        subcategory: Optional subcategory (e.g., "Google" for master_system, "task_classification" for workflow)
        db_path: Optional database path (defaults to tda_auth.db in project root)
    
    Returns:
        Prompt name (e.g., "GOOGLE_MASTER_SYSTEM_PROMPT") or None if not found
    
    Examples:
        >>> get_prompt_for_category("profile-123", "master_system", "Google")
        'GOOGLE_MASTER_SYSTEM_PROMPT'
        
        >>> get_prompt_for_category("profile-123", "workflow_classification", "task_classification")
        'TASK_CLASSIFICATION_PROMPT'
    """
    if db_path is None:
        from trusted_data_agent.core.utils import get_project_root
        db_path = str(get_project_root() / "tda_auth.db")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. Check for profile-specific mapping
        cursor.execute("""
            SELECT prompt_name FROM profile_prompt_mappings
            WHERE profile_id = ? AND category = ? AND subcategory = ?
        """, (profile_id, category, subcategory))
        
        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0]
        
        # 2. Check for system default mapping
        cursor.execute("""
            SELECT prompt_name FROM profile_prompt_mappings
            WHERE profile_id = '__system_default__' AND category = ? AND subcategory = ?
        """, (category, subcategory))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return row[0]
        
        # 3. Fall back to tda_config.json defaults
        defaults = _load_default_mappings()
        
        if category == "master_system_prompts":
            return defaults.get('master_system_prompts', {}).get(subcategory)
        elif category == "workflow_classification":
            return defaults.get('workflow_classification', {}).get(subcategory)
        elif category == "error_recovery":
            return defaults.get('error_recovery', {}).get(subcategory)
        elif category == "data_operations":
            return defaults.get('data_operations', {}).get(subcategory)
        elif category == "visualization":
            return defaults.get('visualization', {}).get(subcategory)
        elif category == "genie_coordination":
            # Genie coordination prompts with hardcoded default
            genie_defaults = defaults.get('genie_coordination', {
                "coordinator_prompt": "GENIE_COORDINATOR_PROMPT"
            })
            return genie_defaults.get(subcategory)
        elif category == "conversation_execution":
            # Conversation execution prompts with hardcoded defaults
            conversation_defaults = defaults.get('conversation_execution', {
                "conversation": "CONVERSATION_EXECUTION",
                "conversation_with_tools": "CONVERSATION_WITH_TOOLS_EXECUTION"
            })
            return conversation_defaults.get(subcategory)

        return None
        
    except Exception as e:
        logger.error(f"Error resolving prompt mapping: {e}")
        return None


def get_all_mappings_for_profile(
    profile_id: str,
    db_path: Optional[str] = None
) -> dict:
    """
    Get all prompt mappings for a profile, including inherited system defaults.
    
    Returns a dictionary structure:
    {
        "master_system": {"Google": "GOOGLE_MASTER_SYSTEM_PROMPT", ...},
        "workflow_classification": {"task_classification": "TASK_CLASSIFICATION_PROMPT", ...},
        ...
    }
    """
    result = {
        "master_system_prompts": {},
        "workflow_classification": {},
        "error_recovery": {},
        "data_operations": {},
        "visualization": {},
        "genie_coordination": {},
        "conversation_execution": {}
    }
    
    # Load all default mappings first
    defaults = _load_default_mappings()
    
    # Populate with defaults
    for provider in defaults.get('master_system_prompts', {}).keys():
        result["master_system_prompts"][provider] = get_prompt_for_category(
            profile_id, "master_system_prompts", provider, db_path
        )
    
    for subcategory in defaults.get('workflow_classification', {}).keys():
        result["workflow_classification"][subcategory] = get_prompt_for_category(
            profile_id, "workflow_classification", subcategory, db_path
        )
    
    for subcategory in defaults.get('error_recovery', {}).keys():
        result["error_recovery"][subcategory] = get_prompt_for_category(
            profile_id, "error_recovery", subcategory, db_path
        )
    
    for subcategory in defaults.get('data_operations', {}).keys():
        result["data_operations"][subcategory] = get_prompt_for_category(
            profile_id, "data_operations", subcategory, db_path
        )
    
    for subcategory in defaults.get('visualization', {}).keys():
        result["visualization"][subcategory] = get_prompt_for_category(
            profile_id, "visualization", subcategory, db_path
        )

    # Genie coordination (with hardcoded default if not in config)
    genie_defaults = defaults.get('genie_coordination', {"coordinator_prompt": "GENIE_COORDINATOR_PROMPT"})
    for subcategory in genie_defaults.keys():
        result["genie_coordination"][subcategory] = get_prompt_for_category(
            profile_id, "genie_coordination", subcategory, db_path
        )

    # Conversation execution (with hardcoded defaults if not in config)
    conversation_defaults = defaults.get('conversation_execution', {
        "conversation": "CONVERSATION_EXECUTION",
        "conversation_with_tools": "CONVERSATION_WITH_TOOLS_EXECUTION"
    })
    for subcategory in conversation_defaults.keys():
        result["conversation_execution"][subcategory] = get_prompt_for_category(
            profile_id, "conversation_execution", subcategory, db_path
        )

    return result


def set_prompt_mapping(
    profile_id: str,
    category: str,
    subcategory: str,
    prompt_name: str,
    created_by: str,
    db_path: Optional[str] = None
) -> bool:
    """
    Set or update a prompt mapping for a profile.
    
    Returns True if successful, False otherwise.
    """
    if db_path is None:
        from trusted_data_agent.core.utils import get_project_root
        db_path = str(get_project_root() / "tda_auth.db")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO profile_prompt_mappings 
            (profile_id, category, subcategory, prompt_name, created_by, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (profile_id, category, subcategory, prompt_name, created_by))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Set prompt mapping: {profile_id}/{category}/{subcategory} -> {prompt_name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to set prompt mapping: {e}")
        return False


def delete_prompt_mapping(
    profile_id: str,
    category: str,
    subcategory: str,
    db_path: Optional[str] = None
) -> bool:
    """
    Delete a prompt mapping for a profile (revert to system default).
    
    Returns True if successful, False otherwise.
    """
    if db_path is None:
        from trusted_data_agent.core.utils import get_project_root
        db_path = str(get_project_root() / "tda_auth.db")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM profile_prompt_mappings 
            WHERE profile_id = ? AND category = ? AND subcategory = ?
        """, (profile_id, category, subcategory))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Deleted prompt mapping: {profile_id}/{category}/{subcategory}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to delete prompt mapping: {e}")
        return False
