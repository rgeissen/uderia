# Consumption Profiles Implementation

## Overview

The consumption profiles feature allows administrators to manage user quotas and rate limits through reusable profile templates. Users can be assigned to profiles that define their monthly token limits and rate limiting parameters.

## Rate Limiting & Consumption Profile Precedence

**Important:** Rate limiting must be **enabled** for consumption profiles to be enforced. As of the latest update, rate limiting is **enabled by default** to ensure consumption profiles work correctly.

### Precedence Hierarchy (for authenticated users):

1. **Global Override Mode** (Emergency) - When enabled, forces global limits on ALL users, ignoring consumption profiles
2. **Consumption Profiles** (Default) - Per-user profiles take precedence when assigned
3. **Global Settings Fallback** - Applied when user has no consumption profile assigned
4. **Hardcoded Defaults** - Last resort if database unavailable

### Key Settings in Application Configuration:

- **Enable Rate Limiting** - Master switch; must be ON for profiles to work (enabled by default)
- **Global Override Mode** - Emergency toggle to override all profiles with global limits (disabled by default)
- **Per-User Limits** - Fallback values when user has no profile
- **Per-IP Limits** - Always enforced for anonymous/unauthenticated traffic (not affected by profiles)

## Configuration

You can configure rate limiting and consumption profiles in `tda_config.json`:

```json
{
  "rate_limit_enabled": "on",
  "default_consumption_profile": "Unlimited"
}
```

**Configuration Parameters:**

### `rate_limit_enabled`
Controls whether rate limiting is enabled system-wide.

**Supported Values:**
- `"on"` / `"true"` / `"1"` / `"yes"` - Enable rate limiting and consumption profile enforcement **[Default]**
- `"off"` / `"false"` / `"0"` / `"no"` - Disable rate limiting (not recommended for production)

**Important:** Must be enabled for consumption profiles to work.

### `default_consumption_profile`
Determines which profile is assigned to new users.

**Supported Values:**
- `"Free"` - Basic limits (50 prompts/hour, 100K input tokens/month)
- `"Pro"` - Professional limits (200 prompts/hour, 500K input tokens/month)
- `"Enterprise"` - High limits (500 prompts/hour, 2M input tokens/month)
- `"Unlimited"` - No token limits (1000 prompts/hour, unlimited tokens) **[Default]**

This setting determines which profile is marked as `is_default=True` during migration and will be automatically assigned to new users.

## Implementation Status

✅ **Completed Components:**

1. **Database Models** (`src/trusted_data_agent/auth/models.py`)
   - `ConsumptionProfile` - Profile definitions
   - `UserTokenUsage` - Monthly token consumption tracking
   - `User.consumption_profile_id` - Profile assignment

2. **Token Quota Management** (`src/trusted_data_agent/auth/token_quota.py`)
   - `get_user_consumption_profile()` - Fetch user's profile
   - `check_token_quota()` - Validate token usage against limits
   - `record_token_usage()` - Track token consumption
   - `get_user_quota_status()` - Get comprehensive quota status

3. **Rate Limiter Integration** (`src/trusted_data_agent/auth/rate_limiter.py`)
   - Updated `check_user_prompt_quota()` to use profile limits
   - Updated `check_user_config_quota()` to use profile limits
   - Falls back to system defaults if no profile assigned

4. **Admin API Endpoints** (`src/trusted_data_agent/api/auth_routes.py`)
   - `GET /api/v1/auth/admin/consumption-profiles` - List all profiles
   - `POST /api/v1/auth/admin/consumption-profiles` - Create profile
   - `PUT /api/v1/auth/admin/consumption-profiles/<id>` - Update profile
   - `DELETE /api/v1/auth/admin/consumption-profiles/<id>` - Delete profile
   - `PUT /api/v1/auth/admin/users/<id>/consumption-profile` - Assign profile to user
   - `GET /api/v1/auth/user/quota-status` - Get current user's quota status

5. **Database Migration** (`maintenance/migrate_consumption_profiles.py`)
   - Creates all necessary tables
   - Adds column to users table
   - Creates 4 default profiles (Free, Pro, Enterprise, Unlimited)

## Database Schema

### consumption_profiles
```sql
CREATE TABLE consumption_profiles (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    prompts_per_hour INTEGER NOT NULL DEFAULT 100,
    prompts_per_day INTEGER NOT NULL DEFAULT 1000,
    config_changes_per_hour INTEGER NOT NULL DEFAULT 10,
    input_tokens_per_month INTEGER,  -- NULL = unlimited
    output_tokens_per_month INTEGER,  -- NULL = unlimited
    is_default BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### user_token_usage
```sql
CREATE TABLE user_token_usage (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    period VARCHAR(7) NOT NULL,  -- YYYY-MM format
    input_tokens_used INTEGER DEFAULT 0,
    output_tokens_used INTEGER DEFAULT 0,
    total_tokens_used INTEGER DEFAULT 0,
    first_usage_at TIMESTAMP,
    last_usage_at TIMESTAMP,
    UNIQUE(user_id, period)
);
```

### users (modified)
```sql
ALTER TABLE users ADD COLUMN consumption_profile_id INTEGER;
```

## Default Profiles

### 1. Free (Default)
- Prompts: 50/hour, 500/day
- Config changes: 5/hour
- Input tokens: 100K/month
- Output tokens: 50K/month

### 2. Pro
- Prompts: 200/hour, 2000/day
- Config changes: 20/hour
- Input tokens: 500K/month
- Output tokens: 250K/month

### 3. Enterprise
- Prompts: 500/hour, 5000/day
- Config changes: 50/hour
- Input tokens: 2M/month
- Output tokens: 1M/month

### 4. Unlimited
- Prompts: 1000/hour, 10000/day
- Config changes: 100/hour
- Input tokens: Unlimited
- Output tokens: Unlimited

## Installation Steps

### 1. Run Database Migration

```bash
cd /Users/livin2rave/my_private_code/uderia
python maintenance/migrate_consumption_profiles.py
```

This will:
- Create new tables
- Add column to users table
- Create 4 default profiles (Free, Pro, Enterprise, Unlimited)
- Set up all indexes

### 2. Assign Unlimited to Existing Users

**Important:** To avoid disrupting existing users, assign them the Unlimited profile:

```bash
python maintenance/assign_unlimited_profiles.py
```

This will:
- Assign Unlimited profile to all existing users
- Set Unlimited as the default for new users
- Display summary of profile assignments

This ensures existing users continue to have unrestricted access while you set up the UI and gradually assign specific profiles.

### 3. Restart Application

The application needs to be restarted to load the new models and endpoints.

### 4. Verify Installation

```bash
# Test that default profiles exist
sqlite3 tda_auth.db "SELECT * FROM consumption_profiles;"

# Check users table has new column
sqlite3 tda_auth.db "PRAGMA table_info(users);"

# Verify users have Unlimited profile assigned
sqlite3 tda_auth.db "SELECT username, consumption_profile_id FROM users;"
```

## UI Implementation (Next Steps)

### Admin Panel UI (Remaining)

Create new section in Admin Panel for Consumption Profiles:

**Profile Management:**
- List all profiles in a table
- Create/Edit/Delete profile forms
- Set profile as default
- Enable/disable profiles

**User Management:**
- Add "Consumption Profile" column to user list
- Add dropdown to assign profile to users
- Bulk assign profiles

**Code Location:** `templates/index.html` (Admin Panel section)
**JavaScript:** `static/js/adminManager.js`

### User Dashboard (Remaining)

Add quota usage display for users:

**Quota Widget:**
- Show current period (e.g., "December 2025")
- Display input/output token usage with progress bars
- Show remaining tokens
- Display rate limits
- Add visual warnings when approaching limits (e.g., >80%)

**Code Location:** `templates/index.html` (User dashboard)
**API Endpoint:** `GET /api/v1/auth/user/quota-status` (already implemented)

## Token Tracking Integration

To actually enforce and track token usage, you need to integrate the quota checker into your prompt execution flow:

### In Prompt Execution (`src/trusted_data_agent/api/rest_routes.py` or similar):

```python
from trusted_data_agent.auth.token_quota import check_token_quota, record_token_usage

# Before executing prompt
async def execute_prompt(user_id, prompt):
    # 1. Estimate token usage (or check after)
    estimated_input = len(prompt) // 4  # Rough estimate
    estimated_output = 500  # Estimate or use from profile
    
    # 2. Check quota
    allowed, error_msg, quota_info = check_token_quota(
        user_id,
        input_tokens=estimated_input,
        output_tokens=estimated_output
    )
    
    if not allowed:
        return {"error": error_msg, "quota_info": quota_info}, 429
    
    # 3. Execute prompt...
    result = await llm.execute(prompt)
    
    # 4. Record actual usage
    record_token_usage(
        user_id,
        input_tokens=result['usage']['input_tokens'],
        output_tokens=result['usage']['output_tokens']
    )
    
    return result
```

## API Examples

### Get All Profiles (Admin)
```bash
curl -H "Authorization: Bearer <admin_token>" \
  http://localhost:5000/api/v1/auth/admin/consumption-profiles
```

### Create Profile (Admin)
```bash
curl -X POST -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Starter",
    "description": "Starter tier",
    "prompts_per_hour": 30,
    "prompts_per_day": 300,
    "config_changes_per_hour": 3,
    "input_tokens_per_month": 50000,
    "output_tokens_per_month": 25000,
    "is_default": false
  }' \
  http://localhost:5000/api/v1/auth/admin/consumption-profiles
```

### Assign Profile to User (Admin)
```bash
curl -X PUT -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"profile_id": 2}' \
  http://localhost:5000/api/v1/auth/admin/users/<user_id>/consumption-profile
```

### Get My Quota Status (User)
```bash
curl -H "Authorization: Bearer <user_token>" \
  http://localhost:5000/api/v1/auth/user/quota-status
```

Response:
```json
{
  "status": "success",
  "quota": {
    "has_quota": true,
    "period": "2025-12",
    "profile_name": "Pro",
    "profile_id": 2,
    "input_tokens": {
      "limit": 500000,
      "used": 45230,
      "remaining": 454770,
      "percentage_used": 9.0
    },
    "output_tokens": {
      "limit": 250000,
      "used": 23150,
      "remaining": 226850,
      "percentage_used": 9.3
    },
    "rate_limits": {
      "prompts_per_hour": 200,
      "prompts_per_day": 2000,
      "config_changes_per_hour": 20
    }
  }
}
```

## Testing

### Test Profile Creation
```python
# In Python/IPython
from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import ConsumptionProfile

with get_db_session() as session:
    profiles = session.query(ConsumptionProfile).all()
    for p in profiles:
        print(f"{p.id}: {p.name} - {p.input_tokens_per_month}/{p.output_tokens_per_month}")
```

### Test Token Tracking
```python
from trusted_data_agent.auth.token_quota import (
    check_token_quota,
    record_token_usage,
    get_user_quota_status
)

user_id = "your-user-id"

# Record some usage
record_token_usage(user_id, input_tokens=1000, output_tokens=500)

# Check quota
allowed, msg, info = check_token_quota(user_id, input_tokens=5000, output_tokens=2500)
print(f"Allowed: {allowed}, Message: {msg}")

# Get status
status = get_user_quota_status(user_id)
print(status)
```

## Benefits

1. **Flexible Quota Management**: Create profiles for different user tiers
2. **Token Limit Enforcement**: Prevent runaway costs with monthly token limits
3. **Rate Limit Customization**: Different rate limits per profile
4. **Easy User Assignment**: Admins can quickly change user tiers
5. **Usage Tracking**: Monthly tracking with automatic reset
6. **Backward Compatible**: Users without profiles fall back to system defaults

## Next Steps for Complete Implementation

1. **Run Migration**: Execute `migrate_consumption_profiles.py`
2. **Build Admin UI**: Add profile management interface in Admin Panel
3. **Build User Dashboard**: Add quota usage widget for users
4. **Integrate Token Tracking**: Add `check_token_quota()` and `record_token_usage()` calls to prompt execution flow
5. **Test**: Verify profile assignment and quota enforcement
6. **Document**: Add user-facing documentation about tiers

## Files Created/Modified

### New Files:
- `src/trusted_data_agent/auth/token_quota.py` - Token quota management
- `maintenance/migrate_consumption_profiles.py` - Database migration

### Modified Files:
- `src/trusted_data_agent/auth/models.py` - Added models and relationships
- `src/trusted_data_agent/auth/rate_limiter.py` - Profile-aware rate limiting
- `src/trusted_data_agent/api/auth_routes.py` - Admin and user API endpoints

## Support

For questions or issues with consumption profiles:
1. Check logs in `logs/` directory
2. Verify database schema with `sqlite3 tda_auth.db`
3. Test API endpoints with curl
4. Review audit logs for profile assignment changes
