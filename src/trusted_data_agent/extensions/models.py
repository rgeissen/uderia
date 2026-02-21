"""
Data models for the Extensions system.

ExtensionContext carries the rich context passed to every extension.
ExtensionResult is the standardized output returned by extensions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class OutputTarget(Enum):
    """Where the extension output is displayed in the UI."""
    SILENT = "silent"              # API-only, no UI display (default for automation)
    CHAT_APPEND = "chat_append"    # Appended below the LLM answer in chat log
    STATUS_PANEL = "status_panel"  # Rendered in the Live Status panel


@dataclass
class ExtensionContext:
    """
    Rich context passed to every extension's execute() method.

    Contains the LLM answer, execution metadata, token counts,
    and chain context from prior extensions in serial execution.
    """

    # --- Core answer data ---
    answer_text: str
    """Clean plain-text version of the LLM answer."""

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
    """Full execution trace from the executor (phases, tool calls, results)."""

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
