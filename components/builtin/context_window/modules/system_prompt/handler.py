"""
System Prompt context module.

Wraps the system prompt assembly logic from handler.py:_get_full_system_prompt().
Produces the base system prompt with provider-specific formatting and
profile-aware prompt resolution (license tier, profile overrides, defaults).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

logger = logging.getLogger("quart.app")


class SystemPromptModule(ContextModule):
    """
    Contributes the base system prompt to the context window.

    The system prompt is the foundation of every LLM call. This module
    resolves the correct prompt based on:
      - User license tier (PE/Enterprise get custom prompts)
      - Profile-level prompt overrides
      - Provider-specific defaults (Anthropic, Google, etc.)

    Not condensable — the system prompt is always required in full.
    """

    @property
    def module_id(self) -> str:
        return "system_prompt"

    def applies_to(self, profile_type: str) -> bool:
        return True  # Every profile type needs a system prompt

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Assemble the system prompt for the current profile and provider.

        Delegates to the existing _get_full_system_prompt() logic in handler.py.
        The budget is informational — system prompt is always included in full
        since it's a required, non-condensable module.
        """
        session_data = ctx.session_data
        dependencies = ctx.dependencies
        profile_config = ctx.profile_config

        # Extract provider from dependencies or session data
        current_provider = dependencies.get("current_provider", "")
        user_uuid = ctx.user_uuid
        active_profile_id = ctx.profile_id

        # Resolve the system prompt using profile prompt resolver
        system_prompt = ""
        try:
            from trusted_data_agent.agent.profile_prompt_resolver import (
                ProfilePromptResolver,
            )

            resolver = ProfilePromptResolver(
                profile_id=active_profile_id,
                provider=current_provider,
            )
            resolved = resolver.get_master_system_prompt()
            if resolved:
                # get_master_system_prompt() can return str or dict
                import json
                system_prompt = (
                    json.dumps(resolved) if isinstance(resolved, dict) else str(resolved)
                )
        except Exception as e:
            logger.warning(f"SystemPromptModule: resolver failed: {e}")

        # Fallback to provider default if resolver returned nothing
        if not system_prompt:
            try:
                from trusted_data_agent.agent.prompts import PROVIDER_SYSTEM_PROMPTS
                prompt_obj = PROVIDER_SYSTEM_PROMPTS.get(
                    current_provider,
                    PROVIDER_SYSTEM_PROMPTS.get("Google", "You are a helpful assistant."),
                )
                # LazyPrompt objects need str() conversion
                system_prompt = str(prompt_obj)
            except ImportError:
                system_prompt = "You are a helpful assistant."

        tokens = estimate_tokens(system_prompt)

        return Contribution(
            content=system_prompt,
            tokens_used=tokens,
            metadata={
                "provider": current_provider,
                "profile_id": active_profile_id,
                "has_override": bool(profile_config.get("systemPromptOverride")),
                "char_count": len(system_prompt),
            },
            condensable=False,
        )
