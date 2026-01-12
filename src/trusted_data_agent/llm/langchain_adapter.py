"""
LangChain LLM Adapter
=====================

Provides adapters to create LangChain-compatible LLM instances from Uderia configurations.

This module bridges Uderia's LLM configuration system with LangChain's LLM abstractions,
allowing Genie profiles to use any configured LLM provider through LangChain's agent framework.

Usage:
    from trusted_data_agent.llm.langchain_adapter import create_langchain_llm

    llm = create_langchain_llm(llm_config_id="1234", user_uuid="user-uuid")
    # Returns a LangChain Chat model instance (ChatOpenAI, ChatAnthropic, etc.)
"""

import logging
import os
from typing import Any, Optional

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

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=temperature
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
