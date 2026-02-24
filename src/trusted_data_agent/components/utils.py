"""Shared utilities for component HTML generation and payload extraction.

These functions consolidate logic that was previously duplicated across
executor.py, execution_service.py, conversation_agent.py, and
genie_coordinator.py — ensuring a single source of truth for the
component rendering contract.
"""

import json
import uuid
from typing import Any, Dict, List, Optional


def generate_component_html(component_payloads: List[Dict[str, Any]]) -> str:
    """Generate generic component HTML from extracted payloads.

    Produces ``<div data-component-id="..." data-spec='...'>`` containers
    that the frontend's ComponentRendererRegistry dispatches to the
    correct renderer.

    Used by all profile types (llm_only, rag_focused, genie) after
    component payloads have been extracted from tool output.
    """
    html = ""
    for _cp in component_payloads:
        # Skip sub_window payloads — they are delivered via SSE component_render events
        if _cp.get("render_target") == "sub_window":
            continue
        _comp_id = _cp.get("component_id", "unknown")
        _spec = _cp.get("spec", {})
        _cid = f"component-{uuid.uuid4().hex[:12]}"
        try:
            _spec_json = json.dumps(_spec).replace("'", "&apos;")
        except (TypeError, ValueError):
            continue
        html += (
            f'\n<div class="response-card mb-4">'
            f'<div id="{_cid}" data-component-id="{_comp_id}" '
            f"data-spec='{_spec_json}'></div>"
            f'</div>'
        )
    return html


def extract_component_payload(tool_output: Any) -> Optional[Dict[str, Any]]:
    """Parse tool output and extract a component render payload if present.

    Returns the parsed payload dict if it matches the component contract
    ``{status: "success", component_id: str, spec: dict}``, else ``None``.

    Handles both LangChain ToolMessage objects (with ``.content``) and
    plain strings.
    """
    try:
        _raw = tool_output.content if hasattr(tool_output, 'content') else str(tool_output)
        _parsed = json.loads(_raw)
        if (isinstance(_parsed, dict)
                and _parsed.get("status") == "success"
                and _parsed.get("component_id")
                and _parsed.get("spec")):
            return _parsed
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return None
