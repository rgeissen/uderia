"""
#decision extension — LLM-powered semantic decision output.

Uses the session's LLM to semantically analyze the answer and produce a structured
decision that downstream workflow tools can branch on.

Output includes a `branch_key` field designed for n8n Switch nodes.
Compatible with the same JSON shape as previous keyword-based version.

Tier: LLM (LLMExtension) — calls the session's configured LLM.

Usage:
    #decision           → auto-detect severity from answer content
    #decision:critical  → focus analysis on critical severity
    #decision:binary    → simplified yes/no output
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


SYSTEM_PROMPT = """You are a decision analysis engine. Analyze the provided text and return a structured JSON decision.

You MUST return valid JSON with exactly these fields:
- "result": One of "threshold_exceeded", "approaching_threshold", "action_required", "nominal"
- "severity": One of "critical", "warning", "info", "ok"
- "confidence": A number between 0.0 and 1.0 indicating your confidence
- "action_recommended": boolean - whether action should be taken
- "branch_key": A string combining result and severity as "result_severity" (e.g., "threshold_exceeded_critical")
- "reasoning": A brief (1-2 sentence) explanation of your decision

Respond with JSON only, no markdown fences or extra text."""

BINARY_SYSTEM_PROMPT = """You are a decision analysis engine. Analyze the provided text and return a binary yes/no decision.

You MUST return valid JSON with exactly these fields:
- "result": "yes" if action is needed or issues exist, "no" if everything is fine
- "action_recommended": boolean
- "branch_key": "yes" or "no"
- "reasoning": A brief (1-2 sentence) explanation

Respond with JSON only, no markdown fences or extra text."""


class DecisionExtension(LLMExtension):

    name = "decision"
    description = "LLM-powered semantic decision analysis for workflow branching"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        is_binary = param == "binary"

        # Build the analysis prompt
        severity_hint = ""
        if param and param != "binary":
            severity_hint = f"\nFocus your analysis on '{param}'-level concerns."

        prompt = (
            f"Analyze this LLM response and produce a decision:\n\n"
            f"**Original query:** {context.clean_query}\n\n"
            f"**LLM answer:**\n{context.answer_text[:3000]}"
            f"{severity_hint}"
        )

        system = BINARY_SYSTEM_PROMPT if is_binary else SYSTEM_PROMPT

        try:
            raw_response = await self.call_llm(
                prompt=prompt,
                system_prompt=system,
                temperature=0.1,
                json_mode=True,
            )

            parsed = extract_json_from_text(raw_response)
            if parsed is None:
                parsed = json.loads(raw_response)

            # Ensure required fields exist with defaults
            if is_binary:
                output = {
                    "result": parsed.get("result", "no"),
                    "action_recommended": parsed.get("action_recommended", False),
                    "branch_key": parsed.get("branch_key", parsed.get("result", "no")),
                    "reasoning": parsed.get("reasoning", ""),
                }
            else:
                result = parsed.get("result", "nominal")
                severity = parsed.get("severity", "info")
                output = {
                    "result": result,
                    "severity": severity,
                    "confidence": parsed.get("confidence", 0.8),
                    "action_recommended": parsed.get("action_recommended", False),
                    "branch_key": parsed.get("branch_key", f"{result}_{severity}"),
                    "reasoning": parsed.get("reasoning", ""),
                    "query": context.clean_query,
                }

        except Exception as e:
            # Graceful degradation: return a safe default
            output = {
                "result": "nominal",
                "severity": "info",
                "confidence": 0.0,
                "action_recommended": False,
                "branch_key": "nominal_info",
                "reasoning": f"LLM analysis failed: {str(e)}",
                "query": context.clean_query,
            }

        return ExtensionResult(
            extension_name="decision",
            content=output,
            content_type="application/json",
            metadata={"param": param, "mode": "binary" if is_binary else "multi-branch"},
        )
