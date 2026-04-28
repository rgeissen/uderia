# src/trusted_data_agent/agent/execution_service.py
import logging
import json
import re
import asyncio
import uuid
from datetime import datetime, timezone

from trusted_data_agent.agent.executor import PlanExecutor
from trusted_data_agent.agent.session_name_generator import generate_session_name_with_events
from trusted_data_agent.core.config import APP_STATE
from trusted_data_agent.core import session_manager
from trusted_data_agent.extensions.runner import ExtensionRunner, serialize_extension_results
from trusted_data_agent.extensions.manager import get_extension_manager
from trusted_data_agent.extensions.models import ExtensionContext
from trusted_data_agent.extensions.db import get_user_activated_extensions

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


async def _run_extensions(
    extension_specs: list,
    final_payload: dict,
    user_input: str,
    session_id: str,
    user_uuid: str,
    event_handler,
    llm_config_id: str = None,
) -> tuple:
    """
    Execute post-processing extensions after the LLM answer is complete.

    Builds an ExtensionContext from the final payload and runs extensions
    serially via ExtensionRunner. Only activated extensions are executed;
    activation default_param is used when query doesn't provide one.

    Returns (serialized_results, collected_events) tuple, or (None, []).
    """
    try:
        manager = get_extension_manager()
        runner = ExtensionRunner(manager)

        # Look up user's activated extensions keyed by activation_name
        activated = get_user_activated_extensions(user_uuid)
        activated_lookup = {a["activation_name"]: a for a in activated}

        # Filter to activated-only, resolve extension_id, merge default params
        resolved_specs = []
        for spec in extension_specs:
            name = spec.get("name", "")  # activation_name from frontend
            activation = activated_lookup.get(name)

            if activation is None:
                app_logger.warning(
                    f"Extension '{name}' not activated for user {user_uuid} — skipping"
                )
                continue

            # Query param overrides activation default_param
            param = spec.get("param") or activation.get("default_param")
            resolved_specs.append({
                "name": name,                                # activation_name (for result keys)
                "extension_id": activation["extension_id"],  # actual extension to execute
                "param": param,
            })

        if not resolved_specs:
            app_logger.info("No activated extensions to run after filtering")
            return None, []

        # Build rich context from the final answer payload
        context = ExtensionContext(
            answer_text=final_payload.get("final_answer_text") or final_payload.get("final_summary_text") or "",
            answer_html=final_payload.get("final_answer") or final_payload.get("html_response") or "",
            original_query=user_input,
            clean_query=user_input,  # Already stripped by frontend
            session_id=session_id,
            turn_id=final_payload.get("turn_id", 0),
            task_id=final_payload.get("task_id"),
            profile_tag=final_payload.get("profile_tag"),
            profile_type=final_payload.get("profile_type", "tool_enabled"),
            provider=final_payload.get("provider"),
            model=final_payload.get("model"),
            turn_input_tokens=final_payload.get("turn_input_tokens", 0),
            turn_output_tokens=final_payload.get("turn_output_tokens", 0),
            total_input_tokens=final_payload.get("total_input_tokens", 0),
            total_output_tokens=final_payload.get("total_output_tokens", 0),
            execution_trace=final_payload.get("execution_trace", []),
            tools_used=final_payload.get("tools_used", []),
            collected_data=final_payload.get("collected_data", []),
            # LLM config for LLMExtension support
            user_uuid=user_uuid,
            llm_config_id=llm_config_id,
        )

        # Build GenieContext for genie coordinator profiles
        if final_payload.get("genie_coordination"):
            from trusted_data_agent.extensions.models import GenieContext, GenieChildResult

            genie_events = final_payload.get("genie_events", [])

            # Extract available_profiles from genie_coordination_start event
            available_profiles = []
            for evt in genie_events:
                if evt.get("type") == "genie_coordination_start":
                    available_profiles = evt.get("payload", {}).get("slave_profiles", [])
                    break

            # Extract child queries from genie_slave_invoked and results from genie_slave_completed
            child_queries = {}   # tag → {query, profile_id}
            child_results = {}   # tag → GenieChildResult
            for evt in genie_events:
                payload = evt.get("payload", {})
                evt_type = evt.get("type")

                if evt_type == "genie_slave_invoked":
                    child_queries[payload.get("profile_tag")] = {
                        "query": payload.get("query", ""),
                        "profile_id": payload.get("profile_id", ""),
                    }
                elif evt_type == "genie_slave_completed":
                    tag = payload.get("profile_tag", "")
                    invoked = child_queries.get(tag, {})
                    # Resolve profile_type from available_profiles
                    child_profile_type = "unknown"
                    for ap in available_profiles:
                        if ap.get("tag") == tag:
                            child_profile_type = ap.get("profile_type", "unknown")
                            break
                    child_results[tag] = GenieChildResult(
                        profile_tag=tag,
                        profile_id=invoked.get("profile_id", ""),
                        profile_type=child_profile_type,
                        session_id=payload.get("slave_session_id", ""),
                        query=invoked.get("query", ""),
                        response=payload.get("result", ""),
                        duration_ms=payload.get("duration_ms", 0),
                        success=payload.get("success", False),
                        error=payload.get("error"),
                    )

            # Extract coordination metrics
            coordination_duration_ms = 0
            coordinator_llm_steps = 0
            profiles_invoked = []
            for evt in genie_events:
                payload = evt.get("payload", {})
                if evt.get("type") == "genie_coordination_complete":
                    coordination_duration_ms = payload.get("total_duration_ms", 0)
                    profiles_invoked = payload.get("profiles_used", [])
                elif evt.get("type") == "genie_llm_step":
                    coordinator_llm_steps += 1

            context.genie = GenieContext(
                coordinator_response=final_payload.get("final_answer_text") or "",
                coordinator_profile_tag=final_payload.get("profile_tag", "GENIE"),
                available_profiles=available_profiles,
                profiles_invoked=profiles_invoked,
                child_results=child_results,
                slave_sessions=final_payload.get("slave_sessions_used", {}),
                coordination_events=genie_events,
                coordination_duration_ms=coordination_duration_ms,
                coordinator_llm_steps=coordinator_llm_steps,
            )

            app_logger.info(
                f"Built GenieContext: {len(child_results)} child results, "
                f"{len(profiles_invoked)} profiles invoked, "
                f"{coordinator_llm_steps} LLM steps"
            )

        # Wrap event_handler to collect extension lifecycle events for persistence
        collected_events = []

        async def collecting_event_handler(data, event_type):
            """Forward events AND capture extension lifecycle events."""
            await event_handler(data, event_type)
            # Capture extension-related events for session persistence
            evt_type = data.get("type") if isinstance(data, dict) else None
            if evt_type in ("extension_start", "extension_complete") or event_type == "extension_results":
                collected_events.append({
                    "type": evt_type or event_type,
                    "payload": data.get("payload", data) if isinstance(data, dict) else data,
                })

        app_logger.info(f"Running {len(resolved_specs)} extension(s): {[s.get('name') for s in resolved_specs]}")
        results = await runner.run(resolved_specs, context, collecting_event_handler)
        serialized = serialize_extension_results(results)

        # Emit combined extension_results event for frontend
        await collecting_event_handler(
            {"type": "extension_results", "payload": serialized},
            "extension_results",
        )

        return serialized, collected_events

    except Exception as e:
        app_logger.error(f"Extension execution failed: {e}", exc_info=True)
        return None, []


async def _persist_extension_results(
    ext_results: dict,
    ext_events: list,
    user_uuid: str,
    session_id: str,
    event_handler,
    prior_turn_input: int = 0,
    prior_turn_output: int = 0,
    provider: str = None,
    model: str = None,
):
    """
    Persist extension results to the session file and emit cost events if needed.

    Aggregates extension token/cost usage across all results. If any extension
    consumed tokens (LLM-calling extensions), emits a token_update event
    and updates session totals. Turn tokens include prior execution tokens
    (from the main LLM calls) plus extension tokens for accurate KPI display.
    """
    # Aggregate extension token costs
    total_ext_input = sum(r.get("extension_input_tokens", 0) for r in ext_results.values())
    total_ext_output = sum(r.get("extension_output_tokens", 0) for r in ext_results.values())

    # If extensions consumed tokens, update session totals and emit token_update
    if total_ext_input > 0 or total_ext_output > 0:
        await session_manager.update_token_count(
            user_uuid, session_id, total_ext_input, total_ext_output
        )

        current_session = await session_manager.get_session(user_uuid, session_id)
        if current_session:
            total_ext_cost = sum(r.get("extension_cost_usd", 0) for r in ext_results.values())

            # Fallback: calculate cost if extensions didn't (e.g. CostManager failed in call_llm)
            if total_ext_cost == 0 and provider and model:
                try:
                    from trusted_data_agent.core.cost_manager import CostManager
                    cost_mgr = CostManager()
                    total_ext_cost = cost_mgr.calculate_cost(
                        provider, model, total_ext_input, total_ext_output
                    )
                    # Backfill cost into extension results for session persistence
                    for r in ext_results.values():
                        ext_in = r.get("extension_input_tokens", 0)
                        ext_out = r.get("extension_output_tokens", 0)
                        if ext_in > 0 or ext_out > 0:
                            r["extension_cost_usd"] = cost_mgr.calculate_cost(
                                provider, model, ext_in, ext_out
                            )
                    # Backfill cost into extension_complete events for reload renderer
                    for evt in ext_events:
                        if evt.get("type") == "extension_complete":
                            payload = evt.get("payload", {})
                            ext_name = payload.get("name")
                            if ext_name and ext_name in ext_results:
                                payload["cost_usd"] = ext_results[ext_name].get("extension_cost_usd", 0)
                    app_logger.info(f"Extension cost fallback: ${total_ext_cost:.6f}")
                except Exception as e:
                    app_logger.warning(f"Extension cost fallback failed: {e}")

            await event_handler({
                "statement_input": total_ext_input,
                "statement_output": total_ext_output,
                "turn_input": prior_turn_input + total_ext_input,
                "turn_output": prior_turn_output + total_ext_output,
                "total_input": current_session.get("input_tokens", 0),
                "total_output": current_session.get("output_tokens", 0),
                "call_id": "extensions",
                "cost_usd": total_ext_cost,
            }, "token_update")

            app_logger.info(
                f"Extension token update: {total_ext_input} in / {total_ext_output} out "
                f"(turn cumulative: {prior_turn_input + total_ext_input} in / "
                f"{prior_turn_output + total_ext_output} out, "
                f"cost: ${total_ext_cost:.6f})"
            )

    # Persist to session file (post-append to already-saved turn)
    await session_manager.append_extension_results_to_turn(
        user_uuid=user_uuid,
        session_id=session_id,
        extension_results=ext_results,
        extension_events=ext_events,
        extension_input_tokens=total_ext_input,
        extension_output_tokens=total_ext_output,
    )


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
    attachments: list = None,  # Document upload attachments [{file_id, filename, ...}]
    extension_specs: list = None,  # Post-processing extensions [{"name": "json", "param": null}]
    skill_specs: list = None,  # Pre-processing skills [{"name": "sql-expert", "param": "strict"}]
    canvas_context: dict = None,  # Canvas bidirectional context {title, language, content, modified}
    force_profile_type: str = None  # Override profile type detection (e.g. "tool_enabled" for KG constructor)
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
                attachments=attachments,
                extension_specs=extension_specs,
                skill_specs=skill_specs
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

        # --- SKILL RESOLUTION: Resolve pre-processing skills before executor/genie ---
        # Two sources: (1) profile auto-assigned skills, (2) manual per-query skills
        # Runs for ALL profile types (tool_enabled, rag_focused, llm_only, genie)
        skill_result = None
        try:
            from trusted_data_agent.skills.manager import get_skill_manager
            from trusted_data_agent.skills.models import SkillSpec, SkillResult
            from trusted_data_agent.skills.settings import is_skill_available
            skill_manager = get_skill_manager()
            resolved_specs = []
            seen_skill_ids = set()

            # Build profile-level skill lookup (enabled + active flags)
            profile_skills = {}
            if active_profile:
                for entry in active_profile.get("skillsConfig", {}).get("skills", []):
                    sid = entry.get("id", "")
                    if sid:
                        profile_skills[sid] = entry

            # --- (1) AUTO-SKILLS: Profile skills with active=true ---
            for skill_id, entry in profile_skills.items():
                if entry.get("active") and is_skill_available(skill_id) and skill_id not in seen_skill_ids:
                    resolved_specs.append(SkillSpec(
                        name=skill_id,
                        param=entry.get("param"),
                    ))
                    seen_skill_ids.add(skill_id)
                    app_logger.debug(f"Auto-skill from profile: {skill_id}")

            # --- (2) MANUAL SKILLS: #hashtag skills checked against profile enabled list ---
            if skill_specs:
                for spec in skill_specs:
                    skill_id = spec.get("name", "")
                    profile_entry = profile_skills.get(skill_id)

                    if not profile_entry or not profile_entry.get("enabled", False):
                        app_logger.warning(f"Skill '{skill_id}' not enabled in profile — skipping")
                        continue

                    if not is_skill_available(skill_id):
                        app_logger.warning(f"Skill '{skill_id}' is disabled by admin — skipping")
                        continue

                    param = spec.get("param") or profile_entry.get("param")

                    if skill_id in seen_skill_ids:
                        # Manual overrides auto-skill param for same skill_id
                        resolved_specs = [
                            SkillSpec(name=skill_id, param=param) if s.name == skill_id else s
                            for s in resolved_specs
                        ]
                        app_logger.debug(f"Manual skill '{skill_id}' overrides auto-skill param")
                    else:
                        resolved_specs.append(SkillSpec(name=skill_id, param=param))
                        seen_skill_ids.add(skill_id)

            # --- Resolve all skills through SkillManager ---
            if resolved_specs:
                skill_result = skill_manager.resolve_skills(resolved_specs)
                if skill_result and skill_result.has_content:
                    applied_list = skill_result.to_applied_list()
                    await event_handler({
                        "type": "skills_applied",
                        "payload": {
                            "skills": applied_list,
                            "total_estimated_tokens": skill_result.total_estimated_tokens,
                        }
                    }, "notification")
                    app_logger.info(
                        f"Skills applied: {[s['name'] for s in applied_list]} "
                        f"(~{skill_result.total_estimated_tokens} tokens)"
                    )
        except Exception as e:
            app_logger.error(f"Failed to resolve skills: {e}", exc_info=True)
            skill_result = None

        # Route Genie profiles to Genie coordinator
        if active_profile_type == "genie" and active_profile:
            app_logger.info(f"🔮 Detected Genie profile '{active_profile.get('tag')}' - routing to Genie coordinator")
            from trusted_data_agent.agent.engines.coordinate_engine import CoordinateEngine
            final_result_payload = await CoordinateEngine().execute_genie(
                user_uuid=user_uuid,
                session_id=session_id,
                user_input=user_input,
                event_handler=event_handler,
                genie_profile=active_profile,
                task_id=task_id,
                disabled_history=disabled_history,  # Pass history context flag
                is_session_primer=is_session_primer,  # Pass session primer flag
                attachments=attachments,  # Pass document upload attachments
                skill_result=skill_result,  # Pass resolved skills to genie coordinator
            )

            return final_result_payload
        # --- END GENIE PROFILE DETECTION ---

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
            plan_to_execute=plan_to_execute,
            is_replay=is_replay,
            task_id=task_id,
            profile_override_id=profile_override_id,
            event_handler=event_handler,
            is_session_primer=is_session_primer,
            attachments=attachments,
            skill_result=skill_result,
            canvas_context=canvas_context,
            force_profile_type=force_profile_type,
        )

        async for event_str in executor.run():
            event_data, event_type = _parse_sse_event(event_str)
            await event_handler(event_data, event_type)
            if event_type == "final_answer":
                final_result_payload = event_data

        # --- EXTENSION EXECUTION (shared by all non-genie profile types) ---
        if extension_specs and final_result_payload:
            _prior_turn_input = 0
            _prior_turn_output = 0
            _ext_provider = None
            _ext_model = None
            try:
                _session_data = await session_manager.get_session(user_uuid, session_id)
                if _session_data:
                    _wh = _session_data.get("last_turn_data", {}).get("workflow_history", [])
                    if _wh:
                        _latest = _wh[-1]
                        _prior_turn_input = _latest.get("turn_input_tokens", 0) or 0
                        _prior_turn_output = _latest.get("turn_output_tokens", 0) or 0
                        _ext_provider = _latest.get("provider")
                        _ext_model = _latest.get("model")
            except Exception:
                pass

            ext_results, ext_events = await _run_extensions(
                extension_specs=extension_specs,
                final_payload=final_result_payload,
                user_input=user_input,
                session_id=session_id,
                user_uuid=user_uuid,
                event_handler=event_handler,
                llm_config_id=active_profile.get("llmConfigurationId") if active_profile else None,
            )
            if ext_results:
                final_result_payload["extension_results"] = ext_results
                await _persist_extension_results(
                    ext_results, ext_events, user_uuid, session_id, event_handler,
                    prior_turn_input=_prior_turn_input,
                    prior_turn_output=_prior_turn_output,
                    provider=_ext_provider,
                    model=_ext_model,
                )

    except Exception as e:
        app_logger.error(f"An unhandled error occurred in the agent execution service for user {user_uuid}, session {session_id}: {e}", exc_info=True)
        await event_handler({"error": str(e)}, "error")
        raise

    return final_result_payload

