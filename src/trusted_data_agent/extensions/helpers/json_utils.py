"""
JSON extraction and serialization utilities for extension authors.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Union


def extract_json_from_text(text: str) -> Optional[Union[dict, list]]:
    """
    Find and parse the first JSON object or array in text.

    Handles:
    - Bare JSON
    - JSON inside markdown code fences (```json ... ```)
    - JSON preceded by explanatory text
    - Nested brackets

    Returns:
        Parsed dict/list, or None if no valid JSON found.
    """
    # 1. Try markdown code fence first
    fence_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 2. Find first { or [ and try to parse from there
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        idx = text.find(start_char)
        if idx == -1:
            continue
        # Walk forward counting brackets to find the matching close
        depth = 0
        in_string = False
        escape = False
        for i in range(idx, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_string:
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == start_char:
                depth += 1
            elif c == end_char:
                depth -= 1
                if depth == 0:
                    candidate = text[idx:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
        # If we didn't find a match, try next bracket type

    # 3. Last resort: try parsing the entire text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def safe_json_dumps(obj: Any, indent: int = 2) -> str:
    """
    json.dumps with default=str and ensure_ascii=False.

    Safely serializes objects containing datetime, UUID, Decimal, etc.
    """
    return json.dumps(obj, indent=indent, default=str, ensure_ascii=False)
