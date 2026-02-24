"""
Canvas Component Handler.

Processes TDA_Canvas tool calls into interactive canvas render specifications.
Pure pass-through handler — no LLM calls, no data transformation. The handler
validates the language, computes metadata (line count, previewable flag), and
returns a ComponentRenderPayload that the frontend's CanvasCore renders with
CodeMirror 6 + capability plugins.
"""

import logging
from typing import Any, Dict, Tuple

from trusted_data_agent.components.base import (
    BaseComponentHandler,
    ComponentRenderPayload,
    RenderTarget,
)

logger = logging.getLogger("quart.app")


class CanvasComponentHandler(BaseComponentHandler):
    """Handler for the TDA_Canvas tool — interactive code/document workspace."""

    SUPPORTED_LANGUAGES = {
        "html", "css", "javascript", "python", "sql",
        "markdown", "json", "svg", "mermaid",
    }

    EXTENSION_MAP = {
        "html": ".html",
        "css": ".css",
        "javascript": ".js",
        "python": ".py",
        "sql": ".sql",
        "markdown": ".md",
        "json": ".json",
        "svg": ".svg",
        "mermaid": ".mmd",
    }

    @property
    def component_id(self) -> str:
        return "canvas"

    @property
    def tool_name(self) -> str:
        return "TDA_Canvas"

    @property
    def is_deterministic(self) -> bool:
        return True

    def validate_arguments(self, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        content = arguments.get("content")
        if not content or not isinstance(content, str) or not content.strip():
            return False, "The 'content' argument is required and must be a non-empty string."
        return True, ""

    async def process(
        self,
        arguments: Dict[str, Any],
        context: Dict[str, Any] = None,
    ) -> ComponentRenderPayload:
        content = arguments.get("content", "")
        language = (arguments.get("language") or "").lower().strip()
        title = arguments.get("title", "Canvas")
        sources = arguments.get("sources", "")

        # Normalize / auto-detect language
        if language not in self.SUPPORTED_LANGUAGES:
            language = self._detect_language(content) or "html"

        previewable = language in {"html", "svg", "markdown"}
        line_count = content.count("\n") + 1

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.INLINE,
            spec={
                "content": content,
                "language": language,
                "title": title,
                "previewable": previewable,
                "line_count": line_count,
                "file_extension": self.EXTENSION_MAP.get(language, ".txt"),
                "sources": sources if sources else None,
            },
            title=title,
            metadata={
                "tool_name": self.tool_name,
                "language": language,
                "content_length": len(content),
                "line_count": line_count,
            },
        )

    @staticmethod
    def _detect_language(content: str) -> str | None:
        """Heuristic language detection fallback."""
        c = content.strip()
        if not c:
            return None
        if c.startswith("<!DOCTYPE") or c.startswith("<html") or "<head" in c[:200]:
            return "html"
        if c.startswith("<svg"):
            return "svg"
        if c.startswith("graph ") or c.startswith("sequenceDiagram"):
            return "mermaid"
        if "def " in c[:500] or "import " in c[:200]:
            return "python"
        if any(kw in c.upper()[:300] for kw in ["SELECT ", "CREATE TABLE", "INSERT INTO"]):
            return "sql"
        if c.startswith("{") and c.endswith("}"):
            return "json"
        if c.startswith("# ") or "\n## " in c:
            return "markdown"
        return None
