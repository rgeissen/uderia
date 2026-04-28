"""
IFOC Engine Registry

A lightweight class-registry that maps profile type strings to ExecutionEngine
subclasses.  Resolution order: last-registered wins (later registrations can
override earlier ones, enabling specialisation without modifying base engines).

Usage
-----
Registration (at module import time via decorator)::

    from trusted_data_agent.agent.engines.registry import EngineRegistry
    from trusted_data_agent.agent.engines.base import ExecutionEngine

    @EngineRegistry.register
    class MyEngine(ExecutionEngine):
        profile_type = "my_new_type"
        ...

Dispatch (in execution_service.py)::

    engine_cls = EngineRegistry.resolve(active_profile)
    if engine_cls:
        async for event_str in engine_cls().run(...):
            ...
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Dict, List, Optional, Type

from .base import ExecutionEngine

app_logger = logging.getLogger("quart.app")


class EngineRegistry:
    """Class-level registry mapping profile types to ExecutionEngine subclasses."""

    _engines: ClassVar[List[Type[ExecutionEngine]]] = []

    @classmethod
    def register(cls, engine_cls: Type[ExecutionEngine]) -> Type[ExecutionEngine]:
        """Register an engine class.  Returns the class unchanged (decorator-safe)."""
        cls._engines.append(engine_cls)
        app_logger.debug(
            f"[EngineRegistry] Registered engine: {engine_cls.__name__} "
            f"(profile_type={engine_cls.profile_type!r})"
        )
        return engine_cls

    @classmethod
    def resolve(cls, profile: Dict[str, Any]) -> Optional[Type[ExecutionEngine]]:
        """Return the engine class that should handle *profile*, or None.

        Iterates registrations in reverse order so the last-registered engine
        wins when multiple engines claim the same profile type.
        """
        for engine_cls in reversed(cls._engines):
            if engine_cls.applies_to(profile):
                app_logger.debug(
                    f"[EngineRegistry] Resolved {engine_cls.__name__} "
                    f"for profile_type={profile.get('profile_type')!r}"
                )
                return engine_cls
        app_logger.warning(
            f"[EngineRegistry] No engine found for profile_type="
            f"{profile.get('profile_type')!r}; caller must apply a fallback."
        )
        return None

    @classmethod
    def all_engines(cls) -> List[Type[ExecutionEngine]]:
        """Return a snapshot of all registered engine classes (registration order)."""
        return list(cls._engines)

    @classmethod
    def registered_types(cls) -> List[str]:
        """Return the profile_type strings of all registered engines."""
        return [e.profile_type for e in cls._engines]
