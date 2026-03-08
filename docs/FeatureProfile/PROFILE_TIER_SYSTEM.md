# Profile Tier System Implementation

## Overview

The Uderia Platform now implements a **3-tier hierarchical profile system** for role-based access control (RBAC). Every authenticated user is assigned one of three profile tiers:

1. **User** (default) - Basic access
2. **Developer** - Advanced features
3. **Admin** - Full system access

## Tier Hierarchy

Higher tiers inherit all permissions from lower tiers:

```
Admin (highest privileges)
  ↓ inherits from
Developer
  ↓ inherits from
User (basic privileges)
```

## Feature Access by Tier

### 👤 User Tier (Default for New Registrations)

**Basic Application Access:**
- Execute prompts and use MCP tools
- View own session history only
- Use stored credentials (auto-load)
- Basic configuration access
- View own audit logs
- Standard REST API endpoints

**Restrictions:**
- Cannot view other users' sessions
- Cannot manage RAG collections
- Cannot access admin endpoints
- Cannot create/edit templates

---

### 🔧 Developer Tier

**All User Tier Features +**

**Advanced Features:**
- View all sessions (when `SESSIONS_FILTER_BY_USER=false`)
- RAG collection management (create/edit/delete collections)
- Template creation and testing
- MCP server connection testing
- Advanced configuration options
- Export/import capabilities
- Developer-specific API endpoints

**Typical Use Cases:**
- Power users who need advanced analytics
- Data scientists creating custom templates
- Developers testing MCP integrations
- Users managing team-wide RAG knowledge bases

---

### 👑 Admin Tier

**All Developer Tier Features +**

**System Administration:**
- User management (promote/demote/unlock/delete users)
- Change any user's profile tier
- Credential management oversight (all users)
- System statistics and monitoring
- Full audit log access (all users)
- Global configuration changes
- Security settings management
- Database administration

**Admin-Only API Endpoints:**
- `GET /api/v1/admin/users` - List all users
- `GET /api/v1/admin/users/<id>` - View user details
- `PATCH /api/v1/admin/users/<id>` - Update user
- `DELETE /api/v1/admin/users/<id>` - Deactivate user
- `PATCH /api/v1/admin/users/<id>/tier` - Change user's tier
- `POST /api/v1/admin/users/<id>/unlock` - Unlock locked account
- `GET /api/v1/admin/stats` - System statistics

---

## Database Schema

### User Model Changes

```python
class User(Base):
    # ... existing fields ...
    
    # NEW: Profile tier field
    profile_tier = Column(String(20), default='user', nullable=False)
    # Values: 'user', 'developer', 'admin'
    
    # Legacy field (kept for backward compatibility)
    is_admin = Column(Boolean, default=False, nullable=False)
    # Automatically synced: is_admin=True when profile_tier='admin'
```

**Migration:**
- New column: `profile_tier` (default: `'user'`)
- Existing users with `is_admin=True` migrated to `profile_tier='admin'`
- Index created on `profile_tier` for query performance

---

## API Usage

### Check User's Tier

**Endpoint:** `GET /api/v1/auth/me`

**Response:**
```json
{
  "user": {
    "id": "...",
    "username": "john_doe",
    "profile_tier": "developer",
    "is_admin": false
  }
}
```

---

### Promote User (Admin Only)

**Endpoint:** `PATCH /api/v1/admin/users/<user_id>/tier`

**Request:**
```json
{
  "profile_tier": "developer"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "User promoted to developer tier",
  "user": {
    "id": "abc-123",
    "username": "john_doe",
    "profile_tier": "developer",
    "is_admin": false
  }
}
```

**Valid Tiers:** `"user"`, `"developer"`, `"admin"`

---

### Get System Statistics (Admin Only)

**Endpoint:** `GET /api/v1/admin/stats`

**Response:**
```json
{
  "status": "success",
  "stats": {
    "total_users": 50,
    "active_users": 45,
    "admin_users": 2,
    "tier_distribution": {
      "user": 40,
      "developer": 8,
      "admin": 2
    },
    "recent_logins_24h": 25,
    "recent_registrations_7d": 5
  }
}
```

---

## Permission Decorators

### Python Implementation

```python
from trusted_data_agent.auth.admin import require_tier, require_developer, require_admin

# User tier or higher (all authenticated users)
@rest_api_bp.route('/api/v1/execute')
async def execute_prompt():
    # Any authenticated user can access
    ...

# Developer tier or higher
@rest_api_bp.route('/api/v1/developer/rag')
@require_developer
async def manage_rag():
    # Only developer and admin tiers
    ...

# Admin tier only
@rest_api_bp.route('/api/v1/admin/users')
@require_admin
async def list_users():
    # Only admin tier
    ...

# Custom tier requirement
@rest_api_bp.route('/api/v1/custom')
@require_tier('developer')
async def custom_endpoint():
    # Minimum developer tier required
    ...
```

### Helper Functions

```python
from trusted_data_agent.auth.admin import (
    get_user_tier,      # Get user's tier: 'user', 'developer', or 'admin'
    has_tier,           # Check if user has minimum tier (hierarchical)
    is_admin,           # Check if user is admin tier
    is_developer        # Check if user is developer or admin tier
)

user = get_current_user_from_request()

# Get tier
tier = get_user_tier(user)  # Returns: 'user', 'developer', or 'admin'

# Hierarchical check
if has_tier(user, 'developer'):
    # User is developer OR admin
    ...

# Specific checks
if is_admin(user):
    # User is admin tier
    ...

if is_developer(user):
    # User is developer or admin tier
    ...
```

---

## Configuration

### Session Filtering by Tier

The `SESSIONS_FILTER_BY_USER` configuration is now tier-aware:

```python
# In config.py
SESSIONS_FILTER_BY_USER = os.environ.get('TDA_SESSIONS_FILTER_BY_USER', 'true').lower() == 'true'
```

**Behavior:**
- **User tier**: Always filtered to own sessions (cannot override)
- **Developer tier**: Can view all sessions when `SESSIONS_FILTER_BY_USER=false`
- **Admin tier**: Can view all sessions by default

**Environment Variable:**
```bash
# User tier sees only their own sessions (enforced)
# Developer/Admin can see all sessions
export TDA_SESSIONS_FILTER_BY_USER=false
```

---

## Admin Self-Protection

Admins cannot modify their own profile tier to prevent accidental lockout:

**Restriction:** `can_manage_user(admin, target_user_id)` returns `False` if `admin.id == target_user_id`

**Error Response:**
```json
{
  "status": "error",
  "message": "Cannot modify your own profile tier"
}
```

**Workaround:** Another admin must change your tier.

---

## Backward Compatibility

### Legacy `is_admin` Field

The `is_admin` boolean field is maintained for backward compatibility:

**Sync Rules:**
- `profile_tier='admin'` → `is_admin=True`
- `profile_tier='developer'` → `is_admin=False`
- `profile_tier='user'` → `is_admin=False`

**Migration:**
- Existing users with `is_admin=True` automatically get `profile_tier='admin'`
- Code checking `is_admin` continues to work

---

## Testing

### Create Test Users

```bash
# Register user (defaults to 'user' tier)
curl -X POST http://127.0.0.1:5050/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"user1","email":"user1@test.com","password":"Pass123!"}'

# Promote to developer (requires admin token)
curl -X PATCH http://127.0.0.1:5050/api/v1/admin/users/<user_id>/tier \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"profile_tier":"developer"}'

# Promote to admin
curl -X PATCH http://127.0.0.1:5050/api/v1/admin/users/<user_id>/tier \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"profile_tier":"admin"}'
```

### Verify Tier

```bash
curl -X GET http://127.0.0.1:5050/api/v1/auth/me \
  -H "Authorization: Bearer <token>"
```

---

## Security Considerations

1. **Default Tier:** New users always start as `'user'` tier (principle of least privilege)
2. **Promotion Only:** Only admins can change profile tiers
3. **No Demotion Lock:** Admins can be demoted by other admins (no permanent admin lock)
4. **Self-Protection:** Admins cannot modify their own tier
5. **Audit Logging:** All tier changes logged in `audit_logs` table
6. **Session Isolation:** User tier enforces session filtering regardless of config

---

## Audit Logging

All tier changes are logged:

```python
audit.log_admin_action(
    admin_user.id,
    "tier_change",
    target_user.id,
    f"Changed profile tier: user -> developer"
)
```

**Query Audit Logs:**
```bash
curl -X GET http://127.0.0.1:5050/api/v1/auth/me/audit-logs \
  -H "Authorization: Bearer <token>"
```

---

## Migration Guide

### For Existing Deployments

1. **Run Migration Script:**
   ```bash
   python3 add_profile_tier_column.py
   ```

2. **Verify Migration:**
   - Check that `profile_tier` column exists
   - Verify admin users have `profile_tier='admin'`
   - Check tier distribution statistics

3. **Restart Server:**
   ```bash
   ./start_with_auth.sh
   ```

4. **Promote Users as Needed:**
   - Use admin API to promote developers
   - Document tier assignments for your team

### For New Deployments

- Profile tier system is active by default
- All new users start as `'user'` tier
- First registered user should be promoted to admin

---

## Recommended Tier Assignment Strategy

### Small Teams (1-10 users)
- **1-2 admins**: IT/DevOps staff
- **2-3 developers**: Power users, data scientists
- **Rest as users**: Standard analysts, business users

### Medium Teams (10-50 users)
- **2-3 admins**: IT admins, security officers
- **5-10 developers**: Technical leads, ML engineers
- **Rest as users**: Analysts, business intelligence users

### Large Deployments (50+ users)
- **3-5 admins**: Distributed admin team
- **10-20% developers**: Technical staff, power users
- **80-90% users**: General user population

---

## Future Enhancements

Potential additions to the tier system:

1. **Custom Tiers:** Allow defining custom tiers beyond the default 3
2. **Role Permissions:** Granular permission matrix (e.g., "can_create_templates")
3. **Temporary Elevation:** Time-limited tier promotions
4. **Group/Team Tiers:** Assign tiers to groups instead of individuals
5. **Tier-Based Rate Limiting:** Different API rate limits per tier
6. **Tier-Based Resource Quotas:** Storage/compute limits per tier

---

## Troubleshooting

### User Can't Access Developer Features

**Check tier:**
```bash
curl -X GET http://127.0.0.1:5050/api/v1/auth/me \
  -H "Authorization: Bearer <token>"
```

**Promote if needed:**
```bash
curl -X PATCH http://127.0.0.1:5050/api/v1/admin/users/<user_id>/tier \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"profile_tier":"developer"}'
```

### Admin Can't Change Own Tier

**Expected behavior:** Admins cannot modify their own tier (security feature)

**Solution:** Ask another admin to change your tier

### Migration Failed

**Check database:**
```bash
sqlite3 tda_auth.db "PRAGMA table_info(users);" | grep profile_tier
```

**Re-run migration:**
```bash
python3 add_profile_tier_column.py
```

---

## Summary

The 3-tier profile system provides:

✅ **Hierarchical permissions** - Higher tiers inherit lower tier access  
✅ **Secure by default** - New users start as 'user' tier  
✅ **Admin-controlled promotion** - Only admins can change tiers  
✅ **Self-protection** - Admins cannot demote themselves  
✅ **Backward compatible** - `is_admin` field still works  
✅ **Audit logging** - All tier changes tracked  
✅ **Flexible configuration** - Tier-aware feature flags  

The system is production-ready and can be extended with additional tiers or permissions as needed.
