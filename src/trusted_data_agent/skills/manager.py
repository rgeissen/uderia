"""
Skill Manager: Discovers, loads, and manages pre-processing skills.

Skills are pure markdown knowledge documents (compatible with Claude Code)
that get injected into the LLM context when activated by the user.

Discovery mirrors ExtensionManager (4 modes):
  1. Registry (skill_registry.json) → skills/builtin/ directories
  2. User override (~/.tda/skills/) → same structure, overrides builtins by name
  3. Manifest-only → directory with skill.json + .md file, no registry entry needed
  4. Manifest-free → directory with only a .md file → auto-generates in-memory manifest

Hot-reload via POST /v1/skills/reload or manager.reload().
"""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from trusted_data_agent.skills.models import SkillContent, SkillSpec, SkillResult
from trusted_data_agent.skills.loader import load_skill_content

logger = logging.getLogger("quart.app")


class SkillManager:
    """
    Manages pre-processing skills loaded from markdown files.

    Each skill lives in its own directory with:
      - skill.json  — manifest (metadata, tags, keywords, params)
      - *.md        — markdown content (the actual skill knowledge)

    Discovery order (later overrides earlier):
      1. Built-in: skills/builtin/
      2. User:     ~/.tda/skills/
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        user_dir: Optional[Path] = None,
    ):
        # Resolve project root → skills/ directory
        if skills_dir is None:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            skills_dir = project_root / "skills"

        self.skills_dir = skills_dir
        self.builtin_dir = skills_dir / "builtin"
        self.registry_file = skills_dir / "skill_registry.json"
        self.schemas_dir = skills_dir / "schemas"

        # User override directory
        self.user_dir = user_dir or (Path.home() / ".tda" / "skills")

        # Loaded state
        self.manifests: Dict[str, Dict[str, Any]] = {}
        self.skill_dirs: Dict[str, Path] = {}
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
        """Load the skill registry from disk."""
        if not self.registry_file.exists():
            logger.warning(
                f"Skill registry not found at {self.registry_file}. "
                "Using empty registry."
            )
            self.registry = {
                "registry_version": "1.0.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "skills": [],
            }
            return

        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                self.registry = json.load(f)
            count = len(self.registry.get("skills", []))
            logger.info(f"Loaded skill registry with {count} skill(s)")
        except json.JSONDecodeError as e:
            logger.error(f"Skill registry contains invalid JSON: {e}")
            self.registry = {"skills": []}
        except Exception as e:
            logger.error(f"Failed to load skill registry: {e}")
            self.registry = {"skills": []}

    # ------------------------------------------------------------------
    # Discovery & Loading
    # ------------------------------------------------------------------

    def _discover_and_load(self) -> None:
        """Discover and load skills from builtin + user directories."""
        loaded = 0

        # Mode 1: Registry-based discovery
        for entry in self.registry.get("skills", []):
            skill_id = entry.get("skill_id")
            status = entry.get("status", "active")
            plugin_directory = entry.get("plugin_directory", skill_id)

            if status == "deprecated":
                logger.debug(f"Skipping deprecated skill: {skill_id}")
                continue

            # Try user directory first (override), then builtin
            skill_dir = None
            is_user = False
            if self.user_dir.exists():
                candidate = self.user_dir / plugin_directory
                if candidate.exists() and self._has_content(candidate):
                    skill_dir = candidate
                    is_user = True

            if skill_dir is None:
                candidate = self.builtin_dir / plugin_directory
                if candidate.exists() and self._has_content(candidate):
                    skill_dir = candidate

            if skill_dir is None:
                logger.warning(
                    f"Skill directory not found for '{skill_id}' "
                    f"(looked in {self.builtin_dir} and {self.user_dir})"
                )
                continue

            if self._load_skill(skill_id, skill_dir, is_user=is_user):
                loaded += 1

        # Mode 2-4: Auto-discover user skills not in the registry
        auto_loaded = self._auto_discover_user_skills()
        loaded += auto_loaded

        logger.info(f"Loaded {loaded} skill(s) ({auto_loaded} auto-discovered)")

    def _has_content(self, directory: Path) -> bool:
        """Check if a directory has skill content (.md file or skill.json)."""
        if (directory / "skill.json").exists():
            return True
        return any(directory.glob("*.md"))

    def _auto_discover_user_skills(self) -> int:
        """
        Auto-discover user skills in ~/.tda/skills/ that have no registry entry.

        Three discovery modes:
          Mode A: Subdirectory with skill.json (manifest mode)
          Mode B: Subdirectory with .md but no skill.json (manifest-free)
          Mode C: Flat .md files directly in user_dir (manifest-free)
        """
        if not self.user_dir.exists():
            return 0

        loaded_ids = set(self.manifests.keys())
        auto_loaded = 0

        # Mode C: Flat .md files (zero friction — just drop a .md file)
        for md_file in sorted(self.user_dir.glob("*.md")):
            if md_file.name.startswith((".", "_")):
                continue

            skill_id = md_file.stem
            if skill_id in loaded_ids:
                continue

            # Auto-generate in-memory manifest from filename
            manifest = self._build_manifest_from_md(skill_id, md_file)
            self.manifests[skill_id] = manifest
            self.skill_dirs[skill_id] = self.user_dir
            auto_loaded += 1
            loaded_ids.add(skill_id)
            logger.info(f"Auto-discovered user skill: {skill_id} (flat .md)")

        # Mode A & B: Subdirectories
        for subdir in sorted(self.user_dir.iterdir()):
            if not subdir.is_dir() or subdir.name.startswith((".", "_")):
                continue

            skill_id = subdir.name
            if skill_id in loaded_ids:
                continue

            manifest_path = subdir / "skill.json"

            if manifest_path.exists():
                # Mode A: Manifest mode (Claude Code compatible)
                if self._load_skill(skill_id, subdir, is_user=True):
                    auto_loaded += 1
                    loaded_ids.add(skill_id)
                    logger.info(f"Auto-discovered user skill: {skill_id} (manifest mode)")
            else:
                # Mode B: Manifest-free (just .md file in a directory)
                md_files = list(subdir.glob("*.md"))
                if not md_files:
                    continue

                md_file = None
                for f in md_files:
                    if f.stem == subdir.name:
                        md_file = f
                        break
                if md_file is None:
                    md_file = md_files[0]

                manifest = self._build_manifest_from_md(skill_id, md_file)
                self.manifests[skill_id] = manifest
                self.skill_dirs[skill_id] = subdir
                auto_loaded += 1
                loaded_ids.add(skill_id)
                logger.info(f"Auto-discovered user skill: {skill_id} (manifest-free)")

        return auto_loaded

    def _build_manifest_from_md(self, skill_id: str, md_path: Path) -> Dict[str, Any]:
        """Build an in-memory manifest from a bare .md file."""
        # Try to extract description from first non-heading line
        description = ""
        try:
            lines = md_path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped[:200]
                    break
        except Exception:
            pass

        return {
            "name": skill_id,
            "version": "1.0.0",
            "description": description,
            "author": "User",
            "tags": [],
            "keywords": [],
            "use_cases": [],
            "main_file": md_path.name,
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "_is_user": True,
            "_auto_generated": True,
            "_dir": str(md_path.parent),
        }

    def _load_skill(
        self,
        skill_id: str,
        skill_dir: Path,
        is_user: bool = False,
    ) -> bool:
        """Load a single skill from its directory (must have skill.json)."""
        manifest_path = skill_dir / "skill.json"

        # Load manifest
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load manifest for skill '{skill_id}': {e}")
            return False

        # Use manifest name if available, fallback to directory name
        actual_name = manifest.get("name", skill_id)

        # Verify the .md file exists
        main_file = manifest.get("main_file", f"{actual_name}.md")
        md_path = skill_dir / main_file
        if not md_path.exists():
            # Try any .md file
            md_files = list(skill_dir.glob("*.md"))
            if not md_files:
                logger.warning(f"No markdown content found for skill '{skill_id}' in {skill_dir}")
                return False
            manifest["main_file"] = md_files[0].name

        # Store
        manifest["_is_user"] = is_user
        manifest["_dir"] = str(skill_dir)
        self.manifests[actual_name] = manifest
        self.skill_dirs[actual_name] = skill_dir

        source_label = "user" if is_user else "builtin"
        logger.info(f"Loaded skill: {actual_name} ({source_label})")
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_skills(
        self,
        specs: List[SkillSpec],
    ) -> SkillResult:
        """
        Resolve a list of skill specs into a SkillResult.

        Loads content for each requested skill, respecting params,
        and organizes by injection target.
        """
        result = SkillResult()

        for spec in specs:
            manifest = self.manifests.get(spec.name)
            if not manifest:
                logger.warning(f"Skill '{spec.name}' not found, skipping")
                continue

            skill_dir = self.skill_dirs.get(spec.name)
            if not skill_dir:
                logger.warning(f"Skill directory not found for '{spec.name}', skipping")
                continue

            content = load_skill_content(skill_dir, manifest, param=spec.param)
            if not content:
                logger.warning(f"Failed to load content for skill '{spec.name}', skipping")
                continue

            # Build delimited block
            label = f"{spec.name}:{spec.param}" if spec.param else spec.name
            block = f"--- Skill: {label} ---\n\n{content.content}"

            # Route to correct injection target
            if content.injection_target == "user_context":
                result.user_context_additions.append(block)
            else:
                result.system_prompt_additions.append(block)

            result.skill_contents[spec.name] = content

        return result

    def get_skill_manifest(self, name: str) -> Optional[Dict[str, Any]]:
        """Get the full manifest for a skill."""
        return self.manifests.get(name)

    def get_skill_content_preview(self, name: str, max_chars: int = 500) -> Optional[str]:
        """Get a preview of the skill's markdown content."""
        manifest = self.manifests.get(name)
        skill_dir = self.skill_dirs.get(name)
        if not manifest or not skill_dir:
            return None

        content = load_skill_content(skill_dir, manifest)
        if not content:
            return None

        if len(content.content) > max_chars:
            return content.content[:max_chars] + "..."
        return content.content

    def get_skill_full_content(self, name: str) -> Optional[str]:
        """Get the full raw markdown content of a skill (for editor)."""
        manifest = self.manifests.get(name)
        skill_dir = self.skill_dirs.get(name)
        if not manifest or not skill_dir:
            return None

        main_file = manifest.get("main_file", f"{name}.md")
        md_path = skill_dir / main_file
        if not md_path.exists():
            md_files = list(skill_dir.glob("*.md"))
            if not md_files:
                return None
            md_path = md_files[0]

        try:
            return md_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read content for skill '{name}': {e}")
            return None

    def list_skills(self) -> List[Dict[str, Any]]:
        """
        List all loaded skills with manifest metadata.
        Used for UI cards and autocomplete endpoints.
        """
        result = []
        for name, manifest in self.manifests.items():
            uderia_config = manifest.get("uderia", {})
            result.append({
                "skill_id": name,
                "name": manifest.get("name", name),
                "display_name": manifest.get("name", name).replace("-", " ").replace("_", " ").title(),
                "description": manifest.get("description", ""),
                "version": manifest.get("version", "1.0.0"),
                "author": manifest.get("author", "Unknown"),
                "tags": manifest.get("tags", []),
                "keywords": manifest.get("keywords", []),
                "use_cases": manifest.get("use_cases", []),
                "allowed_params": uderia_config.get("allowed_params", []),
                "param_descriptions": uderia_config.get("param_descriptions", {}),
                "injection_target": uderia_config.get("injection_target", "system_prompt"),
                "icon": uderia_config.get("icon", ""),
                "is_user": manifest.get("_is_user", False),
                "is_builtin": not manifest.get("_is_user", False),
                "auto_generated": manifest.get("_auto_generated", False),
                "last_updated": manifest.get("last_updated", ""),
                "status": "active",
            })
        return result

    def get_all_names(self) -> List[str]:
        """Get all registered skill names. Used for autocomplete."""
        return list(self.manifests.keys())

    def save_skill(
        self,
        name: str,
        content: str,
        manifest_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Save a skill to the user directory (~/.tda/skills/).

        Creates both the skill.json manifest and the .md content file.
        """
        target_dir = self.user_dir / name
        target_dir.mkdir(parents=True, exist_ok=True)

        # Build manifest
        if manifest_data is None:
            manifest_data = {}

        manifest = {
            "name": name,
            "version": manifest_data.get("version", "1.0.0"),
            "description": manifest_data.get("description", ""),
            "author": manifest_data.get("author", "User"),
            "tags": manifest_data.get("tags", []),
            "keywords": manifest_data.get("keywords", []),
            "use_cases": manifest_data.get("use_cases", []),
            "main_file": f"{name}.md",
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

        # Add uderia section if present
        uderia = manifest_data.get("uderia")
        if uderia:
            manifest["uderia"] = uderia

        try:
            # Write manifest
            (target_dir / "skill.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            # Write content
            (target_dir / f"{name}.md").write_text(content, encoding="utf-8")

            logger.info(f"Saved skill '{name}' to {target_dir}")
            self.reload()
            return True
        except Exception as e:
            logger.error(f"Failed to save skill '{name}': {e}")
            return False

    def delete_skill(self, name: str) -> bool:
        """Delete a user-created skill. Raises ValueError for builtins."""
        manifest = self.manifests.get(name)
        if not manifest:
            raise ValueError(f"Skill '{name}' not found")
        if not manifest.get("_is_user"):
            raise ValueError("Only user-created skills can be deleted")

        skill_dir = manifest.get("_dir")
        if skill_dir and Path(skill_dir).is_dir():
            shutil.rmtree(skill_dir)
            logger.info(f"Deleted skill directory: {skill_dir}")
        else:
            raise ValueError(f"Could not locate files for skill '{name}'")

        self.reload()
        return True

    def reload(self) -> None:
        """Hot-reload all skills from disk."""
        self.manifests.clear()
        self.skill_dirs.clear()
        self._load_registry()
        self._discover_and_load()
        logger.info("Skills reloaded")


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_instance: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    """Get or create the singleton SkillManager instance."""
    global _instance
    if _instance is None:
        _instance = SkillManager()
    return _instance
