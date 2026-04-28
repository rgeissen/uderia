"""
Optimize Engine — tool_enabled profile execution.

Full Planner/Executor pipeline for tool_enabled (Optimize / @OPTIM) profiles.
Handles profile override setup, strategic planning, tactical execution,
self-correction, and turn persistence.

Profile type:  ``tool_enabled``  (IFOC label: "Optimize", colour: orange)

This engine is registered with EngineRegistry so it can be resolved via:
    EngineRegistry.resolve(profile)   # returns OptimizeEngine class
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncGenerator

from .registry import EngineRegistry
from .base import ExecutionEngine

if TYPE_CHECKING:
    from trusted_data_agent.agent.executor import PlanExecutor

app_logger = logging.getLogger("quart.app")


@EngineRegistry.register
class OptimizeEngine(ExecutionEngine):
    """Full Planner/Executor pipeline for ``tool_enabled`` profiles."""

    profile_type = "tool_enabled"

    async def run(self, executor: "PlanExecutor") -> AsyncGenerator[str, None]:  # type: ignore[override]
        """Execute a full Planner/Executor pipeline turn.

        Extracted from PlanExecutor.run() tool_enabled block (lines 3032–4116).
        All state is accessed via the ``executor`` parameter.
        """
        # --- Local imports (all names used by the original block) ---
        from trusted_data_agent.core.config import (
            APP_CONFIG, APP_STATE,
            get_user_provider, get_user_model,
            set_user_provider, set_user_model,
            set_user_aws_region, set_user_azure_deployment_details,
            set_user_friendli_details, set_user_model_provider_in_profile,
        )
        from trusted_data_agent.core import session_manager
        from trusted_data_agent.agent.planner import Planner
        from trusted_data_agent.agent.executor import (
            rebuild_tools_and_prompts_context,
            unwrap_exception,
            DefinitiveToolError,
        )

        # --- MODIFICATION START: Setup temporary profile override if requested ---
        temp_llm_instance = None
        temp_mcp_client = None

        # Debug log to verify profile_override_id is being passed
        if executor.profile_override_id:
            app_logger.debug(f"Profile override detected: {executor.profile_override_id}")
        else:
            app_logger.info(f"ℹ️  No profile override - using default profile configuration")
            # Set effective MCP server ID to the default (for RAG storage)
            executor.effective_mcp_server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID

        if executor.profile_override_id:
            try:
                from trusted_data_agent.core.config_manager import get_config_manager
                from langchain_mcp_adapters.client import MultiServerMCPClient
                import boto3

                config_manager = get_config_manager()
                profiles = config_manager.get_profiles(executor.user_uuid)
                override_profile = next((p for p in profiles if p.get("id") == executor.profile_override_id), None)

                if not override_profile:
                    app_logger.warning(f"Profile override ID {executor.profile_override_id} not found. Using default profile.")
                else:
                    # Store original state BEFORE logging (to capture default profile info)
                    executor.original_llm = APP_STATE.get('llm')
                    executor.original_mcp_tools = APP_STATE.get('mcp_tools')
                    executor.original_mcp_prompts = APP_STATE.get('mcp_prompts')
                    executor.original_structured_tools = APP_STATE.get('structured_tools')
                    executor.original_structured_prompts = APP_STATE.get('structured_prompts')
                    executor.original_provider = get_user_provider(executor.user_uuid)
                    executor.original_model = get_user_model(executor.user_uuid)

                    # Save provider-specific details
                    if executor.original_provider == "Friendli":
                        executor.original_provider_details['friendli'] = getattr(APP_CONFIG, 'CURRENT_FRIENDLI_DETAILS', None)
                    elif executor.original_provider == "Azure":
                        executor.original_provider_details['azure'] = getattr(APP_CONFIG, 'CURRENT_AZURE_DEPLOYMENT_DETAILS', None)
                    elif executor.original_provider == "Amazon":
                        executor.original_provider_details['aws_region'] = getattr(APP_CONFIG, 'CURRENT_AWS_REGION', None)
                        executor.original_provider_details['aws_model_provider'] = getattr(APP_CONFIG, 'CURRENT_MODEL_PROVIDER_IN_PROFILE', None)
                    original_provider = executor.original_provider
                    original_model = executor.original_model

                    app_logger.info(f"Profile override: {original_provider}/{original_model} -> @{override_profile.get('tag', 'N/A')} ({override_profile.get('name', 'Unknown')})")

                    # Get override profile's LLM configuration
                    override_llm_config_id = override_profile.get('llmConfigurationId')
                    if override_llm_config_id:
                        # CRITICAL: Pass user_uuid to get user's updated LLM configs (not bootstrap defaults)
                        llm_configs = config_manager.get_llm_configurations(executor.user_uuid)
                        override_llm_config = next((cfg for cfg in llm_configs if cfg['id'] == override_llm_config_id), None)

                        if override_llm_config:
                            provider = override_llm_config.get('provider')
                            model = override_llm_config.get('model')
                            credentials = override_llm_config.get('credentials', {})

                            app_logger.debug(f"Creating temporary LLM instance: {provider}/{model} (config: {override_llm_config_id})")

                            # Load stored credentials from encrypted database (authentication always enabled)
                            from trusted_data_agent.auth.models import User
                            from trusted_data_agent.auth.database import get_db_session
                            from trusted_data_agent.core.configuration_service import retrieve_credentials_for_provider

                            try:
                                # Get user_id from database using user_uuid (not from request context)
                                with get_db_session() as session:
                                    user = session.query(User).filter_by(id=executor.user_uuid).first()
                                    if user:
                                        stored_result = await retrieve_credentials_for_provider(user.id, provider)
                                        if stored_result.get("credentials"):
                                            credentials = {**stored_result["credentials"], **credentials}
                                        else:
                                            app_logger.warning(f"No stored credentials found for {provider} (status: {stored_result.get('status')})")
                                    else:
                                        app_logger.warning(f"User not found for uuid {executor.user_uuid}, cannot load stored credentials")
                            except Exception as e:
                                app_logger.error(f"Error loading stored credentials: {e}", exc_info=True)

                            # Create temporary LLM instance using shared factory (pooled)
                            from trusted_data_agent.llm.client_factory import get_or_create_llm_client, get_provider_config_details

                            try:
                                temp_llm_instance = await get_or_create_llm_client(provider, model, credentials)

                                # Only update if LLM instance was created successfully
                                # Update APP_CONFIG and executor's cached values for this turn
                                set_user_provider(provider, executor.user_uuid)
                                set_user_model(model, executor.user_uuid)
                                executor.current_provider = provider
                                executor.current_model = model

                                # Apply provider-specific configuration details
                                provider_details = get_provider_config_details(provider, model, credentials)
                                for key, value in provider_details.items():
                                    setattr(APP_CONFIG, key, value)

                                APP_STATE['llm'] = temp_llm_instance
                                app_logger.debug(f"Override LLM instance created: {provider}/{model}")
                            except Exception as llm_error:
                                app_logger.error(f"❌ Failed to create LLM instance for profile override: {llm_error}")
                                app_logger.error(f"   Provider: {provider}, Model: {model}")
                                app_logger.error(f"   Credentials present: {bool(credentials)}")
                                app_logger.error(f"   Continuing with default profile")
                                raise  # Re-raise to trigger outer exception handler

                    # Get override profile's MCP server configuration
                    override_mcp_server_id = override_profile.get('mcpServerId')
                    override_profile_type = override_profile.get("profile_type", "tool_enabled")

                    app_logger.debug(f"Override MCP setup: type={override_profile_type}, server={override_mcp_server_id}")

                    override_use_mcp_tools = override_profile.get("useMcpTools", False)
                    if override_profile_type == "llm_only" and not override_use_mcp_tools:
                        # Pure LLM-only profile (no tool calling): Skip MCP setup entirely
                        app_logger.info(f"🗨️ Pure LLM-only profile (no useMcpTools) - skipping MCP")
                    elif override_mcp_server_id:
                        # CRITICAL: Pass user_uuid to load user's config from database, not bootstrap template
                        mcp_servers = config_manager.get_mcp_servers(executor.user_uuid)
                        override_mcp_server = next((srv for srv in mcp_servers if srv['id'] == override_mcp_server_id), None)

                        if override_mcp_server:
                            server_name = override_mcp_server.get('name')  # For logging only

                            # Check transport type
                            transport_config = override_mcp_server.get('transport', {})
                            transport_type = transport_config.get('type', 'http')  # Default to HTTP for backwards compat

                            app_logger.debug(f"Creating temporary MCP client: {server_name} ({transport_type})")

                            if transport_type == 'stdio':
                                # STDIO transport: use command/args from transport config
                                command = transport_config.get('command')
                                args = transport_config.get('args', [])
                                env = transport_config.get('env', {})

                                # CRITICAL: Use server ID as key, not name
                                # CRITICAL: Must include "transport" key for langchain_mcp_adapters
                                temp_server_configs = {
                                    override_mcp_server_id: {
                                        "transport": "stdio",
                                        "command": command,
                                        "args": args,
                                        "env": env
                                    }
                                }
                                temp_mcp_client = MultiServerMCPClient(temp_server_configs)
                            else:
                                # HTTP transport (original code path)
                                host = override_mcp_server.get('host')
                                port = override_mcp_server.get('port')
                                path = override_mcp_server.get('path')

                                mcp_server_url = f"http://{host}:{port}{path}"
                                # CRITICAL: Use server ID as key, not name
                                temp_server_configs = {override_mcp_server_id: {"url": mcp_server_url, "transport": "streamable_http"}}
                                temp_mcp_client = MultiServerMCPClient(temp_server_configs)

                            # CRITICAL: Track the override MCP server ID for RAG case storage
                            executor.effective_mcp_server_id = override_mcp_server_id

                            # Load and process tools AND prompts using the same method as configuration_service
                            from langchain_mcp_adapters.tools import load_mcp_tools
                            from trusted_data_agent.mcp_adapter.adapter import CLIENT_SIDE_TOOLS
                            loaded_override_prompts = []
                            async with temp_mcp_client.session(override_mcp_server_id) as session:
                                all_processed_tools = await load_mcp_tools(session)
                                # Also load prompts from the override MCP server
                                try:
                                    list_prompts_result = await session.list_prompts()
                                    if hasattr(list_prompts_result, 'prompts'):
                                        loaded_override_prompts = list_prompts_result.prompts
                                except Exception as e:
                                    app_logger.warning(f"   Failed to load prompts from override MCP server: {e}")

                            # CRITICAL FIX: Add CLIENT_SIDE_TOOLS to all_processed_tools
                            # load_mcp_tools only loads server tools, but CLIENT_SIDE_TOOLS (TDA_FinalReport, etc.)
                            # are core system tools that must always be available for FASTPATH optimization
                            class SimpleTool:
                                def __init__(self, **kwargs):
                                    self.__dict__.update(kwargs)

                            for tool_def in CLIENT_SIDE_TOOLS:
                                all_processed_tools.append(SimpleTool(**tool_def))

                            app_logger.debug(f"Loaded {len(all_processed_tools)} tools (MCP + {len(CLIENT_SIDE_TOOLS)} client-side)")

                            # Get enabled tool and prompt names for this profile
                            # CRITICAL: Must pass user_uuid to load user-specific profile config (not bootstrap template)
                            enabled_tool_names = set(config_manager.get_profile_enabled_tools(executor.profile_override_id, executor.user_uuid))
                            enabled_prompt_names = set(config_manager.get_profile_enabled_prompts(executor.profile_override_id, executor.user_uuid))

                            # CRITICAL FIX: Handle wildcard "*" in enabled_tool_names
                            # If profile has tools: ["*"], expand to include ALL tool names from MCP server
                            # The wildcard means "all tools" - ignore disabled flags in classification_results
                            if "*" in enabled_tool_names:
                                # Expand wildcard to all available tool names (including TDA_ tools)
                                enabled_tool_names = {tool.name for tool in all_processed_tools}
                                app_logger.info(f"   Wildcard '*' expanded to {len(enabled_tool_names)} tools from MCP server")

                            # Same for prompts
                            if "*" in enabled_prompt_names:
                                if loaded_override_prompts:
                                    enabled_prompt_names = {p.name for p in loaded_override_prompts}
                                elif executor.original_mcp_prompts:
                                    enabled_prompt_names = set(executor.original_mcp_prompts.keys())
                                app_logger.info(f"   Wildcard '*' expanded to {len(enabled_prompt_names)} prompts")

                            # Filter to only enabled tools (prompts handled separately via original structure)
                            # CRITICAL FIX: Always include TDA client-side tools (reporting, synthesis) regardless of profile filtering
                            # These are core system tools, not MCP server tools, and must always be available for FASTPATH optimization
                            TDA_CORE_TOOLS = {"TDA_FinalReport", "TDA_ComplexPromptReport", "TDA_ContextReport", "TDA_LLMTask", "TDA_LLMFilter", "TDA_CurrentDate", "TDA_DateRange"}
                            filtered_tools = [tool for tool in all_processed_tools if tool.name in enabled_tool_names or tool.name in TDA_CORE_TOOLS]

                            # Convert to dictionary with tool names as keys (matching normal structure)
                            filtered_tools_dict = {tool.name: tool for tool in filtered_tools}

                            # Build mcp_prompts from override MCP server's loaded prompts (not from original)
                            # The original mcp_prompts may be empty if the default profile didn't load MCP
                            if loaded_override_prompts:
                                all_override_prompts_dict = {p.name: p for p in loaded_override_prompts}
                                filtered_prompts_dict = {name: prompt for name, prompt in all_override_prompts_dict.items()
                                                        if name in enabled_prompt_names}
                            else:
                                # Fallback to original if MCP prompt loading failed
                                filtered_prompts_dict = {name: prompt for name, prompt in (executor.original_mcp_prompts or {}).items()
                                                        if name in enabled_prompt_names}

                            # CRITICAL FIX: Build structured_tools from scratch for the override MCP server
                            # We can't filter original_structured_tools because it's from a DIFFERENT MCP server!
                            # The override profile uses "time" MCP server, not the default "Teradata MCP" server
                            filtered_structured_tools = {}

                            # Get classification results from override profile to determine categories
                            classification_results = override_profile.get("classification_results", {})
                            classified_tools = classification_results.get("tools", {})

                            if classified_tools:
                                # Use classification categories from profile
                                for category, tools_list in classified_tools.items():
                                    filtered_category_tools = []
                                    for tool_info in tools_list:
                                        tool_name = tool_info.get("name")
                                        # Include if tool is in our enabled set AND was successfully loaded from MCP
                                        if tool_name in enabled_tool_names and tool_name in filtered_tools_dict:
                                            filtered_category_tools.append({
                                                "name": tool_name,
                                                "description": tool_info.get("description", ""),
                                                "arguments": tool_info.get("arguments", []),
                                                "disabled": False  # Always enable since it's in enabled_tool_names
                                            })
                                    if filtered_category_tools:
                                        filtered_structured_tools[category] = filtered_category_tools
                            else:
                                # Fallback: create a single "All Tools" category
                                all_tools_category = []
                                for tool in filtered_tools:
                                    all_tools_category.append({
                                        "name": tool.name,
                                        "description": tool.description or "",
                                        "arguments": [],
                                        "disabled": False
                                    })
                                if all_tools_category:
                                    filtered_structured_tools["All Tools"] = all_tools_category

                            # CRITICAL FIX: Inject TDA_* client-side tools into structured_tools.
                            # These tools are in filtered_tools_dict (protected by TDA_CORE_TOOLS)
                            # but NOT in classification_results (they're not MCP server tools).
                            # Without this, TDA_* tools appear deactivated in the resource panel
                            # and invisible to the planner during profile overrides.
                            from trusted_data_agent.mcp_adapter.adapter import CLIENT_SIDE_TOOLS
                            system_tools_category = []
                            for tool_def in CLIENT_SIDE_TOOLS:
                                tool_name_cs = tool_def["name"]
                                if tool_name_cs in filtered_tools_dict:
                                    processed_args = []
                                    for arg_name, arg_details in tool_def.get("args", {}).items():
                                        if isinstance(arg_details, dict):
                                            processed_args.append({
                                                "name": arg_name,
                                                "type": arg_details.get("type", "any"),
                                                "description": arg_details.get("description", "No description."),
                                                "required": arg_details.get("required", False)
                                            })
                                    system_tools_category.append({
                                        "name": tool_name_cs,
                                        "description": tool_def.get("description", ""),
                                        "arguments": processed_args,
                                        "disabled": False
                                    })
                            if system_tools_category:
                                filtered_structured_tools["System Tools"] = system_tools_category

                            app_logger.info(f"   Built structured_tools from override MCP server: {len(filtered_structured_tools)} categories")

                            # Rebuild structured_prompts from override MCP server (not from original)
                            # CRITICAL FIX: Prioritize freshly loaded prompts over potentially stale classification
                            # Classification results may be incomplete or outdated, causing prompt lookup failures
                            filtered_structured_prompts = {}
                            classified_prompts = classification_results.get("prompts", {})

                            if loaded_override_prompts:
                                # FIXED: Include ALL prompts (enabled and disabled) so they can be executed from resource panel
                                # Deactivated prompts should still be executable via resource panel, just not used in regular conversation
                                from trusted_data_agent.mcp_adapter.adapter import _extract_prompt_type_from_description
                                all_prompts_category = []
                                for prompt_obj in loaded_override_prompts:
                                    # Include ALL prompts, mark as disabled if not in enabled list
                                    is_disabled = prompt_obj.name not in enabled_prompt_names
                                    cleaned_desc, prompt_type = _extract_prompt_type_from_description(prompt_obj.description)
                                    processed_args = []
                                    if hasattr(prompt_obj, 'arguments') and prompt_obj.arguments:
                                        for arg in prompt_obj.arguments:
                                            arg_dict = arg.model_dump()
                                            processed_args.append(arg_dict)
                                    all_prompts_category.append({
                                        "name": prompt_obj.name,
                                        "description": cleaned_desc or "No description available.",
                                        "arguments": processed_args,
                                        "disabled": is_disabled,
                                        "prompt_type": prompt_type
                                    })
                                if all_prompts_category:
                                    filtered_structured_prompts["All Prompts"] = all_prompts_category
                            elif classified_prompts:
                                # Fallback: use classification categories from profile if MCP loading failed
                                # Include ALL prompts, mark disabled flag appropriately
                                for category, prompts_list in classified_prompts.items():
                                    category_prompts = []
                                    for prompt_info in prompts_list:
                                        prompt_copy = dict(prompt_info)
                                        prompt_copy['disabled'] = prompt_info.get('name') not in enabled_prompt_names
                                        category_prompts.append(prompt_copy)
                                    if category_prompts:
                                        filtered_structured_prompts[category] = category_prompts
                            else:
                                # Last resort: use original prompts (mark disabled flag appropriately)
                                for category, prompts_list in (executor.original_structured_prompts or {}).items():
                                    category_prompts = []
                                    for prompt_info in prompts_list:
                                        prompt_copy = dict(prompt_info)
                                        prompt_copy['disabled'] = prompt_info.get('name') not in enabled_prompt_names
                                        category_prompts.append(prompt_copy)
                                    if category_prompts:
                                        filtered_structured_prompts[category] = category_prompts

                            # CRITICAL FIX: Update current_server_id_by_user for tool execution
                            # The mcp_adapter uses get_user_mcp_server_id() which reads this dict
                            # Save original for restoration
                            current_server_id_by_user = APP_STATE.setdefault("current_server_id_by_user", {})
                            executor.original_server_id = current_server_id_by_user.get(executor.user_uuid)
                            current_server_id_by_user[executor.user_uuid] = override_mcp_server_id

                            APP_STATE['mcp_client'] = temp_mcp_client
                            APP_STATE['mcp_tools'] = filtered_tools_dict
                            APP_STATE['mcp_prompts'] = filtered_prompts_dict
                            APP_STATE['structured_tools'] = filtered_structured_tools
                            APP_STATE['structured_prompts'] = filtered_structured_prompts

                            # CRITICAL FIX: Rebuild tools_context and prompts_context after filtering
                            # The planner uses these context strings to show the LLM available tools/prompts
                            # Without this rebuild, the LLM sees the OLD/DEFAULT tools, not the override profile's tools
                            tools_context, prompts_context = rebuild_tools_and_prompts_context()
                            APP_STATE['tools_context'] = tools_context
                            APP_STATE['prompts_context'] = prompts_context

                            app_logger.info(f"Profile override applied: {len(filtered_tools_dict)} tools, {len(filtered_prompts_dict)} prompts")
                        else:
                            app_logger.warning(f"❌ MCP server {override_mcp_server_id} not found in config!")
                            app_logger.warning(f"   Profile override will continue with LLM only (no tools)")
                    elif not override_mcp_server_id:
                        app_logger.info(f"ℹ️  Profile has no MCP server configured - LLM only mode")

            except Exception as e:
                app_logger.error(f"Failed to apply profile override: {e}", exc_info=True)

                # CRITICAL: Restore original LLM instance before continuing
                # If profile override LLM creation failed, APP_STATE['llm'] may be None
                # Restore it to the original LLM instance so execution can continue
                if executor.original_llm is not None:
                    APP_STATE['llm'] = executor.original_llm
                    app_logger.info(f"Restored original LLM after profile override failure")
                else:
                    app_logger.error(f"❌ Cannot restore LLM - original LLM was None (default profile may not be configured)")

                # CRITICAL: Restore original provider/model before they get saved to session
                # The override attempt may have changed executor.current_provider and executor.current_model
                # but since it failed, we need to restore them to the original values
                if executor.original_provider and executor.original_model:
                    app_logger.info(f"🔄 Restoring provider/model from {executor.current_provider}/{executor.current_model} to {executor.original_provider}/{executor.original_model}")
                    executor.current_provider = executor.original_provider
                    executor.current_model = executor.original_model
                    set_user_provider(executor.original_provider, executor.user_uuid)
                    set_user_model(executor.original_model, executor.user_uuid)

                # Send warning banner notification to user via SSE
                from trusted_data_agent.core.config_manager import get_config_manager
                config_manager = get_config_manager()
                override_profile = None
                if executor.profile_override_id:
                    profiles = config_manager.get_profiles(executor.user_uuid)
                    override_profile = next((p for p in profiles if p.get("id") == executor.profile_override_id), None)

                # Get default profile tag for notification
                default_profile_tag = executor._get_active_profile_tag()

                # Clear profile_override_id NOW so subsequent calls use default profile
                app_logger.info(f"🔄 Clearing profile_override_id to use default profile tag: {default_profile_tag}")
                executor.profile_override_id = None

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
                    app_logger.debug(f"Sending profile_override_failed notification")
                    yield executor._format_sse_with_depth(notification_data, event="notification")

                # Continue with default profile if override fails
                # Note: Do NOT call update_models_used here - it will be called below with the restored default values
        # --- MODIFICATION END ---

        # Update session with correct provider/model/profile_tag at the start of execution
        # This ensures the session data is correct before any LLM calls
        profile_tag = executor._get_current_profile_tag()
        await session_manager.update_models_used(executor.user_uuid, executor.session_id, executor.current_provider, executor.current_model, profile_tag)

        # Send immediate SSE notification so UI updates in real-time
        session_data = await session_manager.get_session(executor.user_uuid, executor.session_id)
        if session_data:
            # Include dual-model info if active
            dual_model_info = None
            if session_data.get("is_dual_model_active"):
                dual_model_info = {
                    "strategicProvider": session_data.get("strategic_provider"),
                    "strategicModel": session_data.get("strategic_model"),
                    "tacticalProvider": session_data.get("tactical_provider"),
                    "tacticalModel": session_data.get("tactical_model")
                }

            notification_payload = {
                "session_id": executor.session_id,
                "models_used": session_data.get("models_used", []),
                "profile_tags_used": session_data.get("profile_tags_used", []),
                "last_updated": session_data.get("last_updated"),
                "provider": executor.current_provider,
                "model": executor.current_model,
                "name": session_data.get("name", "Unnamed Session"),
                "dual_model_info": dual_model_info
            }
            app_logger.debug(f"Sending session_model_update: {notification_payload['provider']}/{notification_payload['model']}")
            yield executor._format_sse_with_depth({
                "type": "session_model_update",
                "payload": notification_payload
            }, event="notification")
        else:
            app_logger.warning(f"Could not send session_model_update - session_data is None for {executor.session_id}")

        # Check for cancellation before starting execution
        executor._check_cancellation()

        # --- PHASE 2: Emit execution_start lifecycle event for tool_enabled ---
        # Initialize event collection array (similar to knowledge_events for RAG)
        # Events are: 1) Yielded as SSE for live UI updates, 2) Collected for session persistence, 3) Replayed during historical turn reload
        executor.tool_enabled_events = []

        try:
            start_event_payload = {
                "profile_type": "tool_enabled",
                "profile_tag": profile_tag,
                "query": executor.original_user_input,
                "has_context": bool(executor.previous_turn_data),
                "is_replay": bool(executor.plan_to_execute)
            }

            start_event = executor._emit_lifecycle_event("execution_start", start_event_payload)
            yield start_event

            # Collect event for persistence (matches pattern from RAG/Genie profiles)
            executor.tool_enabled_events.append({
                "type": "execution_start",
                "payload": start_event_payload,
                "metadata": {"execution_depth": executor.execution_depth}
            })

            app_logger.info("✅ Emitted execution_start event for tool_enabled profile")
        except Exception as e:
            # Silent failure - don't break execution
            app_logger.warning(f"Failed to emit execution_start event: {e}")
        # --- PHASE 2 END ---

        # Track execution start time for duration calculation (tool_enabled profiles)
        executor.tool_enabled_start_time = time.time()

        # --- Canvas bidirectional context: Prepend for tool_enabled planning ---
        canvas_ctx = executor._format_canvas_context()
        if canvas_ctx:
            executor.original_user_input = f"{canvas_ctx}\n\n{executor.original_user_input}"
            app_logger.info(f"Prepended canvas context to user input for tool_enabled planning")

        # --- Document upload: Prepend document context for tool_enabled planning ---
        # By this point, llm_only, conversation_with_tools, and rag_focused have all returned.
        # Augment original_user_input so the Planner sees document context in strategic planning.
        if executor.document_context:
            executor.original_user_input = f"[User has uploaded documents]\n{executor.document_context}\n\n[User's question]\n{executor.original_user_input}"
            app_logger.info(f"Prepended document context ({len(executor.document_context):,} chars) to user input for tool_enabled planning")

        # --- EPC: tool_enabled query_intake + profile_resolve ---
        profile_type = "tool_enabled"
        executor.provenance.add_step("query_intake", executor.original_user_input,
                                 f"Query: {executor.original_user_input[:80]}")
        profile_tag = executor._get_current_profile_tag() or "OPTIM"
        executor.provenance.add_step("profile_resolve",
                                 f"{executor.active_profile_id}:{profile_type}:{profile_tag}",
                                 f"Profile: @{profile_tag} ({profile_type})")
        # --- EPC END ---

        # local variable (replaces the outer run() local that was None when entering this block)
        final_answer_override = None

        try:
            # --- MODIFICATION START: Handle Replay ---
            if executor.plan_to_execute:
                app_logger.info(f"Starting replay execution for user {executor.user_uuid}, session {executor.session_id}.")
                executor.meta_plan = copy.deepcopy(executor.plan_to_execute) # Use the provided plan
                executor.state = executor.AgentState.EXECUTING # Skip planning
                # Inject a status event indicating replay
                replay_type_text = "Optimized" if "optimized" in str(executor.is_replay).lower() else "Original" # Basic type check
                # Find the turn ID where this plan originally came from
                original_turn_id = "..." # Default if not found
                if session_data and isinstance(session_data.get("last_turn_data", {}).get("workflow_history"), list):
                    for idx, turn in enumerate(session_data["last_turn_data"]["workflow_history"]):
                        if turn.get("original_plan") == executor.plan_to_execute:
                            original_turn_id = str(idx + 1)
                            break

                event_data = {
                    "step": f"🔄 Replaying {replay_type_text} Plan (from Turn {original_turn_id})",
                    "type": "system_message",
                    "details": f"Re-executing {'optimized' if replay_type_text == 'Optimized' else 'original'} plan..."
                }
                executor._log_system_event(event_data)
                yield executor._format_sse_with_depth(event_data)
            # --- MODIFICATION END ---
            else:
                if executor.is_delegated_task:
                    async for event in executor._run_delegated_prompt():
                        yield event
                    # _run_delegated_prompt() plans + executes via _run_plan() which
                    # sets state=SUMMARIZING, but the normal summarization phase at
                    # the bottom of run() is unreachable due to the early return.
                    # Call _handle_summarization() explicitly so the sub-executor
                    # emits execution_complete (and honours is_synthesis_from_history).
                    if executor.state == executor.AgentState.SUMMARIZING:
                        async for event in executor._handle_summarization(final_answer_override):
                            yield event
                    return # Exit early for delegated tasks

                # --- Planning Phase ---
                if executor.state == executor.AgentState.PLANNING:
                    # Check for cancellation before starting planning
                    executor._check_cancellation()

                    # --- MODIFICATION START: Pass RAG retriever instance to Planner ---
                    # Create a wrapped event handler that captures RAG collection info and knowledge retrieval
                    async def rag_aware_event_handler(data, event_name):
                        if event_name == "rag_retrieval" and data and 'collection_id' in data.get('full_case_data', {}).get('metadata', {}):
                            # Store the collection ID and case ID from the retrieved RAG case
                            executor.rag_source_collection_id = data['full_case_data']['metadata']['collection_id']
                            executor.rag_source_case_id = data.get('case_id')  # Capture case_id for feedback tracking
                            app_logger.debug(f"RAG example retrieved from collection {executor.rag_source_collection_id}, case_id: {executor.rag_source_case_id}")

                        # --- PHASE 2: Track knowledge repository access ---
                        elif event_name == "knowledge_retrieval":
                            collections = data.get("collections", [])
                            document_count = data.get("document_count", 0)

                            # Store knowledge access info for turn summary
                            for collection_name in collections:
                                executor.knowledge_accessed.append({
                                    "collection_name": collection_name,
                                    "document_count": document_count,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })

                            # Store the full event for replay when plan is reloaded
                            executor.knowledge_retrieval_event = data
                            app_logger.info(f"Tracked knowledge retrieval: {len(collections)} collection(s), {document_count} document(s)")
                            app_logger.debug(f"Stored knowledge_retrieval_event with {len(data.get('chunks', []))} chunks")
                        # --- PHASE 2 END ---

                        # --- KG ENRICHMENT: Track knowledge graph context injection ---
                        elif event_name == "kg_enrichment":
                            executor.kg_enrichment_event = data
                            app_logger.info(
                                f"Tracked KG enrichment: {data.get('total_entities', 0)} entities, "
                                f"{data.get('total_relationships', 0)} relationships"
                            )

                        # Pass through to the original event handler
                        if executor.event_handler:
                            await executor.event_handler(data, event_name)

                    planner = Planner(executor, rag_retriever_instance=executor.rag_retriever, event_handler=rag_aware_event_handler)
                    # --- MODIFICATION END ---
                    should_replan = False
                    planning_is_disabled_history = executor.disabled_history

                    replan_attempt = 0
                    max_replans = 1
                    while True:
                        replan_context = None
                        is_replan = replan_attempt > 0

                        if is_replan:
                            prompts_in_plan = {p['executable_prompt'] for p in (executor.meta_plan or []) if 'executable_prompt' in p}
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
                                    prompt_info = executor._get_prompt_info(prompt_name)
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
                                    executor.turn_action_history.append({"action": "system_correction", "result": event_data})
                                except json.JSONDecodeError:
                                    app_logger.warning(f"Could not parse planner event for history logging: {event}")
                            # --- MODIFICATION END ---
                            yield event

                        # --- MODIFICATION START: Store original plan AFTER refinement ---
                        # Store the plan that was actually generated and refined before any execution begins
                        executor.original_plan_for_history = copy.deepcopy(executor.meta_plan)
                        app_logger.debug("Stored original plan (post-refinement) for history.")
                        # --- MODIFICATION END ---

                        # --- EPC: strategic_plan step ---
                        try:
                            executor.provenance.add_step(
                                "strategic_plan",
                                json.dumps(executor.meta_plan, sort_keys=True, default=str),
                                f"Plan: {len(executor.meta_plan)} phase(s)")
                        except Exception as _epc_err:
                            app_logger.debug(f"[EPC] strategic_plan step error: {_epc_err}")
                        # --- EPC END ---

                        # --- MODIFICATION START: Inject knowledge context into workflow_state for hybrid plans ---
                        # This allows TDA_FinalReport to access both gathered data AND knowledge context
                        if hasattr(planner, '_last_knowledge_context') and planner._last_knowledge_context:
                            executor.workflow_state['_knowledge_context'] = planner._last_knowledge_context
                            app_logger.info("Injected knowledge context into workflow_state for final report access.")
                        # --- MODIFICATION END ---

                        plan_has_prompt = executor.meta_plan and any('executable_prompt' in phase for phase in executor.meta_plan)
                        replan_triggered = False
                        if plan_has_prompt:
                            prompts_in_plan = {phase['executable_prompt'] for phase in executor.meta_plan if 'executable_prompt' in phase}
                            non_granted_prompts = [p for p in prompts_in_plan if p not in APP_CONFIG.GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING]
                            has_other_significant_tool = any('executable_prompt' not in phase and phase.get('relevant_tools') != ['TDA_LLMTask'] for phase in executor.meta_plan)
                            is_single_phase_prompt = len(executor.meta_plan) == 1
                            if has_other_significant_tool and not is_single_phase_prompt and non_granted_prompts:
                                replan_triggered = True

                        if executor.execution_depth == 0 and replan_triggered and replan_attempt < max_replans:
                            replan_attempt += 1
                            event_data = {
                                "step": "Re-planning for Efficiency", "type": "plan_optimization",
                                "details": {
                                    "summary": "Initial plan uses a sub-prompt alongside other tools. Agent is re-planning to create a more efficient, tool-only workflow.",
                                    "original_plan": copy.deepcopy(executor.meta_plan) # Log the plan *before* this replan
                                }
                            }
                            executor._log_system_event(event_data)
                            yield executor._format_sse_with_depth(event_data)
                            continue # Loop back to replan
                        break # Exit planning loop

                    # Handle single prompt plan expansion (if applicable)
                    executor.is_single_prompt_plan = (executor.meta_plan and len(executor.meta_plan) == 1 and 'executable_prompt' in executor.meta_plan[0] and not executor.is_delegated_task)

                    if executor.is_single_prompt_plan:
                        async for event in executor._handle_single_prompt_plan(planner):
                            yield event
                        # --- MODIFICATION START: Re-capture plan if single prompt expansion happened ---
                        # If the plan was expanded from a single prompt, update the stored original plan
                        executor.original_plan_for_history = copy.deepcopy(executor.meta_plan)
                        app_logger.debug("Re-stored plan after single-prompt expansion for history.")
                        # --- MODIFICATION END ---


                    # Check for conversational plan
                    if executor.is_conversational_plan:
                        app_logger.info("Detected a conversational plan. Bypassing execution.")
                        executor.state = executor.AgentState.SUMMARIZING
                    else:
                        executor.state = executor.AgentState.EXECUTING

            # --- Execution Phase ---
            try:
                if executor.state == executor.AgentState.EXECUTING:
                    async for event in executor._run_plan(): yield event
            except DefinitiveToolError as e:
                app_logger.error(f"Execution halted by definitive tool error: {e.friendly_message}")
                event_data = {"step": "Unrecoverable Error", "details": e.friendly_message, "type": "error"}
                executor._log_system_event(event_data, "tool_result")
                yield executor._format_sse_with_depth(event_data, "tool_result")
                final_answer_override = f"I could not complete the request. Reason: {e.friendly_message}"
                executor.state = executor.AgentState.SUMMARIZING # Go to summarization even on error

            # --- Summarization Phase ---
            if executor.state == executor.AgentState.SUMMARIZING:
                async for event in executor._handle_summarization(final_answer_override):
                    yield event

        except asyncio.CancelledError:
            # Handle cancellation specifically
            app_logger.info(f"PlanExecutor execution cancelled for user {executor.user_uuid}, session {executor.session_id}.")
            executor.state = executor.AgentState.ERROR  # Mark as error to prevent normal history update
            # Yield a specific event to the frontend - include turn_id for badge creation
            event_data = {
                "step": "Execution Stopped",
                "details": "The process was stopped by the user.",
                "type": "cancelled",
                "turn_id": executor.current_turn_number,
                "session_id": executor.session_id
            }
            executor._log_system_event(event_data, "cancelled")
            yield executor._format_sse_with_depth(event_data, "cancelled")

            # --- PHASE 2: Emit execution_cancelled lifecycle event (all profiles) ---
            try:
                _profile_type = executor._detect_profile_type()
                # Emit for all profile types (tool_enabled, llm_only, rag_focused)
                cancelled_event = executor._emit_lifecycle_event("execution_cancelled", {
                    "profile_type": _profile_type,
                    "profile_tag": executor._get_current_profile_tag(),
                    "phases_completed": len([a for a in executor.turn_action_history if isinstance(a.get("action"), dict) and a["action"].get("tool_name") != "TDA_SystemLog"]),
                    "cancellation_stage": executor.state.name,
                    "partial_input_tokens": executor.turn_input_tokens,
                    "partial_output_tokens": executor.turn_output_tokens
                })
                yield cancelled_event
                app_logger.info(f"✅ Emitted execution_cancelled event for {_profile_type} profile")
            except Exception as e:
                # Silent failure - don't break cancellation flow
                app_logger.warning(f"Failed to emit execution_cancelled event: {e}")
            # --- PHASE 2 END ---

            # Save partial turn data before re-raising
            await executor._save_partial_turn_data(
                status="cancelled",
                error_message="Execution stopped by user",
                error_details="The user cancelled the execution before completion."
            )

            # Re-raise so the caller (routes.py) knows it was cancelled
            raise

        except Exception as e:
            # Handle other general exceptions
            root_exception = unwrap_exception(e)
            app_logger.error(f"Error in state {executor.state.name} for user {executor.user_uuid}, session {executor.session_id}: {root_exception}", exc_info=True)
            executor.state = executor.AgentState.ERROR
            event_data = {
                "error": "Execution stopped due to an unrecoverable error.",
                "details": str(root_exception),
                "step": "Unrecoverable Error",
                "type": "error",
                "turn_id": executor.current_turn_number,
                "session_id": executor.session_id
            }
            executor._log_system_event(event_data, "error")
            yield executor._format_sse_with_depth(event_data, "error")

            # --- PHASE 2: Emit execution_error lifecycle event (all profiles) ---
            try:
                _profile_type = executor._detect_profile_type()
                # Emit for all profile types (tool_enabled, llm_only, rag_focused)
                error_type = executor._classify_error(root_exception)
                error_event = executor._emit_lifecycle_event("execution_error", {
                    "profile_type": _profile_type,
                    "profile_tag": executor._get_current_profile_tag(),
                    "error_message": str(root_exception),
                    "error_type": error_type,
                    "error_stage": executor.state.name,
                    "phases_completed": len([a for a in executor.turn_action_history if isinstance(a.get("action"), dict) and a["action"].get("tool_name") != "TDA_SystemLog"]),
                    "partial_input_tokens": executor.turn_input_tokens,
                    "partial_output_tokens": executor.turn_output_tokens,
                    "success": False
                })
                yield error_event
                app_logger.info(f"✅ Emitted execution_error event for {_profile_type} profile (error_type: {error_type})")
            except Exception as e:
                # Silent failure - don't break error handling flow
                app_logger.warning(f"Failed to emit execution_error event: {e}")
            # --- PHASE 2 END ---

            # Save partial turn data for error case
            await executor._save_partial_turn_data(
                status="error",
                error_message="Execution stopped due to an unrecoverable error.",
                error_details=str(root_exception)
            )

        finally:
            # --- MODIFICATION START: Restore original MCP/LLM state if profile was overridden ---
            if executor.profile_override_id:
                try:
                    from trusted_data_agent.core.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    default_profile_id = config_manager.get_default_profile_id(executor.user_uuid)
                    default_profile_name = "Default Profile"
                    if default_profile_id:
                        profiles = config_manager.get_profiles(executor.user_uuid)
                        default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
                        if default_profile:
                            default_profile_name = f"{default_profile.get('name')} (Tag: @{default_profile.get('tag', 'N/A')})"

                    app_logger.info(f"Reverting to default profile: {default_profile_name}")

                    if executor.original_llm is not None:
                        APP_STATE['llm'] = executor.original_llm
                        if executor.original_provider:
                            set_user_provider(executor.original_provider, executor.user_uuid)
                        if executor.original_model:
                            set_user_model(executor.original_model, executor.user_uuid)

                        # Restore provider-specific details
                        if executor.original_provider == "Friendli" and 'friendli' in executor.original_provider_details:
                            set_user_friendli_details(executor.original_provider_details['friendli'], executor.user_uuid)
                        elif executor.original_provider == "Azure" and 'azure' in executor.original_provider_details:
                            set_user_azure_deployment_details(executor.original_provider_details['azure'], executor.user_uuid)
                        elif executor.original_provider == "Amazon":
                            if 'aws_region' in executor.original_provider_details:
                                set_user_aws_region(executor.original_provider_details['aws_region'], executor.user_uuid)
                            if 'aws_model_provider' in executor.original_provider_details:
                                set_user_model_provider_in_profile(executor.original_provider_details['aws_model_provider'], executor.user_uuid)

                        app_logger.debug(f"Restored LLM: {executor.original_provider}/{executor.original_model}")

                    if executor.original_mcp_tools is not None:
                        APP_STATE['mcp_tools'] = executor.original_mcp_tools

                    if executor.original_mcp_prompts is not None:
                        APP_STATE['mcp_prompts'] = executor.original_mcp_prompts

                    if executor.original_structured_tools is not None:
                        APP_STATE['structured_tools'] = executor.original_structured_tools

                    if executor.original_structured_prompts is not None:
                        APP_STATE['structured_prompts'] = executor.original_structured_prompts

                    # CRITICAL FIX: Restore original current_server_id_by_user
                    # This ensures tool execution uses the correct MCP server after override
                    if executor.original_server_id is not None:
                        current_server_id_by_user = APP_STATE.setdefault("current_server_id_by_user", {})
                        current_server_id_by_user[executor.user_uuid] = executor.original_server_id

                    # CRITICAL FIX: Rebuild tools_context and prompts_context after restoring original state
                    # This ensures subsequent queries in the same session see the correct default profile tools
                    if executor.original_mcp_tools is not None or executor.original_structured_tools is not None:
                        tools_context, prompts_context = rebuild_tools_and_prompts_context()
                        APP_STATE['tools_context'] = tools_context
                        APP_STATE['prompts_context'] = prompts_context

                    # Close temporary MCP client if created
                    if temp_mcp_client:
                        try:
                            # Note: MultiServerMCPClient may not have explicit close method
                            # But context managers handle cleanup automatically
                            pass
                        except Exception as cleanup_error:
                            app_logger.warning(f"⚠️  Error closing temporary MCP client: {cleanup_error}")

                    app_logger.info(f"Reverted to default profile")

                except Exception as restore_error:
                    app_logger.error(f"❌ Error restoring original state after profile override: {restore_error}", exc_info=True)
            # --- MODIFICATION END ---

            # --- Cleanup Phase (Always runs) ---
            # --- MODIFICATION START: Only top-level executor (depth 0) saves history ---
            # Update history only if the execution wasn't cancelled, errored,
            # AND this is the top-level executor instance.
            if executor.state != executor.AgentState.ERROR and executor.execution_depth == 0:
            # --- MODIFICATION END ---
                # --- MODIFICATION START: Include model/provider and use executor.current_turn_number ---
                # Get profile tag from default profile (or override if active)
                profile_tag = executor._get_current_profile_tag()

                # Get session data for session token totals (needed for plan reload display)
                session_data = await session_manager.get_session(executor.user_uuid, executor.session_id)
                session_input_tokens = session_data.get("input_tokens", 0) if session_data else 0
                session_output_tokens = session_data.get("output_tokens", 0) if session_data else 0

                # Collect system events for plan reload (like session name generation)
                # CRITICAL: Use the collected events from session name generation (stored in executor.session_name_events)
                # These events were collected during the actual generation process and include accurate token counts
                system_events = executor.session_name_events if hasattr(executor, 'session_name_events') else []

                if system_events:
                    app_logger.debug(f"Using {len(system_events)} collected session name events for workflow history")

                # Pre-build execution_complete event for persistence BEFORE constructing turn_summary.
                # The actual SSE emission happens later (after final_answer yield), but we need
                # the event data stored in tool_enabled_events now so it's included in the saved turn.
                if hasattr(executor, 'tool_enabled_events') and hasattr(executor, 'tool_enabled_start_time'):
                    duration_ms = int((time.time() - executor.tool_enabled_start_time) * 1000)
                    # Calculate cost for persisted execution_complete (used by historical reload)
                    _pre_cost = 0
                    try:
                        from trusted_data_agent.core.cost_manager import CostManager
                        _pre_cost = CostManager().calculate_cost(
                            provider=executor.current_provider or "Unknown",
                            model=executor.current_model or "Unknown",
                            input_tokens=executor.turn_input_tokens,
                            output_tokens=executor.turn_output_tokens
                        )
                    except Exception:
                        pass
                    executor.tool_enabled_events.append({
                        "type": "execution_complete",
                        "payload": {
                            "profile_type": "tool_enabled",
                            "profile_tag": executor._get_current_profile_tag(),
                            "phases_executed": len([a for a in executor.turn_action_history if isinstance(a.get("action"), dict) and a["action"].get("tool_name") != "TDA_SystemLog"]),
                            "total_input_tokens": executor.turn_input_tokens,
                            "total_output_tokens": executor.turn_output_tokens,
                            "duration_ms": duration_ms,
                            "cost_usd": _pre_cost,
                            "success": True
                        },
                        "metadata": {"execution_depth": executor.execution_depth}
                    })

                # Calculate turn cost for persistence (fixes historical reload $0 cost bug)
                turn_cost = 0  # Default
                try:
                    from trusted_data_agent.core.cost_manager import CostManager
                    cost_manager = CostManager()
                    turn_cost = cost_manager.calculate_cost(
                        provider=executor.current_provider,
                        model=executor.current_model,
                        input_tokens=executor.turn_input_tokens,
                        output_tokens=executor.turn_output_tokens
                    )
                    app_logger.debug(f"Calculated turn cost for persistence: ${turn_cost:.6f}")
                except Exception as e:
                    app_logger.warning(f"Failed to calculate turn cost for persistence: {e}")

                # Calculate session cost (cumulative up to and including this turn)
                session_cost_usd = 0.0
                try:
                    previous_session_cost = executor._calculate_session_cost_at_turn(session_data)
                    session_cost_usd = previous_session_cost + turn_cost
                    app_logger.debug(f"[tool_enabled] Session cost at turn {executor.current_turn_number}: ${session_cost_usd:.6f}")
                except Exception as e:
                    app_logger.warning(f"Failed to calculate session cost: {e}", exc_info=True)

                turn_summary = {
                    "turn": executor.current_turn_number, # Use the authoritative instance variable
                    "user_query": executor.original_user_input, # Store the original query
                    "is_session_primer": executor.is_session_primer,  # Flag for RAG case filtering
                    "raw_llm_plan": executor.raw_llm_plan,  # LLM's raw output before preprocessing/rewrites
                    "original_plan": executor.original_plan_for_history, # Plan after all rewrite passes (what was actually executed)
                    "execution_trace": executor.turn_action_history,
                    "final_summary": executor.final_summary_text,
                    "system_events": system_events,  # Session name generation and other system operations (UI replay only)
                    "tool_enabled_events": getattr(executor, 'tool_enabled_events', []),  # Lifecycle events for tool_enabled profiles (execution_start, execution_complete)
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "provider": executor.current_provider, # Add snapshot of provider (for backwards compatibility)
                    "model": executor.current_model,       # Add snapshot of model (for backwards compatibility)
                    "profile_tag": profile_tag,        # Add snapshot of profile tag
                    "task_id": executor.task_id,            # Add the task_id
                    "turn_input_tokens": executor.turn_input_tokens,
                    "turn_output_tokens": executor.turn_output_tokens,
                    "turn_cost": turn_cost,  # Add turn cost for historical reload (fixes $0 cost bug)
                    "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                    # Session totals at the time of this turn (for plan reload)
                    "session_input_tokens": session_input_tokens,
                    "session_output_tokens": session_output_tokens,
                    # --- MODIFICATION START: Add session_id and mcp_server_id for RAG worker ---
                    "session_id": executor.session_id,
                    "mcp_server_id": executor.effective_mcp_server_id or APP_CONFIG.CURRENT_MCP_SERVER_ID,  # Use effective MCP ID (override aware)
                    "user_uuid": executor.user_uuid,  # Add user UUID for RAG access control
                    # --- MODIFICATION END ---
                    # --- MODIFICATION START: Add RAG source collection ID and case ID ---
                    "rag_source_collection_id": executor.rag_source_collection_id,
                    "case_id": executor.rag_source_case_id,  # Add case_id for feedback tracking
                    # --- MODIFICATION END ---
                    # --- PHASE 2: Add knowledge repository tracking ---
                    "knowledge_accessed": executor.knowledge_accessed,  # List of knowledge collections used
                    "knowledge_retrieval_event": executor.knowledge_retrieval_event,  # Full event for replay on reload
                    "kg_enrichment_event": executor.kg_enrichment_event,  # KG context injection event for replay
                    # --- PHASE 2 END ---
                    "context_window_snapshot_event": executor._snapshot_with_distillation_events(),  # Context window budget snapshot for replay
                    "strategic_context_snapshot_event": executor.strategic_context_snapshot_event,  # Per-call strategic snapshot for reload
                    # Status fields for consistency with partial turn data
                    "status": "success",
                    "is_partial": False,
                    # Duration tracking for tool_enabled profile (calculated from start time)
                    "duration_ms": int((time.time() - executor.tool_enabled_start_time) * 1000) if hasattr(executor, 'tool_enabled_start_time') else 0,
                    "skills_applied": executor.skill_result.to_applied_list() if executor.skill_result and executor.skill_result.has_content else []
                }
                # --- EPC: Seal provenance chain and merge into turn_summary ---
                try:
                    executor.provenance.add_step("turn_complete",
                                             executor.final_summary_text or "",
                                             "Turn completed successfully")
                    turn_summary.update(executor.provenance.finalize())
                except Exception as _epc_err:
                    app_logger.debug(f"[EPC] finalize error: {_epc_err}")
                # --- EPC END ---
                # --- MODIFICATION END ---
                await session_manager.update_last_turn_data(executor.user_uuid, executor.session_id, turn_summary)
                app_logger.debug(f"Saved last turn data to session {executor.session_id} for user {executor.user_uuid}")

                # --- MODIFICATION START: Add "Producer" logic to send turn to RAG worker ---
                # Skip RAG processing for temporary API sessions (e.g., prompt execution, question generation)
                # Check the source parameter to determine if this is a temporary/utility execution
                skip_rag_for_temp_sessions = executor.source in [
                    "prompt_library_raw",
                    "question_generator"
                ]

                if APP_CONFIG.RAG_ENABLED and APP_STATE.get('rag_processing_queue') and executor.rag_retriever and not skip_rag_for_temp_sessions:
                    try:
                        app_logger.debug(f"Adding turn {executor.current_turn_number} to RAG processing queue.")
                        # Add user_uuid to turn_summary for session updates
                        turn_summary['user_uuid'] = executor.user_uuid
                        # Put the summary in the queue. This is non-blocking and instantaneous.
                        await APP_STATE['rag_processing_queue'].put(turn_summary)
                    except Exception as e:
                        # Log error if queue.put fails, but don't crash the executor
                        app_logger.error(f"Failed to add turn summary to RAG processing queue: {e}", exc_info=True)
                elif skip_rag_for_temp_sessions:
                    app_logger.debug(f"Skipping RAG processing for temporary execution with source: {executor.source}")
                # --- MODIFICATION END ---

            else:
                 # --- MODIFICATION START: Update log message to include depth ---
                 app_logger.info(
                     f"Skipping history save for user {executor.user_uuid}, session {executor.session_id}. "
                     f"Final state: {executor.state.name}, Execution Depth: {executor.execution_depth}"
                 )
                 # --- MODIFICATION END ---
