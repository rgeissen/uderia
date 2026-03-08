"""
Data models for the Component system.

ComponentDefinition wraps a loaded component's manifest, handler, and metadata.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("quart.app")


@dataclass
class ComponentDefinition:
    """
    A fully loaded component ready for use.

    Created by ComponentManager during discovery. Holds the parsed manifest,
    resolved file paths, and optional loaded handler instance.
    """

    component_id: str
    """Unique identifier (e.g., 'chart', 'code_editor')."""

    display_name: str
    """Human-readable name for UI display."""

    description: str = ""
    """Short description of what the component does."""

    version: str = "1.0.0"
    """Semantic version string."""

    component_type: str = "action"
    """'action' (LLM-invoked), 'structural' (data-driven), or 'system' (infrastructure)."""

    category: str = "General"
    """UI category for filtering (e.g., 'Visualization', 'Media', 'Code')."""

    source: str = "builtin"
    """Where this component came from: 'builtin', 'agent_pack', 'user'."""

    agent_pack_id: Optional[str] = None
    """If installed via agent pack, the pack ID."""

    # --- File paths ---
    directory: Optional[Path] = None
    """Absolute path to the component directory."""

    manifest_path: Optional[Path] = None
    """Absolute path to manifest.json."""

    handler_path: Optional[Path] = None
    """Absolute path to the Python handler file."""

    renderer_path: Optional[Path] = None
    """Relative path to the JS renderer file (served via API)."""

    # --- Parsed manifest data ---
    manifest: Dict[str, Any] = field(default_factory=dict)
    """Full parsed manifest.json content."""

    tool_definition: Optional[Dict[str, Any]] = None
    """Tool definition from manifest (name, description, args). None for structural."""

    instructions_config: Dict[str, Any] = field(default_factory=dict)
    """Instructions config from manifest (file, format, substitutions)."""

    render_targets: Dict[str, Any] = field(default_factory=dict)
    """Render target configuration from manifest."""

    frontend_config: Dict[str, Any] = field(default_factory=dict)
    """Frontend config from manifest (renderer_file, cdn_dependencies)."""

    profile_defaults: Dict[str, Any] = field(default_factory=dict)
    """Default profile settings (enabled_for, default_intensity)."""

    # --- Loaded handler instance ---
    handler: Optional[Any] = None
    """Instantiated BaseComponentHandler (set by manager after import)."""

    # --- Cached instruction text ---
    _instructions_cache: Dict[str, str] = field(default_factory=dict)

    def get_instructions(self, intensity: str = "medium") -> str:
        """
        Load and return the LLM prompt instructions for this component.

        Args:
            intensity: For intensity-keyed instructions (e.g., chart: none/medium/heavy).
                       Ignored for non-intensity formats.

        Returns:
            Instruction text string, or empty string if no instructions defined.
        """
        if not self.instructions_config or not self.directory:
            return ""

        cache_key = intensity
        if cache_key in self._instructions_cache:
            return self._instructions_cache[cache_key]

        instructions_file = self.instructions_config.get("file")
        if not instructions_file:
            return ""

        file_path = self.directory / instructions_file
        if not file_path.exists():
            logger.warning(
                f"Component '{self.component_id}': instructions file "
                f"not found at {file_path}"
            )
            return ""

        try:
            raw = file_path.read_text(encoding="utf-8")
            fmt = self.instructions_config.get("format", "plain")

            if fmt == "intensity_keyed":
                # JSON dict keyed by intensity level
                data = json.loads(raw)
                text = data.get(intensity, data.get("medium", ""))
            else:
                # Plain text
                text = raw

            # Apply placeholder substitutions from supplementary files
            substitutions = self.instructions_config.get(
                "placeholder_substitutions", {}
            )
            for placeholder, filename in substitutions.items():
                supplement_path = self.directory / filename
                if supplement_path.exists():
                    supplement_text = supplement_path.read_text(encoding="utf-8")
                    text = text.replace(placeholder, supplement_text)
                else:
                    logger.warning(
                        f"Component '{self.component_id}': supplementary file "
                        f"'{filename}' not found"
                    )

            self._instructions_cache[cache_key] = text
            return text

        except (json.JSONDecodeError, OSError) as e:
            logger.error(
                f"Component '{self.component_id}': failed to load instructions: {e}"
            )
            return ""

    def get_tool_name(self) -> Optional[str]:
        """Return the TDA_* tool name, or None for structural components."""
        if self.tool_definition:
            return self.tool_definition.get("name")
        return None

    def get_cdn_dependencies(self) -> List[Dict[str, str]]:
        """Return CDN dependency list for frontend loading."""
        return self.frontend_config.get("cdn_dependencies", [])

    def get_default_render_target(self) -> str:
        """Return the default render target ('inline', 'sub_window', etc.)."""
        return self.render_targets.get("default", "inline")

    def supports_render_target(self, target: str) -> bool:
        """Check if this component supports a given render target."""
        supported = self.render_targets.get("supports", ["inline"])
        return target in supported

    def to_api_dict(self) -> Dict[str, Any]:
        """Serialize for REST API responses (GET /v1/components)."""
        return {
            "component_id": self.component_id,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "component_type": self.component_type,
            "category": self.category,
            "source": self.source,
            "agent_pack_id": self.agent_pack_id,
            "tool_name": self.get_tool_name(),
            "render_targets": self.render_targets,
            "profile_defaults": self.profile_defaults,
            "frontend": {
                "renderer_file": self.frontend_config.get("renderer_file"),
                "cdn_dependencies": self.get_cdn_dependencies(),
            },
            "has_handler": self.handler is not None,
        }

    def to_frontend_manifest(self) -> Dict[str, Any]:
        """Minimal manifest for frontend ComponentRendererRegistry."""
        return {
            "component_id": self.component_id,
            "display_name": self.display_name,
            "renderer_file": self.frontend_config.get("renderer_file"),
            "renderer_export": self.frontend_config.get("renderer_export"),
            "cdn_dependencies": self.get_cdn_dependencies(),
            "render_targets": self.render_targets,
        }
