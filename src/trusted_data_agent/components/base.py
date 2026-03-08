"""
Base classes for Generative UI Components.

Three-tier hierarchy:
  - BaseComponentHandler:  Full component handler with tool processing
  - StructuralHandler:     Simpler handler for data-driven rendering (no tool call)
  - SystemHandler:         Infrastructure handler for platform-level concerns (no tool, no UI)

Component handlers process LLM tool-call arguments into ComponentRenderPayload
objects that the frontend's ComponentRendererRegistry knows how to render.
System handlers manage platform resources (context window, etc.) and produce
metrics for observability rather than rendered output.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("quart.app")


# ---------------------------------------------------------------------------
# Render targets
# ---------------------------------------------------------------------------

class RenderTarget(Enum):
    """Where the component output is displayed on the conversation canvas."""
    INLINE = "inline"              # Inside the chat message bubble
    SUB_WINDOW = "sub_window"      # Persistent, resizable panel on the canvas
    STATUS_PANEL = "status_panel"  # In the Live Status panel


# ---------------------------------------------------------------------------
# Component render payload
# ---------------------------------------------------------------------------

@dataclass
class ComponentRenderPayload:
    """
    Standardized output from a component handler.

    This is the contract between backend handlers and frontend renderers.
    The formatter embeds this as a data-component div in the final_answer HTML,
    or emits it as a component_render SSE event for sub-window components.
    """

    component_id: str
    """Which component produced this payload (e.g., 'chart', 'code_editor')."""

    render_target: RenderTarget = RenderTarget.INLINE
    """Where to render: inline (chat), sub_window (panel), or status_panel."""

    spec: Dict[str, Any] = field(default_factory=dict)
    """
    JSON-serializable spec for client-side rendering.
    For charts: G2Plot spec. For code_editor: {language, content}. etc.
    """

    html: str = ""
    """
    Pre-rendered HTML for inline components (table, key_metric).
    When non-empty, the frontend inserts this directly instead of using spec.
    """

    container_id: str = ""
    """Unique DOM ID for the render target div. Auto-generated if empty."""

    title: str = ""
    """Display title (used for sub-window title bar, chart caption, etc.)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Component-specific metadata (tool_name, chart_type, language, etc.)."""

    tts_text: str = ""
    """Plain text for TTS narration. Empty if not applicable."""

    # --- Sub-window specific ---
    window_id: str = ""
    """
    Sub-window identifier. For 'update' actions, references an existing window.
    For 'create' actions, auto-generated if empty.
    """

    window_action: str = "create"
    """Sub-window action: 'create', 'update', or 'close'."""

    interactive: bool = False
    """Whether the sub-window supports bidirectional editing."""

    def __post_init__(self):
        if not self.container_id:
            self.container_id = f"component-{uuid.uuid4().hex[:12]}"
        if self.render_target == RenderTarget.SUB_WINDOW and not self.window_id:
            self.window_id = f"sw-{uuid.uuid4().hex[:12]}"

    def to_collected_data(self) -> Dict[str, Any]:
        """Convert to the collected_data format used by the formatter."""
        return {
            "type": self.component_id,
            "component_id": self.component_id,
            "render_target": self.render_target.value,
            "spec": self.spec,
            "html": self.html,
            "container_id": self.container_id,
            "title": self.title,
            "metadata": self.metadata,
            "window_id": self.window_id,
            "window_action": self.window_action,
            "interactive": self.interactive,
        }

    def to_sse_event(self) -> Dict[str, Any]:
        """Convert to SSE event payload for component_render events."""
        return {
            "component_id": self.component_id,
            "render_target": self.render_target.value,
            "container_id": self.container_id,
            "spec": self.spec,
            "title": self.title,
            "window_id": self.window_id,
            "window_action": self.window_action,
            "interactive": self.interactive,
        }


# ---------------------------------------------------------------------------
# Base component handler
# ---------------------------------------------------------------------------

class BaseComponentHandler(ABC):
    """
    Base class for all component backend handlers.

    Subclasses must implement:
        component_id  — unique identifier matching the manifest
        tool_name     — the TDA_* tool name the LLM calls
        process()     — transforms tool arguments into a render payload

    Optional overrides:
        is_deterministic  — if True, skip tactical LLM (fast-path). Default True.
        validate_arguments — argument validation before processing
    """

    @property
    @abstractmethod
    def component_id(self) -> str:
        """Unique component identifier (e.g., 'chart', 'code_editor')."""

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """The TDA_* tool name this handler processes (e.g., 'TDA_Charting')."""

    @property
    def is_deterministic(self) -> bool:
        """
        If True, the executor bypasses tactical LLM and calls this handler
        directly (fast-path). Most components are deterministic.
        """
        return True

    @abstractmethod
    async def process(
        self,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ComponentRenderPayload:
        """
        Process tool-call arguments into a renderable payload.

        Args:
            arguments: Tool call arguments from the LLM (e.g., chart_type, data, mapping)
            context: Execution context dict with keys:
                - session_id, user_uuid, profile_config
                - workflow_state (previous phase results)
                - session_data (charting_intensity, etc.)

        Returns:
            ComponentRenderPayload for frontend rendering.
        """

    def validate_arguments(
        self,
        arguments: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Validate tool arguments before processing.

        Override in subclass to enforce required arguments.

        Returns:
            (is_valid, error_message) — error_message is empty when valid.
        """
        return True, ""

    async def get_context_enrichment(
        self,
        query: str,
        profile_id: str,
        user_uuid: str,
    ) -> str:
        """
        Optional: Return context text for planner prompt injection.

        Components that provide domain knowledge (e.g., knowledge graph)
        override this to inject structured context before strategic planning.
        The returned text is appended to the knowledge_context_str in the
        planner, flowing through the existing {knowledge_context} placeholder.

        Args:
            query: The user's original input query.
            profile_id: Active profile ID.
            user_uuid: Current user UUID.

        Returns:
            Context text for prompt injection, or empty string if none.
        """
        return ""


# ---------------------------------------------------------------------------
# Structural handler (no tool call, data-driven)
# ---------------------------------------------------------------------------

class StructuralHandler(BaseComponentHandler):
    """
    Simplified handler for structural components (table, code_block, key_metric).

    Structural components don't have tool calls — they render automatically
    based on data types in collected_data. The tool_name property returns
    an empty string, and is_deterministic is always True.
    """

    @property
    def tool_name(self) -> str:
        return ""

    @property
    def is_deterministic(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# System handler (infrastructure, no tool call, no UI rendering)
# ---------------------------------------------------------------------------

class SystemHandler(ABC):
    """
    Base class for system components that manage platform infrastructure.

    System components differ fundamentally from action/structural components:
      - No tool definition (the LLM doesn't call them)
      - No LLM instructions injection (they manage LLM input, not guide it)
      - Render target: status_panel only (metrics and observability)
      - Different lifecycle: orchestrate resources rather than process tool calls

    The Context Window Manager is the reference implementation — it orchestrates
    context budget allocation across pluggable context modules.

    Subclasses must implement:
        component_id  — unique identifier matching the manifest
        get_metrics() — return current metrics for observability
    """

    @property
    @abstractmethod
    def component_id(self) -> str:
        """Unique component identifier (e.g., 'context_window')."""

    @property
    def component_type(self) -> str:
        """System components are always type 'system'."""
        return "system"

    @property
    def tool_name(self) -> str:
        """System components don't expose tools to the LLM."""
        return ""

    @property
    def is_deterministic(self) -> bool:
        """System components are infrastructure — always deterministic."""
        return True

    @abstractmethod
    async def get_metrics(self) -> Dict[str, Any]:
        """
        Return current metrics for observability.

        Returns a dict suitable for SSE event emission and Live Status
        panel rendering. The structure is component-specific.
        """
