"""
Execution Context Distiller — unified data distillation for LLM context.

Replaces the hardcoded _distill_data_for_llm_context() in executor.py
with a configurable, observable utility that lives within the context
window component.  Thresholds can be set per context-window-type
(via tda_config.json) instead of relying on global APP_CONFIG constants.

Used at three points during intra-turn execution:
  1. Tactical planning prompt assembly
  2. TDA_LLMTask focused data payloads
  3. Multi-loop / error-recovery report assembly
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("quart.app")

# Fallback defaults (match existing APP_CONFIG values)
_DEFAULT_MAX_ROWS = 500
_DEFAULT_MAX_CHARS = 10_000


class ExecutionContextDistiller:
    """
    Recursively distills large data structures into metadata summaries
    to protect the LLM context window during intra-turn execution.

    Configurable via context-window-type config or explicit constructor
    arguments.  Produces distillation event dicts for observability.
    """

    def __init__(
        self,
        max_rows: int = _DEFAULT_MAX_ROWS,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ):
        self.max_rows = max_rows
        self.max_chars = max_chars

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def from_context_window_type(cwt: Optional[Dict[str, Any]] = None) -> "ExecutionContextDistiller":
        """
        Create a distiller from a context-window-type config dict.

        Reads the optional ``distillation`` block:

        .. code-block:: json

            {
              "id": "cwt-default-balanced",
              "distillation": {
                "max_rows": 500,
                "max_chars": 10000
              }
            }

        Falls back to module-level defaults when the block is absent.
        """
        if cwt and isinstance(cwt, dict):
            dist_cfg = cwt.get("distillation", {})
            return ExecutionContextDistiller(
                max_rows=dist_cfg.get("max_rows", _DEFAULT_MAX_ROWS),
                max_chars=dist_cfg.get("max_chars", _DEFAULT_MAX_CHARS),
            )
        return ExecutionContextDistiller()

    # ------------------------------------------------------------------
    # Core distillation
    # ------------------------------------------------------------------

    def distill(self, data: Any, events: Optional[List[Dict[str, Any]]] = None) -> Any:
        """
        Recursively distill *data*, replacing large ``results`` arrays
        with compact metadata summaries.

        Args:
            data:   Arbitrarily nested dict/list structure (typically
                    ``workflow_state`` or ``turn_action_history``).
            events: Optional accumulator list — each distillation
                    appends an event dict for observability / SSE.

        Returns:
            A (potentially) reduced copy of *data*.  The caller is
            responsible for passing a ``copy.deepcopy()`` if the
            original must be preserved.
        """
        if isinstance(data, dict):
            if "results" in data and isinstance(data["results"], list):
                results_list = data["results"]
                is_large = (
                    len(results_list) > self.max_rows
                    or len(json.dumps(results_list)) > self.max_chars
                )

                if is_large and all(isinstance(item, dict) for item in results_list):
                    columns = list(results_list[0].keys()) if results_list else []
                    if events is not None:
                        events.append({
                            "subtype": "context_distillation",
                            "summary": (
                                f"Large result distilled: {len(results_list):,} rows "
                                f"→ metadata summary"
                            ),
                            "row_count": len(results_list),
                            "char_count": len(json.dumps(results_list)),
                            "columns": columns,
                        })
                    return {
                        "status": data.get("status", "success"),
                        "metadata": {
                            "row_count": len(results_list),
                            "columns": columns,
                            **data.get("metadata", {}),
                        },
                        "comment": "Full data is too large for context. This is a summary.",
                    }

            return {
                key: self.distill(value, events=events)
                for key, value in data.items()
            }

        if isinstance(data, list):
            return [self.distill(item, events=events) for item in data]

        return data
