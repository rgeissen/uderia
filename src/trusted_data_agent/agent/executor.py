# trusted_data_agent/agent/executor.py
import re
import json
import logging
import copy
import uuid
# --- MODIFICATION START: Import asyncio ---
import asyncio
# --- MODIFICATION END ---
from enum import Enum, auto
from typing import Tuple, List
# --- MODIFICATION START: Import datetime and timezone ---
from datetime import datetime, timezone
# --- MODIFICATION END ---

from trusted_data_agent.agent.formatter import OutputFormatter
from trusted_data_agent.core import session_manager
from trusted_data_agent.llm import handler as llm_handler
# --- MODIFICATION START: Import APP_CONFIG and APP_STATE ---
from trusted_data_agent.core.config import (
    APP_CONFIG, APP_STATE,
    get_user_provider, get_user_model, set_user_provider, set_user_model,
    set_user_aws_region, set_user_azure_deployment_details,
    set_user_friendli_details, set_user_model_provider_in_profile
)
# --- MODIFICATION END ---
from trusted_data_agent.agent.response_models import CanonicalResponse, PromptReportResponse
from trusted_data_agent.mcp_adapter import adapter as mcp_adapter


# Refactored components
from trusted_data_agent.agent.planner import Planner
from trusted_data_agent.agent.phase_executor import PhaseExecutor


app_logger = logging.getLogger("quart.app")


class DefinitiveToolError(Exception):
    """Custom exception for unrecoverable tool errors."""
    def __init__(self, message, friendly_message):
        super().__init__(message)
        self.friendly_message = friendly_message


class AgentState(Enum):
    PLANNING = auto()
    EXECUTING = auto()
    SUMMARIZING = auto()
    DONE = auto()
    ERROR = auto()


def unwrap_exception(e: BaseException) -> BaseException:
    """Recursively unwraps ExceptionGroups to find the root cause."""
    if isinstance(e, ExceptionGroup) and e.exceptions:
        return unwrap_exception(e.exceptions[0])
    return e


class PlanExecutor:
    AgentState = AgentState

    def _get_prompt_info(self, prompt_name: str) -> dict | None:
        """Helper to find prompt details from the structured prompts in the global state."""
        if not prompt_name:
            return None
        structured_prompts = self.dependencies['STATE'].get('structured_prompts', {})
        for category_prompts in structured_prompts.values():
            for prompt in category_prompts:
                if prompt.get("name") == prompt_name:
                    return prompt
        return None

    # --- MODIFICATION START: Add plan_to_execute and is_replay ---
    def __init__(self, session_id: str, user_uuid: str, original_user_input: str, dependencies: dict, active_prompt_name: str = None, prompt_arguments: dict = None, execution_depth: int = 0, disabled_history: bool = False, previous_turn_data: dict = None, force_history_disable: bool = False, source: str = "text", is_delegated_task: bool = False, force_final_summary: bool = False, plan_to_execute: list = None, is_replay: bool = False, task_id: str = None, profile_override_id: str = None, event_handler=None):
        self.session_id = session_id
        self.user_uuid = user_uuid
        self.event_handler = event_handler
        # --- MODIFICATION END ---
        self.original_user_input = original_user_input
        self.dependencies = dependencies
        self.state = self.AgentState.PLANNING

        # --- MODIFICATION START: Store profile override and setup temporary context ---
        self.profile_override_id = profile_override_id
        self.original_llm = None  # Will store original LLM if overridden
        self.original_mcp_tools = None  # Will store original tools if overridden
        self.original_mcp_prompts = None  # Will store original prompts if overridden
        self.original_provider = None  # Will store original provider if overridden
        self.original_model = None  # Will store original model if overridden
        self.original_structured_tools = None  # Will store original structured_tools if overridden
        self.original_structured_prompts = None  # Will store original structured_prompts if overridden
        self.original_provider_details = {}  # Will store provider-specific config (Friendli, Azure, AWS)
        
        # Snapshot model and provider for this turn from active profile (default or override)
        # Don't use global config as it may not match the profile being used
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            
            # Determine which profile will be used (override or default)
            self.active_profile_id = profile_override_id if profile_override_id else config_manager.get_default_profile_id(user_uuid)
            
            if self.active_profile_id:
                profiles = config_manager.get_profiles(user_uuid)
                active_profile = next((p for p in profiles if p.get("id") == self.active_profile_id), None)
                
                if active_profile:
                    # Get LLM configuration from the active profile
                    llm_config_id = active_profile.get('llmConfigurationId')
                    if llm_config_id:
                        llm_configs = config_manager.get_llm_configurations(user_uuid)
                        llm_config = next((cfg for cfg in llm_configs if cfg['id'] == llm_config_id), None)
                        
                        if llm_config:
                            self.current_provider = llm_config.get('provider', get_user_provider(user_uuid))
                            self.current_model = llm_config.get('model', get_user_model(user_uuid))
                            app_logger.debug(f"Initialized consumption tracking with profile model: {self.current_provider}/{self.current_model}")
                        else:
                            # Fallback to global config if LLM config not found
                            self.current_model = get_user_model(user_uuid)
                            self.current_provider = get_user_provider(user_uuid)
                    else:
                        # Fallback to global config if no LLM config in profile
                        self.current_model = get_user_model(user_uuid)
                        self.current_provider = get_user_provider(user_uuid)
                else:
                    # Fallback to global config if profile not found
                    self.current_model = get_user_model(user_uuid)
                    self.current_provider = get_user_provider(user_uuid)
            else:
                # Fallback to global config if no active profile
                self.active_profile_id = "__system_default__"
                self.current_model = get_user_model(user_uuid)
                self.current_provider = get_user_provider(user_uuid)
        except Exception as e:
            # Fallback to global config on error
            app_logger.warning(f"Failed to get model/provider from profile, using global config: {e}")
            self.active_profile_id = "__system_default__"
            self.current_model = get_user_model(user_uuid)
            self.current_provider = get_user_provider(user_uuid)
        
        # Initialize profile-aware prompt resolver
        from trusted_data_agent.agent.profile_prompt_resolver import ProfilePromptResolver
        self.prompt_resolver = ProfilePromptResolver(
            profile_id=self.active_profile_id,
            provider=self.current_provider
        )
        app_logger.info(f"Initialized ProfilePromptResolver with profile_id='{self.active_profile_id}', provider='{self.current_provider}'")
        # --- MODIFICATION END ---

        self.structured_collected_data = {}
        self.workflow_state = {}
        self.turn_action_history = []
        self.meta_plan = None
        self.original_plan_for_history = None # Added to store original plan
        self.current_phase_index = 0
        self.last_tool_output = None

        self.active_prompt_name = active_prompt_name
        self.prompt_arguments = prompt_arguments or {}
        self.workflow_goal_prompt = ""

        prompt_info = self._get_prompt_info(active_prompt_name)
        self.prompt_type = prompt_info.get("prompt_type", "reporting") if prompt_info else "reporting"

        self.is_in_loop = False
        self.current_loop_items = []
        self.processed_loop_items = []

        self.tool_constraints_cache = {}
        self.globally_skipped_tools = set()
        self.temp_data_holder = None
        self.last_failed_action_info = "None"
        self.events_to_yield = []
        self.last_action_str = None

        self.llm_debug_history = []
        self.max_steps = 40

        self.execution_depth = execution_depth
        self.MAX_EXECUTION_DEPTH = 5

        self.disabled_history = disabled_history or force_history_disable
        self.previous_turn_data = previous_turn_data or {}
        self.is_synthesis_from_history = False
        self.is_conversational_plan = False
        self.source = source
        self.is_delegated_task = is_delegated_task
        self.force_final_summary = force_final_summary

        self.is_complex_prompt_workflow = False
        self.final_canonical_response = None
        self.is_single_prompt_plan = False
        self.final_summary_text = ""

        # --- MODIFICATION START: Store replay flags ---
        self.plan_to_execute = plan_to_execute # Store the plan if provided for replay
        self.is_replay = is_replay # Flag indicating if this is a replay
        # --- MODIFICATION END ---
        # --- MODIFICATION START: Add instance variable for turn number ---
        self.current_turn_number = 0 # Will be calculated once in run()
        # --- MODIFICATION END ---
        # --- MODIFICATION START: Store task_id ---
        self.task_id = task_id
        # --- MODIFICATION END ---
        self.turn_input_tokens = 0
        self.turn_output_tokens = 0

        # --- MODIFICATION START: Store the global RAG retriever instance ---
        if APP_CONFIG.RAG_ENABLED:
            self.rag_retriever = self.dependencies['STATE'].get('rag_retriever_instance')
        else:
            self.rag_retriever = None
        # --- MODIFICATION END ---
        
        # --- MODIFICATION START: Track which collection RAG examples came from ---
        self.rag_source_collection_id = None  # Will be set when RAG examples are retrieved
        # --- MODIFICATION END ---
        
        # --- PHASE 2: Track knowledge repository access ---
        self.knowledge_accessed = []  # List of {collection_id, collection_name, document_count} during planning
        self.knowledge_retrieval_event = None  # Store the knowledge retrieval event for replay
        # --- PHASE 2 END ---


    def _log_system_event(self, event_data: dict, event_name: str = None):
        """Logs a system-level event to the turn action history for replay and debugging."""
        # Avoid logging token updates or status indicators
        if event_name in ["token_update", "status_indicator_update"] or "state" in event_data:
            return

        # Avoid logging the final answer event as it's not a step in the process
        if event_name == "final_answer":
            return

        action_for_history = {
            "tool_name": "TDA_SystemLog",
            "arguments": {
                "message": event_data.get("step"),
                "details": event_data.get("details")
            },
            "metadata": {
                "execution_depth": self.execution_depth,
                "type": event_data.get("type"),
                # --- MODIFICATION START: Add timestamp for per-step timing ---
                "timestamp": datetime.now(timezone.utc).isoformat()
                # --- MODIFICATION END ---
            }
        }
        result = {"status": "info"}
        if event_data.get("type") in ["error", "cancelled"]:
            result["status"] = event_data.get("type")

        self.turn_action_history.append({"action": action_for_history, "result": result})


    @staticmethod
    def _format_sse(data: dict, event: str = None) -> str:
        msg = f"data: {json.dumps(data)}\n"
        if event is not None:
            msg += f"event: {event}\n"
        return f"{msg}\n"

    async def _call_llm_and_update_tokens(self, prompt: str, reason: str, system_prompt_override: str = None, raise_on_error: bool = False, disabled_history: bool = False, active_prompt_name_for_filter: str = None, source: str = "text") -> tuple[str, int, int]:
        """A centralized wrapper for calling the LLM that handles token updates."""
        final_disabled_history = disabled_history or self.disabled_history

        response_text, statement_input_tokens, statement_output_tokens, actual_provider, actual_model = await llm_handler.call_llm_api(
            self.dependencies['STATE']['llm'], prompt,
            # --- MODIFICATION START: Pass user_uuid and session_id ---
            user_uuid=self.user_uuid, session_id=self.session_id,
            # --- MODIFICATION END ---
            dependencies=self.dependencies, reason=reason,
            system_prompt_override=system_prompt_override, raise_on_error=raise_on_error,
            disabled_history=final_disabled_history,
            active_prompt_name_for_filter=active_prompt_name_for_filter,
            source=source,
            # --- MODIFICATION START: Pass active profile and provider for prompt resolution ---
            active_profile_id=self.active_profile_id,
            current_provider=self.current_provider
            # --- MODIFICATION END ---
        )
        self.llm_debug_history.append({"reason": reason, "response": response_text})
        app_logger.debug(f"LLM RESPONSE (DEBUG): Reason='{reason}', Response='{response_text}'")

        self.turn_input_tokens += statement_input_tokens
        self.turn_output_tokens += statement_output_tokens

        return response_text, statement_input_tokens, statement_output_tokens

    def _get_current_profile_tag(self) -> str | None:
        """
        Get the current profile tag from active profiles or profile override.
        
        Returns:
            Profile tag string or None if no active profile
        """
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            
            # If profile override is active, use that profile's tag
            if self.profile_override_id:
                profiles = config_manager.get_profiles(self.user_uuid)
                override_profile = next((p for p in profiles if p.get("id") == self.profile_override_id), None)
                if override_profile:
                    profile_tag = override_profile.get("tag")
                    app_logger.debug(f"_get_current_profile_tag: Using profile override tag: {profile_tag}")
                    return profile_tag
                else:
                    app_logger.warning(f"_get_current_profile_tag: Profile override ID {self.profile_override_id} not found")
            
            # Otherwise use the default profile
            default_profile_id = config_manager.get_default_profile_id(self.user_uuid)
            if default_profile_id:
                profiles = config_manager.get_profiles(self.user_uuid)
                default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
                if default_profile:
                    profile_tag = default_profile.get("tag")
                    app_logger.debug(f"_get_current_profile_tag: Using default profile tag: {profile_tag}")
                    return profile_tag
            
            app_logger.debug(f"_get_current_profile_tag: No profile tag found (override_id={self.profile_override_id}, default_id={default_profile_id if 'default_profile_id' in locals() else 'not set'})")
        except Exception as e:
            app_logger.warning(f"Failed to get current profile tag: {e}", exc_info=True)
        return None

    def _get_active_profile_tag(self) -> str:
        """
        Get the tag of the currently active (default) profile, ignoring any profile override.
        Used for fallback messaging when profile override fails.
        
        Returns:
            str: The tag of the default profile, or "DEFAULT" if none found
        """
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            
            default_profile_id = config_manager.get_default_profile_id(self.user_uuid)
            if default_profile_id:
                profiles = config_manager.get_profiles(self.user_uuid)
                default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
                if default_profile:
                    return default_profile.get("tag", "DEFAULT")
            
        except Exception as e:
            app_logger.warning(f"Failed to get default profile tag: {e}", exc_info=True)
        
        return "DEFAULT"

    async def _get_tool_constraints(self, tool_name: str) -> Tuple[dict, list]:
        """
        Uses an LLM to determine if a tool requires numeric or character columns.
        Returns the constraints and a list of events to be yielded by the caller.
        """
        if tool_name in self.tool_constraints_cache:
            return self.tool_constraints_cache[tool_name], []

        events = []
        tool_definition = self.dependencies['STATE'].get('mcp_tools', {}).get(tool_name)
        constraints = {}

        if tool_definition:
            prompt_modifier = ""
            if any(k in tool_name.lower() for k in ["univariate", "standarddeviation", "negativevalues"]):
                prompt_modifier = "This tool is for quantitative analysis and requires a 'numeric' data type for `column_name`."
            elif any(k in tool_name.lower() for k in ["distinctcategories"]):
                prompt_modifier = "This tool is for categorical analysis and requires a 'character' data type for `column_name`."

            prompt = (
                f"Analyze the tool to determine if its `column_name` argument is for 'numeric', 'character', or 'any' type.\n"
                f"Tool: `{tool_definition.name}`\nDescription: \"{tool_definition.description}\"\nHint: {prompt_modifier}\n"
                "Respond with a single JSON object: {\"dataType\": \"numeric\" | \"character\" | \"any\"}"
            )

            reason="Determining tool constraints for column iteration."
            call_id = str(uuid.uuid4())
            events.append(self._format_sse({"step": "Calling LLM", "type": "system_message", "details": {"summary": reason, "call_id": call_id}}))

            response_text, input_tokens, output_tokens = await self._call_llm_and_update_tokens(
                prompt=prompt, reason=reason,
                system_prompt_override="You are a JSON-only responding assistant.",
                raise_on_error=True,
                source=self.source
            )

            updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
            if updated_session:
                events.append(self._format_sse({
                    "statement_input": input_tokens,
                    "statement_output": output_tokens,
                    "total_input": updated_session.get("input_tokens", 0),
                    "total_output": updated_session.get("output_tokens", 0),
                    "call_id": call_id
                }, "token_update"))

            try:
                constraints = json.loads(re.search(r'\{.*\}', response_text, re.DOTALL).group(0))
            except (json.JSONDecodeError, AttributeError):
                constraints = {}

        self.tool_constraints_cache[tool_name] = constraints
        return constraints, events

    def _add_to_structured_data(self, tool_result: dict, context_key_override: str = None):
        """Adds tool results to the structured data dictionary."""
        context_key = context_key_override or f"Plan Results: {self.active_prompt_name or 'Ad-hoc'}"
        if context_key not in self.structured_collected_data:
            self.structured_collected_data[context_key] = []

        if isinstance(tool_result, list):
             self.structured_collected_data[context_key].extend(tool_result)
        else:
             self.structured_collected_data[context_key].append(tool_result)
        app_logger.debug(f"Added tool result to structured data under key: '{context_key}'.")

    def _distill_data_for_llm_context(self, data: any) -> any:
        """
        Recursively distills large data structures into metadata summaries to protect the LLM context window.
        """
        if isinstance(data, dict):
            if 'results' in data and isinstance(data['results'], list):
                results_list = data['results']
                is_large = (len(results_list) > APP_CONFIG.CONTEXT_DISTILLATION_MAX_ROWS or
                            len(json.dumps(results_list)) > APP_CONFIG.CONTEXT_DISTILLATION_MAX_CHARS)

                if is_large and all(isinstance(item, dict) for item in results_list):
                    distilled_result = {
                        "status": data.get("status", "success"),
                        "metadata": {
                            "row_count": len(results_list),
                            "columns": list(results_list[0].keys()) if results_list else [],
                            **data.get("metadata", {})
                        },
                        "comment": "Full data is too large for context. This is a summary."
                    }
                    return distilled_result

            return {key: self._distill_data_for_llm_context(value) for key, value in data.items()}

        elif isinstance(data, list):
            return [self._distill_data_for_llm_context(item) for item in data]

        return data

    def _find_value_by_key(self, data_structure: any, target_key: str) -> any:
        """Recursively searches a nested data structure for the first value of a given key."""
        if isinstance(data_structure, dict):
            # Check for a direct match, but be case-insensitive for robustness
            for key, value in data_structure.items():
                if key.lower() == target_key.lower():
                    return value

            # If no direct match, recurse into values
            for value in data_structure.values():
                found = self._find_value_by_key(value, target_key)
                if found is not None:
                    return found

        elif isinstance(data_structure, list):
            for item in data_structure:
                found = self._find_value_by_key(item, target_key)
                if found is not None:
                    return found
        return None

    def _unwrap_single_value_from_result(self, data_structure: any) -> any:
        """
        Deterministically unwraps a standard tool result structure to extract a
        single primary value, if one exists.
        """
        is_single_value_structure = (
            isinstance(data_structure, list) and len(data_structure) == 1 and
            isinstance(data_structure[0], dict) and "results" in data_structure[0] and
            isinstance(data_structure[0]["results"], list) and len(data_structure[0]["results"]) == 1 and
            isinstance(data_structure[0]["results"][0], dict) and len(data_structure[0]["results"][0]) == 1
        )

        if is_single_value_structure:
            # Extract the single value from the nested structure
            return next(iter(data_structure[0]["results"][0].values()))

        # If the structure doesn't match, return the original data structure
        return data_structure

    def _resolve_arguments(self, arguments: dict, loop_item: dict = None) -> dict:
        """
        Scans tool arguments for placeholders and resolves them based on the
        current context (workflow state and the optional loop_item).
        """
        if not isinstance(arguments, dict):
            return arguments

        resolved_args = {}

        placeholder_pattern = re.compile(r'(\s*\{[\s\n]*"source":\s*"[^"]+"(?:,[\s\n]*"key":\s*"[^"]+")?[\s\n]*\}\s*)')

        def _resolve_embedded_placeholder(match):
            """Callback function for re.sub to resolve a matched placeholder string."""
            placeholder_str = match.group(1).strip()
            try:
                placeholder_data = json.loads(placeholder_str)
                source_key = placeholder_data.get("source")
                target_key = placeholder_data.get("key")

                data_from_source = None
                if source_key == "loop_item" and loop_item:
                    data_from_source = loop_item
                elif source_key and source_key.startswith("result_of_phase_"):
                    data_from_source = self.workflow_state.get(source_key)
                elif source_key and source_key.startswith("phase_"):
                    data_from_source = self.workflow_state.get(f"result_of_{source_key}")
                elif source_key:
                    data_from_source = self.workflow_state.get(source_key)

                if data_from_source is None:
                    app_logger.warning(f"Could not resolve embedded placeholder: source '{source_key}' not found.")
                    return match.group(1)

                if target_key:
                    found_value = self._find_value_by_key(data_from_source, target_key)
                else:
                    found_value = self._unwrap_single_value_from_result(data_from_source)

                if found_value is not None:
                    app_logger.info(f"Resolved embedded placeholder '{placeholder_str}' to value '{found_value}'.")
                    return str(found_value)
                else:
                    app_logger.warning(f"Could not resolve embedded placeholder: key '{target_key}' not found in source '{source_key}'.")
                    return match.group(1)

            except (json.JSONDecodeError, AttributeError):
                return match.group(1)

        for key, value in arguments.items():
            if isinstance(value, str) and '"source":' in value and not placeholder_pattern.fullmatch(value.strip()):
                resolved_value = placeholder_pattern.sub(_resolve_embedded_placeholder, value)
                resolved_args[key] = resolved_value
                continue

            source_phase_key = None
            target_data_key = None
            is_placeholder = False
            original_placeholder = copy.deepcopy(value)

            if isinstance(value, dict) and value.get("source") == "loop_item" and loop_item:
                loop_key = value.get("key")
                # --- MODIFICATION START ---
                # If a key is specified, get that value. If no key is specified, pass the entire loop_item.
                resolved_args[key] = loop_item.get(loop_key) if loop_key else loop_item
                # --- MODIFICATION END ---
                continue

            if isinstance(value, str):
                match = re.match(r"(result_of_phase_\d+|phase_\d+|injected_previous_turn_data)", value)
                if match:
                    source_phase_key = match.group(1)
                    is_placeholder = True

            elif isinstance(value, dict):
                if "source" in value and "key" in value:
                    source_phase_key = value["source"]
                    target_data_key = value["key"]
                    is_placeholder = True

                elif "source" in value and "key" not in value:
                    source_phase_key = value["source"]
                    target_data_key = None
                    is_placeholder = True
                    self.events_to_yield.append(self._format_sse({
                        "step": "System Correction", "type": "workaround",
                        "details": {
                            "summary": "The agent's plan used an incomplete placeholder. The system will automatically extract the primary value from the source.",
                            "correction_type": "placeholder_unwrapping",
                            "from": original_placeholder,
                            "to": f"Unwrapped value from '{source_phase_key}'"
                        }
                    }))

                else:
                    for k, v in value.items():
                        if re.match(r"result_of_phase_\d+", k):
                            source_phase_key = k
                            target_data_key = v
                            is_placeholder = True

                            canonical_value = {"source": source_phase_key, "key": target_data_key}
                            self.events_to_yield.append(self._format_sse({
                                "step": "System Correction", "type": "workaround",
                                "details": {
                                    "summary": "The agent's plan contained a non-standard placeholder. The system has automatically normalized it to ensure correct data flow.",
                                    "correction_type": "placeholder_normalization",
                                    "from": original_placeholder,
                                    "to": canonical_value
                                }
                            }))
                            value = canonical_value
                            break

            if is_placeholder:
                if source_phase_key and source_phase_key.startswith("phase_"):
                    source_phase_key = f"result_of_{source_phase_key}"

                if source_phase_key in self.workflow_state:
                    data_from_phase = self.workflow_state[source_phase_key]

                    if target_data_key:
                        found_value = self._find_value_by_key(data_from_phase, target_data_key)
                        if found_value is not None:
                            resolved_args[key] = found_value
                        else:
                            app_logger.warning(f"Could not resolve placeholder: key '{target_data_key}' not found in '{source_phase_key}'.")
                            resolved_args[key] = None
                    else:
                        unwrapped_value = self._unwrap_single_value_from_result(data_from_phase)
                        resolved_args[key] = unwrapped_value
                        app_logger.info(f"Resolved placeholder for '{key}' by unwrapping the result of '{source_phase_key}'.")

                else:
                    app_logger.warning(f"Could not resolve placeholder: source '{source_phase_key}' not in workflow state.")
                    resolved_args[key] = value

            elif isinstance(value, dict):
                resolved_args[key] = self._resolve_arguments(value, loop_item)

            elif isinstance(value, list):
                resolved_list = [self._resolve_arguments(item, loop_item) if isinstance(item, dict) else item for item in value]
                resolved_args[key] = resolved_list

            else:
                resolved_args[key] = value

        return resolved_args

    async def _generate_session_name(self, query: str) -> str:
        """
        Uses the LLM to generate a concise name for the session based on the initial query.
        """
        prompt = (
            f"Based on the following user query, generate a concise and descriptive name (3-5 words) "
            f"suitable for a chat session history list. Do not include any punctuation or extra text.\n\n"
            f"User Query: \"{query}\"\n\n"
            f"Session Name:"
        )
        reason = "Generating session name from initial query."
        system_prompt = "You generate short, descriptive titles. Only respond with the title text."

        try:
            name_text, _, _ = await self._call_llm_and_update_tokens(
                prompt=prompt,
                reason=reason,
                system_prompt_override=system_prompt,
                raise_on_error=True,
                disabled_history=True, # Don't need history for naming
                source="system" # Indicate system-initiated call
            )
            # Basic cleaning: remove extra quotes, trim whitespace
            cleaned_name = name_text.strip().strip('"\'')
            if cleaned_name:
                app_logger.info(f"Generated session name: '{cleaned_name}'")
                return cleaned_name
            else:
                app_logger.warning("LLM returned an empty session name.")
                return "New Chat" # Fallback
        except Exception as e:
            app_logger.error(f"Failed to generate session name: {e}", exc_info=True)
            return "New Chat" # Fallback on error


    async def run(self):
        """The main, unified execution loop for the agent."""
        final_answer_override = None
        
        # --- CONSUMPTION ENFORCEMENT START ---
        # Check rate limits and token quotas BEFORE execution
        try:
            from trusted_data_agent.auth.database import get_db_session
            from trusted_data_agent.auth.consumption_manager import ConsumptionManager
            
            with get_db_session() as db_session:
                manager = ConsumptionManager(db_session)
                
                # Check rate limits
                rate_allowed, rate_reason = manager.check_rate_limits(self.user_uuid)
                if not rate_allowed:
                    error_msg = f"Rate limit exceeded: {rate_reason}"
                    app_logger.warning(f"Blocking execution for user {self.user_uuid}: {error_msg}")
                    raise ValueError(error_msg)
                
                # Check token quotas
                quota_allowed, quota_reason = manager.check_token_quota(self.user_uuid)
                if not quota_allowed:
                    error_msg = f"Token quota exceeded: {quota_reason}"
                    app_logger.warning(f"Blocking execution for user {self.user_uuid}: {error_msg}")
                    raise ValueError(error_msg)
                
                app_logger.debug(f"Consumption checks passed for user {self.user_uuid}")
        except ValueError:
            # Re-raise quota/rate limit errors
            raise
        except Exception as e:
            # Non-critical: If enforcement fails, allow execution (fail-open)
            app_logger.error(f"Failed to check consumption limits for user {self.user_uuid}: {e}")
        # --- CONSUMPTION ENFORCEMENT END ---
        
        # --- MODIFICATION START: Calculate turn number once and store on self ---
        self.current_turn_number = 1
        session_data = await session_manager.get_session(self.user_uuid, self.session_id)
        if session_data and isinstance(session_data.get("last_turn_data", {}).get("workflow_history"), list):
            self.current_turn_number = len(session_data["last_turn_data"]["workflow_history"]) + 1
        app_logger.info(f"PlanExecutor initialized for turn: {self.current_turn_number}")
        # --- MODIFICATION END ---

        # --- MODIFICATION START: Setup temporary profile override if requested ---
        temp_llm_instance = None
        temp_mcp_client = None
        
        # Debug log to verify profile_override_id is being passed
        if self.profile_override_id:
            app_logger.info(f"🔍 Profile override detected: {self.profile_override_id}")
        else:
            app_logger.info(f"ℹ️  No profile override - using default profile configuration")
        
        if self.profile_override_id:
            try:
                from trusted_data_agent.core.config_manager import get_config_manager
                from langchain_mcp_adapters.client import MultiServerMCPClient
                import boto3
                
                config_manager = get_config_manager()
                profiles = config_manager.get_profiles()
                override_profile = next((p for p in profiles if p.get("id") == self.profile_override_id), None)
                
                if not override_profile:
                    app_logger.warning(f"Profile override ID {self.profile_override_id} not found. Using default profile.")
                else:
                    # Store original state BEFORE logging (to capture default profile info)
                    self.original_llm = APP_STATE.get('llm')
                    self.original_mcp_tools = APP_STATE.get('mcp_tools')
                    self.original_mcp_prompts = APP_STATE.get('mcp_prompts')
                    self.original_structured_tools = APP_STATE.get('structured_tools')
                    self.original_structured_prompts = APP_STATE.get('structured_prompts')
                    self.original_provider = get_user_provider(self.user_uuid)
                    self.original_model = get_user_model(self.user_uuid)
                    
                    # Save provider-specific details
                    if self.original_provider == "Friendli":
                        self.original_provider_details['friendli'] = getattr(APP_CONFIG, 'CURRENT_FRIENDLI_DETAILS', None)
                    elif self.original_provider == "Azure":
                        self.original_provider_details['azure'] = getattr(APP_CONFIG, 'CURRENT_AZURE_DEPLOYMENT_DETAILS', None)
                    elif self.original_provider == "Amazon":
                        self.original_provider_details['aws_region'] = getattr(APP_CONFIG, 'CURRENT_AWS_REGION', None)
                        self.original_provider_details['aws_model_provider'] = getattr(APP_CONFIG, 'CURRENT_MODEL_PROVIDER_IN_PROFILE', None)
                    original_provider = self.original_provider
                    original_model = self.original_model
                    
                    app_logger.info(f"\n{'='*80}")
                    app_logger.info(f"🔄 TEMPORARY PROFILE SWITCH INITIATED")
                    app_logger.info(f"From: Default Profile (Provider: {original_provider}, Model: {original_model})")
                    app_logger.info(f"To: {override_profile.get('name', 'Unknown')} (Tag: @{override_profile.get('tag', 'N/A')}, ID: {self.profile_override_id})")
                    app_logger.info(f"{'='*80}\n")
                    
                    # Get override profile's LLM configuration
                    override_llm_config_id = override_profile.get('llmConfigurationId')
                    if override_llm_config_id:
                        llm_configs = config_manager.get_llm_configurations()
                        override_llm_config = next((cfg for cfg in llm_configs if cfg['id'] == override_llm_config_id), None)
                        
                        if override_llm_config:
                            provider = override_llm_config.get('provider')
                            model = override_llm_config.get('model')
                            credentials = override_llm_config.get('credentials', {})
                            
                            app_logger.info(f"📝 Creating temporary LLM instance")
                            app_logger.info(f"   Provider: {provider}")
                            app_logger.info(f"   Model: {model}")
                            app_logger.info(f"   Config ID: {override_llm_config_id}")
                            
                            # Load stored credentials from encrypted database (authentication always enabled)
                            from trusted_data_agent.auth.models import User
                            from trusted_data_agent.auth.database import get_db_session
                            from trusted_data_agent.core.configuration_service import retrieve_credentials_for_provider
                            
                            try:
                                # Get user_id from database using user_uuid (not from request context)
                                with get_db_session() as session:
                                    user = session.query(User).filter_by(id=self.user_uuid).first()
                                    if user:
                                        app_logger.info(f"Loading credentials for user {user.id}, provider {provider}")
                                        stored_result = await retrieve_credentials_for_provider(user.id, provider)
                                        if stored_result.get("credentials"):
                                            credentials = {**stored_result["credentials"], **credentials}
                                            app_logger.info(f"✓ Successfully loaded stored credentials for {provider}")
                                        else:
                                            app_logger.warning(f"No stored credentials found for {provider} (status: {stored_result.get('status')})")
                                    else:
                                        app_logger.warning(f"User not found for uuid {self.user_uuid}, cannot load stored credentials")
                            except Exception as e:
                                app_logger.error(f"Error loading stored credentials: {e}", exc_info=True)
                            
                            # Create temporary LLM instance using shared factory
                            from trusted_data_agent.llm.client_factory import create_llm_client, get_provider_config_details
                            
                            try:
                                temp_llm_instance = await create_llm_client(provider, model, credentials)
                                
                                # Only update if LLM instance was created successfully
                                # Update APP_CONFIG and executor's cached values for this turn
                                set_user_provider(provider, self.user_uuid)
                                set_user_model(model, self.user_uuid)
                                self.current_provider = provider
                                self.current_model = model
                                
                                # Apply provider-specific configuration details
                                provider_details = get_provider_config_details(provider, model, credentials)
                                for key, value in provider_details.items():
                                    setattr(APP_CONFIG, key, value)
                                
                                APP_STATE['llm'] = temp_llm_instance
                                app_logger.info(f"✅ LLM instance created and configured successfully")
                            except Exception as llm_error:
                                app_logger.error(f"❌ Failed to create LLM instance for profile override: {llm_error}")
                                app_logger.error(f"   Provider: {provider}, Model: {model}")
                                app_logger.error(f"   Credentials present: {bool(credentials)}")
                                app_logger.error(f"   Continuing with default profile")
                                raise  # Re-raise to trigger outer exception handler
                    
                    # Get override profile's MCP server configuration
                    override_mcp_server_id = override_profile.get('mcpServerId')
                    if override_mcp_server_id:
                        mcp_servers = config_manager.get_mcp_servers()
                        override_mcp_server = next((srv for srv in mcp_servers if srv['id'] == override_mcp_server_id), None)
                        
                        if override_mcp_server:
                            server_name = override_mcp_server.get('name')
                            host = override_mcp_server.get('host')
                            port = override_mcp_server.get('port')
                            path = override_mcp_server.get('path')
                            
                            app_logger.info(f"🔧 Creating temporary MCP client")
                            app_logger.info(f"   Server: {server_name}")
                            app_logger.info(f"   URL: http://{host}:{port}{path}")
                            
                            mcp_server_url = f"http://{host}:{port}{path}"
                            temp_server_configs = {server_name: {"url": mcp_server_url, "transport": "streamable_http"}}
                            temp_mcp_client = MultiServerMCPClient(temp_server_configs)
                            
                            # Load and process tools using the same method as configuration_service
                            from langchain_mcp_adapters.tools import load_mcp_tools
                            async with temp_mcp_client.session(server_name) as session:
                                all_processed_tools = await load_mcp_tools(session)
                            
                            # Get enabled tool and prompt names for this profile
                            enabled_tool_names = set(config_manager.get_profile_enabled_tools(self.profile_override_id))
                            enabled_prompt_names = set(config_manager.get_profile_enabled_prompts(self.profile_override_id))
                            
                            # Filter to only enabled tools (prompts handled separately via original structure)
                            filtered_tools = [tool for tool in all_processed_tools if tool.name in enabled_tool_names]
                            
                            # Convert to dictionary with tool names as keys (matching normal structure)
                            filtered_tools_dict = {tool.name: tool for tool in filtered_tools}
                            
                            # For prompts, filter the original mcp_prompts dict
                            filtered_prompts_dict = {name: prompt for name, prompt in self.original_mcp_prompts.items() 
                                                    if name in enabled_prompt_names}
                            
                            # Rebuild structured_tools to only include filtered tools
                            # Keep the original structure but filter the tool lists
                            filtered_structured_tools = {}
                            
                            for category, tools_list in (self.original_structured_tools or {}).items():
                                filtered_category_tools = [
                                    tool_info for tool_info in tools_list 
                                    if tool_info['name'] in enabled_tool_names or tool_info['name'].startswith('TDA_')
                                ]
                                if filtered_category_tools:
                                    filtered_structured_tools[category] = filtered_category_tools
                            
                            # Rebuild structured_prompts to only include filtered prompts
                            filtered_structured_prompts = {}
                            
                            for category, prompts_list in (self.original_structured_prompts or {}).items():
                                filtered_category_prompts = [
                                    prompt_info for prompt_info in prompts_list 
                                    if prompt_info['name'] in enabled_prompt_names
                                ]
                                if filtered_category_prompts:
                                    filtered_structured_prompts[category] = filtered_category_prompts
                            
                            APP_STATE['mcp_client'] = temp_mcp_client
                            APP_STATE['mcp_tools'] = filtered_tools_dict
                            APP_STATE['mcp_prompts'] = filtered_prompts_dict
                            APP_STATE['structured_tools'] = filtered_structured_tools
                            APP_STATE['structured_prompts'] = filtered_structured_prompts
                            
                            app_logger.info(f"✅ MCP client created successfully")
                            app_logger.info(f"   Tools enabled: {len(filtered_tools_dict)} (processed with load_mcp_tools)")
                            app_logger.info(f"   Prompts enabled: {len(filtered_prompts_dict)}")
                            app_logger.info(f"   Categories in structured_tools: {len(filtered_structured_tools)}")
                            app_logger.info(f"   Categories in structured_prompts: {len(filtered_structured_prompts)}")
                            app_logger.info(f"\n{'='*80}")
                            app_logger.info(f"✨ Profile override applied successfully - executing with temporary context")
                            app_logger.info(f"{'='*80}\n")
                    
            except Exception as e:
                app_logger.error(f"Failed to apply profile override: {e}", exc_info=True)
                
                # CRITICAL: Restore original provider/model before they get saved to session
                # The override attempt may have changed self.current_provider and self.current_model
                # but since it failed, we need to restore them to the original values
                if self.original_provider and self.original_model:
                    app_logger.info(f"🔄 Restoring provider/model from {self.current_provider}/{self.current_model} to {self.original_provider}/{self.original_model}")
                    self.current_provider = self.original_provider
                    self.current_model = self.original_model
                    set_user_provider(self.original_provider, self.user_uuid)
                    set_user_model(self.original_model, self.user_uuid)
                
                # Send warning banner notification to user via SSE
                from trusted_data_agent.core.config_manager import get_config_manager
                config_manager = get_config_manager()
                override_profile = None
                if self.profile_override_id:
                    profiles = config_manager.get_profiles(self.user_uuid)
                    override_profile = next((p for p in profiles if p.get("id") == self.profile_override_id), None)
                
                # Get default profile tag for notification
                default_profile_tag = self._get_active_profile_tag()
                
                # Clear profile_override_id NOW so subsequent calls use default profile
                app_logger.info(f"🔄 Clearing profile_override_id to use default profile tag: {default_profile_tag}")
                self.profile_override_id = None
                
                if override_profile:
                    # Send notification as SSE event to show banner in header
                    notification_data = {
                        "type": "profile_override_failed",
                        "payload": {
                            "override_profile_name": override_profile.get('name', 'Unknown'),
                            "override_profile_tag": override_profile.get('tag', 'N/A'),
                            "default_profile_tag": default_profile_tag,
                            "error_message": str(e)
                        }
                    }
                    app_logger.info(f"📢 Yielding profile_override_failed notification: {notification_data}")
                    yield self._format_sse(notification_data, event="notification")
                
                # Continue with default profile if override fails
                # Note: Do NOT call update_models_used here - it will be called below with the restored default values
        # --- MODIFICATION END ---

        # Update session with correct provider/model/profile_tag at the start of execution
        # This ensures the session data is correct before any LLM calls
        profile_tag = self._get_current_profile_tag()
        app_logger.info(f"🔍 About to call update_models_used with: provider={self.current_provider}, model={self.current_model}, profile_tag={profile_tag}, profile_override_id={self.profile_override_id}")
        await session_manager.update_models_used(self.user_uuid, self.session_id, self.current_provider, self.current_model, profile_tag)
        app_logger.info(f"✅ Session {self.session_id} initialized with provider={self.current_provider}, model={self.current_model}, profile_tag={profile_tag}")
        
        # Send immediate SSE notification so UI updates in real-time
        session_data = await session_manager.get_session(self.user_uuid, self.session_id)
        if session_data:
            notification_payload = {
                "session_id": self.session_id,
                "models_used": session_data.get("models_used", []),
                "profile_tags_used": session_data.get("profile_tags_used", []),
                "last_updated": session_data.get("last_updated"),
                "provider": self.current_provider,
                "model": self.current_model,
                "name": session_data.get("name", "Unnamed Session"),
            }
            app_logger.info(f"🔔 [DEBUG] Sending session_model_update SSE notification: provider={notification_payload['provider']}, model={notification_payload['model']}, profile_tags={notification_payload['profile_tags_used']}")
            yield self._format_sse({
                "type": "session_model_update",
                "payload": notification_payload
            }, event="notification")
        else:
            app_logger.warning(f"🔔 [DEBUG] Could not send SSE notification - session_data is None for session {self.session_id}")

        try:
            # --- MODIFICATION START: Handle Replay ---
            if self.plan_to_execute:
                app_logger.info(f"Starting replay execution for user {self.user_uuid}, session {self.session_id}.")
                self.meta_plan = copy.deepcopy(self.plan_to_execute) # Use the provided plan
                self.state = self.AgentState.EXECUTING # Skip planning
                # Inject a status event indicating replay
                replay_type_text = "Optimized" if "optimized" in str(self.is_replay).lower() else "Original" # Basic type check
                # Find the turn ID where this plan originally came from
                original_turn_id = "..." # Default if not found
                if session_data and isinstance(session_data.get("last_turn_data", {}).get("workflow_history"), list):
                    for idx, turn in enumerate(session_data["last_turn_data"]["workflow_history"]):
                        if turn.get("original_plan") == self.plan_to_execute:
                            original_turn_id = str(idx + 1)
                            break

                event_data = {
                    "step": f"🔄 Replaying {replay_type_text} Plan (from Turn {original_turn_id})",
                    "type": "system_message",
                    "details": f"Re-executing {'optimized' if replay_type_text == 'Optimized' else 'original'} plan..."
                }
                self._log_system_event(event_data)
                yield self._format_sse(event_data)
            # --- MODIFICATION END ---
            else:
                if self.is_delegated_task:
                    async for event in self._run_delegated_prompt():
                        yield event
                    return # Exit early for delegated tasks

                # --- Planning Phase ---
                if self.state == self.AgentState.PLANNING:
                    # --- MODIFICATION START: Pass RAG retriever instance to Planner ---
                    # Create a wrapped event handler that captures RAG collection info and knowledge retrieval
                    async def rag_aware_event_handler(data, event_name):
                        if event_name == "rag_retrieval" and data and 'collection_id' in data.get('full_case_data', {}).get('metadata', {}):
                            # Store the collection ID from the retrieved RAG case
                            self.rag_source_collection_id = data['full_case_data']['metadata']['collection_id']
                            app_logger.info(f"RAG example retrieved from collection {self.rag_source_collection_id}")
                        
                        # --- PHASE 2: Track knowledge repository access ---
                        elif event_name == "knowledge_retrieval":
                            collections = data.get("collections", [])
                            document_count = data.get("document_count", 0)
                            
                            # Store knowledge access info for turn summary
                            for collection_name in collections:
                                self.knowledge_accessed.append({
                                    "collection_name": collection_name,
                                    "document_count": document_count,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
                            
                            # Store the full event for replay when plan is reloaded
                            self.knowledge_retrieval_event = data
                            app_logger.info(f"Tracked knowledge retrieval: {len(collections)} collection(s), {document_count} document(s)")
                            app_logger.debug(f"Stored knowledge_retrieval_event with {len(data.get('chunks', []))} chunks")
                        # --- PHASE 2 END ---
                        
                        # Pass through to the original event handler
                        if self.event_handler:
                            await self.event_handler(data, event_name)
                    
                    planner = Planner(self, rag_retriever_instance=self.rag_retriever, event_handler=rag_aware_event_handler)
                    # --- MODIFICATION END ---
                    should_replan = False
                    planning_is_disabled_history = self.disabled_history

                    replan_attempt = 0
                    max_replans = 1
                    while True:
                        replan_context = None
                        is_replan = replan_attempt > 0

                        if is_replan:
                            prompts_in_plan = {p['executable_prompt'] for p in (self.meta_plan or []) if 'executable_prompt' in p}
                            granted_prompts_in_plan = {p for p in prompts_in_plan if p in APP_CONFIG.GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING}
                            non_granted_prompts_to_deconstruct = {p for p in prompts_in_plan if p not in granted_prompts_in_plan}

                            context_parts = ["\n--- CONTEXT FOR RE-PLANNING ---"]
                            deconstruction_instruction = (
                                "Your previous plan was inefficient because it contained high-level prompts that must be broken down. "
                                "You MUST create a new, more detailed plan that achieves the same overall goal."
                            )
                            context_parts.append(deconstruction_instruction)
                            if granted_prompts_in_plan:
                                preservation_rule = (
                                    f"\n**CRITICAL PRESERVATION RULE:** The following prompts are explicitly granted and you **MUST** "
                                    f"include them as phases in the new plan: `{list(granted_prompts_in_plan)}`. "
                                    "You should rebuild the other parts of the plan around these required steps.\n"
                                )
                                context_parts.append(preservation_rule)
                            if non_granted_prompts_to_deconstruct:
                                deconstruction_directive = (
                                    "\n**CRITICAL REPLANNING DIRECTIVE:** You **MUST** replicate the logical goal of the following discarded prompt(s) "
                                    "using **only basic tools**. To help you, here are their original goals:"
                                )
                                context_parts.append(deconstruction_directive)
                                for prompt_name in non_granted_prompts_to_deconstruct:
                                    prompt_info = self._get_prompt_info(prompt_name)
                                    if prompt_info:
                                        context_parts.append(f"- The goal of the discarded prompt `{prompt_name}` was: \"{prompt_info.get('description', 'No description.')}\"")
                            replan_context = "\n".join(context_parts)

                        async for event in planner.generate_and_refine_plan(
                            force_disable_history=planning_is_disabled_history,
                            replan_context=replan_context
                        ):
                            # --- MODIFICATION START: Capture and log planner corrections ---
                            # Check if the yielded event is a system correction and log it to the history.
                            if "system_correction" in event.lower() or '"type": "workaround"' in event.lower():
                                try:
                                    # The event is a JSON string, parse it.
                                    event_data = json.loads(event.replace("data: ", "").strip())
                                    self.turn_action_history.append({"action": "system_correction", "result": event_data})
                                except json.JSONDecodeError:
                                    app_logger.warning(f"Could not parse planner event for history logging: {event}")
                            # --- MODIFICATION END ---
                            yield event

                        # --- MODIFICATION START: Store original plan AFTER refinement ---
                        # Store the plan that was actually generated and refined before any execution begins
                        self.original_plan_for_history = copy.deepcopy(self.meta_plan)
                        app_logger.debug("Stored original plan (post-refinement) for history.")
                        # --- MODIFICATION END ---

                        plan_has_prompt = self.meta_plan and any('executable_prompt' in phase for phase in self.meta_plan)
                        replan_triggered = False
                        if plan_has_prompt:
                            prompts_in_plan = {phase['executable_prompt'] for phase in self.meta_plan if 'executable_prompt' in phase}
                            non_granted_prompts = [p for p in prompts_in_plan if p not in APP_CONFIG.GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING]
                            has_other_significant_tool = any('executable_prompt' not in phase and phase.get('relevant_tools') != ['TDA_LLMTask'] for phase in self.meta_plan)
                            is_single_phase_prompt = len(self.meta_plan) == 1
                            if has_other_significant_tool and not is_single_phase_prompt and non_granted_prompts:
                                replan_triggered = True

                        if self.execution_depth == 0 and replan_triggered and replan_attempt < max_replans:
                            replan_attempt += 1
                            event_data = {
                                "step": "Re-planning for Efficiency", "type": "plan_optimization",
                                "details": {
                                    "summary": "Initial plan uses a sub-prompt alongside other tools. Agent is re-planning to create a more efficient, tool-only workflow.",
                                    "original_plan": copy.deepcopy(self.meta_plan) # Log the plan *before* this replan
                                }
                            }
                            self._log_system_event(event_data)
                            yield self._format_sse(event_data)
                            continue # Loop back to replan
                        break # Exit planning loop

                    # Handle single prompt plan expansion (if applicable)
                    self.is_single_prompt_plan = (self.meta_plan and len(self.meta_plan) == 1 and 'executable_prompt' in self.meta_plan[0] and not self.is_delegated_task)

                    if self.is_single_prompt_plan:
                        async for event in self._handle_single_prompt_plan(planner):
                            yield event
                        # --- MODIFICATION START: Re-capture plan if single prompt expansion happened ---
                        # If the plan was expanded from a single prompt, update the stored original plan
                        self.original_plan_for_history = copy.deepcopy(self.meta_plan)
                        app_logger.debug("Re-stored plan after single-prompt expansion for history.")
                        # --- MODIFICATION END ---


                    # Check for conversational plan
                    if self.is_conversational_plan:
                        app_logger.info("Detected a conversational plan. Bypassing execution.")
                        self.state = self.AgentState.SUMMARIZING
                    else:
                        self.state = self.AgentState.EXECUTING

            # --- Execution Phase ---
            try:
                if self.state == self.AgentState.EXECUTING:
                    async for event in self._run_plan(): yield event
            except DefinitiveToolError as e:
                app_logger.error(f"Execution halted by definitive tool error: {e.friendly_message}")
                event_data = {"step": "Unrecoverable Error", "details": e.friendly_message, "type": "error"}
                self._log_system_event(event_data, "tool_result")
                yield self._format_sse(event_data, "tool_result")
                final_answer_override = f"I could not complete the request. Reason: {e.friendly_message}"
                self.state = self.AgentState.SUMMARIZING # Go to summarization even on error

            # --- Summarization Phase ---
            if self.state == self.AgentState.SUMMARIZING:
                async for event in self._handle_summarization(final_answer_override):
                    yield event

        except asyncio.CancelledError:
            # Handle cancellation specifically
            app_logger.info(f"PlanExecutor execution cancelled for user {self.user_uuid}, session {self.session_id}.")
            self.state = self.AgentState.ERROR # Mark as error to prevent history update
            # Yield a specific event to the frontend
            event_data = {"step": "Execution Stopped", "details": "The process was stopped by the user.", "type": "cancelled"}
            self._log_system_event(event_data, "cancelled")
            yield self._format_sse(event_data, "cancelled")
            # Re-raise so the caller (routes.py) knows it was cancelled
            raise

        except Exception as e:
            # Handle other general exceptions
            root_exception = unwrap_exception(e)
            app_logger.error(f"Error in state {self.state.name} for user {self.user_uuid}, session {self.session_id}: {root_exception}", exc_info=True)
            self.state = self.AgentState.ERROR
            event_data = {"error": "Execution stopped due to an unrecoverable error.", "details": str(root_exception), "step": "Unrecoverable Error", "type": "error"}
            self._log_system_event(event_data, "error")
            yield self._format_sse(event_data, "error")

        finally:
            # --- MODIFICATION START: Restore original MCP/LLM state if profile was overridden ---
            if self.profile_override_id:
                try:
                    from trusted_data_agent.core.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    default_profile_id = config_manager.get_default_profile_id()
                    default_profile_name = "Default Profile"
                    if default_profile_id:
                        profiles = config_manager.get_profiles()
                        default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
                        if default_profile:
                            default_profile_name = f"{default_profile.get('name')} (Tag: @{default_profile.get('tag', 'N/A')})"
                    
                    app_logger.info(f"\n{'='*80}")
                    app_logger.info(f"🔙 REVERTING TO DEFAULT PROFILE")
                    app_logger.info(f"Restoring: {default_profile_name}")
                    
                    if self.original_llm is not None:
                        APP_STATE['llm'] = self.original_llm
                        if self.original_provider:
                            set_user_provider(self.original_provider, self.user_uuid)
                        if self.original_model:
                            set_user_model(self.original_model, self.user_uuid)
                        
                        # Restore provider-specific details
                        if self.original_provider == "Friendli" and 'friendli' in self.original_provider_details:
                            set_user_friendli_details(self.original_provider_details['friendli'], self.user_uuid)
                        elif self.original_provider == "Azure" and 'azure' in self.original_provider_details:
                            set_user_azure_deployment_details(self.original_provider_details['azure'], self.user_uuid)
                        elif self.original_provider == "Amazon":
                            if 'aws_region' in self.original_provider_details:
                                set_user_aws_region(self.original_provider_details['aws_region'], self.user_uuid)
                            if 'aws_model_provider' in self.original_provider_details:
                                set_user_model_provider_in_profile(self.original_provider_details['aws_model_provider'], self.user_uuid)
                        
                        app_logger.info(f"✅ Restored original LLM instance")
                        app_logger.info(f"   Provider: {self.original_provider}")
                        app_logger.info(f"   Model: {self.original_model}")
                    
                    if self.original_mcp_tools is not None:
                        APP_STATE['mcp_tools'] = self.original_mcp_tools
                        app_logger.info(f"✅ Restored original MCP tools ({len(self.original_mcp_tools)} tools)")
                    
                    if self.original_mcp_prompts is not None:
                        APP_STATE['mcp_prompts'] = self.original_mcp_prompts
                        app_logger.info(f"✅ Restored original MCP prompts ({len(self.original_mcp_prompts)} prompts)")
                    
                    if self.original_structured_tools is not None:
                        APP_STATE['structured_tools'] = self.original_structured_tools
                        app_logger.info(f"✅ Restored original structured_tools ({len(self.original_structured_tools)} categories)")
                    
                    if self.original_structured_prompts is not None:
                        APP_STATE['structured_prompts'] = self.original_structured_prompts
                        app_logger.info(f"✅ Restored original structured_prompts ({len(self.original_structured_prompts)} categories)")
                    
                    # Close temporary MCP client if created
                    if temp_mcp_client:
                        try:
                            # Note: MultiServerMCPClient may not have explicit close method
                            # But context managers handle cleanup automatically
                            pass
                        except Exception as cleanup_error:
                            app_logger.warning(f"⚠️  Error closing temporary MCP client: {cleanup_error}")
                    
                    app_logger.info(f"{'='*80}")
                    app_logger.info(f"✅ Successfully reverted to default profile")
                    app_logger.info(f"{'='*80}\n")
                    
                except Exception as restore_error:
                    app_logger.error(f"❌ Error restoring original state after profile override: {restore_error}", exc_info=True)
            # --- MODIFICATION END ---
            
            # --- Cleanup Phase (Always runs) ---
            # --- MODIFICATION START: Only top-level executor (depth 0) saves history ---
            # Update history only if the execution wasn't cancelled, errored,
            # AND this is the top-level executor instance.
            if self.state != self.AgentState.ERROR and self.execution_depth == 0:
            # --- MODIFICATION END ---
                # --- MODIFICATION START: Include model/provider and use self.current_turn_number ---
                # Get profile tag from default profile (or override if active)
                profile_tag = self._get_current_profile_tag()
                
                turn_summary = {
                    "turn": self.current_turn_number, # Use the authoritative instance variable
                    "user_query": self.original_user_input, # Store the original query
                    "original_plan": self.original_plan_for_history, # Store the actual plan used
                    "execution_trace": self.turn_action_history,
                    "final_summary": self.final_summary_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "provider": self.current_provider, # Add snapshot of provider (for backwards compatibility)
                    "model": self.current_model,       # Add snapshot of model (for backwards compatibility)
                    "profile_tag": profile_tag,        # Add snapshot of profile tag
                    "task_id": self.task_id,            # Add the task_id
                    "turn_input_tokens": self.turn_input_tokens,
                    "turn_output_tokens": self.turn_output_tokens,
                    # --- MODIFICATION START: Add session_id for RAG worker ---
                    "session_id": self.session_id,
                    # --- MODIFICATION END ---
                    # --- MODIFICATION START: Add RAG source collection ID ---
                    "rag_source_collection_id": self.rag_source_collection_id,
                    # --- MODIFICATION END ---
                    # --- PHASE 2: Add knowledge repository tracking ---
                    "knowledge_accessed": self.knowledge_accessed,  # List of knowledge collections used
                    "knowledge_retrieval_event": self.knowledge_retrieval_event  # Full event for replay on reload
                    # --- PHASE 2 END ---
                }
                # --- MODIFICATION END ---
                await session_manager.update_last_turn_data(self.user_uuid, self.session_id, turn_summary)
                app_logger.debug(f"Saved last turn data to session {self.session_id} for user {self.user_uuid}")

                # --- MODIFICATION START: Add "Producer" logic to send turn to RAG worker ---
                # Skip RAG processing for temporary API sessions (e.g., prompt execution, question generation)
                # Check the source parameter to determine if this is a temporary/utility execution
                skip_rag_for_temp_sessions = self.source in [
                    "prompt_library_raw",
                    "question_generator"
                ]
                
                if APP_CONFIG.RAG_ENABLED and APP_STATE.get('rag_processing_queue') and self.rag_retriever and not skip_rag_for_temp_sessions:
                    try:
                        app_logger.debug(f"Adding turn {self.current_turn_number} to RAG processing queue.")
                        # Add user_uuid to turn_summary for session updates
                        turn_summary['user_uuid'] = self.user_uuid
                        # Put the summary in the queue. This is non-blocking and instantaneous.
                        await APP_STATE['rag_processing_queue'].put(turn_summary)
                    except Exception as e:
                        # Log error if queue.put fails, but don't crash the executor
                        app_logger.error(f"Failed to add turn summary to RAG processing queue: {e}", exc_info=True)
                elif skip_rag_for_temp_sessions:
                    app_logger.debug(f"Skipping RAG processing for temporary execution with source: {self.source}")
                # --- MODIFICATION END ---


                # Session Naming Logic (remains unchanged)
                # --- MODIFICATION START: Use self.current_turn_number for check ---
                if self.current_turn_number == 1 and session_data and session_data.get("name") == "New Chat":
                # --- MODIFICATION END ---
                    app_logger.info(f"First turn detected for session {self.session_id}. Attempting to generate name.")
                    new_name = await self._generate_session_name(self.original_user_input)
                    if new_name != "New Chat":
                        try:
                            await session_manager.update_session_name(self.user_uuid, self.session_id, new_name)
                            yield self._format_sse({
                                "session_id": self.session_id,
                                "newName": new_name
                            }, "session_name_update")
                            app_logger.info(f"Successfully updated session {self.session_id} name to '{new_name}'.")
                        except Exception as name_e:
                            app_logger.error(f"Failed to save or emit updated session name '{new_name}': {name_e}", exc_info=True)

            else:
                 # --- MODIFICATION START: Update log message to include depth ---
                 app_logger.info(
                     f"Skipping history save for user {self.user_uuid}, session {self.session_id}. "
                     f"Final state: {self.state.name}, Execution Depth: {self.execution_depth}"
                 )
                 # --- MODIFICATION END ---
    # --- END of run method ---


    async def _handle_single_prompt_plan(self, planner: Planner):
        """Orchestrates the logic for expanding a single-prompt plan."""
        single_phase = self.meta_plan[0]
        prompt_name = single_phase.get('executable_prompt')
        prompt_args = single_phase.get('arguments', {})

        event_data = {
            "step": "System Correction", "type": "workaround",
            "details": f"Single Prompt('{prompt_name}') identified. Expanding plan in-process to improve efficiency."
        }
        self._log_system_event(event_data)
        yield self._format_sse(event_data)

        prompt_info = self._get_prompt_info(prompt_name)
        if prompt_info:
            required_args = {arg['name'] for arg in prompt_info.get('arguments', []) if arg.get('required')}
            missing_args = required_args - set(prompt_args.keys())

            if missing_args:
                event_data = {
                    "step": "System Correction", "type": "workaround",
                    "details": f"Prompt '{prompt_name}' is missing required arguments: {missing_args}. Attempting to extract from user query."
                }
                self._log_system_event(event_data)
                yield self._format_sse(event_data)

                enrichment_prompt = (
                    f"You are an expert argument extractor. From the user's query, extract the values for the following missing arguments: {list(missing_args)}. "
                    f"User Query: \"{self.original_user_input}\"\n"
                    "Respond with only a single, valid JSON object mapping the argument names to their extracted values."
                )
                reason = f"Extracting missing arguments for prompt '{prompt_name}'"

                call_id = str(uuid.uuid4())
                event_data = {
                    "step": "Calling LLM for Argument Enrichment",
                    "type": "system_message",
                    "details": {"summary": reason, "call_id": call_id}
                }
                self._log_system_event(event_data)
                yield self._format_sse(event_data)
                yield self._format_sse({"target": "llm", "state": "busy"}, "status_indicator_update")

                response_text, input_tokens, output_tokens = await self._call_llm_and_update_tokens(
                    prompt=enrichment_prompt, reason=reason,
                    system_prompt_override="You are a JSON-only responding assistant.",
                    raise_on_error=True,
                    source=self.source
                )

                updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
                if updated_session:
                    yield self._format_sse({
                        "statement_input": input_tokens, "statement_output": output_tokens,
                        "total_input": updated_session.get("input_tokens", 0),
                        "total_output": updated_session.get("output_tokens", 0),
                        "call_id": call_id
                    }, "token_update")

                yield self._format_sse({"target": "llm", "state": "idle"}, "status_indicator_update")

                try:
                    extracted_args = json.loads(response_text)
                    prompt_args.update(extracted_args)
                    app_logger.info(f"Successfully enriched arguments: {extracted_args}")
                except (json.JSONDecodeError, AttributeError) as e:
                    app_logger.error(f"Failed to parse extracted arguments: {e}. The prompt may fail.")

        self.active_prompt_name = prompt_name
        self.prompt_arguments = self._resolve_arguments(prompt_args)
        self.prompt_type = prompt_info.get("prompt_type", "reporting") if prompt_info else "reporting"

        # Regenerate the plan based on the expanded prompt
        async for event in planner.generate_and_refine_plan():
            yield event

    async def _run_plan(self):
        """Executes the generated meta-plan, delegating to the PhaseExecutor."""
        if not self.meta_plan:
            raise RuntimeError("Cannot execute plan: meta_plan is not generated.")

        phase_executor = PhaseExecutor(self) # Pass self (PlanExecutor instance)

        # Skip final summary check (remains unchanged)
        if not APP_CONFIG.SUB_PROMPT_FORCE_SUMMARY and self.execution_depth > 0 and len(self.meta_plan) > 1:
            last_phase = self.meta_plan[-1]
            last_phase_tools = last_phase.get('relevant_tools', [])
            is_final_report_phase = any(tool in ["TDA_FinalReport", "TDA_ComplexPromptReport"] for tool in last_phase_tools)

            if is_final_report_phase:
                app_logger.info(f"Sub-process (depth {self.execution_depth}) is skipping its final summary phase.")
                event_data = {
                    "step": "Plan Optimization", "type": "plan_optimization",
                    "details": "Sub-process is skipping its final summary task to prevent redundant work. The main process will generate the final report."
                }
                self._log_system_event(event_data)
                yield self._format_sse(event_data)
                self.meta_plan = self.meta_plan[:-1]


        while self.current_phase_index < len(self.meta_plan):
            current_phase = self.meta_plan[self.current_phase_index]
            is_delegated_prompt_phase = 'executable_prompt' in current_phase and self.execution_depth < self.MAX_EXECUTION_DEPTH

            # --- MODIFICATION START: Add replay status prefix ---
            replay_prefix = ""
            if self.is_replay:
                replay_type_text = "Optimized" if "optimized" in str(self.is_replay).lower() else "Original"
                # Find original turn ID (similar logic as in run method)
                original_turn_id = "..."
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                if session_data and isinstance(session_data.get("last_turn_data", {}).get("workflow_history"), list):
                    for idx, turn in enumerate(session_data["last_turn_data"]["workflow_history"]):
                        if turn.get("original_plan") == self.plan_to_execute: # Compare against the plan being replayed
                            original_turn_id = str(idx + 1)
                            break
                replay_prefix = f"🔄 Replay ({replay_type_text} from Turn {original_turn_id}): "
            # --- MODIFICATION END ---


            if is_delegated_prompt_phase:
                prompt_name = current_phase.get('executable_prompt')
                prompt_args = current_phase.get('arguments', {})
                
                # Safeguard: Skip if prompt_name is None or empty (shouldn't happen after planner cleanup, but defensive)
                if not prompt_name or prompt_name in ['None', 'null', '']:
                    app_logger.warning(f"Skipping delegated prompt phase with invalid prompt_name: '{prompt_name}'. Phase: {current_phase}")
                    error_event = {
                        "step": "Plan Optimization",
                        "details": f"Skipping invalid prompt execution step. The plan phase contained an unusable prompt reference.",
                        "type": "workaround"
                    }
                    self._log_system_event(error_event)
                    yield self._format_sse(error_event)
                    self.current_phase_index += 1
                    continue
                
                # Send phase_start event for delegated prompt phases
                phase_num = current_phase.get("phase", self.current_phase_index + 1)
                phase_goal = current_phase.get("goal", "No goal defined.")
                event_data = {
                    "step": f"Starting Plan Phase {phase_num}/{len(self.meta_plan)}",
                    "type": "phase_start",
                    "details": {
                        "phase_num": phase_num,
                        "total_phases": len(self.meta_plan),
                        "goal": phase_goal,
                        "phase_details": current_phase,
                        "execution_depth": self.execution_depth
                    }
                }
                self._log_system_event(event_data)
                yield self._format_sse(event_data)
                
                async for event in self._run_sub_prompt(prompt_name, prompt_args):
                    yield event
                
                # Send phase_end event after sub-prompt completes
                event_data = {
                    "step": f"Ending Plan Phase {phase_num}/{len(self.meta_plan)}",
                    "type": "phase_end",
                    "details": {"phase_num": phase_num, "total_phases": len(self.meta_plan), "status": "completed"}
                }
                self._log_system_event(event_data)
                yield self._format_sse(event_data)
            else:
                # --- MODIFICATION START: Pass replay prefix conceptually ---
                # PhaseExecutor needs modification to accept and use this prefix
                # For now, just logging it here. Actual prefixing requires PhaseExecutor changes.
                if replay_prefix:
                    app_logger.debug(f"Passing replay prefix to PhaseExecutor: '{replay_prefix}'")
                async for event in phase_executor.execute_phase(current_phase): # Assuming execute_phase will handle the prefix internally
                    yield event
                # --- MODIFICATION END ---

            self.current_phase_index += 1

        app_logger.debug("Meta-plan has been fully executed. Transitioning to summarization.")
        self.state = self.AgentState.SUMMARIZING

    async def _run_sub_prompt(self, prompt_name: str, prompt_args: dict, is_delegated_task: bool = False):
        """
        Creates and runs a sub-executor for a delegated prompt, adopting its
        final state upon completion to ensure a continuous and complete workflow.
        """
        # Safety check: Don't execute if prompt_name is invalid (final defensive layer)
        if not prompt_name or prompt_name in ['None', 'null', '']:
            error_event = {
                "step": "Plan Optimization",
                "details": f"Skipping execution of invalid prompt reference. The system prevented an error.",
                "type": "workaround"
            }
            self._log_system_event(error_event)
            yield self._format_sse(error_event)
            app_logger.error(f"Attempted to run sub-prompt with invalid name: '{prompt_name}'")
            return
        
        event_data = {
            "step": "Prompt Execution Granted",
            "details": f"Executing prompt '{prompt_name}' as part of the plan.",
            "type": "workaround"
        }
        self._log_system_event(event_data)
        yield self._format_sse(event_data)

        force_disable_sub_history = is_delegated_task
        if force_disable_sub_history:
            app_logger.info(f"Token Optimization: Disabling history for delegated recovery task '{prompt_name}'.")

        sub_executor = PlanExecutor(
            session_id=self.session_id,
            user_uuid=self.user_uuid,
            original_user_input=f"Executing prompt: {prompt_name}",
            dependencies=self.dependencies,
            active_prompt_name=prompt_name,
            prompt_arguments=prompt_args,
            execution_depth=self.execution_depth + 1,
            disabled_history=self.disabled_history or force_disable_sub_history,
            previous_turn_data=self.previous_turn_data,
            source="prompt_library",
            is_delegated_task=is_delegated_task,
            force_final_summary=APP_CONFIG.SUB_PROMPT_FORCE_SUMMARY,
            event_handler=self.event_handler
        )

        sub_executor.workflow_state = self.workflow_state
        sub_executor.structured_collected_data = self.structured_collected_data



        async for event in sub_executor.run():
            yield event

        self.structured_collected_data = sub_executor.structured_collected_data
        self.workflow_state = sub_executor.workflow_state
        
        # --- MODIFICATION START: Append sub-trace, don't overwrite ---
        if sub_executor.turn_action_history:
            self.turn_action_history.extend(sub_executor.turn_action_history)
        # --- MODIFICATION END ---
            
        self.last_tool_output = sub_executor.last_tool_output
        


        if sub_executor.state == self.AgentState.ERROR:
            app_logger.error(f"Sub-executor for prompt '{prompt_name}' failed.")
            if not self.last_tool_output or self.last_tool_output.get("status") != "error":
                self.last_tool_output = {"status": "error", "error_message": f"Sub-prompt '{prompt_name}' failed."}
        else:
             if self.last_tool_output is None:
                self.last_tool_output = {"status": "success"}

    async def _run_delegated_prompt(self):
        """
        Executes a single, delegated prompt by immediately expanding it into a
        concrete plan. This is used for sub-executors created during
        self-correction to avoid redundant planning and recursion.
        """
        if not self.active_prompt_name:
            app_logger.error("Delegated task started without an active_prompt_name.")
            self.state = self.AgentState.ERROR
            return

        # --- MODIFICATION START: Pass RAG retriever instance to Planner ---
        planner = Planner(self, rag_retriever_instance=self.rag_retriever)
        # --- MODIFICATION END ---
        app_logger.info(f"Delegated task: Directly expanding prompt '{self.active_prompt_name}' into a concrete plan.")

        async for event in planner.generate_and_refine_plan():
            yield event
        # --- MODIFICATION START: Store plan for history even in delegated ---
        # Ensure the plan generated for the delegated task is also stored
        self.original_plan_for_history = copy.deepcopy(self.meta_plan)
        app_logger.info("Stored delegated prompt plan for history.")
        # --- MODIFICATION END ---


        self.state = self.AgentState.EXECUTING
        async for event in self._run_plan():
            yield event

    async def _handle_summarization(self, final_answer_override: str | None):
        """Orchestrates the final summarization and answer formatting."""
        final_content = None

        # Summarization logic remains largely the same
        if self.is_synthesis_from_history:
            app_logger.info("Bypassing summarization. Using direct synthesized answer from planner.")
            synthesized_answer = "Could not extract synthesized answer."
            if self.last_tool_output and isinstance(self.last_tool_output.get("results"), list) and self.last_tool_output["results"]:
                synthesized_answer = self.last_tool_output["results"][0].get("response", synthesized_answer)
            final_content = CanonicalResponse(direct_answer=synthesized_answer)
        elif self.execution_depth > 0 and not self.force_final_summary:
            app_logger.info(f"Sub-planner (depth {self.execution_depth}) completed. Bypassing final summary.")
            self.state = self.AgentState.DONE
        elif final_answer_override:
            final_content = CanonicalResponse(direct_answer=final_answer_override)
        elif self.is_conversational_plan:
            response_text = self.temp_data_holder or "I'm sorry, I don't have a response for that."
            final_content = CanonicalResponse(direct_answer=response_text)
        elif self.last_tool_output and self.last_tool_output.get("status") == "success":
            results = self.last_tool_output.get("results", [{}])
            if not results:
                final_content = CanonicalResponse(direct_answer="The agent has completed its work, but the final step produced no data.")
            else:
                last_result = results[0]
                tool_name = self.last_tool_output.get("metadata", {}).get("tool_name")

                if self.active_prompt_name and tool_name == "TDA_ComplexPromptReport":
                    final_content = PromptReportResponse.model_validate(last_result)
                elif tool_name == "TDA_FinalReport":
                    final_content = CanonicalResponse.model_validate(last_result)
                else:
                    final_content = CanonicalResponse(direct_answer="The agent has completed its work, but a final report was not generated.")
        else:
            final_content = CanonicalResponse(direct_answer="The agent has completed its work, but an issue occurred in the final step.")

        if final_content:
            async for event in self._format_and_yield_final_answer(final_content):
                yield event
            self.state = self.AgentState.DONE

    async def _format_and_yield_final_answer(self, final_content: CanonicalResponse | PromptReportResponse):
        """
        Formats a raw summary string OR a CanonicalResponse object and yields
        the final SSE event to the UI. Also saves the final HTML to session history.
        Includes the turn number in the final event payload.
        """
        formatter_kwargs = {
            "collected_data": self.structured_collected_data,
            "original_user_input": self.original_user_input,
            "active_prompt_name": self.active_prompt_name
        }
        if isinstance(final_content, PromptReportResponse):
            formatter_kwargs["prompt_report_response"] = final_content
        else:
            formatter_kwargs["canonical_response"] = final_content

        formatter = OutputFormatter(**formatter_kwargs)
        final_html, tts_payload = formatter.render()

        # --- MODIFICATION START: Decouple UI and LLM history ---
        # First, determine the clean text summary for the LLM
        clean_summary_for_llm = "The agent has completed its work."
        if hasattr(final_content, 'direct_answer'):
            clean_summary_for_llm = final_content.direct_answer
        elif hasattr(final_content, 'executive_summary'):
            clean_summary_for_llm = final_content.executive_summary
        
        # Store this clean summary in self.final_summary_text *before* saving
        self.final_summary_text = clean_summary_for_llm

        # Now, save both versions to their respective histories
        await session_manager.add_message_to_histories(
            self.user_uuid,
            self.session_id,
            'assistant',
            content=self.final_summary_text, # Clean text for LLM's chat_object
            html_content=final_html          # Rich HTML for UI's session_history
        )
        # --- MODIFICATION END ---

        # The clean summary is already in self.final_summary_text
        event_data = {"step": "LLM has generated the final answer", "details": self.final_summary_text}
        self._log_system_event(event_data, "llm_thought")
        yield self._format_sse(event_data, "llm_thought")

        # --- MODIFICATION START: Include both HTML and clean text in response ---
        yield self._format_sse({
            "final_answer": final_html,
            "final_answer_text": self.final_summary_text,  # Clean text for LLM consumption
            "tts_payload": tts_payload,
            "source": self.source,
            "turn_id": self.current_turn_number, # Use the authoritative instance variable
            # Raw execution data for API consumers
            "execution_trace": self.turn_action_history,
            "collected_data": self.structured_collected_data,
            "turn_input_tokens": self.turn_input_tokens,
            "turn_output_tokens": self.turn_output_tokens
        }, "final_answer")
        # --- MODIFICATION END ---