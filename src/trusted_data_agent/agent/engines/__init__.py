"""
IFOC Execution Engine Package

This package contains the modular execution engine system for the Uderia IFOC
profile types.  Import order matters: each engine module must be imported here
so its @EngineRegistry.register decorator fires and the engine is available for
dispatch.

Current registration status:
  Phase 0 — Base infrastructure (this file, base.py, registry.py)
  Phase 1 — IdeateEngine    (llm_only)     [complete]
  Phase 2 — FocusEngine     (rag_focused)  [complete]
  Phase 3 — CoordinateEngine (genie)       [complete]
  Phase 4 — OptimizeEngine  (tool_enabled) [complete]
"""

from .base import ExecutionEngine
from .registry import EngineRegistry

# Phase 1 — IdeateEngine (llm_only)
from .ideate_engine import IdeateEngine  # noqa: F401  — registers on import

# Phase 2 — FocusEngine (rag_focused)
from .focus_engine import FocusEngine  # noqa: F401  — registers on import

# Phase 3 — CoordinateEngine (genie)
from .coordinate_engine import CoordinateEngine  # noqa: F401  — registers on import

# Phase 4 — OptimizeEngine (tool_enabled)
from .optimize_engine import OptimizeEngine  # noqa: F401  — registers on import

__all__ = [
    "ExecutionEngine",
    "EngineRegistry",
    "IdeateEngine",
    "FocusEngine",
    "CoordinateEngine",
    "OptimizeEngine",
]
