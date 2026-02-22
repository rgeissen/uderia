"""
Data models for the Skills system.

Skills are pre-processing prompt injections — reusable markdown knowledge
documents whose content gets injected into the LLM's system prompt or
user message before execution.

Fully compatible with Claude Code skills format:
  skill-name/
    skill.json     — manifest (metadata + discovery)
    skill-name.md  — free-form markdown content
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SkillSpec:
    """A skill selection parsed from user input (e.g., !sql-expert:strict)."""

    name: str
    """Activation name (e.g., 'sql-expert')."""

    param: Optional[str] = None
    """Optional parameter (e.g., 'strict')."""


@dataclass
class SkillContent:
    """Loaded content from a single skill, ready for injection."""

    skill_name: str
    """Name of the skill that produced this content."""

    content: str
    """The markdown content to inject into the LLM context."""

    injection_target: str = "system_prompt"
    """Where to inject: 'system_prompt' or 'user_context'."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Full manifest metadata from skill.json."""

    param: Optional[str] = None
    """The param that was used to resolve this content (if any)."""

    @property
    def content_length(self) -> int:
        return len(self.content)

    @property
    def estimated_tokens(self) -> int:
        """Rough chars-to-tokens estimate (÷4)."""
        return len(self.content) // 4


@dataclass
class SkillResult:
    """
    Merged result from all selected skills for a query.

    Separates content by injection target so the executor can
    inject into the right place.
    """

    system_prompt_additions: List[str] = field(default_factory=list)
    """Skill contents targeting the system prompt."""

    user_context_additions: List[str] = field(default_factory=list)
    """Skill contents targeting user context (prepended to user message)."""

    skill_contents: Dict[str, SkillContent] = field(default_factory=dict)
    """Per-skill details keyed by skill name."""

    @property
    def has_content(self) -> bool:
        return bool(self.system_prompt_additions or self.user_context_additions)

    @property
    def total_estimated_tokens(self) -> int:
        return sum(sc.estimated_tokens for sc in self.skill_contents.values())

    def get_system_prompt_block(self) -> str:
        """Get concatenated system prompt additions, delimited per skill."""
        if not self.system_prompt_additions:
            return ""
        return "\n\n".join(self.system_prompt_additions)

    def get_user_context_block(self) -> str:
        """Get concatenated user context additions, delimited per skill."""
        if not self.user_context_additions:
            return ""
        return "\n\n".join(self.user_context_additions)

    def to_applied_list(self) -> List[Dict[str, Any]]:
        """Build the skills_applied metadata for SSE event and workflow history."""
        return [
            {
                "name": sc.skill_name,
                "param": sc.param,
                "injection_target": sc.injection_target,
                "content_length": sc.content_length,
                "estimated_tokens": sc.estimated_tokens,
            }
            for sc in self.skill_contents.values()
        ]
