# JWT vs Access Token: Complete Comparison

This document provides a detailed comparison of the two authentication methods for session creation in the Uderia Platform REST API.

## Side-by-Side Comparison

| Aspect | JWT Token | Access Token |
|--------|-----------|--------------|
| **Format** | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` | `tda_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| **Lifetime** | 24 hours (configurable via env) | 30/90/180/365 days or never expires |
| **Best For** | Web UI, interactive sessions | API automation, CI/CD, scripts |
| **Created By** | `POST /auth/login` with credentials | `POST /api/v1/auth/tokens` with JWT |
| **Automatic Expiration** | Yes (24 hours) | Optional (configurable) |
| **Manual Revocation** | Via token blacklist (if enabled) | Yes, individual token revocation |
| **Storage** | Client-side (localStorage) | Secure database (SHA256 hash) |
| **Retrieval** | Can be obtained anytime by logging in | Shown only once at creation |
| **Visibility** | Can see in browser console | Cannot be retrieved after creation |
| **Refresh** | Auto-managed by client | Manual management needed |
| **Security** | Stateless, no server storage | Hashed, tracked in database |
| **Use Case** | Interactive users | Unattended processes |
| **Multiple Tokens** | One per session | Many per user (one per app/env) |
| **Environment Variable** | `TDA_JWT_SECRET_KEY` | N/A (stored in DB) |
| **API Calls Limit** | None | Trackable via audit logs |

## Detailed Flow Comparison

### JWT Token Flow

```
┌─────────────────────────────────────────┐
│ 1. USER PROVIDES CREDENTIALS            │
│    username: "john_doe"                 │
│    password: "SecurePass123!"           │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 2. POST /auth/login                     │
│    System validates credentials         │
│    - Checks if user exists              │
│    - Compares bcrypt hash               │
│    - Checks account lockout             │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 3. GENERATE JWT TOKEN                   │
│    Payload = {                          │
│      user_id: "uuid",                   │
│      username: "john_doe",              │
│      exp: now + 24 hours,               │
│      iat: now,                          │
│      jti: random_id                     │
│    }                                    │
│    Token = HS256(payload, secret_key)   │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 4. STORE IN BROWSER                     │
│    localStorage.setItem('tda_auth_token',│
│      'eyJhbGc...')                      │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 5. USE FOR API CALLS                    │
│    curl -H "Authorization: Bearer $JWT" │
│         http://localhost:5050/api/v1/   │
│         sessions                        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 6. AUTOMATIC EXPIRATION                 │
│    24 hours later:                      │
│    Token is no longer valid             │
│    User must login again                │
└─────────────────────────────────────────┘
```

### Access Token Flow

```
┌─────────────────────────────────────────┐
│ 1. USER PROVIDES CREDENTIALS            │
│    (same as JWT flow)                   │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 2. POST /auth/login (get JWT)           │
│    (same as JWT flow)                   │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 3. POST /api/v1/auth/tokens             │
│    Request body = {                     │
│      name: "Production Server",         │
│      expires_in_days: 90                │
│    }                                    │
│    Header = Authorization: Bearer $JWT  │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 4. GENERATE ACCESS TOKEN                │
│    token = "tda_" + random_32_chars     │
│    token_hash = SHA256(token)           │
│    expiry = now + 90 days               │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 5. STORE IN DATABASE                    │
│    INSERT INTO access_tokens            │
│    (user_id, token_hash, expiry, ...)   │
│                                         │
│    ⚠️  Full token shown only ONCE       │
│    Cannot be retrieved later!           │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 6. USE FOR API CALLS                    │
│    curl -H "Authorization: Bearer $TOK" │
│         http://localhost:5050/api/v1/   │
│         sessions                        │
│                                         │
│    On each API call:                    │
│    - Extract token                      │
│    - Hash it (SHA256)                   │
│    - Query database for hash            │
│    - Check if revoked                   │
│    - Check if expired                   │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ 7. MANUAL REVOCATION (optional)         │
│    DELETE /api/v1/auth/tokens/{token_id}│
│    or wait for expiration (90 days)     │
└─────────────────────────────────────────┘
```

## When to Use Which

### Use JWT Token When:

✅ Interactive web application
```python
# User logs in via web UI
async def login_handler():
    jwt_token = await get_jwt_from_login()  # 24-hour token
    return json_response(token=jwt_token)
```

✅ Short-lived API client
```bash
# Run one-off query from shell
JWT=$(login)
curl -H "Authorization: Bearer $JWT" /api/v1/sessions
# JWT expires, user logs in again
```

✅ Browser-based testing
```javascript
// Testing API from browser console
const jwt = localStorage.getItem('tda_auth_token');
fetch('/api/v1/sessions', {
    headers: { 'Authorization': `Bearer ${jwt}` }
});
```

### Use Access Token When:

✅ Scheduled automation/cron job
```bash
# Script runs every hour, access token lasts 90 days
TOKEN="tda_xxxxxxxx" # Saved in secure location
curl -H "Authorization: Bearer $TOKEN" /api/v1/sessions
```

✅ CI/CD pipeline
```yaml
# GitHub Actions / GitLab CI
- name: Run TDA Query
  env:
    TDA_ACCESS_TOKEN: ${{ secrets.TDA_ACCESS_TOKEN }}
  run: |
    curl -H "Authorization: Bearer $TDA_ACCESS_TOKEN" \
         http://tda-server:5050/api/v1/sessions
```

✅ Microservice integration
```python
# Service A needs to call TDA Service B
class TDAClient:
    def __init__(self):
        self.token = os.getenv('TDA_ACCESS_TOKEN')  # 90-day token
    
    def create_session(self):
        return self.api_request(
            'POST', '/api/v1/sessions',
            headers={'Authorization': f'Bearer {self.token}'}
        )
```

✅ Multiple applications/environments
```bash
# Keep separate tokens for each environment
export TDA_DEV_TOKEN="tda_dev_xxxxx"
export TDA_PROD_TOKEN="tda_prod_xxxxx"
export TDA_TEST_TOKEN="tda_test_xxxxx"

# Each can be revoked independently
```

## Security Considerations

### JWT Token Security

**Strengths:**
- Stateless (server doesn't store tokens)
- Short expiration (24 hours by default)
- Cannot be retrieved after expiration
- Suitable for web browsers

**Risks:**
- If stolen, valid for 24 hours
- Stored in localStorage (vulnerable to XSS)
- Manual revocation difficult (requires blacklist)

**Mitigation:**
- Use HTTPS only
- Set short expiration (24 hours)
- Implement token rotation
- Monitor for suspicious activity

### Access Token Security

**Strengths:**
- Long-lived but explicitly configured
- Hashed storage in database
- Can be individually revoked
- Trackable in audit logs
- Suitable for APIs and automation

**Risks:**
- If stolen, valid until expiration
- Must be stored securely
- Longer lifetime means higher risk window

**Mitigation:**
- Store in secure vaults (not in code)
- Rotate regularly (create new, revoke old)
- Use environment variables or secrets manager
- Monitor usage via audit logs
- Set appropriate expiration (90 days recommended)

## Implementation Examples

### Python: Session Creation with JWT

```python
import requests
from datetime import datetime

BASE_URL = "http://localhost:5050"

# 1. Login
response = requests.post(
    f"{BASE_URL}/auth/login",
    json={"username": "user", "password": "pass"}
)
jwt_token = response.json()['token']

# 2. Use JWT for session creation
response = requests.post(
    f"{BASE_URL}/api/v1/sessions",
    headers={"Authorization": f"Bearer {jwt_token}"}
)
session_id = response.json()['session_id']
print(f"Created session: {session_id} (valid for 24 hours)")
```

### Python: Session Creation with Access Token

```python
import requests
import os

BASE_URL = "http://localhost:5050"

# 1. Login (one-time, to create access token)
response = requests.post(
    f"{BASE_URL}/auth/login",
    json={"username": "user", "password": "pass"}
)
jwt_token = response.json()['token']

# 2. Create long-lived access token
response = requests.post(
    f"{BASE_URL}/api/v1/auth/tokens",
    headers={"Authorization": f"Bearer {jwt_token}"},
    json={"name": "my_app", "expires_in_days": 90}
)
access_token = response.json()['token']
print(f"Access token (save securely!): {access_token}")

# Store securely (environment variable, vault, etc.)
os.environ['TDA_ACCESS_TOKEN'] = access_token

# 3. Use access token for subsequent calls (next 90 days)
response = requests.post(
    f"{BASE_URL}/api/v1/sessions",
    headers={"Authorization": f"Bearer {access_token}"}
)
session_id = response.json()['session_id']
print(f"Created session: {session_id} (using 90-day token)")
```

### Bash: Session Creation with JWT

```bash
#!/bin/bash

BASE_URL="http://localhost:5050"

# 1. Login
JWT=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"user","password":"pass"}' | jq -r '.token')

# 2. Create session
SESSION=$(curl -s -X POST "$BASE_URL/api/v1/sessions" \
  -H "Authorization: Bearer $JWT")

echo "Session ID: $(echo $SESSION | jq -r '.session_id')"
```

### Bash: Session Creation with Access Token

```bash
#!/bin/bash

BASE_URL="http://localhost:5050"

# 1. Login (one-time)
JWT=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"user","password":"pass"}' | jq -r '.token')

# 2. Create access token
TOKEN=$(curl -s -X POST "$BASE_URL/api/v1/auth/tokens" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"my_app","expires_in_days":90}' | jq -r '.token')

echo "Access token (save securely): $TOKEN"

# 3. Use access token for session
SESSION=$(curl -s -X POST "$BASE_URL/api/v1/sessions" \
  -H "Authorization: Bearer $TOKEN")

echo "Session ID: $(echo $SESSION | jq -r '.session_id')"
```

## Testing

Run the provided test scripts to see both approaches in action:

```bash
# Python test (recommended)
python test/test_session_creation_methods.py

# Bash test
bash test/test_session_creation_methods.sh
```

These tests will:
1. Prompt for credentials
2. Demonstrate JWT token flow
3. Create a session with JWT
4. Demonstrate access token flow
5. Create a session with access token
6. Submit queries with both tokens
7. Show task status checking

## FAQs

**Q: Can I use both JWT and access tokens simultaneously?**
A: Yes! They serve different purposes and can coexist. Use JWT for web UI, access tokens for API automation.

**Q: How do I save an access token?**
A: Save it securely in:
- Environment variable: `export TDA_ACCESS_TOKEN="tda_xxx"`
- Password manager
- Secure vault (HashiCorp Vault, AWS Secrets Manager, etc.)
- Config file (with restricted permissions: `chmod 600`)

**Q: What happens if I lose my access token?**
A: Create a new one. The old one will remain valid until its expiration date.

**Q: Can I revoke a JWT token?**
A: The system tracks JWT tokens and can revoke them via a blacklist. They automatically expire after 24 hours anyway.

**Q: How do I revoke an access token?**
A: `DELETE /api/v1/auth/tokens/{token_id}`

**Q: Which is more secure?**
A: Both are secure when used properly. JWT is better for short interactions, access tokens are better for long-lived automation because they can be revoked anytime.

## References

- [REST API Documentation](../docs/RestAPI/restAPI.md)
- [Authentication Guide](../docs/RestAPI/restAPI.md#2-authentication)
- [Session Management](../docs/RestAPI/restAPI.md#34-session-management)
- [Test Scripts](./TEST_SESSION_CREATION_README.md)
