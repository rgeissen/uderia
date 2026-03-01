"""
Context Window Snapshot — metrics dataclass for observability.

ContextWindowSnapshot captures the full state of a context assembly
operation: what each module contributed, what was condensed, which
dynamic adjustments fired, and the overall budget utilization.

Used for:
  - SSE events (context_window_snapshot) to the Live Status panel
  - Resource Panel "Context" tab display
  - Cost tracking and analytics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ContributionMetric:
    """Per-module metrics from a single context assembly."""

    module_id: str
    """Which module produced this contribution."""

    label: str
    """Human-readable label (from module manifest display_name)."""

    category: str
    """Module category: system, tools, history, knowledge, optimization, documents."""

    tokens_allocated: int
    """Tokens allocated to this module by the budget orchestrator."""

    tokens_used: int
    """Actual tokens consumed by the module's contribution."""

    utilization_pct: float
    """Percentage of allocated budget actually used (tokens_used / tokens_allocated)."""

    was_condensed: bool = False
    """Whether this module's output was condensed during Pass 4."""

    is_active: bool = True
    """Whether this module was active (vs deactivated or skipped)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Module-specific metadata from the Contribution object."""


@dataclass
class CondensationEvent:
    """Record of a condensation operation during Pass 4."""

    module_id: str
    """Which module was condensed."""

    tokens_before: int
    """Token count before condensation."""

    tokens_after: int
    """Token count after condensation."""

    reduction_pct: float
    """Percentage reduction: (before - after) / before * 100."""

    strategy: str
    """Condensation strategy used (e.g., 'names_only', 'sliding_window', 'truncation')."""


@dataclass
class ContextWindowSnapshot:
    """
    Complete snapshot of a context assembly operation.

    Emitted as a context_window_snapshot SSE event after each LLM call's
    context assembly. Provides full observability into budget allocation.
    """

    # --- Context window type info ---
    context_window_type_id: str
    """ID of the context window type used for this assembly."""

    context_window_type_name: str
    """Display name of the context window type."""

    # --- Budget summary ---
    model_context_limit: int
    """Model's maximum context window in tokens."""

    output_reserve: int
    """Tokens reserved for LLM output."""

    available_budget: int
    """Tokens available for context (limit - output reserve)."""

    total_used: int
    """Total tokens consumed across all modules."""

    utilization_pct: float
    """Overall budget utilization: total_used / available_budget * 100."""

    # --- Per-module breakdown ---
    contributions: List[ContributionMetric] = field(default_factory=list)
    """Metrics for each module that participated in assembly."""

    # --- Condensation events ---
    condensations: List[CondensationEvent] = field(default_factory=list)
    """Condensation operations that occurred during Pass 4."""

    # --- Intra-turn distillation events ---
    distillation_events: List[Dict[str, Any]] = field(default_factory=list)
    """Distillation events from tactical planning (large tool results → metadata)."""

    # --- Dynamic adjustments ---
    dynamic_adjustments_fired: List[str] = field(default_factory=list)
    """Names of dynamic adjustment rules that were triggered."""

    # --- Module resolution info ---
    profile_type: str = ""
    """Profile type used for module resolution."""

    skipped_modules: List[str] = field(default_factory=list)
    """Module IDs that were skipped (deactivated or not applicable)."""

    active_module_count: int = 0
    """Number of modules that actively contributed."""

    # --- Session context ---
    session_id: str = ""
    """Session ID for this assembly."""

    turn_number: int = 0
    """Turn number within the session."""

    def to_sse_event(self) -> Dict[str, Any]:
        """Format as SSE event payload for context_window_snapshot events."""
        return {
            "type": "context_window_snapshot",
            "context_window_type": {
                "id": self.context_window_type_id,
                "name": self.context_window_type_name,
            },
            "budget": {
                "model_limit": self.model_context_limit,
                "output_reserve": self.output_reserve,
                "available": self.available_budget,
                "used": self.total_used,
                "utilization_pct": round(self.utilization_pct, 1),
            },
            "contributions": [
                {
                    "module_id": c.module_id,
                    "label": c.label,
                    "category": c.category,
                    "allocated": c.tokens_allocated,
                    "used": c.tokens_used,
                    "utilization_pct": round(c.utilization_pct, 1),
                    "condensed": c.was_condensed,
                    "active": c.is_active,
                    "metadata": c.metadata,
                }
                for c in self.contributions
            ],
            "condensations": [
                {
                    "module_id": e.module_id,
                    "before": e.tokens_before,
                    "after": e.tokens_after,
                    "reduction_pct": round(e.reduction_pct, 1),
                    "strategy": e.strategy,
                }
                for e in self.condensations
            ],
            "distillation_events": self.distillation_events,
            "dynamic_adjustments": self.dynamic_adjustments_fired,
            "resolution": {
                "profile_type": self.profile_type,
                "active_modules": self.active_module_count,
                "skipped_modules": self.skipped_modules,
            },
            "session_id": self.session_id,
            "turn_number": self.turn_number,
        }

    def to_summary_text(self) -> str:
        """
        Format as compact text for logging or status display.

        Example: "Context: 10.4K/184K (5.7%) | Sys:1.0K Tools:3.2K Hist:4.1K"
        """
        parts = []
        for c in self.contributions:
            if c.is_active and c.tokens_used > 0:
                label = c.label[:4]  # Short label
                tokens_k = c.tokens_used / 1000
                parts.append(f"{label}:{tokens_k:.1f}K")

        total_k = self.total_used / 1000
        budget_k = self.available_budget / 1000
        modules_str = " ".join(parts)

        return f"Context: {total_k:.1f}K/{budget_k:.0f}K ({self.utilization_pct:.1f}%) | {modules_str}"
