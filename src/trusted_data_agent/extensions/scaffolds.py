"""
Extension scaffolding templates.

Generates complete, working extension skeletons for each level.
Used by the scaffold API endpoint and the UI "Create Extension" button.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Level 0: Convention-based (flat .py file, zero friction)
# ---------------------------------------------------------------------------

CONVENTION_TEMPLATE = '''\
"""
#{name} extension — {description}

Drop this file in ~/.tda/extensions/ and reload.
No imports, no classes, no manifest needed.
"""

EXTENSION_NAME = "{name}"
EXTENSION_DESCRIPTION = "{description}"
# ALLOWED_PARAMS = {{"param1", "param2"}}  # Uncomment to restrict parameters
# CONTENT_TYPE = "application/json"         # Default: application/json
# OUTPUT_TARGET = "silent"                  # Options: silent, chat_append, status_panel


def transform(answer_text, param=None):
    """
    Transform the LLM answer into structured output.

    Args:
        answer_text: The LLM's plain-text response.
        param:       Optional parameter from #name:param syntax.

    Returns:
        A dict (for JSON) or str (for text) result.
    """
    # TODO: Replace this with your logic
    words = answer_text.split()
    return {{
        "word_count": len(words),
        "char_count": len(answer_text),
        "param": param,
    }}
'''

# ---------------------------------------------------------------------------
# Level 1: SimpleExtension (class-based, minimal)
# ---------------------------------------------------------------------------

SIMPLE_TEMPLATE = '''\
"""
#{name} extension — {description}

Tier: Simple (SimpleExtension)
Only override transform() — everything else is auto-wired.
"""

from trusted_data_agent.extensions import SimpleExtension


class {class_name}(SimpleExtension):

    name = "{name}"
    description = "{description}"
    # allowed_params = {{"param1", "param2"}}  # Uncomment to restrict parameters
    # content_type = "application/json"         # Default: application/json

    def transform(self, answer_text, param=None):
        """
        Transform the LLM answer into structured output.

        Args:
            answer_text: The LLM's plain-text response.
            param:       Optional parameter from #name:param syntax.

        Returns:
            A dict (for JSON) or str (for text) result.
        """
        # TODO: Replace this with your logic
        words = answer_text.split()
        return {{
            "word_count": len(words),
            "char_count": len(answer_text),
            "param": param,
        }}
'''

# ---------------------------------------------------------------------------
# Level 2: Standard Extension (full context access)
# ---------------------------------------------------------------------------

STANDARD_TEMPLATE = '''\
"""
#{name} extension — {description}

Tier: Standard (Extension)
Full access to ExtensionContext for advanced processing.
"""

from typing import Optional

from trusted_data_agent.extensions import Extension, ExtensionResult, ExtensionContext, OutputTarget


class {class_name}(Extension):

    @property
    def name(self) -> str:
        return "{name}"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT  # Change to CHAT_APPEND or STATUS_PANEL if needed

    def validate_param(self, param: Optional[str] = None) -> tuple[bool, Optional[str]]:
        # TODO: Add parameter validation if needed
        return True, None

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:
        """
        Full context available:
            context.answer_text        — plain text LLM answer
            context.answer_html        — HTML formatted answer
            context.original_query     — user's query with #tags
            context.clean_query        — query without #tags
            context.session_id         — session identifier
            context.turn_id            — turn number
            context.profile_tag        — active profile tag
            context.provider / .model  — LLM provider and model
            context.turn_input_tokens  — tokens used this turn
            context.execution_trace    — tool calls and results
            context.tools_used         — list of MCP tools used
            context.previous_extension_results — results from prior #extensions
        """
        # TODO: Replace this with your logic
        output = {{
            "query": context.clean_query,
            "answer_length": len(context.answer_text),
            "tools_used": context.tools_used,
            "param": param,
        }}

        return ExtensionResult(
            extension_name="{name}",
            content=output,
            content_type="application/json",
            metadata={{"param": param}},
        )
'''

# ---------------------------------------------------------------------------
# Level 3: LLM Extension (calls the session's LLM)
# ---------------------------------------------------------------------------

LLM_TEMPLATE = '''\
"""
#{name} extension — {description}

Tier: LLM (LLMExtension)
Calls the session's configured LLM with automatic cost tracking.
"""

import json
from typing import Optional

from trusted_data_agent.extensions import LLMExtension, ExtensionResult, ExtensionContext, OutputTarget
from trusted_data_agent.extensions.helpers import extract_json_from_text


SYSTEM_PROMPT = """You are a specialized analysis engine.
Analyze the provided text and return structured JSON.

Return valid JSON with these fields:
- "result": Your analysis result
- "confidence": A number between 0.0 and 1.0
- "reasoning": A brief explanation

Respond with JSON only, no markdown fences or extra text."""


class {class_name}(LLMExtension):

    name = "{name}"
    description = "{description}"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.SILENT  # Change to CHAT_APPEND to show in chat

    def validate_param(self, param: Optional[str] = None) -> tuple[bool, Optional[str]]:
        # TODO: Add parameter validation if needed
        return True, None

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:

        prompt = (
            f"Analyze this response:\\n\\n"
            f"**Query:** {{context.clean_query}}\\n\\n"
            f"**Answer:**\\n{{context.answer_text[:3000]}}"
        )

        try:
            raw_response = await self.call_llm(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                temperature=0.2,
                json_mode=True,
            )

            parsed = extract_json_from_text(raw_response)
            if parsed is None:
                parsed = json.loads(raw_response)

            output = {{
                "result": parsed.get("result", ""),
                "confidence": parsed.get("confidence", 0.0),
                "reasoning": parsed.get("reasoning", ""),
            }}

        except Exception as e:
            output = {{
                "result": "error",
                "confidence": 0.0,
                "reasoning": f"LLM analysis failed: {{str(e)}}",
            }}

        return ExtensionResult(
            extension_name="{name}",
            content=output,
            content_type="application/json",
            metadata={{"param": param}},
        )
'''

# ---------------------------------------------------------------------------
# Manifest template (for levels that use one)
# ---------------------------------------------------------------------------

MANIFEST_TEMPLATE = {
    "name": "{name}-extension",
    "version": "1.0.0",
    "extension_id": "{name}",
    "display_name": "{display_name}",
    "description": "{description}",
    "author": "User",
    "license": "MIT",
    "category": "Custom",
    "extension_tier": "{tier}",
    "requires_llm": False,
    "keywords": [],
    "files": {
        "extension": "{name}.py"
    },
    "output_target": "silent",
    "parameters": {
        "supported": True,
        "description": "Extension parameter"
    },
    "output_schema": {},
    "metadata": {
        "tags": ["custom"]
    }
}


def generate_scaffold(
    name: str,
    level: str = "convention",
    description: str = "",
    parameters: Optional[list] = None,
) -> dict:
    """
    Generate extension files for the given level.

    Args:
        name:        Extension name (lowercase, no spaces).
        level:       One of "convention", "simple", "standard", "llm".
        description: One-line description.
        parameters:  Optional list of valid parameter values.

    Returns:
        {"path": str, "files": {filename: content}}
    """
    user_dir = Path.home() / ".tda" / "extensions"
    class_name = "".join(word.capitalize() for word in name.split("_")) + "Extension"
    display_name = name.replace("_", " ").title()
    desc = description or f"Custom {name} extension"

    format_vars = {
        "name": name,
        "class_name": class_name,
        "display_name": display_name,
        "description": desc,
    }

    files = {}

    if level == "convention":
        # Flat file, no directory
        path = user_dir / f"{name}.py"
        files[f"{name}.py"] = CONVENTION_TEMPLATE.format(**format_vars)
        return {"path": str(path.parent), "files": files}

    # All other levels use a directory
    path = user_dir / name

    if level == "simple":
        files[f"{name}.py"] = SIMPLE_TEMPLATE.format(**format_vars)

    elif level == "standard":
        files[f"{name}.py"] = STANDARD_TEMPLATE.format(**format_vars)
        manifest = dict(MANIFEST_TEMPLATE)
        manifest["extension_tier"] = "standard"
        manifest_str = json.dumps(manifest, indent=2)
        for k, v in format_vars.items():
            manifest_str = manifest_str.replace(f"{{{k}}}", v)
        manifest_str = manifest_str.replace('"requires_llm": false', '"requires_llm": false')
        files["manifest.json"] = manifest_str

    elif level == "llm":
        files[f"{name}.py"] = LLM_TEMPLATE.format(**format_vars)
        manifest = dict(MANIFEST_TEMPLATE)
        manifest["extension_tier"] = "llm"
        manifest["requires_llm"] = True
        manifest_str = json.dumps(manifest, indent=2)
        for k, v in format_vars.items():
            manifest_str = manifest_str.replace(f"{{{k}}}", v)
        manifest_str = manifest_str.replace('"requires_llm": false', '"requires_llm": true')
        files["manifest.json"] = manifest_str

    else:
        raise ValueError(f"Unknown level: {level}. Valid: convention, simple, standard, llm")

    return {"path": str(path), "files": files}


def write_scaffold(
    name: str,
    level: str = "convention",
    description: str = "",
    parameters: Optional[list] = None,
) -> dict:
    """
    Generate AND write extension files to disk.

    Returns:
        {"path": str, "files": [filenames], "level": str}
    """
    result = generate_scaffold(name, level, description, parameters)
    target_path = Path(result["path"])

    if level == "convention":
        # Flat file
        target_path.mkdir(parents=True, exist_ok=True)
        file_path = target_path / f"{name}.py"
        file_path.write_text(result["files"][f"{name}.py"], encoding="utf-8")
    else:
        # Directory with files
        target_path.mkdir(parents=True, exist_ok=True)
        for filename, content in result["files"].items():
            (target_path / filename).write_text(content, encoding="utf-8")

    return {
        "path": str(target_path if level != "convention" else target_path / f"{name}.py"),
        "files": list(result["files"].keys()),
        "level": level,
    }
