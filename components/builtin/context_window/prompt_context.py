"""
PromptContext — return value from ContextBuilder.build().

Encapsulates everything an LLM call site needs: ready-to-use template
variables, per-module content blocks, a snapshot for observability,
and token accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .snapshot import ContextWindowSnapshot


@dataclass
class PromptContext:
    """
    Complete context package for a single LLM call.

    Returned by ``ContextBuilder.build()`` and consumed by callers
    (planner.py, phase_executor.py, executor.py) to populate prompt
    templates and emit observability events.
    """

    call_type: str
    """Which call type produced this context: strategic, tactical, synthesis, utility."""

    template_vars: Dict[str, Any] = field(default_factory=dict)
    """
    Ready-to-use variables for prompt template .format() injection.

    Contains BOTH content data (from modules, budget-aware) and control
    data (execution-specific, passed through from caller).  Callers use:

        prompt = TEMPLATE.format(**prompt_ctx.template_vars)
    """

    content_blocks: Dict[str, str] = field(default_factory=dict)
    """
    Module content keyed by module_id.

    Provides direct access to each module's contribution text when
    callers need to manipulate content outside of template formatting
    (e.g., build a user message from knowledge + history + docs).
    """

    snapshot: Optional[ContextWindowSnapshot] = None
    """Per-call context window snapshot for observability."""

    tokens_used: int = 0
    """Total estimated tokens consumed by all content in this context."""

    source: str = "builder"
    """How this context was assembled: 'builder' (normal) or 'fallback' (legacy path)."""
