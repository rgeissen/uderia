"""
Coordinate Engine — genie profile execution.

Wraps GenieCoordinator to provide multi-expert coordination for genie profiles.
Routes queries to child (slave) profiles and synthesises their responses.

Profile type:  ``genie``  (IFOC label: "Coordinate", colour: purple)

Notes
-----
- This engine is registered with EngineRegistry for profile resolution.
- In Phase 3 the genie dispatch path in execution_service.py still calls
  execute_genie() directly; CoordinateEngine.run() is not yet wired into
  the PlanExecutor dispatch chain.
- Phase 4 will unify dispatch so genie profiles also flow through
  EngineRegistry.resolve() → CoordinateEngine.run().
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional

from .registry import EngineRegistry
from .base import ExecutionEngine

if TYPE_CHECKING:
    from trusted_data_agent.agent.executor import PlanExecutor

app_logger = logging.getLogger("quart.app")


@EngineRegistry.register
class CoordinateEngine(ExecutionEngine):
    """Multi-expert coordination engine for ``genie`` profiles."""

    profile_type = "genie"

    async def run(self, executor: "PlanExecutor") -> AsyncGenerator[str, None]:  # type: ignore[override]
        """Not used in Phase 3 — genie is dispatched via execute_genie().

        Phase 4 will wire genie profiles into the unified EngineRegistry dispatch
        so this method becomes the primary execution path.
        """
        raise NotImplementedError(
            "CoordinateEngine must be invoked via execute_genie() in Phase 3. "
            "Phase 4 will add unified PlanExecutor dispatch."
        )
        yield  # type: ignore[misc]  — marks this as AsyncGenerator; unreachable

    async def execute_genie(
        self,
        user_uuid: str,
        session_id: str,
        user_input: str,
        event_handler,
        genie_profile: dict,
        task_id: str = None,
        disabled_history: bool = False,
        current_nesting_level: int = 0,
        is_session_primer: bool = False,
        attachments: list = None,
        skill_result=None,
    ) -> Optional[Dict[str, Any]]:
        """Execute a genie coordination turn.

        Extracted from execution_service._run_genie_execution().
        Builds and runs GenieCoordinator, streams events via event_handler,
        persists turn data, and returns the final payload dict.

        Args:
            user_uuid: UUID of the user who owns the sessions.
            session_id: Parent genie session ID.
            user_input: The user's query text.
            event_handler: Async callable (payload, event_type) → None.
            genie_profile: Genie profile configuration dict.
            task_id: Optional task ID for REST API tracking.
            disabled_history: If True, skip loading conversation history.
            current_nesting_level: Current depth in nested genie hierarchy.
            is_session_primer: If True, skip session name generation.
            attachments: Optional list of uploaded document attachments.
            skill_result: Optional pre-resolved skill content.

        Returns:
            Final payload dict (same structure as other profile types), or None on error.
        """
        from trusted_data_agent.core import session_manager
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

            # Annotate each slave with per-slave settings from the coordinator profile
            slave_profile_settings = genie_config.get("slaveProfileSettings", {})
            for slave in slave_profiles:
                settings = slave_profile_settings.get(slave["id"], {})
                slave["full_result_passthrough"] = settings.get("fullResultPassthrough", False)

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

            # --- EPC: Create provenance chain for genie ---
            _genie_provenance = None
            try:
                from trusted_data_agent.core.provenance import ProvenanceChain, get_previous_turn_tip_hash
                prev_tip = await get_previous_turn_tip_hash(user_uuid, session_id)
                _genie_provenance = ProvenanceChain(
                    session_id=session_id, turn_number=0,  # Will be updated below
                    user_uuid=user_uuid, profile_type="genie",
                    previous_turn_tip_hash=prev_tip,
                    event_queue=None,  # Genie doesn't use async generator
                )
                _genie_provenance.add_step("query_intake", user_input, f"Query: {user_input[:100]}")
                _genie_provenance.add_step("profile_resolve", f"{profile_id}:genie:{profile_tag}", f"Profile: @{profile_tag} (genie)")
            except Exception as _epc_err:
                app_logger.debug(f"EPC genie init: {_epc_err}")

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
                current_nesting_level=current_nesting_level,
                provenance=_genie_provenance,
                skill_result=skill_result,
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

            # Compute turn number for lifecycle events (same logic as executor.py)
            workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', []) if session_data else []
            turn_number = len(workflow_history) + 1
            coordinator.turn_number = turn_number
            # Update provenance turn number now that we know it
            if _genie_provenance:
                _genie_provenance.turn_number = turn_number

            # --- CONTEXT WINDOW MANAGER (Feature-Flagged, Observability) ---
            cw_history_window = 10  # Default fallback
            cw_document_max_chars = None  # Default: use APP_CONFIG limit
            genie_cw_snapshot_event = None  # Capture for turn_data persistence
            try:
                from trusted_data_agent.core.config import APP_CONFIG as _CW_APP_CONFIG
                if _CW_APP_CONFIG.USE_CONTEXT_WINDOW_MANAGER:
                    from components.builtin.context_window.handler import ContextWindowHandler
                    from components.builtin.context_window.base import AssemblyContext

                    cwt = config_manager.get_default_context_window_type(user_uuid)
                    if cwt:
                        enriched_session = dict(session_data) if session_data else {}
                        enriched_session['current_query'] = user_input or ''

                        # Resolve model context limit
                        model_context_limit = 128_000
                        try:
                            import litellm
                            model_key = f"{provider}/{model}"
                            model_info = litellm.model_cost.get(model_key) or litellm.model_cost.get(model or "")
                            if model_info:
                                model_context_limit = model_info.get("max_input_tokens") or model_info.get("max_tokens") or 128_000
                        except Exception:
                            pass

                        # Apply profile-level context limit override
                        context_limit_override = genie_profile.get("contextLimitOverride")
                        if context_limit_override and isinstance(context_limit_override, int):
                            if context_limit_override < model_context_limit:
                                model_context_limit = context_limit_override

                        # Apply session-level context limit override (takes precedence)
                        session_context_limit = enriched_session.get('session_context_limit_override')
                        if session_context_limit and isinstance(session_context_limit, int):
                            if session_context_limit < model_context_limit:
                                model_context_limit = session_context_limit

                        ctx = AssemblyContext(
                            profile_type="genie",
                            profile_id=profile_id or "",
                            session_id=session_id,
                            user_uuid=user_uuid,
                            session_data=enriched_session,
                            turn_number=turn_number,
                            is_first_turn=turn_number == 1,
                            model_context_limit=model_context_limit,
                            dependencies={},
                            profile_config=genie_profile,
                        )

                        handler = ContextWindowHandler()
                        assembled = await handler.assemble(cwt, ctx)

                        if assembled and assembled.snapshot:
                            app_logger.info(
                                f"Context Window Snapshot: "
                                f"{assembled.snapshot.total_used:,}/{assembled.snapshot.available_budget:,} tokens "
                                f"({assembled.snapshot.utilization_pct:.1f}% utilization)"
                            )
                            snapshot_payload = assembled.snapshot.to_sse_event()
                            genie_cw_snapshot_event = snapshot_payload
                            await event_handler({
                                "step": "Context Window Assembly",
                                "type": "context_window_snapshot",
                                "details": assembled.snapshot.to_summary_text(),
                                "payload": snapshot_payload,
                            }, "notification")

                            # Extract budget-aware values for downstream use
                            cw_hist = assembled.contributions.get("conversation_history")
                            if cw_hist and cw_hist.metadata.get("turn_count", 0) > 0:
                                cw_history_window = cw_hist.metadata["turn_count"]
                            app_logger.info(
                                f"Context window: conversation_history budget-aware window={cw_history_window} "
                                f"({cw_hist.tokens_used:,} tokens)" if cw_hist else
                                f"Context window: using default history window={cw_history_window}"
                            )
                            for cm in assembled.snapshot.contributions:
                                if cm.module_id == "document_context" and cm.tokens_allocated > 0:
                                    cw_document_max_chars = cm.tokens_allocated * 4
                                    app_logger.info(
                                        f"Context window: document_context budget={cm.tokens_allocated:,} tokens "
                                        f"(~{cw_document_max_chars:,} chars)"
                                    )
                                    break
            except Exception as cw_err:
                app_logger.debug(f"[Genie] Context window assembly skipped: {cw_err}")
            # --- CONTEXT WINDOW MANAGER END ---

            conversation_history = []

            if disabled_history:
                # When disabled_history is True, skip loading conversation history
                # This supports the Alt-key single-turn context mode
                app_logger.info(f"[Genie] History disabled for this turn - skipping conversation context")
            elif session_data:
                chat_object = session_data.get("chat_object", [])
                app_logger.debug(f"[Genie] chat_object has {len(chat_object)} messages")

                # Take last N messages for context, excluding the current query
                # (current query was already saved by caller before this runs)
                # cw_history_window is budget-aware (from context window module) or defaults to 10
                history_messages = chat_object[-(cw_history_window + 1):]  # Get one extra to check

                # Remove current query from history if present (it will be passed separately)
                user_input_stripped = user_input.strip() if user_input else ""
                if history_messages and history_messages[-1].get("role") == "user":
                    last_content = history_messages[-1].get("content", "").strip()
                    if last_content == user_input_stripped:
                        history_messages = history_messages[:-1]
                        app_logger.debug("[Genie] Excluding current query from history")

                # Build conversation history (filter priming messages and respect isValid flag)
                priming_messages = {"You are a helpful assistant.", "Understood."}
                for msg in history_messages[-cw_history_window:]:
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
                doc_context, _ = load_document_context(user_uuid, session_id, attachments, max_total_chars=cw_document_max_chars)
                if doc_context:
                    genie_user_input = f"[User has uploaded documents]\n{doc_context}\n\n[User's question]\n{user_input}"

            # Execute coordination with conversation context
            result = await coordinator.execute(genie_user_input, conversation_history=conversation_history)

            # Extract the final response
            coordinator_response = result.get('coordinator_response', '')
            # In pass-through mode the coordinator preserves the slave's full HTML response
            # (tables, charts, key observations) separately from the plain-text summary.
            # Fall back to coordinator_response when synthesis ran (coordinator_html is None).
            coordinator_html = result.get('coordinator_html') or coordinator_response
            success = result.get('success', False)

            # Generate component HTML from coordinator's direct component tool calls
            # (TDA_Charting, etc. — component-agnostic, works for any future component)
            from trusted_data_agent.components.utils import generate_component_html
            genie_component_html = generate_component_html(result.get("component_payloads", []))

            # Extract token counts from coordination result IMMEDIATELY (before any other processing)
            input_tokens = result.get('input_tokens', 0) or 0
            output_tokens = result.get('output_tokens', 0) or 0

            # Initialize session totals (updated inside the if-block, used in final_payload)
            session_input_tokens = 0
            session_output_tokens = 0

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
                # Include component HTML (chart, code, etc.) for UI display if present
                genie_html_content = coordinator_html + (genie_component_html or "")
                if genie_html_content == coordinator_response:
                    genie_html_content = None  # No separate HTML needed when content is identical
                await session_manager.add_message_to_histories(
                    user_uuid=user_uuid,
                    session_id=session_id,
                    role='assistant',
                    content=coordinator_response,
                    html_content=genie_html_content,
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

                # --- EPC: Seal provenance chain for genie ---
                _provenance_data = None
                try:
                    if _genie_provenance and not _genie_provenance._sealed:
                        _genie_provenance.add_step("coordinator_synthesis", coordinator_response[:4096] if coordinator_response else "", f"Genie synthesis complete")
                        _genie_provenance.add_step("turn_complete", coordinator_response or "", f"genie turn {turn_number} complete")
                        _provenance_data = _genie_provenance.finalize()
                except Exception as _epc_err:
                    app_logger.debug(f"EPC genie finalize: {_epc_err}")

                turn_data = {
                    'turn': turn_number,
                    'user_query': user_input,
                    'genie_coordination': True,
                    'tools_used': result.get('tools_used', []),
                    'slave_sessions': result.get('slave_sessions', {}),
                    'genie_events': combined_genie_events,  # Include session name events
                    'kg_enrichment_event': result.get('kg_enrichment_event'),  # KG enrichment for persistence
                    'context_window_snapshot_event': genie_cw_snapshot_event,  # CW snapshot for reload
                    'skills_applied': skill_result.to_applied_list() if skill_result and skill_result.has_content else [],
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
                if _provenance_data:
                    turn_data.update(_provenance_data)

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

            except Exception as log_error:
                app_logger.error(f"Failed to log Genie session data: {log_error}")

            # Send final answer event with proper fields for frontend and extensions
            # Include component HTML (chart divs, etc.) in the visual response but keep clean text for extensions
            genie_visual_response = (coordinator_html + genie_component_html) if genie_component_html else coordinator_html
            final_payload = {
                "final_answer": genie_visual_response,  # Required by eventHandlers.js (includes component divs)
                "final_answer_text": coordinator_response,  # Plain text for extensions (ExtensionContext.answer_text)
                "html_response": genie_visual_response,
                "raw_response": coordinator_response,
                "turn_id": turn_number,  # Required for turn numbering in UI
                "session_id": session_id,  # Include session_id for filtering when switching sessions
                "profile_tag": profile_tag,
                "profile_type": "genie",
                "provider": provider,
                "model": model,
                "turn_input_tokens": input_tokens,
                "turn_output_tokens": output_tokens,
                "total_input_tokens": session_input_tokens,
                "total_output_tokens": session_output_tokens,
                "execution_trace": result.get('genie_events', []),
                "tools_used": result.get('tools_used', []),
                "genie_coordination": True,
                "slave_sessions_used": result.get('slave_sessions', {}),
                "genie_events": result.get('genie_events', []),  # Full event list for GenieContext
                "kg_enrichment_event": result.get('kg_enrichment_event'),  # KG enrichment for persistence
            }
            await event_handler(final_payload, "final_answer")

            # Emit session name events AFTER final answer (events already collected and saved to history)
            # Note: Don't gate on turn_number==1 — when a session primer occupies turn 1,
            # the first real query arrives on turn 2+ and still needs name emission.
            # The generation guard ensures we only generate when name is unset or "New Chat".
            if session_name_events:
                # Emit the collected session name events via SSE
                for event in session_name_events:
                    await event_handler(event['payload'], event['type'])

                # Persist session name tokens and emit token_update so Last Stmt KPI updates
                if session_name_input_tokens > 0 or session_name_output_tokens > 0:
                    await session_manager.update_token_count(
                        user_uuid, session_id,
                        session_name_input_tokens, session_name_output_tokens
                    )
                    _updated_session = await session_manager.get_session(user_uuid, session_id)
                    if _updated_session:
                        _sess_in = _updated_session.get("input_tokens", 0)
                        _sess_out = _updated_session.get("output_tokens", 0)
                        _name_cost = 0
                        try:
                            from trusted_data_agent.core.cost_manager import CostManager
                            _name_cost = CostManager().calculate_cost(
                                provider=provider or "Unknown",
                                model=model or "Unknown",
                                input_tokens=session_name_input_tokens,
                                output_tokens=session_name_output_tokens
                            )
                        except Exception:
                            pass
                        await event_handler({
                            "statement_input": session_name_input_tokens,
                            "statement_output": session_name_output_tokens,
                            "turn_input": input_tokens + session_name_input_tokens,
                            "turn_output": output_tokens + session_name_output_tokens,
                            "total_input": _sess_in,
                            "total_output": _sess_out,
                            "call_id": "genie_session_name",
                            "cost_usd": _name_cost
                        }, "token_update")

                # Update session name in database
                if session_name and session_name != "New Chat":
                    await session_manager.update_session_name(user_uuid, session_id, session_name)
                    await event_handler({
                        "session_id": session_id,
                        "newName": session_name
                    }, "session_name_update")

                    app_logger.info(f"[Genie] Session name updated to '{session_name}' "
                                  f"({session_name_input_tokens} in / {session_name_output_tokens} out)")

            # Send session_model_update so the master session bubbles to the top of the history panel
            # (all other profile types emit this; Genie was the only one missing it)
            _genie_session_data = await session_manager.get_session(user_uuid, session_id)
            if _genie_session_data:
                await event_handler({
                    "session_id": session_id,
                    "models_used": _genie_session_data.get("models_used", []),
                    "profile_tags_used": _genie_session_data.get("profile_tags_used", []),
                    "last_updated": _genie_session_data.get("last_updated"),
                    "provider": provider,
                    "model": model,
                    "name": _genie_session_data.get("name", "New Chat"),
                }, "session_model_update")

            return final_payload

        except Exception as e:
            app_logger.error(f"Genie coordination error for user {user_uuid}, session {session_id}: {e}", exc_info=True)
            await event_handler({
                "error": f"Genie coordination failed: {str(e)}"
            }, "error")
            return None
