"""
Base class for all extensions.

Three-tier hierarchy:
  - SimpleExtension: Zero-boilerplate for stateless, deterministic transforms (~15 lines)
  - Extension:       Full context access, maximum flexibility (existing pattern)
  - LLMExtension:    Calls the user's configured LLM with automatic cost tracking

Extensions must subclass one of these and implement the required method(s).
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)

logger = logging.getLogger("quart.app")


# ---------------------------------------------------------------------------
# Tier 2: Full-power base (existing, unchanged contract)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tier 1: Zero-boilerplate for stateless deterministic transforms
# ---------------------------------------------------------------------------

class SimpleExtension(Extension):
    """
    Zero-boilerplate base for stateless, deterministic transforms.

    Override:
        name            — unique #name trigger (property or class attribute)
        transform()     — receives answer_text + param, returns dict or str

    Optional overrides:
        allowed_params  — set of valid param values (None = any)
        content_type    — MIME type (default: application/json)
        description     — one-line for UI

    Example (~15 lines, complete custom extension):

        from trusted_data_agent.extensions import SimpleExtension

        class WordCountExtension(SimpleExtension):
            name = "wordcount"
            description = "Counts words, sentences, and characters"

            def transform(self, answer_text, param=None):
                words = answer_text.split()
                return {
                    "word_count": len(words),
                    "char_count": len(answer_text),
                }
    """

    allowed_params: Optional[set] = None
    """Set of valid param values. None = accept any parameter."""

    content_type: str = "application/json"
    """MIME type for the extension result."""

    description: str = ""
    """One-line description shown in the UI."""

    @abstractmethod
    def transform(self, answer_text: str, param: Optional[str] = None) -> Any:
        """
        The only method you must implement.

        Args:
            answer_text: Clean plain-text LLM answer.
            param:       Optional parameter from #name:param syntax.

        Returns:
            dict or str — will be wrapped into an ExtensionResult automatically.
        """

    # --- Pre-implemented: delegates to transform(), builds ExtensionResult ---

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:
        try:
            result = self.transform(context.answer_text, param)
            return ExtensionResult(
                extension_name=self.name,
                content=result,
                content_type=self.content_type,
                success=True,
                metadata={"param": param},
            )
        except Exception as e:
            return ExtensionResult(
                extension_name=self.name,
                content=None,
                content_type="text/plain",
                success=False,
                error=str(e),
                metadata={"param": param},
            )

    # --- Pre-implemented: validates against allowed_params ---

    def validate_param(self, param: Optional[str] = None) -> tuple[bool, Optional[str]]:
        if self.allowed_params is None:
            return True, None
        if param is None:
            return True, None  # No param is always fine
        if param in self.allowed_params:
            return True, None
        valid_list = ", ".join(sorted(self.allowed_params))
        return False, f"Invalid parameter '{param}'. Valid: {valid_list}"


# ---------------------------------------------------------------------------
# Tier 3: LLM-powered extensions with automatic cost tracking
# ---------------------------------------------------------------------------

class LLMExtension(Extension):
    """
    Base for extensions that call an LLM for semantic analysis.

    Provides:
        self.call_llm(prompt, system_prompt, temperature, json_mode)
        Automatic token counting and cost tracking

    The LLM config is injected by ExtensionRunner before execute().

    Example:

        from trusted_data_agent.extensions import LLMExtension

        class SentimentExtension(LLMExtension):
            name = "sentiment"
            description = "Analyzes sentiment using the session's LLM"

            async def execute(self, context, param=None):
                result = await self.call_llm(
                    prompt=f"Classify the sentiment: {context.answer_text}",
                    system_prompt="Return JSON: {sentiment, confidence}",
                    json_mode=True,
                )
                import json
                return ExtensionResult(
                    extension_name=self.name,
                    content=json.loads(result),
                    content_type="application/json",
                    success=True,
                )
    """

    # --- Injected by ExtensionRunner before execute() ---
    _llm_config_id: Optional[str] = None
    _user_uuid: Optional[str] = None
    _provider: Optional[str] = None
    _model: Optional[str] = None

    # --- Accumulated automatically across call_llm() invocations ---
    _total_input_tokens: int = 0
    _total_output_tokens: int = 0
    _total_cost_usd: float = 0.0

    description: str = ""
    """One-line description shown in the UI."""

    @property
    def requires_llm(self) -> bool:
        """Signals to ExtensionRunner that LLM config injection is needed."""
        return True

    async def call_llm(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        """
        Call the session's LLM. Tokens are accumulated automatically.

        Args:
            prompt:        User message to send to the LLM.
            system_prompt: System message (default: generic assistant).
            temperature:   Sampling temperature (default: 0.3 for structured output).
            json_mode:     If True, hint the LLM to return valid JSON.

        Returns:
            The LLM's text response.

        Raises:
            RuntimeError: If LLM config was not injected (no LLM configured).
        """
        if not self._llm_config_id or not self._user_uuid:
            raise RuntimeError(
                f"Extension '{self.name}' requires an LLM but no LLM configuration "
                "is available. Ensure the active profile has an LLM configuration."
            )

        from trusted_data_agent.llm.langchain_adapter import create_langchain_llm

        llm = create_langchain_llm(
            llm_config_id=self._llm_config_id,
            user_uuid=self._user_uuid,
            temperature=temperature,
        )

        # Build messages
        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [SystemMessage(content=system_prompt)]

        if json_mode:
            messages.append(HumanMessage(
                content=f"{prompt}\n\nRespond with valid JSON only, no markdown fences."
            ))
        else:
            messages.append(HumanMessage(content=prompt))

        # Invoke and extract response
        response = await llm.ainvoke(messages)
        response_text = response.content if hasattr(response, "content") else str(response)

        # Extract token usage from response metadata
        usage = getattr(response, "usage_metadata", None)
        if usage:
            input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else getattr(usage, "input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else getattr(usage, "output_tokens", 0)

            self._total_input_tokens += input_tokens
            self._total_output_tokens += output_tokens

            # Calculate cost
            if self._provider and self._model:
                try:
                    from trusted_data_agent.core.cost_manager import CostManager
                    cost_mgr = CostManager()
                    cost = cost_mgr.calculate_cost(
                        self._provider, self._model,
                        input_tokens, output_tokens,
                    )
                    self._total_cost_usd += cost
                except Exception as cost_err:
                    logger.warning(
                        f"Extension '{self.name}' cost calculation failed "
                        f"(provider={self._provider}, model={self._model}): {cost_err}"
                    )

            logger.debug(
                f"Extension '{self.name}' LLM call: "
                f"{input_tokens} in / {output_tokens} out "
                f"(accumulated: {self._total_input_tokens} in / {self._total_output_tokens} out)"
            )

        return response_text
