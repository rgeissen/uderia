"""
Unified session name generation for all profile types.
Provides consistent timing, event emission, and token tracking.
"""
import logging
import re
from typing import AsyncGenerator, Tuple, Optional

logger = logging.getLogger("quart.app")


# Common words to exclude when building a fallback title from the query
_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
    'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as',
    'into', 'through', 'during', 'before', 'after', 'above', 'below',
    'and', 'but', 'or', 'nor', 'not', 'so', 'yet', 'both', 'either',
    'neither', 'each', 'every', 'all', 'any', 'few', 'more', 'most',
    'other', 'some', 'such', 'no', 'only', 'own', 'same', 'than',
    'too', 'very', 'just', 'because', 'if', 'when', 'where', 'how',
    'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those',
    'i', 'me', 'my', 'myself', 'we', 'our', 'you', 'your', 'he', 'she',
    'it', 'its', 'they', 'them', 'their', 'show', 'tell', 'give', 'get',
    'make', 'let', 'please', 'help', 'want', 'like', 'know', 'think',
    'about', 'up', 'out', 'there', 'here', 'also', 'then', 'now',
})


def _fallback_name_from_query(query: str, max_words: int = 5) -> str:
    """
    Extract a meaningful session name from the user's query itself.
    Used as a fallback when LLM-based generation fails.

    Examples:
        "Show me all products with low inventory" -> "Products Low Inventory"
        "What databases are on the system?"       -> "Databases System"
        "How many users signed up last month?"     -> "Users Signed Up Month"
    """
    if not query or not query.strip():
        return "New Chat"

    # Strip @TAG prefix (e.g., "@CHAT What is...")
    cleaned = re.sub(r'^@\S+\s+', '', query.strip())
    # Remove punctuation
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    # Extract significant words
    words = [w for w in cleaned.split() if w.lower() not in _STOP_WORDS and len(w) > 1]

    if not words:
        # All words were stop words; take first few original words instead
        words = cleaned.split()[:max_words]

    # Title-case and limit
    title_words = [w.capitalize() for w in words[:max_words]]
    result = ' '.join(title_words)

    return result if result else "New Chat"


def _extract_from_thinking_content(thinking_text: str) -> str:
    """
    Extract session name from thinking block content.

    Handles formats like:
    - "**Session Title Brainstorm**\n\nOkay, I need to... The best title is: Product Search"
    - "Here's my thought... I'll use: Database Query"
    - "**Possible Titles:**\n1. First Option\n2. Second Option"
    """
    import re

    if not thinking_text:
        return ""

    # Pattern 1: Look for explicit title statements
    # "The best title is: XXX", "I'll use: XXX", "My title: XXX"
    explicit_patterns = [
        r'(?:best|final|chosen|good|suggested) (?:title|name) (?:is|would be|should be|:)\s*["\']?([^"\'\n.!?]{3,50})["\']?',
        r'(?:I\'ll use|I would use|I suggest|I recommend|My title|Title):\s*["\']?([^"\'\n.!?]{3,50})["\']?',
        r'(?:Result|Output|Answer):\s*["\']?([^"\'\n.!?]{3,50})["\']?',
    ]

    for pattern in explicit_patterns:
        match = re.search(pattern, thinking_text, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            # Validate it's a reasonable title (3-10 words)
            word_count = len(extracted.split())
            if 2 <= word_count <= 10:
                return extracted

    # Pattern 2: Look for markdown headers followed by potential titles
    # "**Session Title**\nBest Running Shoes"
    header_patterns = [
        r'\*\*(?:Session )?(?:Title|Name)\*\*\s*\n+\s*([A-Z][^.\n!?]{3,50})(?:\n|$)',
        r'##?\s*(?:Session )?(?:Title|Name)\s*\n+\s*([A-Z][^.\n!?]{3,50})(?:\n|$)',
    ]

    for pattern in header_patterns:
        match = re.search(pattern, thinking_text, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            word_count = len(extracted.split())
            if 2 <= word_count <= 10:
                return extracted

    # Pattern 3: Look for numbered/bulleted lists and extract first item
    # "Possible titles:\n1. Best Option\n2. Second Option"
    list_pattern = r'(?:possible|potential|suggested) (?:titles?|names?).*?[\n:]\s*(?:1\.|-|\*)\s*([A-Z][^.\n!?]{3,50})(?:\n|$)'
    match = re.search(list_pattern, thinking_text, re.IGNORECASE | re.DOTALL)
    if match:
        extracted = match.group(1).strip()
        word_count = len(extracted.split())
        if 2 <= word_count <= 10:
            return extracted

    # Pattern 4: Look for quoted titles in the text
    # "The title 'Product Search' would work well"
    quoted_pattern = r'["\']([A-Z][A-Za-z\s]{5,50})["\']'
    for match in re.finditer(quoted_pattern, thinking_text):
        extracted = match.group(1).strip()
        word_count = len(extracted.split())
        # Prefer shorter, title-like phrases
        if 2 <= word_count <= 8 and not extracted.lower().startswith(('the ', 'a ', 'an ')):
            return extracted

    # Pattern 5: Extract first capitalized phrase (fallback)
    # Find first phrase that starts with capital and is 3-6 words
    capitalized_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,5})\b'
    for match in re.finditer(capitalized_pattern, thinking_text):
        extracted = match.group(1).strip()
        word_count = len(extracted.split())
        if 2 <= word_count <= 6:
            # Avoid common false positives
            if not extracted.lower().startswith(('here ', 'okay ', 'let me ', 'i need ', 'i will ')):
                return extracted

    return ""


def _extract_session_name(name_text: str) -> str:
    """
    Extract clean session name from potentially verbose LLM output.

    Cheaper models may include reasoning like:
    "Okay, let me think... The title should be: Database Query"

    This function extracts just "Database Query".
    """
    import re
    import json

    # Log raw input for debugging
    logger.info(f"[SessionNameExtractor] Raw LLM output ({len(name_text)} chars): {name_text[:200]}...")

    if not name_text:
        logger.warning("[SessionNameExtractor] Empty input text")
        return ""

    # Step 1: Handle JSON/dict-formatted thinking blocks (e.g., {'type': 'thinking', 'thinking': '...'})
    # Some models return structured thinking instead of plain text
    if name_text.strip().startswith('{') and ('thinking' in name_text.lower() or 'type' in name_text.lower()):
        try:
            # Try to parse as JSON
            parsed = json.loads(name_text)
            # If it's a thinking block, try to extract title from within
            if isinstance(parsed, dict) and ('thinking' in parsed or 'type' in parsed):
                logger.warning(f"[SessionNameExtractor] JSON thinking block detected: {list(parsed.keys())}")
                thinking_content = parsed.get('thinking', '')
                if thinking_content:
                    # Try multiple patterns to extract title from thinking content
                    extracted = _extract_from_thinking_content(thinking_content)
                    if extracted:
                        logger.info(f"[SessionNameExtractor] Extracted from JSON thinking: '{extracted}'")
                        return extracted
                logger.warning("[SessionNameExtractor] Could not extract title from JSON thinking block")
                return ""
        except (json.JSONDecodeError, ValueError):
            # Not valid JSON, might be partial JSON string or Python dict literal
            # Try to extract thinking content using regex
            thinking_content_match = re.search(r'thinking[\'"]:\s*[\'"]([^}]+)', name_text, re.IGNORECASE)
            if thinking_content_match:
                thinking_text = thinking_content_match.group(1)
                # Try to extract title from thinking text
                extracted = _extract_from_thinking_content(thinking_text)
                if extracted:
                    logger.info(f"[SessionNameExtractor] Extracted from malformed JSON thinking: '{extracted}'")
                    name_text = extracted
                else:
                    logger.warning("[SessionNameExtractor] Could not extract title from malformed thinking block")
                    return ""
            else:
                # Look for common title patterns in malformed JSON
                title_match = re.search(r'(?:title|name)[\'":\s]+([^{}\[\],"\']+)', name_text, re.IGNORECASE)
                if title_match:
                    name_text = title_match.group(1).strip()
                else:
                    logger.warning("[SessionNameExtractor] Unparseable JSON/dict format")
                    return ""

    # Remove XML-style thinking tags
    name_text = re.sub(r'<think>.*?</think>', '', name_text, flags=re.DOTALL | re.IGNORECASE)
    name_text = re.sub(r'<thinking>.*?</thinking>', '', name_text, flags=re.DOTALL | re.IGNORECASE)

    # Try to extract after common separator phrases
    separators = [
        r'Session Name:\s*',
        r'Title:\s*',
        r'The title should be:\s*',
        r'The session name is:\s*',
        r'I would suggest:\s*',
        r'Here\'s the title:\s*',
        r'Result:\s*',
    ]

    for separator in separators:
        match = re.search(separator + r'(.+?)(?:\.|$)', name_text, re.IGNORECASE | re.DOTALL)
        if match:
            name_text = match.group(1).strip()
            break

    # Remove common reasoning prefixes
    reasoning_patterns = [
        r'^(?:Okay|Sure|Alright|Let me think|Based on)[,.]?\s+',
        r'^The user (?:asked|wants|is asking)[^.]+\.\s+',
        r'^(?:I think|I would say|I suggest)[^:]+:\s+',
    ]

    for pattern in reasoning_patterns:
        name_text = re.sub(pattern, '', name_text, flags=re.IGNORECASE)

    # Extract the last line if there are multiple lines (reasoning might be on earlier lines)
    lines = [line.strip() for line in name_text.split('\n') if line.strip()]
    if lines:
        name_text = lines[-1]

    # Remove quotes
    name_text = name_text.strip('\'"')

    # Remove trailing punctuation
    name_text = name_text.rstrip('.!?,;:')

    # Limit to first 10 words (prompts specify 3-5 words, but allow some buffer)
    words = name_text.split()
    if len(words) > 10:
        name_text = ' '.join(words[:10])

    # Final cleanup
    name_text = ' '.join(name_text.split())  # Normalize whitespace

    # Log final result
    logger.info(f"[SessionNameExtractor] Final cleaned name ({len(name_text)} chars): '{name_text}'")

    return name_text


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
        fallback = _fallback_name_from_query(user_query)
        logger.info(f"[SessionName] Using query-based fallback: '{fallback}'")
        name, input_tokens, output_tokens = fallback, 0, 0

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
        f"Generate a concise session name (3-5 words) for the following user query.\n\n"
        f"User Query: \"{query}\"\n\n"
        f"Output ONLY the title with no additional text:"
    )
    system_prompt = (
        "You are a title generator. Your ONLY task is to output a short session title (3-5 words).\n"
        "\n"
        "CRITICAL REQUIREMENTS:\n"
        "- Output ONLY the title text, nothing else\n"
        "- NO thinking, reasoning, or explanations\n"
        "- NO JSON, markdown, or formatting\n"
        "- NO punctuation, quotes, or extra words\n"
        "- NO prefixes like 'Title:', 'Session Name:', etc.\n"
        "- If your model supports extended thinking mode, DISABLE IT for this task\n"
        "\n"
        "EXAMPLES:\n"
        "User: 'Show me all products with low inventory'\n"
        "You: Product Inventory Check\n"
        "\n"
        "User: 'What are the best running shoes?'\n"
        "You: Best Running Shoes\n"
        "\n"
        "WRONG OUTPUT:\n"
        "- {'type': 'thinking', 'thinking': '**Session Title**...'}\n"
        "- 'Okay, let me think... The title should be: Database Query'\n"
        "- 'Session Name: Database Query'\n"
        "- <think>This is about...</think> Database Query\n"
        "\n"
        "CORRECT OUTPUT:\n"
        "Database Query"
    )

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

    # Clean the name and extract only the final title
    cleaned_name = _extract_session_name(name_text)
    if not cleaned_name:
        cleaned_name = _fallback_name_from_query(query)
        logger.info(f"[SessionName] Extraction empty, using query-based fallback: '{cleaned_name}'")
    return cleaned_name, input_tokens, output_tokens


async def _generate_via_langchain(
    query: str,
    llm_instance
) -> Tuple[str, int, int]:
    """Generate session name using LangChain LLM instance."""
    from langchain_core.messages import HumanMessage, SystemMessage

    system_msg = SystemMessage(
        content=(
            "You are a title generator. Your ONLY task is to output a short session title (3-5 words).\n"
            "\n"
            "CRITICAL REQUIREMENTS:\n"
            "- Output ONLY the title text, nothing else\n"
            "- NO thinking, reasoning, or explanations\n"
            "- NO JSON, markdown, or formatting\n"
            "- NO punctuation, quotes, or extra words\n"
            "- NO prefixes like 'Title:', 'Session Name:', etc.\n"
            "- If your model supports extended thinking mode, DISABLE IT for this task\n"
            "\n"
            "EXAMPLES:\n"
            "User: 'Show me all products with low inventory'\n"
            "You: Product Inventory Check\n"
            "\n"
            "User: 'What are the best running shoes?'\n"
            "You: Best Running Shoes\n"
            "\n"
            "WRONG OUTPUT:\n"
            "- {'type': 'thinking', 'thinking': '**Session Title**...'}\n"
            "- 'Okay, let me think... The title should be: Database Query'\n"
            "- 'Session Name: Database Query'\n"
            "- <think>This is about...</think> Database Query\n"
            "\n"
            "CORRECT OUTPUT:\n"
            "Database Query"
        )
    )
    human_msg = HumanMessage(
        content=f"Generate a concise session name (3-5 words) for this query: \"{query[:200]}\""
    )

    response = await llm_instance.ainvoke([system_msg, human_msg])

    # Extract text and tokens
    # Handle Google Gemini which may return content as a list of parts
    raw_content = response.content if hasattr(response, 'content') else str(response)
    if isinstance(raw_content, list):
        # Extract text from list of content parts (Google Gemini multimodal format)
        name_text = ' '.join(str(part) for part in raw_content if part)
    else:
        name_text = str(raw_content) if raw_content else ""

    # Clean the name and extract only the final title
    cleaned_name = _extract_session_name(name_text)

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
        cleaned_name = _fallback_name_from_query(query)
        logger.info(f"[SessionName] LangChain extraction failed/too long, using query-based fallback: '{cleaned_name}'")

    return cleaned_name, input_tokens, output_tokens
