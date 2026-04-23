"""
Plan Hydration context module.

Wraps the plan hydration logic from planner.py:_hydrate_plan_from_previous_turn().
Injects previous turn execution results into the current context to enable
the LLM to skip redundant tool calls (e.g., schema re-fetching).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, TYPE_CHECKING

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

if TYPE_CHECKING:
    from trusted_data_agent.vectorstore.types import VectorDocument

logger = logging.getLogger("quart.app")


class PlanHydrationModule(ContextModule):
    """
    Contributes previous turn results for plan hydration.

    Extracts successful execution results from the previous turn's
    workflow history and injects them into the current context. This
    allows the LLM to reference prior results directly instead of
    re-executing redundant tool calls (30-50% token savings on multi-turn).

    Condensation strategy: summarize results instead of full data.
    RAG condensation: floor% via summary + remainder from semantic retrieval
    (default floor=0: replace entirely — relevance beats recency for tool results).
    Purgeable: clears accumulated turn data.
    """

    supports_rag_condensation: bool = True
    APPROX_TOKENS_PER_CHUNK: int = 300

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

    async def condense_rag(
        self,
        content: str,
        target_tokens: int,
        query: str,
        ctx: AssemblyContext,
        session_store: Any,
        floor_pct: int,
    ) -> Contribution:
        """
        RAG condensation: keep floor_pct% via summary, fill remainder with
        semantically retrieved tool results. Uses the current phase goal as
        retrieval query when available — surfaces the most relevant prior results
        for the specific operation being planned.
        """
        # Phase goal is more precise than the raw user message for tool result retrieval
        retrieval_query = ctx.session_data.get("current_phase_goal") or query

        floor_tokens = int(target_tokens * floor_pct / 100)
        rag_tokens = target_tokens - floor_tokens

        floor_contribution = None
        if floor_pct > 0 and floor_tokens > 0:
            floor_contribution = await self.condense(content, floor_tokens, ctx)

        n_chunks = max(1, rag_tokens // self.APPROX_TOKENS_PER_CHUNK)
        results = await session_store.retrieve(self.module_id, retrieval_query, n_results=n_chunks)
        rag_content = self._format_rag_chunks(results)

        parts = []
        if floor_contribution and floor_contribution.content:
            parts.append(f"--- Recent Context ---\n{floor_contribution.content}")
        if rag_content:
            parts.append(f"--- Relevant Earlier Context ---\n{rag_content}")

        if not parts:
            return await self.condense(content, target_tokens, ctx)

        combined = "\n\n".join(parts)
        return Contribution(
            content=combined,
            tokens_used=estimate_tokens(combined),
            metadata={
                "strategy": "rag_offload",
                "floor_pct": floor_pct,
                "chunks_retrieved": len(results),
                "condensed": True,
            },
            condensable=True,
        )

    def _format_rag_chunks(self, results: "List[VectorDocument]") -> str:
        """Format retrieved tool result chunks."""
        parts = []
        for doc in results:
            tool_name = doc.metadata.get("tool_name", "tool")
            phase = doc.metadata.get("phase", "")
            label = tool_name
            if phase:
                label += f" (phase {phase})"
            parts.append(f"{label}:\n{doc.content}")
        return "\n\n".join(parts)

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
