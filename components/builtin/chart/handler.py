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
from dataclasses import dataclass, field
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

# ---------------------------------------------------------------------------
# Mapping pipeline data structures
# ---------------------------------------------------------------------------

_CAMEL_CASE_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@dataclass
class MappingValidation:
    """Diagnostic result from _validate_mapping."""

    is_valid: bool
    missing_required: List[str] = field(default_factory=list)
    bad_columns: Dict[str, str] = field(default_factory=dict)
    swapped_axes: bool = False
    duplicate_columns: List[str] = field(default_factory=list)


@dataclass
class MappingResult:
    """Output of the mapping pipeline."""

    mapping: Dict[str, str] = field(default_factory=dict)
    needs_melt: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)


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
        # Sort and limit (handles 'top N' / 'bottom N' queries)
        data = _apply_data_filters(data, arguments)
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

        chart_type = (arguments.get("chart_type") or "bar").lower()

        # --- Mapping validation & repair pipeline (always runs) ---
        mapping_meta: Dict[str, Any] = {}
        if data:
            raw_mapping = arguments.get("mapping") or {}
            result = await _resolve_and_validate_mapping(
                chart_type, data, raw_mapping, context,
            )

            if result.needs_melt:
                x_col = result.mapping.get("x_axis", list(data[0].keys())[0])
                metric_cols = [c for c in data[0].keys() if c != x_col]
                original_shape = f"{len(data)} rows x {len(data[0])} columns"
                data = _melt_wide_to_long(data, x_col, metric_cols)
                arguments["data"] = data
                result.meta["auto_melt"] = True
                result.meta["original_shape"] = original_shape
                result.meta["melted_shape"] = f"{len(data)} cells"

            arguments["mapping"] = result.mapping
            mapping_meta = result.meta
            logger.info(
                f"Chart mapping ({mapping_meta.get('resolved_by', 'unknown')}): "
                f"{result.mapping}"
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
        if mapping_meta.get("resolved_by") == "llm_assisted":
            metadata["llm_input_tokens"] = mapping_meta.get("llm_input_tokens", 0)
            metadata["llm_output_tokens"] = mapping_meta.get("llm_output_tokens", 0)
        # Propagate piggybacked Live Status events for the SSE stream
        if "_component_llm_events" in mapping_meta:
            metadata["_component_llm_events"] = mapping_meta["_component_llm_events"]

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


def _apply_data_filters(data: list, arguments: Dict[str, Any]) -> list:
    """
    Apply sorting and row limiting to chart data.

    Called after _transform_chart_data() but before mapping resolution.
    Handles 'top N' / 'bottom N' queries where the data-gathering tool
    returned more rows than the user requested.
    """
    if not data or not isinstance(data, list) or not isinstance(data[0], dict):
        return data

    sort_by = arguments.get("sort_by")
    sort_dir = (arguments.get("sort_direction") or "desc").lower()
    row_limit = arguments.get("row_limit")

    # Sort
    if sort_by and sort_by in data[0]:
        reverse = sort_dir != "asc"

        def sort_key(row):
            val = row.get(sort_by)
            if val is None:
                return (1, 0)  # None values last
            if isinstance(val, (int, float)):
                return (0, val)
            try:
                return (0, float(val))
            except (ValueError, TypeError):
                return (0, str(val))

        data = sorted(data, key=sort_key, reverse=reverse)
        logger.info(f"Chart data sorted by '{sort_by}' {sort_dir}: {len(data)} rows")

    # Limit
    if row_limit is not None:
        try:
            row_limit = int(row_limit)
        except (ValueError, TypeError):
            row_limit = None
    if row_limit and row_limit > 0:
        original_count = len(data)
        data = data[:row_limit]
        if original_count > row_limit:
            logger.info(f"Chart data limited: {original_count} → {row_limit} rows")

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
        # Defense-in-depth: pipeline guarantees clean input, but guard anyway
        if not isinstance(data_col_name, str) or not data_col_name:
            logger.warning(
                f"Skipping mapping key '{llm_key}': column name is {data_col_name!r}"
            )
            continue
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


def _has_multiple_values(col: str, data: List[dict], sample_size: int = 50) -> bool:
    """
    Check if a column has more than one unique value (early-exit sampling).

    A column where every row has the same value (e.g., SourceColumnName = "ProductType"
    in qlty_distinctCategories output) is metadata — not a chartable dimension.
    Used by ``_assign_roles()`` and ``_repair_mapping_deterministic()`` to filter
    out constant-value columns that would collapse a chart to a single category.
    """
    sample = data[:sample_size]
    if len(sample) < 2:
        return False
    first_val = str(sample[0].get(col, ""))
    return any(str(row.get(col, "")) != first_val for row in sample[1:])


# ---------------------------------------------------------------------------
# Stage 1: Sanitize mapping — strip garbage values
# ---------------------------------------------------------------------------


def _sanitize_mapping(
    mapping: Dict[str, Any], chart_type: str,
) -> Tuple[Dict[str, str], List[str]]:
    """
    Strip invalid entries from an LLM-provided mapping.

    Drops: None values, empty strings, non-string values, unknown role keys,
    internal keys (prefixed with ``_``).  Returns ``(clean_mapping, actions)``.
    """
    chart_entry = _CHART_TYPES.get(chart_type.lower(), {})
    valid_roles = set(chart_entry.get("mapping_roles", [])) | set(
        chart_entry.get("optional_roles", [])
    )
    # Always accept the universal role keys even if the manifest doesn't list them
    valid_roles |= {"x_axis", "y_axis", "color", "angle", "size", "value"}

    clean: Dict[str, str] = {}
    actions: List[str] = []

    for key, val in mapping.items():
        if key.startswith("_"):
            actions.append(f"dropped {key}: internal key")
            continue
        if key not in valid_roles:
            actions.append(f"dropped {key}: not a valid role")
            continue
        if not isinstance(val, str) or not val.strip():
            actions.append(f"dropped {key}: {val!r}")
            continue
        clean[key] = val.strip()

    return clean, actions


# ---------------------------------------------------------------------------
# Stage 2: Validate mapping — purely diagnostic
# ---------------------------------------------------------------------------


def _validate_mapping(
    mapping: Dict[str, str],
    required_roles: List[str],
    data: List[dict],
) -> MappingValidation:
    """
    Diagnose structural issues in a mapping.  Does NOT repair — purely diagnostic.

    Returns a ``MappingValidation`` with ``is_valid=True`` when the mapping is
    safe to pass directly to ``_build_g2plot_spec()``.
    """
    missing_required: List[str] = [r for r in required_roles if r not in mapping]
    bad_columns: Dict[str, str] = {}
    duplicate_columns: List[str] = []
    swapped_axes = False

    if data:
        first_row_keys_lower = {k.lower(): k for k in data[0].keys()}
        seen_cols: Dict[str, str] = {}  # lowercase col → first role

        for role, col in mapping.items():
            col_lower = col.lower()
            # Check column exists (case-insensitive)
            if col_lower not in first_row_keys_lower:
                bad_columns[role] = col
            # Check duplicates
            if col_lower in seen_cols:
                duplicate_columns.append(f"{role}={col} duplicates {seen_cols[col_lower]}")
            else:
                seen_cols[col_lower] = role

        # Check swapped axes: x_axis should be categorical, y_axis numeric
        if "x_axis" in mapping and "y_axis" in mapping:
            x_col = mapping["x_axis"]
            y_col = mapping["y_axis"]
            if (
                x_col.lower() in first_row_keys_lower
                and y_col.lower() in first_row_keys_lower
            ):
                actual_x = first_row_keys_lower[x_col.lower()]
                actual_y = first_row_keys_lower[y_col.lower()]
                # Sample up to 5 rows to check types
                sample = data[:5]
                x_all_numeric = all(_is_numeric_value(row.get(actual_x)) for row in sample)
                y_any_non_numeric = any(
                    not _is_numeric_value(row.get(actual_y)) for row in sample
                )
                if x_all_numeric and y_any_non_numeric:
                    swapped_axes = True

    is_valid = not missing_required and not bad_columns and not swapped_axes
    return MappingValidation(
        is_valid=is_valid,
        missing_required=missing_required,
        bad_columns=bad_columns,
        swapped_axes=swapped_axes,
        duplicate_columns=duplicate_columns,
    )


# ---------------------------------------------------------------------------
# Fuzzy column matching helpers (for Stage 3)
# ---------------------------------------------------------------------------


def _tokenize_column_name(name: str) -> List[str]:
    """
    Split a column name into lowercase tokens.

    Handles camelCase, snake_case, kebab-case, and space-separated names::

        'DistinctValueCount' → ['distinct', 'value', 'count']
        'product_type'       → ['product', 'type']
        'Request Count'      → ['request', 'count']
    """
    # Split on camelCase boundaries first
    parts = _CAMEL_CASE_RE.sub(" ", name)
    # Then split on underscores, hyphens, spaces
    tokens = re.split(r"[_\-\s]+", parts)
    return [t.lower() for t in tokens if t]


def _fuzzy_match_column(target: str, data_columns: List[str]) -> Optional[str]:
    """
    Find the best matching data column for a target name.

    Match priority:
    1. Case-insensitive exact match
    2. Normalized match (strip all separators, lowercase)
    3. Token-overlap (Jaccard) — requires >0.5 AND unique best match
    4. Substring — target is suffix/prefix of exactly one column

    Returns the actual column name (preserving original case) or ``None``.
    """
    if not target or not data_columns:
        return None

    target_lower = target.lower()

    # 1. Case-insensitive exact match
    for col in data_columns:
        if col.lower() == target_lower:
            return col

    # 2. Normalized match (strip all non-alphanumeric, lowercase)
    target_norm = re.sub(r"[^a-z0-9]", "", target_lower)
    for col in data_columns:
        col_norm = re.sub(r"[^a-z0-9]", "", col.lower())
        if col_norm == target_norm:
            return col

    # 3. Token overlap (Jaccard similarity)
    target_tokens = set(_tokenize_column_name(target))
    if target_tokens:
        best_score = 0.0
        best_col: Optional[str] = None
        tied = False

        for col in data_columns:
            col_tokens = set(_tokenize_column_name(col))
            if not col_tokens:
                continue
            intersection = target_tokens & col_tokens
            union = target_tokens | col_tokens
            score = len(intersection) / len(union) if union else 0.0
            if score > best_score:
                best_score = score
                best_col = col
                tied = False
            elif score == best_score and score > 0:
                tied = True

        if best_score > 0.5 and not tied:
            return best_col

    # 4. Substring match (target is prefix/suffix of exactly one column)
    matches = [
        col
        for col in data_columns
        if col.lower().startswith(target_lower) or col.lower().endswith(target_lower)
    ]
    if len(matches) == 1:
        return matches[0]

    return None


# ---------------------------------------------------------------------------
# Stage 3: Deterministic repair — fuzzy match, swap axes, fill roles
# ---------------------------------------------------------------------------


def _repair_mapping_deterministic(
    mapping: Dict[str, str],
    validation: MappingValidation,
    chart_type: str,
    required_roles: List[str],
    optional_roles: List[str],
    data: List[dict],
) -> Tuple[Dict[str, str], bool, List[str]]:
    """
    Attempt to repair a mapping using deterministic strategies.

    Strategies applied in order:
    - 3a. Fuzzy column matching for bad (not found) columns
    - 3b. Axis swap when x_axis/y_axis types are swapped
    - 3c. Fill missing required roles using column classification

    Returns ``(repaired_mapping, needs_melt, repairs_list)``.
    """
    repaired = dict(mapping)
    repairs: List[str] = []
    needs_melt = False
    data_columns = list(data[0].keys()) if data else []

    # 3a. Fuzzy column matching for bad columns
    for role, bad_col in validation.bad_columns.items():
        match = _fuzzy_match_column(bad_col, data_columns)
        if match:
            # Reject constant-value columns for categorical roles —
            # fuzzy matching "ColumnName" → "SourceColumnName" is structurally
            # correct but semantically useless when all rows share the same
            # value.  Defer to 3c (classify + assign) which is cardinality-aware.
            if role in ("x_axis", "color") and data and not _has_multiple_values(match, data):
                repaired.pop(role, None)
                repairs.append(
                    f"rejected_fuzzy {role}: '{bad_col}' → '{match}' "
                    f"(constant value, deferring to classifier)"
                )
            else:
                repaired[role] = match
                repairs.append(f"fuzzy_matched {role}: '{bad_col}' → '{match}'")
        else:
            # Remove the bad mapping — it'll be filled by 3c if required
            repaired.pop(role, None)
            repairs.append(f"removed {role}: '{bad_col}' not found in data")

    # 3b. Axis swap
    if validation.swapped_axes and "x_axis" in repaired and "y_axis" in repaired:
        repaired["x_axis"], repaired["y_axis"] = repaired["y_axis"], repaired["x_axis"]
        repairs.append(
            f"swapped axes: x_axis←'{repaired['y_axis']}', y_axis←'{repaired['x_axis']}'"
        )

    # 3c. Fill missing required roles using classification
    still_missing = [r for r in required_roles if r not in repaired]
    if still_missing:
        classified = _classify_columns(data)
        # Use _assign_roles to get a full mapping, but only take roles we need
        full_assignment = _assign_roles(
            chart_type, required_roles, optional_roles, classified, data,
        )
        needs_melt = bool(full_assignment.pop("_needs_melt", False))

        for role in still_missing:
            if role in full_assignment:
                repaired[role] = full_assignment[role]
                repairs.append(f"filled {role}: '{full_assignment[role]}' (classified)")

    return repaired, needs_melt, repairs


# ---------------------------------------------------------------------------
# Stage 4: LLM-assisted repair wrapper
# ---------------------------------------------------------------------------


async def _repair_mapping_via_llm_wrapper(
    mapping: Dict[str, str],
    chart_type: str,
    required_roles: List[str],
    data: List[dict],
    classified: Dict[str, List[str]],
    context: Dict[str, Any],
) -> Tuple[Optional[Dict[str, str]], bool, Dict[str, Any]]:
    """
    Wrap the existing ``_resolve_mapping_via_llm()`` with partial-mapping context
    and output sanitization.

    Returns ``(repaired_mapping_or_None, needs_melt, meta_dict)``.
    """
    llm_callable = context.get("llm_callable")
    if not llm_callable:
        return None, False, {}

    # Only call LLM if there are ambiguous columns to resolve
    if not classified.get("ambiguous"):
        return None, False, {}

    llm_result, tokens = await _resolve_mapping_via_llm(
        chart_type, required_roles, data, classified, llm_callable,
    )

    if not llm_result:
        return None, False, {
            "llm_input_tokens": tokens[0],
            "llm_output_tokens": tokens[1],
        }

    # Sanitize LLM output (LLMs can also return None values)
    sanitized, _ = _sanitize_mapping(llm_result, chart_type)

    # Merge: preserve existing valid roles, overlay LLM assignments
    merged = dict(mapping)
    for role, col in sanitized.items():
        if role not in merged:
            merged[role] = col

    needs_melt = bool(
        llm_result.pop("_needs_melt", False) or llm_result.pop("needs_melt", False)
    )

    return merged, needs_melt, {
        "llm_input_tokens": tokens[0],
        "llm_output_tokens": tokens[1],
    }


# ---------------------------------------------------------------------------
# Pipeline orchestrator — replaces _is_mapping_complete + _resolve_chart_mapping
# ---------------------------------------------------------------------------


async def _resolve_and_validate_mapping(
    chart_type: str,
    data: List[dict],
    raw_mapping: Dict[str, Any],
    context: Dict[str, Any],
) -> MappingResult:
    """
    Five-stage mapping validation and repair pipeline.

    Every mapping passes through stages 1-2.  Stages 3-5 only run if stage 2
    finds problems.  The output is always a valid mapping that
    ``_build_g2plot_spec()`` can consume without error.

    Stages:
        1. Sanitize — strip garbage values (None, empty, non-string, unknown roles)
        2. Validate — diagnose structural issues (missing roles, bad columns, swapped axes)
        3. Deterministic repair — fuzzy match columns, swap axes, fill missing roles
        4. LLM repair — surgical call for genuinely ambiguous columns
        5. Positional fallback — guaranteed last resort
    """
    chart_entry = _CHART_TYPES.get(chart_type.lower(), {})
    required_roles = chart_entry.get("mapping_roles", ["x_axis", "y_axis"])
    optional_roles = chart_entry.get("optional_roles", [])
    meta: Dict[str, Any] = {"stages_applied": []}

    # --- Stage 1: Sanitize ---
    sanitized, sanitize_actions = _sanitize_mapping(raw_mapping, chart_type)
    meta["stages_applied"].append("sanitize")
    if sanitize_actions:
        meta["sanitize_actions"] = sanitize_actions

    # --- Stage 2: Validate ---
    validation = _validate_mapping(sanitized, required_roles, data)

    if validation.is_valid:
        meta["resolved_by"] = "sanitized_passthrough"
        return MappingResult(mapping=sanitized, meta=meta)

    # --- Stage 3: Deterministic repair ---
    meta["stages_applied"].append("deterministic_repair")
    classified = _classify_columns(data)
    meta["classified"] = classified

    repaired, needs_melt, repairs = _repair_mapping_deterministic(
        sanitized, validation, chart_type, required_roles, optional_roles, data,
    )
    if repairs:
        meta["repairs_applied"] = repairs

    # Re-validate after repair
    post_repair_validation = _validate_mapping(repaired, required_roles, data)
    if post_repair_validation.is_valid or (
        needs_melt and not post_repair_validation.missing_required
    ):
        meta["resolved_by"] = "deterministic_repair"
        return MappingResult(mapping=repaired, needs_melt=needs_melt, meta=meta)

    # --- Stage 4: LLM repair ---
    llm_mapping, llm_melt, llm_meta = await _repair_mapping_via_llm_wrapper(
        repaired, chart_type, required_roles, data, classified, context,
    )
    if llm_meta:
        meta["stages_applied"].append("llm_repair")
        meta.update(llm_meta)

    if llm_mapping:
        # Validate LLM output
        llm_validation = _validate_mapping(llm_mapping, required_roles, data)
        if llm_validation.is_valid or (
            llm_melt and not llm_validation.missing_required
        ):
            meta["resolved_by"] = "llm_assisted"
            # Build Live Status event for piggybacking
            in_tok = llm_meta.get("llm_input_tokens", 0)
            out_tok = llm_meta.get("llm_output_tokens", 0)
            missing_count = len(post_repair_validation.missing_required)
            meta["_component_llm_events"] = [
                {
                    "step": "Chart Mapping Resolution (LLM)",
                    "type": "plan_optimization",
                    "details": {
                        "summary": (
                            f"Deterministic repair insufficient — LLM resolved "
                            f"{missing_count} ambiguous role(s). "
                            f"({in_tok} in / {out_tok} out)"
                        ),
                        "correction_type": "component_llm_mapping",
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                    },
                }
            ]
            return MappingResult(
                mapping=llm_mapping, needs_melt=llm_melt, meta=meta,
            )

    # --- Stage 5: Positional fallback ---
    meta["stages_applied"].append("positional_fallback")
    fallback = _positional_fallback(chart_type, required_roles, data)
    fallback_melt = bool(fallback.pop("_needs_melt", False))
    meta["resolved_by"] = "positional_fallback"
    return MappingResult(mapping=fallback, needs_melt=fallback_melt, meta=meta)


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

    # Filter out constant-value columns — a column where every row has the
    # same value (e.g. SourceColumnName="ProductType" in qlty_distinctCategories
    # output) is metadata, not a chartable dimension.  Keep the unfiltered
    # list as fallback in case ALL candidates are constant (single-row data).
    x_varied = [c for c in x_candidates if _has_multiple_values(c, data)]
    if x_varied:
        x_candidates = x_varied

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
        cat_varied = [c for c in cat if _has_multiple_values(c, data)]
        if cat_varied:
            cat = cat_varied
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
