# Session Creation Test - Both Authentication Methods

This directory contains test scripts to demonstrate and verify session creation using both authentication approaches supported by the Uderia Platform REST API.

## ⚠️ Prerequisites: Profile Configuration

**Important:** Before running these tests, you must have a configured **default profile** consisting of:
- An **LLM Provider** (e.g., Google, OpenAI, AWS Bedrock)
- An **MCP Server** (for data access)

### Quick Setup

1. **Open the web UI** at http://localhost:5050
2. **Click Configuration** panel (bottom left)
3. **Add LLM Provider** (if not already added)
4. **Add MCP Server** (if not already added)
5. **Create a Profile** combining LLM + MCP Server
6. **Set as Default** (click the star icon or "Set as Default" button)

If you already have LLM and MCP configured, the test scripts will automatically create and set a default profile for you.

## Quick Start

### Python Test (Recommended)

```bash
python test/test_session_creation_methods.py
```

**Features:**
- Interactive prompts for credentials
- Automatic profile setup (if components exist)
- Colored output for easy reading
- Comprehensive error handling
- Tests both authentication methods
- Demonstrates query submission and task status checking

### Bash Test

```bash
bash test/test_session_creation_methods.sh
```

**Features:**
- Uses `curl` and `jq`
- Same test flow as Python version
- Profile validation before session creation
- Good for shell scripting integration
- Can be embedded in automation workflows

## What Gets Tested

### 1. JWT Token Approach
- Login with username/password
- Receive 24-hour JWT token
- **Verify default profile is configured** ✨ NEW
- Create session using JWT
- Submit query to session
- Check task status

**Typical Use:** Web UI sessions, interactive applications

### 2. Access Token Approach
- Login with credentials (temporary JWT)
- Create long-lived access token (90 days default)
- **Verify default profile is configured** ✨ NEW
- Create session using access token
- Submit query to session
- Check task status

**Typical Use:** API automation, CI/CD pipelines, unattended scripts

## Prerequisites

### For Python Test
```bash
# Standard library only, no additional packages needed
python3 test/test_session_creation_methods.py
```

### For Bash Test
```bash
# Install curl and jq
brew install curl jq        # macOS
sudo apt-get install curl jq  # Ubuntu/Debian

# Then run
bash test/test_session_creation_methods.sh
```

### For Both Tests
- Server running: `python -m trusted_data_agent.main`
- Server accessible at: `http://localhost:5050`
- Valid user credentials
- **User must have a configured default profile (LLM + MCP Server combination)** ⚠️

## Environment Variables

### Customize Server URL
```bash
# Python
export TDA_SERVER=http://localhost:5050
python test/test_session_creation_methods.py

# Bash
export BASE_URL=http://localhost:5050
bash test/test_session_creation_methods.sh
```

## Test Output Example

### JWT Token Approach
```
>>> METHOD 1: JWT Token (Short-lived, 24 hours)

[Step 1] Login to get JWT token
ℹ POST /auth/login
✓ Login successful
  Token (first 50 chars): eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2...
  User: api_user
  User ID: 550e8400-e29b-41d4-a716-446655440000

[Step 2] Check for default profile
ℹ GET /api/v1/profiles
✓ Default profile is configured

[Step 3] Create session using JWT token
ℹ POST /api/v1/sessions
✓ Session created successfully
  Session ID: a1b2c3d4-e5f6-7890-1234-567890abcdef

[Step 4] Submit test query to session
ℹ POST /api/v1/sessions/a1b2c3d4.../query
✓ Query submitted successfully
  Task ID: task-9876-5432-1098-7654

[Step 5] Check task status
ℹ GET /api/v1/tasks/task-9876-5432-1098-7654
✓ Task status retrieved
  Status: processing
```

### Access Token Approach
```
>>> METHOD 2: Access Token (Long-lived, configurable)

[Step 1] Login to get JWT token (temporary)
ℹ POST /auth/login
✓ Login successful (got temporary JWT)
  Token (first 50 chars): eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2...

[Step 2] Create long-lived access token using JWT
ℹ POST /api/v1/auth/tokens
✓ Access token created successfully
  Token: tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
  Token ID: abc123-def456-ghi789
  Expires at: 2026-02-26T10:00:00Z
  ⚠️  SAVE THIS TOKEN! It cannot be retrieved later!

[Step 3] Check for default profile
ℹ GET /api/v1/profiles
✓ Default profile is configured

[Step 4] Create session using access token
ℹ POST /api/v1/sessions
✓ Session created successfully
  Session ID: b2c3d4e5-f6f7-8901-2345-678901bcdef0
```

## Key Findings from Testing

✅ **Both methods work identically for session creation**
- Same endpoints used
- Same response format
- Same user-scoping behavior

✅ **Both support full API workflow**
- Create sessions
- Submit queries
- Check task status
- Cancel tasks

✅ **Differences are in token lifecycle**
- JWT: Short-lived (24 hours), auto-expires
- Access Token: Long-lived (configurable), manual management

## Troubleshooting

### "No default profile found"
- **Cause:** User doesn't have a profile configured
- **Solution:** 
  1. Open web UI at http://localhost:5050
  2. Go to Configuration panel
  3. Add LLM Provider (if needed)
  4. Add MCP Server (if needed)
  5. Create a profile combining them
  6. Mark as default (click star icon)

### "Profile is incomplete"
- **Cause:** Profile exists but missing LLM or MCP Server
- **Solution:**
  1. Open web UI at http://localhost:5050
  2. Edit the profile in Configuration panel
  3. Add missing LLM Provider or MCP Server
  4. Save the profile

### "Login failed: 401"
- Check username and password are correct
- User account exists and is not locked

### "Cannot connect to server"
- Ensure server is running: `python -m trusted_data_agent.main`
- Check BASE_URL/TDA_SERVER environment variable

### "jq: command not found" (Bash test)
- Install jq: `brew install jq` (macOS) or `sudo apt-get install jq` (Ubuntu)

### "Session creation failed" (after profile check passes)
- Ensure authentication token is valid
- Check server logs for detailed error message
- Verify profile still has both LLM and MCP configured

### "Query submission failed"
- Ensure session ID is correct
- Verify token hasn't expired
- Check if LLM and MCP are still configured

## What Changed (Profile-Based Model)

The tests now include a **profile validation step** before attempting session creation:

| Step | Before | After |
|------|--------|-------|
| 1 | Login | Login |
| 2 | Create Session | **Check/Setup Profile** ✨ |
| 3 | Submit Query | Create Session |
| 4 | Check Status | Submit Query |
| - | - | Check Status |

This ensures:
- ✅ Clear error messages if profile isn't configured
- ✅ Automatic profile creation (if LLM + MCP exist)
- ✅ Session creation always has required components
- ✅ Tests fail fast with actionable feedback

## Manual Testing

### Using curl directly

**Create session with JWT:**
```bash
# 1. Login
JWT=$(curl -s -X POST http://localhost:5050/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"user","password":"pass"}' | jq -r '.token')

# 2. Create session
curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $JWT"
```

**Create session with Access Token:**
```bash
# 1. Create access token (using JWT from above)
TOKEN=$(curl -s -X POST http://localhost:5050/api/v1/auth/tokens \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"my_token","expires_in_days":90}' | jq -r '.token')

# 2. Create session
curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN"
```

## See Also

- [REST API Documentation](../docs/RestAPI/restAPI.md)
- [Authentication Guide](../docs/RestAPI/restAPI.md#2-authentication)
- [Session Management](../docs/RestAPI/restAPI.md#34-session-management)
- [Query Execution](../docs/RestAPI/restAPI.md#35-query-execution)
