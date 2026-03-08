"""
Skill Loader: Reads markdown content and resolves param-specific blocks.

Handles the full loading pipeline:
  1. Read the markdown file referenced by main_file in skill.json
  2. If a param is specified, extract base content + matching param block
  3. If no param, extract base content only (outside param blocks)
  4. Return SkillContent with resolved text and injection_target

Param blocks use HTML comment syntax (invisible to Claude Code):
  <!-- param:strict -->
  Content for strict mode...
  <!-- /param:strict -->
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from trusted_data_agent.skills.models import SkillContent

logger = logging.getLogger("quart.app")

# Regex for matching param blocks: <!-- param:NAME --> ... <!-- /param:NAME -->
_PARAM_BLOCK_RE = re.compile(
    r"<!--\s*param:(\w+)\s*-->(.*?)<!--\s*/param:\1\s*-->",
    re.DOTALL,
)

# Regex for stripping ALL param blocks (to get base content)
_ALL_PARAM_BLOCKS_RE = re.compile(
    r"<!--\s*param:\w+\s*-->.*?<!--\s*/param:\w+\s*-->",
    re.DOTALL,
)


def load_skill_content(
    skill_dir: Path,
    manifest: Dict[str, Any],
    param: Optional[str] = None,
) -> Optional[SkillContent]:
    """
    Load skill content from a directory.

    Args:
        skill_dir: Path to the skill directory.
        manifest: The parsed skill.json manifest.
        param: Optional parameter to include param-specific content.

    Returns:
        SkillContent with resolved markdown, or None on error.
    """
    main_file = manifest.get("main_file")
    if not main_file:
        # Fallback: look for any .md file matching skill name
        skill_name = manifest.get("name", skill_dir.name)
        main_file = f"{skill_name}.md"

    md_path = skill_dir / main_file
    if not md_path.exists():
        # Try any .md file in the directory
        md_files = list(skill_dir.glob("*.md"))
        if md_files:
            md_path = md_files[0]
        else:
            logger.warning(f"No markdown file found for skill in {skill_dir}")
            return None

    try:
        raw_content = md_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read skill content from {md_path}: {e}")
        return None

    # Resolve content based on param
    content = _resolve_content(raw_content, param)

    # Get injection target from uderia-specific manifest section
    uderia_config = manifest.get("uderia", {})
    injection_target = uderia_config.get("injection_target", "system_prompt")

    # Validate param against allowed_params
    if param:
        allowed_params = uderia_config.get("allowed_params", [])
        if allowed_params and param not in allowed_params:
            logger.warning(
                f"Param '{param}' not in allowed_params {allowed_params} "
                f"for skill '{manifest.get('name', skill_dir.name)}'. "
                f"Using base content only."
            )
            content = _resolve_content(raw_content, None)

    skill_name = manifest.get("name", skill_dir.name)

    return SkillContent(
        skill_name=skill_name,
        content=content,
        injection_target=injection_target,
        metadata=manifest,
        param=param,
    )


def _resolve_content(raw: str, param: Optional[str]) -> str:
    """
    Resolve skill content based on the requested param.

    - No param: strip ALL param blocks, return base content only
    - With param: strip other param blocks, include base + matching block
    """
    if not param:
        # Remove all param blocks, keep only base content
        base = _ALL_PARAM_BLOCKS_RE.sub("", raw)
        return base.strip()

    # Extract the matching param block
    param_content = None
    for match in _PARAM_BLOCK_RE.finditer(raw):
        if match.group(1) == param:
            param_content = match.group(2).strip()
            break

    # Base content = raw with all param blocks stripped
    base = _ALL_PARAM_BLOCKS_RE.sub("", raw).strip()

    if param_content:
        return f"{base}\n\n{param_content}"
    else:
        # Param not found — just return base
        logger.debug(f"Param block '{param}' not found in content, using base only")
        return base


def extract_param_blocks(raw: str) -> Dict[str, str]:
    """
    Extract all param blocks from skill content.
    Returns dict of {param_name: block_content}.
    Used by the editor to show param-specific sections.
    """
    blocks = {}
    for match in _PARAM_BLOCK_RE.finditer(raw):
        blocks[match.group(1)] = match.group(2).strip()
    return blocks


def get_base_content(raw: str) -> str:
    """
    Get the base content (everything outside param blocks).
    Used by the editor to show base instructions.
    """
    return _ALL_PARAM_BLOCKS_RE.sub("", raw).strip()


def build_full_content(base: str, param_blocks: Dict[str, str]) -> str:
    """
    Reconstruct full markdown from base content and param blocks.
    Used by the editor when saving from intermediate/expert level.
    """
    parts = [base.strip()]
    for name, content in param_blocks.items():
        parts.append(f"\n\n<!-- param:{name} -->\n{content.strip()}\n<!-- /param:{name} -->")
    return "\n".join(parts)
