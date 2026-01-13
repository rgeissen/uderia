"""
Genie Profile Coordinator
==========================

Provides LangChain-based coordination for Genie profiles.
Genie profiles orchestrate multiple slave profiles (sessions) to answer complex queries.

Architecture:
- GenieCoordinator: Main class that builds and executes a LangChain agent
- SlaveSessionTool: LangChain tool wrapper for slave session REST calls
- Session context is reused when the same slave profile is called multiple times

Usage:
    from trusted_data_agent.agent.genie_coordinator import GenieCoordinator

    coordinator = GenieCoordinator(
        genie_profile=profile,
        slave_profiles=slave_profiles,
        user_uuid=user_uuid,
        parent_session_id=session_id,
        auth_token=token,
        llm_instance=langchain_llm
    )

    result = await coordinator.execute("Your complex question here")
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Callable

import httpx
from pydantic import Field

from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage

from trusted_data_agent.agent.profile_prompt_resolver import ProfilePromptResolver

logger = logging.getLogger(__name__)

# Module-level session cache (shared across all SlaveSessionTool instances)
# Using module-level dict avoids Pydantic treating it as a private attribute
_slave_session_cache: Dict[str, str] = {}

# Module-level event callbacks (keyed by parent_session_id)
_event_callbacks: Dict[str, Callable[[str, Dict], None]] = {}


class SlaveSessionTool(BaseTool):
    """
    LangChain tool that wraps REST calls to a slave session.

    Each slave profile becomes a separate tool instance. When invoked,
    it creates or reuses a slave session and executes the query through
    the existing Uderia REST API.
    """
    name: str = Field(description="Tool name like invoke_CHAT")
    description: str = Field(description="Description of what this profile does")
    profile_id: str = Field(description="Profile ID for this slave")
    profile_tag: str = Field(description="Profile tag (e.g., CHAT, RAG)")
    user_uuid: str = Field(description="User UUID who owns the sessions")
    parent_session_id: str = Field(description="Parent Genie session ID")
    base_url: str = Field(default="http://localhost:5050", description="API base URL")
    auth_token: str = Field(description="Authentication token for API calls")

    class Config:
        arbitrary_types_allowed = True

    def _emit_event(self, event_type: str, payload: dict):
        """Emit event via callback if configured."""
        callback = _event_callbacks.get(self.parent_session_id)
        if callback:
            try:
                callback(event_type, payload)
            except Exception as e:
                logger.warning(f"SlaveSessionTool event callback error: {e}")

    def _run(self, query: str) -> str:
        """Synchronous run - not implemented, use async."""
        raise NotImplementedError("Use async _arun instead")

    async def _arun(self, query: str) -> str:
        """Execute query via slave session with context reuse."""
        start_time = time.time()

        # Emit slave invoked event
        self._emit_event("genie_slave_invoked", {
            "profile_tag": self.profile_tag,
            "profile_id": self.profile_id,
            "query": query[:100] if query else "",
            "session_id": self.parent_session_id
        })

        try:
            session_id = await self._get_or_create_slave_session()

            # Update event with session ID
            self._emit_event("genie_slave_progress", {
                "profile_tag": self.profile_tag,
                "slave_session_id": session_id,
                "status": "executing",
                "message": "Processing query...",
                "session_id": self.parent_session_id
            })

            result = await self._execute_and_poll(session_id, query)

            # Emit completion event
            duration_ms = int((time.time() - start_time) * 1000)
            self._emit_event("genie_slave_completed", {
                "profile_tag": self.profile_tag,
                "slave_session_id": session_id,
                "result_preview": result[:200] if result else "",
                "duration_ms": duration_ms,
                "success": True,
                "session_id": self.parent_session_id
            })

            return result
        except Exception as e:
            logger.error(f"SlaveSessionTool error for @{self.profile_tag}: {e}", exc_info=True)

            # Emit error event
            duration_ms = int((time.time() - start_time) * 1000)
            self._emit_event("genie_slave_completed", {
                "profile_tag": self.profile_tag,
                "duration_ms": duration_ms,
                "success": False,
                "error": str(e),
                "session_id": self.parent_session_id
            })

            return f"Error invoking @{self.profile_tag}: {str(e)}"

    async def _get_or_create_slave_session(self) -> str:
        """Reuse existing session or create new one."""
        cache_key = f"{self.parent_session_id}:{self.profile_id}"

        if cache_key in _slave_session_cache:
            logger.debug(f"Reusing existing slave session for @{self.profile_tag}")
            return _slave_session_cache[cache_key]

        logger.info(f"Creating new slave session for @{self.profile_tag}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/sessions",
                headers={"Authorization": f"Bearer {self.auth_token}"},
                json={
                    "profile_id": self.profile_id,
                    "genie_parent_session_id": self.parent_session_id,
                    "genie_slave_profile_id": self.profile_id
                }
            )

            if response.status_code != 201:
                raise Exception(f"Failed to create slave session: {response.status_code} - {response.text}")

            data = response.json()
            session_id = data.get("session_id")

            if not session_id:
                raise Exception(f"No session_id in response: {data}")

            _slave_session_cache[cache_key] = session_id
            logger.info(f"Created slave session {session_id} for @{self.profile_tag}")

            return session_id

    async def _execute_and_poll(self, session_id: str, query: str) -> str:
        """Submit query and poll for completion."""
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Submit query
            response = await client.post(
                f"{self.base_url}/api/v1/sessions/{session_id}/query",
                headers={"Authorization": f"Bearer {self.auth_token}"},
                json={
                    "prompt": query,
                    "profile_id": self.profile_id
                }
            )

            if response.status_code != 202:
                raise Exception(f"Failed to submit query: {response.status_code} - {response.text}")

            data = response.json()
            task_id = data.get("task_id")

            if not task_id:
                raise Exception(f"No task_id in response: {data}")

            logger.info(f"Submitted query to @{self.profile_tag}, task_id: {task_id}")

            # Poll for completion
            max_polls = 300  # 5 minutes max
            poll_interval = 1.0

            for _ in range(max_polls):
                status_response = await client.get(
                    f"{self.base_url}/api/v1/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {self.auth_token}"}
                )

                if status_response.status_code != 200:
                    logger.warning(f"Task status check failed: {status_response.status_code}")
                    await asyncio.sleep(poll_interval)
                    continue

                status_data = status_response.json()
                status = status_data.get("status")

                if status in ("completed", "complete"):
                    result = status_data.get("result", {})
                    # Try both field names - REST API uses final_answer, SSE uses final_response
                    final_response = result.get("final_response") or result.get("final_answer") or result.get("final_answer_text", "")
                    logger.info(f"@{self.profile_tag} completed successfully")
                    return final_response

                elif status in ("failed", "error"):
                    error = status_data.get("error", "Unknown error")
                    logger.error(f"@{self.profile_tag} task failed: {error}")
                    return f"Error from @{self.profile_tag}: {error}"

                await asyncio.sleep(poll_interval)

            return f"Timeout waiting for @{self.profile_tag} response"


class GenieCoordinator:
    """
    Builds and executes a LangChain agent that coordinates slave sessions.

    The coordinator:
    1. Creates tools from slave profiles
    2. Loads the coordinator system prompt (with profile-level overrides)
    3. Builds a LangChain agent executor
    4. Executes queries and synthesizes results
    5. Emits real-time events for UI feedback (if event_callback provided)
    """

    def __init__(
        self,
        genie_profile: Dict[str, Any],
        slave_profiles: List[Dict[str, Any]],
        user_uuid: str,
        parent_session_id: str,
        auth_token: str,
        llm_instance: Any,  # LangChain-compatible LLM
        base_url: str = "http://localhost:5050",
        event_callback: Optional[Callable[[str, Dict], None]] = None
    ):
        """
        Initialize the Genie Coordinator.

        Args:
            genie_profile: The Genie profile configuration
            slave_profiles: List of slave profile configurations
            user_uuid: User UUID who owns the sessions
            parent_session_id: The parent Genie session ID
            auth_token: Authentication token for REST API calls
            llm_instance: LangChain-compatible LLM instance
            base_url: Base URL for REST API (default localhost:5050)
            event_callback: Optional callback for real-time UI events.
                           Signature: (event_type: str, payload: dict) -> None
        """
        self.genie_profile = genie_profile
        self.slave_profiles = slave_profiles
        self.user_uuid = user_uuid
        self.parent_session_id = parent_session_id
        self.auth_token = auth_token
        self.llm_instance = llm_instance
        self.base_url = base_url
        self.event_callback = event_callback

        # Collect events during execution for plan reload
        self.collected_events = []

        # Track LLM call count for step naming
        self.llm_call_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # Register event callback for this parent session
        # Wrap the callback to also collect events from slave tools
        if event_callback:
            def collecting_callback(event_type: str, payload: dict):
                # Collect event for plan reload
                self.collected_events.append({
                    "type": event_type,
                    "payload": dict(payload)
                })
                # Forward to original callback
                event_callback(event_type, payload)
            _event_callbacks[parent_session_id] = collecting_callback
        else:
            # Even without an external callback, collect events for plan reload
            def collecting_only_callback(event_type: str, payload: dict):
                self.collected_events.append({
                    "type": event_type,
                    "payload": dict(payload)
                })
            _event_callbacks[parent_session_id] = collecting_only_callback

        # Build tools and agent
        self.tools = self._build_tools()
        self.agent_executor = self._build_agent()

        logger.info(f"GenieCoordinator initialized with {len(self.tools)} slave tools")

    def _emit_event(self, event_type: str, payload: dict):
        """Emit event via callback if configured. Events are collected via the registered callback."""
        # Events are collected via _event_callbacks[parent_session_id] which wraps
        # the original callback to also collect events for plan reload
        callback = _event_callbacks.get(self.parent_session_id)
        if callback:
            try:
                callback(event_type, payload)
            except Exception as e:
                logger.warning(f"GenieCoordinator event callback error: {e}")

    def _build_tools(self) -> List[SlaveSessionTool]:
        """Create a LangChain tool for each slave profile."""
        tools = []

        for profile in self.slave_profiles:
            profile_id = profile.get("id")
            profile_tag = profile.get("tag", "UNKNOWN")
            profile_name = profile.get("name", profile_tag)
            profile_description = profile.get("description", "")
            profile_type = profile.get("profile_type", "tool_enabled")

            # Build tool description
            description = self._build_tool_description(profile)

            tool = SlaveSessionTool(
                name=f"invoke_{profile_tag}",
                description=description,
                profile_id=profile_id,
                profile_tag=profile_tag,
                user_uuid=self.user_uuid,
                parent_session_id=self.parent_session_id,
                base_url=self.base_url,
                auth_token=self.auth_token
            )

            tools.append(tool)

            logger.debug(f"Created tool: invoke_{profile_tag}")

        return tools

    def _build_tool_description(self, profile: Dict[str, Any]) -> str:
        """
        Build a descriptive tool description for LLM routing decisions.

        Enhanced format includes profile name alongside tag for better context:
        @TAG (Profile Name): Description. Type: profile_type
        """
        profile_tag = profile.get("tag", "UNKNOWN")
        profile_name = profile.get("name", "")
        profile_type = profile.get("profile_type", "tool_enabled")
        description = profile.get("description", "General purpose profile")

        # Format: @TAG (Name): Description. Type: type
        # Include name only if it's different from tag and not empty
        if profile_name and profile_name.upper() != profile_tag.upper():
            return f"@{profile_tag} ({profile_name}): {description}. Type: {profile_type}"
        else:
            return f"@{profile_tag}: {description}. Type: {profile_type}"

    def _build_agent(self):
        """Build the LangGraph react agent with coordinator prompt."""
        # Load prompt from database (supports profile-level overrides)
        resolver = ProfilePromptResolver(profile_id=self.genie_profile.get("id"))
        system_prompt = resolver.get_genie_coordinator_prompt()

        if not system_prompt:
            # Fallback to hardcoded default
            logger.warning("Could not load GENIE_COORDINATOR_PROMPT from database, using fallback")
            system_prompt = self._get_fallback_prompt()

        # Inject available profiles into the prompt
        tool_descriptions = "\n".join([
            f"- {self._build_tool_description(p)}"
            for p in self.slave_profiles
        ])
        system_prompt = system_prompt.replace("{available_profiles}", tool_descriptions)

        # Store system prompt for use in execute()
        self.system_prompt = system_prompt

        # Create LangGraph react agent (new API in langchain v1 / langgraph)
        return create_react_agent(
            model=self.llm_instance,
            tools=self.tools
        )

    def _get_fallback_prompt(self) -> str:
        """Get fallback coordinator prompt if database prompt unavailable."""
        return """You are a Genie Coordinator that orchestrates specialized AI profiles to answer complex queries.

Your available profiles are tools that invoke specialized sessions:
{available_profiles}

---
### Coordination Rules

1. **ANALYZE** the user's question to determine which profile(s) are best suited to answer it.

2. **ROUTE** the query (or decomposed sub-queries) to appropriate profiles using the invoke_* tools.
   - For database queries or data analysis: Use tool-enabled profiles
   - For conversational explanation: Use llm_only profiles
   - For knowledge lookups: Use rag_focused profiles
   - For complex questions: Decompose and route to multiple profiles

3. **SYNTHESIZE** the results from profile invocations into a coherent final response.

4. **SINGLE PROFILE OPTIMIZATION**: If a single profile can fully answer the question, use only that profile.

---
### Important Behaviors

- Each tool invocation creates or reuses a real session visible in the UI
- Subsequent calls to the same profile reuse that session's context
- Be specific in your sub-queries to get targeted results
- Always briefly explain your routing decision before invoking tools

---
### Response Format

After gathering information from profiles, provide a synthesized answer that:
- Combines insights from all consulted profiles
- Presents a unified, coherent response
- Credits which profiles contributed to the answer (if multiple were used)
"""

    async def execute(self, query: str) -> Dict[str, Any]:
        """
        Execute the coordinator logic for a user query.

        Args:
            query: The user's question

        Returns:
            Dict with coordinator_response and metadata
        """
        start_time = time.time()
        logger.info(f"GenieCoordinator executing query: {query[:100]}...")

        # Emit coordination start event
        self._emit_event("genie_coordination_start", {
            "genie_session_id": self.parent_session_id,
            "session_id": self.parent_session_id,
            "query": query[:200] if query else "",
            "slave_profiles": [
                {
                    "id": p.get("id"),
                    "tag": p.get("tag", "UNKNOWN"),
                    "name": p.get("name", "")
                }
                for p in self.slave_profiles
            ]
        })

        try:
            # Build input messages with system prompt
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=query)
            ]

            # Reset LLM call tracking for this execution
            self.llm_call_count = 0
            self.total_input_tokens = 0
            self.total_output_tokens = 0

            output = ""
            tools_used = []

            # Use astream_events to track LLM calls with token usage
            async for event in self.agent_executor.astream_events(
                {"messages": messages},
                version="v2"
            ):
                event_kind = event.get("event", "")
                event_name = event.get("name", "")
                event_data = event.get("data", {})

                # Track token usage from LLM calls
                # Some providers emit on_llm_end, others emit on_chat_model_end
                if event_kind in ("on_llm_end", "on_chat_model_end"):
                    llm_output = event_data.get("output", {})

                    # Extract token usage
                    input_tokens = 0
                    output_tokens = 0

                    if hasattr(llm_output, 'usage_metadata') and llm_output.usage_metadata:
                        usage = llm_output.usage_metadata
                        if isinstance(usage, dict):
                            input_tokens = usage.get('input_tokens', 0) or 0
                            output_tokens = usage.get('output_tokens', 0) or 0
                        else:
                            input_tokens = getattr(usage, 'input_tokens', 0) or 0
                            output_tokens = getattr(usage, 'output_tokens', 0) or 0

                    self.total_input_tokens += input_tokens
                    self.total_output_tokens += output_tokens

                    # Emit LLM step event
                    self.llm_call_count += 1

                    # Determine step type based on output
                    has_tool_calls = hasattr(llm_output, 'tool_calls') and llm_output.tool_calls
                    if self.llm_call_count == 1:
                        step_name = "Routing Decision" if has_tool_calls else "Response Generation"
                    else:
                        step_name = "Response Synthesis" if not has_tool_calls else f"Routing Decision #{self.llm_call_count}"

                    self._emit_event("genie_llm_step", {
                        "step_number": self.llm_call_count,
                        "step_name": step_name,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "session_id": self.parent_session_id
                    })

                    logger.info(f"[Genie] LLM Step {self.llm_call_count} ({step_name}): {input_tokens} in / {output_tokens} out")

                # Capture final output from chain end
                elif event_kind == "on_chain_end" and event_name == "LangGraph":
                    chain_output = event_data.get("output", {})
                    if isinstance(chain_output, dict) and "messages" in chain_output:
                        # Extract final AI message for response
                        for msg in reversed(chain_output["messages"]):
                            if hasattr(msg, 'content') and hasattr(msg, 'type'):
                                if msg.type == 'ai' and msg.content:
                                    output = msg.content
                                    break
                                # Track tool calls
                                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                    for tc in msg.tool_calls:
                                        tool_name = tc.get('name', '') if isinstance(tc, dict) else getattr(tc, 'name', '')
                                        if tool_name and tool_name not in tools_used:
                                            tools_used.append(tool_name)

            # Emit synthesis start event
            self._emit_event("genie_synthesis_start", {
                "profiles_consulted": tools_used,
                "session_id": self.parent_session_id
            })

            # Calculate duration
            total_duration_ms = int((time.time() - start_time) * 1000)

            # Emit coordination complete event
            self._emit_event("genie_coordination_complete", {
                "total_duration_ms": total_duration_ms,
                "profiles_used": tools_used,
                "success": True,
                "session_id": self.parent_session_id,
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens
            })

            logger.info(f"GenieCoordinator completed. Tools used: {tools_used}")

            # Filter slave_sessions to only include sessions for tools actually used in this turn
            # This ensures per-turn tracking instead of returning all accumulated sessions
            turn_slave_sessions = {}
            for tool_name in tools_used:
                # Tool names are invoke_{profile_tag}, extract the tag
                profile_tag = tool_name.replace("invoke_", "") if tool_name.startswith("invoke_") else tool_name
                # Find the profile_id for this tag
                for profile in self.slave_profiles:
                    if profile.get("tag") == profile_tag:
                        profile_id = profile.get("id")
                        cache_key = f"{self.parent_session_id}:{profile_id}"
                        if cache_key in _slave_session_cache:
                            # Store with profile_tag as key for frontend display
                            turn_slave_sessions[profile_tag] = _slave_session_cache[cache_key]
                        break

            return {
                "coordinator_response": output,
                "tools_used": tools_used,
                "slave_sessions": turn_slave_sessions,
                "genie_events": self.collected_events,  # For plan reload
                "success": True
            }

        except Exception as e:
            logger.error(f"GenieCoordinator execution error: {e}", exc_info=True)

            # Calculate duration
            total_duration_ms = int((time.time() - start_time) * 1000)

            # Emit error completion event
            self._emit_event("genie_coordination_complete", {
                "total_duration_ms": total_duration_ms,
                "profiles_used": [],
                "success": False,
                "error": str(e),
                "session_id": self.parent_session_id
            })

            return {
                "coordinator_response": f"Error during coordination: {str(e)}",
                "tools_used": [],
                "slave_sessions": {},  # No sessions for failed turn
                "genie_events": self.collected_events,  # For plan reload (includes error event)
                "success": False,
                "error": str(e)
            }

    def get_used_slave_sessions(self) -> Dict[str, str]:
        """Get map of profile_id -> session_id for all used slave sessions."""
        return dict(_slave_session_cache)

    def load_existing_slave_sessions(self, existing_sessions: List[Dict[str, Any]]):
        """
        Pre-populate the session cache with existing slave sessions from database.

        This preserves conversational context across multiple queries by reusing
        existing slave sessions instead of creating new ones.

        Args:
            existing_sessions: List of session records from get_genie_slave_sessions()
                Each record should have 'slave_session_id' and 'slave_profile_id'
        """
        for session_record in existing_sessions:
            slave_session_id = session_record.get('slave_session_id')
            slave_profile_id = session_record.get('slave_profile_id')

            if slave_session_id and slave_profile_id:
                cache_key = f"{self.parent_session_id}:{slave_profile_id}"
                _slave_session_cache[cache_key] = slave_session_id
                logger.info(f"Loaded existing slave session {slave_session_id} for profile {slave_profile_id}")

        logger.info(f"Pre-loaded {len(existing_sessions)} existing slave sessions into cache")

    def clear_session_cache(self):
        """Clear the session cache (useful for testing)."""
        _slave_session_cache = {}
