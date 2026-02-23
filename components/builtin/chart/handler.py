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
from pathlib import Path
from typing import Any, Dict, Tuple

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

        chart_type = arguments.get("chart_type", "bar")
        title = arguments.get("title", "Generated Chart")

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.INLINE,
            spec=chart_spec,
            title=title,
            metadata={
                "tool_name": self.tool_name,
                "chart_type": chart_type,
                "row_count": len(data),
            },
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

    # Pie chart uses colorField instead of seriesField
    if chart_type == "pie" and "seriesField" in options:
        options["colorField"] = options.pop("seriesField")

    # Ensure numeric fields are actually numbers
    final_data = []
    if data:
        numeric_keys = set()
        for g2plot_key, actual_col_name in options.items():
            if g2plot_key in ("yField", "angleField", "sizeField", "value"):
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
