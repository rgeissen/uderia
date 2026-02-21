"""
#json extension — Structured JSON output.

Wraps the LLM answer and execution metadata into a standardized JSON
structure that downstream tools (n8n, Flowise, Airflow) can parse reliably.

Tier: Standard (Extension) — needs full ExtensionContext for metadata.

Usage:
    #json           → standard output (query, answer, metadata, tokens, tools)
    #json:minimal   → query + answer only
    #json:full      → includes execution trace and collected data
"""

from datetime import datetime, timezone
from typing import Optional

from trusted_data_agent.extensions.base import Extension
from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)
from trusted_data_agent.extensions.helpers import json_result

VALID_PARAMS = {"minimal", "full"}


class JsonExtension(Extension):

    @property
    def name(self) -> str:
        return "json"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.CHAT_APPEND

    def validate_param(self, param: Optional[str] = None) -> tuple[bool, Optional[str]]:
        if param is not None and param not in VALID_PARAMS:
            return False, f"Invalid param '{param}'. Allowed: {', '.join(sorted(VALID_PARAMS))}"
        return True, None

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        if param == "minimal":
            output = {
                "query": context.clean_query,
                "answer": context.answer_text,
            }
        else:
            output = {
                "query": context.clean_query,
                "answer": context.answer_text,
                "session_id": context.session_id,
                "turn_id": context.turn_id,
                "profile_tag": context.profile_tag,
                "profile_type": context.profile_type,
                "provider": context.provider,
                "model": context.model,
                "tokens": {
                    "input": context.turn_input_tokens,
                    "output": context.turn_output_tokens,
                    "total_input": context.total_input_tokens,
                    "total_output": context.total_output_tokens,
                },
                "tools_used": context.tools_used,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if param == "full":
                output["execution_trace"] = context.execution_trace
                output["collected_data"] = context.collected_data

        return json_result("json", output, param=param or "standard")
