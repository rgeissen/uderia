"""
Token estimation utilities for context window budget management.

Uses tiktoken (Rust-based BPE tokenizer) when available for accurate
token counts. Falls back to character-based heuristics if tiktoken
is not installed. Both approaches are fast enough for budget allocation.

Actual token counts come from provider responses — these estimates
are for pre-allocation budget planning.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("quart.app")

# --- tiktoken lazy loading ---
# Cached encoder instance (loaded once, reused across all calls).
_tiktoken_encoder = None
_tiktoken_available: Optional[bool] = None


def _get_tiktoken_encoder():
    """Lazy-load tiktoken encoder. Returns encoder or None."""
    global _tiktoken_encoder, _tiktoken_available
    if _tiktoken_available is False:
        return None
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    try:
        import tiktoken
        # cl100k_base is the most widely applicable encoding
        # (GPT-4, GPT-3.5, and a reasonable approximation for
        # Anthropic/Google models in budget planning contexts).
        _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        _tiktoken_available = True
        logger.info("Token estimator: using tiktoken (cl100k_base) for accurate estimation")
        return _tiktoken_encoder
    except Exception:
        _tiktoken_available = False
        logger.info("Token estimator: tiktoken not available, using character heuristic")
        return None


# Average characters per token across common LLM providers.
# Used as fallback when tiktoken is not available, and for
# tokens_to_chars conversion (inverse direction).
DEFAULT_CHARS_PER_TOKEN = 4.0

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

    Uses tiktoken when available for accurate BPE tokenization.
    Falls back to character-based heuristic otherwise.

    Args:
        text: The text to estimate tokens for.
        provider: Optional provider name (used for heuristic fallback).

    Returns:
        Estimated token count (always >= 0).
    """
    if not text:
        return 0

    encoder = _get_tiktoken_encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(text, disallowed_special=()))
        except Exception:
            pass  # Fall through to heuristic

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
    Always uses the heuristic (inverse tokenization is not meaningful).

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
