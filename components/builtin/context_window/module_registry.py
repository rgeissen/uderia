"""
Context Module Registry — discovers, loads, and manages context modules.

Follows the same discovery pattern as ComponentManager:
  1. Built-in modules:     components/builtin/context_window/modules/
  2. Agent pack modules:   installed via agent packs
  3. User modules:         ~/.tda/context_modules/

Modules are self-contained directories with manifest.json + handler.py.
The registry loads them at startup, supports hot-reload, and provides
install/uninstall/purge operations for user and agent-pack modules.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import ContextModule

logger = logging.getLogger("quart.app")


# ---------------------------------------------------------------------------
# Module definition — loaded from manifest.json
# ---------------------------------------------------------------------------

@dataclass
class ContextModuleDefinition:
    """
    A loaded context module with its manifest metadata and handler instance.
    """

    module_id: str
    """Unique identifier from manifest."""

    display_name: str
    """Human-readable name."""

    version: str
    """Semantic version string."""

    description: str
    """Short description."""

    category: str
    """Category: system, tools, history, knowledge, optimization, documents."""

    # --- Capabilities ---
    condensable: bool = False
    """Whether the module can condense its output under budget pressure."""

    purgeable: bool = False
    """Whether the module's data can be cleared."""

    has_cache: bool = False
    """Whether the module maintains a cache."""

    # --- Applicability ---
    applicable_profile_types: List[str] = field(default_factory=list)
    """Profile types this module applies to."""

    required: bool = False
    """If True, module cannot be deactivated in context window types."""

    # --- Defaults ---
    default_priority: int = 50
    """Default priority for this module (90-100 critical, 1-29 optional)."""

    default_target_pct: float = 5.0
    """Default target percentage of context budget."""

    default_min_pct: float = 0.0
    """Default minimum percentage."""

    default_max_pct: float = 15.0
    """Default maximum percentage."""

    # --- Runtime ---
    handler: Optional[ContextModule] = field(default=None, repr=False)
    """Loaded handler instance."""

    source: str = "builtin"
    """Where this module was loaded from: builtin, agent_pack, user."""

    source_path: str = ""
    """Filesystem path to the module directory."""

    manifest_raw: Dict[str, Any] = field(default_factory=dict, repr=False)
    """Raw manifest.json contents for reference."""


# ---------------------------------------------------------------------------
# Registry singleton
# ---------------------------------------------------------------------------

_registry_instance: Optional["ContextModuleRegistry"] = None


def get_module_registry() -> "ContextModuleRegistry":
    """Get or create the singleton module registry."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ContextModuleRegistry()
        _registry_instance.discover_modules()
    return _registry_instance


def reset_module_registry() -> None:
    """Reset the registry singleton (for testing / hot-reload)."""
    global _registry_instance
    _registry_instance = None


# ---------------------------------------------------------------------------
# Registry implementation
# ---------------------------------------------------------------------------

class ContextModuleRegistry:
    """
    Discovers, loads, and manages context modules from all sources.
    """

    def __init__(self):
        self.modules: Dict[str, ContextModuleDefinition] = {}
        self._builtin_path = Path(__file__).parent / "modules"
        self._user_path = Path.home() / ".tda" / "context_modules"

    def discover_modules(self) -> Dict[str, ContextModuleDefinition]:
        """
        Discover and load modules from all sources.

        Discovery order (later overrides earlier):
        1. Built-in modules
        2. Agent pack modules (future)
        3. User modules

        Returns:
            Dict of loaded modules keyed by module_id.
        """
        self.modules.clear()

        # 1. Built-in modules
        self._discover_from_directory(self._builtin_path, source="builtin")

        # 2. Agent pack modules (future — discover from installed packs)
        # TODO: Iterate agent pack install directories

        # 3. User modules
        if self._user_path.exists():
            self._discover_from_directory(self._user_path, source="user")

        logger.info(
            f"Context module registry: loaded {len(self.modules)} modules "
            f"({sum(1 for m in self.modules.values() if m.source == 'builtin')} builtin, "
            f"{sum(1 for m in self.modules.values() if m.source == 'user')} user)"
        )
        return self.modules

    def _discover_from_directory(
        self,
        base_path: Path,
        source: str,
    ) -> None:
        """Discover modules from subdirectories of base_path."""
        if not base_path.exists():
            return

        for entry in sorted(base_path.iterdir()):
            if not entry.is_dir():
                continue

            manifest_path = entry / "manifest.json"
            if not manifest_path.exists():
                logger.debug(f"Skipping {entry.name}: no manifest.json")
                continue

            try:
                definition = self._load_module(entry, source)
                if definition:
                    self.modules[definition.module_id] = definition
            except Exception as e:
                logger.error(f"Failed to load context module from {entry}: {e}")

    def _load_module(
        self,
        module_dir: Path,
        source: str,
    ) -> Optional[ContextModuleDefinition]:
        """Load a single module from its directory."""
        manifest_path = module_dir / "manifest.json"

        with open(manifest_path) as f:
            manifest = json.load(f)

        module_id = manifest.get("module_id")
        if not module_id:
            logger.warning(f"Module at {module_dir} missing module_id in manifest")
            return None

        # Parse capabilities
        capabilities = manifest.get("capabilities", {})
        applicability = manifest.get("applicability", {})
        defaults = manifest.get("defaults", {})
        handler_config = manifest.get("handler", {})

        # Load handler class
        handler_file = handler_config.get("file", "handler.py")
        handler_class_name = handler_config.get("class")
        handler = self._load_handler(
            module_dir / handler_file,
            handler_class_name,
            module_id,
        )

        return ContextModuleDefinition(
            module_id=module_id,
            display_name=manifest.get("display_name", module_id),
            version=manifest.get("version", "0.0.0"),
            description=manifest.get("description", ""),
            category=manifest.get("category", "general"),
            condensable=capabilities.get("condensable", False),
            purgeable=capabilities.get("purgeable", False),
            has_cache=capabilities.get("has_cache", False),
            applicable_profile_types=applicability.get("profile_types", []),
            required=applicability.get("required", False),
            default_priority=defaults.get("priority", 50),
            default_target_pct=defaults.get("target_pct", 5.0),
            default_min_pct=defaults.get("min_pct", 0.0),
            default_max_pct=defaults.get("max_pct", 15.0),
            handler=handler,
            source=source,
            source_path=str(module_dir),
            manifest_raw=manifest,
        )

    def _load_handler(
        self,
        handler_path: Path,
        class_name: Optional[str],
        module_id: str,
    ) -> Optional[ContextModule]:
        """Dynamically load a handler class from a Python file.

        Module handlers use relative imports (``from ..base import ...``)
        that require proper package context.  When loaded via the
        ComponentManager, this registry lives inside a synthetic package
        (e.g. ``component_pkg_context_window``).  We register each module
        subdirectory as a child package so that ``..base`` resolves to the
        parent package where ``base.py`` lives.
        """
        if not handler_path.exists():
            logger.warning(f"Handler file not found: {handler_path}")
            return None

        try:
            import sys
            import types

            # Determine parent package for relative imports.
            # When loaded via ComponentManager the registry's __module__ is
            # e.g. 'component_pkg_context_window.module_registry'.
            # Stripping the last segment gives us the package that contains
            # base.py and token_estimator.py.
            own_module_name = self.__class__.__module__
            parent_pkg = (
                own_module_name.rsplit(".", 1)[0]
                if "." in own_module_name
                else None
            )

            if parent_pkg and parent_pkg in sys.modules:
                # Register a sub-package for this context module so that
                # relative imports like ``from ..base import ...`` resolve
                # to the parent package (where base.py lives).
                sub_pkg_name = f"{parent_pkg}.{module_id}"
                handler_module_name = f"{sub_pkg_name}.handler"

                if sub_pkg_name not in sys.modules:
                    pkg = types.ModuleType(sub_pkg_name)
                    pkg.__path__ = [str(handler_path.parent)]
                    pkg.__file__ = str(handler_path.parent / "__init__.py")
                    pkg.__package__ = sub_pkg_name
                    sys.modules[sub_pkg_name] = pkg

                spec = importlib.util.spec_from_file_location(
                    handler_module_name, handler_path,
                )
                if spec is None or spec.loader is None:
                    logger.error(f"Could not create import spec for {handler_path}")
                    return None

                module = importlib.util.module_from_spec(spec)
                module.__package__ = sub_pkg_name
                sys.modules[handler_module_name] = module
                spec.loader.exec_module(module)
            else:
                # Fallback: flat loading (relative imports won't work but
                # absolute-import-only modules will still load).
                logger.debug(
                    f"No parent package context for module '{module_id}' — "
                    f"falling back to flat loading"
                )
                spec = importlib.util.spec_from_file_location(
                    f"context_module_{module_id}",
                    handler_path,
                )
                if spec is None or spec.loader is None:
                    logger.error(f"Could not create import spec for {handler_path}")
                    return None

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

            # Find the handler class
            if class_name:
                handler_cls = getattr(module, class_name, None)
            else:
                # Auto-detect: find the first ContextModule subclass
                handler_cls = None
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, ContextModule)
                        and attr is not ContextModule
                    ):
                        handler_cls = attr
                        break

            if handler_cls is None:
                logger.warning(
                    f"No ContextModule subclass found in {handler_path}"
                )
                return None

            return handler_cls()

        except Exception as e:
            logger.error(f"Error loading handler from {handler_path}: {e}")
            return None

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def get_module(self, module_id: str) -> Optional[ContextModuleDefinition]:
        """Get a module definition by ID."""
        return self.modules.get(module_id)

    def get_handler(self, module_id: str) -> Optional[ContextModule]:
        """Get a module's handler instance by ID."""
        defn = self.modules.get(module_id)
        return defn.handler if defn else None

    def get_all_modules(self) -> List[ContextModuleDefinition]:
        """Get all loaded module definitions."""
        return list(self.modules.values())

    def get_installed_modules(self) -> List[Dict[str, Any]]:
        """
        Get module info suitable for API responses and UI display.

        Returns list of dicts with module metadata (no handler instances).
        """
        result = []
        for defn in self.modules.values():
            result.append({
                "module_id": defn.module_id,
                "display_name": defn.display_name,
                "version": defn.version,
                "description": defn.description,
                "category": defn.category,
                "source": defn.source,
                "capabilities": {
                    "condensable": defn.condensable,
                    "purgeable": defn.purgeable,
                    "has_cache": defn.has_cache,
                },
                "applicability": {
                    "profile_types": defn.applicable_profile_types,
                    "required": defn.required,
                },
                "defaults": {
                    "priority": defn.default_priority,
                    "target_pct": defn.default_target_pct,
                    "min_pct": defn.default_min_pct,
                    "max_pct": defn.default_max_pct,
                },
            })
        return result

    async def purge_module(
        self,
        module_id: str,
        session_id: str,
        user_uuid: str,
    ) -> Dict[str, Any]:
        """
        Purge a module's cached/accumulated data.

        Args:
            module_id: Module to purge.
            session_id: Session scope (empty for all sessions).
            user_uuid: User scope.

        Returns:
            Dict with purge results.
        """
        handler = self.get_handler(module_id)
        if handler is None:
            return {"purged": False, "reason": f"Module '{module_id}' not found"}

        defn = self.modules[module_id]
        if not defn.purgeable:
            return {"purged": False, "reason": f"Module '{module_id}' is not purgeable"}

        return await handler.purge(session_id, user_uuid)

    def install_module(self, module_path: str) -> Optional[ContextModuleDefinition]:
        """
        Install a module from a filesystem path.

        Copies the module directory to ~/.tda/context_modules/ and loads it.

        Args:
            module_path: Path to the module directory to install.

        Returns:
            The loaded module definition, or None on failure.
        """
        source_dir = Path(module_path)
        if not (source_dir / "manifest.json").exists():
            logger.error(f"No manifest.json found at {module_path}")
            return None

        # Ensure user modules directory exists
        self._user_path.mkdir(parents=True, exist_ok=True)

        # Read module_id from manifest
        with open(source_dir / "manifest.json") as f:
            manifest = json.load(f)
        module_id = manifest.get("module_id")
        if not module_id:
            logger.error("Module manifest missing module_id")
            return None

        # Copy to user modules directory
        target_dir = self._user_path / module_id
        if target_dir.exists():
            logger.warning(f"Module '{module_id}' already installed at {target_dir}")
            return self.modules.get(module_id)

        import shutil
        shutil.copytree(source_dir, target_dir)

        # Load and register
        defn = self._load_module(target_dir, source="user")
        if defn:
            self.modules[defn.module_id] = defn
            logger.info(f"Installed context module: {module_id} from {module_path}")

        return defn

    def uninstall_module(self, module_id: str) -> bool:
        """
        Uninstall a user or agent-pack module.

        Built-in modules cannot be uninstalled.

        Args:
            module_id: Module to uninstall.

        Returns:
            True if uninstalled successfully.
        """
        defn = self.modules.get(module_id)
        if defn is None:
            logger.warning(f"Module '{module_id}' not found")
            return False

        if defn.source == "builtin":
            logger.warning(f"Cannot uninstall built-in module '{module_id}'")
            return False

        # Remove from filesystem
        module_dir = Path(defn.source_path)
        if module_dir.exists():
            import shutil
            shutil.rmtree(module_dir)

        # Remove from registry
        del self.modules[module_id]
        logger.info(f"Uninstalled context module: {module_id}")
        return True

    def reload(self) -> None:
        """
        Hot-reload all modules.

        Re-discovers modules from all sources. Existing handler instances
        are replaced with fresh ones.
        """
        logger.info("Hot-reloading context module registry...")
        self.discover_modules()
