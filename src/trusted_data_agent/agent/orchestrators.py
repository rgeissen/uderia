# trusted_data_agent/agent/orchestrators.py
import json
import logging
from datetime import datetime, timedelta, timezone
import re

from trusted_data_agent.mcp_adapter import adapter as mcp_adapter
from trusted_data_agent.llm import handler as llm_handler
from trusted_data_agent.core.config import AppConfig
from trusted_data_agent.core.utils import get_argument_by_canonical_name


app_logger = logging.getLogger("quart.app")

def _format_sse(data: dict, event: str = None) -> str:
    """Helper to format data for Server-Sent Events."""
    msg = f"data: {json.dumps(data)}\n"
    if event is not None:
        msg += f"event: {event}\n"
    return f"{msg}\n"

# --- MODIFICATION START: Add user_uuid ---
async def execute_date_range_orchestrator(executor, command: dict, date_param_name: str, date_phrase: str, phase: dict):
# --- MODIFICATION END ---
    """
    Executes a tool over a calculated date range when the tool itself
    only supports a single date parameter. It is now "plan-aware" and will use
    pre-calculated date lists from previous phases if available, bypassing
    redundant LLM calls.
    """
    tool_name = command.get("tool_name")
    args = command.get("arguments", {})
    date_list = []
    # --- MODIFICATION START: Get user_uuid from executor ---
    user_uuid = executor.user_uuid
    # --- MODIFICATION END ---

    # --- MODIFICATION START: Plan-Aware and Resilient Date Handling ---
    is_pre_calculated = False
    arg_value = args.get(date_param_name)

    # Scenario 1: The date argument points to a pre-calculated list in the workflow state.
    if isinstance(arg_value, dict) and "source" in arg_value:
        source_key = arg_value.get("source")
        if source_key in executor.workflow_state:
            source_data = executor.workflow_state[source_key]
            if (isinstance(source_data, list) and len(source_data) > 0 and 
                isinstance(source_data[0], dict) and 'results' in source_data[0]):
                
                potential_dates = source_data[0]['results']
                if isinstance(potential_dates, list) and all(isinstance(d, dict) and 'date' in d for d in potential_dates):
                    date_list = potential_dates
                    is_pre_calculated = True

    # Scenario 1.5: Validate date argument format before proceeding
    if not is_pre_calculated:
        # If arg_value is a dict placeholder, log error and fail fast
        if isinstance(arg_value, dict) and ("source" in arg_value or "key" in arg_value):
            yield _format_sse({
                "step": "System Correction", "type": "workaround",
                "details": (
                    f"Date Range Orchestrator received unresolved placeholder: {arg_value}. "
                    f"This indicates fast-path validation failed. Falling back to tactical planning."
                )
            })
            app_logger.error(
                f"ORCHESTRATOR GUARD: Unresolved placeholder detected in date argument: {arg_value}. "
                f"Fast-path validation should have blocked this. Forcing tactical planning."
            )

            # Raise error to trigger phase retry with tactical planning
            raise ValueError(
                f"Date argument contains unresolved placeholder: {arg_value}. "
                f"Cannot proceed with orchestration. Requires tactical planning."
            )

        # If arg_value is a temporal phrase string, it should have been resolved
        if isinstance(arg_value, str) and not re.match(r'^\d{4}-\d{2}-\d{2}$', arg_value):
            temporal_patterns = [
                r'past\s+\d+\s+(hours?|days?|weeks?|months?)',
                r'last\s+\d+\s+(hours?|days?|weeks?|months?)',
                r'(yesterday|today)'
            ]
            if any(re.search(pattern, arg_value.lower()) for pattern in temporal_patterns):
                yield _format_sse({
                    "step": "System Correction", "type": "workaround",
                    "details": (
                        f"Date Range Orchestrator received temporal phrase '{arg_value}' "
                        f"instead of resolved dates. Forcing tactical planning."
                    )
                })
                app_logger.error(
                    f"ORCHESTRATOR GUARD: Temporal phrase '{arg_value}' was not resolved. "
                    f"This indicates fast-path incorrectly executed. Forcing tactical planning."
                )
                raise ValueError(
                    f"Date argument contains unresolved temporal phrase: '{arg_value}'. "
                    f"Requires tactical planning to resolve dates."
                )

    # Scenario 2: The date argument is a single, valid date string (prevents recursion).
    if not is_pre_calculated and isinstance(arg_value, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', arg_value):
        yield _format_sse({
            "step": "System Correction", "type": "workaround",
            "details": "Orchestrator called with a single date; executing directly to prevent recursion."
        })
        yield _format_sse({"target": "db", "state": "busy"}, "status_indicator_update")
        # --- MODIFICATION START: Pass user_uuid ---
        single_result, _, _ = await mcp_adapter.invoke_mcp_tool(
            executor.dependencies['STATE'], command, user_uuid=user_uuid, session_id=executor.session_id
        )
        # --- MODIFICATION END ---
        yield _format_sse({"target": "db", "state": "idle"}, "status_indicator_update")
        
        executor._add_to_structured_data(single_result)
        executor.last_tool_output = single_result
        return # Exit the orchestrator

    if is_pre_calculated:
        yield _format_sse({
            "step": "Plan Optimization", "type": "plan_optimization",
            "details": "Date Range Orchestrator is using pre-calculated date list from a previous phase."
        })
    else:
        # Scenario 3: Fallback to original LLM-based calculation for natural language phrases.
        yield _format_sse({
            "step": "System Orchestration", "type": "workaround",
            "details": f"Detected date range query ('{date_phrase}') for single-day tool ('{tool_name}')."
        })
        
        # Log orchestration event to turn_action_history for RAG processing visibility
        phase_num = phase.get("phase", executor.current_phase_index + 1)
        orchestration_event = {
            "action": {
                "tool_name": "TDA_SystemOrchestration",
                "arguments": {
                    "orchestration_type": "date_range",
                    "target_tool": tool_name,
                    "date_phrase": date_phrase,
                    "date_param_name": date_param_name
                },
                "metadata": {
                    "phase_number": phase_num,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "is_orchestration": True
                }
            },
            "result": {
                "status": "orchestration_started",
                "metadata": {"comment": "Date range orchestration initiated"},
                "results": []
            }
        }
        executor.turn_action_history.append(orchestration_event)

        date_command = {"tool_name": "TDA_CurrentDate"}
        # --- MODIFICATION START: Pass user_uuid ---
        date_result, _, _ = await mcp_adapter.invoke_mcp_tool(
            executor.dependencies['STATE'], date_command, user_uuid=user_uuid, session_id=executor.session_id
        )
        # --- MODIFICATION END ---
        if not (date_result and date_result.get("status") == "success" and date_result.get("results")):
            raise RuntimeError("Date Range Orchestrator failed to fetch current date.")
        current_date_str = date_result["results"][0].get("current_date")

        conversion_prompt = (
            f"Given the current date is {current_date_str}, "
            f"what are the start and end dates for '{date_phrase}'? "
            "Respond with ONLY a JSON object with 'start_date' and 'end_date' in YYYY-MM-DD format."
        )
        reason = "Calculating date range."
        yield _format_sse({"step": "Calling LLM", "details": {"summary": reason}})
        yield _format_sse({"target": "llm", "state": "busy"}, "status_indicator_update")
        range_response_str, _, _ = await executor._call_llm_and_update_tokens(
            prompt=conversion_prompt, reason=reason,
            system_prompt_override="You are a JSON-only responding assistant.", raise_on_error=True
        )
        yield _format_sse({"target": "llm", "state": "idle"}, "status_indicator_update")
        
        try:
            # Added extraction logic to handle conversational models
            json_match = re.search(r"```json\s*\n(.*?)\n\s*```|(\{.*\})", range_response_str, re.DOTALL)
            if not json_match: raise json.JSONDecodeError("No JSON found in LLM response", range_response_str, 0)
            json_str = json_match.group(1) or json_match.group(2)

            range_data = json.loads(json_str)
            start_date = datetime.strptime(range_data['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(range_data['end_date'], '%Y-%m-%d').date()
            
            current_date_in_loop = start_date
            while current_date_in_loop <= end_date:
                date_list.append({"date": current_date_in_loop.strftime('%Y-%m-%d')})
                current_date_in_loop += timedelta(days=1)

        except (json.JSONDecodeError, KeyError, ValueError, AttributeError) as e:
            raise RuntimeError(f"Date Range Orchestrator failed to parse date range. Error: {e}")
    # --- MODIFICATION END ---

    if not date_list or not all(isinstance(d, dict) and 'date' in d for d in date_list):
         raise RuntimeError(f"Orchestrator failed: Date list is empty or malformed. Content: {date_list}")

    cleaned_command_args = { k: v for k, v in args.items() if 'date' not in k.lower() }
    cleaned_command = {**command, 'arguments': cleaned_command_args}

    all_results = []
    yield _format_sse({"target": "db", "state": "busy"}, "status_indicator_update")
    for date_item in date_list:
        date_str = date_item['date']
        yield _format_sse({"step": f"Processing data for: {date_str}"})
        
        day_command = {**cleaned_command, 'arguments': {**cleaned_command['arguments'], date_param_name: date_str}}
        # --- MODIFICATION START: Pass user_uuid ---
        day_result, _, _ = await mcp_adapter.invoke_mcp_tool(
            executor.dependencies['STATE'], day_command, user_uuid=user_uuid, session_id=executor.session_id
        )
        # Add timestamp metadata for timing analysis
        day_command.setdefault("metadata", {})["timestamp"] = datetime.now(timezone.utc).isoformat()
        executor.turn_action_history.append({"action": day_command, "result": day_result})
        # --- MODIFICATION END ---
        
        if isinstance(day_result, dict) and day_result.get("status") == "success" and day_result.get("results"):
            all_results.extend(day_result["results"])
        
    yield _format_sse({"target": "db", "state": "idle"}, "status_indicator_update")
    
    final_tool_output = {
        "status": "success",
        "metadata": {"tool_name": tool_name, "comment": f"Consolidated results for {date_phrase}"},
        "results": all_results
    }

    phase_num = phase.get("phase", executor.current_phase_index + 1)
    phase_result_key = f"result_of_phase_{phase_num}"
    executor.workflow_state[phase_result_key] = [final_tool_output]
    
    executor._add_to_structured_data(final_tool_output)
    executor.last_tool_output = final_tool_output
    
    # Log orchestration completion to turn_action_history
    orchestration_complete_event = {
        "action": {
            "tool_name": "TDA_SystemOrchestration",
            "arguments": {
                "orchestration_type": "date_range_complete",
                "target_tool": tool_name,
                "num_iterations": len(date_list)
            },
            "metadata": {
                "phase_number": phase_num,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "is_orchestration": True
            }
        },
        "result": final_tool_output
    }
    executor.turn_action_history.append(orchestration_complete_event)

# --- MODIFICATION START: Add user_uuid ---
async def execute_column_iteration(executor, command: dict):
# --- MODIFICATION END ---
    """
    Executes a tool over multiple columns of a table, including checks for
    data type compatibility.
    """
    tool_name = command.get("tool_name")
    base_args = command.get("arguments", {})
    # --- MODIFICATION START: Get user_uuid from executor ---
    user_uuid = executor.user_uuid
    # --- MODIFICATION END ---

    # --- MODIFICATION START: Use synonym-aware helper to get arguments ---
    db_name = get_argument_by_canonical_name(base_args, 'database_name')
    table_name = get_argument_by_canonical_name(base_args, 'object_name')
    # --- MODIFICATION END ---

    cols_command = {"tool_name": "base_columnDescription", "arguments": {"database_name": db_name, "object_name": table_name}}
    yield _format_sse({"target": "db", "state": "busy"}, "status_indicator_update")
    # --- MODIFICATION START: Pass user_uuid ---
    cols_result, _, _ = await mcp_adapter.invoke_mcp_tool(
        executor.dependencies['STATE'], cols_command, user_uuid=user_uuid, session_id=executor.session_id
    )
    # --- MODIFICATION END ---
    yield _format_sse({"target": "db", "state": "idle"}, "status_indicator_update")
    
    if not (cols_result and isinstance(cols_result, dict) and cols_result.get('status') == 'success' and cols_result.get('results')):
        raise ValueError(f"Failed to retrieve column list for iteration. Response: {cols_result}")
    
    all_columns_metadata = cols_result.get('results', [])
    all_column_results = [cols_result]
    
    yield _format_sse({"target": "llm", "state": "busy"}, "status_indicator_update")
    # --- MODIFICATION START: Call the relocated method on the main executor ---
    tool_constraints, constraint_events = await executor._get_tool_constraints(tool_name)
    for event in constraint_events:
        yield event
    # --- MODIFICATION END ---
    yield _format_sse({"target": "llm", "state": "idle"}, "status_indicator_update")
    required_type = tool_constraints.get("dataType") if tool_constraints else None
    
    yield _format_sse({"target": "db", "state": "busy"}, "status_indicator_update")
    for column_info in all_columns_metadata:
        column_name = column_info.get("ColumnName")
        col_type = next((v for k, v in column_info.items() if "type" in k.lower()), "").upper()

        if required_type and col_type != "UNKNOWN":
            is_numeric = any(t in col_type for t in ["INT", "NUMERIC", "DECIMAL", "FLOAT"])
            is_char = any(t in col_type for t in ["CHAR", "VARCHAR", "TEXT"])
            if (required_type == "numeric" and not is_numeric) or \
               (required_type == "character" and not is_char):
                skipped_result = {"status": "skipped", "metadata": {"tool_name": tool_name, "column_name": column_name}, "results": [{"reason": f"Tool requires {required_type}, but '{column_name}' is {col_type}."}]}
                all_column_results.append(skipped_result)
                yield _format_sse({"step": "Skipping incompatible column", "details": skipped_result}, "tool_result")
                continue
        
        # --- MODIFICATION START: Explicitly replace placeholder column_name ---
        # Create a mutable copy of the base arguments for this iteration.
        iter_args = base_args.copy()
        # Find all synonyms for 'column_name' that might exist in the arguments.
        column_synonyms = AppConfig.ARGUMENT_SYNONYM_MAP.get('column_name', set())
        # Remove any placeholder synonyms (like '*') from the arguments.
        for synonym in column_synonyms:
            if synonym in iter_args:
                del iter_args[synonym]
        # Set the one, correct 'column_name' for this specific iteration.
        iter_args['column_name'] = column_name
        
        iter_command = {"tool_name": tool_name, "arguments": iter_args}
        # --- MODIFICATION END ---
        # --- MODIFICATION START: Pass user_uuid ---
        col_result, _, _ = await mcp_adapter.invoke_mcp_tool(
            executor.dependencies['STATE'], iter_command, user_uuid=user_uuid, session_id=executor.session_id
        )
        # --- MODIFICATION END ---
        all_column_results.append(col_result)
    yield _format_sse({"target": "db", "state": "idle"}, "status_indicator_update")

    executor._add_to_structured_data(all_column_results)
    executor.last_tool_output = {"metadata": {"tool_name": tool_name}, "results": all_column_results, "status": "success"}

async def execute_hallucinated_loop(executor, phase: dict):
    """
    Handles cases where the planner hallucinates a loop over a list of natural
    language strings instead of a proper data source. It uses an LLM to
    semantically understand the intent and then executes a deterministic loop.
    """
    tool_name = phase.get("relevant_tools", [None])[0]
    hallucinated_items = phase.get("loop_over", [])
    
    yield _format_sse({
        "step": "System Correction", "type": "workaround",
        "details": f"Planner hallucinated a loop. Correcting with generalized orchestrator for items: {hallucinated_items}"
    })

    if len(hallucinated_items) == 1 and isinstance(hallucinated_items[0], str):
        date_keywords = ["day", "week", "month", "year", "past", "last", "next"]
        if any(keyword in hallucinated_items[0].lower() for keyword in date_keywords):
            command_for_date_orchestrator = {"tool_name": tool_name, "arguments": {}}
            async for event in execute_date_range_orchestrator(executor, command_for_date_orchestrator, 'date', hallucinated_items[0]):
                yield event
            return

    semantic_prompt = (
        f"Given the tool `{tool_name}` and the list of items `{json.dumps(hallucinated_items)}`, "
        "what single tool argument name do these items represent? "
        "Respond with only a JSON object, like `{{\"argument_name\": \"table_name\"}}`."
    )
    reason = "Semantically analyzing hallucinated loop items."
    yield _format_sse({"step": "Calling LLM", "details": {"summary": reason}})
    yield _format_sse({"target": "llm", "state": "busy"}, "status_indicator_update")
    response_str, _, _ = await executor._call_llm_and_update_tokens(
        prompt=semantic_prompt, reason=reason,
        system_prompt_override="You are a JSON-only responding assistant.", raise_on_error=True
    )
    yield _format_sse({"target": "llm", "state": "idle"}, "status_indicator_update")
    
    try:
        semantic_data = json.loads(response_str)
        argument_name = semantic_data.get("argument_name")
        if not argument_name:
            raise ValueError("LLM did not provide an 'argument_name'.")
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(f"Failed to semantically understand hallucinated loop items. Error: {e}")

    all_results = []
    yield _format_sse({"target": "db", "state": "busy"}, "status_indicator_update")
    for item in hallucinated_items:
        yield _format_sse({"step": f"Processing item: {item}"})
        command = {"tool_name": tool_name, "arguments": {argument_name: item}}
        # --- MODIFICATION START: Pass user_uuid ---
        result, _, _ = await mcp_adapter.invoke_mcp_tool(
            executor.dependencies['STATE'], command, user_uuid=executor.user_uuid, session_id=executor.session_id
        )
        # --- MODIFICATION END ---
        all_results.append(result)
    yield _format_sse({"target": "db", "state": "idle"}, "status_indicator_update")

    executor._add_to_structured_data(all_results)
    executor.last_tool_output = {"metadata": {"tool_name": tool_name}, "results": all_results, "status": "success"}

