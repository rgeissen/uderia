"""
#classify extension — Answer categorization.

Categorizes the LLM answer into predefined topic buckets using
keyword-frequency scoring. Produces a primary category with confidence
score, suitable for n8n Switch node routing.

Categories:
    alert          — Critical issues, failures, outages
    performance    — CPU, memory, throughput, latency metrics
    data_quality   — Missing data, nulls, duplicates, validation
    capacity       — Storage, growth, forecasting
    security       — Access, permissions, audit, compliance
    data_report    — Query results, tables, records, summaries
    informational  — General information (fallback)

Usage:
    #classify   → categorize the answer
"""

from typing import Optional

from trusted_data_agent.extensions.base import Extension
from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)

# Category → keyword sets (more keywords = more specific matching)
CATEGORIES = {
    "alert": [
        "critical", "urgent", "failure", "failed", "down", "outage",
        "crash", "error", "emergency", "unreachable", "fatal",
    ],
    "performance": [
        "cpu", "memory", "disk", "throughput", "latency", "utilization",
        "response time", "slow", "bottleneck", "performance", "iops",
        "bandwidth", "queue", "wait",
    ],
    "data_quality": [
        "missing", "null", "duplicate", "invalid", "quality", "orphan",
        "inconsistent", "mismatch", "corrupt", "stale", "outlier",
    ],
    "capacity": [
        "storage", "space", "growth", "forecast", "capacity", "full",
        "remaining", "projected", "trend", "quota",
    ],
    "security": [
        "access", "permission", "unauthorized", "breach", "audit",
        "compliance", "privilege", "role", "authentication", "encrypt",
    ],
    "data_report": [
        "rows", "records", "table", "column", "query", "result",
        "total", "count", "sum", "average", "report", "database",
    ],
}


class ClassifyExtension(Extension):

    @property
    def name(self) -> str:
        return "classify"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        answer_lower = context.answer_text.lower()

        # Score each category
        scores = {}
        for category, keywords in CATEGORIES.items():
            score = sum(1 for kw in keywords if kw in answer_lower)
            if score > 0:
                scores[category] = score

        # Determine primary category
        if scores:
            primary = max(scores, key=scores.get)
            max_score = scores[primary]
            # Confidence scales with the score relative to keyword count
            keyword_count = len(CATEGORIES[primary])
            confidence = min(max_score / max(keyword_count * 0.4, 1), 1.0)
        else:
            primary = "informational"
            confidence = 0.5

        output = {
            "primary_category": primary,
            "confidence": round(confidence, 2),
            "all_categories": scores,
            "branch_key": primary,
            "query": context.clean_query,
        }

        return ExtensionResult(
            extension_name="classify",
            content=output,
            content_type="application/json",
            metadata={"categories_matched": len(scores)},
        )
