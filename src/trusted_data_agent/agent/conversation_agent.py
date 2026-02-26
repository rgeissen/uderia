"""
Conversation Agent Executor
===========================

Provides a LangChain-based agent for conversational tool use with visual cards.

This module implements a simpler, more conversational approach to MCP tool usage
compared to the multi-phase planner/executor architecture. It uses LangChain's
native tool-calling capabilities for efficient, single-loop agent execution.

Architecture:
- ConversationAgentExecutor: Main class that builds and executes a LangChain agent
- Emits SSE events for real-time UI updates (visual tool cards)
- Supports streaming execution with intermediate step tracking

Usage:
    from trusted_data_agent.agent.conversation_agent import ConversationAgentExecutor

    executor = ConversationAgentExecutor(
        profile=profile_config,
        user_uuid=user_uuid,
        session_id=session_id,
        llm_instance=langchain_llm,
        mcp_tools=tools,
        event_callback=emit_sse_event
    )

    result = await executor.execute("Show me all products with low inventory")
"""

import asyncio
import json
import logging
import re
import time
from typing import Dict, List, Any, Optional, Callable

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from trusted_data_agent.agent.profile_prompt_resolver import ProfilePromptResolver

logger = logging.getLogger(__name__)

# LLM conversation loggers for debugging/auditing
llm_logger = logging.getLogger("llm_conversation")
llm_history_logger = logging.getLogger("llm_conversation_history")


class ConversationAgentExecutor:
    """
    LangChain-based agent for conversational tool use with visual cards.

    This executor provides a simpler alternative to the planner/executor architecture,
    using LangChain's native tool-calling for a more natural conversational flow.

    Features:
    - Single-loop ReAct agent (vs multi-phase planning)
    - Real-time SSE events for visual tool cards
    - Native function calling (OpenAI, Anthropic, Google)
    - Profile-aware tool filtering
    - Streaming execution support
    """

    def __init__(
        self,
        profile: Dict[str, Any],
        user_uuid: str,
        session_id: str,
        llm_instance: Any,
        mcp_tools: List[Any],
        event_callback: Optional[Callable[[str, Dict], None]] = None,
        async_event_handler: Optional[Callable] = None,
        max_iterations: int = 5,
        conversation_history: Optional[List[Dict]] = None,
        knowledge_context: Optional[str] = None,
        document_context: Optional[str] = None,
        multimodal_content: Optional[List[Dict]] = None,
        turn_number: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        canvas_context: Optional[str] = None
    ):
        """
        Initialize the Conversation Agent Executor.

        Args:
            profile: The profile configuration dictionary
            user_uuid: User UUID who owns the session
            session_id: The current session ID
            llm_instance: LangChain-compatible LLM instance
            mcp_tools: List of LangChain tool objects
            event_callback: Optional callback for real-time UI events (sync).
                           Signature: (event_type: str, payload: dict) -> None
            async_event_handler: Optional async callback for real-time SSE events.
                           Signature: async (payload: dict, event_type: str) -> None
                           When provided, events are emitted in real-time via asyncio.create_task()
            max_iterations: Maximum agent iterations (default: 5)
            conversation_history: Optional list of previous messages for context
            knowledge_context: Optional pre-retrieved knowledge context to inject
            document_context: Optional extracted text from uploaded documents
            multimodal_content: Optional list of native multimodal blocks for providers that support it
            turn_number: Optional turn number for status title tracking in the UI
            provider: Optional provider name for event tracking (dual-model feature)
            model: Optional model name for event tracking (dual-model feature)
            canvas_context: Optional formatted canvas context string for bidirectional context
        """
        self.profile = profile
        self.profile_id = profile.get("id")
        self.profile_tag = profile.get("tag", "CONV")
        self.user_uuid = user_uuid
        self.session_id = session_id
        self.llm_instance = llm_instance
        self.mcp_tools = mcp_tools
        self.event_callback = event_callback
        self.async_event_handler = async_event_handler
        self.max_iterations = max_iterations
        self.conversation_history = conversation_history or []
        self.knowledge_context = knowledge_context
        self.document_context = document_context
        self.multimodal_content = multimodal_content
        self.canvas_context = canvas_context
        self.turn_number = turn_number
        self.provider = provider or "Unknown"
        self.model = model or "Unknown"

        # Collect events during execution for session storage/replay
        self.collected_events = []

        # Collect component render payloads (chart specs, code blocks, etc.)
        # Extracted from tool results so the executor can generate rendering HTML.
        self.component_payloads: list = []

        # Track tool execution state
        self.tools_invoked = []
        self.tool_start_times = {}

        # Track component-internal LLM token usage (not captured by LangChain callbacks)
        self._component_llm_input_tokens = 0
        self._component_llm_output_tokens = 0

        # Track LLM call count for step naming
        self.llm_call_count = 0

        # Build the agent
        self.system_prompt = self._load_system_prompt()
        self.agent_executor = self._build_agent()

        logger.info(
            f"ConversationAgentExecutor initialized: "
            f"profile={self.profile_tag}, tools={len(self.mcp_tools)}, "
            f"max_iterations={self.max_iterations}"
        )

    async def _emit_event(self, event_type: str, payload: dict):
        """Emit event via callback and collect for replay.

        If async_event_handler is provided, events are awaited directly
        for immediate SSE streaming.
        """
        # Add to collected events for session storage/replay
        self.collected_events.append({
            "type": event_type,
            "payload": dict(payload),
            "timestamp": time.time()
        })

        # Real-time SSE emission via async handler (preferred)
        if self.async_event_handler:
            try:
                # Format as notification event for SSE
                event_data = {
                    "type": event_type,
                    "payload": payload
                }
                logger.info(f"[ConvAgent] Sending {event_type} event via async_event_handler to SSE queue")
                # CRITICAL: Await to ensure event gets into SSE queue
                # The asyncio.sleep(0) calls after _emit_event in the caller allow SSE consumer to process
                await self.async_event_handler(event_data, "notification")
                logger.info(f"[ConvAgent] ✓ Event {event_type} successfully sent to SSE queue")
            except Exception as e:
                logger.warning(f"ConversationAgentExecutor async event handler error: {e}")
        # Fallback to sync callback if no async handler
        elif self.event_callback:
            try:
                self.event_callback(event_type, payload)
            except Exception as e:
                logger.warning(f"ConversationAgentExecutor event callback error: {e}")
        else:
            logger.warning(f"[ConvAgent] No event handler available - event {event_type} will NOT be sent to SSE!")

    async def _emit_status_indicator(self, target: str, status_state: str):
        """Emit a status_indicator_update event directly (not wrapped as notification).

        Status indicator events use a dedicated SSE event type so the frontend
        can update indicator dots (LLM busy/idle, MCP busy/idle) in real-time.
        """
        if self.async_event_handler:
            try:
                await self.async_event_handler(
                    {"target": target, "state": status_state},
                    "status_indicator_update"
                )
            except Exception as e:
                logger.warning(f"ConversationAgentExecutor status indicator error: {e}")

    def _load_system_prompt(self) -> str:
        """Load the system prompt for conversation with tools."""
        # Try to load from prompt system
        resolver = ProfilePromptResolver(profile_id=self.profile_id)

        # Try profile-specific prompt first
        prompt = resolver.get_prompt("CONVERSATION_WITH_TOOLS_EXECUTION")

        if not prompt:
            # Fall back to default prompt
            logger.warning("CONVERSATION_WITH_TOOLS_EXECUTION prompt not found, using default")
            prompt = self._get_default_prompt()

        # Inject available tools into prompt
        tool_descriptions = "\n".join([
            f"- {tool.name}: {tool.description}"
            for tool in self.mcp_tools
        ])
        prompt = prompt.replace("{tools_context}", f"AVAILABLE TOOLS:\n{tool_descriptions}")

        # Inject component instructions
        from trusted_data_agent.components.manager import get_component_instructions_for_prompt
        comp_section = get_component_instructions_for_prompt(self.profile_id, self.user_uuid)
        prompt = prompt.replace("{component_instructions_section}", comp_section)

        # Inject knowledge context if available
        if self.knowledge_context:
            knowledge_section = f"""
KNOWLEDGE CONTEXT:
The following relevant information has been retrieved from knowledge repositories:

{self.knowledge_context}

Use this knowledge to inform your responses. Reference the source documents when appropriate.
"""
            prompt = prompt + "\n" + knowledge_section
            logger.info("Injected knowledge context into system prompt")

        return prompt

    def _get_default_prompt(self) -> str:
        """Get default system prompt for conversation with tools."""
        return """You are a helpful AI assistant with access to tools for retrieving data and performing operations.

YOUR CAPABILITIES:
- You have access to tools for database queries, API calls, and other operations
- When a user request requires external data, use the appropriate tool
- After tool execution, interpret and present results conversationally
- You can chain multiple tool calls if needed

{tools_context}

TOOL USAGE GUIDELINES:
- Only use tools when the user's request requires external data
- Present tool results in a natural, conversational way
- If a tool fails, explain the issue and suggest alternatives
- For multi-step queries, execute tools in sequence and synthesize results

CONVERSATION CONTEXT:
- You have access to the complete conversation history
- Reference previous results when relevant
- Be aware of profile context switches

RESPONSE FORMAT:
- Use markdown for formatting (rendered in UI)
- Present data clearly with tables when appropriate
- Cite tool results naturally in your response
"""

    def _build_agent(self):
        """Build the LangGraph react agent."""
        # Create LangGraph react agent
        return create_react_agent(
            model=self.llm_instance,
            tools=self.mcp_tools
        )

    async def execute(self, query: str) -> Dict[str, Any]:
        """
        Execute the agent for a user query.

        Args:
            query: The user's question

        Returns:
            Dict with:
                - response: The final response text
                - tools_used: List of tools that were called
                - collected_events: Events for session storage
                - success: Boolean indicating success
        """
        start_time = time.time()
        logger.info(f"ConversationAgentExecutor executing query: {query[:100]}...")

        # Emit agent start event (carries combined data for single Live Status card)
        await self._emit_event("conversation_agent_start", {
            "session_id": self.session_id,
            "profile_tag": self.profile_tag,
            "profile_type": "conversation_with_tools",
            "available_tools": [tool.name for tool in self.mcp_tools],
            "query": query[:200] if query else "",
            "turn_id": self.turn_number,
        })

        try:
            # Build input messages
            messages = [SystemMessage(content=self.system_prompt)]

            # Add conversation history if available
            logger.info(f"[ConvAgent] Adding {len(self.conversation_history)} history messages")
            for i, msg in enumerate(self.conversation_history):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                logger.debug(f"[ConvAgent] History[{i}] role={role}, content (first 50 chars): {content[:50] if content else 'EMPTY'}")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))

            # Add current query (with canvas context, document context, and/or multimodal content if present)
            effective_query = query
            if self.canvas_context:
                effective_query = f"{self.canvas_context}\n\n{effective_query}"
                logger.info(f"Prepended canvas context ({len(self.canvas_context):,} chars) to query for conversation agent")
            if self.document_context:
                effective_query = f"[User has uploaded documents]\n{self.document_context}\n\n[User's question]\n{effective_query}"
                logger.info(f"Prepended document context ({len(self.document_context):,} chars) to query for conversation agent")

            # Build multimodal HumanMessage if native content blocks are available
            if self.multimodal_content:
                import base64
                content_blocks = [{"type": "text", "text": effective_query}]
                for block in self.multimodal_content:
                    if block["type"] == "image":
                        try:
                            with open(block["path"], "rb") as f:
                                b64 = base64.b64encode(f.read()).decode("utf-8")
                            content_blocks.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{block['mime_type']};base64,{b64}"}
                            })
                            logger.info(f"[ConvAgent/Multimodal] Added native image: {block['filename']}")
                        except Exception as img_err:
                            logger.warning(f"[ConvAgent/Multimodal] Failed to load image {block['filename']}: {img_err}")
                    # PDFs/documents: LangChain doesn't support universal document blocks
                    # These are handled by text extraction fallback in document_context
                logger.info(f"[ConvAgent] Adding multimodal query with {len(content_blocks)} block(s)")
                messages.append(HumanMessage(content=content_blocks))
            else:
                logger.info(f"[ConvAgent] Adding current query: {effective_query[:100] if effective_query else 'EMPTY'}...")
                messages.append(HumanMessage(content=effective_query))

            # Log all HumanMessage contents to identify duplicates
            human_messages = [m.content[:100] for m in messages if isinstance(m, HumanMessage)]
            logger.info(f"[ConvAgent] Total HumanMessages being sent: {len(human_messages)}")
            for i, hm in enumerate(human_messages):
                logger.info(f"[ConvAgent] HumanMessage[{i}]: {hm}...")

            # Log the conversation for debugging/auditing
            history_str = "\n".join([
                f"[{msg.type.upper()}]: {msg.content[:200]}..." if len(msg.content) > 200 else f"[{msg.type.upper()}]: {msg.content}"
                for msg in messages[1:]  # Skip system prompt in summary
            ])
            llm_history_logger.info(
                f"--- CONVERSATION AGENT EXECUTION ---\n"
                f"Profile: @{self.profile_tag}\n"
                f"Tools Available: {len(self.mcp_tools)}\n"
                f"History Messages: {len(self.conversation_history)}\n\n"
                f"--- SYSTEM PROMPT ---\n{self.system_prompt[:500]}...\n\n"
                f"--- CONVERSATION ---\n{history_str}\n"
                + "-" * 50
            )

            # Execute agent with streaming for tool call tracking
            tools_used = []
            final_response = ""
            total_input_tokens = 0
            total_output_tokens = 0

            # Track LLM call timing
            llm_start_time = None

            # Use astream_events to track tool calls in real-time
            async for event in self.agent_executor.astream_events(
                {"messages": messages},
                version="v2"
            ):
                event_kind = event.get("event", "")
                event_name = event.get("name", "")
                event_data = event.get("data", {})

                # Track LLM start time and signal busy indicator
                if event_kind in ("on_llm_start", "on_chat_model_start"):
                    llm_start_time = time.time()
                    await self._emit_status_indicator("llm", "busy")
                    logger.debug(f"[ConvAgent] LLM call started at {llm_start_time}")

                # Track LLM events - try multiple event types
                # Some providers emit on_llm_end, others emit on_chat_model_end
                if event_kind in ("on_llm_end", "on_chat_model_end"):
                    await self._emit_status_indicator("llm", "idle")
                    output = event_data.get("output", {})

                    # Try multiple ways to get token usage from LangChain
                    tokens_found = False
                    input_tokens = 0
                    output_tokens = 0

                    # Method 1: usage_metadata attribute (newer LangChain format)
                    if hasattr(output, 'usage_metadata'):
                        usage = output.usage_metadata
                        logger.info(f"[ConvAgent] Found usage_metadata (raw): {usage}, type: {type(usage)}")
                        if not usage:
                            logger.warning(f"[ConvAgent] usage_metadata exists but is empty/None for FriendliAI")
                        if usage:
                            # Handle both dict and object formats
                            if isinstance(usage, dict):
                                # Try LangChain standard field names first
                                input_tokens = usage.get('input_tokens', 0) or 0
                                output_tokens = usage.get('output_tokens', 0) or 0
                                # Fallback to OpenAI field names (for FriendliAI and other OpenAI-compatible APIs)
                                if not input_tokens and not output_tokens:
                                    input_tokens = usage.get('prompt_tokens', 0) or 0
                                    output_tokens = usage.get('completion_tokens', 0) or 0
                            else:
                                # Try LangChain standard attribute names first
                                input_tokens = getattr(usage, 'input_tokens', 0) or 0
                                output_tokens = getattr(usage, 'output_tokens', 0) or 0
                                # Fallback to OpenAI attribute names (for FriendliAI and other OpenAI-compatible APIs)
                                if not input_tokens and not output_tokens:
                                    input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
                                    output_tokens = getattr(usage, 'completion_tokens', 0) or 0
                            if input_tokens or output_tokens:
                                total_input_tokens += input_tokens
                                total_output_tokens += output_tokens
                                tokens_found = True
                                logger.info(f"[ConvAgent] Tokens from usage_metadata: input={input_tokens}, output={output_tokens}")

                    # Method 2: response_metadata attribute
                    if not tokens_found and hasattr(output, 'response_metadata') and output.response_metadata:
                        meta = output.response_metadata
                        logger.info(f"[ConvAgent] Found response_metadata keys: {meta.keys() if isinstance(meta, dict) else 'not a dict'}")

                        # Try different key names used by various providers
                        for usage_key in ['token_usage', 'usage', 'usage_metadata']:
                            if usage_key in meta:
                                usage = meta[usage_key]
                                logger.info(f"[ConvAgent] Found usage in response_metadata[{usage_key}]: {usage}")
                                input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0) or 0
                                output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0) or 0
                                if input_tokens or output_tokens:
                                    total_input_tokens += input_tokens
                                    total_output_tokens += output_tokens
                                    tokens_found = True
                                    logger.info(f"[ConvAgent] Tokens from response_metadata: input={input_tokens}, output={output_tokens}")
                                    break

                    # Method 3: Check if output is a list of messages (LangChain AIMessage with usage)
                    if not tokens_found and hasattr(output, 'generations'):
                        for gen in output.generations:
                            if hasattr(gen, 'message') and hasattr(gen.message, 'usage_metadata'):
                                usage = gen.message.usage_metadata
                                if usage:
                                    # Handle both dict and object formats
                                    if isinstance(usage, dict):
                                        # Try LangChain standard field names first
                                        input_tokens = usage.get('input_tokens', 0) or 0
                                        output_tokens = usage.get('output_tokens', 0) or 0
                                        # Fallback to OpenAI field names (for FriendliAI and other OpenAI-compatible APIs)
                                        if not input_tokens and not output_tokens:
                                            input_tokens = usage.get('prompt_tokens', 0) or 0
                                            output_tokens = usage.get('completion_tokens', 0) or 0
                                    else:
                                        # Try LangChain standard attribute names first
                                        input_tokens = getattr(usage, 'input_tokens', 0) or 0
                                        output_tokens = getattr(usage, 'output_tokens', 0) or 0
                                        # Fallback to OpenAI attribute names (for FriendliAI and other OpenAI-compatible APIs)
                                        if not input_tokens and not output_tokens:
                                            input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
                                            output_tokens = getattr(usage, 'completion_tokens', 0) or 0
                                    if input_tokens or output_tokens:
                                        total_input_tokens += input_tokens
                                        total_output_tokens += output_tokens
                                        tokens_found = True
                                        logger.info(f"[ConvAgent] Tokens from generations: input={input_tokens}, output={output_tokens}")
                                        break

                    if not tokens_found:
                        # Log full output structure for debugging
                        logger.warning(f"[ConvAgent] Could not find token usage. Output attrs: {dir(output) if hasattr(output, '__dict__') else 'N/A'}")

                    # Emit LLM step event for Live Status display
                    self.llm_call_count += 1

                    # Calculate LLM call duration
                    duration_ms = 0
                    if llm_start_time is not None:
                        duration_ms = int((time.time() - llm_start_time) * 1000)
                        logger.debug(f"[ConvAgent] LLM call duration: {duration_ms}ms")

                    # Determine step type based on output content
                    # If output has tool_calls, it's Tool Selection; otherwise it's Response Generation
                    has_tool_calls = hasattr(output, 'tool_calls') and output.tool_calls
                    if self.llm_call_count == 1:
                        step_name = "Tool Selection" if has_tool_calls else "Response Generation"
                    else:
                        step_name = "Response Generation" if not has_tool_calls else f"Tool Selection #{self.llm_call_count}"

                    # Calculate cost for this LLM call
                    from trusted_data_agent.core.cost_manager import CostManager
                    cost_manager = CostManager()
                    call_cost = cost_manager.calculate_cost(
                        provider=self.provider,
                        model=self.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens
                    )

                    await self._emit_event("conversation_llm_step", {
                        "step_number": self.llm_call_count,
                        "step_name": step_name,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "duration_ms": duration_ms,
                        "provider": self.provider,  # NEW: Track provider for dual-model
                        "model": self.model,        # NEW: Track model for dual-model
                        "session_id": self.session_id,
                        "cost_usd": call_cost  # NEW: Track cost for all profile types
                    })

                    logger.info(f"[ConvAgent] ✓ Emitted conversation_llm_step event #{self.llm_call_count} ({step_name})")

                    # CRITICAL: Yield control to event loop to allow SSE consumer to process queue
                    # Use small non-zero delay to ensure SSE actually gets scheduled
                    await asyncio.sleep(0.001)

                    # Emit LLM synthesis results event when it's a Response Generation (not tool selection)
                    if not has_tool_calls:
                        # Extract response content from the output
                        response_content = ""
                        if hasattr(output, 'content'):
                            response_content = output.content or ""
                        elif hasattr(output, 'generations') and output.generations:
                            # For ChatResult objects
                            response_content = output.generations[0].text if hasattr(output.generations[0], 'text') else ""

                        # Calculate cost for this LLM completion
                        from trusted_data_agent.core.cost_manager import CostManager
                        cost_manager = CostManager()
                        completion_cost = cost_manager.calculate_cost(
                            provider=self.provider,
                            model=self.model,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens
                        )

                        await self._emit_event("conversation_llm_complete", {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "response_preview": response_content[:500] + "..." if len(response_content) > 500 else response_content,
                            "response_length": len(response_content),
                            "session_id": self.session_id,
                            "cost_usd": completion_cost
                        })
                        logger.info(f"[ConvAgent] ✓ Emitted conversation_llm_complete event (response length: {len(response_content)})")
                        await asyncio.sleep(0.001)

                    logger.info(f"[ConvAgent] LLM Step {self.llm_call_count} ({step_name}): {input_tokens} in / {output_tokens} out")

                # Track tool invocations
                if event_kind == "on_tool_start":
                    tool_name = event_name
                    tool_input = event_data.get("input", {})

                    # Signal MCP busy for status indicator dots (frontend uses "db" target for MCP dot)
                    await self._emit_status_indicator("db", "busy")

                    # Record start time
                    self.tool_start_times[tool_name] = time.time()

                    # Emit tool invoked event
                    await self._emit_event("conversation_tool_invoked", {
                        "tool_name": tool_name,
                        "arguments": self._safe_serialize(tool_input),
                        "session_id": self.session_id
                    })

                    # CRITICAL: Yield control to event loop to allow SSE tasks to run
                    await asyncio.sleep(0)

                    logger.info(f"Tool invoked: {tool_name}")

                # Track tool completions
                elif event_kind == "on_tool_end":
                    # Signal MCP idle for status indicator dots (frontend uses "db" target for MCP dot)
                    await self._emit_status_indicator("db", "idle")
                    tool_name = event_name
                    tool_output = event_data.get("output", "")

                    # Calculate duration
                    start = self.tool_start_times.get(tool_name, time.time())
                    duration_ms = int((time.time() - start) * 1000)

                    # Record tool usage
                    if tool_name not in tools_used:
                        tools_used.append(tool_name)

                    # Emit tool completed event
                    output_preview = str(tool_output)[:5000] if tool_output else ""
                    logger.info(f"[ConvAgent] Tool output preview length: {len(output_preview)} chars")
                    logger.debug(f"[ConvAgent] Tool output preview content: {output_preview[:100]}...")

                    await self._emit_event("conversation_tool_completed", {
                        "tool_name": tool_name,
                        "result_preview": output_preview,
                        "duration_ms": duration_ms,
                        "success": True,
                        "session_id": self.session_id
                    })
                    logger.info(f"[ConvAgent] ✓ Emitted conversation_tool_completed event with result_preview: {bool(output_preview)}")

                    # Detect component render payloads (chart specs, code blocks, etc.)
                    # so the executor can generate data-component-id divs for the frontend.
                    from trusted_data_agent.components.utils import extract_component_payload
                    _payload = extract_component_payload(tool_output)
                    if _payload:
                        # Check if this payload targets a sub_window — emit SSE immediately
                        _render_target = _payload.get("render_target", "inline")
                        if _render_target == "sub_window":
                            await self._emit_event("component_render", {
                                "component_id": _payload.get("component_id"),
                                "render_target": "sub_window",
                                "spec": _payload.get("spec", {}),
                                "title": _payload.get("title", _payload.get("component_id")),
                                "window_id": _payload.get("window_id", ""),
                                "action": _payload.get("window_action", "create"),
                                "interactive": _payload.get("interactive", False),
                                "session_id": self.session_id,
                            })
                            logger.info(f"[ConvAgent] Emitted sub_window component_render SSE for {_payload['component_id']}")
                        # Always collect for inline rendering (sub_window payloads filtered out in generate_component_html)
                        self.component_payloads.append(_payload)
                        logger.info(f"[ConvAgent] Captured component payload: {_payload['component_id']}")

                        # --- Component LLM event & token extraction (mirrors phase_executor:2076) ---
                        _comp_meta = _payload.get("metadata") or {}

                        # Emit piggybacked Live Status events (e.g., chart mapping LLM resolution)
                        _comp_events = _comp_meta.pop("_component_llm_events", None)
                        if _comp_events:
                            for evt in _comp_events:
                                await self._emit_event("component_llm_resolution", evt)
                            logger.info(
                                f"[ConvAgent] Emitted {len(_comp_events)} component LLM event(s) "
                                f"for {_payload['component_id']}"
                            )

                        # Accumulate component LLM tokens (not captured by LangChain callbacks)
                        _comp_in = _comp_meta.get("llm_input_tokens", 0)
                        _comp_out = _comp_meta.get("llm_output_tokens", 0)
                        if _comp_in or _comp_out:
                            self._component_llm_input_tokens += _comp_in
                            self._component_llm_output_tokens += _comp_out
                            logger.info(
                                f"[ConvAgent] Component LLM tokens: {_comp_in} in / {_comp_out} out"
                            )

                    # CRITICAL: Yield control to event loop to allow SSE tasks to run
                    await asyncio.sleep(0)

                    logger.info(f"Tool completed: {tool_name} ({duration_ms}ms)")

                # Track tool errors
                elif event_kind == "on_tool_error":
                    # Signal MCP idle on error too (frontend uses "db" target for MCP dot)
                    await self._emit_status_indicator("db", "idle")
                    tool_name = event_name
                    error = str(event_data.get("error", "Unknown error"))

                    # Calculate duration
                    start = self.tool_start_times.get(tool_name, time.time())
                    duration_ms = int((time.time() - start) * 1000)

                    # Record tool usage (even if failed)
                    if tool_name not in tools_used:
                        tools_used.append(tool_name)

                    # Emit tool error event
                    await self._emit_event("conversation_tool_completed", {
                        "tool_name": tool_name,
                        "result_preview": f"Error: {error}",
                        "duration_ms": duration_ms,
                        "success": False,
                        "error": error,
                        "session_id": self.session_id
                    })

                    # CRITICAL: Yield control to event loop to allow SSE tasks to run
                    await asyncio.sleep(0)

                    logger.warning(f"Tool error: {tool_name} - {error}")

                # Capture final output and token usage from chain end
                elif event_kind == "on_chain_end" and event_name == "LangGraph":
                    output = event_data.get("output", {})
                    if isinstance(output, dict) and "messages" in output:
                        # Extract final AI message for response
                        for msg in reversed(output["messages"]):
                            if hasattr(msg, 'content') and hasattr(msg, 'type'):
                                if msg.type == 'ai' and msg.content:
                                    content = msg.content
                                    # Handle extended thinking format where content is a list of blocks
                                    # e.g., [{"type": "thinking", ...}, {"type": "text", "text": "..."}]
                                    if isinstance(content, list):
                                        # Extract text from content blocks
                                        text_parts = []
                                        for block in content:
                                            if isinstance(block, dict):
                                                if block.get("type") == "text":
                                                    text_parts.append(block.get("text", ""))
                                                elif block.get("type") == "thinking":
                                                    # Skip thinking blocks in final response
                                                    pass
                                            elif isinstance(block, str):
                                                text_parts.append(block)
                                        final_response = "\n".join(text_parts)
                                    else:
                                        final_response = content
                                    break

                        # Sum up token usage from ALL AI messages (each LLM call has its own usage)
                        # Only do this if we haven't captured tokens from on_llm_end events
                        if total_input_tokens == 0 and total_output_tokens == 0:
                            chain_input_tokens = 0
                            chain_output_tokens = 0
                            for msg in output["messages"]:
                                if hasattr(msg, 'type') and msg.type == 'ai':
                                    if hasattr(msg, 'usage_metadata'):
                                        usage = msg.usage_metadata
                                        if usage:
                                            # Handle both dict and object formats
                                            if isinstance(usage, dict):
                                                # Try LangChain standard field names first
                                                input_t = usage.get('input_tokens', 0) or 0
                                                output_t = usage.get('output_tokens', 0) or 0
                                                # Fallback to OpenAI field names (for FriendliAI and other OpenAI-compatible APIs)
                                                if not input_t and not output_t:
                                                    input_t = usage.get('prompt_tokens', 0) or 0
                                                    output_t = usage.get('completion_tokens', 0) or 0
                                            else:
                                                # Try LangChain standard attribute names first
                                                input_t = getattr(usage, 'input_tokens', 0) or 0
                                                output_t = getattr(usage, 'output_tokens', 0) or 0
                                                # Fallback to OpenAI attribute names (for FriendliAI and other OpenAI-compatible APIs)
                                                if not input_t and not output_t:
                                                    input_t = getattr(usage, 'prompt_tokens', 0) or 0
                                                    output_t = getattr(usage, 'completion_tokens', 0) or 0
                                            chain_input_tokens += input_t
                                            chain_output_tokens += output_t

                            if chain_input_tokens > 0 or chain_output_tokens > 0:
                                total_input_tokens = chain_input_tokens
                                total_output_tokens = chain_output_tokens
                                logger.debug(f"[ConvAgent] Total tokens from chain messages: input={total_input_tokens}, output={total_output_tokens}")

            # Calculate total duration
            total_duration_ms = int((time.time() - start_time) * 1000)

            # Calculate total cost for this conversation agent execution
            from trusted_data_agent.core.cost_manager import CostManager
            cost_manager = CostManager()
            total_cost = cost_manager.calculate_cost(
                provider=self.provider,
                model=self.model,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens
            )

            # Emit agent complete event (carries combined data for single Live Status card)
            await self._emit_event("conversation_agent_complete", {
                "total_duration_ms": total_duration_ms,
                "tools_used": tools_used,
                "success": True,
                "session_id": self.session_id,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "profile_tag": self.profile_tag,
                "profile_type": "conversation_with_tools",
                "cost_usd": total_cost
            })

            logger.info(
                f"ConversationAgentExecutor completed. "
                f"Tools used: {tools_used}, Duration: {total_duration_ms}ms, "
                f"Tokens: {total_input_tokens} in / {total_output_tokens} out"
            )

            # Log the response for debugging/auditing
            llm_logger.info(
                f"--- REASON FOR CALL ---\n"
                f"Conversation Agent Execution (@{self.profile_tag})\n"
                f"--- TOOLS USED ---\n{', '.join(tools_used) if tools_used else 'None'}\n"
                f"--- TOKENS ---\nInput: {total_input_tokens}, Output: {total_output_tokens}\n"
                f"--- RESPONSE ---\n{final_response}\n"
                + "-" * 50
            )

            # Auto-canvas: convert markdown code blocks to Canvas component payloads
            # when the LLM failed to use TDA_Canvas directly.
            final_response = self._auto_canvas_code_blocks(final_response)

            return {
                "response": final_response,
                "tools_used": tools_used,
                "collected_events": self.collected_events,
                "component_payloads": self.component_payloads,
                "success": True,
                "duration_ms": total_duration_ms,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "component_llm_input_tokens": self._component_llm_input_tokens,
                "component_llm_output_tokens": self._component_llm_output_tokens,
            }

        except Exception as e:
            logger.error(f"ConversationAgentExecutor error: {e}", exc_info=True)

            # Calculate duration
            total_duration_ms = int((time.time() - start_time) * 1000)

            # Emit error completion event (carries combined data for single Live Status card)
            await self._emit_event("conversation_agent_complete", {
                "total_duration_ms": total_duration_ms,
                "tools_used": self.tools_invoked,
                "success": False,
                "error": str(e),
                "session_id": self.session_id,
                "profile_tag": self.profile_tag,
                "profile_type": "conversation_with_tools",
            })

            return {
                "response": f"I encountered an error while processing your request: {str(e)}",
                "tools_used": self.tools_invoked,
                "collected_events": self.collected_events,
                "success": False,
                "error": str(e),
                "duration_ms": total_duration_ms
            }

    def _safe_serialize(self, obj: Any) -> Any:
        """Safely serialize object for event payload."""
        try:
            if isinstance(obj, dict):
                return {k: self._safe_serialize(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [self._safe_serialize(item) for item in obj]
            elif isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            else:
                return str(obj)
        except Exception:
            return str(obj)

    # ------------------------------------------------------------------
    # Auto-Canvas: post-process markdown code blocks into Canvas renders
    # ------------------------------------------------------------------

    _CODE_BLOCK_RE = re.compile(r'```(\w+)?\s*\n(.*?)```', re.DOTALL)

    _CANVAS_LANGUAGES = {
        "html", "css", "javascript", "python", "sql",
        "markdown", "json", "svg", "mermaid",
    }

    _EXTENSION_MAP = {
        "html": ".html", "css": ".css", "javascript": ".js",
        "python": ".py", "sql": ".sql", "markdown": ".md",
        "json": ".json", "svg": ".svg", "mermaid": ".mmd",
    }

    def _auto_canvas_code_blocks(self, response: str) -> str:
        """Post-process LLM response: convert markdown code blocks to Canvas payloads.

        When the LLM generates a fenced code block instead of calling TDA_Canvas,
        this method detects the block, creates a Canvas component payload, and
        strips the block from the response text so the executor renders it via
        the component system instead.

        Returns:
            The response text with code blocks removed (Canvas payloads appended
            to ``self.component_payloads``).
        """
        # Skip if TDA_Canvas is not among the bound tools
        if not any(t.name == "TDA_Canvas" for t in self.mcp_tools):
            return response

        # Skip if the LLM already used TDA_Canvas properly
        if any(cp.get("component_id") == "canvas" for cp in self.component_payloads):
            return response

        matches = list(self._CODE_BLOCK_RE.finditer(response))
        if not matches:
            return response

        # Process in reverse so string indices stay valid
        converted = 0
        for match in reversed(matches):
            lang_hint = (match.group(1) or "").lower().strip()
            code = match.group(2).strip()

            if not code:
                continue

            # Resolve language
            language = lang_hint if lang_hint in self._CANVAS_LANGUAGES else None
            if not language:
                language = self._detect_language_hint(code)
            if not language:
                continue  # Unrecognised language — leave as markdown

            # Build a canvas component payload (mirrors CanvasComponentHandler.process)
            line_count = code.count("\n") + 1
            title = "SQL Query" if language == "sql" else f"{language.title()} Code"

            payload = {
                "status": "success",
                "component_id": "canvas",
                "render_target": "inline",
                "spec": {
                    "content": code,
                    "language": language,
                    "title": title,
                    "previewable": language in {"html", "svg", "markdown"},
                    "line_count": line_count,
                    "file_extension": self._EXTENSION_MAP.get(language, ".txt"),
                    "sources": None,
                },
                "title": title,
                "metadata": {
                    "tool_name": "TDA_Canvas",
                    "language": language,
                    "content_length": len(code),
                    "line_count": line_count,
                    "auto_canvas": True,
                },
            }
            self.component_payloads.append(payload)

            # Strip the code block from the response text
            response = response[:match.start()] + response[match.end():]
            converted += 1
            logger.info(
                f"[ConvAgent] Auto-canvas: converted {language} code block "
                f"({line_count} lines) to canvas payload"
            )

        if converted:
            logger.info(f"[ConvAgent] Auto-canvas: {converted} code block(s) converted")

        return response.strip()

    @staticmethod
    def _detect_language_hint(content: str) -> Optional[str]:
        """Heuristic language detection for code blocks without a language tag."""
        c = content.strip()
        if not c:
            return None
        if c.startswith("<!DOCTYPE") or c.startswith("<html") or "<head" in c[:200]:
            return "html"
        if c.startswith("<svg"):
            return "svg"
        if c.startswith("graph ") or c.startswith("sequenceDiagram"):
            return "mermaid"
        if "def " in c[:500] or "import " in c[:200]:
            return "python"
        if any(kw in c.upper()[:300] for kw in ["SELECT ", "CREATE TABLE", "INSERT INTO"]):
            return "sql"
        if c.startswith("{") and c.endswith("}"):
            return "json"
        if c.startswith("# ") or "\n## " in c:
            return "markdown"
        return None
