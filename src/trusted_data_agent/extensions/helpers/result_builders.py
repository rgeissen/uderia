"""
Convenience constructors for ExtensionResult.

Eliminates boilerplate when building results in extension code.
"""

from __future__ import annotations

from typing import Any

from trusted_data_agent.extensions.models import ExtensionResult


def json_result(name: str, content: Any, **metadata) -> ExtensionResult:
    """
    Build a successful JSON result.

    Args:
        name:     Extension name.
        content:  Dict or list to serialize as JSON.
        **metadata: Extra metadata key-value pairs.
    """
    return ExtensionResult(
        extension_name=name,
        content=content,
        content_type="application/json",
        success=True,
        metadata=metadata,
    )


def text_result(name: str, content: str, **metadata) -> ExtensionResult:
    """
    Build a successful plain-text result.

    Args:
        name:     Extension name.
        content:  Text string.
        **metadata: Extra metadata key-value pairs.
    """
    return ExtensionResult(
        extension_name=name,
        content=content,
        content_type="text/plain",
        success=True,
        metadata=metadata,
    )


def error_result(name: str, error_msg: str) -> ExtensionResult:
    """
    Build a failed result with an error message.

    Args:
        name:      Extension name.
        error_msg: Human-readable error description.
    """
    return ExtensionResult(
        extension_name=name,
        content=None,
        content_type="text/plain",
        success=False,
        error=error_msg,
    )
