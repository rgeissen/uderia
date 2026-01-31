# src/trusted_data_agent/core/utils.py
import json
import logging
import os
import uuid # Import uuid
from pathlib import Path

try:
    from google.cloud import texttospeech
    from google.oauth2 import service_account
except ImportError:
    texttospeech = None
    service_account = None

from trusted_data_agent.core.config import APP_STATE, AppConfig

app_logger = logging.getLogger("quart.app")


def get_project_root() -> Path:
    """
    Get the correct project root directory.
    
    Works by finding the location of the tda_auth.db or tda_config.json files
    or by looking for the uderia/rag/trusted_data_agent markers.
    
    This solves the issue where pip install -e . installs from one location
    but the application actually runs from another.
    
    Returns:
        Path to the project root (uderia directory)
    """
    # First, check if TDA_AUTH_DB_URL environment variable points us to the right place
    db_url = os.environ.get('TDA_AUTH_DB_URL', '')
    if db_url.startswith('sqlite:///'):
        db_path = Path(db_url.replace('sqlite:///', ''))
        if db_path.exists():
            return db_path.parent
    
    # Check common locations where tda_config.json might be
    current_script = Path(__file__).resolve()
    
    # Go up from this file (src/trusted_data_agent/core/utils.py) -> 3 levels to project root
    candidate = current_script.parents[3]
    if (candidate / "tda_config.json").exists() or (candidate / "tda_auth.db").exists():
        return candidate
    
    # If the above doesn't work, try checking current working directory
    cwd = Path.cwd()
    if (cwd / "tda_config.json").exists() or (cwd / "tda_auth.db").exists():
        return cwd
    
    # Check if there's a pyproject.toml or setup.py indicating this is the project root
    if (cwd / "pyproject.toml").exists() and (cwd / "src" / "trusted_data_agent").exists():
        return cwd
    
    # Fallback to the calculated path (original behavior)
    app_logger.warning(f"Could not find project root markers, using calculated path: {candidate}")
    return candidate

# --- MODIFICATION START: Add generate_task_id function ---
def generate_task_id() -> str:
    """Generates a unique task ID."""
    return f"task-{uuid.uuid4()}"

# --- MODIFICATION START: Add generate_session_id function ---
def generate_session_id() -> str:
    """Generates a unique session ID."""
    return str(uuid.uuid4())
# --- MODIFICATION END ---
# --- MODIFICATION END ---

# --- MODIFICATION START: Add a centralized, synonym-aware argument reader ---
def get_argument_by_canonical_name(args: dict, canonical_name: str) -> any:
    """
    Intelligently retrieves a value from an arguments dictionary by checking
    for the canonical name and all of its registered synonyms.

    This provides a robust, centralized way to access arguments without
    needing to know which specific synonym (e.g., 'table_name', 'object_name')
    was used in a particular tool call.

    Args:
        args: The dictionary of arguments from a tool call.
        canonical_name: The canonical name of the argument to find (e.g., 'object_name').

    Returns:
        The value of the argument if found, otherwise None.
    """
    if not isinstance(args, dict):
        return None

    # Get all possible names for the desired argument from the synonym map.
    # Fallback to a set containing just the canonical_name if it's not in the map.
    possible_names = AppConfig.ARGUMENT_SYNONYM_MAP.get(canonical_name, {canonical_name})

    # Iterate through all possible names and return the value for the first one found.
    for name in possible_names:
        if name in args:
            return args[name]

    return None
# --- MODIFICATION END ---


def get_tts_client(credentials_json: str = None):
    """
    Initializes and returns a Google Cloud TextToSpeechClient.

    Args:
        credentials_json: Optional JSON string of Google service account credentials.
                          If provided, used directly. If None, falls back to
                          GOOGLE_APPLICATION_CREDENTIALS environment variable.
    """
    if texttospeech is None:
        app_logger.warning("The 'google-cloud-texttospeech' library is not installed. Voice features will be disabled.")
        return None

    # --- 1. Use explicit credentials if provided ---
    if credentials_json:
        try:
            credentials_info = json.loads(credentials_json)
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            client = texttospeech.TextToSpeechClient(credentials=credentials)
            app_logger.info("Successfully initialized Google Cloud TTS client using provided credentials.")
            return client
        except json.JSONDecodeError:
            app_logger.error("Failed to parse TTS credentials JSON. It appears to be invalid JSON.")
            return None
        except Exception as e:
            app_logger.error(f"Failed to initialize TTS client with provided credentials: {e}", exc_info=True)
            return None

    # --- 2. Fallback to environment variables ---
    elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        try:
            client = texttospeech.TextToSpeechClient()
            app_logger.info("Successfully initialized Google Cloud TTS client using environment variables.")
            return client
        except Exception as e:
            app_logger.error(f"Failed to initialize Google Cloud TTS client with environment variables: {e}", exc_info=True)
            return None

    # --- 3. No credentials available ---
    else:
        app_logger.info("No TTS credentials available. TTS client will not be initialized.")
        return None

def synthesize_speech(client, text: str) -> bytes | None:
    """
    Synthesizes speech from the provided text using the given TTS client.
    """
    if not client:
        app_logger.error("TTS client is not available. Cannot synthesize speech.")
        return None

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Studio-O",
        ssml_gender=texttospeech.SsmlVoiceGender.FEMALE,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.1
    )

    try:
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        return response.audio_content
    except Exception as e:
        app_logger.error(f"Google Cloud TTS API call failed: {e}", exc_info=True)
        return None

def unwrap_exception(e: BaseException) -> BaseException:
    """Recursively unwraps ExceptionGroups to find the root cause."""
    # ExceptionGroup is only available in Python 3.11+
    # Use try/except to handle both versions
    try:
        if isinstance(e, ExceptionGroup) and e.exceptions:
            return unwrap_exception(e.exceptions[0])
    except NameError:
        # ExceptionGroup doesn't exist in Python 3.10 and earlier
        pass
    return e

def _get_prompt_info(prompt_name: str) -> dict | None:
    """Helper to find prompt details from the structured prompts in the global state."""
    structured_prompts = APP_STATE.get('structured_prompts', {})
    for category_prompts in structured_prompts.values():
        for prompt in category_prompts:
            if prompt.get("name") == prompt_name:
                return prompt
    return None

def _indent_multiline_description(description: str, indent_level: int = 2) -> str:
    """Indents all but the first line of a multi-line string."""
    if not description or '\n' not in description:
        return description
    
    lines = description.split('\n')
    first_line = lines[0]
    rest_lines = lines[1:]
    
    indentation = ' ' * indent_level
    indented_rest = [f"{indentation}{line}" for line in rest_lines]
    
    return '\n'.join([first_line] + indented_rest)

def _regenerate_contexts():
    """
    Updates all capability contexts ('tools_context', 'prompts_context', etc.)
    in the global STATE based on the current disabled lists and prints the
    current status to the console for debugging.
    """
    app_logger.debug("Regenerating Agent Capability Contexts")

    disabled_tools_list = APP_STATE.get("disabled_tools", [])
    disabled_prompts_list = APP_STATE.get("disabled_prompts", [])
    
    if 'mcp_tools' in APP_STATE and 'structured_tools' in APP_STATE:
        for category, tool_list in APP_STATE['structured_tools'].items():
            for tool_info in tool_list:
                tool_info['disabled'] = tool_info['name'] in disabled_tools_list
        
        enabled_count = sum(1 for category in APP_STATE['structured_tools'].values() for t in category if not t['disabled'])

        app_logger.debug(f"Tools Status: Active={enabled_count}, Inactive={len(disabled_tools_list)}")

        tool_context_parts = ["--- Available Tools ---"]
        for category, tools in sorted(APP_STATE['structured_tools'].items()):
            enabled_tools_in_category = [t for t in tools if not t['disabled']]
            if not enabled_tools_in_category:
                continue
                
            tool_context_parts.append(f"--- Category: {category} ---")
            for tool_info in enabled_tools_in_category:
                tool_description = tool_info.get("description", "No description available.")
                indented_description = _indent_multiline_description(tool_description, indent_level=2)
                tool_str = f"- `{tool_info['name']}` (tool): {indented_description}"
                
                processed_args = tool_info.get('arguments', [])
                if processed_args:
                    tool_str += "\n  - Arguments:"
                    for arg_details in processed_args:
                        arg_name = arg_details.get('name', 'unknown')
                        arg_type = arg_details.get('type', 'any')
                        is_required = arg_details.get('required', False)
                        req_str = "required" if is_required else "optional"
                        arg_desc = arg_details.get('description', 'No description.')
                        tool_str += f"\n    - `{arg_name}` ({arg_type}, {req_str}): {arg_desc}"
                tool_context_parts.append(tool_str)
        
        if len(tool_context_parts) > 1:
            APP_STATE['tools_context'] = "\n".join(tool_context_parts)
        else:
            APP_STATE['tools_context'] = "--- No Tools Available ---"
        app_logger.debug(f"Regenerated LLM tool context. {enabled_count} tools are active.")

    if 'mcp_prompts' in APP_STATE and 'structured_prompts' in APP_STATE:
        for category, prompt_list in APP_STATE['structured_prompts'].items():
            for prompt_info in prompt_list:
                prompt_info['disabled'] = prompt_info['name'] in disabled_prompts_list

        enabled_count = sum(1 for category in APP_STATE['structured_prompts'].values() for p in category if not p['disabled'])

        app_logger.debug(f"Prompts Status: Active={enabled_count}, Inactive={len(disabled_prompts_list)}")
        
        prompt_context_parts = ["--- Available Prompts ---"]
        for category, prompts in sorted(APP_STATE['structured_prompts'].items()):
            enabled_prompts_in_category = [p for p in prompts if not p['disabled']]
            if not enabled_prompts_in_category:
                continue

            prompt_context_parts.append(f"--- Category: {category} ---")
            for prompt_info in enabled_prompts_in_category:
                prompt_description = prompt_info.get("description", "No description available.")
                indented_description = _indent_multiline_description(prompt_description, indent_level=2)
                prompt_str = f"- `{prompt_info['name']}` (prompt): {indented_description}"
                
                processed_args = prompt_info.get('arguments', [])
                if processed_args:
                    prompt_str += "\n  - Arguments:"
                    for arg_details in processed_args:
                        arg_name = arg_details.get('name', 'unknown')
                        arg_type = arg_details.get('type', 'any')
                        is_required = arg_details.get('required', False)
                        req_str = "required" if is_required else "optional"
                        arg_desc = arg_details.get('description', 'No description.')
                        prompt_str += f"\n    - `{arg_name}` ({arg_type}, {req_str}): {arg_desc}"
                prompt_context_parts.append(prompt_str)

        if len(prompt_context_parts) > 1:
            APP_STATE['prompts_context'] = "\n".join(prompt_context_parts)
        else:
            APP_STATE['prompts_context'] = "--- No Prompts Available ---"
        app_logger.debug(f"Regenerated LLM prompt context. {enabled_count} prompts are active.")

    if disabled_tools_list or disabled_prompts_list:
        constraints_list = []
        if disabled_tools_list:
            constraints_list.extend([f"- `{name}` (tool)" for name in disabled_tools_list])
        if disabled_prompts_list:
            constraints_list.extend([f"- `{name}` (prompt)" for name in disabled_prompts_list])
        
        APP_STATE['constraints_context'] = (
            "\n--- CONSTRAINTS ---\n"
            "You are explicitly forbidden from using the following capabilities in your plan under any circumstances:\n"
            + "\n".join(constraints_list) + "\n"
        )
        app_logger.debug(f"Regenerated LLM constraints context. {len(constraints_list)} capabilities are forbidden.")
    else:
        APP_STATE['constraints_context'] = "" 
        app_logger.debug("Regenerated LLM constraints context. No capabilities are currently forbidden.")

