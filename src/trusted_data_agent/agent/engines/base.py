"""
IFOC Engine Modularization — Base Classes

Every execution engine must subclass ExecutionEngine and declare a
``profile_type`` class variable. The EngineRegistry maps profile type strings
to engine classes and resolves the correct engine at dispatch time.

Adding a new engine
-------------------
1. Create a new file in this package.
2. Subclass ExecutionEngine, set ``profile_type``, implement ``run()``.
3. Decorate the class with ``@EngineRegistry.register``.
4. Add an import in ``engines/__init__.py`` so the decorator fires.

Migration note (phases 1-3)
----------------------------
During the phased extraction, ``run(executor)`` receives a fully-initialised
``PlanExecutor`` instance as its context object.  The engine accesses all
shared state (session, LLM client, profile config, etc.) via ``executor.*``.

Phase 4 will replace the ``PlanExecutor`` argument with a lean
``EngineContext`` dataclass so engines can be instantiated without PlanExecutor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncGenerator, ClassVar, Dict

if TYPE_CHECKING:
    # Avoid circular import at runtime; PlanExecutor is only needed for type hints.
    from trusted_data_agent.agent.executor import PlanExecutor


class ExecutionEngine(ABC):
    """Abstract base class for all IFOC execution engines."""

    # Subclasses declare which profile_type string they handle, e.g. "llm_only".
    profile_type: ClassVar[str] = ""

    @classmethod
    def applies_to(cls, profile: Dict[str, Any]) -> bool:
        """Return True if this engine should handle *profile*.

        Override for complex eligibility (e.g. llm_only + useMcpTools routing).
        Default: exact match on profile_type.
        """
        return bool(cls.profile_type) and profile.get("profile_type") == cls.profile_type

    @abstractmethod
    async def run(self, executor: "PlanExecutor") -> AsyncGenerator[str, None]:
        """Execute the query and yield SSE-formatted event strings.

        During phases 1-3, ``executor`` is a fully-initialised ``PlanExecutor``
        that provides all shared state and helper methods.  The engine must
        yield a ``final_answer`` SSE event as its last substantive event.

        Phase 4 will change this signature to accept an ``EngineContext``
        dataclass instead, removing the dependency on PlanExecutor entirely.

        Args:
            executor: Initialised PlanExecutor (or future EngineContext).
        """
        # Satisfy the type checker — concrete implementations must yield.
        yield  # type: ignore[misc]
