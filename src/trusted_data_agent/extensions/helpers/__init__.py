"""
Extension helpers — shared utilities for extension authors.

Import commonly-used helpers directly:

    from trusted_data_agent.extensions.helpers import (
        extract_json_from_text,
        safe_json_dumps,
        count_words,
        extract_code_blocks,
        truncate,
        json_result,
        text_result,
        error_result,
    )
"""

from trusted_data_agent.extensions.helpers.json_utils import (
    extract_json_from_text,
    safe_json_dumps,
)
from trusted_data_agent.extensions.helpers.text import (
    count_words,
    extract_sentences,
    extract_code_blocks,
    extract_tables,
    truncate,
)
from trusted_data_agent.extensions.helpers.result_builders import (
    json_result,
    text_result,
    error_result,
)

__all__ = [
    # JSON utilities
    "extract_json_from_text",
    "safe_json_dumps",
    # Text utilities
    "count_words",
    "extract_sentences",
    "extract_code_blocks",
    "extract_tables",
    "truncate",
    # Result builders
    "json_result",
    "text_result",
    "error_result",
]
