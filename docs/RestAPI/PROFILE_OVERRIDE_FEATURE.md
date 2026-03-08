# Profile Override Feature for REST API

## Overview

The REST API now supports optional **profile overrides** for individual queries. This allows you to:

- Execute queries with different profiles from the same session
- Have each query display with its own profile badge in the UI
- Maintain full visibility into which profile was used for each query

## Usage

### 1. Basic Query (Uses Default Profile)

```bash
curl -X POST http://localhost:5050/api/v1/sessions/{session_id}/query \
  -H "Authorization: Bearer {jwt_token}" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the system version?"}'
```

**Result:**
- Query executes with the user's default profile
- Message displays with default profile badge (e.g., `@GOGET`)

### 2. Query with Profile Override

```bash
curl -X POST http://localhost:5050/api/v1/sessions/{session_id}/query \
  -H "Authorization: Bearer {jwt_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Tell me about the current date",
    "profile_id": "profile-1764006444002-z0hdduce9"
  }'
```

**Result:**
- Query executes with the specified profile
- Message displays with the override profile badge (e.g., `@FRGOT`)
- Session shows both profiles in `profile_tags_used`

## How It Works

### Backend Flow

1. **REST Request** → Include optional `profile_id` in request body
2. **REST Endpoint** → Extracts `profile_id` (or uses default)
3. **Execution Service** → Receives `profile_override_id` parameter
4. **Profile Context** → Switches to the requested profile
5. **Message Storage** → Stores the profile tag with the user message
6. **Session History** → Each message remembers which profile executed it

### Frontend Display

When loading a session:
1. UI reads `profile_tag` from each message
2. For user messages with a profile_tag, renders a profile badge
3. Badge shows profile name and color (from profile configuration)
4. Different messages can show different profile badges

## Getting Available Profiles

To see available profiles and get their IDs:

```bash
curl -X GET http://localhost:5050/api/v1/profiles \
  -H "Authorization: Bearer {jwt_token}"
```

Response:
```json
{
  "profiles": [
    {
      "id": "profile-1763993711628-vvbh23q09",
      "tag": "GOGET",
      "name": "Google - Reduced Stack",
      "color": "#4285f4",
      ...
    },
    {
      "id": "profile-1764006444002-z0hdduce9",
      "tag": "FRGOT",
      "name": "Friendly AI - Reduced Stack",
      "color": "#ff6b6b",
      ...
    }
  ],
  "default_profile_id": "profile-1763993711628-vvbh23q09"
}
```

## Examples

### Python

```python
import requests
import json

BASE_URL = "http://localhost:5050"
API_BASE = f"{BASE_URL}/api/v1"

# Login
login_response = requests.post(
    f"{BASE_URL}/api/v1/auth/login",
    json={"username": "admin", "password": "admin"}
)
jwt_token = login_response.json()['token']

# Get profiles
profiles_response = requests.get(
    f"{API_BASE}/profiles",
    headers={"Authorization": f"Bearer {jwt_token}"}
)
profiles = profiles_response.json()['profiles']
override_profile_id = profiles[1]['id']  # Use second profile

# Create session
session_response = requests.post(
    f"{API_BASE}/sessions",
    headers={"Authorization": f"Bearer {jwt_token}"}
)
session_id = session_response.json()['session_id']

# Query with default profile
query1 = requests.post(
    f"{API_BASE}/sessions/{session_id}/query",
    headers={"Authorization": f"Bearer {jwt_token}"},
    json={"prompt": "What is the system version?"}
)

# Query with profile override
query2 = requests.post(
    f"{API_BASE}/sessions/{session_id}/query",
    headers={"Authorization": f"Bearer {jwt_token}"},
    json={
        "prompt": "Tell me about the current date",
        "profile_id": override_profile_id
    }
)
```

### Node.js/JavaScript

```javascript
const baseUrl = 'http://localhost:5050';
const apiBase = `${baseUrl}/api/v1`;

// Login
const loginRes = await fetch(`${baseUrl}/api/v1/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password: 'admin' })
});
const { token } = await loginRes.json();

// Get profiles
const profilesRes = await fetch(`${apiBase}/profiles`, {
  headers: { 'Authorization': `Bearer ${token}` }
});
const { profiles } = await profilesRes.json();

// Create session
const sessionRes = await fetch(`${apiBase}/sessions`, {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}` }
});
const { session_id } = await sessionRes.json();

// Query with profile override
const queryRes = await fetch(`${apiBase}/sessions/${session_id}/query`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    prompt: 'Tell me about the current date',
    profile_id: profiles[1].id  // Override with second profile
  })
});
const { task_id } = await queryRes.json();
```

## UI Display

When viewing a session with multiple profiles:

```
┌─────────────────────────────────────────────────────────┐
│ User (12:34 PM)                                         │
│ @GOGET (default)                                        │
│                                                         │
│ What is the system version?                             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Assistant                                               │
│                                                         │
│ The system version is 20.00.22.31.                      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ User (12:35 PM)                                         │
│ @FRGOT (overridden)                                     │
│                                                         │
│ Tell me about the current date                          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Assistant                                               │
│                                                         │
│ The current date is 2025-11-26.                         │
└─────────────────────────────────────────────────────────┘
```

Each profile badge shows:
- **Tag** (e.g., `@GOGET`, `@FRGOT`)
- **Color** from the profile's branding
- **Tooltip** on hover showing full profile name

## Error Handling

If you specify an invalid `profile_id`:

```bash
curl -X POST http://localhost:5050/api/v1/sessions/{session_id}/query \
  -H "Authorization: Bearer {jwt_token}" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test", "profile_id": "invalid-id"}'
```

**Response:** The system will still process the query, but will log a warning and fall back to using the active context.

## Session Details

You can check which profiles were used in a session:

```bash
curl -X GET http://localhost:5050/api/v1/sessions/{session_id}/details \
  -H "Authorization: Bearer {jwt_token}"
```

Response includes:
```json
{
  "session_id": "87ebb982-5e22-4307-b7a2-fb079ee27fa0",
  "profile_id": "profile-1763993711628-vvbh23q09",
  "profile_tags_used": ["GOGET", "FRGOT"],
  "models_used": [
    "Google/gemini-2.5-flash",
    "Friendli/meta-llama/Llama-3.3-70B-Instruct"
  ],
  ...
}
```

## Implementation Details

### Files Modified

- `src/trusted_data_agent/api/rest_routes.py`
  - POST `/v1/sessions/{id}/query` endpoint
  - Accepts optional `profile_id` in request body
  - Passes `profile_override_id` to execution service
  - Stores `profile_id_override` in task state

- `src/trusted_data_agent/agent/execution_service.py`
  - Receives `profile_override_id` parameter
  - Resolves profile tag from profile ID
  - Passes profile tag to `add_message_to_histories()`

- `src/trusted_data_agent/core/session_manager.py`
  - `add_message_to_histories()` already supported `profile_tag`
  - Messages now store profile information

- `static/js/handlers/sessionManagement.js`
  - Reads `profile_tag` from loaded messages
  - Passes it to UI.addMessage()

- `static/js/ui.js`
  - `addMessage()` creates profile badges for messages with `profile_tag`
  - Applies profile-specific styling (color, branding)

### Message Structure

```json
{
  "role": "user",
  "content": "What is the system version?",
  "profile_tag": "GOGET",
  "source": "rest",
  "turn_number": 1,
  "isValid": true
}
```

## Testing

Run the provided test scripts to verify the feature:

```bash
# Test basic profile override functionality
python test/test_profile_override.py

# Test per-message profile tracking
python test/test_profile_override_per_message.py

# Verify profile tags are stored correctly
python test/verify_profile_tags.py
```

## Notes

- Profile overrides are **per-query**, not per-session
- Sessions maintain their primary profile for branding purposes
- Each message independently records which profile executed it
- The UI displays the correct profile badge for each message
- Profile colors and styling come from profile configuration

