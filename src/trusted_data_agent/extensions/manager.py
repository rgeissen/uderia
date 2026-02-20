"""
Extension Manager: Discovers, loads, and manages post-processing extensions.

Mirrors the RAGTemplateManager pattern:
- Singleton via get_extension_manager()
- Registry-based discovery from extension_registry.json
- Scans builtin + user (~/.tda/extensions/) directories
- Hot-reload via reload()
"""

import importlib.util
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from trusted_data_agent.extensions.base import Extension

logger = logging.getLogger("quart.app")


class ExtensionManager:
    """
    Manages post-processing extensions loaded from Python files.

    Each extension lives in its own directory with:
      - manifest.json  — metadata for UI and validation
      - *.py           — Python implementation (subclass of Extension)

    Discovery order (later overrides earlier):
      1. Built-in: extensions/builtin/
      2. User:     ~/.tda/extensions/
    """

    def __init__(
        self,
        extensions_dir: Optional[Path] = None,
        user_dir: Optional[Path] = None,
    ):
        # Resolve project root → extensions/ directory
        if extensions_dir is None:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            extensions_dir = project_root / "extensions"

        self.extensions_dir = extensions_dir
        self.builtin_dir = extensions_dir / "builtin"
        self.registry_file = extensions_dir / "extension_registry.json"
        self.schemas_dir = extensions_dir / "schemas"

        # User override directory
        self.user_dir = user_dir or (Path.home() / ".tda" / "extensions")

        # Loaded state
        self.extensions: Dict[str, Extension] = {}
        self.manifests: Dict[str, Dict[str, Any]] = {}
        self.registry: Dict[str, Any] = {}

        # Ensure builtin directory exists
        self.builtin_dir.mkdir(parents=True, exist_ok=True)

        # Load
        self._load_registry()
        self._discover_and_load()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def _load_registry(self) -> None:
        """Load the extension registry from disk."""
        if not self.registry_file.exists():
            logger.warning(
                f"Extension registry not found at {self.registry_file}. "
                "Using empty registry."
            )
            self.registry = {
                "registry_version": "1.0.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "extensions": [],
            }
            return

        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                self.registry = json.load(f)
            count = len(self.registry.get("extensions", []))
            logger.info(f"Loaded extension registry with {count} extension(s)")
        except json.JSONDecodeError as e:
            logger.error(f"Extension registry contains invalid JSON: {e}")
            self.registry = {"extensions": []}
        except Exception as e:
            logger.error(f"Failed to load extension registry: {e}")
            self.registry = {"extensions": []}

    # ------------------------------------------------------------------
    # Discovery & Loading
    # ------------------------------------------------------------------

    def _discover_and_load(self) -> None:
        """Discover and load extensions from builtin + user directories."""
        loaded = 0

        for entry in self.registry.get("extensions", []):
            ext_id = entry.get("extension_id")
            status = entry.get("status", "active")
            plugin_directory = entry.get("plugin_directory", ext_id)

            if status == "deprecated":
                logger.debug(f"Skipping deprecated extension: {ext_id}")
                continue

            # Try user directory first (override), then builtin
            ext_dir = None
            is_user = False
            if self.user_dir.exists():
                candidate = self.user_dir / plugin_directory
                if candidate.exists() and (candidate / "manifest.json").exists():
                    ext_dir = candidate
                    is_user = True

            if ext_dir is None:
                candidate = self.builtin_dir / plugin_directory
                if candidate.exists() and (candidate / "manifest.json").exists():
                    ext_dir = candidate

            if ext_dir is None:
                logger.warning(
                    f"Extension directory not found for '{ext_id}' "
                    f"(looked in {self.builtin_dir} and {self.user_dir})"
                )
                continue

            if self._load_extension(ext_id, ext_dir, is_user=is_user):
                loaded += 1

        logger.info(f"Loaded {loaded} extension(s)")

    def _load_extension(
        self,
        ext_id: str,
        ext_dir: Path,
        is_user: bool = False,
    ) -> bool:
        """Load a single extension from its directory."""
        manifest_path = ext_dir / "manifest.json"

        # 1. Load manifest
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load manifest for '{ext_id}': {e}")
            return False

        # 2. Find the Python file
        py_filename = manifest.get("files", {}).get("extension")
        if not py_filename:
            logger.error(f"Extension '{ext_id}' manifest missing files.extension")
            return False

        py_path = ext_dir / py_filename
        if not py_path.exists():
            logger.error(f"Extension script not found: {py_path}")
            return False

        # 3. Dynamically import the module
        try:
            module_name = f"extension_{ext_id}"
            spec = importlib.util.spec_from_file_location(module_name, py_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error(f"Failed to import extension '{ext_id}' from {py_path}: {e}")
            return False

        # 4. Find the Extension subclass in the module
        ext_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Extension)
                and attr is not Extension
            ):
                ext_class = attr
                break

        if ext_class is None:
            logger.error(
                f"No Extension subclass found in {py_path}. "
                "Ensure the module defines a class that extends Extension."
            )
            return False

        # 5. Instantiate and register
        try:
            instance = ext_class()
        except Exception as e:
            logger.error(f"Failed to instantiate extension '{ext_id}': {e}")
            return False

        # Validate that the instance name matches the registry id
        if instance.name != ext_id:
            logger.warning(
                f"Extension name mismatch: registry says '{ext_id}' "
                f"but class reports '{instance.name}'. Using registry id."
            )

        self.extensions[ext_id] = instance
        manifest["_is_user"] = is_user
        manifest["_source_path"] = str(py_path)
        manifest["_dir"] = str(ext_dir)
        self.manifests[ext_id] = manifest

        source_label = "user" if is_user else "builtin"
        logger.info(f"Loaded extension: {ext_id} ({source_label})")
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_extension(self, name: str) -> Optional[Extension]:
        """Get a loaded extension by name. Returns None if not found."""
        return self.extensions.get(name)

    def list_extensions(self) -> List[Dict[str, Any]]:
        """
        List all loaded extensions with their manifest metadata.
        Used for the UI cards and autocomplete endpoint.
        """
        result = []
        for ext_id, manifest in self.manifests.items():
            ext = self.extensions.get(ext_id)
            result.append({
                "extension_id": ext_id,
                "display_name": manifest.get("display_name", ext_id),
                "description": manifest.get("description", ""),
                "category": manifest.get("category", "General"),
                "version": manifest.get("version", "0.0.0"),
                "author": manifest.get("author", "Unknown"),
                "output_target": ext.output_target.value if ext else "silent",
                "parameters": manifest.get("parameters", {}),
                "output_schema": manifest.get("output_schema", {}),
                "keywords": manifest.get("keywords", []),
                "is_user": manifest.get("_is_user", False),
                "status": "active",
            })
        return result

    def get_all_names(self) -> List[str]:
        """Get all registered extension names. Used for autocomplete."""
        return list(self.extensions.keys())

    def get_extension_source(self, name: str) -> Optional[str]:
        """
        Get the Python source code of an extension.
        Used by the 'View Script' feature in the UI.
        """
        manifest = self.manifests.get(name)
        if not manifest:
            return None
        source_path = manifest.get("_source_path")
        if not source_path:
            return None
        try:
            return Path(source_path).read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read source for extension '{name}': {e}")
            return None

    def get_manifest(self, name: str) -> Optional[Dict[str, Any]]:
        """Get the full manifest for an extension."""
        return self.manifests.get(name)

    def reload(self) -> None:
        """Hot-reload all extensions from disk."""
        self.extensions.clear()
        self.manifests.clear()
        self._load_registry()
        self._discover_and_load()
        logger.info("Extensions reloaded")


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_instance: Optional[ExtensionManager] = None


def get_extension_manager() -> ExtensionManager:
    """Get or create the singleton ExtensionManager instance."""
    global _instance
    if _instance is None:
        _instance = ExtensionManager()
    return _instance
