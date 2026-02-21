"""
#classify extension — LLM-powered answer categorization.

Uses the session's LLM to semantically classify the answer into
topic categories. Produces a primary category with confidence score,
suitable for n8n Switch node routing.

Compatible categories:
    alert, performance, data_quality, capacity, security, data_report, informational

Tier: LLM (LLMExtension) — calls the session's configured LLM.

Usage:
    #classify   → categorize the answer
"""

import json
from typing import Optional

from trusted_data_agent.extensions.base import LLMExtension
from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)
from trusted_data_agent.extensions.helpers import extract_json_from_text

VALID_CATEGORIES = [
    "alert", "performance", "data_quality", "capacity",
    "security", "data_report", "informational",
]

SYSTEM_PROMPT = f"""You are a content classification engine. Classify the provided text into exactly one primary category.

Valid categories:
- "alert": Critical issues, failures, outages, errors
- "performance": CPU, memory, throughput, latency, response time metrics
- "data_quality": Missing data, nulls, duplicates, validation issues
- "capacity": Storage, growth, forecasting, quotas
- "security": Access control, permissions, audit, compliance
- "data_report": Query results, tables, records, summaries, counts
- "informational": General information that doesn't fit other categories

You MUST return valid JSON with exactly these fields:
- "primary_category": One of the valid categories above
- "confidence": A number between 0.0 and 1.0
- "all_categories": An object mapping each relevant category to a relevance score (0-10)
- "branch_key": Same as primary_category (for n8n Switch node routing)
- "reasoning": A brief (1 sentence) explanation of why this category was chosen

Respond with JSON only, no markdown fences or extra text."""


class ClassifyExtension(LLMExtension):

    name = "classify"
    description = "LLM-powered semantic classification into topic categories"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        prompt = (
            f"Classify this LLM response:\n\n"
            f"**Original query:** {context.clean_query}\n\n"
            f"**LLM answer:**\n{context.answer_text[:3000]}"
        )

        try:
            raw_response = await self.call_llm(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                temperature=0.1,
                json_mode=True,
            )

            parsed = extract_json_from_text(raw_response)
            if parsed is None:
                parsed = json.loads(raw_response)

            primary = parsed.get("primary_category", "informational")
            # Validate category
            if primary not in VALID_CATEGORIES:
                primary = "informational"

            output = {
                "primary_category": primary,
                "confidence": parsed.get("confidence", 0.8),
                "all_categories": parsed.get("all_categories", {primary: 10}),
                "branch_key": primary,
                "query": context.clean_query,
            }

        except Exception as e:
            output = {
                "primary_category": "informational",
                "confidence": 0.0,
                "all_categories": {},
                "branch_key": "informational",
                "query": context.clean_query,
                "error": f"LLM classification failed: {str(e)}",
            }

        return ExtensionResult(
            extension_name="classify",
            content=output,
            content_type="application/json",
            metadata={"categories_matched": len(output.get("all_categories", {}))},
        )
