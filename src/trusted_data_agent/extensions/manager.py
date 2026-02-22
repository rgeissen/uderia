"""
Extension Manager: Discovers, loads, and manages post-processing extensions.

Mirrors the RAGTemplateManager pattern:
- Singleton via get_extension_manager()
- Registry-based discovery from extension_registry.json
- Auto-discovery from ~/.tda/extensions/ (no registry entry required)
- Manifest-free mode for SimpleExtension subclasses (single .py file)
- Hot-reload via reload()

Discovery order (later overrides earlier):
  1. Built-in (registry):  extensions/builtin/
  2. User (registry):      ~/.tda/extensions/ (if ID matches registry)
  3. User (auto-discover): ~/.tda/extensions/ (manifest.json present, no registry entry)
  4. User (manifest-free): ~/.tda/extensions/ (SimpleExtension subclass, no manifest)
"""

import importlib.util
import inspect
import json
import logging
import re
import sys
from datetime import datetime, timezone
import shutil
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

        # Auto-discover user extensions not in the registry
        auto_loaded = self._auto_discover_user_extensions()
        loaded += auto_loaded

        logger.info(f"Loaded {loaded} extension(s) ({auto_loaded} auto-discovered)")

    def _auto_discover_user_extensions(self) -> int:
        """
        Auto-discover user extensions in ~/.tda/extensions/ that have
        no registry entry.

        Four discovery modes (lowest friction first):
          Mode A: Flat .py files directly in user_dir (convention-based, Level 0)
          Mode B: Subdirectory with .py but no manifest (class-based, Level 1)
          Mode C: Subdirectory with manifest.json (any level)
          Mode D: Registry-based (already handled before this method)

        Returns:
            Number of successfully loaded extensions.
        """
        if not self.user_dir.exists():
            return 0

        loaded_ids = set(self.extensions.keys())
        auto_loaded = 0

        # --- Mode A: Flat .py files (convention-based, zero friction) ---
        for py_file in sorted(self.user_dir.glob("*.py")):
            if py_file.name.startswith((".", "_")):
                continue

            result = self._try_convention_wrap(py_file)
            if result is None:
                continue

            ext_id, instance, manifest = result
            if ext_id in loaded_ids:
                continue

            self.extensions[ext_id] = instance
            manifest["_is_user"] = True
            manifest["_source_path"] = str(py_file)
            manifest["_dir"] = str(self.user_dir)
            self.manifests[ext_id] = manifest
            auto_loaded += 1
            loaded_ids.add(ext_id)
            logger.info(f"Auto-discovered user extension: {ext_id} (convention-based)")

        # --- Mode B & C: Subdirectories ---
        for subdir in sorted(self.user_dir.iterdir()):
            if not subdir.is_dir() or subdir.name.startswith((".", "_")):
                continue

            manifest_path = subdir / "manifest.json"

            if manifest_path.exists():
                # Mode C: Manifest mode
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    ext_id = manifest.get("extension_id", subdir.name)
                except Exception as e:
                    logger.warning(f"Auto-discover: bad manifest in {subdir}: {e}")
                    continue

                if ext_id in loaded_ids:
                    continue

                if self._load_extension(ext_id, subdir, is_user=True):
                    auto_loaded += 1
                    loaded_ids.add(ext_id)
                    logger.info(f"Auto-discovered user extension: {ext_id} (manifest mode)")

            else:
                # Mode B: Manifest-free (class-based)
                auto_manifest = self._try_auto_manifest(subdir)
                if auto_manifest is None:
                    continue

                ext_id = auto_manifest.get("extension_id", subdir.name)
                if ext_id in loaded_ids:
                    continue

                if self._load_extension_from_auto_manifest(ext_id, subdir, auto_manifest):
                    auto_loaded += 1
                    loaded_ids.add(ext_id)
                    logger.info(f"Auto-discovered user extension: {ext_id} (manifest-free)")

        return auto_loaded

    def _try_convention_wrap(self, py_path: Path) -> Optional[tuple]:
        """
        Level 0: Convention-based wrapping for flat .py files.

        Looks for module-level constants and a transform() function,
        then auto-wraps them into a SimpleExtension instance.

        Required:
            EXTENSION_NAME = "name"           — the #name trigger
            def transform(answer_text, param=None) -> dict|str

        Optional:
            EXTENSION_DESCRIPTION = "..."     — UI description
            ALLOWED_PARAMS = {"a", "b"}       — valid param values
            CONTENT_TYPE = "application/json"  — MIME type
            OUTPUT_TARGET = "silent"           — silent, chat_append, status_panel

        Returns:
            (ext_id, instance, manifest) tuple, or None if not applicable.
        """
        from trusted_data_agent.extensions.base import SimpleExtension
        from trusted_data_agent.extensions.models import OutputTarget

        try:
            module_name = f"user_ext_conv_{py_path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, py_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            logger.debug(f"Convention wrap: failed to import {py_path}: {e}")
            return None

        # Check for required convention markers
        ext_name = getattr(module, "EXTENSION_NAME", None)
        transform_fn = getattr(module, "transform", None)

        if not ext_name or not callable(transform_fn):
            return None  # Not a convention-based extension

        # Read optional constants
        description = getattr(module, "EXTENSION_DESCRIPTION", "")
        allowed_params = getattr(module, "ALLOWED_PARAMS", None)
        content_type = getattr(module, "CONTENT_TYPE", "application/json")
        output_target_str = getattr(module, "OUTPUT_TARGET", "silent")

        # Resolve output target
        try:
            output_target = OutputTarget(output_target_str)
        except ValueError:
            output_target = OutputTarget.SILENT

        # Capture the function reference for the closure
        _transform = transform_fn
        _name = ext_name
        _allowed = set(allowed_params) if allowed_params else None
        _ctype = content_type
        _desc = description
        _target = output_target

        # Dynamically create a SimpleExtension subclass wrapping the function
        class ConventionWrappedExtension(SimpleExtension):
            name = _name
            description = _desc
            allowed_params = _allowed
            content_type = _ctype

            @property
            def output_target(self):
                return _target

            def transform(self, answer_text, param=None):
                return _transform(answer_text, param)

        try:
            instance = ConventionWrappedExtension()
        except Exception as e:
            logger.warning(f"Convention wrap: failed to create extension from {py_path}: {e}")
            return None

        manifest = {
            "extension_id": ext_name,
            "display_name": ext_name.replace("_", " ").title(),
            "description": description,
            "version": "1.0.0",
            "author": "User",
            "category": "Custom",
            "extension_tier": "convention",
            "requires_llm": False,
            "files": {"extension": py_path.name},
            "parameters": {},
            "output_schema": {},
            "keywords": [],
            "_auto_generated": True,
            "_convention_based": True,
        }

        if allowed_params:
            manifest["parameters"] = {
                "param": {
                    "description": "Extension parameter",
                    "valid_values": sorted(allowed_params),
                }
            }

        return (ext_name, instance, manifest)

    def _try_auto_manifest(self, ext_dir: Path) -> Optional[Dict[str, Any]]:
        """
        Try to generate an in-memory manifest from a SimpleExtension subclass.

        Looks for a single .py file in the directory, imports it,
        finds a SimpleExtension subclass, and reads its class attributes
        to build a manifest dict.

        Returns:
            In-memory manifest dict, or None if not applicable.
        """
        from trusted_data_agent.extensions.base import SimpleExtension, LLMExtension

        py_files = [f for f in ext_dir.iterdir() if f.suffix == ".py" and not f.name.startswith("_")]
        if not py_files:
            return None

        # Use the first .py file (or the one matching the directory name)
        py_path = None
        for f in py_files:
            if f.stem == ext_dir.name:
                py_path = f
                break
        if py_path is None:
            py_path = py_files[0]

        # Import and inspect
        try:
            module_name = f"user_ext_auto_{ext_dir.name}"
            spec = importlib.util.spec_from_file_location(module_name, py_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            logger.debug(f"Auto-manifest: failed to import {py_path}: {e}")
            return None

        # Find Extension subclass (SimpleExtension, LLMExtension, or plain Extension)
        ext_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Extension)
                and attr not in (Extension, SimpleExtension, LLMExtension)
                and not inspect.isabstract(attr)
            ):
                ext_class = attr
                break

        if ext_class is None:
            return None

        # Instantiate to read attributes
        try:
            instance = ext_class()
        except Exception as e:
            logger.debug(f"Auto-manifest: failed to instantiate {ext_class.__name__}: {e}")
            return None

        # Determine tier
        if issubclass(ext_class, LLMExtension):
            tier = "llm"
            requires_llm = True
        elif issubclass(ext_class, SimpleExtension):
            tier = "simple"
            requires_llm = False
        else:
            tier = "standard"
            requires_llm = False

        # Build in-memory manifest
        ext_name = instance.name
        description = getattr(instance, "description", "") or ""
        allowed_params = getattr(instance, "allowed_params", None)

        manifest = {
            "extension_id": ext_name,
            "display_name": ext_name.replace("_", " ").title(),
            "description": description,
            "version": "1.0.0",
            "author": "User",
            "category": "Custom",
            "extension_tier": tier,
            "requires_llm": requires_llm,
            "files": {"extension": py_path.name},
            "parameters": {},
            "output_schema": {},
            "keywords": [],
            "_auto_generated": True,
        }

        # Add parameter info if allowed_params is defined
        if allowed_params:
            manifest["parameters"] = {
                "param": {
                    "description": "Extension parameter",
                    "valid_values": sorted(allowed_params),
                }
            }

        return manifest

    def _load_extension_from_auto_manifest(
        self,
        ext_id: str,
        ext_dir: Path,
        manifest: Dict[str, Any],
    ) -> bool:
        """
        Load an extension using an auto-generated in-memory manifest.

        Similar to _load_extension but skips reading manifest.json from disk.
        """
        from trusted_data_agent.extensions.base import SimpleExtension, LLMExtension

        py_filename = manifest.get("files", {}).get("extension")
        if not py_filename:
            return False

        py_path = ext_dir / py_filename
        if not py_path.exists():
            return False

        # Module may already be loaded from _try_auto_manifest
        module_name = f"user_ext_auto_{ext_dir.name}"
        module = sys.modules.get(module_name)

        if module is None:
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error(f"Failed to import auto-discovered extension '{ext_id}': {e}")
                return False

        # Find the Extension subclass
        ext_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Extension)
                and attr not in (Extension, SimpleExtension, LLMExtension)
                and not inspect.isabstract(attr)
            ):
                ext_class = attr
                break

        if ext_class is None:
            return False

        try:
            instance = ext_class()
        except Exception as e:
            logger.error(f"Failed to instantiate auto-discovered extension '{ext_id}': {e}")
            return False

        self.extensions[ext_id] = instance
        manifest["_is_user"] = True
        manifest["_source_path"] = str(py_path)
        manifest["_dir"] = str(ext_dir)
        self.manifests[ext_id] = manifest

        return True

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
        from trusted_data_agent.extensions.base import SimpleExtension, LLMExtension

        result = []
        for ext_id, manifest in self.manifests.items():
            ext = self.extensions.get(ext_id)

            # Determine tier from manifest or by inspecting the instance
            tier = manifest.get("extension_tier")
            if not tier and ext:
                if isinstance(ext, LLMExtension):
                    tier = "llm"
                elif isinstance(ext, SimpleExtension):
                    tier = "simple"
                else:
                    tier = "standard"

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
                "is_builtin": not manifest.get("_is_user", False),
                "extension_tier": tier or "standard",
                "requires_llm": manifest.get("requires_llm", False),
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

    def delete_extension(self, ext_id: str) -> bool:
        """Delete a user-created extension from disk and reload.

        Raises ValueError if the extension is built-in or not found.
        Returns True on success.
        """
        manifest = self.get_manifest(ext_id)
        if not manifest:
            raise ValueError(f"Extension '{ext_id}' not found")
        if not manifest.get("_is_user"):
            raise ValueError("Only user-created extensions can be deleted")

        ext_dir = manifest.get("_dir")
        source_path = manifest.get("_source_path")

        if ext_dir and Path(ext_dir).is_dir():
            shutil.rmtree(ext_dir)
            logger.info(f"Deleted extension directory: {ext_dir}")
        elif source_path and Path(source_path).is_file():
            Path(source_path).unlink()
            logger.info(f"Deleted extension file: {source_path}")
        else:
            raise ValueError(f"Could not locate files for extension '{ext_id}'")

        self.reload()
        return True

    def duplicate_extension(self, ext_id: str) -> Dict[str, Any]:
        """Duplicate an extension (built-in or user) into a new user extension.

        Creates a copy under ~/.tda/extensions/{new_id}/ with a unique ID
        and rewritten source name references.

        Returns dict with extension_id and display_name of the new copy.
        Raises ValueError if the source extension is not found.
        """
        manifest = self.get_manifest(ext_id)
        if not manifest:
            raise ValueError(f"Extension '{ext_id}' not found")

        source = self.get_extension_source(ext_id)
        if not source:
            raise ValueError(f"Could not read source for extension '{ext_id}'")

        # Generate unique ID and display name
        new_id = self._generate_unique_copy_id(ext_id)
        orig_display = manifest.get("display_name") or manifest.get("name") or ext_id
        new_display = f"{orig_display} (Copy)"
        # Check if display name also needs a suffix
        existing_names = {m.get("display_name", "") for m in self.manifests.values()}
        if new_display in existing_names:
            counter = 2
            while f"{orig_display} (Copy {counter})" in existing_names:
                counter += 1
            new_display = f"{orig_display} (Copy {counter})"

        # Rewrite name references in source
        rewritten_source = self._rewrite_extension_name(source, ext_id, new_id)

        # Build cleaned manifest for the copy
        new_manifest = {}
        internal_keys = {"_is_user", "_source_path", "_dir", "_auto_generated",
                         "_convention_based", "export_format_version", "exported_at"}
        for k, v in manifest.items():
            if k not in internal_keys:
                new_manifest[k] = v
        new_manifest["extension_id"] = new_id
        new_manifest["name"] = new_id
        new_manifest["display_name"] = new_display
        new_manifest["files"] = {"extension": f"{new_id}.py"}

        # Write to user directory
        target_dir = self.user_dir / new_id
        target_dir.mkdir(parents=True, exist_ok=True)

        (target_dir / f"{new_id}.py").write_text(rewritten_source, encoding="utf-8")
        (target_dir / "manifest.json").write_text(
            json.dumps(new_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        logger.info(f"Duplicated extension '{ext_id}' → '{new_id}' at {target_dir}")
        self.reload()

        return {"extension_id": new_id, "display_name": new_display}

    def _generate_unique_copy_id(self, base_id: str) -> str:
        """Generate a unique extension ID for a copy."""
        candidate = f"{base_id}_copy"
        if candidate not in self.manifests:
            return candidate
        counter = 2
        while f"{candidate}_{counter}" in self.manifests:
            counter += 1
        return f"{candidate}_{counter}"

    @staticmethod
    def _rewrite_extension_name(source: str, old_id: str, new_id: str) -> str:
        """Best-effort rewrite of extension name references in Python source."""
        escaped = re.escape(old_id)
        # Pattern A: return "old_id" (in @property def name)
        source = re.sub(
            r'(return\s+["\'])' + escaped + r'(["\'])',
            rf'\g<1>{new_id}\g<2>', source, count=1,
        )
        # Pattern B: name = "old_id" (class attribute)
        source = re.sub(
            r'(name\s*=\s*["\'])' + escaped + r'(["\'])',
            rf'\g<1>{new_id}\g<2>', source, count=1,
        )
        # Pattern C: EXTENSION_NAME = "old_id" (module constant)
        source = re.sub(
            r'(EXTENSION_NAME\s*=\s*["\'])' + escaped + r'(["\'])',
            rf'\g<1>{new_id}\g<2>', source, count=1,
        )
        return source

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
