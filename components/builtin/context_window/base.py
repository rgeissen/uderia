"""
Base classes for the Context Window module plugin system.

Defines the ContextModule abstract base class that all context contributors
implement, along with the Contribution and AssemblyContext data classes
that form the contract between modules and the orchestrator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Assembly context — shared state passed to all modules during assembly
# ---------------------------------------------------------------------------

@dataclass
class AssemblyContext:
    """
    Shared state passed to all context modules during budget assembly.

    Contains everything a module needs to produce its contribution:
    profile info, session state, model limits, and results from
    higher-priority modules (for cross-module awareness).
    """

    # --- Profile & session identity ---
    profile_type: str
    """Profile class: tool_enabled, llm_only, rag_focused, genie."""

    profile_id: str
    """Active profile ID."""

    session_id: str
    """Current session ID."""

    user_uuid: str
    """Current user UUID."""

    # --- Session state ---
    session_data: Dict[str, Any] = field(default_factory=dict)
    """Full session data dict (chat_object, workflow_history, etc.)."""

    turn_number: int = 1
    """Current turn number in the conversation."""

    is_first_turn: bool = True
    """Whether this is the first turn (controls full vs condensed context)."""

    # --- Model limits ---
    model_context_limit: int = 128_000
    """Provider's maximum context window in tokens."""

    output_token_reserve: int = 16_384
    """Tokens reserved for LLM output generation."""

    # --- Execution dependencies ---
    dependencies: Dict[str, Any] = field(default_factory=dict)
    """
    MCP tools, prompts, structured tools, and other runtime dependencies.
    Mirrors the executor's dependencies dict.
    """

    # --- Cross-module awareness ---
    previous_contributions: Dict[str, "Contribution"] = field(default_factory=dict)
    """
    Results from higher-priority modules that have already contributed.
    Keyed by module_id. Allows lower-priority modules to adapt
    (e.g., skip content that a higher-priority module already provided).
    """

    # --- Profile config ---
    profile_config: Dict[str, Any] = field(default_factory=dict)
    """Full profile configuration dict."""

    @property
    def available_budget(self) -> int:
        """Total tokens available for context (limit minus output reserve)."""
        return self.model_context_limit - self.output_token_reserve


# ---------------------------------------------------------------------------
# Contribution — output from a module's assembly
# ---------------------------------------------------------------------------

@dataclass
class Contribution:
    """
    Output of a context module's contribute() or condense() call.

    This is the atomic unit of context — a piece of text with metadata
    about how many tokens it consumed and whether it can be further reduced.
    """

    content: str
    """The actual text to include in the LLM context window."""

    tokens_used: int
    """Estimated tokens consumed by this content."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """
    Module-specific metrics for observability. Examples:
    - system_prompt: {"provider": "Anthropic", "has_override": true}
    - tool_definitions: {"tool_count": 15, "mode": "names_only"}
    - conversation_history: {"turn_count": 5, "invalid_filtered": 2}
    - rag_context: {"cases_retrieved": 3, "confidence": 0.87}
    """

    condensable: bool = True
    """Whether this contribution can be further reduced under budget pressure."""


# ---------------------------------------------------------------------------
# Context module — abstract base class for all context contributors
# ---------------------------------------------------------------------------

class ContextModule(ABC):
    """
    Abstract base class for context window modules.

    A context module is a self-contained unit that contributes content
    to the LLM context window. Each module:
      - Knows how to produce its content (fetch tools, retrieve RAG, format history)
      - Declares whether it can condense its output under budget pressure
      - Declares which profile types it applies to
      - Can be installed, activated, deactivated, purged, or uninstalled

    Built-in modules wrap existing scattered logic (handler.py, planner.py, etc.)
    into a clean interface. Third-party modules can be added via agent packs
    or the ~/.tda/context_modules/ directory.
    """

    @property
    @abstractmethod
    def module_id(self) -> str:
        """
        Unique module identifier (e.g., 'system_prompt', 'tool_definitions').
        Must match the module_id in the module's manifest.json.
        """

    @abstractmethod
    def applies_to(self, profile_type: str) -> bool:
        """
        Whether this module is relevant for the given profile type.

        Called during Pass 1 of the orchestrator to determine which modules
        participate in budget allocation. Modules that return False are
        skipped and their budget is redistributed.

        Args:
            profile_type: One of 'tool_enabled', 'llm_only', 'rag_focused', 'genie'.

        Returns:
            True if this module should contribute for the given profile type.
        """

    @abstractmethod
    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Produce content within the given token budget.

        This is the primary method — called during Pass 2 of the orchestrator.
        The module should produce its best content within the allocated budget.

        Args:
            budget: Maximum tokens allocated to this module.
            ctx: Assembly context with session state, dependencies, etc.

        Returns:
            Contribution with content, token count, and metadata.
        """

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Reduce existing content to fit a smaller budget.

        Called during Pass 4 of the orchestrator when total context exceeds
        the available budget. Modules are condensed in condensation_order
        (lowest priority first).

        Override in subclass to implement condensation strategies:
          - tool_definitions: full descriptions → names-only list
          - conversation_history: sliding window, summarization
          - rag_context: fewer examples, lower k
          - document_context: per-file truncation

        Default implementation returns the content unchanged.

        Args:
            content: The current content to condense.
            target_tokens: The target token count to fit within.
            ctx: Assembly context.

        Returns:
            Condensed Contribution.
        """
        from .token_estimator import estimate_tokens
        return Contribution(
            content=content,
            tokens_used=estimate_tokens(content),
            metadata={"condensed": False, "reason": "not condensable"},
        )

    async def purge(
        self,
        session_id: str,
        user_uuid: str,
    ) -> Dict[str, Any]:
        """
        Clear cached or accumulated data for this module.

        Called when an admin or user triggers a purge action. Modules with
        purgeable data (conversation history, RAG cache, workflow history)
        should override this to clear their state.

        Args:
            session_id: Session to purge (or empty string for all sessions).
            user_uuid: User whose data to purge.

        Returns:
            Dict with purge results: {"purged": bool, "details": str}
        """
        return {"purged": False, "reason": "Module is not purgeable"}

    def get_status(self) -> Dict[str, Any]:
        """
        Return module health and status for the admin dashboard.

        Override to report cache size, last purge time, error counts, etc.

        Returns:
            Dict with status info: {"status": "ok", ...}
        """
        return {"status": "ok", "module_id": self.module_id}
