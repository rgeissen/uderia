"""
#summary extension — LLM-powered executive summary.

Produces a concise executive summary of the LLM answer with key points.
Output is displayed in the chat via CHAT_APPEND.

Tier: LLM (LLMExtension) — calls the session's configured LLM.

Usage:
    #summary           → brief summary (default)
    #summary:brief     → 2-3 sentence summary with key points
    #summary:detailed  → comprehensive summary with sections
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


BRIEF_SYSTEM_PROMPT = """You are an executive summary engine. Produce a concise summary of the provided content.

Return valid JSON with these fields:
- "summary": A 2-3 sentence executive summary
- "key_points": An array of 3-5 bullet-point key takeaways (short strings)
- "action_items": An array of any action items mentioned (empty array if none)

Respond with JSON only, no markdown fences or extra text."""

DETAILED_SYSTEM_PROMPT = """You are an executive summary engine. Produce a comprehensive summary of the provided content.

Return valid JSON with these fields:
- "summary": A detailed paragraph (4-6 sentences) summarizing the content
- "key_points": An array of 5-8 detailed key takeaways
- "sections": An object mapping section names to 1-2 sentence summaries of each major topic
- "action_items": An array of any action items or recommendations mentioned
- "data_highlights": An array of key numbers, metrics, or data points found

Respond with JSON only, no markdown fences or extra text."""


class SummaryExtension(LLMExtension):

    name = "summary"
    description = "Produces an executive summary of the LLM answer"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.CHAT_APPEND

    def validate_param(self, param: Optional[str] = None) -> tuple[bool, Optional[str]]:
        valid = {"brief", "detailed"}
        if param is not None and param not in valid:
            return False, f"Invalid param '{param}'. Allowed: {', '.join(sorted(valid))}"
        return True, None

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        is_detailed = param == "detailed"
        system = DETAILED_SYSTEM_PROMPT if is_detailed else BRIEF_SYSTEM_PROMPT

        prompt = (
            f"Summarize this response:\n\n"
            f"**Query:** {context.clean_query}\n\n"
            f"**Response:**\n{context.answer_text[:4000]}"
        )

        try:
            raw_response = await self.call_llm(
                prompt=prompt,
                system_prompt=system,
                temperature=0.2,
                json_mode=True,
            )

            parsed = extract_json_from_text(raw_response)
            if parsed is None:
                parsed = json.loads(raw_response)

            output = {
                "summary": parsed.get("summary", ""),
                "key_points": parsed.get("key_points", []),
                "action_items": parsed.get("action_items", []),
            }

            if is_detailed:
                output["sections"] = parsed.get("sections", {})
                output["data_highlights"] = parsed.get("data_highlights", [])

        except Exception as e:
            output = {
                "summary": f"Summary generation failed: {str(e)}",
                "key_points": [],
                "action_items": [],
            }

        return ExtensionResult(
            extension_name="summary",
            content=output,
            content_type="application/json",
            metadata={"param": param or "brief", "mode": "detailed" if is_detailed else "brief"},
        )
