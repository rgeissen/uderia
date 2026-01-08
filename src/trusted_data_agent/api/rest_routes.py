# src/trusted_data_agent/api/rest_routes.py
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import re
import uuid # Import uuid
import copy # --- MODIFICATION START: Import copy ---
from functools import wraps
import sys

# Import template exceptions
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from rag_templates.exceptions import (
    TemplateError,
    TemplateNotFoundError,
    TemplateValidationError,
    SchemaValidationError,
    TemplateRegistryError,
    TemplateLoadError
)

# --- MODIFICATION START: Import generate_task_id ---
from quart import Blueprint, current_app, jsonify, request, abort
from trusted_data_agent.core.utils import generate_task_id, _get_prompt_info
# --- MODIFICATION END ---

from trusted_data_agent.core.config import APP_CONFIG, APP_STATE
from trusted_data_agent.core import session_manager
from trusted_data_agent.agent import execution_service
from trusted_data_agent.core import configuration_service
from langchain_mcp_adapters.client import MultiServerMCPClient
from trusted_data_agent.auth.admin import require_admin

from trusted_data_agent.agent.executor import PlanExecutor
from langchain_mcp_adapters.prompts import load_mcp_prompt
from trusted_data_agent.llm import handler as llm_handler

rest_api_bp = Blueprint('rest_api', __name__)
app_logger = logging.getLogger("quart.app") # Use quart logger

# Database path - use absolute path to project root (4 parents up from api/rest_routes.py)
DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"

# --- MODIFICATION START: Helper to get User UUID from JWT token ---
def _get_user_uuid_from_request():
    """
    Extract user UUID from JWT authentication token.
    
    Returns:
        Optional[str]: User UUID if authenticated, None otherwise
        
    Note:
        Authentication is always required for REST API.
        Returns None if token is missing or invalid.
    """
    try:
        from trusted_data_agent.auth.middleware import get_current_user
        user = get_current_user()
        if user and user.id:
            return user.id
        else:
            app_logger.warning("REST API: No valid authentication token provided")
            return None
    except Exception as e:
        app_logger.error(f"REST API authentication error: {e}", exc_info=True)
        return None
# --- MODIFICATION END ---


def _validate_user_profile(user_uuid: str) -> tuple[bool, dict]:
    """
    Validate that a user has a properly configured profile for REST operations.
    
    Returns:
        Tuple of (is_valid, error_response_dict)
        - is_valid: True if profile is valid, False otherwise
        - error_response_dict: Contains 'error' key if invalid, empty dict if valid
    
    Profile is valid if:
    - User has a default profile set
    - Default profile exists and is properly configured
    - Default profile has both LLM and MCP server configured
    """
    try:
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        # Check if user has a default profile configured
        default_profile_id = config_manager.get_default_profile_id(user_uuid)
        if not default_profile_id:
            return False, {
                "error": "No default profile configured for this user. Please configure a profile (LLM + MCP Server combination) in the Configuration panel first."
            }
        
        # Verify the default profile exists
        default_profile = config_manager.get_profile(default_profile_id, user_uuid)
        if not default_profile:
            return False, {
                "error": "Default profile not found. Please configure a profile first."
            }
        
        # Extract LLM and MCP configuration from profile
        llm_config_id = default_profile.get("llmConfigurationId")
        mcp_server_id = default_profile.get("mcpServerId")
        profile_type = default_profile.get("profile_type", "tool_enabled")

        # LLM always required
        if not llm_config_id:
            return False, {
                "error": "Profile is incomplete. LLM Provider is required."
            }

        # MCP only required for tool-enabled profiles
        if profile_type == "tool_enabled" and not mcp_server_id:
            return False, {
                "error": "Tool-enabled profiles require an MCP Server configuration."
            }
        
        return True, {}
    except Exception as e:
        app_logger.error(f"REST API profile validation error: {e}", exc_info=True)
        return False, {
            "error": "Failed to validate profile configuration."
        }

# --- MODIFICATION END ---

def _sanitize_for_json(obj):
    """
    Recursively sanitizes an object to make it JSON-serializable by removing
    non-printable characters from strings.
    """
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(elem) for elem in obj]
    elif isinstance(obj, str):
        # Remove ASCII control characters (0x00-0x1F), except for newline,
        # carriage return, and tab, which are valid in JSON strings.
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', obj)
    else:
        return obj


@rest_api_bp.route("/v1/prompts/<prompt_name>/execute", methods=["POST"])
async def execute_prompt(prompt_name: str):
    """
    Execute an MCP prompt with the LLM and return the response.
    
    Requires:
    - User must be authenticated (JWT or Access Token)
    - User must have a configured profile (LLM + MCP server combination)
    
    Request body:
    {
        "arguments": {"database": "mydb", ...}  // Optional prompt arguments
    }
    
    Returns:
    {
        "status": "success",
        "prompt_text": "<rendered prompt>",
        "response": "<LLM response>",
        "input_tokens": 123,
        "output_tokens": 456
    }
    """
    try:
        # Get user context
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({
                "status": "error",
                "message": "Authentication required"
            }), 401
        
        # Validate user has a configured profile
        is_valid, error_response = _validate_user_profile(user_uuid)
        if not is_valid:
            return jsonify(error_response), 400
        
        # Switch to user's default profile context
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        default_profile_id = config_manager.get_default_profile_id(user_uuid)
        
        from trusted_data_agent.core.configuration_service import switch_profile_context
        profile_context = await switch_profile_context(default_profile_id, user_uuid, validate_llm=False)
        
        if "error" in profile_context:
            return jsonify({
                "status": "error",
                "message": f"Failed to activate user profile: {profile_context.get('error')}"
            }), 503
        
        mcp_client = APP_STATE.get("mcp_client")
        if not mcp_client:
            return jsonify({
                "status": "error",
                "message": "MCP client not configured for profile"
            }), 503

        server_name = APP_CONFIG.CURRENT_MCP_SERVER_NAME
        if not server_name:
            return jsonify({
                "status": "error",
                "message": "MCP server not configured for profile"
            }), 503
            
        llm_instance = APP_STATE.get('llm')
        if not llm_instance:
            return jsonify({
                "status": "error",
                "message": "LLM not configured for profile"
            }), 503

        # Get arguments from request body
        data = await request.get_json() or {}
        user_arguments = data.get('arguments', {})
        
        # Get prompt definition to know all expected arguments
        prompt_info = _get_prompt_info(prompt_name)
        prompt_arguments = {}
        
        if prompt_info and prompt_info.get("arguments"):
            # Build complete argument set - MCP server may require all arguments
            for arg in prompt_info["arguments"]:
                arg_name = arg.get("name")
                if arg_name:
                    if arg_name in user_arguments:
                        # Use user-provided value
                        prompt_arguments[arg_name] = user_arguments[arg_name]
                    elif arg.get("required"):
                        # Required argument missing
                        return jsonify({
                            "status": "error",
                            "message": f"Required argument '{arg_name}' is missing"
                        }), 400
                    else:
                        # Optional argument - use placeholder or empty string
                        prompt_arguments[arg_name] = ""
        else:
            # No argument definition found, use what user provided
            prompt_arguments = user_arguments
        
        # Load the prompt with arguments
        app_logger.info(f"Executing prompt '{prompt_name}' with server '{server_name}' and arguments: {prompt_arguments}")
        
        try:
            async with mcp_client.session(server_name) as temp_session:
                if prompt_arguments:
                    prompt_obj = await load_mcp_prompt(
                        temp_session, name=prompt_name, arguments=prompt_arguments
                    )
                else:
                    prompt_obj = await temp_session.get_prompt(name=prompt_name)
        except Exception as e:
            app_logger.error(f"Failed to load prompt '{prompt_name}' from MCP server: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": f"Failed to load prompt from MCP server: {str(e)}"
            }), 500
        
        if not prompt_obj:
            return jsonify({
                "status": "error",
                "message": f"Prompt '{prompt_name}' not found"
            }), 404
        
        # Extract prompt text (reuse existing logic from planner.py)
        prompt_text = ""
        if isinstance(prompt_obj, str):
            prompt_text = prompt_obj
        elif (isinstance(prompt_obj, list) and len(prompt_obj) > 0 and 
              hasattr(prompt_obj[0], 'content')):
            if isinstance(prompt_obj[0].content, str):
                prompt_text = prompt_obj[0].content
            elif hasattr(prompt_obj[0].content, 'text'):
                prompt_text = prompt_obj[0].content.text
        elif (hasattr(prompt_obj, 'messages') and 
              isinstance(prompt_obj.messages, list) and 
              len(prompt_obj.messages) > 0 and 
              hasattr(prompt_obj.messages[0], 'content') and 
              hasattr(prompt_obj.messages[0].content, 'text')):
            prompt_text = prompt_obj.messages[0].content.text
        elif hasattr(prompt_obj, 'text') and isinstance(prompt_obj.text, str):
            prompt_text = prompt_obj.text
            
        if not prompt_text:
            return jsonify({
                "status": "error",
                "message": "Could not extract text from prompt"
            }), 500
        
        # Log the rendered prompt for debugging
        
        # Create a temporary session and use the agent execution service
        # This ensures tools are properly registered and execution is autonomous
        llm_instance = APP_STATE.get("llm")
        
        temp_session_id = await session_manager.create_session(
            user_uuid=user_uuid,
            provider=APP_CONFIG.CURRENT_PROVIDER,
            llm_instance=llm_instance,
            charting_intensity="medium",
            is_temporary=True,
            temporary_purpose=f"Prompt execution: {prompt_name}"
        )
        
        app_logger.info(f"Executing MCP prompt '{prompt_name}' via agent execution service with temp session: {temp_session_id}")
        
        # Create a dummy event handler for API calls (no SSE needed)
        async def dummy_event_handler(data, event_type):
            pass
        
        # Execute using the agent execution service which handles tool registration properly
        result_payload = await execution_service.run_agent_execution(
            user_uuid=user_uuid,
            session_id=temp_session_id,
            user_input=prompt_text,
            event_handler=dummy_event_handler,  # Provide dummy handler instead of None
            source='prompt_library'  # Indicates this is a prompt execution
        )
        
        # Extract response and tokens from result
        response_html = result_payload.get('final_answer', '')
        response_text = result_payload.get('final_answer_text', '')  # Clean text without HTML
        input_tokens = result_payload.get('total_input_tokens', 0)
        output_tokens = result_payload.get('total_output_tokens', 0)
        actual_provider = APP_CONFIG.CURRENT_PROVIDER
        actual_model = APP_CONFIG.CURRENT_MODEL
        
        # Archive the temporary session (don't delete - keep for transparency)
        try:
            app_logger.info(f"Attempting to archive temporary session: {temp_session_id}")
            success = await session_manager.delete_session(user_uuid, temp_session_id)
            if success:
                app_logger.info(f"Successfully archived temporary session: {temp_session_id}")
            else:
                app_logger.error(f"Failed to archive temporary session {temp_session_id}: delete_session returned False")
        except Exception as e:
            app_logger.error(f"Exception while archiving temp session {temp_session_id}: {e}", exc_info=True)
        
        app_logger.info(f"Prompt '{prompt_name}' executed successfully. Tokens: in={input_tokens}, out={output_tokens}")
        
        return jsonify({
            "status": "success",
            "prompt_text": prompt_text,
            "response": response_html,  # HTML formatted response for display
            "response_text": response_text,  # Clean text for LLM consumption
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "provider": actual_provider,
            "model": actual_model
        })
        
    except Exception as e:
        app_logger.error(f"Error executing prompt '{prompt_name}': {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@rest_api_bp.route("/v1/prompts/<prompt_name>/execute-raw", methods=["POST"])
async def execute_prompt_raw(prompt_name: str):
    """
    Execute an MCP prompt and return raw, structured execution data.
    
    This endpoint is designed for programmatic consumption (e.g., auto-generating RAG cases)
    where clean, structured data is needed rather than HTML-formatted responses.
    
    Request body:
    {
        "arguments": {"database": "mydb", ...}  // Optional prompt arguments
    }
    
    Returns:
    {
        "status": "success",
        "prompt_text": "<rendered prompt>",
        "execution_trace": [...],
        "collected_data": {...},
        "final_answer_text": "<clean LLM summary>",
        "token_usage": {"input": 123, "output": 456, "total": 579}
    }
    """
    try:
        # Get request data early to check for MCP server override
        data = await request.get_json() or {}
        requested_mcp_server_id = data.get('mcp_server_id')
        
        # Try to get global MCP client (works if system is configured globally)
        mcp_client = APP_STATE.get("mcp_client")
        server_name = APP_CONFIG.CURRENT_MCP_SERVER_NAME
        llm_instance = APP_STATE.get('llm')
        
        # If MCP server specified in request, override with that
        if requested_mcp_server_id:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            mcp_servers = config_manager.get_mcp_servers()
            mcp_server = next((s for s in mcp_servers if s.get("id") == requested_mcp_server_id), None)
            if mcp_server:
                server_name = mcp_server.get("name")
                current_app.logger.info(f"Using MCP server from request: {server_name}")
                # Also need to get the MCP client for this user
                user_uuid = _get_user_uuid_from_request()
                current_app.logger.info(f"User UUID: {user_uuid}")
                if user_uuid:
                    from trusted_data_agent.core.config import get_user_mcp_client, get_user_llm_instance, set_user_mcp_client, set_user_llm_instance
                    
                    if not mcp_client:
                        mcp_client = get_user_mcp_client(user_uuid)
                    if not llm_instance:
                        llm_instance = get_user_llm_instance(user_uuid)
                    
                    current_app.logger.info(f"User instances from cache - MCP: {mcp_client is not None}, LLM: {llm_instance is not None}")
                    
                    # If not available, try to create from user's default profile
                    if not mcp_client or not llm_instance:
                        try:
                            default_profile_id = config_manager.get_default_profile_id(user_uuid)
                            if default_profile_id:
                                profile = config_manager.get_profile(default_profile_id, user_uuid)
                                current_app.logger.info(f"Loading from default profile: {profile.get('profileName') if profile else 'Not found'}")
                                
                                if profile:
                                    # Create LLM instance from profile
                                    if not llm_instance:
                                        llm_config_id = profile.get("llmConfigurationId")
                                        if llm_config_id:
                                            llm_configs = config_manager.get_llm_configurations(user_uuid)
                                            llm_config = next((cfg for cfg in llm_configs if cfg.get("id") == llm_config_id), None)
                                            if llm_config:
                                                from trusted_data_agent.llm.client_factory import create_llm_client
                                                provider = llm_config.get("provider")
                                                model = llm_config.get("model")
                                                credentials = llm_config.get("credentials", {})
                                                llm_instance = await create_llm_client(provider, model, credentials)
                                                set_user_llm_instance(llm_instance, user_uuid)
                                                current_app.logger.info("Created LLM instance from profile")
                                    
                                    # Create MCP client from profile
                                    if not mcp_client:
                                        from trusted_data_agent.mcp import MCPClientManager
                                        mcp_manager = MCPClientManager.get_instance()
                                        mcp_client = await mcp_manager.get_client(user_uuid)
                                        if mcp_client:
                                            set_user_mcp_client(mcp_client, user_uuid)
                                            current_app.logger.info("Created MCP client from profile")
                        except Exception as e:
                            current_app.logger.error(f"Error loading from profile: {e}", exc_info=True)
            else:
                current_app.logger.warning(f"MCP server with ID {requested_mcp_server_id} not found")
        
        # If no global config, try to get from authenticated user's profile
        if not mcp_client or not server_name or not llm_instance:
            user_uuid = _get_user_uuid_from_request()
            if not user_uuid:
                return jsonify({"status": "error", "message": "Authentication required and no global MCP/LLM configured"}), 401
            
            # Get user's default profile
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            default_profile_id = config_manager.get_default_profile_id(user_uuid)
            if not default_profile_id:
                return jsonify({"status": "error", "message": "No default profile configured. Please set up a profile in Configuration panel."}), 400
            
            default_profile = config_manager.get_profile(default_profile_id, user_uuid)
            if not default_profile:
                return jsonify({"status": "error", "message": "Default profile not found"}), 400
            
            # Get MCP server from profile
            mcp_server_id = default_profile.get("mcpServerId")
            if mcp_server_id and not server_name:
                mcp_servers = config_manager.get_mcp_servers()
                mcp_server = next((s for s in mcp_servers if s.get("id") == mcp_server_id), None)
                if mcp_server:
                    server_name = mcp_server.get("name")
            
            # Get user's MCP client if not available globally
            if not mcp_client:
                from trusted_data_agent.core.config import get_user_mcp_client
                mcp_client = get_user_mcp_client(user_uuid)
            
            # Get user's LLM if not available globally
            if not llm_instance:
                from trusted_data_agent.core.config import get_user_llm_instance
                llm_instance = get_user_llm_instance(user_uuid)
        
        # Final validation
        current_app.logger.info(f"Final validation - mcp_client: {mcp_client is not None}, server_name: {server_name}, llm_instance: {llm_instance is not None}")
        if not mcp_client:
            return jsonify({"status": "error", "message": "MCP client not configured. Please activate a profile in the Configuration panel."}), 400
        if not server_name:
            return jsonify({"status": "error", "message": "MCP server not configured. Please activate a profile in the Configuration panel."}), 400
        if not llm_instance:
            return jsonify({"status": "error", "message": "LLM not configured. Please activate a profile in the Configuration panel."}), 400

        # Get arguments from request body (data already loaded above)
        user_arguments = data.get('arguments', {})
        
        # Get prompt definition to know all expected arguments
        prompt_info = _get_prompt_info(prompt_name)
        prompt_arguments = {}
        
        if prompt_info and prompt_info.get("arguments"):
            for arg in prompt_info["arguments"]:
                arg_name = arg.get("name")
                if arg_name:
                    if arg_name in user_arguments:
                        prompt_arguments[arg_name] = user_arguments[arg_name]
                    elif arg.get("required"):
                        return jsonify({
                            "status": "error",
                            "message": f"Required argument '{arg_name}' is missing"
                        }), 400
                    else:
                        prompt_arguments[arg_name] = ""
        else:
            prompt_arguments = user_arguments
        
        # Load the prompt with arguments
        app_logger.info(f"Executing prompt '{prompt_name}' (raw mode) with server '{server_name}'")
        
        try:
            async with mcp_client.session(server_name) as temp_session:
                if prompt_arguments:
                    prompt_obj = await load_mcp_prompt(
                        temp_session, name=prompt_name, arguments=prompt_arguments
                    )
                else:
                    prompt_obj = await temp_session.get_prompt(name=prompt_name)
        except Exception as e:
            app_logger.error(f"Failed to load prompt '{prompt_name}': {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": f"Failed to load prompt: {str(e)}"
            }), 500
        
        if not prompt_obj:
            return jsonify({"status": "error", "message": f"Prompt '{prompt_name}' not found"}), 404
        
        # Extract prompt text (reuse existing logic)
        prompt_text = ""
        if isinstance(prompt_obj, str):
            prompt_text = prompt_obj
        elif (isinstance(prompt_obj, list) and len(prompt_obj) > 0 and 
              hasattr(prompt_obj[0], 'content')):
            if isinstance(prompt_obj[0].content, str):
                prompt_text = prompt_obj[0].content
            elif hasattr(prompt_obj[0].content, 'text'):
                prompt_text = prompt_obj[0].content.text
        elif (hasattr(prompt_obj, 'messages') and 
              isinstance(prompt_obj.messages, list) and 
              len(prompt_obj.messages) > 0 and 
              hasattr(prompt_obj.messages[0], 'content') and 
              hasattr(prompt_obj.messages[0].content, 'text')):
            prompt_text = prompt_obj.messages[0].content.text
        elif hasattr(prompt_obj, 'text') and isinstance(prompt_obj.text, str):
            prompt_text = prompt_obj.text
            
        if not prompt_text:
            return jsonify({"status": "error", "message": "Could not extract text from prompt"}), 500
        
        # Get authenticated user UUID for session creation
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        # Create temporary session for the authenticated user
        temp_session_id = await session_manager.create_session(
            user_uuid=user_uuid,
            provider=APP_CONFIG.CURRENT_PROVIDER,
            llm_instance=llm_instance,
            charting_intensity="medium",
            is_temporary=True,
            temporary_purpose=f"Prompt execution: {prompt_name}"
        )
        
        app_logger.info(f"Executing prompt '{prompt_name}' (raw) with temp session: {temp_session_id}")
        
        # Dummy event handler
        async def dummy_event_handler(data, event_type):
            pass
        
        # Execute via agent execution service
        result_payload = await execution_service.run_agent_execution(
            user_uuid=user_uuid,
            session_id=temp_session_id,
            user_input=prompt_text,
            event_handler=dummy_event_handler,
            source='prompt_library_raw'
        )
        
        # Archive temp session (don't delete - keep for transparency)
        try:
            app_logger.info(f"Attempting to archive temporary session: {temp_session_id}")
            success = await session_manager.delete_session(user_uuid, temp_session_id)
            if success:
                app_logger.info(f"Successfully archived temporary session: {temp_session_id}")
            else:
                app_logger.error(f"Failed to archive temporary session {temp_session_id}: delete_session returned False")
        except Exception as e:
            app_logger.error(f"Exception while archiving temp session {temp_session_id}: {e}", exc_info=True)
        
        # Extract data from result
        execution_trace = result_payload.get('execution_trace', [])
        collected_data = result_payload.get('collected_data', {})
        final_answer_text = result_payload.get('final_answer_text', '')
        input_tokens = result_payload.get('turn_input_tokens', 0)
        output_tokens = result_payload.get('turn_output_tokens', 0)
        
        app_logger.info(f"Prompt '{prompt_name}' (raw) done. Tokens: in={input_tokens}, out={output_tokens}")
        
        return jsonify({
            "status": "success",
            "prompt_text": prompt_text,
            "execution_trace": execution_trace,
            "collected_data": collected_data,
            "final_answer_text": final_answer_text,
            "token_usage": {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens
            },
            "provider": APP_CONFIG.CURRENT_PROVIDER,
            "model": APP_CONFIG.CURRENT_MODEL
        })
        
    except Exception as e:
        app_logger.error(f"Error executing prompt '{prompt_name}' (raw): {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


def build_question_generation_prompt(prompt_config, context_content, variables):
    """
    Build a question generation prompt from template configuration.
    
    Args:
        prompt_config: Dictionary with prompt template structure from manifest
        context_content: The main context (database schema or document text)
        variables: Dict with {subject, count, database_name, target_database, conversion_rules}
    
    Returns:
        str: Formatted prompt ready for LLM
    """
    # Extract variables
    subject = variables.get('subject', '')
    count = variables.get('count', 5)
    database_name = variables.get('database_name', '')
    target_database = variables.get('target_database', 'Teradata')
    conversion_rules = variables.get('conversion_rules', '')
    context_label = variables.get('context_label', 'Technical Documentation')
    
    # Build conversion rules section if provided
    conversion_rules_section = ""
    if conversion_rules:
        conversion_rules_section = f"\n{len(prompt_config.get('requirements', [])) + 1}. CRITICAL: Follow these explicit {target_database} conversion rules:\n{conversion_rules}\n"
    
    # Build requirements list
    requirements = prompt_config.get('requirements', [])
    requirements_text = ""
    for i, req in enumerate(requirements, 1):
        # Apply variable substitution
        req_text = req.format(
            count=count,
            subject=subject,
            target_database=target_database,
            database_name=database_name
        )
        requirements_text += f"{i}. {req_text}\n"
    
    # Add conversion rules if present
    if conversion_rules_section:
        requirements_text += conversion_rules_section
    
    # Add final requirement for output format
    requirements_text += f"{len(requirements) + (1 if conversion_rules else 0) + 1}. {prompt_config.get('output_format', '').format(database_name=database_name)}"
    
    # Build approach instructions if present
    approach_section = ""
    if 'approach_instructions' in prompt_config:
        approach_section = f"\n{prompt_config['approach_instructions'].format(target_database=target_database, database_name=database_name)}\n\n"
    
    # Build critical guidelines
    guidelines = prompt_config.get('critical_guidelines', [])
    guidelines_text = "\n".join([f"- {g.format(count=count)}" for g in guidelines])
    
    # Construct final prompt
    prompt = f"""{prompt_config.get('system_role', '')}

{prompt_config.get('task_description', '').format(count=count, subject=subject)}
{approach_section}
{context_label}:
{context_content}

Requirements:
{requirements_text}

CRITICAL GUIDELINES:
{guidelines_text}"""
    
    return prompt


@rest_api_bp.route("/v1/rag/generate-questions", methods=["POST"])
async def generate_rag_questions():
    """
    Generate question/SQL pairs for RAG collection population.
    
    Request body:
    {
        "subject": "sales analysis",
        "count": 5,
        "database_context": "...",  // Output from Phase 2 (database context)
        "database_name": "fitness_db"
    }
    
    Returns:
    {
        "status": "success",
        "questions": [
            {"question": "What are...", "sql": "SELECT..."},
            ...
        ],
        "count": 5
    }
    """
    try:
        # Get authenticated user
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({
                "status": "error",
                "message": "Authentication required"
            }), 401
        
        # Validate user has a configured profile
        is_valid, error_response = _validate_user_profile(user_uuid)
        if not is_valid:
            return jsonify(error_response), 400
        
        # Switch to user's default profile context
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        default_profile_id = config_manager.get_default_profile_id(user_uuid)
        
        from trusted_data_agent.core.configuration_service import switch_profile_context
        profile_context = await switch_profile_context(default_profile_id, user_uuid, validate_llm=False)
        
        if "error" in profile_context:
            return jsonify({
                "status": "error",
                "message": f"Failed to activate user profile: {profile_context.get('error')}"
            }), 503
        
        # Get configuration from activated profile
        mcp_client = APP_STATE.get("mcp_client")
        if not mcp_client:
            return jsonify({
                "status": "error",
                "message": "MCP client not configured for profile"
            }), 503

        llm_instance = APP_STATE.get('llm')
        if not llm_instance:
            return jsonify({
                "status": "error",
                "message": "LLM not configured for profile"
            }), 503
        
        # Check if LLM is a placeholder (credentials not configured)
        if isinstance(llm_instance, dict) and llm_instance.get('placeholder'):
            return jsonify({
                "status": "error",
                "message": f"LLM credentials not configured. Please add credentials for {llm_instance.get('provider')} in the Configuration panel."
            }), 503

        # Get parameters from request
        data = await request.get_json() or {}
        subject = data.get('subject', '').strip()
        count = int(data.get('count', 5))
        database_context = data.get('database_context', '').strip()
        execution_trace = data.get('execution_trace', [])  # Get full execution trace if provided
        database_name = data.get('database_name', '').strip()
        target_database = data.get('target_database', 'Teradata').strip()
        conversion_rules = data.get('conversion_rules', '').strip()
        
        # DEBUG: Log execution_trace structure
        app_logger.info(f"[DEBUG] execution_trace type: {type(execution_trace)}")
        if execution_trace and isinstance(execution_trace, list) and len(execution_trace) > 0:
            app_logger.info(f"[DEBUG] First trace_item type: {type(execution_trace[0])}")
            app_logger.info(f"[DEBUG] First trace_item: {execution_trace[0]}")
            if isinstance(execution_trace[0], dict):
                action_value = execution_trace[0].get('action')
                app_logger.info(f"[DEBUG] First action type: {type(action_value)}, value: {action_value}")
        
        # Extract meaningful content from execution trace
        # Skip TDA_SystemLog (clutter), extract everything else
        schema_details = ""
        if execution_trace and isinstance(execution_trace, list):
            for trace_item in execution_trace:
                if not isinstance(trace_item, dict):
                    continue
                    
                action = trace_item.get('action', {})
                result = trace_item.get('result', {})
                
                # Ensure action is a dict before trying to access it
                if not isinstance(action, dict):
                    continue
                
                tool_name = action.get('tool_name', '')
                
                # Skip system log messages (clutter) - only hardcoded TDA_ function
                if tool_name == 'TDA_SystemLog':
                    continue
                
                if not isinstance(result, dict):
                    continue
                    
                results_array = result.get('results', [])
                if not results_array or not isinstance(results_array, list):
                    continue
                
                for item in results_array:
                    if not isinstance(item, dict):
                        continue
                    
                    # Extract any text fields that look meaningful
                    # Check for common field names in order of preference
                    content = None
                    
                    # First priority: structured outputs from TDA tools
                    if tool_name == 'TDA_FinalReport':
                        direct_answer = item.get('direct_answer', '')
                        if direct_answer:
                            schema_details += f"\n\n{direct_answer}"
                        
                        key_observations = item.get('key_observations', [])
                        if key_observations:
                            for obs in key_observations:
                                if isinstance(obs, dict):
                                    text = obs.get('text', '')
                                    if text:
                                        schema_details += f"\n- {text}"
                        continue
                    
                    if tool_name == 'TDA_LLMTask':
                        content = item.get('response', '')
                    
                    # Second priority: common MCP tool output fields
                    if not content:
                        content = item.get('tool_output', '')
                    if not content:
                        content = item.get('content', '')
                    if not content:
                        content = item.get('Request Text', '')
                    
                    # Add the content if it's substantial
                    if content and isinstance(content, str) and len(content.strip()) > 20:
                        # Clean up formatting
                        cleaned = content.replace('\r', ' ').replace('\n', ' ')
                        cleaned = ' '.join(cleaned.split())
                        schema_details += f"\n\n{cleaned}"
        
        # Combine context with extracted schema details
        full_context = database_context
        if schema_details:
            full_context = f"{database_context}\n\n=== Detailed Schema Information ===\n{schema_details}"
            app_logger.info(f"Extracted schema details from execution trace ({len(schema_details)} chars)")
        else:
            app_logger.warning("No schema details extracted from execution trace - questions may be less accurate")
        
        if not subject:
            return jsonify({
                "status": "error",
                "message": "Subject is required"
            }), 400
            
        if not database_context:
            return jsonify({
                "status": "error",
                "message": "Database context is required (run Phase 2 first)"
            }), 400
            
        if not database_name:
            return jsonify({
                "status": "error",
                "message": "Database name is required"
            }), 400
        
        # Get template prompt configuration
        try:
            template_manager = APP_STATE.get('template_manager')
            if not template_manager:
                app_logger.warning("Template manager not available, using fallback prompt")
                raise ValueError("Template manager not available")
            
            # Get plugin info which includes prompt templates
            plugin_info = template_manager.get_plugin_info('sql_query_v1')
            prompt_config = plugin_info.get('prompt_templates', {}).get('question_generation', {})
            
            if not prompt_config:
                app_logger.warning("No prompt template found in manifest, using fallback")
                raise ValueError("No prompt template in manifest")
            
            # Build prompt from template
            prompt_text = build_question_generation_prompt(
                prompt_config=prompt_config,
                context_content=full_context,
                variables={
                    'subject': subject,
                    'count': count,
                    'database_name': database_name,
                    'target_database': target_database,
                    'conversion_rules': conversion_rules,
                    'context_label': 'Database Context'
                }
            )
            
        except Exception as e:
            app_logger.error(f"Failed to load prompt from template, using fallback: {e}")
            # Fallback to simple prompt if template loading fails
            prompt_text = f"""You are a SQL expert. Generate {count} question/SQL pairs about "{subject}" for database "{database_name}" using {target_database} syntax.

Database Context:
{full_context}

Return ONLY a JSON array: [{{"question": "...", "sql": "..."}}]"""

        app_logger.info(f"Generating {count} RAG questions for subject '{subject}' in database '{database_name}' (context: {len(full_context)} chars)")

        # Get authenticated user UUID
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        # Call LLM directly using the handler to avoid agent execution framework and TDA_FinalReport validation
        from trusted_data_agent.llm import handler as llm_handler

        # Implement batching to avoid token limit issues with large question counts
        # Most LLMs have 8K-16K output token limits; a question pair ~= 100-150 tokens
        # Safe batch size: 20 questions per batch (estimate ~3000 tokens)
        BATCH_SIZE = 20
        all_questions = []
        total_input_tokens = 0
        total_output_tokens = 0

        # Calculate number of batches needed
        num_batches = (count + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division

        if num_batches > 1:
            app_logger.info(f"Splitting {count} questions into {num_batches} batches of up to {BATCH_SIZE} questions each")

        try:
            for batch_num in range(num_batches):
                batch_start = batch_num * BATCH_SIZE
                batch_count = min(BATCH_SIZE, count - batch_start)

                # Build context of previously generated questions to avoid duplicates
                previous_questions_context = ""
                if batch_num > 0 and all_questions:
                    # Show LLM what questions were already generated
                    prev_count = len(all_questions)
                    prev_questions_list = "\n".join([
                        f"  - {q['question']}"
                        for q in all_questions[:min(10, prev_count)]  # Show first 10 as examples
                    ])
                    if prev_count > 10:
                        prev_questions_list += f"\n  ... and {prev_count - 10} more questions"

                    previous_questions_context = f"""

IMPORTANT - AVOID DUPLICATES:
The following {prev_count} questions have ALREADY been generated in previous batches.
You MUST generate {batch_count} NEW and DIFFERENT questions that cover different aspects:

Previously Generated Questions:
{prev_questions_list}

Generate {batch_count} questions that explore DIFFERENT topics, tables, or analytical angles.
"""

                # Update prompt for this batch
                if num_batches > 1:
                    # Rebuild prompt with batch-specific count and previous context
                    try:
                        batch_prompt_text = build_question_generation_prompt(
                            prompt_config=prompt_config,
                            context_content=full_context,
                            variables={
                                'subject': subject,
                                'count': batch_count,
                                'database_name': database_name,
                                'target_database': target_database,
                                'conversion_rules': conversion_rules,
                                'context_label': 'Database Context'
                            }
                        )
                        # Append previous questions context
                        batch_prompt_text += previous_questions_context
                    except:
                        # Fallback if template failed
                        batch_prompt_text = f"""You are a SQL expert. Generate {batch_count} question/SQL pairs about "{subject}" for database "{database_name}" using {target_database} syntax.

Database Context:
{full_context}
{previous_questions_context}

Return ONLY a JSON array: [{{"question": "...", "sql": "..."}}]"""
                else:
                    # Single batch - use original prompt
                    batch_prompt_text = prompt_text

                app_logger.info(f"Generating batch {batch_num + 1}/{num_batches}: {batch_count} questions")

                # Direct LLM invocation using the existing handler
                response_text, input_tokens, output_tokens, provider, model = await llm_handler.call_llm_api(
                    llm_instance=llm_instance,
                    prompt=batch_prompt_text,
                    user_uuid=user_uuid,
                    session_id=None,
                    dependencies={'STATE': APP_STATE, 'CONFIG': APP_CONFIG},
                    reason=f"Generating RAG questions (batch {batch_num + 1}/{num_batches})",
                    disabled_history=True,  # Don't store this in chat history
                    source='rag_question_generator'
                )

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens

                app_logger.info(f"Batch {batch_num + 1}/{num_batches} completed: {input_tokens} input tokens, {output_tokens} output tokens")

                # Parse this batch's JSON response
                try:
                    # Try to extract JSON if wrapped in markdown code blocks
                    json_text = response_text.strip()
                    if json_text.startswith('```json'):
                        json_text = json_text[7:]  # Remove ```json
                    elif json_text.startswith('```'):
                        json_text = json_text[3:]  # Remove ```
                    if json_text.endswith('```'):
                        json_text = json_text[:-3]  # Remove trailing ```
                    json_text = json_text.strip()

                    batch_questions = json.loads(json_text)

                    if not isinstance(batch_questions, list):
                        raise ValueError(f"Batch {batch_num + 1} response is not a JSON array")

                    # Validate structure for this batch
                    for q in batch_questions:
                        if not isinstance(q, dict) or 'question' not in q or 'sql' not in q:
                            raise ValueError(f"Batch {batch_num + 1} has invalid question structure")

                    all_questions.extend(batch_questions)
                    app_logger.info(f"Batch {batch_num + 1}/{num_batches} parsed successfully: {len(batch_questions)} questions")

                except json.JSONDecodeError as e:
                    app_logger.error(f"Failed to parse batch {batch_num + 1} response as JSON: {e}")
                    app_logger.error(f"Batch {batch_num + 1} response was: {response_text[:500]}")
                    return jsonify({
                        "status": "error",
                        "message": f"Batch {batch_num + 1} did not return valid JSON",
                        "raw_response": response_text[:1000]
                    }), 500
                except ValueError as e:
                    app_logger.error(f"Batch {batch_num + 1} invalid structure: {e}")
                    return jsonify({
                        "status": "error",
                        "message": str(e),
                        "raw_response": response_text[:1000]
                    }), 500

            # All batches completed successfully
            app_logger.info(f"Generated {len(all_questions)} question/SQL pairs across {num_batches} batch(es)")

            # Deduplicate questions using fuzzy matching
            # Remove exact duplicates and very similar questions
            deduplicated_questions = []
            seen_questions_lower = set()
            seen_sql_normalized = set()
            duplicates_removed = 0

            for q in all_questions:
                question_text = q.get('question', '').strip()
                sql_text = q.get('sql', '').strip()

                # Normalize for comparison
                question_lower = question_text.lower()
                # Normalize SQL: remove extra whitespace, convert to lowercase
                sql_normalized = ' '.join(sql_text.lower().split())

                # Check for exact duplicates (case-insensitive)
                if question_lower in seen_questions_lower or sql_normalized in seen_sql_normalized:
                    duplicates_removed += 1
                    app_logger.debug(f"Removed duplicate: {question_text[:50]}...")
                    continue

                # Add to results and tracking sets
                deduplicated_questions.append(q)
                seen_questions_lower.add(question_lower)
                seen_sql_normalized.add(sql_normalized)

            if duplicates_removed > 0:
                app_logger.info(f"Removed {duplicates_removed} duplicate questions. Final count: {len(deduplicated_questions)}")
            else:
                app_logger.info(f"No duplicates found. Final count: {len(deduplicated_questions)}")

            return jsonify({
                "status": "success",
                "questions": deduplicated_questions,
                "count": len(deduplicated_questions),
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "batches": num_batches,
                "duplicates_removed": duplicates_removed
            })

        except Exception as e:
            app_logger.error(f"Failed to generate questions with LLM: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": f"LLM invocation failed: {str(e)}"
            }), 500
        
    except Exception as e:
        app_logger.error(f"Error generating RAG questions: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@rest_api_bp.route("/v1/rag/generate-questions-from-documents", methods=["POST"])
async def generate_rag_questions_from_documents():
    """
    Generate question/SQL pairs from uploaded documents for Document Context template.
    
    Request body (multipart/form-data):
    {
        "subject": "sales analysis",
        "count": 5,
        "database_name": "fitness_db",
        "target_database": "Teradata",
        "conversion_rules": "...",
        "files": [document files]
    }
    
    Returns:
    {
        "status": "success",
        "questions": [
            {"question": "What are...", "sql": "SELECT..."},
            ...
        ],
        "count": 5
    }
    """
    try:
        # Get authenticated user
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({
                "status": "error",
                "message": "Authentication required"
            }), 401
        
        # Validate user has a configured profile
        is_valid, error_response = _validate_user_profile(user_uuid)
        if not is_valid:
            return jsonify(error_response), 400
        
        # Switch to user's default profile context
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        default_profile_id = config_manager.get_default_profile_id(user_uuid)
        
        from trusted_data_agent.core.configuration_service import switch_profile_context
        profile_context = await switch_profile_context(default_profile_id, user_uuid, validate_llm=False)
        
        if "error" in profile_context:
            return jsonify({
                "status": "error",
                "message": f"Failed to activate user profile: {profile_context.get('error')}"
            }), 503
        
        # Get configuration from activated profile
        llm_instance = APP_STATE.get('llm')
        if not llm_instance:
            return jsonify({
                "status": "error",
                "message": "LLM not configured for profile"
            }), 503
        
        # Get provider info from profile (as backup to llm_instance)
        default_profile = config_manager.get_profile(default_profile_id, user_uuid)
        llm_config_id = default_profile.get("llmConfigurationId") if default_profile else None
        profile_provider = None
        profile_model = None
        
        if llm_config_id:
            # Get all LLM configurations and find the one matching our ID
            all_llm_configs = config_manager.get_llm_configurations(user_uuid)
            llm_config = next((cfg for cfg in all_llm_configs if cfg.get("id") == llm_config_id), None)
            if llm_config:
                profile_provider = llm_config.get("provider")
                profile_model = llm_config.get("model")
                app_logger.info(f"Profile LLM config: {profile_provider}/{profile_model}")

        # Get form data
        form_data = await request.form
        files = await request.files
        
        subject = form_data.get('subject', '').strip()
        count = int(form_data.get('count', 5))
        database_name = form_data.get('database_name', '').strip()
        target_database = form_data.get('target_database', 'Teradata').strip()
        conversion_rules = form_data.get('conversion_rules', '').strip()
        
        # Validate inputs
        if not subject:
            return jsonify({
                "status": "error",
                "message": "Subject is required"
            }), 400
            
        if not database_name:
            return jsonify({
                "status": "error",
                "message": "Database name is required"
            }), 400
        
        # Process uploaded documents using DocumentUploadHandler
        from trusted_data_agent.llm.document_upload import DocumentUploadHandler
        from trusted_data_agent.llm.document_upload_config_manager import DocumentUploadConfigManager
        import tempfile
        import os as os_module
        
        file_list = files.getlist('files')
        
        if not file_list or len(file_list) == 0:
            return jsonify({
                "status": "error",
                "message": "At least one document file is required"
            }), 400
        
        app_logger.info(f"Processing {len(file_list)} document(s) for question generation")
        
        # Get LLM provider information (handle both dict and object instances)
        if isinstance(llm_instance, dict):
            # Placeholder dict from configuration_service
            provider_name = llm_instance.get('provider', 'Unknown')
            model_name = llm_instance.get('model', None)
        else:
            # Actual LLM instance
            provider_name = getattr(llm_instance, 'provider', 'Unknown')
            model_name = getattr(llm_instance, 'model', None)
        
        # Fallback to profile config if llm_instance doesn't have provider
        if provider_name == 'Unknown' and profile_provider:
            provider_name = profile_provider
            model_name = profile_model
            app_logger.info(f"Using provider from profile config: {provider_name}/{model_name}")
        
        app_logger.info(f"Using provider: {provider_name}, model: {model_name}")
        
        # Check effective configuration for this provider
        effective_config = DocumentUploadConfigManager.get_effective_config(provider_name)
        
        if not effective_config['enabled']:
            return jsonify({
                "status": "error",
                "message": f"Document upload is disabled for provider: {provider_name}"
            }), 400
        
        app_logger.info(f"Document upload config for {provider_name}: capability={effective_config['capability']}, native={effective_config['use_native_upload']}, max_size={effective_config['max_file_size_mb']}MB")
        
        # Initialize document handler
        doc_handler = DocumentUploadHandler()
        
        # Process documents based on capability
        processed_documents = []
        temp_files = []  # Track temp files for cleanup
        
        try:
            for file in file_list:
                try:
                    filename = file.filename
                    app_logger.info(f"Processing document: {filename}")
                    
                    # Read file content (synchronous in Quart)
                    file_content = file.read()
                    
                    # Validate file size
                    file_size_mb = len(file_content) / (1024 * 1024)
                    max_size = effective_config['max_file_size_mb']
                    
                    if file_size_mb > max_size:
                        return jsonify({
                            "status": "error",
                            "message": f"File {filename} exceeds maximum size of {max_size}MB (actual: {file_size_mb:.1f}MB)"
                        }), 400
                    
                    # Save to temporary file for processing
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os_module.path.splitext(filename)[1])
                    temp_file.write(file_content)
                    temp_file.flush()
                    temp_file.close()
                    temp_files.append(temp_file.name)
                    
                    app_logger.info(f"Saved {filename} to temporary file: {temp_file.name}")
                    
                    # Prepare document using abstraction layer
                    prepared_doc = doc_handler.prepare_document_for_llm(
                        file_path=temp_file.name,
                        provider_name=provider_name,
                        model_name=model_name,
                        effective_config=effective_config
                    )
                    
                    processed_documents.append({
                        'filename': filename,
                        'prepared': prepared_doc,
                        'method': prepared_doc['method']
                    })
                    
                    app_logger.info(f"Successfully processed {filename} using method: {prepared_doc['method']}")
                    
                except Exception as e:
                    app_logger.error(f"Error processing file {file.filename}: {e}", exc_info=True)
                    return jsonify({
                        "status": "error",
                        "message": f"Failed to process file {file.filename}: {str(e)}"
                    }), 400
            
            if not processed_documents:
                return jsonify({
                    "status": "error",
                    "message": "No documents could be processed"
                }), 400
            
            # Combine document contents for context
            # If using native upload, we'll pass metadata; otherwise use extracted text
            if processed_documents[0]['method'] == 'text_extraction':
                # Text extraction - combine all text
                document_texts = [doc['prepared']['content'] for doc in processed_documents]
                combined_document_content = "\n\n=== Document Separator ===\n\n".join(document_texts)
                
                app_logger.info(f"Extracted {len(combined_document_content)} characters from {len(document_texts)} document(s)")
                
                # Truncate if too long (keep first 50,000 chars to stay within token limits)
                if len(combined_document_content) > 50000:
                    combined_document_content = combined_document_content[:50000] + "\n\n[... content truncated ...]"
                    app_logger.warning("Document content truncated to 50,000 characters")
            else:
                # Native upload - documents will be passed separately to LLM
                # For now, still extract text for the prompt (future: pass native documents to LLM)
                document_texts = []
                for doc in processed_documents:
                    if doc['method'] == 'native_google':
                        # For Google, we have the file object but need text for prompt
                        # Extract text as fallback for prompt context
                        app_logger.info(f"Native Google upload: extracting text for prompt context from {doc['filename']}")
                        text_result = doc_handler._extract_text_from_document(temp_files[processed_documents.index(doc)])
                        document_texts.append(text_result['content'])
                    elif doc['method'] == 'native_anthropic':
                        # For Anthropic, decode base64 and extract text
                        app_logger.info(f"Native Anthropic upload: extracting text for prompt context from {doc['filename']}")
                        text_result = doc_handler._extract_text_from_document(temp_files[processed_documents.index(doc)])
                        document_texts.append(text_result['content'])
                    else:
                        document_texts.append(doc['prepared']['content'])
                
                combined_document_content = "\n\n=== Document Separator ===\n\n".join(document_texts)
                app_logger.info(f"Prepared {len(document_texts)} document(s) using {processed_documents[0]['method']}")
        
        finally:
            # Cleanup temporary files
            for temp_file in temp_files:
                try:
                    os_module.unlink(temp_file)
                    app_logger.debug(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    app_logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")
        
        # Get template prompt configuration
        try:
            template_manager = APP_STATE.get('template_manager')
            if not template_manager:
                app_logger.warning("Template manager not available, using fallback prompt")
                raise ValueError("Template manager not available")
            
            # Get plugin info which includes prompt templates
            plugin_info = template_manager.get_plugin_info('sql_query_doc_context_v1')
            prompt_config = plugin_info.get('prompt_templates', {}).get('question_generation', {})
            
            if not prompt_config:
                app_logger.warning("No prompt template found in manifest, using fallback")
                raise ValueError("No prompt template in manifest")
            
            # Build prompt from template
            prompt_text = build_question_generation_prompt(
                prompt_config=prompt_config,
                context_content=combined_document_content,
                variables={
                    'subject': subject,
                    'count': count,
                    'database_name': database_name,
                    'target_database': target_database,
                    'conversion_rules': conversion_rules,
                    'context_label': 'Technical Documentation'
                }
            )
            
        except Exception as e:
            app_logger.error(f"Failed to load prompt from template, using fallback: {e}")
            # Fallback to simple prompt if template loading fails
            prompt_text = f"""You are a SQL expert. Analyze the technical documentation and generate {count} question/SQL pairs about "{subject}" for database "{database_name}" using {target_database} syntax.

Technical Documentation:
{combined_document_content}

Return ONLY a JSON array: [{{"question": "...", "sql": "..."}}]"""

        app_logger.info(f"Generating {count} RAG questions from documents for subject '{subject}' in database '{database_name}'")

        # Implement batching to avoid token limit issues with large question counts
        # Same approach as generate_rag_questions endpoint
        BATCH_SIZE = 20
        all_questions = []
        total_input_tokens = 0
        total_output_tokens = 0

        # Calculate number of batches needed
        num_batches = (count + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division

        if num_batches > 1:
            app_logger.info(f"Splitting {count} questions into {num_batches} batches of up to {BATCH_SIZE} questions each")

        # Call LLM directly using the handler
        try:
            for batch_num in range(num_batches):
                batch_start = batch_num * BATCH_SIZE
                batch_count = min(BATCH_SIZE, count - batch_start)

                # Build context of previously generated questions to avoid duplicates
                previous_questions_context = ""
                if batch_num > 0 and all_questions:
                    # Show LLM what questions were already generated
                    prev_count = len(all_questions)
                    prev_questions_list = "\n".join([
                        f"  - {q['question']}"
                        for q in all_questions[:min(10, prev_count)]  # Show first 10 as examples
                    ])
                    if prev_count > 10:
                        prev_questions_list += f"\n  ... and {prev_count - 10} more questions"

                    previous_questions_context = f"""

IMPORTANT - AVOID DUPLICATES:
The following {prev_count} questions have ALREADY been generated in previous batches.
You MUST generate {batch_count} NEW and DIFFERENT questions that cover different aspects:

Previously Generated Questions:
{prev_questions_list}

Generate {batch_count} questions that explore DIFFERENT topics, tables, or analytical angles.
"""

                # Update prompt for this batch
                if num_batches > 1:
                    # Rebuild prompt with batch-specific count and previous context
                    try:
                        batch_prompt_text = build_question_generation_prompt(
                            prompt_config=prompt_config,
                            context_content=combined_document_content,
                            variables={
                                'subject': subject,
                                'count': batch_count,
                                'database_name': database_name,
                                'target_database': target_database,
                                'conversion_rules': conversion_rules,
                                'context_label': 'Technical Documentation'
                            }
                        )
                        # Append previous questions context
                        batch_prompt_text += previous_questions_context
                    except:
                        # Fallback if template failed
                        batch_prompt_text = f"""You are a SQL expert. Analyze the technical documentation and generate {batch_count} question/SQL pairs about "{subject}" for database "{database_name}" using {target_database} syntax.

Technical Documentation:
{combined_document_content}
{previous_questions_context}

Return ONLY a JSON array: [{{"question": "...", "sql": "..."}}]"""
                else:
                    # Single batch - use original prompt
                    batch_prompt_text = prompt_text

                app_logger.info(f"Generating batch {batch_num + 1}/{num_batches}: {batch_count} questions from documents")

                response_text, input_tokens, output_tokens, provider, model = await llm_handler.call_llm_api(
                    llm_instance=llm_instance,
                    prompt=batch_prompt_text,
                    user_uuid=user_uuid,
                    session_id=None,
                    dependencies={'STATE': APP_STATE, 'CONFIG': APP_CONFIG},
                    reason=f"Generating RAG questions from documents (batch {batch_num + 1}/{num_batches})",
                    disabled_history=True,
                    source='rag_document_question_generator'
                )

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens

                app_logger.info(f"Batch {batch_num + 1}/{num_batches} completed: {input_tokens} input tokens, {output_tokens} output tokens")

                # Parse this batch's JSON response
                try:
                    # Try to extract JSON if wrapped in markdown code blocks
                    json_text = response_text.strip()
                    if json_text.startswith('```json'):
                        json_text = json_text[7:]
                    elif json_text.startswith('```'):
                        json_text = json_text[3:]
                    if json_text.endswith('```'):
                        json_text = json_text[:-3]
                    json_text = json_text.strip()

                    batch_questions = json.loads(json_text)

                    if not isinstance(batch_questions, list):
                        raise ValueError(f"Batch {batch_num + 1} response is not a JSON array")

                    # Validate structure for this batch
                    for q in batch_questions:
                        if not isinstance(q, dict) or 'question' not in q or 'sql' not in q:
                            raise ValueError(f"Batch {batch_num + 1} has invalid question structure")

                    all_questions.extend(batch_questions)
                    app_logger.info(f"Batch {batch_num + 1}/{num_batches} parsed successfully: {len(batch_questions)} questions")

                except json.JSONDecodeError as e:
                    app_logger.error(f"Failed to parse batch {batch_num + 1} response as JSON: {e}")
                    app_logger.error(f"Batch {batch_num + 1} response was: {response_text[:500]}")
                    return jsonify({
                        "status": "error",
                        "message": f"Batch {batch_num + 1} did not return valid JSON",
                        "raw_response": response_text[:1000]
                    }), 500
                except ValueError as e:
                    app_logger.error(f"Batch {batch_num + 1} invalid structure: {e}")
                    return jsonify({
                        "status": "error",
                        "message": str(e),
                        "raw_response": response_text[:1000]
                    }), 500

            # All batches completed successfully
            app_logger.info(f"Generated {len(all_questions)} question/SQL pairs from documents across {num_batches} batch(es)")

            # Deduplicate questions using fuzzy matching
            # Remove exact duplicates and very similar questions
            deduplicated_questions = []
            seen_questions_lower = set()
            seen_sql_normalized = set()
            duplicates_removed = 0

            for q in all_questions:
                question_text = q.get('question', '').strip()
                sql_text = q.get('sql', '').strip()

                # Normalize for comparison
                question_lower = question_text.lower()
                # Normalize SQL: remove extra whitespace, convert to lowercase
                sql_normalized = ' '.join(sql_text.lower().split())

                # Check for exact duplicates (case-insensitive)
                if question_lower in seen_questions_lower or sql_normalized in seen_sql_normalized:
                    duplicates_removed += 1
                    app_logger.debug(f"Removed duplicate: {question_text[:50]}...")
                    continue

                # Add to results and tracking sets
                deduplicated_questions.append(q)
                seen_questions_lower.add(question_lower)
                seen_sql_normalized.add(sql_normalized)

            if duplicates_removed > 0:
                app_logger.info(f"Removed {duplicates_removed} duplicate questions. Final count: {len(deduplicated_questions)}")
            else:
                app_logger.info(f"No duplicates found. Final count: {len(deduplicated_questions)}")

            return jsonify({
                "status": "success",
                "questions": deduplicated_questions,
                "count": len(deduplicated_questions),
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "batches": num_batches,
                "duplicates_removed": duplicates_removed,
                "documents_processed": len(processed_documents),
                "processing_method": processed_documents[0]['method'] if processed_documents else 'unknown',
                "provider": provider_name,
                "native_upload_used": processed_documents[0]['method'] != 'text_extraction' if processed_documents else False
            })

        except Exception as e:
            app_logger.error(f"Failed to generate questions with LLM: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": f"LLM invocation failed: {str(e)}"
            }), 500
        
    except Exception as e:
        app_logger.error(f"Error generating RAG questions from documents: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@rest_api_bp.route("/v1/configure", methods=["POST"])
async def configure_services_rest():
    """
    Configures and validates the core LLM and MCP services via the REST API.
    This is a protected, atomic operation that uses the centralized
    configuration service.
    """
    config_data = await request.get_json()
    if not config_data:
        return jsonify({"status": "error", "message": "Request body must be a valid JSON."}), 400
    
    # Extract user_uuid for per-user context isolation
    user_uuid = _get_user_uuid_from_request()
    config_data["user_uuid"] = user_uuid

    result = await configuration_service.setup_and_categorize_services(config_data)

    if result.get("status") == "success":
        # --- MODIFICATION START: Broadcast reconfiguration notification ---
        # Create a copy of the config to sanitize it for notification
        safe_config = config_data.copy()
        if "credentials" in safe_config:
            safe_config["credentials"] = {k: v for k, v in safe_config["credentials"].items() if "key" not in k.lower() and "token" not in k.lower()}
        if "tts_credentials_json" in safe_config:
            del safe_config["tts_credentials_json"]

        notification = {
            "type": "reconfiguration",
            "payload": {
                "message": "Application has been reconfigured via REST API. A refresh is required.",
                "config": safe_config
            }
        }

        # Broadcast to all active notification queues
        all_queues = [q for user_queues in APP_STATE.get("notification_queues", {}).values() for q in user_queues]
        if all_queues:
            for queue in all_queues:
                asyncio.create_task(queue.put(notification))
        # --- MODIFICATION END ---
        return jsonify(result), 200
    else:
        # Configuration errors are client-side problems (bad keys, wrong host, etc.)
        # so a 400-level error is more appropriate than a 500.
        return jsonify(result), 400


@rest_api_bp.route("/v1/config/stored-credentials", methods=["GET"])
async def get_stored_credentials_info():
    """
    Get information about stored credentials for the current user.
    Does not return actual credential values, only metadata.
    
    Returns:
    {
        "status": "success",
        "has_stored_credentials": true,
        "providers": ["Amazon", "Google"],
        "credentials_available": {
            "Amazon": ["aws_access_key_id", "aws_secret_access_key", "aws_region"],
            "Google": ["apiKey"]
        }
    }
    """
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    
    try:
        result = await configuration_service.list_user_providers(user_uuid)
        
        if result["status"] != "success":
            return jsonify(result), 500
        
        providers = result.get("providers", [])
        credentials_available = {}
        
        # Look up user by id
        from trusted_data_agent.auth.models import User
        from trusted_data_agent.auth.database import get_db_session
        
        with get_db_session() as session:
            user = session.query(User).filter_by(id=user_uuid).first()
            if user:
                # Get credential keys for each provider (without values)
                for provider in providers:
                    cred_result = await configuration_service.retrieve_credentials_for_provider(user.id, provider)
                    if cred_result.get("credentials"):
                        credentials_available[provider] = list(cred_result["credentials"].keys())
        
        return jsonify({
            "status": "success",
            "has_stored_credentials": len(providers) > 0,
            "providers": providers,
            "credentials_available": credentials_available
        }), 200
        
    except Exception as e:
        app_logger.error(f"Failed to get stored credentials info: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/config/classification", methods=["GET", "PUT"])
async def manage_classification_setting():
    """
    GET: Returns the current enable_mcp_classification setting (GLOBAL).
    PUT: Updates the enable_mcp_classification setting as a GLOBAL runtime flag.
    
    NOTE: This is a GLOBAL application setting that affects ALL users.
    It is stored in APP_CONFIG and persisted to a global settings file (not per-user).
    
    PUT Request body:
    {
        "enable_mcp_classification": true/false
    }
    
    Returns:
    {
        "status": "success",
        "enable_mcp_classification": true/false
    }
    """
    if request.method == "GET":
        # Return current GLOBAL setting
        return jsonify({
            "status": "success",
            "enable_mcp_classification": APP_CONFIG.ENABLE_MCP_CLASSIFICATION
        }), 200
    
    elif request.method == "PUT":
        # Update GLOBAL setting - affects all users
        data = await request.get_json()
        if data is None or "enable_mcp_classification" not in data:
            return jsonify({
                "status": "error",
                "message": "Request body must contain 'enable_mcp_classification' field"
            }), 400
        
        enable_classification = bool(data["enable_mcp_classification"])
        
        # Update the GLOBAL runtime setting
        APP_CONFIG.ENABLE_MCP_CLASSIFICATION = enable_classification
        
        # Persist to global settings file (not per-user config)
        try:
            global_settings_file = Path("tda_global_settings.json")
            if global_settings_file.exists():
                with open(global_settings_file, 'r') as f:
                    global_settings = json.load(f)
            else:
                global_settings = {}
            
            global_settings["enable_mcp_classification"] = enable_classification
            
            with open(global_settings_file, 'w') as f:
                json.dump(global_settings, f, indent=2)
            
            app_logger.info(f"Updated GLOBAL MCP classification setting to: {enable_classification}")
        except Exception as e:
            app_logger.error(f"Failed to persist global classification setting: {e}")
            return jsonify({
                "status": "error",
                "message": "Failed to save configuration to file"
            }), 500
        
        app_logger.info(f"MCP Classification setting updated to: {enable_classification}")
        
        return jsonify({
            "status": "success",
            "enable_mcp_classification": enable_classification,
            "message": f"Classification {'enabled' if enable_classification else 'disabled'}. Changes will take effect on next configuration."
        }), 200


@rest_api_bp.route("/v1/config/document-upload-capabilities", methods=["GET"])
async def get_document_upload_capabilities():
    """
    Get document upload capabilities for all LLM providers.
    
    Returns capability information including:
    - Native upload support
    - Supported file formats
    - Max file size limits
    - Provider-specific requirements
    
    Returns:
    {
        "status": "success",
        "capabilities": {
            "Google": {...},
            "Anthropic": {...},
            ...
        }
    }
    """
    try:
        from trusted_data_agent.llm.document_upload import DocumentUploadHandler, DocumentUploadConfig
        
        # Get all provider configurations
        capabilities = {}
        for provider in ["Google", "Anthropic", "OpenAI", "Amazon", "Azure", "Friendli", "Ollama"]:
            capabilities[provider] = DocumentUploadHandler.get_capability_info(provider)
        
        return jsonify({
            "status": "success",
            "capabilities": capabilities
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error fetching document upload capabilities: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@rest_api_bp.route("/v1/config/document-upload-capabilities/<provider>", methods=["GET"])
async def get_provider_document_capability(provider: str):
    """
    Get document upload capability for a specific provider/model.
    
    Query parameters:
    - model: Optional model name for model-specific capability detection
    
    Returns:
    {
        "status": "success",
        "provider": "Anthropic",
        "model": "claude-3-opus-20240229",
        "capability": "native_full",
        "supports_native": true,
        "supported_formats": [".pdf", ".jpg", ...],
        "max_file_size_mb": 32,
        "description": "..."
    }
    """
    try:
        from trusted_data_agent.llm.document_upload import DocumentUploadHandler
        
        model = request.args.get('model')
        capability_info = DocumentUploadHandler.get_capability_info(provider, model)
        
        return jsonify({
            "status": "success",
            **capability_info
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error fetching capability for {provider}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =============================================================================
# Document Upload Configuration Management (Admin)
# =============================================================================

@rest_api_bp.route("/v1/admin/config/document-upload", methods=["GET"])
@require_admin
async def get_all_document_upload_configs():
    """
    Get all document upload configurations with effective settings.
    Admin only endpoint.
    
    Returns:
    {
        "status": "success",
        "configs": [
            {
                "provider": "Google",
                "enabled": true,
                "use_native_upload": true,
                "capability": "NATIVE_FULL",
                "max_file_size_mb": 20,
                "supported_formats": ["pdf", "jpg", ...],
                "has_overrides": false,
                "notes": null
            },
            ...
        ]
    }
    """
    try:
        from trusted_data_agent.llm.document_upload_config_manager import DocumentUploadConfigManager
        
        # Get effective configs for all providers
        all_providers = ['Google', 'Anthropic', 'Amazon', 'OpenAI', 'Azure', 'Friendli', 'Ollama']
        configs = []
        
        for provider in all_providers:
            effective_config = DocumentUploadConfigManager.get_effective_config(provider)
            configs.append(effective_config)
        
        return jsonify({
            "status": "success",
            "configs": configs
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error fetching document upload configs: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@rest_api_bp.route("/v1/admin/config/document-upload/<provider>", methods=["GET"])
@require_admin
async def get_document_upload_config(provider: str):
    """
    Get document upload configuration for a specific provider.
    Admin only endpoint.
    
    Returns effective configuration with overrides applied.
    """
    try:
        from trusted_data_agent.llm.document_upload_config_manager import DocumentUploadConfigManager
        
        effective_config = DocumentUploadConfigManager.get_effective_config(provider)
        
        return jsonify({
            "status": "success",
            "config": effective_config
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error fetching config for {provider}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@rest_api_bp.route("/v1/admin/config/document-upload/<provider>", methods=["PUT"])
@require_admin
async def update_document_upload_config(provider: str):
    """
    Update document upload configuration for a provider.
    Admin only endpoint.
    
    Request body:
    {
        "use_native_upload": true,
        "enabled": true,
        "max_file_size_mb": 50,  # Optional override
        "supported_formats_override": ["pdf", "docx"],  # Optional override
        "notes": "Increased file size for special use case"
    }
    
    Returns updated configuration.
    """
    try:
        from trusted_data_agent.llm.document_upload_config_manager import DocumentUploadConfigManager
        
        data = await request.get_json()
        
        # Extract update parameters
        use_native_upload = data.get('use_native_upload')
        enabled = data.get('enabled')
        max_file_size_mb = data.get('max_file_size_mb')
        supported_formats_override = data.get('supported_formats_override')
        notes = data.get('notes')
        
        # Update configuration
        updated_config = DocumentUploadConfigManager.update_config(
            provider=provider,
            use_native_upload=use_native_upload,
            enabled=enabled,
            max_file_size_mb=max_file_size_mb,
            supported_formats_override=supported_formats_override,
            notes=notes
        )
        
        if updated_config:
            # Get effective config to return
            effective_config = DocumentUploadConfigManager.get_effective_config(provider)
            
            return jsonify({
                "status": "success",
                "message": f"Configuration updated for {provider}",
                "config": effective_config
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": f"Failed to update configuration for {provider}"
            }), 500
            
    except Exception as e:
        app_logger.error(f"Error updating config for {provider}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@rest_api_bp.route("/v1/admin/config/document-upload/<provider>/reset", methods=["POST"])
@require_admin
async def reset_document_upload_config(provider: str):
    """
    Reset document upload configuration to defaults for a provider.
    Admin only endpoint.
    
    Removes all overrides and restores default settings.
    """
    try:
        from trusted_data_agent.llm.document_upload_config_manager import DocumentUploadConfigManager
        
        reset_config = DocumentUploadConfigManager.reset_to_defaults(provider)
        
        if reset_config:
            # Get effective config to return
            effective_config = DocumentUploadConfigManager.get_effective_config(provider)
            
            return jsonify({
                "status": "success",
                "message": f"Configuration reset to defaults for {provider}",
                "config": effective_config
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": f"Failed to reset configuration for {provider}"
            }), 500
            
    except Exception as e:
        app_logger.error(f"Error resetting config for {provider}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@rest_api_bp.route("/v1/sessions", methods=["POST"])
async def create_session():
    """
    Creates a new conversation session for the requesting user.
    
    Requires:
    - User must be authenticated (JWT or Access Token)
    - User must have a configured profile (LLM + MCP server combination)
    - Profile must be set as default or active for consumption
    
    Returns:
    - 201: Session created successfully with session_id
    - 400: No profile configured for the user
    - 503: Profile exists but configuration is incomplete
    """
    # Get User UUID from JWT/Access Token
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({
            "error": "Authentication required"
        }), 401

    try:
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        # Check if user has a default profile configured
        default_profile_id = config_manager.get_default_profile_id(user_uuid)
        if not default_profile_id:
            return jsonify({
                "error": "No default profile configured for this user. Please configure a profile (LLM + MCP Server combination) in the Configuration panel first."
            }), 400
        
        # Verify the default profile exists and is properly configured
        default_profile = config_manager.get_profile(default_profile_id, user_uuid)
        if not default_profile:
            return jsonify({
                "error": "Default profile not found. Please configure a profile first."
            }), 400
        
        # Extract LLM and MCP configuration from profile
        llm_config_id = default_profile.get("llmConfigurationId")
        mcp_server_id = default_profile.get("mcpServerId")
        profile_type = default_profile.get("profile_type", "tool_enabled")

        # LLM always required
        if not llm_config_id:
            return jsonify({
                "error": "Profile is incomplete. LLM Provider is required."
            }), 503

        # MCP only required for tool-enabled profiles
        if profile_type == "tool_enabled" and not mcp_server_id:
            return jsonify({
                "error": "Tool-enabled profiles require an MCP Server configuration."
            }), 503
        
        # Get LLM configuration
        llm_configs = config_manager.get_llm_configurations(user_uuid)
        llm_config = next((c for c in llm_configs if c.get("id") == llm_config_id), None)
        if not llm_config:
            return jsonify({
                "error": "LLM configuration for profile not found."
            }), 503
        
        # Get MCP server configuration
        mcp_configs = config_manager.get_mcp_servers(user_uuid)
        mcp_config = next((m for m in mcp_configs if m.get("id") == mcp_server_id), None)
        if not mcp_config:
            return jsonify({
                "error": "MCP Server configuration for profile not found."
            }), 503
        
        # Extract provider from LLM config
        provider = llm_config.get("provider", "Google")
        
        # Switch to this profile's context to get LLM instance
        from trusted_data_agent.core.configuration_service import switch_profile_context
        profile_context = await switch_profile_context(default_profile_id, user_uuid, validate_llm=False)
        
        if "error" in profile_context:
            return jsonify({
                "error": f"Failed to activate profile: {profile_context.get('error')}"
            }), 503
        
        llm_instance = APP_STATE.get("llm")
        
        # Create session with the profile's context
        app_logger.info(f"REST API: Creating session with profile_id={default_profile_id}, profile_tag={default_profile.get('tag')}")  # DEBUG
        session_id = await session_manager.create_session(
            user_uuid=user_uuid,
            provider=provider,
            llm_instance=llm_instance,
            charting_intensity=APP_CONFIG.DEFAULT_CHARTING_INTENSITY,
            profile_tag=default_profile.get("tag"),
            profile_id=default_profile_id  # Store profile ID for badge/color info
        )
        app_logger.info(f"REST API: Created new session: {session_id} for user {user_uuid} using profile {default_profile_id}")

        # Retrieve the newly created session's full data
        new_session_data = await session_manager.get_session(user_uuid=user_uuid, session_id=session_id)
        if new_session_data:
            # Prepare notification payload
            notification_payload = {
                "id": new_session_data["id"],
                "name": new_session_data.get("name", "New Chat"),
                "models_used": new_session_data.get("models_used", []),
                "last_updated": new_session_data.get("last_updated", datetime.now(timezone.utc).isoformat())
            }

            # Broadcast to all active notification queues for this user
            notification_queues = APP_STATE.get("notification_queues", {}).get(user_uuid, set())
            if notification_queues:
                notification = {
                    "type": "new_session_created",
                    "payload": notification_payload
                }
                for queue in notification_queues:
                    asyncio.create_task(queue.put(notification))
        else:
            app_logger.warning(f"REST API: Could not retrieve full session data for new session {session_id} for user {user_uuid}.")

        return jsonify({"session_id": session_id}), 201
    except Exception as e:
        app_logger.error(f"Failed to create REST session for user {user_uuid}: {e}", exc_info=True)
        return jsonify({"error": "Failed to create session."}), 500

@rest_api_bp.route("/v1/sessions/<session_id>/query", methods=["POST"])
async def execute_query(session_id: str):
    """Submits a query to a session and starts a background task *for the requesting user*."""
    # --- MODIFICATION START: Get User UUID ---
    user_uuid = _get_user_uuid_from_request()
    # --- MODIFICATION END ---

    data = await request.get_json()
    prompt = data.get("prompt")
    if not prompt:
        return jsonify({"error": "The 'prompt' field is required."}), 400

    # --- MODIFICATION START: Validate session for this user ---
    if not await session_manager.get_session(user_uuid, session_id):
        app_logger.warning(f"REST API: Session '{session_id}' not found for user '{user_uuid}'.")
        return jsonify({"error": f"Session '{session_id}' not found."}), 404
    # --- MODIFICATION END ---

    # --- NEW: Switch to profile context for query execution (with optional override) ---
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.core.configuration_service import switch_profile_context
    
    config_manager = get_config_manager()
    
    # Allow optional profile_id parameter; defaults to user's default profile
    profile_id_override = data.get("profile_id")
    profile_id_to_use = profile_id_override or config_manager.get_default_profile_id(user_uuid)
    
    if profile_id_to_use:
        # Activate profile context to ensure correct LLM and profile badges are associated
        profile_context = await switch_profile_context(profile_id_to_use, user_uuid, validate_llm=False)
        if "error" in profile_context:
            app_logger.warning(f"REST API: Could not activate profile {profile_id_to_use} for query execution: {profile_context.get('error')}")
    # --- END NEW ---

    task_id = generate_task_id()

    # Initialize the task state
    APP_STATE.setdefault("background_tasks", {})[task_id] = {
        "task_id": task_id,
        "user_uuid": user_uuid, # Store the user UUID with the task
        "session_id": session_id, # Store session ID for reference
        "profile_id_override": profile_id_override, # Track which profile was used for this query
        "status": "pending",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "events": [],
        "intermediate_data": [],
        "result": None
    }

    async def event_handler(event_data, event_type):
        """This handler is called by the execution service for each event."""
        task_status_dict = APP_STATE["background_tasks"].get(task_id)
        sanitized_event_data = _sanitize_for_json(event_data)

        # 1. Update the persistent task state (for polling clients)
        if task_status_dict:
            task_status_dict["events"].append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_data": sanitized_event_data,
                "event_type": event_type
            })
            if event_type == "tool_result" and isinstance(sanitized_event_data, dict):
                details = sanitized_event_data.get("details", {})
                if isinstance(details, dict) and details.get("status") == "success" and "results" in details:
                    task_status_dict["intermediate_data"].append({
                        "tool_name": details.get("metadata", {}).get("tool_name", "unknown_tool"),
                        "data": details["results"]
                    })
            task_status_dict["last_updated"] = datetime.now(timezone.utc).isoformat()

        # 2. Create and send a canonical event to the UI notification stream
        notification_queues = APP_STATE.get("notification_queues", {}).get(user_uuid, set())
        if notification_queues:
            try:
                # --- MODIFICATION START: Build canonical_event directly ---
                # No need to format/re-parse. Just build the dict.
                canonical_event = copy.deepcopy(sanitized_event_data)
                # Ensure 'type' key exists, merging the event_type string
                canonical_event['type'] = event_type
                # --- MODIFICATION END ---
                    
                # --- MODIFICATION START: Handle session_name_update as a top-level event ---
                # --- MODIFICATION START: Handle status_indicator_update directly ---
                if event_type == "status_indicator_update":
                    notification = {
                        "type": "status_indicator_update",
                        "payload": canonical_event # canonical_event already contains target and state
                    }
                # --- MODIFICATION END ---
                elif event_type == "session_name_update":
                    notification = {
                        "type": "session_name_update",
                        "payload": canonical_event # Payload already contains session_id and newName
                    }
                else:
                    notification = {
                        "type": "rest_task_update",
                        "payload": {
                            "task_id": task_id,
                            "session_id": session_id,
                            "event": canonical_event
                        }
                    }
                # --- MODIFICATION END ---
                for queue in notification_queues:
                    asyncio.create_task(queue.put(notification))

            except Exception as e:
                app_logger.error(f"Failed to format or send canonical event for REST task {task_id}: {e}", exc_info=True)

    async def background_wrapper():
        """Wraps the execution to handle context, final state updates, and notifications."""
        task_status_dict = APP_STATE["background_tasks"].get(task_id)
        final_result_payload = None
        try:
            if task_status_dict: task_status_dict["status"] = "processing"

            final_result_payload = await execution_service.run_agent_execution(
                user_uuid=user_uuid,
                session_id=session_id,
                user_input=prompt,
                event_handler=event_handler,
                source='rest', # Identify source as REST
                task_id=task_id, # Pass the task_id here
                profile_override_id=profile_id_override # Pass profile override for per-message tracking
            )

            if task_status_dict:
                task_status_dict["status"] = "complete"
                task_status_dict["result"] = _sanitize_for_json(final_result_payload)
                task_status_dict["last_updated"] = datetime.now(timezone.utc).isoformat()

        except asyncio.CancelledError:
            app_logger.info(f"REST background task {task_id} (user {user_uuid}) was cancelled.")
            if task_status_dict:
                task_status_dict["status"] = "cancelled"
                task_status_dict["result"] = {"message": "Task cancelled by user."}
                task_status_dict["last_updated"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            app_logger.error(f"Background task {task_id} (user {user_uuid}) failed: {e}", exc_info=True)
            if task_status_dict:
                task_status_dict["status"] = "error"
                task_status_dict["result"] = {"error": str(e)}
                task_status_dict["last_updated"] = datetime.now(timezone.utc).isoformat()
        finally:
            # Remove from ACTIVE tasks registry
            if task_id in APP_STATE.get("active_tasks", {}):
                del APP_STATE["active_tasks"][task_id]

            # Send final notification to UI clients on success
            if final_result_payload and task_status_dict and task_status_dict.get("status") == "complete":
                notification_queues = APP_STATE.get("notification_queues", {}).get(user_uuid, set())
                if notification_queues:
                    # Get the session to retrieve profile tag
                    profile_tag = None
                    try:
                        session_data = await session_manager.get_session(user_uuid, session_id)
                        profile_tag = session_data.get("profile_tag") if session_data else None
                    except Exception as e:
                        app_logger.warning(f"Could not retrieve profile tag for session {session_id}: {e}")
                    
                    completion_notification = {
                        "type": "rest_task_complete",
                        "payload": {
                            "task_id": task_id,
                            "session_id": session_id,
                            "turn_id": final_result_payload.get("turn_id"),
                            "user_input": prompt,
                            "final_answer": final_result_payload.get("final_answer"),
                            "profile_tag": profile_tag
                        }
                    }
                    for queue in notification_queues:
                        asyncio.create_task(queue.put(completion_notification))

            app_logger.info(f"Background task {task_id} (user {user_uuid}) finished with status: {task_status_dict.get('status', 'unknown') if task_status_dict else 'unknown'}")

    # Start the agent execution in the background
    task_object = asyncio.create_task(background_wrapper())
    # Store the actual task object for potential cancellation (uses task_id)
    APP_STATE.setdefault("active_tasks", {})[task_id] = task_object

    status_url = f"/api/v1/tasks/{task_id}"

    return jsonify({"task_id": task_id, "status_url": status_url}), 202

@rest_api_bp.route("/v1/tasks/<task_id>", methods=["GET"])
async def get_task_status(task_id: str):
    """Gets the status and results of a background task."""
    # --- MODIFICATION START: Get User UUID and optionally check ownership ---
    user_uuid = _get_user_uuid_from_request()
    task = APP_STATE["background_tasks"].get(task_id)

    if not task:
        app_logger.warning(f"REST API: Task '{task_id}' not found for user '{user_uuid}'.")
        return jsonify({"error": f"Task '{task_id}' not found."}), 404

    # Optional: Check if the requesting user owns this task
    if task.get("user_uuid") != user_uuid:
        app_logger.error(f"REST API: User '{user_uuid}' attempted to access task '{task_id}' owned by user '{task.get('user_uuid')}'.")
        return jsonify({"error": "Access denied to this task."}), 403
    # --- MODIFICATION END ---

    # Exclude user_uuid from the response payload if desired
    # response_task = task.copy()
    # response_task.pop("user_uuid", None)
    # return jsonify(response_task)
    return jsonify(task)


@rest_api_bp.route("/v1/tasks/<task_id>/cancel", methods=["POST"])
async def cancel_task(task_id: str):
    """Cancels an active background task initiated via the REST API *by the requesting user*."""
    # --- MODIFICATION START: Get User UUID and check task ownership ---
    user_uuid = _get_user_uuid_from_request()
    task_status_dict = APP_STATE["background_tasks"].get(task_id)

    if not task_status_dict:
        app_logger.warning(f"REST API: Cancel failed. Task '{task_id}' not found for user '{user_uuid}'.")
        return jsonify({"error": f"Task '{task_id}' not found."}), 404

    if task_status_dict.get("user_uuid") != user_uuid:
        app_logger.error(f"REST API: User '{user_uuid}' attempted to cancel task '{task_id}' owned by user '{task_status_dict.get('user_uuid')}'. Denying.")
        return jsonify({"error": "Access denied: You cannot cancel a task you did not start."}), 403
    # --- MODIFICATION END ---

    active_tasks = APP_STATE.get("active_tasks", {})
    task_object = active_tasks.get(task_id) # Get the asyncio.Task object

    if task_object and not task_object.done():
        app_logger.info(f"Received REST request from user {user_uuid} to cancel task {task_id}.")
        task_object.cancel()
        # Remove immediately from active tasks dict
        if task_id in active_tasks:
             del active_tasks[task_id]
        # Update the status in the background_tasks dict as well
        task_status_dict["status"] = "cancelling" # Or "cancelled" immediately
        task_status_dict["last_updated"] = datetime.now(timezone.utc).isoformat()

        return jsonify({"status": "success", "message": "Cancellation request sent."}), 200
    elif task_object and task_object.done():
        app_logger.info(f"REST cancellation request for task {task_id} (user {user_uuid}) ignored: task already completed.")
        if task_id in active_tasks:
             del active_tasks[task_id]
        # Ensure final status reflects completion if missed
        if task_status_dict.get("status") not in ["complete", "error", "cancelled"]:
             task_status_dict["status"] = "complete" # Or infer from result if possible
        return jsonify({"status": "success", "message": "Task already completed."}), 200
    else:
        # Task might exist in background_tasks but not in active_tasks if already finished/cancelled
        current_status = task_status_dict.get("status", "unknown")
        if current_status in ["complete", "error", "cancelled"]:
             app_logger.info(f"REST cancellation request for task {task_id} (user {user_uuid}) ignored: task already finished with status '{current_status}'.")
             return jsonify({"status": "success", "message": f"Task already finished ({current_status})."}), 200
        else:
            app_logger.warning(f"REST cancellation request for task {task_id} (user {user_uuid}) failed: No active asyncio task found, status is '{current_status}'.")
            return jsonify({"status": "error", "message": "No active running task found for this task ID."}), 404


# --- RAG Collection Management Endpoints ---

@rest_api_bp.route("/v1/rag/collections", methods=["GET"])
async def get_rag_collections():
    """Get RAG collections accessible to the authenticated user (owned + subscribed)."""
    try:
        # --- MARKETPLACE PHASE 2: Filter by user access ---
        user_uuid = _get_user_uuid_from_request()
        retriever = APP_STATE.get("rag_retriever_instance")
        
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Get collections directly from database (always fresh)
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        accessible_collections = collection_db.get_all_collections(user_id=user_uuid)
        app_logger.info(f"GET /v1/rag/collections for user {user_uuid}: Found {len(accessible_collections)} collections")
        for coll in accessible_collections:
            app_logger.info(f"  - Collection {coll['id']}: {coll['name']}")
        # --- MARKETPLACE PHASE 2 END ---
        
        # Add 'is_active' field and 'count' to indicate if collection is actually loaded and how many docs it has
        enhanced_collections = []
        for coll in accessible_collections:
            coll_copy = coll.copy()
            # A collection is active if it's loaded in the retriever's collections dict
            is_active = retriever and coll["id"] in retriever.collections if retriever else False
            coll_copy["is_active"] = is_active
            
            # --- MARKETPLACE PHASE 2: Add ownership indicators ---
            coll_copy["is_owned"] = retriever.is_user_collection_owner(coll["id"], user_uuid)
            coll_copy["is_subscribed"] = retriever.is_subscribed_collection(coll["id"], user_uuid)
            
            # Add subscription_id if user is subscribed (needed for unsubscribe action)
            if coll_copy["is_subscribed"] and not coll_copy["is_owned"]:
                from trusted_data_agent.auth.database import get_db_session
                from trusted_data_agent.auth.models import CollectionSubscription
                with get_db_session() as session:
                    subscription = session.query(CollectionSubscription).filter_by(
                        user_id=user_uuid,
                        source_collection_id=coll["id"]
                    ).first()
                    if subscription:
                        coll_copy["subscription_id"] = subscription.id
            # --- MARKETPLACE PHASE 2 END ---
            
            # Get document count if collection is active
            if is_active and retriever:
                try:
                    chromadb_collection = retriever.collections.get(coll["id"])
                    if chromadb_collection:
                        coll_copy["count"] = chromadb_collection.count()
                    else:
                        coll_copy["count"] = 0
                except Exception as count_err:
                    app_logger.warning(f"Failed to get count for collection {coll['id']}: {count_err}")
                    coll_copy["count"] = 0
            else:
                coll_copy["count"] = 0
            
            enhanced_collections.append(coll_copy)
        
        # Add rating statistics in bulk (efficient single query)
        collection_ids = [c["id"] for c in enhanced_collections]
        ratings_map = collection_db.get_bulk_collection_ratings(collection_ids)
        for coll in enhanced_collections:
            coll_ratings = ratings_map.get(coll["id"], {"average_rating": 0.0, "rating_count": 0})
            coll["average_rating"] = coll_ratings["average_rating"]
            coll["rating_count"] = coll_ratings["rating_count"]
        
        return jsonify({"status": "success", "collections": enhanced_collections}), 200
    except Exception as e:
        app_logger.error(f"Error getting RAG collections: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections", methods=["POST"])
async def create_rag_collection():
    """Create a new RAG collection."""
    try:
        # --- MARKETPLACE PHASE 2: Get authenticated user ---
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        # --- MARKETPLACE PHASE 2 END ---
        
        data = await request.get_json()
        
        # Validate required fields
        if not data.get("name"):
            return jsonify({"status": "error", "message": "Collection name is required"}), 400
        
        name = data["name"]
        # repository_type: Storage model (planner|knowledge) - determines DB schema
        # - planner: Stores execution strategies/traces (requires MCP server)
        # - knowledge: Stores document chunks with embeddings
        repository_type = data.get("repository_type", "planner")
        
        # ENFORCEMENT: mcp_server_id is required for planner repositories only
        mcp_server_id = data.get("mcp_server_id")
        if repository_type == "planner" and not mcp_server_id:
            return jsonify({"status": "error", "message": "mcp_server_id is required for planner repositories. Collections must be associated with an MCP server."}), 400
        
        description = data.get("description", "")
        chunking_strategy = data.get("chunking_strategy", "none")
        chunk_size = data.get("chunk_size", 1000)
        chunk_overlap = data.get("chunk_overlap", 200)
        embedding_model = data.get("embedding_model", "all-MiniLM-L6-v2")
        
        # Add collection via RAG retriever
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # --- MARKETPLACE PHASE 2: Pass owner_user_id and repository configuration ---
        collection_id = retriever.add_collection(
            name, description, mcp_server_id, owner_user_id=user_uuid,
            repository_type=repository_type, chunking_strategy=chunking_strategy,
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, embedding_model=embedding_model
        )
        # --- MARKETPLACE PHASE 2 END ---
        
        if collection_id is not None:
            app_logger.info(f"Created {repository_type} RAG collection with ID: {collection_id}, MCP server: {mcp_server_id}")
            return jsonify({
                "status": "success", 
                "message": "Collection created successfully", 
                "collection_id": collection_id,
                "mcp_server_id": mcp_server_id,
                "repository_type": repository_type
            }), 201
        else:
            return jsonify({"status": "error", "message": "Failed to create collection"}), 500

    except Exception as e:
        app_logger.error(f"Error creating RAG collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>", methods=["GET"])
async def get_rag_collection(collection_id: int):
    """Get a single RAG collection by ID."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        # Get collection from database
        from trusted_data_agent.core.collection_db import CollectionDatabase
        db = CollectionDatabase()
        collection = db.get_collection_by_id(collection_id)

        if not collection:
            return jsonify({"status": "error", "message": f"Collection {collection_id} not found"}), 404

        # Check if user has access (owner or subscriber)
        if collection['owner_user_id'] != user_uuid:
            # Check if user is subscribed
            subscription = db.get_subscription_by_user_and_collection(user_uuid, collection_id)
            if not subscription:
                return jsonify({"status": "error", "message": "Access denied"}), 403

        return jsonify({
            "status": "success",
            "collection": collection
        }), 200

    except Exception as e:
        app_logger.error(f"Error getting collection {collection_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>", methods=["PUT"])
async def update_rag_collection(collection_id: int):
    """Update a RAG collection's metadata (name, MCP server, description)."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core.collection_db import CollectionDatabase

        data = await request.get_json()

        # Get collection from database to determine its type
        db = CollectionDatabase()
        collection = db.get_collection_by_id(collection_id)

        if not collection:
            return jsonify({"status": "error", "message": f"Collection with ID {collection_id} not found"}), 404

        # Validate ownership
        if collection['owner_user_id'] != user_uuid:
            return jsonify({"status": "error", "message": "Only collection owners can update collections"}), 403

        repository_type = collection.get('repository_type', 'planner')

        # ENFORCEMENT: Prevent removing mcp_server_id from ANY collection
        if "mcp_server_id" in data:
            new_mcp_server_id = data["mcp_server_id"]
            if not new_mcp_server_id:
                return jsonify({
                    "status": "error",
                    "message": "Cannot remove mcp_server_id. All collections must be associated with an MCP server."
                }), 400

        # Update in database
        update_data = {}
        if "name" in data:
            update_data["name"] = data["name"]
        if "description" in data:
            update_data["description"] = data["description"]
        if "mcp_server_id" in data:
            update_data["mcp_server_id"] = data["mcp_server_id"]

        db.update_collection(collection_id, update_data)

        # For planner repositories, also update APP_STATE
        if repository_type == 'planner':
            collections_list = APP_STATE.get("rag_collections", [])
            coll_meta = next((c for c in collections_list if c["id"] == collection_id), None)

            if coll_meta:
                # Update fields in APP_STATE
                if "name" in data:
                    coll_meta["name"] = data["name"]
                if "description" in data:
                    coll_meta["description"] = data["description"]
                if "mcp_server_id" in data:
                    coll_meta["mcp_server_id"] = data["mcp_server_id"]

                # Save to APP_STATE
                APP_STATE["rag_collections"] = collections_list

                # Persist to config file
                config_manager = get_config_manager()
                config_manager.save_rag_collections(collections_list, user_uuid)

        # Get updated collection from database
        updated_collection = db.get_collection_by_id(collection_id)

        app_logger.info(f"Updated {repository_type} collection {collection_id}: {updated_collection['name']}")
        return jsonify({
            "status": "success",
            "message": "Collection updated successfully",
            "collection": updated_collection
        }), 200

    except Exception as e:
        app_logger.error(f"Error updating RAG collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>", methods=["DELETE"])
async def delete_rag_collection(collection_id: int):
    """Delete a RAG collection."""
    try:
        # --- MARKETPLACE PHASE 2: Validate ownership ---
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
            
        if not retriever.is_user_collection_owner(collection_id, user_uuid):
            return jsonify({"status": "error", "message": "Only collection owners can delete collections"}), 403
        
        # Prevent deletion of user's default collection
        default_collection_id = retriever._get_user_default_collection_id(user_uuid)
        if default_collection_id and collection_id == default_collection_id:
            return jsonify({"status": "error", "message": "Cannot delete your default collection"}), 400
        # --- MARKETPLACE PHASE 2 END ---
        
        # Pass user_id for additional validation in remove_collection
        success = retriever.remove_collection(collection_id, user_id=user_uuid)
        
        if success:
            app_logger.info(f"Deleted RAG collection: {collection_id}")
            return jsonify({"status": "success", "message": "Collection deleted successfully"}), 200
        else:
            return jsonify({"status": "error", "message": "Failed to delete collection or collection not found"}), 404
            
    except Exception as e:
        app_logger.error(f"Error deleting RAG collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>/toggle", methods=["POST"])
async def toggle_rag_collection(collection_id: int):
    """Enable or disable a RAG collection."""
    try:
        data = await request.get_json()
        enabled = data.get("enabled")
        
        if enabled is None:
            return jsonify({"status": "error", "message": "Field 'enabled' is required"}), 400
        
        # Check if attempting to enable a PLANNER collection without MCP server assignment FIRST
        # Knowledge repositories don't require MCP servers
        # This validation should happen even if RAG retriever is not initialized
        if enabled:
            collections_list = APP_STATE.get("rag_collections", [])
            coll_meta = next((c for c in collections_list if c["id"] == collection_id), None)
            if coll_meta:
                repo_type = coll_meta.get("repository_type", "planner")
                # Only planner repositories require MCP server assignment
                if repo_type == "planner" and not coll_meta.get("mcp_server_id"):
                    return jsonify({
                        "status": "error", 
                        "message": "Cannot enable collection: MCP server must be assigned first"
                    }), 400
        
        # Now check if RAG retriever is initialized
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized. Please configure and connect the application first."}), 500
        
        success = retriever.toggle_collection(collection_id, enabled)
        
        if success:
            action = "enabled" if enabled else "disabled"
            app_logger.info(f"{action.capitalize()} RAG collection: {collection_id}")
            return jsonify({
                "status": "success", 
                "message": f"Collection {action} successfully",
                "enabled": enabled
            }), 200
        else:
            return jsonify({"status": "error", "message": "Failed to toggle collection or collection not found"}), 404
            
    except Exception as e:
        app_logger.error(f"Error toggling RAG collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/reload-collections", methods=["POST"])
async def reload_all_collections():
    """
    Reload all enabled collections into the RAG retriever.
    This ensures both planner and knowledge collections are loaded into memory.
    Called during conversation initialization to ensure repositories are ready for querying.
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Reload collections from MCP server (loads both planner and knowledge collections)
        app_logger.info(f"[reload_all_collections] Reloading collections for user {user_uuid}")
        retriever.reload_collections_for_mcp_server()
        
        # Get counts
        loaded_count = len(retriever.collections)
        loaded_ids = list(retriever.collections.keys())
        
        # Get collection details from database
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        accessible_collections = collection_db.get_all_collections(user_id=user_uuid)
        
        planner_count = sum(1 for c in accessible_collections if c['repository_type'] == 'planner' and c['id'] in loaded_ids)
        knowledge_count = sum(1 for c in accessible_collections if c['repository_type'] == 'knowledge' and c['id'] in loaded_ids)
        
        app_logger.info(f"[reload_all_collections] ✅ Loaded {loaded_count} collections: {planner_count} planner, {knowledge_count} knowledge")
        
        return jsonify({
            "status": "success",
            "message": f"Loaded {loaded_count} collection(s): {planner_count} planner, {knowledge_count} knowledge",
            "loaded_collections": loaded_ids,
            "planner_count": planner_count,
            "knowledge_count": knowledge_count,
            "total_count": loaded_count
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error reloading collections: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>/refresh", methods=["POST"])
async def refresh_rag_collection(collection_id: int):
    """Refresh the vector store for a specific RAG collection."""
    try:
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Check if the collection is actually loaded
        if collection_id not in retriever.collections:
            # Get collection info for better error message
            collections_list = APP_STATE.get("rag_collections", [])
            coll_meta = next((c for c in collections_list if c["id"] == collection_id), None)
            
            if not coll_meta:
                return jsonify({"status": "error", "message": f"Collection {collection_id} not found in configuration"}), 404
            
            # Collection exists but isn't loaded - explain why
            current_mcp = APP_CONFIG.CURRENT_MCP_SERVER_ID
            coll_mcp = coll_meta.get("mcp_server_id")
            error_msg = f"Collection '{coll_meta['name']}' (ID: {collection_id}) is not loaded. "
            
            if coll_mcp != current_mcp:
                error_msg += f"It's associated with MCP server '{coll_mcp}' but current server is '{current_mcp}'. "
            elif not coll_meta.get("enabled", False):
                error_msg += "It's disabled. Please enable it first."
            else:
                error_msg += "Reason unknown. Check server logs."
            
            app_logger.warning(error_msg)
            return jsonify({"status": "error", "message": error_msg}), 400
        
        # Run refresh in background to avoid timeout
        asyncio.create_task(asyncio.to_thread(retriever.refresh_vector_store, collection_id))
        
        app_logger.info(f"Started refresh for RAG collection: {collection_id}")
        return jsonify({"status": "success", "message": "Collection refresh started"}), 202
            
    except Exception as e:
        app_logger.error(f"Error refreshing RAG collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>/rows", methods=["GET"])
async def get_rag_collection_rows(collection_id: int):
    """Get rows (cases) from a specific RAG collection.
    
    Query Parameters:
      limit (int): number of rows to return (default 25, max 10000)
      q (str): optional search query; if provided runs a similarity query
      light (bool): if true, omits full_case_data from response for lighter payload
    """
    try:
        # Get query parameters
        limit = int(request.args.get('limit', 25))
        limit = min(limit, 10000)  # Cap at 10000 for performance
        query_text = request.args.get('q', '').strip()
        light = request.args.get('light', 'false').lower() == 'true'
        
        # Get retriever
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"error": "RAG retriever not initialized"}), 500
        
        # Check if collection is loaded in ChromaDB
        if collection_id not in retriever.collections:
            # Collection exists in database but not loaded in ChromaDB yet
            # Log which collections ARE loaded for debugging
            loaded_ids = list(retriever.collections.keys())
            app_logger.warning(f"Collection {collection_id} not in retriever.collections. Loaded IDs: {loaded_ids}")

            # Try to reload collections to pick up newly imported ones
            try:
                retriever.reload_collections_for_mcp_server()
                app_logger.info(f"Reloaded collections. Now have {len(retriever.collections)} loaded")

                # Check again after reload
                if collection_id in retriever.collections:
                    app_logger.info(f"Collection {collection_id} successfully loaded after reload")
                else:
                    # Still not found - return empty
                    return jsonify({
                        "rows": [],
                        "total": 0,
                        "collection_id": collection_id,
                        "message": f"Collection is not loaded. Loaded IDs: {loaded_ids}. Try refreshing the page."
                    }), 200
            except Exception as e:
                app_logger.error(f"Failed to reload collections: {e}", exc_info=True)
                return jsonify({
                    "rows": [],
                    "total": 0,
                    "collection_id": collection_id,
                    "message": "Collection is empty. Add some RAG cases to get started."
                }), 200
        
        # Get the ChromaDB collection
        collection = retriever.collections[collection_id]
        
        # Get collection metadata
        collections_list = APP_STATE.get("rag_collections", [])
        collection_meta = next((c for c in collections_list if c["id"] == collection_id), None)
        
        if not collection_meta:
            return jsonify({"error": f"Collection {collection_id} metadata not found"}), 404
        
        rows = []
        total = 0
        
        if query_text and len(query_text) >= 3:
            # Similarity search
            try:
                query_results = collection.query(
                    query_texts=[query_text], n_results=limit, include=["metadatas", "distances"]
                )
                if query_results and query_results.get("ids"):
                    total = len(query_results["ids"][0])
                    for i in range(total):
                        row_id = query_results["ids"][0][i]
                        meta = query_results["metadatas"][0][i]
                        distance = query_results["distances"][0][i]
                        similarity = 1 - distance
                        full_case_data = None
                        if not light:
                            try:
                                full_case_data = json.loads(meta.get("full_case_data", "{}"))
                            except json.JSONDecodeError:
                                full_case_data = None
                        rows.append({
                            "id": row_id,
                            "user_query": meta.get("user_query"),
                            "strategy_type": meta.get("strategy_type"),
                            "is_most_efficient": meta.get("is_most_efficient"),
                            "user_feedback_score": meta.get("user_feedback_score", 0),
                            "output_tokens": meta.get("output_tokens"),
                            "timestamp": meta.get("timestamp"),
                            "similarity_score": similarity,
                            "full_case_data": full_case_data,
                        })
            except Exception as qe:
                app_logger.warning(f"Query failed for collection {collection_id}: {qe}")
        else:
            # Get all or sample
            try:
                all_results = collection.get(include=["metadatas"])
                ids = all_results.get("ids", [])
                metas = all_results.get("metadatas", [])
                total = len(ids)
                sample_count = min(limit, total)
                for i in range(sample_count):
                    meta = metas[i]
                    full_case_data = None
                    if not light:
                        try:
                            full_case_data = json.loads(meta.get("full_case_data", "{}"))
                        except json.JSONDecodeError:
                            full_case_data = None
                    rows.append({
                        "id": ids[i],
                        "user_query": meta.get("user_query"),
                        "strategy_type": meta.get("strategy_type"),
                        "is_most_efficient": meta.get("is_most_efficient"),
                        "user_feedback_score": meta.get("user_feedback_score", 0),
                        "output_tokens": meta.get("output_tokens"),
                        "timestamp": meta.get("timestamp"),
                        "full_case_data": full_case_data,
                    })
            except Exception as ge:
                app_logger.error(f"Failed to get rows for collection {collection_id}: {ge}", exc_info=True)
        
        return jsonify({
            "rows": rows,
            "total": total,
            "query": query_text,
            "collection_id": collection_id,
            "collection_name": collection_meta["name"]
        }), 200
            
    except Exception as e:
        app_logger.error(f"Error getting collection rows: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@rest_api_bp.route("/v1/rag/cases/<case_id>/feedback", methods=["POST"])
async def submit_rag_case_feedback(case_id: str):
    """Submit user feedback (upvote/downvote) for a RAG case."""
    try:
        data = await request.get_json()
        feedback_score = data.get("feedback_score")
        
        # Validate feedback_score
        if feedback_score not in [-1, 0, 1]:
            return jsonify({
                "status": "error", 
                "message": "Invalid feedback_score. Must be -1 (downvote), 0 (neutral), or 1 (upvote)"
            }), 400
        
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Update the case feedback
        success = await retriever.update_case_feedback(case_id, feedback_score)
        
        if success:
            action = "upvoted" if feedback_score == 1 else "downvoted" if feedback_score == -1 else "reset"
            app_logger.info(f"Case {case_id} {action} by user")
            return jsonify({
                "status": "success", 
                "message": f"Feedback submitted successfully",
                "case_id": case_id,
                "feedback_score": feedback_score
            }), 200
        else:
            return jsonify({"status": "error", "message": "Failed to update feedback. Case not found."}), 404
            
    except Exception as e:
        app_logger.error(f"Error submitting RAG case feedback: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>/populate", methods=["POST"])
async def populate_collection_from_template(collection_id: int):
    """
    Populate a RAG collection using a template and user-provided examples.
    
    Request body:
    {
        "template_type": "sql_query",
        "examples": [
            {
                "user_query": "Show me all users older than 25",
                "sql_statement": "SELECT * FROM users WHERE age > 25"
            },
            {
                "user_query": "Count completed orders",
                "sql_statement": "SELECT COUNT(*) FROM orders WHERE status = 'completed'"
            }
        ],
        "database_name": "mydb",  // optional
        "mcp_tool_name": "base_readQuery"  // optional
    }
    """
    try:
        data = await request.get_json()
        
        # Validate required fields
        # template_type: Strategy/execution type (sql_query, api_request, etc.)
        # - Determines which template definition to use
        # - Maps to template JSON files (sql_query_v1.json, etc.)
        template_type = data.get("template_type")
        template_id = data.get("template_id")  # New: support specific template ID
        examples_data = data.get("examples", [])
        
        if not template_type:
            return jsonify({"status": "error", "message": "template_type is required"}), 400
        
        if not examples_data or not isinstance(examples_data, list):
            return jsonify({"status": "error", "message": "examples must be a non-empty list"}), 400
        
        # Currently only SQL template is supported
        if template_type != "sql_query":
            return jsonify({"status": "error", "message": f"Unsupported template_type: {template_type}. Only 'sql_query' is supported."}), 400
        
        # Default to sql_query_v1 if no specific template_id provided
        if not template_id:
            template_id = "sql_query_v1"
        
        # Parse examples based on template type
        if template_type == "sql_query":
            examples = []
            for idx, ex in enumerate(examples_data):
                user_query = ex.get("user_query")
                sql_statement = ex.get("sql_statement")
                
                if not user_query or not sql_statement:
                    return jsonify({
                        "status": "error", 
                        "message": f"Example {idx+1} missing required fields (user_query, sql_statement)"
                    }), 400
                
                examples.append((user_query, sql_statement))
        
        # Get RAG retriever
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Import and create template generator
        from trusted_data_agent.agent.rag_template_generator import RAGTemplateGenerator
        generator = RAGTemplateGenerator(retriever)
        
        # Validate examples first
        app_logger.info(f"Validating {len(examples)} examples before population")
        validation_issues = generator.validate_sql_examples(examples)
        if validation_issues:
            app_logger.error(f"Validation failed: {validation_issues}")
            # Log all failing examples for debugging
            for issue in validation_issues:
                idx = issue['example_index'] - 1  # Convert to 0-based index
                if idx < len(examples):
                    app_logger.error(f"Failed example {issue['example_index']}: {examples[idx]}")
            return jsonify({
                "status": "error", 
                "message": "Validation failed for some examples",
                "validation_issues": validation_issues
            }), 400
        
        # Populate collection
        database_name = data.get("database_name")
        mcp_tool_name = data.get("mcp_tool_name")
        
        # Use template-specific defaults if not provided
        if not mcp_tool_name:
            # Get default from template configuration
            template_config = generator.template_manager.get_template_config(template_id)
            mcp_tool_name = template_config.get("default_mcp_tool", "base_readQuery")
        
        app_logger.info(f"Populating collection {collection_id} with {len(examples)} examples using template {template_id}")
        
        # Use generic populate method that works with any template
        results = generator.populate_collection_from_template(
            template_id=template_id,
            collection_id=collection_id,
            examples=examples,
            database_name=database_name,
            mcp_tool_name=mcp_tool_name
        )
        
        app_logger.info(f"Population complete - Successful: {results['successful']}, Failed: {results['failed']}")
        if results['errors']:
            app_logger.error(f"Population errors: {results['errors']}")
        
        return jsonify({
            "status": "success",
            "message": f"Successfully populated {results['successful']} cases",
            "results": results
        }), 200
        
    except ValueError as ve:
        # Collection validation error
        app_logger.error(f"Validation error: {ve}")
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        app_logger.error(f"Error populating collection from template: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates", methods=["GET"])
async def get_rag_templates():
    """Get information about available Planner Repository Constructors."""
    try:
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        from trusted_data_agent.agent.rag_template_generator import RAGTemplateGenerator
        generator = RAGTemplateGenerator(retriever)
        
        # Get info for all supported templates
        sql_template = generator.get_template_info("sql_query")
        
        return jsonify({
            "status": "success",
            "templates": {
                "sql_query": sql_template
            }
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error getting Planner Repository Constructors: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/<template_id>/config", methods=["GET"])
async def get_rag_template_config(template_id: str):
    """
    Get the editable configuration for a specific template.
    
    Returns the current configuration values that can be customized.
    """
    try:
        from trusted_data_agent.agent.rag_template_manager import get_template_manager
        
        template_manager = get_template_manager()
        
        # Get template - will raise TemplateNotFoundError if not found
        template = template_manager.get_template(template_id)
        
        # Get editable configuration
        config = template_manager.get_template_config(template_id)
        
        # Get template metadata
        metadata = {
            "template_id": template.get("template_id"),
            "template_name": template.get("template_name"),
            "template_type": template.get("template_type"),
            "description": template.get("description"),
            "version": template.get("template_version")
        }
        
        return jsonify({
            "status": "success",
            "template": metadata,
            "config": config
        }), 200
    
    except TemplateNotFoundError as e:
        return jsonify({
            "status": "error",
            "error_type": "template_not_found",
            "message": str(e),
            "template_id": template_id
        }), 404
    except TemplateError as e:
        app_logger.error(f"Template error getting config: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error_type": "template_error",
            "message": str(e)
        }), 500
    except Exception as e:
        app_logger.error(f"Unexpected error getting template config: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/<template_id>/config", methods=["PUT"])
async def update_rag_template_config(template_id: str):
    """
    Update the editable configuration for a specific template.
    
    Body:
    {
        "default_mcp_tool": "base_readQuery",
        "estimated_input_tokens": 150,
        "estimated_output_tokens": 180
    }
    """
    try:
        from trusted_data_agent.agent.rag_template_manager import get_template_manager
        
        data = await request.get_json()
        
        template_manager = get_template_manager()
        
        # Update configuration - will raise TemplateNotFoundError if template doesn't exist
        template_manager.update_template_config(template_id, data)
        
        # Get updated config
        updated_config = template_manager.get_template_config(template_id)
        
        return jsonify({
            "status": "success",
            "message": f"Template {template_id} configuration updated",
            "config": updated_config
        }), 200
    
    except TemplateNotFoundError as e:
        return jsonify({
            "status": "error",
            "error_type": "template_not_found",
            "message": str(e),
            "template_id": template_id
        }), 404
    except TemplateError as e:
        app_logger.error(f"Template error updating config: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error_type": "template_error",
            "message": str(e)
        }), 500
    except Exception as e:
        app_logger.error(f"Unexpected error updating template config: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/list", methods=["GET"])
async def list_rag_templates():
    """
    List all available templates with their metadata.
    """
    try:
        from trusted_data_agent.agent.rag_template_manager import get_template_manager
        
        template_manager = get_template_manager()
        templates = template_manager.list_templates()
        
        return jsonify({
            "status": "success",
            "templates": templates
        }), 200
    
    except TemplateRegistryError as e:
        app_logger.error(f"Registry error listing templates: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error_type": "registry_error",
            "message": str(e)
        }), 500
    except TemplateError as e:
        app_logger.error(f"Template error listing templates: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error_type": "template_error",
            "message": str(e)
        }), 500
    except Exception as e:
        app_logger.error(f"Unexpected error listing templates: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/discover", methods=["GET"])
async def discover_template_plugins():
    """
    Discover all available template plugins from configured directories.
    
    Returns information about plugins including those not yet loaded.
    """
    try:
        from trusted_data_agent.agent.rag_template_manager import get_template_manager
        
        template_manager = get_template_manager()
        discovered = template_manager.discover_plugins()
        
        return jsonify({
            "status": "success",
            "plugins": discovered,
            "count": len(discovered)
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error discovering plugins: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/<template_id>/full", methods=["GET"])
async def get_full_template(template_id: str):
    """
    Get the complete template data including all configuration.
    
    Returns the full template JSON with all fields.
    """
    try:
        from trusted_data_agent.agent.rag_template_manager import get_template_manager
        
        template_manager = get_template_manager()
        template = template_manager.get_template(template_id)  # Will raise TemplateNotFoundError if not found
        
        return jsonify({
            "status": "success",
            "template": template
        }), 200
    
    except TemplateNotFoundError as e:
        return jsonify({
            "status": "error",
            "error_type": "template_not_found",
            "message": str(e),
            "template_id": template_id
        }), 404
    except TemplateError as e:
        app_logger.error(f"Template error getting full template: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error_type": "template_error",
            "message": str(e)
        }), 500
    except Exception as e:
        app_logger.error(f"Unexpected error getting full template: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/<template_id>/plugin-info", methods=["GET"])
async def get_template_plugin_info(template_id: str):
    """
    Get plugin manifest information for a specific template.
    
    Returns the manifest.json content if available.
    """
    try:
        from trusted_data_agent.agent.rag_template_manager import get_template_manager
        
        template_manager = get_template_manager()
        plugin_info = template_manager.get_plugin_info(template_id)
        
        if not plugin_info:
            return jsonify({
                "status": "error",
                "message": f"No plugin info found for template {template_id}"
            }), 404
        
        return jsonify({
            "status": "success",
            "plugin_info": plugin_info
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error getting plugin info: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>/export", methods=["GET"])
async def export_collection(collection_id: int):
    """
    Export a knowledge collection as a portable .zip file.

    Query Parameters:
        export_path (optional): Custom directory path for server-side export.
                               If not provided, file is downloaded to browser.

    The export includes:
    - collection_metadata.json: Collection configuration from database
    - chroma_data/: ChromaDB collection data (embeddings + documents)

    This allows fast import on other servers without re-embedding.
    """
    import zipfile
    import tempfile
    import shutil
    from quart import send_file
    import os

    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        # Get optional export_path parameter
        export_path = request.args.get('export_path', '').strip()

        # Get collection from database
        from trusted_data_agent.core.collection_db import CollectionDatabase
        db = CollectionDatabase()
        collection = db.get_collection_by_id(collection_id)

        if not collection:
            return jsonify({"status": "error", "message": f"Collection {collection_id} not found"}), 404

        # Check ownership
        if collection['owner_user_id'] != user_uuid:
            return jsonify({"status": "error", "message": "You don't own this collection"}), 403

        # Get ChromaDB collection name and path
        collection_name = collection['collection_name']
        chroma_base_path = Path(__file__).resolve().parents[3] / ".chromadb_rag_cache"

        # Find the ChromaDB collection directory (UUID-based)
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500

        # Get the actual ChromaDB collection to find its UUID
        chroma_collection = None
        try:
            chroma_collection = retriever.client.get_collection(name=collection_name)
        except Exception as e:
            return jsonify({"status": "error", "message": f"ChromaDB collection not found: {e}"}), 404

        # ChromaDB uses segments for vector storage
        # The directory names are segment IDs, not collection IDs
        # We need to query the ChromaDB SQLite to find the segment ID for this collection
        chroma_uuid = str(chroma_collection.id)

        # Query ChromaDB's SQLite database to find the segment ID
        import sqlite3
        chroma_db_path = chroma_base_path / "chroma.sqlite3"

        try:
            conn = sqlite3.connect(str(chroma_db_path))
            cursor = conn.cursor()

            # Get VECTOR segment ID
            cursor.execute("SELECT id FROM segments WHERE collection = ? AND scope = 'VECTOR'", (chroma_uuid,))
            result = cursor.fetchone()
            if not result:
                conn.close()
                app_logger.error(f"No vector segment found for collection {chroma_uuid}")
                return jsonify({"status": "error", "message": "ChromaDB segment not found"}), 404
            segment_id = result[0]
            chroma_collection_path = chroma_base_path / segment_id

            # Get METADATA segment ID (for embedding data)
            cursor.execute("SELECT id FROM segments WHERE collection = ? AND scope = 'METADATA'", (chroma_uuid,))
            metadata_result = cursor.fetchone()
            metadata_segment_id = metadata_result[0] if metadata_result else None

            app_logger.info(f"Export: Collection UUID: {chroma_uuid}, Vector Segment ID: {segment_id}, Metadata Segment ID: {metadata_segment_id}")
            app_logger.info(f"Export: ChromaDB data path: {chroma_collection_path}")

        except Exception as e:
            conn.close()
            app_logger.error(f"Error querying ChromaDB database: {e}", exc_info=True)
            return jsonify({"status": "error", "message": f"Failed to locate ChromaDB data: {e}"}), 500

        if not chroma_collection_path.exists():
            return jsonify({"status": "error", "message": "ChromaDB segment directory not found"}), 404

        # Get actual document count from ChromaDB
        try:
            actual_document_count = chroma_collection.count()
            app_logger.info(f"Export: ChromaDB collection has {actual_document_count} documents")
        except Exception as e:
            app_logger.warning(f"Failed to get document count from ChromaDB: {e}")
            actual_document_count = collection.get('document_count', 0)

        # Create temporary directory for export
        temp_dir = tempfile.mkdtemp()
        temp_export_dir = Path(temp_dir)

        try:
            # 1. Save collection metadata
            metadata = {
                "collection_id": collection_id,
                "name": collection['name'],
                "description": collection['description'],
                "repository_type": collection['repository_type'],
                "mcp_server_id": collection.get('mcp_server_id'),  # For planner repositories
                "chunking_strategy": collection['chunking_strategy'],
                "chunk_size": collection['chunk_size'],
                "chunk_overlap": collection['chunk_overlap'],
                "embedding_model": collection['embedding_model'],
                "collection_name": collection_name,
                "chroma_uuid": chroma_uuid,
                "chroma_segment_id": segment_id,
                "document_count": actual_document_count,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "export_version": "1.0"
            }

            metadata_file = temp_export_dir / "collection_metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            # 2. Export all documents with embeddings using ChromaDB API
            # This is the proper way - ChromaDB handles all internal consistency
            try:
                # Get all documents with their embeddings and metadata
                all_data = chroma_collection.get(include=['embeddings', 'documents', 'metadatas'])

                # Convert embeddings to lists (they might be numpy arrays)
                # and handle NaN/Infinity values
                embeddings_list = []
                for emb in all_data['embeddings']:
                    if isinstance(emb, list):
                        embeddings_list.append(emb)
                    else:
                        # Convert numpy array to list
                        embeddings_list.append(emb.tolist() if hasattr(emb, 'tolist') else list(emb))

                # Save complete document data
                documents_file = temp_export_dir / "documents.json"
                documents_export = {
                    'ids': all_data['ids'],
                    'documents': all_data['documents'],
                    'metadatas': all_data['metadatas'],
                    'embeddings': embeddings_list
                }

                with open(documents_file, 'w') as f:
                    json.dump(documents_export, f, allow_nan=False)

                app_logger.info(f"Export: Saved {len(all_data['ids'])} documents with embeddings and metadata")
            except Exception as e:
                app_logger.warning(f"Failed to export documents: {e}", exc_info=True)

            # 4. Create zip file
            # Sanitize collection name for filesystem (remove invalid characters including slashes)
            safe_name = re.sub(r'[<>:"/\\|?*]', '-', collection['name'])  # Replace invalid chars with dash
            safe_name = safe_name.replace(' ', '_')  # Replace spaces with underscores
            safe_name = safe_name.strip('-_')  # Remove leading/trailing dashes/underscores
            zip_filename = f"collection_{collection_id}_{safe_name}.zip"

            # Determine zip file location
            if export_path:
                # Validate and create custom export directory
                try:
                    custom_export_dir = Path(export_path).expanduser().resolve()
                    if not custom_export_dir.exists():
                        custom_export_dir.mkdir(parents=True, exist_ok=True)
                    if not custom_export_dir.is_dir():
                        raise ValueError(f"Export path is not a directory: {export_path}")
                    zip_path = custom_export_dir / zip_filename
                    app_logger.info(f"Export: Using custom directory: {custom_export_dir}")
                except Exception as e:
                    app_logger.error(f"Invalid export path '{export_path}': {e}")
                    return jsonify({
                        "status": "error",
                        "message": f"Invalid export path: {str(e)}"
                    }), 400
            else:
                # Use temp directory for browser download
                zip_path = Path(temp_dir) / zip_filename

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in temp_export_dir.rglob('*'):
                    if file_path.is_file() and file_path != zip_path:
                        arcname = file_path.relative_to(temp_export_dir)
                        zipf.write(file_path, arcname)

            app_logger.info(f"Exported collection {collection_id} to {zip_filename} ({zip_path.stat().st_size / 1024 / 1024:.2f} MB)")

            # If custom export path, save file there and return success message
            if export_path:
                # File already saved to custom location, clean up temp directory
                shutil.rmtree(temp_dir, ignore_errors=True)
                return jsonify({
                    "status": "success",
                    "message": f"Collection exported to {zip_path}",
                    "file_path": str(zip_path),
                    "file_size_mb": round(zip_path.stat().st_size / 1024 / 1024, 2)
                }), 200
            else:
                # Send file to browser and clean up after
                response = await send_file(
                    str(zip_path),
                    as_attachment=True,
                    attachment_filename=zip_filename,
                    mimetype='application/zip'
                )
                # Schedule cleanup (Quart will clean up after sending)
                return response

        except Exception as e:
            # Clean up temp directory on error
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    except Exception as e:
        app_logger.error(f"Error exporting collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/import", methods=["POST"])
async def import_collection():
    """
    Import a knowledge collection from an exported .zip file.

    Two modes:
    1. File upload: multipart/form-data with 'file' field containing the .zip
    2. Server path: JSON body with 'import_path' field pointing to .zip on server

    The import will:
    - Extract collection metadata
    - Restore ChromaDB data (no re-embedding needed)
    - Create new collection in database with new owner
    """
    import zipfile
    import tempfile
    import shutil
    import os

    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        temp_path = Path(temp_dir)

        try:
            # Determine import mode: file upload or server path
            content_type = request.content_type or ''

            if 'multipart/form-data' in content_type:
                # Mode 1: File upload from browser
                files = await request.files
                if 'file' not in files:
                    return jsonify({"status": "error", "message": "No file uploaded"}), 400

                uploaded_file = files['file']
                if not uploaded_file.filename.endswith('.zip'):
                    return jsonify({"status": "error", "message": "File must be a .zip archive"}), 400

                # Save uploaded file
                zip_path = temp_path / "import.zip"
                await uploaded_file.save(str(zip_path))
                app_logger.info(f"Import: Received uploaded file {uploaded_file.filename}")

            elif 'application/json' in content_type:
                # Mode 2: Import from server path
                data = await request.get_json()
                import_path = data.get('import_path', '').strip()

                if not import_path:
                    return jsonify({"status": "error", "message": "import_path required"}), 400

                # Validate and resolve server path
                try:
                    server_zip_path = Path(import_path).expanduser().resolve()

                    if not server_zip_path.exists():
                        raise FileNotFoundError(f"File not found: {import_path}")

                    if not server_zip_path.is_file():
                        raise ValueError(f"Path is not a file: {import_path}")

                    if not str(server_zip_path).endswith('.zip'):
                        raise ValueError(f"File must be a .zip archive")

                    # Copy to temp directory for processing
                    zip_path = temp_path / "import.zip"
                    shutil.copy2(server_zip_path, zip_path)
                    app_logger.info(f"Import: Using server file {server_zip_path}")

                except Exception as e:
                    app_logger.error(f"Invalid import path '{import_path}': {e}")
                    return jsonify({
                        "status": "error",
                        "message": f"Invalid import path: {str(e)}"
                    }), 400
            else:
                return jsonify({
                    "status": "error",
                    "message": "Request must be multipart/form-data (file upload) or application/json (server path)"
                }), 400

            # Extract zip
            extract_path = temp_path / "extracted"
            extract_path.mkdir()

            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(extract_path)

            # Read metadata
            metadata_file = extract_path / "collection_metadata.json"
            if not metadata_file.exists():
                return jsonify({"status": "error", "message": "Invalid export: metadata file missing"}), 400

            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            # Validate export version
            if metadata.get('export_version') != "1.0":
                return jsonify({"status": "error", "message": "Unsupported export version"}), 400

            # Check if documents data exists
            documents_file = extract_path / "documents.json"
            if not documents_file.exists():
                return jsonify({"status": "error", "message": "Invalid export: documents.json missing"}), 400

            # Generate new collection name (avoid conflicts)
            import time
            original_name = metadata['name']
            new_collection_name = f"col_{user_uuid}_{int(time.time())}"

            # Get the RAG retriever to recreate the collection using ChromaDB's API
            retriever = APP_STATE.get("rag_retriever_instance")
            if not retriever:
                return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500

            # Get the embedding model
            embedding_model = metadata.get('embedding_model', 'all-MiniLM-L6-v2')

            # Create embedding function
            from chromadb.utils import embedding_functions
            embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embedding_model)

            # Import documents using ChromaDB's proper API
            # IMPORTANT: Use the retriever's client to avoid synchronization issues
            # Creating a separate client can cause timing problems where the documents
            # aren't immediately visible when we reload
            chroma_client = retriever.client

            try:
                # Get repository type and create metadata
                repo_type = metadata.get('repository_type', 'knowledge')
                collection_metadata = {
                    "hnsw:space": "cosine",
                    "repository_type": repo_type
                }

                # Create new collection
                app_logger.info(f"Creating ChromaDB collection: {new_collection_name}")
                chroma_collection = chroma_client.create_collection(
                    name=new_collection_name,
                    metadata=collection_metadata,
                    embedding_function=embedding_func
                )
                app_logger.info(f"Created ChromaDB collection: {new_collection_name}")

                # Load documents data from export
                documents_file = extract_path / "documents.json"

                if documents_file.exists():
                    app_logger.info(f"Loading documents from documents.json")

                    with open(documents_file, 'r') as f:
                        documents_data = json.load(f)

                    ids = documents_data.get('ids', [])
                    documents = documents_data.get('documents', [])
                    metadatas = documents_data.get('metadatas', [])
                    embeddings = documents_data.get('embeddings', [])

                    app_logger.info(f"Loaded {len(ids)} IDs, {len(documents)} documents, {len(metadatas)} metadatas, {len(embeddings)} embeddings")

                    # Add documents with their pre-computed embeddings
                    # ChromaDB will handle all internal indexing and metadata
                    if ids and documents and embeddings:
                        try:
                            chroma_collection.add(
                                ids=ids,
                                documents=documents,
                                metadatas=metadatas if metadatas else None,
                                embeddings=embeddings
                            )
                            app_logger.info(f"Successfully added {len(ids)} documents to ChromaDB collection")
                        except Exception as add_error:
                            app_logger.error(f"Failed to add documents to ChromaDB: {add_error}", exc_info=True)
                            raise
                    else:
                        app_logger.warning(f"No valid document data found in export - ids={len(ids)}, docs={len(documents)}, embs={len(embeddings)}")
                else:
                    app_logger.warning(f"documents.json not found - collection will be empty")

                # Verify import
                document_count = chroma_collection.count()
                app_logger.info(f"Imported collection has {document_count} documents")

            except Exception as e:
                app_logger.error(f"Failed to import collection into ChromaDB: {e}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to import collection: {e}"}), 500

            # Create collection in our database
            from trusted_data_agent.core.collection_db import CollectionDatabase
            db = CollectionDatabase()

            # For planner repositories, associate with current MCP server (not the original one)
            # This ensures the imported collection is immediately usable
            repo_type = metadata.get('repository_type', 'knowledge')
            if repo_type == 'planner':
                current_mcp_server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID
                app_logger.info(f"Associating imported planner collection with current MCP server: {current_mcp_server_id}")
                assigned_mcp_server_id = current_mcp_server_id
            else:
                # Knowledge repositories don't need MCP server association
                assigned_mcp_server_id = None

            new_collection = {
                "name": f"{original_name} (Imported)",
                "collection_name": new_collection_name,
                "description": metadata.get('description', ''),
                "repository_type": repo_type,
                "mcp_server_id": assigned_mcp_server_id,
                "chunking_strategy": metadata.get('chunking_strategy', 'recursive'),
                "chunk_size": metadata.get('chunk_size', 1000),
                "chunk_overlap": metadata.get('chunk_overlap', 200),
                "embedding_model": embedding_model,
                "owner_user_id": user_uuid,
                "enabled": True,
                "visibility": "private"
            }

            collection_id = db.create_collection(new_collection)

            # For planner repositories, update APP_STATE to include the new collection
            if new_collection['repository_type'] == 'planner':
                # Get the full collection metadata from database
                from trusted_data_agent.core.collection_db import get_collection_db
                collection_db = get_collection_db()
                imported_collection_meta = collection_db.get_collection_by_id(collection_id)

                # Add to APP_STATE rag_collections list
                rag_collections = APP_STATE.get("rag_collections", [])
                rag_collections.append(imported_collection_meta)
                APP_STATE["rag_collections"] = rag_collections
                app_logger.info(f"Added imported planner collection to APP_STATE (total: {len(rag_collections)})")

            # Reload ChromaDB collections in retriever
            try:
                retriever.reload_collections_for_mcp_server()
                app_logger.info(f"Reloaded RAG collections after import")
                app_logger.info(f"Retriever now has collection IDs: {list(retriever.collections.keys())}")

                # Verify the imported collection using the retriever's loaded collection
                if collection_id in retriever.collections:
                    imported_collection = retriever.collections[collection_id]
                    actual_count = imported_collection.count()
                    app_logger.info(f"Imported collection has {actual_count} documents (verified from retriever)")
                else:
                    app_logger.warning(f"Collection {collection_id} not found in retriever.collections after reload")
                    actual_count = document_count

            except Exception as e:
                app_logger.warning(f"Failed to verify import: {e}", exc_info=True)
                actual_count = document_count

            app_logger.info(f"Imported collection {collection_id} for user {user_uuid} from {uploaded_file.filename}")

            return jsonify({
                "status": "success",
                "message": f"Collection imported successfully",
                "collection_id": collection_id,
                "collection_name": new_collection['name'],
                "document_count": actual_count
            }), 200

        finally:
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    except Exception as e:
        app_logger.error(f"Error importing collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/reload", methods=["POST"])
async def reload_template_plugins():
    """
    Hot-reload all template plugins without restarting the application.
    
    Useful for development and testing new templates.
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.agent.rag_template_manager import get_template_manager
        
        template_manager = get_template_manager()
        template_manager.reload_templates()
        
        templates = template_manager.list_templates()
        
        return jsonify({
            "status": "success",
            "message": "Templates reloaded successfully",
            "count": len(templates),
            "templates": templates
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error reloading templates: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/validate", methods=["POST"])
async def validate_template_plugin():
    """
    Validate a template plugin package before installation.
    
    Request body:
    {
        "plugin_path": "/path/to/plugin/directory"
    }
    
    Returns validation results with errors and warnings.
    """
    try:
        from trusted_data_agent.agent.template_plugin_validator import validate_plugin_package
        from pathlib import Path
        
        data = await request.get_json()
        plugin_path = data.get("plugin_path")
        
        if not plugin_path:
            return jsonify({
                "status": "error",
                "message": "plugin_path is required"
            }), 400
        
        plugin_dir = Path(plugin_path)
        if not plugin_dir.exists():
            return jsonify({
                "status": "error",
                "message": f"Plugin directory not found: {plugin_path}"
            }), 404
        
        is_valid, errors, warnings = validate_plugin_package(plugin_dir)
        
        return jsonify({
            "status": "success",
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error validating plugin: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/<template_id>/defaults", methods=["GET"])
async def get_template_defaults(template_id: str):
    """
    Get template parameter defaults for the current user.
    Falls back to system defaults if user hasn't customized.
    
    Returns:
    {
        "status": "success",
        "template_id": "knowledge_repo_v1",
        "defaults": {
            "chunking_strategy": "semantic",
            "embedding_model": "all-MiniLM-L6-v2",
            ...
        },
        "is_customized": true  // Whether user has customized defaults
    }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        import sqlite3
        from datetime import datetime

        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        # Get user-specific defaults
        cursor.execute("""
            SELECT parameter_name, parameter_value, parameter_type
            FROM template_defaults
            WHERE template_id = ? AND user_id = ?
        """, (template_id, user_uuid))
        
        user_defaults = {row[0]: _parse_parameter_value(row[1], row[2]) for row in cursor.fetchall()}
        
        # Get system defaults (fallback)
        cursor.execute("""
            SELECT parameter_name, parameter_value, parameter_type
            FROM template_defaults
            WHERE template_id = ? AND is_system_default = 1
        """, (template_id,))
        
        system_defaults = {row[0]: _parse_parameter_value(row[1], row[2]) for row in cursor.fetchall()}
        
        conn.close()
        
        # Merge: user defaults override system defaults
        defaults = {**system_defaults, **user_defaults}
        is_customized = len(user_defaults) > 0
        
        return jsonify({
            "status": "success",
            "template_id": template_id,
            "defaults": defaults,
            "is_customized": is_customized
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error getting template defaults: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/<template_id>/defaults", methods=["POST"])
async def save_template_defaults(template_id: str):
    """
    Save template parameter defaults for the current user.
    
    Request body:
    {
        "defaults": {
            "chunking_strategy": "paragraph",
            "embedding_model": "all-mpnet-base-v2",
            "chunk_size": 1500
        }
    }
    
    Returns:
    {
        "status": "success",
        "message": "Defaults saved successfully",
        "updated_count": 3
    }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        data = await request.get_json()
        defaults = data.get("defaults", {})
        
        if not defaults:
            return jsonify({"status": "error", "message": "No defaults provided"}), 400
        
        import sqlite3
        from datetime import datetime

        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        updated_count = 0
        now = datetime.utcnow().isoformat()
        
        for param_name, param_value in defaults.items():
            # Determine parameter type
            param_type = _get_parameter_type(param_value)
            param_value_str = _serialize_parameter_value(param_value, param_type)
            
            # Upsert: Insert or update
            cursor.execute("""
                INSERT INTO template_defaults 
                (template_id, user_id, parameter_name, parameter_value, parameter_type, 
                 is_system_default, created_at, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(template_id, user_id, parameter_name) 
                DO UPDATE SET 
                    parameter_value = excluded.parameter_value,
                    parameter_type = excluded.parameter_type,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
            """, (template_id, user_uuid, param_name, param_value_str, param_type, 
                  now, now, user_uuid))
            
            updated_count += 1
        
        conn.commit()
        conn.close()
        
        app_logger.info(f"User {user_uuid} saved {updated_count} defaults for template {template_id}")
        
        return jsonify({
            "status": "success",
            "message": "Defaults saved successfully",
            "updated_count": updated_count
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error saving template defaults: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/templates/<template_id>/defaults", methods=["DELETE"])
async def reset_template_defaults(template_id: str):
    """
    Reset template defaults to system defaults (delete user customizations).
    
    Returns:
    {
        "status": "success",
        "message": "Defaults reset to system defaults"
    }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401


        import sqlite3

        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM template_defaults
            WHERE template_id = ? AND user_id = ?
        """, (template_id, user_uuid))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        app_logger.info(f"User {user_uuid} reset {deleted_count} defaults for template {template_id}")
        
        return jsonify({
            "status": "success",
            "message": "Defaults reset to system defaults",
            "deleted_count": deleted_count
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error resetting template defaults: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


def _get_parameter_type(value):
    """Determine parameter type from Python value."""
    if isinstance(value, bool):
        return 'boolean'
    elif isinstance(value, int):
        return 'integer'
    elif isinstance(value, float):
        return 'number'
    elif isinstance(value, list):
        return 'array'
    elif isinstance(value, dict):
        return 'object'
    else:
        return 'string'


def _serialize_parameter_value(value, param_type):
    """Serialize parameter value to string for storage."""
    if param_type in ['array', 'object']:
        import json
        return json.dumps(value)
    elif param_type == 'boolean':
        return '1' if value else '0'
    else:
        return str(value)


def _parse_parameter_value(value_str, param_type):
    """Parse parameter value from storage string."""
    if param_type == 'boolean':
        return value_str in ['1', 'true', 'True']
    elif param_type == 'integer':
        return int(value_str)
    elif param_type == 'number':
        return float(value_str)
    elif param_type in ['array', 'object']:
        import json
        return json.loads(value_str)
    else:
        return value_str


# ============================================================================
# MCP SERVER CONFIGURATION ENDPOINTS
# ============================================================================

@rest_api_bp.route("/v1/mcp/servers", methods=["GET"])
async def get_mcp_servers():
    """Get all MCP server configurations."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        servers = config_manager.get_mcp_servers(user_uuid)
        active_server_id = config_manager.get_active_mcp_server_id(user_uuid)
        
        return jsonify({
            "status": "success",
            "servers": servers,
            "active_server_id": active_server_id
        }), 200
    except Exception as e:
        app_logger.error(f"Error getting MCP servers: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/mcp/servers", methods=["POST"])
async def create_mcp_server():
    """Create a new MCP server configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        data = await request.get_json()
        
        # Validate required fields
        required_fields = ["id", "name", "host", "port"]
        for field in required_fields:
            if field not in data:
                return jsonify({"status": "error", "message": f"Field '{field}' is required"}), 400
        
        # Add server
        success = config_manager.add_mcp_server(data, user_uuid)
        
        if success:
            app_logger.info(f"Created MCP server: {data.get('name')} (ID: {data.get('id')})")
            return jsonify({
                "status": "success",
                "message": "MCP server created successfully",
                "server_id": data.get("id")
            }), 201
        else:
            return jsonify({"status": "error", "message": "Failed to create MCP server"}), 500
            
    except Exception as e:
        app_logger.error(f"Error creating MCP server: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/mcp/servers/<server_id>", methods=["PUT"])
async def update_mcp_server(server_id: str):
    """Update an existing MCP server configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        data = await request.get_json()
        
        # Don't allow changing the ID
        if "id" in data and data["id"] != server_id:
            return jsonify({"status": "error", "message": "Cannot change server ID"}), 400
        
        success = config_manager.update_mcp_server(server_id, data, user_uuid)
        
        if success:
            app_logger.info(f"Updated MCP server: {server_id}")
            return jsonify({
                "status": "success",
                "message": "MCP server updated successfully"
            }), 200
        else:
            return jsonify({"status": "error", "message": "MCP server not found"}), 404
            
    except Exception as e:
        app_logger.error(f"Error updating MCP server: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/mcp/servers/<server_id>", methods=["DELETE"])
async def delete_mcp_server(server_id: str):
    """Delete an MCP server configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        # Try to remove the server (will fail if collections are assigned)
        success, error_message = config_manager.remove_mcp_server(server_id, user_uuid)
        
        if not success:
            return jsonify({
                "status": "error", 
                "message": error_message or "Failed to delete MCP server"
            }), 400
        
        # Check if this was the active server and clear it
        active_server_id = config_manager.get_active_mcp_server_id(user_uuid)
        if active_server_id == server_id:
            config_manager.set_active_mcp_server_id(None, user_uuid)
        
        app_logger.info(f"Deleted MCP server: {server_id}")
        return jsonify({
            "status": "success",
            "message": "MCP server deleted successfully"
        }), 200
            
    except Exception as e:
        app_logger.error(f"Error deleting MCP server: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/mcp/servers/<server_id>/activate", methods=["POST"])
async def activate_mcp_server(server_id: str):
    """Set an MCP server as the active server."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        # Verify server exists
        servers = config_manager.get_mcp_servers(user_uuid)
        server = next((s for s in servers if s.get("id") == server_id), None)
        
        if not server:
            return jsonify({"status": "error", "message": "MCP server not found"}), 404
        
        success = config_manager.set_active_mcp_server_id(server_id, user_uuid)
        
        if success:
            app_logger.info(f"Activated MCP server: {server_id}")
            return jsonify({
                "status": "success",
                "message": "MCP server activated successfully"
            }), 200
        else:
            return jsonify({"status": "error", "message": "Failed to activate MCP server"}), 500
            
    except Exception as e:
        app_logger.error(f"Error activating MCP server: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@rest_api_bp.route("/v1/mcp/resources", methods=["POST"])
async def get_mcp_resources_for_server():
    """
    Gets the tools and prompts for a specific MCP server configuration
    without requiring the application to be globally configured with it.
    """
    data = await request.get_json()
    if not data or not all(k in data for k in ["name", "host", "port", "path"]):
        return jsonify({"status": "error", "message": "Missing required MCP server details"}), 400

    server_name = data["name"]
    
    try:
        mcp_server_url = f"http://{data['host']}:{data['port']}{data['path']}"
        temp_server_configs = {server_name: {"url": mcp_server_url, "transport": "streamable_http"}}
        temp_mcp_client = MultiServerMCPClient(temp_server_configs)
        
        async with temp_mcp_client.session(server_name) as temp_session:
            tools_result = await temp_session.list_tools()
            prompts_result = await temp_session.list_prompts()
        
        structured_tools = {}
        for tool in tools_result.tools:
            category = "General"  # Fallback category
            if hasattr(tool, 'metadata') and tool.metadata:
                category = tool.metadata.get("category", "General")

            if category not in structured_tools:
                structured_tools[category] = []
            structured_tools[category].append({"name": tool.name, "description": tool.description, "disabled": False})

        structured_prompts = {}
        for prompt in prompts_result.prompts:
            category = "General"
            description = ""
            arguments = []
            if hasattr(prompt, 'metadata') and prompt.metadata:
                category = prompt.metadata.get("category", "General")
                description = prompt.metadata.get("description", "")
                arguments = prompt.metadata.get("arguments", [])

            if category not in structured_prompts:
                structured_prompts[category] = []
            structured_prompts[category].append({
                "name": prompt.name,
                "description": description,
                "arguments": arguments,
                "disabled": False
            })

        return jsonify({
            "status": "success",
            "tools": structured_tools,
            "prompts": structured_prompts
        }), 200

    except Exception as e:
        app_logger.error(f"Error fetching resources for server {server_name}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# LLM CONFIGURATION ENDPOINTS
# ============================================================================

@rest_api_bp.route("/v1/llm/configurations", methods=["GET"])
async def get_llm_configurations():
    """Get all LLM configurations."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        configurations = config_manager.get_llm_configurations(user_uuid)
        active_config_id = config_manager.get_active_llm_configuration_id(user_uuid)
        
        return jsonify({
            "status": "success",
            "configurations": configurations,
            "active_configuration_id": active_config_id
        }), 200
    except Exception as e:
        app_logger.error(f"Error getting LLM configurations: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/llm/configurations", methods=["POST"])
async def create_llm_configuration():
    """Create a new LLM configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.auth import encryption
        from trusted_data_agent.auth.admin import get_current_user_from_request
        config_manager = get_config_manager()
        
        data = await request.get_json()
        
        # Validate required fields
        if not all(k in data for k in ["id", "provider", "name", "model", "credentials"]):
            return jsonify({
                "status": "error",
                "message": "Missing required fields: id, provider, name, model, credentials"
            }), 400
        
        # Validate name uniqueness
        configurations = config_manager.get_llm_configurations(user_uuid)
        if any(c.get("name") == data["name"] for c in configurations):
            return jsonify({
                "status": "error",
                "message": f"Configuration name '{data['name']}' is already in use."
            }), 400
        
        # Validate ID uniqueness
        if any(c.get("id") == data["id"] for c in configurations):
            return jsonify({
                "status": "error",
                "message": "Configuration ID already exists."
            }), 400
        
        # In auth mode, store credentials encrypted in database
        credentials = data.get("credentials", {})
        provider = data.get("provider")
        
        # Get current user for encryption (needs user.id, not user_uuid)
        current_user = get_current_user_from_request()
        app_logger.info(f"Creating LLM config - current_user: {current_user}, has_credentials: {bool(credentials)}")
        
        if not current_user:
            app_logger.error("No authenticated user - cannot create LLM configuration with credentials")
            return jsonify({
                "status": "error",
                "message": "Authentication required to store LLM credentials"
            }), 401
        
        if credentials:
            # Encrypt credentials in database
            app_logger.info(f"Encrypting credentials for provider {provider}, user {current_user.username} (id={current_user.id})")
            encryption.encrypt_credentials(current_user.id, provider, credentials)
            app_logger.info(f"Successfully encrypted credentials for provider {provider}")
            
            # Remove credentials from config data (they're in encrypted storage now)
            data_without_creds = {k: v for k, v in data.items() if k != "credentials"}
            data_without_creds["credentials"] = {}  # Store empty dict in config
            success = config_manager.add_llm_configuration(data_without_creds, user_uuid)
        else:
            # No credentials provided - store config without credentials
            app_logger.info("No credentials provided - storing config without credentials")
            success = config_manager.add_llm_configuration(data, user_uuid)
        
        if success:
            app_logger.info(f"Created LLM configuration: {data['name']}")
            return jsonify({
                "status": "success",
                "message": "LLM configuration created successfully",
                "configuration": data
            }), 201
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to create LLM configuration"
            }), 500
            
    except Exception as e:
        app_logger.error(f"Error creating LLM configuration: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/llm/configurations/<config_id>", methods=["GET"])
async def get_llm_configuration(config_id: str):
    """Get a single LLM configuration with decrypted credentials (for editing)."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.auth import encryption
        from trusted_data_agent.auth.admin import get_current_user_from_request
        config_manager = get_config_manager()
        
        # Find the configuration
        configurations = config_manager.get_llm_configurations(user_uuid)
        config = next((c for c in configurations if c.get("id") == config_id), None)
        
        if not config:
            return jsonify({
                "status": "error",
                "message": "LLM configuration not found"
            }), 404
        
        # Decrypt credentials if available
        provider = config.get("provider")
        if provider:
            current_user = get_current_user_from_request()
            if current_user:
                try:
                    app_logger.info(f"Retrieving credentials for provider {provider}, user {current_user.username} (id={current_user.id})")
                    credentials = encryption.decrypt_credentials(current_user.id, provider)
                    if credentials:
                        # Add decrypted credentials to config
                        config = config.copy()  # Don't modify the original
                        config["credentials"] = credentials
                        app_logger.info(f"Successfully decrypted credentials for provider {provider}")
                    else:
                        app_logger.warning(f"No encrypted credentials found for provider {provider}")
                        config["credentials"] = {}
                except Exception as e:
                    app_logger.error(f"Error decrypting credentials: {e}", exc_info=True)
                    config["credentials"] = {}
            else:
                app_logger.warning("No authenticated user - cannot decrypt credentials")
                config["credentials"] = {}
        
        return jsonify({
            "status": "success",
            "configuration": config
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error getting LLM configuration: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/llm/configurations/<config_id>", methods=["PUT"])
async def update_llm_configuration(config_id: str):
    """Update an existing LLM configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.auth import encryption
        from trusted_data_agent.auth.admin import get_current_user_from_request
        config_manager = get_config_manager()
        
        data = await request.get_json()
        
        # If name is being updated, check uniqueness
        if "name" in data:
            configurations = config_manager.get_llm_configurations(user_uuid)
            if any(c.get("name") == data["name"] and c.get("id") != config_id for c in configurations):
                return jsonify({
                    "status": "error",
                    "message": f"Configuration name '{data['name']}' is already in use."
                }), 400
        
        # In auth mode, store credentials encrypted in database
        if "credentials" in data and data["credentials"]:
            credentials = data["credentials"]
            
            # Get provider from existing config or from update data
            configurations = config_manager.get_llm_configurations(user_uuid)
            existing_config = next((c for c in configurations if c.get("id") == config_id), None)
            provider = data.get("provider") or (existing_config.get("provider") if existing_config else None)
            
            if provider:
                current_user = get_current_user_from_request()
                app_logger.info(f"Updating LLM config - current_user: {current_user}, provider: {provider}, has_credentials: {bool(credentials)}")
                
                if not current_user:
                    app_logger.error("No authenticated user - cannot update LLM configuration with credentials")
                    return jsonify({
                        "status": "error",
                        "message": "Authentication required to store LLM credentials"
                    }), 401
                
                # Encrypt credentials in database
                app_logger.info(f"Encrypting credentials for provider {provider}, user {current_user.username} (id={current_user.id})")
                encryption.encrypt_credentials(current_user.id, provider, credentials)
                app_logger.info(f"Successfully encrypted credentials for provider {provider}")
                
                # Remove credentials from update data (they're in encrypted storage now)
                data = {k: v for k, v in data.items() if k != "credentials"}
                data["credentials"] = {}  # Store empty dict in config
        
        success = config_manager.update_llm_configuration(config_id, data, user_uuid)
        
        if success:
            app_logger.info(f"Updated LLM configuration: {config_id}")
            return jsonify({
                "status": "success",
                "message": "LLM configuration updated successfully"
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "LLM configuration not found"
            }), 404
            
    except Exception as e:
        app_logger.error(f"Error updating LLM configuration: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/llm/configurations/<config_id>", methods=["DELETE"])
async def delete_llm_configuration(config_id: str):
    """Delete an LLM configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        success, error_message = config_manager.remove_llm_configuration(config_id, user_uuid)
        
        if success:
            app_logger.info(f"Deleted LLM configuration: {config_id}")
            return jsonify({
                "status": "success",
                "message": "LLM configuration deleted successfully"
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": error_message or "Failed to delete LLM configuration"
            }), 400 if error_message and "assigned" in error_message else 404
            
    except Exception as e:
        app_logger.error(f"Error deleting LLM configuration: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/llm/configurations/<config_id>/activate", methods=["POST"])
async def activate_llm_configuration(config_id: str):
    """Set an LLM configuration as the active configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        # Verify configuration exists
        configurations = config_manager.get_llm_configurations(user_uuid)
        configuration = next((c for c in configurations if c.get("id") == config_id), None)
        
        if not configuration:
            return jsonify({"status": "error", "message": "LLM configuration not found"}), 404
        
        success = config_manager.set_active_llm_configuration_id(config_id, user_uuid)
        
        if success:
            app_logger.info(f"Activated LLM configuration: {config_id}")
            return jsonify({
                "status": "success",
                "message": "LLM configuration activated successfully"
            }), 200
        else:
            return jsonify({"status": "error", "message": "Failed to activate LLM configuration"}), 500
            
    except Exception as e:
        app_logger.error(f"Error activating LLM configuration: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# PROFILE CONFIGURATION ENDPOINTS
# ============================================================================

@rest_api_bp.route("/v1/profiles", methods=["GET"])
async def get_profiles():
    """Get all profile configurations."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core.provider_colors import get_provider_color, get_provider_from_llm_config
        config_manager = get_config_manager()
        
        profiles = config_manager.get_profiles(user_uuid)
        default_profile_id = config_manager.get_default_profile_id(user_uuid)
        active_for_consumption_profile_ids = config_manager.get_active_for_consumption_profile_ids(user_uuid)
        
        # Enrich profiles with color information based on provider
        llm_configurations = config_manager.get_llm_configurations(user_uuid)
        for profile in profiles:
            llm_config_id = profile.get("llmConfigurationId")
            if llm_config_id:
                llm_config = next((c for c in llm_configurations if c.get("id") == llm_config_id), None)
                if llm_config:
                    provider = get_provider_from_llm_config(llm_config)
                    colors = get_provider_color(provider)
                    profile["color"] = colors["primary"]
                    profile["colorSecondary"] = colors["secondary"]
                    profile["providerName"] = colors["name"]
        
        return jsonify({
            "status": "success",
            "profiles": profiles,
            "default_profile_id": default_profile_id,
            "active_for_consumption_profile_ids": active_for_consumption_profile_ids
        }), 200
    except Exception as e:
        app_logger.error(f"Error getting profiles: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
        
        
@rest_api_bp.route("/v1/profiles", methods=["POST"])
async def create_profile():
    """Create a new profile configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        data = await request.get_json()
        
        # Validate tag uniqueness
        tag = data.get("tag")
        if tag:
            profiles = config_manager.get_profiles(user_uuid)
            if any(p.get("tag") == tag for p in profiles):
                return jsonify({"status": "error", "message": f"Tag '{tag}' is already in use."}), 400

        # Add a unique ID if not provided
        if "id" not in data:
            data["id"] = f"profile-{uuid.uuid4()}"
        
        # Validate and set classification mode
        classification_mode = data.get("classification_mode", "light")
        if classification_mode not in ["light", "full"]:
            return jsonify({
                "status": "error", 
                "message": f"Invalid classification_mode: '{classification_mode}'. Must be 'light' or 'full'."
            }), 400
        data["classification_mode"] = classification_mode
        
        # Initialize empty classification results (will be populated on first classification)
        if "classification_results" not in data:
            data["classification_results"] = {
                "tools": {},
                "prompts": {},
                "resources": {},
                "last_classified": None,
                "classified_with_mode": None
            }
        
        # New profiles don't need reclassification warning - they've never been classified
        # The flag will be set automatically when provider configuration changes after first classification
        
        success = config_manager.add_profile(data, user_uuid)
        
        if success:
            app_logger.info(f"Created profile with tag: {data.get('tag')} (ID: {data.get('id')})")
            
            return jsonify({
                "status": "success",
                "message": "Profile created successfully",
                "profile": data
            }), 201
        else:
            return jsonify({"status": "error", "message": "Failed to create profile"}), 500
            
    except Exception as e:
        app_logger.error(f"Error creating profile: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@rest_api_bp.route("/v1/profiles/<profile_id>/activate", methods=["POST"])
async def activate_profile(profile_id: str):
    """
    Activate a profile, switching the runtime context to use its configuration and classification.
    This loads the profile's LLM settings, MCP servers, and classification results.
    Requires all profile tests to pass before activation.
    """
    user_uuid = _get_user_uuid_from_request()
    from trusted_data_agent.core import configuration_service
    from trusted_data_agent.core.config_manager import ConfigManager
    
    try:
        # Check if profile needs reclassification
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        profile = config_manager.get_profile(profile_id, user_uuid)
        
        if not profile:
            return jsonify({
                "status": "error",
                "message": f"Profile '{profile_id}' not found"
            }), 404
        
        # Run tests before activation
        test_results = {}
        all_tests_passed = True
        
        # Test LLM configuration
        try:
            llm_config_id = profile.get("llmConfigurationId")
            if llm_config_id:
                llm_configs = config_manager.get_llm_configurations(user_uuid)
                llm_config = next((cfg for cfg in llm_configs if cfg.get("id") == llm_config_id), None)
                
                if llm_config:
                    from trusted_data_agent.llm.llm_factory import LLMFactory
                    llm_instance = LLMFactory.create_llm(llm_config)
                    response = await llm_instance.ainvoke("Say 'OK' if you can read this.")
                    test_results["llm"] = {"status": "success", "message": "LLM connection successful."}
                else:
                    test_results["llm"] = {"status": "error", "message": "LLM configuration not found."}
                    all_tests_passed = False
            else:
                test_results["llm"] = {"status": "error", "message": "No LLM configuration specified."}
                all_tests_passed = False
        except Exception as llm_error:
            test_results["llm"] = {"status": "error", "message": f"LLM connection failed: {str(llm_error)}"}
            all_tests_passed = False
        
        # Test MCP server
        try:
            mcp_server_id = profile.get("mcpServerId")
            if mcp_server_id:
                mcp_servers = config_manager.get_mcp_servers(user_uuid)
                mcp_server = next((srv for srv in mcp_servers if srv.get("id") == mcp_server_id), None)
                
                if mcp_server:
                    test_results["mcp_server"] = {"status": "success", "message": f"MCP server configured: {mcp_server.get('name', 'Unknown')}"}
                else:
                    test_results["mcp_server"] = {"status": "error", "message": "MCP server not found."}
                    all_tests_passed = False
            else:
                test_results["mcp_server"] = {"status": "error", "message": "No MCP server specified."}
                all_tests_passed = False
        except Exception as mcp_error:
            test_results["mcp_server"] = {"status": "error", "message": f"MCP test failed: {str(mcp_error)}"}
            all_tests_passed = False
        
        # Test RAG collections (check database, not ChromaDB)
        try:
            from trusted_data_agent.core.collection_db import get_collection_db
            collection_db = get_collection_db()
            user_collections = collection_db.get_all_collections(user_id=user_uuid)
            
            if user_collections and len(user_collections) > 0:
                test_results["rag_collections"] = {"status": "success", "message": f"RAG collections available ({len(user_collections)} collection(s))."}
            else:
                test_results["rag_collections"] = {"status": "warning", "message": "No RAG collections configured. A Default Collection will be created on first use."}
                # Warning doesn't fail activation
        except Exception as rag_error:
            test_results["rag_collections"] = {"status": "warning", "message": f"RAG test skipped: {str(rag_error)}"}
            # Don't fail activation for RAG issues
        
        # If tests failed, return error
        if not all_tests_passed:
            return jsonify({
                "status": "error",
                "message": "Profile tests failed. Cannot activate profile.",
                "test_results": test_results
            }), 400
        
        # If profile needs reclassification, return a special status
        if profile.get("needs_reclassification", False):
            result = await configuration_service.switch_profile_context(profile_id, user_uuid)
            
            if result["status"] == "success":
                # Add warning about reclassification
                result["needs_reclassification"] = True
                result["warning"] = "This profile has changes that require reclassification for optimal categorization."
                result["test_results"] = test_results
                return jsonify(result), 200
            else:
                return jsonify(result), 400
        
        # Normal activation flow
        result = await configuration_service.switch_profile_context(profile_id, user_uuid)
        
        if result["status"] == "success":
            result["test_results"] = test_results
            return jsonify(result), 200
        else:
            return jsonify(result), 400
    
    except Exception as e:
        app_logger.error(f"Failed to activate profile {profile_id}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Profile activation failed: {str(e)}"
        }), 500


@rest_api_bp.route("/v1/profiles/<profile_id>/classification", methods=["GET"])
async def get_profile_classification(profile_id: str):
    """
    Get the classification results for a specific profile.
    Returns the cached classification structure (tools, prompts, resources).
    """
    user_uuid = _get_user_uuid_from_request()
    from trusted_data_agent.core.config_manager import get_config_manager
    config_manager = get_config_manager()
    
    # Verify profile exists and belongs to user
    profile = config_manager.get_profile(profile_id, user_uuid)
    if not profile:
        return jsonify({
            "status": "error",
            "message": f"Profile '{profile_id}' not found"
        }), 404
    
    # Get classification results
    classification_results = config_manager.get_profile_classification(profile_id, user_uuid)
    classification_mode = profile.get('classification_mode', 'light')
    
    # Log what we're returning
    tool_count = sum(len(tools) for tools in classification_results.get('tools', {}).values())
    prompt_count = sum(len(prompts) for prompts in classification_results.get('prompts', {}).values())
    app_logger.info(f"Returning classification for profile {profile_id}: {len(classification_results.get('tools', {}))} tool categories with {tool_count} tools, {len(classification_results.get('prompts', {}))} prompt categories with {prompt_count} prompts")
    
    return jsonify({
        "status": "success",
        "profile_id": profile_id,
        "classification_mode": classification_mode,
        "classification_results": classification_results
    }), 200


@rest_api_bp.route("/v1/profiles/<profile_id>/reclassify", methods=["POST"])
async def reclassify_profile(profile_id: str):
    """
    Force reclassification of MCP resources for a specific profile.
    This clears cached results and re-runs classification using the profile's LLM and mode.
    Initializes temporary LLM and MCP clients for classification if not already present.
    """
    user_uuid = _get_user_uuid_from_request()
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.auth.admin import get_current_user_from_request
    
    config_manager = get_config_manager()
    
    # Get current user for credential lookup (when auth is enabled)
    current_user = get_current_user_from_request()
    user_id_for_creds = current_user.id if current_user else user_uuid
    
    # Verify profile exists and belongs to user
    profile = config_manager.get_profile(profile_id, user_uuid)
    if not profile:
        return jsonify({
            "status": "error",
            "message": f"Profile '{profile_id}' not found"
        }), 404
    
    # Check if this profile is active for consumption
    active_profiles = config_manager.get_active_for_consumption_profile_ids(user_uuid)
    is_active_for_consumption = profile_id in active_profiles
    
    if not is_active_for_consumption:
        # For inactive profiles, just clear the cache
        config_manager.clear_profile_classification(profile_id, user_uuid)
        return jsonify({
            "status": "success",
            "message": "Classification cache cleared. Profile must be active for classification to run.",
            "profile_id": profile_id,
            "note": "Activate the profile to run classification."
        }), 200
    
    # Profile is active - need to run classification
    app_logger.info(f"Profile {profile_id} is active for consumption, running reclassification now")
    
    # Store original state
    original_llm = APP_STATE.get('llm')
    original_mcp_client = APP_STATE.get('mcp_client')
    original_profile_id = APP_CONFIG.CURRENT_PROFILE_ID
    temp_llm_instance = None
    temp_mcp_client = None
    
    try:
        # Clear existing classification
        config_manager.clear_profile_classification(profile_id, user_uuid)
        app_logger.info(f"Cleared classification cache for profile {profile_id}")
        
        # Initialize temporary clients if needed
        from trusted_data_agent.llm.client_factory import create_llm_client
        
        # Authentication is always enabled - encryption always available
        ENCRYPTION_AVAILABLE = True
        
        # Get LLM configuration from profile
        llm_config_id = profile.get('llmConfigurationId')
        if not llm_config_id:
            return jsonify({
                "status": "error",
                "message": "Profile has no LLM configuration selected"
            }), 400
        
        # Look up the actual LLM configuration
        llm_config = next((c for c in config_manager.get_llm_configurations(user_uuid) 
                          if c.get("id") == llm_config_id), None)
        
        if not llm_config:
            return jsonify({
                "status": "error",
                "message": f"LLM configuration '{llm_config_id}' not found"
            }), 404
        
        provider = llm_config.get('provider')
        model = llm_config.get('model')
        
        if not provider or not model:
            return jsonify({
                "status": "error",
                "message": "LLM configuration incomplete (missing provider or model)"
            }), 400
        
        # Get credentials (decrypt if needed)
        credentials = None
        app_logger.info(f"Attempting to retrieve credentials for {provider}")
        app_logger.info(f"  ENCRYPTION_AVAILABLE: {ENCRYPTION_AVAILABLE}")
        app_logger.info(f"  user_id_for_creds: {user_id_for_creds}")
        app_logger.info(f"  current_user: {current_user}")
        
        if ENCRYPTION_AVAILABLE and user_id_for_creds:
            try:
                from trusted_data_agent.auth import encryption
                app_logger.info(f"Attempting to decrypt credentials for user_id={user_id_for_creds}, provider={provider}")
                credentials = encryption.decrypt_credentials(user_id_for_creds, provider)
                if credentials:
                    app_logger.info(f"Successfully loaded encrypted credentials for {provider}")
                else:
                    app_logger.warning(f"decrypt_credentials returned None for {provider}")
            except Exception as e:
                app_logger.warning(f"Could not load encrypted credentials: {e}", exc_info=True)
        else:
            app_logger.warning(f"Skipping encryption: ENCRYPTION_AVAILABLE={ENCRYPTION_AVAILABLE}, user_id_for_creds={user_id_for_creds}")
        
        # Fall back to credentials in config if not found via encryption
        if not credentials:
            credentials = llm_config.get('credentials', {})
            if credentials:
                app_logger.info(f"Using credentials from LLM configuration")
            else:
                app_logger.warning(f"No credentials available for {provider}")
                app_logger.warning(f"  LLM config keys: {list(llm_config.keys())}")
                return jsonify({
                    "status": "error",
                    "message": f"No credentials available for {provider}. Credentials must be stored in the encrypted database. Please save your LLM configuration credentials first."
                }), 400
        
        # Create temporary LLM client
        app_logger.info(f"Creating temporary LLM client for {provider}/{model}")
        temp_llm_instance = await create_llm_client(provider, model, credentials)
        
        # Get MCP configuration from profile
        mcp_server_id = profile.get('mcpServerId')
        if not mcp_server_id:
            return jsonify({
                "status": "error",
                "message": "Profile has no MCP server selected"
            }), 400
        
        # Look up the actual MCP server configuration
        mcp_server = next((s for s in config_manager.get_mcp_servers(user_uuid) 
                          if s.get("id") == mcp_server_id), None)
        
        if not mcp_server:
            return jsonify({
                "status": "error",
                "message": f"MCP server '{mcp_server_id}' not found"
            }), 404
        
        server_name = mcp_server.get('name')
        server_host = mcp_server.get('host')
        server_port = mcp_server.get('port')
        server_path = mcp_server.get('path')
        
        if not all([server_name, server_host, server_port, server_path]):
            return jsonify({
                "status": "error",
                "message": "MCP server configuration incomplete (missing name, host, port, or path)"
            }), 400
        
        # Build MCP server config for MultiServerMCPClient
        mcp_server_url = f"http://{server_host}:{server_port}{server_path}"
        server_config = {"url": mcp_server_url, "transport": "streamable_http"}
        
        app_logger.info(f"Creating temporary MCP client for server {server_name} at {mcp_server_url}")
        temp_mcp_client = MultiServerMCPClient({server_name: server_config})
        
        # Set temporary clients in APP_STATE
        APP_STATE['llm'] = temp_llm_instance
        APP_STATE['mcp_client'] = temp_mcp_client
        
        # Set provider and model in config so call_llm_api can use them
        from trusted_data_agent.core.config import (
            set_user_mcp_server_name, set_user_mcp_server_id,
            set_user_provider, set_user_model
        )
        set_user_provider(provider, user_uuid)
        set_user_model(model, user_uuid)
        set_user_mcp_server_name(server_name, user_uuid)
        set_user_mcp_server_id(mcp_server_id, user_uuid)
        
        # Now run classification via switch_profile_context
        from trusted_data_agent.core import configuration_service
        result = await configuration_service.switch_profile_context(profile_id, user_uuid)
        
        if result["status"] == "success":
            # Get updated results
            classification_results = config_manager.get_profile_classification(profile_id, user_uuid)
            
            return jsonify({
                "status": "success",
                "message": "Profile reclassified successfully",
                "profile_id": profile_id,
                "classification_results": classification_results
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": f"Classification failed: {result.get('message', 'Unknown error')}"
            }), 500
            
    except Exception as e:
        app_logger.error(f"Error during reclassification: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Reclassification failed: {str(e)}"
        }), 500
        
    finally:
        # Restore original state
        APP_STATE['llm'] = original_llm
        APP_STATE['mcp_client'] = original_mcp_client
        
        # Clean up temporary MCP client
        if temp_mcp_client:
            try:
                if hasattr(temp_mcp_client, 'cleanup'):
                    await temp_mcp_client.cleanup()
            except Exception as cleanup_error:
                app_logger.warning(f"Error cleaning up temporary MCP client: {cleanup_error}")
        
        # Switch back to original profile if needed
        if original_profile_id and original_profile_id != profile_id:
            app_logger.info(f"Switching back to original profile {original_profile_id}")
            try:
                await configuration_service.switch_profile_context(original_profile_id, user_uuid)
            except Exception as switch_error:
                app_logger.warning(f"Error switching back to original profile: {switch_error}")


@rest_api_bp.route("/v1/profiles/<profile_id>", methods=["PUT"])
async def update_profile(profile_id: str):
    """Update an existing profile configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core.config import APP_STATE
        config_manager = get_config_manager()
        
        data = await request.get_json()
        
        # Don't allow changing the ID
        if "id" in data and data["id"] != profile_id:
            return jsonify({"status": "error", "message": "Cannot change profile ID"}), 400

        # Get current profile to detect changes
        current_profile = config_manager.get_profiles(user_uuid)
        current_profile = next((p for p in current_profile if p.get("id") == profile_id), None)
        
        if not current_profile:
            return jsonify({"status": "error", "message": f"Profile '{profile_id}' not found"}), 404
        
        # Track if reclassification is needed
        # Only flag reclassification when provider configuration changes AND profile was previously classified
        # New/never-classified profiles should not show reclassification warning
        needs_reclassification = False
        
        # Check if this profile has ever been classified
        classification_results = current_profile.get("classification_results", {})
        was_previously_classified = classification_results.get("last_classified") is not None
        
        # Validate classification_mode if provided
        if "classification_mode" in data:
            if data["classification_mode"] not in ["light", "full"]:
                return jsonify({
                    "status": "error", 
                    "message": f"Invalid classification_mode: '{data['classification_mode']}'. Must be 'light' or 'full'."
                }), 400
            
            # If classification mode is changing, clear cached results and flag for reclassification
            if current_profile.get("classification_mode") != data["classification_mode"]:
                data["classification_results"] = {
                    "tools": {},
                    "prompts": {},
                    "resources": {},
                    "last_classified": None,
                    "classified_with_mode": None
                }
                # Only flag if profile was previously classified
                if was_previously_classified:
                    needs_reclassification = True
                    app_logger.info(f"Classification mode changed for profile {profile_id}, clearing cached results")
                else:
                    app_logger.info(f"Classification mode changed for never-classified profile {profile_id}, no reclassification flag needed")
        
        # Check if MCP server changed (affects available tools/prompts)
        if "mcpServerId" in data:
            current_server = current_profile.get("mcpServerId")
            new_server = data["mcpServerId"]
            if current_server != new_server and was_previously_classified:
                needs_reclassification = True
                app_logger.info(f"MCP server changed for profile {profile_id}, reclassification needed")
        
        # Check if MCP servers changed (legacy field - affects available tools/prompts)
        if "mcp_servers" in data:
            current_servers = current_profile.get("mcp_servers", [])
            new_servers = data["mcp_servers"]
            if current_servers != new_servers and was_previously_classified:
                needs_reclassification = True
                app_logger.info(f"MCP servers changed for profile {profile_id}, reclassification needed")
        
        # Check if LLM configuration changed (affects full mode categorization)
        if "llmConfigurationId" in data:
            current_llm_config = current_profile.get("llmConfigurationId")
            new_llm_config = data["llmConfigurationId"]
            if current_llm_config != new_llm_config and current_profile.get("classification_mode") == "full" and was_previously_classified:
                needs_reclassification = True
                app_logger.info(f"LLM configuration changed for profile {profile_id} (full mode), reclassification recommended")
        
        # Check if LLM provider/model changed (legacy fields - affects full mode categorization)
        if "llm_provider" in data or "llm_model" in data:
            provider_changed = "llm_provider" in data and current_profile.get("llm_provider") != data["llm_provider"]
            model_changed = "llm_model" in data and current_profile.get("llm_model") != data["llm_model"]
            if (provider_changed or model_changed) and current_profile.get("classification_mode") == "full" and was_previously_classified:
                needs_reclassification = True
                app_logger.info(f"LLM configuration changed for profile {profile_id} (full mode), reclassification recommended")
        
        # Set the reclassification flag
        if needs_reclassification:
            data["needs_reclassification"] = True

        # Validate tag uniqueness if tag is being changed
        tag = data.get("tag")
        if tag:
            profiles = config_manager.get_profiles(user_uuid)
            if any(p.get("tag") == tag and p.get("id") != profile_id for p in profiles):
                return jsonify({"status": "error", "message": f"Tag '{tag}' is already in use."}), 400

        # Check if this profile is currently active for consumption
        active_profile_ids = config_manager.get_active_for_consumption_profile_ids(user_uuid)
        is_active = profile_id in active_profile_ids
        
        success = config_manager.update_profile(profile_id, data, user_uuid)
        
        if success:
            app_logger.info(f"Updated profile: {profile_id}")
            
            # If this profile is active for consumption, update APP_STATE
            if is_active and active_profile_ids:
                primary_profile_id = active_profile_ids[0]
                APP_STATE["disabled_tools"] = config_manager.get_profile_disabled_tools(primary_profile_id, user_uuid)
                APP_STATE["disabled_prompts"] = config_manager.get_profile_disabled_prompts(primary_profile_id, user_uuid)
                
                app_logger.info(f"Profile {profile_id} is active - updated APP_STATE with {len(APP_STATE['disabled_tools'])} disabled tools and {len(APP_STATE['disabled_prompts'])} disabled prompts")
                
                # Regenerate contexts to reflect the updated disabled lists
                from trusted_data_agent.core.utils import _regenerate_contexts
                _regenerate_contexts()
            
            return jsonify({
                "status": "success",
                "message": "Profile updated successfully"
            }), 200
        else:
            return jsonify({"status": "error", "message": "Profile not found"}), 404
            
    except Exception as e:
        app_logger.error(f"Error updating profile: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@rest_api_bp.route("/v1/profiles/<profile_id>", methods=["DELETE"])
async def delete_profile(profile_id: str):
    """Delete a profile configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        success = config_manager.remove_profile(profile_id, user_uuid)
        
        if not success:
            return jsonify({
                "status": "error", 
                "message": "Profile not found"
            }), 404
        
        # Check if this profile was in the active list and remove it
        active_profile_ids = config_manager.get_active_for_consumption_profile_ids(user_uuid)
        if profile_id in active_profile_ids:
            active_profile_ids = [pid for pid in active_profile_ids if pid != profile_id]
            config_manager.set_active_for_consumption_profile_ids(active_profile_ids, user_uuid)
            app_logger.info(f"Removed deleted profile {profile_id} from active profiles list")
        
        app_logger.info(f"Deleted profile: {profile_id}")
        
        return jsonify({
            "status": "success",
            "message": "Profile deleted successfully"
        }), 200
            
    except Exception as e:
        app_logger.error(f"Error deleting profile: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@rest_api_bp.route("/v1/profiles/<profile_id>/set_default", methods=["POST"])
async def set_default_profile(profile_id: str):
    """Set a profile as the default profile."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        
        # Verify profile exists
        profiles = config_manager.get_profiles(user_uuid)
        profile = next((p for p in profiles if p.get("id") == profile_id), None)
        
        if not profile:
            return jsonify({"status": "error", "message": "Profile not found"}), 404
        
        success = config_manager.set_default_profile_id(profile_id, user_uuid)
        
        if success:
            app_logger.info(f"Set default profile: {profile_id}")
            
            return jsonify({
                "status": "success",
                "message": "Default profile set successfully"
            }), 200
        else:
            return jsonify({"status": "error", "message": "Failed to set default profile"}), 500
            
    except Exception as e:
        app_logger.error(f"Error setting default profile: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@rest_api_bp.route("/v1/profiles/set_active_for_consumption", methods=["POST"])
async def set_active_for_consumption_profiles():
    """Set the list of profiles active for consumption and update APP_STATE with enabled/disabled lists."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core.config import APP_STATE
        config_manager = get_config_manager()
        
        data = await request.get_json()
        profile_ids = data.get("profile_ids", [])
        
        success = config_manager.set_active_for_consumption_profile_ids(profile_ids, user_uuid)
        
        if success and profile_ids:
            # Update APP_STATE with disabled lists from the first active profile
            # (For simplicity, we use the first profile's settings)
            primary_profile_id = profile_ids[0]
            
            # Check if profile needs classification (either never classified or explicitly needs reclassification)
            from trusted_data_agent.core import configuration_service
            profile = config_manager.get_profile(primary_profile_id, user_uuid)
            
            if profile:
                # Check if classification is empty or missing
                classification_results = config_manager.get_profile_classification(primary_profile_id, user_uuid)
                tools_dict = classification_results.get('tools', {}) if classification_results else {}
                prompts_dict = classification_results.get('prompts', {}) if classification_results else {}
                total_tools = sum(len(tools) for tools in tools_dict.values()) if tools_dict else 0
                total_prompts = sum(len(prompts) for prompts in prompts_dict.values()) if prompts_dict else 0
                
                # Profile needs classification if it has no tools/prompts OR needs_reclassification flag is set
                needs_classification = (total_tools == 0 and total_prompts == 0) or profile.get('needs_reclassification', False)
                
                if needs_classification:
                    app_logger.info(f"Profile {primary_profile_id} needs classification, triggering context switch")
                    # Use switch_profile_context to trigger classification
                    result = await configuration_service.switch_profile_context(primary_profile_id, user_uuid)
                    if result["status"] != "success":
                        return jsonify(result), 400
            
            APP_STATE["disabled_tools"] = config_manager.get_profile_disabled_tools(primary_profile_id, user_uuid)
            APP_STATE["disabled_prompts"] = config_manager.get_profile_disabled_prompts(primary_profile_id, user_uuid)
            
            app_logger.info(f"Set active for consumption profiles: {profile_ids}")
            app_logger.info(f"Updated APP_STATE with {len(APP_STATE['disabled_tools'])} disabled tools and {len(APP_STATE['disabled_prompts'])} disabled prompts from profile {primary_profile_id}")
            
            # Regenerate contexts to reflect the new disabled lists
            from trusted_data_agent.core.utils import _regenerate_contexts
            _regenerate_contexts()
            
            return jsonify({
                "status": "success",
                "message": "Active for consumption profiles set successfully"
            }), 200
        elif success:
            # No active profiles - clear disabled lists
            APP_STATE["disabled_tools"] = []
            APP_STATE["disabled_prompts"] = []
            app_logger.info("Cleared active for consumption profiles and disabled lists")
            
            return jsonify({
                "status": "success",
                "message": "Active for consumption profiles cleared successfully"
            }), 200
        else:
            return jsonify({"status": "error", "message": "Failed to set active for consumption profiles"}), 500
            
    except Exception as e:
        app_logger.error(f"Error setting active for consumption profiles: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@rest_api_bp.route("/v1/profiles/<profile_id>/test", methods=["POST"])
async def test_profile(profile_id: str):
    """Test a profile's configuration."""
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.auth.admin import get_current_user_from_request
        
        config_manager = get_config_manager()
        
        # Get profile
        profiles = config_manager.get_profiles(user_uuid)
        profile = next((p for p in profiles if p.get("id") == profile_id), None)
        if not profile:
            return jsonify({"status": "error", "message": "Profile not found"}), 404
        
        # Get current user for credential lookup
        current_user = get_current_user_from_request()
        user_id_for_creds = current_user.id if current_user else user_uuid

        results = {}

        # Test LLM connection - actually verify credentials work
        llm_config_id = profile.get("llmConfigurationId")
        if llm_config_id:
            try:
                # Get the LLM configuration
                llm_config = next((c for c in config_manager.get_llm_configurations(user_uuid) 
                                 if c.get("id") == llm_config_id), None)
                
                if llm_config:
                    # Use shared validation logic with proper user ID
                    success, message = await _validate_llm_credentials(llm_config, user_id_for_creds)
                    results["llm_connection"] = {
                        "status": "success" if success else "error",
                        "message": message
                    }
                else:
                    results["llm_connection"] = {"status": "error", "message": f"LLM configuration '{llm_config_id}' not found."}
                    
            except Exception as llm_error:
                results["llm_connection"] = {"status": "error", "message": f"LLM connection failed: {str(llm_error)}"}
        else:
            results["llm_connection"] = {"status": "error", "message": "No LLM configuration selected."}

        # Test MCP connection (skip for llm_only profiles)
        profile_type = profile.get("profile_type", "tool_enabled")
        if profile_type == "tool_enabled":
            mcp_server_id = profile.get("mcpServerId")
            if mcp_server_id:
                mcp_server = next((s for s in config_manager.get_mcp_servers(user_uuid)
                                 if s.get("id") == mcp_server_id), None)
                if mcp_server:
                    results["mcp_connection"] = {"status": "success", "message": f"MCP server configured: {mcp_server.get('name', 'Unknown')}."}
                else:
                    results["mcp_connection"] = {"status": "error", "message": f"MCP server '{mcp_server_id}' not found."}
            else:
                results["mcp_connection"] = {"status": "warning", "message": "No MCP server configured."}
        else:
            # LLM-only profile - MCP not required
            results["profile_type"] = {"status": "success", "message": "Conversation profile (LLM only - no tools required)."}

        # Test RAG collections (check database for user-accessible collections)
        try:
            from trusted_data_agent.core.collection_db import get_collection_db
            collection_db = get_collection_db()
            
            # Get collections accessible to this user
            user_collections = collection_db.get_all_collections(user_id=user_uuid)
            
            if user_collections and len(user_collections) > 0:
                results["rag_collections"] = {"status": "success", "message": f"RAG collections available ({len(user_collections)} collection(s))."}
            else:
                results["rag_collections"] = {"status": "warning", "message": "No RAG collections found."}
        except Exception as rag_error:
            results["rag_collections"] = {"status": "error", "message": f"RAG test failed: {str(rag_error)}"}

        return jsonify({"status": "success", "results": results}), 200

    except Exception as e:
        app_logger.error(f"Error testing profile: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# Helper function for LLM credential validation
async def _validate_llm_credentials(llm_config, user_id: str):
    """
    Validate LLM credentials by making a test API call.
    Returns tuple: (success: bool, message: str)
    """
    from trusted_data_agent.llm.client_factory import test_llm_credentials
    from trusted_data_agent.auth.encryption import decrypt_credentials
    
    llm_provider = llm_config.get("provider")
    llm_model = llm_config.get("model")
    
    # Get decrypted credentials from database
    credentials = decrypt_credentials(user_id, llm_provider)
    if not credentials:
        return False, f"No credentials found for {llm_provider}. Please configure credentials first."
    
    # Use shared test function from client_factory
    try:
        success, message = await test_llm_credentials(llm_provider, llm_model, credentials)
        if not success:
            app_logger.error(f"LLM credential validation failed: {message}")
        return success, message
    except Exception as e:
        error_msg = str(e)
        app_logger.error(f"LLM credential validation failed: {error_msg}", exc_info=True)
        return False, f"Validation failed: {error_msg}"

@rest_api_bp.route("/v1/llm_configurations/<config_id>/test", methods=["POST"])
async def test_llm_configuration(config_id: str):
    """
    Test an LLM configuration by making a simple API call to validate credentials.
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.auth.admin import get_current_user_from_request
        
        config_manager = get_config_manager()
        
        # Get the LLM configuration
        llm_config = next((c for c in config_manager.get_llm_configurations(user_uuid) 
                         if c.get("id") == config_id), None)
        
        if not llm_config:
            return jsonify({
                "status": "error",
                "message": "LLM configuration not found"
            }), 404
        
        # Get current user for credential lookup
        current_user = get_current_user_from_request()
        if not current_user:
            return jsonify({
                "status": "error",
                "message": "Authentication required"
            }), 401
        
        # Use shared validation logic with current_user.id
        success, message = await _validate_llm_credentials(llm_config, current_user.id)
        
        if success:
            return jsonify({"status": "success", "message": message}), 200
        else:
            return jsonify({"status": "error", "message": message}), 400
                
    except Exception as e:
        app_logger.error(f"LLM configuration test failed for {config_id}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"LLM connection failed: {str(e)}"
        }), 400
        
# ============================================================================
# EXECUTION DASHBOARD API ENDPOINTS
# ============================================================================
@rest_api_bp.route('/v1/sessions/analytics', methods=['GET'])
async def get_sessions_analytics():
    """
    Get comprehensive analytics across all sessions for the execution dashboard.
    Returns: total sessions, tokens, success rate, cost, velocity, model distribution, top champions
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        from pathlib import Path
        from trusted_data_agent.core.config import APP_CONFIG
        
        project_root = Path(__file__).resolve().parents[3]
        sessions_base = project_root / 'tda_sessions'
        
        # Determine which sessions to scan based on filter setting
        if APP_CONFIG.SESSIONS_FILTER_BY_USER:
            # User-specific mode
            sessions_root = sessions_base / user_uuid
            if not sessions_root.exists():
                return jsonify({
                    "total_sessions": 0,
                    "total_tokens": {"input": 0, "output": 0, "total": 0},
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "success_rate_percent": 0,
                    "estimated_cost_usd": 0,
                    "model_distribution": {},
                    "top_expensive_queries": [],
                    "top_expensive_questions": [],
                    "velocity_data": []
                }), 200
            scan_dirs = [sessions_root]
        else:
            # All users mode
            if not sessions_base.exists():
                return jsonify({
                    "total_sessions": 0,
                    "total_tokens": {"input": 0, "output": 0, "total": 0},
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "success_rate_percent": 0,
                    "estimated_cost_usd": 0,
                    "model_distribution": {},
                    "top_expensive_queries": [],
                    "top_expensive_questions": [],
                    "velocity_data": []
                }), 200
            scan_dirs = [d for d in sessions_base.iterdir() if d.is_dir()]
        
        # Initialize analytics
        total_sessions = 0
        total_input_tokens = 0
        total_output_tokens = 0
        successful_turns = 0
        total_turns = 0
        model_usage = {}
        sessions_by_hour = {}
        expensive_queries = []
        expensive_questions = []
        
        # RAG tracking
        rag_guided_turns = 0  # Turns where RAG provided champion case
        rag_guided_output_tokens = 0  # Output tokens in RAG-guided turns (measures plan quality)
        non_rag_output_tokens = 0  # Output tokens in non-RAG turns
        non_rag_turns = 0
        
        # Scan all session files from determined directories
        for session_dir in scan_dirs:
            for session_file in session_dir.glob('*.json'):
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                    
                    total_sessions += 1
                    total_input_tokens += session_data.get('input_tokens', 0)
                    total_output_tokens += session_data.get('output_tokens', 0)
                    
                    # Track model usage
                    models_used = session_data.get('models_used', [])
                    for model in models_used:
                        model_usage[model] = model_usage.get(model, 0) + 1
                    
                    # Analyze workflow history
                    workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', [])
                    for turn in workflow_history:
                        if turn.get('isValid', True):
                            total_turns += 1
                            # Simple success heuristic: has final_summary and no critical errors
                            if turn.get('final_summary'):
                                successful_turns += 1
                            
                            # Track RAG usage - focus on OUTPUT tokens (plan quality metric)
                            output_tokens = turn.get('turn_output_tokens', 0)
                            
                            # Check if this turn had RAG guidance (rag_source_collection_id is set when planner retrieves a champion case)
                            had_rag_guidance = turn.get('rag_source_collection_id') is not None
                            
                            if had_rag_guidance:
                                rag_guided_turns += 1
                                rag_guided_output_tokens += output_tokens
                            else:
                                non_rag_turns += 1
                                non_rag_output_tokens += output_tokens
                            
                            # Track expensive individual questions
                            user_query = turn.get('user_query', '')
                            turn_input_tokens = turn.get('turn_input_tokens', 0)
                            turn_output_tokens_val = turn.get('turn_output_tokens', 0)
                            turn_total_tokens = turn_input_tokens + turn_output_tokens_val
                            
                            if turn_total_tokens > 0 and user_query:
                                expensive_questions.append({
                                    "query": user_query[:60] + "..." if len(user_query) > 60 else user_query,
                                    "tokens": turn_total_tokens,
                                    "session_id": session_data.get('id', 'unknown')[:8]
                                })
                    
                    # Track expensive sessions (tokens are at session level, not turn level)
                    session_tokens = session_data.get('input_tokens', 0) + session_data.get('output_tokens', 0)
                    session_name = session_data.get('name', 'Unnamed Session')
                    
                    if session_tokens > 0:
                        expensive_queries.append({
                            "query": session_name[:60] + "..." if len(session_name) > 60 else session_name,
                            "tokens": session_tokens,
                            "session_id": session_data.get('id', 'unknown')[:8]
                        })
                    
                    # Track velocity (sessions per hour)
                    created_at = session_data.get('created_at')
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            hour_key = dt.strftime('%Y-%m-%d %H:00')
                            sessions_by_hour[hour_key] = sessions_by_hour.get(hour_key, 0) + 1
                        except:
                            pass
                            
                except Exception as e:
                    app_logger.warning(f"Error processing session file {session_file.name}: {e}")
                    continue
        
        # Calculate metrics
        total_tokens_val = total_input_tokens + total_output_tokens
        success_rate = (successful_turns / total_turns * 100) if total_turns > 0 else 0
        
        # Calculate actual cost using cost manager
        from trusted_data_agent.core.cost_manager import get_cost_manager
        cost_manager = get_cost_manager()
        estimated_cost = 0.0

        # Recalculate costs with actual pricing
        turns_processed = 0
        for session_dir in scan_dirs:
            for session_file in session_dir.glob('*.json'):
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)

                    workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', [])
                    for turn in workflow_history:
                        if not turn.get('isValid', True):
                            continue

                        provider = turn.get('provider', 'Unknown')
                        model = turn.get('model', 'unknown')
                        input_tokens = turn.get('turn_input_tokens', 0)
                        output_tokens = turn.get('turn_output_tokens', 0)

                        turn_cost = cost_manager.calculate_cost(provider, model, input_tokens, output_tokens)
                        estimated_cost += turn_cost
                        turns_processed += 1

                except Exception as e:
                    app_logger.warning(f"Error calculating cost for session {session_file.name}: {e}")

        app_logger.info(f"[Analytics] Processed {turns_processed} turns, total cost: ${estimated_cost:.4f}")
        
        # Model distribution percentages
        total_model_count = sum(model_usage.values())
        model_distribution = {
            model: round(count / total_model_count * 100, 1)
            for model, count in model_usage.items()
        } if total_model_count > 0 else {}
        
        # Sort by token count (descending) and take top 5 most expensive sessions and questions
        expensive_queries.sort(key=lambda x: x['tokens'], reverse=True)
        top_expensive_queries = expensive_queries[:5]
        
        expensive_questions.sort(key=lambda x: x['tokens'], reverse=True)
        top_expensive_questions = expensive_questions[:5]
        
        # Velocity data (last 24 hours)
        velocity_data = []
        if sessions_by_hour:
            sorted_hours = sorted(sessions_by_hour.items())[-24:]  # Last 24 hours
            velocity_data = [{"hour": hour, "count": count} for hour, count in sorted_hours]
        
        # Calculate RAG efficiency metrics - focus on OUTPUT efficiency (better plans)
        rag_activation_rate = round((rag_guided_turns / total_turns * 100), 1) if total_turns > 0 else 0
        
        # Calculate average OUTPUT tokens per turn (measures plan quality)
        avg_rag_output = round(rag_guided_output_tokens / rag_guided_turns, 1) if rag_guided_turns > 0 else 0
        avg_non_rag_output = round(non_rag_output_tokens / non_rag_turns, 1) if non_rag_turns > 0 else 0
        
        # Calculate output efficiency gain (better plans = fewer output tokens)
        efficiency_gain = 0
        if avg_non_rag_output > 0 and avg_rag_output > 0:
            efficiency_gain = round((avg_non_rag_output - avg_rag_output) / avg_non_rag_output * 100, 1)
        
        # Get real-time efficiency metrics from centralized tracker
        from trusted_data_agent.core.efficiency_tracker import get_efficiency_tracker
        tracker = get_efficiency_tracker()
        
        # Get user-specific metrics
        user_efficiency_metrics = tracker.get_metrics(user_uuid=user_uuid)
        user_output_tokens_saved = user_efficiency_metrics["total_output_tokens_saved"]
        user_rag_savings_cost = user_efficiency_metrics["cumulative_cost_saved"]
        
        # Get global metrics (all users)
        global_efficiency_metrics = tracker.get_metrics()
        global_output_tokens_saved = global_efficiency_metrics["total_output_tokens_saved"]
        global_rag_savings_cost = global_efficiency_metrics["cumulative_cost_saved"]
        
        # Check if user is admin
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import User
        is_admin = False
        try:
            with get_db_session() as db:
                user_record = db.query(User).filter(User.id == user_uuid).first()
                if user_record:
                    app_logger.info(f"User {user_uuid[:8]} has profile_tier: {user_record.profile_tier}, is_admin: {user_record.is_admin}")
                    # Check both profile_tier and is_admin flag
                    if user_record.profile_tier == 'admin' or user_record.is_admin:
                        is_admin = True
                else:
                    app_logger.warning(f"User record not found for {user_uuid[:8]}")
        except Exception as e:
            app_logger.error(f"Error checking admin status: {e}", exc_info=True)
        
        return jsonify({
            "total_sessions": total_sessions,
            "total_tokens": {
                "input": total_input_tokens,
                "output": total_output_tokens,
                "total": total_tokens_val
            },
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "success_rate_percent": round(success_rate, 1),
            "estimated_cost_usd": round(estimated_cost, 2),
            "model_distribution": model_distribution,
            "top_expensive_queries": top_expensive_queries,
            "top_expensive_questions": top_expensive_questions,
            "velocity_data": velocity_data,
            "is_admin": is_admin,
            "rag_metrics": {
                "rag_guided_turns": rag_guided_turns,
                "total_turns": total_turns,
                "activation_rate": rag_activation_rate,
                "avg_rag_output": avg_rag_output,
                "avg_non_rag_output": avg_non_rag_output,
                "efficiency_gain": efficiency_gain,
                "tokens_saved": user_output_tokens_saved,
                "cost_saved": user_rag_savings_cost
            },
            "rag_metrics_global": {
                "tokens_saved": global_output_tokens_saved,
                "cost_saved": global_rag_savings_cost,
                "total_improvements": global_efficiency_metrics["total_rag_improvements"],
                "total_sessions": global_efficiency_metrics["total_sessions_tracked"]
            }
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error getting session analytics: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# CONSUMPTION TRACKING API ENDPOINTS (Optimized DB-backed)
# ============================================================================

@rest_api_bp.route('/v1/consumption/summary', methods=['GET'])
async def get_consumption_summary():
    """
    Get comprehensive consumption summary for current user (DB-backed, <50ms).
    Replaces file-scanning approach with O(1) database lookup.
    """
    from trusted_data_agent.auth.middleware import get_current_user
    
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    
    try:
        user_uuid = current_user.id
        
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.consumption_manager import ConsumptionManager
        from trusted_data_agent.auth.models import ConsumptionTurn
        from sqlalchemy import func
        from datetime import datetime, timezone, timedelta
        
        with get_db_session() as db_session:
            manager = ConsumptionManager(db_session)
            summary = manager.get_consumption_summary(user_uuid)
            
            # Calculate velocity data (last 24 hours) from consumption_turns table
            now = datetime.now(timezone.utc)
            last_24h = now - timedelta(hours=24)
            
            # Query turns grouped by hour for last 24 hours
            velocity_query = db_session.query(
                func.strftime('%Y-%m-%d %H:00:00', ConsumptionTurn.created_at).label('hour'),
                func.count(ConsumptionTurn.id).label('count')
            ).filter(
                ConsumptionTurn.user_id == user_uuid,
                ConsumptionTurn.created_at >= last_24h
            ).group_by('hour').order_by('hour')
            
            velocity_results = velocity_query.all()
            velocity_data = [{"hour": hour, "count": count} for hour, count in velocity_results]
            
            # Calculate model distribution from recent activity
            model_query = db_session.query(
                ConsumptionTurn.model,
                func.count(ConsumptionTurn.id).label('count')
            ).filter(
                ConsumptionTurn.user_id == user_uuid
            ).group_by(ConsumptionTurn.model)
            
            model_results = model_query.all()
            total_model_count = sum(count for _, count in model_results)
            model_distribution = {
                model: round(count / total_model_count * 100, 1)
                for model, count in model_results
            } if total_model_count > 0 else {}
            
            # Get top expensive sessions (by total tokens per session)
            expensive_sessions_query = db_session.query(
                ConsumptionTurn.session_id,
                func.max(ConsumptionTurn.session_name).label('session_name'),
                func.sum(ConsumptionTurn.total_tokens).label('total_tokens'),
                func.sum(ConsumptionTurn.cost_usd_cents).label('total_cost')
            ).filter(
                ConsumptionTurn.user_id == user_uuid
            ).group_by(ConsumptionTurn.session_id).order_by(
                func.sum(ConsumptionTurn.total_tokens).desc()
            ).limit(5)
            
            expensive_sessions = []
            for session_id, session_name, tokens, cost in expensive_sessions_query.all():
                expensive_sessions.append({
                    'session_id': session_id,
                    'name': session_name or 'Untitled Session',
                    'tokens': tokens,
                    'cost': cost / 1000000.0 if cost else 0.0
                })
            
            # Get top expensive individual turns (questions)
            expensive_turns_query = db_session.query(
                ConsumptionTurn.session_id,
                ConsumptionTurn.turn_number,
                ConsumptionTurn.user_query,
                ConsumptionTurn.total_tokens,
                ConsumptionTurn.cost_usd_cents
            ).filter(
                ConsumptionTurn.user_id == user_uuid
            ).order_by(ConsumptionTurn.total_tokens.desc()).limit(5)
            
            expensive_questions = []
            for session_id, turn_num, user_query, tokens, cost in expensive_turns_query.all():
                expensive_questions.append({
                    'session_id': session_id,
                    'turn': turn_num,
                    'query': user_query or 'No query text',
                    'tokens': tokens,
                    'cost': cost / 1000000.0 if cost else 0.0
                })
            
            # Add all analytics data to summary
            summary['velocity_data'] = velocity_data
            summary['model_distribution'] = model_distribution
            summary['top_expensive_queries'] = expensive_sessions
            summary['top_expensive_questions'] = expensive_questions
            
            return jsonify(summary), 200
    
    except Exception as e:
        app_logger.error(f"Error getting consumption summary: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@rest_api_bp.route('/v1/consumption/system-summary', methods=['GET'])
@require_admin
async def get_system_consumption_summary():
    """
    Get system-wide consumption summary (all users aggregated) - Admin only.
    Returns aggregated metrics for the entire system.
    """
    try:
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import UserConsumption, ConsumptionTurn
        from sqlalchemy import func, desc
        from datetime import datetime, timedelta
        
        with get_db_session() as db_session:
            # Aggregate all user consumption data
            result = db_session.query(
                func.count(UserConsumption.user_id).label('total_users'),
                func.sum(UserConsumption.total_input_tokens).label('total_input_tokens'),
                func.sum(UserConsumption.total_output_tokens).label('total_output_tokens'),
                func.sum(UserConsumption.total_tokens).label('total_tokens'),
                func.sum(UserConsumption.total_sessions).label('total_sessions'),
                func.sum(UserConsumption.total_turns).label('total_turns'),
                func.sum(UserConsumption.successful_turns).label('successful_turns'),
                func.sum(UserConsumption.failed_turns).label('failed_turns'),
                func.sum(UserConsumption.rag_guided_turns).label('rag_guided_turns'),
                func.sum(UserConsumption.rag_output_tokens_saved).label('rag_output_tokens_saved'),
                func.sum(UserConsumption.rag_cost_saved_usd).label('rag_cost_saved_usd'),
                func.sum(UserConsumption.estimated_cost_usd).label('total_cost_cents'),
                func.sum(UserConsumption.sessions_last_24h).label('sessions_last_24h'),
                func.sum(UserConsumption.turns_last_24h).label('turns_last_24h')
            ).first()
            
            # Calculate derived metrics
            total_users = result.total_users or 0
            total_tokens = result.total_tokens or 0
            total_turns = result.total_turns or 0
            successful_turns = result.successful_turns or 0
            rag_guided_turns = result.rag_guided_turns or 0
            
            success_rate = (successful_turns / total_turns * 100) if total_turns > 0 else 0
            rag_activation_rate = (rag_guided_turns / total_turns * 100) if total_turns > 0 else 0
            avg_tokens_per_user = (total_tokens / total_users) if total_users > 0 else 0
            
            # Count active users (users with token usage)
            active_users = db_session.query(func.count(UserConsumption.user_id)).filter(
                UserConsumption.total_tokens > 0
            ).scalar() or 0
            
            # Get velocity data (last 30 days, all users aggregated)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            velocity_query = db_session.query(
                func.date(ConsumptionTurn.created_at).label('date'),
                func.count(ConsumptionTurn.id).label('count')
            ).filter(
                ConsumptionTurn.created_at >= thirty_days_ago
            ).group_by(
                func.date(ConsumptionTurn.created_at)
            ).order_by('date').all()
            
            velocity_data = [{'date': str(row.date), 'count': row.count or 0} for row in velocity_query]
            
            # Get model distribution (all users aggregated)
            model_dist_query = db_session.query(
                ConsumptionTurn.model,
                func.count(ConsumptionTurn.id).label('count')
            ).filter(
                ConsumptionTurn.model.isnot(None)
            ).group_by(
                ConsumptionTurn.model
            ).all()
            
            # Calculate percentages
            total_model_count = sum(row.count for row in model_dist_query)
            model_distribution = {
                row.model: round(row.count / total_model_count * 100, 1)
                for row in model_dist_query
            } if total_model_count > 0 else {}
            
            # Get top expensive sessions (all users)
            top_sessions_query = db_session.query(
                ConsumptionTurn.session_id,
                func.max(ConsumptionTurn.session_name).label('session_name'),
                func.sum(ConsumptionTurn.total_tokens).label('total_tokens')
            ).filter(
                ConsumptionTurn.session_id.isnot(None)
            ).group_by(
                ConsumptionTurn.session_id
            ).order_by(desc('total_tokens')).limit(5).all()
            
            top_expensive_queries = [
                {
                    'session_id': row.session_id,
                    'name': row.session_name or 'Unnamed Session',
                    'tokens': row.total_tokens or 0
                }
                for row in top_sessions_query
            ]
            
            # Get top expensive questions (all users)
            top_questions_query = db_session.query(
                ConsumptionTurn.user_query,
                ConsumptionTurn.session_id,
                ConsumptionTurn.total_tokens
            ).filter(
                ConsumptionTurn.user_query.isnot(None),
                ConsumptionTurn.user_query != ''
            ).order_by(desc(ConsumptionTurn.total_tokens)).limit(5).all()
            
            top_expensive_questions = [
                {
                    'query': row.user_query[:100],  # Truncate long queries
                    'session_id': row.session_id,
                    'tokens': row.total_tokens or 0
                }
                for row in top_questions_query
            ]
            
            summary = {
                'total_users': total_users,
                'active_users': active_users,
                'total_input_tokens': result.total_input_tokens or 0,
                'total_output_tokens': result.total_output_tokens or 0,
                'total_tokens': total_tokens,
                'avg_tokens_per_user': int(avg_tokens_per_user),
                'total_sessions': result.total_sessions or 0,
                'total_turns': total_turns,
                'successful_turns': successful_turns,
                'failed_turns': result.failed_turns or 0,
                'success_rate_percent': round(success_rate, 2),
                'rag_guided_turns': rag_guided_turns,
                'rag_activation_rate_percent': round(rag_activation_rate, 2),
                'rag_output_tokens_saved': result.rag_output_tokens_saved or 0,
                'rag_cost_saved_usd': (result.rag_cost_saved_usd or 0) / 1000000.0,  # Convert micro-dollars to dollars
                'estimated_cost_usd': (result.total_cost_cents or 0) / 1000000.0,
                'sessions_last_24h': result.sessions_last_24h or 0,
                'turns_last_24h': result.turns_last_24h or 0,
                'velocity_data': velocity_data,
                'model_distribution': model_distribution,
                'top_expensive_queries': top_expensive_queries,
                'top_expensive_questions': top_expensive_questions
            }
            
            return jsonify(summary), 200
    
    except Exception as e:
        app_logger.error(f"Error getting system consumption summary: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@rest_api_bp.route('/v1/consumption/users', methods=['GET'])
@require_admin
async def get_all_users_consumption():
    """
    Get consumption data for all users (admin only, for Admin dashboard).
    Query params: threshold (filter users near limit), sort, limit, offset
    """
    try:
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import UserConsumption, User
        
        # Parse query params
        threshold = request.args.get('threshold', type=float)  # e.g., 80.0 for 80%
        sort_by = request.args.get('sort', 'total_tokens')  # total_tokens, success_rate, etc.
        limit = request.args.get('limit', type=int, default=100)
        offset = request.args.get('offset', type=int, default=0)
        
        with get_db_session() as db_session:
            query = db_session.query(UserConsumption, User).join(
                User, UserConsumption.user_id == User.id
            )
            
            # Apply threshold filter if specified
            if threshold:
                query = query.filter(
                    (UserConsumption.total_input_tokens * 100.0 / UserConsumption.input_tokens_limit >= threshold) |
                    (UserConsumption.total_output_tokens * 100.0 / UserConsumption.output_tokens_limit >= threshold)
                ).filter(
                    (UserConsumption.input_tokens_limit.isnot(None)) |
                    (UserConsumption.output_tokens_limit.isnot(None))
                )
            
            # Apply sorting
            if sort_by == 'total_tokens':
                query = query.order_by(UserConsumption.total_tokens.desc())
            elif sort_by == 'success_rate':
                query = query.order_by(
                    (UserConsumption.successful_turns * 100.0 / UserConsumption.total_turns).desc()
                )
            elif sort_by == 'cost':
                query = query.order_by(UserConsumption.estimated_cost_usd.desc())
            
            # Pagination
            total_count = query.count()
            results = query.limit(limit).offset(offset).all()
            
            # Format response
            users_data = []
            for consumption, user in results:
                data = consumption.to_dict()
                data['username'] = user.username
                data['email'] = user.email
                data['is_admin'] = user.is_admin
                users_data.append(data)
            
            return jsonify({
                'users': users_data,
                'total_count': total_count,
                'limit': limit,
                'offset': offset
            }), 200
    
    except Exception as e:
        app_logger.error(f"Error getting all users consumption: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@rest_api_bp.route('/v1/consumption/turns', methods=['GET'])
async def get_consumption_turns():
    """
    Get turn-level consumption details for current user.
    Query params: session_id, limit, offset
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import ConsumptionTurn
        
        # Parse query params
        session_id = request.args.get('session_id')
        limit = request.args.get('limit', type=int, default=50)
        offset = request.args.get('offset', type=int, default=0)
        
        with get_db_session() as db_session:
            query = db_session.query(ConsumptionTurn).filter_by(user_id=user_uuid)
            
            if session_id:
                query = query.filter_by(session_id=session_id)
            
            query = query.order_by(ConsumptionTurn.created_at.desc())
            
            total_count = query.count()
            turns = query.limit(limit).offset(offset).all()
            
            return jsonify({
                'turns': [turn.to_dict() for turn in turns],
                'total_count': total_count,
                'limit': limit,
                'offset': offset
            }), 200
    
    except Exception as e:
        app_logger.error(f"Error getting consumption turns: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@rest_api_bp.route('/v1/consumption/history', methods=['GET'])
async def get_consumption_history():
    """
    Get historical period archives for current user.
    Returns archived monthly consumption data for trend analysis.
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import ConsumptionPeriodsArchive
        
        with get_db_session() as db_session:
            archives = db_session.query(ConsumptionPeriodsArchive).filter_by(
                user_id=user_uuid
            ).order_by(ConsumptionPeriodsArchive.period.desc()).limit(12).all()
            
            return jsonify({
                'history': [archive.to_dict() for archive in archives]
            }), 200
    
    except Exception as e:
        app_logger.error(f"Error getting consumption history: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@rest_api_bp.route('/v1/sessions', methods=['GET'])
async def get_sessions_list():
    """
    Get list of all sessions with metadata for the execution dashboard.
    Query params: search, sort, filter_status, filter_model, limit, offset, all_users
    """
    try:
        from pathlib import Path
        from trusted_data_agent.core.config import APP_CONFIG
        from trusted_data_agent.auth.middleware import get_current_user
        
        # Get authenticated user (for auth-enabled mode) or UUID from header (legacy mode)
        current_user = get_current_user()
        if current_user:
            user_uuid = current_user.id
        else:
            user_uuid = _get_user_uuid_from_request()
        
        # Get query parameters
        search_query = request.args.get('search', '').lower()
        sort_by = request.args.get('sort', 'recent')  # recent, oldest, tokens, turns
        filter_status = request.args.get('filter_status', 'all')  # all, success, partial, failed
        filter_model = request.args.get('filter_model', 'all')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        all_users = request.args.get('all_users', 'false').lower() == 'true'
        
        # Check if user has VIEW_ALL_SESSIONS feature when requesting all users
        if all_users:
            from trusted_data_agent.auth.features import get_user_features, Feature
            
            # If we have an authenticated user, check their features
            if current_user:
                user_features = get_user_features(current_user)
                if Feature.VIEW_ALL_SESSIONS not in user_features:
                    app_logger.warning(f"User {user_uuid} attempted to view all sessions without permission")
                    return jsonify({"status": "error", "message": "Insufficient permissions to view all sessions"}), 403
            else:
                # No authentication - deny all_users mode
                app_logger.warning(f"Unauthenticated request attempted to view all sessions")
                return jsonify({"status": "error", "message": "Authentication required to view all sessions"}), 401
        
        project_root = Path(__file__).resolve().parents[3]
        sessions_base = project_root / 'tda_sessions'
        
        # Determine which sessions to scan based on all_users parameter or filter setting
        if all_users or not APP_CONFIG.SESSIONS_FILTER_BY_USER:
            # All users mode
            pass  # Fetching all users' sessions
            if not sessions_base.exists():
                return jsonify({"sessions": [], "total": 0}), 200
            scan_dirs = [d for d in sessions_base.iterdir() if d.is_dir()]
            pass  # Scanning directories
        else:
            # User-specific mode
            if not user_uuid:
                app_logger.warning("No user_uuid available for user-specific session fetch")
                return jsonify({"sessions": [], "total": 0}), 200
            
            sessions_root = sessions_base / user_uuid
            if not sessions_root.exists():
                return jsonify({"sessions": [], "total": 0}), 200
            scan_dirs = [sessions_root]
        
        sessions = []
        
        # Load all sessions from determined directories
        for session_dir in scan_dirs:
            for session_file in session_dir.glob('*.json'):
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                    
                    session_id = session_data.get('id')
                    name = session_data.get('name', 'Unnamed Session')
                    created_at = session_data.get('created_at', '')
                    last_updated = session_data.get('last_updated', '')
                    provider = session_data.get('provider', 'Unknown')
                    model = session_data.get('model', 'Unknown')
                    input_tokens = session_data.get('input_tokens', 0)
                    output_tokens = session_data.get('output_tokens', 0)
                    
                    # Analyze workflow
                    workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', [])
                    turn_count = len([t for t in workflow_history if t.get('isValid', True)])
                    
                    # Determine status
                    has_errors = False
                    all_successful = True
                    for turn in workflow_history:
                        if not turn.get('isValid', True):
                            continue
                        if not turn.get('final_summary'):
                            all_successful = False
                        # Check for errors in execution trace
                        exec_trace = turn.get('execution_trace', [])
                        for entry in exec_trace:
                            if isinstance(entry, dict):
                                result = entry.get('result', {})
                                if isinstance(result, dict) and result.get('status') == 'error':
                                    has_errors = True
                    
                    if all_successful and not has_errors and turn_count > 0:
                        status = 'success'
                    elif turn_count > 0:
                        status = 'partial' if all_successful else 'failed'
                    else:
                        status = 'empty'
                    
                    # Check for RAG enhancement
                    rag_cases_dir = project_root / 'rag' / 'tda_rag_cases'
                    has_rag = False
                    if rag_cases_dir.exists():
                        for case_file in rag_cases_dir.glob(f'case_*-{session_id[:8]}*.json'):
                            has_rag = True
                            break
                    
                    # Apply filters (but not search - let client handle that for flexibility)
                    if filter_status != 'all' and status != filter_status:
                        continue
                    if filter_model != 'all' and filter_model not in f"{provider}/{model}":
                        continue
                    
                    sessions.append({
                        "id": session_id,
                        "name": name,
                        "created_at": created_at,
                        "last_updated": last_updated,
                        "provider": provider,
                        "model": model,
                        "models_used": session_data.get("models_used", []),
                        "profile_tags_used": session_data.get("profile_tags_used", []),
                        "turn_count": turn_count,
                        "total_tokens": input_tokens + output_tokens,
                        "status": status,
                        "has_rag": has_rag,
                        "has_errors": has_errors,
                        "archived": session_data.get("archived", False),
                        "archived_at": session_data.get("archived_at"),
                        "is_temporary": session_data.get("is_temporary", False),
                        "temporary_purpose": session_data.get("temporary_purpose"),
                        "last_turn_data": {
                            "workflow_history": workflow_history
                        }
                    })
                    
                except Exception as e:
                    app_logger.warning(f"Error processing session {session_file.name}: {e}")
                    continue
        
        # Sort sessions
        if sort_by == 'recent':
            sessions.sort(key=lambda x: x.get('last_updated', ''), reverse=True)
        elif sort_by == 'oldest':
            sessions.sort(key=lambda x: x.get('created_at', ''))
        elif sort_by == 'tokens':
            sessions.sort(key=lambda x: x.get('total_tokens', 0), reverse=True)
        elif sort_by == 'turns':
            sessions.sort(key=lambda x: x.get('turn_count', 0), reverse=True)
        
        # Paginate
        total = len(sessions)
        sessions_page = sessions[offset:offset + limit]
        
        return jsonify({
            "sessions": sessions_page,
            "total": total,
            "limit": limit,
            "offset": offset
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error getting sessions list: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@rest_api_bp.route('/v1/sessions/<session_id>/details', methods=['GET'])
async def get_session_details(session_id: str):
    """
    Get full session details for deep dive inspector.
    Returns: complete session data with timeline, execution traces, RAG associations
    """
    try:
        from pathlib import Path
        from trusted_data_agent.core.config import APP_CONFIG
        from trusted_data_agent.auth.middleware import get_current_user
        from trusted_data_agent.auth.features import get_user_features, Feature
        
        # Get authenticated user (for auth-enabled mode) or UUID from header (legacy mode)
        current_user = get_current_user()
        if current_user:
            user_uuid = current_user.id
            # Check if user has VIEW_ALL_SESSIONS feature
            user_features = get_user_features(current_user)
            can_view_all = Feature.VIEW_ALL_SESSIONS in user_features
        else:
            user_uuid = _get_user_uuid_from_request()
            can_view_all = False
        
        project_root = Path(__file__).resolve().parents[3]
        sessions_base = project_root / 'tda_sessions'
        rag_cases_dir = project_root / 'rag' / 'tda_rag_cases'
        
        # Find session file - check user's own directory first, then all if permitted
        session_file = None
        if user_uuid:
            # Try user's own directory first
            session_file = sessions_base / user_uuid / f"{session_id}.json"
            if session_file.exists():
                app_logger.debug(f"Found session {session_id} in user's directory")
            else:
                session_file = None
        
        # If not found in user's directory and they have permission, search all directories
        if not session_file and (can_view_all or not APP_CONFIG.SESSIONS_FILTER_BY_USER):
            app_logger.debug(f"Searching all directories for session {session_id}")
            for user_dir in sessions_base.iterdir():
                if user_dir.is_dir():
                    potential_path = user_dir / f"{session_id}.json"
                    if potential_path.exists():
                        session_file = potential_path
                        app_logger.debug(f"Found session {session_id} in directory {user_dir.name}")
                        break
        
        if not session_file or not session_file.exists():
            return jsonify({"error": "Session not found"}), 404
        
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
        
        # Find associated RAG cases
        rag_cases = []
        if rag_cases_dir.exists():
            # RAG cases are stored in collection_X/ subdirectories
            for collection_dir in rag_cases_dir.iterdir():
                if not collection_dir.is_dir() or not collection_dir.name.startswith('collection_'):
                    continue
                
                for case_file in collection_dir.glob('case_*.json'):
                    try:
                        with open(case_file, 'r', encoding='utf-8') as cf:
                            case_data = json.load(cf)
                        
                        if case_data.get('metadata', {}).get('session_id') == session_id:
                            rag_cases.append({
                                "case_id": case_data.get('case_id'),
                                "turn_id": case_data.get('metadata', {}).get('turn_id'),
                                "is_most_efficient": case_data.get('metadata', {}).get('is_most_efficient', False),
                                "output_tokens": case_data.get('metadata', {}).get('llm_config', {}).get('output_tokens', 0),
                                "strategy_metrics": case_data.get('metadata', {}).get('strategy_metrics', {}),
                                "collection_id": case_data.get('metadata', {}).get('collection_id', 0)
                            })
                    except:
                        continue
        
        session_data['rag_cases'] = rag_cases
        
        return jsonify(session_data), 200
        
    except Exception as e:
        app_logger.error(f"Error getting session details: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# MARKETPLACE API ENDPOINTS - PHASE 3
# ============================================================================

@rest_api_bp.route("/v1/marketplace/collections", methods=["GET"])
async def browse_marketplace_collections():
    """
    Browse public marketplace collections.
    
    Query parameters:
    - visibility: Filter by visibility (public, unlisted). Default: public
    - search: Search in name and description
    - repository_type: Filter by repository type (planner, knowledge). Default: all
    - sort_by: Sort order - "rating" (by average rating), "subscribers" (by subscriber count), "recent" (by date). Default: subscribers
    - limit: Max results (default: 50)
    - offset: Pagination offset (default: 0)
    
    Returns:
    {
        "status": "success",
        "collections": [...],  // Each collection includes average_rating and rating_count
        "total": 123,
        "limit": 50,
        "offset": 0
    }
    """
    try:
        # Get current user for ownership check
        user_uuid = _get_user_uuid_from_request()
        
        # Parse query parameters
        visibility_filter = request.args.get("visibility", "public")
        search_query = request.args.get("search", "").lower()
        repository_type_filter = request.args.get("repository_type", None)  # Filter by repository type
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        
        # Get all collections from database
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        all_collections = collection_db.get_all_collections()
        retriever = APP_STATE.get("rag_retriever_instance")
        
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Filter marketplace-listed collections
        marketplace_collections = []
        for coll in all_collections:
            # Must be marketplace-listed
            if not coll.get("is_marketplace_listed", False):
                continue
            
            # Skip collections with no owner (system collections)
            if coll.get("owner_user_id") is None:
                continue
            
            # Skip collections owned by the current user
            if user_uuid and coll.get("owner_user_id") == user_uuid:
                continue
            
            # Check visibility filter
            coll_visibility = coll.get("visibility", "private")
            if visibility_filter == "public" and coll_visibility != "public":
                continue
            
            # Repository type filter (if provided)
            if repository_type_filter:
                coll_repo_type = coll.get("repository_type", "planner")
                if coll_repo_type != repository_type_filter:
                    continue
            
            # Search filter (if provided)
            if search_query:
                name_match = search_query in coll.get("name", "").lower()
                desc_match = search_query in coll.get("description", "").lower()
                if not (name_match or desc_match):
                    continue
            
            # Add document count and ownership flag
            coll_copy = coll.copy()
            if coll["id"] in retriever.collections:
                try:
                    coll_copy["count"] = retriever.collections[coll["id"]].count()
                except:
                    coll_copy["count"] = 0
            else:
                coll_copy["count"] = 0
            
            # Check if current user owns this collection
            if user_uuid:
                coll_copy["is_owner"] = retriever.is_user_collection_owner(coll["id"], user_uuid)
                coll_copy["is_subscribed"] = retriever.is_subscribed_collection(coll["id"], user_uuid)
                
                # Add subscription_id if user is subscribed (needed for unsubscribe action)
                if coll_copy["is_subscribed"]:
                    from trusted_data_agent.auth.database import get_db_session
                    from trusted_data_agent.auth.models import CollectionSubscription
                    with get_db_session() as session:
                        subscription = session.query(CollectionSubscription).filter_by(
                            user_id=user_uuid,
                            source_collection_id=coll["id"]
                        ).first()
                        if subscription:
                            coll_copy["subscription_id"] = subscription.id
            else:
                coll_copy["is_owner"] = False
                coll_copy["is_subscribed"] = False
            
            marketplace_collections.append(coll_copy)
        
        # Add rating statistics in bulk (efficient single query)
        collection_ids = [c["id"] for c in marketplace_collections]
        ratings_map = collection_db.get_bulk_collection_ratings(collection_ids)
        for coll in marketplace_collections:
            coll_ratings = ratings_map.get(coll["id"], {"average_rating": 0.0, "rating_count": 0})
            coll["average_rating"] = coll_ratings["average_rating"]
            coll["rating_count"] = coll_ratings["rating_count"]
        
        # Sort by rating or subscriber count
        sort_by = request.args.get("sort_by", "subscribers")  # "rating", "subscribers", or "recent"
        if sort_by == "rating":
            marketplace_collections.sort(key=lambda c: (c.get("average_rating", 0), c.get("rating_count", 0)), reverse=True)
        elif sort_by == "recent":
            marketplace_collections.sort(key=lambda c: c.get("created_at", ""), reverse=True)
        else:  # Default: subscribers
            marketplace_collections.sort(key=lambda c: c.get("subscriber_count", 0), reverse=True)
        
        # Pagination
        total = len(marketplace_collections)
        paginated = marketplace_collections[offset:offset + limit]
        
        return jsonify({
            "status": "success",
            "collections": paginated,
            "total": total,
            "limit": limit,
            "offset": offset
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error browsing marketplace collections: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/marketplace/collections/<int:collection_id>/subscribe", methods=["POST"])
async def subscribe_to_collection(collection_id: int):
    """
    Subscribe to a marketplace collection.
    
    Creates a subscription that allows the user to query the collection
    without copying data (reference-based model).
    
    Returns:
    {
        "status": "success",
        "subscription_id": "uuid",
        "collection_id": 123,
        "message": "Successfully subscribed to collection"
    }
    """
    try:
        # Get authenticated user
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        # Get retriever and validate collection exists
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        coll_meta = retriever.get_collection_metadata(collection_id)
        if not coll_meta:
            return jsonify({"status": "error", "message": "Collection not found"}), 404
        
        # Check if collection is available for subscription
        visibility = coll_meta.get("visibility", "private")
        is_listed = coll_meta.get("is_marketplace_listed", False)
        
        if visibility == "private" and not is_listed:
            return jsonify({"status": "error", "message": "Collection is private and not available for subscription"}), 403
        
        # Check if user already owns this collection
        if retriever.is_user_collection_owner(collection_id, user_uuid):
            return jsonify({"status": "error", "message": "You already own this collection"}), 400
        
        # Check if already subscribed
        if retriever.is_subscribed_collection(collection_id, user_uuid):
            return jsonify({"status": "error", "message": "You are already subscribed to this collection"}), 400
        
        # Create subscription
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import CollectionSubscription
        from trusted_data_agent.core.config_manager import get_config_manager
        
        with get_db_session() as session:
            subscription = CollectionSubscription(
                user_id=user_uuid,
                source_collection_id=collection_id,
                enabled=True
            )
            session.add(subscription)
            session.flush()  # Get the ID
            subscription_id = subscription.id
        
        # Increment subscriber count in database
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        current_coll = collection_db.get_collection_by_id(collection_id)
        if current_coll:
            new_count = current_coll.get("subscriber_count", 0) + 1
            collection_db.update_collection(collection_id, {"subscriber_count": new_count})
        
        app_logger.info(f"User {user_uuid} subscribed to collection {collection_id}")
        
        return jsonify({
            "status": "success",
            "subscription_id": subscription_id,
            "collection_id": collection_id,
            "message": "Successfully subscribed to collection"
        }), 201
        
    except Exception as e:
        app_logger.error(f"Error subscribing to collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/marketplace/subscriptions/<subscription_id>", methods=["DELETE"])
async def unsubscribe_from_collection(subscription_id: str):
    """
    Unsubscribe from a collection.
    
    Removes the subscription and decrements the subscriber count.
    
    Returns:
    {
        "status": "success",
        "message": "Successfully unsubscribed"
    }
    """
    try:
        # Get authenticated user
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import CollectionSubscription
        from trusted_data_agent.core.config_manager import get_config_manager
        
        with get_db_session() as session:
            # Find subscription
            subscription = session.query(CollectionSubscription).filter_by(
                id=subscription_id,
                user_id=user_uuid
            ).first()
            
            if not subscription:
                return jsonify({"status": "error", "message": "Subscription not found or you don't have permission"}), 404
            
            collection_id = subscription.source_collection_id
            
            # Delete subscription
            session.delete(subscription)
        
        # Decrement subscriber count in database
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        current_coll = collection_db.get_collection_by_id(collection_id)
        if current_coll:
            new_count = max(0, current_coll.get("subscriber_count", 0) - 1)
            collection_db.update_collection(collection_id, {"subscriber_count": new_count})
        
        app_logger.info(f"User {user_uuid} unsubscribed from collection {collection_id}")
        
        return jsonify({
            "status": "success",
            "message": "Successfully unsubscribed"
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error unsubscribing: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/marketplace/collections/<int:collection_id>/fork", methods=["POST"])
async def fork_marketplace_collection(collection_id: int):
    """
    Fork a collection to create an independent copy.
    
    Request body:
    {
        "name": "My Forked Collection",
        "description": "Custom description",
        "mcp_server_id": "my-mcp-server"
    }
    
    Returns:
    {
        "status": "success",
        "collection_id": 123,
        "message": "Collection forked successfully"
    }
    """
    try:
        # Get authenticated user
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        # Parse request
        data = await request.get_json()
        new_name = data.get("name")
        new_description = data.get("description", "")
        
        if not new_name:
            return jsonify({"status": "error", "message": "Collection name is required"}), 400
        
        # Use the user's own MCP server (get from their config)
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        user_config = config_manager.load_config(user_uuid)
        mcp_servers = user_config.get("mcp_servers", [])
        
        # Use active MCP server or first available
        active_mcp_id = user_config.get("active_mcp_server_id")
        if active_mcp_id:
            mcp_server_id = active_mcp_id
        elif mcp_servers:
            mcp_server_id = mcp_servers[0].get("id")
        else:
            return jsonify({"status": "error", "message": "No MCP server configured for your account"}), 400
        
        # Get retriever
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Verify source collection exists and is accessible
        coll_meta = retriever.get_collection_metadata(collection_id)
        if not coll_meta:
            return jsonify({"status": "error", "message": "Source collection not found"}), 404
        
        # Check access (must be owner, subscriber, or public)
        accessible_ids = retriever._get_user_accessible_collections(user_uuid)
        if collection_id not in accessible_ids:
            return jsonify({"status": "error", "message": "You don't have access to this collection"}), 403
        
        # Fork the collection
        forked_id = retriever.fork_collection(
            source_collection_id=collection_id,
            new_name=new_name,
            new_description=new_description,
            owner_user_id=user_uuid,
            mcp_server_id=mcp_server_id
        )
        
        if forked_id:
            app_logger.info(f"User {user_uuid} forked collection {collection_id} -> {forked_id}")
            return jsonify({
                "status": "success",
                "collection_id": forked_id,
                "source_collection_id": collection_id,
                "message": "Collection forked successfully"
            }), 201
        else:
            return jsonify({"status": "error", "message": "Failed to fork collection"}), 500
        
    except Exception as e:
        app_logger.error(f"Error forking collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>/publish", methods=["POST"])
async def publish_collection_to_marketplace(collection_id: int):
    """
    Publish a collection to the marketplace.
    
    Request body:
    {
        "visibility": "public",  // or "unlisted"
        "marketplace_metadata": {
            "category": "analytics",
            "tags": ["sql", "reporting"],
            "long_description": "..."
        }
    }
    
    Returns:
    {
        "status": "success",
        "message": "Collection published to marketplace"
    }
    """
    try:
        # Get authenticated user
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        # Prevent publishing the Default Collection (ID 0)
        if collection_id == 0:
            return jsonify({"status": "error", "message": "The Default Collection cannot be published to the marketplace"}), 400
        
        # Get retriever and validate ownership
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        if not retriever.is_user_collection_owner(collection_id, user_uuid):
            return jsonify({"status": "error", "message": "Only collection owners can publish collections"}), 403
        
        # Parse request
        data = await request.get_json()
        visibility = data.get("visibility", "public")
        marketplace_metadata = data.get("marketplace_metadata", {})
        
        if visibility not in ["public", "unlisted"]:
            return jsonify({"status": "error", "message": "Visibility must be 'public' or 'unlisted'"}), 400
        
        # Update collection in database
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        
        # Prepare update data
        updates = {
            "visibility": visibility,
            "is_marketplace_listed": True,
            "marketplace_metadata": marketplace_metadata
        }
        
        # Update in database
        success = collection_db.update_collection(collection_id, updates)
        if not success:
            return jsonify({"status": "error", "message": "Collection not found"}), 404
        
        # Reload collections into APP_STATE
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        APP_STATE["rag_collections"] = config_manager.get_rag_collections()
        
        app_logger.info(f"User {user_uuid} published collection {collection_id} with visibility '{visibility}'")
        
        return jsonify({
            "status": "success",
            "message": "Collection published to marketplace",
            "visibility": visibility
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error publishing collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/rag/collections/<int:collection_id>/unpublish", methods=["POST"])
async def unpublish_collection_from_marketplace(collection_id: int):
    """
    Unpublish a collection from the marketplace.
    
    Removes collection from marketplace browse while preserving:
    - Existing subscriber access (read-only)
    - Ratings and reviews
    - Subscriber count (historical data)
    
    Returns:
    {
        "status": "success",
        "message": "Collection unpublished from marketplace"
    }
    """
    try:
        # Get authenticated user
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        # Get retriever and validate ownership
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        if not retriever.is_user_collection_owner(collection_id, user_uuid):
            return jsonify({"status": "error", "message": "Only collection owners can unpublish collections"}), 403
        
        # Check if collection is actually published
        coll_meta = retriever.get_collection_metadata(collection_id)
        if not coll_meta:
            return jsonify({"status": "error", "message": "Collection not found"}), 404
        
        if not coll_meta.get("is_marketplace_listed", False):
            return jsonify({"status": "error", "message": "Collection is not currently published"}), 400
        
        # Prevent unpublishing default collection (defensive check)
        default_collection_id = retriever._get_user_default_collection_id(user_uuid)
        if default_collection_id and collection_id == default_collection_id:
            return jsonify({"status": "error", "message": "Cannot unpublish your default collection"}), 400
        
        # Update collection in database
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        
        # Unpublish: Remove from marketplace but keep subscriptions active
        updates = {
            "is_marketplace_listed": False,
            "visibility": "private"  # Set to private to prevent new subscriptions
        }
        
        # Update in database
        success = collection_db.update_collection(collection_id, updates)
        if not success:
            return jsonify({"status": "error", "message": "Failed to update collection"}), 500
        
        # Reload collections into APP_STATE
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        APP_STATE["rag_collections"] = config_manager.get_rag_collections()
        
        app_logger.info(f"User {user_uuid} unpublished collection {collection_id} from marketplace")
        
        return jsonify({
            "status": "success",
            "message": "Collection unpublished from marketplace"
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error unpublishing collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route("/v1/marketplace/collections/<int:collection_id>/rate", methods=["POST"])
async def rate_marketplace_collection(collection_id: int):
    """
    Rate and review a marketplace collection.
    
    Request body:
    {
        "rating": 5,  // 1-5 stars
        "comment": "Great collection!"  // Optional
    }
    
    Returns:
    {
        "status": "success",
        "rating_id": "uuid",
        "message": "Rating submitted successfully"
    }
    """
    try:
        # Get authenticated user
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        # Parse request
        data = await request.get_json()
        rating_value = data.get("rating")
        comment = data.get("comment", "")
        
        # Validate rating
        if rating_value is None:
            return jsonify({"status": "error", "message": "Rating is required"}), 400
        
        if not isinstance(rating_value, int) or rating_value < 1 or rating_value > 5:
            return jsonify({"status": "error", "message": "Rating must be an integer between 1 and 5"}), 400
        
        # Verify collection exists
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        coll_meta = retriever.get_collection_metadata(collection_id)
        if not coll_meta:
            return jsonify({"status": "error", "message": "Collection not found"}), 404
        
        # Check if collection is marketplace-listed
        if not coll_meta.get("is_marketplace_listed", False):
            return jsonify({"status": "error", "message": "Collection is not listed in the marketplace"}), 400
        
        # Cannot rate your own collection
        if retriever.is_user_collection_owner(collection_id, user_uuid):
            return jsonify({"status": "error", "message": "You cannot rate your own collection"}), 400
        
        # Create or update rating
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import CollectionRating
        
        with get_db_session() as session:
            # Check for existing rating
            existing_rating = session.query(CollectionRating).filter_by(
                collection_id=collection_id,
                user_id=user_uuid
            ).first()
            
            if existing_rating:
                # Update existing rating
                existing_rating.rating = rating_value
                existing_rating.comment = comment
                existing_rating.updated_at = datetime.now(timezone.utc)
                rating_id = existing_rating.id
                message = "Rating updated successfully"
            else:
                # Create new rating
                new_rating = CollectionRating(
                    collection_id=collection_id,
                    user_id=user_uuid,
                    rating=rating_value,
                    comment=comment
                )
                session.add(new_rating)
                session.flush()
                rating_id = new_rating.id
                message = "Rating submitted successfully"
        
        app_logger.info(f"User {user_uuid} rated collection {collection_id}: {rating_value}/5")
        
        return jsonify({
            "status": "success",
            "rating_id": rating_id,
            "message": message
        }), 201 if message.startswith("Rating submitted") else 200
        
    except Exception as e:
        app_logger.error(f"Error rating collection: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# COST MANAGEMENT API ENDPOINTS
# ============================================================================

@rest_api_bp.route('/v1/costs/sync', methods=['POST'])
@require_admin
async def sync_costs_from_litellm():
    """
    Sync model pricing data from LiteLLM.
    Admin only endpoint.
    
    Returns:
        Sync results with counts of new/updated models
    """
    try:
        from trusted_data_agent.core.cost_manager import get_cost_manager
        
        cost_manager = get_cost_manager()
        results = cost_manager.sync_from_litellm()
        
        app_logger.info(f"LiteLLM cost sync completed: {results['synced']} models, {len(results['errors'])} errors")
        
        return jsonify({
            "status": "success",
            "synced_count": results['synced'],
            "new_models": results['new_models'],
            "updated_models": results['updated_models'],
            "errors": results['errors']
        }), 200
        
    except Exception as e:
        app_logger.error(f"Failed to sync costs: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route('/v1/costs/models', methods=['GET'])
@require_admin
async def get_all_model_costs():
    """
    Get all model pricing entries.
    Admin only endpoint.
    
    Query params:
        include_fallback: Include fallback entry (default: true)
    
    Returns:
        List of model cost entries
    """
    try:
        from trusted_data_agent.core.cost_manager import get_cost_manager
        
        include_fallback = request.args.get('include_fallback', 'true').lower() == 'true'
        
        cost_manager = get_cost_manager()
        costs = cost_manager.get_all_costs(include_fallback=include_fallback)
        
        return jsonify({
            "status": "success",
            "costs": costs,
            "count": len(costs)
        }), 200
        
    except Exception as e:
        app_logger.error(f"Failed to get model costs: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route('/v1/costs/models/<cost_id>', methods=['PUT'])
@require_admin
async def update_model_cost(cost_id: str):
    """
    Update a model cost entry (manual override).
    Admin only endpoint.
    
    Request body:
    {
        "input_cost": 0.075,
        "output_cost": 0.30,
        "notes": "Updated from official docs"
    }
    
    Returns:
        Success status
    """
    try:
        from trusted_data_agent.core.cost_manager import get_cost_manager
        
        data = await request.get_json()
        input_cost = data.get('input_cost')
        output_cost = data.get('output_cost')
        notes = data.get('notes')
        
        if input_cost is None or output_cost is None:
            return jsonify({"status": "error", "message": "input_cost and output_cost are required"}), 400
        
        cost_manager = get_cost_manager()
        success = cost_manager.update_model_cost(cost_id, input_cost, output_cost, notes)
        
        if success:
            return jsonify({"status": "success", "message": "Model cost updated"}), 200
        else:
            return jsonify({"status": "error", "message": "Model cost entry not found"}), 404
            
    except Exception as e:
        app_logger.error(f"Failed to update model cost: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route('/v1/costs/models', methods=['POST'])
@require_admin
async def add_manual_model_cost():
    """
    Add a manual cost entry for a model.
    Admin only endpoint.
    
    Request body:
    {
        "provider": "Google",
        "model": "gemini-2.0-flash",
        "input_cost": 0.075,
        "output_cost": 0.30,
        "notes": "From official pricing page"
    }
    
    Returns:
        New cost entry ID
    """
    try:
        from trusted_data_agent.core.cost_manager import get_cost_manager
        
        data = await request.get_json()
        provider = data.get('provider')
        model = data.get('model')
        input_cost = data.get('input_cost')
        output_cost = data.get('output_cost')
        notes = data.get('notes')
        
        if not all([provider, model, input_cost is not None, output_cost is not None]):
            return jsonify({
                "status": "error",
                "message": "provider, model, input_cost, and output_cost are required"
            }), 400
        
        cost_manager = get_cost_manager()
        cost_id = cost_manager.add_manual_cost(provider, model, input_cost, output_cost, notes)
        
        if cost_id:
            return jsonify({
                "status": "success",
                "cost_id": cost_id,
                "message": "Model cost added"
            }), 201
        else:
            return jsonify({
                "status": "error",
                "message": "Model cost entry already exists"
            }), 409
            
    except Exception as e:
        app_logger.error(f"Failed to add model cost: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route('/v1/costs/models/<cost_id>', methods=['DELETE'])
@require_admin
async def delete_model_cost(cost_id: str):
    """
    Delete a model cost entry.
    Admin only endpoint.
    Cannot delete fallback entries.
    
    Returns:
        Success status
    """
    try:
        from trusted_data_agent.core.cost_manager import get_cost_manager
        
        cost_manager = get_cost_manager()
        success = cost_manager.delete_model_cost(cost_id)
        
        if success:
            return jsonify({"status": "success", "message": "Model cost deleted"}), 200
        else:
            return jsonify({"status": "error", "message": "Model cost entry not found or cannot be deleted"}), 404
            
    except Exception as e:
        app_logger.error(f"Failed to delete model cost: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route('/v1/costs/fallback', methods=['PUT'])
@require_admin
async def update_fallback_cost():
    """
    Update the fallback cost for unknown models.
    Admin only endpoint.
    
    Request body:
    {
        "input_cost": 10.0,
        "output_cost": 30.0
    }
    
    Returns:
        Success status
    """
    try:
        from trusted_data_agent.core.cost_manager import get_cost_manager
        
        data = await request.get_json()
        input_cost = data.get('input_cost')
        output_cost = data.get('output_cost')
        
        if input_cost is None or output_cost is None:
            return jsonify({"status": "error", "message": "input_cost and output_cost are required"}), 400
        
        cost_manager = get_cost_manager()
        success = cost_manager.update_fallback_cost(input_cost, output_cost)
        
        if success:
            return jsonify({"status": "success", "message": "Fallback cost updated"}), 200
        else:
            return jsonify({"status": "error", "message": "Failed to update fallback cost"}), 500
            
    except Exception as e:
        app_logger.error(f"Failed to update fallback cost: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@rest_api_bp.route('/v1/costs/analytics', methods=['GET'])
@require_admin
async def get_cost_analytics():
    """
    Get comprehensive cost analytics across all sessions.
    Admin only endpoint.
    
    Returns:
        Detailed cost analytics including:
        - Total costs by provider/model
        - Cost trends over time
        - Most expensive sessions/queries
        - Average costs per turn/session
    """
    try:
        from trusted_data_agent.core.cost_manager import get_cost_manager
        from pathlib import Path
        
        user_uuid = _get_user_uuid_from_request()
        cost_manager = get_cost_manager()
        
        project_root = Path(__file__).resolve().parents[3]
        sessions_base = project_root / 'tda_sessions'
        
        # Determine which sessions to scan
        if APP_CONFIG.SESSIONS_FILTER_BY_USER:
            sessions_root = sessions_base / user_uuid
            if not sessions_root.exists():
                return jsonify({
                    "total_cost": 0.0,
                    "cost_by_provider": {},
                    "cost_by_model": {},
                    "avg_cost_per_session": 0.0,
                    "avg_cost_per_turn": 0.0,
                    "most_expensive_sessions": [],
                    "most_expensive_queries": [],
                    "cost_trend": []
                }), 200
            scan_dirs = [sessions_root]
        else:
            if not sessions_base.exists():
                return jsonify({
                    "total_cost": 0.0,
                    "cost_by_provider": {},
                    "cost_by_model": {},
                    "avg_cost_per_session": 0.0,
                    "avg_cost_per_turn": 0.0,
                    "most_expensive_sessions": [],
                    "most_expensive_queries": [],
                    "cost_trend": []
                }), 200
            scan_dirs = [d for d in sessions_base.iterdir() if d.is_dir()]
        
        # Initialize analytics
        total_cost = 0.0
        cost_by_provider = {}
        cost_by_model = {}
        session_costs = []
        query_costs = []
        total_turns = 0
        total_sessions = 0
        cost_by_date = {}
        
        # Scan all session files
        for session_dir in scan_dirs:
            for session_file in session_dir.glob('*.json'):
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                    
                    total_sessions += 1
                    session_cost = 0.0
                    session_id = session_data.get('id', session_file.stem)
                    session_date = session_data.get('created_at', '')[:10] if session_data.get('created_at') else 'unknown'
                    
                    # Analyze workflow history for token costs
                    workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', [])
                    for turn in workflow_history:
                        if not turn.get('isValid', True):
                            continue
                        
                        total_turns += 1
                        provider = turn.get('provider', 'Unknown')
                        model = turn.get('model', 'unknown')
                        input_tokens = turn.get('turn_input_tokens', 0)
                        output_tokens = turn.get('turn_output_tokens', 0)
                        
                        # Calculate cost for this turn
                        turn_cost = cost_manager.calculate_cost(provider, model, input_tokens, output_tokens)
                        session_cost += turn_cost
                        
                        # Track by provider
                        cost_by_provider[provider] = cost_by_provider.get(provider, 0.0) + turn_cost
                        
                        # Track by model
                        model_key = f"{provider}/{model}"
                        cost_by_model[model_key] = cost_by_model.get(model_key, 0.0) + turn_cost
                        
                        # Track expensive queries
                        query_costs.append({
                            'query': turn.get('user_query', '')[:100],
                            'cost': turn_cost,
                            'provider': provider,
                            'model': model,
                            'tokens': input_tokens + output_tokens,
                            'session_id': session_id,
                            'timestamp': turn.get('timestamp', '')
                        })
                    
                    # Track session cost
                    if session_cost > 0:
                        session_costs.append({
                            'session_id': session_id,
                            'cost': session_cost,
                            'turns': len(workflow_history),
                            'created_at': session_data.get('created_at', '')
                        })
                        
                        # Track cost by date
                        cost_by_date[session_date] = cost_by_date.get(session_date, 0.0) + session_cost
                    
                    total_cost += session_cost
                    
                except Exception as e:
                    app_logger.warning(f"Error processing session file {session_file.name}: {e}")
                    continue
        
        # Calculate averages
        avg_cost_per_session = total_cost / total_sessions if total_sessions > 0 else 0.0
        avg_cost_per_turn = total_cost / total_turns if total_turns > 0 else 0.0
        
        # Sort and get top expensive items
        session_costs.sort(key=lambda x: x['cost'], reverse=True)
        query_costs.sort(key=lambda x: x['cost'], reverse=True)
        
        # Sort cost by model (descending)
        cost_by_model_sorted = dict(sorted(cost_by_model.items(), key=lambda x: x[1], reverse=True))
        
        # Cost trend (daily)
        cost_trend = [{"date": date, "cost": cost} for date, cost in sorted(cost_by_date.items())]
        
        return jsonify({
            "total_cost": round(total_cost, 2),
            "cost_by_provider": {k: round(v, 2) for k, v in cost_by_provider.items()},
            "cost_by_model": {k: round(v, 4) for k, v in list(cost_by_model_sorted.items())[:20]},  # Top 20 models
            "avg_cost_per_session": round(avg_cost_per_session, 4),
            "avg_cost_per_turn": round(avg_cost_per_turn, 4),
            "most_expensive_sessions": session_costs[:10],
            "most_expensive_queries": query_costs[:20],
            "cost_trend": cost_trend[-30:],  # Last 30 days
            "total_sessions": total_sessions,
            "total_turns": total_turns
        }), 200
        
    except Exception as e:
        app_logger.error(f"Failed to get cost analytics: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
