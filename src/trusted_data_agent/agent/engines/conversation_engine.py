"""
Conversation Engine — llm_only profiles with MCP tools or active component tools.

Handles the LangChain ReAct agent path: a single-turn tool-calling agent
without the multi-phase Planner/Executor overhead of OptimizeEngine.

Profile type:  ``llm_only_with_tools``  (IFOC label: "Ideate" + tools, colour: green)

Notes
-----
- Pure llm_only (no useMcpTools, no component tools) routes to IdeateEngine.
- llm_only WITH useMcpTools=True is claimed here via applies_to().
- llm_only with active component tools (but no useMcpTools) is detected at
  runtime in executor.run() and also delegates here.

This engine is registered with EngineRegistry so it can be resolved via:
    EngineRegistry.resolve(profile)   # returns ConversationEngine class
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncGenerator

from .registry import EngineRegistry
from .base import ExecutionEngine

if TYPE_CHECKING:
    from trusted_data_agent.agent.executor import PlanExecutor

app_logger = logging.getLogger("quart.app")


@EngineRegistry.register
class ConversationEngine(ExecutionEngine):
    """LangChain ReAct agent for llm_only profiles with MCP tools or component tools."""

    profile_type = "llm_only_with_tools"

    @classmethod
    def applies_to(cls, profile) -> bool:
        """Claim llm_only profiles that have useMcpTools=True.

        The has_component_tools case requires runtime detection (component manager)
        and is handled separately in executor.run() which also delegates here.
        """
        return (
            profile.get("profile_type") == "llm_only"
            and bool(profile.get("useMcpTools", False))
        )

    async def run(self, executor: "PlanExecutor") -> AsyncGenerator[str, None]:  # type: ignore[override]
        """Execute LangChain ReAct agent turn.

        Extracted from PlanExecutor._execute_conversation_with_tools() (lines 1686–2401).
        All state is accessed via the ``executor`` parameter.
        """
        # --- All imports used by the method body ---
        import os
        import time
        from trusted_data_agent.llm.langchain_adapter import (
            create_langchain_llm,
            load_mcp_tools_for_langchain,
        )
        from trusted_data_agent.agent.conversation_agent import ConversationAgentExecutor
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core import session_manager
        from trusted_data_agent.core.config import APP_CONFIG
        from trusted_data_agent.agent.formatter import OutputFormatter

        config_manager = get_config_manager()

        # Get profile configuration
        profile_config = executor._get_profile_config()
        profile_tag = profile_config.get("tag", "CONV")
        mcp_server_id = profile_config.get("mcpServerId")
        llm_config_id = profile_config.get("llmConfigurationId")

        # --- EPC: Record query intake and profile for conversation_with_tools ---
        try:
            if hasattr(executor, 'provenance') and executor.provenance:
                executor.provenance.add_step("query_intake", executor.original_user_input, f"Query: {executor.original_user_input[:100]}")
                executor.provenance.add_step("profile_resolve", f"{executor.active_profile_id}:conversation_with_tools:{profile_tag}", f"Profile: @{profile_tag} (conversation_with_tools)")
        except Exception as _epc_err:
            app_logger.debug(f"EPC conversation_with_tools intake: {_epc_err}")

        # MCP server is optional when component tools are available (platform feature).
        # Component tools (TDA_Charting, etc.) don't require an MCP server.
        from trusted_data_agent.components.manager import get_component_langchain_tools
        component_tools = get_component_langchain_tools(executor.active_profile_id, executor.user_uuid, session_id=executor.session_id)

        if not mcp_server_id and not component_tools:
            error_msg = "conversation_with_tools profile requires an MCP server configuration or active component tools."
            app_logger.error(error_msg)
            yield executor._format_sse_with_depth({"step": "Error", "error": error_msg}, "error")
            return

        if not llm_config_id:
            error_msg = "conversation_with_tools profile requires an LLM configuration."
            app_logger.error(error_msg)
            yield executor._format_sse_with_depth({"step": "Error", "error": error_msg}, "error")
            return

        try:
            # Create LangChain LLM instance
            app_logger.info(f"Creating LangChain LLM for config {llm_config_id}")
            llm_instance = create_langchain_llm(llm_config_id, executor.user_uuid, thinking_budget=executor.thinking_budget)

            # Load MCP tools filtered by profile (if MCP server configured)
            all_tools = []
            if mcp_server_id:
                app_logger.info(f"Loading MCP tools from server {mcp_server_id}")
                mcp_tools = await load_mcp_tools_for_langchain(
                    mcp_server_id=mcp_server_id,
                    profile_id=executor.active_profile_id,
                    user_uuid=executor.user_uuid
                )
                all_tools.extend(mcp_tools)
                app_logger.info(f"Loaded {len(mcp_tools)} MCP tools for agent")

            # Merge component tools (TDA_Charting, etc.) — platform feature, per-profile config
            # component_tools already loaded above (before MCP server check)
            if component_tools:
                all_tools.extend(component_tools)
                app_logger.info(f"Added {len(component_tools)} component tool(s): {', '.join(t.name for t in component_tools)}")

            # Budget-aware history window from context window module (set in execute())
            cw_history_window = getattr(executor, '_cw_history_window', 10)

            # Get conversation history for context
            # NOTE: The current user query has already been added to chat_object by execution_service.py
            # before this code runs. We need to exclude it to avoid duplication since the agent
            # will add it again as the current query.
            session_data = await session_manager.get_session(executor.user_uuid, executor.session_id)
            conversation_history = []
            if session_data:
                chat_object = session_data.get("chat_object", [])
                app_logger.debug(f"[ConvAgent] chat_object has {len(chat_object)} messages")

                # Take last N messages for context, excluding the current query
                # Budget-aware window from context window module (replaces hardcoded 10)
                # We need to exclude ALL instances of the current query from the end of history
                history_messages = chat_object[-(cw_history_window + 1):]  # Get one extra to check

                # Debug: Log what we're comparing
                if history_messages:
                    last_msg = history_messages[-1]
                    last_content = last_msg.get("content", "")
                    app_logger.debug(f"[ConvAgent] Last message role: {last_msg.get('role')}")
                    app_logger.debug(f"[ConvAgent] Last message content (first 100 chars): {last_content[:100] if last_content else 'EMPTY'}")
                    app_logger.debug(f"[ConvAgent] Current query (first 100 chars): {executor.original_user_input[:100] if executor.original_user_input else 'EMPTY'}")
                    app_logger.debug(f"[ConvAgent] Contents match: {last_content == executor.original_user_input}")
                    app_logger.debug(f"[ConvAgent] Contents match (stripped): {last_content.strip() == executor.original_user_input.strip() if last_content and executor.original_user_input else False}")

                # Use stripped comparison to handle whitespace differences
                original_input_stripped = executor.original_user_input.strip() if executor.original_user_input else ""

                # Remove current query from history if present (compare stripped to handle whitespace)
                if history_messages and history_messages[-1].get("role") == "user":
                    last_content = history_messages[-1].get("content", "").strip()
                    if last_content == original_input_stripped:
                        # Exclude the current query from history (it will be added by the agent)
                        app_logger.info(f"[ConvAgent] Excluding current query from history")
                        history_messages = history_messages[:-1]
                    else:
                        app_logger.info(f"[ConvAgent] Last message differs from current query, keeping in history")

                # Take only the last 10 after exclusion
                # Filter out Google's initial priming messages that shouldn't be in conversation history
                priming_messages = {
                    "You are a helpful assistant.",
                    "Understood."
                }

                # Budget-aware window from context window module (replaces hardcoded 10)
                app_logger.info(f"[ConvAgent] Processing {len(history_messages[-cw_history_window:])} messages for history (window={cw_history_window})")
                for msg in history_messages[-cw_history_window:]:
                    msg_content = msg.get("content", "")

                    # Skip messages marked as invalid (purged or toggled off by user)
                    if msg.get("isValid") is False:
                        app_logger.debug(f"[ConvAgent] Skipping invalid message: {msg_content[:50]}...")
                        continue

                    # Skip Google priming messages
                    if msg_content in priming_messages:
                        app_logger.info(f"[ConvAgent] Skipping priming message: {msg_content[:50]}")
                        continue

                    # Normalize role: 'model' (Google) → 'assistant' (standard)
                    msg_role = msg.get("role", "user")
                    original_role = msg_role
                    if msg_role == "model":
                        msg_role = "assistant"
                    app_logger.info(f"[ConvAgent] Adding to history: role={msg_role} (original: {original_role}), content first 50 chars: {msg_content[:50]}")
                    conversation_history.append({
                        "role": msg_role,
                        "content": msg_content
                    })

                app_logger.info(f"[ConvAgent] Built conversation history with {len(conversation_history)} messages")

            # --- KNOWLEDGE RETRIEVAL FOR CONVERSATION WITH TOOLS ---
            # Check if knowledge collections are enabled for this profile
            knowledge_config = profile_config.get("knowledgeConfig", {})
            knowledge_enabled = knowledge_config.get("enabled", False)
            knowledge_context_str = ""
            knowledge_accessed = []
            knowledge_chunks = []
            knowledge_retrieval_event_data = None

            if knowledge_enabled and executor.rag_retriever:
                app_logger.info("🔍 Knowledge retrieval enabled for conversation_with_tools profile")

                try:
                    retrieval_start_time = time.time()

                    knowledge_collections = knowledge_config.get("collections", [])
                    # Use three-tier configuration (global -> profile -> locks)
                    effective_config = config_manager.get_effective_knowledge_config(knowledge_config)
                    max_docs = effective_config.get("maxDocs", APP_CONFIG.KNOWLEDGE_RAG_NUM_DOCS)
                    min_relevance = effective_config.get("minRelevanceScore", APP_CONFIG.KNOWLEDGE_MIN_RELEVANCE_SCORE)
                    max_tokens = effective_config.get("maxTokens", APP_CONFIG.KNOWLEDGE_MAX_TOKENS)
                    # Budget-aware override from context window module (Phase 5b)
                    cw_knowledge_budget = getattr(executor, '_cw_knowledge_max_tokens', None)
                    if cw_knowledge_budget:
                        max_tokens = min(cw_knowledge_budget, max_tokens) if max_tokens else cw_knowledge_budget
                        app_logger.info(f"[ConvAgent] Knowledge max_tokens from context window budget: {max_tokens:,}")

                    if knowledge_collections:
                        # Emit start event (fetch actual collection names from metadata)
                        collection_names_for_start = []
                        for coll_config in knowledge_collections:
                            coll_id = coll_config.get("id")
                            if coll_id and executor.rag_retriever:
                                coll_meta = executor.rag_retriever.get_collection_metadata(coll_id)
                                if coll_meta:
                                    collection_names_for_start.append(coll_meta.get("name", coll_id))
                                else:
                                    # Fallback: try to get name from collection DB table directly
                                    try:
                                        from trusted_data_agent.core.collection_db import get_collection_db
                                        coll_db = get_collection_db()
                                        coll_info = coll_db.get_collection_by_id(coll_id)
                                        if coll_info and coll_info.get("name"):
                                            collection_names_for_start.append(coll_info["name"])
                                        else:
                                            collection_names_for_start.append(coll_config.get("name", coll_id))
                                    except Exception as e:
                                        app_logger.warning(f"Failed to fetch collection name for {coll_id}: {e}")
                                        collection_names_for_start.append(coll_config.get("name", coll_id))
                            else:
                                collection_names_for_start.append(coll_config.get("name", coll_id or "Unknown"))

                        # Collect per-collection search modes for Live Status display
                        _search_modes = {}
                        try:
                            from trusted_data_agent.core.collection_db import get_collection_db
                            _cdb = get_collection_db()
                            for _cc in knowledge_collections:
                                _cid = _cc.get("id")
                                _cn = _cc.get("name", str(_cid))
                                if _cid:
                                    _dbr = _cdb.get_collection_by_id(_cid)
                                    if _dbr:
                                        _search_modes[_cn] = _dbr.get("search_mode", "semantic")
                                        continue
                                _search_modes[_cn] = "semantic"
                        except Exception as _e:
                            app_logger.debug(f"Failed to read search_mode for collections: {_e}")

                        yield executor._format_sse_with_depth({
                            "type": "knowledge_retrieval_start",
                            "payload": {
                                "collections": collection_names_for_start,
                                "max_docs": max_docs,
                                "session_id": executor.session_id,
                                "search_modes": _search_modes,
                            }
                        }, event="notification")

                        from trusted_data_agent.agent.rag_access_context import RAGAccessContext
                        rag_context = RAGAccessContext(user_id=executor.user_uuid, retriever=executor.rag_retriever)

                        all_results = await executor.rag_retriever.retrieve_examples(
                            query=executor.original_user_input,
                            k=max_docs * len(knowledge_collections),
                            min_score=min_relevance,
                            allowed_collection_ids=set([c["id"] for c in knowledge_collections]),
                            rag_context=rag_context,
                            repository_type="knowledge"
                        )

                        if all_results:
                            # Apply reranking if configured
                            reranked_results = all_results
                            for coll_config in knowledge_collections:
                                if coll_config.get("reranking", False):
                                    coll_results = [r for r in all_results
                                                  if r.get("metadata", {}).get("collection_id") == coll_config["id"]]
                                    if coll_results and executor.llm_handler:
                                        # Get actual collection name from metadata
                                        coll_id = coll_config.get("id")
                                        coll_name = "Unknown"
                                        if coll_id and executor.rag_retriever:
                                            coll_meta = executor.rag_retriever.get_collection_metadata(coll_id)
                                            if coll_meta:
                                                coll_name = coll_meta.get("name", "Unknown")
                                            else:
                                                coll_name = coll_config.get("name", "Unknown")
                                        else:
                                            coll_name = coll_config.get("name", "Unknown")

                                        # Emit reranking start event
                                        yield executor._format_sse_with_depth({
                                            "type": "knowledge_reranking_start",
                                            "payload": {
                                                "collection": coll_name,
                                                "document_count": len(coll_results),
                                                "session_id": executor.session_id
                                            }
                                        }, event="notification")

                                        reranked = await executor._rerank_knowledge_with_llm(
                                            query=executor.original_user_input,
                                            documents=coll_results,
                                            max_docs=max_docs
                                        )

                                        # Emit reranking complete event with token info
                                        # Get session to show updated token counts
                                        updated_session = await session_manager.get_session(executor.user_uuid, executor.session_id)
                                        if updated_session:
                                            yield executor._format_sse_with_depth({
                                                "type": "knowledge_reranking_complete",
                                                "payload": {
                                                    "collection": coll_name,
                                                    "reranked_count": len(reranked),
                                                    "session_id": executor.session_id
                                                }
                                            }, event="notification")

                                        reranked_results = [r for r in reranked_results
                                                          if r.get("metadata", {}).get("collection_id") != coll_config["id"]]
                                        reranked_results.extend(reranked)

                            # Limit total documents
                            final_results = reranked_results[:max_docs]

                            # Enrich documents with collection_name
                            for doc in final_results:
                                if not doc.get("collection_name"):
                                    coll_id = doc.get("collection_id")
                                    if coll_id:
                                        coll_meta = executor.rag_retriever.get_collection_metadata(coll_id)
                                        if coll_meta:
                                            doc["collection_name"] = coll_meta.get("name", "Unknown")

                            # Format knowledge context for agent
                            knowledge_context_str = executor._format_knowledge_for_prompt(final_results, max_tokens)

                            # Build detailed event data for Live Status panel
                            collection_names = set()
                            for doc in final_results:
                                collection_name = doc.get("collection_name", "Unknown")
                                collection_names.add(collection_name)
                                doc_metadata = doc.get("metadata", {})

                                # Try title first (user-friendly name), then filename
                                source_name = doc_metadata.get("title") or doc_metadata.get("filename")

                                # If no title or filename, check if this is an imported collection
                                if not source_name:
                                    if "(Imported)" in collection_name or doc_metadata.get("source") == "import":
                                        source_name = "No Document Source (Imported)"
                                    else:
                                        source_name = "Unknown Source"

                                knowledge_chunks.append({
                                    "source": source_name,
                                    "content": doc.get("content", ""),
                                    "similarity_score": doc.get("similarity_score", 0),
                                    "document_id": doc.get("document_id"),
                                    "chunk_index": doc.get("chunk_index", 0)
                                })

                            knowledge_accessed = list(collection_names)

                            # Calculate retrieval duration
                            retrieval_duration_ms = int((time.time() - retrieval_start_time) * 1000)

                            # Store event data for SSE emission and turn summary
                            # Include chunks for live status window display
                            knowledge_retrieval_event_data = {
                                "collections": list(collection_names),
                                "document_count": len(final_results),
                                "duration_ms": retrieval_duration_ms,
                                "summary": f"Retrieved {len(final_results)} documents from {len(collection_names)} collection(s)",
                                "chunks": knowledge_chunks,  # Include full chunks for UI display
                                "search_modes": _search_modes,
                            }

                            # Emit completion event for Live Status panel (replaces old single event)
                            yield executor._format_sse_with_depth({
                                "type": "knowledge_retrieval_complete",
                                "payload": knowledge_retrieval_event_data
                            }, event="notification")

                            app_logger.info(f"📚 Retrieved {len(final_results)} knowledge documents from {len(collection_names)} collection(s) in {retrieval_duration_ms}ms")

                except Exception as e:
                    app_logger.error(f"Error during knowledge retrieval for conversation_with_tools: {e}", exc_info=True)
                    # Continue without knowledge (graceful degradation)
            # --- END KNOWLEDGE RETRIEVAL ---

            # --- KG enrichment (all profile types) ---
            kg_enrichment_text = await executor._get_kg_enrichment()
            if kg_enrichment_text:
                if knowledge_context_str:
                    knowledge_context_str += "\n\n" + kg_enrichment_text
                else:
                    knowledge_context_str = kg_enrichment_text
                yield executor._format_sse_with_depth({
                    "step": "Knowledge Graph Enrichment",
                    "type": "kg_enrichment",
                    "details": executor.kg_enrichment_event
                })

            # Create and execute agent with real-time SSE event handler
            # Pass executor.event_handler for immediate SSE streaming during execution
            # Respect capability flag: some LLMs don't support function calling
            effective_tools = [] if getattr(llm_instance, '_no_function_calling', False) else all_tools
            agent = ConversationAgentExecutor(
                profile=profile_config,
                user_uuid=executor.user_uuid,
                session_id=executor.session_id,
                llm_instance=llm_instance,
                mcp_tools=effective_tools,
                async_event_handler=executor.event_handler,  # Real-time SSE via asyncio.create_task()
                max_iterations=APP_CONFIG.LANGCHAIN_MAX_ITERATIONS,
                conversation_history=conversation_history,
                knowledge_context=knowledge_context_str or None,  # From knowledge retrieval and/or KG enrichment
                document_context=executor.document_context,
                multimodal_content=executor.multimodal_content,
                turn_number=executor.current_turn_number,
                provider=executor.current_provider,  # NEW: Pass provider for event tracking
                model=executor.current_model,        # NEW: Pass model for event tracking
                canvas_context=executor._format_canvas_context(),  # Canvas bidirectional context
                component_instructions=getattr(executor, '_cw_component_instructions', None),
                provenance=getattr(executor, 'provenance', None),  # EPC: Pass provenance chain
            )

            # Execute agent (events are emitted in real-time via async_event_handler)
            # Wrap with timeout to prevent indefinite hangs (e.g. Friendli streaming stalls)
            _conv_timeout = int(os.environ.get('TDA_CONVERSATION_AGENT_TIMEOUT', '300'))
            try:
                result = await asyncio.wait_for(
                    agent.execute(executor.original_user_input),
                    timeout=_conv_timeout
                )
            except asyncio.TimeoutError:
                app_logger.error(
                    f"⏱️ Conversation agent timed out after {_conv_timeout}s. "
                    f"Provider: {executor.current_provider}, Model: {executor.current_model}"
                )
                raise Exception(
                    f"The AI model did not respond within {_conv_timeout} seconds. "
                    f"This may be a temporary issue with the {executor.current_provider} provider. "
                    f"Please try again or switch to a different model."
                )

            # Note: Events are now emitted in real-time via asyncio.create_task() in the agent
            # The collected_events in result are used for session storage/replay only

            # Extract result data
            response_text = result.get("response", "")
            tools_used = result.get("tools_used", [])
            success = result.get("success", False)
            duration_ms = result.get("duration_ms", 0)
            input_tokens = result.get("input_tokens", 0)
            output_tokens = result.get("output_tokens", 0)

            # Include component-internal LLM tokens (e.g., chart mapping resolution).
            # These are NOT captured by LangChain callbacks but were already persisted
            # to session DB by call_llm_api → update_token_count (handler.py:1082).
            comp_llm_in = result.get("component_llm_input_tokens", 0)
            comp_llm_out = result.get("component_llm_output_tokens", 0)
            combined_input = input_tokens + comp_llm_in
            combined_output = output_tokens + comp_llm_out

            # Update turn token counters with combined totals
            executor.turn_input_tokens += combined_input
            executor.turn_output_tokens += combined_output

            # LangChain tokens are now persisted incrementally per LLM step
            # inside conversation_agent.py (via update_token_count per on_chat_model_end).
            # Only persist component LLM tokens here (chart mapping, etc.) since those
            # are NOT captured by LangChain callbacks.
            if comp_llm_in > 0 or comp_llm_out > 0:
                await session_manager.update_token_count(
                    executor.user_uuid,
                    executor.session_id,
                    comp_llm_in,
                    comp_llm_out
                )

            # Emit final token_update event with complete session totals
            updated_session = await session_manager.get_session(executor.user_uuid, executor.session_id)
            if updated_session:
                # Calculate cost using combined tokens (LangChain + component LLM)
                _conv_cost = 0
                try:
                    from trusted_data_agent.core.cost_manager import CostManager
                    _conv_cost = CostManager().calculate_cost(
                        provider=executor.current_provider or "Unknown",
                        model=executor.current_model or "Unknown",
                        input_tokens=combined_input,
                        output_tokens=combined_output
                    )
                except Exception:
                    pass
                yield executor._format_sse_with_depth({
                    "statement_input": combined_input,
                    "statement_output": combined_output,
                    "turn_input": executor.turn_input_tokens,
                    "turn_output": executor.turn_output_tokens,
                    "total_input": updated_session.get("input_tokens", 0),
                    "total_output": updated_session.get("output_tokens", 0),
                    "call_id": str(uuid.uuid4()),
                    "cost_usd": _conv_cost
                }, "token_update")

            # Format the response using OutputFormatter's markdown renderer
            # This ensures consistent formatting with other profile types
            formatter_kwargs = {
                "llm_response_text": response_text,  # Triggers markdown rendering
                "collected_data": [],  # No structured data from conversation agent
                "original_user_input": executor.original_user_input,
                "active_prompt_name": None
            }
            formatter = OutputFormatter(**formatter_kwargs)
            final_html, tts_payload = formatter.render()

            # Append component rendering HTML (chart, code, audio, video, etc.)
            from trusted_data_agent.components.utils import generate_component_html
            final_html += generate_component_html(result.get("component_payloads", []))

            # Add assistant message to conversation history (with HTML for display)
            await session_manager.add_message_to_histories(
                user_uuid=executor.user_uuid,
                session_id=executor.session_id,
                role='assistant',
                content=response_text,  # Clean text for LLM consumption
                html_content=final_html,  # Formatted HTML for UI display
                profile_tag=profile_tag,
                is_session_primer=executor.is_session_primer
            )

            # Update session metadata
            await session_manager.update_models_used(
                executor.user_uuid,
                executor.session_id,
                executor.current_provider,
                executor.current_model,
                profile_tag
            )

            # Collect system events for plan reload (like session name generation)
            system_events = []

            # Generate session name if first turn (using unified generator)
            if executor.current_turn_number == 1:
                async for name_result in executor._generate_and_emit_session_name():
                    if isinstance(name_result, str):
                        # SSE event - yield to frontend
                        yield name_result
                    else:
                        # Final result tuple: (name, input_tokens, output_tokens, collected_events)
                        new_name, name_input_tokens, name_output_tokens, name_events = name_result
                        system_events.extend(name_events)

                        # Add session name tokens to turn totals and session totals
                        if name_input_tokens > 0 or name_output_tokens > 0:
                            executor.turn_input_tokens += name_input_tokens
                            executor.turn_output_tokens += name_output_tokens
                            await session_manager.update_token_count(
                                executor.user_uuid, executor.session_id, name_input_tokens, name_output_tokens
                            )
                            # Emit token_update event so UI reflects updated session totals
                            updated_session = await session_manager.get_session(executor.user_uuid, executor.session_id)
                            if updated_session:
                                from trusted_data_agent.core.cost_manager import CostManager as _CM1
                                _name_cost = _CM1().calculate_cost(
                                    provider=executor.current_provider or "Unknown",
                                    model=executor.current_model or "Unknown",
                                    input_tokens=name_input_tokens,
                                    output_tokens=name_output_tokens
                                )
                                yield executor._format_sse_with_depth({
                                    "statement_input": name_input_tokens,
                                    "statement_output": name_output_tokens,
                                    "turn_input": executor.turn_input_tokens,
                                    "turn_output": executor.turn_output_tokens,
                                    "total_input": updated_session.get("input_tokens", 0),
                                    "total_output": updated_session.get("output_tokens", 0),
                                    "call_id": "session_name_generation",
                                    "cost_usd": _name_cost
                                }, "token_update")

                        if new_name and new_name != "New Chat":
                            await session_manager.update_session_name(executor.user_uuid, executor.session_id, new_name)
                            yield executor._format_sse_with_depth({
                                "session_id": executor.session_id,
                                "newName": new_name
                            }, "session_name_update")

            # Emit final answer with formatted HTML
            yield executor._format_sse_with_depth({
                "step": "Finished",
                "final_answer": final_html,  # Send formatted HTML
                "final_answer_text": response_text,  # Also include clean text
                "turn_id": executor.current_turn_number,
                "session_id": executor.session_id,  # Include session_id for filtering when switching sessions
                "tts_payload": tts_payload,
                "source": executor.source,
                "is_session_primer": executor.is_session_primer
            }, "final_answer")

            # Get session data for session token totals (needed for plan reload display)
            session_data = await session_manager.get_session(executor.user_uuid, executor.session_id)
            session_input_tokens = session_data.get("input_tokens", 0) if session_data else 0
            session_output_tokens = session_data.get("output_tokens", 0) if session_data else 0

            # Calculate turn cost for persistence
            turn_cost = 0.0
            try:
                from trusted_data_agent.core.cost_manager import CostManager
                cost_manager = CostManager()
                turn_cost = cost_manager.calculate_cost(
                    provider=executor.current_provider,
                    model=executor.current_model,
                    input_tokens=executor.turn_input_tokens,
                    output_tokens=executor.turn_output_tokens
                )
                app_logger.debug(f"[conversation_with_tools] Turn {executor.current_turn_number} cost: ${turn_cost:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate turn cost: {e}", exc_info=True)

            # Calculate session cost (cumulative up to and including this turn)
            session_cost_usd = 0.0
            try:
                previous_session_cost = executor._calculate_session_cost_at_turn(session_data)
                session_cost_usd = previous_session_cost + turn_cost  # Add current turn
                app_logger.debug(f"[conversation_with_tools] Session cost at turn {executor.current_turn_number}: ${session_cost_usd:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate session cost: {e}", exc_info=True)

            # --- EPC: Seal provenance chain for conversation_with_tools ---
            _provenance_data = None
            try:
                if hasattr(executor, 'provenance') and executor.provenance:
                    executor.provenance.add_step("turn_complete", response_text or "", f"conversation_with_tools turn {executor.current_turn_number} complete")
                    _provenance_data = executor.provenance.finalize()
            except Exception as _epc_err:
                app_logger.debug(f"EPC conversation_with_tools finalize: {_epc_err}")

            # Save turn data to workflow_history for session reload
            turn_summary = {
                "turn": executor.current_turn_number,
                "user_query": executor.original_user_input,
                "final_summary_text": response_text,  # Clean text for LLM context
                "final_summary_html": final_html,  # Formatted HTML for session reload
                "status": "success" if success else "failed",
                "is_session_primer": executor.is_session_primer,  # Flag for RAG case filtering
                "execution_trace": [],
                "tools_used": tools_used,
                "conversation_agent_events": result.get("collected_events", []),
                "system_events": system_events,  # Session name generation and other system operations (UI replay only)
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": executor.current_provider,
                "model": executor.current_model,
                "profile_tag": profile_tag,
                "profile_type": "conversation_with_tools",
                "duration_ms": duration_ms,
                "session_id": executor.session_id,
                "turn_input_tokens": executor.turn_input_tokens,  # Cumulative turn total (includes all LLM calls like reranking)
                "turn_output_tokens": executor.turn_output_tokens,  # Cumulative turn total
                "turn_cost": turn_cost,  # NEW - Cost at time of execution
                "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                # Session totals at the time of this turn (for plan reload)
                "session_input_tokens": session_input_tokens,
                "session_output_tokens": session_output_tokens,
                # Knowledge retrieval tracking for session reload
                "knowledge_accessed": knowledge_accessed,
                "knowledge_retrieval_event": knowledge_retrieval_event_data,
                # UI-only: Full document chunks for plan reload display (not sent to LLM)
                "knowledge_chunks_ui": knowledge_chunks if knowledge_enabled else [],
                # KG enrichment event for session reload
                "kg_enrichment_event": executor.kg_enrichment_event,
                "context_window_snapshot_event": getattr(executor, 'context_window_snapshot_event', None),
                # Pre-processing skills applied to this turn
                "skills_applied": executor.skill_result.to_applied_list() if executor.skill_result and executor.skill_result.has_content else []
            }
            if _provenance_data:
                turn_summary.update(_provenance_data)

            await session_manager.update_last_turn_data(executor.user_uuid, executor.session_id, turn_summary)
            app_logger.info(f"✅ conversation_with_tools execution completed: {len(tools_used)} tools used")

        except Exception as e:
            app_logger.error(f"conversation_with_tools execution error: {e}", exc_info=True)
            error_msg = f"Agent execution failed: {str(e)}"
            yield executor._format_sse_with_depth({"step": "Error", "error": error_msg}, "error")

            # Get session data for session cost calculation
            session_data = await session_manager.get_session(executor.user_uuid, executor.session_id)

            # Calculate turn cost for error case
            turn_cost = 0.0
            try:
                from trusted_data_agent.core.cost_manager import CostManager
                cost_manager = CostManager()
                turn_cost = cost_manager.calculate_cost(
                    provider=executor.current_provider,
                    model=executor.current_model,
                    input_tokens=executor.turn_input_tokens,
                    output_tokens=executor.turn_output_tokens
                )
                app_logger.debug(f"[conversation_with_tools-error] Turn {executor.current_turn_number} cost: ${turn_cost:.6f}")
            except Exception as cost_err:
                app_logger.warning(f"Failed to calculate turn cost for error case: {cost_err}")

            # Calculate session cost (cumulative up to and including this turn)
            session_cost_usd = 0.0
            try:
                previous_session_cost = executor._calculate_session_cost_at_turn(session_data)
                session_cost_usd = previous_session_cost + turn_cost
                app_logger.debug(f"[conversation_with_tools-error] Session cost at turn {executor.current_turn_number}: ${session_cost_usd:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate session cost for error case: {e}")

            # Save error turn data
            turn_summary = {
                "turn": executor.current_turn_number,
                "user_query": executor.original_user_input,
                "final_summary_text": error_msg,
                "status": "failed",
                "is_session_primer": executor.is_session_primer,  # Flag for RAG case filtering
                "error": str(e),
                "profile_tag": profile_config.get("tag", "CONV"),
                "profile_type": "conversation_with_tools",
                "turn_input_tokens": executor.turn_input_tokens,  # Accumulated tokens up to failure
                "turn_output_tokens": executor.turn_output_tokens,
                "turn_cost": turn_cost,  # NEW - Cost at time of error
                "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "skills_applied": executor.skill_result.to_applied_list() if executor.skill_result and executor.skill_result.has_content else []
            }
            await session_manager.update_last_turn_data(executor.user_uuid, executor.session_id, turn_summary)
