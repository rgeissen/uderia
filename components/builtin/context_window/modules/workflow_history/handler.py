"""
Workflow History context module.

Wraps the turn summary assembly from planner.py:_create_summary_from_history().
Provides the strategic planner with structured execution traces from
previous turns for multi-turn awareness and plan optimization.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

logger = logging.getLogger("quart.app")


class WorkflowHistoryModule(ContextModule):
    """
    Contributes workflow history to the context window.

    Provides the strategic planner with structured execution traces
    from previous turns. This enables multi-turn awareness — the planner
    can see what tools were called, what results were obtained, and
    plan accordingly to avoid redundant operations.

    Condensation strategy: fewer turns (keep most recent N).
    Purgeable: clears accumulated workflow history.
    """

    @property
    def module_id(self) -> str:
        return "workflow_history"

    def applies_to(self, profile_type: str) -> bool:
        return profile_type == "tool_enabled"

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Assemble workflow history within the token budget.

        Reads workflow_history from session data and formats valid
        turns as structured summaries for the planner.
        """
        if ctx.is_first_turn:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"turn_count": 0, "reason": "first_turn"},
                condensable=False,
            )

        session_data = ctx.session_data
        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

        if not workflow_history:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"turn_count": 0, "reason": "no_history"},
                condensable=False,
            )

        # Filter to valid turns
        valid_turns = [
            turn for turn in workflow_history
            if turn.get("isValid") is not False
        ]

        if not valid_turns:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"turn_count": 0, "invalid_filtered": len(workflow_history)},
                condensable=False,
            )

        # Format within budget
        char_budget = tokens_to_chars(budget)
        content = self._format_workflow_history(valid_turns, char_budget)
        tokens = estimate_tokens(content)

        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={
                "turn_count": len(valid_turns),
                "total_turns_available": len(workflow_history),
                "invalid_filtered": len(workflow_history) - len(valid_turns),
            },
            condensable=True,
        )

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """Condense by keeping fewer turns."""
        session_data = ctx.session_data
        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

        valid_turns = [
            turn for turn in workflow_history
            if turn.get("isValid") is not False
        ]

        if not valid_turns:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"condensed": True, "turn_count": 0},
            )

        # Keep only the most recent turns that fit
        char_budget = tokens_to_chars(target_tokens)
        content = self._format_workflow_history(
            valid_turns, char_budget, newest_first=True
        )
        tokens = estimate_tokens(content)

        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={
                "condensed": True,
                "strategy": "fewer_turns",
                "turn_count": content.count("Turn #"),
            },
        )

    async def purge(
        self,
        session_id: str,
        user_uuid: str,
    ) -> Dict[str, Any]:
        """Purge workflow history for a session."""
        try:
            from trusted_data_agent.core.session_manager import SessionManager

            sm = SessionManager()
            if session_id:
                session_data = await sm.load_session(session_id, user_uuid)
                if session_data:
                    turn_count = len(session_data.get("last_turn_data", {}).get("workflow_history", []))
                    session_data["workflow_history"] = []
                    await sm.save_session(session_id, user_uuid, session_data)
                    return {
                        "purged": True,
                        "details": f"Cleared {turn_count} workflow turns from session {session_id}",
                    }
            return {"purged": False, "reason": "Session not found"}
        except Exception as e:
            logger.error(f"WorkflowHistoryModule purge failed: {e}")
            return {"purged": False, "reason": str(e)}

    def _format_workflow_history(
        self,
        turns: List[Dict],
        char_budget: int,
        newest_first: bool = False,
    ) -> str:
        """Format workflow turns for planner context."""
        lines = ["--- WORKFLOW HISTORY ---"]
        lines.append(
            "Previous execution turns for multi-turn awareness:\n"
        )
        total_chars = sum(len(line) for line in lines)

        # Order turns
        ordered_turns = list(reversed(turns)) if newest_first else turns

        for turn in ordered_turns:
            turn_text = self._format_single_turn(turn)
            if total_chars + len(turn_text) > char_budget and total_chars > 100:
                break
            lines.append(turn_text)
            total_chars += len(turn_text)

        return "\n".join(lines)

    def _format_single_turn(self, turn: dict) -> str:
        """Format a single workflow turn."""
        parts = []
        turn_number = turn.get("turn_number", "?")
        parts.append(f"Turn #{turn_number}:")

        execution_trace = turn.get("execution_trace", [])
        for phase in execution_trace:
            action = phase.get("action", {})
            tool_name = action.get("tool_name", "unknown")
            output = phase.get("tool_output_summary", {})
            status = output.get("status", "unknown")

            results = output.get("results", [])
            if isinstance(results, list):
                row_count = len(results)
                result_summary = f"{row_count} rows"
            else:
                result_summary = "data returned"

            parts.append(f"  - {tool_name}: {status} ({result_summary})")

        parts.append("")
        return "\n".join(parts)
