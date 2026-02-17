# trusted_data_agent/mcp/adapter.py
import copy
import json
import logging
import re
import uuid
from datetime import datetime, timedelta

from pydantic import ValidationError
from langchain_mcp_adapters.tools import load_mcp_tools
from trusted_data_agent.llm import handler as llm_handler
from trusted_data_agent.core.config import APP_CONFIG, AppConfig
from trusted_data_agent.core.config import get_user_mcp_server_id
from trusted_data_agent.agent.response_models import CanonicalResponse, PromptReportResponse

app_logger = logging.getLogger("quart.app")


# ---------------------------------------------------------------------------
# Report-aware context distillation
# ---------------------------------------------------------------------------
# Unlike the executor's _distill_data_for_llm_context (metadata-only),
# this preserves sample rows so the LLM can generate meaningful analysis.

def _distill_workflow_for_report(workflow_state: dict) -> tuple[dict, dict | None]:
    """Create a report-friendly distillation of workflow_state.

    Keeps first APP_CONFIG.REPORT_DISTILLATION_MAX_ROWS rows as representative
    samples and adds metadata summary for the full dataset. Applies a total
    budget check and aggressively reduces if needed.

    Returns:
        Tuple of (distilled dict, distillation metadata dict or None if no meaningful reduction)
    """
    original_size = len(json.dumps(workflow_state))
    distilled = copy.deepcopy(workflow_state)

    for key in list(distilled.keys()):
        if key.startswith('_'):
            continue
        distilled[key] = _distill_value_for_report(distilled[key])

    # Safety check: if total size still exceeds budget, reduce further
    total_json = json.dumps(distilled)
    budget = APP_CONFIG.REPORT_DISTILLATION_TOTAL_BUDGET
    triggered_level2 = len(total_json) > budget
    if triggered_level2:
        app_logger.warning(
            f"Report distillation: total size {len(total_json):,} chars exceeds "
            f"budget {budget:,}. Applying aggressive reduction."
        )
        _aggressive_distill(distilled)
        reduced_json = json.dumps(distilled)
        app_logger.info(f"Report distillation: reduced to {len(reduced_json):,} chars")

    distilled_size = len(json.dumps(distilled))
    meta = None
    if distilled_size < original_size * 0.9:  # only report meaningful reductions (>10%)
        meta = {
            "subtype": "report_distillation",
            "summary": f"Report data distilled: {original_size:,} → {distilled_size:,} chars ({round((1 - distilled_size / original_size) * 100, 1)}% reduction, L{'2' if triggered_level2 else '1'})",
            "original_chars": original_size,
            "distilled_chars": distilled_size,
            "reduction_pct": round((1 - distilled_size / original_size) * 100, 1),
            "level": 2 if triggered_level2 else 1,
            "budget_chars": budget
        }

    return distilled, meta


def _distill_value_for_report(data):
    """Recursively distill a single value, preserving sample rows."""
    max_rows = APP_CONFIG.REPORT_DISTILLATION_MAX_ROWS
    max_chars = APP_CONFIG.REPORT_DISTILLATION_MAX_CHARS

    if isinstance(data, dict):
        if 'results' in data and isinstance(data['results'], list):
            results_list = data['results']
            is_large = (
                len(results_list) > max_rows
                or len(json.dumps(results_list)) > max_chars
            )
            if is_large and results_list and all(isinstance(r, dict) for r in results_list[:5]):
                sample = results_list[:max_rows]
                distilled = dict(data)
                distilled['results'] = sample
                distilled.setdefault('metadata', {})
                distilled['metadata']['total_row_count'] = len(results_list)
                distilled['metadata']['sample_rows_included'] = len(sample)
                distilled['metadata']['columns'] = list(results_list[0].keys()) if results_list else []
                distilled['metadata']['truncated'] = True
                distilled['metadata']['truncation_note'] = (
                    f"Showing first {len(sample)} of {len(results_list)} rows. "
                    f"Analysis should note patterns are based on this sample."
                )
                return distilled
        return {k: _distill_value_for_report(v) for k, v in data.items()}

    elif isinstance(data, list):
        if (
            len(data) > max_rows
            and data
            and all(isinstance(item, dict) for item in data[:5])
        ):
            sample = data[:max_rows]
            return {
                '_distilled': True,
                'sample': sample,
                'total_count': len(data),
                'columns': list(data[0].keys()) if data else [],
                'note': f"Showing first {len(sample)} of {len(data)} items."
            }
        return [_distill_value_for_report(item) for item in data]

    return data


def _aggressive_distill(distilled: dict, max_rows: int = None):
    """Further reduce sample sizes when initial distillation exceeds budget."""
    if max_rows is None:
        max_rows = APP_CONFIG.REPORT_DISTILLATION_AGGRESSIVE_ROWS
    for key in list(distilled.keys()):
        if key.startswith('_'):
            continue
        distilled[key] = _reduce_samples(distilled[key], max_rows)


def _reduce_samples(data, max_rows: int):
    """Recursively reduce sample sizes in already-distilled data."""
    if isinstance(data, dict):
        if 'results' in data and isinstance(data['results'], list) and len(data['results']) > max_rows:
            data['results'] = data['results'][:max_rows]
            if 'metadata' in data and isinstance(data['metadata'], dict):
                data['metadata']['sample_rows_included'] = max_rows
                data['metadata']['truncation_note'] = (
                    f"Aggressively reduced to first {max_rows} of "
                    f"{data['metadata'].get('total_row_count', '?')} rows."
                )
        if '_distilled' in data and 'sample' in data and isinstance(data['sample'], list):
            data['sample'] = data['sample'][:max_rows]
        return {k: _reduce_samples(v, max_rows) for k, v in data.items()}
    elif isinstance(data, list):
        return [_reduce_samples(item, max_rows) for item in data]
    return data


# --- MODIFICATION START: Consolidate all client-side tools into a single list ---
CLIENT_SIDE_TOOLS = [
    {
        "name": "TDA_Charting",
        "description": "Generates a data visualization based on provided data. You must specify the chart type and map the data fields to the appropriate visual roles.",
        "args": {
            "chart_type": {
                "type": "string",
                "description": "The type of chart to generate (e.g., 'bar', 'pie', 'line', 'scatter'). This MUST be one of the types listed in the 'Charting Guidelines'.",
                "required": True
            },
            "data": {
                "type": "list[dict]",
                "description": "The data to be visualized, passed directly from the output of another tool.",
                "required": True
            },
            "title": {
                "type": "string",
                "description": "A descriptive title for the chart.",
                "required": True
            },
            "mapping": {
                "type": "dict",
                "description": "A dictionary that maps data keys to chart axes or roles (e.g., {'x_axis': 'product_name', 'y_axis': 'sales_total'}). The required keys for this mapping depend on the selected chart_type.",
                "required": True
            }
        }
    },
    {
        "name": "TDA_CurrentDate",
        "description": "Returns the current system date in YYYY-MM-DD format. Use this as the first step for any user query involving relative dates like 'today', 'yesterday', or 'this week'.",
        "args": {}
    },
    {
        "name": "TDA_DateRange",
        "description": "Calculates a list of dates based on a start date and a natural language phrase (e.g., 'past 3 days', 'last week'). This is a necessary second step for multi-day queries.",
        "args": {
            "start_date": {
                "type": "string",
                "description": "The anchor date for the calculation, usually today's date from `TDA_CurrentDate`. Must be in YYYY-MM-DD format.",
                "required": True
            },
            "date_phrase": {
                "type": "string",
                "description": "The natural language phrase describing the desired range (e.g., 'past 3 days', 'last 2 weeks').",
                "required": True
            }
        }
    },
    {
        "name": "TDA_LLMFilter",
        "description": "A specialized internal tool that filters a list of items based on a natural language goal and extracts a single, clean value. This is used as an intermediate step to pass a specific, machine-readable value from one tool to another.",
        "args": {
            "goal": {
                "type": "string",
                "description": "A clear, natural language description of the item to find and extract (e.g., 'Find the database related to fitness', 'Extract the name of the sales summary table').",
                "required": True
            },
            "data_to_filter": {
                "type": "list[dict]",
                "description": "The list of data objects to be filtered, passed from the result of a previous phase.",
                "required": True
            }
        }
    },
    {
        "name": "TDA_LLMTask",
        "description": "Performs internal, LLM-driven tasks that are not direct calls to the Teradata database. This tool is used for text synthesis, summarization, and formatting based on a specific 'task_description' provided by the LLM itself.",
        "args": {
            "task_description": {
                "type": "string",
                "description": "A natural language description of the internal task to be executed (e.g., 'describe the table in a business context', 'format final output'). The LLM infers this from the workflow plan.",
                "required": True
            },
            "source_data": {
                "type": "list[string]",
                "description": "A list of keys (e.g., 'result_of_phase_1') identifying which data from the workflow history is relevant for this task. This is critical for providing the correct context.",
                "required": True
            },
            "synthesized_answer": {
                "type": "string",
                "description": "The final, synthesized natural language answer, provided directly by the planner when it can confidently answer from history.",
                "required": False
            }
        }
    },
    {
        "name": "TDA_ContextReport",
        "description": "The History First Shortcut. This tool MUST be used for a single-phase plan if, and only if, the user's question can be answered entirely from the existing Workflow History. It bypasses all data gathering. Do NOT use this tool if you need to gather new data.",
        "args": {
            "answer_from_context": {
                "type": "string",
                "description": "The final, synthesized natural language answer, provided directly by the planner when it has confidently answered the user's question from the conversation history.",
                "required": True
            }
        }
    },
    {
        "name": "TDA_FinalReport",
        "description": "The Data Summarization Tool. This tool MUST be the final phase of a multi-step plan to synthesize the results from all previous data-gathering phases into a final report. Do NOT use this tool in a single-phase plan or as a first step.",
        "args": {}
    },
    {
        "name": "TDA_ComplexPromptReport",
        "description": "A special internal tool used to format and deliver the final, structured report for a pre-defined UI prompt. This tool MUST be called when all data gathering phases for the prompt are complete.",
        "args": {}
    }
]
# --- MODIFICATION END ---

# --- MODIFICATION START: Implement robust argument synonym resolution ---
def _normalize_tool_arguments(args: dict) -> dict:
    """
    Resolves argument synonyms to their canonical form using a 'last-wins'
    strategy. It iterates through the provided arguments, and if an argument
    is a known synonym, it maps it to the single, canonical argument name
    defined in the config, overwriting any previous value for that canonical name.
    This prevents validation errors and correctly handles cases where specific
    loop data should override generic plan data.
    """
    if not isinstance(args, dict):
        return {}

    resolved_args = {}
    # Create a reverse map for quick lookup: {synonym: canonical}
    reverse_synonym_map = {
        synonym: canonical
        for canonical, synonyms in AppConfig.ARGUMENT_SYNONYM_MAP.items()
        for synonym in synonyms
    }

    for arg_name, arg_value in args.items():
        # Find the canonical name for the current argument.
        # If the arg_name is not a synonym, it is treated as its own canonical name.
        canonical_name = reverse_synonym_map.get(arg_name, arg_name)

        # --- MODIFICATION START: Implement "last-wins" logic ---
        # Unconditionally set (or overwrite) the value for the canonical name.
        # This ensures the last synonym encountered takes precedence.
        resolved_args[canonical_name] = arg_value
        # --- MODIFICATION END ---

    return resolved_args
# --- MODIFICATION END ---


def _extract_and_clean_description(description: str | None) -> tuple[str, str]:
    if not isinstance(description, str):
        return "", "unknown"
    datatype = "unknown"
    match = re.search(r'\s*\((type:\s*(str|int|float|bool))\)', description, re.IGNORECASE)
    if match:
        datatype = match.group(2).lower()
        cleaned_description = description.replace(match.group(0), "").strip()
    else:
        cleaned_description = description
    return cleaned_description, datatype

def _extract_prompt_type_from_description(description: str | None) -> tuple[str, str]:
    if not isinstance(description, str):
        return "", "reporting"
    prompt_type = "reporting"
    match = re.search(r'\s*\((prompt_type:\s*(reporting|context))\)', description, re.IGNORECASE)
    if match:
        prompt_type = match.group(2).lower()
        cleaned_description = description.replace(match.group(0), "").strip()
    else:
        cleaned_description = description
    return cleaned_description, prompt_type

def _get_arg_descriptions_from_string(description: str) -> tuple[str, dict]:
    if not description:
        return "", {}
    args_section_match = re.search(r'\n\s*(Arguments|Args):\s*\n', description, re.IGNORECASE)
    if not args_section_match:
        return description, {}
    cleaned_description = description[:args_section_match.start()].strip()
    args_section_text = description[args_section_match.end():]
    pattern = re.compile(r'^\s*(?P<name>\w+)\s*[-:]\s*(?P<desc>.+)')
    descriptions = {}
    for line in args_section_text.split('\n'):
        match = pattern.match(line.strip())
        if match:
            data = match.groupdict()
            descriptions[data['name']] = data['desc'].strip()
    return cleaned_description, descriptions

def _get_type_from_schema(schema: dict) -> str:
    if not isinstance(schema, dict):
        return "any"
    if "type" in schema:
        return schema["type"]
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        for type_option in schema["anyOf"]:
            if isinstance(type_option, dict) and type_option.get("type") != "null":
                return type_option.get("type", "any")
    return "any"


async def load_and_categorize_mcp_resources(STATE: dict, user_uuid: str = None, profile_id: str = None):
    """
    Load MCP tools, prompts, and resources, then categorize them based on the profile's classification mode.
    
    Args:
        STATE: Application state dictionary
        user_uuid: User identifier for config loading
        profile_id: Profile ID to get classification settings from
    """
    mcp_client = STATE.get('mcp_client')
    llm_instance = STATE.get('llm')
    if not mcp_client or not llm_instance:
        raise Exception("MCP or LLM client not initialized.")

    # Use server ID instead of name for session management
    server_id = get_user_mcp_server_id(user_uuid)
    if not server_id:
        raise Exception("MCP server ID not found in configuration.")

    # Get classification mode from profile if provided
    classification_mode = 'light'  # default
    skip_classification_profile = False  # Track if this profile type should skip classification
    is_conversation_profile = False  # Track if this is a conversation profile (LangChain-based)
    if profile_id:
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        profile = config_manager.get_profile(profile_id, user_uuid)
        if profile:
            classification_mode = profile.get('classification_mode', 'light')
            profile_type = profile.get('profile_type', 'tool_enabled')
            use_mcp_tools = profile.get('useMcpTools', False)

            # Determine if this is a conversation profile (llm_only with MCP tools enabled)
            is_conversation_profile = (profile_type == 'llm_only' and use_mcp_tools)

            # Check if this profile type should skip LLM classification:
            # - llm_only with useMcpTools: Uses LangChain for tool selection, not the planner
            # - rag_focused: Uses knowledge retrieval, not MCP tool classification
            skip_classification_profile = (
                (profile_type == 'llm_only' and use_mcp_tools) or
                profile_type == 'rag_focused'
            )

            # CRITICAL: Force 'light' mode for profiles that don't need LLM classification
            if skip_classification_profile and classification_mode != 'light':
                app_logger.info(f"Forcing 'light' classification mode for {profile_type} profile {profile_id} (was: {classification_mode})")
                classification_mode = 'light'
            app_logger.info(f"Using classification mode '{classification_mode}' from profile {profile_id} (skip classification: {skip_classification_profile})")
        else:
            app_logger.warning(f"Profile {profile_id} not found, using default classification mode 'full'")
    else:
        app_logger.warning("No profile_id provided to load_and_categorize_mcp_resources, using default mode 'full'")

    # === CACHING LAYER: Check schema cache ===
    import time
    cache_key = server_id
    schema_cache = STATE.setdefault('mcp_tool_schema_cache', {})
    cached_schemas = schema_cache.get(cache_key)

    cache_valid = False
    loaded_tools = []
    loaded_prompts = []
    loaded_resources = []

    if cached_schemas:
        age = time.time() - cached_schemas.get('timestamp', 0)
        if age < 300:  # 5 minute TTL
            cache_valid = True
            app_logger.info(f"✓ CACHE HIT: Tool schemas for server {server_id} (age: {age:.1f}s, {cached_schemas.get('tool_count', 0)} tools, saved ~7s)")
            loaded_tools = cached_schemas['tools']
            loaded_prompts = cached_schemas['prompts']
            loaded_resources = cached_schemas['resources']
        else:
            app_logger.info(f"Cache expired for server {server_id} (age: {age:.1f}s > 300s TTL)")

    # === Load from MCP if cache miss/expired ===
    if not cache_valid:
        async with mcp_client.session(server_id) as temp_session:
            app_logger.info("--- Loading and classifying MCP tools and prompts... ---")

            list_tools_result = await temp_session.list_tools()
            raw_tools = list_tools_result.tools if hasattr(list_tools_result, 'tools') else []

            processed_tools = []
            class SimpleTool:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

            for raw_tool in raw_tools:
                tool_name = raw_tool.name
                tool_desc = raw_tool.description or ""
                processed_args = []
                cleaned_description = tool_desc

                if hasattr(raw_tool, 'inputSchema') and raw_tool.inputSchema and 'properties' in raw_tool.inputSchema:
                    cleaned_description, arg_desc_map = _get_arg_descriptions_from_string(tool_desc)
                    schema = raw_tool.inputSchema
                    required_args = schema.get('required', []) or []

                    for arg_name, arg_schema in schema['properties'].items():
                        processed_args.append({
                            "name": arg_name,
                            "type": _get_type_from_schema(arg_schema),
                            "required": arg_name in required_args,
                            "description": arg_desc_map.get(arg_name, arg_schema.get('title', 'No description.'))
                        })

                processed_tools.append(SimpleTool(
                    name=tool_name,
                    description=cleaned_description,
                    args={arg['name']: arg for arg in processed_args}
                ))

            loaded_tools = processed_tools
            app_logger.info(f"Loaded {len(loaded_tools)} tools from MCP server")

            loaded_prompts = []
            try:
                list_prompts_result = await temp_session.list_prompts()
                if hasattr(list_prompts_result, 'prompts'):
                    loaded_prompts = list_prompts_result.prompts
                    app_logger.info(f"Loaded {len(loaded_prompts)} prompts from MCP server")
            except Exception as e:
                app_logger.error(f"CRITICAL ERROR while loading prompts: {e}", exc_info=True)

            # --- MODIFICATION START: Gracefully handle resource loading ---
            loaded_resources = []
            try:
                # Attempt to list resources, which might not be supported by all MCP servers.
                list_resources_result = await temp_session.list_resources()
                if hasattr(list_resources_result, 'resources'):
                    loaded_resources = list_resources_result.resources
                    app_logger.info(f"Successfully loaded {len(loaded_resources)} resources from MCP server.")
            except Exception as e:
                # If the call fails (e.g., method not found), log a warning and continue.
                app_logger.warning(f"Could not load resources from MCP server (this may be expected for older servers): {e}")
                # Ensure loaded_resources remains an empty list.
                loaded_resources = []
            # --- MODIFICATION END ---

        # --- MODIFICATION START: Iterate over the consolidated list ---
        for tool_def in CLIENT_SIDE_TOOLS:
            loaded_tools.append(SimpleTool(**tool_def))
        # --- MODIFICATION END ---

        # === Cache the loaded schemas ===
        schema_cache[cache_key] = {
            'tools': loaded_tools,
            'prompts': loaded_prompts,
            'resources': loaded_resources,
            'timestamp': time.time(),
            'tool_count': len(loaded_tools)
        }
        app_logger.info(f"✓ Cached tool schemas for server {server_id} ({len(loaded_tools)} tools, {len(loaded_prompts)} prompts, {len(loaded_resources)} resources)")

    # === Process tools/prompts and save classification (runs for both fresh load AND cache hit) ===
    # This is outside the cache block because we need to populate STATE and save classification
    # results even when using cached schemas (schema cache != profile classification cache)
    STATE['mcp_tools'] = {tool.name: tool for tool in loaded_tools}
    if loaded_prompts:
        STATE['mcp_prompts'] = {prompt.name: prompt for prompt in loaded_prompts}

    all_capabilities = []
    all_capabilities.extend([f"- {tool.name} (tool): {tool.description}" for tool in loaded_tools])

    for p in loaded_prompts:
        prompt_str = f"- {p.name} (prompt): {p.description or 'No description available.'}"
        if hasattr(p, 'arguments') and p.arguments:
            prompt_str += "\n  - Arguments:"
            for arg in p.arguments:
                arg_dict = arg.model_dump()
                arg_name = arg_dict.get('name', 'unknown_arg')
                prompt_str += f"\n    - `{arg_name}`"
        all_capabilities.append(prompt_str)

    # --- MODIFICATION START: Include loaded resources in the capabilities list for classification ---
    if loaded_resources:
        all_capabilities.extend([f"- {res.name} (resource): {res.description or 'No description.'}" for res in loaded_resources])
    # --- MODIFICATION END ---


    capabilities_list_str = "\n".join(all_capabilities)

    # --- Determine classification behavior based on profile's classification_mode ---
    # 'light': Single generic category per type ("All Tools", "All Prompts", "All Resources")
    # 'full': LLM-based semantic categorization

    if classification_mode == 'light':
        app_logger.info(f"Classification mode 'light': using generic single-category structure. Processing {len(loaded_tools)} tools, {len(loaded_prompts)} prompts, {len(loaded_resources)} resources")
        classified_data = {}
        skip_classification = True
    elif classification_mode == 'full':
        skip_classification = False
        app_logger.info("Classification mode 'full': calling LLM to semantically categorize capabilities...")
        classification_prompt = (
            "You are a helpful assistant that analyzes a list of technical capabilities (tools and prompts) and classifies them. "
            "For each capability, you must determine a single user-friendly 'category' for a UI. "
            "Example categories might be 'Data Quality', 'Table Management', 'Performance', 'Utilities', 'Database Information', etc. Be concise and consistent.\n\n"
            "Your response MUST be a single, valid JSON object. The keys of this object must be the capability names, "
            "and the value for each key must be another JSON object containing only the 'category' you determined.\n\n"
            "Example format:\n"
            "{\n"
            '  "capability_name_1": {"category": "Some Category"},\n'
            '  "capability_name_2": {"category": "Another Category"}\n'
            "}\n\n"
            f"--- Capability List ---\n{capabilities_list_str}"
        )
        categorization_system_prompt = "You are an expert assistant that only responds with valid JSON."

        classified_capabilities_str, _, _, _, _ = await llm_handler.call_llm_api(
            llm_instance, classification_prompt, raise_on_error=True,
            system_prompt_override=categorization_system_prompt
        )

        match = re.search(r'\{.*\}', classified_capabilities_str, re.DOTALL)
        if match is None:
            raise ValueError(f"LLM failed to return a valid JSON for capability classification. Response: '{classified_capabilities_str}'")

        cleaned_str = match.group(0)
        classified_data = json.loads(cleaned_str)
    else:
        app_logger.warning(f"Unknown classification mode '{classification_mode}', defaulting to 'light'")
        classified_data = {}
        skip_classification = True

    STATE['structured_tools'] = {}
    disabled_tools_list = STATE.get("disabled_tools", [])

    for tool in loaded_tools:
        if skip_classification:  # 'light' mode
            category = "All Tools"
        else:  # 'full' mode
            classification = classified_data.get(tool.name, {})
            category = classification.get("category", "Uncategorized")

        if category not in STATE['structured_tools']:
            STATE['structured_tools'][category] = []

        processed_args = []
        if hasattr(tool, 'args') and isinstance(tool.args, dict):
            for arg_name, arg_details in tool.args.items():
                if isinstance(arg_details, dict):
                    processed_args.append({
                        "name": arg_name,
                        "type": arg_details.get("type", "any"),
                        "description": arg_details.get("description", "No description available."),
                        "required": arg_details.get("required", False)
                    })

        STATE.setdefault('tool_scopes', {})
        required_args_raw = {arg['name'] for arg in processed_args if arg.get('required')}

        canonical_required_args = set()
        for arg_name in required_args_raw:
            found_canonical = False
            for canonical, synonyms in AppConfig.ARGUMENT_SYNONYM_MAP.items():
                if arg_name in synonyms:
                    canonical_required_args.add(canonical)
                    found_canonical = True
                    break
            if not found_canonical:
                canonical_required_args.add(arg_name)

        for scope, required_set in AppConfig.TOOL_SCOPE_HIERARCHY:
            if required_set.issubset(canonical_required_args):
                STATE['tool_scopes'][tool.name] = scope
                break

        is_disabled = tool.name in disabled_tools_list
        STATE['structured_tools'][category].append({
            "name": tool.name,
            "description": tool.description,
            "arguments": processed_args,
            "disabled": is_disabled
        })

    # --- MODIFICATION START: Remove the generation of the static tools_context ---
    # STATE['tools_context'] will now be built dynamically in the handler.
    STATE['tools_context'] = "--- No Tools Available ---"
    # --- MODIFICATION END ---

    STATE['structured_prompts'] = {}
    disabled_prompts_list = STATE.get("disabled_prompts", [])

    if loaded_prompts:
        for prompt_obj in loaded_prompts:
            if skip_classification:  # 'light' mode
                category = "All Prompts"
            else:  # 'full' mode
                classification = classified_data.get(prompt_obj.name, {})
                category = classification.get("category", "Uncategorized")

            if category not in STATE['structured_prompts']:
                STATE['structured_prompts'][category] = []

            is_disabled = prompt_obj.name in disabled_prompts_list

            cleaned_prompt_desc, prompt_type = _extract_prompt_type_from_description(prompt_obj.description)

            processed_args = []
            if hasattr(prompt_obj, 'arguments') and prompt_obj.arguments:
                for arg in prompt_obj.arguments:
                    arg_dict = arg.model_dump()
                    cleaned_arg_desc, arg_type = _extract_and_clean_description(arg_dict.get("description"))
                    arg_dict['description'] = cleaned_arg_desc
                    arg_dict['type'] = arg_type
                    processed_args.append(arg_dict)

            STATE['structured_prompts'][category].append({
                "name": prompt_obj.name,
                "description": cleaned_prompt_desc or "No description available.",
                "arguments": processed_args,
                "disabled": is_disabled,
                "prompt_type": prompt_type
            })

    # --- MODIFICATION START: Process and categorize loaded resources ---
    STATE['structured_resources'] = {} # Initialize the structure
    if loaded_resources:
        for resource_obj in loaded_resources:
            if skip_classification:  # 'light' mode
                category = "All Resources"
            else:  # 'full' mode
                classification = classified_data.get(resource_obj.name, {})
                category = classification.get("category", "Uncategorized")

            if category not in STATE['structured_resources']:
                STATE['structured_resources'][category] = []

            STATE['structured_resources'][category].append({
                "name": resource_obj.name,
                "description": resource_obj.description or "No description."
            })
    # --- MODIFICATION END ---


    prompt_context_parts = ["--- Available Prompts ---"]
    for category, prompts in sorted(STATE['structured_prompts'].items()):
        enabled_prompts_in_category = [p for p in prompts if not p['disabled']]
        if enabled_prompts_in_category:
            prompt_context_parts.append(f"--- Category: {category} ---")
            for prompt_info in enabled_prompts_in_category:
                prompt_description = prompt_info.get("description", "No description available.")
                prompt_str = f"- `{prompt_info['name']}` (prompt): {prompt_description}"

                processed_args = prompt_info.get('arguments', [])
                if processed_args:
                    prompt_str += "\n  - Arguments:"
                    for arg_details in processed_args:
                        arg_name = arg_details.get('name', 'unknown')
                        arg_type = arg_details.get('type', 'any')
                        is_required = arg_details.get('required', False)
                        req_str = "required" if is_required else "optional"
                        arg_desc = arg_details.get('description', 'No description.')
                        prompt_str += f"\n    - `{arg_name}` ({arg_type}, {req_str}): {arg_desc}"
                prompt_context_parts.append(prompt_str)

    if len(prompt_context_parts) > 1:
        STATE['prompts_context'] = "\n".join(prompt_context_parts)
    else:
        STATE['prompts_context'] = "--- No Prompts Available ---"

    tool_args = set()
    for tool in STATE['mcp_tools'].values():
        if hasattr(tool, 'args') and isinstance(tool.args, dict):
            tool_args.update(tool.args.keys())

    prompt_args = set()
    for prompt_list in STATE['structured_prompts'].values():
        for prompt_info in prompt_list:
            if 'arguments' in prompt_info and isinstance(prompt_info['arguments'], list):
                for arg_details in prompt_info['arguments']:
                    if 'name' in arg_details:
                        prompt_args.add(arg_details['name'])

    STATE['all_known_mcp_arguments'] = {
        "tool": list(tool_args),
        "prompt": list(prompt_args)
    }
    app_logger.info(f"Dynamically identified {len(tool_args)} tool and {len(prompt_args)} prompt arguments for context enrichment.")

    # Save classification results to profile if profile_id provided
    if profile_id:
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()

        # CRITICAL: Conversation profiles use LangChain which doesn't support MCP prompts
        # Exclude prompts from classification results for conversation profiles
        classification_results = {
            'tools': STATE.get('structured_tools', {}),
            'prompts': {} if is_conversation_profile else STATE.get('structured_prompts', {}),
            'resources': STATE.get('structured_resources', {}),
            'tool_scopes': STATE.get('tool_scopes', {}),
            'classified_with_mode': classification_mode
        }

        config_manager.save_profile_classification(
            profile_id=profile_id,
            classification_results=classification_results,
            user_uuid=user_uuid
        )
        tool_count = sum(len(tools) for tools in classification_results['tools'].values())
        prompt_count = sum(len(prompts) for prompts in classification_results['prompts'].values())
        resource_count = sum(len(resources) for resources in classification_results['resources'].values())
        app_logger.info(f"Saved classification results to profile {profile_id} (mode: {classification_mode}): {len(classification_results['tools'])} tool categories with {tool_count} tools, {len(classification_results['prompts'])} prompt categories with {prompt_count} prompts, {len(classification_results['resources'])} resource categories with {resource_count} resources")


def _transform_chart_data(data: any) -> list[dict]:
    if isinstance(data, list) and all(isinstance(item, dict) and 'results' in item for item in data):
        app_logger.info("Detected nested tool output. Flattening data for charting.")
        flattened_data = []
        for item in data:
            results_list = item.get("results")
            if isinstance(results_list, list):
                flattened_data.extend(results_list)
        return flattened_data

    if isinstance(data, dict) and 'labels' in data and 'values' in data:
        app_logger.warning("Correcting hallucinated chart data format from labels/values to list of dicts.")
        labels = data.get('labels', [])
        values = data.get('values', [])
        if isinstance(labels, list) and isinstance(values, list) and len(labels) == len(values):
            return [{"label": l, "value": v} for l, v in zip(labels, values)]
    if isinstance(data, dict) and 'columns' in data and 'rows' in data:
        app_logger.warning("Correcting hallucinated chart data format from columns/rows to list of dicts.")
        if isinstance(data.get('rows'), list):
            return data['rows']

    if isinstance(data, list) and data and isinstance(data[0], dict):
        if "ColumnName" in data[0] and "DistinctValue" in data[0] and "DistinctValueCount" in data[0]:
            app_logger.info("Detected qlty_distinctCategories output pattern. Renaming 'ColumnName' to 'SourceColumnName'.")
            transformed_data = []
            for row in data:
                new_row = row.copy()
                if "ColumnName" in new_row:
                    new_row["SourceColumnName"] = new_row.pop("ColumnName")
                transformed_data.append(new_row)
            return transformed_data

    return data

def _build_g2plot_spec(args: dict, data: list[dict]) -> dict:
    chart_type = args.get("chart_type", "").lower()
    mapping = args.get("mapping", {})

    canonical_map = {
        'x_axis': 'xField',
        'y_axis': 'yField',
        'color': 'seriesField',
        'angle': 'angleField',
        'category': 'xField',
        'value': 'yField'
    }

    # Create a reverse lookup from alias (lowercase) to canonical G2Plot key
    reverse_canonical_map = {}
    for canonical, g2plot_key in canonical_map.items():
        reverse_canonical_map[canonical.lower()] = g2plot_key
        # Add common aliases - extend this if needed
        if canonical == 'x_axis':
            reverse_canonical_map['category'] = g2plot_key
        if canonical == 'y_axis':
            reverse_canonical_map['value'] = g2plot_key

    options = {"title": {"text": args.get("title", "Generated Chart")}}

    first_row_keys_lower = {k.lower(): k for k in data[0].keys()} if data and data[0] else {}

    processed_mapping = {}
    for llm_key, data_col_name in mapping.items():
        g2plot_key = reverse_canonical_map.get(llm_key.lower()) # Use reverse map
        if g2plot_key:
            actual_col_name = first_row_keys_lower.get(data_col_name.lower())
            if not actual_col_name:
                raise KeyError(f"The mapped column '{data_col_name}' (from '{llm_key}') was not found in the provided data.")
            processed_mapping[g2plot_key] = actual_col_name # Use g2plot_key here
        else:
            app_logger.warning(f"Unknown mapping key from LLM: '{llm_key}'. Skipping.")

    options.update(processed_mapping)

    # Specific adjustments for G2Plot types
    if chart_type == 'pie' and 'seriesField' in options:
        options['colorField'] = options.pop('seriesField') # Pie uses colorField for categories

    # Ensure numeric fields are actually numbers
    final_data = []
    if data:
        for row in data:
            new_row = row.copy()
            for g2plot_key, actual_col_name in options.items():
                if g2plot_key in ['yField', 'angleField', 'sizeField', 'value']: # Added 'value' just in case
                    cell_value = new_row.get(actual_col_name)
                    if cell_value is not None:
                        try:
                            # Attempt conversion, handling potential commas
                            numeric_value = float(str(cell_value).replace(',', ''))
                            new_row[actual_col_name] = numeric_value
                        except (ValueError, TypeError):
                            app_logger.warning(f"Non-numeric value '{cell_value}' encountered for numeric field '{actual_col_name}'. Conversion failed.")
            final_data.append(new_row)

    options["data"] = final_data

    # Map common names to official G2Plot types
    g2plot_type_map = {
        "bar": "Column", "column": "Column", "line": "Line", "area": "Area",
        "pie": "Pie", "scatter": "Scatter", "histogram": "Histogram",
        "heatmap": "Heatmap", "boxplot": "Box", "wordcloud": "WordCloud"
    }
    g2plot_type = g2plot_type_map.get(chart_type, chart_type.capitalize()) # Default to capitalized if not found

    return {"type": g2plot_type, "options": options}

# --- MODIFICATION START: Add user_uuid and update docstring ---
async def _invoke_llm_filter_task(STATE: dict, command: dict, user_uuid: str = None, session_id: str = None, call_id: str | None = None) -> tuple[dict, int, int]:
    """
    Executes a specialized LLM-based filtering task. It takes a list of data
    and a natural language goal, and is strictly prompted to return only a
    single, clean, machine-readable string value.
    This now robustly handles being passed a single dict from a loop.
    """
    # --- MODIFICATION END ---
    args = command.get("arguments", {})
    goal = args.get("goal")
    data_to_filter = args.get("data_to_filter")
    llm_instance = STATE.get('llm')

    final_call_id = call_id or str(uuid.uuid4())

    if not goal or not data_to_filter:
        return {"status": "error", "error_message": "TDA_LLMFilter requires 'goal' and 'data_to_filter' arguments."}, 0, 0

    # --- MODIFICATION START: Make context-sensitive to loop execution ---
    # If data_to_filter is a single dictionary (from a loop), wrap it in a list.
    if isinstance(data_to_filter, dict):
        app_logger.debug("TDA_LLMFilter received a single dict, wrapping in a list for processing.")
        data_to_filter = [data_to_filter]
    elif not isinstance(data_to_filter, list):
        app_logger.error(f"TDA_LLMFilter received invalid data_to_filter type: {type(data_to_filter)}")
        return {"status": "error", "error_message": f"TDA_LLMFilter 'data_to_filter' must be a list or a dict, but got {type(data_to_filter)}."}, 0, 0
    # --- MODIFICATION END ---

    filtering_prompt = (
        "You are an expert data extraction assistant. Your task is to find a single, specific item within a list of JSON objects that matches a given goal.\n\n"
        f"--- GOAL ---\n{goal}\n\n"
        f"--- DATA LIST ---\n{json.dumps(data_to_filter, indent=2)}\n\n"
        "--- INSTRUCTIONS ---\n"
        "1. Analyze the GOAL to understand what specific entity is being sought (e.g., a specific database name, a table name).\n"
        "2. Scan the DATA LIST to find the single JSON object that best matches this entity.\n"
        "3. From that single object, identify the key that holds the entity's primary identifier or name.\n"
        "4. Extract the value associated with that key.\n\n"
        "**CRITICAL OUTPUT FORMATTING:** Your response MUST be only the single, extracted value. It MUST NOT contain any punctuation, conversational text, explanations, markdown, or any other characters. Your output will be used directly as a parameter for another tool and must be perfectly clean.\n\n"
        "Example: If you extract the database name 'fitness_db', your response must be exactly `fitness_db` and nothing else."
    )

    reason = f"Client-Side Tool Call: TDA_LLMFilter\nGoal: {goal}"

    # --- MODIFICATION START: Pass user_uuid ---
    response_text, input_tokens, output_tokens, _, _ = await llm_handler.call_llm_api(
        llm_instance=llm_instance,
        prompt=filtering_prompt,
        reason=reason,
        system_prompt_override="You are a data extraction assistant that only responds with clean, single values.",
        raise_on_error=True,
        user_uuid=user_uuid,
        session_id=session_id
    )
    # --- MODIFICATION END ---

    cleaned_response_text = response_text.strip().strip('.,:;')

    result = {
        "status": "success",
        # --- MODIFICATION START: Add token counts to metadata ---
        "metadata": {
            "call_id": final_call_id,
            "tool_name": "TDA_LLMFilter",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        },
        # --- MODIFICATION END ---
        "results": [{"response": cleaned_response_text}]
    }

    return result, input_tokens, output_tokens

# --- MODIFICATION START: Add user_uuid and correct data fetching/prompt ---
async def _invoke_core_llm_task(STATE: dict, command: dict, workflow_state: dict, user_uuid: str = None, session_history: list = None, mode: str = "standard", session_id: str = None, call_id: str | None = None) -> tuple[dict, int, int]:
    args = command.get("arguments", {})
    user_question = args.get("user_question", "No user question provided.")
    llm_instance = STATE.get('llm')
    final_prompt = ""
    reason = ""

    final_call_id = call_id or str(uuid.uuid4())

    if mode == 'full_context':
        # ... (full_context mode logic remains unchanged) ...
        app_logger.info(f"Executing client-side LLM task in 'full_context' mode.")
        reason = f"Client-Side Tool Call: TDA_LLMTask (Full Context)\nSynthesizing answer for: '{user_question}'"

        history_str_parts = []
        if session_history:
            for entry in session_history:
                role = entry.get('role', 'unknown')
                content = entry.get('content', '')
                history_str_parts.append(f"--- Role: {role.capitalize()} ---\n{content}\n--- End Entry ---")
        history_str = "\n".join(history_str_parts)

        final_prompt = (
            "You are an expert data analyst and synthesizer. Your task is to answer the user's question by carefully analyzing the provided conversation history.\n"
            "The history contains the full dialogue, including the user's requests and the assistant's detailed, formatted HTML responses from previous turns.\n"
            "The answer to the current question is likely already present in this history.\n\n"
            "--- CURRENT USER QUESTION ---\n"
            f"{user_question}\n\n"
            "--- FULL CONVERSATION HISTORY ---\n"
            f"{history_str}\n\n"
            "--- INSTRUCTIONS ---\n"
            "1. Read the 'CURRENT USER QUESTION' to understand the user's goal.\n"
            "2. Thoroughly review the 'FULL CONVERSATION HISTORY' to find the previous turn where this question was successfully answered.\n"
            "3. Extract the relevant information from the assistant's previous HTML response.\n"
            "4. Synthesize a new, clean final answer that directly addresses the current user question.\n"
            "5. Your response MUST follow the same semantic content and markdown formatting as the original answer found in the history. Do NOT add conversational intros like \"I found this in the history...\". Simply provide the answer as if you were generating it for the first time."
        )

    else: # Standard mode
        task_description = args.get("task_description")
        source_data_keys = args.get("source_data", [])
        formatting_instructions = args.get("formatting_instructions")

        # Prioritize 'data' argument if present (from looping phase)
        focused_data_for_task = args.get("data")
        data_keys_found = [] # Track which keys were actually found

        if focused_data_for_task is None:
            # Fallback: Explicitly fetch from workflow_state using source_data_keys
            app_logger.info(f"TDA_LLMTask standard mode: Fetching data from workflow_state using keys: {source_data_keys}")
            focused_data_for_task = {}
            if isinstance(workflow_state, dict):
                for key in source_data_keys:
                    if key in workflow_state:
                        focused_data_for_task[key] = workflow_state[key]
                        data_keys_found.append(key)
                    else:
                        app_logger.warning(f"TDA_LLMTask: Source data key '{key}' specified in arguments was NOT found in the current workflow state.")
            else:
                 app_logger.error(f"TDA_LLMTask: workflow_state is not a dictionary. Cannot fetch source data. State type: {type(workflow_state)}")

            # Accurate Warning: Only warn if keys were specified but *none* were found.
            if source_data_keys and not data_keys_found:
                 app_logger.warning(f"TDA_LLMTask was called for '{task_description}' but NO source data was found for the specified keys: {source_data_keys}. The data payload will be empty.")
                 # Ensure focused_data_for_task is explicitly empty if nothing was found
                 focused_data_for_task = {}
            elif source_data_keys and len(data_keys_found) < len(source_data_keys):
                 app_logger.warning(f"TDA_LLMTask: Not all specified source data keys were found. Found: {data_keys_found}, Missing: {set(source_data_keys) - set(data_keys_found)}")


        else:
             app_logger.info(f"TDA_LLMTask is using the pre-filtered 'data' argument provided by the executor.")

        app_logger.info(f"Executing client-side LLM task in 'standard' mode: {task_description}")
        reason = f"Client-Side Tool Call: TDA_LLMTask\nTask: {task_description}"


        known_context = {}
        # Try to extract context from focused data first, then full state if needed
        # Use the definitively populated focused_data_for_task
        context_source = focused_data_for_task
        if isinstance(context_source, dict):
            for phase_results in context_source.values():
                # Handle both list of results and single result dicts robustly
                results_to_process = []
                if isinstance(phase_results, list):
                    results_to_process = phase_results
                elif isinstance(phase_results, dict): # Handle case where source might be a single dict
                    results_to_process = [phase_results]

                for result in results_to_process:
                    if isinstance(result, dict) and "metadata" in result:
                        metadata = result.get("metadata", {})
                        if "database" in metadata and "database_name" not in known_context:
                            known_context["database_name"] = metadata["database"]
                        if "table" in metadata and "table_name" not in known_context:
                            known_context["table_name"] = metadata["table"]
                        if "column_name" in metadata and "column_name" not in known_context:
                             known_context["column_name"] = metadata["column_name"]

        known_context_str = "\n".join([f"- {key}: {value}" for key, value in known_context.items()]) if known_context else "None"

        final_prompt = "You are a highly capable text processing and synthesis assistant.\n\n"

        if user_question and user_question != "Executing prompt...": # Don't inject default text
            final_prompt += (
                "--- PRIMARY GOAL ---\n"
                f"Your most important task is to directly answer the user's original question: '{user_question}'.\n"
                "You MUST begin your response with the direct answer. Do not repeat the user's question or use conversational intros like 'Here is...'. "
                "After providing the direct answer, you may then proceed with a more general summary or analysis of the data.\n\n"
            )

        final_prompt += (
            "--- TASK ---\n"
            f"{task_description}\n\n"
            "--- RELEVANT DATA (Selected from Previous Phases) ---\n"
            f"{json.dumps(focused_data_for_task, indent=2)}\n\n" # Use the definitively populated data
            "--- KNOWN CONTEXT ---\n"
            "The following key information has already been established in previous steps. You MUST use this information to populate header fields like 'Table Name' or 'Database Name'.\n"
            f"{known_context_str}\n\n"
            "--- SEMANTIC GUIDANCE ---\n"
            "When the 'TASK' asks for a 'description', 'analysis', or 'summary', you MUST synthesize new content that reflects the *semantic intent* of the request.\n"
            "For example:\n"
            "- If the 'TASK' asks for a 'business description of a table', you MUST explain its purpose from an organizational, functional, or analytical viewpoint, and the business significance of its columns. Do NOT simply reiterate technical DDL (Data Definition Language) information, even if it is present in the `RELEVANT DATA`.\n"
            "- If the 'TASK' asks for a 'summary of errors', you MUST provide a concise overview of the issues, not just a list of error codes.\n"
            "Always prioritize generating content that matches the *meaning* and *purpose* of the 'TASK', interpreting the raw data to produce the desired semantic output.\n\n"
            "--- CRITICAL RULES ---\n"
            "1. **Accurate Refusal:** If you cannot complete the `TASK` because the `RELEVANT DATA` is missing or is of the wrong type (e.g., you need descriptions but received DDLs), you MUST state this clearly. Explain *why* the provided data is insufficient (e.g., 'I need table descriptions, but only DDLs were provided'). Do NOT falsely claim the `RELEVANT DATA` section is empty if data is present.\n"
            "2. **Separate Data from Description:** If the 'TASK' requires you to output header fields (like `***Table Name:***` or `***Database Name:***`) AND a main description, you MUST treat these as separate steps. First, populate the header fields using the 'KNOWN CONTEXT'. Then, write the main description. Do NOT merge context data (like the database name) into a single header field.\n"
            "3. **Content and Formatting Precision:** You MUST adhere to any and all formatting instructions contained in the 'TASK' description with absolute precision. Do not deviate, simplify, or change the requested format in any way. You MUST generate content that genuinely fulfills the semantic goal of the 'TASK'.\n"
            "4. **Key Name Adherence:** If the 'TASK' description provides an example format, you MUST use the exact key names (e.g., `***Description:***`, `***Table Name:***`) shown in the example. Do not invent new key names or use synonyms like 'Table Description'.\n"
            "5. **Column Placeholder Replacement:** If the 'TASK' involves describing table columns and the formatting guidelines include a placeholder like `***ColumnX:***` or `***[Column Name]:***`, you MUST replace that placeholder with the actual name of the column you are describing (e.g., `***CUST_ID:***`, `***FIRSTNAME:***`). Do not use generic, numbered placeholders like 'Column1', 'Column2', etc.\n"
            "6. **Layout and Line Breaks:** Each key-value pair or list item specified in the formatting guidelines MUST be on its own separate line. Do not combine multiple items onto a single line.\n\n"
        )

        if formatting_instructions:
            final_prompt += f"--- ADDITIONAL FORMATTING INSTRUCTIONS ---\n{formatting_instructions}\n\n"

        final_prompt += "Your response should be the direct result of the task. Do not add any conversational text or extra formatting unless explicitly requested by the task description."
    # --- MODIFICATION END ---


    # --- MODIFICATION START: Pass user_uuid and planning_phase ---
    response_text, input_tokens, output_tokens, _, _ = await llm_handler.call_llm_api(
        llm_instance=llm_instance,
        prompt=final_prompt,
        reason=reason,
        system_prompt_override="You are a text processing and synthesis assistant.",
        raise_on_error=True,
        user_uuid=user_uuid,
        session_id=session_id,
        planning_phase="conversation"  # Track as conversation phase
    )
    # --- MODIFICATION END ---

    refusal_phrases = [
        "i'm unable to", "i cannot", "unable to generate", "no specific task",
        "as an ai model", "i can't provide"
    ]

    if any(phrase in response_text.lower() for phrase in refusal_phrases):
        app_logger.error(f"TDA_LLMTask failed due to detected LLM refusal. Response: '{response_text}'")
        result = {
            "status": "error",
            "error_message": "LLM refused to perform the synthesis task.",
            "data": response_text
        }
    else:
        result = {
            "status": "success",
            # --- MODIFICATION START: Add token counts to metadata ---
            "metadata": {
                "call_id": final_call_id,
                "tool_name": "TDA_LLMTask",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            },
            # --- MODIFICATION END ---
            "results": [{"response": response_text}]
        }

    return result, input_tokens, output_tokens

# --- MODIFICATION START: Add user_uuid ---
async def _invoke_final_report_task(STATE: dict, command: dict, workflow_state: dict, user_uuid: str = None, session_id: str = None, call_id: str | None = None) -> tuple[dict, int, int]:
# --- MODIFICATION END ---
    llm_instance = STATE.get('llm')
    user_question = command.get("arguments", {}).get("user_question", "No user question provided.")
    final_call_id = call_id or str(uuid.uuid4())

    # --- OPTIMIZATION START: Pass-through mode when tactical planner pre-formatted the report ---
    # If the tactical planner already generated a well-formatted "report" argument,
    # skip the LLM call and use it directly. This saves ~3,000 tokens per query.
    pre_formatted_report = command.get("arguments", {}).get("report")
    if pre_formatted_report and isinstance(pre_formatted_report, str) and len(pre_formatted_report.strip()) > 0:
        app_logger.info(f"TDA_FinalReport: Using pre-formatted report from tactical planner (pass-through mode)")

        result = {
            "status": "success",
            "metadata": {
                "call_id": final_call_id,
                "tool_name": "TDA_FinalReport",
                "input_tokens": 0,
                "output_tokens": 0,
                "optimization": "pass_through"
            },
            "results": [{
                "direct_answer": pre_formatted_report.strip(),
                "key_metric": None,
                "key_observations": []
            }],
            "corrections": []
        }
        return result, 0, 0
    # --- OPTIMIZATION END ---

    # --- MODIFICATION START: Extract and format knowledge context separately for clarity ---
    # Use .get() instead of .pop() to avoid modifying the original workflow_state
    knowledge_context = workflow_state.get('_knowledge_context')
    knowledge_section = ""
    if knowledge_context:
        knowledge_section = (
            "--- KNOWLEDGE CONTEXT (Concepts, Syntax, Best Practices) ---\n"
            f"{knowledge_context}\n\n"
        )
        # Create a copy without the knowledge context for the DATA section (avoid duplication)
        workflow_state_for_data = {k: v for k, v in workflow_state.items() if k != '_knowledge_context'}
    else:
        workflow_state_for_data = workflow_state
    # --- MODIFICATION END ---

    distilled_data, distill_meta = _distill_workflow_for_report(workflow_state_for_data)
    distilled_json = json.dumps(distilled_data, indent=2)

    final_summary_prompt_text = (
        "You are an expert data analyst. Your task is to create a final report for the user by analyzing the provided data and their original question.\n\n"
        f"--- USER'S ORIGINAL QUESTION ---\n{user_question}\n\n"
        f"{knowledge_section}"
        f"--- DATA FOR ANALYSIS ---\n{distilled_json}\n\n"
        "--- INSTRUCTIONS ---\n"
        "Your response MUST be a single JSON object that strictly follows the schema for a `CanonicalResponse`.\n"
        "You are required to populate its fields based on your analysis of the data provided above.\n"
        + ("If KNOWLEDGE CONTEXT is provided above, integrate relevant concepts, syntax examples, or best practices into your response alongside the data analysis.\n\n" if knowledge_context else "\n")
        + "--- FIELD GUIDELINES ---\n"
        "1.  `direct_answer`: REQUIRED. A single, concise sentence that directly and factually answers the user's primary question.\n"
        "2.  `key_metric`: OPTIONAL. Use ONLY if the answer can be summarized by a single, primary value (e.g., a total count, a status). Requires `value` (string) and `label` (string). Omit the entire field if not applicable.\n"
        "3.  `key_observations`: OPTIONAL. A list of objects, each with a `text` field containing a single, narrative bullet point of supporting detail or context. Do NOT include raw data or code."
    )

    reason = f"Client-Side Tool Call: TDA_FinalReport\nGoal: {user_question}"

    # --- FIX: Log prompt size to help diagnose large data issues ---
    raw_data_chars = len(json.dumps(workflow_state_for_data, indent=2))
    prompt_char_count = len(final_summary_prompt_text)
    app_logger.info(
        f"TDA_FinalReport: Prompt size={prompt_char_count:,} chars, "
        f"raw workflow_data={raw_data_chars:,} chars "
        f"(distilled to {prompt_char_count:,} in prompt)"
    )
    # --- END FIX ---

    # --- MODIFICATION START: Pass user_uuid and planning_phase ---
    response_text, input_tokens, output_tokens, _, _ = await llm_handler.call_llm_api(
        llm_instance=llm_instance,
        prompt=final_summary_prompt_text,
        reason=reason,
        system_prompt_override="You are a JSON-only reporting assistant.",
        raise_on_error=True,
        user_uuid=user_uuid,
        session_id=session_id,
        planning_phase="conversation"  # Track as conversation phase
    )
    # --- MODIFICATION END ---

    try:
        report_data, correction_descriptions = llm_handler.parse_and_coerce_llm_response(response_text, CanonicalResponse)

        result = {
            "status": "success",
            # --- MODIFICATION START: Add token counts to metadata ---
            "metadata": {
                "call_id": final_call_id,
                "tool_name": "TDA_FinalReport",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            },
            # --- MODIFICATION END ---
            "results": [report_data.model_dump()],
            "corrections": correction_descriptions
        }
        if distill_meta:
            result["_distillation_meta"] = distill_meta
        return result, input_tokens, output_tokens
    except (json.JSONDecodeError, ValidationError) as e:
        # --- FIX: More detailed error logging to diagnose parsing failures ---
        response_preview = response_text[:500] if len(response_text) > 500 else response_text
        response_end = response_text[-200:] if len(response_text) > 200 else ""
        app_logger.error(
            f"Failed to parse/validate TDA_FinalReport.\n"
            f"  Error: {e}\n"
            f"  Response length: {len(response_text)} chars\n"
            f"  Response start: {response_preview}\n"
            f"  Response end: {response_end}"
        )
        # --- END FIX ---
        return {"status": "error", "error_message": "Failed to generate valid report JSON.", "data": str(e)}, input_tokens, output_tokens

# --- MODIFICATION START: Add user_uuid ---
async def _invoke_complex_prompt_report_task(STATE: dict, command: dict, workflow_state: dict, user_uuid: str = None, session_id: str = None, call_id: str | None = None) -> tuple[dict, int, int]:
# --- MODIFICATION END ---
    llm_instance = STATE.get('llm')
    prompt_goal = command.get("arguments", {}).get("prompt_goal", "No prompt goal provided.")
    final_call_id = call_id or str(uuid.uuid4())

    distilled_data, distill_meta = _distill_workflow_for_report(workflow_state)
    distilled_json = json.dumps(distilled_data, indent=2)

    final_summary_prompt_text = (
        "You are an expert technical writer and data analyst. Your task is to synthesize all the collected data from a completed workflow into a formal, structured report that fulfills the original prompt's goal.\n\n"
        f"--- ORIGINAL PROMPT GOAL ---\n{prompt_goal}\n\n"
        f"--- ALL COLLECTED DATA ---\n{distilled_json}\n\n"
        "--- INSTRUCTIONS ---\n"
        "Your response MUST be a single JSON object that strictly follows the schema for a `PromptReportResponse`.\n\n"
        "--- FIELD GUIDELINES ---\n"
        "1.  `title`: REQUIRED. A clear, professional title for the report, derived from the ORIGINAL PROMPT GOAL.\n"
        "2.  `executive_summary`: REQUIRED. A concise, high-level summary paragraph explaining the key findings of the analysis.\n"
        "3.  `report_sections`: REQUIRED. A list of objects, where each object represents a logical section of the report. Each section object MUST have:\n"
        "    - `title`: The title for that specific section (e.g., 'Data Quality Analysis', 'Table DDL').\n"
        "    - `content`: The detailed findings for that section, formatted in markdown. You can use lists, bolding, code blocks, and MARKDOWN TABLES for clarity. When the prompt goal asks for tables, heatmaps, or rankings, you MUST include them as markdown tables inside the content string — do not defer rendering to the UI or use placeholders. Compute actual values from the data. IMPORTANT: Do NOT start the content with a markdown heading that repeats the section title — the title is already rendered separately by the UI."
    )

    raw_data_chars = len(json.dumps(workflow_state, indent=2))
    prompt_chars = len(final_summary_prompt_text)
    app_logger.info(
        f"TDA_ComplexPromptReport: raw workflow_state={raw_data_chars:,} chars, "
        f"distilled prompt={prompt_chars:,} chars"
    )

    reason = f"Client-Side Tool Call: TDA_ComplexPromptReport\nGoal: {prompt_goal}"

    # --- MODIFICATION START: Pass user_uuid ---
    response_text, input_tokens, output_tokens, _, _ = await llm_handler.call_llm_api(
        llm_instance=llm_instance,
        prompt=final_summary_prompt_text,
        reason=reason,
        system_prompt_override="You are a JSON-only reporting assistant.",
        raise_on_error=True,
        user_uuid=user_uuid,
        session_id=session_id
    )
    # --- MODIFICATION END ---

    try:
        report_data, correction_descriptions = llm_handler.parse_and_coerce_llm_response(response_text, PromptReportResponse)

        result = {
            "status": "success",
            # --- MODIFICATION START: Add token counts to metadata ---
            "metadata": {
                "call_id": final_call_id,
                "tool_name": "TDA_ComplexPromptReport",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            },
            # --- MODIFICATION END ---
            "results": [report_data.model_dump()],
            "corrections": correction_descriptions
        }
        if distill_meta:
            result["_distillation_meta"] = distill_meta
        return result, input_tokens, output_tokens
    except (json.JSONDecodeError, ValidationError) as e:
        app_logger.error(f"Failed to parse/validate TDA_ComplexPromptReport: {e}. Response: {response_text}")
        return {"status": "error", "error_message": "Failed to generate valid report JSON.", "data": str(e)}, input_tokens, output_tokens

# --- MODIFICATION START: Add user_uuid ---
async def _invoke_util_calculate_date_range(STATE: dict, command: dict, user_uuid: str = None, session_id: str = None) -> dict:
# --- MODIFICATION END ---
    args = command.get("arguments", {})
    start_date_str = args.get("start_date")
    date_phrase = args.get("date_phrase", "").lower().strip()

    app_logger.info(f"Executing client-side tool: TDA_DateRange with start: '{start_date_str}', phrase: '{date_phrase}'")

    if not start_date_str or not date_phrase:
        return {"status": "error", "error_message": "Missing start_date or date_phrase."}

    # Guard against unresolved placeholder dicts from planner
    if not isinstance(start_date_str, str):
        return {"status": "error", "error_message": f"start_date must be a string (got {type(start_date_str).__name__}). Likely an unresolved placeholder from the plan."}

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = None

    try:
        # Simplified deterministic logic - add more cases as needed
        if "yesterday" in date_phrase:
            start_date = start_date - timedelta(days=1)
            end_date = start_date
        elif "today" in date_phrase:
            end_date = start_date
        elif "past weekend" in date_phrase or "last weekend" in date_phrase:
            days_since_sunday = (start_date.weekday() - 6) % 7 # Sunday is 6
            end_date = start_date - timedelta(days=days_since_sunday + 1) # Go back to previous Sunday
            start_date = end_date - timedelta(days=1) # Previous Saturday
        elif "last week" in date_phrase or "past week" in date_phrase:
            start_of_last_week = start_date - timedelta(days=start_date.weekday() + 7)
            end_of_last_week = start_of_last_week + timedelta(days=6)
            start_date, end_date = start_of_last_week, end_of_last_week
        elif "last month" in date_phrase or "past month" in date_phrase:
            first_day_of_current_month = start_date.replace(day=1)
            last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
            first_day_of_last_month = last_day_of_last_month.replace(day=1)
            start_date, end_date = first_day_of_last_month, last_day_of_last_month
        elif "last year" in date_phrase or "past year" in date_phrase:
            first_day_of_last_year = start_date.replace(year=start_date.year - 1, month=1, day=1)
            last_day_of_last_year = start_date.replace(year=start_date.year - 1, month=12, day=31)
            start_date, end_date = first_day_of_last_year, last_day_of_last_year
        else:
            match = re.search(r'(\d+)\s+(day|week|month|year)s?', date_phrase)
            if match:
                quantity = int(match.group(1))
                unit = match.group(2)

                if "past" in date_phrase or "last" in date_phrase:
                    if unit == "day":
                        end_date = start_date - timedelta(days=1)
                        start_date = end_date - timedelta(days=quantity - 1)
                    elif unit == "week":
                        # End of previous week (Sunday)
                        end_date = start_date - timedelta(days=start_date.weekday() + 1)
                        # Start of N-1 weeks before that (Monday)
                        start_date = end_date - timedelta(weeks=quantity - 1, days=6)
                    elif unit == "month":
                        # Last day of previous month
                        end_date = start_date.replace(day=1) - timedelta(days=1)
                        # First day of N-1 months before that
                        start_date = end_date.replace(day=1)
                        for _ in range(quantity - 1):
                             start_date = (start_date - timedelta(days=1)).replace(day=1)
                    elif unit == "year":
                        # Last day of previous year
                        end_date = start_date.replace(month=1, day=1) - timedelta(days=1)
                        # First day of N-1 years before that
                        start_date = end_date.replace(year=end_date.year - (quantity - 1), month=1, day=1)

    except Exception as e:
        app_logger.warning(f"Deterministic date parsing failed with error: {e}. This may be expected for complex phrases.")
        end_date = None # Ensure fallback if deterministic logic fails

    # Fallback to LLM if deterministic logic didn't find a range
    if end_date is None:
        app_logger.info(f"Deterministic logic failed for '{date_phrase}'. Falling back to LLM-based date extraction.")

        llm_prompt = (
            f"Given the current date is {start_date_str}, analyze the phrase '{date_phrase}'. "
            "Determine the exact start and end dates for this phrase. "
            "Your response MUST be ONLY a single, valid JSON object with two keys: 'start_date' and 'end_date', both in 'YYYY-MM-DD' format."
        )

        # --- MODIFICATION START: Pass user_uuid ---
        response_text, _, _, _, _ = await llm_handler.call_llm_api(
            llm_instance=STATE.get('llm'),
            prompt=llm_prompt,
            reason=f"LLM fallback for complex date phrase: {date_phrase}",
            system_prompt_override="You are a helpful assistant that only responds with valid JSON.",
            raise_on_error=True,
            user_uuid=user_uuid,
            session_id=session_id
        )
        # --- MODIFICATION END ---

        try:
            # Added extraction logic for robustness
            json_match = re.search(r"```json\s*\n(.*?)\n\s*```|(\{.*\})", response_text, re.DOTALL)
            if not json_match: raise json.JSONDecodeError("No JSON found in LLM response", response_text, 0)
            json_str = json_match.group(1) or json_match.group(2)

            date_data = json.loads(json_str)
            start_date = datetime.strptime(date_data['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(date_data['end_date'], '%Y-%m-%d').date()
        except (json.JSONDecodeError, KeyError, ValueError, AttributeError) as e:
            error_msg = f"LLM fallback for date range failed to produce a valid result. Response: '{response_text}'. Error: {e}"
            app_logger.error(error_msg)
            return {"status": "error", "error_message": error_msg}

    # Generate the list of dates
    date_list = []
    current_date = start_date
    while current_date <= end_date:
        date_list.append({"date": current_date.strftime('%Y-%m-%d')})
        current_date += timedelta(days=1)

    return {
        "status": "success",
        "metadata": {"tool_name": "TDA_DateRange"},
        "results": date_list
    }

# --- MODIFICATION START: Add user_uuid ---
async def invoke_mcp_tool(STATE: dict, command: dict, user_uuid: str = None, session_id: str = None, call_id: str | None = None, workflow_state: dict = None) -> tuple[any, int, int]:
# --- MODIFICATION END ---
    mcp_client = STATE.get('mcp_client')
    tool_name = command.get("tool_name")

    # --- MODIFICATION START: Add handler for the new TDA_ContextReport tool ---
    if tool_name == "TDA_ContextReport":
        app_logger.info("Executing client-side tool: TDA_ContextReport")
        answer = command.get("arguments", {}).get("answer_from_context", "The agent has completed its work.")
        result = {
            "status": "success",
            "metadata": {"tool_name": "TDA_ContextReport"},
            "results": [{"response": answer}]
        }
        return result, 0, 0
    # --- MODIFICATION END ---

    if tool_name == "TDA_LLMFilter":
        # --- MODIFICATION START: Pass user_uuid ---
        return await _invoke_llm_filter_task(STATE, command, user_uuid=user_uuid, session_id=session_id, call_id=call_id)
        # --- MODIFICATION END ---

    if tool_name == "TDA_FinalReport":
        command.setdefault("arguments", {})["user_question"] = workflow_state.get("original_user_input", "N/A")
        # --- MODIFICATION START: Pass user_uuid and workflow_state correctly ---
        return await _invoke_final_report_task(STATE, command, workflow_state, user_uuid=user_uuid, session_id=session_id, call_id=call_id)
        # --- MODIFICATION END ---

    if tool_name == "TDA_ComplexPromptReport":
        command.setdefault("arguments", {})["prompt_goal"] = workflow_state.get("workflow_goal_prompt", "N/A")
        # --- MODIFICATION START: Pass user_uuid and workflow_state correctly ---
        return await _invoke_complex_prompt_report_task(STATE, command, workflow_state, user_uuid=user_uuid, session_id=session_id, call_id=call_id)
        # --- MODIFICATION END ---

    if tool_name == "TDA_LLMTask":
        args = command.get("arguments", {})
        # Ensure 'mode' and 'session_history' are popped so they aren't passed to the core logic
        mode = args.pop("mode", "standard")
        session_history = args.pop("session_history", None)
        # Reconstruct the command with the remaining args for the core task function
        command_for_core = {"tool_name": "TDA_LLMTask", "arguments": args}
        # --- MODIFICATION START: Pass user_uuid and workflow_state correctly ---
        # Note: workflow_state contains the *entire* state, including results from previous phases.
        # _invoke_core_llm_task will handle extracting the relevant parts based on 'source_data' or using 'data' if present.
        return await _invoke_core_llm_task(STATE, command_for_core, workflow_state=workflow_state, user_uuid=user_uuid, session_history=session_history, mode=mode, session_id=session_id, call_id=call_id)
        # --- MODIFICATION END ---


    if tool_name == "TDA_CurrentDate":
        app_logger.info("Executing client-side tool: TDA_CurrentDate")
        current_date = datetime.now().strftime('%Y-%m-%d')
        result = {
            "status": "success",
            "metadata": {"tool_name": "TDA_CurrentDate"},
            "results": [{"current_date": current_date}]
        }
        return result, 0, 0

    if tool_name == "TDA_DateRange":
        # --- MODIFICATION START: Pass user_uuid ---
        result = await _invoke_util_calculate_date_range(STATE, command, user_uuid=user_uuid, session_id=session_id)
        # --- MODIFICATION END ---
        return result, 0, 0

    if tool_name == "TDA_Charting":
        app_logger.info(f"Handling abstract chart generation for: {command}")

        try:
            args = command.get("arguments", {})
            data = args.get("data")
            # --- Robust Data Transformation ---
            data = _transform_chart_data(data)

            if not isinstance(data, list) or not data:
                # Handle empty list case specifically
                if isinstance(data, list) and not data:
                     error_detail = "The 'data' argument was an empty list. Cannot generate chart without data."
                else: # Handle non-list case
                     error_detail = "The 'data' argument must be a non-empty list of dictionaries."
                result = {"status": "error", "error": "Validation failed", "data": error_detail}
                return result, 0, 0

            # Ensure data is list of dicts after transformation
            if not all(isinstance(item, dict) for item in data):
                result = {"status": "error", "error": "Validation failed", "data": "Transformed 'data' is not a list of dictionaries."}
                return result, 0, 0

            chart_spec = _build_g2plot_spec(args, data)

            result = {"type": "chart", "spec": chart_spec, "metadata": {"tool_name": "TDA_Charting"}}
            return result, 0, 0
        except Exception as e:
            app_logger.error(f"Error building G2Plot spec: {e}", exc_info=True)
            result = {"status": "error", "error": "Chart Generation Failed", "data": str(e)}
            return result, 0, 0

    # --- Argument Extraction and Normalization ---
    args = {}
    if isinstance(command, dict):
        potential_arg_keys = [
            "arguments", "args", "tool_args", "parameters",
            "tool_input", "action_input", "tool_arguments"
        ]

        found_args = None
        # Check top-level keys first
        for key in potential_arg_keys:
            if key in command and isinstance(command[key], dict):
                found_args = command[key]
                break

        # If not found, check nested structures (e.g., {"action": {"arguments": ...}})
        if found_args is None:
            possible_wrapper_keys = ["action", "tool"]
            for wrapper_key in possible_wrapper_keys:
                if wrapper_key in command and isinstance(command[wrapper_key], dict):
                    nested_dict = command[wrapper_key]
                    for arg_key in potential_arg_keys:
                        if arg_key in nested_dict and isinstance(nested_dict[arg_key], dict):
                            found_args = nested_dict[arg_key]
                            break # Found args in nested structure
                    if found_args is not None:
                        break # Found args, no need to check other wrapper keys

        # Fallback: Assume the whole command *might* be the args if no standard keys found
        if found_args is None and command and all(k not in command for k in ["tool_name", "action", "tool"]):
             app_logger.warning(f"Could not find standard argument key for tool '{tool_name}'. Assuming entire command object contains arguments: {command}")
             found_args = command

    # Ensure found_args is a dict before normalization
    args = found_args if isinstance(found_args, dict) else {}

    normalized_args = _normalize_tool_arguments(args)
    if normalized_args != args:
        app_logger.debug(f"Normalized tool arguments for '{tool_name}'")

    args = normalized_args

    # --- MODIFICATION START: Implement Intelligent Argument Alignment ---
    tool_def = STATE.get('mcp_tools', {}).get(tool_name)
    aligned_args = args.copy()

    if tool_def and hasattr(tool_def, 'args') and isinstance(tool_def.args, dict):
        tool_arg_names = set(tool_def.args.keys()) # Names the actual tool expects
        canonical_to_synonyms_map = AppConfig.ARGUMENT_SYNONYM_MAP

        # Iterate through the *canonical* names we have after normalization
        for canonical_name in list(aligned_args.keys()):
            # If the canonical name itself is NOT what the tool expects...
            if canonical_name not in tool_arg_names:
                # ...find all synonyms for this canonical name.
                synonyms = canonical_to_synonyms_map.get(canonical_name, set())

                # Check if any of those synonyms ARE what the tool expects.
                for synonym in synonyms:
                    if synonym in tool_arg_names:
                        # Found a match! The tool wants this specific synonym.
                        app_logger.debug(f"Aligning argument for '{tool_name}': '{canonical_name}' -> '{synonym}'")
                        # Rename the key in our arguments to match the tool's expectation.
                        aligned_args[synonym] = aligned_args.pop(canonical_name)
                        break # Found the correct synonym, move to the next canonical name
    # --- MODIFICATION END ---


    app_logger.debug(f"[MCP] Calling tool '{tool_name}' with args: {aligned_args}")
    try:
        # Use server ID instead of name for session management
        server_id = get_user_mcp_server_id(user_uuid)
        if not server_id:
            raise Exception("MCP server ID not found in configuration.")

        async with mcp_client.session(server_id) as temp_session:
            call_tool_result = await temp_session.call_tool(tool_name, aligned_args)
    except Exception as e:
        app_logger.error(f"❌ [MCP CALL ERROR] Tool '{tool_name}' failed: {e}", exc_info=True)
        result = {"status": "error", "error": f"An exception occurred while invoking tool '{tool_name}'.", "data": str(e)}
        return result, 0, 0

    # --- Robust Result Parsing ---
    # Try to parse the standard content structure
    if hasattr(call_tool_result, 'content') and isinstance(call_tool_result.content, list) and len(call_tool_result.content) > 0:
        text_content_obj = call_tool_result.content[0]
        if hasattr(text_content_obj, 'text') and isinstance(text_content_obj.text, str):
            raw_text = text_content_obj.text
            try:
                # Attempt to find JSON within the string
                json_match = re.search(r'\{.*\}|\[.*\]', raw_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    result = json.loads(json_str)
                    # Add metadata if missing and result looks like success
                    if isinstance(result, dict) and "metadata" not in result and "status" not in result:
                         result["metadata"] = {"tool_name": tool_name}
                         result["status"] = "success"
                    # --- MODIFICATION START: Add tool_name to existing metadata if missing ---
                    elif isinstance(result, dict) and "metadata" in result and isinstance(result["metadata"], dict) and "tool_name" not in result["metadata"]:
                         result["metadata"]["tool_name"] = tool_name
                    # --- MODIFICATION END ---
                    return result, 0, 0
                else:
                    # If no JSON found, treat as potential error string
                    app_logger.warning(f"Tool '{tool_name}' returned a non-JSON string: '{raw_text}' - treating as error.")
                    result = {"status": "error", "error": "Tool returned non-JSON string", "data": raw_text}
                    return result, 0, 0
            except json.JSONDecodeError:
                app_logger.warning(f"Tool '{tool_name}' returned a malformed JSON string: '{raw_text}' - treating as error.")
                result = {"status": "error", "error": "Tool returned malformed JSON string", "data": raw_text}
                return result, 0, 0

    # Fallback for unexpected formats - log and return error
    app_logger.error(f"Unexpected tool result format for '{tool_name}': {call_tool_result}")
    result = {"status": "error", "error": "Unexpected tool result format", "data": str(call_tool_result)}
    return result, 0, 0