# trusted_data_agent/agent/planner.py
import re
import json
import logging
import copy
import uuid
from typing import TYPE_CHECKING, Optional
from pathlib import Path

from langchain_mcp_adapters.prompts import load_mcp_prompt

from trusted_data_agent.core import session_manager
from trusted_data_agent.core.config import APP_CONFIG
from trusted_data_agent.agent.prompts import (
    WORKFLOW_META_PLANNING_PROMPT,
)
from trusted_data_agent.agent.rag_access_context import RAGAccessContext  # --- MODIFICATION: Import RAGAccessContext ---

if TYPE_CHECKING:
    from trusted_data_agent.agent.executor import PlanExecutor
    from trusted_data_agent.agent.rag_retriever import RAGRetriever  # Type hint only - lazy loaded at runtime


app_logger = logging.getLogger("quart.app")


def get_prompt_text_content(prompt_obj):
    """
    Extracts the text content from a loaded prompt object, handling different
    potential formats returned by the MCP adapter.
    """
    if isinstance(prompt_obj, str):
        return prompt_obj
    if (isinstance(prompt_obj, list) and
        len(prompt_obj) > 0 and
        hasattr(prompt_obj[0], 'content') and
        isinstance(prompt_obj[0].content, str)):
        return prompt_obj[0].content
    elif (isinstance(prompt_obj, dict) and
        'messages' in prompt_obj and
        isinstance(prompt_obj['messages'], list) and
        len(prompt_obj['messages']) > 0 and
        'content' in prompt_obj['messages'][0] and
        isinstance(prompt_obj['messages'][0]['content'], dict) and
        'text' in prompt_obj['messages'][0]['content']):
        return prompt_obj['messages'][0]['content']['text']

    return ""


class Planner:
    """
    Encapsulates all logic related to plan generation, validation, and refinement.
    It is instantiated by the PlanExecutor and maintains a reference to it for state
    and helper method access.
    """
    # --- MODIFICATION START: Accept RAGRetriever instance from executor ---
    def __init__(self, executor: 'PlanExecutor', rag_retriever_instance: Optional['RAGRetriever'] = None, event_handler=None):
        self.executor = executor
        self.rag_retriever = rag_retriever_instance
        self.event_handler = event_handler
        if APP_CONFIG.RAG_ENABLED and not self.rag_retriever:
            app_logger.warning("Planner initialized without a RAGRetriever instance, though RAG is enabled.")
        elif APP_CONFIG.RAG_ENABLED and self.rag_retriever:
            app_logger.info("Planner initialized with global RAGRetriever instance.")
    # --- MODIFICATION END ---

    # --- MODIFICATION START: Update history creation to filter by context validity ---
    def _create_summary_from_history(self, history: dict) -> str:
        """
        Creates an enhanced summary of previous workflow history for planning context.

        Includes explicit turn metadata to help the planner:
        - Identify the most recent turn
        - Understand profile types used
        - Extract SQL queries from conversation context

        This function filters out any turns marked with 'isValid': false.
        """
        if not history or not isinstance(history, dict) or "workflow_history" not in history:
            return json.dumps({"workflow_history": []}, indent=2)

        # 1. Get the full workflow history
        full_workflow_history = history.get("workflow_history", [])
        if not isinstance(full_workflow_history, list):
             return json.dumps({"workflow_history": []}, indent=2)

        # 2. Filter for valid turns only
        # A turn is valid if 'isValid' is missing (defaults to true) or is explicitly true.
        valid_workflow_history = [
            turn for turn in full_workflow_history
            if isinstance(turn, dict) and turn.get("isValid", True) is not False
        ]

        # --- MODIFICATION START: Scrub TDA_SystemLog messages and add turn metadata ---
        scrubbed_workflow_history = []
        for idx, turn in enumerate(valid_workflow_history):
            new_turn = copy.deepcopy(turn)

            # Remove UI-only fields from context to keep it lean
            # These are stored for plan reload UI but not needed for LLM planning
            ui_only_fields = [
                "genie_events",
                "slave_sessions",
                "provider",
                "model",
                "status",
                "conversation_agent_events",
                "knowledge_events",  # Event stream for RAG/knowledge profiles (UI replay only)
                "system_events",  # System operations like session name generation (UI replay only)
                "knowledge_chunks_ui",  # Document chunks for UI display (extracted from knowledge_retrieval_event)
                "session_input_tokens",  # Session totals for UI display only
                "session_output_tokens",  # Session totals for UI display only
                "final_summary_html",  # HTML formatted output (UI only, LLM uses final_summary_text)
                "tts_payload"  # Text-to-speech data (UI only)
            ]
            for field in ui_only_fields:
                if field in new_turn:
                    del new_turn[field]

            # Remove heavy chunks array from knowledge_retrieval_event (already in knowledge_chunks_ui)
            if "knowledge_retrieval_event" in new_turn and isinstance(new_turn["knowledge_retrieval_event"], dict):
                if "chunks" in new_turn["knowledge_retrieval_event"]:
                    del new_turn["knowledge_retrieval_event"]["chunks"]

            if "execution_trace" in new_turn and isinstance(new_turn["execution_trace"], list):
                scrubbed_trace = []
                for entry in new_turn["execution_trace"]:
                    if isinstance(entry, dict):
                        action_data = entry.get("action", {})
                        if isinstance(action_data, dict) and action_data.get("tool_name") != "TDA_SystemLog":
                            scrubbed_trace.append(entry)
                new_turn["execution_trace"] = scrubbed_trace

            # Add explicit metadata for planning context
            new_turn["turn_metadata"] = {
                "turn_number": new_turn.get("turn", idx + 1),
                "profile_tag": new_turn.get("profile_tag", "unknown"),
                "profile_type": new_turn.get("profile_type", "unknown"),
                "is_most_recent": (idx == len(valid_workflow_history) - 1)
            }

            # Extract SQL queries from final_summary_text (for llm_only turns)
            # This helps the planner find SQL queries that weren't executed
            if "final_summary_text" in new_turn:
                # Try multiple SQL extraction patterns
                sql_pattern_with_backticks = r"```sql\n(.*?)\n```"
                sql_pattern_generic = r"```\n(SELECT.*?)\n```"
                sql_pattern_plain = r"(SELECT\s+.+?FROM\s+.+?(?:WHERE\s+.+?)?(?:GROUP\s+BY\s+.+?)?(?:ORDER\s+BY\s+.+?)?;)"

                sql_matches = []
                # Try markdown SQL block first
                sql_matches.extend(re.findall(sql_pattern_with_backticks, new_turn["final_summary_text"], re.DOTALL | re.IGNORECASE))
                # Try generic code block
                if not sql_matches:
                    sql_matches.extend(re.findall(sql_pattern_generic, new_turn["final_summary_text"], re.DOTALL | re.IGNORECASE))
                # Try plain SELECT statement
                if not sql_matches:
                    sql_matches.extend(re.findall(sql_pattern_plain, new_turn["final_summary_text"], re.DOTALL | re.IGNORECASE))

                if sql_matches:
                    new_turn["turn_metadata"]["sql_mentioned_in_conversation"] = sql_matches
                    app_logger.debug(f"Extracted {len(sql_matches)} SQL queries from turn {new_turn.get('turn', idx + 1)} (profile: {new_turn.get('profile_tag')})")

            scrubbed_workflow_history.append(new_turn)
        # --- MODIFICATION END ---

        # 3. Create the final history object with only valid turns
        # Add summary header with context
        valid_history_summary = {
            "total_turns": len(scrubbed_workflow_history),
            "most_recent_turn_number": scrubbed_workflow_history[-1].get("turn", len(scrubbed_workflow_history)) if scrubbed_workflow_history else 0,
            "workflow_history": scrubbed_workflow_history
        }

        app_logger.debug(f"Planner context created. Original turns: {len(full_workflow_history)}, Valid (active) turns: {len(valid_workflow_history)}")

        return json.dumps(valid_history_summary, indent=2)
    # --- MODIFICATION END ---

    def _hydrate_plan_from_previous_turn(self):
        """
        Detects if a plan starts with a loop that depends on data from the
        previous turn, and if so, injects that data into the current state.
        This is the "plan injection" feature.
        """
        if not self.executor.meta_plan or not self.executor.previous_turn_data:
            return

        first_phase = self.executor.meta_plan[0]
        is_candidate = (
            first_phase.get("type") == "loop" and
            isinstance(first_phase.get("loop_over"), str) and
            first_phase.get("loop_over").startswith("result_of_phase_")
        )

        if not is_candidate:
            return

        looping_phase_num = first_phase.get("phase")
        source_phase_key = first_phase.get("loop_over")
        source_phase_num_match = re.search(r'\d+', source_phase_key)
        if not source_phase_num_match:
            return
        source_phase_num = int(source_phase_num_match.group())

        if source_phase_num >= looping_phase_num:
            data_to_inject = None

            workflow_history = self.executor.previous_turn_data.get("workflow_history", [])
            if not isinstance(workflow_history, list):
                 return

            for turn in reversed(workflow_history):
                if not isinstance(turn, dict): continue
                execution_trace = turn.get("execution_trace", [])
                for entry in reversed(execution_trace):
                    result_summary = entry.get("tool_output_summary", {})
                    if (isinstance(result_summary, dict) and
                        result_summary.get("status") == "success"):

                        data_to_inject = {
                            "status": "success",
                            "metadata": result_summary.get("metadata", {}),
                            "comment": "Data injected from previous turn's summary."
                        }
                        if "results" in result_summary:
                            data_to_inject["results"] = result_summary["results"]

                        break
                if data_to_inject:
                    break

            if data_to_inject:
                injection_key = "injected_previous_turn_data"
                self.executor.workflow_state[injection_key] = [data_to_inject]

                original_loop_source = self.executor.meta_plan[0]['loop_over']
                self.executor.meta_plan[0]['loop_over'] = injection_key

                app_logger.info(f"PLAN INJECTION: Hydrated plan with data from previous turn. Loop source changed from '{original_loop_source}' to '{injection_key}'.")

                event_data = {
                    "step": "Plan Optimization",
                    "type": "plan_optimization",
                    "details": f"PLAN HYDRATION: Injected data from the previous turn to fulfill the request: '{self.executor.original_user_input}'."
                }
                self.executor._log_system_event(event_data)
                yield self.executor._format_sse(event_data)

    def _validate_and_correct_plan(self):
        """
        Deterministically validates the generated meta-plan for common LLM errors,
        such as misclassifying prompts as tools, and corrects them in place.
        """
        if not self.executor.meta_plan:
            return

        all_prompts = self.executor.dependencies['STATE'].get('mcp_prompts', {})
        all_tools = self.executor.dependencies['STATE'].get('mcp_tools', {})

        for phase in self.executor.meta_plan:
            original_phase = copy.deepcopy(phase)
            correction_made = False
            correction_type = None
            
            # Correction 1: Clean up null/None/empty executable_prompt values
            if 'executable_prompt' in phase and phase['executable_prompt'] in [None, 'None', 'null', '', 'undefined']:
                invalid_value = phase['executable_prompt']
                app_logger.warning(f"PLAN CORRECTION: Removing invalid executable_prompt value: '{invalid_value}'")
                del phase['executable_prompt']
                correction_made = True
                correction_type = "invalid_prompt"

            # Correction 2: Prompt misclassified as tool
            if 'relevant_tools' in phase and isinstance(phase['relevant_tools'], list) and phase['relevant_tools']:
                capability_name = phase['relevant_tools'][0]
                if capability_name in all_prompts:
                    app_logger.warning(f"PLAN CORRECTION: Planner wrongly classified prompt '{capability_name}' as a tool. Correcting.")
                    phase['executable_prompt'] = capability_name
                    del phase['relevant_tools']
                    correction_made = True
                    correction_type = "prompt_as_tool"

            # --- MODIFICATION START: Change elif to if for independent correction ---
            # Correction 3: Tool misclassified as prompt
            # Changed from 'elif' to 'if' to ensure this correction runs independently.
            # This handles cases where LLM generates both fields (e.g., empty relevant_tools
            # AND executable_prompt with a tool like TDA_ContextReport). Corrections 2 and 3
            # are mutually exclusive in practice (one deletes what the other creates), so
            # both won't trigger on the same phase in a single pass.
            if 'executable_prompt' in phase and isinstance(phase['executable_prompt'], str):
                capability_name = phase['executable_prompt']
                if capability_name in all_tools:
                    app_logger.warning(f"PLAN CORRECTION: Planner wrongly classified tool '{capability_name}' as a prompt. Correcting.")
                    phase['relevant_tools'] = [capability_name]
                    del phase['executable_prompt']
                    correction_made = True
                    correction_type = "tool_as_prompt"
            # --- MODIFICATION END ---
            
            # Correction 4: Remove hallucinated/extraneous arguments that don't exist in tool schema
            # Also mark phases that need argument refinement at execution time
            if 'relevant_tools' in phase and isinstance(phase['relevant_tools'], list) and phase['relevant_tools']:
                tool_name = phase['relevant_tools'][0]
                tool_def = all_tools.get(tool_name)
                
                if tool_def and hasattr(tool_def, 'args') and isinstance(tool_def.args, dict):
                    # Get all valid argument names from tool schema (including synonyms)
                    from trusted_data_agent.core.config import AppConfig
                    valid_args = set()
                    required_args = set()
                    
                    for schema_arg_name, arg_details in tool_def.args.items():
                        valid_args.add(schema_arg_name)
                        
                        # Find canonical name by checking synonym map
                        canonical_name = schema_arg_name
                        for canonical, synonyms in AppConfig.ARGUMENT_SYNONYM_MAP.items():
                            if schema_arg_name in synonyms:
                                canonical_name = canonical
                                valid_args.update(synonyms)
                                break
                        
                        # Track required arguments (using canonical name)
                        if isinstance(arg_details, dict) and arg_details.get('required', False):
                            required_args.add(canonical_name)
                    
                    # Ensure arguments dict exists
                    if 'arguments' not in phase:
                        phase['arguments'] = {}
                    
                    # Find extraneous arguments
                    provided_args = set(phase['arguments'].keys())
                    extraneous_args = provided_args - valid_args
                    
                    # Check for missing required arguments (canonicalized)
                    provided_canonical = set()
                    for arg in provided_args:
                        # Find canonical name for this provided arg
                        canonical_arg = arg
                        for canonical, synonyms in AppConfig.ARGUMENT_SYNONYM_MAP.items():
                            if arg in synonyms:
                                canonical_arg = canonical
                                break
                        provided_canonical.add(canonical_arg)
                    missing_required = required_args - provided_canonical
                    
                    if extraneous_args:
                        app_logger.warning(f"PLAN CORRECTION: Tool '{tool_name}' received hallucinated arguments: {extraneous_args}")
                        for arg_name in extraneous_args:
                            del phase['arguments'][arg_name]
                        correction_made = True
                        correction_type = "extraneous_args"
                    
                    # If we removed args and now required args are missing, mark for refinement
                    if extraneous_args and missing_required:
                        app_logger.warning(f"PLAN CORRECTION: After removing hallucinated args, tool '{tool_name}' is missing required arguments: {missing_required}")
                        phase['_needs_refinement'] = True  # Flag for executor to force refinement

            if correction_made:
                # Determine the appropriate message based on correction type
                if correction_type == "invalid_prompt":
                    summary = "Plan contained invalid prompt reference. The system has removed it to prevent execution errors."
                elif correction_type == "prompt_as_tool":
                    summary = "Planner misclassified a prompt as a tool. The system has corrected the plan to ensure proper execution."
                elif correction_type == "tool_as_prompt":
                    summary = "Planner misclassified a tool as a prompt. The system has corrected the plan to ensure proper execution."
                elif correction_type == "extraneous_args":
                    summary = "Plan contained hallucinated arguments not accepted by the tool. The system has removed them to prevent validation errors."
                else:
                    summary = "Plan has been corrected by the system."
                
                event_data = {
                    "step": "Plan Optimization",
                    "type": "workaround",
                    "details": summary,
                    "correction": {
                        "from": original_phase,
                        "to": phase
                    }
                }
                self.executor._log_system_event(event_data)
                yield self.executor._format_sse(event_data)

    def _ensure_final_report_phase(self):
        """
        Deterministically checks and adds a final reporting phase. It is context-aware
        and will not add a report phase to sub-processes where it is not required,
        preventing redundant plan modifications.
        """
        if not self.executor.meta_plan or self.executor.is_conversational_plan:
            return

        is_sub_process_without_summary = (
            self.executor.execution_depth > 0 and
            not self.executor.force_final_summary and
            not APP_CONFIG.SUB_PROMPT_FORCE_SUMMARY
        )
        if is_sub_process_without_summary:
            app_logger.info("Skipping final report check for non-summarizing sub-process.")
            return

        last_phase = self.executor.meta_plan[-1]

        # --- MODIFICATION START: Make final report check robust to LLM key variations ---
        # Check for the key 'relevant_tools' (list)
        last_phase_tools_list = last_phase.get("relevant_tools", [])
        # Also check for the key 'tool' (string), which the LLM used in the log
        last_phase_tool_str = last_phase.get("tool")

        is_already_finalized = (
            any(tool in ["TDA_FinalReport", "TDA_ComplexPromptReport"] for tool in last_phase_tools_list) or
            last_phase_tool_str in ["TDA_FinalReport", "TDA_ComplexPromptReport"]
        )
        # --- MODIFICATION END ---

        # --- MODIFICATION START: Check both relevant_tools AND executable_prompt for TDA_ContextReport ---
        # Knowledge repository queries use TDA_ContextReport for single-phase bypass.
        # The LLM sometimes misclassifies it as executable_prompt instead of relevant_tools.
        # We need to check both locations to properly detect synthesis plans.
        is_synthesis_plan = any(
            "TDA_ContextReport" in p.get("relevant_tools", []) or
            p.get("executable_prompt") == "TDA_ContextReport"
            for p in self.executor.meta_plan
        )
        # --- MODIFICATION END ---

        app_logger.debug(f"DEBUG: _ensure_final_report_phase - Current meta_plan: {self.executor.meta_plan}")
        app_logger.debug(f"DEBUG: _ensure_final_report_phase - Last phase: {last_phase}")
        app_logger.debug(f"DEBUG: _ensure_final_report_phase - Last phase tools list: {last_phase_tools_list}")
        app_logger.debug(f"DEBUG: _ensure_final_report_phase - Last phase tool string: {last_phase_tool_str}")
        app_logger.debug(f"DEBUG: _ensure_final_report_phase - is_already_finalized: {is_already_finalized}")
        app_logger.debug(f"DEBUG: _ensure_final_report_phase - is_synthesis_plan: {is_synthesis_plan}")

        if is_already_finalized or is_synthesis_plan:
            return

        app_logger.warning("PLAN CORRECTION: The generated plan is missing a final reporting step. System is adding it now.")

        reporting_tool_name = "TDA_ComplexPromptReport" if self.executor.source == 'prompt_library' else "TDA_FinalReport"

        new_phase_number = len(self.executor.meta_plan) + 1
        final_phase = {
            "phase": new_phase_number,
            "goal": "Generate the final report based on the data gathered.",
            "relevant_tools": [reporting_tool_name],
            "arguments": {}
        }
        self.executor.meta_plan.append(final_phase)

        event_data = {
            "step": "System Correction",
            "type": "workaround",
            "details": {
                "summary": "The agent's plan was missing a final reporting step. The system has automatically added it to ensure a complete response.",
                "correction": { "added_phase": final_phase }
            }
        }
        self.executor._log_system_event(event_data)
        yield self.executor._format_sse(event_data)

    # ===========================================================================
    # PLAN NORMALIZATION METHODS - Template Syntax Canonicalization
    # ===========================================================================

    def _convert_to_canonical(self, value):
        """
        Converts a single argument value to canonical template format.

        Handles all LLM-generated template variations:
        - {{loop_item.key}} → {"source": "loop_item", "key": "key"} (as dict if standalone)
        - {{loop_item['key']}} → {"source": "loop_item", "key": "key"}
        - {loop_item[key]} → {"source": "loop_item", "key": "key"}
        - {loop_item.key} → {"source": "loop_item", "key": "key"}
        - {KeyName} → {"source": "loop_item", "key": "KeyName"}

        Args:
            value: Argument value (string, dict, or primitive)

        Returns:
            Normalized value with canonical template format (dict if pure template, string if embedded)
        """
        # Skip if not string or dict
        if not isinstance(value, (str, dict)):
            return value

        # Handle dict format (may already be canonical or legacy)
        if isinstance(value, dict):
            if value.get("source") == "loop_item" and "key" in value:
                return value  # Already canonical
            # Handle legacy {"result_of_phase_1": "key"} format
            for k, v in value.items():
                if re.match(r"result_of_phase_\d+|phase_\d+", k):
                    return {"source": k, "key": v}
            return value  # Not a template

        # Handle string format
        original_value = value

        # Check if this is a PURE template (entire value is just a template)
        # Pattern: exactly "{KeyName}" with nothing before or after
        pure_template_match = re.fullmatch(r'\{([A-Za-z][A-Za-z0-9_]*)\}', value)
        if pure_template_match:
            key = pure_template_match.group(1)
            # Only convert if it looks like a template variable
            if key[0].isupper() or key in ['TableName', 'ColumnName', 'DatabaseName', 'SchemaName']:
                app_logger.debug(f"Template normalized (pure): '{original_value}' → dict object")
                return {"source": "loop_item", "key": key}

        # Check for other pure template patterns
        pure_patterns = [
            (r'\{\{loop_item\.([A-Za-z0-9_]+)\}\}', 'loop_item'),
            (r'\{\{loop_item\[[\'\"]([A-Za-z0-9_]+)[\'\"]\]\}\}', 'loop_item'),
            (r'\{loop_item\[[\'\"]?([A-Za-z0-9_]+)[\'\"]?\]\}', 'loop_item'),
            (r'\{loop_item\.([A-Za-z0-9_]+)\}', 'loop_item'),
        ]

        for pattern, source in pure_patterns:
            match = re.fullmatch(pattern, value)
            if match:
                key = match.group(1)
                app_logger.debug(f"Template normalized (pure): '{original_value}' → dict object")
                return {"source": source, "key": key}

        # If we get here, it's an EMBEDDED template (template within other text)
        # For embedded templates, we keep them as strings but don't convert to JSON
        # The executor's embedded placeholder handler will resolve them
        # So we actually DON'T need to do anything for embedded templates in the new approach

        # Return unchanged - embedded templates will be left as-is for executor to handle
        return value

    def _normalize_arguments(self, args):
        """
        Recursively normalizes all arguments in a dict to canonical template format.

        Args:
            args: Dictionary of tool/prompt arguments

        Returns:
            Dictionary with normalized template references
        """
        if not isinstance(args, dict):
            return args

        normalized = {}

        for key, value in args.items():
            if isinstance(value, dict):
                # Recursively normalize nested dicts
                normalized[key] = self._normalize_arguments(value)
            elif isinstance(value, list):
                # Normalize each item in list
                normalized[key] = [
                    self._normalize_arguments(item) if isinstance(item, dict)
                    else self._convert_to_canonical(item)
                    for item in value
                ]
            else:
                # Convert individual values
                normalized[key] = self._convert_to_canonical(value)

        return normalized

    def _normalize_plan_syntax(self, plan):
        """
        Normalizes all template syntax in a plan to canonical format.

        This runs ONCE after plan generation, before validation and execution.
        Converts all LLM-generated template variations to a single canonical
        format, simplifying downstream execution logic.

        Args:
            plan: List of phase dictionaries from LLM

        Returns:
            Plan with all templates normalized to canonical format
        """
        if not isinstance(plan, list):
            return plan

        total_changes = 0

        for phase in plan:
            if not isinstance(phase, dict):
                continue

            # Normalize arguments if present
            if "arguments" in phase and isinstance(phase["arguments"], dict):
                original_args = copy.deepcopy(phase["arguments"])
                phase["arguments"] = self._normalize_arguments(phase["arguments"])

                if phase["arguments"] != original_args:
                    total_changes += 1
                    app_logger.debug(
                        f"Phase {phase.get('phase')} arguments normalized:\n"
                        f"  Before: {original_args}\n"
                        f"  After:  {phase['arguments']}"
                    )

        if total_changes > 0:
            app_logger.info(f"Plan normalization complete: {total_changes} phases updated")

        return plan

    async def _rewrite_plan_for_multi_loop_synthesis(self):
        """
        Surgically corrects plans where multiple, parallel loops feed into a
        final summary. It inserts a new, intermediate distillation phase to
        transform the raw data into high-level insights before the final
        summary is generated.
        """
        if not self.executor.meta_plan or len(self.executor.meta_plan) < 3:
            return

        made_change = False
        i = 0
        while i < len(self.executor.meta_plan) - 1:
            if (self.executor.meta_plan[i].get("type") == "loop" and
                self.executor.meta_plan[i+1].get("type") == "loop"):

                loop_block_start_index = i
                loop_block = [self.executor.meta_plan[i]]
                base_loop_source = self.executor.meta_plan[i].get("loop_over")

                if not base_loop_source:
                    i += 1
                    continue

                j = i + 1
                while j < len(self.executor.meta_plan) and self.executor.meta_plan[j].get("type") == "loop" and self.executor.meta_plan[j].get("loop_over") == base_loop_source:
                    loop_block.append(self.executor.meta_plan[j])
                    j += 1

                if len(loop_block) >= 2 and j < len(self.executor.meta_plan):
                    final_phase = self.executor.meta_plan[j]
                    is_final_summary = final_phase.get("relevant_tools") == ["TDA_LLMTask"]

                    if is_final_summary:
                        app_logger.warning(
                            "PLAN REWRITE: Detected inefficient multi-loop plan. "
                            "Injecting an intermediate distillation phase."
                        )
                        original_plan_snippet = copy.deepcopy(self.executor.meta_plan[loop_block_start_index : j+1])

                        synthesis_phase_num = j + 1
                        source_data_keys = [f"result_of_phase_{p['phase']}" for p in loop_block]

                        synthesis_task = {
                            "phase": synthesis_phase_num,
                            "goal": f"Distill the raw data from phases {loop_block[0]['phase']}-{loop_block[-1]['phase']} into a concise, per-item summary.",
                            "relevant_tools": ["TDA_LLMTask"],
                            "arguments": {
                                "task_description": (
                                    "Analyze the voluminous raw data from the previous loops. Your task is to distill this information. "
                                    "For each item (e.g., table) processed, produce a concise, one-paragraph summary of the most critical findings. "
                                    "Your output MUST be a clean list of these summary objects, each containing the item's name and the summary text."
                                ),
                                "source_data": source_data_keys
                            }
                        }

                        self.executor.meta_plan.insert(j, synthesis_task)

                        for phase_index in range(j + 1, len(self.executor.meta_plan)):
                            self.executor.meta_plan[phase_index]["phase"] += 1

                        final_summary_phase = self.executor.meta_plan[j+1]
                        new_source_key = f"result_of_phase_{synthesis_phase_num}"
                        final_summary_phase["arguments"]["source_data"] = [new_source_key]

                        made_change = True

                        event_data = {
                            "step": "System Correction",
                            "type": "workaround",
                            "details": {
                                "summary": "The agent's plan was inefficient. The system has automatically rewritten it to include a data distillation step, improving the quality and reliability of the final report.",
                                "correction": {
                                    "from": original_plan_snippet,
                                    "to": copy.deepcopy(self.executor.meta_plan[loop_block_start_index : j+2])
                                }
                            }
                        }
                        self.executor._log_system_event(event_data)
                        yield self.executor._format_sse(event_data)

                        i = j + 1
                        continue
            i += 1

        if made_change:
            app_logger.info(f"PLAN REWRITE (Multi-Loop): Final rewritten plan: {self.executor.meta_plan}")

    async def _rewrite_plan_for_corellmtask_loops(self):
        """
        Surgically corrects plans where the LLM has incorrectly placed a
        `TDA_LLMTask` inside a loop for an aggregation-style task. It transforms
        the loop into a standard, single-execution phase. This now uses a
        classifier LLM call to determine if the task is appropriate for this optimization.
        """
        if not self.executor.meta_plan:
            return

        made_change = False
        for phase in self.executor.meta_plan:
            is_inefficient_loop = (
                phase.get("type") == "loop" and
                phase.get("relevant_tools") == ["TDA_LLMTask"]
            )

            if is_inefficient_loop:
                task_description = phase.get("arguments", {}).get("task_description", "")

                if not task_description:
                    task_type = "aggregation"
                    app_logger.warning("TDA_LLMTask loop has no task_description. Defaulting to 'aggregation' for rewrite.")
                else:
                    # Use profile-aware prompt resolution
                    classification_prompt_content = self.executor.prompt_resolver.get_task_classification_prompt()
                    if not classification_prompt_content:
                        app_logger.error("Failed to resolve TASK_CLASSIFICATION_PROMPT from profile mapping")
                        task_type = "synthesis"
                    else:
                        classification_prompt = classification_prompt_content.format(task_description=task_description)
                        reason = "Classifying TDA_LLMTask loop intent for optimization."

                        call_id = str(uuid.uuid4())
                        event_data = {"step": "Analyzing Plan Efficiency", "type": "plan_optimization", "details": {"summary": "Checking if an iterative task can be optimized into a single batch operation.", "call_id": call_id}}
                        self.executor._log_system_event(event_data)
                        yield self.executor._format_sse(event_data)
                        yield self.executor._format_sse({"target": "llm", "state": "busy"}, "status_indicator_update")

                        response_text, input_tokens, output_tokens = await self.executor._call_llm_and_update_tokens(
                            prompt=classification_prompt,
                            reason=reason,
                            system_prompt_override="You are a JSON-only responding assistant.",
                            raise_on_error=False,
                            disabled_history=True,
                            source=self.executor.source
                        )

                        # --- MODIFICATION START: Pass user_uuid to get_session ---
                        updated_session = await session_manager.get_session(self.executor.user_uuid, self.executor.session_id)
                        # --- MODIFICATION END ---
                        if updated_session:
                            yield self.executor._format_sse({ "statement_input": input_tokens, "statement_output": output_tokens, "turn_input": self.executor.turn_input_tokens, "turn_output": self.executor.turn_output_tokens, "total_input": updated_session.get("input_tokens", 0), "total_output": updated_session.get("output_tokens", 0), "call_id": call_id }, "token_update")

                        yield self.executor._format_sse({"target": "llm", "state": "idle"}, "status_indicator_update")

                        try:
                            classification_data = json.loads(response_text)
                            task_type = classification_data.get("classification", "synthesis")
                        except (json.JSONDecodeError, AttributeError):
                            app_logger.error(f"Failed to parse task classification. Defaulting to 'synthesis' to be safe. Response: {response_text}")
                            task_type = "synthesis"

                if task_type == "aggregation":
                    app_logger.warning(
                        f"PLAN REWRITE: Detected inefficient AGGREGATION TDA_LLMTask loop in phase {phase.get('phase')}. "
                        "Transforming to a standard phase."
                    )

                    original_phase = copy.deepcopy(phase)

                    phase.pop("type", None)
                    loop_source = phase.pop("loop_over", None)

                    if "arguments" not in phase: phase["arguments"] = {}
                    if "source_data" not in phase["arguments"] and loop_source:
                        phase["arguments"]["source_data"] = [loop_source]
                    if "task_description" not in phase["arguments"]:
                         phase["arguments"]["task_description"] = phase.get("goal", "Perform the required task.")

                    event_data = {
                        "step": "System Correction",
                        "type": "workaround",
                        "details": {
                            "summary": "The agent's plan was inefficient. The system has automatically rewritten it to perform the analysis in a single, efficient step.",
                            "correction": {"from": original_phase, "to": phase}
                        }
                    }
                    self.executor._log_system_event(event_data)
                    yield self.executor._format_sse(event_data)
                    made_change = True
                else:
                    app_logger.info(f"PLAN REWRITE SKIPPED: Task classified as 'synthesis'. Preserving loop for phase {phase.get('phase')}.")

        if made_change:
            app_logger.info(f"PLAN REWRITE (TDA_LLMTask): Final rewritten plan: {self.executor.meta_plan}")


    def _rewrite_plan_for_date_range_loops(self):
        """
        Deterministically rewrites a plan where a `TDA_DateRange` tool
        is not followed by a necessary loop, correcting a common planning flaw.
        This runs after the main plan generation and before execution.
        """
        if not self.executor.meta_plan or len(self.executor.meta_plan) < 2:
            return

        i = 0
        made_change = False
        while i < len(self.executor.meta_plan) - 1:
            current_phase = self.executor.meta_plan[i]
            next_phase = self.executor.meta_plan[i+1]

            is_date_range_phase = (
                "TDA_DateRange" in current_phase.get("relevant_tools", [])
            )
            is_missing_loop = (
                next_phase.get("type") != "loop"
            )

            uses_date_range_output = False
            if isinstance(next_phase.get("arguments"), dict):
                for arg_value in next_phase["arguments"].values():
                    if isinstance(arg_value, str) and arg_value == f"result_of_phase_{current_phase['phase']}":
                         uses_date_range_output = True
                         break

            if is_date_range_phase and is_missing_loop and uses_date_range_output:
                app_logger.warning(
                    f"PLAN REWRITE: Detected TDA_DateRange at phase {current_phase['phase']} "
                    f"not followed by a loop. Rewriting phase {next_phase['phase']}."
                )

                original_next_phase = copy.deepcopy(next_phase)

                next_phase["type"] = "loop"
                next_phase["loop_over"] = f"result_of_phase_{current_phase['phase']}"

                for arg_name, arg_value in next_phase["arguments"].items():
                    if (isinstance(arg_value, str) and
                        arg_value == f"result_of_phase_{current_phase['phase']}"):

                        next_phase["arguments"][arg_name] = {
                            "source": "loop_item",
                            "key": "date"
                        }
                        break

                event_data = {
                    "step": "System Correction",
                    "type": "workaround",
                    "details": {
                        "summary": "The agent's plan was inefficiently structured. The system has automatically rewritten it to correctly process each item in the date range.",
                        "correction": {
                            "from": original_next_phase,
                            "to": next_phase
                        }
                    }
                }
                self.executor._log_system_event(event_data)
                yield self.executor._format_sse(event_data)
                made_change = True

            i += 1

        if made_change:
            app_logger.info(f"PLAN REWRITE (Date-Range): Final rewritten plan: {self.executor.meta_plan}")

    async def _rewrite_plan_for_empty_context_report(self, knowledge_context_used: str = ""):
        """
        Detects when TDA_ContextReport is used with empty arguments (missing answer_from_context).
        If knowledge context was retrieved, synthesizes an answer from that context and injects
        it into the plan to prevent execution errors.
        
        Args:
            knowledge_context_used: The knowledge context string that was retrieved during planning
        """
        if not self.executor.meta_plan:
            return
        
        made_change = False
        
        for phase in self.executor.meta_plan:
            # Check if this phase uses TDA_ContextReport
            relevant_tools = phase.get("relevant_tools", [])
            if "TDA_ContextReport" not in relevant_tools:
                continue
            
            # Check if arguments are missing or answer_from_context is empty
            arguments = phase.get("arguments", {})
            answer_from_context = arguments.get("answer_from_context")
            
            if answer_from_context:
                # Answer already provided, no need to rewrite
                continue
            
            app_logger.warning(
                f"PLAN REWRITE: Phase {phase.get('phase')} uses TDA_ContextReport but has empty arguments. "
                "Attempting to synthesize answer from knowledge context."
            )
            
            # If we have knowledge context, use it to synthesize an answer
            if knowledge_context_used:
                synthesis_prompt = f"""You are helping to answer a user's question using relevant knowledge from a documentation repository.

User's Question: {self.executor.original_user_input}

Retrieved Knowledge Context:
{knowledge_context_used}

Your task: Provide a clear, comprehensive answer to the user's question based ONLY on the knowledge context above. 
- Directly address what the user is asking
- Use specific examples from the context when helpful
- If the context doesn't fully answer the question, explain what information is available
- Keep the tone helpful and professional

Respond with ONLY the answer text, no preamble or meta-commentary."""

                reason = "Synthesizing answer from knowledge context for TDA_ContextReport"
                call_id = str(uuid.uuid4())
                
                event_data = {
                    "step": "Synthesizing Knowledge Answer",
                    "type": "plan_optimization",
                    "details": {
                        "summary": "TDA_ContextReport was called without an answer. Synthesizing response from retrieved knowledge.",
                        "call_id": call_id
                    }
                }
                self.executor._log_system_event(event_data)
                yield self.executor._format_sse(event_data)
                yield self.executor._format_sse({"target": "llm", "state": "busy"}, "status_indicator_update")
                
                try:
                    response_text, input_tokens, output_tokens = await self.executor._call_llm_and_update_tokens(
                        prompt=synthesis_prompt,
                        reason=reason,
                        system_prompt_override="You are a helpful assistant that answers questions based on provided documentation.",
                        raise_on_error=False,
                        disabled_history=True,
                        source=self.executor.source
                    )
                    
                    yield self.executor._format_sse({"target": "llm", "state": "idle"}, "status_indicator_update")
                    
                    # Update session with token usage
                    updated_session = await session_manager.get_session(self.executor.user_uuid, self.executor.session_id)
                    if updated_session:
                        yield self.executor._format_sse({
                            "statement_input": input_tokens,
                            "statement_output": output_tokens,
                            "turn_input": self.executor.turn_input_tokens,
                            "turn_output": self.executor.turn_output_tokens,
                            "total_input": updated_session.get("input_tokens", 0),
                            "total_output": updated_session.get("output_tokens", 0),
                            "call_id": call_id
                        }, "token_update")

                    # Inject the synthesized answer into the phase arguments
                    original_phase = copy.deepcopy(phase)
                    phase["arguments"]["answer_from_context"] = response_text.strip()
                    
                    event_data = {
                        "step": "System Correction",
                        "type": "workaround",
                        "details": {
                            "summary": "TDA_ContextReport was missing an answer. System synthesized one from knowledge context.",
                            "correction": {
                                "from": original_phase,
                                "to": phase
                            }
                        }
                    }
                    self.executor._log_system_event(event_data)
                    yield self.executor._format_sse(event_data)
                    
                    made_change = True
                    app_logger.info(f"Successfully synthesized answer for TDA_ContextReport in phase {phase.get('phase')}")
                    
                except Exception as e:
                    app_logger.error(f"Failed to synthesize answer from knowledge context: {e}. Using fallback message.")
                    # Inject a fallback message
                    phase["arguments"]["answer_from_context"] = (
                        "I found relevant information in the knowledge base. "
                        "Please review the retrieved documents for details about your question."
                    )
                    made_change = True
            else:
                # No knowledge context available, inject a generic fallback
                app_logger.warning(f"No knowledge context available for TDA_ContextReport in phase {phase.get('phase')}. Using generic fallback.")
                phase["arguments"]["answer_from_context"] = (
                    "I don't have enough information to answer this question. "
                    "Please try rephrasing or providing more context."
                )
                made_change = True
        
        if made_change:
            app_logger.info(f"PLAN REWRITE (Empty Context Report): Final rewritten plan: {self.executor.meta_plan}")

    async def _rewrite_plan_for_sql_consolidation(self):
        """
        Detects and consolidates sequential, inefficient SQL query phases into a
        single, optimized query using a specialized LLM call.
        """
        if not self.executor.meta_plan or len(self.executor.meta_plan) < 2:
            return

        sql_tools = set(APP_CONFIG.SQL_OPTIMIZATION_TOOLS)

        i = 0
        while i < len(self.executor.meta_plan) - 1:
            current_phase = self.executor.meta_plan[i]

            current_tool = (current_phase.get("relevant_tools") or [None])[0]
            if current_tool not in sql_tools:
                i += 1
                continue

            j = i + 1
            while j < len(self.executor.meta_plan):
                next_tool = (self.executor.meta_plan[j].get("relevant_tools") or [None])[0]
                if next_tool not in sql_tools:
                    break
                j += 1

            sql_sequence = self.executor.meta_plan[i:j]

            if len(sql_sequence) > 1:
                app_logger.warning(f"PLAN REWRITE: Detected inefficient sequential SQL plan from phase {i+1} to {j}. Consolidating...")

                inefficient_queries = []
                sql_arg_synonyms = ["sql", "query", "query_request"]
                for phase in sql_sequence:
                    args = phase.get("arguments", {})
                    query = next((args[key] for key in sql_arg_synonyms if key in args), None)
                    if query:
                        inefficient_queries.append(f"-- Query from Phase {phase['phase']}:\n{query}")

                if not inefficient_queries:
                    i = j
                    continue

                # Use profile-aware prompt resolution
                consolidation_prompt_content = self.executor.prompt_resolver.get_sql_consolidation_prompt()
                if not consolidation_prompt_content:
                    app_logger.error("Failed to resolve SQL_CONSOLIDATION_PROMPT from profile mapping, skipping consolidation")
                    i = j
                    continue
                
                consolidation_prompt = consolidation_prompt_content.format(
                    user_goal=self.executor.original_user_input,
                    inefficient_queries="\n\n".join(inefficient_queries)
                )

                reason = "Consolidating inefficient SQL plan."
                call_id = str(uuid.uuid4())
                event_data = {
                    "step": "Optimizing SQL Plan", "type": "plan_optimization",
                    "details": {"summary": "Detected an inefficient multi-step SQL plan. The agent is consolidating it into a single, optimized query.", "call_id": call_id}
                }
                self.executor._log_system_event(event_data)
                yield self.executor._format_sse(event_data)
                yield self.executor._format_sse({"target": "llm", "state": "busy"}, "status_indicator_update")

                response_text, input_tokens, output_tokens = await self.executor._call_llm_and_update_tokens(
                    prompt=consolidation_prompt, reason=reason,
                    system_prompt_override="You are a JSON-only responding SQL expert.",
                    raise_on_error=True, source=self.executor.source
                )

                yield self.executor._format_sse({"target": "llm", "state": "idle"}, "status_indicator_update")

                # --- MODIFICATION START: Pass user_uuid to get_session ---
                updated_session = await session_manager.get_session(self.executor.user_uuid, self.executor.session_id)
                # --- MODIFICATION END ---
                if updated_session:
                    yield self.executor._format_sse({ "statement_input": input_tokens, "statement_output": output_tokens, "turn_input": self.executor.turn_input_tokens, "turn_output": self.executor.turn_output_tokens, "total_input": updated_session.get("input_tokens", 0), "total_output": updated_session.get("output_tokens", 0), "call_id": call_id }, "token_update")

                try:
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if not json_match: raise ValueError("No JSON object found in consolidation response.")

                    data = json.loads(json_match.group(0))
                    consolidated_query = data.get("consolidated_query")
                    if not consolidated_query: raise ValueError("'consolidated_query' key not found.")

                    original_phases = copy.deepcopy(sql_sequence)

                    consolidated_phase = sql_sequence[-1]
                    consolidated_phase['phase'] = sql_sequence[0]['phase']
                    consolidated_phase['goal'] = f"Execute consolidated SQL query to achieve the goal: '{self.executor.original_user_input}'"

                    args = consolidated_phase.get("arguments", {})
                    found_key = next((key for key in sql_arg_synonyms if key in args), "sql")
                    args[found_key] = consolidated_query
                    consolidated_phase['arguments'] = args

                    num_phases_to_remove = len(sql_sequence)
                    self.executor.meta_plan[i] = consolidated_phase
                    for _ in range(num_phases_to_remove - 1):
                        del self.executor.meta_plan[i+1]

                    for phase_idx in range(i + 1, len(self.executor.meta_plan)):
                        self.executor.meta_plan[phase_idx]['phase'] -= (num_phases_to_remove - 1)

                    event_data = {
                        "step": "System Correction", "type": "workaround",
                        "details": {
                            "summary": "The agent's SQL plan was inefficient. The system has automatically consolidated it into a single query.",
                            "correction": {"from": original_phases, "to": consolidated_phase}
                        }
                    }
                    self.executor._log_system_event(event_data)
                    yield self.executor._format_sse(event_data)
                    app_logger.info(f"PLAN REWRITE (SQL Consolidation): Final rewritten plan: {self.executor.meta_plan}")
                    i = 0
                    continue

                except (json.JSONDecodeError, ValueError, AttributeError) as e:
                    app_logger.error(f"Failed to consolidate SQL plan: {e}. Proceeding with original inefficient plan. Response: {response_text}")

            i += 1

    # ===========================================================================
    # KNOWLEDGE REPOSITORY RETRIEVAL METHODS
    # ===========================================================================
    
    def _is_knowledge_enabled(self, profile_config: Optional[dict] = None) -> bool:
        """
        Check if knowledge retrieval is enabled globally and EXPLICITLY in the profile.

        Knowledge retrieval now requires explicit opt-in via profile.knowledgeConfig.enabled = true.
        This separates MCP tool-focused profiles (no knowledge) from RAG-focused profiles (with knowledge).

        Args:
            profile_config: Optional profile configuration dictionary

        Returns:
            True if knowledge retrieval should be performed
        """
        # Global kill switch
        if not APP_CONFIG.KNOWLEDGE_RAG_ENABLED:
            return False

        # CHANGED: Require explicit opt-in from profile
        if not profile_config:
            return False  # No profile = no knowledge retrieval

        knowledge_config = profile_config.get("knowledgeConfig", {})
        # CHANGED: Default to False (require explicit enablement)
        if not knowledge_config.get("enabled", False):
            return False

        return True
    
    def _get_knowledge_collections(self, profile_config: Optional[dict] = None) -> list:
        """
        Get the list of knowledge collections to query based on profile configuration.
        
        Args:
            profile_config: Optional profile configuration dictionary
            
        Returns:
            List of collection metadata dicts with reranking settings
        """
        if not profile_config:
            return []
        
        knowledge_config = profile_config.get("knowledgeConfig", {})
        configured_collections = knowledge_config.get("collections", [])

        if not configured_collections:
            return []

        result = []
        for coll_config in configured_collections:
            # Support both 'id' and 'collectionId' for backwards compatibility
            coll_id = coll_config.get("id") or coll_config.get("collectionId")
            if coll_id is None:
                continue

            # Find collection metadata using retriever's centralized method
            # This checks both APP_STATE (planner collections) and database (knowledge collections)
            coll_meta = self.rag_retriever.get_collection_metadata(coll_id)
            if not coll_meta:
                app_logger.warning(f"Collection {coll_id} configured in profile but not found in APP_STATE or database")
                continue

            # Only include knowledge repositories
            if coll_meta.get("repository_type") != "knowledge":
                app_logger.debug(f"Skipping collection {coll_id} - not a knowledge repository")
                continue

            # Check if collection is enabled
            if not coll_meta.get("enabled", False):
                app_logger.debug(f"Skipping collection {coll_id} - not enabled")
                continue

            result.append({
                "id": coll_id,
                "name": coll_meta.get("name"),
                "reranking_enabled": coll_config.get("reranking", False),
                "metadata": coll_meta
            })

        return result
    
    def _balance_collection_diversity(self, results: list, max_docs: int) -> list:
        """
        Balance document selection to ensure diversity across multiple collections.
        Uses round-robin selection to avoid over-representing any single collection.
        
        Args:
            results: List of retrieved documents with collection_id
            max_docs: Maximum number of documents to return
            
        Returns:
            Balanced list of documents with diverse collection representation
        """
        if not results or max_docs <= 0:
            return []
        
        if len(results) <= max_docs:
            return results
        
        # Group by collection
        by_collection = {}
        for doc in results:
            coll_id = doc.get("collection_id")
            if coll_id not in by_collection:
                by_collection[coll_id] = []
            by_collection[coll_id].append(doc)
        
        # Round-robin selection
        selected = []
        collection_ids = list(by_collection.keys())
        idx = 0
        
        while len(selected) < max_docs:
            # Get next collection in round-robin
            coll_id = collection_ids[idx % len(collection_ids)]
            
            # Take one document from this collection if available
            if by_collection[coll_id]:
                selected.append(by_collection[coll_id].pop(0))
            
            idx += 1
            
            # Break if all collections are exhausted
            if all(len(docs) == 0 for docs in by_collection.values()):
                break
        
        return selected
    
    def _format_with_token_limit(self, documents: list, max_tokens: int) -> str:
        """
        Format knowledge documents into a string while respecting token limits.
        Uses approximate token counting (4 chars ≈ 1 token).
        
        Args:
            documents: List of document dictionaries
            max_tokens: Maximum tokens for all documents combined
            
        Returns:
            Formatted knowledge context string
        """
        if not documents:
            return ""
        
        max_chars = max_tokens * 4  # Rough approximation: 4 chars per token
        
        formatted_sections = []
        current_chars = 0
        
        for i, doc in enumerate(documents, 1):
            # Format document header
            collection_name = doc.get("collection_name", "Unknown")
            similarity = doc.get("similarity_score", 0)
            
            header = f"### Knowledge Document {i} (from '{collection_name}', relevance: {similarity:.2f})\n"
            
            # Get document content - different structure for knowledge vs planner documents
            content = doc.get("content", "")
            
            # If no direct content field, try to get from full_case_data (planner documents)
            if not content:
                full_case = doc.get("full_case_data", {})
                if isinstance(full_case, dict):
                    # Try knowledge structure first
                    content = full_case.get("content", "")
                    # Fall back to planner structure
                    if not content:
                        content = full_case.get("intent", {}).get("user_query", "")
                    
                    # Get strategy/answer if available (planner documents)
                    if "successful_strategy" in full_case:
                        strategy = full_case.get("successful_strategy", {})
                        phases = strategy.get("phases", [])
                        if phases:
                            content += "\n\n**Strategy:**\n"
                            for phase in phases:
                                goal = phase.get("goal", "")
                                tools = phase.get("relevant_tools", [])
                                content += f"- {goal} (using: {', '.join(tools)})\n"
            
            section = header + content + "\n\n"
            section_len = len(section)
            
            # Check if adding this document would exceed limit
            if current_chars + section_len > max_chars:
                # Try to add truncated version
                remaining = max_chars - current_chars
                if remaining > len(header) + 100:  # Only add if we can include meaningful content
                    truncated = header + content[:remaining - len(header) - 20] + "...\n\n"
                    formatted_sections.append(truncated)
                    current_chars += len(truncated)
                break
            
            formatted_sections.append(section)
            current_chars += section_len
        
        if not formatted_sections:
            return ""
        
        return "".join(formatted_sections)
    
    async def _rerank_knowledge_with_llm(self, query: str, documents: list, max_docs: int) -> list:
        """
        Rerank knowledge documents using LLM to assess relevance to the planning query.
        
        Args:
            query: The user's query/goal
            documents: List of candidate documents
            max_docs: Number of top documents to return after reranking
            
        Returns:
            Reranked and filtered list of documents
        """
        if not documents or max_docs <= 0:
            return []
        
        if len(documents) <= max_docs:
            return documents
        
        try:
            # Prepare reranking prompt
            docs_for_ranking = []
            for i, doc in enumerate(documents):
                full_case = doc.get("full_case_data", {})
                content = full_case.get("intent", {}).get("user_query", "")[:500]  # Limit content length
                docs_for_ranking.append(f"Document {i+1}: {content}")
            
            reranking_prompt = f"""You are helping to select the most relevant knowledge documents for a planning task.

User's Goal: {query}

Available Documents:
{chr(10).join(docs_for_ranking)}

Task: Rank these documents by relevance to the user's goal. Return ONLY a JSON array of document numbers in order of relevance (most relevant first).
Example: [3, 1, 5, 2, 4]

Ranking:"""

            # Call LLM for reranking
            response_text, _, _ = await self.executor._call_llm_and_update_tokens(
                prompt=reranking_prompt,
                reason="Reranking knowledge documents for relevance"
            )
            
            # Parse ranking
            ranking_match = re.search(r'\[[\d,\s]+\]', response_text)
            if not ranking_match:
                app_logger.warning("Failed to parse LLM reranking response, using original order")
                return documents[:max_docs]
            
            ranking = json.loads(ranking_match.group())
            
            # Reorder documents based on ranking
            reranked = []
            for rank in ranking[:max_docs]:
                if 1 <= rank <= len(documents):
                    reranked.append(documents[rank - 1])
            
            app_logger.info(f"LLM reranking selected top {len(reranked)} documents from {len(documents)} candidates")
            return reranked
            
        except Exception as e:
            app_logger.error(f"Error during LLM reranking: {e}. Falling back to similarity order.")
            return documents[:max_docs]
    
    async def _retrieve_knowledge_for_planning(self, query: str, profile_config: Optional[dict] = None) -> str:
        """
        Main knowledge retrieval pipeline for strategic planning.
        
        This method:
        1. Checks if knowledge retrieval is enabled
        2. Gets configured knowledge collections from profile
        3. Retrieves relevant documents from those collections
        4. Applies optional LLM reranking per collection configuration
        5. Balances diversity across collections
        6. Formats results with token limits
        
        Args:
            query: The user's query/goal for planning
            profile_config: Optional profile configuration dictionary
            
        Returns:
            Formatted knowledge context string for inclusion in planning prompt
        """
        app_logger.info(f"[KNOWLEDGE DEBUG] _retrieve_knowledge_for_planning called with query: {query[:100]}")
        app_logger.info(f"[KNOWLEDGE DEBUG] profile_config: {profile_config is not None}")
        
        # 1. Check if enabled
        if not self._is_knowledge_enabled(profile_config):
            app_logger.info(f"[KNOWLEDGE DEBUG] Knowledge retrieval disabled (global or profile setting)")
            return ""
        
        # 2. Get configured collections
        knowledge_collections = self._get_knowledge_collections(profile_config)
        app_logger.info(f"[KNOWLEDGE DEBUG] knowledge_collections: {knowledge_collections}")
        if not knowledge_collections:
            app_logger.info("[KNOWLEDGE DEBUG] No knowledge collections configured in profile")
            return ""
        
        app_logger.info(f"Retrieving knowledge from {len(knowledge_collections)} configured collections")
        
        # 3. Retrieve documents from all collections
        if not self.rag_retriever:
            app_logger.warning("RAG retriever not available for knowledge retrieval")
            return ""
        
        # Get retrieval parameters using three-tier configuration (global -> profile -> locks)
        knowledge_config = profile_config.get("knowledgeConfig", {}) if profile_config else {}
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        effective_config = config_manager.get_effective_knowledge_config(knowledge_config)
        max_docs = effective_config.get("maxDocs", APP_CONFIG.KNOWLEDGE_RAG_NUM_DOCS)
        min_relevance = effective_config.get("minRelevanceScore", APP_CONFIG.KNOWLEDGE_MIN_RELEVANCE_SCORE)
        max_tokens = effective_config.get("maxTokens", APP_CONFIG.KNOWLEDGE_MAX_TOKENS)
        
        # Create RAG context for user-aware retrieval
        rag_context = RAGAccessContext(
            user_id=self.executor.user_uuid,
            retriever=self.rag_retriever
        )
        
        # Query with repository_type filter
        collection_ids = {coll["id"] for coll in knowledge_collections}
        all_results = self.rag_retriever.retrieve_examples(
            query=query,
            k=max_docs * len(knowledge_collections),  # Retrieve more candidates for diversity balancing
            min_score=min_relevance,
            allowed_collection_ids=collection_ids,
            rag_context=rag_context,
            repository_type="knowledge"  # Filter for knowledge repositories only
        )
        
        if not all_results:
            app_logger.info("No relevant knowledge documents found")
            return ""
        
        app_logger.info(f"Retrieved {len(all_results)} candidate knowledge documents")
        
        # 4. Apply per-collection reranking if configured
        collections_with_reranking = [c for c in knowledge_collections if c.get("reranking_enabled")]
        
        if collections_with_reranking:
            # Group results by collection for per-collection reranking
            by_collection = {}
            for doc in all_results:
                coll_id = doc.get("collection_id")
                if coll_id not in by_collection:
                    by_collection[coll_id] = []
                by_collection[coll_id].append(doc)
            
            # Rerank collections that have reranking enabled
            reranked_results = []
            for coll in knowledge_collections:
                coll_id = coll["id"]
                coll_docs = by_collection.get(coll_id, [])
                
                if not coll_docs:
                    continue
                
                if coll.get("reranking_enabled"):
                    app_logger.info(f"Applying LLM reranking to {len(coll_docs)} documents from collection '{coll['name']}'")
                    coll_docs = await self._rerank_knowledge_with_llm(query, coll_docs, max_docs)
                
                reranked_results.extend(coll_docs)
            
            all_results = reranked_results
        
        # 5. Balance diversity across collections
        balanced_results = self._balance_collection_diversity(all_results, max_docs)
        
        app_logger.info(f"Selected {len(balanced_results)} knowledge documents for planning (balanced across collections)")
        app_logger.info(f"[KNOWLEDGE DEBUG] Balanced results: {[{k: v for k, v in doc.items() if k in ['collection_name', 'similarity_score']} for doc in balanced_results]}")
        
        # 6. Format with token limits
        formatted_knowledge = self._format_with_token_limit(balanced_results, max_tokens)
        
        app_logger.info(f"[KNOWLEDGE DEBUG] Formatted knowledge length: {len(formatted_knowledge)} chars")
        app_logger.info(f"[KNOWLEDGE DEBUG] Formatted knowledge preview: {formatted_knowledge[:500] if formatted_knowledge else '(EMPTY)'}")
        
        # Track which collections were accessed for event logging
        accessed_collections = list(set(doc.get("collection_name") for doc in balanced_results if doc.get("collection_name")))
        if accessed_collections:
            self.tracked_knowledge_collections = accessed_collections
            self.tracked_knowledge_doc_count = len(balanced_results)
            self.tracked_knowledge_results = balanced_results  # Store full results for event details
            app_logger.info(f"Tracked {len(accessed_collections)} knowledge collections: {accessed_collections}")
            
            if self.event_handler:
                await self.event_handler({
                    "collections": accessed_collections,
                    "document_count": len(balanced_results)
                }, "knowledge_retrieval")
        
        # --- STORE KNOWLEDGE CONTEXT FOR PLAN OPTIMIZATION ---
        # Save the formatted knowledge for potential use in plan rewriting
        self._last_knowledge_context = formatted_knowledge
        # --- END STORAGE ---
        
        return formatted_knowledge

    async def generate_and_refine_plan(self, force_disable_history: bool = False, replan_context: str = None):
        """
        The main public method to generate a plan and then run all validation and
        refinement steps.
        """
        # Store knowledge context before calling _generate_meta_plan
        knowledge_context_for_optimization = ""
        
        async for event in self._generate_meta_plan(
            force_disable_history=force_disable_history,
            replan_context=replan_context
        ):
            # Capture knowledge context if it was generated
            if hasattr(self, '_last_knowledge_context'):
                knowledge_context_for_optimization = self._last_knowledge_context
            yield event

        # --- MODIFICATION START: Make SQL consolidation rewrite conditional ---
        if APP_CONFIG.ENABLE_SQL_CONSOLIDATION_REWRITE:
            async for event in self._rewrite_plan_for_sql_consolidation():
                yield event
        # --- MODIFICATION END ---

        async for event in self._rewrite_plan_for_multi_loop_synthesis():
            yield event
        async for event in self._rewrite_plan_for_corellmtask_loops():
            yield event
        for event in self._rewrite_plan_for_date_range_loops():
            yield event
        for event in self._validate_and_correct_plan():
            yield event
        for event in self._hydrate_plan_from_previous_turn():
            yield event
        # --- NEW OPTIMIZATION: Rewrite empty TDA_ContextReport with synthesized answer ---
        async for event in self._rewrite_plan_for_empty_context_report(knowledge_context_for_optimization):
            yield event
        # --- END NEW OPTIMIZATION ---
        for event in self._ensure_final_report_phase():
            yield event


        event_data = {
            "step": "Strategic Meta-Plan Generated",
            "type": "plan_generated",
            "details": self.executor.meta_plan,
            "metadata": {
                "execution_depth": self.executor.execution_depth
            }
        }
        self.executor._log_system_event(event_data)
        yield self.executor._format_sse(event_data)

    async def _generate_meta_plan(self, force_disable_history: bool = False, replan_context: str = None):
        """The universal planner. It generates a meta-plan for ANY request."""
        prompt_obj = None
        explicit_parameters_section = ""

        if self.executor.active_prompt_name:
            event_data = {"step": "Loading Workflow Prompt", "type": "system_message", "details": f"Loading '{self.executor.active_prompt_name}'"}
            self.executor._log_system_event(event_data)
            yield self.executor._format_sse(event_data)
            mcp_client = self.executor.dependencies['STATE'].get('mcp_client')
            if not mcp_client: raise RuntimeError("MCP client is not connected.")

            prompt_def = self.executor._get_prompt_info(self.executor.active_prompt_name)

            if not prompt_def:
                raise ValueError(f"Could not find a definition for prompt '{self.executor.active_prompt_name}' in the local cache.")

            required_args = {arg['name'] for arg in prompt_def.get('arguments', []) if arg.get('required')}

            enriched_args = self.executor.prompt_arguments.copy()

            missing_args = {arg for arg in required_args if arg not in enriched_args or enriched_args.get(arg) is None}
            if missing_args:
                raise ValueError(
                    f"Cannot execute prompt '{self.executor.active_prompt_name}' because the following required arguments "
                    f"are missing: {missing_args}"
                )

            self.executor.prompt_arguments = enriched_args

            try:
                # Use server ID instead of name for session management
                server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID
                if not server_id:
                    raise RuntimeError("MCP server ID is not configured.")
                async with mcp_client.session(server_id) as temp_session:
                    prompt_obj = await load_mcp_prompt(
                        temp_session, name=self.executor.active_prompt_name, arguments=self.executor.prompt_arguments
                    )
            except Exception as e:
                app_logger.error(f"Failed to load MCP prompt '{self.executor.active_prompt_name}': {e}", exc_info=True)
                raise ValueError(f"Prompt '{self.executor.active_prompt_name}' could not be loaded from the MCP server.") from e

            if not prompt_obj: raise ValueError(f"Prompt '{self.executor.active_prompt_name}' could not be loaded.")

            self.executor.workflow_goal_prompt = get_prompt_text_content(prompt_obj)
            if not self.executor.workflow_goal_prompt:
                raise ValueError(f"Could not extract text content from rendered prompt '{self.executor.active_prompt_name}'.")

            param_items = [f"- {key}: {json.dumps(value)}" for key, value in self.executor.prompt_arguments.items()]
            explicit_parameters_section = (
                "\n--- EXPLICIT PARAMETERS ---\n"
                "The following parameters were explicitly provided for this prompt execution:\n"
                + "\n".join(param_items) + "\n"
            )
        else:
            self.executor.workflow_goal_prompt = self.executor.original_user_input

        call_id = str(uuid.uuid4())
        summary = f"Generating a strategic meta-plan for the goal"
        
        # --- MODIFICATION START: Defer payload creation until after LLM call ---
        # details_payload = {
        #     "summary": summary,
        #     "full_text": self.executor.workflow_goal_prompt,
        #     "call_id": call_id,
        #     "execution_depth": self.executor.execution_depth
        # }
        # event_data = {"step": "Calling LLM for Planning", "type": "system_message", "details": details_payload}
        # self.executor._log_system_event(event_data)
        # yield self.executor._format_sse(event_data)
        # --- MODIFICATION END ---


        previous_turn_summary_str = self._create_summary_from_history(self.executor.previous_turn_data)

        active_prompt_context_section = ""
        if self.executor.active_prompt_name:
            active_prompt_context_section = f"\n- Active Prompt: You are currently executing the '{self.executor.active_prompt_name}' prompt. Do not call it again."

        constraints_section = self.executor.dependencies['STATE'].get("constraints_context", "")

        sql_consolidation_rule_str = ""
        opt_prompts = APP_CONFIG.SQL_OPTIMIZATION_PROMPTS
        opt_tools = APP_CONFIG.SQL_OPTIMIZATION_TOOLS

        if opt_prompts or opt_tools:
            favored_capabilities = []
            if opt_prompts:
                favored_capabilities.extend([f"`{p}` (prompt)" for p in opt_prompts])
            if opt_tools:
                favored_capabilities.extend([f"`{t}` (tool)" for t in opt_tools])

            sql_consolidation_rule_str = (
                "**CRITICAL STRATEGY (SQL Consolidation):** Before creating a multi-step plan, first consider if the user's entire request can be fulfilled with a single, consolidated SQL query. "
                "If the goal involves a sequence of filtering, joining, or looking up data (e.g., \"find all tables in a database that contains X\"), you **MUST** favor using one of the following capabilities "
                f"to write a single statement that performs the entire operation: {', '.join(favored_capabilities)}. "
                "Avoid creating multiple `base_...List` steps if a single query would be more efficient."
            )

        reporting_tool_name_injection = ""
        if self.executor.source == 'prompt_library':
            reporting_tool_name_injection = "TDA_ComplexPromptReport"
        else:
            reporting_tool_name_injection = "TDA_FinalReport"

        # --- KNOWLEDGE REPOSITORIES: Domain knowledge context (retrieved FIRST to inform RAG decision) ---
        knowledge_context_str = ""
        app_logger.info(f"[KNOWLEDGE DEBUG] Starting knowledge retrieval: rag_retriever={self.rag_retriever is not None}, KNOWLEDGE_RAG_ENABLED={APP_CONFIG.KNOWLEDGE_RAG_ENABLED}")
        
        if self.rag_retriever and APP_CONFIG.KNOWLEDGE_RAG_ENABLED:
            # Get profile configuration for knowledge settings
            profile_config = None
            # Use executor's active_profile_id which is already correctly set to either
            # the override profile or the default profile at initialization (executor.py line 103)
            if self.executor.active_profile_id and self.executor.active_profile_id != "__system_default__":
                app_logger.info(f"[KNOWLEDGE DEBUG] active_profile_id={self.executor.active_profile_id}, user_uuid={self.executor.user_uuid}")
                try:
                    from trusted_data_agent.core.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    profiles = config_manager.get_profiles(self.executor.user_uuid)

                    # Use the active profile directly - it's already the correct profile
                    profile_id = self.executor.active_profile_id

                    app_logger.info(f"[KNOWLEDGE DEBUG] Selected profile_id={profile_id}")

                    if profile_id:
                        profile_config = next((p for p in profiles if p.get("id") == profile_id), None)
                        app_logger.info(f"[KNOWLEDGE DEBUG] Found profile_config={profile_config is not None}")
                        if profile_config:
                            app_logger.info(f"[KNOWLEDGE DEBUG] Profile has knowledgeConfig={profile_config.get('knowledgeConfig')}")
                except Exception as e:
                    app_logger.warning(f"Failed to get profile for knowledge retrieval: {e}")
            
            # Retrieve knowledge documents
            knowledge_docs = await self._retrieve_knowledge_for_planning(
                query=self.executor.original_user_input,
                profile_config=profile_config
            )
            
            if knowledge_docs:
                knowledge_context_str = f"\n\n--- KNOWLEDGE CONTEXT ---\nThe following domain knowledge may be relevant to your planning:\n\n{knowledge_docs}\n"
                app_logger.info("Retrieved knowledge context for planning")
                
                # Yield status event for knowledge retrieval (visible in Live Status Window)
                if hasattr(self, 'tracked_knowledge_collections') and self.tracked_knowledge_collections:
                    # Get the actual document details for the event
                    knowledge_chunks = []
                    if hasattr(self, 'tracked_knowledge_results'):
                        for doc in self.tracked_knowledge_results:
                            knowledge_chunks.append({
                                "collection_name": doc.get("collection_name"),
                                "content": doc.get("content", ""),
                                "similarity_score": doc.get("similarity_score", 0),
                                "document_id": doc.get("document_id"),
                                "chunk_index": doc.get("chunk_index", 0)
                            })
                    
                    event_details = {
                        "summary": f"Retrieved {self.tracked_knowledge_doc_count} relevant documents from {len(self.tracked_knowledge_collections)} knowledge collection(s)",
                        "collections": self.tracked_knowledge_collections,
                        "document_count": self.tracked_knowledge_doc_count,
                        "chunks": knowledge_chunks
                    }
                    
                    # Yield SSE event for live UI display
                    yield self.executor._format_sse({
                        "step": "Knowledge Retrieved",
                        "type": "knowledge_retrieval",
                        "details": event_details
                    })
                    
                    # Call event handler to capture event for turn summary storage
                    if self.event_handler:
                        await self.event_handler(event_details, "knowledge_retrieval")
            else:
                app_logger.debug("No knowledge context retrieved for planning")

        # --- PLANNER REPOSITORIES: Few-shot examples for execution patterns ---
        # Include RAG examples alongside knowledge context - Directive 3 will decide the best approach
        rag_few_shot_examples_str = ""
        
        if self.rag_retriever:
            # Determine which collections to query based on profile
            allowed_collection_ids = None
            # Use executor's active_profile_id which is already correctly set to either
            # the override profile or the default profile at initialization (executor.py line 103)
            app_logger.info(f"[RAG FILTER DEBUG] Starting collection filtering: active_profile_id={self.executor.active_profile_id}, user_uuid={self.executor.user_uuid}")
            if self.executor.active_profile_id and self.executor.active_profile_id != "__system_default__":
                try:
                    from trusted_data_agent.core.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    profiles = config_manager.get_profiles(self.executor.user_uuid)
                    app_logger.info(f"[RAG FILTER DEBUG] Retrieved {len(profiles)} profiles from config_manager")

                    # Use the active profile directly - it's already the correct profile
                    profile_id = self.executor.active_profile_id
                    app_logger.info(f"[RAG FILTER DEBUG] Using profile_id: {profile_id}")

                    if profile_id:
                        profile = next((p for p in profiles if p.get("id") == profile_id), None)
                        app_logger.info(f"[RAG FILTER DEBUG] profile_id={profile_id}, profile_found={profile is not None}")
                        if profile:
                            # Use ragCollections instead of autocompleteCollections for RAG retrieval filtering
                            rag_collections = profile.get("ragCollections", ["*"])
                            app_logger.info(f"[RAG FILTER DEBUG] ragCollections from profile: {rag_collections}")
                            if rag_collections != ["*"]:
                                allowed_collection_ids = set(rag_collections)
                                app_logger.info(f"RAG retrieval filtered to collections: {allowed_collection_ids} (profile: {profile.get('name')})")
                            else:
                                app_logger.info(f"[RAG FILTER DEBUG] ragCollections is wildcard, not filtering")
                        else:
                            app_logger.warning(f"[RAG FILTER DEBUG] Profile {profile_id} not found in profiles list")
                except Exception as e:
                    app_logger.warning(f"Failed to get profile collections for RAG filtering: {e}")
            
            # --- MODIFICATION START: Create RAGAccessContext for user-aware retrieval ---
            rag_context = RAGAccessContext(
                user_id=self.executor.user_uuid,
                retriever=self.rag_retriever
            )
            
            retrieved_cases = self.rag_retriever.retrieve_examples(
                query=self.executor.original_user_input,
                k=APP_CONFIG.RAG_NUM_EXAMPLES,
                allowed_collection_ids=allowed_collection_ids,
                rag_context=rag_context,  # --- MODIFICATION: Pass context ---
                repository_type="planner"  # Explicitly retrieve from planner repositories
            )
            # --- MODIFICATION END ---
            if retrieved_cases:
                if self.event_handler:
                    # Send the full case data of the first (most relevant) case
                    await self.event_handler({
                        "case_id": retrieved_cases[0]['case_id'],
                        "full_case_data": retrieved_cases[0]['full_case_data']
                    }, "rag_retrieval")
                # Add adaptive guidance header when RAG cases exist
                adaptive_header = """### Retrieved RAG Examples (Adapt to Current Request)

**CRITICAL**: These are proven patterns to inform your strategy, NOT templates to copy exactly.
- **Priority**: User's explicit requirements (charts, exports, formats) > RAG pattern
- **If user adds new steps**: You MUST include them even if RAG case doesn't have them
- **Example**: RAG shows "query→report" but user asks "query→chart→report" → chart phase is MANDATORY

"""
                formatted_examples = [self.rag_retriever._format_few_shot_example(case) for case in retrieved_cases]
                rag_few_shot_examples_str = "\n\n" + adaptive_header + "\n".join(formatted_examples) + "\n\n"
                app_logger.info(f"Retrieved RAG cases for few-shot examples: {[case['case_id'] for case in retrieved_cases]}")
            else:
                app_logger.info("No relevant RAG cases found for few-shot examples.")

        # Get MCP system name from database (bootstrapped from tda_config.json)
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root
        db_path = get_project_root() / 'tda_auth.db'
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT default_value FROM global_parameters WHERE parameter_name = 'mcp_system_name'"
        )
        row = cursor.fetchone()
        mcp_system_name = row[0] if row else 'Database System'
        conn.close()

        # Get tools and prompts context from APP_STATE
        from trusted_data_agent.core.config import APP_STATE
        tools_context = APP_STATE.get('tools_context', '--- No Tools Available ---')
        prompts_context = APP_STATE.get('prompts_context', '--- No Prompts Available ---')

        planning_prompt = WORKFLOW_META_PLANNING_PROMPT.format(
            workflow_goal=self.executor.workflow_goal_prompt,
            explicit_parameters_section=explicit_parameters_section,
            original_user_input=self.executor.original_user_input,
            turn_action_history=previous_turn_summary_str,
            execution_depth=self.executor.execution_depth,
            active_prompt_context_section=active_prompt_context_section,
            mcp_system_name=mcp_system_name,
            replan_instructions=replan_context or "",
            constraints_section=constraints_section,
            sql_consolidation_rule=sql_consolidation_rule_str,
            reporting_tool_name=reporting_tool_name_injection,
            rag_few_shot_examples=rag_few_shot_examples_str,  # Pass the populated examples
            knowledge_context=knowledge_context_str,  # Empty string when knowledge disabled
            available_tools=tools_context,  # Pass tools context
            available_prompts=prompts_context  # Pass prompts context
        )

        yield self.executor._format_sse({"target": "llm", "state": "busy"}, "status_indicator_update")
        response_text, input_tokens, output_tokens = await self.executor._call_llm_and_update_tokens(
            prompt=planning_prompt,
            reason=f"Generating a strategic meta-plan for the goal: '{self.executor.workflow_goal_prompt[:100]}'",
            disabled_history=force_disable_history,
            active_prompt_name_for_filter=self.executor.active_prompt_name,
            source=self.executor.source
            # No user_uuid/session_id needed here directly as _call_llm takes from self.executor
        )
        yield self.executor._format_sse({"target": "llm", "state": "idle"}, "status_indicator_update")

        # --- MODIFICATION START: Build payload *after* LLM call to include tokens ---
        details_payload = {
            "summary": summary,
            "full_text": self.executor.workflow_goal_prompt,
            "call_id": call_id,
            "execution_depth": self.executor.execution_depth,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }
        event_data = {"step": "Calling LLM for Planning", "type": "system_message", "details": details_payload}
        self.executor._log_system_event(event_data)
        yield self.executor._format_sse(event_data)
        # --- MODIFICATION END ---

        if rag_few_shot_examples_str:
            app_logger.info(f"RAG Findings (few-shot examples) used:\n{rag_few_shot_examples_str}")

        app_logger.info(
            f"\n--- Meta-Planner Turn ---\n"
            f"** CONTEXT **\n"
            f"Original User Input: {self.executor.original_user_input}\n"
            f"Execution Depth: {self.executor.execution_depth}\n"
            f"Previous Turn History Summary (for prompt):\n{previous_turn_summary_str}\n"
            f"** GENERATED PLAN **\n{response_text}\n"
            f"-------------------------"
        )

        # --- MODIFICATION START: Pass user_uuid to get_session ---
        # Get user_uuid and session_id from the executor instance
        user_uuid = self.executor.user_uuid
        session_id = self.executor.session_id
        updated_session = await session_manager.get_session(user_uuid, session_id)
        # --- MODIFICATION END ---
        if updated_session:
            yield self.executor._format_sse({ "statement_input": input_tokens, "statement_output": output_tokens, "turn_input": self.executor.turn_input_tokens, "turn_output": self.executor.turn_output_tokens, "total_input": updated_session.get("input_tokens", 0), "total_output": updated_session.get("output_tokens", 0), "call_id": call_id }, "token_update")

        try:
            # Check for empty or invalid response from LLM
            if not response_text or len(response_text.strip()) < 3:
                raise ValueError(f"LLM returned an empty or invalid response: '{response_text}'. The model may be overloaded or the query may not be suitable for planning.")

            json_str = response_text

            # Look for ```json block ANYWHERE in the response (not just at start)
            # Some LLMs add preamble text before the JSON block
            if "```json" in response_text:
                match = re.search(r"```json\s*\n?(.*?)\n?\s*```", response_text, re.DOTALL)
                if match:
                    json_str = match.group(1).strip()
            elif "```" in response_text:
                # Also handle generic ``` code blocks without json specifier
                match = re.search(r"```\s*\n?(.*?)\n?\s*```", response_text, re.DOTALL)
                if match:
                    json_str = match.group(1).strip()

            # Validate json_str before parsing
            if not json_str or len(json_str.strip()) < 2:
                raise ValueError(f"Could not extract valid JSON from LLM response. Raw response: '{response_text[:200]}'")

            plan_object = json.loads(json_str)

            if isinstance(plan_object, dict) and plan_object.get("plan_type") == "conversational":
                self.executor.is_conversational_plan = True
                self.executor.temp_data_holder = plan_object.get("response", "I'm sorry, I don't have a response for that.")
                event_data = {"step": "Conversational Response Identified", "type": "system_message", "details": self.executor.temp_data_holder}
                self.executor._log_system_event(event_data)
                yield self.executor._format_sse(event_data)
                return

            plan_object_is_dict = isinstance(plan_object, dict)
            is_direct_tool = plan_object_is_dict and "tool_name" in plan_object
            is_direct_prompt = plan_object_is_dict and ("prompt_name" in plan_object or "executable_prompt" in plan_object)

            if is_direct_tool or is_direct_prompt:
                event_data = {
                    "step": "System Correction",
                    "type": "workaround",
                    "details": "Planner returned a direct action instead of a plan. System is correcting the format."
                }
                self.executor._log_system_event(event_data)
                yield self.executor._format_sse(event_data)

                phase = {
                    "phase": 1,
                    "goal": f"Execute the action for the user's request: '{self.executor.original_user_input}'",
                    "arguments": plan_object.get("arguments", {})
                }

                if is_direct_tool:
                    phase["relevant_tools"] = [plan_object["tool_name"]]
                elif is_direct_prompt:
                    phase["executable_prompt"] = plan_object.get("prompt_name") or plan_object.get("executable_prompt")

                self.executor.meta_plan = [phase]
            elif not isinstance(plan_object, list) or not plan_object:
                raise ValueError("LLM response for meta-plan was not a non-empty list.")
            else:
                self.executor.meta_plan = plan_object

        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"Failed to generate a valid meta-plan from the LLM. Response: {response_text}. Error: {e}")

        # --- NORMALIZATION: Convert all template syntaxes to canonical format ---
        if self.executor.meta_plan:
            app_logger.info("Normalizing plan template syntax to canonical format...")
            self.executor.meta_plan = self._normalize_plan_syntax(self.executor.meta_plan)
        # --- END NORMALIZATION ---

        if self.executor.active_prompt_name and self.executor.meta_plan:
            if len(self.executor.meta_plan) > 1 or any(phase.get("type") == "loop" for phase in self.executor.meta_plan):
                self.executor.is_complex_prompt_workflow = True
                app_logger.info(f"'{self.executor.active_prompt_name}' has been qualified as a complex prompt workflow based on the generated plan.")