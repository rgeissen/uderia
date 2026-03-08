# @TAG Profile Override System - Implementation Summary

## Overview
Implemented a temporary profile override system that allows users to execute queries with a different profile's configuration using the `@TAG` syntax, without permanently switching profiles.

## User Experience

### Usage
```
@AWS show me all tables
@TERADATA list databases
@LOCALDB query customer data
```

### Behavior
1. **Default Profile**: Used for normal queries and system configuration
2. **@TAG Override**: Temporarily switches to tagged profile for single query
3. **Autocomplete**: Shows suggestions from override profile when @TAG is typed
4. **Reversion**: Automatically reverts to default profile after query completes

## Architecture

### Frontend Flow

#### 1. Autocomplete Enhancement (`static/js/main.js`)
```javascript
// Detects @TAG and filters autocomplete
const tagMatch = trimmedQuery.match(/^@(\w+)\s+(.+)/);
if (tagMatch) {
    const [_, tag, searchQuery] = tagMatch;
    const profile = profiles.find(p => p.tag?.toLowerCase() === tag.toLowerCase());
    if (profile) {
        profileId = profile.id;
        queryText = searchQuery; // Search without @TAG
    }
}
```

#### 2. Query Submission (`static/js/eventHandlers.js`)
```javascript
// Parses @TAG and extracts profile_override_id
const tagMatch = fullMessage.match(/^@(\w+)\s+(.+)/);
if (tagMatch) {
    const [_, tag, restOfMessage] = tagMatch;
    const profile = profiles.find(p => p.tag?.toLowerCase() === tag.toLowerCase());
    if (profile) {
        requestBody.profile_override_id = profile.id;
        requestBody.query = restOfMessage; // Query without @TAG
    }
}
```

### Backend Flow

#### 1. Request Reception (`src/trusted_data_agent/api/routes.py`)
```python
# Extracts profile_override_id from request
profile_override_id = data.get("profile_override_id")

# Determines profile tag for session metadata
if profile_override_id:
    override_profile = next((p for p in profiles if p.get("id") == profile_override_id), None)
    profile_tag = override_profile.get("tag") if override_profile else None
else:
    default_profile_id = config_manager.get_default_profile_id()
    # ... use default profile tag
```

#### 2. Executor Initialization (`src/trusted_data_agent/agent/executor.py`)
```python
def __init__(self, ..., profile_override_id: str = None, ...):
    self.profile_override_id = profile_override_id
    self.original_llm = None  # Storage for restoration
    self.original_mcp_tools = None
    self.original_mcp_prompts = None
```

#### 3. Temporary Profile Setup (`executor.py` - run() method start)
```python
if self.profile_override_id:
    # Store original state
    self.original_llm = APP_STATE.get('llm')
    self.original_mcp_tools = APP_STATE.get('mcp_tools')
    self.original_mcp_prompts = APP_STATE.get('mcp_prompts')
    
    # Get override profile configuration
    override_profile = config_manager.get_profile_by_id(self.profile_override_id)
    
    # Create temporary LLM instance
    if override_llm_config:
        provider = override_llm_config.get('provider')
        model = override_llm_config.get('model')
        credentials = override_llm_config.get('credentials', {})
        
        # Provider-specific client creation
        if provider == "Google":
            genai.configure(api_key=credentials.get("apiKey"))
            temp_llm_instance = genai.GenerativeModel(model_name=model)
        elif provider == "Amazon":
            temp_llm_instance = boto3.client(
                service_name='bedrock-runtime',
                aws_access_key_id=credentials.get("aws_access_key_id"),
                aws_secret_access_key=credentials.get("aws_secret_access_key"),
                region_name=credentials.get("aws_region")
            )
        # ... other providers
        
        APP_STATE['llm'] = temp_llm_instance
    
    # Create temporary MCP client with filtered tools/prompts
    if override_mcp_server:
        mcp_server_url = f"http://{host}:{port}{path}"
        temp_mcp_client = MultiServerMCPClient({server_name: {"url": mcp_server_url, "transport": "streamable_http"}})
        
        # Filter by enabled tools/prompts
        enabled_tool_names = set(config_manager.get_profile_enabled_tools(self.profile_override_id))
        enabled_prompt_names = set(config_manager.get_profile_enabled_prompts(self.profile_override_id))
        
        filtered_tools = [tool for tool in all_tools if tool.name in enabled_tool_names]
        filtered_prompts = [prompt for prompt in all_prompts if prompt.name in enabled_prompt_names]
        
        APP_STATE['mcp_client'] = temp_mcp_client
        APP_STATE['mcp_tools'] = filtered_tools
        APP_STATE['mcp_prompts'] = filtered_prompts
```

#### 4. Query Execution
- Executor runs normally with temporary APP_STATE values
- LLM uses override provider/model
- MCP tools/prompts use filtered lists from override profile
- No MCP resource re-classification occurs

#### 5. State Restoration (`executor.py` - finally block)
```python
finally:
    if self.profile_override_id:
        # Restore original state
        if self.original_llm is not None:
            APP_STATE['llm'] = self.original_llm
        if self.original_mcp_tools is not None:
            APP_STATE['mcp_tools'] = self.original_mcp_tools
        if self.original_mcp_prompts is not None:
            APP_STATE['mcp_prompts'] = self.original_mcp_prompts
```

## Key Design Decisions

### 1. Reuse Existing Infrastructure
- Uses same LLM client creation patterns from `configuration_service.py`
- Uses same MCP client creation from `MultiServerMCPClient`
- Uses existing tool/prompt filtering from `config_manager`

### 2. Minimal State Changes
- Only modifies `APP_STATE['llm']`, `APP_STATE['mcp_tools']`, `APP_STATE['mcp_prompts']`
- Does not modify `APP_CONFIG` global settings (except temporarily during execution)
- Does not re-classify MCP resources

### 3. Automatic Cleanup
- `finally` block ensures restoration even on errors
- Temporary MCP client auto-closed by context managers
- No orphaned state after execution

### 4. Profile Precedence
- Default profile: Normal queries, system configuration
- Active profiles: RAG autocomplete filtering only
- Override profile: Temporary execution context via @TAG

## Testing Checklist

- [ ] @TAG detected in autocomplete input
- [ ] Autocomplete shows override profile's RAG questions
- [ ] @TAG parsed correctly in submission
- [ ] profile_override_id passed to backend
- [ ] Temporary LLM instance created for override provider
- [ ] Temporary MCP client created for override server
- [ ] Tools/prompts filtered to override profile's enabled lists
- [ ] Query executes with override context
- [ ] Original LLM/MCP state restored after execution
- [ ] Subsequent queries use default profile
- [ ] Error cases handled gracefully (invalid tag, missing profile)
- [ ] Multiple consecutive overrides work correctly

## Supported LLM Providers

1. **Google** - `google.generativeai`
2. **Anthropic** - `AsyncAnthropic`
3. **OpenAI** - `AsyncOpenAI`
4. **Amazon Bedrock** - `boto3.client('bedrock-runtime')`
5. **Azure** - `AsyncAzureOpenAI`
6. **Friendli.ai** - `AsyncOpenAI` with custom base_url
7. **Ollama** - `OllamaClient`

## Files Modified

1. `src/trusted_data_agent/agent/executor.py`
   - Added `profile_override_id` parameter to `__init__`
   - Added temporary state storage variables
   - Implemented profile override setup in `run()` method
   - Implemented state restoration in `finally` block

2. `src/trusted_data_agent/api/routes.py`
   - Added profile_override_id extraction from request
   - Modified profile tag determination logic
   - Passed profile_override_id to execution_service

3. `src/trusted_data_agent/agent/execution_service.py`
   - Added profile_override_id parameter (already present)
   - Passed to PlanExecutor

4. `static/js/main.js`
   - Added @TAG parsing for autocomplete
   - Modified fetchAndShowSuggestions to use override profile

5. `static/js/eventHandlers.js`
   - Added @TAG parsing for query submission
   - Extracted profile_override_id and stripped @TAG from message

## Benefits

1. **No Configuration Disruption**: Default profile remains configured
2. **Quick Profile Testing**: Test different profiles without full reconfiguration
3. **Use Case Flexibility**: Different profiles for different query types
4. **Clean State Management**: Automatic restoration prevents state corruption
5. **Intuitive UX**: Simple @TAG syntax familiar to users

## Future Enhancements

1. Auto-suggest profile tags when typing @
2. Visual indicator showing active override in UI
3. Profile override history/tracking
4. Support for multiple concurrent sessions with different overrides
5. Caching of temporary LLM/MCP clients for performance
