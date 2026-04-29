# trusted_data_agent/agent/json_utils.py
import json
import re
import logging
from typing import Union, Optional

app_logger = logging.getLogger("quart.app")


def robust_json_parse(response_str: str) -> Optional[Union[dict, list]]:
    """
    Robustly extracts and parses JSON from an LLM response string.

    Three-tier approach:
      1. Direct json.loads after content extraction  — zero-overhead fast path.
      2. json_repair for common LLM artifacts: trailing commas, truncated output,
         single-quoted strings, Python None/True/False literals, surrounding prose.
      3. Returns None — caller should inject the parse error into the next LLM
         prompt and retry (see _generate_meta_plan / _get_next_tactical_action).

    Works identically across all supported providers (Ollama, OpenRouter, Gemini,
    Anthropic, Azure, Bedrock, FriendliAI) — no provider API capabilities required.
    """
    if not response_str or not isinstance(response_str, str):
        return None

    for candidate in _extract_json_candidates(response_str):
        # Fast path: direct parse (no overhead for well-formed JSON)
        try:
            result = json.loads(candidate)
            if isinstance(result, (dict, list)):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        # Repair path: handle common LLM formatting artifacts
        try:
            from json_repair import repair_json  # noqa: PLC0415
            result = repair_json(candidate, return_objects=True)
            if isinstance(result, (dict, list)) and result:
                return result
        except Exception as exc:
            app_logger.debug("json_repair failed on candidate: %s", exc)

    return None


def _extract_json_candidates(response_str: str) -> list:
    """
    Returns candidate substrings to try parsing, in descending priority order.
    Candidates are deduplicated while preserving insertion order.
    """
    seen: set = set()
    candidates: list = []

    def _add(s: str) -> None:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            candidates.append(s)

    # 1. Markdown fenced code block — most explicit LLM intent signal
    code_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", response_str)
    if code_match:
        _add(code_match.group(1))

    # 2. Outermost JSON array (only when the array is closed — complete JSON)
    arr_match = re.search(r"(\[[\s\S]*\])", response_str)
    if arr_match:
        _add(arr_match.group(1))

    # 3. Full response before trying partial object extraction — allows json_repair
    #    to recover truncated arrays that have no closing bracket yet.
    _add(response_str)

    # 4. Outermost JSON object — fallback when response is dict-shaped
    obj_match = re.search(r"(\{[\s\S]*\})", response_str)
    if obj_match:
        _add(obj_match.group(1))

    return candidates
