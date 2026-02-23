"""
Chart Component Handler.

Processes TDA_Charting tool calls into G2Plot render specifications.
Extracted from adapter.py (_build_g2plot_spec, _transform_chart_data).

Chart type registry is loaded from manifest.json at import time, making it
extensible without code changes — add new entries to ``chart_types`` in the
manifest and restart.
"""

import json as _json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from trusted_data_agent.components.base import (
    BaseComponentHandler,
    ComponentRenderPayload,
    RenderTarget,
)

logger = logging.getLogger("quart.app")

# ---------------------------------------------------------------------------
# Chart type registry — loaded once from the co-located manifest.json
# ---------------------------------------------------------------------------

_MANIFEST_PATH = Path(__file__).parent / "manifest.json"
try:
    _MANIFEST = _json.loads(_MANIFEST_PATH.read_text())
except Exception:
    _MANIFEST = {}

_CHART_TYPES: Dict[str, Dict[str, Any]] = _MANIFEST.get("chart_types", {})

# ---------------------------------------------------------------------------
# Column classification patterns — used by the mapping resolver
# ---------------------------------------------------------------------------

_TEMPORAL_PATTERN = re.compile(
    r"(hour|day|month|year|date|time|period|week|quarter|minute|second)"
    r"|(_at$|_on$|_date$|_time$)",
    re.IGNORECASE,
)

_METRIC_PATTERN = re.compile(
    r"(count|total|sum|avg|average|mean|min|max|rate|ratio|percent|pct"
    r"|amount|cost|price|revenue|profit|volume|quantity|usage|utilization"
    r"|bytes|kb|mb|io|cpu|memory|latency|duration|size)",
    re.IGNORECASE,
)


class ChartComponentHandler(BaseComponentHandler):
    """Handler for the TDA_Charting tool — builds G2Plot specs from LLM arguments."""

    @property
    def component_id(self) -> str:
        return "chart"

    @property
    def tool_name(self) -> str:
        return "TDA_Charting"

    @property
    def is_deterministic(self) -> bool:
        return True

    def validate_arguments(self, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        data = arguments.get("data")
        if not isinstance(data, list) or not data:
            if isinstance(data, list) and not data:
                return False, "The 'data' argument was an empty list. Cannot generate chart without data."
            return False, "The 'data' argument must be a non-empty list of dictionaries."
        if not all(isinstance(item, dict) for item in data):
            return False, "Transformed 'data' is not a list of dictionaries."
        return True, ""

    async def process(
        self,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ComponentRenderPayload:
        """Build a G2Plot spec from tool arguments and return a render payload."""
        data = arguments.get("data", [])

        # Robust data transformation (handles hallucinated formats)
        data = _transform_chart_data(data)
        arguments["data"] = data

        # Validate after transformation
        is_valid, error = self.validate_arguments(arguments)
        if not is_valid:
            return ComponentRenderPayload(
                component_id=self.component_id,
                render_target=RenderTarget.INLINE,
                spec={"error": error},
                metadata={"tool_name": self.tool_name, "status": "error"},
            )

        chart_type = arguments.get("chart_type", "bar").lower()

        # --- Intelligent mapping resolution (all chart types) ---
        mapping_meta: Dict[str, Any] = {}
        if data:
            existing_mapping = arguments.get("mapping") or {}
            chart_entry = _CHART_TYPES.get(chart_type, {})
            required_roles = chart_entry.get("mapping_roles", ["x_axis", "y_axis"])

            if not _is_mapping_complete(existing_mapping, required_roles, data):
                resolved_mapping, needs_melt, mapping_meta = await _resolve_chart_mapping(
                    chart_type, data, existing_mapping, context,
                )

                if needs_melt:
                    x_col = resolved_mapping.get("x_axis", list(data[0].keys())[0])
                    metric_cols = [c for c in data[0].keys() if c != x_col]
                    original_shape = f"{len(data)} rows x {len(data[0])} columns"
                    data = _melt_wide_to_long(data, x_col, metric_cols)
                    arguments["data"] = data
                    mapping_meta["auto_melt"] = True
                    mapping_meta["original_shape"] = original_shape
                    mapping_meta["melted_shape"] = f"{len(data)} cells"

                arguments["mapping"] = resolved_mapping
                logger.info(
                    f"Chart mapping resolved ({mapping_meta.get('approach', 'unknown')}): "
                    f"{resolved_mapping}"
                )

        try:
            chart_spec = _build_g2plot_spec(arguments, data)
        except Exception as e:
            logger.error(f"Error building G2Plot spec: {e}", exc_info=True)
            return ComponentRenderPayload(
                component_id=self.component_id,
                render_target=RenderTarget.INLINE,
                spec={"error": str(e)},
                metadata={"tool_name": self.tool_name, "status": "error"},
            )

        title = arguments.get("title", "Generated Chart")

        metadata: Dict[str, Any] = {
            "tool_name": self.tool_name,
            "chart_type": chart_type,
            "row_count": len(data),
        }
        if mapping_meta:
            metadata["mapping_resolution"] = mapping_meta
        if mapping_meta.get("approach") == "llm_assisted":
            metadata["llm_input_tokens"] = mapping_meta.get("llm_input_tokens", 0)
            metadata["llm_output_tokens"] = mapping_meta.get("llm_output_tokens", 0)

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.INLINE,
            spec=chart_spec,
            title=title,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Data transformation helpers (extracted from adapter.py)
# ---------------------------------------------------------------------------


def _transform_chart_data(data: Any) -> list:
    """
    Normalize chart data into a flat list of dicts.

    Handles several hallucinated/nested formats that LLMs produce:
    - Nested tool output: [{results: [...]}, {results: [...]}]
    - Labels/values format: {labels: [...], values: [...]}
    - Columns/rows format: {columns: [...], rows: [...]}
    - qlty_distinctCategories output renaming
    """
    # Nested tool output
    if isinstance(data, list) and all(
        isinstance(item, dict) and "results" in item for item in data
    ):
        logger.info("Detected nested tool output. Flattening data for charting.")
        flattened = []
        for item in data:
            results_list = item.get("results")
            if isinstance(results_list, list):
                flattened.extend(results_list)
        return flattened

    # Labels/values hallucination
    if isinstance(data, dict) and "labels" in data and "values" in data:
        logger.warning(
            "Correcting hallucinated chart data format from labels/values to list of dicts."
        )
        labels = data.get("labels", [])
        values = data.get("values", [])
        if (
            isinstance(labels, list)
            and isinstance(values, list)
            and len(labels) == len(values)
        ):
            return [{"label": l, "value": v} for l, v in zip(labels, values)]

    # Columns/rows hallucination
    if isinstance(data, dict) and "columns" in data and "rows" in data:
        logger.warning(
            "Correcting hallucinated chart data format from columns/rows to list of dicts."
        )
        if isinstance(data.get("rows"), list):
            return data["rows"]

    # qlty_distinctCategories output renaming
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if (
            "ColumnName" in data[0]
            and "DistinctValue" in data[0]
            and "DistinctValueCount" in data[0]
        ):
            logger.info(
                "Detected qlty_distinctCategories output pattern. "
                "Renaming 'ColumnName' to 'SourceColumnName'."
            )
            transformed = []
            for row in data:
                new_row = row.copy()
                if "ColumnName" in new_row:
                    new_row["SourceColumnName"] = new_row.pop("ColumnName")
                transformed.append(new_row)
            return transformed

    return data


def _build_g2plot_spec(args: dict, data: list) -> dict:
    """
    Build a G2Plot specification from LLM arguments and chart data.

    Maps the LLM's semantic role names (x_axis, y_axis, color, angle, size)
    to G2Plot field names (xField, yField, seriesField, angleField, colorField).
    """
    chart_type = args.get("chart_type", "").lower()
    mapping = args.get("mapping", {})

    canonical_map = {
        "x_axis": "xField",
        "y_axis": "yField",
        "color": "seriesField",
        "angle": "angleField",
        "category": "xField",
        "value": "yField",
    }

    # Reverse lookup from alias (lowercase) to G2Plot key
    reverse_canonical_map = {}
    for canonical, g2plot_key in canonical_map.items():
        reverse_canonical_map[canonical.lower()] = g2plot_key
        if canonical == "x_axis":
            reverse_canonical_map["category"] = g2plot_key
        if canonical == "y_axis":
            reverse_canonical_map["value"] = g2plot_key

    options = {"title": {"text": args.get("title", "Generated Chart")}}

    first_row_keys_lower = (
        {k.lower(): k for k in data[0].keys()} if data and data[0] else {}
    )

    processed_mapping = {}
    for llm_key, data_col_name in mapping.items():
        g2plot_key = reverse_canonical_map.get(llm_key.lower())
        if g2plot_key:
            actual_col_name = first_row_keys_lower.get(data_col_name.lower())
            if not actual_col_name:
                raise KeyError(
                    f"The mapped column '{data_col_name}' (from '{llm_key}') "
                    f"was not found in the provided data."
                )
            processed_mapping[g2plot_key] = actual_col_name
        else:
            logger.warning(f"Unknown mapping key from LLM: '{llm_key}'. Skipping.")

    options.update(processed_mapping)

    # Pie and heatmap use colorField instead of seriesField
    if chart_type in ("pie", "heatmap") and "seriesField" in options:
        options["colorField"] = options.pop("seriesField")

    # Ensure numeric fields are actually numbers
    final_data = []
    if data:
        numeric_keys = set()
        for g2plot_key, actual_col_name in options.items():
            if g2plot_key in ("yField", "angleField", "sizeField", "value", "colorField"):
                # For heatmap, yField is categorical (metric name) — skip numeric coercion
                if chart_type == "heatmap" and g2plot_key == "yField":
                    continue
                numeric_keys.add(actual_col_name)

        for row in data:
            new_row = row.copy()
            for col_name in numeric_keys:
                cell_value = new_row.get(col_name)
                if cell_value is not None:
                    try:
                        new_row[col_name] = float(str(cell_value).replace(",", ""))
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Non-numeric value '{cell_value}' for field '{col_name}'. "
                            f"Conversion failed."
                        )
            final_data.append(new_row)

    options["data"] = final_data

    # Look up the G2Plot type from the manifest registry.
    # Fallback: capitalize() — so any G2Plot chart type is reachable even if
    # not explicitly registered in the manifest.
    chart_entry = _CHART_TYPES.get(chart_type, {})
    g2plot_type = chart_entry.get("g2plot_type", chart_type.capitalize())

    return {"type": g2plot_type, "options": options}


# ---------------------------------------------------------------------------
# Intelligent mapping resolver — manifest-driven, hybrid heuristic + LLM
# ---------------------------------------------------------------------------


def _is_numeric_value(val: Any) -> bool:
    """Check if a value is numeric (int, float, or numeric string)."""
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str):
        try:
            float(val.replace(",", ""))
            return True
        except (ValueError, TypeError):
            return False
    return False


def _classify_columns(data: List[dict]) -> Dict[str, List[str]]:
    """Classify data columns into temporal, metric, dimension, or ambiguous."""
    first_row = data[0]
    result: Dict[str, List[str]] = {
        "temporal": [],
        "metric": [],
        "dimension": [],
        "ambiguous": [],
    }

    for col, val in first_row.items():
        is_num = _is_numeric_value(val)

        if _TEMPORAL_PATTERN.search(col):
            result["temporal"].append(col)
        elif _METRIC_PATTERN.search(col):
            result["metric"].append(col)
        elif not is_num:
            result["dimension"].append(col)
        else:
            # Numeric value with no recognizable name pattern
            result["ambiguous"].append(col)

    return result


def _is_mapping_complete(
    mapping: Dict[str, str],
    required_roles: List[str],
    data: List[dict],
    allow_synthetic: bool = False,
) -> bool:
    """Check if all required roles are filled and mapped columns exist in data."""
    if not mapping:
        return False
    if not all(mapping.get(role) for role in required_roles):
        return False
    if allow_synthetic:
        return True  # Synthetic columns (Metric/Value) will be created by melt
    first_row_keys_lower = {k.lower() for k in data[0]} if data else set()
    return all(
        mapping[r].lower() in first_row_keys_lower
        for r in required_roles
        if mapping.get(r)
    )


def _assign_roles(
    chart_type: str,
    required_roles: List[str],
    optional_roles: List[str],
    classified: Dict[str, List[str]],
    data: List[dict],
) -> Dict[str, Any]:
    """Assign columns to chart roles based on classification and manifest requirements."""
    mapping: Dict[str, Any] = {}
    ct = chart_type.lower()
    x_candidates = classified["temporal"] + classified["dimension"]
    all_numeric = classified["metric"] + classified["ambiguous"]

    # --- Heatmap: may need wide→long melt ---
    if ct == "heatmap":
        if x_candidates and len(all_numeric) >= 2:
            mapping = {
                "x_axis": x_candidates[0],
                "y_axis": "Metric",
                "color": "Value",
                "_needs_melt": True,
            }
        elif len(x_candidates) >= 2 and all_numeric:
            mapping = {
                "x_axis": x_candidates[0],
                "y_axis": x_candidates[1],
                "color": all_numeric[0],
            }
        elif len(all_numeric) >= 3:
            mapping = {
                "x_axis": all_numeric[0],
                "y_axis": "Metric",
                "color": "Value",
                "_needs_melt": True,
            }
        return mapping

    # --- Pie: angle (numeric) + color (categorical) ---
    if ct == "pie":
        if all_numeric:
            mapping["angle"] = all_numeric[0]
        cat = classified["dimension"] + classified["temporal"]
        if cat:
            mapping["color"] = cat[0]
        return mapping

    # --- Gauge: single value ---
    if ct == "gauge":
        if all_numeric:
            mapping["value"] = all_numeric[0]
        return mapping

    # --- Scatter: prefers two numeric columns ---
    if ct == "scatter":
        if len(all_numeric) >= 2:
            mapping["x_axis"] = all_numeric[0]
            mapping["y_axis"] = all_numeric[1]
        elif x_candidates and all_numeric:
            mapping["x_axis"] = x_candidates[0]
            mapping["y_axis"] = all_numeric[0]
        return mapping

    # --- Default: bar/column/line/area/histogram/boxplot/waterfall/
    #     radar/rose/funnel/wordcloud/treemap/dualaxes ---
    used: set = set()
    if "x_axis" in required_roles:
        if x_candidates:
            mapping["x_axis"] = x_candidates[0]
            used.add(x_candidates[0])
        elif all_numeric:
            mapping["x_axis"] = all_numeric[0]
            used.add(all_numeric[0])

    if "y_axis" in required_roles:
        y_pool = [c for c in all_numeric if c not in used]
        if y_pool:
            mapping["y_axis"] = y_pool[0]
            used.add(y_pool[0])

    if "color" in optional_roles:
        remaining_cats = [c for c in x_candidates if c not in used]
        if remaining_cats:
            mapping["color"] = remaining_cats[0]

    return mapping


def _positional_fallback(
    chart_type: str, required_roles: List[str], data: List[dict],
) -> Dict[str, Any]:
    """Best-effort positional assignment: first column = first role, etc."""
    columns = list(data[0].keys()) if data else []
    mapping: Dict[str, Any] = {}
    for i, role in enumerate(required_roles):
        if i < len(columns):
            mapping[role] = columns[i]
    # Heatmap with many columns: melt
    if chart_type.lower() == "heatmap" and len(columns) > 3:
        mapping = {
            "x_axis": columns[0],
            "y_axis": "Metric",
            "color": "Value",
            "_needs_melt": True,
        }
    return mapping


async def _resolve_chart_mapping(
    chart_type: str,
    data: List[dict],
    mapping: Optional[Dict[str, str]],
    context: Dict[str, Any],
) -> Tuple[Dict[str, str], bool, Dict[str, Any]]:
    """
    Resolve chart mapping for ANY chart type using a 3-tier strategy:

    1. Validate existing mapping against manifest roles
    2. Smart deterministic classification + manifest-driven role assignment
    3. LLM fallback (only if required roles remain unfilled + ambiguous columns exist)

    Returns ``(mapping, needs_melt, approach_metadata)``.
    """
    chart_entry = _CHART_TYPES.get(chart_type.lower(), {})
    required_roles = chart_entry.get("mapping_roles", ["x_axis", "y_axis"])
    optional_roles = chart_entry.get("optional_roles", [])

    # --- Tier 1: Validate existing mapping completeness ---
    if mapping and _is_mapping_complete(mapping, required_roles, data):
        return mapping, False, {"approach": "user_provided"}

    # --- Tier 2: Deterministic classification + role assignment ---
    classified = _classify_columns(data)
    resolved = _assign_roles(chart_type, required_roles, optional_roles, classified, data)

    if resolved:
        needs_melt = resolved.pop("_needs_melt", False)
        if _is_mapping_complete(resolved, required_roles, data, allow_synthetic=needs_melt):
            return resolved, needs_melt, {
                "approach": "heuristic",
                "classified": classified,
                "final_mapping": dict(resolved),
            }

    # --- Tier 3: LLM fallback (ambiguous columns AND unfilled required roles) ---
    llm_callable = context.get("llm_callable")
    if llm_callable and classified.get("ambiguous"):
        llm_result, tokens = await _resolve_mapping_via_llm(
            chart_type, required_roles, data, classified, llm_callable,
        )
        if llm_result:
            needs_melt = llm_result.pop("_needs_melt", False) or llm_result.pop("needs_melt", False)
            return llm_result, needs_melt, {
                "approach": "llm_assisted",
                "llm_input_tokens": tokens[0],
                "llm_output_tokens": tokens[1],
                "classified": classified,
                "final_mapping": dict(llm_result),
            }

    # --- Tier 3b: Positional fallback (best effort) ---
    fallback = _positional_fallback(chart_type, required_roles, data)
    needs_melt = fallback.pop("_needs_melt", False)
    return fallback, needs_melt, {
        "approach": "heuristic_positional",
        "classified": classified,
        "final_mapping": dict(fallback),
    }


# ---------------------------------------------------------------------------
# Wide→Long data transformation (melt)
# ---------------------------------------------------------------------------


def _sort_key(val: Any) -> Tuple:
    """Sort numerically if possible, otherwise lexicographically."""
    try:
        return (0, float(str(val).replace(",", "")))
    except (ValueError, TypeError):
        return (1, str(val))


def _melt_wide_to_long(
    data: List[dict], x_col: str, metric_cols: List[str],
) -> List[dict]:
    """
    Transform wide-format data to long-format for heatmap rendering.

    Input:  [{hourOfDay: "5", "Request Count": "781", "AMPCPUTime": "34.78"}, ...]
    Output: [{hourOfDay: "5", Metric: "Request Count", Value: 781.0}, ...]
    """
    melted: List[dict] = []
    for row in data:
        for metric in metric_cols:
            try:
                val = float(str(row.get(metric, 0)).replace(",", ""))
            except (ValueError, TypeError):
                val = 0.0
            melted.append({x_col: row[x_col], "Metric": metric, "Value": val})

    # Sort by x_axis for proper heatmap visual ordering
    melted.sort(key=lambda r: _sort_key(r[x_col]))
    logger.info(
        f"Melted wide-format data: {len(data)} rows x {len(metric_cols)} metrics "
        f"→ {len(melted)} cells"
    )
    return melted


# ---------------------------------------------------------------------------
# LLM-assisted mapping resolution (fallback for ambiguous columns)
# ---------------------------------------------------------------------------


async def _resolve_mapping_via_llm(
    chart_type: str,
    required_roles: List[str],
    data: List[dict],
    classified: Dict[str, List[str]],
    llm_callable: Any,
) -> Tuple[Optional[Dict[str, str]], Tuple[int, int]]:
    """Small LLM call to resolve ambiguous column roles (~300 in, ~80 out tokens)."""
    first_row = data[0]
    col_lines = []
    for col, val in first_row.items():
        cat = "ambiguous"
        for c in ("temporal", "metric", "dimension"):
            if col in classified[c]:
                cat = c
                break
        col_lines.append(f"  - {col}: sample={repr(val)}, auto_detected={cat}")

    roles_str = ", ".join(required_roles)
    prompt = (
        f"Chart type: {chart_type}\n"
        f"Required mapping roles: {roles_str}\n"
        f"Data columns:\n" + "\n".join(col_lines) + "\n\n"
        f"Assign each required role to a column name. If the data is wide-format "
        f"(many metric columns, one dimension), set needs_melt=true.\n"
        f"Respond ONLY with JSON: {{" + ", ".join(f'"{r}": "col"' for r in required_roles)
        + ', "needs_melt": false}'
    )

    try:
        result = await llm_callable(
            prompt,
            system_prompt="You are a data visualization expert. Respond with JSON only.",
            max_tokens=200,
        )
        content = result.get("content", "")
        # Extract JSON from response (tolerant of surrounding text)
        json_start = content.index("{")
        json_end = content.rindex("}") + 1
        parsed = _json.loads(content[json_start:json_end])
        tokens = (result.get("input_tokens", 0), result.get("output_tokens", 0))
        logger.info(f"LLM mapping resolution succeeded: {parsed} (tokens: {tokens})")
        return parsed, tokens
    except Exception as e:
        logger.warning(f"LLM mapping resolution failed: {e}")
        return None, (0, 0)
