"""
Skills package — pre-processing prompt injection for LLM context.

Skills are reusable markdown knowledge documents that get injected into
the LLM's system prompt or user message before execution. Fully compatible
with Claude Code skills format (bidirectional import/export).

Triggered by !name:param syntax in user queries.

Format:
  skill-name/
    skill.json     — manifest (metadata + discovery)
    skill-name.md  — free-form markdown content
"""

from trusted_data_agent.skills.models import (
    SkillSpec,
    SkillContent,
    SkillResult,
)
from trusted_data_agent.skills.manager import get_skill_manager

__all__ = [
    # Models
    "SkillSpec",
    "SkillContent",
    "SkillResult",
    # Infrastructure
    "get_skill_manager",
]
