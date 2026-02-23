"""
Component Manager: Discovers, loads, and manages Generative UI Components.

Mirrors the ExtensionManager pattern:
- Singleton via get_component_manager()
- Registry-based discovery from component_registry.json
- Auto-discovery from ~/.tda/components/
- Hot-reload via reload()

Discovery order (later overrides earlier):
  1. Built-in (registry):  components/builtin/
  2. Agent Pack:           components installed via agent packs
  3. User (auto-discover): ~/.tda/components/
"""

import importlib.util
import inspect
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from trusted_data_agent.components.base import BaseComponentHandler, StructuralHandler
from trusted_data_agent.components.models import ComponentDefinition

logger = logging.getLogger("quart.app")

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager_instance: Optional["ComponentManager"] = None


def get_component_manager(
    components_dir: Optional[Path] = None,
    user_dir: Optional[Path] = None,
) -> "ComponentManager":
    """
    Get or create the singleton ComponentManager.

    On first call, discovers and loads all components.
    Subsequent calls return the cached instance.
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ComponentManager(components_dir, user_dir)
    return _manager_instance


def reset_component_manager() -> None:
    """Reset the singleton (for testing or hot-reload)."""
    global _manager_instance
    _manager_instance = None


def get_component_instructions_for_prompt(
    profile_id: Optional[str],
    user_uuid: Optional[str],
    session_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Resolve component instructions for injection into any profile's system prompt.

    Encapsulates the full resolve-profile → get-instructions → format pattern
    so that all profile types (tool_enabled, llm_only, genie, rag_focused) use
    the same code path for component instruction injection.

    Returns formatted instruction text ready for {component_instructions_section}
    replacement, or empty string if no active components.
    """
    try:
        manager = get_component_manager()
        profile_config: Dict[str, Any] = {}
        if profile_id and user_uuid:
            try:
                from trusted_data_agent.core.config_manager import get_config_manager
                cm = get_config_manager()
                profile_config = cm.get_profile(profile_id, user_uuid) or {}
            except Exception:
                pass

        text = manager.get_instructions_text(profile_config, session_data or {})
        if text:
            return f"- **Component Guidelines:**\n{text}"
    except Exception as e:
        logger.warning(f"Component instructions assembly failed: {e}")
    return ""


def get_component_langchain_tools(
    profile_id: Optional[str],
    user_uuid: Optional[str],
) -> List[Any]:
    """
    Resolve profile → get LangChain component tools.

    Convenience function parallel to get_component_instructions_for_prompt().
    Profile classes call this one function — all resolution logic is internal.

    Returns:
        List of LangChain StructuredTool objects for active action components,
        or empty list if none.
    """
    try:
        manager = get_component_manager()
        profile_config: Dict[str, Any] = {}
        if profile_id and user_uuid:
            try:
                from trusted_data_agent.core.config_manager import get_config_manager
                cm = get_config_manager()
                profile_config = cm.get_profile(profile_id, user_uuid) or {}
            except Exception:
                pass

        return manager.get_langchain_tools(profile_config)
    except Exception as e:
        logger.warning(f"Component LangChain tools assembly failed: {e}")
    return []


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
# LangChain args_schema builder
# ---------------------------------------------------------------------------


def _build_args_schema(tool_def: dict) -> type:
    """
    Build a Pydantic BaseModel from a component manifest ``tool_definition``.

    Without a proper ``args_schema``, LangChain's ``StructuredTool`` wraps all
    arguments under a single ``kwargs`` key, which breaks handler argument
    parsing.  This function converts the manifest's ``args`` dict into a
    dynamically-created Pydantic model that LangChain uses as the input schema.
    """
    from pydantic import BaseModel, Field
    from typing import Any as _Any, Dict as _Dict, List as _List, Optional as _Opt

    args_spec = tool_def.get("args", {})
    _type_map = {
        "string": str,
        "str": str,
        "list[dict]": _List[_Dict[str, _Any]],
        "list": list,
        "dict": _Dict[str, _Any],
        "int": int,
        "float": float,
        "bool": bool,
    }

    annotations: dict = {}
    field_defaults: dict = {}
    for arg_name, arg_def in args_spec.items():
        py_type = _type_map.get(arg_def.get("type", "string"), _Any)
        description = arg_def.get("description", "")
        if arg_def.get("required", False):
            annotations[arg_name] = py_type
            field_defaults[arg_name] = Field(description=description)
        else:
            annotations[arg_name] = _Opt[py_type]
            field_defaults[arg_name] = Field(default=None, description=description)

    # Dynamically create a BaseModel subclass with the computed fields
    model_name = tool_def.get("name", "ComponentTool") + "Input"
    namespace = {"__annotations__": annotations, **field_defaults}
    return type(model_name, (BaseModel,), namespace)


# ---------------------------------------------------------------------------

class ComponentManager:
    """
    Manages Generative UI Components loaded from manifest + handler files.

    Each component lives in its own directory with:
      - manifest.json  — metadata, tool definition, render targets
      - handler.py     — Python handler (subclass of BaseComponentHandler)
      - renderer.js    — Frontend renderer (served via API)
      - instructions   — LLM prompt text (optional)
    """

    def __init__(
        self,
        components_dir: Optional[Path] = None,
        user_dir: Optional[Path] = None,
    ):
        # Resolve project root → components/ directory
        if components_dir is None:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            components_dir = project_root / "components"

        self.components_dir = components_dir
        self.builtin_dir = components_dir / "builtin"
        self.registry_file = components_dir / "component_registry.json"
        self.schemas_dir = components_dir / "schemas"

        # User override directory
        self.user_dir = user_dir or (Path.home() / ".tda" / "components")

        # Loaded state
        self.components: Dict[str, ComponentDefinition] = {}
        self.registry: Dict[str, Any] = {}

        # Tool name → component_id lookup for fast handler routing
        self._tool_to_component: Dict[str, str] = {}

        # Ensure directories exist
        self.builtin_dir.mkdir(parents=True, exist_ok=True)
        self.user_dir.mkdir(parents=True, exist_ok=True)

        # Load
        self._load_registry()
        self._discover_and_load()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def _load_registry(self) -> None:
        """Load the component registry from disk."""
        if not self.registry_file.exists():
            logger.info(
                f"Component registry not found at {self.registry_file}. "
                "Using empty registry — will auto-discover only."
            )
            self.registry = {
                "registry_version": "1.0.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "components": [],
            }
            return

        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                self.registry = json.load(f)
            count = len(self.registry.get("components", []))
            logger.info(f"Loaded component registry with {count} component(s)")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse component registry: {e}")
            self.registry = {"components": []}

    # ------------------------------------------------------------------
    # Discovery and loading
    # ------------------------------------------------------------------

    def _discover_and_load(self) -> None:
        """Discover and load components from all sources."""
        self.components.clear()
        self._tool_to_component.clear()

        # 1. Load built-in components from registry
        for entry in self.registry.get("components", []):
            comp_id = entry.get("component_id")
            plugin_dir = entry.get("plugin_directory", comp_id)
            comp_dir = self.builtin_dir / plugin_dir

            if not comp_dir.exists():
                logger.warning(
                    f"Component '{comp_id}': directory not found at {comp_dir}"
                )
                continue

            self._load_component(comp_dir, source="builtin")

        # 2. Auto-discover from builtin (not in registry)
        if self.builtin_dir.exists():
            for subdir in sorted(self.builtin_dir.iterdir()):
                if not subdir.is_dir():
                    continue
                manifest_file = subdir / "manifest.json"
                if manifest_file.exists():
                    # Check if already loaded via registry
                    try:
                        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                        comp_id = manifest.get("component_id")
                        if comp_id and comp_id not in self.components:
                            self._load_component(subdir, source="builtin")
                    except (json.JSONDecodeError, OSError):
                        pass

        # 3. Auto-discover user components
        if self.user_dir.exists():
            for subdir in sorted(self.user_dir.iterdir()):
                if not subdir.is_dir():
                    continue
                manifest_file = subdir / "manifest.json"
                if manifest_file.exists():
                    self._load_component(subdir, source="user")

        logger.info(
            f"ComponentManager: loaded {len(self.components)} component(s): "
            f"{', '.join(self.components.keys())}"
        )

        # Sync discovered components to database for admin visibility
        self._sync_to_database()

    def _sync_to_database(self) -> None:
        """Sync discovered components to installed_components table for admin visibility."""
        try:
            import sqlite3
            from trusted_data_agent.core.config import APP_CONFIG
            db_path = APP_CONFIG.AUTH_DB_PATH
            if not db_path:
                return

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            for comp_id, comp_def in self.components.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO installed_components
                    (component_id, display_name, version, source, agent_pack_id, is_active, manifest_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                """, (
                    comp_id,
                    comp_def.display_name,
                    comp_def.version,
                    comp_def.source,
                    comp_def.agent_pack_id,
                    json.dumps(comp_def.manifest) if comp_def.manifest else None,
                ))

            # Deactivate components no longer on disk
            discovered_ids = list(self.components.keys())
            if discovered_ids:
                placeholders = ','.join('?' * len(discovered_ids))
                cursor.execute(
                    f"UPDATE installed_components SET is_active = 0 WHERE component_id NOT IN ({placeholders})",
                    discovered_ids,
                )

            conn.commit()
            conn.close()
            logger.debug(f"Synced {len(self.components)} component(s) to installed_components table")
        except Exception as e:
            logger.warning(f"Failed to sync components to database: {e}")

    def _load_component(self, comp_dir: Path, source: str = "builtin") -> None:
        """Load a single component from its directory."""
        manifest_file = comp_dir / "manifest.json"
        if not manifest_file.exists():
            logger.warning(f"No manifest.json in {comp_dir}, skipping")
            return

        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load manifest from {comp_dir}: {e}")
            return

        comp_id = manifest.get("component_id")
        if not comp_id:
            logger.warning(f"Manifest in {comp_dir} missing 'component_id', skipping")
            return

        # Build ComponentDefinition
        comp_def = ComponentDefinition(
            component_id=comp_id,
            display_name=manifest.get("display_name", comp_id),
            description=manifest.get("description", ""),
            version=manifest.get("version", "1.0.0"),
            component_type=manifest.get("component_type", "action"),
            category=manifest.get("category", "General"),
            source=source,
            agent_pack_id=manifest.get("agent_pack_id"),
            directory=comp_dir,
            manifest_path=manifest_file,
            manifest=manifest,
            tool_definition=manifest.get("tool_definition"),
            instructions_config=manifest.get("instructions", {}),
            render_targets=manifest.get("render_targets", {"default": "inline", "supports": ["inline"]}),
            frontend_config=manifest.get("frontend", {}),
            profile_defaults=manifest.get("profile_defaults", {}),
        )

        # Load handler
        backend_config = manifest.get("backend", {})
        handler_file = backend_config.get("handler_file")
        if handler_file:
            handler_path = comp_dir / handler_file
            comp_def.handler_path = handler_path
            if handler_path.exists():
                handler = self._load_handler(
                    handler_path,
                    backend_config.get("handler_class"),
                    comp_id,
                )
                comp_def.handler = handler
            else:
                logger.warning(
                    f"Component '{comp_id}': handler file not found at {handler_path}"
                )

        # Set renderer path (relative for API serving)
        renderer_file = comp_def.frontend_config.get("renderer_file")
        if renderer_file:
            comp_def.renderer_path = comp_dir / renderer_file

        # Register
        self.components[comp_id] = comp_def

        # Build tool → component lookup
        tool_name = comp_def.get_tool_name()
        if tool_name:
            self._tool_to_component[tool_name] = comp_id

        logger.info(
            f"  Loaded component: {comp_id} "
            f"(type={comp_def.component_type}, "
            f"tool={tool_name or 'none'}, "
            f"source={source})"
        )

    def _load_handler(
        self,
        handler_path: Path,
        handler_class_name: Optional[str],
        comp_id: str,
    ) -> Optional[BaseComponentHandler]:
        """Import and instantiate a component handler from a Python file."""
        module_name = f"component_handler_{comp_id}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, handler_path)
            if spec is None or spec.loader is None:
                logger.error(f"Component '{comp_id}': cannot create module spec for {handler_path}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Find the handler class
            if handler_class_name:
                cls = getattr(module, handler_class_name, None)
                if cls is None:
                    logger.error(
                        f"Component '{comp_id}': class '{handler_class_name}' "
                        f"not found in {handler_path}"
                    )
                    return None
            else:
                # Auto-detect: first BaseComponentHandler subclass
                cls = None
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, BaseComponentHandler)
                        and obj is not BaseComponentHandler
                        and obj is not StructuralHandler
                    ):
                        cls = obj
                        break

                if cls is None:
                    logger.error(
                        f"Component '{comp_id}': no BaseComponentHandler subclass "
                        f"found in {handler_path}"
                    )
                    return None

            return cls()

        except Exception as e:
            logger.error(f"Component '{comp_id}': failed to load handler: {e}")
            return None

    # ------------------------------------------------------------------
    # Public API: Component access
    # ------------------------------------------------------------------

    def get_component(self, component_id: str) -> Optional[ComponentDefinition]:
        """Get a component by ID."""
        return self.components.get(component_id)

    def get_handler(self, tool_name: str) -> Optional[BaseComponentHandler]:
        """Get the handler for a given tool name (e.g., 'TDA_Charting')."""
        comp_id = self._tool_to_component.get(tool_name)
        if comp_id:
            comp = self.components.get(comp_id)
            if comp and comp.handler:
                return comp.handler
        return None

    def is_component_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to a component."""
        return tool_name in self._tool_to_component

    def get_all_components(self) -> List[ComponentDefinition]:
        """Get all loaded components."""
        return list(self.components.values())

    def get_builtin_components(self) -> List[ComponentDefinition]:
        """Get only built-in components."""
        return [c for c in self.components.values() if c.source == "builtin"]

    # ------------------------------------------------------------------
    # Public API: Profile-filtered queries
    # ------------------------------------------------------------------

    def get_active_components(
        self,
        profile_config: Dict[str, Any],
    ) -> List[ComponentDefinition]:
        """
        Get components that are active for a given profile configuration.

        Args:
            profile_config: Profile dict with optional 'componentConfig' key.
                If componentConfig is absent, all components are active (backward compat).

        Returns:
            List of active ComponentDefinition objects.
        """
        component_config = profile_config.get("componentConfig")

        if component_config is None:
            # Backward compat: no componentConfig → all components active
            return list(self.components.values())

        active = []
        for comp_id, comp_def in self.components.items():
            comp_settings = component_config.get(comp_id, {})
            if comp_settings.get("enabled", True):
                active.append(comp_def)

        return active

    def get_tool_definitions(
        self,
        profile_config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Get tool definitions for all active action components.

        Returns tool definitions formatted for injection into the LLM's
        tools context, filtered by profile component configuration.
        """
        active = self.get_active_components(profile_config)
        tools = []
        for comp in active:
            if comp.tool_definition and comp.component_type == "action":
                tools.append(comp.tool_definition)
        return tools

    def get_instructions_text(
        self,
        profile_config: Dict[str, Any],
        session_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Assemble active components' LLM instructions into a single text block.

        This is injected into the system prompt via {component_instructions_section}.

        Args:
            profile_config: Profile dict with optional componentConfig.
            session_data: Session data dict (for intensity resolution).

        Returns:
            Combined instruction text, or empty string if none.
        """
        session_data = session_data or {}
        component_config = profile_config.get("componentConfig", {})
        active = self.get_active_components(profile_config)

        parts = []
        for comp in active:
            if not comp.instructions_config:
                continue

            # Resolve intensity
            comp_settings = component_config.get(comp.component_id, {})
            intensity = comp_settings.get(
                "intensity",
                session_data.get("charting_intensity", "medium"),
            )

            instructions = comp.get_instructions(intensity)
            if instructions:
                parts.append(instructions)

        return "\n\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Public API: LangChain tool integration
    # ------------------------------------------------------------------

    def has_active_tool_components(
        self,
        profile_config: Dict[str, Any],
    ) -> bool:
        """
        Check if profile has any active action components requiring tool calling.

        Used by profile classes to decide whether to auto-upgrade to an agent
        with tool-calling capability (e.g., llm_only → ConversationAgentExecutor).
        """
        active = self.get_active_components(profile_config)
        return any(
            c.tool_definition and c.component_type == "action"
            for c in active
        )

    def get_langchain_tools(
        self,
        profile_config: Dict[str, Any],
    ) -> List[Any]:
        """
        Create LangChain Tool objects for all active action components.

        Each tool wraps the component handler's process() method so that
        LangChain agents (ConversationAgentExecutor) can call component tools
        the same way they call MCP tools.

        Returns:
            List of LangChain StructuredTool objects. Empty if no active
            action components or if LangChain is not available.
        """
        active = self.get_active_components(profile_config)
        action_components = [
            c for c in active
            if c.tool_definition and c.component_type == "action" and c.handler
        ]
        if not action_components:
            return []

        try:
            from langchain_core.tools import StructuredTool
        except ImportError:
            logger.warning("langchain_core not available — cannot create component LangChain tools")
            return []

        tools = []
        for comp in action_components:
            tool_def = comp.tool_definition
            handler = comp.handler

            # Build a Pydantic args_schema from the manifest tool_definition
            # so LangChain delivers arguments as proper keyword args (not
            # double-wrapped under a "kwargs" key).
            args_schema = _build_args_schema(tool_def)

            # Build the async wrapper that calls the handler's process() method
            async def _run_component(
                _handler=handler,
                _comp_id=comp.component_id,
                **kwargs,
            ) -> str:
                """Execute a component handler and return a JSON result."""
                import json as _json
                try:
                    payload = await _handler.process(kwargs, {})
                    # Return serialized result for the LLM to reference
                    return _json.dumps({
                        "status": "success",
                        "component_id": _comp_id,
                        "title": payload.title,
                        "metadata": payload.metadata,
                        "render_target": payload.render_target.value,
                        "spec": payload.spec,
                    })
                except Exception as e:
                    return _json.dumps({
                        "status": "error",
                        "component_id": _comp_id,
                        "error": str(e),
                    })

            tool = StructuredTool.from_function(
                coroutine=_run_component,
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                args_schema=args_schema,
            )
            tools.append(tool)

        logger.info(
            f"Created {len(tools)} LangChain component tool(s): "
            f"{', '.join(t.name for t in tools)}"
        )
        return tools

    # ------------------------------------------------------------------
    # Public API: Frontend manifest
    # ------------------------------------------------------------------

    def get_frontend_manifest(self) -> List[Dict[str, Any]]:
        """
        Get minimal manifest data for the frontend ComponentRendererRegistry.

        Returns list of dicts with: component_id, renderer_file, cdn_dependencies, etc.
        """
        return [comp.to_frontend_manifest() for comp in self.components.values()]

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload(self) -> int:
        """
        Hot-reload all components from disk.

        Returns:
            Number of components loaded after reload.
        """
        logger.info("ComponentManager: hot-reloading components...")

        # Clear cached instruction text
        for comp in self.components.values():
            comp._instructions_cache.clear()

        # Re-discover
        self._load_registry()
        self._discover_and_load()

        return len(self.components)
