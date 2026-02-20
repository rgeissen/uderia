"""
Base class for all extensions.

Extensions must subclass Extension and implement the execute() method.
Each extension lives in its own directory with a manifest.json.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)


class Extension(ABC):
    """
    Abstract base class for post-processing extensions.

    Subclasses must define:
        name        — unique identifier matching the #name trigger syntax
        execute()   — async method that transforms the LLM answer

    Optional overrides:
        output_target  — where to display output in the UI (default: SILENT)
        validate_param — parameter validation (default: accepts anything)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique extension identifier. Lowercase, no spaces.
        Must match the #name syntax users type in queries.
        """

    @property
    def output_target(self) -> OutputTarget:
        """
        Where the extension output is displayed in the UI.
        Override in subclass to change from the default (SILENT / API-only).
        """
        return OutputTarget.SILENT

    @abstractmethod
    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:
        """
        Transform the LLM answer into structured output.

        Args:
            context: Rich context with answer text, metadata, tokens,
                     execution trace, and results from prior extensions
                     in the chain (context.previous_extension_results).
            param:   Optional parameter from #name:param syntax.
                     None if no colon was used.

        Returns:
            ExtensionResult with structured content.
        """

    def validate_param(self, param: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        Validate the parameter passed via #name:param syntax.

        Override in subclass to enforce specific parameter values.

        Returns:
            (is_valid, error_message) — error_message is None when valid.
        """
        return True, None
