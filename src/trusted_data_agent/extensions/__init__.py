"""
Extensions package — post-processing pipeline for LLM answers.

Extensions transform non-deterministic LLM output into structured,
machine-parseable formats for downstream workflow tools (n8n, Flowise, Airflow).

Triggered by #name:param syntax in user queries.
"""

from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)
from trusted_data_agent.extensions.base import Extension
from trusted_data_agent.extensions.manager import get_extension_manager
from trusted_data_agent.extensions.runner import ExtensionRunner

__all__ = [
    "Extension",
    "ExtensionContext",
    "ExtensionResult",
    "ExtensionRunner",
    "OutputTarget",
    "get_extension_manager",
]
