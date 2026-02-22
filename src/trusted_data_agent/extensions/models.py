"""
Data models for the Extensions system.

ExtensionContext carries the rich context passed to every extension.
ExtensionResult is the standardized output returned by extensions.

Genie coordination models (GenieContentNode, GenieChildResult, GenieContext)
provide structured access to multi-profile coordination data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OutputTarget(Enum):
    """Where the extension output is displayed in the UI."""
    SILENT = "silent"              # API-only, no UI display (default for automation)
    CHAT_APPEND = "chat_append"    # Appended below the LLM answer in chat log
    STATUS_PANEL = "status_panel"  # Rendered in the Live Status panel


# ---------------------------------------------------------------------------
# Genie coordination models
# ---------------------------------------------------------------------------

@dataclass
class GenieContentNode:
    """A labeled content unit from a node in the genie execution tree.

    Used by GenieContext.get_content() to provide scope-based content access.
    Each node represents either the coordinator's synthesis or a child profile's
    response, with enough metadata for extensions to render rich output.

    Example — PDF extension iterating nodes::

        for node in context.genie.get_content(scope="all"):
            pdf.add_section(title=node.label, content=node.text)
    """

    label: str
    """Display label, e.g. 'Coordinator Synthesis' or '@CHAT Response'."""

    text: str
    """Full response text from this node."""

    node_type: str
    """'coordinator' or 'child'."""

    profile_tag: str
    """Profile tag, e.g. 'VAT' for coordinator, 'CHAT' for a child."""

    profile_type: str
    """Profile class: 'genie', 'tool_enabled', 'llm_only', 'rag_focused'."""

    duration_ms: int = 0
    """Execution time in milliseconds (0 for coordinator synthesis)."""

    success: bool = True
    """Whether this node completed successfully."""

    metadata: dict = field(default_factory=dict)
    """Extra fields (session_id, error, query sent to child, etc.)."""


@dataclass
class GenieChildResult:
    """Result from a single child profile invocation during genie coordination.

    One instance per invoked child, keyed by profile_tag in
    GenieContext.child_results.
    """

    profile_tag: str
    """Child profile tag, e.g. 'CHAT', 'RAG', 'OPTIM'."""

    profile_id: str
    """UUID of the child profile."""

    profile_type: str
    """Child profile class: 'tool_enabled', 'llm_only', 'rag_focused', 'genie'."""

    session_id: str
    """Child session ID created for this invocation."""

    query: str
    """Query the coordinator sent to this child."""

    response: str
    """Full response text returned by the child."""

    duration_ms: int = 0
    """Execution time in milliseconds."""

    success: bool = True
    """Whether the child completed successfully."""

    error: Optional[str] = None
    """Error message if success is False."""


@dataclass
class GenieContext:
    """Rich context for genie coordinator executions.

    Populated only when profile_type == 'genie'. Attached to
    ExtensionContext.genie (None for non-genie profiles).

    Provides three levels of content access via get_content(scope):
      - ``"coordinator"`` — only the coordinator's synthesized response
      - ``"children"``    — individual child profile responses
      - ``"all"``         — children first, then coordinator synthesis

    Example — detecting a genie execution::

        if context.genie:
            nodes = context.genie.get_content(scope="all")
            for node in nodes:
                process(node.label, node.text)

    Example — accessing a specific child::

        rag_answer = context.genie.get_child_response("RAG")
    """

    # --- Coordinator data ---
    coordinator_response: str
    """The coordinator's final synthesized answer."""

    coordinator_profile_tag: str
    """Profile tag of the genie coordinator, e.g. 'VAT'."""

    # --- Child profiles ---
    available_profiles: list = field(default_factory=list)
    """All child profiles configured on this genie.
    Each entry is a dict with keys: tag, id, name, profile_type."""

    profiles_invoked: list = field(default_factory=list)
    """Profile tags actually called this turn, e.g. ['CHAT', 'RAG']."""

    child_results: Dict[str, GenieChildResult] = field(default_factory=dict)
    """Per-child results keyed by profile tag."""

    slave_sessions: dict = field(default_factory=dict)
    """Mapping of profile tag → child session ID for this turn."""

    # --- Coordination metadata ---
    coordination_events: list = field(default_factory=list)
    """Full genie event timeline (genie_slave_invoked, genie_slave_completed, etc.)."""

    coordination_duration_ms: int = 0
    """Total coordination wall-clock time in milliseconds."""

    coordinator_llm_steps: int = 0
    """Number of LLM reasoning steps the coordinator took."""

    # --- Scope-based content access ---

    def get_content(self, scope: str = "all") -> List[GenieContentNode]:
        """Get content nodes for the requested scope.

        Args:
            scope: One of ``"coordinator"``, ``"children"``, or ``"all"``.

        Returns:
            Ordered list of :class:`GenieContentNode` objects.

            - ``"coordinator"``: Single node with the coordinator's synthesis.
            - ``"children"``: One node per invoked child profile, ordered by
              invocation sequence.
            - ``"all"``: Children first (invocation order), then coordinator
              synthesis last.
        """
        children_nodes: List[GenieContentNode] = []
        coordinator_node = GenieContentNode(
            label="Coordinator Synthesis",
            text=self.coordinator_response,
            node_type="coordinator",
            profile_tag=self.coordinator_profile_tag,
            profile_type="genie",
            duration_ms=self.coordination_duration_ms,
            success=True,
            metadata={},
        )

        if scope == "coordinator":
            return [coordinator_node]

        # Build child nodes in invocation order
        for tag in self.profiles_invoked:
            child = self.child_results.get(tag)
            if child is None:
                continue
            children_nodes.append(GenieContentNode(
                label=f"@{child.profile_tag} Response",
                text=child.response,
                node_type="child",
                profile_tag=child.profile_tag,
                profile_type=child.profile_type,
                duration_ms=child.duration_ms,
                success=child.success,
                metadata={
                    "session_id": child.session_id,
                    "query": child.query,
                    "error": child.error,
                },
            ))

        if scope == "children":
            return children_nodes

        # scope == "all": children first, coordinator last
        return children_nodes + [coordinator_node]

    # --- Convenience methods ---

    def get_child_response(self, profile_tag: str) -> Optional[str]:
        """Get a specific child's response text by profile tag.

        Returns None if the child was not invoked this turn.
        """
        child = self.child_results.get(profile_tag)
        return child.response if child else None

    def get_all_responses(self) -> Dict[str, str]:
        """Get all successful child responses as ``{tag: response_text}``."""
        return {
            tag: child.response
            for tag, child in self.child_results.items()
            if child.success
        }

    def get_children_by_type(self, profile_type: str) -> List[GenieChildResult]:
        """Filter child results by profile type (e.g., 'rag_focused')."""
        return [
            child for child in self.child_results.values()
            if child.profile_type == profile_type
        ]


# ---------------------------------------------------------------------------
# Extension context and result models
# ---------------------------------------------------------------------------

@dataclass
class ExtensionContext:
    """
    Rich context passed to every extension's execute() method.

    Contains the LLM answer, execution metadata, token counts,
    and chain context from prior extensions in serial execution.

    For genie profiles, the ``genie`` field provides structured access
    to the full coordination layer including individual child responses.
    """

    # --- Core answer data ---
    answer_text: str
    """Clean plain-text version of the LLM answer.
    For genie profiles, this is the coordinator's synthesized response."""

    answer_html: str
    """HTML-formatted version of the LLM answer."""

    original_query: str
    """User's original query text including #extension tags."""

    clean_query: str
    """Query with #extension tags stripped (what the LLM actually saw)."""

    # --- Session / turn identity ---
    session_id: str
    turn_id: int
    task_id: Optional[str] = None
    """REST API task ID. None for SSE-only (interactive) requests."""

    # --- Profile context ---
    profile_tag: Optional[str] = None
    profile_type: str = "tool_enabled"
    """One of: tool_enabled, llm_only, rag_focused, genie."""

    # --- LLM provider info ---
    provider: Optional[str] = None
    model: Optional[str] = None

    # --- Token / cost data ---
    turn_input_tokens: int = 0
    turn_output_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # --- Execution trace (tool_enabled profiles) ---
    execution_trace: list = field(default_factory=list)
    """Full execution trace from the executor (phases, tool calls, results).
    For genie profiles, contains genie coordination events."""

    tools_used: list = field(default_factory=list)
    """List of MCP tool names invoked during this turn."""

    collected_data: list = field(default_factory=list)
    """Structured collected data from tool execution results."""

    # --- Serial chaining context ---
    previous_extension_results: dict = field(default_factory=dict)
    """
    Results from prior extensions in the chain.
    Keyed by extension name → ExtensionResult.
    Populated automatically by ExtensionRunner during serial execution.
    """

    # --- LLM config (for LLMExtension, injected by runner) ---
    user_uuid: Optional[str] = None
    """User UUID for LLM credential resolution."""

    llm_config_id: Optional[str] = None
    """LLM configuration ID from the active profile."""

    # --- Genie coordination context ---
    genie: Optional[GenieContext] = None
    """Rich genie coordination context. None for non-genie profiles.

    When populated, provides scope-based content access::

        if context.genie:
            # Get all content nodes (children + coordinator)
            nodes = context.genie.get_content(scope="all")
            # Get a specific child's response
            rag_answer = context.genie.get_child_response("RAG")
    """


@dataclass
class ExtensionResult:
    """
    Standardized output returned by an extension.

    The `content` field is the primary output — typically a dict for JSON
    extensions (content_type="application/json") or a string for text.
    """

    extension_name: str
    """Name of the extension that produced this result."""

    content: Any
    """Primary output. Usually a dict (JSON) or str (text/HTML)."""

    content_type: str = "application/json"
    """MIME type of the content. Helps downstream consumers auto-detect parsing."""

    success: bool = True
    """Whether the extension executed successfully."""

    error: Optional[str] = None
    """Error message if success=False."""

    output_target: str = "silent"
    """Where to display the result in the UI (silent, chat_append, status_panel)."""

    metadata: dict = field(default_factory=dict)
    """Extension-specific metadata (timing, version, parameters used, etc.)."""

    # --- Cost KPI fields (optional, default 0 for deterministic extensions) ---
    extension_input_tokens: int = 0
    """Input tokens consumed by this extension (0 for non-LLM extensions)."""

    extension_output_tokens: int = 0
    """Output tokens consumed by this extension (0 for non-LLM extensions)."""

    extension_cost_usd: float = 0.0
    """Cost in USD for this extension's LLM usage (0 for non-LLM extensions)."""
