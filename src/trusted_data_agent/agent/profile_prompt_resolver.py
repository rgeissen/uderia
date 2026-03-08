"""
Profile-Aware Prompt Resolver
==============================

Provides runtime prompt resolution that respects profile overrides.
Replaces direct imports from prompts.py for categories that support profile mapping.

This module wraps the profile mapping system to provide lazy-loaded, profile-aware
prompts that can be used throughout the codebase as drop-in replacements.

Usage:
    from trusted_data_agent.agent.profile_prompt_resolver import ProfilePromptResolver
    
    # Create resolver with active profile
    resolver = ProfilePromptResolver(profile_id="profile-123", provider="Google")
    
    # Get profile-aware prompts
    task_classification = resolver.get_workflow_prompt("task_classification")
    error_recovery = resolver.get_error_recovery_prompt("error_recovery")
    sql_consolidation = resolver.get_data_operations_prompt("sql_consolidation")
"""

import json
import logging
from typing import Optional
from trusted_data_agent.agent.prompt_mapping import get_prompt_for_category
from trusted_data_agent.agent.prompt_loader import get_prompt_loader

logger = logging.getLogger(__name__)


class ProfilePromptResolver:
    """
    Resolves prompts based on profile mappings with lazy loading.
    
    This resolver maintains the profile context throughout its lifetime and
    provides methods to access prompts from all supported categories while
    respecting profile-specific overrides.
    """
    
    def __init__(self, profile_id: Optional[str] = None, provider: Optional[str] = None):
        """
        Initialize resolver with profile context.
        
        Args:
            profile_id: Active profile ID (defaults to "__system_default__")
            provider: LLM provider (e.g., "Google", "Anthropic") for master system prompts
        """
        self.profile_id = profile_id or "__system_default__"
        self.provider = provider
        self._loader = get_prompt_loader()
        self._cache = {}
        
        logger.debug(f"ProfilePromptResolver initialized for profile '{self.profile_id}' with provider '{provider}'")
    
    def _resolve_prompt_name(self, category: str, subcategory: str) -> Optional[str]:
        """
        Resolve prompt name through profile mapping system.
        
        Returns the mapped prompt name or None if not found.
        """
        cache_key = f"{category}:{subcategory}"
        
        if cache_key not in self._cache:
            prompt_name = get_prompt_for_category(
                profile_id=self.profile_id,
                category=category,
                subcategory=subcategory
            )
            self._cache[cache_key] = prompt_name
            logger.debug(f"Resolved {cache_key} -> {prompt_name} for profile {self.profile_id}")
        
        return self._cache[cache_key]
    
    def _load_prompt_content(self, prompt_name: str):
        """
        Load prompt content from database, handling both string and JSON formats.
        
        Returns the prompt content or None if not found.
        """
        if not prompt_name:
            return None
        
        try:
            content = self._loader.get_prompt(prompt_name)
            
            # Try to parse as JSON dict
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            
            return content
        except Exception as e:
            logger.error(f"Failed to load prompt '{prompt_name}': {e}")
            return None
    
    def get_master_system_prompt(self) -> Optional[str]:
        """
        Get master system prompt for the configured provider.
        
        Uses profile mapping to determine which master system prompt variant to use.
        Falls back to provider-specific defaults if no mapping exists.
        """
        if not self.provider:
            logger.warning("No provider set, cannot resolve master system prompt")
            return None
        
        prompt_name = self._resolve_prompt_name("master_system_prompts", self.provider)
        return self._load_prompt_content(prompt_name)
    
    def get_workflow_prompt(self, subcategory: str) -> Optional[str]:
        """
        Get workflow classification prompt.
        
        Args:
            subcategory: Workflow type (e.g., "task_classification")
        
        Returns:
            Prompt content as string
        """
        prompt_name = self._resolve_prompt_name("workflow_classification", subcategory)
        return self._load_prompt_content(prompt_name)
    
    def get_error_recovery_prompt(self, subcategory: str) -> Optional[str]:
        """
        Get error recovery prompt.
        
        Args:
            subcategory: Error type (e.g., "error_recovery", "tactical_self_correction",
                        "self_correction_column_error", "self_correction_table_error")
        
        Returns:
            Prompt content as string
        """
        prompt_name = self._resolve_prompt_name("error_recovery", subcategory)
        return self._load_prompt_content(prompt_name)
    
    def get_data_operations_prompt(self, subcategory: str) -> Optional[str]:
        """
        Get data operations prompt.
        
        Args:
            subcategory: Operation type (e.g., "sql_consolidation")
        
        Returns:
            Prompt content as string
        """
        prompt_name = self._resolve_prompt_name("data_operations", subcategory)
        return self._load_prompt_content(prompt_name)
    
    # Convenience methods for specific prompts
    
    def get_task_classification_prompt(self) -> Optional[str]:
        """Get TASK_CLASSIFICATION_PROMPT via profile mapping."""
        return self.get_workflow_prompt("task_classification")
    
    def get_error_recovery_base_prompt(self) -> Optional[str]:
        """Get ERROR_RECOVERY_PROMPT via profile mapping."""
        return self.get_error_recovery_prompt("error_recovery")
    
    def get_tactical_self_correction_prompt(self) -> Optional[str]:
        """Get TACTICAL_SELF_CORRECTION_PROMPT via profile mapping."""
        return self.get_error_recovery_prompt("tactical_self_correction")
    
    def get_tactical_self_correction_column_error_prompt(self) -> Optional[str]:
        """Get TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR via profile mapping."""
        return self.get_error_recovery_prompt("self_correction_column_error")
    
    def get_tactical_self_correction_table_error_prompt(self) -> Optional[str]:
        """Get TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR via profile mapping."""
        return self.get_error_recovery_prompt("self_correction_table_error")
    
    def get_sql_consolidation_prompt(self) -> Optional[str]:
        """Get SQL_CONSOLIDATION_PROMPT via profile mapping."""
        return self.get_data_operations_prompt("sql_consolidation")
    
    def get_genie_coordination_prompt(self, subcategory: str = "coordinator_prompt") -> Optional[str]:
        """
        Get genie coordination prompt.

        Args:
            subcategory: Coordination type (e.g., "coordinator_prompt")

        Returns:
            Prompt content as string
        """
        prompt_name = self._resolve_prompt_name("genie_coordination", subcategory)
        return self._load_prompt_content(prompt_name)

    def get_genie_coordinator_prompt(self) -> Optional[str]:
        """Get GENIE_COORDINATOR_PROMPT via profile mapping."""
        return self.get_genie_coordination_prompt("coordinator_prompt")

    def get_conversation_execution_prompt(self, subcategory: str = "conversation") -> Optional[str]:
        """
        Get conversation execution prompt.

        Args:
            subcategory: Conversation type (e.g., "conversation", "conversation_with_tools")

        Returns:
            Prompt content as string
        """
        prompt_name = self._resolve_prompt_name("conversation_execution", subcategory)
        return self._load_prompt_content(prompt_name)

    def get_conversation_with_tools_prompt(self) -> Optional[str]:
        """Get CONVERSATION_WITH_TOOLS_EXECUTION via profile mapping."""
        return self.get_conversation_execution_prompt("conversation_with_tools")

    def get_prompt(self, prompt_name: str) -> Optional[str]:
        """
        Direct prompt lookup by name (bypasses profile mapping).

        This is a convenience method for prompts that don't use the category/subcategory
        mapping system, or for direct fallback lookups.

        Args:
            prompt_name: The database prompt name (e.g., 'CONVERSATION_WITH_TOOLS_EXECUTION')

        Returns:
            Prompt content as string, or None if not found
        """
        return self._load_prompt_content(prompt_name)
