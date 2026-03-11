"""
!boolean_check extension — LLM-powered boolean evaluation.

Semantically evaluates whether the LLM answer affirms or denies
the user's query, producing a deterministic True/False/Not Applicable
output for automation pipelines (n8n, Airflow, Flowise).

Tier: LLM (LLMExtension) — calls the session's configured LLM.

Usage:
    !boolean_check          → JSON: {result, confidence, reasoning}
    !boolean_check:strict   → bare string: "True", "False", or "Not Applicable"
    !boolean_check:json     → same as default (explicit JSON mode)
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


VALID_RESULTS = {"True", "False", "Not Applicable"}

SYSTEM_PROMPT = """\
You are a boolean evaluation engine. Your job is to determine whether \
the provided LLM answer, in the context of the original user query, \
evaluates to True, False, or Not Applicable.

Rules:
- "True" means the answer clearly affirms, confirms, or provides \
evidence that the queried condition holds.
- "False" means the answer clearly denies, refutes, or provides \
evidence that the queried condition does NOT hold.
- "Not Applicable" means the answer is ambiguous, inconclusive, does \
not address the question directly, or the question cannot be reduced \
to a boolean evaluation.

You MUST return valid JSON with exactly these fields:
- "result": Exactly one of "True", "False", or "Not Applicable" \
(case-sensitive, use these exact strings)
- "confidence": A number between 0.0 and 1.0 indicating how confident \
you are in the evaluation
- "reasoning": A brief one-line explanation (max 100 words)

Respond with JSON only, no markdown fences or extra text."""


def _normalize_result(raw: str) -> str:
    """Normalize an LLM result string to one of the three valid values.

    Handles common LLM quirks: lowercase, extra whitespace, missing
    capitalization, abbreviations, synonyms, etc.
    """
    cleaned = raw.strip().strip('"').strip("'")
    lower = cleaned.lower()

    if lower in ("true", "yes", "correct", "confirmed", "affirmative"):
        return "True"
    if lower in ("false", "no", "incorrect", "denied", "negative"):
        return "False"
    if lower in (
        "not applicable", "n/a", "na", "none", "inconclusive",
        "unknown", "unclear", "ambiguous", "not_applicable",
    ):
        return "Not Applicable"

    # Prefix matching as last resort
    if lower.startswith("true") or lower.startswith("yes"):
        return "True"
    if lower.startswith("false") or lower.startswith("no"):
        return "False"

    return "Not Applicable"


class BooleanCheckExtension(LLMExtension):

    name = "boolean_check"
    description = (
        "Evaluates LLM answer as True, False, or Not Applicable "
        "for automation branching"
    )

    ALLOWED_PARAMS = {"strict", "json"}

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT

    def validate_param(
        self, param: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        if param is None:
            return True, None
        if param in self.ALLOWED_PARAMS:
            return True, None
        valid_list = ", ".join(sorted(self.ALLOWED_PARAMS))
        return False, f"Invalid parameter '{param}'. Valid: {valid_list}"

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        is_strict = param == "strict"

        prompt = (
            f"Evaluate whether this LLM answer affirms or denies "
            f"the user's query:\n\n"
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

            # Parse JSON response
            parsed = extract_json_from_text(raw_response)
            if parsed is None:
                parsed = json.loads(raw_response)

            # Extract and normalize fields
            raw_result = parsed.get("result", "Not Applicable")
            result = _normalize_result(str(raw_result))
            confidence = parsed.get("confidence", 0.8)
            reasoning = parsed.get("reasoning", "")

            # Clamp confidence to valid range
            try:
                confidence = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                confidence = 0.8

        except Exception as e:
            result = "Not Applicable"
            confidence = 0.0
            reasoning = f"Analysis failed: {str(e)}"

        # Strict mode: bare string for maximum parsability
        if is_strict:
            return ExtensionResult(
                extension_name="boolean_check",
                content=result,
                content_type="text/plain",
                metadata={
                    "param": param,
                    "mode": "strict",
                    "confidence": confidence,
                },
            )

        # Default / :json mode: full structured output
        output = {
            "result": result,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        return ExtensionResult(
            extension_name="boolean_check",
            content=output,
            content_type="application/json",
            metadata={"param": param, "mode": "json"},
        )
