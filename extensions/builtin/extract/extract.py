"""
#extract extension — Structured data extraction.

Pulls numbers, percentages, and entity names from the LLM answer
using deterministic regex patterns. No LLM call required.

Tier: Simple (SimpleExtension) — only needs answer_text.

Usage:
    #extract              → extract all data types
    #extract:numbers      → numbers only
    #extract:percentages  → percentages only
    #extract:entities     → entity names only
"""

from trusted_data_agent.extensions.base import SimpleExtension
from trusted_data_agent.extensions.helpers.regex import (
    NUMBER_WITH_UNIT,
    PERCENTAGE,
    IDENTIFIER,
    ENTITY_STOPWORDS,
)


class ExtractExtension(SimpleExtension):

    name = "extract"
    description = "Extracts numbers, percentages, and entity names from the LLM answer"
    allowed_params = {"numbers", "percentages", "entities"}

    def transform(self, answer_text, param=None):
        # --- Numbers ---
        numbers = []
        seen_values = set()
        for match in NUMBER_WITH_UNIT.finditer(answer_text):
            label = match.group(1).strip()
            raw_value = match.group(2).replace(",", "")
            unit = (match.group(3) or "").strip()
            try:
                value = float(raw_value)
            except ValueError:
                continue
            key = (label.lower(), value)
            if key not in seen_values:
                seen_values.add(key)
                numbers.append({"label": label, "value": value, "unit": unit})

        # --- Percentages ---
        percentages = []
        for match in PERCENTAGE.finditer(answer_text):
            try:
                percentages.append(float(match.group(1)))
            except ValueError:
                continue
        percentages = sorted(set(percentages))

        # --- Entities ---
        entities = sorted(set(
            m.group(1)
            for m in IDENTIFIER.finditer(answer_text)
            if m.group(1) not in ENTITY_STOPWORDS
        ))

        # Build output
        full_output = {
            "numbers": numbers,
            "percentages": percentages,
            "entities": entities,
            "source_length": len(answer_text),
        }

        # Apply filter if param specified
        if param and param in full_output:
            return {param: full_output[param]}
        return full_output
