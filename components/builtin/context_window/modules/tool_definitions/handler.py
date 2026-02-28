"""
Tool Definitions context module.

Wraps the tool schema formatting and condensation logic from handler.py.
Supports two modes:
  - Full: Complete tool descriptions with argument schemas (first turn)
  - Names-only: Condensed tool names grouped by category (~60-70% savings)
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

logger = logging.getLogger("quart.app")


class ToolDefinitionsModule(ContextModule):
    """
    Contributes MCP tool definitions to the context window.

    On the first turn, provides full tool descriptions with argument schemas
    so the LLM understands each tool's purpose and parameters. On subsequent
    turns, condenses to names-only format grouped by category, saving 60-70%
    of tool context tokens.

    Condensation strategy: full descriptions → names-only list.
    """

    @property
    def module_id(self) -> str:
        return "tool_definitions"

    def applies_to(self, profile_type: str) -> bool:
        return profile_type in ("tool_enabled", "genie")

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Format tool definitions for the LLM context.

        Uses full descriptions on the first turn, names-only on subsequent turns
        (unless budget pressure forces condensation earlier).
        """
        dependencies = ctx.dependencies
        structured_tools = dependencies.get("structured_tools", {})
        is_first_turn = ctx.is_first_turn

        if not structured_tools:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"tool_count": 0, "mode": "empty"},
                condensable=False,
            )

        # Choose mode based on turn number
        if is_first_turn:
            content = self._format_full(structured_tools)
            mode = "full"
        else:
            content = self._format_condensed(structured_tools)
            mode = "names_only"

        # Truncate to budget if needed
        char_budget = tokens_to_chars(budget)
        if len(content) > char_budget:
            # Fall back to condensed if full doesn't fit
            if mode == "full":
                content = self._format_condensed(structured_tools)
                mode = "names_only"
            # Final truncation if still over
            if len(content) > char_budget:
                content = content[:char_budget] + "\n... (truncated)"

        tool_count = sum(len(tools) for tools in structured_tools.values())
        tokens = estimate_tokens(content)

        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={
                "tool_count": tool_count,
                "category_count": len(structured_tools),
                "mode": mode,
            },
            condensable=True,
        )

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """Condense tool definitions to names-only format."""
        dependencies = ctx.dependencies
        structured_tools = dependencies.get("structured_tools", {})

        if not structured_tools:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"tool_count": 0, "mode": "empty", "condensed": True},
            )

        condensed = self._format_condensed(structured_tools)
        tool_count = sum(len(tools) for tools in structured_tools.values())
        tokens = estimate_tokens(condensed)

        return Contribution(
            content=condensed,
            tokens_used=tokens,
            metadata={
                "tool_count": tool_count,
                "mode": "names_only",
                "condensed": True,
                "strategy": "names_only",
            },
        )

    def _format_full(self, structured_tools: Dict[str, Any]) -> str:
        """Format tools with full descriptions and argument schemas."""
        lines = ["Available tools:\n"]

        for category, tools in structured_tools.items():
            if not tools:
                continue
            lines.append(f"**{category}**:")
            for tool_name, tool_info in tools.items():
                desc = tool_info.get("description", "")
                lines.append(f"- `{tool_name}` (tool): {desc}")

                # Format arguments
                args = tool_info.get("inputSchema", {}).get("properties", {})
                required = tool_info.get("inputSchema", {}).get("required", [])
                for arg_name, arg_info in args.items():
                    arg_type = arg_info.get("type", "string")
                    arg_desc = arg_info.get("description", "")
                    req_label = "required" if arg_name in required else "optional"
                    lines.append(
                        f"  - `{arg_name}` ({arg_type}, {req_label}): {arg_desc}"
                    )
            lines.append("")

        return "\n".join(lines)

    def _format_condensed(self, structured_tools: Dict[str, Any]) -> str:
        """Format tools as names-only grouped by category."""
        lines = ["Available tools (condensed):\n"]

        for category, tools in structured_tools.items():
            if not tools:
                continue
            tool_names = ", ".join(f"`{name}`" for name in tools.keys())
            lines.append(f"- **{category}**: {tool_names}")

        return "\n".join(lines)
