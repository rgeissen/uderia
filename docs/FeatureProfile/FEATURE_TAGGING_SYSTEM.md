# Feature Tagging System

## Overview

The Feature Tagging System provides granular control over application features based on user profile tiers. Each feature is tagged with its minimum required tier, allowing dynamic enable/disable of functionality throughout the application.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Feature Tags (Enum)                     │
│  68 distinct features across all application areas          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│               Feature-to-Tier Mapping (Dict)                │
│  Maps each feature to its minimum required tier             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              Access Control Functions                        │
│  • user_has_feature()    • get_user_features()             │
│  • @require_feature()    • feature groups                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│            Application Layer (UI/API)                        │
│  Conditionally shows/hides features based on user tier      │
└─────────────────────────────────────────────────────────────┘
```

---

## Feature Categories

### 1. Core Execution (User Tier)
- `EXECUTE_PROMPTS` - Execute AI prompts
- `USE_MCP_TOOLS` - Use Model Context Protocol tools
- `VIEW_EXECUTION_RESULTS` - View execution results

### 2. Session Management
**User Tier:**
- `VIEW_OWN_SESSIONS` - View own session history
- `DELETE_OWN_SESSIONS` - Delete own sessions
- `EXPORT_OWN_SESSIONS` - Export own sessions

**Developer Tier:**
- `VIEW_ALL_SESSIONS` - View all users' sessions
- `EXPORT_ALL_SESSIONS` - Export all sessions
- `SESSION_ANALYTICS` - Advanced session analytics

### 3. Credential Management (User Tier)
- `STORE_CREDENTIALS` - Store encrypted credentials
- `USE_STORED_CREDENTIALS` - Use auto-load feature
- `DELETE_OWN_CREDENTIALS` - Delete own credentials

### 4. RAG Management (Developer Tier)
- `CREATE_RAG_COLLECTIONS` - Create new RAG collections
- `EDIT_RAG_COLLECTIONS` - Edit existing collections
- `DELETE_RAG_COLLECTIONS` - Delete collections
- `REFRESH_RAG_COLLECTIONS` - Refresh vector store
- `VIEW_RAG_STATISTICS` - View RAG statistics

### 5. Template Management (Developer Tier)
- `CREATE_TEMPLATES` - Create new templates
- `EDIT_TEMPLATES` - Edit existing templates
- `DELETE_TEMPLATES` - Delete templates
- `TEST_TEMPLATES` - Test template functionality
- `PUBLISH_TEMPLATES` - Publish templates

### 6. User Management (Admin Tier)
- `VIEW_ALL_USERS` - View all users
- `CREATE_USERS` - Create new users
- `EDIT_USERS` - Edit user details
- `DELETE_USERS` - Delete/deactivate users
- `UNLOCK_USERS` - Unlock locked accounts
- `CHANGE_USER_TIERS` - Change user profile tiers

### 7. System Administration (Admin Tier)
- `VIEW_SYSTEM_STATS` - View system statistics
- `VIEW_ALL_AUDIT_LOGS` - View all audit logs
- `MONITOR_PERFORMANCE` - Monitor system performance
- `MANAGE_DATABASE` - Database administration
- `CONFIGURE_SECURITY` - Security configuration

---

## Python API

### Module Location
```python
from trusted_data_agent.auth.features import (
    Feature,
    user_has_feature,
    get_user_features,
    require_feature,
    FEATURE_GROUPS
)
```

### Check Single Feature

```python
from trusted_data_agent.auth.features import Feature, user_has_feature

user = get_current_user_from_request()

if user_has_feature(user, Feature.CREATE_RAG_COLLECTIONS):
    # Show RAG creation UI
    enable_rag_creation_button()
else:
    # Hide or disable feature
    hide_rag_creation_button()
```

### Get All User Features

```python
from trusted_data_agent.auth.features import get_user_features

user = get_current_user_from_request()
features = get_user_features(user)

# Returns Set[Feature] with all available features
if Feature.VIEW_ALL_SESSIONS in features:
    show_all_sessions_view()
```

### Protect API Endpoint

```python
from trusted_data_agent.auth.features import Feature, require_feature

@rest_api_bp.route('/api/v1/rag/collections', methods=['POST'])
@require_feature(Feature.CREATE_RAG_COLLECTIONS)
async def create_rag_collection():
    # Only users with developer tier or higher can access
    ...
```

### Check Feature Groups

```python
from trusted_data_agent.auth.features import user_has_feature_group

user = get_current_user_from_request()

# Check if user has ANY feature from group
if user_has_feature_group(user, 'rag_management'):
    show_rag_menu()

# Check if user has ALL features from group
from trusted_data_agent.auth.features import user_has_all_features_in_group
if user_has_all_features_in_group(user, 'system_admin'):
    enable_admin_dashboard()
```

---

## REST API

### Get User Features

**Endpoint:** `GET /api/v1/auth/me/features`

**Headers:**
```
Authorization: Bearer <token>
```

**Response:**
```json
{
  "status": "success",
  "profile_tier": "developer",
  "features": [
    "execute_prompts",
    "use_mcp_tools",
    "view_own_sessions",
    "create_rag_collections",
    "edit_rag_collections",
    "create_templates"
  ],
  "feature_groups": {
    "session_management": true,
    "rag_management": true,
    "template_management": true,
    "user_management": false,
    "system_admin": false
  },
  "feature_count": 35
}
```

**Usage Example:**
```bash
curl -X GET http://127.0.0.1:5050/api/v1/auth/me/features \
  -H "Authorization: Bearer <token>"
```

---

## Frontend Integration

### JavaScript/TypeScript

```typescript
// Fetch user features on login
async function loadUserFeatures() {
  const response = await fetch('/api/v1/auth/me/features', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  const data = await response.json();
  return new Set(data.features);
}

// Check feature availability
const userFeatures = await loadUserFeatures();

if (userFeatures.has('create_rag_collections')) {
  // Show RAG creation button
  document.getElementById('createRagBtn').style.display = 'block';
} else {
  // Hide RAG creation button
  document.getElementById('createRagBtn').style.display = 'none';
}

// Check feature groups
const featureGroups = data.feature_groups;
if (featureGroups.rag_management) {
  // Show RAG menu section
  showRagMenu();
}
```

### React Example

```jsx
import { useState, useEffect } from 'react';

function useUserFeatures() {
  const [features, setFeatures] = useState(new Set());
  const [featureGroups, setFeatureGroups] = useState({});
  
  useEffect(() => {
    fetch('/api/v1/auth/me/features', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(res => res.json())
    .then(data => {
      setFeatures(new Set(data.features));
      setFeatureGroups(data.feature_groups);
    });
  }, [token]);
  
  return { features, featureGroups };
}

// Component usage
function RagManagementButton() {
  const { features } = useUserFeatures();
  
  if (!features.has('create_rag_collections')) {
    return null; // Don't render if feature not available
  }
  
  return <button onClick={createRag}>Create RAG Collection</button>;
}

// Conditional rendering based on group
function AdminDashboard() {
  const { featureGroups } = useUserFeatures();
  
  return (
    <div>
      {featureGroups.user_management && <UserManagementPanel />}
      {featureGroups.system_admin && <SystemAdminPanel />}
    </div>
  );
}
```

---

## Feature Groups

Pre-defined groups of related features for bulk checking:

### Available Groups

1. **session_management** - Session viewing, export, analytics
2. **rag_management** - RAG collection CRUD operations
3. **template_management** - Template creation and management
4. **user_management** - User administration
5. **system_admin** - System-level administration

### Usage

```python
from trusted_data_agent.auth.features import FEATURE_GROUPS

# Get all features in a group
rag_features = FEATURE_GROUPS['rag_management']
# Returns: {
#   Feature.CREATE_RAG_COLLECTIONS,
#   Feature.EDIT_RAG_COLLECTIONS,
#   Feature.DELETE_RAG_COLLECTIONS,
#   Feature.REFRESH_RAG_COLLECTIONS,
#   Feature.VIEW_RAG_STATISTICS
# }

# Check if user has access to the group
if user_has_feature_group(user, 'rag_management'):
    show_rag_menu()
```

---

## Complete Feature List

### User Tier (19 features)

**Core Execution:**
- execute_prompts
- use_mcp_tools
- view_execution_results

**Session Management:**
- view_own_sessions
- delete_own_sessions
- export_own_sessions

**Credentials:**
- store_credentials
- use_stored_credentials
- delete_own_credentials

**Configuration:**
- basic_configuration
- select_provider
- select_model
- select_mcp_server

**Profile & Audit:**
- view_own_audit_logs
- update_own_profile
- change_own_password

**UI Features:**
- use_voice_conversation
- use_charting
- basic_ui_access

### Developer Tier (+25 features = 44 total)

**Advanced Sessions:**
- view_all_sessions
- export_all_sessions
- session_analytics

**RAG Management:**
- create_rag_collections
- edit_rag_collections
- delete_rag_collections
- refresh_rag_collections
- view_rag_statistics

**Templates:**
- create_templates
- edit_templates
- delete_templates
- test_templates
- publish_templates

**MCP Development:**
- test_mcp_connections
- view_mcp_diagnostics
- configure_mcp_servers

**Advanced Config:**
- advanced_configuration
- configure_optimization
- configure_rag_settings

**Import/Export:**
- export_configurations
- import_configurations
- bulk_operations

**Dev Tools:**
- view_debug_logs
- access_api_documentation
- use_developer_console

### Admin Tier (+24 features = 68 total)

**User Management:**
- view_all_users
- create_users
- edit_users
- delete_users
- unlock_users
- change_user_tiers

**Credential Oversight:**
- view_all_credentials
- delete_any_credentials

**System Config:**
- modify_global_config
- manage_feature_flags
- configure_security

**Monitoring:**
- view_system_stats
- view_all_audit_logs
- monitor_performance
- view_error_logs

**Database:**
- manage_database
- run_migrations
- backup_database

**Security & Compliance:**
- manage_encryption_keys
- configure_authentication
- manage_audit_settings
- export_compliance_reports

---

## Adding New Features

### Step 1: Add Feature to Enum

```python
# In src/trusted_data_agent/auth/features.py

class Feature(str, Enum):
    # ... existing features ...
    
    # NEW FEATURE
    MY_NEW_FEATURE = "my_new_feature"
```

### Step 2: Map Feature to Tier

```python
# In FEATURE_TIER_MAP dictionary

FEATURE_TIER_MAP = {
    # ... existing mappings ...
    
    Feature.MY_NEW_FEATURE: PROFILE_TIER_DEVELOPER,  # Requires developer tier
}
```

### Step 3: (Optional) Add to Feature Group

```python
# In FEATURE_GROUPS dictionary

FEATURE_GROUPS = {
    "my_feature_category": {
        Feature.MY_NEW_FEATURE,
        Feature.RELATED_FEATURE,
    },
}
```

### Step 4: Use in Application

```python
# Protect endpoint
@rest_api_bp.route('/api/v1/my-feature')
@require_feature(Feature.MY_NEW_FEATURE)
async def my_feature_endpoint():
    ...

# Check in code
if user_has_feature(user, Feature.MY_NEW_FEATURE):
    enable_my_feature()
```

---

## Testing

### Test Feature Access

```python
def test_user_feature_access():
    """Test that users have correct feature access"""
    from trusted_data_agent.auth.features import get_features_by_tier
    
    # User tier should have basic features
    user_features = get_features_by_tier('user')
    assert Feature.EXECUTE_PROMPTS in user_features
    assert Feature.CREATE_RAG_COLLECTIONS not in user_features
    
    # Developer tier should inherit user features + dev features
    dev_features = get_features_by_tier('developer')
    assert Feature.EXECUTE_PROMPTS in dev_features  # Inherited
    assert Feature.CREATE_RAG_COLLECTIONS in dev_features  # Developer feature
    assert Feature.VIEW_ALL_USERS not in dev_features  # Admin only
    
    # Admin tier should have all features
    admin_features = get_features_by_tier('admin')
    assert len(admin_features) == 68  # All features
```

### Test Feature Endpoint Protection

```bash
# User tier trying to access developer feature (should fail)
curl -X POST http://127.0.0.1:5050/api/v1/rag/collections \
  -H "Authorization: Bearer <user_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"test"}'

# Expected: 403 Forbidden
# {
#   "status": "error",
#   "message": "Feature 'create_rag_collections' requires developer tier (you have user)"
# }

# Developer tier accessing same feature (should succeed)
curl -X POST http://127.0.0.1:5050/api/v1/rag/collections \
  -H "Authorization: Bearer <developer_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"test"}'

# Expected: 200 OK
```

---

## Best Practices

### 1. Always Check Features in UI

```javascript
// ✅ GOOD: Check before rendering
if (features.has('create_templates')) {
  renderCreateTemplateButton();
}

// ❌ BAD: Render without checking
renderCreateTemplateButton(); // Shows to all users
```

### 2. Use Feature Groups for Menus

```python
# ✅ GOOD: Show entire menu section if user has any feature
if user_has_feature_group(user, 'rag_management'):
    show_rag_menu()

# ❌ BAD: Check each feature individually
if (user_has_feature(user, Feature.CREATE_RAG_COLLECTIONS) or
    user_has_feature(user, Feature.EDIT_RAG_COLLECTIONS) or
    user_has_feature(user, Feature.DELETE_RAG_COLLECTIONS)):
    show_rag_menu()
```

### 3. Protect Both API and UI

```python
# Backend protection
@require_feature(Feature.DELETE_USERS)
async def delete_user_endpoint():
    ...

# Frontend should also hide button
# This is defense in depth - even if user hacks frontend,
# backend will still reject the request
```

### 4. Cache Features in Frontend

```javascript
// ✅ GOOD: Load once on login, cache in memory
const features = await loadUserFeatures();
localStorage.setItem('userFeatures', JSON.stringify([...features]));

// ❌ BAD: Fetch on every feature check
async function hasFeature(feature) {
  const response = await fetch('/api/v1/auth/me/features');
  const data = await response.json();
  return data.features.includes(feature);
}
```

### 5. Use Semantic Feature Names

```python
# ✅ GOOD: Clear, descriptive names
Feature.CREATE_RAG_COLLECTIONS
Feature.VIEW_ALL_AUDIT_LOGS

# ❌ BAD: Vague or abbreviated names
Feature.RAG_CREATE
Feature.LOGS
```

---

## Migration Guide

### Existing Code Without Feature Tags

**Before:**
```python
@rest_api_bp.route('/api/v1/rag/collections')
@require_developer  # Only checks tier
async def create_rag():
    ...
```

**After:**
```python
from trusted_data_agent.auth.features import Feature, require_feature

@rest_api_bp.route('/api/v1/rag/collections')
@require_feature(Feature.CREATE_RAG_COLLECTIONS)  # Checks specific feature
async def create_rag():
    ...
```

**Benefits:**
- More granular control
- Self-documenting code
- Easier to change tier requirements
- Clear feature inventory

---

## Summary

The Feature Tagging System provides:

✅ **68 distinct features** across all application areas  
✅ **Hierarchical access control** - Higher tiers inherit lower tier features  
✅ **Granular permissions** - Control individual features, not just tier levels  
✅ **Feature groups** - Bulk checking for related features  
✅ **REST API** - Frontend can query available features  
✅ **Decorator support** - Easy endpoint protection with `@require_feature`  
✅ **Self-documenting** - Feature enum provides clear inventory  
✅ **Extensible** - Easy to add new features without breaking changes  

The system integrates seamlessly with the 3-tier profile system while providing flexibility for future granular permission requirements.
