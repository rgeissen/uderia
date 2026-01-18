"""
Unified session name generation for all profile types.
Provides consistent timing, event emission, and token tracking.
"""
import logging
from typing import AsyncGenerator, Tuple, Optional

logger = logging.getLogger("quart.app")


async def generate_session_name_with_events(
    user_query: str,
    session_id: str,
    llm_interface: str,  # "executor" or "langchain"
    llm_dependencies: dict = None,  # For executor interface
    llm_instance = None,  # For langchain interface
    user_uuid: str = None,
    active_profile_id: int = None,
    current_provider: str = None,
    emit_events: bool = True
) -> AsyncGenerator[Tuple[Optional[dict], Optional[str], int, int], None]:
    """
    Generate session name using appropriate LLM interface.

    Args:
        user_query: The user's initial query
        session_id: Current session ID
        llm_interface: "executor" (uses llm_handler) or "langchain" (uses llm_instance)
        llm_dependencies: Required for executor interface
        llm_instance: Required for langchain interface
        user_uuid: Required for executor interface
        active_profile_id: Optional for executor interface
        current_provider: Optional for executor interface
        emit_events: Whether to yield SSE events (default True)

    Yields:
        Tuples of (sse_event_dict, event_type, input_tokens, output_tokens)
        Final yield returns (None, session_name, input_tokens, output_tokens)
    """

    # Always yield start event (caller decides whether to emit as SSE)
    start_event = {
        "step": "Generating Session Name",
        "type": "session_name_generation_start",
        "details": {
            "summary": "Using LLM to generate descriptive session title",
            "session_id": session_id
        }
    }
    yield (start_event, "session_name_generation_start", 0, 0)

    # Generate name using appropriate interface
    try:
        if llm_interface == "executor":
            # Use executor's LLM handler
            name, input_tokens, output_tokens = await _generate_via_executor(
                user_query, llm_dependencies, user_uuid, active_profile_id, current_provider
            )
        elif llm_interface == "langchain":
            # Use LangChain LLM instance
            name, input_tokens, output_tokens = await _generate_via_langchain(
                user_query, llm_instance
            )
        else:
            raise ValueError(f"Invalid llm_interface: {llm_interface}")
    except Exception as e:
        logger.error(f"Failed to generate session name: {e}", exc_info=True)
        name, input_tokens, output_tokens = "New Chat", 0, 0

    # Always yield completion event (caller decides whether to emit as SSE)
    complete_event = {
        "step": "Session Name Generated",
        "type": "session_name_generation_complete",
        "details": {
            "session_name": name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "summary": f"Generated name: '{name}' ({input_tokens} in / {output_tokens} out)",
            "session_id": session_id
        }
    }
    yield (complete_event, "session_name_generation_complete", input_tokens, output_tokens)

    # Final return with name and tokens
    yield (None, name, input_tokens, output_tokens)


async def _generate_via_executor(
    query: str,
    dependencies: dict,
    user_uuid: str,
    active_profile_id: int,
    current_provider: str
) -> Tuple[str, int, int]:
    """Generate session name using executor's LLM handler."""
    from trusted_data_agent.llm import handler as llm_handler

    prompt = (
        f"Based on the following user query, generate a concise and descriptive name (3-5 words) "
        f"suitable for a chat session history list. Do not include any punctuation or extra text.\n\n"
        f"User Query: \"{query}\"\n\n"
        f"Session Name:"
    )
    system_prompt = "You generate short, descriptive titles. Only respond with the title text."

    name_text, input_tokens, output_tokens, _, _ = await llm_handler.call_llm_api(
        dependencies['STATE']['llm'],
        prompt,
        user_uuid=user_uuid,
        session_id=None,  # Don't add to session history
        dependencies=dependencies,
        reason="Generating session name from initial query",
        system_prompt_override=system_prompt,
        raise_on_error=True,
        disabled_history=True,
        source="system",
        active_profile_id=active_profile_id,
        current_provider=current_provider
    )

    cleaned_name = name_text.strip().strip('"\'')
    return cleaned_name or "New Chat", input_tokens, output_tokens


async def _generate_via_langchain(
    query: str,
    llm_instance
) -> Tuple[str, int, int]:
    """Generate session name using LangChain LLM instance."""
    from langchain_core.messages import HumanMessage, SystemMessage

    system_msg = SystemMessage(
        content="You generate short, descriptive titles (3-5 words). Only respond with the title text, no punctuation or quotes."
    )
    human_msg = HumanMessage(
        content=f"Generate a concise session name for this query: \"{query[:200]}\""
    )

    response = await llm_instance.ainvoke([system_msg, human_msg])

    # Extract text and tokens
    name_text = response.content if hasattr(response, 'content') else str(response)
    cleaned_name = name_text.strip().strip('"\'')

    # Extract token usage from response (handles multiple provider formats)
    input_tokens = 0
    output_tokens = 0

    # Google Gemini: usage_metadata is a direct attribute on AIMessage
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        usage_meta = response.usage_metadata
        logger.info(f"Session name usage_metadata (direct attribute): {usage_meta}")

        # Google Gemini format
        if hasattr(usage_meta, 'get'):
            input_tokens = usage_meta.get('prompt_token_count', 0) or usage_meta.get('input_tokens', 0) or 0
            output_tokens = usage_meta.get('candidates_token_count', 0) or usage_meta.get('output_tokens', 0) or 0
        # Pydantic object format
        else:
            input_tokens = getattr(usage_meta, 'prompt_token_count', 0) or getattr(usage_meta, 'input_tokens', 0) or 0
            output_tokens = getattr(usage_meta, 'candidates_token_count', 0) or getattr(usage_meta, 'output_tokens', 0) or 0

    # OpenAI/Anthropic: usage is in response_metadata
    elif hasattr(response, 'response_metadata'):
        metadata = response.response_metadata
        logger.info(f"Session name response_metadata: {metadata}")

        usage = metadata.get('usage', {})
        if usage:
            input_tokens = usage.get('input_tokens', 0) or usage.get('prompt_tokens', 0) or 0
            output_tokens = usage.get('output_tokens', 0) or usage.get('completion_tokens', 0) or 0

    logger.info(f"Session name extracted tokens: {input_tokens} in / {output_tokens} out")

    if not cleaned_name or len(cleaned_name) >= 100:
        return "New Chat", input_tokens, output_tokens

    return cleaned_name, input_tokens, output_tokens
