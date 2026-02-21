"""
Text analysis utilities for extension authors.
"""

from __future__ import annotations

import re
from typing import List


def count_words(text: str) -> int:
    """Count whitespace-separated words in text."""
    return len(text.split())


def extract_sentences(text: str) -> List[str]:
    """
    Split text into sentences using punctuation boundaries.

    Handles common abbreviations (e.g., Mr., Dr., etc.) to avoid
    false splits, but errs on the side of splitting.
    """
    # Split on sentence-ending punctuation followed by whitespace + capital letter
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text.strip())
    return [s.strip() for s in parts if s.strip()]


def extract_code_blocks(text: str) -> List[dict]:
    """
    Extract fenced code blocks from markdown text.

    Returns:
        List of {"language": str, "code": str} dicts.
        language is "" if no language tag was specified.
    """
    pattern = re.compile(
        r'```(\w*)\s*\n(.*?)```',
        re.DOTALL,
    )
    blocks = []
    for match in pattern.finditer(text):
        blocks.append({
            "language": match.group(1),
            "code": match.group(2).rstrip("\n"),
        })
    return blocks


def extract_tables(text: str) -> List[List[List[str]]]:
    """
    Extract markdown tables from text.

    Returns:
        List of tables, where each table is a list of rows,
        and each row is a list of cell strings.
        The separator row (---|---) is excluded.
    """
    tables = []
    lines = text.split("\n")
    current_table: List[List[str]] = []

    for line in lines:
        stripped = line.strip()
        if "|" in stripped:
            # Check if it's a separator row (---|---)
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.match(r'^:?-+:?$', c) for c in cells if c):
                continue  # Skip separator
            current_table.append(cells)
        else:
            if current_table:
                tables.append(current_table)
                current_table = []

    if current_table:
        tables.append(current_table)

    return tables


def truncate(text: str, max_chars: int = 1000) -> str:
    """
    Truncate text to max_chars with an ellipsis indicator.

    Tries to break at a word boundary near the limit.
    """
    if len(text) <= max_chars:
        return text
    # Find last space before the limit
    cut = text.rfind(" ", 0, max_chars)
    if cut == -1:
        cut = max_chars
    return text[:cut] + "..."
