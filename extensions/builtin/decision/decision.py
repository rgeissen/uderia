"""
#decision extension — Binary/multi-branch decision output.

Analyzes the LLM answer using keyword heuristics to produce a structured
decision that downstream workflow tools can branch on.

Output includes a `branch_key` field designed for n8n Switch nodes.

Usage:
    #decision           → auto-detect severity from answer content
    #decision:critical  → force severity context to 'critical'
    #decision:binary    → simplified yes/no output
"""

from typing import Optional

from trusted_data_agent.extensions.base import Extension
from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)

# Keyword signal groups (ordered by specificity)
CRITICAL_SIGNALS = [
    "critical", "urgent", "immediate", "emergency", "exceeded",
    "failure", "failed", "down", "outage", "crash", "fatal",
    "overflow", "exhausted", "unreachable",
]
WARNING_SIGNALS = [
    "warning", "elevated", "approaching", "caution", "above normal",
    "degraded", "slow", "high", "spike", "anomaly", "increasing",
    "nearing", "threshold",
]
OK_SIGNALS = [
    "normal", "within limits", "healthy", "no issues", "all clear",
    "stable", "optimal", "good", "below threshold", "nominal",
]
ACTION_SIGNALS = [
    "recommend", "should", "suggest", "action required", "consider",
    "investigate", "review", "attention", "needed",
]


class DecisionExtension(Extension):

    @property
    def name(self) -> str:
        return "decision"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        answer_lower = context.answer_text.lower()

        # Count signal matches per category
        critical_count = sum(1 for s in CRITICAL_SIGNALS if s in answer_lower)
        warning_count = sum(1 for s in WARNING_SIGNALS if s in answer_lower)
        ok_count = sum(1 for s in OK_SIGNALS if s in answer_lower)
        action_count = sum(1 for s in ACTION_SIGNALS if s in answer_lower)

        # Determine result and severity
        if critical_count > 0:
            result = "threshold_exceeded"
            severity = "critical"
            confidence = min(0.6 + critical_count * 0.1, 0.98)
        elif warning_count > 0:
            result = "approaching_threshold"
            severity = "warning"
            confidence = min(0.5 + warning_count * 0.1, 0.90)
        elif ok_count > 0:
            result = "nominal"
            severity = "ok"
            confidence = min(0.5 + ok_count * 0.1, 0.95)
        else:
            result = "nominal"
            severity = "info"
            confidence = 0.5

        action_recommended = action_count > 0 or severity in ("critical", "warning")

        # Binary mode simplification
        if param == "binary":
            output = {
                "result": "yes" if severity in ("critical", "warning") else "no",
                "action_recommended": action_recommended,
                "branch_key": "yes" if action_recommended else "no",
                "reasoning": f"Analyzed {len(context.answer_text)} chars of LLM output",
            }
        else:
            output = {
                "result": result,
                "severity": severity,
                "confidence": round(confidence, 2),
                "action_recommended": action_recommended,
                "branch_key": f"{result}_{severity}",
                "signal_counts": {
                    "critical": critical_count,
                    "warning": warning_count,
                    "ok": ok_count,
                    "action": action_count,
                },
                "reasoning": f"Analyzed {len(context.answer_text)} chars of LLM output",
                "query": context.clean_query,
            }

        return ExtensionResult(
            extension_name="decision",
            content=output,
            content_type="application/json",
            metadata={"param": param, "mode": "binary" if param == "binary" else "multi-branch"},
        )
