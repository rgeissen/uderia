# Per-User Runtime Context Architecture

## Problem Statement

Currently, `APP_CONFIG.CURRENT_PROVIDER`, `CURRENT_MODEL`, and related runtime configuration variables are stored as class variables in the `AppConfig` singleton. This creates conflicts when multiple users configure different LLM providers simultaneously:

```python
# Current problem:
User A configures: Google/gemini-2.5-flash
User B configures: Anthropic/claude-3-5-haiku

# APP_CONFIG.CURRENT_PROVIDER is SHARED - User B overwrites User A's setting!
APP_CONFIG.CURRENT_PROVIDER = "Anthropic"  # ← Last write wins for ALL users
```

## Proposed Solution

Create a **per-user runtime context** stored in `APP_STATE` that isolates runtime configuration by `user_uuid`.

### Architecture

```python
# New structure in APP_STATE
APP_STATE = {
    # ... existing keys ...
    
    # NEW: Per-user runtime contexts
    "user_runtime_contexts": {
        "user-aaa": {
            "provider": "Google",
            "model": "gemini-2.5-flash",
            "mcp_server_name": "Teradata MCP",
            "mcp_server_id": "server-123",
            "aws_region": None,
            "azure_deployment_details": None,
            "friendli_details": None,
            "model_provider_in_profile": None,
            "llm_instance": <llm_object>,
            "last_access": "2025-11-23T10:00:00Z"
        },
        "user-bbb": {
            "provider": "Anthropic",
            "model": "claude-3-5-haiku-20241022",
            # ... different config ...
        }
    }
}
```

### Helper Functions API

Create new helper functions in `config.py`:

```python
def get_user_runtime_context(user_uuid: str) -> dict:
    """
    Get or create runtime context for a specific user.
    
    Args:
        user_uuid: User UUID
        
    Returns:
        User's runtime context dictionary
    """
    contexts = APP_STATE.setdefault("user_runtime_contexts", {})
    
    if user_uuid not in contexts:
        # Create default context for new user
        contexts[user_uuid] = {
            "provider": None,
            "model": None,
            "mcp_server_name": None,
            "mcp_server_id": None,
            "aws_region": None,
            "azure_deployment_details": None,
            "friendli_details": None,
            "model_provider_in_profile": None,
            "llm_instance": None,
            "mcp_client": None,
            "server_configs": {},
            "last_access": datetime.now(timezone.utc).isoformat()
        }
    
    # Update last access time
    contexts[user_uuid]["last_access"] = datetime.now(timezone.utc).isoformat()
    
    return contexts[user_uuid]


def get_user_provider(user_uuid: str = None) -> str:
    """Get current provider for user. Falls back to global if no user_uuid."""
    if user_uuid:
        return get_user_runtime_context(user_uuid).get("provider")
    return APP_CONFIG.CURRENT_PROVIDER


def set_user_provider(provider: str, user_uuid: str = None):
    """Set current provider for user."""
    if user_uuid:
        get_user_runtime_context(user_uuid)["provider"] = provider
    APP_CONFIG.CURRENT_PROVIDER = provider  # Also set global for backward compatibility


def get_user_model(user_uuid: str = None) -> str:
    """Get current model for user. Falls back to global if no user_uuid."""
    if user_uuid:
        return get_user_runtime_context(user_uuid).get("model")
    return APP_CONFIG.CURRENT_MODEL


def set_user_model(model: str, user_uuid: str = None):
    """Set current model for user."""
    if user_uuid:
        get_user_runtime_context(user_uuid)["model"] = model
    APP_CONFIG.CURRENT_MODEL = model  # Also set global for backward compatibility


def get_user_llm_instance(user_uuid: str = None):
    """Get LLM instance for user."""
    if user_uuid:
        return get_user_runtime_context(user_uuid).get("llm_instance")
    return APP_STATE.get("llm")


def set_user_llm_instance(llm_instance, user_uuid: str = None):
    """Set LLM instance for user."""
    if user_uuid:
        get_user_runtime_context(user_uuid)["llm_instance"] = llm_instance
    APP_STATE["llm"] = llm_instance  # Also set global for backward compatibility


def get_user_mcp_client(user_uuid: str = None):
    """Get MCP client for user."""
    if user_uuid:
        return get_user_runtime_context(user_uuid).get("mcp_client")
    return APP_STATE.get("mcp_client")


def set_user_mcp_client(mcp_client, user_uuid: str = None):
    """Set MCP client for user."""
    if user_uuid:
        get_user_runtime_context(user_uuid)["mcp_client"] = mcp_client
    APP_STATE["mcp_client"] = mcp_client  # Also set global for backward compatibility


def cleanup_inactive_user_contexts(max_age_hours: int = 24):
    """
    Remove runtime contexts for users who haven't accessed in max_age_hours.
    Called periodically to prevent memory leaks.
    """
    
        return  # Only cleanup in multi-user mode
    
    contexts = APP_STATE.get("user_runtime_contexts", {})
    now = datetime.now(timezone.utc)
    inactive_users = []
    
    for user_uuid, context in contexts.items():
        last_access = datetime.fromisoformat(context.get("last_access", now.isoformat()))
        age_hours = (now - last_access).total_seconds() / 3600
        if age_hours > max_age_hours:
            inactive_users.append(user_uuid)
    
    for user_uuid in inactive_users:
        del contexts[user_uuid]
        app_logger.info(f"Cleaned up inactive runtime context for user: {user_uuid}")
```

## Migration Strategy

### Phase 1: Add Helper Functions (Non-Breaking)

1. Add helper functions to `config.py`
2. Keep existing `APP_CONFIG.CURRENT_*` variables for backward compatibility
3. Helper functions update BOTH per-user context AND global config

### Phase 2: Update Code Incrementally

Update files one-by-one to use helper functions. Priority order:

**High Priority** (direct user-facing impact):
1. `api/routes.py` - Main query endpoints
2. `api/rest_routes.py` - REST API endpoints
3. `core/configuration_service.py` - Configuration setup
4. `agent/executor.py` - Query execution

**Medium Priority** (indirect impact):
5. `llm/handler.py` - LLM interactions
6. `mcp/adapter.py` - MCP tool calls
7. `core/session_manager.py` - Session tracking

**Low Priority** (rarely accessed):
8. `agent/planner.py` - Planning logic
9. `agent/rag_retriever.py` - RAG operations

### Phase 3: Add Cleanup Task

Add periodic cleanup to `main.py` startup:

```python
# In main.py startup

    # Schedule cleanup every hour
    async def periodic_cleanup():
        while True:
            await asyncio.sleep(3600)  # 1 hour
            cleanup_inactive_user_contexts()
    
    asyncio.create_task(periodic_cleanup())
```

## Code Changes Required

### File: `src/trusted_data_agent/core/config.py`

**Add at end of file:**

```python
# ==============================================================================
# PER-USER RUNTIME CONTEXT HELPERS
# ==============================================================================

def get_user_runtime_context(user_uuid: str) -> dict:
    """Get or create runtime context for a specific user."""
    # ... implementation from above ...

def get_user_provider(user_uuid: str = None) -> str:
    """Get current provider for user."""
    # ... implementation from above ...

# ... all other helper functions ...
```

### File: `src/trusted_data_agent/api/routes.py`

**Example changes:**

```python
# BEFORE:
session_manager.update_models_used(
    user_uuid=user_uuid, 
    session_id=session_id, 
    provider=APP_CONFIG.CURRENT_PROVIDER,  # ← Global
    model=APP_CONFIG.CURRENT_MODEL,        # ← Global
    profile_tag=profile_tag
)

# AFTER:
from trusted_data_agent.core.config import get_user_provider, get_user_model

session_manager.update_models_used(
    user_uuid=user_uuid, 
    session_id=session_id, 
    provider=get_user_provider(user_uuid),  # ← Per-user
    model=get_user_model(user_uuid),        # ← Per-user
    profile_tag=profile_tag
)
```

### File: `src/trusted_data_agent/core/configuration_service.py`

```python
# BEFORE:
APP_CONFIG.CURRENT_PROVIDER = provider
APP_CONFIG.CURRENT_MODEL = model
APP_STATE['llm'] = temp_llm_instance

# AFTER:
from trusted_data_agent.core.config import (
    set_user_provider, set_user_model, set_user_llm_instance
)

set_user_provider(provider, user_uuid)
set_user_model(model, user_uuid)
set_user_llm_instance(temp_llm_instance, user_uuid)
```

### File: `src/trusted_data_agent/agent/executor.py`

```python
# BEFORE:
self.current_model = APP_CONFIG.CURRENT_MODEL
self.current_provider = APP_CONFIG.CURRENT_PROVIDER

# AFTER:
from trusted_data_agent.core.config import get_user_provider, get_user_model

self.current_model = get_user_model(self.user_uuid)
self.current_provider = get_user_provider(self.user_uuid)
```

## Behavior Modes



## Testing Strategy

### Unit Tests

```python
def test_per_user_runtime_context():
    """Test that users get isolated runtime contexts."""
    user_a = "user-aaa"
    user_b = "user-bbb"
    
    set_user_provider("Google", user_a)
    set_user_model("gemini-2.5-flash", user_a)
    
    set_user_provider("Anthropic", user_b)
    set_user_model("claude-3-5-haiku", user_b)
    
    # Verify isolation
    assert get_user_provider(user_a) == "Google"
    assert get_user_provider(user_b) == "Anthropic"
    assert get_user_model(user_a) == "gemini-2.5-flash"
    assert get_user_model(user_b) == "claude-3-5-haiku"


def test_context_cleanup():
    """Test that old contexts are cleaned up."""
    user_old = "user-old"
    user_new = "user-new"
    
    # Create old context
    context = get_user_runtime_context(user_old)
    context["last_access"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    
    # Create new context
    get_user_runtime_context(user_new)
    
    # Run cleanup
    cleanup_inactive_user_contexts(max_age_hours=24)
    
    # Verify old removed, new retained
    contexts = APP_STATE["user_runtime_contexts"]
    assert user_old not in contexts
    assert user_new in contexts
```

### Integration Tests

1. **Multi-user simultaneous configuration**: Two users configure different providers
2. **Session persistence**: User A's sessions use correct provider after User B configures
3. **Cleanup verification**: Old user contexts are removed after inactivity
4. **Backward compatibility**: Works correctly with existing configurations

## Rollout Plan

### Phase 1: Week 1
- Add helper functions to `config.py`
- Add unit tests
- Update documentation

### Phase 2: Week 2
- Update high-priority files (api/, core/)
- Run integration tests
- Deploy to staging

### Phase 3: Week 3
- Update medium-priority files (llm/, mcp/, agent/)
- Run full test suite
- Deploy to production

### Phase 4: Week 4
- Update low-priority files
- Add cleanup task
- Monitor for issues

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing deployments | High | Keep global variables, update gradually |
| Memory leaks from contexts | Medium | Add periodic cleanup task |
| Race conditions in multi-user | Medium | Use locks when updating contexts |
| Incomplete migration | Medium | Keep both paths working during transition |

## Success Metrics

- ✅ No cross-user configuration conflicts in logs
- ✅ All integration tests pass
- ✅ Memory usage stable with 10+ concurrent users
- ✅ Zero production incidents related to provider/model mismatch

## Future Enhancements

1. **Request-scoped context**: Pass user context through request chain explicitly
2. **Database-backed contexts**: Store active contexts in Redis for multi-container
3. **Context inheritance**: Allow sessions to inherit context from creation time
4. **Admin dashboard**: View all active user contexts and their configurations

## Questions & Decisions

### Q: Should we maintain backward compatibility forever?
**A**: Keep for 2-3 releases, then deprecate global variables with warnings.

### Q: What about MCP clients - per-user or shared?
**A**: Per-user in phase 1. Each user can connect to different MCP servers.

### Q: How to handle profile overrides?
**A**: Profile override already stores provider/model - just needs to use helper functions.

### Q: Performance impact of helper function calls?
**A**: Negligible - single dictionary lookup. Can add caching if needed.

---

**Document Version**: 1.0  
**Date**: 2025-11-23  
**Author**: GitHub Copilot  
**Status**: Proposed
