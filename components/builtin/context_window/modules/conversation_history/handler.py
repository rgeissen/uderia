"""
Conversation History context module.

Wraps the chat_object history assembly from session_manager.py.
Supports sliding window condensation under budget pressure and
purging of accumulated conversation data.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, estimate_tokens_for_messages

logger = logging.getLogger("quart.app")


class ConversationHistoryModule(ContextModule):
    """
    Contributes conversation history (chat_object) to the context window.

    Assembles the multi-turn conversation for LLM context. Filters out
    invalid turns and applies sliding window condensation when under
    budget pressure (keeps most recent N turns).

    Condensation strategy: sliding window (drop oldest turns first).
    Purgeable: clears accumulated conversation history.
    """

    @property
    def module_id(self) -> str:
        return "conversation_history"

    def applies_to(self, profile_type: str) -> bool:
        return True  # All profile types need conversation history

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Assemble conversation history within the token budget.

        Reads chat_object from session data and formats as messages.
        On the first turn, returns empty (no history yet).
        """
        session_data = ctx.session_data
        chat_object = session_data.get("chat_object", [])

        if not chat_object:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"turn_count": 0, "mode": "empty"},
                condensable=False,
            )

        # Filter to valid messages only
        valid_messages = self._filter_valid_messages(chat_object)

        if not valid_messages:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"turn_count": 0, "invalid_filtered": len(chat_object)},
                condensable=False,
            )

        # Estimate tokens and apply sliding window if over budget
        total_tokens = estimate_tokens_for_messages(valid_messages)
        if total_tokens > budget and len(valid_messages) > 2:
            valid_messages = self._apply_sliding_window(valid_messages, budget)
            total_tokens = estimate_tokens_for_messages(valid_messages)

        # Format as text for context
        content = self._format_messages(valid_messages)
        tokens = estimate_tokens(content)

        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={
                "turn_count": len(valid_messages),
                "total_messages_available": len(chat_object),
                "invalid_filtered": len(chat_object) - len(valid_messages),
                "mode": "full" if len(valid_messages) == len(chat_object) else "windowed",
            },
            condensable=True,
        )

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """Condense by applying a tighter sliding window."""
        session_data = ctx.session_data
        chat_object = session_data.get("chat_object", [])

        if not chat_object:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"turn_count": 0, "condensed": True},
            )

        valid_messages = self._filter_valid_messages(chat_object)
        windowed = self._apply_sliding_window(valid_messages, target_tokens)
        condensed_content = self._format_messages(windowed)
        tokens = estimate_tokens(condensed_content)

        return Contribution(
            content=condensed_content,
            tokens_used=tokens,
            metadata={
                "turn_count": len(windowed),
                "condensed": True,
                "strategy": "sliding_window",
                "turns_dropped": len(valid_messages) - len(windowed),
            },
        )

    async def purge(
        self,
        session_id: str,
        user_uuid: str,
    ) -> Dict[str, Any]:
        """
        Purge conversation history for a session.

        Clears the chat_object in the session data, effectively
        resetting the conversation to a fresh state.
        """
        try:
            from trusted_data_agent.core.session_manager import SessionManager

            sm = SessionManager()
            if session_id:
                session_data = await sm.load_session(session_id, user_uuid)
                if session_data:
                    turn_count = len(session_data.get("chat_object", []))
                    session_data["chat_object"] = []
                    await sm.save_session(session_id, user_uuid, session_data)
                    return {
                        "purged": True,
                        "details": f"Cleared {turn_count} messages from session {session_id}",
                    }
            return {"purged": False, "reason": "Session not found"}
        except Exception as e:
            logger.error(f"ConversationHistoryModule purge failed: {e}")
            return {"purged": False, "reason": str(e)}

    def _filter_valid_messages(self, chat_object: list) -> list:
        """Filter to valid messages with role and content."""
        valid = []
        for msg in chat_object:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") and msg.get("content"):
                # Skip messages marked as invalid
                if msg.get("isValid") is False:
                    continue
                valid.append(msg)
        return valid

    def _apply_sliding_window(self, messages: list, token_budget: int) -> list:
        """Keep most recent messages that fit within the token budget."""
        if not messages:
            return []

        # Always keep the most recent message pair (user + assistant)
        # Then add older messages from newest to oldest until budget is exceeded
        result = []
        running_tokens = 0

        for msg in reversed(messages):
            msg_tokens = estimate_tokens(msg.get("content", "")) + 4  # +4 overhead
            if running_tokens + msg_tokens > token_budget and len(result) >= 2:
                break
            result.append(msg)
            running_tokens += msg_tokens

        result.reverse()
        return result

    def _format_messages(self, messages: list) -> str:
        """Format messages as a text block for context."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"[{role}]: {content}")
        return "\n\n".join(lines)
