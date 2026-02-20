"""
#extract extension — Structured data extraction.

Pulls numbers, percentages, and entity names from the LLM answer
using deterministic regex patterns. No LLM call required.

Usage:
    #extract              → extract all data types
    #extract:numbers      → numbers only
    #extract:percentages  → percentages only
    #extract:entities     → entity names only
"""

import re
from typing import Optional

from trusted_data_agent.extensions.base import Extension
from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)

VALID_FILTERS = {"numbers", "percentages", "entities"}

# Patterns for number extraction: "label: 94.5%" or "label = 1,234 rows"
NUMBER_PATTERN = re.compile(
    r"(?:^|[•\-\*]|\.\s+)"             # line start, bullet, or sentence boundary
    r"\s*([A-Za-z][\w\s/]*?)"          # label (starts with letter)
    r"[\s:=–\-]+?"                      # separator (colon, equals, dash)
    r"(\d{1,3}(?:[,]\d{3})*(?:\.\d+)?)"  # number (with optional commas/decimals)
    r"\s*"
    r"(%|GB|MB|TB|KB|PB|ms|μs|ns|seconds?|minutes?|hours?|days?|rows?|items?|records?|bytes?|connections?|queries|requests?|users?|sessions?|threads?|cores?|nodes?)?"
    r"(?:\s|$|[,.\)])",
    re.MULTILINE | re.IGNORECASE,
)

PERCENTAGE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Entities: UPPER_CASE identifiers (database names, table names, server names)
ENTITY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_]{2,}(?:\.[A-Za-z_]\w*)?)\b")


class ExtractExtension(Extension):

    @property
    def name(self) -> str:
        return "extract"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT

    def validate_param(self, param: Optional[str] = None) -> tuple[bool, Optional[str]]:
        if param is not None and param not in VALID_FILTERS:
            return False, f"Invalid filter '{param}'. Allowed: {', '.join(sorted(VALID_FILTERS))}"
        return True, None

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        text = context.answer_text

        # --- Numbers ---
        numbers = []
        seen_values = set()
        for match in NUMBER_PATTERN.finditer(text):
            label = match.group(1).strip()
            raw_value = match.group(2).replace(",", "")
            unit = (match.group(3) or "").strip()
            try:
                value = float(raw_value)
            except ValueError:
                continue
            # Deduplicate by (label, value)
            key = (label.lower(), value)
            if key not in seen_values:
                seen_values.add(key)
                numbers.append({"label": label, "value": value, "unit": unit})

        # --- Percentages ---
        percentages = []
        for match in PERCENTAGE_PATTERN.finditer(text):
            try:
                percentages.append(float(match.group(1)))
            except ValueError:
                continue
        percentages = sorted(set(percentages))

        # --- Entities ---
        # Filter out common English words that happen to be uppercase
        STOPWORDS = {
            "THE", "AND", "FOR", "NOT", "ARE", "BUT", "ALL", "ANY",
            "CAN", "HAS", "HER", "WAS", "ONE", "OUR", "OUT", "SQL",
            "CPU", "RAM", "GPU", "SSD", "HDD", "API", "URL", "HTML",
            "CSS", "PDF", "CSV", "JSON", "XML", "HTTP", "HTTPS",
            "LLM", "RAG", "MCP", "SSE", "JWT", "TDA",
        }
        entities = sorted(set(
            m.group(1)
            for m in ENTITY_PATTERN.finditer(text)
            if m.group(1) not in STOPWORDS
        ))

        # Build output
        full_output = {
            "numbers": numbers,
            "percentages": percentages,
            "entities": entities,
            "source_length": len(text),
        }

        # Apply filter if param specified
        if param and param in full_output:
            output = {param: full_output[param]}
        else:
            output = full_output

        return ExtensionResult(
            extension_name="extract",
            content=output,
            content_type="application/json",
            metadata={
                "param": param,
                "counts": {
                    "numbers": len(numbers),
                    "percentages": len(percentages),
                    "entities": len(entities),
                },
            },
        )
