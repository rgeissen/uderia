"""
LangChain LLM Adapter
=====================

Provides adapters to create LangChain-compatible LLM instances from Uderia configurations.

This module bridges Uderia's LLM configuration system with LangChain's LLM abstractions,
allowing Genie profiles and conversation_with_tools profiles to use any configured LLM
provider through LangChain's agent framework.

Usage:
    from trusted_data_agent.llm.langchain_adapter import create_langchain_llm, load_mcp_tools_for_langchain

    llm = create_langchain_llm(llm_config_id="1234", user_uuid="user-uuid")
    # Returns a LangChain Chat model instance (ChatOpenAI, ChatAnthropic, etc.)

    tools = await load_mcp_tools_for_langchain(mcp_server_id="server-123", profile_id="profile-456", user_uuid="user-uuid")
    # Returns a list of LangChain-compatible tools filtered by profile configuration
"""

import logging
import os
from typing import Any, Optional, List

from trusted_data_agent.core.config_manager import get_config_manager
from trusted_data_agent.auth.encryption import decrypt_credentials
from trusted_data_agent.auth import encryption

logger = logging.getLogger(__name__)


def create_langchain_llm(
    llm_config_id: str,
    user_uuid: str,
    temperature: float = 0.7
) -> Any:
    """
    Create a LangChain-compatible LLM instance from Uderia LLM configuration.

    Args:
        llm_config_id: The ID of the LLM configuration in Uderia
        user_uuid: User UUID for accessing encrypted credentials
        temperature: LLM temperature setting (default 0.7)

    Returns:
        LangChain Chat model instance

    Raises:
        ValueError: If provider is not supported
        Exception: If LLM creation fails
    """
    config_manager = get_config_manager()

    # Get LLM configuration
    llm_configurations = config_manager.get_llm_configurations(user_uuid)
    llm_config = next((c for c in llm_configurations if c.get("id") == llm_config_id), None)
    if not llm_config:
        raise ValueError(f"LLM configuration {llm_config_id} not found")

    provider = llm_config.get("provider")
    model = llm_config.get("model")
    credentials = llm_config.get("credentials", {})

    # Load credentials from credential store (like configuration_service does)
    decrypted_creds = _load_credentials_for_provider(user_uuid, provider, credentials)

    logger.info(f"Creating LangChain LLM for provider={provider}, model={model}")

    # Create provider-specific LangChain LLM
    if provider == "OpenAI":
        return _create_openai_llm(model, decrypted_creds, temperature)
    elif provider == "Anthropic":
        return _create_anthropic_llm(model, decrypted_creds, temperature)
    elif provider == "Google":
        return _create_google_llm(model, decrypted_creds, temperature)
    elif provider == "Azure":
        return _create_azure_llm(model, decrypted_creds, llm_config, temperature)
    else:
        raise ValueError(f"Unsupported provider for LangChain: {provider}")


def _load_credentials_for_provider(user_uuid: str, provider: str, config_credentials: dict) -> dict:
    """
    Load credentials for a provider from the credential store.

    Mirrors the approach used in configuration_service.py to load stored credentials.
    Falls back to environment variables if no stored credentials found.
    """
    credentials = dict(config_credentials) if config_credentials else {}

    try:
        # Try to load stored credentials from the database
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import User

        with get_db_session() as session:
            # User.id is the UUID field (String(36) primary key)
            user = session.query(User).filter_by(id=user_uuid).first()
            if user:
                logger.info(f"Loading credentials for user {user.id}, provider {provider}")
                # Credentials are stored using user.id (which IS the user_uuid)
                stored_creds = encryption.decrypt_credentials(user.id, provider)
                if stored_creds:
                    credentials = {**stored_creds, **credentials}
                    logger.info(f"✓ Successfully loaded stored credentials for {provider}")
                else:
                    logger.warning(f"No stored credentials found for {provider}")
            else:
                logger.warning(f"No user found for user_uuid={user_uuid}")

    except Exception as e:
        logger.error(f"Error loading stored credentials: {e}", exc_info=True)

    # Fall back to environment variables if no credentials found
    if not credentials.get("apiKey") and not credentials.get("api_key"):
        logger.info(f"No credentials in store, checking environment variables for {provider}")
        if provider == "Google":
            env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if env_key:
                credentials["apiKey"] = env_key
                logger.info("Loaded Google API key from environment")
        elif provider == "Anthropic":
            env_key = os.environ.get("ANTHROPIC_API_KEY")
            if env_key:
                credentials["apiKey"] = env_key
                logger.info("Loaded Anthropic API key from environment")
        elif provider == "OpenAI":
            env_key = os.environ.get("OPENAI_API_KEY")
            if env_key:
                credentials["apiKey"] = env_key
                logger.info("Loaded OpenAI API key from environment")

    return credentials


def _create_openai_llm(model: str, credentials: dict, temperature: float) -> Any:
    """Create LangChain ChatOpenAI instance."""
    try:
        from langchain_openai import ChatOpenAI

        api_key = credentials.get("apiKey") or credentials.get("api_key")
        if not api_key:
            raise ValueError("OpenAI API key not found in credentials")

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            temperature=temperature
        )
    except ImportError:
        raise ImportError("langchain-openai package not installed. Run: pip install langchain-openai")


def _create_anthropic_llm(model: str, credentials: dict, temperature: float) -> Any:
    """Create LangChain ChatAnthropic instance."""
    try:
        from langchain_anthropic import ChatAnthropic

        api_key = credentials.get("apiKey") or credentials.get("api_key")
        if not api_key:
            raise ValueError("Anthropic API key not found in credentials")

        return ChatAnthropic(
            model=model,
            api_key=api_key,
            temperature=temperature
        )
    except ImportError:
        raise ImportError("langchain-anthropic package not installed. Run: pip install langchain-anthropic")


def _create_google_llm(model: str, credentials: dict, temperature: float) -> Any:
    """Create LangChain ChatGoogleGenerativeAI instance."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = credentials.get("apiKey") or credentials.get("api_key")
        if not api_key:
            raise ValueError("Google API key not found in credentials")

        # NOTE: include_thoughts=True is required to get usage_metadata from Google API
        # This is a workaround for a LangChain bug where token usage isn't populated otherwise
        # See: https://github.com/langchain-ai/langchain-google/issues/957
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=temperature,
            include_thoughts=True  # Required for token usage tracking
        )
    except ImportError:
        raise ImportError("langchain-google-genai package not installed. Run: pip install langchain-google-genai")


def _create_azure_llm(model: str, credentials: dict, llm_config: dict, temperature: float) -> Any:
    """Create LangChain AzureChatOpenAI instance."""
    try:
        from langchain_openai import AzureChatOpenAI

        api_key = credentials.get("azure_api_key")
        endpoint = credentials.get("azure_endpoint")
        deployment = credentials.get("azure_deployment_name")
        api_version = credentials.get("azure_api_version", "2024-02-01")

        if not all([api_key, endpoint, deployment]):
            raise ValueError("Azure credentials incomplete")

        return AzureChatOpenAI(
            azure_deployment=deployment,
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            temperature=temperature
        )
    except ImportError:
        raise ImportError("langchain-openai package not installed. Run: pip install langchain-openai")


def get_supported_providers() -> list:
    """Get list of providers supported for LangChain integration."""
    return ["OpenAI", "Anthropic", "Google", "Azure"]


def is_provider_supported(provider: str) -> bool:
    """Check if a provider is supported for LangChain integration."""
    return provider in get_supported_providers()


async def load_mcp_tools_for_langchain(
    mcp_server_id: str,
    profile_id: str,
    user_uuid: str
) -> List[Any]:
    """
    Load MCP tools as LangChain-compatible tools, filtered by profile configuration.

    This function:
    1. Builds a connection config from the MCP server configuration
    2. Loads tools using langchain_mcp_adapters with the connection parameter
       (this keeps the session alive internally for tool execution)
    3. Filters tools based on the profile's enabled tools list
    4. Returns LangChain-compatible tool objects

    Args:
        mcp_server_id: The MCP server ID to load tools from
        profile_id: The profile ID for filtering enabled tools
        user_uuid: User UUID for accessing configuration

    Returns:
        List of LangChain-compatible tool objects

    Raises:
        ValueError: If MCP server configuration not found
        Exception: If tool loading fails
    """
    from langchain_mcp_adapters.tools import load_mcp_tools

    config_manager = get_config_manager()

    # Get profile's enabled tools
    enabled_tools = config_manager.get_profile_enabled_tools(profile_id, user_uuid)
    logger.info(f"Profile {profile_id} has {len(enabled_tools)} enabled tools")

    # Handle wildcard - all tools enabled
    filter_tools = enabled_tools != ['*']

    # Get MCP server configuration
    mcp_servers = config_manager.get_mcp_servers(user_uuid)
    mcp_server = next((s for s in mcp_servers if s.get("id") == mcp_server_id), None)

    if not mcp_server:
        raise ValueError(f"MCP server {mcp_server_id} not found in configuration")

    # Build connection config based on transport type
    transport_info = mcp_server.get('transport', {})
    transport_type = transport_info.get('type', 'sse')

    if transport_type == 'stdio':
        command = transport_info.get('command', '')
        args = transport_info.get('args', [])
        env = transport_info.get('env')

        if not command:
            raise ValueError(f"stdio transport requires 'command' field")

        # StdioConnection is a TypedDict - must include 'transport' key
        connection = {
            "transport": "stdio",
            "command": command,
            "args": args
        }
        if env:
            connection["env"] = env
        logger.info(f"Using stdio connection for MCP server {mcp_server_id}")

    elif transport_type in ('sse', 'http', 'streamable_http'):
        host = mcp_server.get('host')
        port = mcp_server.get('port')
        path = mcp_server.get('path')

        if not all([host, port, path]):
            raise ValueError(f"SSE/HTTP transport requires host, port, and path")

        mcp_server_url = f"http://{host}:{port}{path}"
        # StreamableHttpConnection is a TypedDict - must include 'transport' key
        connection = {
            "transport": "streamable_http",
            "url": mcp_server_url
        }
        logger.info(f"Using HTTP connection for MCP server {mcp_server_id}: {mcp_server_url}")

    else:
        raise ValueError(f"Unsupported transport type: {transport_type}")

    # Load tools using connection parameter (keeps session alive for tool execution)
    try:
        all_tools = await load_mcp_tools(session=None, connection=connection)
        logger.info(f"Loaded {len(all_tools)} tools from MCP server {mcp_server_id}")

        # Filter tools based on profile configuration
        if filter_tools:
            filtered_tools = [
                tool for tool in all_tools
                if tool.name in enabled_tools or tool.name.startswith('TDA_')
            ]
            logger.info(f"Filtered to {len(filtered_tools)} tools based on profile settings")
            return filtered_tools
        else:
            return all_tools

    except Exception as e:
        logger.error(f"Failed to load MCP tools for LangChain: {e}", exc_info=True)
        raise


async def create_langchain_agent_executor(
    llm_config_id: str,
    user_uuid: str,
    mcp_server_id: str,
    profile_id: str,
    system_prompt: Optional[str] = None,
    max_iterations: int = 5
) -> Any:
    """
    Create a complete LangChain agent executor with MCP tools bound.

    This is a convenience function that:
    1. Creates the LangChain LLM
    2. Loads and filters MCP tools
    3. Creates a tool-calling agent
    4. Returns an AgentExecutor ready for use

    Args:
        llm_config_id: The LLM configuration ID
        user_uuid: User UUID for configuration access
        mcp_server_id: MCP server ID for tool loading
        profile_id: Profile ID for tool filtering
        system_prompt: Optional system prompt for the agent
        max_iterations: Maximum agent iterations (default: 5)

    Returns:
        LangChain AgentExecutor instance

    Raises:
        ValueError: If configuration not found
        Exception: If agent creation fails
    """
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    # Create LLM
    llm = create_langchain_llm(llm_config_id, user_uuid)
    logger.info(f"Created LangChain LLM for config {llm_config_id}")

    # Load tools
    tools = await load_mcp_tools_for_langchain(mcp_server_id, profile_id, user_uuid)
    logger.info(f"Loaded {len(tools)} tools for agent")

    # Build prompt template
    if system_prompt:
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
    else:
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful AI assistant with access to tools."),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

    # Create tool-calling agent
    agent = create_tool_calling_agent(llm, tools, prompt)

    # Create executor
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=max_iterations,
        return_intermediate_steps=True,
        handle_parsing_errors=True
    )

    logger.info(f"Created AgentExecutor with {len(tools)} tools, max_iterations={max_iterations}")
    return executor
