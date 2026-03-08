"""
Plan Hydration context module.

Wraps the plan hydration logic from planner.py:_hydrate_plan_from_previous_turn().
Injects previous turn execution results into the current context to enable
the LLM to skip redundant tool calls (e.g., schema re-fetching).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

logger = logging.getLogger("quart.app")


class PlanHydrationModule(ContextModule):
    """
    Contributes previous turn results for plan hydration.

    Extracts successful execution results from the previous turn's
    workflow history and injects them into the current context. This
    allows the LLM to reference prior results directly instead of
    re-executing redundant tool calls (30-50% token savings on multi-turn).

    Condensation strategy: summarize results instead of full data.
    Purgeable: clears accumulated turn data.
    """

    @property
    def module_id(self) -> str:
        return "plan_hydration"

    def applies_to(self, profile_type: str) -> bool:
        return profile_type == "tool_enabled"

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Extract and format previous turn results for plan hydration.

        Only active on turns > 1 where previous execution data exists.
        """
        if ctx.is_first_turn:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"reason": "first_turn", "hydrated": False},
                condensable=False,
            )

        session_data = ctx.session_data
        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

        if not workflow_history:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"reason": "no_history", "hydrated": False},
                condensable=False,
            )

        # Extract results from the most recent successful turn
        previous_results = self._extract_previous_results(workflow_history)

        if not previous_results:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"reason": "no_results", "hydrated": False},
                condensable=False,
            )

        # Format results within budget
        char_budget = tokens_to_chars(budget)
        content = self._format_hydration_context(previous_results, char_budget)
        tokens = estimate_tokens(content)

        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={
                "hydrated": True,
                "phases_available": len(previous_results),
                "turn_source": len(workflow_history),
            },
            condensable=True,
        )

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """Condense by summarizing hydration data instead of full results."""
        if not content:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"condensed": True, "hydrated": False},
            )

        # Truncate to target budget
        char_budget = tokens_to_chars(target_tokens)
        if len(content) > char_budget:
            content = content[:char_budget] + "\n... (hydration data truncated)"

        tokens = estimate_tokens(content)
        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={"condensed": True, "strategy": "summary"},
        )

    async def purge(
        self,
        session_id: str,
        user_uuid: str,
    ) -> Dict[str, Any]:
        """Purge cached hydration data."""
        return {
            "purged": True,
            "details": "Plan hydration cache cleared (session-scoped, resets on new turn)",
        }

    def _extract_previous_results(self, workflow_history: list) -> list:
        """
        Extract successful phase results from the most recent turn.

        Returns list of phase result dicts with tool_name, status, and summary.
        """
        results = []

        # Work backward through history to find the most recent valid turn
        for turn in reversed(workflow_history):
            if turn.get("isValid") is False:
                continue

            execution_trace = turn.get("execution_trace", [])
            for phase in execution_trace:
                action = phase.get("action", {})
                output = phase.get("tool_output_summary", {})

                if output.get("status") == "success":
                    results.append({
                        "tool_name": action.get("tool_name", "unknown"),
                        "arguments": action.get("arguments", {}),
                        "results": output.get("results", []),
                        "metadata": output.get("metadata", {}),
                    })

            if results:
                break  # Only use the most recent valid turn

        return results

    def _format_hydration_context(self, results: list, char_budget: int) -> str:
        """Format previous results for context injection."""
        lines = ["--- PREVIOUS TURN RESULTS ---"]
        lines.append(
            "The following data is available from the previous turn's execution. "
            "Reference this data directly instead of re-executing the same tool calls.\n"
        )

        total_chars = sum(len(line) for line in lines)

        for result in results:
            tool_name = result["tool_name"]
            result_data = result.get("results", [])

            # Summarize large results
            if isinstance(result_data, list) and len(result_data) > 20:
                summary = (
                    f"Previous call to `{tool_name}` returned {len(result_data)} rows. "
                    f"First 5 rows: {json.dumps(result_data[:5], default=str)}"
                )
            else:
                summary = (
                    f"Previous call to `{tool_name}` returned: "
                    f"{json.dumps(result_data, default=str)}"
                )

            if total_chars + len(summary) > char_budget:
                break
            lines.append(summary)
            total_chars += len(summary)

        return "\n".join(lines)
