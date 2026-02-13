# src/trusted_data_agent/agent/execution_service.py
import logging
import json
import re
import asyncio
from datetime import datetime, timezone

from trusted_data_agent.agent.executor import PlanExecutor
from trusted_data_agent.agent.session_name_generator import generate_session_name_with_events
from trusted_data_agent.core.config import APP_STATE
from trusted_data_agent.core import session_manager

app_logger = logging.getLogger("quart.app")


def _format_sse(data: dict, event_type: str = None) -> str:
    """Format data as SSE event string."""
    lines = []
    if event_type:
        lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")
    return "\n".join(lines)

def _parse_sse_event(event_str: str) -> tuple[dict, str]:
    """
    Parses a raw SSE event string into its data and event type.
    """
    data = {}
    event_type = None
    for line in event_str.strip().split('\n'):
        if line.startswith('data:'):
            try:
                data = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                app_logger.warning(f"Could not decode event JSON: {line}")
                data = {"raw_content": line[5:].strip()}
        elif line.startswith('event:'):
            event_type = line[6:].strip()
    return data, event_type


# --- MODIFICATION START: Add plan_to_execute and is_replay parameters ---
async def run_agent_execution(
    user_uuid: str,
    session_id: str,
    user_input: str,
    event_handler,
    active_prompt_name: str = None,
    prompt_arguments: dict = None,
    disabled_history: bool = False,
    source: str = "text",
    plan_to_execute: list = None, # Added optional plan
    is_replay: bool = False, # Added replay flag
    display_message: str = None, # Added optional display message for replays
    task_id: str = None, # Add task_id parameter here
    profile_override_id: str = None, # Add profile override parameter
    is_session_primer: bool = False, # Session primer flag - marks messages as initialization
    attachments: list = None  # Document upload attachments [{file_id, filename, ...}]
):
# --- MODIFICATION END ---
    """
    The central, abstracted service for running the PlanExecutor.
    """
    final_result_payload = None
    try:
        session_data = await session_manager.get_session(user_uuid, session_id)

        if not session_data:
             app_logger.error(f"Execution service: Session {session_id} not found for user {user_uuid}.")
             await event_handler({"error": f"Session '{session_id}' not found."}, "error")
             return None # Indicate failure

        # Send an event with the latest model usage
        await event_handler({
            "session_id": session_id,
            "models_used": session_data.get("models_used", []),
            "profile_tags_used": session_data.get("profile_tags_used", []),
            "last_updated": session_data.get("last_updated", session_data.get("created_at"))
        }, "session_model_update")

        # --- MODIFICATION START: Save the correct user message to history ---
        # For a replay, we save the "Replaying..." message for UI persistence.
        # For a normal query, we save the actual user input.
        message_to_save = display_message if is_replay and display_message else user_input

        # Get profile tag from profile_override_id or current default profile
        # IMPORTANT: Use default profile, not stale session profile_id, to avoid wrong tags after override expires
        profile_tag = None
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()

            # Priority: override > current default profile (NOT stale session profile_id)
            # This ensures profile tags are always correct, even after override expires
            default_profile_id = config_manager.get_default_profile_id(user_uuid)
            profile_id_to_check = profile_override_id or default_profile_id

            if profile_id_to_check:
                profiles = config_manager.get_profiles(user_uuid)
                profile = next((p for p in profiles if p.get("id") == profile_id_to_check), None)
                if profile:
                    profile_tag = profile.get("tag")
                    app_logger.debug(f"Resolved profile_tag for user message: {profile_tag} (override={bool(profile_override_id)})")
                else:
                    app_logger.warning(f"Profile {profile_id_to_check} not found when resolving user message tag")
        except Exception as e:
            app_logger.warning(f"Failed to get profile tag: {e}")

        if message_to_save:
            await session_manager.add_message_to_histories(
                user_uuid,
                session_id,
                'user',
                message_to_save,
                html_content=None, # User input is plain text
                source=source,
                profile_tag=profile_tag,
                is_session_primer=is_session_primer,
                attachments=attachments
            )
            app_logger.debug(f"Added user message to session_history for {session_id}: '{message_to_save}' with profile_tag: {profile_tag}, is_session_primer: {is_session_primer}")

            # Send SSE event to update frontend with the resolved profile_tag
            # This ensures session primers display the correct profile tag immediately
            if profile_tag:
                app_logger.info(f"Sending user_message_profile_tag SSE event: profile_tag={profile_tag}, is_session_primer={is_session_primer}")
                await event_handler({
                    "type": "user_message_profile_tag",
                    "payload": {
                        "profile_tag": profile_tag,
                        "is_session_primer": is_session_primer
                    }
                }, "notification")
        # --- MODIFICATION END ---

        previous_turn_data = session_data.get("last_turn_data", {})

        # --- GENIE PROFILE DETECTION: Route to Genie coordinator for genie profiles ---
        # Determine active profile type
        active_profile = None
        active_profile_type = "tool_enabled"  # Default

        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()

        # Get current default profile
        default_profile_id = config_manager.get_default_profile_id(user_uuid)

        # Profile resolution logic:
        # 1. If profile_override_id is set (explicit @TAG), use it
        # 2. Otherwise, ALWAYS use the current default profile (ignore stale session profile_id)
        profile_id_to_use = profile_override_id or default_profile_id

        if profile_id_to_use:
            profiles = config_manager.get_profiles(user_uuid)
            active_profile = next((p for p in profiles if p.get("id") == profile_id_to_use), None)
            if active_profile:
                active_profile_type = active_profile.get("profile_type", "tool_enabled")
                app_logger.debug(
                    f"Resolved profile: {active_profile.get('tag')} (type: {active_profile_type}, "
                    f"override: {bool(profile_override_id)}, default: {profile_id_to_use == default_profile_id})"
                )

        if not active_profile:
            # Fallback to tool_enabled if no profile found
            active_profile_type = "tool_enabled"
            app_logger.warning(f"No active profile found, defaulting to tool_enabled")

        # Update session to reflect the profile being used (unless it's an override)
        # profile_id tracks the "base" profile, overrides are temporary
        if not profile_override_id and active_profile:
            session_profile_id = session_data.get("profile_id")
            if session_profile_id != active_profile.get("id"):
                app_logger.info(
                    f"Updating session profile from {session_profile_id} to {active_profile.get('id')} "
                    f"(default changed to @{active_profile.get('tag')})"
                )
                # BUG FIX: Reload session to get the user message that was just added
                session_data = await session_manager.get_session(user_uuid, session_id)
                session_data["profile_id"] = active_profile.get("id")
                session_data["profile_tag"] = active_profile.get("tag")
                await session_manager._save_session(user_uuid, session_id, session_data)

        # Track the last executed profile (for prompt invocations from resource panel)
        if active_profile:
            current_last_executed = session_data.get("last_executed_profile_id")
            if current_last_executed != active_profile.get("id"):
                # BUG FIX: Reload session to get the user message that was just added
                session_data = await session_manager.get_session(user_uuid, session_id)
                session_data["last_executed_profile_id"] = active_profile.get("id")
                app_logger.debug(f"Updated last_executed_profile_id to {active_profile.get('id')} (@{active_profile.get('tag')})")
                await session_manager._save_session(user_uuid, session_id, session_data)

        # Route Genie profiles to Genie coordinator
        if active_profile_type == "genie" and active_profile:
            app_logger.info(f"🔮 Detected Genie profile '{active_profile.get('tag')}' - routing to Genie coordinator")
            final_result_payload = await _run_genie_execution(
                user_uuid=user_uuid,
                session_id=session_id,
                user_input=user_input,
                event_handler=event_handler,
                genie_profile=active_profile,
                task_id=task_id,
                disabled_history=disabled_history,  # Pass history context flag
                is_session_primer=is_session_primer,  # Pass session primer flag
                attachments=attachments  # Pass document upload attachments
            )
            return final_result_payload
        # --- END GENIE PROFILE DETECTION ---

        # --- MODIFICATION START: Pass new parameters to PlanExecutor ---
        executor = PlanExecutor(
            user_uuid=user_uuid,
            session_id=session_id,
            original_user_input=user_input,
            dependencies={'STATE': APP_STATE},
            active_prompt_name=active_prompt_name,
            prompt_arguments=prompt_arguments,
            disabled_history=disabled_history,
            previous_turn_data=previous_turn_data,
            source=source,
            plan_to_execute=plan_to_execute, # Pass the plan
            is_replay=is_replay, # Pass the flag
            task_id=task_id, # Pass the task_id here
            profile_override_id=profile_override_id, # Pass the profile override
            event_handler=event_handler,
            is_session_primer=is_session_primer, # Pass the session primer flag
            attachments=attachments  # Pass document upload attachments
        )
        # --- MODIFICATION END ---

        async for event_str in executor.run():
            event_data, event_type = _parse_sse_event(event_str)
            await event_handler(event_data, event_type)

            if event_type == "final_answer":
                final_result_payload = event_data

    except Exception as e:
        app_logger.error(f"An unhandled error occurred in the agent execution service for user {user_uuid}, session {session_id}: {e}", exc_info=True)
        await event_handler({"error": str(e)}, "error")
        raise

    return final_result_payload


async def _run_genie_execution(
    user_uuid: str,
    session_id: str,
    user_input: str,
    event_handler,
    genie_profile: dict,
    task_id: str = None,
    disabled_history: bool = False,
    current_nesting_level: int = 0,
    is_session_primer: bool = False,
    attachments: list = None
):
    """
    Execute a query using Genie coordination for SSE streaming.

    This function handles Genie profile queries by:
    1. Building the GenieCoordinator with slave profiles
    2. Executing the coordination
    3. Streaming events back via SSE

    Args:
        current_nesting_level: Current depth in nested Genie hierarchy (0 = top-level)
    """
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.llm.langchain_adapter import create_langchain_llm
    from trusted_data_agent.agent.genie_coordinator import GenieCoordinator

    config_manager = get_config_manager()
    profile_id = genie_profile.get("id")
    profile_tag = genie_profile.get("tag", "GENIE")

    try:
        # Check depth limit at runtime
        global_settings = config_manager.get_genie_global_settings()
        max_depth = int(global_settings.get('maxNestingDepth', {}).get('value', 3))

        if current_nesting_level >= max_depth:
            await event_handler({
                "error": f"Maximum Genie nesting depth ({max_depth}) exceeded. Cannot execute nested Genie at level {current_nesting_level}."
            }, "error")
            app_logger.warning(f"Genie execution blocked: nesting level {current_nesting_level} >= max depth {max_depth}")
            return None

        # Note: genie_coordination_start is emitted by GenieCoordinator with full details

        # Validate genie configuration
        genie_config = genie_profile.get("genieConfig", {})
        slave_profile_ids = genie_config.get("slaveProfiles", [])

        if not slave_profile_ids:
            await event_handler({
                "error": "Genie profile has no child profiles configured."
            }, "error")
            return None

        # Get child profile details
        slave_profiles = []
        for pid in slave_profile_ids:
            slave_profile = config_manager.get_profile(pid, user_uuid)
            if slave_profile:
                slave_profiles.append(slave_profile)
            else:
                app_logger.warning(f"Genie profile {profile_id} references missing child profile {pid}")

        if not slave_profiles:
            await event_handler({
                "error": "No valid child profiles found for this genie."
            }, "error")
            return None

        # Note: genie_coordination_start is emitted by GenieCoordinator with slave_profiles details

        # Get LLM configuration for coordinator
        llm_config_id = genie_profile.get("llmConfigurationId")
        if not llm_config_id:
            await event_handler({
                "error": "Genie profile requires an LLM configuration."
            }, "error")
            return None

        # Get effective genie config (merges global settings with profile overrides)
        effective_genie_config = config_manager.get_effective_genie_config(genie_config)

        # Create LangChain LLM from Uderia config with temperature from genie config
        llm_instance = create_langchain_llm(
            llm_config_id,
            user_uuid,
            temperature=float(effective_genie_config['temperature'])
        )

        # Get LLM config details for logging
        llm_configurations = config_manager.get_llm_configurations(user_uuid)
        llm_config = next((c for c in llm_configurations if c.get("id") == llm_config_id), None)
        provider = llm_config.get('provider', 'Unknown') if llm_config else 'Unknown'
        model = llm_config.get('model', 'unknown') if llm_config else 'unknown'

        # Determine base URL - use internal localhost for self-calls
        base_url = "http://localhost:5050"

        # Get auth token from APP_STATE or generate internal token
        # For internal execution, we use a special internal auth mechanism
        from trusted_data_agent.auth.security import create_internal_token
        auth_token = create_internal_token(user_uuid)

        # Create event handler that forwards Genie events to SSE
        async def genie_sse_event_handler(event_type: str, payload: dict):
            """Forward genie coordination events to SSE stream."""
            await event_handler(payload, event_type)

        # Build and execute coordinator
        coordinator = GenieCoordinator(
            genie_profile=genie_profile,
            slave_profiles=slave_profiles,
            user_uuid=user_uuid,
            parent_session_id=session_id,
            auth_token=auth_token,
            llm_instance=llm_instance,
            base_url=base_url,
            event_callback=lambda t, p: asyncio.create_task(genie_sse_event_handler(t, p)),
            genie_config=effective_genie_config,
            current_nesting_level=current_nesting_level
        )

        # Load existing child sessions to preserve context across multiple queries
        existing_slaves = await session_manager.get_genie_slave_sessions(session_id, user_uuid)
        if existing_slaves:
            coordinator.load_existing_slave_sessions(existing_slaves)
            app_logger.info(f"Loaded {len(existing_slaves)} existing child sessions for Genie session {session_id}")

        # Build conversation history from session's chat_object
        # This provides multi-turn context to the Genie coordinator
        # Respects disabled_history flag (for single-turn context mode) and isValid flag (for purged/toggled turns)
        session_data = await session_manager.get_session(user_uuid, session_id)

        # Compute turn number for lifecycle events (same logic as executor.py:1945-1951)
        workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', []) if session_data else []
        coordinator.turn_number = len(workflow_history) + 1

        conversation_history = []

        if disabled_history:
            # When disabled_history is True, skip loading conversation history
            # This supports the Alt-key single-turn context mode
            app_logger.info(f"[Genie] History disabled for this turn - skipping conversation context")
        elif session_data:
            chat_object = session_data.get("chat_object", [])
            app_logger.debug(f"[Genie] chat_object has {len(chat_object)} messages")

            # Take last 10 messages for context, excluding the current query
            # (current query was already saved by caller before this runs)
            history_messages = chat_object[-11:]  # Get one extra to check

            # Remove current query from history if present (it will be passed separately)
            user_input_stripped = user_input.strip() if user_input else ""
            if history_messages and history_messages[-1].get("role") == "user":
                last_content = history_messages[-1].get("content", "").strip()
                if last_content == user_input_stripped:
                    history_messages = history_messages[:-1]
                    app_logger.debug("[Genie] Excluding current query from history")

            # Build conversation history (filter priming messages and respect isValid flag)
            priming_messages = {"You are a helpful assistant.", "Understood."}
            for msg in history_messages[-10:]:
                msg_content = msg.get("content", "")

                # Handle content that may be a list (Google Gemini multimodal format)
                if isinstance(msg_content, list):
                    msg_content = ' '.join(str(part) for part in msg_content if part)

                # Skip messages marked as invalid (purged or toggled off)
                if msg.get("isValid") is False:
                    app_logger.debug(f"[Genie] Skipping invalid message: {msg_content[:50] if msg_content else ''}...")
                    continue

                if msg_content in priming_messages:
                    continue
                msg_role = msg.get("role", "user")
                if msg_role == "model":
                    msg_role = "assistant"
                conversation_history.append({
                    "role": msg_role,
                    "content": msg_content
                })

            app_logger.info(f"[Genie] Built conversation history with {len(conversation_history)} messages")

        # Prepend document context to user_input for genie if attachments present
        genie_user_input = user_input
        if attachments:
            from trusted_data_agent.agent.executor import load_document_context
            doc_context = load_document_context(user_uuid, session_id, attachments)
            if doc_context:
                genie_user_input = f"[User has uploaded documents]\n{doc_context}\n\n[User's question]\n{user_input}"

        # Execute coordination with conversation context
        result = await coordinator.execute(genie_user_input, conversation_history=conversation_history)

        # Extract the final response
        coordinator_response = result.get('coordinator_response', '')
        success = result.get('success', False)

        # Extract token counts from coordination result IMMEDIATELY (before any other processing)
        input_tokens = result.get('input_tokens', 0) or 0
        output_tokens = result.get('output_tokens', 0) or 0

        # Update session token counts and emit token_update event IMMEDIATELY
        # This ensures the status window shows correct tokens during live execution
        if input_tokens > 0 or output_tokens > 0:
            await session_manager.update_token_count(
                user_uuid,
                session_id,
                input_tokens,
                output_tokens
            )

            # Get updated session totals and turn number for token_update event
            current_session = await session_manager.get_session(user_uuid, session_id)
            if current_session:
                workflow_history = current_session.get('last_turn_data', {}).get('workflow_history', [])
                turn_number = len(workflow_history) + 1
                session_input_tokens = current_session.get("input_tokens", 0)
                session_output_tokens = current_session.get("output_tokens", 0)

                # Calculate cost for genie coordinator LLM call
                _genie_cost = 0
                try:
                    from trusted_data_agent.core.cost_manager import CostManager
                    _genie_cost = CostManager().calculate_cost(
                        provider=provider or "Unknown",
                        model=model or "Unknown",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens
                    )
                except Exception:
                    pass

                # Emit token_update event IMMEDIATELY (before session name generation)
                # For genie, turn tokens = statement tokens (single coordination per turn)
                await event_handler({
                    "statement_input": input_tokens,
                    "statement_output": output_tokens,
                    "turn_input": input_tokens,
                    "turn_output": output_tokens,
                    "total_input": session_input_tokens,
                    "total_output": session_output_tokens,
                    "call_id": f"genie_{turn_number}",
                    "cost_usd": _genie_cost
                }, "token_update")

                app_logger.info(f"[Genie] Token update emitted: {input_tokens} in / {output_tokens} out "
                              f"(session total: {session_input_tokens} in / {session_output_tokens} out)")

        # Log the Genie conversation to session files
        try:
            # Add coordinator response to session history (user message was already saved by caller)
            await session_manager.add_message_to_histories(
                user_uuid=user_uuid,
                session_id=session_id,
                role='assistant',
                content=coordinator_response,
                profile_tag=profile_tag,
                is_session_primer=is_session_primer
            )

            # Add turn data to workflow_history
            current_session = await session_manager.get_session(user_uuid, session_id)
            workflow_history = current_session.get('last_turn_data', {}).get('workflow_history', [])
            turn_number = len(workflow_history) + 1

            # Get session token totals (after updating them above)
            session_input_tokens = current_session.get("input_tokens", 0)
            session_output_tokens = current_session.get("output_tokens", 0)

            # Collect session name generation events (before creating turn_data)
            # Skip if this is a session primer - only generate from real user queries
            session_name_events = []
            if not is_session_primer:  # Skip session primers
                current_session_check = await session_manager.get_session(user_uuid, session_id)
                # Generate if name not set (works for turn 1 or turn 2+ after primer)
                if current_session_check and (not current_session_check.get("name") or current_session_check.get("name") == "New Chat"):
                    try:
                        app_logger.info(f"[Genie] Generating session name from first real user query (collecting events for history)")

                        from trusted_data_agent.agent.session_name_generator import generate_session_name_with_events
                        from trusted_data_agent.llm.langchain_adapter import create_langchain_llm

                        # Create a separate LangChain instance with thinking disabled for session name generation
                        # This ensures we get clean titles (3-5 tokens) instead of thinking blocks (100+ tokens)
                        session_name_llm = create_langchain_llm(
                            llm_config_id,
                            user_uuid,
                            temperature=0.7,
                            disable_thinking=True  # Disable extended thinking for session names
                        )

                        async for event_dict, event_type, in_tok, out_tok in generate_session_name_with_events(
                            user_query=user_input,
                            session_id=session_id,
                            llm_interface="langchain",
                            llm_instance=session_name_llm,  # Use dedicated instance with thinking disabled
                            emit_events=False  # Don't emit yet, we'll emit after saving to history
                        ):
                            if event_dict is None:
                                # Final yield: session name
                                session_name = event_type
                                session_name_input_tokens = in_tok
                                session_name_output_tokens = out_tok
                            else:
                                # Collect event for history (store complete event_data)
                                session_name_events.append({
                                    "type": event_type,
                                    "payload": event_dict  # Full event data, not just details
                                })

                    except Exception as name_error:
                        app_logger.warning(f"Failed to generate genie session name: {name_error}")
                        session_name = None
                        session_name_input_tokens = 0
                        session_name_output_tokens = 0
                else:
                    session_name = None
                    session_name_input_tokens = 0
                    session_name_output_tokens = 0
            else:
                # Session primer - skip name generation
                if is_session_primer:
                    app_logger.debug(f"[Genie] ⏭️  Skipping session name generation for session primer: {user_input[:50]}...")
                session_name = None
                session_name_input_tokens = 0
                session_name_output_tokens = 0

            # Combine coordinator events with session name events
            combined_genie_events = result.get('genie_events', []) + session_name_events

            turn_data = {
                'turn': turn_number,
                'user_query': user_input,
                'genie_coordination': True,
                'tools_used': result.get('tools_used', []),
                'slave_sessions': result.get('slave_sessions', {}),
                'genie_events': combined_genie_events,  # Include session name events
                'success': success,
                'final_response': coordinator_response[:500] if coordinator_response else '',
                'status': 'success' if success else 'failed',
                'provider': provider,
                'model': model,
                'profile_tag': profile_tag,
                'profile_type': 'genie',  # Mark as genie for session gallery status detection
                # Token tracking (consistent with other execution paths)
                'turn_input_tokens': input_tokens,  # Cumulative turn total
                'turn_output_tokens': output_tokens,  # Cumulative turn total
                'session_input_tokens': session_input_tokens,  # Session totals at time of this turn
                'session_output_tokens': session_output_tokens  # Session totals at time of this turn
            }

            await session_manager.update_last_turn_data(
                user_uuid=user_uuid,
                session_id=session_id,
                turn_data=turn_data
            )

            # Update models used
            await session_manager.update_models_used(
                user_uuid=user_uuid,
                session_id=session_id,
                provider=provider,
                model=model,
                profile_tag=profile_tag
            )
            # Note: Token update event emitted immediately after coordination (line 413)
            # Note: Session name generation happens after final_answer (see below after line 506)

        except Exception as log_error:
            app_logger.error(f"Failed to log Genie session data: {log_error}")

        # Send final answer event with proper fields for frontend
        final_payload = {
            "final_answer": coordinator_response,  # Required by eventHandlers.js
            "html_response": coordinator_response,
            "raw_response": coordinator_response,
            "turn_id": turn_number,  # Required for turn numbering in UI
            "session_id": session_id,  # Include session_id for filtering when switching sessions
            "profile_tag": profile_tag,
            "genie_coordination": True,
            "slave_sessions_used": result.get('slave_sessions', {})
        }
        await event_handler(final_payload, "final_answer")

        # Emit session name events AFTER final answer (events already collected and saved to history)
        # Note: Don't gate on turn_number==1 — when a session primer occupies turn 1,
        # the first real query arrives on turn 2+ and still needs name emission.
        # The generation guard (line 456-459) already ensures we only generate when
        # name is unset or "New Chat", so no risk of overwriting an existing name.
        if session_name_events:
            # Emit the collected session name events via SSE
            # Payload now contains the complete event_dict (step, details, type)
            for event in session_name_events:
                await event_handler(event['payload'], event['type'])

            # Update session name in database
            if session_name and session_name != "New Chat":
                await session_manager.update_session_name(user_uuid, session_id, session_name)
                await event_handler({
                    "session_id": session_id,
                    "newName": session_name
                }, "session_name_update")

                app_logger.info(f"[Genie] Session name updated to '{session_name}' "
                              f"({session_name_input_tokens} in / {session_name_output_tokens} out)")

        return final_payload

    except Exception as e:
        app_logger.error(f"Genie coordination error for user {user_uuid}, session {session_id}: {e}", exc_info=True)
        await event_handler({
            "error": f"Genie coordination failed: {str(e)}"
        }, "error")
        return None
