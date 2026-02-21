"""
Extensions package — post-processing pipeline for LLM answers.

Extensions transform non-deterministic LLM output into structured,
machine-parseable formats for downstream workflow tools (n8n, Flowise, Airflow).

Triggered by #name:param syntax in user queries.

Three-tier hierarchy for extension authors:
  - SimpleExtension: ~15 lines, stateless transforms, no manifest needed
  - Extension:       Full context access, maximum flexibility
  - LLMExtension:    Calls the user's LLM with automatic cost tracking
"""

from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)
from trusted_data_agent.extensions.base import Extension, SimpleExtension, LLMExtension
from trusted_data_agent.extensions.manager import get_extension_manager
from trusted_data_agent.extensions.runner import ExtensionRunner

__all__ = [
    # Base classes (three tiers)
    "SimpleExtension",
    "Extension",
    "LLMExtension",
    # Models
    "ExtensionContext",
    "ExtensionResult",
    "OutputTarget",
    # Infrastructure
    "ExtensionRunner",
    "get_extension_manager",
]
