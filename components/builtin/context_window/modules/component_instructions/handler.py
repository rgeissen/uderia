"""
Component Instructions context module.

Wraps the component instructions assembly from manager.py:get_instructions_text().
Collects LLM prompt instructions from all active Generative UI components
(chart, canvas, etc.) at the configured intensity level.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

logger = logging.getLogger("quart.app")


class ComponentInstructionsModule(ContextModule):
    """
    Contributes component instructions to the context window.

    Collects LLM prompt instructions from all active Generative UI
    components at the profile's configured intensity level (none/medium/heavy).
    These instructions guide the LLM on when and how to use components
    like charts, code editors, etc.

    Condensation strategy: reduce intensity level (heavy → medium → none).
    """

    @property
    def module_id(self) -> str:
        return "component_instructions"

    def applies_to(self, profile_type: str) -> bool:
        return profile_type in ("tool_enabled", "llm_only")

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Assemble component instructions for the current profile.

        Delegates to ComponentManager.get_instructions_text() which
        iterates active components and collects their instructions
        at the configured intensity level.
        """
        profile_config = ctx.profile_config
        session_data = ctx.session_data
        profile_id = ctx.profile_id
        user_uuid = ctx.user_uuid

        try:
            from trusted_data_agent.components.manager import (
                get_component_instructions_for_prompt,
            )

            instructions = get_component_instructions_for_prompt(
                profile_id=profile_id,
                user_uuid=user_uuid,
                session_data=session_data,
            )
        except Exception as e:
            logger.warning(f"ComponentInstructionsModule: failed to get instructions: {e}")
            instructions = ""

        if not instructions:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"component_count": 0, "reason": "no_instructions"},
                condensable=False,
            )

        # Truncate to budget if needed
        char_budget = tokens_to_chars(budget)
        if len(instructions) > char_budget:
            instructions = instructions[:char_budget] + "\n... (instructions truncated)"

        tokens = estimate_tokens(instructions)

        # Count active components from profile config
        component_config = profile_config.get("componentConfig", {})
        active_count = sum(
            1 for cfg in component_config.values()
            if isinstance(cfg, dict) and cfg.get("enabled", False)
        )

        return Contribution(
            content=instructions,
            tokens_used=tokens,
            metadata={
                "component_count": active_count,
                "char_count": len(instructions),
            },
            condensable=True,
        )

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Condense by reducing intensity or truncating.

        In a full implementation, this would re-fetch instructions at a
        lower intensity level. For now, truncates to fit.
        """
        if not content:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"condensed": True, "component_count": 0},
            )

        char_budget = tokens_to_chars(target_tokens)
        if len(content) > char_budget:
            content = content[:char_budget] + "\n... (instructions condensed)"

        tokens = estimate_tokens(content)
        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={"condensed": True, "strategy": "intensity_reduction"},
        )
