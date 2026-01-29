"""
LLM Client Factory - Single source of truth for creating LLM client instances.

This module provides a unified way to create LLM client instances for any provider,
ensuring consistency between default profile initialization and temporary profile overrides.
"""

from typing import Dict, Any, Tuple
from openai import AsyncOpenAI, AsyncAzureOpenAI
import asyncio
import boto3
import httpx


async def create_llm_client(provider: str, model: str, credentials: Dict[str, Any], validate: bool = False) -> Any:
    """
    Creates an LLM client instance for the specified provider.
    
    Args:
        provider: The LLM provider name (Google, Anthropic, OpenAI, Friendli, Amazon, Azure, Ollama)
        model: The model identifier
        credentials: Dictionary containing provider-specific credentials
        validate: If True, performs validation API calls to test the connection
        
    Returns:
        The initialized LLM client instance
        
    Raises:
        ValueError: If provider is unsupported or required credentials are missing
    """
    
    if provider == "Google":
        import google.generativeai as genai
        api_key = credentials.get("apiKey")
        if not api_key:
            raise ValueError("Google API key is required but not provided")
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(model_name=model)
    
    elif provider == "Anthropic":
        from anthropic import AsyncAnthropic
        api_key = credentials.get("apiKey")
        if not api_key:
            raise ValueError("Anthropic API key is required but not provided")
        return AsyncAnthropic(api_key=api_key)
    
    elif provider == "OpenAI":
        api_key = credentials.get("apiKey")
        if not api_key:
            raise ValueError("OpenAI API key is required but not provided")
        return AsyncOpenAI(api_key=api_key)
    
    elif provider == "Friendli":
        friendli_api_key = credentials.get("friendli_token")
        endpoint_url = credentials.get("friendli_endpoint_url")

        if not friendli_api_key:
            raise ValueError("Friendli API token is required but not provided")

        # Set a 30-second timeout to prevent hanging on unavailable models
        if endpoint_url:
            # Dedicated endpoint
            client = AsyncOpenAI(api_key=friendli_api_key, base_url=endpoint_url, timeout=30.0)
            if validate:
                validation_url = f"{endpoint_url.rstrip('/')}/v1/models"
                headers = {"Authorization": f"Bearer {friendli_api_key}"}
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    response = await http_client.get(validation_url, headers=headers)
                    response.raise_for_status()
            return client
        else:
            # Serverless endpoint
            client = AsyncOpenAI(api_key=friendli_api_key, base_url="https://api.friendli.ai/serverless/v1", timeout=30.0)
            if validate:
                await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "test"}],
                    max_tokens=1
                )
            return client
    
    elif provider == "Amazon":
        aws_access_key = credentials.get("aws_access_key_id")
        aws_secret_key = credentials.get("aws_secret_access_key")
        aws_region = credentials.get("aws_region")
        
        if not aws_access_key or not aws_secret_key:
            raise ValueError("AWS credentials (access key and secret key) are required but not provided")
        
        return boto3.client(
            service_name='bedrock-runtime',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region
        )
    
    elif provider == "Ollama":
        from trusted_data_agent.llm import handler as llm_handler
        ollama_host = credentials.get("ollama_host", "http://localhost:11434")
        return llm_handler.OllamaClient(host=ollama_host)
    
    elif provider == "Azure":
        api_key = credentials.get("azure_api_key")
        endpoint = credentials.get("azure_endpoint")
        api_version = credentials.get("azure_api_version")
        
        if not api_key or not endpoint:
            raise ValueError("Azure API key and endpoint are required but not provided")
        
        return AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version
        )
    
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def get_provider_config_details(provider: str, model: str, credentials: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gets provider-specific configuration details that need to be stored in APP_CONFIG.
    
    Args:
        provider: The LLM provider name
        model: The model identifier
        credentials: Dictionary containing provider-specific credentials
        
    Returns:
        Dictionary with provider-specific config keys and values
    """
    details = {}
    
    if provider == "Amazon":
        details["CURRENT_AWS_REGION"] = credentials.get("aws_region")
        if model.startswith("arn:aws:bedrock:"):
            profile_part = model.split('/')[-1]
            details["CURRENT_MODEL_PROVIDER_IN_PROFILE"] = profile_part.split('.')[1]
    
    elif provider == "Azure":
        details["CURRENT_AZURE_DEPLOYMENT_DETAILS"] = {
            "endpoint": credentials.get("azure_endpoint"),
            "deployment_name": credentials.get("azure_deployment_name"),
            "api_version": credentials.get("azure_api_version")
        }
    
    elif provider == "Friendli":
        is_dedicated = bool(credentials.get("friendli_endpoint_url"))
        details["CURRENT_FRIENDLI_DETAILS"] = {
            "token": credentials.get("friendli_token"),
            "endpoint_url": credentials.get("friendli_endpoint_url"),
            "models_path": "/v1/models" if is_dedicated else None
        }
    
    return details


async def test_llm_credentials(provider: str, model: str, credentials: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Test LLM credentials by making a lightweight API call.
    
    Args:
        provider: The LLM provider name
        model: The model identifier
        credentials: Dictionary containing provider-specific credentials
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Create the client
        llm_instance = await create_llm_client(provider, model, credentials)
        
        # Make provider-specific test call
        if provider == "Google":
            response = await llm_instance.generate_content_async("test")
            if hasattr(response, 'text'):
                return True, f"LLM connection successful ({provider} {model})."
                
        elif provider == "Anthropic":
            response = await llm_instance.messages.create(
                model=model,
                max_tokens=5,
                messages=[{"role": "user", "content": "test"}]
            )
            if response.content:
                return True, f"LLM connection successful ({provider} {model})."
                
        elif provider in ["OpenAI", "Friendli", "Azure"]:
            # Use timeout wrapper to prevent hanging on unavailable models
            try:
                response = await asyncio.wait_for(
                    llm_instance.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": "test"}],
                        max_tokens=5
                    ),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                return False, f"Connection timed out testing {provider} model '{model}'. The model may not be available."
            if response.choices:
                return True, f"LLM connection successful ({provider} {model})."
                
        elif provider == "Amazon":
            import json
            
            # Determine provider from model ID or inference profile ARN
            is_inference_profile = model.startswith("arn:aws:bedrock:")
            if is_inference_profile:
                # Extract provider from inference profile ARN
                # Format: arn:aws:bedrock:region:account:inference-profile/provider.model-name
                try:
                    profile_part = model.split('/')[-1]
                    bedrock_provider = profile_part.split('.')[1] if '.' in profile_part else "unknown"
                except:
                    bedrock_provider = "unknown"
            else:
                # Direct model ID - extract provider from model ID
                # Handle version suffix (e.g., amazon.nova-lite-v1:0 -> amazon)
                model_base = model.split(':')[0]  # Remove version suffix if present
                bedrock_provider = model_base.split('.')[0]
            
            # Build request body based on provider
            if bedrock_provider == "anthropic":
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "test"}]
                })
            elif bedrock_provider == "amazon":
                # Amazon Nova format
                body = json.dumps({
                    "messages": [{"role": "user", "content": [{"text": "test"}]}],
                    "inferenceConfig": {"maxTokens": 5}
                })
            else:
                # Default format for other providers
                body = json.dumps({
                    "prompt": "test",
                    "max_tokens": 5
                })
            
            try:
                response = llm_instance.invoke_model(modelId=model, body=body)
            except Exception as invoke_error:
                error_msg = str(invoke_error)
                if "ValidationException" in error_msg or "ResourceNotFoundException" in error_msg:
                    return False, f"Model '{model}' not available in your AWS region or not accessible with your credentials. Error: {error_msg}"
                raise
            response_body = json.loads(response['body'].read())
            
            # Check response based on provider
            if bedrock_provider == "anthropic":
                if response_body.get('content'):
                    return True, f"LLM connection successful ({provider} {model})."
            elif bedrock_provider == "amazon":
                if response_body.get('output', {}).get('message'):
                    return True, f"LLM connection successful ({provider} {model})."
            else:
                if response_body.get('results') or response_body.get('completion'):
                    return True, f"LLM connection successful ({provider} {model})."
                
        elif provider == "Ollama":
            response = await llm_instance.generate(model=model, prompt="test")
            if response.get('response'):
                return True, f"LLM connection successful ({provider} {model})."
                
        else:
            return False, f"Provider '{provider}' is not supported for testing."
            
        return False, "LLM returned empty response."
        
    except Exception as e:
        error_msg = str(e)
        # Clean up error message
        if "(" in error_msg:
            error_msg = error_msg.split("(")[0].strip()
        return False, f"Validation failed: {error_msg}"
