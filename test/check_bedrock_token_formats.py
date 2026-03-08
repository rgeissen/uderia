#!/usr/bin/env python3
"""
Check AWS Bedrock token response formats for different model providers.
This will help us understand what token usage data is available.
"""
import json

# Example responses from AWS documentation

# Anthropic Claude response
anthropic_response = {
    "id": "msg_bdrk_01234567890abcdefg",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "Hello!"}],
    "model": "claude-3-sonnet-20240229",
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 10,
        "output_tokens": 25
    }
}

# Amazon Titan Text Express response (legacy format)
titan_express_response = {
    "inputTextTokenCount": 8,
    "results": [{
        "tokenCount": 25,
        "outputText": "Hello! This is a response.",
        "completionReason": "FINISH"
    }]
}

# Amazon Titan Text (newer format)
titan_new_response = {
    "output": {
        "message": {
            "role": "assistant",
            "content": [{"text": "Hello!"}]
        }
    },
    "stopReason": "end_turn",
    "usage": {
        "inputTokens": 10,
        "outputTokens": 25,
        "totalTokens": 35
    }
}

# Meta Llama response
meta_response = {
    "generation": "Hello! How can I help?",
    "prompt_token_count": 10,
    "generation_token_count": 25,
    "stop_reason": "stop"
}

# Cohere Command response
cohere_response = {
    "generations": [{
        "finish_reason": "COMPLETE",
        "id": "abc123",
        "text": "Hello!"
    }],
    "id": "xyz789",
    "prompt": "Hi"
}

# Mistral response
mistral_response = {
    "outputs": [{
        "text": "Hello!",
        "stop_reason": "stop"
    }]
}

# AI21 response
ai21_response = {
    "completions": [{
        "data": {
            "text": "Hello!"
        },
        "finishReason": {
            "reason": "endoftext"
        }
    }]
}

print("=== Token Usage Data Availability ===\n")

print("✅ Anthropic Claude:")
print(f"   - Has 'usage' field: {('usage' in anthropic_response)}")
print(f"   - Input tokens: {anthropic_response['usage']['input_tokens']}")
print(f"   - Output tokens: {anthropic_response['usage']['output_tokens']}")
print()

print("✅ Amazon Titan Text (Legacy - Express):")
print(f"   - Has inputTextTokenCount: {('inputTextTokenCount' in titan_express_response)}")
print(f"   - Input tokens: {titan_express_response['inputTextTokenCount']}")
print(f"   - Output tokens: {titan_express_response['results'][0]['tokenCount']}")
print()

print("✅ Amazon Titan Text (New format - Premier/Nova):")
print(f"   - Has 'usage' field: {('usage' in titan_new_response)}")
print(f"   - Input tokens: {titan_new_response['usage']['inputTokens']}")
print(f"   - Output tokens: {titan_new_response['usage']['outputTokens']}")
print(f"   - Total tokens: {titan_new_response['usage']['totalTokens']}")
print()

print("✅ Meta Llama:")
print(f"   - Has token count fields: {('prompt_token_count' in meta_response)}")
print(f"   - Input tokens: {meta_response.get('prompt_token_count', 'N/A')}")
print(f"   - Output tokens: {meta_response.get('generation_token_count', 'N/A')}")
print()

print("❌ Cohere Command:")
print(f"   - Has token count fields: {any(k in cohere_response for k in ['usage', 'token_count'])}")
print(f"   - No token usage data available")
print()

print("❌ Mistral:")
print(f"   - Has token count fields: {any(k in mistral_response for k in ['usage', 'token_count'])}")
print(f"   - No token usage data available")
print()

print("❌ AI21:")
print(f"   - Has token count fields: {any(k in ai21_response for k in ['usage', 'token_count'])}")
print(f"   - No token usage data available")
print()

print("\n=== Summary ===")
print("Models WITH token counts:")
print("  ✅ Anthropic Claude (all versions)")
print("  ✅ Amazon Titan Text Express (legacy format)")
print("  ✅ Amazon Titan Text Premier (new format)")
print("  ✅ Amazon Nova (new format with usage field)")
print("  ✅ Meta Llama (prompt_token_count, generation_token_count)")
print()
print("Models WITHOUT token counts:")
print("  ❌ Cohere Command")
print("  ❌ Mistral")
print("  ❌ AI21")
print()
print("Note: Inference profiles return the same token format as their base models")
