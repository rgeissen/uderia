# src/trusted_data_agent/core/configuration_service.py
import logging
import httpx
import os
# --- MODIFICATION START: Import Path ---
from pathlib import Path
# --- MODIFICATION END ---

from google.api_core import exceptions as google_exceptions
from anthropic import APIError, AsyncAnthropic
from openai import AsyncOpenAI, APIError as OpenAI_APIError, AsyncAzureOpenAI
from botocore.exceptions import ClientError
import google.generativeai as genai
import boto3
from langchain_mcp_adapters.client import MultiServerMCPClient

from trusted_data_agent.core.config import (
    APP_CONFIG, APP_STATE,
    set_user_provider, set_user_model, set_user_aws_region,
    set_user_azure_deployment_details, set_user_friendli_details,
    set_user_model_provider_in_profile,
    set_user_mcp_server_id, set_user_llm_instance, set_user_mcp_client,
    set_user_server_configs
)
from trusted_data_agent.llm import handler as llm_handler
from trusted_data_agent.mcp_adapter import adapter as mcp_adapter
from trusted_data_agent.core.utils import unwrap_exception, _regenerate_contexts
# --- MODIFICATION START: Import RAGRetriever, config_manager, and encryption ---
from trusted_data_agent.agent.rag_retriever import RAGRetriever
from trusted_data_agent.core.config_manager import get_config_manager

# Authentication is always enabled - import encryption module
from trusted_data_agent.auth import encryption, audit
ENCRYPTION_AVAILABLE = True
# --- MODIFICATION END ---

app_logger = logging.getLogger("quart.app")


def build_mcp_server_config(server_id: str, server_data: dict) -> dict:
    """
    Build MCP server configuration for MultiServerMCPClient based on transport type.

    Args:
        server_id: Server ID (used as key in connections dict)
        server_data: Server configuration from database

    Returns:
        dict: Configuration dict compatible with MultiServerMCPClient

    Raises:
        ValueError: If transport type is unsupported or configuration is invalid
    """
    transport_info = server_data.get('transport', {})
    transport_type = transport_info.get('type', 'sse')  # Default to SSE for backwards compatibility

    # Handle stdio transport
    if transport_type == 'stdio':
        command = transport_info.get('command', '')
        args = transport_info.get('args', [])
        env = transport_info.get('env')
        cwd = transport_info.get('cwd')

        if not command:
            raise ValueError(f"stdio transport requires 'command' field")

        config = {
            'transport': 'stdio',
            'command': command,
            'args': args,
            'env': env,
            'cwd': cwd,
            'encoding': 'utf-8',
            'encoding_error_handler': 'strict'
        }

        app_logger.info(f"Building stdio config for {server_id}: {command} {' '.join(args)}")
        return {server_id: config}

    # Handle SSE/HTTP transports (existing behavior)
    elif transport_type in ('sse', 'http', 'streamable_http'):
        host = server_data.get('host')
        port = server_data.get('port')
        path = server_data.get('path')

        if not all([host, port, path]):
            raise ValueError(f"SSE/HTTP transport requires host, port, and path")

        # Detect stdio server being passed without transport info
        if host == 'stdio' or str(port) == '0':
            raise ValueError(
                f"Server appears to be stdio-based (host={host}, port={port}) but transport info is missing. "
                "Ensure 'transport' field is included with type='stdio', command, and args."
            )

        # Build URL
        mcp_server_url = f"http://{host}:{port}{path}"

        config = {
            'transport': 'streamable_http',
            'url': mcp_server_url
        }

        app_logger.info(f"Building HTTP config for {server_id}: {mcp_server_url}")
        return {server_id: config}

    else:
        raise ValueError(f"Unsupported transport type: {transport_type}")


def load_profile_classification_into_state(profile_id: str, user_uuid: str) -> bool:
    """
    Load cached classification results from a profile into APP_STATE.
    If the profile has inherit_classification=true, loads from the default profile instead.
    Returns True if cached results were loaded, False if classification needs to run.
    """
    config_manager = get_config_manager()
    profile = config_manager.get_profile(profile_id, user_uuid)
    
    if not profile:
        app_logger.warning(f"Profile {profile_id} not found")
        return False
    
    # Check if this profile inherits classification from master classification profile
    target_profile_id = profile_id
    if profile.get('inherit_classification', False):
        # Use master classification profile instead of default profile for inheritance
        master_profile_id = config_manager.get_master_classification_profile_id(user_uuid)
        if master_profile_id and master_profile_id != profile_id:
            app_logger.info(f"Profile {profile_id} inherits classification from master classification profile {master_profile_id}")
            target_profile_id = master_profile_id
            profile = config_manager.get_profile(master_profile_id, user_uuid)
            if not profile:
                app_logger.warning(f"Master classification profile {master_profile_id} not found")
                return False
        else:
            # Fallback: Use default profile if no master set (backward compatibility)
            default_profile_id = config_manager.get_default_profile_id(user_uuid)
            if default_profile_id and default_profile_id != profile_id:
                app_logger.warning(f"No master classification profile set, falling back to default profile {default_profile_id} for inheritance")
                target_profile_id = default_profile_id
                profile = config_manager.get_profile(default_profile_id, user_uuid)
                if not profile:
                    app_logger.warning(f"Default profile {default_profile_id} not found")
                    return False
    
    classification_results = config_manager.get_profile_classification(target_profile_id, user_uuid)
    
    # Check if we have cached results with actual content
    tools_dict = classification_results.get('tools', {}) if classification_results else {}
    prompts_dict = classification_results.get('prompts', {}) if classification_results else {}
    
    # Count actual tools/prompts in the classification
    total_tools = sum(len(tools) for tools in tools_dict.values()) if tools_dict else 0
    total_prompts = sum(len(prompts) for prompts in prompts_dict.values()) if prompts_dict else 0
    
    if not classification_results or (total_tools == 0 and total_prompts == 0):
        app_logger.info(f"No cached classification for profile {target_profile_id} (empty or missing), will run classification")
        return False
    
    # Check if classification mode matches what was used
    classification_mode = profile.get('classification_mode', 'full')
    cached_mode = classification_results.get('classified_with_mode')
    
    if cached_mode and cached_mode != classification_mode:
        app_logger.info(f"Classification mode changed from '{cached_mode}' to '{classification_mode}', will reclassify")
        return False
    
    # Load ALL cached results into APP_STATE (UI will show active/inactive based on disabled lists)
    APP_STATE['structured_tools'] = classification_results.get('tools', {})
    APP_STATE['structured_prompts'] = classification_results.get('prompts', {})
    APP_STATE['structured_resources'] = classification_results.get('resources', {})
    
    # Reconstruct mcp_tools and mcp_prompts dictionaries from structured data
    # This is needed for the agent execution and validation checks
    # We need to create simple objects that have attributes (not just dicts)
    class SimpleTool:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    
    mcp_tools_dict = {}
    for category, tool_list in APP_STATE['structured_tools'].items():
        for tool_info in tool_list:
            # Convert 'arguments' list to 'args' dict format expected by SimpleTool
            arguments_list = tool_info.get('arguments', [])
            args_dict = {arg['name']: arg for arg in arguments_list}
            
            # Create a SimpleTool object with proper attributes
            mcp_tools_dict[tool_info['name']] = SimpleTool(
                name=tool_info['name'],
                description=tool_info.get('description', ''),
                args=args_dict
            )
    APP_STATE['mcp_tools'] = mcp_tools_dict
    
    mcp_prompts_dict = {}
    for category, prompt_list in APP_STATE['structured_prompts'].items():
        for prompt_info in prompt_list:
            # Create a simple object with the prompt info as attributes
            # Prompts may also have arguments, convert if present
            arguments_list = prompt_info.get('arguments', [])
            args_dict = {arg['name']: arg for arg in arguments_list} if arguments_list else {}
            
            mcp_prompts_dict[prompt_info['name']] = SimpleTool(
                name=prompt_info['name'],
                description=prompt_info.get('description', ''),
                args=args_dict
            )
    APP_STATE['mcp_prompts'] = mcp_prompts_dict
    
    app_logger.info(f"Loaded cached classification for profile {profile_id} (mode: {classification_mode})")
    app_logger.info(f"  - {len(APP_STATE['structured_tools'])} tool categories, {len(mcp_tools_dict)} total tools")
    app_logger.info(f"  - {len(APP_STATE['structured_prompts'])} prompt categories, {len(mcp_prompts_dict)} total prompts")
    app_logger.info(f"  - {len(APP_STATE['structured_resources'])} resource categories")
    
    return True


async def switch_profile_context(profile_id: str, user_uuid: str, validate_llm: bool = False) -> dict:
    """
    Switch the active profile context, loading its classification and configuration.
    This initializes the MCP client and loads cached classification data.
    
    Args:
        profile_id: ID of the profile to switch to
        user_uuid: User UUID for per-user context
        validate_llm: If True, validates LLM client (required for conversation)
                     If False, skips LLM validation (for resource viewing only)
    
    Returns a result dict with status and message.
    """
    config_manager = get_config_manager()
    profile = config_manager.get_profile(profile_id, user_uuid)
    
    if not profile:
        return {
            "status": "error",
            "message": f"Profile {profile_id} not found"
        }
    
    try:
        # Update runtime state
        APP_CONFIG.CURRENT_PROFILE_ID = profile_id
        classification_mode = profile.get('classification_mode', 'light')
        APP_CONFIG.CURRENT_PROFILE_CLASSIFICATION_MODE = classification_mode
        
        app_logger.info(f"Switching to profile {profile_id} (classification mode: {classification_mode}, validate_llm: {validate_llm})")
        
        # Load LLM configuration from profile
        llm_config_id = profile.get('llmConfigurationId')
        if not llm_config_id:
            return {
                "status": "error",
                "message": f"Profile {profile_id} has no llmConfigurationId configured"
            }
        
        llm_configs = config_manager.get_llm_configurations(user_uuid)
        llm_config = next((c for c in llm_configs if c.get('id') == llm_config_id), None)
        
        if not llm_config:
            return {
                "status": "error",
                "message": f"LLM configuration {llm_config_id} not found"
            }
        
        provider = llm_config.get('provider')
        model = llm_config.get('model')
        credentials = llm_config.get('credentials', {})
        
        app_logger.info(f"Initializing LLM client for profile {profile_id}: {provider}/{model}")
        
        # Load stored credentials if available - use user_uuid to look up user_id for encrypted credentials
        if ENCRYPTION_AVAILABLE and user_uuid:
            try:
                from trusted_data_agent.auth.models import User
                from trusted_data_agent.auth.database import get_db_session
                
                # Look up user by id
                with get_db_session() as session:
                    user = session.query(User).filter_by(id=user_uuid).first()
                    if user:
                        app_logger.info(f"Loading credentials for user {user.id}, provider {provider}")
                        stored_result = await retrieve_credentials_for_provider(user.id, provider)
                        if stored_result.get("credentials"):
                            credentials = {**stored_result["credentials"], **credentials}
                            app_logger.info(f"✓ Successfully loaded stored credentials for {provider}")
                        else:
                            app_logger.warning(f"No stored credentials found for {provider} (status: {stored_result.get('status')})")
                    else:
                        app_logger.warning(f"No user found for user_uuid={user_uuid}, cannot load stored credentials")
            except Exception as e:
                app_logger.error(f"Error loading stored credentials: {e}", exc_info=True)
        
        # Fall back to environment variables if no credentials in config or store
        import os
        if not credentials.get("apiKey") and not credentials.get("friendli_token") and not credentials.get("aws_access_key_id"):
            app_logger.info(f"No credentials in config/store, checking environment variables for {provider}")
            if provider == "Google":
                env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                if env_key:
                    credentials["apiKey"] = env_key
                    app_logger.info("Loaded Google API key from environment")
            elif provider == "Anthropic":
                env_key = os.environ.get("ANTHROPIC_API_KEY")
                if env_key:
                    credentials["apiKey"] = env_key
                    app_logger.info("Loaded Anthropic API key from environment")
            elif provider == "OpenAI":
                env_key = os.environ.get("OPENAI_API_KEY")
                if env_key:
                    credentials["apiKey"] = env_key
                    app_logger.info("Loaded OpenAI API key from environment")
            elif provider == "Azure":
                credentials["apiKey"] = os.environ.get("AZURE_OPENAI_API_KEY")
                credentials["azure_endpoint"] = os.environ.get("AZURE_OPENAI_ENDPOINT")
                credentials["azure_deployment_name"] = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
                credentials["azure_api_version"] = os.environ.get("AZURE_OPENAI_API_VERSION")
                if any(credentials.values()):
                    app_logger.info("Loaded Azure credentials from environment")
            elif provider == "Friendli":
                credentials["friendli_token"] = os.environ.get("FRIENDLI_TOKEN")
                credentials["friendli_endpoint_url"] = os.environ.get("FRIENDLI_ENDPOINT_URL")
                if credentials["friendli_token"]:
                    app_logger.info("Loaded Friendli credentials from environment")
            elif provider == "Amazon":
                credentials["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID")
                credentials["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY")
                credentials["aws_region"] = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
                if credentials["aws_access_key_id"]:
                    app_logger.info("Loaded AWS credentials from environment")
            elif provider == "Ollama":
                credentials["ollama_host"] = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
                app_logger.info("Using Ollama host from environment")
        
        # Initialize and optionally validate LLM client
        temp_llm_instance = None
        if validate_llm or credentials:  # Create instance if validating OR if credentials are available
            # Create LLM client (with optional validation test)
            try:
                if provider == "Google":
                    genai.configure(api_key=credentials.get("apiKey"))
                    temp_llm_instance = genai.GenerativeModel(model)
                    if validate_llm:
                        await temp_llm_instance.generate_content_async("test", generation_config={"max_output_tokens": 1})
                
                elif provider == "Anthropic":
                    temp_llm_instance = AsyncAnthropic(api_key=credentials.get("apiKey"))
                    if validate_llm:
                        await temp_llm_instance.models.list()
                
                elif provider == "OpenAI":
                    temp_llm_instance = AsyncOpenAI(api_key=credentials.get("apiKey"))
                    if validate_llm:
                        await temp_llm_instance.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": "test"}],
                            max_tokens=1
                        )
                
                elif provider == "Azure":
                    temp_llm_instance = AsyncAzureOpenAI(
                        api_key=credentials.get("apiKey"),
                        azure_endpoint=credentials.get("azure_endpoint"),
                        api_version=credentials.get("azure_api_version")
                    )
                    if validate_llm:
                        await temp_llm_instance.chat.completions.create(
                            model=credentials.get("azure_deployment_name"),
                            messages=[{"role": "user", "content": "test"}],
                            max_tokens=1
                        )
                
                elif provider == "Friendli":
                    is_dedicated = bool(credentials.get("friendli_endpoint_url"))
                    if is_dedicated:
                        temp_llm_instance = AsyncOpenAI(
                            api_key=credentials.get("friendli_token"),
                            base_url=credentials.get("friendli_endpoint_url")
                        )
                    else:
                        temp_llm_instance = AsyncOpenAI(
                            api_key=credentials.get("friendli_token"),
                            base_url="https://api.friendli.ai/serverless/v1"
                        )
                    if validate_llm:
                        await temp_llm_instance.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": "test"}],
                            max_tokens=1
                        )
                
                elif provider == "Amazon":
                    aws_region = credentials.get("aws_region")
                    temp_llm_instance = boto3.client(
                        service_name='bedrock-runtime',
                        aws_access_key_id=credentials.get("aws_access_key_id"),
                        aws_secret_access_key=credentials.get("aws_secret_access_key"),
                        region_name=aws_region
                    )
                    if validate_llm:
                        app_logger.info("Boto3 client for Bedrock validated")
                    else:
                        app_logger.info("Boto3 client for Bedrock created (validation skipped)")
                
                elif provider == "Ollama":
                    host = credentials.get("ollama_host")
                    if not host:
                        raise ValueError("Ollama host is required")
                    temp_llm_instance = llm_handler.OllamaClient(host=host)
                    if validate_llm:
                        await temp_llm_instance.list_models()
                
                else:
                    raise ValueError(f"Unsupported provider: {provider}")
                
                app_logger.info(f"LLM client validated successfully: {provider}/{model}")
                
            except Exception as e:
                app_logger.error(f"Failed to initialize LLM client: {e}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Failed to initialize LLM client: {str(e)}"
                }
        else:
            # Skip validation - just set configuration (client will be created on first message)
            app_logger.info(f"LLM configuration loaded without validation: {provider}/{model}")
        
        # Store LLM client and configuration
        set_user_provider(provider, user_uuid)
        set_user_model(model, user_uuid)
        if temp_llm_instance:
            set_user_llm_instance(temp_llm_instance, user_uuid)
        else:
            # Set placeholder for resource loading
            APP_STATE['llm'] = {"placeholder": True, "provider": provider, "model": model}
        APP_CONFIG.ACTIVE_PROVIDER = provider
        APP_CONFIG.ACTIVE_MODEL = model
        
        # Store provider-specific credentials
        if provider == "Azure":
            azure_details = {
                "endpoint": credentials.get("azure_endpoint"),
                "deployment_name": credentials.get("azure_deployment_name"),
                "api_version": credentials.get("azure_api_version")
            }
            set_user_azure_deployment_details(azure_details, user_uuid)
        elif provider == "Friendli":
            friendli_details = {
                "token": credentials.get("friendli_token"),
                "endpoint_url": credentials.get("friendli_endpoint_url")
            }
            set_user_friendli_details(friendli_details, user_uuid)
        elif provider == "Amazon":
            set_user_aws_region(credentials.get("aws_region"), user_uuid)
            # Extract provider from inference profile ARN if applicable
            if model.startswith("arn:aws:bedrock:"):
                try:
                    profile_part = model.split('/')[-1]
                    model_provider = profile_part.split('.')[1]
                    set_user_model_provider_in_profile(model_provider, user_uuid)
                    app_logger.info(f"Detected inference profile provider: {model_provider}")
                except Exception as e:
                    app_logger.warning(f"Failed to extract provider from inference profile ARN: {e}")
                    set_user_model_provider_in_profile(None, user_uuid)
            else:
                set_user_model_provider_in_profile(None, user_uuid)
        
        # Load MCP server configuration from profile (skip for llm_only profiles)
        profile_type = profile.get('profile_type', 'tool_enabled')
        cached_loaded = None  # Initialize for both paths

        if profile_type == 'tool_enabled':
            # Tool-enabled profiles require MCP server
            mcp_server_id = profile.get('mcpServerId')
            if not mcp_server_id:
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} has no mcpServerId configured"
                }

            mcp_servers = config_manager.get_mcp_servers(user_uuid)
            mcp_server = next((s for s in mcp_servers if s.get('id') == mcp_server_id), None)

            if not mcp_server:
                return {
                    "status": "error",
                    "message": f"MCP server {mcp_server_id} not found in configuration"
                }

            server_name = mcp_server.get('name')  # For logging only
            app_logger.info(f"Initializing MCP client for profile {profile_id} (server: {server_name}, ID: {mcp_server_id})")

            # Initialize and validate MCP client
            try:
                import asyncio

                # Build server config based on transport type
                server_configs = build_mcp_server_config(mcp_server_id, mcp_server)
                temp_mcp_client = MultiServerMCPClient(server_configs)

                # Test MCP connection with 10 second timeout
                app_logger.info(f"Testing MCP connection to {server_name} (ID: {mcp_server_id})...")
                async def test_mcp():
                    # Use server ID for session, not name
                    async with temp_mcp_client.session(mcp_server_id) as temp_session:
                        await temp_session.list_tools()

                await asyncio.wait_for(test_mcp(), timeout=10.0)
                app_logger.info(f"MCP server connection validated successfully: {server_name} (ID: {mcp_server_id})")

            except asyncio.TimeoutError:
                app_logger.error(f"MCP server connection timed out after 10 seconds: {server_name} (ID: {mcp_server_id})")
                return {
                    "status": "error",
                    "message": f"MCP server connection timed out. Server may be down or unreachable: {server_name}"
                }
            except Exception as e:
                app_logger.error(f"Failed to initialize MCP client: {e}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Failed to connect to MCP server: {str(e)}"
                }

            # Store MCP client in APP_STATE
            set_user_mcp_client(temp_mcp_client, user_uuid)
            set_user_server_configs(server_configs, user_uuid)
            # Server name no longer stored - only ID is needed for session management
            set_user_mcp_server_id(mcp_server_id, user_uuid)

            APP_CONFIG.MCP_SERVER_CONNECTED = True
            APP_CONFIG.SERVICES_CONFIGURED = True

            app_logger.info(f"Profile {profile_id} fully initialized and validated")

            # Try to load cached classification
            app_logger.info(f"Checking for cached classification for profile {profile_id}...")
            cached_loaded = load_profile_classification_into_state(profile_id, user_uuid)
            app_logger.info(f"Cached classification loaded: {cached_loaded}")

            # If no cache, run classification
            if not cached_loaded:
                app_logger.info(f"No cached classification, running classification for profile {profile_id}")
                await mcp_adapter.load_and_categorize_mcp_resources(APP_STATE, user_uuid, profile_id)

                # After first classification, initialize profile's enabled tools/prompts with ALL discovered capabilities
                # This makes all capabilities enabled by default, simplifying the selection process
                profile = config_manager.get_profile(profile_id, user_uuid)
                if profile and (not profile.get("tools") or len(profile.get("tools", [])) == 0):
                    # Get all discovered tools from APP_STATE
                    all_tools = list(APP_STATE.get('mcp_tools', {}).keys())
                    all_prompts = list(APP_STATE.get('mcp_prompts', {}).keys())

                    if all_tools or all_prompts:
                        app_logger.info(f"Initializing profile {profile_id} with all discovered capabilities: {len(all_tools)} tools, {len(all_prompts)} prompts")
                        config_manager.update_profile(profile_id, {
                            "tools": all_tools,
                            "prompts": all_prompts
                        }, user_uuid)

                # Clear needs_reclassification flag after successful classification
                config_manager.update_profile(profile_id, {"needs_reclassification": False}, user_uuid)
                app_logger.info(f"Cleared needs_reclassification flag for profile {profile_id} after classification")
            else:
                # For cached classification, also ensure profile has tools/prompts initialized
                # This fixes the bug where cached profiles had all resources deactivated
                app_logger.info(f"Using cached classification for profile {profile_id}, checking profile initialization...")
                profile = config_manager.get_profile(profile_id, user_uuid)
                if profile and (not profile.get("tools") or len(profile.get("tools", [])) == 0):
                    # Profile doesn't have tools list yet - initialize with all discovered tools from cache
                    all_tools = list(APP_STATE.get('mcp_tools', {}).keys())
                    all_prompts = list(APP_STATE.get('mcp_prompts', {}).keys())

                    if all_tools or all_prompts:
                        app_logger.info(f"Initializing cached profile {profile_id} with all discovered capabilities: {len(all_tools)} tools, {len(all_prompts)} prompts")
                        config_manager.update_profile(profile_id, {
                            "tools": all_tools,
                            "prompts": all_prompts
                        }, user_uuid)
        else:
            # LLM-only profile - skip MCP setup
            app_logger.info(f"Profile {profile_id} is llm_only - skipping MCP server initialization")
            APP_CONFIG.MCP_SERVER_CONNECTED = False
            APP_CONFIG.SERVICES_CONFIGURED = True

            # Clear disabled tools/prompts for llm_only profiles
            APP_STATE["disabled_tools"] = []
            APP_STATE["disabled_prompts"] = []

        # Calculate disabled tools/prompts from profile's enabled lists (for tool-enabled profiles)
        if profile_type == 'tool_enabled':
            APP_STATE["disabled_tools"] = config_manager.get_profile_disabled_tools(profile_id, user_uuid)
            APP_STATE["disabled_prompts"] = config_manager.get_profile_disabled_prompts(profile_id, user_uuid)

            app_logger.info(f"Loaded profile {profile_id}: {len(APP_STATE['disabled_tools'])} disabled tools, {len(APP_STATE['disabled_prompts'])} disabled prompts")

            # Regenerate contexts with new classification
            _regenerate_contexts()
        
        return {
            "status": "success",
            "message": f"Switched to profile {profile_id}",
            "classification_mode": classification_mode,
            "used_cache": cached_loaded
        }
    
    except Exception as e:
        app_logger.error(f"Failed to switch profile context: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to switch profile: {str(e)}"
        }


async def setup_and_categorize_services(config_data: dict) -> dict:
    """
    A centralized, atomic, and lock-protected service to configure the entire
    application. It validates connections, sets up clients, and runs the
    automatic, LLM-based capability classification.
    """
    # --- Use the global lock to prevent race conditions ---
    async with APP_STATE["configuration_lock"]:
        app_logger.info("Configuration lock acquired. Starting service setup...")
        
        provider = config_data.get("provider")
        model = config_data.get("model")
        server_name = config_data.get("mcp_server", {}).get("name") or config_data.get("server_name")
        server_id = config_data.get("mcp_server", {}).get("id") or config_data.get("server_id")
        tts_credentials_json = config_data.get("tts_credentials_json")
        user_uuid = config_data.get("user_uuid")  # Extract user_uuid for per-user isolation

        # Determine if MCP server configuration is provided
        # MCP server is optional for llm_only and rag_focused profiles
        has_mcp_config = bool(server_name and server_id)

        # Check if already configured (skip MCP check if no MCP config provided)
        is_already_configured = (
            APP_CONFIG.SERVICES_CONFIGURED and
            provider == APP_CONFIG.ACTIVE_PROVIDER and
            model == APP_CONFIG.ACTIVE_MODEL and
            (not has_mcp_config or server_id == APP_CONFIG.CURRENT_MCP_SERVER_ID)
        )

        if is_already_configured:
            app_logger.info("Bypassing configuration: The requested configuration is already active.")
            return {"status": "success", "message": f"Services are already configured with the requested settings."}

        temp_llm_instance = None
        temp_mcp_client = None
        
        try:
            app_logger.info(f"Validating credentials for provider: {provider}")
            
            # --- 1. LLM Client Validation ---
            credentials = config_data.get("credentials", {})
            
            # --- Always try to load stored credentials from database ---
            if user_uuid and ENCRYPTION_AVAILABLE:
                app_logger.info(f"Attempting to load stored credentials for provider: {provider}")
                from trusted_data_agent.auth.encryption import decrypt_credentials
                
                stored_creds = decrypt_credentials(user_uuid, provider)
                
                if stored_creds:
                    # Merge stored credentials with provided credentials (provided takes precedence)
                    credentials = {**stored_creds, **credentials}
                    app_logger.info(f"Loaded stored credential fields for {provider}")
                else:
                    app_logger.warning(f"No stored credentials found for {provider}, using provided credentials only")
            # --- END credential loading ---
            if provider == "Google":
                genai.configure(api_key=credentials.get("apiKey"))
                temp_llm_instance = genai.GenerativeModel(model)
                await temp_llm_instance.generate_content_async("test", generation_config={"max_output_tokens": 1})
            
            elif provider == "Anthropic":
                temp_llm_instance = AsyncAnthropic(api_key=credentials.get("apiKey"))
                await temp_llm_instance.models.list()

            elif provider in ["OpenAI", "Azure", "Friendli"]:
                if provider == "OpenAI":
                    temp_llm_instance = AsyncOpenAI(api_key=credentials.get("apiKey"))
                    await temp_llm_instance.models.list()

                elif provider == "Azure":
                    temp_llm_instance = AsyncAzureOpenAI(
                        api_key=credentials.get("azure_api_key"),
                        azure_endpoint=credentials.get("azure_endpoint"),
                        api_version=credentials.get("azure_api_version")
                    )
                    await temp_llm_instance.chat.completions.create(model=model, messages=[{"role": "user", "content": "test"}], max_tokens=1)
                
                elif provider == "Friendli":
                    friendli_api_key = credentials.get("friendli_token")
                    endpoint_url = credentials.get("friendli_endpoint_url")
                    
                    app_logger.info(f"Friendli.ai API Key status: {'Provided' if friendli_api_key else 'Missing/Empty'}")
                    if not friendli_api_key:
                        raise ValueError("Friendli.ai API key is required but was not provided in the configuration.")

                    if endpoint_url: # Dedicated Endpoint: Validate by listing models
                        app_logger.info("Validating Friendli.ai Dedicated Endpoint by listing models.")
                        validation_url = f"{endpoint_url.rstrip('/')}/v1/models"
                        headers = {"Authorization": f"Bearer {friendli_api_key}"}
                        async with httpx.AsyncClient() as client:
                            response = await client.get(validation_url, headers=headers)
                            response.raise_for_status()
                        temp_llm_instance = AsyncOpenAI(api_key=friendli_api_key, base_url=endpoint_url)
                        app_logger.info("Friendli.ai Dedicated Endpoint connection validated successfully.")
                    else: # Serverless Endpoint: Validate with a test completion call
                        app_logger.info(f"Validating Friendli.ai Serverless Endpoint with model '{model}'.")
                        if not model:
                            raise ValueError("A Model ID is required for Friendli.ai Serverless Endpoint configuration.")
                        
                        # --- MODIFICATION START: Correct the base_url for serverless endpoints ---
                        temp_llm_instance = AsyncOpenAI(api_key=friendli_api_key, base_url="https://api.friendli.ai/serverless/v1")
                        # --- MODIFICATION END ---
                        await temp_llm_instance.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": "test"}],
                            max_tokens=1
                        )
                        app_logger.info("Friendli.ai Serverless Endpoint token and model ID validated successfully.")

            elif provider == "Amazon":
                aws_region = credentials.get("aws_region")
                temp_llm_instance = boto3.client(
                    service_name='bedrock-runtime',
                    aws_access_key_id=credentials.get("aws_access_key_id"),
                    aws_secret_access_key=credentials.get("aws_secret_access_key"),
                    region_name=aws_region
                )
                app_logger.info("Boto3 client for Bedrock created. Skipping pre-flight model invocation.")

            elif provider == "Ollama":
                host = credentials.get("ollama_host")
                if not host:
                    raise ValueError("Ollama host is required.")
                temp_llm_instance = llm_handler.OllamaClient(host=host)
                await temp_llm_instance.list_models()
            else:
                raise NotImplementedError(f"Provider '{provider}' is not yet supported.")
            app_logger.info("LLM credentials/connection validated successfully.")

            # --- 2. MCP Client Validation (Optional - only for tool_enabled profiles) ---
            temp_server_configs = None
            if has_mcp_config:
                mcp_server_config = config_data.get("mcp_server", {})
                app_logger.info(f"Connecting to MCP server: {server_name} (ID: {server_id})")

                # Build server config based on transport type
                temp_server_configs = build_mcp_server_config(server_id, mcp_server_config)
                temp_mcp_client = MultiServerMCPClient(temp_server_configs)
                async with temp_mcp_client.session(server_id) as temp_session:
                    await temp_session.list_tools()
                app_logger.info(f"MCP server connection validated successfully (ID: {server_id})")
            else:
                app_logger.info("No MCP server configuration provided. Skipping MCP validation (llm_only or rag_focused profile).")

            app_logger.info("All validations passed. Committing configuration to application state.")
            
            # --- PHASE 4: Optionally save credentials after successful validation ---
            save_credentials = config_data.get("save_credentials", False)
            if save_credentials and user_uuid and ENCRYPTION_AVAILABLE and not use_stored_credentials:
                # Only save if not using already-stored credentials
                try:
                    save_result = await store_credentials_for_provider(user_uuid, provider, credentials)
                    if save_result.get("status") == "success":
                        app_logger.info(f"Saved validated credentials for {provider}")
                except Exception as e:
                    # Don't fail configuration if credential save fails
                    app_logger.warning(f"Failed to save credentials: {e}")
            # --- END PHASE 4 ---
            
            # --- 3. Commit to Global State (with per-user isolation support) ---
            set_user_provider(provider, user_uuid)
            set_user_model(model, user_uuid)
            set_user_aws_region(credentials.get("aws_region") if provider == "Amazon" else None, user_uuid)
            
            if provider == "Azure":
                azure_details = {
                    "endpoint": credentials.get("azure_endpoint"),
                    "deployment_name": credentials.get("azure_deployment_name"),
                    "api_version": credentials.get("azure_api_version")
                }
                set_user_azure_deployment_details(azure_details, user_uuid)
            
            if provider == "Friendli":
                is_dedicated = bool(credentials.get("friendli_endpoint_url"))
                friendli_details = {
                    "token": credentials.get("friendli_token"),
                    "endpoint_url": credentials.get("friendli_endpoint_url"),
                    "models_path": "/v1/models" if is_dedicated else None # No path for serverless
                }
                set_user_friendli_details(friendli_details, user_uuid)
            
            set_user_model_provider_in_profile(None, user_uuid)

            # Only set MCP-related state if MCP configuration was provided
            if has_mcp_config:
                # Server name no longer stored - only ID is needed for session management
                set_user_mcp_server_id(server_id, user_uuid)
                set_user_mcp_client(temp_mcp_client, user_uuid)
                set_user_server_configs(temp_server_configs, user_uuid)
            else:
                # Clear MCP state for llm_only and rag_focused profiles
                set_user_mcp_server_id(None, user_uuid)
                set_user_mcp_client(None, user_uuid)
                set_user_server_configs(None, user_uuid)

            set_user_llm_instance(temp_llm_instance, user_uuid)

            if provider == "Amazon" and model.startswith("arn:aws:bedrock:"):
                profile_part = model.split('/')[-1]
                set_user_model_provider_in_profile(profile_part.split('.')[1], user_uuid)
            
            # --- MODIFICATION START: Initialize and store RAGRetriever instance ---
            # Note: RAGRetriever is now initialized at application startup independently
            # Here we only reload collections if MCP server changes (only for tool_enabled profiles)
            if APP_CONFIG.RAG_ENABLED and has_mcp_config:
                try:
                    # Check if RAGRetriever already exists (should be initialized at startup)
                    existing_retriever = APP_STATE.get('rag_retriever_instance')

                    if existing_retriever:
                        # MCP server changed - reload collections for new server
                        app_logger.info("RAGRetriever already exists. Reloading collections for new MCP server.")
                        existing_retriever.reload_collections_for_mcp_server()
                    else:
                        # Fallback: Initialize RAG if it wasn't started at startup for some reason
                        app_logger.warning("RAGRetriever not initialized at startup. Initializing now...")
                        project_root = Path(__file__).resolve().parents[3]
                        rag_cases_dir = project_root / APP_CONFIG.RAG_CASES_DIR
                        persist_dir = project_root / APP_CONFIG.RAG_PERSIST_DIR

                        config_manager = get_config_manager()
                        collections_list = config_manager.get_rag_collections()
                        APP_STATE["rag_collections"] = collections_list
                        app_logger.info(f"Loaded {len(collections_list)} RAG collections from persistent config")

                        app_logger.info(f"Initializing RAGRetriever with cases dir: {rag_cases_dir}")
                        retriever_instance = RAGRetriever(
                            rag_cases_dir=rag_cases_dir,
                            embedding_model_name=APP_CONFIG.RAG_EMBEDDING_MODEL,
                            persist_directory=persist_dir
                        )
                        APP_STATE['rag_retriever_instance'] = retriever_instance
                        app_logger.info("RAGRetriever initialized and stored in APP_STATE successfully.")

                    # Auto-enable and assign default collection to current MCP server if needed
                    config_manager = get_config_manager()
                    collections_list = config_manager.get_rag_collections()
                    default_collection = next((c for c in collections_list if c["id"] == 0), None)

                    collection_needs_update = False
                    if default_collection:
                        # Check if default collection needs to be assigned to this MCP server or enabled
                        if not default_collection.get("mcp_server_id") or not default_collection.get("enabled"):
                            app_logger.info(f"Auto-assigning/enabling default collection for MCP server '{server_id}'")
                            default_collection["mcp_server_id"] = server_id
                            default_collection["enabled"] = True
                            collection_needs_update = True
                        # Also update if switching to a different MCP server
                        elif default_collection.get("mcp_server_id") != server_id:
                            app_logger.info(f"Updating default collection from server '{default_collection.get('mcp_server_id')}' to '{server_id}'")
                            default_collection["mcp_server_id"] = server_id
                            collection_needs_update = True

                    if collection_needs_update:
                        config_manager.save_rag_collections(collections_list)
                        APP_STATE["rag_collections"] = collections_list
                        
                        # Reload collections to pick up the changes
                        retriever_instance = APP_STATE.get('rag_retriever_instance')
                        if retriever_instance:
                            retriever_instance.reload_collections_for_mcp_server()
                            loaded_count = len(retriever_instance.collections)
                            app_logger.info(f"Default collection configured and reloaded. {loaded_count} collection(s) now active.")
                
                except Exception as e:
                    app_logger.error(f"Failed to initialize RAGRetriever: {e}", exc_info=True)
                    # This is not a critical failure, so we just log it and continue.
                    # The planner will check for the instance before using it.
                    APP_STATE['rag_retriever_instance'] = None
            else:
                app_logger.info("RAG is disabled by config. Skipping RAGRetriever initialization.")
                APP_STATE['rag_retriever_instance'] = None
            # --- MODIFICATION END ---

            # --- 4. Load and Classify Capabilities (The Automatic Step) ---
            # Only needed for tool_enabled profiles that use MCP
            config_manager = get_config_manager()
            profile_id = config_manager.get_default_profile_id(user_uuid)

            if has_mcp_config:
                # Get default or active profile to use its classification mode
                if profile_id:
                    APP_CONFIG.CURRENT_PROFILE_ID = profile_id
                    app_logger.info(f"Using profile {profile_id} for MCP classification")
                else:
                    app_logger.warning("No default profile found, classification will use default mode 'full'")

                # Try to load cached classification first
                cached_loaded = False
                if profile_id:
                    cached_loaded = load_profile_classification_into_state(profile_id, user_uuid)

                # Run classification if no cache available
                if not cached_loaded:
                    await mcp_adapter.load_and_categorize_mcp_resources(APP_STATE, user_uuid, profile_id)
                else:
                    app_logger.info("Using cached classification results, skipping LLM classification")

                APP_CONFIG.MCP_SERVER_CONNECTED = True

                # Update classification mode in runtime state
                if profile_id:
                    profile = config_manager.get_profile(profile_id, user_uuid)
                    if profile:
                        APP_CONFIG.CURRENT_PROFILE_CLASSIFICATION_MODE = profile.get('classification_mode', 'light')
                        app_logger.info(f"Set runtime classification mode to '{APP_CONFIG.CURRENT_PROFILE_CLASSIFICATION_MODE}'")
            else:
                # For llm_only and rag_focused profiles, skip MCP classification
                app_logger.info("Skipping MCP classification for non-tool profile (llm_only or rag_focused)")
                APP_CONFIG.MCP_SERVER_CONNECTED = False
                if profile_id:
                    APP_CONFIG.CURRENT_PROFILE_ID = profile_id
            
            # --- 4a. Load Enabled/Disabled Tools/Prompts from Active Profile ---
            # CRITICAL: Use active_for_consumption profile, not default profile
            # The active profile is what determines which tools/prompts are available in the conversation
            active_profile_ids = config_manager.get_active_for_consumption_profile_ids(user_uuid)

            if active_profile_ids:
                # Use the first active profile (primary profile)
                primary_profile_id = active_profile_ids[0]
                APP_STATE["disabled_tools"] = config_manager.get_profile_disabled_tools(primary_profile_id, user_uuid)
                APP_STATE["disabled_prompts"] = config_manager.get_profile_disabled_prompts(primary_profile_id, user_uuid)
                app_logger.info(f"Loaded disabled lists from active profile {primary_profile_id}: {len(APP_STATE['disabled_tools'])} tools, {len(APP_STATE['disabled_prompts'])} prompts")
            elif profile_id:
                # Fallback: Use default profile if no active profiles
                APP_STATE["disabled_tools"] = config_manager.get_profile_disabled_tools(profile_id, user_uuid)
                APP_STATE["disabled_prompts"] = config_manager.get_profile_disabled_prompts(profile_id, user_uuid)
                app_logger.info(f"Loaded disabled lists from default profile {profile_id}: {len(APP_STATE['disabled_tools'])} tools, {len(APP_STATE['disabled_prompts'])} prompts")
            else:
                # No profiles exist yet, initialize with empty lists
                APP_STATE["disabled_tools"] = []
                APP_STATE["disabled_prompts"] = []
                app_logger.info("No profiles found. Initialized with empty disabled lists.")

            # Only set CHART_MCP_CONNECTED if MCP is configured
            if has_mcp_config:
                APP_CONFIG.CHART_MCP_CONNECTED = True
            else:
                APP_CONFIG.CHART_MCP_CONNECTED = False

            APP_STATE['tts_credentials_json'] = tts_credentials_json
            if APP_CONFIG.VOICE_CONVERSATION_ENABLED:
                from trusted_data_agent.core.utils import get_tts_client
                app_logger.info("AUDIO DEBUG: Configuration updated. Re-initializing TTS client.")
                APP_STATE['tts_client'] = get_tts_client()

            # --- 5. Finalize Contexts ---
            _regenerate_contexts()

            APP_CONFIG.SERVICES_CONFIGURED = True
            APP_CONFIG.ACTIVE_PROVIDER = provider
            APP_CONFIG.ACTIVE_MODEL = model

            if has_mcp_config:
                return {"status": "success", "message": f"MCP Server '{server_name}' and LLM configured successfully."}
            else:
                return {"status": "success", "message": f"LLM ({provider}/{model}) configured successfully for {profile_id or 'conversation'} profile."}

        except (APIError, OpenAI_APIError, google_exceptions.PermissionDenied, ClientError, RuntimeError, Exception) as e:
            app_logger.error(f"Configuration failed during validation: {e}", exc_info=True)
            # --- Rollback state on failure ---
            APP_STATE['llm'] = None
            APP_STATE['mcp_client'] = None
            APP_CONFIG.MCP_SERVER_CONNECTED = False
            APP_CONFIG.CHART_MCP_CONNECTED = False

            APP_CONFIG.SERVICES_CONFIGURED = False
            APP_CONFIG.ACTIVE_PROVIDER = None
            APP_CONFIG.ACTIVE_MODEL = None
            
            root_exception = unwrap_exception(e)
            error_message = ""

            if isinstance(root_exception, (httpx.ConnectTimeout, httpx.ConnectError)):
                if has_mcp_config:
                    error_message = "Connection to MCP server failed. Please check the Host and Port and ensure the server is running."
                else:
                    error_message = "Connection to LLM provider failed. Please check your network connection and credentials."
            elif isinstance(root_exception, (google_exceptions.PermissionDenied, ClientError)):
                if 'AccessDeniedException' in str(e):
                    error_message = "Access denied. Please check your AWS IAM permissions for the selected model."
                else:
                    error_message = "Authentication failed. Please check your API keys or credentials."
            elif isinstance(root_exception, (APIError, OpenAI_APIError)) and "authentication_error" in str(e).lower():
                error_message = f"Authentication failed. Please check your {provider} API key."
            else:
                error_message = getattr(root_exception, 'message', str(root_exception))

            return {"status": "error", "message": f"Configuration failed: {error_message}"}
        finally:
            app_logger.info("Configuration lock released.")


# ==============================================================================
# CREDENTIAL STORAGE HELPERS (Phase 4)
# ==============================================================================

async def store_credentials_for_provider(user_id: str, provider: str, credentials: dict) -> dict:
    """
    Store encrypted credentials for a provider.
    
    Args:
        user_id: User's unique identifier
        provider: Provider name (Amazon, Google, etc.)
        credentials: Dictionary of credential key-value pairs
        
    Returns:
        dict: {"status": "success"/"error", "message": str}
    """
    if not ENCRYPTION_AVAILABLE:
        return {"status": "error", "message": "Credential encryption not available"}
    
    try:
        # Filter out empty/None values
        filtered_creds = {k: v for k, v in credentials.items() if v}
        
        if not filtered_creds:
            return {"status": "error", "message": "No valid credentials provided"}
        
        result = encryption.encrypt_credentials(user_id, provider, filtered_creds)
        
        if result:
            # Log the credential storage
            audit.log_credential_change(user_id, provider, "stored")
            app_logger.info(f"Stored encrypted credentials for user {user_id}, provider {provider}")
            return {"status": "success", "message": f"Credentials stored securely for {provider}"}
        else:
            return {"status": "error", "message": "Failed to encrypt credentials"}
            
    except Exception as e:
        app_logger.error(f"Failed to store credentials: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def retrieve_credentials_for_provider(user_identifier: str, provider: str) -> dict:
    """
    Retrieve decrypted credentials for a provider.
    
    Args:
        user_identifier: User's database ID (user.id) - credentials are stored by this
                        NOTE: This should be user.id, NOT user_uuid
        provider: Provider name
        
    Returns:
        dict: {"status": "success"/"error", "credentials": dict or None, "message": str}
    """
    if not ENCRYPTION_AVAILABLE:
        return {"status": "error", "credentials": None, "message": "Credential encryption not available"}
    
    try:
        # user_identifier should be user.id (the database primary key)
        # Credentials are encrypted/stored using user.id as the key
        credentials = encryption.decrypt_credentials(user_identifier, provider)
        
        if credentials:
            app_logger.info(f"Retrieved credentials for user {user_identifier}, provider {provider}")
            return {"status": "success", "credentials": credentials}
        else:
            app_logger.info(f"No stored credentials found for user {user_identifier}, provider {provider}")
            return {"status": "success", "credentials": None, "message": "No stored credentials found"}
            
    except Exception as e:
        app_logger.error(f"Failed to retrieve credentials for user {user_identifier}: {e}", exc_info=True)
        return {"status": "error", "credentials": None, "message": str(e)}


async def delete_credentials_for_provider(user_id: str, provider: str) -> dict:
    """
    Delete stored credentials for a provider.
    
    Args:
        user_id: User's unique identifier
        provider: Provider name
        
    Returns:
        dict: {"status": "success"/"error", "message": str}
    """
    if not ENCRYPTION_AVAILABLE:
        return {"status": "error", "message": "Credential encryption not available"}
    
    try:
        result = encryption.delete_credentials(user_id, provider)
        
        if result:
            audit.log_credential_change(user_id, provider, "deleted")
            app_logger.info(f"Deleted credentials for user {user_id}, provider {provider}")
            return {"status": "success", "message": f"Credentials deleted for {provider}"}
        else:
            return {"status": "error", "message": "Credentials not found or already deleted"}
            
    except Exception as e:
        app_logger.error(f"Failed to delete credentials: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def list_user_providers(user_id: str) -> dict:
    """
    List all providers with stored credentials for a user.
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        dict: {"status": "success"/"error", "providers": list, "message": str}
    """
    if not ENCRYPTION_AVAILABLE:
        return {"status": "error", "providers": [], "message": "Credential encryption not available"}
    
    try:
        providers = encryption.list_user_providers(user_id)
        return {"status": "success", "providers": providers}
            
    except Exception as e:
        app_logger.error(f"Failed to list providers: {e}", exc_info=True)
        return {"status": "error", "providers": [], "message": str(e)}