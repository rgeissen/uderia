"""
Token estimation utilities for context window budget management.

Provides fast, approximate token counting for budget allocation decisions.
These are estimates — actual token counts come from provider responses.
The goal is to be within ~10% of actual counts for budget planning.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("quart.app")

# Average characters per token across common LLM providers.
# Most providers average 3.5-4.5 chars/token for English text.
# We use 4.0 as a balanced default.
DEFAULT_CHARS_PER_TOKEN = 4.0

# Provider-specific ratios (can be tuned based on observed accuracy).
PROVIDER_CHARS_PER_TOKEN = {
    "Google": 4.0,
    "Anthropic": 3.8,
    "OpenAI": 4.0,
    "Azure": 4.0,
    "Amazon": 3.8,   # Bedrock Anthropic models
    "Friendli": 4.0,
    "Ollama": 4.0,
}


def estimate_tokens(
    text: str,
    provider: Optional[str] = None,
) -> int:
    """
    Estimate token count for a text string.

    Uses a character-based heuristic that's fast enough for budget
    planning. Actual token counts come from provider responses.

    Args:
        text: The text to estimate tokens for.
        provider: Optional provider name for provider-specific ratios.

    Returns:
        Estimated token count (always >= 0).
    """
    if not text:
        return 0

    chars_per_token = PROVIDER_CHARS_PER_TOKEN.get(
        provider, DEFAULT_CHARS_PER_TOKEN
    )
    return max(1, int(len(text) / chars_per_token))


def tokens_to_chars(
    tokens: int,
    provider: Optional[str] = None,
) -> int:
    """
    Convert a token budget to an approximate character budget.

    Useful for modules that need to truncate text to fit a token budget.

    Args:
        tokens: Token budget.
        provider: Optional provider name.

    Returns:
        Approximate character budget.
    """
    if tokens <= 0:
        return 0

    chars_per_token = PROVIDER_CHARS_PER_TOKEN.get(
        provider, DEFAULT_CHARS_PER_TOKEN
    )
    return int(tokens * chars_per_token)


def estimate_tokens_for_messages(
    messages: list,
    provider: Optional[str] = None,
) -> int:
    """
    Estimate total tokens for a list of chat messages.

    Each message has overhead for role formatting (~4 tokens).

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
        provider: Optional provider name.

    Returns:
        Estimated total token count.
    """
    if not messages:
        return 0

    total = 0
    message_overhead = 4  # Tokens for role, formatting, separators

    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content, provider) + message_overhead
        elif isinstance(content, list):
            # Handle multi-part content (e.g., vision messages)
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += estimate_tokens(part["text"], provider)
            total += message_overhead

    return total
