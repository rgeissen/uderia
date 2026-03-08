#!/usr/bin/env python3
"""
AWS Bedrock Connectivity Test Script

This script validates AWS Bedrock connectivity using the application's mechanics
(without inference profiles). It tests direct model invocation using boto3 clients
as used in the main application.

Features:
- Interactive credential input
- Lists available foundation models
- Tests connection with selected model
- Uses application's client creation patterns
"""

import boto3
import json
import sys
from typing import List, Dict, Any, Optional


def print_header(text: str):
    """Print formatted header."""
    print(f"\n{'=' * 60}")
    print(f" {text}")
    print(f"{'=' * 60}\n")


def print_success(text: str):
    """Print success message."""
    print(f"✓ {text}")


def print_error(text: str):
    """Print error message."""
    print(f"✗ {text}")


def get_credentials() -> Dict[str, str]:
    """
    Prompt user for AWS credentials and region.
    
    Returns:
        Dictionary containing access_key_id, secret_access_key, and region
    """
    print_header("AWS Bedrock Connectivity Test")
    
    print("Please enter your AWS credentials:")
    access_key_id = input("  Access Key ID: ").strip()
    secret_access_key = input("  Secret Access Key: ").strip()
    region = input("  Region (e.g., us-east-1, eu-central-1): ").strip()
    
    if not all([access_key_id, secret_access_key, region]):
        print_error("All credentials are required!")
        sys.exit(1)
    
    return {
        "access_key_id": access_key_id,
        "secret_access_key": secret_access_key,
        "region": region
    }


def create_bedrock_client(credentials: Dict[str, str]) -> boto3.client:
    """
    Create a Bedrock client using application mechanics.
    
    Args:
        credentials: Dictionary with AWS credentials
        
    Returns:
        Boto3 Bedrock client
    """
    try:
        client = boto3.client(
            service_name='bedrock',
            region_name=credentials['region'],
            aws_access_key_id=credentials['access_key_id'],
            aws_secret_access_key=credentials['secret_access_key']
        )
        print_success(f"Bedrock client created for region: {credentials['region']}")
        return client
    except Exception as e:
        print_error(f"Failed to create Bedrock client: {e}")
        sys.exit(1)


def create_bedrock_runtime_client(credentials: Dict[str, str]) -> boto3.client:
    """
    Create a Bedrock Runtime client for model invocation.
    
    Args:
        credentials: Dictionary with AWS credentials
        
    Returns:
        Boto3 Bedrock Runtime client
    """
    try:
        client = boto3.client(
            service_name='bedrock-runtime',
            region_name=credentials['region'],
            aws_access_key_id=credentials['access_key_id'],
            aws_secret_access_key=credentials['secret_access_key']
        )
        print_success("Bedrock Runtime client created")
        return client
    except Exception as e:
        print_error(f"Failed to create Bedrock Runtime client: {e}")
        sys.exit(1)


def list_available_models(client: boto3.client) -> List[Dict[str, Any]]:
    """
    List available foundation models (excluding inference profiles).
    
    Args:
        client: Bedrock client
        
    Returns:
        List of model dictionaries
    """
    print_header("Listing Available Foundation Models")
    
    try:
        response = client.list_foundation_models()
        
        # Filter for text generation models only (no inference profiles)
        text_models = [
            model for model in response.get('modelSummaries', [])
            if 'TEXT' in model.get('inputModalities', []) 
            and 'TEXT' in model.get('outputModalities', [])
        ]
        
        if not text_models:
            print_error("No text generation models found in this region.")
            return []
        
        print_success(f"Found {len(text_models)} text generation models:\n")
        
        for i, model in enumerate(text_models, 1):
            model_id = model.get('modelId', 'N/A')
            provider = model.get('providerName', 'N/A')
            status = model.get('modelLifecycle', {}).get('status', 'N/A')
            
            print(f"  {i:2d}. {model_id}")
            print(f"      Provider: {provider}")
            print(f"      Status: {status}")
            print()
        
        return text_models
        
    except Exception as e:
        print_error(f"Error listing models: {e}")
        return []


def get_request_body(model_id: str, prompt: str) -> str:
    """
    Generate request body based on model provider.
    Uses the same logic as the application's handler.
    
    Args:
        model_id: The model identifier
        prompt: The prompt text
        
    Returns:
        JSON string with request body
    """
    # Determine provider from model ID
    if "anthropic" in model_id.lower():
        return json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": prompt}]
        })
    
    elif "amazon" in model_id.lower() and "titan" in model_id.lower():
        return json.dumps({
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": 100,
                "temperature": 0.7,
                "topP": 0.9
            }
        })
    
    elif "amazon.nova" in model_id.lower():
        return json.dumps({
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "maxTokens": 100,
                "temperature": 0.7,
                "topP": 0.9
            }
        })
    
    elif "ai21" in model_id.lower():
        return json.dumps({
            "prompt": prompt,
            "maxTokens": 100,
            "temperature": 0.7,
            "topP": 0.9
        })
    
    elif "cohere" in model_id.lower():
        return json.dumps({
            "prompt": prompt,
            "max_tokens": 100,
            "temperature": 0.7,
            "p": 0.9
        })
    
    elif "meta" in model_id.lower() and "llama" in model_id.lower():
        return json.dumps({
            "prompt": prompt,
            "max_gen_len": 100,
            "temperature": 0.7,
            "top_p": 0.9
        })
    
    elif "mistral" in model_id.lower():
        return json.dumps({
            "prompt": prompt,
            "max_tokens": 100,
            "temperature": 0.7,
            "top_p": 0.9
        })
    
    else:
        # Generic fallback
        return json.dumps({
            "prompt": prompt,
            "max_tokens_to_sample": 100,
            "temperature": 0.7
        })


def extract_response_text(model_id: str, response_body: Dict[str, Any]) -> str:
    """
    Extract response text based on model provider.
    Uses the same logic as the application's handler.
    
    Args:
        model_id: The model identifier
        response_body: The response body from Bedrock
        
    Returns:
        Extracted text response
    """
    generated_text = "Could not parse response."
    
    if "anthropic" in model_id.lower():
        # Anthropic Claude models
        if 'content' in response_body:
            if isinstance(response_body['content'], list):
                for block in response_body['content']:
                    if 'text' in block:
                        return block['text']
        return response_body.get('completion', generated_text)
    
    elif "amazon" in model_id.lower() and "titan" in model_id.lower():
        # Amazon Titan models
        results = response_body.get('results', [])
        if results:
            return results[0].get('outputText', generated_text)
        return generated_text
    
    elif "amazon.nova" in model_id.lower():
        # Amazon Nova models
        output = response_body.get('output', {})
        message = output.get('message', {})
        content = message.get('content', [])
        if content:
            for block in content:
                if 'text' in block:
                    return block['text']
        return "Nova model response structure not recognized."
    
    elif "ai21" in model_id.lower():
        # AI21 models
        completions = response_body.get('completions', [])
        if completions:
            return completions[0].get('data', {}).get('text', generated_text)
        return generated_text
    
    elif "cohere" in model_id.lower():
        # Cohere models
        generations = response_body.get('generations', [])
        if generations:
            return generations[0].get('text', generated_text)
        return generated_text
    
    elif "meta" in model_id.lower() and "llama" in model_id.lower():
        # Meta Llama models
        return response_body.get('generation', generated_text)
    
    elif "mistral" in model_id.lower():
        # Mistral models
        outputs = response_body.get('outputs', [])
        if outputs:
            return outputs[0].get('text', generated_text)
        return generated_text
    
    else:
        # Try common response keys
        if 'completion' in response_body:
            return response_body['completion']
        elif 'outputText' in response_body:
            return response_body['outputText']
        elif 'text' in response_body:
            return response_body['text']
        elif 'generated_text' in response_body:
            return response_body['generated_text']
        
        return generated_text


def test_model_connection(
    runtime_client: boto3.client, 
    model_id: str,
    region: str
) -> bool:
    """
    Test connection with selected model by sending a simple prompt.
    
    Args:
        runtime_client: Bedrock Runtime client
        model_id: The model identifier to test
        region: AWS region
        
    Returns:
        True if successful, False otherwise
    """
    print_header(f"Testing Connection with {model_id}")
    
    test_prompt = "Hello! Please respond with a brief greeting."
    
    try:
        # Handle regional prefixes for Nova models (application logic)
        adjusted_model_id = model_id
        if "amazon.nova" in model_id.lower():
            if region.startswith("us-"):
                adjusted_model_id = f"us.{model_id}"
            elif region.startswith("eu-"):
                adjusted_model_id = f"eu.{model_id}"
            elif region.startswith("ap-"):
                adjusted_model_id = f"apac.{model_id}"
            print(f"  Note: Using adjusted model ID for Nova: {adjusted_model_id}")
        
        # Prepare request body
        body = get_request_body(model_id, test_prompt)
        
        print(f"  Sending test prompt: '{test_prompt}'")
        print(f"  Model ID: {adjusted_model_id}")
        
        # Invoke model
        response = runtime_client.invoke_model(
            body=body,
            modelId=adjusted_model_id,
            accept='application/json',
            contentType='application/json'
        )
        
        # Parse response
        response_body = json.loads(response.get('body').read())
        response_text = extract_response_text(model_id, response_body)
        
        print_success("Model invocation successful!\n")
        print(f"{'─' * 60}")
        print("Response:")
        print(f"{'─' * 60}")
        print(response_text.strip())
        print(f"{'─' * 60}\n")
        
        return True
        
    except Exception as e:
        print_error(f"Model invocation failed: {e}")
        return False


def main():
    """Main execution flow."""
    try:
        # Step 1: Get credentials
        credentials = get_credentials()
        
        # Step 2: Create Bedrock client
        bedrock_client = create_bedrock_client(credentials)
        
        # Step 3: List available models
        models = list_available_models(bedrock_client)
        
        if not models:
            print_error("No models available. Exiting.")
            sys.exit(1)
        
        # Step 4: Model selection loop
        while True:
            print(f"\n{'─' * 60}")
            choice = input("Enter model number to test (or 'q' to quit): ").strip().lower()
            
            if choice == 'q':
                print("\nExiting. Goodbye!")
                break
            
            try:
                choice_idx = int(choice) - 1
                
                if 0 <= choice_idx < len(models):
                    selected_model = models[choice_idx]
                    model_id = selected_model['modelId']
                    
                    # Create runtime client
                    runtime_client = create_bedrock_runtime_client(credentials)
                    
                    # Test the connection
                    success = test_model_connection(
                        runtime_client,
                        model_id,
                        credentials['region']
                    )
                    
                    if success:
                        print_success(f"Connectivity validated for {model_id}")
                    else:
                        print_error(f"Connectivity test failed for {model_id}")
                    
                    # Ask if user wants to test another model
                    another = input("\nTest another model? (yes/no): ").strip().lower()
                    if another != 'yes':
                        print("\nExiting. Goodbye!")
                        break
                else:
                    print_error("Invalid selection. Please choose a number from the list.")
                    
            except ValueError:
                print_error("Invalid input. Please enter a number or 'q'.")
            except KeyboardInterrupt:
                print("\n\nInterrupted by user. Exiting.")
                break
                
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting.")
        sys.exit(0)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
